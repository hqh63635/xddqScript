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
PUPIL_ENTER = 211801
PUPIL_ENTER_RESPONSE = 11801
PUPIL_TRAIN = 211802
PUPIL_TRAIN_RESPONSE = 11802
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
INVADE_GET_DATA = 21402
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
YARD_AD_FREE_DAILY_MAX = 2
HOMELAND_SYNC = 21051
HOMELAND_SYNC_RESPONSE = 1051
HOMELAND_ENTER = 21052
HOMELAND_ENTER_RESPONSE = 1052
HOMELAND_MANAGE = 21053
HOMELAND_MANAGE_RESPONSE = 1053
HOMELAND_EXPLORE = 21058
HOMELAND_EXPLORE_RESPONSE = 1058
HOMELAND_EXPLORE_REFRESH = 21059
HOMELAND_EXPLORE_REFRESH_RESPONSE = 1059
HOMELAND_DISPATCH_WORKER = 21060
HOMELAND_DISPATCH_WORKER_RESPONSE = 1060
HOMELAND_REFRESH_COOLDOWN_MS = 300_000

HOMELAND_RESOURCE_NAMES = {
    100004: "仙桃",
    100025: "净瓶水",
    100000: "仙玉",
    100003: "灵石",
    100029: "琉璃珠",
    100044: "天衍令",
    100047: "昆仑铁",
}
TALENT_STATE_REQUEST = 20621
TALENT_SYNC = 621
TALENT_RANDOM = 20622
TALENT_RANDOM_RESPONSE = 622
TALENT_DEAL = 20623
TALENT_DEAL_RESPONSE = 623
TALENT_READ_BOOK = 20624
TALENT_READ_BOOK_RESPONSE = 624
TALENT_GET_PENDING = 20625
TALENT_GET_PENDING_RESPONSE = 625
TALENT_GRASS_ITEM = 100007
TALENT_BOOK_ITEM = 100008
MAGIC_SYNC = 4400
MAGIC_DERIVATION = 24408
MAGIC_DERIVATION_RESPONSE = 4408
MAGIC_FREE_DAILY_MAX = 2
MAGIC_NORMAL_FREE_MAX = 1
MAGIC_TICKET_ITEM = 100044
SPIRIT_SYNC = 821
SPIRIT_DRAW = 20822
SPIRIT_DRAW_RESPONSE = 822
SPIRIT_FREE_DAILY_MAX = 2
SPIRIT_TICKET_ITEM = 100023
LAW_LOOKS_LOGIN_SYNC = 18711
LAW_LOOKS_DRAW = 218709
LAW_LOOKS_DRAW_RESPONSE = 18709
LAW_LOOKS_FREE_DAILY_MAX = 2
LAW_LOOKS_TICKET_ITEM = 100184
PET_KERNEL_DRAW = 211706
PET_KERNEL_DRAW_RESPONSE = 11706
PET_KERNEL_STATE_REQUEST = 211708
PET_KERNEL_STATE_RESPONSE = 11708
PET_KERNEL_FREE_DAILY_MAX = 2
PET_KERNEL_DRAW_ITEM = 100100
UNIVERSE_STATE_REQUEST = 214302
UNIVERSE_STATE_RESPONSE = 14302
UNIVERSE_WHEEL_DRAW = 214304
UNIVERSE_WHEEL_DRAW_RESPONSE = 14304
UNIVERSE_SKILL_DRAW = 214308
UNIVERSE_SKILL_DRAW_RESPONSE = 14308
UNIVERSE_SKILL_FREE_MAX = 2
UNIVERSE_SKILL_DRAW_ITEM = 100126
UNIVERSE_STONE_ITEM = 100124
TOWER_SYNC = 761
TOWER_CHALLENGE = 20762
TOWER_CHALLENGE_RESPONSE = 762
TOWER_QUICK_CHALLENGE = 20763
TOWER_QUICK_CHALLENGE_RESPONSE = 763
TOWER_SELECT_BUFF = 20764
TOWER_SELECT_BUFF_RESPONSE = 764
TOWER_SAVE_PREFERENCE = 20767
TOWER_SAVE_PREFERENCE_RESPONSE = 767
TOWER_DEFAULT_PREFERENCES = (1017, 1018, 1023, 1024, 1022)
STAGE_SYNC = 403
STAGE_CHALLENGE = 20402
STAGE_CHALLENGE_RESPONSE = 402
DIVINE_INSIGHT_RECEIVE_MIND = 231002
DIVINE_INSIGHT_RECEIVE_MIND_RESPONSE = 31002
TREASURE_AUCTION_ENTER = 234001
TREASURE_AUCTION_ENTER_RESPONSE = 34001
TREASURE_AUCTION_BEGIN_EXPLORE = 234004
TREASURE_AUCTION_BEGIN_EXPLORE_RESPONSE = 34004
TREASURE_AUCTION_REWARD = 234005
TREASURE_AUCTION_REWARD_RESPONSE = 34005
TREASURE_AUCTION_HELP = 234007
TREASURE_AUCTION_HELP_RESPONSE = 34007
TREASURE_AUCTION_IDENTIFY = 234009
TREASURE_AUCTION_IDENTIFY_RESPONSE = 34009
TREASURE_AUCTION_DISASSEMBLE = 234011
TREASURE_AUCTION_DISASSEMBLE_RESPONSE = 34011
TREASURE_AUCTION_GET_HELP_LIST = 234012
TREASURE_AUCTION_GET_HELP_LIST_RESPONSE = 34012
FREE_DRAW_INTERVAL_SECONDS = 8.0
MAGIC_TREASURE_STATE_REQUEST = 26301
MAGIC_TREASURE_SYNC = 6301
MAGIC_TREASURE_DRAW = 26302
MAGIC_TREASURE_DRAW_RESPONSE = 6302
MAGIC_TREASURE_FREE_MAX = 2
MAGIC_TREASURE_POOLS = {
    1: "灵瀚仙界",
    2: "神遗灵界",
    3: "缥缈凡界",
}
MAGIC_TREASURE_COMPASS_ITEMS = {
    1: 100197,
    2: 100091,
    3: 100064,
}

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


def _text_value(fields: list[dict[str, Any]], number: int) -> str:
    field = next((item for item in fields if item["field"] == number and "raw" in item), None)
    if field is None:
        return ""
    try:
        return field["raw"].decode("utf-8")
    except UnicodeDecodeError:
        return ""


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


def parse_yard_buildings(payload: bytes) -> dict[int, list[dict[str, int]]]:
    """Decode the four functional buildings from YardEnterResp."""
    buildings: dict[int, list[dict[str, int]]] = {}
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
            buildings.setdefault(build_id, []).append(values)
    return buildings


def yard_buildings_of_type(
    buildings: dict[int, Any], build_id: int,
) -> list[dict[str, int]]:
    """Return every instance while accepting the former single-building shape."""
    value = buildings.get(build_id, [])
    if isinstance(value, dict):
        return [value]
    return list(value)


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


def parse_homeland_state(payload: bytes) -> dict[str, int] | None:
    fields = parse_protobuf(payload)
    free = _values(fields, 1)
    total = _values(fields, 2)
    energy = _values(fields, 3)
    if not free or not total:
        return None
    return {
        "freeWorkerNum": int(free[0]),
        "totalWorkerNum": int(total[0]),
        "energy": int(energy[0]) if energy else 0,
    }


def _parse_homeland_competitor(fields: list[dict[str, Any]]) -> dict[str, Any]:
    player_ids = _values(fields, 1)
    worker_nums = _values(fields, 4)
    winners = _values(fields, 5)
    return {
        "playerId": int(player_ids[0]) if player_ids else 0,
        "workerNum": int(worker_nums[0]) if worker_nums else 0,
        "isWinner": bool(winners[0]) if winners else None,
    }


def parse_homeland_reward(fields: list[dict[str, Any]]) -> dict[str, Any]:
    owners = _children(fields, 6)
    enemies = _children(fields, 7)
    return {
        "reward": _text_value(fields, 1),
        "level": int((_values(fields, 2) or [0])[0]),
        "pos": int((_values(fields, 4) or [0])[0]),
        "maxWorkerNum": int((_values(fields, 5) or [1])[0]),
        "owner": _parse_homeland_competitor(owners[0]) if owners else None,
        "enemy": _parse_homeland_competitor(enemies[0]) if enemies else None,
        "finishTime": int((_values(fields, 8) or [0])[0]),
        "playerId": int((_values(fields, 9) or [0])[0]),
        "isOnlyOwnerPull": bool((_values(fields, 10) or [0])[0]),
    }


def parse_homeland_enter(payload: bytes) -> dict[str, Any] | None:
    homelands = _children(parse_protobuf(payload), 1)
    if not homelands:
        return None
    homeland = homelands[0]
    owners = _children(homeland, 4)
    if not owners:
        return None
    player_ids = _values(owners[0], 1)
    if not player_ids:
        return None
    return {
        "playerId": int(player_ids[0]),
        "rewards": [parse_homeland_reward(item) for item in _children(homeland, 2)],
    }


def parse_homeland_manage(payload: bytes) -> list[dict[str, Any]]:
    return [parse_homeland_reward(item) for item in _children(parse_protobuf(payload), 1)]


def parse_homeland_explore(payload: bytes) -> dict[str, Any]:
    root = parse_protobuf(payload)
    explore_messages = _children(root, 2)
    explore = explore_messages[0] if explore_messages else root

    def players(field_number: int) -> list[dict[str, Any]]:
        result = []
        for entry in _children(explore, field_number):
            infos = _children(entry, 1)
            player_ids = _values(infos[0], 1) if infos else []
            if player_ids:
                result.append({
                    "playerId": int(player_ids[0]),
                    "rewardIds": [int(value) for value in _values(entry, 2)],
                })
        return result

    return {
        "near": players(1),
        "enemy": players(2),
        "lastRefreshTime": int((_values(explore, 3) or [0])[0]),
    }


def parse_talent_data(fields: list[dict[str, Any]]) -> dict[str, Any] | None:
    types = _values(fields, 1)
    talent_ids = _values(fields, 2)
    levels = _values(fields, 3)
    qualities = _values(fields, 4)
    if not types or not talent_ids or not qualities:
        return None
    attributes = []
    for attribute in _children(fields, 5):
        attr_types = _values(attribute, 1)
        if not attr_types:
            continue
        attributes.append({
            "type": int(attr_types[0]),
            "value": _text_value(attribute, 2),
        })
    return {
        "type": int(types[0]),
        "talentId": int(talent_ids[0]),
        "level": int(levels[0]) if levels else 0,
        "quality": int(qualities[0]),
        "attributes": attributes,
    }


