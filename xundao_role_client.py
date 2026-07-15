#!/usr/bin/env python3
"""Read-only login chain for Xundao Daqian role metadata."""

from __future__ import annotations

import argparse
import base64
import json
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from xundao_game_client import fetch_game_data
from xundao_qr_login import save_json

PUBLISHER_LOGIN_URL = (
    "https://gapigameh5.sqwannet.com/api/v1/quickAppEnter"
    "?pt_type=1&appid=37zfbxyx&c=enter&a=quickAppEnter&game_id=239"
)
SERVER_LIST_URL = "https://login-xddq-cn-40.kvps85.com/server/list"
CLIENT_VERSION = "3.9.00.493"
PACKAGE_ID = "40001001"
CHANNEL_ID = 40


def _device_info() -> str:
    values = {
        "IC": 2, "DF": "browser", "OS": "", "AT": "", "DC": "", "PM": "",
        "UA": "Mozilla/5.0", "BW": "", "RL": "", "PN": "", "PV": "",
        "SDKV": "10.6.80", "IDFA": "", "ADID": "", "UEADID": "", "IMEI": "",
        "OAID": "", "LU": "zh-CN", "IDFV": "", "CC": "", "BT": "", "DN": "",
        "CI": "", "MM": "", "DISK": "", "SFT": "", "MODEL": "", "TZ": "",
        "CAID": "", "CS": "",
    }
    raw = "|".join(f"{key}={value}" for key, value in values.items())
    return base64.b64encode(raw.encode()).decode()


def publisher_login(auth_code: str, device_id: str, timeout: float = 30) -> dict[str, Any]:
    system_info = {
        "platform": "windows", "pcPlatform": "browser", "system": "Windows 11",
        "version": "10.6.80", "language": "zh-CN", "model": "PC", "SDKVersion": "3.8.0",
    }
    response = requests.post(PUBLISHER_LOGIN_URL, data={
        "js_code": auth_code,
        "wx_param": json.dumps({"referer": "haxyxtf_g1_xmt_pc_zfbPC"}, separators=(",", ":")),
        "wx_system_info": json.dumps(system_info, separators=(",", ":")),
        "c_game_id": "android.game.xddq_zfbxyxtg",
        "device_info": _device_info(),
        "guid": device_id,
    }, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 1:
        raise RuntimeError(f"Publisher login failed: {payload.get('code')} {payload.get('msg')}")
    return payload


def fetch_server_list(publisher_data: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
    response = requests.post(SERVER_LIST_URL, json={
        "openId": publisher_data["uid"], "clientVersion": CLIENT_VERSION,
        "pFullVersion": CLIENT_VERSION, "platform": "alipay", "channelId": CHANNEL_ID,
        "urlType": "", "packageMark": PACKAGE_ID, "language": "zh_cn",
    }, timeout=timeout)
    response.raise_for_status()
    return response.json()


def login_roles(publisher_data: dict[str, Any], servers: dict[str, Any],
                device_id: str, output_dir: Path, timeout: float = 30) -> list[dict[str, Any]]:
    owned = {str(value) for value in servers.get("playerServerList", [])}
    roles: list[dict[str, Any]] = []
    encoded_data = quote(json.dumps(publisher_data, ensure_ascii=False, separators=(",", ":")), safe="~()*!.'")
    for server in servers.get("serverList", []):
        if str(server.get("serverId")) not in owned:
            continue
        body = {
            "data": encoded_data, "loginType": 5, "deviceplate": "Windows",
            "deviceId": "PC-" + device_id.replace("-", "")[:30], "channelId": CHANNEL_ID,
            "appid": str(publisher_data["appid"]), "gameId": publisher_data["game_id"],
            "urlType": "", "packageId": PACKAGE_ID,
        }
        response = requests.post(server["address"] + "/player/login", json=body, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        save_json(output_dir, f"player-login-{server['serverId']}.json", payload)
        if payload.get("ret") != 0:
            continue
        roles.append({
            "serverId": server["serverId"], "serverName": server["serverName"],
            "labelName": server.get("labelName"), "playerId": payload.get("playerId"),
            "roleId": payload.get("roleId"), "nickName": payload.get("nickName"),
            "realmsId": payload.get("realmsId"), "wsAddress": payload.get("wsAddress"),
        })
    return roles


def fetch_roles(auth_code: str, output_dir: Path) -> list[dict[str, Any]]:
    device_id = str(uuid.uuid4())
    publisher = publisher_login(auth_code, device_id)
    save_json(output_dir, "publisher-login.json", publisher)
    servers = fetch_server_list(publisher["data"])
    save_json(output_dir, "server-list.json", servers)
    roles = login_roles(publisher["data"], servers, device_id, output_dir)
    save_json(output_dir, "roles-summary.json", roles)
    return roles


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Xundao Daqian role metadata")
    parser.add_argument("--login", type=Path, default=Path("login-output/login-success.json"))
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("login-output"))
    args = parser.parse_args()
    login = json.loads(args.login.read_text(encoding="utf-8-sig"))
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    game = fetch_game_data(login["data"]["token"], config["ctoken"], args.output_dir)
    roles = fetch_roles(game["auth"]["data"]["authCode"], args.output_dir)
    print(json.dumps(roles, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, requests.RequestException, RuntimeError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
