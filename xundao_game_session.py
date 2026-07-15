#!/usr/bin/env python3
"""Authenticated game WebSocket session and guarded tree-chop automation."""

from __future__ import annotations

import json
import struct
import time
from pathlib import Path
from typing import Any, Callable

import websocket

HEADER = 29099
HEADER_SIZE = 18
PLAYER_LOGIN = 20001
LOGIN_SYNC_OVER = 2
CHOP_TREE = 20203
CHOP_TREE_RESPONSE = 203
DEAL_EQUIPMENT = 20202
DEAL_EQUIPMENT_RESPONSE = 202
GET_PENDING_EQUIPMENT = 20209
GET_PENDING_EQUIPMENT_RESPONSE = 209


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
        config_ids = _values(message, 2)
        qualities = _values(message, 3)
        slots = _values(message, 4)
        sources = _values(message, 6)
        attrs = _children(message, 5)
        if not (ids and config_ids and qualities and slots and sources and attrs):
            continue
        # Equipment config IDs use the 7-digit 10xxyyzz form and quality is a
        # small enum. This excludes similarly shaped role/loadout messages.
        if int(config_ids[0]) < 1_000_000 or not 0 < int(qualities[0]) <= 20:
            continue
        attributes = []
        for attr in attrs:
            types = _values(attr, 1)
            values = next((field.get("text") for field in attr if field["field"] == 2 and "text" in field), None)
            if types and values is not None:
                attributes.append({"type": int(types[0]), "value": values})
        equipment_id = int(ids[0])
        found[equipment_id] = {
            "id": equipment_id,
            "configId": int(config_ids[0]),
            "quality": int(qualities[0]),
            "slot": int(slots[0]),
            "src": int(sources[0]),
            "attributes": attributes,
        }
    return list(found.values())


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


class GameSession:
    def __init__(self, ws_address: str, player_id: int, token: str, timeout: float = 30) -> None:
        self.ws_address = ws_address
        self.player_id = int(player_id)
        self.token = token
        self.timeout = timeout
        self.socket: websocket.WebSocket | None = None
        self.login_frames: list[tuple[int, bytes]] = []

    def connect(self) -> None:
        self.socket = websocket.create_connection(
            self.ws_address, timeout=self.timeout, origin="https://www.wanyiwan.top", http_proxy_host=None
        )
        payload = protobuf_string(1, self.token) + protobuf_string(2, "zh_cn") + protobuf_int(3, 0)
        self.socket.send_binary(make_frame(PLAYER_LOGIN, self.player_id, payload))
        self.login_frames = self._collect_login_sync()

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
            if player_id == self.player_id and message_id == target_message_id:
                return payload
        raise RuntimeError(f"Timed out waiting for game message {target_message_id}")

    def _request(self, message_id: int, response_id: int, payload: bytes = b"") -> bytes:
        if self.socket is None:
            self.connect()
        assert self.socket is not None
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
        return {"ret": response_ret(response), "equipment": equipment[:1], "payloadHex": response.hex()}

    def decompose(self, equipment_ids: list[int]) -> dict[str, Any]:
        if not equipment_ids:
            raise ValueError("No equipment selected for decomposition")
        # protobufjs encodes repeated numeric proto3 fields in packed form.
        payload = protobuf_int(1, 1) + protobuf_packed_ints(2, equipment_ids)
        response = self._request(DEAL_EQUIPMENT, DEAL_EQUIPMENT_RESPONSE, payload)
        return {"ret": response_ret(response), "payloadHex": response.hex()}

    def close(self) -> None:
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def __enter__(self) -> "GameSession":
        self.connect()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def _load_login(server_id: int, output_dir: Path) -> dict[str, Any]:
    return json.loads((output_dir / f"player-login-{server_id}.json").read_text(encoding="utf-8-sig"))


def fetch_role_snapshot(server_id: int, output_dir: Path) -> dict[str, Any]:
    """Read currency and player attributes from the login synchronization stream."""
    login = _load_login(server_id, output_dir)
    snapshot: dict[str, Any] = {
        "serverId": server_id, "spiritStone": 0, "jade": 0,
        "power": "0", "cultivation": "0", "realmId": 0,
    }
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        for message_id, payload in session.login_frames:
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
                inventory: dict[int, int] = {}
                for item in _children(fields, 1):
                    item_ids = _values(item, 1)
                    count = next((field.get("text") for field in item if field["field"] == 2 and "text" in field), None)
                    if item_ids and count is not None:
                        inventory[int(item_ids[0])] = int(count)
                snapshot["jade"] = inventory.get(100000, 0)
                snapshot["spiritStone"] = inventory.get(100003, 0)
    return snapshot


def run_chop_tasks(
    server_id: int,
    output_dir: Path,
    count: int,
    interval: float,
    equipment_action: str,
    keep_quality: int,
    log: Callable[[str], None],
) -> dict[str, Any]:
    """Run sequential chops, resolving only verified tree-drop equipment."""
    login = _load_login(server_id, output_dir)
    completed = 0
    with GameSession(login["wsAddress"], int(login["playerId"]), login["token"]) as session:
        pending = session.get_pending_equipment()
        for index in range(count):
            equipment = pending
            if not equipment:
                # The in-game automatic mode sends auto=true. Filtering and
                # equipment decisions are still performed by the client.
                result = session.chop_tree(auto=True)
                if result["ret"] != 0:
                    log(f"第 {completed + 1}/{count} 次砍树被服务器拒绝，返回码 {result['ret']}。")
                    return {"ret": result["ret"], "completed": completed, "reason": "chop_failed"}
                equipment = result["equipment"] or session.get_pending_equipment()
                completed += 1
                log(f"第 {completed}/{count} 次砍树成功。")
            if equipment:
                summary = "，".join(f"ID {e['id']} 品质 {e['quality']} 来源 {e['src']}" for e in equipment)
                log(f"待处理装备：{summary}")
                unsafe = [e for e in equipment if e["src"] != 1]
                if unsafe:
                    return {"ret": None, "completed": completed, "reason": "unsafe_source", "equipment": unsafe}
                keep = [e for e in equipment if e["quality"] >= keep_quality]
                if equipment_action != "decompose" or keep:
                    return {"ret": 0, "completed": completed, "reason": "kept", "equipment": keep or equipment}
                deal = session.decompose([e["id"] for e in equipment])
                if deal["ret"] != 0:
                    return {"ret": deal["ret"], "completed": completed, "reason": "decompose_failed"}
                log(f"已自动分解 {len(equipment)} 件砍树装备。")
                pending = []
            if index + 1 < count and interval > 0:
                time.sleep(interval)
    return {"ret": 0, "completed": completed, "reason": "finished"}