def parse_pending_talents(payload: bytes, field_number: int = 2) -> list[dict[str, Any]]:
    result = []
    for pending in _children(parse_protobuf(payload), field_number):
        talents = _children(pending, 1)
        talent = parse_talent_data(talents[0]) if talents else None
        if talent is not None:
            result.append(talent)
    return result


def parse_talent_sync(payload: bytes) -> dict[str, Any]:
    fields = parse_protobuf(payload)
    return {
        "createLevel": int((_values(fields, 2) or [0])[0]),
        "readBookTimes": int((_values(fields, 5) or [0])[0]),
        "pending": [
            talent for pending in _children(fields, 4)
            for talent in [parse_talent_data((_children(pending, 1) or [[]])[0])]
            if talent is not None
        ],
    }


def parse_magic_state(payload: bytes) -> dict[str, int]:
    fields = parse_protobuf(payload)
    free_ads = _children(fields, 7)
    return {
        "freeDrawTimes": int((_values(fields, 5) or [0])[0]),
        "freeAdTimes": int((_values(free_ads[0], 1) or [0])[0]) if free_ads else 0,
        "lastAdTime": int((_values(free_ads[0], 2) or [0])[0]) if free_ads else 0,
    }


def parse_spirit_state(payload: bytes) -> dict[str, int]:
    fields = parse_protobuf(payload)
    sync_messages = _children(fields, 3)
    if sync_messages:
        fields = sync_messages[0]
    free_ads = _children(fields, 8)
    return {
        "drawTimes": int((_values(fields, 4) or [0])[0]),
        "freeAdTimes": int((_values(free_ads[0], 1) or [0])[0]) if free_ads else 0,
        "lastAdTime": int((_values(free_ads[0], 2) or [0])[0]) if free_ads else 0,
    }


def parse_law_looks_state(payload: bytes) -> dict[str, int]:
    fields = parse_protobuf(payload)
    return {
        "freeAdTimes": int((_values(fields, 2) or [0])[0]),
        "freeDrawTimes": int((_values(fields, 3) or [0])[0]),
    }


def parse_pet_kernel_state(payload: bytes) -> dict[str, int]:
    fields = parse_protobuf(payload)
    return {
        "freeDrawTimes": int((_values(fields, 3) or [0])[0]),
        "drawCount": int((_values(fields, 4) or [0])[0]),
        "ensureCount": int((_values(fields, 5) or [0])[0]),
    }


def parse_universe_state(payload: bytes) -> dict[str, int]:
    fields = parse_protobuf(payload)
    wrapped = _children(fields, 1)
    if wrapped and not _values(fields, 2):
        fields = wrapped[0]
    return {
        "level": int((_values(fields, 1) or [0])[0]),
        "stoneNum": int((_values(fields, 2) or [0])[0]),
        "freeDrawTimes": int((_values(fields, 7) or [0])[0]),
        "drawTimes": int((_values(fields, 10) or [0])[0]),
    }


def parse_tower_state(payload: bytes) -> dict[str, Any]:
    fields = parse_protobuf(payload)
    pending = _children(fields, 4)
    return {
        "curPassId": int((_values(fields, 1) or [0])[0]),
        "passMaxId": int((_values(fields, 3) or [0])[0]),
        "pendingBuffIds": [int(value) for value in _values(pending[0], 1)] if pending else [],
        "leftPendingTimes": int((_values(fields, 5) or [0])[0]),
    }


def parse_tower_response_state(payload: bytes, field_number: int) -> dict[str, Any] | None:
    states = _children(parse_protobuf(payload), field_number)
    return parse_tower_state(states[0]) if states else None


def parse_stage_state(payload: bytes) -> dict[str, int]:
    fields = parse_protobuf(payload)
    return {"passStageId": int((_values(fields, 1) or [0])[0])}


def parse_magic_treasure_state(payload: bytes) -> dict[int, dict[str, Any]]:
    fields = parse_protobuf(payload)
    result: dict[int, dict[str, Any]] = {}
    for jackpot in _children(fields, 2):
        pool_ids = _values(jackpot, 1)
        if not pool_ids:
            continue
        pool_id = int(pool_ids[0])
        result[pool_id] = {
            "poolId": pool_id,
            "drawTimes": int((_values(jackpot, 2) or [0])[0]),
            "freeDrawTimes": int((_values(jackpot, 3) or [0])[0]),
            "adFreeTimes": int((_values(jackpot, 4) or [0])[0]),
            "lastAdTime": int((_values(jackpot, 5) or [0])[0]),
            "itemId": MAGIC_TREASURE_COMPASS_ITEMS.get(pool_id, 0),
        }
    for pool_config in _children(fields, 3):
        pool_ids = _values(pool_config, 1)
        if not pool_ids:
            continue
        pool_id = int(pool_ids[0])
        state = result.setdefault(pool_id, {
            "poolId": pool_id, "drawTimes": 0, "freeDrawTimes": 0,
            "adFreeTimes": 0, "lastAdTime": 0,
            "itemId": MAGIC_TREASURE_COMPASS_ITEMS.get(pool_id, 0),
        })
        cost = _text_value(pool_config, 6)
        match = re.search(r"\d+", cost)
        if match:
            state["itemId"] = int(match.group())
        title = _text_value(pool_config, 4)
        if title:
            state["title"] = title
    return result


def _parse_treasure_place(fields: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "id": int((_values(fields, 1) or [0])[0]),
        "treasureMapId": int((_values(fields, 2) or [0])[0]),
        "placeIndex": int((_values(fields, 3) or [0])[0]),
        "beginTime": int((_values(fields, 4) or [0])[0]),
        "helpCount": int((_values(fields, 5) or [0])[0]),
        "realmsId": int((_values(fields, 6) or [0])[0]),
    }


def _parse_treasure_item(fields: list[dict[str, Any]]) -> dict[str, Any]:
    treasure_id = int((_values(fields, 3) or [0])[0])
    identify_list = _children(fields, 6)
    return {
        "id": int((_values(fields, 1) or [0])[0]),
        "treasureId": treasure_id,
        "quality": int((_values(fields, 4) or [0])[0]),
        "isIdentify": bool(identify_list),
        "isSelling": int((_values(fields, 10) or [0])[0]) > 0,
        "lock": bool((_values(fields, 13) or [0])[0]),
    }


