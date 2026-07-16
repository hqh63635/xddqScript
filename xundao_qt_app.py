#!/usr/bin/env python3
"""PySide6 + QFluentWidgets desktop client for Xundao."""

from __future__ import annotations

import io
import base64
import faulthandler
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
from PySide6.QtGui import QColor, QFont, QIcon, QPalette, QPixmap, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget, QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox,
    QToolButton,
)
try:
    from qframelesswindow import FramelessWindow, TitleBar
except ModuleNotFoundError:
    class TitleBar(QWidget):
        def __init__(self, parent: QWidget) -> None:
            super().__init__(parent)
            self.hBoxLayout = QHBoxLayout(self)
            self.minBtn = QPushButton("-", self)
            self.maxBtn = QPushButton("+", self)
            self.closeBtn = QPushButton("x", self)
            self.minBtn.clicked.connect(parent.showMinimized)
            self.maxBtn.clicked.connect(
                lambda: parent.showNormal() if parent.isMaximized() else parent.showMaximized()
            )
            self.closeBtn.clicked.connect(parent.close)

    class FramelessWindow(QWidget):
        def setTitleBar(self, title_bar: QWidget) -> None:
            self._title_bar = title_bar


USING_FLUENT_WIDGETS = True
try:
    from qfluentwidgets import (
        CheckBox, ComboBox, DoubleSpinBox, FluentIcon as FIF, LineEdit, PasswordLineEdit,
        PrimaryPushButton, PushButton, SpinBox, Theme, ToolButton, setTheme,
    )
except ModuleNotFoundError:
    USING_FLUENT_WIDGETS = False
    CheckBox = QCheckBox
    ComboBox = QComboBox
    DoubleSpinBox = QDoubleSpinBox
    LineEdit = QLineEdit
    SpinBox = QSpinBox
    ToolButton = QToolButton

    class Theme:
        LIGHT = "light"

    def setTheme(_: Any) -> None:
        pass

    class _FallbackIcon:
        def icon(self, color: QColor | None = None) -> QIcon:
            return QIcon()

    class _FallbackIcons:
        def __getattr__(self, _: str) -> _FallbackIcon:
            return _FallbackIcon()

    FIF = _FallbackIcons()

    class PushButton(QPushButton):
        def __init__(self, *args: Any) -> None:
            parent: QWidget | None = None
            icon: QIcon | None = None
            text = ""
            if len(args) == 1:
                text = str(args[0])
            elif len(args) >= 2 and hasattr(args[0], "icon"):
                icon = args[0].icon()
                text = str(args[1])
                if len(args) >= 3:
                    parent = args[2]
            elif len(args) >= 2:
                text = str(args[0])
                parent = args[1]
            super().__init__(text, parent)
            if icon is not None:
                self.setIcon(icon)

    class PrimaryPushButton(PushButton):
        pass

    class PasswordLineEdit(QLineEdit):
        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setEchoMode(QLineEdit.EchoMode.Password)

from xundao_game_client import fetch_game_data
from xundao_game_session import (
    ATTRIBUTE_NAMES,
    DESTINY_TRAVEL_COUNT_MAX,
    HOMELAND_RESOURCE_NAMES,
    PROFESSION_CHALLENGE_DAILY_MAX,
    fetch_role_snapshot,
    run_chop_tasks,
    run_adventure_tasks,
    run_destiny_travel_tasks,
    run_divine_mind_collection_tasks,
    run_hero_rank_tasks,
    run_homeland_tasks,
    run_invade_tasks,
    run_law_looks_draw_tasks,
    run_magic_draw_tasks,
    run_magic_treasure_tasks,
    run_pet_kernel_draw_tasks,
    run_profession_challenge_tasks,
    run_profession_quick_task,
    run_pupil_training_tasks,
    run_star_trial_tasks,
    run_spirit_draw_tasks,
    run_talent_tasks,
    run_treasure_auction_tasks,
    run_tower_tasks,
    run_universe_skill_draw_tasks,
    run_universe_wheel_draw_tasks,
    run_wild_boss_tasks,
    run_yard_daily_tasks,
    run_yard_draw_tasks,
)
from xundao_role_client import fetch_roles
from xundao_qr_login import (
    BASE_URL, DEFAULT_APP_ID, DEFAULT_ORIGIN, DEFAULT_UA, SERVICE,
    classify, request_json, save_json,
)


APP_TITLE = "寻道大千脚本助手"
POLL_INTERVAL = 2.0
UI_FONT_FAMILY = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


