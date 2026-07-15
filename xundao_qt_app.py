#!/usr/bin/env python3
"""PySide6 + QFluentWidgets desktop client for Xundao."""

from __future__ import annotations

import io
import json
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import qrcode
import requests
import websocket
from PIL import Image
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPlainTextEdit, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)
from qframelesswindow import FramelessWindow, TitleBar
from qfluentwidgets import (
    CheckBox, ComboBox, DoubleSpinBox, FluentIcon as FIF, LineEdit, PasswordLineEdit,
    PrimaryPushButton, PushButton, SpinBox, Theme, ToolButton, setTheme,
)

from xundao_game_client import fetch_game_data
from xundao_game_session import (
    ATTRIBUTE_NAMES,
    fetch_role_snapshot,
    run_chop_tasks,
    run_hero_rank_tasks,
    run_invade_tasks,
    run_star_trial_tasks,
    run_wild_boss_tasks,
)
from xundao_role_client import fetch_roles
from xundao_qr_login import (
    BASE_URL, DEFAULT_APP_ID, DEFAULT_ORIGIN, DEFAULT_UA, SERVICE,
    classify, request_json, save_json,
)


APP_TITLE = "寻道大千脚本助手"
POLL_INTERVAL = 2.0


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


CONFIG_PATH = app_dir() / "config.json"
OUTPUT_DIR = app_dir() / "login-output"


def read_config() -> dict[str, str]:
    defaults = {
        "pcToken": "", "ctoken": "bigfish_ctoken_1ab4ieaf3e", "sessionToken": "",
        "selectedServerId": "", "chopCount": "unlimited", "chopInterval": "1.0",
        "equipmentAction": "stop", "keepQuality": "5",
        "keepAttributeType": "0", "keepAttributeValue": "0",
        "autoRankBattle": "false", "autoWildBoss": "false", "wildBossCount": "6",
        "autoInvade": "false", "invadeCount": "5",
        "autoStarTrial": "false", "starTrialCount": "30",
        "autoHeroRank": "false", "heroRankCount": "10",
    }
    if not CONFIG_PATH.exists():
        return defaults
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError("config.json 顶层必须是 JSON 对象")
    return {**defaults, **{key: str(item) for key, item in value.items()}}


def update_config(**values: Any) -> None:
    current = read_config()
    current.update({key: str(value) for key, value in values.items()})
    CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def set_margins(layout: QVBoxLayout | QHBoxLayout | QGridLayout, *values: int) -> None:
    layout.setContentsMargins(*values)


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, object_name: str = "card") -> None:
        super().__init__(parent)
        self.setObjectName(object_name)


