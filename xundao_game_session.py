#!/usr/bin/env python3
"""Authenticated game WebSocket session and guarded tree-chop automation."""

from __future__ import annotations

import json
import re
import struct
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

import websocket

HEADER = 29099
HEADER_SIZE = 18
PLAYER_LOGIN = 20001
PLAYER_PING = 20003
LOGIN_SYNC_OVER = 2
CHOP_TREE = 20203
CHOP_TREE_RESPONSE = 203
DEAL_EQUIPMENT = 20202
DEAL_EQUIPMENT_RESPONSE = 202
GET_PENDING_EQUIPMENT = 20209
GET_PENDING_EQUIPMENT_RESPONSE = 209
RANK_BATTLE_GET_LIST = 20410
RANK_BATTLE_GET_LIST_RESPONSE = 410
RANK_BATTLE_CHALLENGE = 20412
RANK_BATTLE_CHALLENGE_RESPONSE = 412
RANK_BATTLE_TICKET = 100026
RANK_BATTLE_TICKET_MAX = 3
PRIVILEGE_CARD_SYNC = 104
WILD_BOSS_GET_DATA = 20731
WILD_BOSS_SYNC = 731
WILD_BOSS_REPEAT = 20733
WILD_BOSS_REPEAT_RESPONSE = 733
WILD_BOSS_DAILY_MAX = 6
WILD_BOSS_MONTHLY_CARD_BONUS = 2
WILD_BOSS_MAX_WITH_MONTHLY_CARD = WILD_BOSS_DAILY_MAX + WILD_BOSS_MONTHLY_CARD_BONUS
INVADE_SYNC = 1402
INVADE_CHALLENGE = 21401
INVADE_CHALLENGE_RESPONSE = 1401
INVADE_DAILY_MAX = 5
STAR_TRIAL_SYNC = 6901
STAR_TRIAL_CHALLENGE = 206902
STAR_TRIAL_CHALLENGE_RESPONSE = 6902
STAR_TRIAL_DAILY_MAX = 30
HERO_RANK_SYNC = 3701
HERO_RANK_ENTER = 23700
HERO_RANK_ENTER_RESPONSE = 3700
HERO_RANK_GET_LIST = 23702
HERO_RANK_GET_LIST_RESPONSE = 3702
HERO_RANK_FIGHT = 23703
HERO_RANK_FIGHT_RESPONSE = 3703
HERO_RANK_ENERGY_MAX = 10
DESTINY_SYNC = 651
DESTINY_TRAVEL = 20653
DESTINY_TRAVEL_RESPONSE = 653
DESTINY_TRAVEL_COUNT_MAX = 30
PROFESSION_SYNC = 18002
PROFESSION_BATTLE = 218004
PROFESSION_BATTLE_RESPONSE = 18004
PROFESSION_QUICK_DAILY_MAX = 1
PROFESSION_CHALLENGE_DAILY_MAX = 30
YARD_ENTER = 215801
YARD_ENTER_RESPONSE = 15801
YARD_DRAW = 215822
YARD_DRAW_RESPONSE = 15822
YARD_BUILD_MAKE = 215825
YARD_BUILD_MAKE_RESPONSE = 15825
YARD_BUILD_GAIN_REWARD = 215827
YARD_BUILD_GAIN_REWARD_RESPONSE = 15827
YARD_LOGIN_SYNC = 15843
YARD_BUILD_STATUS_SYNC = 15848
YARD_MAKE_SYNC = 15849
YARD_BUILD_FARMLAND = 1001
YARD_BUILD_STOVE = 1002
YARD_BUILD_TREE = 1003
YARD_BUILD_CISTERN = 1004
YARD_FARMLAND_PRODUCT = 100158
YARD_DEFAULT_CROP = 400001
YARD_PRODUCT_INTERVAL_MS = 300_000
YARD_HERB_COST = 500
YARD_ALCHEMY_MAX = 999
YARD_DRAW_MAX = 100

ATTRIBUTE_NAMES = {
    1: "攻击", 2: "生命", 3: "防御", 4: "速度",
    5: "击晕", 6: "暴击", 7: "连击", 8: "闪避", 9: "反击", 10: "吸血",
    11: "抗击晕", 12: "抗暴击", 13: "抗连击", 14: "抗闪避", 15: "抗反击", 16: "抗吸血",
    17: "攻击加成", 18: "生命加成", 19: "防御加成", 20: "速度加成",
    21: "最终增伤", 22: "最终减伤", 23: "强化暴伤", 24: "弱化暴伤",
    25: "强化治疗", 26: "弱化治疗", 27: "强化灵兽", 28: "弱化灵兽",
    29: "强化战斗属性", 30: "弱化战斗抗性", 31: "强化道法伤害",
    32: "忽视战斗属性", 33: "忽视战斗抗性", 34: "弱化道法伤害",
    35: "格挡", 36: "抗格挡", 37: "破甲", 38: "抗破甲",
}

ITEM_NAMES = {
    100000: "仙玉",
    100003: "灵石",
    100007: "灵兽果",
    100016: "庚金",
    RANK_BATTLE_TICKET: "挑战状",
}


def _decimal_text(field: dict[str, Any]) -> str | None:
    text = field.get("text")
    if isinstance(text, str) and text.isdecimal():
        return text
    raw = field.get("raw")
    if isinstance(raw, bytes):
        try:
            value = raw.decode("ascii")
        except UnicodeDecodeError:
            return None
        if value.isdecimal():
            return value
    return None


def encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("Negative protobuf integers are not supported")
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift < 70:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ValueError("Invalid protobuf varint")


def protobuf_string(field: int, value: str) -> bytes:
    encoded = value.encode("utf-8")
    return encode_varint(field << 3 | 2) + encode_varint(len(encoded)) + encoded


def protobuf_int(field: int, value: int) -> bytes:
    return encode_varint(field << 3) + encode_varint(value)


def protobuf_packed_ints(field: int, values: list[int]) -> bytes:
    packed = b"".join(encode_varint(value) for value in values)
    return encode_varint(field << 3 | 2) + encode_varint(len(packed)) + packed


def parse_protobuf(data: bytes) -> list[dict[str, Any]]:
    """Decode wire fields without requiring the game's private .proto schema."""
    fields: list[dict[str, Any]] = []
    offset = 0
    while offset < len(data):
        key, offset = decode_varint(data, offset)
        number, wire = key >> 3, key & 7
        if not number:
            raise ValueError("Invalid protobuf field number")
        item: dict[str, Any] = {"field": number, "wire": wire}
        if wire == 0:
            item["value"], offset = decode_varint(data, offset)
        elif wire == 1:
            if offset + 8 > len(data):
                raise ValueError("Truncated fixed64 field")
            item["value"] = int.from_bytes(data[offset:offset + 8], "little")
            offset += 8
        elif wire == 2:
            length, offset = decode_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ValueError("Truncated length-delimited field")
            raw = data[offset:end]
            offset = end
            item["raw"] = raw
            try:
                item["children"] = parse_protobuf(raw) if raw else []
            except (ValueError, IndexError):
                try:
                    item["text"] = raw.decode("utf-8")
                except UnicodeDecodeError:
                    item["hex"] = raw.hex()
        elif wire == 5:
            if offset + 4 > len(data):
                raise ValueError("Truncated fixed32 field")
            item["value"] = int.from_bytes(data[offset:offset + 4], "little")
            offset += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type {wire}")
        fields.append(item)
    return fields


def _values(fields: list[dict[str, Any]], number: int) -> list[Any]:
    return [field.get("value") for field in fields if field["field"] == number and "value" in field]


def _children(fields: list[dict[str, Any]], number: int) -> list[list[dict[str, Any]]]:
    return [field["children"] for field in fields if field["field"] == number and "children" in field]


def _walk_messages(fields: list[dict[str, Any]]):
    yield fields
    for field in fields:
        children = field.get("children")
        if children is not None:
            yield from _walk_messages(children)