CONFIG_PATH = app_dir() / "config.json"
OUTPUT_DIR = app_dir() / "login-output"
_FAULT_LOG: io.TextIOWrapper | None = None


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
        "autoDestinyTravel": "false", "destinyTravelCount": "10",
        "autoProfessionQuick": "false", "autoProfessionChallenge": "false",
        "professionChallengeCount": "30",
        "autoYardDaily": "false", "autoYardDraw": "false", "yardDrawCount": "1",
        "autoHomeland": "false", "homelandPreferredItem": "100004", "homelandPreferredLevel": "3",
        "autoTalent": "false", "talentDrawCount": "3", "talentTotalCount": "unlimited",
        "talentDrawInterval": "2.0",
        "talentMinimumQuality": "5", "talentPreferredAttribute": "5",
        "autoMagicDraw": "false", "magicDrawCount": "2", "magicPaidDrawCount": "0",
        "autoSpiritDraw": "false", "spiritDrawCount": "2", "spiritPaidDrawCount": "0",
        "autoMagicTreasure": "false",
        "magicTreasure1FreeCount": "2", "magicTreasure1PaidCount": "0",
        "magicTreasure2FreeCount": "2", "magicTreasure2PaidCount": "0",
        "magicTreasure3FreeCount": "2", "magicTreasure3PaidCount": "0",
        "autoPupilTraining": "false", "pupilTrainingRounds": "100",
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
    event = Signal(str, str)

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

    def _emit_event(self, event: str, value: object) -> None:
        if isinstance(value, bytes):
            value = {"__bytes__": base64.b64encode(value).decode("ascii")}
        elif event == "dashboard":
            path, roles = value
            value = {"path": str(path), "roles": roles}
        payload = json.dumps(value, ensure_ascii=False)
        self.event.emit(event, payload)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self.app_title_bar.raise_()

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QDialog, #page { background: #f5f7f7; color: #27363b; }
            QLabel { color: #27363b; }
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
            #taskGroupTitle { color: #52636a; font-size: 12px; font-weight: 600; padding-bottom: 3px; }
            #roleName { font-size: 22px; font-weight: 700; color: #17272c; }
            #muted { color: #859398; }
            #statusGood { color: #25a66f; font-weight: 600; }
            QPlainTextEdit { background: #fbfcfc; border: 1px solid #edf1ef; border-radius: 5px; padding: 10px; }
            #settingsScroll { background: transparent; border: 0; }
            #settingsScroll > QWidget > QWidget { background: transparent; }
            #settingsScroll QScrollBar:vertical { background: #edf2f0; width: 8px; margin: 0; border-radius: 4px; }
            #settingsScroll QScrollBar::handle:vertical { background: #aab8b3; min-height: 36px; border-radius: 4px; }
            #settingsScroll QScrollBar::handle:vertical:hover { background: #859690; }
            #settingsScroll QScrollBar::add-line:vertical, #settingsScroll QScrollBar::sub-line:vertical { height: 0; }
            #settingsScroll QScrollBar::add-page:vertical, #settingsScroll QScrollBar::sub-page:vertical { background: transparent; }
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
        self.select_all_tasks = CheckBox("全选")
        self.select_all_tasks.clicked.connect(self._set_all_tasks)
        advanced = PushButton(FIF.SETTING, "高级设置"); advanced.clicked.connect(self.open_settings)
        head.addWidget(title); head.addStretch(); head.addWidget(self.select_all_tasks); head.addSpacing(10)
        head.addWidget(advanced); layout.addLayout(head)

        scroll = QScrollArea(); scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        set_margins(content_layout, 0, 0, 8, 0); content_layout.setSpacing(12)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        task = Card(object_name="softCard"); task_layout = QVBoxLayout(task); set_margins(task_layout, 16, 14, 16, 16)
        title_row = QHBoxLayout(); self.chop_enabled = CheckBox("自动砍树"); self.chop_enabled.setChecked(True)
        desc = QLabel("自动执行砍树任务并处理掉落装备"); desc.setObjectName("muted")
        self.peach_count_label = QLabel("仙桃：--"); self.peach_count_label.setObjectName("muted")
        title_row.addWidget(self.chop_enabled); title_row.addWidget(desc); title_row.addStretch()
        title_row.addWidget(self.peach_count_label); task_layout.addLayout(title_row)
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
        task_layout.addLayout(form); content_layout.addWidget(task)
        pupil_task = Card(object_name="softCard")
        pupil_layout = QHBoxLayout(pupil_task); set_margins(pupil_layout, 16, 12, 16, 12)
        self.pupil_training_enabled = CheckBox("宗门 - 弟子修炼")
        self.pupil_training_enabled.setChecked(config.get("autoPupilTraining", "false").lower() == "true")
        self.pupil_training_rounds = SpinBox()
        self.pupil_training_rounds.setRange(1, 100)
        self.pupil_training_rounds.setValue(int(config.get("pupilTrainingRounds", "100")))
        pupil_hint = QLabel("仅使用现有次数，不购买次数、不自动出师")
        pupil_hint.setObjectName("muted")
        pupil_layout.addWidget(self.pupil_training_enabled)
        pupil_layout.addSpacing(12)
        pupil_layout.addWidget(QLabel("最多轮数"))
        pupil_layout.addWidget(self.pupil_training_rounds)
        pupil_layout.addSpacing(12)
        pupil_layout.addWidget(pupil_hint)
        pupil_layout.addStretch()
        content_layout.addWidget(pupil_task)
        rank_task = Card(object_name="softCard"); rank_layout = QHBoxLayout(rank_task); set_margins(rank_layout, 16, 14, 16, 14)
        self.rank_enabled = CheckBox("自动斗法")
        self.rank_enabled.setChecked(config.get("autoRankBattle", "false").lower() == "true")
        self.rank_ticket_label = QLabel("（挑战状：0 张）"); self.rank_ticket_label.setObjectName("muted")
        rank_info = ToolButton(); rank_info.setIcon(FIF.INFO.icon(color=QColor("#7d8b90"))); rank_info.setFixedSize(28, 28)
        rank_info.setToolTip("有挑战状时自动挑战妖力最低的可用对手；没有挑战状时继续等待砍树掉落。")
        rank_layout.addWidget(self.rank_enabled); rank_layout.addWidget(self.rank_ticket_label); rank_layout.addWidget(rank_info); rank_layout.addStretch()
        content_layout.addWidget(rank_task)
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
        content_layout.addWidget(wild_boss_task)
        limited_task = Card(object_name="softCard")
        limited_layout = QGridLayout(limited_task); set_margins(limited_layout, 16, 12, 16, 12)
        limited_layout.setHorizontalSpacing(12); limited_layout.setVerticalSpacing(8)
        limited_title = QLabel("日常挑战"); limited_title.setObjectName("taskGroupTitle")
        limited_layout.addWidget(limited_title, 0, 0, 1, 4)
        self.invade_enabled, self.invade_count, self.invade_remaining_label = self._add_limited_task_row(
            limited_layout, 1, "异兽入侵", 5, config.get("autoInvade", "false"), config.get("invadeCount", "5"),
            "今日剩余 --/5 次",
        )
        self.star_trial_enabled, self.star_trial_count, self.star_trial_remaining_label = self._add_limited_task_row(
            limited_layout, 2, "星宿试炼", 30, config.get("autoStarTrial", "false"), config.get("starTrialCount", "30"),
            "今日剩余 --/30 次",
        )
        self.hero_rank_enabled, self.hero_rank_count, self.hero_rank_remaining_label = self._add_limited_task_row(
            limited_layout, 3, "群英榜", 10, config.get("autoHeroRank", "false"), config.get("heroRankCount", "10"),
            "当前体力 --/10",
        )
        self.destiny_travel_enabled, self.destiny_travel_count, self.destiny_travel_remaining_label = self._add_limited_task_row(
            limited_layout, 4, "仙友游历", DESTINY_TRAVEL_COUNT_MAX,
            config.get("autoDestinyTravel", "false"), config.get("destinyTravelCount", "10"),
            "当前体力 --",
        )
        content_layout.addWidget(limited_task)

        profession_task = Card(object_name="softCard")
        profession_layout = QGridLayout(profession_task); set_margins(profession_layout, 16, 12, 16, 12)
        profession_layout.setHorizontalSpacing(12); profession_layout.setVerticalSpacing(8)
        profession_title = QLabel("道途试炼"); profession_title.setObjectName("taskGroupTitle")
        profession_layout.addWidget(profession_title, 0, 0, 1, 4)
        self.profession_quick_enabled = CheckBox("道途试炼速战")
        self.profession_quick_enabled.setChecked(config.get("autoProfessionQuick", "false").lower() == "true")
        self.profession_quick_remaining_label = QLabel("今日剩余 --/1 次")
        self.profession_quick_remaining_label.setObjectName("muted")
        profession_layout.addWidget(self.profession_quick_enabled, 1, 0)
        profession_layout.addWidget(QLabel("速战上一关"), 1, 1)
        profession_layout.addWidget(QLabel("每日 1 次"), 1, 2)
        profession_layout.addWidget(self.profession_quick_remaining_label, 1, 3)
        self.profession_challenge_enabled, self.profession_challenge_count, self.profession_challenge_remaining_label = self._add_limited_task_row(
            profession_layout, 2, "道途试炼挑战", PROFESSION_CHALLENGE_DAILY_MAX,
            config.get("autoProfessionChallenge", "false"), config.get("professionChallengeCount", "30"),
            "今日剩余 --/30 次",
        )
        content_layout.addWidget(profession_task)

        yard_task = Card(object_name="softCard")
        yard_layout = QGridLayout(yard_task); set_margins(yard_layout, 16, 12, 16, 12)
        yard_layout.setHorizontalSpacing(12); yard_layout.setVerticalSpacing(8)
        yard_title = QLabel("仙居"); yard_title.setObjectName("taskGroupTitle")
        yard_layout.addWidget(yard_title, 0, 0, 1, 4)
        self.yard_daily_enabled = CheckBox("仙居日常")
        self.yard_daily_enabled.setChecked(config.get("autoYardDaily", "false").lower() == "true")
        yard_daily_desc = QLabel("收桃、收菜、炼丹、化外灵池")
        yard_daily_desc.setObjectName("muted")
        yard_layout.addWidget(self.yard_daily_enabled, 1, 0)
        yard_layout.addWidget(yard_daily_desc, 1, 1, 1, 3)
        self.yard_draw_enabled, self.yard_draw_count, self.yard_draw_remaining_label = self._add_limited_task_row(
            yard_layout, 2, "仙居造物", 100,
            config.get("autoYardDraw", "false"), config.get("yardDrawCount", "1"),
            "优先使用普通免费及 2 次广告免费",
        )
        content_layout.addWidget(yard_task)

        homeland_task = Card(object_name="softCard")
        homeland_layout = QGridLayout(homeland_task); set_margins(homeland_layout, 16, 12, 16, 12)
        homeland_layout.setHorizontalSpacing(12); homeland_layout.setVerticalSpacing(8)
        homeland_title = QLabel("福地"); homeland_title.setObjectName("taskGroupTitle")
        homeland_layout.addWidget(homeland_title, 0, 0, 1, 6)
        self.homeland_enabled = CheckBox("鼠宝采集")
        self.homeland_enabled.setChecked(config.get("autoHomeland", "false").lower() == "true")
        self.homeland_resource_ids = list(HOMELAND_RESOURCE_NAMES)
        self.homeland_resource = ComboBox()
        self.homeland_resource.addItems([
            HOMELAND_RESOURCE_NAMES[item_id] for item_id in self.homeland_resource_ids
        ])
        try:
            saved_item_id = int(config.get("homelandPreferredItem", "100004"))
            resource_index = self.homeland_resource_ids.index(saved_item_id)
        except (TypeError, ValueError):
            resource_index = 0
        self.homeland_resource.setCurrentIndex(resource_index)
        self.homeland_level = ComboBox()
        self.homeland_level.addItems([f"{level} 级" for level in range(1, 6)])
        try:
            saved_level = int(config.get("homelandPreferredLevel", "3"))
        except (TypeError, ValueError):
            saved_level = 3
        self.homeland_level.setCurrentIndex(max(1, min(5, saved_level)) - 1)
        homeland_hint = QLabel("先领取已完成采集，再派出全部空闲鼠宝；探寻刷新遵守冷却")
        homeland_hint.setObjectName("muted")
        homeland_layout.addWidget(self.homeland_enabled, 1, 0)
        homeland_layout.addWidget(QLabel("优先资源"), 1, 1)
        homeland_layout.addWidget(self.homeland_resource, 1, 2)
        homeland_layout.addWidget(QLabel("优先等级"), 1, 3)
        homeland_layout.addWidget(self.homeland_level, 1, 4)
        homeland_layout.addWidget(homeland_hint, 2, 0, 1, 6)
        homeland_layout.setColumnStretch(5, 1)
        content_layout.addWidget(homeland_task)

        talent_task = Card(object_name="softCard")
        talent_layout = QGridLayout(talent_task); set_margins(talent_layout, 16, 12, 16, 12)
        talent_layout.setHorizontalSpacing(12); talent_layout.setVerticalSpacing(8)
        talent_title = QLabel("灵脉"); talent_title.setObjectName("taskGroupTitle")
        talent_layout.addWidget(talent_title, 0, 0, 1, 6)
        self.talent_enabled = CheckBox("激发灵脉")
        self.talent_enabled.setChecked(config.get("autoTalent", "false").lower() == "true")
        self.talent_draw_count = SpinBox(); self.talent_draw_count.setRange(1, 5)
        try:
            saved_talent_count = int(config.get("talentDrawCount", "3"))
        except (TypeError, ValueError):
            saved_talent_count = 3
        self.talent_draw_count.setValue(max(1, min(5, saved_talent_count)))
        self.talent_total_count = ComboBox()
        self.talent_total_count.addItems(["无限次"] + [f"{value} 次" for value in range(1, 1001)])
        saved_talent_total = config.get("talentTotalCount", "unlimited")
        try:
            talent_total_index = 0 if saved_talent_total == "unlimited" else int(saved_talent_total)
        except (TypeError, ValueError):
            talent_total_index = 0
        self.talent_total_count.setCurrentIndex(max(0, min(1000, talent_total_index)))
        self.talent_draw_interval = DoubleSpinBox()
        self.talent_draw_interval.setRange(0.5, 60.0)
        self.talent_draw_interval.setSingleStep(0.5)
        try:
            saved_talent_interval = float(config.get("talentDrawInterval", "2.0"))
        except (TypeError, ValueError):
            saved_talent_interval = 2.0
        self.talent_draw_interval.setValue(max(0.5, min(60.0, saved_talent_interval)))
        self.talent_quality = ComboBox()
        self.talent_quality.addItems([f"{quality} 级" for quality in range(1, 11)])
        try:
            saved_quality = int(config.get("talentMinimumQuality", "5"))
        except (TypeError, ValueError):
            saved_quality = 5
        self.talent_quality.setCurrentIndex(max(1, min(10, saved_quality)) - 1)
        self.talent_attribute_values = list(range(1, 17))
        self.talent_attribute = ComboBox()
        self.talent_attribute.addItems([
            ATTRIBUTE_NAMES[attr_type] for attr_type in self.talent_attribute_values
        ])
        try:
            saved_attribute = int(config.get("talentPreferredAttribute", "5"))
            talent_attribute_index = self.talent_attribute_values.index(saved_attribute)
        except (TypeError, ValueError):
            talent_attribute_index = 0
        self.talent_attribute.setCurrentIndex(talent_attribute_index)
        talent_hint = QLabel("有万年灵芝时先开悟；达到最低等级且包含目标属性才激活")
        talent_hint.setObjectName("muted")
        self.talent_grass_label = QLabel("灵草：--"); self.talent_grass_label.setObjectName("muted")
        talent_layout.addWidget(self.talent_enabled, 1, 0)
        talent_layout.addWidget(QLabel("最低等级"), 1, 1)
        talent_layout.addWidget(self.talent_quality, 1, 2)
        talent_layout.addWidget(QLabel("目标属性"), 1, 3)
        talent_layout.addWidget(self.talent_attribute, 1, 4)
        talent_layout.addWidget(self.talent_grass_label, 1, 5)
        talent_layout.addWidget(QLabel("同时次数"), 2, 1)
        talent_layout.addWidget(self.talent_draw_count, 2, 2)
        talent_layout.addWidget(QLabel("间隔(秒)"), 2, 3)
        talent_layout.addWidget(self.talent_draw_interval, 2, 4)
        talent_layout.addWidget(QLabel("总次数"), 3, 1)
        talent_layout.addWidget(self.talent_total_count, 3, 2)
        talent_layout.addWidget(talent_hint, 4, 0, 1, 6)
        talent_layout.setColumnStretch(5, 1)
        content_layout.addWidget(talent_task)

        tower_task = Card(object_name="softCard")
        tower_layout = QGridLayout(tower_task); set_margins(tower_layout, 16, 12, 16, 12)
        tower_layout.setHorizontalSpacing(12); tower_layout.setVerticalSpacing(8)
        self.tower_enabled = CheckBox("镇妖塔")
        self.tower_enabled.setChecked(config.get("autoTower", "false").lower() == "true")
        self.tower_count = ComboBox(); self.tower_count.addItems([f"{value} 次" for value in range(101)])
        try:
            saved_tower_count = int(config.get("towerChallengeCount", "10"))
        except (TypeError, ValueError):
            saved_tower_count = 10
        self.tower_count.setCurrentIndex(max(0, min(100, saved_tower_count)))
        self.tower_preference_enabled = CheckBox("启用加成偏好")
        self.tower_preference_enabled.setChecked(config.get("towerUsePreference", "true").lower() == "true")
        self.tower_remaining_label = QLabel("当前关卡 -- / 最高 --"); self.tower_remaining_label.setObjectName("muted")
        tower_hint = QLabel("偏好：最终增伤、最终减伤、强化灵兽、弱化灵兽、弱化治疗")
        tower_hint.setObjectName("muted")
        tower_layout.addWidget(self.tower_enabled, 0, 0)
        tower_layout.addWidget(QLabel("继续挑战"), 0, 1); tower_layout.addWidget(self.tower_count, 0, 2)
        tower_layout.addWidget(self.tower_preference_enabled, 0, 3)
        tower_layout.addWidget(self.tower_remaining_label, 0, 4)
        tower_layout.addWidget(tower_hint, 1, 1, 1, 4); tower_layout.setColumnStretch(5, 1)
        content_layout.addWidget(tower_task)

        adventure_task = Card(object_name="softCard")
        adventure_layout = QGridLayout(adventure_task); set_margins(adventure_layout, 16, 12, 16, 12)
        adventure_layout.setHorizontalSpacing(12)
        self.adventure_enabled = CheckBox("冒险")
        self.adventure_enabled.setChecked(config.get("autoAdventure", "false").lower() == "true")
        self.adventure_count = ComboBox()
        self.adventure_count.addItems(["无限次"] + [f"{value} 次" for value in range(1, 1001)])
        saved_adventure_count = config.get("adventureCount", "unlimited")
        try:
            adventure_count_index = 0 if saved_adventure_count == "unlimited" else int(saved_adventure_count)
        except (TypeError, ValueError):
            adventure_count_index = 0
        self.adventure_count.setCurrentIndex(max(0, min(1000, adventure_count_index)))
        self.adventure_stage_label = QLabel("当前关卡 --"); self.adventure_stage_label.setObjectName("muted")
        adventure_layout.addWidget(self.adventure_enabled, 0, 0)
        adventure_layout.addWidget(QLabel("挑战次数"), 0, 1); adventure_layout.addWidget(self.adventure_count, 0, 2)
        adventure_layout.addWidget(self.adventure_stage_label, 0, 3); adventure_layout.setColumnStretch(4, 1)
        content_layout.addWidget(adventure_task)

        treasure_auction_task = Card(object_name="softCard")
        treasure_auction_layout = QGridLayout(treasure_auction_task); set_margins(treasure_auction_layout, 16, 12, 16, 12)
        treasure_auction_layout.setHorizontalSpacing(12); treasure_auction_layout.setVerticalSpacing(8)
        self.treasure_auction_enabled = CheckBox("仙途寻宝")
        self.treasure_auction_enabled.setChecked(config.get("autoTreasureAuction", "false").lower() == "true")
        self.treasure_claim_enabled = CheckBox("领取奖励"); self.treasure_claim_enabled.setChecked(config.get("treasureClaimRewards", "true").lower() == "true")
        self.treasure_begin_enabled = CheckBox("有图即寻宝"); self.treasure_begin_enabled.setChecked(config.get("treasureBeginExplores", "true").lower() == "true")
        self.treasure_help_enabled = CheckBox("好友一键协助"); self.treasure_help_enabled.setChecked(config.get("treasureHelpFriends", "true").lower() == "true")
        self.treasure_identify_enabled = CheckBox("自动鉴宝"); self.treasure_identify_enabled.setChecked(config.get("treasureIdentify", "true").lower() == "true")
        self.treasure_disassemble_quality = ComboBox()
        self.treasure_disassemble_quality.addItems(["不自动分解", "尘品及以下", "凡品及以下", "上品及以下"])
        try:
            saved_disassemble_quality = int(config.get("treasureDisassembleQuality", "-1")) + 1
        except (TypeError, ValueError):
            saved_disassemble_quality = 0
        self.treasure_disassemble_quality.setCurrentIndex(max(0, min(3, saved_disassemble_quality)))
        self.treasure_auction_status_label = QLabel("藏宝图 -- 张 · 仙囊 --/-- · 待鉴宝 --")
        self.treasure_auction_status_label.setObjectName("muted")
        treasure_auction_layout.addWidget(self.treasure_auction_enabled, 0, 0)
        treasure_auction_layout.addWidget(self.treasure_claim_enabled, 0, 1)
        treasure_auction_layout.addWidget(self.treasure_begin_enabled, 0, 2)
        treasure_auction_layout.addWidget(self.treasure_help_enabled, 0, 3)
        treasure_auction_layout.addWidget(self.treasure_identify_enabled, 0, 4)
        treasure_auction_layout.addWidget(QLabel("仙囊满时"), 1, 1)
        treasure_auction_layout.addWidget(self.treasure_disassemble_quality, 1, 2)
        treasure_auction_layout.addWidget(self.treasure_auction_status_label, 1, 3, 1, 2)
        treasure_auction_layout.setColumnStretch(5, 1)
        content_layout.addWidget(treasure_auction_task)

        divine_mind_task = Card(object_name="softCard")
        divine_mind_layout = QGridLayout(divine_mind_task); set_margins(divine_mind_layout, 16, 12, 16, 12)
        divine_mind_layout.setHorizontalSpacing(12)
        self.divine_mind_enabled = CheckBox("神躯 - 气海丹田")
        self.divine_mind_enabled.setChecked(config.get("autoDivineMindCollection", "false").lower() == "true")
        self.divine_mind_interval = SpinBox(); self.divine_mind_interval.setRange(1, 1440)
        try:
            saved_divine_mind_interval = int(config.get("divineMindIntervalMinutes", "60"))
        except (TypeError, ValueError):
            saved_divine_mind_interval = 60
        self.divine_mind_interval.setValue(max(1, min(1440, saved_divine_mind_interval)))
        self.divine_mind_status_label = QLabel("等待收集"); self.divine_mind_status_label.setObjectName("muted")
        divine_mind_layout.addWidget(self.divine_mind_enabled, 0, 0)
        divine_mind_layout.addWidget(QLabel("收集间隔（分钟）"), 0, 1)
        divine_mind_layout.addWidget(self.divine_mind_interval, 0, 2)
        divine_mind_layout.addWidget(self.divine_mind_status_label, 0, 3); divine_mind_layout.setColumnStretch(4, 1)
        content_layout.addWidget(divine_mind_task)

        magic_task = Card(object_name="softCard")
        magic_layout = QGridLayout(magic_task); set_margins(magic_layout, 16, 12, 16, 12)
        magic_layout.setHorizontalSpacing(12); magic_layout.setVerticalSpacing(8)
        self.magic_draw_enabled = CheckBox("获取神通")
        self.magic_draw_enabled.setChecked(config.get("autoMagicDraw", "false").lower() == "true")
        self.magic_draw_count = ComboBox(); self.magic_draw_count.addItems([f"{value} 次" for value in range(4)])
        try:
            saved_magic_count = int(config.get("magicDrawCount", "2"))
        except (TypeError, ValueError):
            saved_magic_count = 2
        self.magic_draw_count.setCurrentIndex(max(0, min(3, saved_magic_count)))
        self.magic_paid_count = ComboBox(); self.magic_paid_count.addItems([f"{value} 次" for value in range(101)])
        try:
            saved_magic_paid = int(config.get("magicPaidDrawCount", "0"))
        except (TypeError, ValueError):
            saved_magic_paid = 0
        self.magic_paid_count.setCurrentIndex(max(0, min(100, saved_magic_paid)))
        self.magic_free_label = QLabel("免费可用 --/3 次"); self.magic_free_label.setObjectName("muted")
        self.magic_ticket_label = QLabel("天衍令可用 -- 次"); self.magic_ticket_label.setObjectName("muted")
        magic_layout.addWidget(self.magic_draw_enabled, 0, 0)
        magic_layout.addWidget(QLabel("免费选择"), 0, 1); magic_layout.addWidget(self.magic_draw_count, 0, 2)
        magic_layout.addWidget(self.magic_free_label, 0, 3)
        magic_layout.addWidget(QLabel("消耗选择"), 1, 1); magic_layout.addWidget(self.magic_paid_count, 1, 2)
        magic_layout.addWidget(self.magic_ticket_label, 1, 3); magic_layout.setColumnStretch(4, 1)
        content_layout.addWidget(magic_task)

        spirit_task = Card(object_name="softCard")
        spirit_layout = QGridLayout(spirit_task); set_margins(spirit_layout, 16, 12, 16, 12)
        spirit_layout.setHorizontalSpacing(12); spirit_layout.setVerticalSpacing(8)
        self.spirit_draw_enabled = CheckBox("召唤精怪")
        self.spirit_draw_enabled.setChecked(config.get("autoSpiritDraw", "false").lower() == "true")
        self.spirit_draw_count = ComboBox(); self.spirit_draw_count.addItems(["0 次", "1 次", "2 次"])
        try:
            saved_spirit_count = int(config.get("spiritDrawCount", "2"))
        except (TypeError, ValueError):
            saved_spirit_count = 2
        self.spirit_draw_count.setCurrentIndex(max(0, min(2, saved_spirit_count)))
        self.spirit_paid_count = ComboBox(); self.spirit_paid_count.addItems([f"{value} 次" for value in range(101)])
        try:
            saved_spirit_paid = int(config.get("spiritPaidDrawCount", "0"))
        except (TypeError, ValueError):
            saved_spirit_paid = 0
        self.spirit_paid_count.setCurrentIndex(max(0, min(100, saved_spirit_paid)))
        self.spirit_remaining_label = QLabel("免费可用 --/2 次")
        self.spirit_remaining_label.setObjectName("muted")
        self.spirit_ticket_label = QLabel("召唤令可用 -- 次"); self.spirit_ticket_label.setObjectName("muted")
        spirit_layout.addWidget(self.spirit_draw_enabled, 0, 0)
        spirit_layout.addWidget(QLabel("免费选择"), 0, 1); spirit_layout.addWidget(self.spirit_draw_count, 0, 2)
        spirit_layout.addWidget(self.spirit_remaining_label, 0, 3)
        spirit_layout.addWidget(QLabel("消耗选择"), 1, 1); spirit_layout.addWidget(self.spirit_paid_count, 1, 2)
        spirit_layout.addWidget(self.spirit_ticket_label, 1, 3); spirit_layout.setColumnStretch(4, 1)
        content_layout.addWidget(spirit_task)

        law_looks_task = Card(object_name="softCard")
        law_looks_layout = QGridLayout(law_looks_task); set_margins(law_looks_layout, 16, 12, 16, 12)
        law_looks_layout.setHorizontalSpacing(12); law_looks_layout.setVerticalSpacing(8)
        self.law_looks_draw_enabled = CheckBox("召唤法象")
        self.law_looks_draw_enabled.setChecked(config.get("autoLawLooksDraw", "false").lower() == "true")
        self.law_looks_draw_count = ComboBox(); self.law_looks_draw_count.addItems(["0 次", "1 次", "2 次"])
        self.law_looks_paid_count = ComboBox(); self.law_looks_paid_count.addItems([f"{value} 次" for value in range(101)])
        try:
            saved_law_looks_count = int(config.get("lawLooksDrawCount", "2"))
            saved_law_looks_paid = int(config.get("lawLooksPaidDrawCount", "0"))
        except (TypeError, ValueError):
            saved_law_looks_count, saved_law_looks_paid = 2, 0
        self.law_looks_draw_count.setCurrentIndex(max(0, min(2, saved_law_looks_count)))
        self.law_looks_paid_count.setCurrentIndex(max(0, min(100, saved_law_looks_paid)))
        self.law_looks_remaining_label = QLabel("免费可用 --/2 次"); self.law_looks_remaining_label.setObjectName("muted")
        self.law_looks_ticket_label = QLabel("引灵灯可用 -- 次"); self.law_looks_ticket_label.setObjectName("muted")
        law_looks_layout.addWidget(self.law_looks_draw_enabled, 0, 0)
        law_looks_layout.addWidget(QLabel("免费选择"), 0, 1); law_looks_layout.addWidget(self.law_looks_draw_count, 0, 2)
        law_looks_layout.addWidget(self.law_looks_remaining_label, 0, 3)
        law_looks_layout.addWidget(QLabel("消耗选择"), 1, 1); law_looks_layout.addWidget(self.law_looks_paid_count, 1, 2)
        law_looks_layout.addWidget(self.law_looks_ticket_label, 1, 3); law_looks_layout.setColumnStretch(4, 1)
        content_layout.addWidget(law_looks_task)

        pet_kernel_task = Card(object_name="softCard")
        pet_kernel_layout = QGridLayout(pet_kernel_task); set_margins(pet_kernel_layout, 16, 12, 16, 12)
        pet_kernel_layout.setHorizontalSpacing(12); pet_kernel_layout.setVerticalSpacing(8)
        self.pet_kernel_draw_enabled = CheckBox("凝聚内丹")
        self.pet_kernel_draw_enabled.setChecked(config.get("autoPetKernelDraw", "false").lower() == "true")
        self.pet_kernel_draw_count = ComboBox(); self.pet_kernel_draw_count.addItems(["0 次", "1 次", "2 次"])
        self.pet_kernel_paid_count = ComboBox(); self.pet_kernel_paid_count.addItems([f"{value} 次" for value in range(101)])
        try:
            saved_pet_kernel_count = int(config.get("petKernelDrawCount", "2"))
            saved_pet_kernel_paid = int(config.get("petKernelPaidDrawCount", "0"))
        except (TypeError, ValueError):
            saved_pet_kernel_count, saved_pet_kernel_paid = 2, 0
        self.pet_kernel_draw_count.setCurrentIndex(max(0, min(2, saved_pet_kernel_count)))
        self.pet_kernel_paid_count.setCurrentIndex(max(0, min(100, saved_pet_kernel_paid)))
        self.pet_kernel_remaining_label = QLabel("免费可用 --/2 次"); self.pet_kernel_remaining_label.setObjectName("muted")
        self.pet_kernel_item_label = QLabel("本源丹可用 -- 次"); self.pet_kernel_item_label.setObjectName("muted")
        pet_kernel_layout.addWidget(self.pet_kernel_draw_enabled, 0, 0)
        pet_kernel_layout.addWidget(QLabel("免费选择"), 0, 1); pet_kernel_layout.addWidget(self.pet_kernel_draw_count, 0, 2)
        pet_kernel_layout.addWidget(self.pet_kernel_remaining_label, 0, 3)
        pet_kernel_layout.addWidget(QLabel("消耗选择"), 1, 1); pet_kernel_layout.addWidget(self.pet_kernel_paid_count, 1, 2)
        pet_kernel_layout.addWidget(self.pet_kernel_item_label, 1, 3); pet_kernel_layout.setColumnStretch(4, 1)
        content_layout.addWidget(pet_kernel_task)

        universe_skill_task = Card(object_name="softCard")
        universe_skill_layout = QGridLayout(universe_skill_task); set_margins(universe_skill_layout, 16, 12, 16, 12)
        universe_skill_layout.setHorizontalSpacing(12); universe_skill_layout.setVerticalSpacing(8)
        self.universe_skill_draw_enabled = CheckBox("山海途 - 洞悉天机")
        self.universe_skill_draw_enabled.setChecked(config.get("autoUniverseSkillDraw", "false").lower() == "true")
        self.universe_skill_draw_count = ComboBox(); self.universe_skill_draw_count.addItems(["0 次", "1 次", "2 次"])
        self.universe_skill_paid_count = ComboBox(); self.universe_skill_paid_count.addItems([f"{value} 次" for value in range(101)])
        try:
            saved_universe_skill_count = int(config.get("universeSkillDrawCount", "2"))
            saved_universe_skill_paid = int(config.get("universeSkillPaidDrawCount", "0"))
        except (TypeError, ValueError):
            saved_universe_skill_count, saved_universe_skill_paid = 2, 0
        self.universe_skill_draw_count.setCurrentIndex(max(0, min(2, saved_universe_skill_count)))
        self.universe_skill_paid_count.setCurrentIndex(max(0, min(100, saved_universe_skill_paid)))
        self.universe_skill_remaining_label = QLabel("免费可用 --/2 次"); self.universe_skill_remaining_label.setObjectName("muted")
        self.universe_skill_item_label = QLabel("太虚元石可用 -- 次"); self.universe_skill_item_label.setObjectName("muted")
        universe_skill_layout.addWidget(self.universe_skill_draw_enabled, 0, 0)
        universe_skill_layout.addWidget(QLabel("免费选择"), 0, 1); universe_skill_layout.addWidget(self.universe_skill_draw_count, 0, 2)
        universe_skill_layout.addWidget(self.universe_skill_remaining_label, 0, 3)
        universe_skill_layout.addWidget(QLabel("消耗选择"), 1, 1); universe_skill_layout.addWidget(self.universe_skill_paid_count, 1, 2)
        universe_skill_layout.addWidget(self.universe_skill_item_label, 1, 3); universe_skill_layout.setColumnStretch(4, 1)
        content_layout.addWidget(universe_skill_task)

        universe_wheel_task = Card(object_name="softCard")
        universe_wheel_layout = QGridLayout(universe_wheel_task); set_margins(universe_wheel_layout, 16, 12, 16, 12)
        universe_wheel_layout.setHorizontalSpacing(12)
        self.universe_wheel_draw_enabled = CheckBox("天道轮台 - 衍取")
        self.universe_wheel_draw_enabled.setChecked(config.get("autoUniverseWheelDraw", "false").lower() == "true")
        self.universe_wheel_draw_count = ComboBox(); self.universe_wheel_draw_count.addItems([f"{value} 次" for value in range(101)])
        try:
            saved_universe_wheel_count = int(config.get("universeWheelDrawCount", "0"))
        except (TypeError, ValueError):
            saved_universe_wheel_count = 0
        self.universe_wheel_draw_count.setCurrentIndex(max(0, min(100, saved_universe_wheel_count)))
        self.universe_stone_label = QLabel("造化石可用 -- 次"); self.universe_stone_label.setObjectName("muted")
        universe_wheel_layout.addWidget(self.universe_wheel_draw_enabled, 0, 0)
        universe_wheel_layout.addWidget(QLabel("衍取次数"), 0, 1); universe_wheel_layout.addWidget(self.universe_wheel_draw_count, 0, 2)
        universe_wheel_layout.addWidget(self.universe_stone_label, 0, 3); universe_wheel_layout.setColumnStretch(4, 1)
        content_layout.addWidget(universe_wheel_task)

        treasure_task = Card(object_name="softCard")
        treasure_layout = QGridLayout(treasure_task); set_margins(treasure_layout, 16, 12, 16, 12)
        treasure_layout.setHorizontalSpacing(12); treasure_layout.setVerticalSpacing(8)
        self.magic_treasure_enabled = CheckBox("法宝寻宝")
        self.magic_treasure_enabled.setChecked(config.get("autoMagicTreasure", "false").lower() == "true")
        treasure_layout.addWidget(self.magic_treasure_enabled, 0, 0)
        treasure_layout.addWidget(QLabel("免费选择"), 0, 2)
        treasure_layout.addWidget(QLabel("免费可用"), 0, 4)
        treasure_layout.addWidget(QLabel("消耗选择"), 0, 5)
        treasure_layout.addWidget(QLabel("灵盘可用"), 0, 7)
        self.magic_treasure_free_counts = {}
        self.magic_treasure_paid_counts = {}
        self.magic_treasure_free_labels = {}
        self.magic_treasure_compass_labels = {}
        for row, (pool_id, pool_name) in enumerate(((1, "灵瀚仙界"), (2, "神遗灵界"), (3, "缥缈凡界")), 1):
            free_count = ComboBox(); free_count.addItems(["0 次", "1 次", "2 次"])
            paid_count = ComboBox(); paid_count.addItems([f"{value} 次" for value in range(101)])
            try:
                saved_free = int(config.get(f"magicTreasure{pool_id}FreeCount", "2"))
                saved_paid = int(config.get(f"magicTreasure{pool_id}PaidCount", "0"))
            except (TypeError, ValueError):
                saved_free, saved_paid = 2, 0
            free_count.setCurrentIndex(max(0, min(2, saved_free)))
            paid_count.setCurrentIndex(max(0, min(100, saved_paid)))
            free_label = QLabel("--/2 次"); free_label.setObjectName("muted")
            compass_label = QLabel("-- 个"); compass_label.setObjectName("muted")
            self.magic_treasure_free_counts[pool_id] = free_count
            self.magic_treasure_paid_counts[pool_id] = paid_count
            self.magic_treasure_free_labels[pool_id] = free_label
            self.magic_treasure_compass_labels[pool_id] = compass_label
            treasure_layout.addWidget(QLabel(pool_name), row, 1)
            treasure_layout.addWidget(free_count, row, 2)
            treasure_layout.addWidget(free_label, row, 4)
            treasure_layout.addWidget(paid_count, row, 5)
            treasure_layout.addWidget(compass_label, row, 7)
        treasure_layout.setColumnStretch(8, 1)
        content_layout.addWidget(treasure_task)
        content_layout.addStretch()

        self.task_checkboxes = [
            self.chop_enabled,
            self.pupil_training_enabled,
            self.rank_enabled,
            self.wild_boss_enabled,
            self.invade_enabled,
            self.star_trial_enabled,
            self.hero_rank_enabled,
            self.destiny_travel_enabled,
            self.profession_quick_enabled,
            self.profession_challenge_enabled,
            self.yard_daily_enabled,
            self.yard_draw_enabled,
            self.homeland_enabled,
            self.talent_enabled,
            self.tower_enabled,
            self.adventure_enabled,
            self.treasure_auction_enabled,
            self.divine_mind_enabled,
            self.magic_draw_enabled,
            self.spirit_draw_enabled,
            self.law_looks_draw_enabled,
            self.pet_kernel_draw_enabled,
            self.universe_skill_draw_enabled,
            self.universe_wheel_draw_enabled,
            self.magic_treasure_enabled,
        ]
        for checkbox in self.task_checkboxes:
            checkbox.toggled.connect(self._sync_select_all_tasks)
        self._sync_select_all_tasks()
        return panel

    def _set_all_tasks(self, checked: bool) -> None:
        for checkbox in self.task_checkboxes:
            checkbox.setChecked(checked)

    def _sync_select_all_tasks(self, _checked: bool | None = None) -> None:
        all_checked = bool(self.task_checkboxes) and all(
            checkbox.isChecked() for checkbox in self.task_checkboxes
        )
        self.select_all_tasks.blockSignals(True)
        self.select_all_tasks.setChecked(all_checked)
        self.select_all_tasks.blockSignals(False)

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
        self.log_text = QPlainTextEdit(); self.log_text.setReadOnly(True); self.log_text.setFont(QFont(UI_FONT_FAMILY, 9)); layout.addWidget(self.log_text)
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
                self._emit_event("profile_snapshot", fetch_role_snapshot(selected_server, OUTPUT_DIR))
            except (OSError, ValueError, KeyError, RuntimeError, websocket.WebSocketException) as exc:
                self._emit_event("profile_error", f"{type(exc).__name__}: {exc}")

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
                self._emit_event("dashboard", (path, roles))
            except Exception as exc: self._emit_event("cached_invalid", str(exc))
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
            stream = io.BytesIO(); image.save(stream, format="PNG"); self._emit_event("qr", stream.getvalue())
            while not stop_event.wait(POLL_INTERVAL):
                payload = request_json(session, f"{BASE_URL}{SERVICE}/loginForPc?{query}", {"token": login_token, "userAgent": DEFAULT_UA}, 15)
                save_json(OUTPUT_DIR, "login-last-response.json", payload); state = classify(payload)
                if state == "success":
                    path = save_json(OUTPUT_DIR, "login-success.json", payload); token = str(payload["data"]["token"]); update_config(sessionToken=token)
                    game_data = fetch_game_data(token, config["ctoken"], OUTPUT_DIR); roles = fetch_roles(game_data["auth"]["data"]["authCode"], OUTPUT_DIR)
                    self._emit_event("dashboard", (path, roles)); return
                if state in ("expired", "failed"): self._emit_event(state, payload); return
                self._emit_event("status", "等待扫码确认…")
        except Exception as exc:
            if not stop_event.is_set(): self._emit_event("error", str(exc))

    def start_chop(self) -> None:
        if not self.current_role:
            return
        run_chop = self.chop_enabled.isChecked()
        run_wild_boss = self.wild_boss_enabled.isChecked()
        run_invade = self.invade_enabled.isChecked()
        run_star_trial = self.star_trial_enabled.isChecked()
        run_hero_rank = self.hero_rank_enabled.isChecked()
        run_destiny_travel = self.destiny_travel_enabled.isChecked()
        run_profession_quick = self.profession_quick_enabled.isChecked()
        run_profession_challenge = self.profession_challenge_enabled.isChecked()
        run_yard_daily = self.yard_daily_enabled.isChecked()
        run_yard_draw = self.yard_draw_enabled.isChecked()
        run_homeland = self.homeland_enabled.isChecked()
        run_talent = self.talent_enabled.isChecked()
        run_tower = self.tower_enabled.isChecked()
        run_adventure = self.adventure_enabled.isChecked()
        run_treasure_auction = self.treasure_auction_enabled.isChecked()
        run_divine_mind = self.divine_mind_enabled.isChecked()
        run_magic_draw = self.magic_draw_enabled.isChecked()
        run_spirit_draw = self.spirit_draw_enabled.isChecked()
        run_law_looks_draw = self.law_looks_draw_enabled.isChecked()
        run_pet_kernel_draw = self.pet_kernel_draw_enabled.isChecked()
        run_universe_skill_draw = self.universe_skill_draw_enabled.isChecked()
        run_universe_wheel_draw = self.universe_wheel_draw_enabled.isChecked()
        run_magic_treasure = self.magic_treasure_enabled.isChecked()
        run_pupil_training = self.pupil_training_enabled.isChecked()
        if not any((
            run_chop, run_wild_boss, run_invade, run_star_trial, run_hero_rank,
            run_destiny_travel, run_profession_quick, run_profession_challenge,
            run_yard_daily, run_yard_draw, run_homeland, run_talent, run_tower, run_adventure,
            run_treasure_auction,
            run_divine_mind,
            run_magic_draw, run_spirit_draw, run_law_looks_draw, run_pet_kernel_draw,
            run_universe_skill_draw, run_universe_wheel_draw,
            run_magic_treasure, run_pupil_training,
        )):
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
            autoDestinyTravel=run_destiny_travel,
            destinyTravelCount=self.destiny_travel_count.currentIndex() + 1,
            autoProfessionQuick=run_profession_quick,
            autoProfessionChallenge=run_profession_challenge,
            professionChallengeCount=self.profession_challenge_count.currentIndex() + 1,
            autoYardDaily=run_yard_daily, autoYardDraw=run_yard_draw,
            yardDrawCount=self.yard_draw_count.currentIndex() + 1,
            autoHomeland=run_homeland,
            homelandPreferredItem=self.homeland_resource_ids[self.homeland_resource.currentIndex()],
            homelandPreferredLevel=self.homeland_level.currentIndex() + 1,
            autoTalent=run_talent,
            talentDrawCount=self.talent_draw_count.value(),
            talentTotalCount=(
                "unlimited" if self.talent_total_count.currentIndex() == 0
                else self.talent_total_count.currentIndex()
            ),
            talentDrawInterval=self.talent_draw_interval.value(),
            talentMinimumQuality=self.talent_quality.currentIndex() + 1,
            talentPreferredAttribute=self.talent_attribute_values[self.talent_attribute.currentIndex()],
            autoTower=run_tower,
            towerChallengeCount=self.tower_count.currentIndex(),
            towerUsePreference=self.tower_preference_enabled.isChecked(),
            autoAdventure=run_adventure,
            adventureCount=(
                "unlimited" if self.adventure_count.currentIndex() == 0
                else self.adventure_count.currentIndex()
            ),
            autoTreasureAuction=run_treasure_auction,
            treasureClaimRewards=self.treasure_claim_enabled.isChecked(),
            treasureBeginExplores=self.treasure_begin_enabled.isChecked(),
            treasureHelpFriends=self.treasure_help_enabled.isChecked(),
            treasureIdentify=self.treasure_identify_enabled.isChecked(),
            treasureDisassembleQuality=self.treasure_disassemble_quality.currentIndex() - 1,
            autoDivineMindCollection=run_divine_mind,
            divineMindIntervalMinutes=self.divine_mind_interval.value(),
            autoMagicDraw=run_magic_draw,
            magicDrawCount=self.magic_draw_count.currentIndex(),
            magicPaidDrawCount=self.magic_paid_count.currentIndex(),
            autoSpiritDraw=run_spirit_draw,
            spiritDrawCount=self.spirit_draw_count.currentIndex(),
            spiritPaidDrawCount=self.spirit_paid_count.currentIndex(),
            autoLawLooksDraw=run_law_looks_draw,
            lawLooksDrawCount=self.law_looks_draw_count.currentIndex(),
            lawLooksPaidDrawCount=self.law_looks_paid_count.currentIndex(),
            autoPetKernelDraw=run_pet_kernel_draw,
            petKernelDrawCount=self.pet_kernel_draw_count.currentIndex(),
            petKernelPaidDrawCount=self.pet_kernel_paid_count.currentIndex(),
            autoUniverseSkillDraw=run_universe_skill_draw,
            universeSkillDrawCount=self.universe_skill_draw_count.currentIndex(),
            universeSkillPaidDrawCount=self.universe_skill_paid_count.currentIndex(),
            autoUniverseWheelDraw=run_universe_wheel_draw,
            universeWheelDrawCount=self.universe_wheel_draw_count.currentIndex(),
            autoMagicTreasure=run_magic_treasure,
            **{
                f"magicTreasure{pool_id}{kind}Count": combos[pool_id].currentIndex()
                for kind, combos in (
                    ("Free", self.magic_treasure_free_counts),
                    ("Paid", self.magic_treasure_paid_counts),
                )
                for pool_id in (1, 2, 3)
            },
            autoPupilTraining=run_pupil_training,
            pupilTrainingRounds=self.pupil_training_rounds.value(),
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
        destiny_travel_count = self.destiny_travel_count.currentIndex() + 1
        profession_challenge_count = self.profession_challenge_count.currentIndex() + 1
        yard_draw_count = self.yard_draw_count.currentIndex() + 1
        homeland_preferred_item = self.homeland_resource_ids[self.homeland_resource.currentIndex()]
        homeland_preferred_level = self.homeland_level.currentIndex() + 1
        talent_minimum_quality = self.talent_quality.currentIndex() + 1
        talent_preferred_attribute = self.talent_attribute_values[self.talent_attribute.currentIndex()]
        talent_draw_count = self.talent_draw_count.value()
        talent_total_count = self.talent_total_count.currentIndex()
        talent_draw_interval = self.talent_draw_interval.value()
        tower_count = self.tower_count.currentIndex()
        tower_use_preference = self.tower_preference_enabled.isChecked()
        adventure_count = self.adventure_count.currentIndex()
        treasure_claim_rewards = self.treasure_claim_enabled.isChecked()
        treasure_begin_explores = self.treasure_begin_enabled.isChecked()
        treasure_help_friends = self.treasure_help_enabled.isChecked()
        treasure_identify = self.treasure_identify_enabled.isChecked()
        treasure_disassemble_quality = self.treasure_disassemble_quality.currentIndex() - 1
        divine_mind_interval = self.divine_mind_interval.value()
        magic_draw_count = self.magic_draw_count.currentIndex()
        magic_paid_count = self.magic_paid_count.currentIndex()
        spirit_draw_count = self.spirit_draw_count.currentIndex()
        spirit_paid_count = self.spirit_paid_count.currentIndex()
        law_looks_draw_count = self.law_looks_draw_count.currentIndex()
        law_looks_paid_count = self.law_looks_paid_count.currentIndex()
        pet_kernel_draw_count = self.pet_kernel_draw_count.currentIndex()
        pet_kernel_paid_count = self.pet_kernel_paid_count.currentIndex()
        universe_skill_draw_count = self.universe_skill_draw_count.currentIndex()
        universe_skill_paid_count = self.universe_skill_paid_count.currentIndex()
        universe_wheel_draw_count = self.universe_wheel_draw_count.currentIndex()
        magic_treasure_free_counts = {
            pool_id: combo.currentIndex() for pool_id, combo in self.magic_treasure_free_counts.items()
        }
        magic_treasure_paid_counts = {
            pool_id: combo.currentIndex() for pool_id, combo in self.magic_treasure_paid_counts.items()
        }
        pupil_training_rounds = self.pupil_training_rounds.value()
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
                collection_thread = None
                if run_divine_mind:
                    def collect_divine_mind() -> None:
                        try:
                            result = run_divine_mind_collection_tasks(
                                int(role["serverId"]), OUTPUT_DIR, 1,
                                lambda msg: self._emit_event("chop_log", msg),
                                self.chop_stop_event,
                                snapshot=lambda value: self._emit_event("profile_snapshot", value),
                                interval_minutes=divine_mind_interval,
                            )
                            result["taskName"] = "神躯 - 气海丹田"
                            self._emit_event("limited_task_result", result)
                        except Exception as exc:
                            self._emit_event("chop_log", f"气海丹田收集失败：{type(exc).__name__}: {exc}")

                    collection_thread = threading.Thread(target=collect_divine_mind, daemon=True)
                    collection_thread.start()
                auxiliary_tasks = [
                    (run_wild_boss, run_wild_boss_tasks, wild_boss_count, "挑战妖王"),
                    (run_invade, run_invade_tasks, invade_count, "异兽入侵"),
                    (run_star_trial, run_star_trial_tasks, star_trial_count, "星宿试炼"),
                    (run_hero_rank, run_hero_rank_tasks, hero_rank_count, "群英榜"),
                    (run_destiny_travel, run_destiny_travel_tasks, destiny_travel_count, "仙友游历"),
                    (run_profession_quick, run_profession_quick_task, 1, "道途试炼速战"),
                    (
                        run_profession_challenge, run_profession_challenge_tasks,
                        profession_challenge_count, "道途试炼挑战",
                    ),
                    (run_yard_daily, run_yard_daily_tasks, 1, "仙居日常"),
                    (run_yard_draw, run_yard_draw_tasks, yard_draw_count, "仙居造物"),
                    (
                        run_homeland,
                        lambda server_id, output_dir, task_count, task_log, stop_event, snapshot: run_homeland_tasks(
                            server_id, output_dir, task_count, task_log, stop_event, snapshot,
                            preferred_item_id=homeland_preferred_item,
                            preferred_level=homeland_preferred_level,
                        ),
                        1, "福地鼠宝采集",
                    ),
                    (
                        run_talent,
                        lambda server_id, output_dir, task_count, task_log, stop_event, snapshot: run_talent_tasks(
                            server_id, output_dir, task_count, task_log, stop_event, snapshot,
                            minimum_quality=talent_minimum_quality,
                            preferred_attribute=talent_preferred_attribute,
                            interval=talent_draw_interval,
                            concurrent_count=talent_draw_count,
                        ),
                        talent_total_count, "灵脉激发",
                    ),
                    (
                        run_tower,
                        lambda server_id, output_dir, task_count, task_log, stop_event, snapshot: run_tower_tasks(
                            server_id, output_dir, task_count, task_log, stop_event, snapshot,
                            use_preferences=tower_use_preference,
                        ),
                        tower_count, "镇妖塔",
                    ),
                    (run_adventure, run_adventure_tasks, adventure_count, "冒险"),
                    (
                        run_treasure_auction,
                        lambda server_id, output_dir, task_count, task_log, stop_event, snapshot: run_treasure_auction_tasks(
                            server_id, output_dir, task_count, task_log, stop_event, snapshot,
                            claim_rewards=treasure_claim_rewards,
                            begin_explores=treasure_begin_explores,
                            help_friends=treasure_help_friends,
                            identify_treasures=treasure_identify,
                            disassemble_quality=treasure_disassemble_quality,
                        ),
                        1, "仙途寻宝",
                    ),
                    (
                        run_magic_draw,
                        lambda server_id, output_dir, task_count, task_log, stop_event, snapshot: run_magic_draw_tasks(
                            server_id, output_dir, task_count, task_log, stop_event, snapshot,
                            paid_count=magic_paid_count,
                        ),
                        magic_draw_count, "获取神通",
                    ),
                    (
                        run_spirit_draw,
                        lambda server_id, output_dir, task_count, task_log, stop_event, snapshot: run_spirit_draw_tasks(
                            server_id, output_dir, task_count, task_log, stop_event, snapshot,
                            paid_count=spirit_paid_count,
                        ),
                        spirit_draw_count, "召唤精怪",
                    ),
                    (
                        run_law_looks_draw,
                        lambda server_id, output_dir, task_count, task_log, stop_event, snapshot: run_law_looks_draw_tasks(
                            server_id, output_dir, task_count, task_log, stop_event, snapshot,
                            paid_count=law_looks_paid_count,
                        ),
                        law_looks_draw_count, "召唤法象",
                    ),
                    (
                        run_pet_kernel_draw,
                        lambda server_id, output_dir, task_count, task_log, stop_event, snapshot: run_pet_kernel_draw_tasks(
                            server_id, output_dir, task_count, task_log, stop_event, snapshot,
                            paid_count=pet_kernel_paid_count,
                        ),
                        pet_kernel_draw_count, "凝聚内丹",
                    ),
                    (
                        run_universe_skill_draw,
                        lambda server_id, output_dir, task_count, task_log, stop_event, snapshot: run_universe_skill_draw_tasks(
                            server_id, output_dir, task_count, task_log, stop_event, snapshot,
                            paid_count=universe_skill_paid_count,
                        ),
                        universe_skill_draw_count, "山海途 - 洞悉天机",
                    ),
                    (
                        run_universe_wheel_draw, run_universe_wheel_draw_tasks,
                        universe_wheel_draw_count, "天道轮台 - 衍取",
                    ),
                    (
                        run_magic_treasure,
                        lambda server_id, output_dir, task_count, task_log, stop_event, snapshot: run_magic_treasure_tasks(
                            server_id, output_dir, task_count, task_log, stop_event, snapshot,
                            free_counts=magic_treasure_free_counts,
                            paid_counts=magic_treasure_paid_counts,
                        ),
                        1, "法宝寻宝",
                    ),
                    (
                        run_pupil_training, run_pupil_training_tasks,
                        pupil_training_rounds, "宗门 - 弟子修炼",
                    ),
                ]
                task_results = []
                for enabled, runner, task_count, task_name in auxiliary_tasks:
                    if not enabled:
                        continue
                    result = runner(
                        int(role["serverId"]), OUTPUT_DIR, task_count,
                        lambda msg: self._emit_event("chop_log", msg), self.chop_stop_event,
                        snapshot=lambda value: self._emit_event("profile_snapshot", value),
                    )
                    result["taskName"] = task_name
                    task_results.append(result)
                    self._emit_event("limited_task_result", result)
                if not run_chop:
                    if collection_thread is not None:
                        collection_thread.join()
                    self._emit_event("auxiliary_tasks_done", task_results)
                    return
                result = run_chop_tasks(
                    int(role["serverId"]), OUTPUT_DIR, count, interval, action, quality,
                    lambda msg: self._emit_event("chop_log", msg), self.chop_stop_event,
                    keep_attribute_type=attribute_type,
                    snapshot=lambda value: self._emit_event("profile_snapshot", value),
                    auto_rank_battle=auto_rank_battle,
                )
                try:
                    self._emit_event(
                        "profile_snapshot",
                        fetch_role_snapshot(int(role["serverId"]), OUTPUT_DIR),
                    )
                except (OSError, ValueError, KeyError, RuntimeError, websocket.WebSocketException) as exc:
                    self._emit_event("profile_error", f"最终资源刷新失败：{type(exc).__name__}: {exc}")
                if collection_thread is not None:
                    collection_thread.join()
                self._emit_event("chop_success", result)
            except Exception as exc:
                self.chop_stop_event.set()
                detail = traceback.format_exc()
                try:
                    (OUTPUT_DIR / "chop-task-error.log").write_text(detail, encoding="utf-8")
                except OSError:
                    pass
                self._emit_event("chop_error", f"{type(exc).__name__}: {exc}")
        threading.Thread(target=worker, daemon=True).start()

    def stop_chop(self) -> None:
        if self.start_button.isEnabled():
            self.append_log("当前没有正在运行的任务。")
            return
        self.chop_stop_event.set()
        self.append_log("已请求停止，当前操作完成后将安全退出。")

    def _handle_event(self, event: str, payload: str) -> None:
        value = json.loads(payload)
        if event == "dashboard": self.show_dashboard(Path(value["path"]), value["roles"])
        elif event == "qr":
            data = base64.b64decode(value["__bytes__"])
            pixmap = QPixmap(); pixmap.loadFromData(data); self.qr_label.setPixmap(pixmap); self.login_status.setText("二维码已生成，请使用支付宝扫码")
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
            if hasattr(self, "peach_count_label"):
                self.peach_count_label.setText(
                    f"仙桃：{self.format_amount(value.get('peachCount', 0))}"
                )
            if hasattr(self, "talent_grass_label"):
                self.talent_grass_label.setText(
                    f"灵草：{self.format_amount(value.get('talentGrassCount', 0))}"
                )
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
                invade_remaining = value.get("invadeRemaining")
                invade_text = "--" if invade_remaining is None else str(int(invade_remaining))
                self.invade_remaining_label.setText(f"今日剩余 {invade_text}/5 次")
                self.star_trial_remaining_label.setText(f"今日剩余 {int(value.get('starTrialRemaining', 0))}/30 次")
                self.hero_rank_remaining_label.setText(f"当前体力 {int(value.get('heroRankEnergy', 0))}/10")
                destiny_power = value.get("destinyPower")
                destiny_text = "--" if destiny_power is None else str(int(destiny_power))
                self.destiny_travel_remaining_label.setText(f"当前体力 {destiny_text}")
                profession_quick = value.get("professionQuickRemaining")
                profession_challenge = value.get("professionChallengeRemaining")
                quick_text = "--" if profession_quick is None else str(int(profession_quick))
                challenge_text = "--" if profession_challenge is None else str(int(profession_challenge))
                self.profession_quick_remaining_label.setText(f"今日剩余 {quick_text}/1 次")
                self.profession_challenge_remaining_label.setText(f"今日剩余 {challenge_text}/30 次")
            if hasattr(self, "spirit_remaining_label"):
                spirit_remaining = value.get("spiritSummonRemaining")
                spirit_text = "--" if spirit_remaining is None else str(int(spirit_remaining))
                self.spirit_remaining_label.setText(f"免费可用 {spirit_text}/2 次")
                self.spirit_ticket_label.setText(
                    f"召唤令可用 {int(value.get('spiritTicketCount', 0))} 次"
                )
            if hasattr(self, "tower_remaining_label"):
                tower_current = value.get("towerCurrentPass")
                tower_max = value.get("towerMaxPass")
                current_text = "--" if tower_current is None else str(int(tower_current))
                max_text = "--" if tower_max is None else str(int(tower_max))
                self.tower_remaining_label.setText(f"当前关卡 {current_text} / 最高 {max_text}")
            if hasattr(self, "adventure_stage_label"):
                adventure_stage = value.get("adventureCurrentStage")
                adventure_text = "--" if adventure_stage is None else str(int(adventure_stage))
                self.adventure_stage_label.setText(f"当前关卡 {adventure_text}")
            if hasattr(self, "treasure_auction_status_label"):
                maps = value.get("treasureMapCount")
                used = value.get("treasureWarehouseUsed")
                limit = value.get("treasureWarehouseLimit")
                unidentified = value.get("treasureUnidentifiedCount")
                display = lambda item: "--" if item is None else str(int(item))
                self.treasure_auction_status_label.setText(
                    f"藏宝图 {display(maps)} 张 · 仙囊 {display(used)}/{display(limit)} · "
                    f"待鉴宝 {display(unidentified)}"
                )
            if hasattr(self, "divine_mind_status_label"):
                last_collected = value.get("divineMindLastCollected")
                total_collected = value.get("divineMindTotalCollected")
                if last_collected is not None:
                    self.divine_mind_status_label.setText(
                        f"上次 {int(last_collected)} / 累计 {int(total_collected or 0)} 真元"
                    )
            if hasattr(self, "magic_free_label"):
                magic_remaining = value.get("magicFreeRemaining")
                magic_text = "--" if magic_remaining is None else str(int(magic_remaining))
                self.magic_free_label.setText(f"免费可用 {magic_text}/3 次")
                self.magic_ticket_label.setText(
                    f"天衍令可用 {int(value.get('magicTicketCount', 0))} 次"
                )
            if hasattr(self, "law_looks_remaining_label"):
                law_looks_remaining = value.get("lawLooksFreeRemaining")
                law_looks_text = "--" if law_looks_remaining is None else str(int(law_looks_remaining))
                self.law_looks_remaining_label.setText(f"免费可用 {law_looks_text}/2 次")
                self.law_looks_ticket_label.setText(
                    f"引灵灯可用 {int(value.get('lawLooksTicketCount', 0))} 次"
                )
            if hasattr(self, "pet_kernel_remaining_label"):
                pet_kernel_remaining = value.get("petKernelFreeRemaining")
                pet_kernel_text = "--" if pet_kernel_remaining is None else str(int(pet_kernel_remaining))
                self.pet_kernel_remaining_label.setText(f"免费可用 {pet_kernel_text}/2 次")
                self.pet_kernel_item_label.setText(
                    f"本源丹可用 {int(value.get('petKernelDrawItemCount', 0))} 次"
                )
            if hasattr(self, "universe_skill_remaining_label"):
                universe_skill_remaining = value.get("universeSkillFreeRemaining")
                universe_skill_text = "--" if universe_skill_remaining is None else str(int(universe_skill_remaining))
                self.universe_skill_remaining_label.setText(f"免费可用 {universe_skill_text}/2 次")
                self.universe_skill_item_label.setText(
                    f"太虚元石可用 {int(value.get('universeSkillDrawItemCount', 0))} 次"
                )
                self.universe_stone_label.setText(
                    f"造化石可用 {int(value.get('universeStoneCount', 0))} 次"
                )
            if hasattr(self, "magic_treasure_free_labels"):
                treasure_pools = value.get("magicTreasurePools", {})
                for pool_id in (1, 2, 3):
                    pool = treasure_pools.get(str(pool_id), treasure_pools.get(pool_id, {}))
                    free_remaining = pool.get("freeRemaining")
                    free_text = "--" if free_remaining is None else str(int(free_remaining))
                    self.magic_treasure_free_labels[pool_id].setText(f"{free_text}/2 次")
                    self.magic_treasure_compass_labels[pool_id].setText(
                        f"{int(pool.get('compassCount', 0))} 个"
                    )
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
                self.append_log(f"{task_name}任务完成，共执行 {completed} 次，剩余 {remaining}。")
            elif value.get("reason") == "stopped":
                self.append_log(f"{task_name}已停止，共完成 {completed} 次，剩余 {remaining}。")
            else:
                reason_text = {
                    "profession_challenge_lost": "当前关卡挑战未通过",
                    "profession_result_unknown": "战斗结果无法解析",
                    "profession_no_passed_boss": "尚无已通关关卡可供速战",
                    "profession_state_unknown": "道途试炼状态未同步",
                }.get(value.get("reason"), value.get("reason"))
                self.append_log(
                    f"{task_name}停止：{reason_text}，服务端返回 {value.get('ret')}，"
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
    global _FAULT_LOG
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _FAULT_LOG = (OUTPUT_DIR / "qt-fault.log").open("a", encoding="utf-8", buffering=1)
    faulthandler.enable(_FAULT_LOG, all_threads=True)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setFont(QFont(UI_FONT_FAMILY, 10))
    if not USING_FLUENT_WIDGETS:
        app.setStyle("Fusion")
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#f5f7f7"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#27363b"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f5f7f7"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#27363b"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#27363b"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#28a779"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#9aa6aa"))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#9aa6aa"))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#9aa6aa"))
        app.setPalette(palette)
    setTheme(Theme.LIGHT)
    window = XundaoWindow(); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