def parse_treasure_auction_state(payload: bytes) -> dict[str, Any]:
    fields = parse_protobuf(payload)
    player_messages = _children(fields, 2)
    player = player_messages[0] if player_messages else []
    items = [_parse_treasure_item(item) for item in _children(fields, 3)]
    places = [_parse_treasure_place(place) for place in _children(player, 3)]
    return {
        "ret": response_ret(payload),
        "helpCount": int((_values(player, 1) or [0])[0]),
        "treasureCount": int((_values(player, 2) or [0])[0]),
        "places": places,
        "warehouseLimit": int((_values(player, 4) or [0])[0]),
        "items": items,
        "equipIds": {int(value) for value in _values(player, 10)},
    }


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

    def invade_state(self, refresh: bool = True) -> tuple[int, int] | None:
        if refresh:
            try:
                response = self._request(INVADE_GET_DATA, INVADE_SYNC)
                used = parse_invade_used_times(response)
                if used is not None:
                    return used, max(0, INVADE_DAILY_MAX - used)
            except (RuntimeError, TimeoutError, websocket.WebSocketException):
                pass
        for message_id, payload in reversed(self.observed_frames):
            if message_id == INVADE_SYNC:
                used = parse_invade_used_times(payload)
                if used is not None:
                    return used, max(0, INVADE_DAILY_MAX - used)
        return None

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

    def yard_draw(self, ten: bool = False, is_ad: bool = False) -> dict[str, Any]:
        payload = (
            protobuf_int(1, int(ten))
            + protobuf_int(2, int(is_ad))
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

    def homeland_state(self) -> dict[str, int] | None:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == HOMELAND_SYNC_RESPONSE:
                state = parse_homeland_state(payload)
                if state is not None:
                    return state
        return None

    def homeland_manage(self) -> list[dict[str, Any]]:
        response = self._request(HOMELAND_MANAGE, HOMELAND_MANAGE_RESPONSE)
        return parse_homeland_manage(response)

    def homeland_enter(self, player_id: int) -> dict[str, Any] | None:
        response = self._request(
            HOMELAND_ENTER, HOMELAND_ENTER_RESPONSE,
            protobuf_int(1, player_id),
        )
        return parse_homeland_enter(response)

    def homeland_explore(self, refresh: bool = False) -> dict[str, Any]:
        request_id = HOMELAND_EXPLORE_REFRESH if refresh else HOMELAND_EXPLORE
        response_id = (
            HOMELAND_EXPLORE_REFRESH_RESPONSE if refresh else HOMELAND_EXPLORE_RESPONSE
        )
        response = self._request(request_id, response_id)
        return {
            "ret": response_ret(response),
            **parse_homeland_explore(response),
        }

    def homeland_dispatch(self, player_id: int, pos: int, worker_num: int) -> dict[str, Any]:
        if worker_num < 0:
            raise ValueError("Homeland worker count must not be negative")
        response = self._request(
            HOMELAND_DISPATCH_WORKER, HOMELAND_DISPATCH_WORKER_RESPONSE,
            protobuf_int(1, player_id)
            + protobuf_int(2, pos)
            + protobuf_int(3, worker_num),
        )
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def talent_state(self, refresh: bool = True) -> dict[str, Any] | None:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == TALENT_SYNC:
                return parse_talent_sync(payload)
        if refresh:
            response = self._request(TALENT_STATE_REQUEST, TALENT_SYNC)
            return parse_talent_sync(response)
        return None

    def talent_get_pending(self) -> dict[str, Any]:
        response = self._request(TALENT_GET_PENDING, TALENT_GET_PENDING_RESPONSE)
        return {
            "ret": response_ret(response),
            "pending": parse_pending_talents(response),
        }

    def talent_read_books(self, count: int) -> dict[str, Any]:
        if count <= 0:
            raise ValueError("Talent enlightenment count must be positive")
        response = self._request(
            TALENT_READ_BOOK, TALENT_READ_BOOK_RESPONSE,
            protobuf_int(1, count),
        )
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def talent_random(self, count: int) -> dict[str, Any]:
        if not 1 <= count <= 5:
            raise ValueError("Talent activation count must be between 1 and 5")
        response = self._request(
            TALENT_RANDOM, TALENT_RANDOM_RESPONSE,
            protobuf_int(1, count),
        )
        return {
            "ret": response_ret(response),
            "pending": parse_pending_talents(response),
            "payloadHex": response.hex(),
        }

    def talent_deal(self, index: int, action: int) -> dict[str, Any]:
        if index < 0 or action not in (1, 2):
            raise ValueError("Invalid talent processing parameters")
        response = self._request(
            TALENT_DEAL, TALENT_DEAL_RESPONSE,
            protobuf_int(1, index) + protobuf_int(2, action),
        )
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def magic_state(self) -> dict[str, int] | None:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == MAGIC_SYNC:
                return parse_magic_state(payload)
        return None

    def magic_draw(self, count: int = 1, is_ad: bool = False) -> dict[str, Any]:
        if count <= 0:
            raise ValueError("Magic draw count must be positive")
        payload = protobuf_int(1, count)
        if is_ad:
            payload += protobuf_int(2, 1) + protobuf_int(3, 0)
        response = self._request(
            MAGIC_DERIVATION, MAGIC_DERIVATION_RESPONSE,
            payload,
        )
        return {
            "ret": response_ret(response),
            "magicIds": [int(value) for value in _values(parse_protobuf(response), 2)],
            "payloadHex": response.hex(),
        }

    def magic_free_draw(self) -> dict[str, Any]:
        return self.magic_draw(1, is_ad=True)

    def spirit_state(self) -> dict[str, int] | None:
        for message_id, payload in reversed(self.observed_frames):
            if message_id in (SPIRIT_SYNC, SPIRIT_DRAW_RESPONSE):
                return parse_spirit_state(payload)
        return None

    def spirit_draw(self, count: int = 1, is_ad: bool = False) -> dict[str, Any]:
        if count <= 0:
            raise ValueError("Spirit draw count must be positive")
        payload = protobuf_int(1, count)
        if is_ad:
            payload += protobuf_int(2, 1) + protobuf_int(3, 0)
        response = self._request(
            SPIRIT_DRAW, SPIRIT_DRAW_RESPONSE,
            payload,
        )
        results = _children(parse_protobuf(response), 2)
        spirit_ids = [
            int((_values(result, 1) or [0])[0]) for result in results
            if _values(result, 1)
        ]
        return {
            "ret": response_ret(response),
            "spiritIds": spirit_ids,
            "payloadHex": response.hex(),
        }

    def spirit_free_draw(self) -> dict[str, Any]:
        return self.spirit_draw(1, is_ad=True)

    def law_looks_state(self) -> dict[str, int] | None:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == LAW_LOOKS_LOGIN_SYNC:
                return parse_law_looks_state(payload)
        return None

    def law_looks_draw(self, count: int = 1, draw_type: int = 2) -> dict[str, Any]:
        if count <= 0 or draw_type not in (0, 1, 2):
            raise ValueError("Invalid law looks draw parameters")
        response = self._request(
            LAW_LOOKS_DRAW, LAW_LOOKS_DRAW_RESPONSE,
            protobuf_int(1, count) + protobuf_int(2, draw_type),
        )
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def pet_kernel_state(self, refresh: bool = True) -> dict[str, int] | None:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == PET_KERNEL_STATE_RESPONSE:
                return parse_pet_kernel_state(payload)
        if refresh:
            response = self._request(PET_KERNEL_STATE_REQUEST, PET_KERNEL_STATE_RESPONSE)
            return parse_pet_kernel_state(response)
        return None

    def pet_kernel_draw(self, ten: bool = False) -> dict[str, Any]:
        response = self._request(
            PET_KERNEL_DRAW, PET_KERNEL_DRAW_RESPONSE,
            protobuf_int(1, int(ten)),
        )
        fields = parse_protobuf(response)
        return {
            "ret": response_ret(response),
            "count": 10 if ten else 1,
            "freeDrawTimes": int((_values(fields, 4) or [0])[0]),
            "payloadHex": response.hex(),
        }

    def universe_state(self, refresh: bool = True) -> dict[str, int] | None:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == UNIVERSE_STATE_RESPONSE:
                return parse_universe_state(payload)
        if refresh:
            response = self._request(UNIVERSE_STATE_REQUEST, UNIVERSE_STATE_RESPONSE)
            return parse_universe_state(response)
        return None

    def universe_skill_draw(self, count: int = 1) -> dict[str, Any]:
        if count <= 0:
            raise ValueError("Universe skill draw count must be positive")
        response = self._request(
            UNIVERSE_SKILL_DRAW, UNIVERSE_SKILL_DRAW_RESPONSE,
            protobuf_int(1, count),
        )
        fields = parse_protobuf(response)
        return {
            "ret": response_ret(response),
            "freeDrawTimes": int((_values(fields, 6) or [0])[0]),
            "payloadHex": response.hex(),
        }

    def universe_wheel_draw(self, multiplier: int = 1) -> dict[str, Any]:
        if multiplier <= 0:
            raise ValueError("Universe wheel multiplier must be positive")
        response = self._request(
            UNIVERSE_WHEEL_DRAW, UNIVERSE_WHEEL_DRAW_RESPONSE,
            protobuf_int(1, multiplier),
        )
        fields = parse_protobuf(response)
        return {
            "ret": response_ret(response),
            "stoneNum": int((_values(fields, 3) or [0])[0]),
            "payloadHex": response.hex(),
        }

    def tower_state(self) -> dict[str, Any] | None:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == TOWER_SYNC:
                return parse_tower_state(payload)
        return None

    def tower_save_preferences(self, skill_types: tuple[int, ...] = TOWER_DEFAULT_PREFERENCES) -> dict[str, Any]:
        payload = b"".join(
            message_field(1, protobuf_int(1, priority) + protobuf_int(2, skill_type))
            for priority, skill_type in enumerate(skill_types, 1)
        )
        response = self._request(
            TOWER_SAVE_PREFERENCE, TOWER_SAVE_PREFERENCE_RESPONSE, payload,
        )
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def tower_quick_challenge(self) -> dict[str, Any]:
        response = self._request(TOWER_QUICK_CHALLENGE, TOWER_QUICK_CHALLENGE_RESPONSE)
        return {
            "ret": response_ret(response),
            "state": parse_tower_response_state(response, 2),
            "payloadHex": response.hex(),
        }

    def tower_select_buff(self, one_key: bool = True) -> dict[str, Any]:
        payload = protobuf_int(1, 0) + protobuf_int(3, int(one_key))
        response = self._request(TOWER_SELECT_BUFF, TOWER_SELECT_BUFF_RESPONSE, payload)
        return {
            "ret": response_ret(response),
            "state": parse_tower_response_state(response, 2),
            "payloadHex": response.hex(),
        }

    def tower_challenge(self) -> dict[str, Any]:
        response = self._request(TOWER_CHALLENGE, TOWER_CHALLENGE_RESPONSE)
        fields = parse_protobuf(response)
        return {
            "ret": response_ret(response),
            "won": bool(int((_values(fields, 3) or [0])[0])),
            "state": parse_tower_response_state(response, 5),
            "payloadHex": response.hex(),
        }

    def stage_state(self) -> dict[str, int] | None:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == STAGE_SYNC:
                return parse_stage_state(payload)
        return None

    def stage_challenge(self) -> dict[str, Any]:
        response = self._request(STAGE_CHALLENGE, STAGE_CHALLENGE_RESPONSE)
        fields = parse_protobuf(response)
        return {
            "ret": response_ret(response),
            "won": bool(int((_values(fields, 3) or [0])[0])),
            "payloadHex": response.hex(),
        }

    def divine_insight_receive_mind(self) -> dict[str, Any]:
        response = self._request(
            DIVINE_INSIGHT_RECEIVE_MIND, DIVINE_INSIGHT_RECEIVE_MIND_RESPONSE,
        )
        fields = parse_protobuf(response)
        return {
            "ret": response_ret(response),
            "receiveNum": int((_values(fields, 3) or [0])[0]),
            "inspireAddNum": int((_values(fields, 4) or [0])[0]),
            "payloadHex": response.hex(),
        }

    def treasure_auction_enter(self) -> dict[str, Any]:
        return parse_treasure_auction_state(
            self._request(TREASURE_AUCTION_ENTER, TREASURE_AUCTION_ENTER_RESPONSE)
        )

    def treasure_auction_claim_rewards(self, place_ids: list[int]) -> dict[str, Any]:
        payload = b"".join(protobuf_int(1, place_id) for place_id in place_ids)
        response = self._request(TREASURE_AUCTION_REWARD, TREASURE_AUCTION_REWARD_RESPONSE, payload)
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def treasure_auction_begin(self, place_id: int) -> dict[str, Any]:
        response = self._request(
            TREASURE_AUCTION_BEGIN_EXPLORE, TREASURE_AUCTION_BEGIN_EXPLORE_RESPONSE,
            protobuf_int(1, place_id),
        )
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def treasure_auction_get_help_list(self) -> dict[str, Any]:
        response = self._request(TREASURE_AUCTION_GET_HELP_LIST, TREASURE_AUCTION_GET_HELP_LIST_RESPONSE)
        return {"ret": response_ret(response), "entries": _children(parse_protobuf(response), 2)}

    def treasure_auction_help_one_key(self) -> dict[str, Any]:
        response = self._request(
            TREASURE_AUCTION_HELP, TREASURE_AUCTION_HELP_RESPONSE, protobuf_int(3, 1),
        )
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def treasure_auction_identify(self, treasure_id: int) -> dict[str, Any]:
        response = self._request(
            TREASURE_AUCTION_IDENTIFY, TREASURE_AUCTION_IDENTIFY_RESPONSE,
            protobuf_int(1, treasure_id),
        )
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def treasure_auction_disassemble(self, treasure_ids: list[int]) -> dict[str, Any]:
        payload = b"".join(protobuf_int(1, treasure_id) for treasure_id in treasure_ids)
        response = self._request(
            TREASURE_AUCTION_DISASSEMBLE, TREASURE_AUCTION_DISASSEMBLE_RESPONSE, payload,
        )
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def magic_treasure_state(self, refresh: bool = True) -> dict[int, dict[str, Any]]:
        for message_id, payload in reversed(self.observed_frames):
            if message_id == MAGIC_TREASURE_SYNC:
                return parse_magic_treasure_state(payload)
        if refresh:
            response = self._request(MAGIC_TREASURE_STATE_REQUEST, MAGIC_TREASURE_SYNC)
            return parse_magic_treasure_state(response)
        return {}

    def magic_treasure_draw(
        self, pool_id: int, count: int = 1, item_id: int = 0, is_ad: bool = False,
    ) -> dict[str, Any]:
        if pool_id not in MAGIC_TREASURE_POOLS or count <= 0:
            raise ValueError("Invalid magic treasure draw parameters")
        payload = protobuf_int(1, count)
        if is_ad:
            payload += protobuf_int(2, 1)
        payload += protobuf_int(3, pool_id)
        if is_ad:
            payload += protobuf_int(4, 0)
        elif item_id > 0:
            payload += protobuf_int(5, item_id)
        response = self._request(MAGIC_TREASURE_DRAW, MAGIC_TREASURE_DRAW_RESPONSE, payload)
        return {"ret": response_ret(response), "payloadHex": response.hex()}

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
        if not any(message_id == MAGIC_TREASURE_SYNC for message_id, _payload in self.observed_frames):
            try:
                self.magic_treasure_state(refresh=True)
            except (RuntimeError, OSError, websocket.WebSocketException):
                pass
        if not any(message_id == PET_KERNEL_STATE_RESPONSE for message_id, _payload in self.observed_frames):
            try:
                self.pet_kernel_state(refresh=True)
            except (RuntimeError, OSError, websocket.WebSocketException):
                pass
        if not any(message_id == UNIVERSE_STATE_RESPONSE for message_id, _payload in self.observed_frames):
            try:
                self.universe_state(refresh=True)
            except (RuntimeError, OSError, websocket.WebSocketException):
                pass
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
    snapshot["peachCount"] = inventory.get(100004, 0)
    snapshot["talentGrassCount"] = inventory.get(TALENT_GRASS_ITEM, 0)
    snapshot["talentBookCount"] = inventory.get(TALENT_BOOK_ITEM, 0)
    snapshot["rankBattleTicket"] = min(RANK_BATTLE_TICKET_MAX, inventory.get(RANK_BATTLE_TICKET, 0))
    snapshot["magicTicketCount"] = inventory.get(MAGIC_TICKET_ITEM, 0)
    snapshot["spiritTicketCount"] = inventory.get(SPIRIT_TICKET_ITEM, 0)
    snapshot["lawLooksTicketCount"] = inventory.get(LAW_LOOKS_TICKET_ITEM, 0)
    snapshot["petKernelDrawItemCount"] = inventory.get(PET_KERNEL_DRAW_ITEM, 0)
    snapshot["universeSkillDrawItemCount"] = inventory.get(UNIVERSE_SKILL_DRAW_ITEM, 0)
    treasure_state = next(
        (
            parse_magic_treasure_state(payload)
            for message_id, payload in reversed(frames)
            if message_id == MAGIC_TREASURE_SYNC
        ),
        {},
    )
    snapshot["magicTreasurePools"] = {
        str(pool_id): {
            "freeRemaining": max(
                0, MAGIC_TREASURE_FREE_MAX - int(treasure_state.get(pool_id, {}).get("freeDrawTimes", 0))
            ) if pool_id in treasure_state else None,
            "itemId": int(treasure_state.get(pool_id, {}).get(
                "itemId", MAGIC_TREASURE_COMPASS_ITEMS[pool_id]
            )),
            "compassCount": inventory.get(int(treasure_state.get(pool_id, {}).get(
                "itemId", MAGIC_TREASURE_COMPASS_ITEMS[pool_id]
            )), 0),
        }
        for pool_id in MAGIC_TREASURE_POOLS
    }
    magic_state = next(
        (
            parse_magic_state(payload)
            for message_id, payload in reversed(frames)
            if message_id == MAGIC_SYNC
        ),
        None,
    )
    snapshot["magicFreeRemaining"] = (
        max(0, MAGIC_NORMAL_FREE_MAX - magic_state["freeDrawTimes"])
        + max(0, MAGIC_FREE_DAILY_MAX - magic_state["freeAdTimes"])
        if magic_state is not None else None
    )
    spirit_state = next(
        (
            parse_spirit_state(payload)
            for message_id, payload in reversed(frames)
            if message_id in (SPIRIT_SYNC, SPIRIT_DRAW_RESPONSE)
        ),
        None,
    )
    snapshot["spiritSummonRemaining"] = (
        max(0, SPIRIT_FREE_DAILY_MAX - spirit_state["freeAdTimes"])
        if spirit_state is not None else None
    )
    law_looks_state = next(
        (
            parse_law_looks_state(payload)
            for message_id, payload in reversed(frames)
            if message_id == LAW_LOOKS_LOGIN_SYNC
        ),
        None,
    )
    snapshot["lawLooksFreeRemaining"] = (
        max(0, LAW_LOOKS_FREE_DAILY_MAX - law_looks_state["freeAdTimes"])
        if law_looks_state is not None else None
    )
    pet_kernel_state = next(
        (
            parse_pet_kernel_state(payload)
            for message_id, payload in reversed(frames)
            if message_id == PET_KERNEL_STATE_RESPONSE
        ),
        None,
    )
    snapshot["petKernelFreeRemaining"] = (
        max(0, PET_KERNEL_FREE_DAILY_MAX - pet_kernel_state["freeDrawTimes"])
        if pet_kernel_state is not None else None
    )
    universe_state = next(
        (
            parse_universe_state(payload)
            for message_id, payload in reversed(frames)
            if message_id == UNIVERSE_STATE_RESPONSE
        ),
        None,
    )
    snapshot["universeSkillFreeRemaining"] = (
        max(0, UNIVERSE_SKILL_FREE_MAX - universe_state["freeDrawTimes"])
        if universe_state is not None else None
    )
    snapshot["universeStoneCount"] = (
        universe_state["stoneNum"] if universe_state is not None
        else inventory.get(UNIVERSE_STONE_ITEM, 0)
    )
    tower_state = next(
        (
            parse_tower_state(payload)
            for message_id, payload in reversed(frames)
            if message_id == TOWER_SYNC
        ),
        None,
    )
    snapshot["towerCurrentPass"] = tower_state["curPassId"] if tower_state else None
    snapshot["towerMaxPass"] = tower_state["passMaxId"] if tower_state else None
    stage_state = next(
        (
            parse_stage_state(payload)
            for message_id, payload in reversed(frames)
            if message_id == STAGE_SYNC
        ),
        None,
    )
    snapshot["adventureCurrentStage"] = (
        stage_state["passStageId"] + 1 if stage_state is not None else None
    )
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
        None,
    )
    snapshot["invadeRemaining"] = (
        max(0, INVADE_DAILY_MAX - invade_used) if invade_used is not None else None
    )
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
        state = session.invade_state()
        if state is None:
            used = 0
            remaining = count
            target = count
            log(f"异兽入侵次数未同步，将按选择的 {count} 次尝试挑战，由服务端校验剩余次数。")
        else:
            used, remaining = state
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