def parse_equipment(payload: bytes) -> list[dict[str, Any]]:
    """Find unDealEquipmentData messages in chop/pending-equipment responses."""
    root = parse_protobuf(payload)
    found: dict[int, dict[str, Any]] = {}
    for message in _walk_messages(root):
        ids = _values(message, 1)
        equipment_ids = _values(message, 2)
        realms_ids = _values(message, 3)
        qualities = _values(message, 4)
        sources = _values(message, 6)
        attrs = _children(message, 5)
        if not (ids and equipment_ids and realms_ids and qualities and sources and attrs):
            continue
        # The unique pending ID is seven digits, while equipmentId is the
        # shorter equipment-table key. Quality is field 4 and can exceed 20
        # at higher tree levels; field 3 is the realm/config progression ID.
        if int(ids[0]) < 1_000_000 or not 0 < int(equipment_ids[0]) < 1_000_000:
            continue
        if not 0 < int(qualities[0]) <= 100 or int(sources[0]) <= 0:
            continue
        attributes = []
        for attr in attrs:
            types = _values(attr, 1)
            values = next((field.get("text") for field in attr if field["field"] == 2 and "text" in field), None)
            if types and values is not None:
                attribute_type = int(types[0])
                attributes.append({
                    "type": attribute_type,
                    "name": ATTRIBUTE_NAMES.get(attribute_type, f"属性{attribute_type}"),
                    "value": values,
                })
        equipment_id = int(ids[0])
        found[equipment_id] = {
            "id": equipment_id,
            "equipmentId": int(equipment_ids[0]),
            "realmId": int(realms_ids[0]),
            "quality": int(qualities[0]),
            "src": int(sources[0]),
            "attributes": attributes,
        }
    return list(found.values())


def parse_chop_rewards(payload: bytes) -> list[dict[str, Any]]:
    rewards: dict[int, int] = {}
    for drop in _children(parse_protobuf(payload), 2):
        reward_field = next((field for field in drop if field["field"] == 1 and "raw" in field), None)
        if reward_field is None or not reward_field["raw"]:
            continue
        try:
            reward_text = reward_field["raw"].decode("utf-8")
        except UnicodeDecodeError:
            continue
        for item_id, count in re.findall(r"(\d+)=(\d+)", reward_text):
            rewards[int(item_id)] = rewards.get(int(item_id), 0) + int(count)
    return [
        {"id": item_id, "name": ITEM_NAMES.get(item_id, f"物品 {item_id}"), "count": count}
        for item_id, count in rewards.items()
    ]


def parse_equipped_items(payload: bytes) -> list[dict[str, Any]]:
    """Parse the active character's equipped items from message 201."""
    items: list[dict[str, Any]] = []
    for message in _children(parse_protobuf(payload), 5):
        ids = _values(message, 1)
        equipment_ids = _values(message, 2)
        realms_ids = _values(message, 3)
        qualities = _values(message, 4)
        sources = _values(message, 6)
        if not (ids and equipment_ids and realms_ids and qualities):
            continue
        attributes = []
        for attr in _children(message, 5):
            types = _values(attr, 1)
            value = next((field.get("text") for field in attr if field["field"] == 2 and "text" in field), None)
            if types and value is not None:
                attribute_type = int(types[0])
                attributes.append({
                    "type": attribute_type,
                    "name": ATTRIBUTE_NAMES.get(attribute_type, f"属性{attribute_type}"),
                    "value": value,
                })
        equipment_id = int(equipment_ids[0])
        items.append({
            "id": int(ids[0]), "equipmentId": equipment_id,
            "slot": equipment_id // 100, "realmId": int(realms_ids[0]),
            "quality": int(qualities[0]), "src": int(sources[0]) if sources else 0,
            "attributes": attributes,
        })
    return items


