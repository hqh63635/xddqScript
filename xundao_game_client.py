#!/usr/bin/env python3
"""Authenticated client for Xundao Daqian's PC game-center metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from xundao_qr_login import DEFAULT_APP_ID, DEFAULT_ORIGIN, DEFAULT_UA, request_json, save_json

GAME_ID = "xddq"
GAMECENTER_BASE_URL = "https://webgwmobiler.alipay.com/gamecenterhome/"
GAME_SERVICE = "com.alipay.gamecenterhome.common.facade.service.GameCenterPcGameFacade"
GAME_INFO_METHOD = "queryPcGameInfo/uprodhatchstation66500008"
GAME_AUTH_METHOD = "queryPcGameAuthInfo/uprodhatchstation66500008"


def create_game_session(token: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": DEFAULT_ORIGIN,
        "Referer": DEFAULT_ORIGIN + "/",
        "User-Agent": DEFAULT_UA,
        "x-game-token-pcweb": token,
        "x-webgw-appid": DEFAULT_APP_ID,
        "x-webgw-ldc-uid": "05",
        "x-webgw-version": "2.0",
    })
    return session


def call_game_api(session: requests.Session, ctoken: str, method: str,
                  body: dict[str, Any], timeout: float = 20) -> dict[str, Any]:
    url = f"{GAMECENTER_BASE_URL}{GAME_SERVICE}/{method}?{urlencode({'ctoken': ctoken})}"
    payload = request_json(session, url, body, timeout)
    if payload.get("success") is not True:
        code = payload.get("errorCode") or "UNKNOWN"
        message = payload.get("errorMsg") or payload.get("errorMessage") or "Game API failed"
        raise RuntimeError(f"{code}: {message}")
    return payload


def fetch_game_data(token: str, ctoken: str, output_dir: Path,
                    game_id: str = GAME_ID) -> dict[str, Any]:
    session = create_game_session(token)
    info = call_game_api(session, ctoken, GAME_INFO_METHOD, {"gameId": game_id})
    save_json(output_dir, "game-info.json", info)
    app_id = str(info.get("data", {}).get("appId") or "")
    if not app_id:
        raise RuntimeError("Game metadata did not contain data.appId")
    auth = call_game_api(session, ctoken, GAME_AUTH_METHOD, {"appId": app_id})
    save_json(output_dir, "game-auth.json", auth)
    return {"info": info, "auth": auth}


def download_game_package(game_info: dict[str, Any], destination: Path,
                          timeout: float = 120) -> Path:
    package_url = game_info.get("data", {}).get("pkgUrl", {}).get("pkgUrl")
    if not package_url:
        raise RuntimeError("Game metadata did not contain data.pkgUrl.pkgUrl")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(package_url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with destination.open("wb") as stream:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    stream.write(chunk)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch authenticated Xundao Daqian game metadata")
    parser.add_argument("--login", type=Path, default=Path("login-output/login-success.json"))
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("login-output"))
    parser.add_argument("--download-package", action="store_true")
    args = parser.parse_args()
    login = json.loads(args.login.read_text(encoding="utf-8-sig"))
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    token = str(login.get("data", {}).get("token") or "")
    ctoken = str(config.get("ctoken") or "")
    if not token or not ctoken:
        raise RuntimeError("Missing login data.token or config ctoken")
    result = fetch_game_data(token, ctoken, args.output_dir)
    if args.download_package:
        download_game_package(result["info"], args.output_dir / "xddq-game.pkg")
    data = result["info"]["data"]
    print(json.dumps({"gameId": GAME_ID, "appId": data["appId"],
                      "appName": data["appName"], "appVersion": data["appVersion"],
                      "outputDir": str(args.output_dir.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, requests.RequestException, RuntimeError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