def _homeland_reward_item_id(reward: dict[str, Any]) -> int | None:
    value = str(reward.get("reward", ""))
    if "=" not in value:
        return None
    try:
        return int(value.split("=", 1)[0])
    except ValueError:
        return None


def run_talent_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
    minimum_quality: int = 5,
    preferred_attribute: int = 5,
    interval: float = 2.0,
    concurrent_count: int = 1,
) -> dict[str, Any]:
    if not 0 <= count <= 1000:
        raise ValueError("Talent total count must be between 0 and 1000")
    if not 1 <= minimum_quality <= 10 or preferred_attribute not in ATTRIBUTE_NAMES:
        raise ValueError("Invalid talent preference")
    if not 0.5 <= interval <= 60:
        raise ValueError("Talent draw interval must be between 0.5 and 60 seconds")
    if not 1 <= concurrent_count <= 5:
        raise ValueError("Talent concurrent count must be between 1 and 5")

    login = _load_login(server_id, output_dir)
    activated = 0
    resolved = 0
    enlightened = 0
    draw_completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        state = session.talent_state()
        if state is None:
            log("灵脉数据未同步，本次不执行激发。")
            return {"ret": None, "completed": 0, "remaining": None, "reason": "talent_state_unknown"}

        def process_pending(pending: list[dict[str, Any]]) -> int | None:
            nonlocal activated, resolved
            for index in range(len(pending) - 1, -1, -1):
                if stop_event is not None and stop_event.is_set():
                    return 0
                talent = pending[index]
                attribute_types = {item["type"] for item in talent["attributes"]}
                should_activate = (
                    talent["quality"] >= minimum_quality
                    and preferred_attribute in attribute_types
                )
                action = 2 if should_activate else 1
                result = session.talent_deal(index, action)
                if result["ret"] != 0:
                    log(f"灵脉处理失败，服务端返回 {result['ret']}。")
                    return result["ret"]
                if should_activate:
                    activated += 1
                    log(
                        f"已激活 {talent['quality']} 级灵脉，"
                        f"属性包含{ATTRIBUTE_NAMES[preferred_attribute]}。"
                    )
                else:
                    resolved += 1
                    log(f"已分解不符合条件的 {talent['quality']} 级灵脉。")
            return None

        pending_result = session.talent_get_pending()
        if pending_result["ret"] != 0:
            return {
                "ret": pending_result["ret"], "completed": 0,
                "remaining": None, "reason": "talent_pending_failed",
            }
        error = process_pending(pending_result["pending"])
        if error is not None:
            return {
                "ret": error, "completed": activated + resolved,
                "remaining": None, "reason": "talent_deal_failed",
            }

        book_count = session.item_count(TALENT_BOOK_ITEM)
        if book_count > 0:
            result = session.talent_read_books(book_count)
            if result["ret"] != 0:
                log(f"灵脉开悟失败，服务端返回 {result['ret']}，停止激发。")
                return {
                    "ret": result["ret"], "completed": activated + resolved,
                    "remaining": None, "reason": "talent_enlighten_failed",
                }
            enlightened = book_count
            log(f"灵脉开悟完成，已使用 {book_count} 个万年灵芝。")
        else:
            log("当前没有万年灵芝，无需开悟。")

        grass_remaining = session.item_count(TALENT_GRASS_ITEM)
        if grass_remaining <= 0:
            log("当前没有仙草，本次不激发灵脉。")
        else:
            log(f"当前共有 {grass_remaining} 个仙草，将持续激发并处理全部结果。")
            draw_target = grass_remaining if count == 0 else min(count, grass_remaining)
            total_text = "无限次" if count == 0 else f"{count} 次"
            log(
                f"本次总次数选择 {total_text}，同时次数 {concurrent_count}，"
                f"实际最多激发 {draw_target} 次。"
            )
            while grass_remaining > 0 and draw_completed < draw_target:
                if stop_event is not None and stop_event.is_set():
                    return {
                        "ret": 0, "completed": activated + resolved,
                        "remaining": grass_remaining, "reason": "stopped",
                    }
                batch_count = min(concurrent_count, draw_target - draw_completed, grass_remaining)
                result = session.talent_random(batch_count)
                if result["ret"] != 0:
                    if result["ret"] == 30:
                        log(f"灵脉激发频率过快，请将间隔调高（当前 {interval:g} 秒）。")
                    return {
                        "ret": result["ret"], "completed": activated + resolved,
                        "remaining": grass_remaining, "reason": "talent_random_failed",
                    }
                grass_remaining -= batch_count
                draw_completed += batch_count
                log(f"已使用 {batch_count} 个仙草激发灵脉，剩余 {grass_remaining} 个。")
                error = process_pending(result["pending"])
                if error is not None:
                    return {
                        "ret": error, "completed": activated + resolved,
                        "remaining": grass_remaining, "reason": "talent_deal_failed",
                    }
                if snapshot is not None:
                    snapshot(session.resource_snapshot(server_id))
                if draw_completed < draw_target:
                    time.sleep(interval)

        if snapshot is not None:
            snapshot(session.resource_snapshot(server_id))
        return {
            "ret": 0, "completed": activated + resolved,
            "remaining": 0, "reason": "finished",
            "activated": activated, "resolved": resolved, "enlightened": enlightened,
            "drawCompleted": draw_completed,
        }