def make_frame(message_id: int, player_id: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HIIQ", HEADER, HEADER_SIZE + len(payload), message_id, player_id) + payload


def parse_frame(frame: bytes) -> tuple[int, int, bytes]:
    if len(frame) < HEADER_SIZE:
        raise RuntimeError("Game frame is shorter than its 18-byte header")
    header, length, message_id, player_id = struct.unpack(">HIIQ", frame[:HEADER_SIZE])
    if header != HEADER or length != len(frame):
        raise RuntimeError("Invalid game frame header")
    return message_id, player_id, frame[HEADER_SIZE:]


def response_ret(payload: bytes) -> int | None:
    try:
        fields = parse_protobuf(payload)
    except ValueError:
        return None
    values = _values(fields, 1)
    return int(values[0]) if values else None


def parse_wild_boss_used_times(payload: bytes) -> int | None:
    """Read WildBossDataSync.data.useRepeatTimes."""
    data = _children(parse_protobuf(payload), 1)
    if not data:
        return None
    values = _values(data[0], 2)
    return int(values[0]) if values else None


def parse_monthly_card_end_time(payload: bytes) -> int:
    values = _values(parse_protobuf(payload), 1)
    return int(values[0]) if values else 0


def wild_boss_daily_max(frames: list[tuple[int, bytes]], now: float | None = None) -> int:
    end_time = next(
        (
            parse_monthly_card_end_time(payload)
            for message_id, payload in reversed(frames)
            if message_id == PRIVILEGE_CARD_SYNC
        ),
        0,
    )
    current = time.time() if now is None else now
    active = end_time > (current * 1000 if end_time >= 1_000_000_000_000 else current)
    return WILD_BOSS_MAX_WITH_MONTHLY_CARD if active else WILD_BOSS_DAILY_MAX


def parse_invade_used_times(payload: bytes) -> int | None:
    values = _values(parse_protobuf(payload), 3)
    return int(values[0]) if values else None


def parse_star_trial_state(payload: bytes) -> tuple[int, int] | None:
    fields = parse_protobuf(payload)
    boss_ids = _values(fields, 1)
    remaining = _values(fields, 2)
    if not boss_ids or not remaining:
        return None
    return int(boss_ids[0]), int(remaining[0])


def parse_hero_rank_energy(payload: bytes) -> int | None:
    player_info = _children(parse_protobuf(payload), 1)
    if not player_info:
        return None
    energy = _values(player_info[0], 1)
    return int(energy[0]) if energy else None


def parse_hero_rank_enter_energy(payload: bytes) -> int | None:
    player_info = _children(parse_protobuf(payload), 2)
    if not player_info:
        return None
    energy = _values(player_info[0], 1)
    return int(energy[0]) if energy else None


def parse_destiny_power(payload: bytes) -> int | None:
    """Read DestinyData.playerDestinyDataMsg.power."""
    player_data = _children(parse_protobuf(payload), 2)
    if not player_data:
        return None
    power = _values(player_data[0], 1)
    return int(power[0]) if power else None


def parse_profession_state(payload: bytes) -> dict[str, int] | None:
    fields = parse_protobuf(payload)
    career_types = _values(fields, 1)
    boss_data = _children(fields, 4)
    if not career_types or not boss_data:
        return None
    passed = _values(boss_data[0], 1)
    battle_times = _values(boss_data[0], 2)
    repeat_times = _values(boss_data[0], 3)
    return {
        "careerType": int(career_types[0]),
        "lastPassedBossId": int(passed[0]) if passed else 0,
        "battleTimesToday": int(battle_times[0]) if battle_times else 0,
        "repeatTimesToday": int(repeat_times[0]) if repeat_times else 0,
    }


def parse_profession_battle_win(payload: bytes) -> bool | None:
    battle_records = _children(parse_protobuf(payload), 2)
    if not battle_records:
        return None
    values = _values(battle_records[0], 3)
    return bool(values[0]) if values else None


def parse_yard_buildings(payload: bytes) -> dict[int, dict[str, int]]:
    """Decode the four functional buildings from YardEnterResp."""
    buildings: dict[int, dict[str, int]] = {}
    for area in _children(parse_protobuf(payload), 2):
        for building in _children(area, 3):
            cells = _children(building, 1)
            details = _children(building, 2)
            if not cells or not details:
                continue
            unique_ids = _values(cells[0], 1)
            build_ids = _values(cells[0], 2)
            if not unique_ids or not build_ids:
                continue
            build_id = int(build_ids[0])
            if build_id not in {
                YARD_BUILD_FARMLAND, YARD_BUILD_STOVE,
                YARD_BUILD_TREE, YARD_BUILD_CISTERN,
            }:
                continue
            detail = details[0]
            values = {
                "uniqueId": int(unique_ids[0]),
                "buildId": build_id,
                "level": int((_values(detail, 1) or [0])[0]),
                "status": int((_values(detail, 2) or [0])[0]),
                "productId": int((_values(detail, 3) or [0])[0]),
                "startTime": int((_values(detail, 4) or [0])[0]),
                "endTime": int((_values(detail, 5) or [0])[0]),
                "collectNum": int((_values(detail, 6) or [0])[0]),
                "totalNum": int((_values(detail, 8) or [0])[0]),
            }
            buildings[build_id] = values
    return buildings


def parse_yard_draw_data(payload: bytes) -> dict[str, int]:
    draw_messages = _children(parse_protobuf(payload), 8)
    if not draw_messages:
        return {"freeDrawTimes": 0, "drawCount": 0, "ensureCount": 0, "adCount": 0}
    draw = draw_messages[0]
    return {
        "freeDrawTimes": int((_values(draw, 1) or [0])[0]),
        "drawCount": int((_values(draw, 2) or [0])[0]),
        "ensureCount": int((_values(draw, 3) or [0])[0]),
        "adCount": int((_values(draw, 4) or [0])[0]),
    }


def yard_build_finished(building: dict[str, int], now_ms: int | None = None) -> bool:
    if building.get("status") != 1 or building.get("startTime", 0) <= 0:
        return False
    current = int(time.time() * 1000) if now_ms is None else now_ms
    end_time = building.get("endTime", 0)
    if end_time > 0:
        return current >= end_time
    if building.get("buildId") == YARD_BUILD_CISTERN:
        remaining = max(0, building.get("totalNum", 0) - building.get("collectNum", 0))
        return remaining > 0 and current >= building["startTime"] + remaining * YARD_PRODUCT_INTERVAL_MS
    return False


def yard_continuous_reward_available(
    building: dict[str, int], now_ms: int | None = None,
) -> bool:
    if building.get("status") != 1 or building.get("startTime", 0) <= 0:
        return False
    if building.get("collectNum", 0) > 0:
        return True
    current = int(time.time() * 1000) if now_ms is None else now_ms
    return current - building["startTime"] >= YARD_PRODUCT_INTERVAL_MS


class GameSession:
    def __init__(self, ws_address: str, player_id: int, token: str, timeout: float = 30) -> None:
        self.ws_address = ws_address
        self.player_id = int(player_id)
        self.token = token
        self.timeout = timeout
        self.socket: websocket.WebSocket | None = None
        self.login_frames: list[tuple[int, bytes]] = []
        self.observed_frames: list[tuple[int, bytes]] = []
        self.equipped_items: list[dict[str, Any]] = []
        self.god_body_id = 0
        self._hero_rank_candidates: list[dict[str, Any]] | None = None
        self._hero_rank = 0
        self._last_ping = 0.0

    def connect(self) -> None:
        self.socket = websocket.create_connection(
            self.ws_address, timeout=self.timeout, origin="https://www.wanyiwan.top", http_proxy_host=None
        )
        payload = protobuf_string(1, self.token) + protobuf_string(2, "zh_cn") + protobuf_int(3, 0)
        self.socket.send_binary(make_frame(PLAYER_LOGIN, self.player_id, payload))
        self.login_frames = self._collect_login_sync()
        self.observed_frames = list(self.login_frames)
        player_data = [payload for message_id, payload in self.login_frames if message_id == 201]
        if player_data:
            self.equipped_items = parse_equipped_items(player_data[-1])
            body_ids = _values(parse_protobuf(player_data[-1]), 6)
            self.god_body_id = int(body_ids[0]) if body_ids else 0
        self._send_heartbeat(force=True)

    def _send_heartbeat(self, force: bool = False) -> None:
        if self.socket is None:
            raise RuntimeError("Game session is not connected")
        now = time.monotonic()
        if force or now - self._last_ping >= 5:
            self.socket.send_binary(make_frame(PLAYER_PING, self.player_id))
            self._last_ping = now

    def _collect_login_sync(self, timeout_messages: int = 400) -> list[tuple[int, bytes]]:
        if self.socket is None:
            raise RuntimeError("Game session is not connected")
        frames: list[tuple[int, bytes]] = []
        for _ in range(timeout_messages):
            data = self.socket.recv()
            if not isinstance(data, bytes):
                continue
            message_id, player_id, payload = parse_frame(data)
            if player_id != self.player_id:
                continue
            frames.append((message_id, payload))
            if message_id == LOGIN_SYNC_OVER:
                return frames
        raise RuntimeError("Timed out waiting for game login synchronization")

    def _wait_for(self, target_message_id: int, timeout_messages: int = 100) -> bytes:
        if self.socket is None:
            raise RuntimeError("Game session is not connected")
        for _ in range(timeout_messages):
            data = self.socket.recv()
            if not isinstance(data, bytes):
                continue
            message_id, player_id, payload = parse_frame(data)
            if player_id == self.player_id:
                self.observed_frames.append((message_id, payload))
            if player_id == self.player_id and message_id == target_message_id:
                return payload
        raise RuntimeError(f"Timed out waiting for game message {target_message_id}")

    def _request(self, message_id: int, response_id: int, payload: bytes = b"") -> bytes:
        if self.socket is None:
            self.connect()
        assert self.socket is not None
        self._send_heartbeat()
        self.socket.send_binary(make_frame(message_id, self.player_id, payload))
        return self._wait_for(response_id)

    def get_pending_equipment(self) -> list[dict[str, Any]]:
        return parse_equipment(self._request(GET_PENDING_EQUIPMENT, GET_PENDING_EQUIPMENT_RESPONSE))

    def chop_tree(self, times: int = 1, auto: bool = False) -> dict[str, Any]:
        if times < 1:
            raise ValueError("Tree-chop times must be positive")
        payload = protobuf_int(1, int(auto)) + protobuf_int(3, times)
        response = self._request(CHOP_TREE, CHOP_TREE_RESPONSE, payload)
        # The chop response also embeds the player's existing slot equipment;
        # the newly dropped pending item is the first equipment message.
        equipment = parse_equipment(response)
        return {
            "ret": response_ret(response), "equipment": equipment[:1],
            "rewards": parse_chop_rewards(response), "payloadHex": response.hex(),
        }

    def item_count(self, item_id: int) -> int:
        inventory: dict[int, int] = {}
        for message_id, payload in self.observed_frames:
            if message_id != 301:
                continue
            for item in _children(parse_protobuf(payload), 1):
                item_ids = _values(item, 1)
                count = next(
                    (_decimal_text(field) for field in item if field["field"] == 2),
                    None,
                )
                if item_ids and count is not None:
                    inventory[int(item_ids[0])] = int(count)
        return inventory.get(item_id, 0)

    def rank_battle(self) -> dict[str, Any]:
        list_payload = self._request(RANK_BATTLE_GET_LIST, RANK_BATTLE_GET_LIST_RESPONSE)
        if response_ret(list_payload) != 0:
            return {"ret": response_ret(list_payload), "reason": "list_failed"}
        opponents = []
        now_ms = int(time.time() * 1000)
        for index, entry in enumerate(_children(parse_protobuf(list_payload), 2)):
            players = _children(entry, 1)
            if not players:
                continue
            player = players[0]
            names = next((field.get("text") for field in player if field["field"] == 3 and "text" in field), "未知对手")
            powers = _values(player, 5)
            protect_times = _values(entry, 3)
            protect_end = int(protect_times[0]) if protect_times else 0
            if protect_end > now_ms:
                continue
            opponents.append({"index": index, "name": names, "power": int(powers[0]) if powers else 0})
        if not opponents:
            return {"ret": None, "reason": "no_opponent"}
        opponent = min(opponents, key=lambda value: value["power"])
        response = self._request(
            RANK_BATTLE_CHALLENGE, RANK_BATTLE_CHALLENGE_RESPONSE,
            protobuf_int(1, opponent["index"]),
        )
        return {
            "ret": response_ret(response), "reason": "challenged",
            "opponent": opponent, "payloadHex": response.hex(),
        }

    def wild_boss_remaining(self, refresh: bool = True) -> int | None:
        if refresh:
            try:
                self._request(WILD_BOSS_GET_DATA, WILD_BOSS_SYNC)
            except (RuntimeError, TimeoutError, websocket.WebSocketException):
                pass
        daily_max = wild_boss_daily_max(self.observed_frames)
        for message_id, payload in reversed(self.observed_frames):
            if message_id == WILD_BOSS_SYNC:
                used = parse_wild_boss_used_times(payload)
                if used is not None:
                    return max(0, daily_max - used)
        return None

    def repeat_wild_boss(self) -> dict[str, Any]:
        response = self._request(WILD_BOSS_REPEAT, WILD_BOSS_REPEAT_RESPONSE)
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def invade_state(self) -> tuple[int, int]:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == INVADE_SYNC:
                used = parse_invade_used_times(payload)
                if used is not None:
                    return used, max(0, INVADE_DAILY_MAX - used)
        return INVADE_DAILY_MAX, 0

    def challenge_invade(self) -> dict[str, Any]:
        response = self._request(INVADE_CHALLENGE, INVADE_CHALLENGE_RESPONSE)
        used = None
        sync = _children(parse_protobuf(response), 5)
        if sync:
            values = _values(sync[0], 3)
            used = int(values[0]) if values else None
        return {"ret": response_ret(response), "used": used, "payloadHex": response.hex()}

    def star_trial_state(self) -> tuple[int, int]:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == STAR_TRIAL_SYNC:
                state = parse_star_trial_state(payload)
                if state is not None:
                    return state
        return 0, 0

    def challenge_star_trial(self, boss_id: int) -> dict[str, Any]:
        response = self._request(
            STAR_TRIAL_CHALLENGE, STAR_TRIAL_CHALLENGE_RESPONSE,
            protobuf_int(1, boss_id),
        )
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def hero_rank_energy(self, refresh: bool = True) -> int | None:
        if refresh:
            try:
                response = self._request(HERO_RANK_ENTER, HERO_RANK_ENTER_RESPONSE)
                if response_ret(response) == 0:
                    ranks = _values(parse_protobuf(response), 4)
                    self._hero_rank = int(ranks[0]) if ranks else 0
                    fight_lists = _children(parse_protobuf(response), 3)
                    self._hero_rank_candidates = (
                        _children(fight_lists[0], 2) if fight_lists else []
                    )
                    energy = parse_hero_rank_enter_energy(response)
                    if energy is not None:
                        return energy
            except (RuntimeError, TimeoutError, websocket.WebSocketException):
                pass
        for message_id, payload in reversed(self.observed_frames):
            if message_id == HERO_RANK_SYNC:
                energy = parse_hero_rank_energy(payload)
                if energy is not None:
                    return energy
        return None

    def destiny_power(self) -> int | None:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == DESTINY_SYNC:
                power = parse_destiny_power(payload)
                if power is not None:
                    return power
        return None

    def travel_destiny(self) -> dict[str, Any]:
        response = self._request(
            DESTINY_TRAVEL, DESTINY_TRAVEL_RESPONSE,
            protobuf_int(1, 0),
        )
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def profession_state(self) -> dict[str, int] | None:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == PROFESSION_SYNC:
                state = parse_profession_state(payload)
                if state is not None:
                    return state
        return None

    def profession_battle(self, boss_id: int, battle_type: int) -> dict[str, Any]:
        if boss_id <= 0 or battle_type not in (1, 2):
            raise ValueError("Invalid profession boss battle parameters")
        response = self._request(
            PROFESSION_BATTLE, PROFESSION_BATTLE_RESPONSE,
            protobuf_int(1, boss_id) + protobuf_int(2, battle_type),
        )
        return {
            "ret": response_ret(response),
            "win": parse_profession_battle_win(response),
            "payloadHex": response.hex(),
        }

    def enter_yard(self) -> dict[str, Any]:
        response = self._request(
            YARD_ENTER, YARD_ENTER_RESPONSE,
            protobuf_int(2, self.player_id),
        )
        return {
            "ret": response_ret(response),
            "buildings": parse_yard_buildings(response),
            "drawData": parse_yard_draw_data(response),
            "payloadHex": response.hex(),
        }

    def yard_grass_num(self) -> int | None:
        for message_id, payload in reversed(self.observed_frames):
            if message_id not in (YARD_LOGIN_SYNC, YARD_MAKE_SYNC):
                continue
            fields = parse_protobuf(payload)
            grass = next(
                (_decimal_text(field) for field in fields if field["field"] == 2),
                None,
            )
            if grass is not None:
                return int(grass)
        return None

    def yard_collect(self, building: dict[str, int]) -> dict[str, Any]:
        response = self._request(
            YARD_BUILD_GAIN_REWARD, YARD_BUILD_GAIN_REWARD_RESPONSE,
            protobuf_int(1, building["uniqueId"])
            + protobuf_int(2, building["buildId"]),
        )
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def yard_make(
        self, building: dict[str, int], count: int,
        product_id: int | None = None,
    ) -> dict[str, Any]:
        if count <= 0:
            raise ValueError("Yard production count must be positive")
        payload = (
            protobuf_int(1, building["uniqueId"])
            + protobuf_int(2, building["buildId"])
        )
        if product_id is not None:
            payload += protobuf_int(3, product_id)
        payload += protobuf_int(4, count) + protobuf_int(5, 0)
        response = self._request(YARD_BUILD_MAKE, YARD_BUILD_MAKE_RESPONSE, payload)
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def yard_draw(self, ten: bool = False) -> dict[str, Any]:
        payload = (
            protobuf_int(1, int(ten))
            + protobuf_int(2, 0)
            + protobuf_int(3, 0)
            + protobuf_int(4, 0)
        )
        response = self._request(YARD_DRAW, YARD_DRAW_RESPONSE, payload)
        fields = parse_protobuf(response)
        rewards = len(_children(fields, 2))
        return {
            "ret": response_ret(response),
            "count": rewards or (10 if ten else 1),
            "payloadHex": response.hex(),
        }

    def hero_rank_fight(self, rank_change_retries: int = 0) -> dict[str, Any]:
        if self._hero_rank_candidates is None:
            list_response = self._request(
                HERO_RANK_GET_LIST, HERO_RANK_GET_LIST_RESPONSE,
                protobuf_int(1, 0),
            )
            if response_ret(list_response) != 0:
                return {"ret": response_ret(list_response), "reason": "list_failed"}
            list_fields = parse_protobuf(list_response)
            ranks = _values(list_fields, 4)
            self._hero_rank = int(ranks[0]) if ranks else self._hero_rank
            fight_lists = _children(list_fields, 2)
            self._hero_rank_candidates = _children(fight_lists[0], 2) if fight_lists else []
        candidates = self._hero_rank_candidates
        opponents = []
        for candidate in candidates:
            ranks = _values(candidate, 1)
            appearances = _children(candidate, 2)
            master_ids = _values(candidate, 3)
            master_levels = _values(candidate, 4)
            if not ranks or not appearances:
                continue
            appearance = appearances[0]
            player_ids = _values(appearance, 1)
            powers = next(
                (_decimal_text(field) for field in appearance if field["field"] == 4),
                None,
            )
            appearance_ids = _values(appearance, 5)
            cloud_ids = _values(appearance, 6)
            names = next(
                (field.get("text") for field in appearance if field["field"] == 2 and "text" in field),
                "未知对手",
            )
            opponents.append({
                "targetId": int(player_ids[0]) if player_ids else 0,
                "rank": int(ranks[0]),
                "masterId": int(master_ids[0]) if master_ids else 0,
                "masterLv": int(master_levels[0]) if master_levels else 0,
                "appearanceId": int(appearance_ids[0]) if appearance_ids else 0,
                "cloudId": int(cloud_ids[0]) if cloud_ids else 0,
                "name": names,
                "power": int(powers) if powers is not None else 0,
            })
        opponents = [
            opponent for opponent in opponents
            if opponent["targetId"] != self.player_id
            and (self._hero_rank <= 0 or opponent["rank"] < self._hero_rank)
        ]
        if not opponents:
            return {"ret": None, "reason": "no_opponent"}
        opponent = min(opponents, key=lambda value: value["power"])
        is_robot = opponent["targetId"] == 0
        payload = b"".join([
            protobuf_int(1, opponent["targetId"]),
            protobuf_int(2, opponent["rank"]),
            protobuf_int(3, opponent["masterId"] if is_robot else 0),
            protobuf_int(4, opponent["masterLv"] if is_robot else 0),
            protobuf_int(5, opponent["appearanceId"] if is_robot else 0),
            protobuf_int(6, opponent["cloudId"] if is_robot else 0),
        ])
        response = self._request(HERO_RANK_FIGHT, HERO_RANK_FIGHT_RESPONSE, payload)
        fields = parse_protobuf(response)
        ret = response_ret(response)
        if ret == 3709 and rank_change_retries < 3:
            list_response = self._request(
                HERO_RANK_GET_LIST, HERO_RANK_GET_LIST_RESPONSE,
                protobuf_int(1, 0),
            )
            if response_ret(list_response) != 0:
                return {"ret": response_ret(list_response), "reason": "list_failed"}
            list_fields = parse_protobuf(list_response)
            ranks = _values(list_fields, 4)
            self._hero_rank = int(ranks[0]) if ranks else self._hero_rank
            fight_lists = _children(list_fields, 2)
            self._hero_rank_candidates = _children(fight_lists[0], 2) if fight_lists else []
            return self.hero_rank_fight(rank_change_retries + 1)
        if ret == 0:
            ranks = _values(fields, 3)
            self._hero_rank = int(ranks[0]) if ranks else self._hero_rank
            fight_lists = _children(fields, 7)
            self._hero_rank_candidates = _children(fight_lists[0], 2) if fight_lists else []
        player_info = _children(fields, 2)
        energy_values = _values(player_info[0], 1) if player_info else []
        return {
            "ret": ret, "reason": "challenged", "opponent": opponent,
            "energy": int(energy_values[0]) if energy_values else None,
            "payloadHex": response.hex(),
        }

    def decompose(self, equipment_ids: list[int]) -> dict[str, Any]:
        if not equipment_ids:
            raise ValueError("No equipment selected for decomposition")
        # protobufjs encodes repeated numeric proto3 fields in packed form.
        payload = protobuf_int(1, 1) + protobuf_packed_ints(2, equipment_ids)
        response = self._request(DEAL_EQUIPMENT, DEAL_EQUIPMENT_RESPONSE, payload)
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def equip_and_resolve(self, equipment: dict[str, Any]) -> dict[str, Any]:
        payload = (
            protobuf_int(1, 2)
            + protobuf_packed_ints(2, [equipment["id"]])
            + protobuf_int(3, self.god_body_id)
        )
        response = self._request(DEAL_EQUIPMENT, DEAL_EQUIPMENT_RESPONSE, payload)
        result = {"ret": response_ret(response), "payloadHex": response.hex()}
        if result["ret"] == 0:
            slot = equipment["equipmentId"] // 100
            self.equipped_items = [item for item in self.equipped_items if item["slot"] != slot]
            self.equipped_items.append({**equipment, "slot": slot})
        return result

    def equipped_for(self, equipment: dict[str, Any]) -> dict[str, Any] | None:
        slot = equipment["equipmentId"] // 100
        return next((item for item in self.equipped_items if item["slot"] == slot), None)

    def resource_snapshot(self, server_id: int, refresh_wild_boss: bool = False) -> dict[str, Any]:
        if refresh_wild_boss:
            self.wild_boss_remaining(refresh=True)
        return _snapshot_from_frames(server_id, self.observed_frames)

    def close(self) -> None:
        if self.socket is not None:
            self.socket.close()
            self.socket = None
            self._last_ping = 0.0

    def __enter__(self) -> "GameSession":
        self.connect()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def _load_login(server_id: int, output_dir: Path) -> dict[str, Any]:
    return json.loads((output_dir / f"player-login-{server_id}.json").read_text(encoding="utf-8-sig"))


def _snapshot_from_frames(server_id: int, frames: list[tuple[int, bytes]]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "serverId": server_id, "spiritStone": 0, "jade": 0,
        "power": "0", "cultivation": "0", "realmId": 0,
    }
    inventory: dict[int, int] = {}
    for message_id, payload in frames:
        fields = parse_protobuf(payload)
        if message_id == 201:
            realm = _values(fields, 1)
            cultivation = next((field.get("text") for field in fields if field["field"] == 2 and "text" in field), None)
            power = next((field.get("text") for field in fields if field["field"] == 3 and "text" in field), None)
            if realm:
                snapshot["realmId"] = int(realm[0])
            if power is not None:
                snapshot["power"] = power
            if cultivation is not None:
                snapshot["cultivation"] = cultivation
        elif message_id == 301:
            for item in _children(fields, 1):
                item_ids = _values(item, 1)
                count = next(
                    (_decimal_text(field) for field in item if field["field"] == 2),
                    None,
                )
                if item_ids and count is not None:
                    inventory[int(item_ids[0])] = int(count)
    snapshot["jade"] = inventory.get(100000, 0)
    snapshot["spiritStone"] = inventory.get(100003, 0)
    snapshot["rankBattleTicket"] = min(RANK_BATTLE_TICKET_MAX, inventory.get(RANK_BATTLE_TICKET, 0))
    daily_max = wild_boss_daily_max(frames)
    used_times = next(
        (
            used
            for message_id, payload in reversed(frames)
            if message_id == WILD_BOSS_SYNC
            for used in [parse_wild_boss_used_times(payload)]
            if used is not None
        ),
        None,
    )
    snapshot["wildBossDailyMax"] = daily_max
    snapshot["wildBossRemaining"] = (
        max(0, daily_max - used_times) if used_times is not None else None
    )
    invade_used = next(
        (
            used
            for message_id, payload in reversed(frames)
            if message_id == INVADE_SYNC
            for used in [parse_invade_used_times(payload)]
            if used is not None
        ),
        INVADE_DAILY_MAX,
    )
    snapshot["invadeRemaining"] = max(0, INVADE_DAILY_MAX - invade_used)
    star_state = next(
        (
            state
            for message_id, payload in reversed(frames)
            if message_id == STAR_TRIAL_SYNC
            for state in [parse_star_trial_state(payload)]
            if state is not None
        ),
        (0, 0),
    )
    snapshot["starTrialRemaining"] = star_state[1]
    hero_energy = next(
        (
            energy
            for message_id, payload in reversed(frames)
            if message_id in (HERO_RANK_ENTER_RESPONSE, HERO_RANK_SYNC)
            for energy in [
                parse_hero_rank_enter_energy(payload)
                if message_id == HERO_RANK_ENTER_RESPONSE
                else parse_hero_rank_energy(payload)
            ]
            if energy is not None
        ),
        0,
    )
    snapshot["heroRankEnergy"] = hero_energy
    snapshot["destinyPower"] = next(
        (
            power
            for message_id, payload in reversed(frames)
            if message_id == DESTINY_SYNC
            for power in [parse_destiny_power(payload)]
            if power is not None
        ),
        None,
    )
    profession_state = next(
        (
            state
            for message_id, payload in reversed(frames)
            if message_id == PROFESSION_SYNC
            for state in [parse_profession_state(payload)]
            if state is not None
        ),
        None,
    )
    snapshot["professionLastBossId"] = (
        profession_state["lastPassedBossId"] if profession_state is not None else None
    )
    snapshot["professionQuickRemaining"] = (
        max(0, PROFESSION_QUICK_DAILY_MAX - profession_state["repeatTimesToday"])
        if profession_state is not None else None
    )
    snapshot["professionChallengeRemaining"] = (
        max(0, PROFESSION_CHALLENGE_DAILY_MAX - profession_state["battleTimesToday"])
        if profession_state is not None else None
    )
    return snapshot


def fetch_role_snapshot(server_id: int, output_dir: Path) -> dict[str, Any]:
    """Read currency and player attributes from the login synchronization stream."""
    login = _load_login(server_id, output_dir)
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        return session.resource_snapshot(server_id, refresh_wild_boss=True)


def run_wild_boss_tasks(
    server_id: int,
    output_dir: Path,
    count: int,
    log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Repeat the wild boss up to the selected count and today's remainder."""
    if not 1 <= count <= WILD_BOSS_MAX_WITH_MONTHLY_CARD:
        raise ValueError("Wild boss count must be between 1 and 8")
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        remaining = session.wild_boss_remaining()
        daily_max = wild_boss_daily_max(session.observed_frames)
        if remaining is None:
            log("妖王剩余次数读取失败，本次不会发起挑战。")
            return {"ret": None, "completed": 0, "remaining": None, "reason": "wild_boss_state_unknown"}
        target = min(count, remaining)
        log(f"妖王今日剩余 {remaining}/{daily_max} 次，计划挑战 {target} 次。")
        initial = session.resource_snapshot(server_id)
        initial["wildBossRemaining"] = remaining
        initial["wildBossDailyMax"] = daily_max
        if snapshot is not None:
            snapshot(initial)
        for _ in range(target):
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": completed, "remaining": remaining, "reason": "stopped"}
            result = session.repeat_wild_boss()
            if result["ret"] != 0:
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": remaining, "reason": "wild_boss_failed",
                }
            completed += 1
            remaining -= 1
            value = session.resource_snapshot(server_id)
            value["wildBossRemaining"] = remaining
            if snapshot is not None:
                snapshot(value)
            log(f"第 {completed}/{target} 次妖王挑战完成，今日剩余 {remaining} 次。")
        return {"ret": 0, "completed": completed, "remaining": remaining, "reason": "finished"}


def run_invade_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not 1 <= count <= INVADE_DAILY_MAX:
        raise ValueError("Invade count must be between 1 and 5")
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        used, remaining = session.invade_state()
        target = min(count, remaining)
        log(f"异兽入侵今日剩余 {remaining}/{INVADE_DAILY_MAX} 次，计划挑战 {target} 次。")
        for _ in range(target):
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": completed, "remaining": remaining, "reason": "stopped"}
            result = session.challenge_invade()
            if result["ret"] != 0:
                return {"ret": result["ret"], "completed": completed, "remaining": remaining, "reason": "invade_failed"}
            completed += 1
            used = result["used"] if result["used"] is not None else used + 1
            remaining = max(0, INVADE_DAILY_MAX - used)
            value = session.resource_snapshot(server_id); value["invadeRemaining"] = remaining
            if snapshot is not None: snapshot(value)
            log(f"第 {completed}/{target} 次异兽入侵完成，今日剩余 {remaining} 次。")
        return {"ret": 0, "completed": completed, "remaining": remaining, "reason": "finished"}


def run_star_trial_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not 1 <= count <= STAR_TRIAL_DAILY_MAX:
        raise ValueError("Star trial count must be between 1 and 30")
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        boss_id, remaining = session.star_trial_state()
        target = min(count, remaining)
        log(f"星宿试炼今日剩余 {remaining}/{STAR_TRIAL_DAILY_MAX} 次，计划挑战 {target} 次。")
        if boss_id <= 0 and target:
            return {"ret": None, "completed": 0, "remaining": remaining, "reason": "star_trial_no_boss"}
        for _ in range(target):
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": completed, "remaining": remaining, "reason": "stopped"}
            result = session.challenge_star_trial(boss_id)
            if result["ret"] != 0:
                return {"ret": result["ret"], "completed": completed, "remaining": remaining, "reason": "star_trial_failed"}
            completed += 1
            synced_boss_id, synced_remaining = session.star_trial_state()
            if synced_remaining < remaining:
                remaining = synced_remaining
                if synced_boss_id > 0:
                    boss_id = synced_boss_id
            else:
                remaining -= 1
            value = session.resource_snapshot(server_id); value["starTrialRemaining"] = remaining
            if snapshot is not None: snapshot(value)
            log(f"第 {completed}/{target} 次星宿试炼完成，今日剩余 {remaining} 次。")
        return {"ret": 0, "completed": completed, "remaining": remaining, "reason": "finished"}


def run_hero_rank_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not 1 <= count <= HERO_RANK_ENERGY_MAX:
        raise ValueError("Hero rank count must be between 1 and 10")
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        energy = session.hero_rank_energy()
        if energy is None:
            log("群英榜体力读取失败，本次不会发起挑战。")
            return {"ret": None, "completed": 0, "remaining": None, "reason": "hero_rank_energy_unknown"}
        target = min(count, energy)
        log(f"群英榜当前体力 {energy}/{HERO_RANK_ENERGY_MAX}，计划挑战 {target} 次。")
        for _ in range(target):
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": completed, "remaining": energy, "reason": "stopped"}
            result = session.hero_rank_fight()
            if result["ret"] != 0:
                return {"ret": result["ret"], "completed": completed, "remaining": energy, "reason": result["reason"]}
            completed += 1
            energy = result["energy"] if result["energy"] is not None else max(0, energy - 1)
            value = session.resource_snapshot(server_id); value["heroRankEnergy"] = energy
            if snapshot is not None: snapshot(value)
            opponent = result["opponent"]
            log(f"群英榜挑战 {opponent['name']} 完成，当前体力 {energy}。")
        return {"ret": 0, "completed": completed, "remaining": energy, "reason": "finished"}


def run_destiny_travel_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not 1 <= count <= DESTINY_TRAVEL_COUNT_MAX:
        raise ValueError("Destiny travel count must be between 1 and 30")
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        power = session.destiny_power()
        if power is None:
            target = count
            log(f"当前连接未收到仙友体力同步，将按所选上限尝试游历 {target} 次。")
        else:
            target = min(count, power)
            log(f"仙友游历当前体力 {power}，计划游历 {target} 次。")
        for _ in range(target):
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": completed, "remaining": power, "reason": "stopped"}
            result = session.travel_destiny()
            if result["ret"] != 0:
                if result["ret"] == 1705:
                    log("仙友游历体力已耗尽。")
                    return {
                        "ret": 0, "completed": completed,
                        "remaining": 0, "reason": "finished",
                    }
                message = {
                    1701: "仙友系统未解锁",
                    1706: "当前游历配置不存在",
                    1707: "一键游历未解锁",
                }.get(result["ret"], f"服务端返回 {result['ret']}")
                log(f"仙友游历失败：{message}。")
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": power, "reason": "destiny_travel_failed",
                }
            completed += 1
            synced_power = session.destiny_power()
            if synced_power is not None:
                power = synced_power
            elif power is not None:
                power = max(0, power - 1)
            value = session.resource_snapshot(server_id); value["destinyPower"] = power
            if snapshot is not None:
                snapshot(value)
            power_text = "等待同步" if power is None else str(power)
            log(f"第 {completed}/{target} 次仙友游历完成，当前体力 {power_text}。")
        return {"ret": 0, "completed": completed, "remaining": power, "reason": "finished"}


