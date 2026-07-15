#!/usr/bin/env python3
"""Local QR login client for the Alipay GameCenter PC auth flow."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import qrcode
import requests


BASE_URL = "https://webgwmobiler.alipay.com/gameauth/"
SERVICE = "com.alipay.gameauth.common.facade.service.GameCenterPcAuthFacade"
DEFAULT_ORIGIN = "https://www.wanyiwan.top"
DEFAULT_APP_ID = "180020010001270314"
DEFAULT_CONFIG = Path(__file__).resolve().with_name("config.json")
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)

WAIT_WORDS = ("wait", "waiting", "pending", "scan", "scanning", "confirm")
EXPIRED_WORDS = ("expire", "expired", "timeout", "invalid")
SUCCESS_WORDS = ("success", "succeed", "logged", "authorized", "complete")
WAIT_ERROR_CODES = {"USER_NOT_LOGIN"}


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            found.extend(strings(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(strings(item))
    elif isinstance(value, (str, int, bool)):
        found.append(str(value).lower())
    return found


def classify(payload: dict[str, Any]) -> str:
    error_code = str(payload.get("errorCode") or "").upper()
    if error_code in WAIT_ERROR_CODES:
        return "waiting"
    text = " ".join(strings(payload))
    if any(word in text for word in EXPIRED_WORDS):
        return "expired"
    if any(word in text for word in SUCCESS_WORDS):
        return "success"
    if any(word in text for word in WAIT_WORDS):
        return "waiting"

    data = payload.get("data")
    if payload.get("success") is True and data not in (None, {}, [], ""):
        return "success"
    if payload.get("success") is False and payload.get("retryable") is False:
        return "failed"
    return "unknown"


def save_json(output_dir: Path, name: str, payload: Any) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def request_json(session: requests.Session, url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    response = session.post(url, json=body, timeout=timeout)
    response.raise_for_status()
    try:
        payload = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        preview = response.text[:500]
        raise RuntimeError(f"接口未返回 JSON（HTTP {response.status_code}）：{preview}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"接口返回了非对象 JSON：{payload!r}")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="寻道大千支付宝游戏中心二维码登录")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="配置文件路径，默认脚本目录下的 config.json")
    parser.add_argument("--pc-token", help="x-game-token-pcweb；也可用 XUNDAO_PC_TOKEN")
    parser.add_argument("--ctoken", help="ctoken 查询参数；也可用 XUNDAO_CTOKEN")
    parser.add_argument("--appid", default=DEFAULT_APP_ID)
    parser.add_argument("--ldc-uid", default="05")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--user-agent", default=DEFAULT_UA)
    parser.add_argument("--interval", type=float, default=2.0, help="轮询间隔秒数，默认 2")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次 HTTP 超时秒数，默认 15")
    parser.add_argument("--max-wait", type=float, default=180.0, help="最长等待秒数，默认 180")
    parser.add_argument("--output-dir", type=Path, default=Path("login-output"))
    parser.add_argument("--no-browser", action="store_true", help="不自动打开二维码链接")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取配置文件 {path}：{exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"配置文件 {path} 的顶层必须是 JSON 对象")
    return value


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    args.pc_token = args.pc_token or os.getenv("XUNDAO_PC_TOKEN") or config.get("pcToken")
    args.ctoken = args.ctoken or os.getenv("XUNDAO_CTOKEN") or config.get("ctoken")
    if not args.pc_token:
        args.pc_token = getpass.getpass(
            f"配置文件 {args.config} 中未设置 pcToken，请粘贴最新的 x-game-token-pcweb（输入不会显示）："
        ).strip()
    if not args.ctoken:
        args.ctoken = input("请粘贴最新的 ctoken：").strip()
    if not args.pc_token or not args.ctoken:
        print("令牌不能为空。请从浏览器最新请求中重新获取后再运行。", file=sys.stderr)
        return 2
    if args.interval < 0.5 or args.max_wait <= 0:
        print("--interval 不能小于 0.5，--max-wait 必须大于 0。", file=sys.stderr)
        return 2

    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": args.origin.rstrip("/"),
        "Referer": args.origin.rstrip("/") + "/",
        "User-Agent": args.user_agent,
        "x-game-token-pcweb": args.pc_token,
        "x-webgw-appid": args.appid,
        "x-webgw-ldc-uid": args.ldc_uid,
        "x-webgw-version": "2.0",
    })
    query = urlencode({"ctoken": args.ctoken})
    token_url = f"{BASE_URL}{SERVICE}/getLoginToken?{query}"
    login_url = f"{BASE_URL}{SERVICE}/loginForPc?{query}"

    print("正在申请二维码登录令牌...")
    token_response = request_json(session, token_url, {}, args.timeout)
    save_json(args.output_dir, "get-login-token.json", token_response)
    try:
        qr = token_response["data"]["qrCode"]
        qr_url = qr["url"]
        login_token = qr["token"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"二维码响应结构与预期不符：{compact(token_response)}") from exc

    qr_path = args.output_dir / "login-qr.png"
    qr_path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(qr_url).save(qr_path)
    print(f"二维码已保存：{qr_path.resolve()}")
    print(f"扫码链接：{qr_url}")
    if not args.no_browser:
        webbrowser.open(qr_url)

    started = time.monotonic()
    last_response = ""
    attempt = 0
    while time.monotonic() - started < args.max_wait:
        attempt += 1
        payload = request_json(
            session,
            login_url,
            {"token": login_token, "userAgent": args.user_agent},
            args.timeout,
        )
        serialized = compact(payload)
        state = classify(payload)
        if serialized != last_response:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 第 {attempt} 次：{state}")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            last_response = serialized

        if state == "success":
            path = save_json(args.output_dir, "login-success.json", payload)
            print(f"登录成功响应已保存：{path.resolve()}")
            return 0
        if state in ("expired", "failed"):
            path = save_json(args.output_dir, f"login-{state}.json", payload)
            print(f"登录终止，响应已保存：{path.resolve()}", file=sys.stderr)
            return 1
        time.sleep(args.interval)

    print(f"等待超过 {args.max_wait:g} 秒，停止轮询。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (requests.RequestException, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