def run_magic_draw_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
    paid_count: int = 0,
) -> dict[str, Any]:
    if not 0 <= count <= MAGIC_NORMAL_FREE_MAX + MAGIC_FREE_DAILY_MAX or not 0 <= paid_count <= 100:
        raise ValueError("Invalid magic draw count")
    if count == 0 and paid_count == 0:
        return {"ret": 0, "completed": 0, "remaining": 0, "reason": "finished"}
    login = _load_login(server_id, output_dir)
    free_completed = 0
    paid_completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        state = session.magic_state()
        if state is None:
            free_modes = [False] + [True] * count
            log(f"神通免费次数未同步，本次免费选择 {count} 次，由服务端校验额度。")
        else:
            normal_free = max(0, MAGIC_NORMAL_FREE_MAX - state["freeDrawTimes"])
            ad_free = max(0, MAGIC_FREE_DAILY_MAX - state["freeAdTimes"])
            free_modes = ([False] * normal_free + [True] * ad_free)[:count]
            log(f"神通当前免费可用 {normal_free + ad_free}/3 次，本次免费选择 {count} 次。")
        for mode_index, is_ad in enumerate(free_modes):
            if free_completed >= count:
                break
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": free_completed + paid_completed, "remaining": 0, "reason": "stopped"}
            result = session.magic_draw(1, is_ad=is_ad)
            if result["ret"] == (4415 if is_ad else 4419):
                if is_ad:
                    break
                continue
            if result["ret"] != 0:
                return {
                    "ret": result["ret"], "completed": free_completed + paid_completed,
                    "remaining": 0, "reason": "magic_draw_failed",
                }
            free_completed += 1
            if result["magicIds"]:
                log(f"第 {free_completed}/{count} 次免费获取神通完成，神通 ID {result['magicIds'][0]}。")
            else:
                log(f"第 {free_completed}/{count} 次免费获取神通完成。")
            if free_completed < count and mode_index + 1 < len(free_modes):
                time.sleep(FREE_DRAW_INTERVAL_SECONDS)

        ticket_available = session.item_count(MAGIC_TICKET_ITEM)
        paid_target = min(paid_count, ticket_available)
        log(f"神通天衍令可用 {ticket_available} 次，本次消耗选择 {paid_count} 次，实际执行 {paid_target} 次。")
        if paid_target > 0:
            result = session.magic_draw(paid_target)
            if result["ret"] != 0:
                return {"ret": result["ret"], "completed": free_completed, "remaining": ticket_available, "reason": "magic_paid_draw_failed"}
            paid_completed = paid_target
            log(f"消耗次数获取神通完成，共执行 {paid_completed} 次。")
        if snapshot is not None:
            snapshot(session.resource_snapshot(server_id))
        return {
            "ret": 0, "completed": free_completed + paid_completed,
            "remaining": max(0, ticket_available - paid_completed), "reason": "finished",
            "freeCompleted": free_completed, "paidCompleted": paid_completed,
        }


def run_spirit_draw_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
    paid_count: int = 0,
) -> dict[str, Any]:
    if not 0 <= count <= SPIRIT_FREE_DAILY_MAX or not 0 <= paid_count <= 100:
        raise ValueError("Invalid spirit draw count")
    if count == 0 and paid_count == 0:
        return {"ret": 0, "completed": 0, "remaining": 0, "reason": "finished"}
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        state = session.spirit_state()
        available = count if state is None else max(0, SPIRIT_FREE_DAILY_MAX - state["freeAdTimes"])
        target = min(count, available)
        log(f"精怪当前免费可用 {available if state is not None else '--'}/2 次，本次免费选择 {count} 次。")
        for index in range(target):
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": completed, "remaining": available - completed, "reason": "stopped"}
            result = session.spirit_free_draw()
            if result["ret"] == 1111:
                log("精怪今日广告免费召唤次数已用完。")
                available = completed
                break
            if result["ret"] != 0:
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": available - completed, "reason": "spirit_draw_failed",
                }
            completed += 1
            if result["spiritIds"]:
                log(f"第 {completed}/{target} 次免费召唤精怪完成，精怪 ID {result['spiritIds'][0]}。")
            else:
                log(f"第 {completed}/{target} 次免费召唤精怪完成。")
            if index + 1 < target:
                time.sleep(FREE_DRAW_INTERVAL_SECONDS)
        ticket_available = session.item_count(SPIRIT_TICKET_ITEM)
        paid_target = min(paid_count, ticket_available)
        log(f"精怪召唤令可用 {ticket_available} 次，本次消耗选择 {paid_count} 次，实际执行 {paid_target} 次。")
        paid_completed = 0
        if paid_target > 0:
            result = session.spirit_draw(paid_target)
            if result["ret"] != 0:
                return {"ret": result["ret"], "completed": completed, "remaining": ticket_available, "reason": "spirit_paid_draw_failed"}
            paid_completed = paid_target
            log(f"消耗召唤令召唤精怪完成，共执行 {paid_completed} 次。")
        if snapshot is not None:
            snapshot(session.resource_snapshot(server_id))
        return {
            "ret": 0, "completed": completed + paid_completed,
            "remaining": max(0, ticket_available - paid_completed), "reason": "finished",
            "freeCompleted": completed, "paidCompleted": paid_completed,
        }


def run_law_looks_draw_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
    paid_count: int = 0,
) -> dict[str, Any]:
    if not 0 <= count <= LAW_LOOKS_FREE_DAILY_MAX or not 0 <= paid_count <= 100:
        raise ValueError("Invalid law looks draw count")
    if count == 0 and paid_count == 0:
        return {"ret": 0, "completed": 0, "remaining": 0, "reason": "finished"}
    login = _load_login(server_id, output_dir)
    free_completed = 0
    paid_completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        state = session.law_looks_state()
        available = count if state is None else max(
            0, LAW_LOOKS_FREE_DAILY_MAX - state["freeAdTimes"]
        )
        target = min(count, available)
        shown_available = str(available) if state is not None else "--"
        log(f"法象当前免费可用 {shown_available}/2 次，本次免费选择 {count} 次。")
        for index in range(target):
            if stop_event is not None and stop_event.is_set():
                return {
                    "ret": 0, "completed": free_completed,
                    "remaining": available - free_completed, "reason": "stopped",
                }
            result = session.law_looks_draw(1, draw_type=0)
            if result["ret"] != 0:
                return {
                    "ret": result["ret"], "completed": free_completed,
                    "remaining": available - free_completed, "reason": "law_looks_free_draw_failed",
                }
            free_completed += 1
            log(f"第 {free_completed}/{target} 次免费召唤法象完成。")
            if index + 1 < target:
                time.sleep(FREE_DRAW_INTERVAL_SECONDS)

        ticket_available = session.item_count(LAW_LOOKS_TICKET_ITEM)
        paid_target = min(paid_count, ticket_available)
        log(
            f"引灵灯可用 {ticket_available} 次，本次消耗选择 {paid_count} 次，"
            f"实际执行 {paid_target} 次。"
        )
        if paid_target > 0:
            result = session.law_looks_draw(paid_target, draw_type=2)
            if result["ret"] != 0:
                return {
                    "ret": result["ret"], "completed": free_completed,
                    "remaining": ticket_available, "reason": "law_looks_paid_draw_failed",
                }
            paid_completed = paid_target
            log(f"消耗引灵灯召唤法象完成，共执行 {paid_completed} 次。")
        if snapshot is not None:
            snapshot(session.resource_snapshot(server_id))
        return {
            "ret": 0, "completed": free_completed + paid_completed,
            "remaining": max(0, ticket_available - paid_completed), "reason": "finished",
            "freeCompleted": free_completed, "paidCompleted": paid_completed,
        }


def run_pet_kernel_draw_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
    paid_count: int = 0,
) -> dict[str, Any]:
    if not 0 <= count <= PET_KERNEL_FREE_DAILY_MAX or not 0 <= paid_count <= 100:
        raise ValueError("Invalid pet kernel draw count")
    if count == 0 and paid_count == 0:
        return {"ret": 0, "completed": 0, "remaining": 0, "reason": "finished"}
    login = _load_login(server_id, output_dir)
    free_completed = 0
    paid_completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        state = session.pet_kernel_state()
        available = count if state is None else max(
            0, PET_KERNEL_FREE_DAILY_MAX - state["freeDrawTimes"]
        )
        target = min(count, available)
        shown_available = str(available) if state is not None else "--"
        log(f"灵兽内丹当前免费可用 {shown_available}/2 次，本次免费选择 {count} 次。")
        for index in range(target):
            if stop_event is not None and stop_event.is_set():
                return {
                    "ret": 0, "completed": free_completed,
                    "remaining": available - free_completed, "reason": "stopped",
                }
            result = session.pet_kernel_draw(ten=False)
            if result["ret"] != 0:
                return {
                    "ret": result["ret"], "completed": free_completed,
                    "remaining": available - free_completed, "reason": "pet_kernel_free_draw_failed",
                }
            free_completed += 1
            log(f"第 {free_completed}/{target} 次免费凝聚内丹完成。")
            if index + 1 < target:
                time.sleep(FREE_DRAW_INTERVAL_SECONDS)

        item_available = session.item_count(PET_KERNEL_DRAW_ITEM)
        paid_target = min(paid_count, item_available)
        log(
            f"本源丹可用 {item_available} 次，本次消耗选择 {paid_count} 次，"
            f"实际执行 {paid_target} 次。"
        )
        remaining_paid = paid_target
        while remaining_paid > 0:
            if stop_event is not None and stop_event.is_set():
                return {
                    "ret": 0, "completed": free_completed + paid_completed,
                    "remaining": item_available - paid_completed, "reason": "stopped",
                }
            batch = 10 if remaining_paid >= 10 else 1
            result = session.pet_kernel_draw(ten=batch == 10)
            if result["ret"] != 0:
                return {
                    "ret": result["ret"], "completed": free_completed + paid_completed,
                    "remaining": item_available - paid_completed, "reason": "pet_kernel_paid_draw_failed",
                }
            paid_completed += batch
            remaining_paid -= batch
        if paid_completed:
            log(f"消耗本源丹凝聚内丹完成，共执行 {paid_completed} 次。")
        if snapshot is not None:
            snapshot(session.resource_snapshot(server_id))
        return {
            "ret": 0, "completed": free_completed + paid_completed,
            "remaining": max(0, item_available - paid_completed), "reason": "finished",
            "freeCompleted": free_completed, "paidCompleted": paid_completed,
        }