def run_profession_quick_task(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if count != 1:
        raise ValueError("Profession quick battle count must be 1")
    login = _load_login(server_id, output_dir)
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        state = session.profession_state()
        if state is None:
            log("道途试炼状态读取失败，本次不会发起速战。")
            return {"ret": None, "completed": 0, "remaining": None, "reason": "profession_state_unknown"}
        remaining = max(0, PROFESSION_QUICK_DAILY_MAX - state["repeatTimesToday"])
        if remaining == 0:
            log("道途试炼今日速战次数已用完。")
            return {"ret": 0, "completed": 0, "remaining": 0, "reason": "finished"}
        boss_id = state["lastPassedBossId"]
        if boss_id <= 0:
            log("道途试炼尚未通关任何关卡，无法速战上一关。")
            return {"ret": None, "completed": 0, "remaining": remaining, "reason": "profession_no_passed_boss"}
        if stop_event is not None and stop_event.is_set():
            return {"ret": 0, "completed": 0, "remaining": remaining, "reason": "stopped"}
        result = session.profession_battle(boss_id, 1)
        if result["ret"] in (654, 18003):
            log("道途试炼今日速战次数已用完。")
            return {"ret": 0, "completed": 0, "remaining": 0, "reason": "finished"}
        if result["ret"] != 0:
            log(f"道途试炼速战失败，服务端返回 {result['ret']}。")
            return {
                "ret": result["ret"], "completed": 0,
                "remaining": remaining, "reason": "profession_quick_failed",
            }
        value = session.resource_snapshot(server_id); value["professionQuickRemaining"] = 0
        if snapshot is not None:
            snapshot(value)
        log(f"道途试炼速战上一关完成，关卡 ID {boss_id}。")
        return {"ret": 0, "completed": 1, "remaining": 0, "reason": "finished"}


def run_profession_challenge_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not 1 <= count <= PROFESSION_CHALLENGE_DAILY_MAX:
        raise ValueError("Profession challenge count must be between 1 and 30")
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        state = session.profession_state()
        if state is None:
            log("道途试炼状态读取失败，本次不会发起挑战。")
            return {"ret": None, "completed": 0, "remaining": None, "reason": "profession_state_unknown"}
        remaining = max(0, PROFESSION_CHALLENGE_DAILY_MAX - state["battleTimesToday"])
        target = min(count, remaining)
        boss_id = state["lastPassedBossId"] + 1 if state["lastPassedBossId"] > 0 else 50001
        log(f"道途试炼今日剩余 {remaining}/30 次，计划挑战 {target} 次。")
        for _ in range(target):
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": completed, "remaining": remaining, "reason": "stopped"}
            result = session.profession_battle(boss_id, 2)
            if result["ret"] == 18003:
                log("道途试炼今日挑战次数已用完。")
                return {"ret": 0, "completed": completed, "remaining": 0, "reason": "finished"}
            if result["ret"] != 0:
                log(f"道途试炼挑战失败，服务端返回 {result['ret']}。")
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": remaining, "reason": "profession_challenge_failed",
                }
            completed += 1
            remaining = max(0, remaining - 1)
            if result["win"] is None:
                log(f"道途试炼关卡 ID {boss_id} 的战斗结果无法解析，任务停止。")
                return {
                    "ret": 0, "completed": completed,
                    "remaining": remaining, "reason": "profession_result_unknown",
                }
            if result["win"] is False:
                log(f"第 {completed}/{target} 次道途试炼未通过关卡 ID {boss_id}，继续挑战本关。")
            else:
                log(f"第 {completed}/{target} 次道途试炼挑战成功，通关关卡 ID {boss_id}。")
                boss_id += 1
            value = session.resource_snapshot(server_id)
            value["professionLastBossId"] = boss_id - 1
            value["professionChallengeRemaining"] = remaining
            if snapshot is not None:
                snapshot(value)
        return {"ret": 0, "completed": completed, "remaining": remaining, "reason": "finished"}


