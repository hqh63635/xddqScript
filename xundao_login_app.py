#!/usr/bin/env python3
"""Windows GUI for the Xundao QR login flow."""

from __future__ import annotations

import io
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Any
from urllib.parse import urlencode

import qrcode
import requests
import websocket
from PIL import Image, ImageTk

from xundao_game_client import fetch_game_data
from xundao_game_session import run_chop_tasks, run_pupil_training
from xundao_role_client import fetch_roles
from xundao_qr_login import (
    BASE_URL,
    DEFAULT_APP_ID,
    DEFAULT_ORIGIN,
    DEFAULT_UA,
    SERVICE,
    classify,
    request_json,
    save_json,
)


APP_TITLE = "寻道大千 - 扫码登录"
POLL_INTERVAL = 2.0


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


CONFIG_PATH = app_dir() / "config.json"
OUTPUT_DIR = app_dir() / "login-output"


def read_config() -> dict[str, str]:
    defaults = {
        "pcToken": "", "ctoken": "bigfish_ctoken_1ab4ieaf3e", "sessionToken": "", "selectedServerId": "",
        "chopCount": "1", "chopInterval": "1.0", "equipmentAction": "stop", "keepQuality": "5",
    }
    if not CONFIG_PATH.exists():
        return defaults
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"配置文件读取失败：{exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("config.json 顶层必须是 JSON 对象")
    return {**defaults, **{key: str(item) for key, item in value.items()}}


def write_config(pc_token: str, ctoken: str) -> None:
    current = read_config()
    current.update({"pcToken": pc_token, "ctoken": ctoken})
    CONFIG_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_config(**values: Any) -> None:
    current = read_config()
    current.update({key: str(value) for key, value in values.items()})
    CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


class LoginApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("460x590")
        self.minsize(420, 540)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.qr_photo: ImageTk.PhotoImage | None = None
        self.config_data: dict[str, str] = {}
        self.login_frame: ttk.Frame | None = None
        self.account_frame: ttk.Frame | None = None
        self.current_role: dict[str, Any] | None = None
        self.log_text: scrolledtext.ScrolledText | None = None
        self.chop_enabled_var = tk.BooleanVar(value=True)
        self.pupil_train_enabled_var = tk.BooleanVar(value=False)
        self.chop_settings = read_config()
        self._build_ui()
        self.after(100, self._drain_events)
        self.after(150, self.restore_session)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.configure(background="#f4f7f6")
        style.configure("TFrame", background="#f4f7f6")
        style.configure("TLabel", background="#f4f7f6", foreground="#253238", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"), foreground="#17252a")
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 11))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(12, 7), borderwidth=1)
        style.configure("Primary.TButton", foreground="#ffffff", background="#2aaa7a", bordercolor="#2aaa7a", padding=(18, 9))
        style.map("Primary.TButton", background=[("active", "#23956b"), ("disabled", "#a9cec1")])
        style.configure("Danger.TButton", foreground="#dc4b4b", background="#fff7f7", bordercolor="#f0caca", padding=(18, 9))
        style.map("Danger.TButton", background=[("active", "#ffeded")])
        style.configure("Compact.TButton", padding=(8, 4), font=("Microsoft YaHei UI", 9))
        style.configure(
            "Form.TCombobox", padding=(10, 7), relief="flat", borderwidth=1,
            fieldbackground="#ffffff", background="#ffffff", foreground="#34454b",
            bordercolor="#d8e1de", lightcolor="#d8e1de", darkcolor="#d8e1de", arrowcolor="#718086",
        )
        style.map(
            "Form.TCombobox", fieldbackground=[("readonly", "#ffffff")],
            selectbackground=[("readonly", "#e9f6f1")], selectforeground=[("readonly", "#27373c")],
            bordercolor=[("focus", "#49b68f")], lightcolor=[("focus", "#49b68f")], darkcolor=[("focus", "#49b68f")],
        )
        style.configure(
            "Form.TSpinbox", padding=(9, 6), arrowsize=13, relief="flat", borderwidth=1,
            fieldbackground="#ffffff", foreground="#34454b", background="#f7faf9",
            bordercolor="#d8e1de", lightcolor="#d8e1de", darkcolor="#d8e1de", arrowcolor="#718086",
        )
        style.map(
            "Form.TSpinbox", bordercolor=[("focus", "#49b68f")],
            lightcolor=[("focus", "#49b68f")], darkcolor=[("focus", "#49b68f")],
        )
        style.configure("Task.TCheckbutton", background="#fbfdfc", foreground="#26353a", font=("Microsoft YaHei UI", 10, "bold"), padding=2)
        style.map("Task.TCheckbutton", indicatorcolor=[("selected", "#2aa77a"), ("!selected", "#ffffff")], background=[("active", "#fbfdfc")])

        root = ttk.Frame(self, padding=(28, 22))
        self.login_frame = root
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="寻道大千", style="Title.TLabel").pack()
        ttk.Label(root, text="支付宝扫码登录", foreground="#555555").pack(pady=(4, 16))

        self.qr_frame = tk.Frame(root, width=310, height=310, bg="#f3f4f6", highlightthickness=1, highlightbackground="#d4d7dc")
        self.qr_frame.pack()
        self.qr_frame.pack_propagate(False)
        self.qr_label = tk.Label(
            self.qr_frame,
            text="正在准备二维码...",
            bg="#f3f4f6",
            fg="#666666",
            font=("Microsoft YaHei UI", 11),
        )
        self.qr_label.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="正在初始化...")
        ttk.Label(root, textvariable=self.status_var, style="Status.TLabel", anchor="center", wraplength=380).pack(
            fill="x", pady=(18, 14)
        )

        buttons = ttk.Frame(root)
        buttons.pack()
        self.refresh_button = ttk.Button(buttons, text="刷新二维码", command=self.start_login)
        self.refresh_button.pack(side="left", padx=5)
        ttk.Button(buttons, text="登录设置", command=self.open_settings).pack(side="left", padx=5)

        ttk.Label(root, text="请使用支付宝扫描二维码", foreground="#777777").pack(side="bottom", pady=(12, 0))

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _append_log(self, message: str) -> None:
        if self.log_text is None or not self.log_text.winfo_exists():
            return
        timestamp = time.strftime("%H:%M:%S")
        lowered = message.lower()
        if any(word in lowered for word in ("失败", "错误", "拒绝", "error", "failed")):
            category, tag = "错误", "error"
        elif any(word in message for word in ("完成", "成功", "获得", "保留")):
            category, tag = "任务", "success"
        elif any(word in message for word in ("砍树", "装备", "任务", "执行")):
            category, tag = "砍树", "task"
        else:
            category, tag = "系统", "system"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}]  ", "timestamp")
        self.log_text.insert("end", f"{category:<4}", tag)
        self.log_text.insert("end", f"  {message}\n", "message")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        if self.log_text is None or not self.log_text.winfo_exists():
            return
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _execute_selected_operations(self) -> None:
        if not self.chop_enabled_var.get() and not self.pupil_train_enabled_var.get():
            self._append_log("未勾选任何操作。")
            return
        if self.pupil_train_enabled_var.get():
            self._confirm_pupil_training(run_chop_after=self.chop_enabled_var.get())
        else:
            self._confirm_chop_tree()

    @staticmethod
    def _masked(value: Any, visible: int = 4) -> str:
        text = str(value or "")
        return text if len(text) <= visible * 2 else f"{text[:visible]}...{text[-visible:]}"

    def _show_login_view(self) -> None:
        self.title("寻道大千 - 扫码登录")
        if self.account_frame is not None:
            self.account_frame.destroy()
            self.account_frame = None
        if self.login_frame is not None:
            self.login_frame.pack(fill="both", expand=True)
        self.geometry("460x590")
        self.minsize(420, 540)

    def _show_account_view(self, login_path: Path, roles: list[dict[str, Any]]) -> None:
        self._render_dashboard(login_path, roles)
        return
        self.title("寻道大千 - 账号中心")
        if self.login_frame is not None:
            self.login_frame.pack_forget()
        if self.account_frame is not None:
            self.account_frame.destroy()
        login = json.loads(login_path.read_text(encoding="utf-8-sig"))
        publisher_path = OUTPUT_DIR / "publisher-login.json"
        publisher = json.loads(publisher_path.read_text(encoding="utf-8-sig")) if publisher_path.exists() else {}
        platform_user_id = login.get("data", {}).get("userId", "")
        publisher_data = publisher.get("data", {})

        self.geometry("760x600")
        self.minsize(680, 520)
        root = ttk.Frame(self, padding=(28, 22))
        root.pack(fill="both", expand=True)
        self.account_frame = root

        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 18))
        ttk.Label(header, text="寻道大千", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="已登录", foreground="#16803c", font=("Microsoft YaHei UI", 11, "bold")).pack(side="right", pady=8)

        account = ttk.LabelFrame(root, text="用户信息", padding=(18, 12))
        account.pack(fill="x", pady=(0, 16))
        account.columnconfigure(1, weight=1)
        account.columnconfigure(3, weight=1)
        fields = (
            ("支付宝游戏用户", self._masked(platform_user_id)),
            ("发行平台 UID", str(publisher_data.get("uid", "-"))),
            ("账号标识", self._masked(publisher_data.get("openid", ""))),
            ("角色数量", str(len(roles))),
        )
        for index, (label, value) in enumerate(fields):
            row, column = divmod(index, 2)
            base = column * 2
            ttk.Label(account, text=label, foreground="#666666").grid(row=row, column=base, sticky="w", pady=5)
            ttk.Label(account, text=value, font=("Microsoft YaHei UI", 10, "bold")).grid(row=row, column=base + 1, sticky="w", padx=(12, 28), pady=5)

        role_box = ttk.LabelFrame(root, text="玩家信息与区服选择", padding=(12, 10))
        role_box.pack(fill="both", expand=True)
        columns = ("server", "nickname", "player_id", "realm")
        tree = ttk.Treeview(role_box, columns=columns, show="headings", height=7, selectmode="browse")
        for column, title, width in (("server", "区服", 150), ("nickname", "角色昵称", 150), ("player_id", "角色 ID", 180), ("realm", "境界 ID", 90)):
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor="center")
        tree.pack(fill="both", expand=True)
        for index, role in enumerate(roles):
            tree.insert("", "end", iid=str(index), values=(role.get("serverName", ""), role.get("nickName", ""), role.get("playerId", ""), role.get("realmsId", "")))

        selected_var = tk.StringVar(value="请选择一个区服")
        selected_role: dict[str, Any] = {}
        ttk.Label(root, textvariable=selected_var, foreground="#444444").pack(fill="x", pady=(12, 4))

        def select_role(_event: Any = None) -> None:
            selection = tree.selection()
            if selection:
                role = roles[int(selection[0])]
                selected_role.clear()
                selected_role.update(role)
                selected_var.set(f"当前区服：{role.get('serverName', '-')}    角色：{role.get('nickName', '-')}    角色 ID：{role.get('playerId', '-')}")

        tree.bind("<<TreeviewSelect>>", select_role)
        if roles:
            tree.selection_set("0")
            tree.focus("0")
            select_role()

        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="重新登录", command=lambda: (self._show_login_view(), self.start_login())).pack(side="left")
        ttk.Button(actions, text="登录设置", command=self.open_settings).pack(side="left", padx=8)
        ttk.Button(actions, text="进入角色", command=lambda: self._show_role_view(login_path, roles, selected_role)).pack(side="right")
        ttk.Button(actions, text="重新扫码刷新", command=self.start_login).pack(side="right", padx=8)

    def _render_dashboard(self, login_path: Path, roles: list[dict[str, Any]]) -> None:
        self.title("寻道大千 - 角色操作台")
        if self.login_frame is not None:
            self.login_frame.pack_forget()
        if self.account_frame is not None:
            self.account_frame.destroy()
        login = json.loads(login_path.read_text(encoding="utf-8-sig"))
        publisher_path = OUTPUT_DIR / "publisher-login.json"
        publisher = json.loads(publisher_path.read_text(encoding="utf-8-sig")) if publisher_path.exists() else {}
        publisher_data = publisher.get("data", {})
        self.geometry("1260x780")
        self.minsize(1060, 680)
        root = tk.Frame(self, bg="#f4f7f6")
        root.pack(fill="both", expand=True)
        self.account_frame = root

        topbar = tk.Frame(root, bg="#ffffff", height=48, highlightbackground="#e7ecea", highlightthickness=1)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        tk.Label(topbar, text="◆", bg="#ffffff", fg="#2aa77a", font=("Microsoft YaHei UI", 15, "bold")).pack(side="left", padx=(18, 8))
        tk.Label(topbar, text="寻道大千脚本助手", bg="#ffffff", fg="#29373c", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        tk.Label(topbar, text="v1.0.0", bg="#ffffff", fg="#8a999e", font=("Microsoft YaHei UI", 9)).pack(side="left", padx=8)
        tk.Label(topbar, text="●  已连接游戏", bg="#ffffff", fg="#25a86f", font=("Microsoft YaHei UI", 9)).pack(side="right", padx=20)

        content = tk.Frame(root, bg="#f4f7f6")
        content.pack(fill="both", expand=True, padx=18, pady=(14, 0))

        profile = tk.Frame(content, bg="#ffffff", height=126, highlightbackground="#e7ecea", highlightthickness=1)
        profile.pack(fill="x", pady=(0, 14))
        profile.pack_propagate(False)
        avatar = tk.Canvas(profile, width=78, height=78, bg="#ffffff", highlightthickness=0)
        avatar.pack(side="left", padx=(22, 16), pady=22)
        avatar.create_oval(3, 3, 75, 75, fill="#e8f7f1", outline="#b8ddcf", width=2)
        avatar.create_text(39, 39, text="道", fill="#2a9d76", font=("Microsoft YaHei UI", 24, "bold"))
        identity = tk.Frame(profile, bg="#ffffff", width=275)
        identity.pack(side="left", fill="y", pady=20)
        identity.pack_propagate(False)
        role_name_var = tk.StringVar(value="暂无角色")
        role_meta_var = tk.StringVar(value="角色信息尚未加载")
        tk.Label(identity, textvariable=role_name_var, bg="#ffffff", fg="#18272c", font=("Microsoft YaHei UI", 16, "bold"), anchor="w").pack(fill="x")
        tk.Label(identity, textvariable=role_meta_var, bg="#ffffff", fg="#718086", font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x", pady=(8, 0))
        platform_id = self._masked(login.get("data", {}).get("userId", ""))
        tk.Label(identity, text=f"账号：{platform_id}    共 {len(roles)} 个角色", bg="#ffffff", fg="#718086", font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x", pady=(7, 0))

        selector = tk.Frame(profile, bg="#ffffff")
        selector.pack(side="left", fill="y", padx=(8, 20), pady=19)
        labels = [f"{role.get('serverName', '-')}  |  {role.get('nickName', '-')}" for role in roles]
        role_var = tk.StringVar()
        tk.Label(selector, text="区服 / 角色", bg="#ffffff", fg="#66767c", font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 9))
        role_combo = ttk.Combobox(selector, textvariable=role_var, values=labels, state="readonly", width=30, style="Form.TCombobox")
        role_combo.grid(row=0, column=1, sticky="ew", pady=(0, 9))
        tk.Label(selector, text="角色 ID", bg="#ffffff", fg="#66767c", font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", padx=(0, 10))
        role_id_var = tk.StringVar(value="-")
        tk.Label(selector, textvariable=role_id_var, bg="#ffffff", fg="#34454b", font=("Microsoft YaHei UI", 9)).grid(row=1, column=1, sticky="w")

        resources = tk.Frame(profile, bg="#ffffff")
        resources.pack(side="right", fill="both", expand=True)
        resource_values = (("灵石", "--", "#2aa77a", "灵"), ("仙玉", "--", "#2c91d1", "玉"), ("境界", "--", "#e99b36", "境"))
        for index, (name, value, color, icon) in enumerate(resource_values):
            item = tk.Frame(resources, bg="#ffffff", highlightbackground="#eef1f0", highlightthickness=1)
            item.pack(side="left", fill="both", expand=True)
            icon_canvas = tk.Canvas(item, width=42, height=42, bg="#ffffff", highlightthickness=0)
            icon_canvas.pack(pady=(15, 0))
            icon_canvas.create_oval(3, 3, 39, 39, fill=color, outline="")
            icon_canvas.create_text(21, 21, text=icon, fill="#ffffff", font=("Microsoft YaHei UI", 11, "bold"))
            tk.Label(item, text=name, bg="#ffffff", fg=color, font=("Microsoft YaHei UI", 9)).pack()
            value_label = tk.Label(item, text=value, bg="#ffffff", fg="#26353a", font=("Microsoft YaHei UI", 11, "bold"))
            value_label.pack(pady=(4, 0))
            if name == "境界":
                self.realm_value_label = value_label

        body = tk.Frame(content, bg="#f4f7f6")
        body.pack(fill="both", expand=True)
        nav = tk.Frame(body, bg="#ffffff", width=92, highlightbackground="#e7ecea", highlightthickness=1)
        nav.pack(side="left", fill="y", padx=(0, 14))
        nav.pack_propagate(False)
        nav_items = (("树", "砍树", True), ("历", "历练", False), ("妖", "妖王", False), ("秘", "秘境", False), ("奖", "领取奖励", False), ("活", "活动任务", False), ("···", "更多功能", False))

        def unavailable(name: str) -> None:
            self._append_log(f"{name}功能暂未开放。")

        for icon, name, active in nav_items:
            bg = "#eaf7f2" if active else "#ffffff"
            fg = "#249f75" if active else "#8d9ba0"
            command = (lambda: None) if active else (lambda item=name: unavailable(item))
            item = tk.Frame(nav, bg=bg, height=72, cursor="hand2")
            item.pack(fill="x", pady=(0, 1))
            item.pack_propagate(False)
            badge = tk.Label(item, text=icon, bg=("#2aa77a" if active else "#eef2f1"), fg=("#ffffff" if active else "#829196"), width=3, font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2")
            badge.pack(pady=(10, 3))
            caption = tk.Label(item, text=name, bg=bg, fg=fg, font=("Microsoft YaHei UI", 8), cursor="hand2")
            caption.pack()
            for widget in (item, badge, caption):
                widget.bind("<Button-1>", lambda _event, callback=command: callback())

        workspace = tk.Frame(body, bg="#ffffff", highlightbackground="#e7ecea", highlightthickness=1)
        workspace.pack(side="left", fill="both", expand=True, padx=(0, 14))
        panel_head = tk.Frame(workspace, bg="#ffffff", height=50)
        panel_head.pack(fill="x", padx=16)
        panel_head.pack_propagate(False)
        tk.Label(panel_head, text="⚙  功能设置", bg="#ffffff", fg="#26353a", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left", pady=15)
        ttk.Button(panel_head, text="高级设置", style="Compact.TButton", command=self.open_chop_settings).pack(side="right", pady=10)

        settings = read_config()
        count_var = tk.StringVar(value=settings.get("chopCount", "1"))
        interval_var = tk.StringVar(value=settings.get("chopInterval", "1.0"))
        action_var = tk.StringVar(value="自动分解" if settings.get("equipmentAction") == "decompose" else "遇到装备停止")
        quality_var = tk.StringVar(value=settings.get("keepQuality", "5"))

        task_card = tk.Frame(workspace, bg="#fbfdfc", highlightbackground="#dce6e2", highlightthickness=1)
        task_card.pack(fill="x", padx=16, pady=(0, 12))
        card_title = tk.Frame(task_card, bg="#fbfdfc")
        card_title.pack(fill="x", padx=14, pady=(12, 7))
        check_mark = tk.Label(card_title, width=2, bg="#2aa77a", fg="#ffffff", font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2")
        check_mark.pack(side="left")
        check_text = tk.Label(card_title, text="自动砍树", bg="#fbfdfc", fg="#26353a", font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2")
        check_text.pack(side="left", padx=(6, 0))

        def refresh_check() -> None:
            enabled = self.chop_enabled_var.get()
            check_mark.configure(text="✓" if enabled else "", bg="#2aa77a" if enabled else "#ffffff", highlightbackground="#cfdad6", highlightthickness=0 if enabled else 1)

        def toggle_check(_event: Any = None) -> None:
            self.chop_enabled_var.set(not self.chop_enabled_var.get())
            refresh_check()

        for widget in (check_mark, check_text):
            widget.bind("<Button-1>", toggle_check)
        refresh_check()
        tk.Label(card_title, text="自动执行砍树任务并处理掉落装备", bg="#fbfdfc", fg="#94a09d", font=("Microsoft YaHei UI", 8)).pack(side="left", padx=10)

        form = tk.Frame(task_card, bg="#fbfdfc")
        form.pack(fill="x", padx=24, pady=(4, 15))
        for column in (1, 3):
            form.columnconfigure(column, weight=1)
        tk.Label(form, text="砍树次数", bg="#fbfdfc", fg="#4e5e63").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=7)
        ttk.Spinbox(form, from_=1, to=10000, textvariable=count_var, width=11, style="Form.TSpinbox").grid(row=0, column=1, sticky="w", pady=7)
        tk.Label(form, text="间隔时间", bg="#fbfdfc", fg="#4e5e63").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=7)
        ttk.Spinbox(form, from_=0, to=60, increment=0.5, textvariable=interval_var, width=11, style="Form.TSpinbox").grid(row=1, column=1, sticky="w", pady=7)
        tk.Label(form, text="秒", bg="#fbfdfc", fg="#7c898d").grid(row=1, column=2, sticky="w", padx=(7, 30))
        tk.Label(form, text="装备处理", bg="#fbfdfc", fg="#4e5e63").grid(row=0, column=3, sticky="e", padx=(8, 10), pady=7)
        action_box = ttk.Combobox(form, textvariable=action_var, values=("遇到装备停止", "自动分解"), state="readonly", width=14, style="Form.TCombobox")
        action_box.grid(row=0, column=4, sticky="w", pady=7)
        tk.Label(form, text="保留品质", bg="#fbfdfc", fg="#4e5e63").grid(row=1, column=3, sticky="e", padx=(8, 10), pady=7)
        ttk.Spinbox(form, from_=1, to=45, textvariable=quality_var, width=11, style="Form.TSpinbox").grid(row=1, column=4, sticky="w", pady=7)

        pupil_card = tk.Frame(workspace, bg="#fbfdfc", highlightbackground="#dce6e2", highlightthickness=1)
        pupil_card.pack(fill="x", padx=16, pady=(0, 12))
        pupil_title = tk.Frame(pupil_card, bg="#fbfdfc")
        pupil_title.pack(fill="x", padx=14, pady=12)
        pupil_mark = tk.Label(
            pupil_title, width=2, bg="#ffffff", fg="#ffffff",
            highlightbackground="#cfdad6", highlightthickness=1,
            font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2",
        )
        pupil_mark.pack(side="left")
        pupil_text = tk.Label(
            pupil_title, text="宗门 - 弟子修炼", bg="#fbfdfc", fg="#26353a",
            font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2",
        )
        pupil_text.pack(side="left", padx=(6, 0))
        tk.Label(
            pupil_title, text="使用现有次数一键修炼，不购买次数、不自动出师",
            bg="#fbfdfc", fg="#94a09d", font=("Microsoft YaHei UI", 8),
        ).pack(side="left", padx=10)

        def refresh_pupil_check() -> None:
            enabled = self.pupil_train_enabled_var.get()
            pupil_mark.configure(
                text="✓" if enabled else "", bg="#2aa77a" if enabled else "#ffffff",
                highlightthickness=0 if enabled else 1,
            )

        def toggle_pupil_check(_event: Any = None) -> None:
            self.pupil_train_enabled_var.set(not self.pupil_train_enabled_var.get())
            refresh_pupil_check()

        for widget in (pupil_mark, pupil_text):
            widget.bind("<Button-1>", toggle_pupil_check)
        refresh_pupil_check()

        status_card = tk.Frame(workspace, bg="#fbfdfc", highlightbackground="#dce6e2", highlightthickness=1)
        status_card.pack(fill="x", padx=16, pady=(0, 12))
        tk.Label(status_card, text="任务状态", bg="#fbfdfc", fg="#27363b", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=14, pady=(12, 4))
        self.role_status_var = tk.StringVar(value="请选择角色后执行操作")
        tk.Label(status_card, textvariable=self.role_status_var, bg="#fbfdfc", fg="#6d7c81", wraplength=500, justify="left").pack(anchor="w", padx=14, pady=(0, 13))
        detail_var = tk.StringVar(value="暂无角色")
        tk.Label(workspace, textvariable=detail_var, bg="#ffffff", fg="#879499", font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x", padx=18, pady=(0, 10))

        log_frame = tk.Frame(body, bg="#ffffff", width=390, highlightbackground="#e7ecea", highlightthickness=1)
        log_frame.pack(side="right", fill="both")
        log_frame.pack_propagate(False)
        log_head = tk.Frame(log_frame, bg="#ffffff", height=50)
        log_head.pack(fill="x", padx=14)
        log_head.pack_propagate(False)
        tk.Label(log_head, text="▤  日志输出", bg="#ffffff", fg="#26353a", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left", pady=15)
        ttk.Button(log_head, text="清空日志", style="Compact.TButton", command=lambda: self._clear_log()).pack(side="right", pady=10)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap="word", state="disabled", font=("Microsoft YaHei UI", 9), background="#fbfcfc", foreground="#445359", relief="flat", padx=12, pady=10, borderwidth=0)
        self.log_text.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.log_text.tag_configure("timestamp", foreground="#8a989d")
        self.log_text.tag_configure("system", foreground="#2685c7", font=("Microsoft YaHei UI", 9, "bold"))
        self.log_text.tag_configure("task", foreground="#28a66f", font=("Microsoft YaHei UI", 9, "bold"))
        self.log_text.tag_configure("success", foreground="#df8b2d", font=("Microsoft YaHei UI", 9, "bold"))
        self.log_text.tag_configure("error", foreground="#dc5656", font=("Microsoft YaHei UI", 9, "bold"))
        self.log_text.tag_configure("message", foreground="#3e4c51", spacing1=2, spacing3=5)

        def persist_form() -> bool:
            try:
                count = int(count_var.get())
                interval = float(interval_var.get())
                quality = int(quality_var.get())
                if count < 1 or interval < 0 or quality < 1:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("设置无效", "次数和品质必须为正整数，间隔不能小于 0。", parent=self)
                return False
            equipment_action = "decompose" if action_var.get() == "自动分解" else "stop"
            update_config(chopCount=count, chopInterval=interval, equipmentAction=equipment_action, keepQuality=quality)
            return True

        def start_task() -> None:
            if persist_form():
                self._execute_selected_operations()

        footer = tk.Frame(root, bg="#ffffff", height=66, highlightbackground="#e4eae8", highlightthickness=1)
        footer.pack(fill="x")
        footer.pack_propagate(False)
        ttk.Button(footer, text="⚙  配置管理", command=self.open_settings).pack(side="left", padx=(22, 8), pady=15)
        ttk.Button(footer, text="↻  刷新角色", command=self.restore_session).pack(side="left", padx=6, pady=15)
        self.chop_button = ttk.Button(footer, text="▶  启动脚本", style="Primary.TButton", command=start_task)
        self.chop_button.pack(side="left", padx=(55, 8), pady=12)
        ttk.Button(footer, text="■  停止", style="Danger.TButton", command=lambda: self._append_log("当前任务将在安全节点停止。")).pack(side="left", padx=8, pady=12)
        tk.Label(footer, text="运行状态：就绪", bg="#ffffff", fg="#738187", font=("Microsoft YaHei UI", 9)).pack(side="right", padx=22)

        def select_index(index: int) -> None:
            if not roles:
                self.current_role = None
                self.chop_button.state(["disabled"])
                return
            index = max(0, min(index, len(roles) - 1))
            role = roles[index]
            self.current_role = dict(role)
            role_combo.current(index)
            role_var.set(labels[index])
            role_name_var.set(role.get("nickName", "-"))
            role_meta_var.set(f"区服：{role.get('serverName', '-')}    称号：寻道者")
            role_id_var.set(str(role.get("playerId", "-")))
            self.realm_value_label.configure(text=str(role.get("realmsId", "-")))
            detail_var.set(f"当前角色：{role.get('nickName', '-')}    角色 ID：{role.get('playerId', '-')}    发行 UID：{publisher_data.get('uid', '-')}")
            self.role_status_var.set("砍树会消耗 1 个桃子，并获得一件待处理装备。")
            self.chop_button.state(["!disabled"])
            update_config(selectedServerId=role.get("serverId", ""))
            self._append_log(f"已选择 {role.get('serverName', '-')} / {role.get('nickName', '-')}。")

        role_combo.bind("<<ComboboxSelected>>", lambda _event: select_index(role_combo.current()))
        saved_server = read_config().get("selectedServerId", "")
        selected_index = next((i for i, role in enumerate(roles) if str(role.get("serverId")) == saved_server), 0)
        select_index(selected_index)
        self._append_log("登录状态有效，角色数据加载完成。")

    def _show_role_view(self, login_path: Path, roles: list[dict[str, Any]], role: dict[str, Any]) -> None:
        if not role:
            messagebox.showwarning("请选择区服", "请先选择一个区服和角色。", parent=self)
            return
        self.current_role = dict(role)
        self.geometry("760x700")
        self.minsize(680, 650)
        if self.account_frame is not None:
            self.account_frame.destroy()
        self.title(f"寻道大千 - {role.get('nickName', '角色详情')}")
        root = ttk.Frame(self, padding=(28, 22))
        root.pack(fill="both", expand=True)
        self.account_frame = root

        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 18))
        ttk.Label(header, text=role.get("nickName", "角色详情"), style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=role.get("serverName", ""), foreground="#555555", font=("Microsoft YaHei UI", 11)).pack(side="right", pady=8)

        details = ttk.LabelFrame(root, text="角色信息", padding=(20, 16))
        details.pack(fill="x", pady=(0, 18))
        rows = (
            ("角色昵称", role.get("nickName", "-")),
            ("角色 ID", role.get("playerId", "-")),
            ("角色形象 ID", role.get("roleId", "-")),
            ("境界 ID", role.get("realmsId", "-")),
            ("所在区服", role.get("serverName", "-")),
            ("区服 ID", role.get("serverId", "-")),
        )
        for index, (label, value) in enumerate(rows):
            ttk.Label(details, text=label, foreground="#666666").grid(row=index, column=0, sticky="w", pady=6)
            ttk.Label(details, text=str(value), font=("Microsoft YaHei UI", 10, "bold")).grid(row=index, column=1, sticky="w", padx=(24, 0), pady=6)

        operation = ttk.LabelFrame(root, text="角色操作", padding=(20, 16))
        operation.pack(fill="x")
        ttk.Label(operation, text="砍树会消耗 1 个桃子，并获得一件待处理装备。", foreground="#555555").pack(anchor="w")
        self.role_status_var = tk.StringVar(value="角色连接尚未建立")
        ttk.Label(operation, textvariable=self.role_status_var, foreground="#555555").pack(anchor="w", pady=(10, 12))
        self.chop_button = ttk.Button(operation, text="砍树 1 次", command=self._confirm_chop_tree)
        self.chop_button.pack(anchor="w")

        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(18, 0))
        ttk.Button(actions, text="返回区服列表", command=lambda: self._show_account_view(login_path, roles)).pack(side="left")

    def _confirm_chop_tree(self) -> None:
        if not self.current_role:
            return
        role = self.current_role
        settings = read_config()
        count = max(1, int(settings.get("chopCount", "1")))
        action_text = "自动分解低于保留品质的装备" if settings.get("equipmentAction") == "decompose" else "遇到装备后停止"
        confirmed = messagebox.askyesno(
            "确认砍树",
            f"将在 {role.get('serverName')} / {role.get('nickName')} 上执行 {count} 次砍树。\n"
            f"装备处理：{action_text}\n\n是否继续？",
            parent=self,
        )
        if not confirmed:
            return
        self.chop_button.state(["disabled"])
        self.role_status_var.set("正在连接角色并执行砍树任务...")
        self._append_log(f"开始任务：{role.get('serverName')} / {role.get('nickName')}，计划砍树 {count} 次。")

        def worker() -> None:
            try:
                result = run_chop_tasks(
                    int(role["serverId"]), OUTPUT_DIR, count,
                    max(0.0, float(settings.get("chopInterval", "1.0"))),
                    settings.get("equipmentAction", "stop"),
                    max(1, int(settings.get("keepQuality", "5"))),
                    lambda message: self.events.put(("chop_log", message)),
                )
                self.events.put(("chop_success", result))
            except (OSError, ValueError, KeyError, RuntimeError, websocket.WebSocketException) as exc:
                self.events.put(("chop_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _confirm_pupil_training(self, run_chop_after: bool = False) -> None:
        if not self.current_role:
            return
        role = self.current_role
        extra = "\n修炼结束后继续执行砍树。" if run_chop_after else ""
        confirmed = messagebox.askyesno(
            "确认弟子修炼",
            f"将在 {role.get('serverName')} / {role.get('nickName')} 使用现有次数执行一键修炼。\n"
            f"不会购买次数，也不会自动出师。{extra}\n\n是否继续？",
            parent=self,
        )
        if not confirmed:
            return
        self.chop_button.state(["disabled"])
        self.role_status_var.set("正在执行弟子修炼...")
        self._append_log(f"开始弟子修炼：{role.get('serverName')} / {role.get('nickName')}。")

        def worker() -> None:
            try:
                result = run_pupil_training(
                    int(role["serverId"]), OUTPUT_DIR,
                    lambda message: self.events.put(("chop_log", message)),
                )
                self.events.put(("pupil_train_success", (result, run_chop_after)))
            except (OSError, ValueError, KeyError, RuntimeError, websocket.WebSocketException) as exc:
                self.events.put(("pupil_train_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def open_chop_settings(self) -> None:
        current = read_config()
        dialog = tk.Toplevel(self)
        dialog.title("砍树设置")
        dialog.geometry("460x310")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)

        count_var = tk.StringVar(value=current.get("chopCount", "1"))
        interval_var = tk.StringVar(value=current.get("chopInterval", "1.0"))
        action_var = tk.StringVar(value=current.get("equipmentAction", "stop"))
        quality_var = tk.StringVar(value=current.get("keepQuality", "5"))
        ttk.Label(body, text="砍树次数").grid(row=0, column=0, sticky="w", pady=7)
        ttk.Spinbox(body, from_=1, to=10000, textvariable=count_var, width=12).grid(row=0, column=1, sticky="w")
        ttk.Label(body, text="每次间隔（秒）").grid(row=1, column=0, sticky="w", pady=7)
        ttk.Spinbox(body, from_=0, to=60, increment=0.5, textvariable=interval_var, width=12).grid(row=1, column=1, sticky="w")
        ttk.Label(body, text="装备处理").grid(row=2, column=0, sticky="w", pady=7)
        action_box = ttk.Combobox(body, textvariable=action_var, values=("stop", "decompose"), state="readonly", width=25)
        action_box.grid(row=2, column=1, sticky="w")
        ttk.Label(body, text="stop：遇到装备停止；decompose：按品质自动分解", foreground="#666666").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        ttk.Label(body, text="保留品质（含）").grid(row=4, column=0, sticky="w", pady=7)
        ttk.Spinbox(body, from_=1, to=45, textvariable=quality_var, width=12).grid(row=4, column=1, sticky="w")

        def save() -> None:
            try:
                count_value = int(count_var.get())
                interval_value = float(interval_var.get())
                quality_value = int(quality_var.get())
                if count_value < 1 or interval_value < 0 or quality_value < 1:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("设置无效", "次数和品质必须为正整数，间隔不能小于 0。", parent=dialog)
                return
            update_config(
                chopCount=count_value, chopInterval=interval_value,
                equipmentAction=action_var.get(), keepQuality=quality_value,
            )
            self._append_log(
                f"砍树设置已更新：{count_value} 次，间隔 {interval_value:g} 秒，装备处理 {action_var.get()}。"
            )
            dialog.destroy()

        actions = ttk.Frame(body)
        actions.grid(row=5, column=0, columnspan=2, sticky="e", pady=(18, 0))
        ttk.Button(actions, text="取消", command=dialog.destroy).pack(side="left", padx=4)
        ttk.Button(actions, text="保存", command=save).pack(side="left", padx=4)

    def open_settings(self) -> None:
        try:
            current = read_config()
        except RuntimeError:
            current = {"pcToken": "", "ctoken": "bigfish_ctoken_1ab4ieaf3e"}

        dialog = tk.Toplevel(self)
        dialog.title("登录设置")
        dialog.geometry("500x245")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="x-game-token-pcweb").grid(row=0, column=0, sticky="w", pady=(0, 6))
        pc_var = tk.StringVar(value=current.get("pcToken", ""))
        pc_entry = ttk.Entry(body, textvariable=pc_var, show="•", width=62)
        pc_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 15))
        ttk.Label(body, text="ctoken").grid(row=2, column=0, sticky="w", pady=(0, 6))
        ctoken_var = tk.StringVar(value=current.get("ctoken", "bigfish_ctoken_1ab4ieaf3e"))
        ttk.Entry(body, textvariable=ctoken_var, width=62).grid(row=3, column=0, columnspan=2, sticky="ew")

        def save() -> None:
            pc_token = pc_var.get().strip()
            ctoken = ctoken_var.get().strip()
            if not pc_token or not ctoken:
                messagebox.showwarning("配置不完整", "两个配置值都不能为空。", parent=dialog)
                return
            try:
                write_config(pc_token, ctoken)
            except OSError as exc:
                messagebox.showerror("保存失败", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.start_login()

        actions = ttk.Frame(body)
        actions.grid(row=4, column=0, columnspan=2, pady=(22, 0), sticky="e")
        ttk.Button(actions, text="取消", command=dialog.destroy).pack(side="left", padx=4)
        ttk.Button(actions, text="保存并登录", command=save).pack(side="left", padx=4)
        pc_entry.focus_set()

    def restore_session(self) -> None:
        try:
            config = read_config()
        except RuntimeError:
            self.start_login()
            return
        token = config.get("sessionToken", "")
        login_path = OUTPUT_DIR / "login-success.json"
        if not token:
            self.start_login()
            return

        self.set_status("正在验证上次登录状态...")
        self.refresh_button.state(["disabled"])

        def worker() -> None:
            try:
                game_data = fetch_game_data(token, config["ctoken"], OUTPUT_DIR)
                roles = fetch_roles(game_data["auth"]["data"]["authCode"], OUTPUT_DIR)
                update_config(sessionToken=token)
                if not login_path.exists():
                    save_json(OUTPUT_DIR, "login-success.json", {"success": True, "data": {"token": token, "userId": ""}})
                self.events.put(("cached_success", (login_path, roles)))
            except (requests.RequestException, RuntimeError, KeyError, TypeError, OSError, ValueError) as exc:
                self.events.put(("cached_invalid", str(exc)))

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def start_login(self) -> None:
        self._show_login_view()
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.worker.join(timeout=0.2)
        try:
            self.config_data = read_config()
        except RuntimeError as exc:
            self.set_status(str(exc))
            self.open_settings()
            return
        if not self.config_data.get("pcToken") or not self.config_data.get("ctoken"):
            self.set_status("请先填写登录配置")
            self.open_settings()
            return

        self.stop_event = threading.Event()
        self.refresh_button.state(["disabled"])
        self.qr_label.configure(image="", text="正在获取二维码...")
        self.set_status("正在连接登录服务...")
        self.worker = threading.Thread(target=self._login_worker, args=(self.stop_event,), daemon=True)
        self.worker.start()

    def _login_worker(self, stop_event: threading.Event) -> None:
        try:
            config = self.config_data
            session = requests.Session()
            session.headers.update({
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "Content-Type": "application/json",
                "Origin": DEFAULT_ORIGIN,
                "Pragma": "no-cache",
                "Referer": DEFAULT_ORIGIN + "/",
                "User-Agent": DEFAULT_UA,
                "x-game-token-pcweb": config["pcToken"],
                "x-webgw-appid": DEFAULT_APP_ID,
                "x-webgw-ldc-uid": "05",
                "x-webgw-version": "2.0",
            })
            query = urlencode({"ctoken": config["ctoken"]})
            token_url = f"{BASE_URL}{SERVICE}/getLoginToken?{query}"
            login_url = f"{BASE_URL}{SERVICE}/loginForPc?{query}"
            token_response = request_json(session, token_url, {}, 15)
            save_json(OUTPUT_DIR, "get-login-token.json", token_response)
            qr_data = token_response["data"]["qrCode"]
            qr_url = str(qr_data["url"])
            login_token = str(qr_data["token"])
            image = qrcode.make(qr_url).convert("RGB").resize((286, 286), Image.Resampling.NEAREST)
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            self.events.put(("qr", stream.getvalue()))

            while not stop_event.wait(POLL_INTERVAL):
                payload = request_json(
                    session,
                    login_url,
                    {"token": login_token, "userAgent": DEFAULT_UA},
                    15,
                )
                save_json(OUTPUT_DIR, "login-last-response.json", payload)
                state = classify(payload)
                if state == "success":
                    path = save_json(OUTPUT_DIR, "login-success.json", payload)
                    try:
                        update_config(sessionToken=str(payload["data"]["token"]))
                        game_data = fetch_game_data(
                            str(payload["data"]["token"]),
                            config["ctoken"],
                            OUTPUT_DIR,
                        )
                        roles = fetch_roles(game_data["auth"]["data"]["authCode"], OUTPUT_DIR)
                    except (requests.RequestException, RuntimeError, KeyError, TypeError, OSError) as exc:
                        self.events.put(("game_data_error", (path, str(exc))))
                        return
                    self.events.put(("account_success", (path, roles)))
                    return
                if state in ("expired", "failed"):
                    save_json(OUTPUT_DIR, f"login-{state}.json", payload)
                    self.events.put((state, payload))
                    return
                self.events.put(("waiting", state))
        except (requests.RequestException, RuntimeError, KeyError, TypeError, OSError) as exc:
            if not stop_event.is_set():
                self.events.put(("error", str(exc)))

    def _drain_events(self) -> None:
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "qr":
                    self.qr_photo = ImageTk.PhotoImage(Image.open(io.BytesIO(value)))
                    self.qr_label.configure(image=self.qr_photo, text="")
                    self.set_status("二维码已生成，请使用支付宝扫码")
                    self.refresh_button.state(["!disabled"])
                elif event == "waiting":
                    self.set_status("等待扫码确认...")
                elif event == "cached_success":
                    path, roles = value
                    self._show_account_view(path, roles)
                elif event == "cached_invalid":
                    self.set_status("上次登录已失效，请重新扫码")
                    self.start_login()
                elif event == "account_success":
                    path, roles = value
                    self._show_account_view(path, roles)
                elif event == "success":
                    self.set_status("登录成功")
                    self.refresh_button.state(["!disabled"])
                    messagebox.showinfo("登录成功", f"登录信息已保存到：\n{value}", parent=self)
                elif event == "game_data_error":
                    path, error = value
                    self.set_status("Login succeeded; game data request failed")
                    self.refresh_button.state(["!disabled"])
                    messagebox.showwarning(
                        "Game data request failed",
                        f"Login succeeded and was saved to:\n{path}\n\nGame data error:\n{error}",
                        parent=self,
                    )
                elif event == "chop_log":
                    self._append_log(str(value))
                elif event == "chop_success":
                    self.chop_button.state(["!disabled"])
                    reason = value.get("reason")
                    completed = value.get("completed", 0)
                    if reason == "finished":
                        self.role_status_var.set(f"砍树任务完成，共执行 {completed} 次。")
                        self._append_log(f"任务完成：共砍树 {completed} 次。")
                    elif reason == "kept":
                        self.role_status_var.set(f"已执行 {completed} 次，装备符合保留条件，任务停止。")
                        self._append_log("装备已保留，请在游戏内决定穿戴或分解。")
                    elif reason == "unsafe_source":
                        self.role_status_var.set("检测到非砍树来源装备，已拒绝自动分解并停止。")
                        self._append_log("安全停止：待处理列表包含 src != 1 的装备。")
                    elif reason == "decompose_failed":
                        self.role_status_var.set(f"装备分解失败，服务端返回 {value.get('ret')}。")
                        self._append_log(f"自动分解失败：服务器返回 {value.get('ret')}。")
                    else:
                        self.role_status_var.set(f"任务停止，服务端返回：{value.get('ret')}")
                        self._append_log(f"任务停止：{reason}，服务器返回 {value.get('ret')}。")
                elif event == "chop_error":
                    self.chop_button.state(["!disabled"])
                    self.role_status_var.set(f"砍树失败：{value}")
                    self._append_log(f"连接或请求失败：{value}")
                elif event == "pupil_train_success":
                    result, run_chop_after = value
                    self.chop_button.state(["!disabled"])
                    completed = result.get("completed", 0)
                    reason = result.get("reason")
                    if completed:
                        self.role_status_var.set(f"弟子修炼结束，共完成 {completed} 轮。")
                        self._append_log(
                            f"弟子修炼结束：完成 {completed} 轮，停止原因 {reason}，服务端返回 {result.get('ret')}。"
                        )
                    else:
                        self.role_status_var.set(f"弟子修炼未执行，服务端返回 {result.get('ret')}。")
                        self._append_log(f"弟子修炼停止：{reason}，服务端返回 {result.get('ret')}。")
                    if run_chop_after:
                        self.after(100, self._confirm_chop_tree)
                elif event == "pupil_train_error":
                    self.chop_button.state(["!disabled"])
                    self.role_status_var.set(f"弟子修炼失败：{value}")
                    self._append_log(f"弟子修炼连接或请求失败：{value}")
                elif event == "expired":
                    self.set_status("二维码已过期，请刷新")
                    self.refresh_button.state(["!disabled"])
                elif event == "failed":
                    self.set_status("登录失败，请刷新二维码或更新配置")
                    self.refresh_button.state(["!disabled"])
                elif event == "error":
                    self.set_status(f"请求失败：{value}")
                    self.refresh_button.state(["!disabled"])
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._drain_events)

    def close(self) -> None:
        self.stop_event.set()
        self.destroy()


if __name__ == "__main__":
    from xundao_qt_app import main

    raise SystemExit(main())