def run_universe_skill_draw_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
    paid_count: int = 0,
) -> dict[str, Any]:
    if not 0 <= count <= UNIVERSE_SKILL_FREE_MAX or not 0 <= paid_count <= 100:
        raise ValueError("Invalid universe skill draw count")
    if count == 0 and paid_count == 0:
        return {"ret": 0, "completed": 0, "remaining": 0, "reason": "finished"}
    login = _load_login(server_id, output_dir)
    free_completed = 0
    paid_completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        state = session.universe_state()
        available = count if state is None else max(
            0, UNIVERSE_SKILL_FREE_MAX - state["freeDrawTimes"]
        )
        target = min(count, available)
        shown_available = str(available) if state is not None else "--"
        log(f"洞悉天机当前免费可用 {shown_available}/2 次，本次免费选择 {count} 次。")
        for index in range(target):
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": free_completed, "remaining": 0, "reason": "stopped"}
            result = session.universe_skill_draw(1)
            if result["ret"] != 0:
                return {"ret": result["ret"], "completed": free_completed, "remaining": 0, "reason": "universe_skill_free_draw_failed"}
            free_completed += 1
            log(f"第 {free_completed}/{target} 次免费洞悉天机完成。")
            if index + 1 < target:
                time.sleep(FREE_DRAW_INTERVAL_SECONDS)

        item_available = session.item_count(UNIVERSE_SKILL_DRAW_ITEM)
        paid_target = min(paid_count, item_available)
        log(
            f"太虚元石可用 {item_available} 次，本次消耗选择 {paid_count} 次，"
            f"实际执行 {paid_target} 次。"
        )
        remaining_paid = paid_target
        while remaining_paid > 0:
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": free_completed + paid_completed, "remaining": item_available - paid_completed, "reason": "stopped"}
            batch = min(10, remaining_paid)
            result = session.universe_skill_draw(batch)
            if result["ret"] != 0:
                return {"ret": result["ret"], "completed": free_completed + paid_completed, "remaining": item_available - paid_completed, "reason": "universe_skill_paid_draw_failed"}
            paid_completed += batch
            remaining_paid -= batch
        if paid_completed:
            log(f"消耗太虚元石洞悉天机完成，共执行 {paid_completed} 次。")
        if snapshot is not None:
            snapshot(session.resource_snapshot(server_id))
        return {
            "ret": 0, "completed": free_completed + paid_completed,
            "remaining": max(0, item_available - paid_completed), "reason": "finished",
            "freeCompleted": free_completed, "paidCompleted": paid_completed,
        }


def run_universe_wheel_draw_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not 0 <= count <= 100:
        raise ValueError("Invalid universe wheel draw count")
    if count == 0:
        return {"ret": 0, "completed": 0, "remaining": 0, "reason": "finished"}
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        state = session.universe_state()
        stone_available = 0 if state is None else state["stoneNum"]
        target = min(count, stone_available)
        log(f"造化石可用 {stone_available} 次，本次衍取选择 {count} 次，实际执行 {target} 次。")
        for index in range(target):
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": completed, "remaining": stone_available - completed, "reason": "stopped"}
            result = session.universe_wheel_draw(1)
            if result["ret"] != 0:
                return {"ret": result["ret"], "completed": completed, "remaining": stone_available - completed, "reason": "universe_wheel_draw_failed"}
            completed += 1
            log(f"第 {completed}/{target} 次天道轮台衍取完成。")
            if index + 1 < target:
                time.sleep(FREE_DRAW_INTERVAL_SECONDS)
        if snapshot is not None:
            value = session.resource_snapshot(server_id)
            value["universeStoneCount"] = max(0, stone_available - completed)
            snapshot(value)
        return {
            "ret": 0, "completed": completed,
            "remaining": max(0, stone_available - completed), "reason": "finished",
        }


def run_tower_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
    use_preferences: bool = True,
) -> dict[str, Any]:
    if not 0 <= count <= 100:
        raise ValueError("Invalid tower challenge count")
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        state = session.tower_state()

        def select_pending(current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, int]:
            selected = 0
            while current and current["leftPendingTimes"] > 0:
                if stop_event is not None and stop_event.is_set():
                    break
                if use_preferences:
                    saved = session.tower_save_preferences()
                    if saved["ret"] != 0:
                        return current, saved["ret"]
                result = session.tower_select_buff(one_key=True)
                if result["ret"] != 0:
                    return current, result["ret"]
                selected += 1
                current = result["state"]
                log(f"镇妖塔已一键选择第 {selected} 次加成。")
            return current, 0

        if use_preferences:
            saved = session.tower_save_preferences()
            if saved["ret"] != 0:
                return {"ret": saved["ret"], "completed": 0, "remaining": count, "reason": "tower_preference_failed"}
            log("镇妖塔加成偏好已激活。")

        quick = session.tower_quick_challenge()
        if quick["ret"] != 0:
            return {"ret": quick["ret"], "completed": 0, "remaining": count, "reason": "tower_quick_challenge_failed"}
        state = quick["state"] or state
        if state:
            log(f"镇妖塔快速挑战完成，当前关卡 {state['curPassId']}，最高关卡 {state['passMaxId']}。")
        else:
            log("镇妖塔快速挑战完成。")

        state, select_ret = select_pending(state)
        if select_ret != 0:
            return {"ret": select_ret, "completed": 0, "remaining": count, "reason": "tower_select_buff_failed"}

        for _index in range(count):
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": completed, "remaining": count - completed, "reason": "stopped"}
            result = session.tower_challenge()
            if result["ret"] != 0 or not result["won"]:
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": count - completed,
                    "reason": "tower_challenge_failed" if result["ret"] else "tower_challenge_lost",
                }
            completed += 1
            state = result["state"] or state
            if state:
                log(f"镇妖塔继续挑战 {completed}/{count} 完成，当前关卡 {state['curPassId']}。")
            else:
                log(f"镇妖塔继续挑战 {completed}/{count} 完成。")
            state, select_ret = select_pending(state)
            if select_ret != 0:
                return {"ret": select_ret, "completed": completed, "remaining": count - completed, "reason": "tower_select_buff_failed"}
            if completed < count:
                time.sleep(FREE_DRAW_INTERVAL_SECONDS)

        if snapshot is not None:
            value = session.resource_snapshot(server_id)
            if state:
                value["towerCurrentPass"] = state["curPassId"]
                value["towerMaxPass"] = state["passMaxId"]
            snapshot(value)
        return {"ret": 0, "completed": completed, "remaining": 0, "reason": "finished"}


def run_adventure_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not 0 <= count <= 1000:
        raise ValueError("Invalid adventure challenge count")
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        state = session.stage_state()
        current_stage = state["passStageId"] + 1 if state is not None else None
        count_text = "无限次" if count == 0 else f"{count} 次"
        stage_text = "--" if current_stage is None else str(current_stage)
        log(f"冒险从当前关卡 {stage_text} 开始，计划挑战 {count_text}。")
        while count == 0 or completed < count:
            if stop_event is not None and stop_event.is_set():
                return {
                    "ret": 0, "completed": completed,
                    "remaining": 0 if count == 0 else count - completed, "reason": "stopped",
                }
            result = session.stage_challenge()
            if result["ret"] != 0:
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": 0 if count == 0 else count - completed,
                    "reason": "adventure_challenge_failed",
                }
            if not result["won"]:
                log("冒险挑战失败，任务停止。")
                return {
                    "ret": 0, "completed": completed,
                    "remaining": 0 if count == 0 else count - completed,
                    "reason": "adventure_challenge_lost",
                }
            completed += 1
            state = session.stage_state()
            current_stage = state["passStageId"] + 1 if state is not None else current_stage
            stage_text = "--" if current_stage is None else str(current_stage)
            progress_text = str(completed) if count == 0 else f"{completed}/{count}"
            log(f"冒险挑战 {progress_text} 完成，当前关卡 {stage_text}。")
            if snapshot is not None:
                value = session.resource_snapshot(server_id)
                value["adventureCurrentStage"] = current_stage
                snapshot(value)
            if count == 0 or completed < count:
                time.sleep(FREE_DRAW_INTERVAL_SECONDS)
        return {"ret": 0, "completed": completed, "remaining": 0, "reason": "finished"}


def run_divine_mind_collection_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
    interval_minutes: float = 60.0,
) -> dict[str, Any]:
    if count != 1 or not 1 <= interval_minutes <= 1440:
        raise ValueError("Invalid divine mind collection parameters")
    login = _load_login(server_id, output_dir)
    completed = 0
    total_received = 0
    interval_seconds = interval_minutes * 60
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        while stop_event is None or not stop_event.is_set():
            result = session.divine_insight_receive_mind()
            if result["ret"] != 0:
                return {
                    "ret": result["ret"], "completed": completed,
                    "remaining": 0, "reason": "divine_mind_collection_failed",
                    "totalReceived": total_received,
                }
            received = result["receiveNum"] + result["inspireAddNum"]
            completed += 1
            total_received += received
            log(
                f"神躯气海丹田第 {completed} 次收集完成，本次获得 {received} 真元，"
                f"累计获得 {total_received} 真元。"
            )
            if snapshot is not None:
                value = session.resource_snapshot(server_id)
                value["divineMindLastCollected"] = received
                value["divineMindTotalCollected"] = total_received
                snapshot(value)
            if stop_event is None:
                return {
                    "ret": 0, "completed": completed, "remaining": 0,
                    "reason": "finished", "totalReceived": total_received,
                }
            log(f"神躯气海丹田将在 {interval_minutes:g} 分钟后再次收集。")
            if stop_event.wait(interval_seconds):
                break
        return {
            "ret": 0, "completed": completed, "remaining": 0,
            "reason": "stopped", "totalReceived": total_received,
        }