def run_yard_daily_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if count != 1:
        raise ValueError("Yard daily task count must be 1")
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        entered = session.enter_yard()
        if entered["ret"] != 0:
            log(f"进入仙居失败，服务端返回 {entered['ret']}。")
            return {
                "ret": entered["ret"], "completed": 0,
                "remaining": 1, "reason": "yard_enter_failed",
            }
        buildings = entered["buildings"]
        if not buildings:
            log("仙居内未读取到功能建筑，本次不会发送生产请求。")
            return {
                "ret": None, "completed": 0,
                "remaining": 1, "reason": "yard_buildings_missing",
            }

        if stop_event is not None and stop_event.is_set():
            return {"ret": 0, "completed": 0, "remaining": 1, "reason": "stopped"}

        tree = buildings.get(YARD_BUILD_TREE)
        if tree and yard_continuous_reward_available(tree):
            result = session.yard_collect(tree)
            if result["ret"] != 0:
                log(f"仙桃树收取失败，服务端返回 {result['ret']}。")
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": 1, "reason": "yard_tree_collect_failed",
                }
            completed += 1
            log("仙桃树收桃完成。")
        elif tree:
            log("仙桃树当前没有可收取的仙桃。")

        farmland = buildings.get(YARD_BUILD_FARMLAND)
        if farmland and yard_continuous_reward_available(farmland):
            result = session.yard_collect(farmland)
            if result["ret"] != 0:
                log(f"灵田收菜失败，服务端返回 {result['ret']}。")
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": 1, "reason": "yard_farmland_collect_failed",
                }
            completed += 1
            log("灵田收菜完成，正在检查可炼丹数量。")
        elif farmland:
            log("灵田当前没有可收取的灵草。")

        stove = buildings.get(YARD_BUILD_STOVE)
        stove_idle = bool(stove and stove.get("status") == 0)
        if stove and yard_build_finished(stove):
            result = session.yard_collect(stove)
            if result["ret"] != 0:
                log(f"炼丹炉收丹失败，服务端返回 {result['ret']}。")
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": 1, "reason": "yard_alchemy_collect_failed",
                }
            completed += 1
            stove_idle = True
            log("炼丹炉收丹完成。")
        elif stove and stove.get("status") == 1:
            log("炼丹炉仍在炼制中，本次不重复操作。")
        elif stove and stove.get("status") == 2:
            log("炼丹炉正在升级，本次不启动炼丹。")

        if stove and stove_idle:
            grass = session.yard_grass_num()
            if grass is None:
                grass = session.item_count(YARD_FARMLAND_PRODUCT)
            alchemy_count = min(YARD_ALCHEMY_MAX, grass // YARD_HERB_COST)
            if alchemy_count > 0:
                result = session.yard_make(stove, alchemy_count)
                if result["ret"] != 0:
                    log(f"炼丹启动失败，服务端返回 {result['ret']}。")
                    return {
                        "ret": result["ret"], "completed": completed,
                        "remaining": 1, "reason": "yard_alchemy_start_failed",
                    }
                completed += 1
                log(f"已消耗灵草启动炼丹，共 {alchemy_count} 次。")
            else:
                log(f"当前灵草 {grass}，不足 {YARD_HERB_COST}，不启动炼丹。")

        cistern = buildings.get(YARD_BUILD_CISTERN)
        cistern_idle = bool(cistern and cistern.get("status") == 0)
        if cistern and yard_build_finished(cistern):
            result = session.yard_collect(cistern)
            if result["ret"] != 0:
                log(f"化外灵池收取失败，服务端返回 {result['ret']}。")
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": 1, "reason": "yard_cistern_collect_failed",
                }
            completed += 1
            cistern_idle = True
            log("化外灵池孕育完成，产物已收取。")
        elif cistern and cistern.get("status") == 1:
            log("化外灵池正在孕育中，本次不做处理。")
        elif cistern and cistern.get("status") == 2:
            log("化外灵池正在升级，本次不启动孕育。")

        if cistern and cistern_idle:
            product_id = cistern.get("productId") or YARD_DEFAULT_CROP
            product_count = max(1, cistern.get("totalNum", 0))
            result = session.yard_make(cistern, product_count, product_id)
            if result["ret"] != 0:
                log(f"化外灵池启动孕育失败，服务端返回 {result['ret']}。")
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": 1, "reason": "yard_cistern_start_failed",
                }
            completed += 1
            log(f"化外灵池已开始孕育，产物 {product_id}，数量 {product_count}。")

        if snapshot is not None:
            snapshot(session.resource_snapshot(server_id))
        return {"ret": 0, "completed": completed, "remaining": 0, "reason": "finished"}