class AppTitleBar(TitleBar):
    """Custom draggable title bar with native window behavior."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("appTitleBar")
        self.setFixedHeight(40)
        self.minBtn.setFixedSize(44, 32)
        self.maxBtn.setFixedSize(44, 32)
        self.closeBtn.setFixedSize(44, 32)
        self.minBtn.setToolTip("最小化")
        self.maxBtn.setToolTip("最大化")
        self.closeBtn.setToolTip("关闭")
        brand = QWidget(self)
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(16, 0, 0, 0)
        brand_layout.setSpacing(7)
        mark = QLabel("◆", brand)
        mark.setStyleSheet("color:#28a779;font-size:13px;")
        name = QLabel(APP_TITLE, brand)
        name.setStyleSheet("font-weight:650;font-size:12px;color:#203138;")
        version = QLabel("v1.0.0", brand)
        version.setStyleSheet("color:#8a989d;font-size:11px;")
        brand_layout.addWidget(mark)
        brand_layout.addWidget(name)
        brand_layout.addWidget(version)
        while self.hBoxLayout.count():
            self.hBoxLayout.takeAt(0)
        self.hBoxLayout.addWidget(brand)
        self.hBoxLayout.addStretch(1)
        self.hBoxLayout.addWidget(self.minBtn)
        self.hBoxLayout.addWidget(self.maxBtn)
        self.hBoxLayout.addWidget(self.closeBtn)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.hBoxLayout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    def set_connected(self, connected: bool) -> None:
        if hasattr(self.parent(), "connection_status"):
            self.parent().connection_status.setText("●  已连接游戏" if connected else "●  等待连接")


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("登录设置")
        self.setFixedSize(560, 270)
        current = read_config()
        layout = QVBoxLayout(self)
        set_margins(layout, 28, 24, 28, 24)
        layout.setSpacing(8)
        layout.addWidget(QLabel("x-game-token-pcweb"))
        self.pc_token = PasswordLineEdit(self)
        self.pc_token.setText(current.get("pcToken", ""))
        layout.addWidget(self.pc_token)
        layout.addSpacing(8)
        layout.addWidget(QLabel("ctoken"))
        self.ctoken = LineEdit(self)
        self.ctoken.setText(current.get("ctoken", ""))
        layout.addWidget(self.ctoken)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = PushButton("取消", self)
        save = PrimaryPushButton(FIF.SAVE, "保存", self)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addStretch()
        layout.addLayout(actions)

    def _save(self) -> None:
        if not self.pc_token.text().strip() or not self.ctoken.text().strip():
            QMessageBox.warning(self, "配置不完整", "两个配置值都不能为空。")
            return
        update_config(pcToken=self.pc_token.text().strip(), ctoken=self.ctoken.text().strip())
        self.accept()


class XundaoWindow(FramelessWindow):
    event = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.app_title_bar = AppTitleBar(self)
        self.setTitleBar(self.app_title_bar)
        self.resize(1360, 860)
        self.setMinimumSize(1120, 720)
        self.roles: list[dict[str, Any]] = []
        self.current_role: dict[str, Any] | None = None
        self.login_path: Path | None = None
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.chop_stop_event = threading.Event()
        self.runtime_seconds = 0.0
        self.runtime_started_at: float | None = None
        self.runtime_timer = QTimer(self)
        self.runtime_timer.setInterval(1000)
        self.runtime_timer.timeout.connect(self._update_runtime)
        self.event.connect(self._handle_event)
        self.stack = QStackedWidget(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        window_layout = QVBoxLayout(self)
        window_layout.setContentsMargins(0, 40, 0, 0)
        window_layout.setSpacing(0)
        window_layout.addWidget(self.stack)
        self.login_page = self._build_login_page()
        self.stack.addWidget(self.login_page)
        self._apply_style()
        self.app_title_bar.raise_()
        self.restore_session()

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.app_title_bar.raise_()

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QDialog, #page { background: #f5f7f7; color: #27363b; }
            QLabel { color: #27363b; font-family: "Microsoft YaHei UI"; }
            #appTitleBar { background: #ffffff; border-bottom: 1px solid #e6ebe9; }
            #topBar, #footer, #card { background: #ffffff; border: 1px solid #e6ebe9; border-radius: 6px; }
            #topBar, #footer { border-radius: 0; border-left: 0; border-right: 0; }
            #softCard { background: #fbfdfc; border: 1px solid #dfe7e4; border-radius: 6px; }
            #nav { background: #ffffff; border: 0; border-right: 1px solid #edf1ef; border-radius: 0; }
            #navActive { background: #eef8f4; border: 0; border-left: 2px solid #28a779; }
            #navItem { background: #ffffff; border: 0; }
            #navItem:hover { background: #f5f9f7; }
            #navActive QLabel { color: #259d74; font-weight: 600; }
            #navItem QLabel { color: #8d9a9f; }
            #resourceGreen { background: #e9f7f1; color: #24a474; border-radius: 23px; font-weight: 700; }
            #resourceBlue { background: #edf7fc; color: #3094cf; border-radius: 23px; font-weight: 700; }
            #resourceOrange { background: #fff5e9; color: #e99a32; border-radius: 23px; font-weight: 700; }
            #sectionTitle { font-size: 15px; font-weight: 600; }
            #roleName { font-size: 22px; font-weight: 700; color: #17272c; }
            #muted { color: #859398; }
            #statusGood { color: #25a66f; font-weight: 600; }
            QPlainTextEdit { background: #fbfcfc; border: 1px solid #edf1ef; border-radius: 5px; padding: 10px; }
        """)

    def _build_login_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        set_margins(layout, 40, 28, 40, 32)
        layout.setSpacing(14)
        title = QLabel("寻道大千")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 28px; font-weight: 700;")
        subtitle = QLabel("支付宝扫码登录")
        subtitle.setObjectName("muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label = QLabel("正在准备二维码…")
        self.qr_label.setFixedSize(320, 320)
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setStyleSheet("background:#fff; border:1px solid #dfe7e4; border-radius:8px; color:#879499;")
        self.login_status = QLabel("正在初始化…")
        self.login_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        buttons = QHBoxLayout()
        refresh = PrimaryPushButton(FIF.SYNC, "刷新二维码")
        settings = PushButton(FIF.SETTING, "登录设置")
        refresh.clicked.connect(self.start_login)
        settings.clicked.connect(self.open_settings)
        buttons.addStretch(); buttons.addWidget(refresh); buttons.addWidget(settings); buttons.addStretch()
        layout.addStretch(); layout.addWidget(title); layout.addWidget(subtitle)
        qr_row = QHBoxLayout(); qr_row.addStretch(); qr_row.addWidget(self.qr_label); qr_row.addStretch()
        layout.addLayout(qr_row); layout.addWidget(self.login_status); layout.addLayout(buttons); layout.addStretch()
        return page

    def _build_dashboard(self) -> QWidget:
        config = read_config()
        page = QWidget(); page.setObjectName("page")
        outer = QVBoxLayout(page); set_margins(outer, 0, 0, 0, 0); outer.setSpacing(0)
        content = QVBoxLayout(); set_margins(content, 18, 14, 18, 14); content.setSpacing(14)
        content.addWidget(self._profile_card())
        main = QHBoxLayout(); main.setSpacing(14)
        main.addWidget(self._navigation(), 0)
        main.addWidget(self._settings_panel(config), 3)
        main.addWidget(self._log_panel(), 2)
        content.addLayout(main, 1)
        holder = QWidget(); holder.setLayout(content); outer.addWidget(holder, 1)
        outer.addWidget(self._footer())
        return page

    def _profile_card(self) -> QFrame:
        card = Card(); card.setFixedHeight(142)
        layout = QHBoxLayout(card); set_margins(layout, 22, 15, 0, 15); layout.setSpacing(18)
        avatar = QLabel("道"); avatar.setAlignment(Qt.AlignmentFlag.AlignCenter); avatar.setFixedSize(88, 88)
        avatar.setStyleSheet("background:#e9f7f1;color:#239d73;border:2px solid #b9dfd1;border-radius:44px;font-size:30px;font-weight:700;")
        identity = QVBoxLayout(); identity.setSpacing(6)
        self.role_name = QLabel("暂无角色"); self.role_name.setObjectName("roleName")
        self.role_meta = QLabel("角色信息尚未加载"); self.role_meta.setObjectName("muted")
        account = "--"
        if self.login_path and self.login_path.exists():
            try:
                user_id = str(json.loads(self.login_path.read_text(encoding="utf-8-sig")).get("data", {}).get("userId", ""))
                account = user_id if len(user_id) <= 8 else f"{user_id[:4]}…{user_id[-4:]}"
            except (OSError, json.JSONDecodeError):
                pass
        self.account_meta = QLabel(f"账号：{account}    共 {len(self.roles)} 个角色"); self.account_meta.setObjectName("muted")
        identity.addWidget(self.role_name); identity.addWidget(self.role_meta); identity.addWidget(self.account_meta); identity.addStretch()
        selector = QGridLayout(); selector.setHorizontalSpacing(10); selector.setVerticalSpacing(10)
        selector.addWidget(QLabel("区服 / 角色"), 0, 0)
        self.role_combo = ComboBox(); self.role_combo.setMinimumWidth(280)
        self.role_combo.addItems([f"{r.get('serverName', '-')}  |  {r.get('nickName', '-')}" for r in self.roles])
        self.role_combo.currentIndexChanged.connect(self._select_role)
        selector.addWidget(self.role_combo, 0, 1)
        layout.addWidget(avatar); layout.addLayout(identity, 2); layout.addLayout(selector, 2)
        layout.addStretch()
        self.resource_values: dict[str, QLabel] = {}
        for label, value, object_name in (("灵石", "--", "resourceGreen"), ("仙玉", "--", "resourceBlue"), ("妖力", "--", "resourceOrange"), ("境界", "--", "resourceGreen")):
            box = QVBoxLayout(); box.setSpacing(3)
            icon = QLabel(label[0]); icon.setObjectName(object_name); icon.setAlignment(Qt.AlignmentFlag.AlignCenter); icon.setFixedSize(46, 46)
            name = QLabel(label); name.setAlignment(Qt.AlignmentFlag.AlignCenter); name.setStyleSheet(f"color:{'#25a474' if label == '灵石' else '#3094cf' if label == '仙玉' else '#e99a32'};")
            amount = QLabel(value); amount.setAlignment(Qt.AlignmentFlag.AlignCenter); amount.setStyleSheet("font-size:16px;font-weight:700;")
            self.resource_values[label] = amount
            box.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter); box.addWidget(name); box.addWidget(amount)
            wrap = QWidget(); wrap.setMinimumWidth(135); wrap.setLayout(box); layout.addWidget(wrap)
        return card

    def _navigation(self) -> QFrame:
        nav = Card(object_name="nav"); nav.setFixedWidth(78)
        layout = QVBoxLayout(nav); set_margins(layout, 0, 0, 0, 0); layout.setSpacing(0)
        items = ((FIF.LEAF, "砍树"), (FIF.HISTORY, "历练"), (FIF.GAME, "妖王"), (FIF.GLOBE, "秘境"), (FIF.MARKET, "领取奖励"), (FIF.CALENDAR, "活动任务"), (FIF.MORE, "更多功能"))
        for index, (icon, text) in enumerate(items):
            item = QFrame(); item.setObjectName("navActive" if index == 0 else "navItem"); item.setFixedHeight(72)
            item_layout = QVBoxLayout(item); set_margins(item_layout, 4, 7, 4, 5); item_layout.setSpacing(2)
            button = ToolButton(); button.setIcon(icon.icon(color=QColor("#28a779" if index == 0 else "#98a4a8")))
            button.setFixedSize(30, 30)
            button.setStyleSheet("QToolButton{background:transparent;border:0;border-radius:4px;} QToolButton:hover{background:#e8f4ef;}")
            label = QLabel(text); label.setAlignment(Qt.AlignmentFlag.AlignCenter); label.setStyleSheet("font-size:11px;")
            item_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
            item_layout.addWidget(label)
            if index == 2:
                button.clicked.connect(self._select_wild_boss_task)
            elif index:
                button.clicked.connect(lambda _checked=False, name=text: self.append_log(f"{name}功能暂未开放。"))
            layout.addWidget(item)
        layout.addStretch()
        return nav

    def _select_wild_boss_task(self) -> None:
        self.wild_boss_enabled.setChecked(True)
        self.append_log("已选择挑战妖王任务，可设置挑战次数后启动。")

    def _settings_panel(self, config: dict[str, str]) -> QFrame:
        panel = Card(); layout = QVBoxLayout(panel); set_margins(layout, 16, 14, 16, 16); layout.setSpacing(12)
        head = QHBoxLayout(); title = QLabel("⚙  功能设置"); title.setObjectName("sectionTitle")
        advanced = PushButton(FIF.SETTING, "高级设置"); advanced.clicked.connect(self.open_settings)
        head.addWidget(title); head.addStretch(); head.addWidget(advanced); layout.addLayout(head)
        task = Card(object_name="softCard"); task_layout = QVBoxLayout(task); set_margins(task_layout, 16, 14, 16, 16)
        title_row = QHBoxLayout(); self.chop_enabled = CheckBox("自动砍树"); self.chop_enabled.setChecked(True)
        desc = QLabel("自动执行砍树任务并处理掉落装备"); desc.setObjectName("muted")
        title_row.addWidget(self.chop_enabled); title_row.addWidget(desc); title_row.addStretch(); task_layout.addLayout(title_row)
        form = QGridLayout(); form.setHorizontalSpacing(14); form.setVerticalSpacing(12)
        self.count_values: list[int | None] = [None, 1, 5, 10, 20, 50, 100, 500, 1000]
        self.count_input = ComboBox(); self.count_input.addItems(["无限次", "1 次", "5 次", "10 次", "20 次", "50 次", "100 次", "500 次", "1000 次"])
        saved_count = config.get("chopCount", "unlimited")
        try:
            count_value: int | None = int(saved_count)
        except (TypeError, ValueError):
            count_value = None
        self.count_input.setCurrentIndex(self.count_values.index(count_value) if count_value in self.count_values else 0)
        self.interval_input = DoubleSpinBox(); self.interval_input.setRange(0, 60); self.interval_input.setSingleStep(0.5); self.interval_input.setValue(float(config["chopInterval"]))
        self.action_input = ComboBox(); self.action_input.addItems(["遇到装备停止", "自动分解"]); self.action_input.setCurrentIndex(1 if config["equipmentAction"] == "decompose" else 0)
        self.quality_input = SpinBox(); self.quality_input.setRange(1, 45); self.quality_input.setValue(int(config["keepQuality"]))
        self.attribute_values = [0, *ATTRIBUTE_NAMES.keys()]
        self.attribute_input = ComboBox(); self.attribute_input.addItems(
            ["不按属性保留", *[ATTRIBUTE_NAMES[value] for value in ATTRIBUTE_NAMES]]
        )
        saved_attribute = int(config.get("keepAttributeType", "0"))
        self.attribute_input.setCurrentIndex(
            self.attribute_values.index(saved_attribute) if saved_attribute in self.attribute_values else 0
        )
        self.quality_input.setEnabled(self.attribute_input.currentIndex() == 0)
        self.attribute_input.currentIndexChanged.connect(
            lambda index: self.quality_input.setEnabled(index == 0)
        )
        form.addWidget(QLabel("砍树次数"), 0, 0); form.addWidget(self.count_input, 0, 1)
        form.addWidget(QLabel("装备处理"), 0, 2); form.addWidget(self.action_input, 0, 3)
        form.addWidget(QLabel("间隔时间"), 1, 0); form.addWidget(self.interval_input, 1, 1)
        form.addWidget(QLabel("保留品质（无属性条件时）"), 1, 2); form.addWidget(self.quality_input, 1, 3)
        form.addWidget(QLabel("保留属性"), 2, 0); form.addWidget(self.attribute_input, 2, 1)
        attribute_rule = QLabel("高于当前同部位装备时自动替换"); attribute_rule.setObjectName("muted")
        form.addWidget(attribute_rule, 2, 2, 1, 2)
        task_layout.addLayout(form); layout.addWidget(task)
        rank_task = Card(object_name="softCard"); rank_layout = QHBoxLayout(rank_task); set_margins(rank_layout, 16, 14, 16, 14)
        self.rank_enabled = CheckBox("自动斗法")
        self.rank_enabled.setChecked(config.get("autoRankBattle", "false").lower() == "true")
        self.rank_ticket_label = QLabel("（挑战状：0 张）"); self.rank_ticket_label.setObjectName("muted")
        rank_info = ToolButton(); rank_info.setIcon(FIF.INFO.icon(color=QColor("#7d8b90"))); rank_info.setFixedSize(28, 28)
        rank_info.setToolTip("有挑战状时自动挑战妖力最低的可用对手；没有挑战状时继续等待砍树掉落。")
        rank_layout.addWidget(self.rank_enabled); rank_layout.addWidget(self.rank_ticket_label); rank_layout.addWidget(rank_info); rank_layout.addStretch()
        layout.addWidget(rank_task)
        wild_boss_task = Card(object_name="softCard")
        wild_boss_layout = QHBoxLayout(wild_boss_task); set_margins(wild_boss_layout, 16, 12, 16, 12)
        self.wild_boss_enabled = CheckBox("挑战妖王")
        self.wild_boss_enabled.setChecked(config.get("autoWildBoss", "false").lower() == "true")
        self.wild_boss_count_values = [1, 2, 3, 4, 5, 6]
        self.wild_boss_count = ComboBox()
        self.wild_boss_count.addItems([f"{value} 次" for value in self.wild_boss_count_values])
        saved_wild_boss_count = int(config.get("wildBossCount", "6"))
        self.wild_boss_count.setCurrentIndex(
            self.wild_boss_count_values.index(saved_wild_boss_count)
            if saved_wild_boss_count in self.wild_boss_count_values else 5
        )
        self.wild_boss_remaining_label = QLabel("今日剩余 --/6 次")
        self.wild_boss_remaining_label.setObjectName("muted")
        wild_boss_layout.addWidget(self.wild_boss_enabled)
        wild_boss_layout.addSpacing(12)
        wild_boss_layout.addWidget(QLabel("挑战次数"))
        wild_boss_layout.addWidget(self.wild_boss_count)
        wild_boss_layout.addSpacing(12)
        wild_boss_layout.addWidget(self.wild_boss_remaining_label)
        wild_boss_layout.addStretch()
        layout.addWidget(wild_boss_task)
        limited_task = Card(object_name="softCard")
        limited_layout = QGridLayout(limited_task); set_margins(limited_layout, 16, 12, 16, 12)
        limited_layout.setHorizontalSpacing(12); limited_layout.setVerticalSpacing(8)
        self.invade_enabled, self.invade_count, self.invade_remaining_label = self._add_limited_task_row(
            limited_layout, 0, "异兽入侵", 5, config.get("autoInvade", "false"), config.get("invadeCount", "5"),
            "今日剩余 --/5 次",
        )
        self.star_trial_enabled, self.star_trial_count, self.star_trial_remaining_label = self._add_limited_task_row(
            limited_layout, 1, "星宿试炼", 30, config.get("autoStarTrial", "false"), config.get("starTrialCount", "30"),
            "今日剩余 --/30 次",
        )
        self.hero_rank_enabled, self.hero_rank_count, self.hero_rank_remaining_label = self._add_limited_task_row(
            limited_layout, 2, "群英榜", 10, config.get("autoHeroRank", "false"), config.get("heroRankCount", "10"),
            "当前体力 --/10",
        )
        layout.addWidget(limited_task)
        layout.addStretch()
        return panel

    def _add_limited_task_row(
        self, layout: QGridLayout, row: int, name: str, maximum: int,
        enabled: str, saved_count: str, remaining_text: str,
    ) -> tuple[CheckBox, ComboBox, QLabel]:
        checkbox = CheckBox(name); checkbox.setChecked(str(enabled).lower() == "true")
        count_input = ComboBox(); count_input.addItems([f"{value} 次" for value in range(1, maximum + 1)])
        try: selected = int(saved_count)
        except (TypeError, ValueError): selected = maximum
        count_input.setCurrentIndex(max(0, min(maximum, selected) - 1))
        remaining = QLabel(remaining_text); remaining.setObjectName("muted")
        layout.addWidget(checkbox, row, 0); layout.addWidget(QLabel("次数"), row, 1)
        layout.addWidget(count_input, row, 2); layout.addWidget(remaining, row, 3); layout.setColumnStretch(4, 1)
        return checkbox, count_input, remaining

    def _log_panel(self) -> QFrame:
        panel = Card(); panel.setMinimumWidth(400)
        layout = QVBoxLayout(panel); set_margins(layout, 14, 14, 14, 14); layout.setSpacing(10)
        head = QHBoxLayout(); title = QLabel("▤  日志输出"); title.setObjectName("sectionTitle")
        clear = PushButton(FIF.DELETE, "清空日志"); clear.clicked.connect(lambda: self.log_text.clear())
        head.addWidget(title); head.addStretch(); head.addWidget(clear); layout.addLayout(head)
        self.log_text = QPlainTextEdit(); self.log_text.setReadOnly(True); self.log_text.setFont(QFont("Microsoft YaHei UI", 9)); layout.addWidget(self.log_text)
        return panel

    def _footer(self) -> QFrame:
        footer = Card(object_name="footer"); footer.setFixedHeight(64)
        layout = QHBoxLayout(footer); set_margins(layout, 20, 0, 20, 0); layout.setSpacing(10)
        config = PushButton(FIF.SETTING, "配置管理"); config.clicked.connect(self.open_settings)
        import_button = PushButton(FIF.DOWNLOAD, "导入配置"); import_button.clicked.connect(lambda: self.append_log("导入配置功能暂未开放。"))
        export_button = PushButton(FIF.SAVE_AS, "导出配置"); export_button.clicked.connect(lambda: self.append_log("导出配置功能暂未开放。"))
        self.start_button = PrimaryPushButton(FIF.PLAY, "启动脚本"); self.start_button.clicked.connect(self.start_chop)
        pause = PushButton(FIF.PAUSE, "暂停"); pause.clicked.connect(lambda: self.append_log("当前任务暂不支持暂停。"))
        self.stop_button = PushButton(FIF.CANCEL, "停止"); self.stop_button.clicked.connect(self.stop_chop)
        self.stop_button.setStyleSheet("color:#d94f4f;")
        self.connection_status = QLabel("●  等待连接"); self.connection_status.setObjectName("statusGood")
        self.runtime_label = QLabel("运行时长：00:00:00"); self.runtime_label.setObjectName("muted")
        layout.addWidget(config); layout.addWidget(import_button); layout.addWidget(export_button)
        layout.addStretch(1)
        layout.addWidget(self.start_button); layout.addWidget(pause); layout.addWidget(self.stop_button)
        layout.addStretch(1)
        layout.addWidget(self.connection_status); layout.addSpacing(24); layout.addWidget(self.runtime_label)
        return footer

    def _update_runtime(self) -> None:
        elapsed = self.runtime_seconds
        if self.runtime_started_at is not None:
            elapsed += time.monotonic() - self.runtime_started_at
        total_seconds = int(elapsed)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.runtime_label.setText(f"运行时长：{hours:02d}:{minutes:02d}:{seconds:02d}")

    def _start_runtime(self) -> None:
        if self.runtime_started_at is not None:
            return
        self.runtime_started_at = time.monotonic()
        self.runtime_timer.start()
        self._update_runtime()

    def _stop_runtime(self) -> None:
        if self.runtime_started_at is None:
            return
        self.runtime_seconds += time.monotonic() - self.runtime_started_at
        self.runtime_started_at = None
        self.runtime_timer.stop()
        self._update_runtime()

    def _select_role(self, index: int) -> None:
        if index < 0 or index >= len(self.roles): return
        role = self.roles[index]; self.current_role = dict(role)
        self.role_name.setText(str(role.get("nickName", "-")))
        self.role_meta.setText(f"区服：{role.get('serverName', '-')}    称号：寻道者")
        self.resource_values["境界"].setText(str(role.get("realmsId", "-")))
        update_config(selectedServerId=role.get("serverId", ""))
        self.append_log(f"已选择 {role.get('serverName', '-')} / {role.get('nickName', '-')}。")
        selected_server = int(role.get("serverId", 0))

        def worker() -> None:
            try:
                self.event.emit("profile_snapshot", fetch_role_snapshot(selected_server, OUTPUT_DIR))
            except (OSError, ValueError, KeyError, RuntimeError, websocket.WebSocketException) as exc:
                self.event.emit("profile_error", f"{type(exc).__name__}: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def show_dashboard(self, path: Path, roles: list[dict[str, Any]]) -> None:
        self.login_path, self.roles = path, roles
        dashboard = self._build_dashboard(); self.stack.addWidget(dashboard); self.stack.setCurrentWidget(dashboard)
        self.app_title_bar.set_connected(True)
        saved = read_config().get("selectedServerId", "")
        index = next((i for i, role in enumerate(roles) if str(role.get("serverId")) == saved), 0)
        if roles:
            self.role_combo.blockSignals(True)
            self.role_combo.setCurrentIndex(index)
            self.role_combo.blockSignals(False)
            self._select_role(index)
        self.append_log("登录状态有效，角色数据加载完成。")

    def append_log(self, message: str) -> None:
        if not hasattr(self, "log_text"): return
        if any(word in message.lower() for word in ("失败", "错误", "拒绝", "error", "failed")): category, color = "错误", "#dc5656"
        elif any(word in message for word in ("完成", "成功", "获得", "保留")): category, color = "成功", "#df8b2d"
        elif any(word in message for word in ("砍树", "装备", "任务", "执行")): category, color = "砍树", "#28a66f"
        else: category, color = "系统", "#2685c7"
        cursor = self.log_text.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(f"[{time.strftime('%H:%M:%S')}]  ", QTextCharFormat())
        fmt = QTextCharFormat(); fmt.setForeground(QColor(color)); fmt.setFontWeight(QFont.Weight.DemiBold)
        cursor.insertText(f"{category:<4}", fmt)
        body = QTextCharFormat(); body.setForeground(QColor("#3e4c51")); cursor.insertText(f"  {message}\n", body)
        self.log_text.setTextCursor(cursor); self.log_text.ensureCursorVisible()

    @staticmethod
    def format_amount(value: int | str) -> str:
        number = int(value)
        if number >= 100_000_000:
            return f"{number / 100_000_000:.2f}亿"
        if number >= 10_000:
            return f"{number / 10_000:.2f}万"
        return str(number)

    def open_settings(self) -> None:
        if SettingsDialog(self).exec() == QDialog.DialogCode.Accepted:
            self.start_login()

    def restore_session(self) -> None:
        try: config = read_config()
        except (OSError, json.JSONDecodeError, RuntimeError): self.start_login(); return
        token = config.get("sessionToken", "")
        if not token: self.start_login(); return
        self.login_status.setText("正在验证上次登录状态…")
        def worker() -> None:
            try:
                game_data = fetch_game_data(token, config["ctoken"], OUTPUT_DIR)
                roles = fetch_roles(game_data["auth"]["data"]["authCode"], OUTPUT_DIR)
                path = OUTPUT_DIR / "login-success.json"
                if not path.exists(): save_json(OUTPUT_DIR, "login-success.json", {"success": True, "data": {"token": token, "userId": ""}})
                self.event.emit("dashboard", (path, roles))
            except Exception as exc: self.event.emit("cached_invalid", str(exc))
        self.worker = threading.Thread(target=worker, daemon=True); self.worker.start()

    def start_login(self) -> None:
        self.app_title_bar.set_connected(False)
        self.stack.setCurrentWidget(self.login_page)
        try: config = read_config()
        except Exception as exc: self.login_status.setText(str(exc)); return
        if not config.get("pcToken") or not config.get("ctoken"):
            self.login_status.setText("请先填写登录配置"); self.open_settings(); return
        self.stop_event.set(); self.stop_event = threading.Event()
        self.login_status.setText("正在连接登录服务…"); self.qr_label.setText("正在获取二维码…"); self.qr_label.setPixmap(QPixmap())
        self.worker = threading.Thread(target=self._login_worker, args=(config, self.stop_event), daemon=True); self.worker.start()

    def _login_worker(self, config: dict[str, str], stop_event: threading.Event) -> None:
        try:
            session = requests.Session(); session.headers.update({
                "Accept": "application/json, text/plain, */*", "Content-Type": "application/json",
                "Origin": DEFAULT_ORIGIN, "Referer": DEFAULT_ORIGIN + "/", "User-Agent": DEFAULT_UA,
                "x-game-token-pcweb": config["pcToken"], "x-webgw-appid": DEFAULT_APP_ID,
                "x-webgw-ldc-uid": "05", "x-webgw-version": "2.0",
            })
            query = urlencode({"ctoken": config["ctoken"]})
            token_response = request_json(session, f"{BASE_URL}{SERVICE}/getLoginToken?{query}", {}, 15)
            save_json(OUTPUT_DIR, "get-login-token.json", token_response)
            qr_data = token_response["data"]["qrCode"]; qr_url = str(qr_data["url"]); login_token = str(qr_data["token"])
            image = qrcode.make(qr_url).convert("RGB").resize((286, 286), Image.Resampling.NEAREST)
            stream = io.BytesIO(); image.save(stream, format="PNG"); self.event.emit("qr", stream.getvalue())
            while not stop_event.wait(POLL_INTERVAL):
                payload = request_json(session, f"{BASE_URL}{SERVICE}/loginForPc?{query}", {"token": login_token, "userAgent": DEFAULT_UA}, 15)
                save_json(OUTPUT_DIR, "login-last-response.json", payload); state = classify(payload)
                if state == "success":
                    path = save_json(OUTPUT_DIR, "login-success.json", payload); token = str(payload["data"]["token"]); update_config(sessionToken=token)
                    game_data = fetch_game_data(token, config["ctoken"], OUTPUT_DIR); roles = fetch_roles(game_data["auth"]["data"]["authCode"], OUTPUT_DIR)
                    self.event.emit("dashboard", (path, roles)); return
                if state in ("expired", "failed"): self.event.emit(state, payload); return
                self.event.emit("status", "等待扫码确认…")
        except Exception as exc:
            if not stop_event.is_set(): self.event.emit("error", str(exc))

    def start_chop(self) -> None:
        if not self.current_role:
            return
        run_chop = self.chop_enabled.isChecked()
        run_wild_boss = self.wild_boss_enabled.isChecked()
        run_invade = self.invade_enabled.isChecked()
        run_star_trial = self.star_trial_enabled.isChecked()
        run_hero_rank = self.hero_rank_enabled.isChecked()
        if not any((run_chop, run_wild_boss, run_invade, run_star_trial, run_hero_rank)):
            self.append_log("请至少选择一个任务。")
            return
        action = "decompose" if self.action_input.currentIndex() == 1 else "stop"
        count = self.count_values[self.count_input.currentIndex()]
        saved_count = "unlimited" if count is None else count
        attribute_type = self.attribute_values[self.attribute_input.currentIndex()]
        update_config(
            chopCount=saved_count, chopInterval=self.interval_input.value(), equipmentAction=action,
            keepQuality=self.quality_input.value(), keepAttributeType=attribute_type,
            autoRankBattle=self.rank_enabled.isChecked(),
            autoWildBoss=run_wild_boss,
            wildBossCount=self.wild_boss_count_values[self.wild_boss_count.currentIndex()],
            autoInvade=run_invade, invadeCount=self.invade_count.currentIndex() + 1,
            autoStarTrial=run_star_trial, starTrialCount=self.star_trial_count.currentIndex() + 1,
            autoHeroRank=run_hero_rank, heroRankCount=self.hero_rank_count.currentIndex() + 1,
        )
        self.chop_stop_event = threading.Event()
        self.start_button.setEnabled(False); role = dict(self.current_role)
        self._start_runtime()
        interval = self.interval_input.value()
        quality = self.quality_input.value()
        auto_rank_battle = self.rank_enabled.isChecked()
        wild_boss_count = self.wild_boss_count_values[self.wild_boss_count.currentIndex()]
        invade_count = self.invade_count.currentIndex() + 1
        star_trial_count = self.star_trial_count.currentIndex() + 1
        hero_rank_count = self.hero_rank_count.currentIndex() + 1
        count_text = "无限次" if count is None else f"{count} 次"
        if run_wild_boss:
            self.append_log(
                f"开始执行挑战妖王：{role.get('serverName')} / {role.get('nickName')}，"
                f"最多 {wild_boss_count} 次。"
            )
        if run_chop:
            self.append_log(f"开始执行自动砍树：{role.get('serverName')} / {role.get('nickName')}，计划 {count_text}。")
        def worker() -> None:
            try:
                auxiliary_tasks = [
                    (run_wild_boss, run_wild_boss_tasks, wild_boss_count, "挑战妖王"),
                    (run_invade, run_invade_tasks, invade_count, "异兽入侵"),
                    (run_star_trial, run_star_trial_tasks, star_trial_count, "星宿试炼"),
                    (run_hero_rank, run_hero_rank_tasks, hero_rank_count, "群英榜"),
                ]
                task_results = []
                for enabled, runner, task_count, task_name in auxiliary_tasks:
                    if not enabled:
                        continue
                    result = runner(
                        int(role["serverId"]), OUTPUT_DIR, task_count,
                        lambda msg: self.event.emit("chop_log", msg), self.chop_stop_event,
                        snapshot=lambda value: self.event.emit("profile_snapshot", value),
                    )
                    result["taskName"] = task_name
                    task_results.append(result)
                    self.event.emit("limited_task_result", result)
                if not run_chop:
                    self.event.emit("auxiliary_tasks_done", task_results)
                    return
                result = run_chop_tasks(
                    int(role["serverId"]), OUTPUT_DIR, count, interval, action, quality,
                    lambda msg: self.event.emit("chop_log", msg), self.chop_stop_event,
                    keep_attribute_type=attribute_type,
                    snapshot=lambda value: self.event.emit("profile_snapshot", value),
                    auto_rank_battle=auto_rank_battle,
                )
                try:
                    self.event.emit(
                        "profile_snapshot",
                        fetch_role_snapshot(int(role["serverId"]), OUTPUT_DIR),
                    )
                except (OSError, ValueError, KeyError, RuntimeError, websocket.WebSocketException) as exc:
                    self.event.emit("profile_error", f"最终资源刷新失败：{type(exc).__name__}: {exc}")
                self.event.emit("chop_success", result)
            except (OSError, ValueError, KeyError, RuntimeError, websocket.WebSocketException) as exc:
                detail = traceback.format_exc()
                try:
                    (OUTPUT_DIR / "chop-task-error.log").write_text(detail, encoding="utf-8")
                except OSError:
                    pass
                self.event.emit("chop_error", f"{type(exc).__name__}: {exc}")
        threading.Thread(target=worker, daemon=True).start()

    def stop_chop(self) -> None:
        if self.start_button.isEnabled():
            self.append_log("当前没有正在运行的任务。")
            return
        self.chop_stop_event.set()
        self.append_log("已请求停止，当前操作完成后将安全退出。")

    def _handle_event(self, event: str, value: object) -> None:
        if event == "dashboard": self.show_dashboard(*value)
        elif event == "qr":
            pixmap = QPixmap(); pixmap.loadFromData(value); self.qr_label.setPixmap(pixmap); self.login_status.setText("二维码已生成，请使用支付宝扫码")
        elif event == "status": self.login_status.setText(str(value))
        elif event == "cached_invalid": self.login_status.setText("上次登录已失效，请重新扫码"); self.start_login()
        elif event == "expired": self.login_status.setText("二维码已过期，请刷新")
        elif event == "failed": self.login_status.setText("登录失败，请刷新二维码或更新配置")
        elif event == "error": self.login_status.setText(f"请求失败：{value}")
        elif event == "chop_log": self.append_log(str(value))
        elif event == "profile_snapshot":
            if not self.current_role or int(value.get("serverId", 0)) != int(self.current_role.get("serverId", 0)):
                return
            self.resource_values["灵石"].setText(self.format_amount(value.get("spiritStone", 0)))
            self.resource_values["仙玉"].setText(self.format_amount(value.get("jade", 0)))
            self.resource_values["妖力"].setText(self.format_amount(value.get("power", 0)))
            self.resource_values["境界"].setText(str(value.get("realmId", "-")))
            if hasattr(self, "rank_ticket_label"):
                self.rank_ticket_label.setText(f"（挑战状：{value.get('rankBattleTicket', 0)} 张）")
            if hasattr(self, "wild_boss_remaining_label"):
                daily_max = int(value.get("wildBossDailyMax", 6))
                remaining = value.get("wildBossRemaining")
                selected = self.wild_boss_count_values[self.wild_boss_count.currentIndex()]
                if self.wild_boss_count_values[-1] != daily_max:
                    self.wild_boss_count_values = list(range(1, daily_max + 1))
                    self.wild_boss_count.clear()
                    self.wild_boss_count.addItems([f"{item} 次" for item in self.wild_boss_count_values])
                    self.wild_boss_count.setCurrentIndex(min(selected, daily_max) - 1)
                remaining_text = "--" if remaining is None else str(int(remaining))
                self.wild_boss_remaining_label.setText(f"今日剩余 {remaining_text}/{daily_max} 次")
            if hasattr(self, "invade_remaining_label"):
                self.invade_remaining_label.setText(f"今日剩余 {int(value.get('invadeRemaining', 0))}/5 次")
                self.star_trial_remaining_label.setText(f"今日剩余 {int(value.get('starTrialRemaining', 0))}/30 次")
                self.hero_rank_remaining_label.setText(f"当前体力 {int(value.get('heroRankEnergy', 0))}/10")
            self.account_meta.setText(
                f"修为：{self.format_amount(value.get('cultivation', 0))}    "
                f"妖力：{self.format_amount(value.get('power', 0))}"
            )
            self.append_log("角色资产与妖力数据加载完成。")
        elif event == "profile_error":
            self.append_log(f"角色详细数据读取失败：{value}")
        elif event == "chop_error":
            self.start_button.setEnabled(True); self._stop_runtime()
            self.append_log(f"连接或请求失败：{value}")
        elif event == "limited_task_result":
            task_name = value.get("taskName", "限次任务")
            completed = value.get("completed", 0)
            remaining = value.get("remaining", 0)
            if value.get("reason") == "finished":
                self.append_log(f"{task_name}任务完成，共挑战 {completed} 次，剩余 {remaining}。")
            elif value.get("reason") == "stopped":
                self.append_log(f"{task_name}已停止，共完成 {completed} 次，剩余 {remaining}。")
            else:
                self.append_log(
                    f"{task_name}停止：{value.get('reason')}，服务端返回 {value.get('ret')}，"
                    f"已完成 {completed} 次。"
                )
        elif event == "auxiliary_tasks_done":
            self.start_button.setEnabled(True); self._stop_runtime()
        elif event == "chop_success":
            self.start_button.setEnabled(True); self._stop_runtime()
            completed = value.get("completed", 0); reason = value.get("reason", "unknown")
            messages = {
                "finished": f"砍树任务完成，共执行 {completed} 次。",
                "stopped": f"砍树任务已停止，共执行 {completed} 次。",
                "kept": f"任务停止：发现需要保留的装备，共执行 {completed} 次。",
                "unsafe_source": "安全停止：待处理列表中存在非砍树来源装备。",
                "decompose_failed": f"自动分解失败，服务端返回 {value.get('ret')}。",
                "replace_failed": f"装备替换失败，服务端返回 {value.get('ret')}。",
                "reconnect_failed": f"游戏连接恢复失败：{value.get('error', '未知错误')}。",
                "chop_failed": f"砍树请求失败，服务端返回 {value.get('ret')}。",
            }
            self.append_log(messages.get(reason, f"任务停止：{reason}，服务端返回 {value.get('ret')}。"))

    def closeEvent(self, event: Any) -> None:
        self.stop_event.set(); self.chop_stop_event.set(); super().closeEvent(event)


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv); app.setFont(QFont("Microsoft YaHei UI", 10)); setTheme(Theme.LIGHT)
    window = XundaoWindow(); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