def run_magic_treasure_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
    free_counts: dict[int, int] | None = None,
    paid_counts: dict[int, int] | None = None,
) -> dict[str, Any]:
    if count != 1:
        raise ValueError("Magic treasure task count must be 1")
    free_counts = free_counts or {}
    paid_counts = paid_counts or {}
    if any(not 0 <= int(value) <= MAGIC_TREASURE_FREE_MAX for value in free_counts.values()):
        raise ValueError("Invalid magic treasure free count")
    if any(not 0 <= int(value) <= 100 for value in paid_counts.values()):
        raise ValueError("Invalid magic treasure paid count")

    login = _load_login(server_id, output_dir)
    free_completed = 0
    paid_completed = 0
    remaining = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        states = session.magic_treasure_state()
        for pool_id, pool_name in MAGIC_TREASURE_POOLS.items():
            selected_free = int(free_counts.get(pool_id, 0))
            selected_paid = int(paid_counts.get(pool_id, 0))
            state = states.get(pool_id)
            available_free = (
                selected_free if state is None
                else max(0, MAGIC_TREASURE_FREE_MAX - int(state.get("freeDrawTimes", 0)))
            )
            free_target = min(selected_free, available_free)
            item_id = int(
                state.get("itemId", MAGIC_TREASURE_COMPASS_ITEMS[pool_id])
                if state is not None else MAGIC_TREASURE_COMPASS_ITEMS[pool_id]
            )
            log(
                f"{pool_name}免费可用 "
                f"{available_free if state is not None else '--'}/2 次，本次选择 {selected_free} 次。"
            )
            for index in range(free_target):
                if stop_event is not None and stop_event.is_set():
                    return {
                        "ret": 0, "completed": free_completed + paid_completed,
                        "remaining": remaining, "reason": "stopped",
                    }
                result = session.magic_treasure_draw(pool_id, 1, item_id=item_id)
                if result["ret"] != 0:
                    return {
                        "ret": result["ret"], "completed": free_completed + paid_completed,
                        "remaining": remaining, "reason": "magic_treasure_free_failed",
                    }
                free_completed += 1
                log(f"{pool_name}第 {index + 1}/{free_target} 次免费寻宝完成。")
                if index + 1 < free_target:
                    time.sleep(FREE_DRAW_INTERVAL_SECONDS)

            compass_available = session.item_count(item_id) if item_id > 0 else 0
            paid_target = min(selected_paid, compass_available)
            remaining += max(0, compass_available - paid_target)
            log(
                f"{pool_name}灵盘可用 {compass_available} 次，本次消耗选择 "
                f"{selected_paid} 次，实际执行 {paid_target} 次。"
            )
            if paid_target > 0:
                result = session.magic_treasure_draw(pool_id, paid_target, item_id=item_id)
                if result["ret"] != 0:
                    return {
                        "ret": result["ret"], "completed": free_completed + paid_completed,
                        "remaining": remaining + paid_target,
                        "reason": "magic_treasure_paid_failed",
                    }
                paid_completed += paid_target
                log(f"{pool_name}消耗灵盘寻宝完成，共执行 {paid_target} 次。")
        if snapshot is not None:
            snapshot(session.resource_snapshot(server_id))
    return {
        "ret": 0, "completed": free_completed + paid_completed,
        "remaining": remaining, "reason": "finished",
        "freeCompleted": free_completed, "paidCompleted": paid_completed,
    }


def run_treasure_auction_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
    claim_rewards: bool = True, begin_explores: bool = True,
    help_friends: bool = True, identify_treasures: bool = True,
    disassemble_quality: int = -1,
) -> dict[str, Any]:
    if disassemble_quality not in (-1, 0, 1, 2):
        raise ValueError("Invalid treasure disassembly quality")
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        state = session.treasure_auction_enter()
        if state.get("ret") != 0:
            return {"ret": state.get("ret"), "completed": 0, "reason": "treasure_enter_failed"}
        places = state.get("places", [])
        if claim_rewards:
            now_ms = int(time.time() * 1000)
            claimable = [p["id"] for p in places if p.get("isCompleted") or (
                p.get("beginTime", 0) > 0 and 0 < p.get("endTime", 0) <= now_ms
            )]
            if claimable:
                result = session.treasure_auction_claim_rewards(claimable)
                if result["ret"] != 0:
                    return {"ret": result["ret"], "completed": completed, "reason": "treasure_claim_failed"}
                completed += len(claimable)
                log(f"仙途寻宝已领取 {len(claimable)} 处寻宝奖励。")
                state = session.treasure_auction_enter()
                places = state.get("places", [])
            # The wire message contains beginTime but the duration comes from client
            # configuration. Probe started places individually so one still-hunting
            # place cannot prevent another completed reward from being claimed.
            unknown_started = [
                p["id"] for p in places
                if p.get("beginTime", 0) > 0 and not p.get("endTime")
                and p["id"] not in claimable
            ]
            probed_claims = 0
            for place_id in unknown_started:
                result = session.treasure_auction_claim_rewards([place_id])
                if result["ret"] == 0:
                    completed += 1
                    probed_claims += 1
            if probed_claims:
                log(f"仙途寻宝已领取 {probed_claims} 处寻宝奖励。")
        if begin_explores:
            unexplored = [p for p in places if p.get("treasureMapId", 0) > 0 and p.get("beginTime", 0) <= 0]
            for place in unexplored:
                if stop_event is not None and stop_event.is_set():
                    return {"ret": 0, "completed": completed, "reason": "stopped"}
                result = session.treasure_auction_begin(place["id"])
                if result["ret"] != 0:
                    return {"ret": result["ret"], "completed": completed, "reason": "treasure_begin_failed"}
                completed += 1
            if unexplored:
                log(f"仙途寻宝已使用 {len(unexplored)} 张藏宝图开始寻宝。")
        if help_friends:
            help_list = session.treasure_auction_get_help_list()
            if help_list["ret"] == 0 and help_list.get("entries"):
                result = session.treasure_auction_help_one_key()
                if result["ret"] != 0:
                    return {"ret": result["ret"], "completed": completed, "reason": "treasure_help_failed"}
                completed += 1
                log("仙途寻宝好友一键协助完成。")
        if identify_treasures:
            state = session.treasure_auction_enter()
            items = state.get("items", [])
            identified = [item for item in items if item.get("isIdentify")]
            unidentified = [item for item in items if not item.get("isIdentify") and not item.get("isSelling")]
            limit = state.get("warehouseLimit", 0)
            free_slots = max(0, limit - len(identified))
            removed_count = 0
            if unidentified and free_slots == 0 and disassemble_quality >= 0:
                equipped = set(state.get("equipIds", set()))
                removable = [item["id"] for item in identified
                    if item.get("quality", 99) <= disassemble_quality and not item.get("lock")
                    and not item.get("isSelling") and item["id"] not in equipped]
                if removable:
                    result = session.treasure_auction_disassemble(removable)
                    if result["ret"] != 0:
                        return {"ret": result["ret"], "completed": completed, "reason": "treasure_disassemble_failed"}
                    free_slots += len(removable)
                    removed_count = len(removable)
                    completed += len(removable)
                    log(f"仙囊已满，自动分解 {len(removable)} 件所选品阶及以下藏宝。")
            identify_count = min(len(unidentified), free_slots)
            for item in unidentified[:identify_count]:
                result = session.treasure_auction_identify(item["id"])
                if result["ret"] != 0:
                    return {"ret": result["ret"], "completed": completed, "reason": "treasure_identify_failed"}
                completed += 1
            log(f"仙途寻宝状态：藏宝图 {len([p for p in places if p.get('treasureMapId', 0)])} 张，仙囊 {len(identified) - removed_count + identify_count}/{limit}，待鉴宝 {len(unidentified) - identify_count} 件。")
        if snapshot is not None:
            value = session.resource_snapshot(server_id)
            value["treasureMapCount"] = len([p for p in places if p.get("treasureMapId", 0)])
            if identify_treasures:
                value["treasureWarehouseUsed"] = len(identified) - removed_count + identify_count
                value["treasureWarehouseLimit"] = limit
                value["treasureUnidentifiedCount"] = len(unidentified) - identify_count
            snapshot(value)
        return {"ret": 0, "completed": completed, "remaining": 0, "reason": "finished"}