def run_yard_draw_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not 1 <= count <= YARD_DRAW_MAX:
        raise ValueError("Yard draw count must be between 1 and 100")
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        entered = session.enter_yard()
        if entered["ret"] != 0:
            log(f"进入仙居失败，服务端返回 {entered['ret']}。")
            return {
                "ret": entered["ret"], "completed": 0,
                "remaining": count, "reason": "yard_enter_failed",
            }
        free_available = entered["drawData"].get("freeDrawTimes", 0) < 1
        log(f"仙居造物计划执行 {count} 次，免费次数{'可用' if free_available else '已使用'}。")
        batches: list[bool] = []
        remaining = count
        if free_available and remaining > 0:
            batches.append(False)
            remaining -= 1
        batches.extend([True] * (remaining // 10))
        batches.extend([False] * (remaining % 10))
        for ten in batches:
            if stop_event is not None and stop_event.is_set():
                return {
                    "ret": 0, "completed": completed,
                    "remaining": count - completed, "reason": "stopped",
                }
            result = session.yard_draw(ten)
            if result["ret"] != 0:
                log(f"仙居造物失败，服务端返回 {result['ret']}，不再继续消耗天工图纸。")
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": count - completed, "reason": "yard_draw_failed",
                }
            batch_count = 10 if ten else 1
            completed += batch_count
            log(f"仙居造物完成 {completed}/{count} 次。")
        if snapshot is not None:
            snapshot(session.resource_snapshot(server_id))
        return {"ret": 0, "completed": completed, "remaining": 0, "reason": "finished"}


def run_chop_tasks(
    server_id: int,
    output_dir: Path,
    count: int | None,
    interval: float,
    equipment_action: str,
    keep_quality: int,
    log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    keep_attribute_type: int = 0,
    keep_attribute_value: str = "0",
    snapshot: Callable[[dict[str, Any]], None] | None = None,
    auto_rank_battle: bool = False,
) -> dict[str, Any]:
    """Run sequential chops, resolving only verified tree-drop equipment."""
    login = _load_login(server_id, output_dir)
    completed = 0
    if stop_event is not None and stop_event.is_set():
        return {"ret": 0, "completed": completed, "reason": "stopped"}
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        initial_snapshot = session.resource_snapshot(server_id)
        jade = int(initial_snapshot.get("jade", 0))
        spirit_stone = int(initial_snapshot.get("spiritStone", 0))
        rank_tickets = min(RANK_BATTLE_TICKET_MAX, session.item_count(RANK_BATTLE_TICKET))
        missing_ticket_logged = False

        def emit_snapshot() -> None:
            nonlocal jade, spirit_stone
            if snapshot is None:
                return
            value = session.resource_snapshot(server_id)
            # Merge inventory pushes received by subsequent requests while
            # retaining rewards parsed before the corresponding push arrives.
            jade = max(jade, int(value.get("jade", 0)))
            spirit_stone = max(spirit_stone, int(value.get("spiritStone", 0)))
            value["jade"] = jade
            value["spiritStone"] = spirit_stone
            value["rankBattleTicket"] = rank_tickets
            snapshot(value)

        emit_snapshot()
        pending = session.get_pending_equipment()
        while count is None or completed < count:
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": completed, "reason": "stopped"}
            equipment = pending
            if not equipment:
                # Python owns the repeated-task loop. Each request must remain
                # a normal single chop, matching the browser payload 08001801;
                # auto=true requires the game's separate auto-mode state.
                result = session.chop_tree(auto=False)
                (output_dir / f"chop-tree-{server_id}.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                if result["ret"] != 0:
                    target = "无限" if count is None else str(count)
                    log(f"第 {completed + 1}/{target} 次砍树被服务器拒绝，返回码 {result['ret']}。")
                    return {"ret": result["ret"], "completed": completed, "reason": "chop_failed"}
                equipment = result["equipment"] or session.get_pending_equipment()
                completed += 1
                target = "无限" if count is None else str(count)
                log(f"第 {completed}/{target} 次砍树成功。")
                for reward in result["rewards"]:
                    log(f"砍树掉落：{reward['name']} x{reward['count']}。")
                    if reward["id"] == 100000:
                        jade += reward["count"]
                    elif reward["id"] == 100003:
                        spirit_stone += reward["count"]
                    elif reward["id"] == RANK_BATTLE_TICKET:
                        rank_tickets = min(RANK_BATTLE_TICKET_MAX, rank_tickets + reward["count"])
                        missing_ticket_logged = False
                emit_snapshot()
            if equipment:
                for item in equipment:
                    attributes = "、".join(
                        f"{attr['name']} {attr['value']}" for attr in item["attributes"]
                    ) or "无属性"
                    log(
                        f"待处理装备：ID {item['id']} 装备 {item['equipmentId']} "
                        f"品质 {item['quality']} 来源 {item['src']}；属性：{attributes}"
                    )
                unsafe = [e for e in equipment if e["src"] != 1]
                if unsafe:
                    return {"ret": None, "completed": completed, "reason": "unsafe_source", "equipment": unsafe}
                if equipment_action != "decompose":
                    return {"ret": 0, "completed": completed, "reason": "kept", "equipment": equipment}

                def attribute_value(item: dict[str, Any] | None) -> Decimal:
                    if item is None:
                        return Decimal(0)
                    attr = next(
                        (value for value in item["attributes"] if value["type"] == keep_attribute_type),
                        None,
                    )
                    try:
                        return Decimal(attr["value"]) if attr else Decimal(0)
                    except InvalidOperation:
                        return Decimal(0)

                to_decompose: list[dict[str, Any]] = []
                if keep_attribute_type > 0:
                    attribute_name = ATTRIBUTE_NAMES.get(keep_attribute_type, f"属性{keep_attribute_type}")
                    for item in equipment:
                        current = session.equipped_for(item)
                        new_value = attribute_value(item)
                        current_value = attribute_value(current)
                        if current is None or new_value > current_value:
                            replace = session.equip_and_resolve(item)
                            if replace["ret"] != 0:
                                return {
                                    "ret": replace["ret"], "completed": completed,
                                    "reason": "replace_failed", "equipment": [item],
                                }
                            previous = "该部位未装备" if current is None else f"当前 {current_value}"
                            log(
                                f"已替换装备 ID {item['id']}：{attribute_name} 新装备 {new_value}，"
                                f"{previous}。旧装备已分解。"
                            )
                            emit_snapshot()
                        else:
                            log(
                                f"装备 ID {item['id']} 不替换：{attribute_name} 新装备 {new_value} "
                                f"<= 当前 {current_value}，将分解新装备。"
                            )
                            to_decompose.append(item)
                else:
                    keep = [item for item in equipment if item["quality"] >= keep_quality]
                    if keep:
                        for item in keep:
                            log(f"保留装备 ID {item['id']}：品质 {item['quality']} >= {keep_quality}。")
                        return {"ret": 0, "completed": completed, "reason": "kept", "equipment": keep}
                    to_decompose = equipment

                if to_decompose:
                    deal = session.decompose([item["id"] for item in to_decompose])
                    if deal["ret"] != 0:
                        return {"ret": deal["ret"], "completed": completed, "reason": "decompose_failed"}
                    log(f"已自动分解 {len(to_decompose)} 件未提升指定属性的砍树装备。")
                    emit_snapshot()
                pending = []
            if auto_rank_battle:
                if rank_tickets <= 0:
                    if not missing_ticket_logged:
                        log("无法斗法：缺少挑战状，等待后续砍树掉落。")
                        missing_ticket_logged = True
                else:
                    try:
                        log(f"检测到挑战状 {rank_tickets} 张，正在获取可挑战对手。")
                        battle = session.rank_battle()
                        if battle["ret"] == 0:
                            rank_tickets -= 1
                            emit_snapshot()
                            opponent = battle["opponent"]
                            log(
                                f"斗法完成：对手 {opponent['name']}，妖力 {opponent['power']}，"
                                f"剩余挑战状 {rank_tickets}。"
                            )
                        elif battle["reason"] == "no_opponent":
                            log("无法斗法：当前没有可挑战的对手。")
                        else:
                            log(f"斗法请求失败，服务端返回 {battle['ret']}，继续砍树轮询。")
                    except (OSError, RuntimeError, websocket.WebSocketException) as exc:
                        log(f"斗法连接中断：{type(exc).__name__}，正在重连并继续砍树轮询。")
                        try:
                            session.close()
                            session.connect()
                            pending = session.get_pending_equipment()
                            reconnected_snapshot = session.resource_snapshot(server_id)
                            jade = int(reconnected_snapshot.get("jade", 0))
                            spirit_stone = int(reconnected_snapshot.get("spiritStone", 0))
                            rank_tickets = min(RANK_BATTLE_TICKET_MAX, session.item_count(RANK_BATTLE_TICKET))
                            emit_snapshot()
                            log("游戏连接已恢复，继续执行砍树和斗法任务。")
                        except (OSError, RuntimeError, websocket.WebSocketException) as reconnect_exc:
                            return {
                                "ret": None, "completed": completed,
                                "reason": "reconnect_failed", "error": str(reconnect_exc),
                            }
            has_more = count is None or completed < count
            if has_more and interval > 0:
                if stop_event is not None:
                    if stop_event.wait(interval):
                        return {"ret": 0, "completed": completed, "reason": "stopped"}
                else:
                    time.sleep(interval)
    return {"ret": 0, "completed": completed, "reason": "finished"}
