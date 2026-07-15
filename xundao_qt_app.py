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
from PySide6.QtCore import Qt, Signal
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
from xundao_game_session import fetch_role_snapshot, run_chop_tasks
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
        "selectedServerId": "", "chopCount": "1", "chopInterval": "1.0",
        "equipmentAction": "stop", "keepQuality": "5",
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
            if index:
                button.clicked.connect(lambda _checked=False, name=text: self.append_log(f"{name}功能暂未开放。"))
            layout.addWidget(item)
        layout.addStretch()
        return nav

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
        self.count_input = SpinBox(); self.count_input.setRange(1, 10000); self.count_input.setValue(int(config["chopCount"]))
        self.interval_input = DoubleSpinBox(); self.interval_input.setRange(0, 60); self.interval_input.setSingleStep(0.5); self.interval_input.setValue(float(config["chopInterval"]))
        self.action_input = ComboBox(); self.action_input.addItems(["遇到装备停止", "自动分解"]); self.action_input.setCurrentIndex(1 if config["equipmentAction"] == "decompose" else 0)
        self.quality_input = SpinBox(); self.quality_input.setRange(1, 20); self.quality_input.setValue(int(config["keepQuality"]))
        form.addWidget(QLabel("砍树次数"), 0, 0); form.addWidget(self.count_input, 0, 1)
        form.addWidget(QLabel("装备处理"), 0, 2); form.addWidget(self.action_input, 0, 3)
        form.addWidget(QLabel("间隔时间"), 1, 0); form.addWidget(self.interval_input, 1, 1)
        form.addWidget(QLabel("保留品质"), 1, 2); form.addWidget(self.quality_input, 1, 3)
        task_layout.addLayout(form); layout.addWidget(task)
        layout.addStretch()
        return panel

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
        stop = PushButton(FIF.CANCEL, "停止"); stop.clicked.connect(lambda: self.append_log("当前任务将在安全节点停止。"))
        stop.setStyleSheet("color:#d94f4f;")
        self.connection_status = QLabel("●  等待连接"); self.connection_status.setObjectName("statusGood")
        runtime = QLabel("运行时长：00:00:00"); runtime.setObjectName("muted")
        layout.addWidget(config); layout.addWidget(import_button); layout.addWidget(export_button)
        layout.addStretch(1)
        layout.addWidget(self.start_button); layout.addWidget(pause); layout.addWidget(stop)
        layout.addStretch(1)
        layout.addWidget(self.connection_status); layout.addSpacing(24); layout.addWidget(runtime)
        return footer

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
        if not self.current_role or not self.chop_enabled.isChecked(): return
        action = "decompose" if self.action_input.currentIndex() == 1 else "stop"
        update_config(chopCount=self.count_input.value(), chopInterval=self.interval_input.value(), equipmentAction=action, keepQuality=self.quality_input.value())
        self.start_button.setEnabled(False); role = dict(self.current_role)
        count = self.count_input.value()
        interval = self.interval_input.value()
        quality = self.quality_input.value()
        self.append_log(f"开始执行自动砍树：{role.get('serverName')} / {role.get('nickName')}，计划 {count} 次。")
        def worker() -> None:
            try:
                result = run_chop_tasks(int(role["serverId"]), OUTPUT_DIR, count, interval, action, quality, lambda msg: self.event.emit("chop_log", msg))
                self.event.emit("chop_success", result)
            except (OSError, ValueError, KeyError, RuntimeError, websocket.WebSocketException) as exc:
                detail = traceback.format_exc()
                try:
                    (OUTPUT_DIR / "chop-task-error.log").write_text(detail, encoding="utf-8")
                except OSError:
                    pass
                self.event.emit("chop_error", f"{type(exc).__name__}: {exc}")
        threading.Thread(target=worker, daemon=True).start()

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
            self.account_meta.setText(
                f"修为：{self.format_amount(value.get('cultivation', 0))}    "
                f"妖力：{self.format_amount(value.get('power', 0))}"
            )
            self.append_log("角色资产与妖力数据加载完成。")
        elif event == "profile_error":
            self.append_log(f"角色详细数据读取失败：{value}")
        elif event == "chop_error": self.start_button.setEnabled(True); self.append_log(f"连接或请求失败：{value}")
        elif event == "chop_success":
            self.start_button.setEnabled(True); completed = value.get("completed", 0); reason = value.get("reason", "unknown")
            messages = {
                "finished": f"砍树任务完成，共执行 {completed} 次。",
                "kept": f"任务停止：发现需要保留的装备，共执行 {completed} 次。",
                "unsafe_source": "安全停止：待处理列表中存在非砍树来源装备。",
                "decompose_failed": f"自动分解失败，服务端返回 {value.get('ret')}。",
                "chop_failed": f"砍树请求失败，服务端返回 {value.get('ret')}。",
            }
            self.append_log(messages.get(reason, f"任务停止：{reason}，服务端返回 {value.get('ret')}。"))

    def closeEvent(self, event: Any) -> None:
        self.stop_event.set(); super().closeEvent(event)


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv); app.setFont(QFont("Microsoft YaHei UI", 10)); setTheme(Theme.LIGHT)
    window = XundaoWindow(); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