def run_homeland_tasks(
    server_id: int, output_dir: Path, count: int, log: Callable[[str], None],
    stop_event: threading.Event | None = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
    preferred_item_id: int = 100004,
    preferred_level: int = 3,
) -> dict[str, Any]:
    if count != 1:
        raise ValueError("Homeland task count must be 1")
    if preferred_item_id not in HOMELAND_RESOURCE_NAMES or not 1 <= preferred_level <= 5:
        raise ValueError("Invalid homeland resource preference")

    login = _load_login(server_id, output_dir)
    completed = 0
    dispatched = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        player_id = session.player_id
        state = session.homeland_state()
        if state is None:
            log("福地鼠宝数据读取失败，本次不派遣。")
            return {"ret": None, "completed": 0, "remaining": None, "reason": "homeland_state_unknown"}

        now_ms = int(time.time() * 1000)
        released_workers = 0
        for job in session.homeland_manage():
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": completed, "remaining": None, "reason": "stopped"}
            competitors = [job.get("owner"), job.get("enemy")]
            mine = next(
                (item for item in competitors if item and item.get("playerId") == player_id),
                None,
            )
            if mine is None or not job.get("finishTime") or job["finishTime"] > now_ms:
                continue
            result = session.homeland_dispatch(job["playerId"], job["pos"], 0)
            if result["ret"] == 0:
                completed += 1
                released_workers += max(1, int(mine.get("workerNum", 1)))
                log(f"福地采集已完成并领取：位置 {job['pos'] + 1}。")
            else:
                log(f"福地完成项领取失败，服务端返回 {result['ret']}，继续检查其他资源。")

        free_workers = min(
            state["totalWorkerNum"], state["freeWorkerNum"] + released_workers,
        )
        if free_workers <= 0:
            log(f"福地鼠宝均在采集中，共 {state['totalWorkerNum']} 只。")
            return {"ret": 0, "completed": completed, "remaining": 0, "reason": "finished"}
        preferred_name = HOMELAND_RESOURCE_NAMES[preferred_item_id]
        log(f"福地有 {free_workers}/{state['totalWorkerNum']} 只空闲鼠宝，优先采集 {preferred_level} 级{preferred_name}。")
        if state.get("energy", 0) <= 0:
            log("鼠宝体力已枯竭，将继续派遣，但采集速度会降低。")

        def load_candidates(explore: dict[str, Any] | None = None, include_self: bool = False) -> list[dict[str, Any]]:
            homelands = []
            if include_self:
                own = session.homeland_enter(player_id)
                if own is not None:
                    homelands.append(own)
            if explore is not None:
                seen_players = set()
                for player in explore["near"] + explore["enemy"]:
                    other_id = player["playerId"]
                    if other_id == player_id or other_id in seen_players:
                        continue
                    seen_players.add(other_id)
                    entered = session.homeland_enter(other_id)
                    if entered is not None:
                        homelands.append(entered)

            candidates = []
            for homeland in homelands:
                is_self = homeland["playerId"] == player_id
                for reward in homeland["rewards"]:
                    item_id = _homeland_reward_item_id(reward)
                    if item_id not in HOMELAND_RESOURCE_NAMES:
                        continue
                    if reward.get("owner") or reward.get("enemy"):
                        continue
                    if not is_self and reward.get("isOnlyOwnerPull"):
                        continue
                    level = int(reward.get("level", 0))
                    if item_id == preferred_item_id and level == preferred_level:
                        priority = 0
                    elif item_id == preferred_item_id:
                        priority = 1
                    else:
                        priority = 2
                    candidates.append({
                        **reward,
                        "itemId": item_id,
                        "homelandPlayerId": homeland["playerId"],
                        "isSelf": is_self,
                        "sortKey": (priority, -level, 0 if is_self else 1, reward["pos"]),
                    })
            return sorted(candidates, key=lambda item: item["sortKey"])

        explore = session.homeland_explore()
        if explore["ret"] != 0:
            log(f"福地探寻失败，服务端返回 {explore['ret']}，仅采集自己的资源。")
            explore = None
        candidates = load_candidates(explore, include_self=True)
        used_remote_players: set[int] = set()

        def dispatch_candidates(items: list[dict[str, Any]]) -> None:
            nonlocal free_workers, dispatched
            for item in items:
                if free_workers <= 0:
                    break
                if stop_event is not None and stop_event.is_set():
                    break
                target_id = item["homelandPlayerId"]
                if not item["isSelf"] and target_id in used_remote_players:
                    continue
                worker_num = min(free_workers, max(1, int(item.get("maxWorkerNum", 1))))
                result = session.homeland_dispatch(target_id, item["pos"], worker_num)
                if result["ret"] != 0:
                    log(f"福地派遣失败，服务端返回 {result['ret']}，继续尝试其他资源。")
                    continue
                free_workers -= worker_num
                dispatched += worker_num
                if not item["isSelf"]:
                    used_remote_players.add(target_id)
                scope = "自己" if item["isSelf"] else "他人"
                name = HOMELAND_RESOURCE_NAMES[item["itemId"]]
                log(f"已派遣 {worker_num} 只鼠宝采集{scope}的 {item['level']} 级{name}。")

        dispatch_candidates(candidates)

        if free_workers > 0 and explore is not None:
            elapsed = now_ms - explore["lastRefreshTime"]
            if explore["lastRefreshTime"] <= 0 or elapsed >= HOMELAND_REFRESH_COOLDOWN_MS:
                refreshed = session.homeland_explore(refresh=True)
                if refreshed["ret"] == 0:
                    log("福地探寻列表已刷新，继续为剩余鼠宝寻找资源。")
                    dispatch_candidates(load_candidates(refreshed))
                else:
                    log(f"福地探寻刷新失败，服务端返回 {refreshed['ret']}。")
            else:
                wait_seconds = max(1, (HOMELAND_REFRESH_COOLDOWN_MS - elapsed + 999) // 1000)
                log(f"福地探寻刷新冷却中，还需约 {wait_seconds} 秒。")

        if snapshot is not None:
            snapshot(session.resource_snapshot(server_id))
        if free_workers > 0:
            log(f"福地仍有 {free_workers} 只空闲鼠宝，当前没有可采集资源。")
        return {
            "ret": 0, "completed": completed + dispatched,
            "remaining": free_workers, "reason": "finished",
        }


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

        errors: list[tuple[int, str]] = []
        trees = yard_buildings_of_type(buildings, YARD_BUILD_TREE)
        # Tree timing fields are not populated consistently across server versions.
        # Claiming is side-effect free when no fruit is ready, so let the server decide.
        claimable_trees = [tree for tree in trees if tree.get("status") != 2]
        tree_collected = 0
        for tree in claimable_trees:
            result = session.yard_collect(tree)
            if result["ret"] != 0:
                log(f"仙桃树当前无可收取产物，服务端返回 {result['ret']}。")
                continue
            completed += 1
            tree_collected += 1
        if tree_collected:
            log(f"仙桃树收桃完成 {tree_collected}/{len(claimable_trees)} 棵。")
        elif claimable_trees:
            log(f"已检查 {len(claimable_trees)} 棵仙桃树，当前没有可收取的仙桃。")
        elif trees:
            log("仙桃树正在升级，本次不收取。")

        farmlands = yard_buildings_of_type(buildings, YARD_BUILD_FARMLAND)
        ready_farmlands = [field for field in farmlands if yard_continuous_reward_available(field)]
        farmland_collected = 0
        for farmland in ready_farmlands:
            result = session.yard_collect(farmland)
            if result["ret"] != 0:
                errors.append((result["ret"], "yard_farmland_collect_failed"))
                log(f"灵田 {farmland.get('uniqueId', 0)} 收菜失败，服务端返回 {result['ret']}，继续处理其他建筑。")
                continue
            completed += 1
            farmland_collected += 1
        if ready_farmlands:
            log(f"灵田收菜完成 {farmland_collected}/{len(ready_farmlands)} 块，正在检查可炼丹数量。")
        elif farmlands:
            log(f"已检查 {len(farmlands)} 块灵田，当前没有可收取的灵草。")

        stoves = yard_buildings_of_type(buildings, YARD_BUILD_STOVE)
        stove = stoves[0] if stoves else None
        stove_idle = bool(stove and stove.get("status") == 0)
        if stove and yard_build_finished(stove):
            result = session.yard_collect(stove)
            if result["ret"] != 0:
                log(f"炼丹炉收丹失败，服务端返回 {result['ret']}。")
                errors.append((result["ret"], "yard_alchemy_collect_failed"))
                stove_idle = False
            else:
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
                    errors.append((result["ret"], "yard_alchemy_start_failed"))
                else:
                    completed += 1
                    log(f"已消耗灵草启动炼丹，共 {alchemy_count} 次。")
            else:
                log(f"当前灵草 {grass}，不足 {YARD_HERB_COST}，不启动炼丹。")

        cisterns = yard_buildings_of_type(buildings, YARD_BUILD_CISTERN)
        cistern = cisterns[0] if cisterns else None
        cistern_idle = bool(cistern and cistern.get("status") == 0)
        if cistern and yard_build_finished(cistern):
            result = session.yard_collect(cistern)
            if result["ret"] != 0:
                log(f"化外灵池收取失败，服务端返回 {result['ret']}。")
                errors.append((result["ret"], "yard_cistern_collect_failed"))
                cistern_idle = False
            else:
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
                errors.append((result["ret"], "yard_cistern_start_failed"))
            else:
                completed += 1
                log(f"化外灵池已开始孕育，产物 {product_id}，数量 {product_count}。")

        if snapshot is not None:
            snapshot(session.resource_snapshot(server_id))
        if errors:
            ret, reason = errors[0]
            return {"ret": ret, "completed": completed, "remaining": 1, "reason": reason}
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
        draw_data = entered["drawData"]
        normal_free = 1 if draw_data.get("freeDrawTimes", 0) < 1 else 0
        ad_free = max(0, YARD_AD_FREE_DAILY_MAX - draw_data.get("adCount", 0))
        log(f"仙居造物计划执行 {count} 次，普通免费 {normal_free} 次，广告免费 {ad_free}/2 次。")

        free_modes = ([False] * normal_free + [True] * ad_free)[:count]
        for index, is_ad in enumerate(free_modes):
            if stop_event is not None and stop_event.is_set():
                return {"ret": 0, "completed": completed, "remaining": count - completed, "reason": "stopped"}
            result = session.yard_draw(False, is_ad=is_ad)
            if result["ret"] == 30225:
                continue
            if result["ret"] != 0:
                return {"ret": result["ret"], "completed": completed, "remaining": count - completed, "reason": "yard_draw_failed"}
            completed += 1
            free_name = "广告免费" if is_ad else "普通免费"
            log(f"仙居造物{free_name}完成，当前 {completed}/{count} 次。")
            if completed < count and index + 1 < len(free_modes):
                time.sleep(FREE_DRAW_INTERVAL_SECONDS)

        batches: list[bool] = []
        remaining = count - completed
        batches.extend([True] * (remaining // 10))
        batches.extend([False] * (remaining % 10))
        for ten in batches:
            if stop_event is not None and stop_event.is_set():
                return {
                    "ret": 0, "completed": completed,
                    "remaining": count - completed, "reason": "stopped",
                }
            result = session.yard_draw(ten, is_ad=False)
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


def run_pupil_training(
    server_id: int,
    output_dir: Path,
    log: Callable[[str], None],
    max_rounds: int = 100,
) -> dict[str, Any]:
    """Use existing disciple training attempts without buying or graduating."""
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        enter = session._request(PUPIL_ENTER, PUPIL_ENTER_RESPONSE)
        enter_ret = response_ret(enter)
        if enter_ret != 0:
            return {"ret": enter_ret, "completed": 0, "reason": "enter_failed"}
        log("门徒系统数据加载成功，开始一键修炼。")
        for _ in range(max_rounds):
            response = session._request(PUPIL_TRAIN, PUPIL_TRAIN_RESPONSE, protobuf_int(1, 1))
            ret = response_ret(response)
            if ret != 0:
                reason = "no_more_attempts" if completed else "train_failed"
                return {"ret": ret, "completed": completed, "reason": reason}
            completed += 1
            log(f"弟子一键修炼第 {completed} 轮成功。")
            time.sleep(0.35)
    return {"ret": 0, "completed": completed, "reason": "safety_limit"}


def run_pupil_training_tasks(
    server_id: int,
    output_dir: Path,
    max_rounds: int,
    log: Callable[[str], None],
    stop_event: Any = None,
    snapshot: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Task-runner adapter used by the Qt operation queue."""
    if stop_event is not None and stop_event.is_set():
        return {"ret": 0, "completed": 0, "reason": "stopped"}
    result = run_pupil_training(server_id, output_dir, log, max_rounds=max_rounds)
    if snapshot is not None:
        try:
            snapshot(fetch_role_snapshot(server_id, output_dir))
        except Exception:
            pass
    return result
