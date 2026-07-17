import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import xundao_game_session as game


class GameSessionTimeoutTests(unittest.TestCase):
    def test_wait_for_uses_one_absolute_deadline_for_unrelated_frames(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token", timeout=0.02)
        fake_socket = Mock()
        fake_socket.recv.side_effect = lambda: (
            time.sleep(0.006) or game.make_frame(999, 1, b"unrelated")
        )
        session.socket = fake_socket

        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            session._wait_for(123, timeout_messages=100)

        self.assertLess(time.monotonic() - started, 0.1)
        self.assertGreaterEqual(fake_socket.settimeout.call_count, 1)


def message_field(number: int, payload: bytes) -> bytes:
    return game.encode_varint(number << 3 | 2) + game.encode_varint(len(payload)) + payload


def string_field(number: int, value: str) -> bytes:
    return message_field(number, value.encode("utf-8"))


class DestinyTravelTests(unittest.TestCase):
    def test_parse_destiny_power_and_snapshot(self) -> None:
        player_data = game.protobuf_int(1, 7) + game.protobuf_int(2, 123456)
        payload = message_field(2, player_data)

        self.assertEqual(game.parse_destiny_power(payload), 7)
        snapshot = game._snapshot_from_frames(42, [(game.DESTINY_SYNC, payload)])
        self.assertEqual(snapshot["destinyPower"], 7)

    def test_travel_request_uses_single_travel_mode(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []

        def request(message_id: int, response_id: int, payload: bytes = b"") -> bytes:
            captured.append((message_id, response_id, payload))
            return game.protobuf_int(1, 0)

        session._request = request  # type: ignore[method-assign]
        result = session.travel_destiny()

        self.assertEqual(result["ret"], 0)
        self.assertEqual(captured, [(
            game.DESTINY_TRAVEL,
            game.DESTINY_TRAVEL_RESPONSE,
            game.protobuf_int(1, 0),
        )])

    def test_task_stops_at_available_power(self) -> None:
        snapshots = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                self.power = 2

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def destiny_power(self) -> int:
                return self.power

            def travel_destiny(self):
                self.power -= 1
                return {"ret": 0}

            def resource_snapshot(self, server_id: int):
                return {"serverId": server_id, "destinyPower": self.power}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_destiny_travel_tasks(
                    42, output_dir, 5, lambda _message: None,
                    snapshot=snapshots.append,
                )

        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["remaining"], 0)
        self.assertEqual([item["destinyPower"] for item in snapshots], [1, 0])

    def test_task_runs_when_login_sync_omits_destiny_power(self) -> None:
        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                self.completed = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def destiny_power(self):
                return None

            def travel_destiny(self):
                self.completed += 1
                return {"ret": 0}

            def resource_snapshot(self, server_id: int):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_destiny_travel_tasks(
                    42, output_dir, 3, lambda _message: None,
                )

        self.assertEqual(result["completed"], 3)
        self.assertEqual(result["reason"], "finished")


class ProfessionTrialTests(unittest.TestCase):
    def test_parse_profession_state_and_snapshot(self) -> None:
        boss_data = (
            game.protobuf_int(1, 50022)
            + game.protobuf_int(2, 4)
            + game.protobuf_int(3, 0)
        )
        payload = game.protobuf_int(1, 3) + message_field(4, boss_data)

        state = game.parse_profession_state(payload)
        self.assertEqual(state, {
            "careerType": 3,
            "lastPassedBossId": 50022,
            "battleTimesToday": 4,
            "repeatTimesToday": 0,
        })
        snapshot = game._snapshot_from_frames(42, [(game.PROFESSION_SYNC, payload)])
        self.assertEqual(snapshot["professionLastBossId"], 50022)
        self.assertEqual(snapshot["professionQuickRemaining"], 1)
        self.assertEqual(snapshot["professionChallengeRemaining"], 26)

    def test_profession_battle_request_and_win_result(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []
        battle_record = game.protobuf_int(3, 1)
        response = game.protobuf_int(1, 0) + message_field(2, battle_record)

        def request(message_id: int, response_id: int, payload: bytes = b"") -> bytes:
            captured.append((message_id, response_id, payload))
            return response

        session._request = request  # type: ignore[method-assign]
        result = session.profession_battle(50023, 2)

        self.assertEqual(result["ret"], 0)
        self.assertIs(result["win"], True)
        self.assertEqual(captured, [(
            game.PROFESSION_BATTLE,
            game.PROFESSION_BATTLE_RESPONSE,
            game.protobuf_int(1, 50023) + game.protobuf_int(2, 2),
        )])

    def test_challenge_retries_same_boss_after_loss(self) -> None:
        requested = []
        results = iter([True, False, True])

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def profession_state(self):
                return {
                    "careerType": 3, "lastPassedBossId": 50022,
                    "battleTimesToday": 0, "repeatTimesToday": 0,
                }

            def profession_battle(self, boss_id: int, battle_type: int):
                requested.append((boss_id, battle_type))
                return {"ret": 0, "win": next(results)}

            def resource_snapshot(self, server_id: int):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_profession_challenge_tasks(
                    42, output_dir, 3, lambda _message: None,
                )

        self.assertEqual(requested, [(50023, 2), (50024, 2), (50024, 2)])
        self.assertEqual(result["completed"], 3)
        self.assertEqual(result["remaining"], 27)
        self.assertEqual(result["reason"], "finished")


class YardTaskTests(unittest.TestCase):
    def test_parse_yard_buildings_and_draw_data(self) -> None:
        cell = game.protobuf_int(1, 90001) + game.protobuf_int(2, game.YARD_BUILD_CISTERN)
        detail = (
            game.protobuf_int(1, 3)
            + game.protobuf_int(2, 1)
            + game.protobuf_int(3, 400003)
            + game.protobuf_int(4, 1_000)
            + game.protobuf_int(5, 2_000)
            + game.protobuf_int(6, 2)
            + game.protobuf_int(8, 8)
        )
        building = message_field(1, cell) + message_field(2, detail)
        area = message_field(3, building)
        draw = game.protobuf_int(1, 1) + game.protobuf_int(2, 12)
        payload = game.protobuf_int(1, 0) + message_field(2, area) + message_field(8, draw)

        self.assertEqual(game.parse_yard_buildings(payload)[game.YARD_BUILD_CISTERN], [{
            "uniqueId": 90001,
            "buildId": game.YARD_BUILD_CISTERN,
            "level": 3,
            "status": 1,
            "productId": 400003,
            "startTime": 1_000,
            "endTime": 2_000,
            "collectNum": 2,
            "totalNum": 8,
        }])
        self.assertEqual(game.parse_yard_draw_data(payload)["drawCount"], 12)

    def test_yard_ad_draw_encodes_ad_type_separately_from_ad_time(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        requests = []

        def request(message_id, response_id, payload=b""):
            requests.append((message_id, response_id, game.parse_protobuf(payload)))
            return game.protobuf_int(1, 0)

        session._request = request
        session.yard_draw(is_ad=True)

        fields = requests[0][2]
        self.assertEqual(game._values(fields, 1), [0])
        self.assertEqual(game._values(fields, 2), [0])
        self.assertEqual(game._values(fields, 3), [1])
        self.assertEqual(game._values(fields, 4), [0])

    def test_daily_tasks_collect_partial_alchemy_without_restarting(self) -> None:
        actions = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def enter_yard(self):
                return {
                    "ret": 0, "drawData": {},
                    "buildings": {game.YARD_BUILD_STOVE: {
                        "uniqueId": 2, "buildId": game.YARD_BUILD_STOVE,
                        "status": 1, "startTime": 1, "endTime": 9_999_999_999_999,
                        "collectNum": 3, "totalNum": 10,
                    }},
                }

            def yard_collect(self, building):
                actions.append(("collect", building["buildId"]))
                return {"ret": 0}

            def yard_make(self, building, count, product_id=None):
                actions.append(("make", building["buildId"], count, product_id))
                return {"ret": 0}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                game.run_yard_daily_tasks(42, output_dir, 1, lambda _message: None)

        self.assertEqual(actions, [("collect", game.YARD_BUILD_STOVE)])

    def test_daily_tasks_restart_alchemy_after_collecting_finished_batch(self) -> None:
        actions = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def enter_yard(self):
                return {
                    "ret": 0, "drawData": {},
                    "buildings": {game.YARD_BUILD_STOVE: {
                        "uniqueId": 2, "buildId": game.YARD_BUILD_STOVE,
                        "status": 1, "startTime": 1, "endTime": 2,
                        "collectNum": 10, "totalNum": 10,
                    }},
                }

            def yard_collect(self, building):
                actions.append(("collect", building["buildId"]))
                return {"ret": 0}

            def yard_grass_num(self):
                return 1_000

            def yard_make(self, building, count, product_id=None):
                actions.append(("make", building["buildId"], count, product_id))
                return {"ret": 0}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                game.run_yard_daily_tasks(42, output_dir, 1, lambda _message: None)

        self.assertEqual(actions, [
            ("collect", game.YARD_BUILD_STOVE),
            ("make", game.YARD_BUILD_STOVE, 2, None),
        ])

    def test_daily_tasks_skip_cistern_while_gestating(self) -> None:
        collected = []
        made = []
        now = int(time.time() * 1000)

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def enter_yard(self):
                return {
                    "ret": 0,
                    "drawData": {},
                    "buildings": {
                        game.YARD_BUILD_FARMLAND: {
                            "uniqueId": 1, "buildId": game.YARD_BUILD_FARMLAND,
                            "status": 1, "startTime": now - 600_000, "collectNum": 0,
                        },
                        game.YARD_BUILD_STOVE: {
                            "uniqueId": 2, "buildId": game.YARD_BUILD_STOVE,
                            "status": 0, "startTime": 0,
                        },
                        game.YARD_BUILD_CISTERN: {
                            "uniqueId": 3, "buildId": game.YARD_BUILD_CISTERN,
                            "status": 1, "startTime": now, "endTime": now + 600_000,
                            "productId": 400004, "totalNum": 2, "collectNum": 0,
                        },
                    },
                }

            def yard_collect(self, building):
                collected.append(building["buildId"])
                return {"ret": 0}

            def yard_grass_num(self):
                return 1_000

            def item_count(self, _item_id):
                return 0

            def yard_make(self, building, count, product_id=None):
                made.append((building["buildId"], count, product_id))
                return {"ret": 0}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_yard_daily_tasks(42, output_dir, 1, lambda _message: None)

        self.assertEqual(collected, [game.YARD_BUILD_FARMLAND])
        self.assertEqual(made, [(game.YARD_BUILD_STOVE, 2, None)])
        self.assertEqual(result["reason"], "finished")


class InvadeTaskTests(unittest.TestCase):
    def test_invade_state_actively_requests_current_data(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []

        def request(message_id, response_id, payload=b"", timeout=None):
            captured.append((message_id, response_id, payload))
            return game.protobuf_int(1, 9001) + game.protobuf_int(3, 0)

        session._request = request
        self.assertEqual(session.invade_state(), (0, 5))
        self.assertEqual(captured, [(game.INVADE_GET_DATA, game.INVADE_SYNC, b"")])

    def test_invade_task_runs_when_sync_is_missing(self) -> None:
        challenges = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def invade_state(self):
                return None

            def challenge_invade(self):
                challenges.append(True)
                return {"ret": 0, "used": None}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_invade_tasks(42, output_dir, 3, lambda _message: None)

        self.assertEqual(len(challenges), 3)
        self.assertEqual(result["completed"], 3)

    def test_daily_tasks_attempt_tree_collect_without_timing_fields(self) -> None:
        collected = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def enter_yard(self):
                return {
                    "ret": 0,
                    "drawData": {},
                    "buildings": {
                        game.YARD_BUILD_TREE: [{
                            "uniqueId": 9, "buildId": game.YARD_BUILD_TREE,
                            "status": 0, "startTime": 0, "collectNum": 0,
                        }],
                    },
                }

            def yard_collect(self, building):
                collected.append(building["uniqueId"])
                return {"ret": 0}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_yard_daily_tasks(42, output_dir, 1, lambda _message: None)

        self.assertEqual(collected, [9])
        self.assertEqual(result["reason"], "finished")

    def test_daily_tasks_collect_all_farmlands_and_continue_after_failure(self) -> None:
        actions = []
        now = int(time.time() * 1000)

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def enter_yard(self):
                farmlands = [
                    {
                        "uniqueId": unique_id,
                        "buildId": game.YARD_BUILD_FARMLAND,
                        "status": 1,
                        "startTime": now - 600_000,
                        "collectNum": 1,
                    }
                    for unique_id in range(1, 7)
                ]
                return {
                    "ret": 0,
                    "drawData": {},
                    "buildings": {
                        game.YARD_BUILD_FARMLAND: farmlands,
                        game.YARD_BUILD_STOVE: [{
                            "uniqueId": 7, "buildId": game.YARD_BUILD_STOVE,
                            "status": 1, "startTime": now - 600_000,
                            "endTime": now - 1,
                        }],
                        game.YARD_BUILD_CISTERN: [{
                            "uniqueId": 8, "buildId": game.YARD_BUILD_CISTERN,
                            "status": 1, "startTime": now - 600_000,
                            "endTime": now - 1, "productId": 400004,
                            "totalNum": 2, "collectNum": 0,
                        }],
                    },
                }

            def yard_collect(self, building):
                actions.append(("collect", building["uniqueId"]))
                return {"ret": 123 if building["uniqueId"] == 1 else 0}

            def yard_grass_num(self):
                return 1_000

            def yard_make(self, building, count, product_id=None):
                actions.append(("make", building["uniqueId"], count, product_id))
                return {"ret": 0}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_yard_daily_tasks(42, output_dir, 1, lambda _message: None)

        self.assertEqual([action for action in actions if action[0] == "collect"], [
            ("collect", 1), ("collect", 2), ("collect", 3), ("collect", 4),
            ("collect", 5), ("collect", 6), ("collect", 7), ("collect", 8),
        ])
        self.assertIn(("make", 7, 2, None), actions)
        self.assertIn(("make", 8, 2, 400004), actions)
        self.assertEqual(result["reason"], "yard_farmland_collect_failed")

    def test_finished_cistern_restarts_previous_product_and_count(self) -> None:
        actions = []
        now = int(time.time() * 1000)

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def enter_yard(self):
                return {
                    "ret": 0, "drawData": {},
                    "buildings": {
                        game.YARD_BUILD_CISTERN: {
                            "uniqueId": 3, "buildId": game.YARD_BUILD_CISTERN,
                            "status": 1, "startTime": now - 1_000_000,
                            "endTime": now - 1, "productId": 400006,
                            "totalNum": 3, "collectNum": 0,
                        },
                    },
                }

            def yard_collect(self, building):
                actions.append(("collect", building["buildId"]))
                return {"ret": 0}

            def yard_make(self, building, count, product_id=None):
                actions.append(("make", building["buildId"], count, product_id))
                return {"ret": 0}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                game.run_yard_daily_tasks(42, output_dir, 1, lambda _message: None)

        self.assertEqual(actions, [
            ("collect", game.YARD_BUILD_CISTERN),
            ("make", game.YARD_BUILD_CISTERN, 3, 400006),
        ])


class HomelandTaskTests(unittest.TestCase):
    def test_parse_homeland_state_enter_and_explore(self) -> None:
        state = game.protobuf_int(1, 3) + game.protobuf_int(2, 5) + game.protobuf_int(3, 80)
        self.assertEqual(game.parse_homeland_state(state), {
            "freeWorkerNum": 3, "totalWorkerNum": 5, "energy": 80,
        })

        competitor = game.protobuf_int(1, 42) + game.protobuf_int(4, 1)
        reward = (
            string_field(1, "100004=10")
            + game.protobuf_int(2, 4)
            + game.protobuf_int(4, 2)
            + game.protobuf_int(5, 3)
            + message_field(6, competitor)
            + game.protobuf_int(8, 1234)
            + game.protobuf_int(9, 42)
        )
        owner = game.protobuf_int(1, 42) + string_field(2, "自己")
        homeland = message_field(2, reward) + message_field(4, owner)
        entered = game.parse_homeland_enter(message_field(1, homeland))
        self.assertEqual(entered["playerId"], 42)
        self.assertEqual(entered["rewards"][0]["level"], 4)
        self.assertEqual(entered["rewards"][0]["owner"]["workerNum"], 1)

        player_info = game.protobuf_int(1, 99) + string_field(2, "邻居")
        near = message_field(1, player_info) + game.protobuf_int(2, 10032)
        explore = message_field(1, near) + game.protobuf_int(3, 5_000)
        parsed = game.parse_homeland_explore(game.protobuf_int(1, 0) + message_field(2, explore))
        self.assertEqual(parsed["near"], [{"playerId": 99, "rewardIds": [10032]}])
        self.assertEqual(parsed["lastRefreshTime"], 5_000)

    def test_homeland_collects_finished_and_dispatches_all_workers_by_priority(self) -> None:
        actions = []
        now = int(time.time() * 1000)

        def reward(player_id, pos, item_id, level, max_workers=1):
            return {
                "reward": f"{item_id}=10", "level": level, "pos": pos,
                "maxWorkerNum": max_workers, "owner": None, "enemy": None,
                "finishTime": 0, "playerId": player_id, "isOnlyOwnerPull": False,
            }

        class FakeSession:
            def __init__(self, _ws, player_id, _token) -> None:
                self.player_id = player_id

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def homeland_state(self):
                return {"freeWorkerNum": 2, "totalWorkerNum": 3, "energy": 100}

            def homeland_manage(self):
                item = reward(42, 4, 100003, 1)
                item.update({
                    "finishTime": now - 1,
                    "owner": {"playerId": 42, "workerNum": 1, "isWinner": True},
                })
                return [item]

            def homeland_enter(self, player_id):
                if player_id == 42:
                    return {"playerId": 42, "rewards": [
                        reward(42, 0, 100003, 5),
                        reward(42, 1, 100004, 3, 2),
                    ]}
                return {"playerId": 99, "rewards": [reward(99, 2, 100004, 3)]}

            def homeland_explore(self, refresh=False):
                self.assert_not_refresh = refresh
                return {"ret": 0, "near": [{"playerId": 99, "rewardIds": [10031]}],
                        "enemy": [], "lastRefreshTime": now}

            def homeland_dispatch(self, player_id, pos, worker_num):
                actions.append((player_id, pos, worker_num))
                return {"ret": 0}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":42,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_homeland_tasks(
                    42, output_dir, 1, lambda _message: None,
                    preferred_item_id=100004, preferred_level=3,
                )

        self.assertEqual(actions, [(42, 4, 0), (42, 1, 2), (99, 2, 1)])
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(result["completed"], 4)


class TalentTaskTests(unittest.TestCase):
    def test_talent_deal_uses_top_level_index_and_type(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []

        def request(message_id, response_id, payload=b""):
            captured.append((message_id, response_id, game.parse_protobuf(payload)))
            return game.protobuf_int(1, 0)

        session._request = request
        session.talent_deal(3, 0)

        fields = captured[0][2]
        self.assertEqual(captured[0][:2], (game.TALENT_DEAL, game.TALENT_DEAL_RESPONSE))
        self.assertEqual(game._values(fields, 1), [3])
        self.assertEqual(game._values(fields, 2), [0])

    def test_talent_random_accepts_client_concurrent_range(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        with self.assertRaises(ValueError):
            session.talent_random(100)
        with self.assertRaises(ValueError):
            session.talent_random(0)
        with self.assertRaises(ValueError):
            session.talent_random(6)

    def test_talent_state_is_requested_when_login_sync_is_missing(self) -> None:
        payload = game.protobuf_int(2, 7) + game.protobuf_int(5, 3)
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []

        def request(message_id, response_id, request_payload=b""):
            captured.append((message_id, response_id, request_payload))
            return payload

        session._request = request
        state = session.talent_state()

        self.assertEqual(captured, [(20621, 621, b"")])
        self.assertEqual(state["createLevel"], 7)
        self.assertEqual(state["readBookTimes"], 3)

    def test_talent_task_enlightens_before_random_and_filters_results(self) -> None:
        actions = []

        def talent(quality, attributes):
            return {
                "type": 1, "talentId": 10000 + quality, "level": 20,
                "quality": quality,
                "attributes": [{"type": attr_type, "value": "10"} for attr_type in attributes],
            }

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def talent_state(self):
                return {"createLevel": 10, "readBookTimes": 0, "pending": []}

            def talent_get_pending(self):
                return {"ret": 0, "pending": [talent(3, [5])]}

            def item_count(self, item_id):
                if item_id == game.TALENT_BOOK_ITEM:
                    return 2
                if item_id == game.TALENT_GRASS_ITEM:
                    return 1
                return 0

            def talent_read_books(self, count):
                actions.append(("enlighten", count))
                return {"ret": 0}

            def talent_random(self, count):
                actions.append(("random", count))
                return {"ret": 0, "pending": [talent(7, [5]), talent(8, [6])]}

            def talent_deal(self, index, action):
                actions.append(("deal", index, action))
                return {"ret": 0}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_talent_tasks(
                    42, output_dir, 1, lambda _message: None,
                    minimum_quality=5, preferred_attribute=5,
                )

        self.assertEqual(actions, [
            ("deal", 0, 1),
            ("enlighten", 2),
            ("random", 1),
            ("deal", 1, 1),
            ("deal", 0, 0),
        ])
        self.assertEqual(result["activated"], 1)
        self.assertEqual(result["resolved"], 2)
        self.assertEqual(result["enlightened"], 2)

    def test_talent_task_processes_all_grass_in_batches_and_resolves_misses(self) -> None:
        random_batches = []
        deal_actions = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def talent_state(self):
                return {"createLevel": 10, "readBookTimes": 0, "pending": []}

            def talent_get_pending(self):
                return {"ret": 0, "pending": []}

            def item_count(self, item_id):
                if item_id == game.TALENT_GRASS_ITEM:
                    return 205
                return 0

            def talent_random(self, count):
                random_batches.append(count)
                return {"ret": 0, "pending": [{
                    "type": 1, "talentId": 10001, "level": 20, "quality": 4,
                    "attributes": [{"type": 6, "value": "10"}],
                }]}

            def talent_deal(self, index, action):
                deal_actions.append((index, action))
                return {"ret": 0}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id, "talentGrassCount": 0}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_talent_tasks(
                    42, output_dir, 205, lambda _message: None,
                    minimum_quality=5, preferred_attribute=5,
                )

        self.assertEqual(random_batches, [1] * 205)
        self.assertEqual(deal_actions, [(0, 1)] * 205)
        self.assertEqual(result["resolved"], 205)

    def test_talent_task_unlimited_mode_uses_inventory_with_selected_concurrency(self) -> None:
        random_batches = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def talent_state(self):
                return {"createLevel": 10, "readBookTimes": 0, "pending": []}

            def talent_get_pending(self):
                return {"ret": 0, "pending": []}

            def item_count(self, item_id):
                return 3 if item_id == game.TALENT_GRASS_ITEM else 0

            def talent_random(self, count):
                random_batches.append(count)
                return {"ret": 0, "pending": []}

            def talent_deal(self, index, action):
                return {"ret": 0}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_talent_tasks(
                    42, output_dir, 0, lambda _message: None, concurrent_count=3,
                )

        self.assertEqual(random_batches, [3])
        self.assertEqual(result["reason"], "finished")

    def test_talent_1201_downgrades_batch_to_single_and_continues(self) -> None:
        random_batches = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs): self.tickets = [7, 6, 6, 5]
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def talent_state(self): return {"createLevel": 10, "readBookTimes": 0, "pending": []}
            def talent_get_pending(self): return {"ret": 0, "pending": []}
            def item_count(self, item_id): return 3 if item_id == game.TALENT_GRASS_ITEM else 0
            def talent_random(self, count):
                random_batches.append(count)
                return {"ret": 1201 if count > 1 else 0, "pending": []}
            def resource_snapshot(self, server_id): return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_talent_tasks(
                    42, output_dir, 0, lambda _message: None, concurrent_count=3,
                )

        self.assertEqual(random_batches, [3, 1, 1, 1])
        self.assertEqual(result["reason"], "finished")


class MagicDrawTaskTests(unittest.TestCase):
    def test_parse_magic_state(self) -> None:
        free_ad = game.protobuf_int(1, 1) + game.protobuf_int(2, 123_456)
        payload = game.protobuf_int(5, 1) + message_field(7, free_ad)

        self.assertEqual(game.parse_magic_state(payload), {
            "freeDrawTimes": 1, "freeAdTimes": 1, "lastAdTime": 123_456,
        })

    def test_magic_draw_never_exceeds_remaining_free_times(self) -> None:
        draws = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def magic_state(self):
                return {"freeDrawTimes": 1, "freeAdTimes": 1, "lastAdTime": 0}

            def assistant_action(self, action_type, params=None):
                draws.append(action_type)
                return {"ret": 0}

            def magic_draw(self, _count=1, is_ad=False):
                draws.append(True)
                return {"ret": 0, "magicIds": [12345]}

            def item_count(self, _item_id):
                return 0

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_magic_draw_tasks(
                    42, output_dir, 2, lambda _message: None,
                )

        self.assertEqual(draws, [game.ASSISTANT_MAGIC_VIDEO, game.ASSISTANT_MAGIC_FREE])
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["remaining"], 0)

    def test_magic_draw_falls_back_when_sync_is_missing(self) -> None:
        calls = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def magic_state(self):
                return None

            def assistant_action(self, action_type, params=None):
                calls.append(action_type)
                return {"ret": 0}

            def magic_draw(self, _count=1, is_ad=False):
                return {"ret": 0, "magicIds": []}

            def item_count(self, _item_id):
                return 0

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_magic_draw_tasks(42, output_dir, 2, lambda _message: None)

        self.assertEqual(calls, [game.ASSISTANT_MAGIC_VIDEO, game.ASSISTANT_MAGIC_FREE])
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["reason"], "finished")


class MagicTreasureTaskTests(unittest.TestCase):
    def test_assistant_action_encodes_setting_and_pool_params(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []

        def request(message_id, response_id, payload=b""):
            captured.append((message_id, response_id, game.parse_protobuf(payload)))
            return game.protobuf_int(1, 0)

        session._request = request
        session.assistant_action(game.ASSISTANT_MAGIC_TREASURE_VIDEO, ["1", "2", "3"])

        fields = captured[0][2]
        setting = game._children(fields, 2)[0]
        self.assertEqual(captured[0][:2], (game.ASSISTANT_ACTION, game.ASSISTANT_ACTION_RESPONSE))
        self.assertEqual(game._values(fields, 1), [0])
        self.assertEqual(game._values(setting, 1), [game.ASSISTANT_MAGIC_TREASURE_VIDEO])
        self.assertEqual([game._text_value(setting, 2)], ["1"])
        self.assertEqual([field["text"] for field in setting if field["field"] == 2], ["1", "2", "3"])

    def test_compass_items_match_the_three_pools(self) -> None:
        self.assertEqual(game.MAGIC_TREASURE_COMPASS_ITEMS, {
            1: 100197, 2: 100091, 3: 100064,
        })

    def test_state_is_requested_when_login_sync_is_missing(self) -> None:
        jackpot = game.protobuf_int(1, 3) + game.protobuf_int(3, 1)
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []

        def request(message_id, response_id, payload=b""):
            captured.append((message_id, response_id, payload))
            return message_field(2, jackpot)

        session._request = request
        state = session.magic_treasure_state()

        self.assertEqual(captured, [(26301, 6301, b"")])
        self.assertEqual(state[3]["itemId"], 100064)
        self.assertEqual(state[3]["freeDrawTimes"], 1)

    def test_parse_pool_state_config_and_snapshot(self) -> None:
        jackpot = (
            game.protobuf_int(1, 1) + game.protobuf_int(2, 9)
            + game.protobuf_int(3, 1) + game.protobuf_int(4, 0)
        )
        pool_config = (
            game.protobuf_int(1, 1)
            + game.protobuf_string(4, "灵瀚仙界")
            + game.protobuf_string(6, "100061=1")
        )
        payload = message_field(2, jackpot) + message_field(3, pool_config)
        state = game.parse_magic_treasure_state(payload)

        self.assertEqual(state[1]["freeDrawTimes"], 1)
        self.assertEqual(state[1]["itemId"], 100061)
        inventory = message_field(
            1, game.protobuf_int(1, 100061) + game.protobuf_string(2, "4")
        )
        snapshot = game._snapshot_from_frames(
            42, [(301, inventory), (game.MAGIC_TREASURE_SYNC, payload)],
        )
        self.assertEqual(snapshot["magicTreasurePools"]["1"]["freeRemaining"], 1)
        self.assertEqual(snapshot["magicTreasurePools"]["1"]["compassCount"], 4)

    def test_draw_request_uses_pool_and_item(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []

        def request(message_id, response_id, payload=b""):
            captured.append((message_id, response_id, game.parse_protobuf(payload)))
            return game.protobuf_int(1, 0)

        session._request = request
        result = session.magic_treasure_draw(2, 3, item_id=100062)

        self.assertEqual(result["ret"], 0)
        self.assertEqual(captured[0][:2], (26302, 6302))
        self.assertEqual(game._values(captured[0][2], 1), [3])
        self.assertEqual(game._values(captured[0][2], 3), [2])
        self.assertEqual(game._values(captured[0][2], 5), [100062])

    def test_free_then_paid_draws_are_bounded_and_wait_eight_seconds(self) -> None:
        requests = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def magic_treasure_state(self):
                return {
                    1: {"freeDrawTimes": 0, "itemId": 100061},
                    2: {"freeDrawTimes": 2, "itemId": 100062},
                    3: {"freeDrawTimes": 2, "itemId": 100064},
                }

            def assistant_action(self, action_type, params=None):
                requests.append((action_type, tuple(params or [])))
                return {"ret": 0}

            def magic_treasure_draw(self, pool_id, count=1, item_id=0, is_ad=False):
                requests.append((pool_id, count, item_id, is_ad))
                return {"ret": 0}

            def item_count(self, item_id):
                return 3 if item_id == 100061 else 0

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep") as sleep:
                result = game.run_magic_treasure_tasks(
                    42, output_dir, 1, lambda _message: None,
                    free_counts={1: 2, 2: 2, 3: 2}, paid_counts={1: 5},
                )

        self.assertEqual(requests, [
            (1, 1, 0, True), (1, 1, 0, True),
            (2, 1, 0, True), (2, 1, 0, True),
            (3, 1, 0, True), (3, 1, 0, True),
            (1, 3, 100061, False),
        ])
        self.assertEqual(sleep.call_count, 6)
        self.assertEqual(result["freeCompleted"], 6)
        self.assertEqual(result["paidCompleted"], 3)
        self.assertEqual(result["remaining"], 0)


class SpiritDrawTaskTests(unittest.TestCase):
    def test_state_is_requested_when_login_sync_is_missing(self) -> None:
        state = game.protobuf_int(4, 7) + message_field(8, game.protobuf_int(1, 1))
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []
        session._request = lambda message_id, response_id, payload=b"": (
            captured.append((message_id, response_id, payload)) or state
        )

        self.assertEqual(session.spirit_state()["freeAdTimes"], 1)
        self.assertEqual(captured, [(game.SPIRIT_STATE_REQUEST, game.SPIRIT_SYNC, b"")])

    def test_free_draw_interval_is_eight_seconds(self) -> None:
        self.assertEqual(game.FREE_DRAW_INTERVAL_SECONDS, 8.0)

    def test_parse_spirit_state_and_snapshot_remaining(self) -> None:
        free_ad = game.protobuf_int(1, 1) + game.protobuf_int(2, 123_456)
        payload = game.protobuf_int(4, 7) + message_field(8, free_ad)

        self.assertEqual(game.parse_spirit_state(payload), {
            "drawTimes": 7, "freeAdTimes": 1, "lastAdTime": 123_456,
        })
        snapshot = game._snapshot_from_frames(42, [(game.SPIRIT_SYNC, payload)])
        self.assertEqual(snapshot["spiritSummonRemaining"], 1)

    def test_spirit_draw_uses_selected_count_bounded_by_available(self) -> None:
        draws = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def spirit_state(self):
                return {"drawTimes": 10, "freeAdTimes": 1, "lastAdTime": 0}

            def spirit_free_draw(self):
                draws.append(True)
                return {"ret": 0, "spiritIds": [121001]}

            def item_count(self, _item_id):
                return 0

            def resource_snapshot(self, server_id):
                return {"serverId": server_id, "spiritSummonRemaining": 0}

        snapshots = []
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_spirit_draw_tasks(
                    42, output_dir, 2, lambda _message: None,
                    snapshot=snapshots.append,
                )

        self.assertEqual(draws, [True])
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(snapshots[0]["spiritSummonRemaining"], 0)

    def test_spirit_draw_executes_each_selected_ad_draw(self) -> None:
        draws = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def spirit_state(self):
                return {"drawTimes": 0, "freeAdTimes": 0, "lastAdTime": 0}

            def spirit_free_draw(self):
                draws.append(True)
                return {"ret": 0, "spiritIds": [121001]}

            def item_count(self, _item_id):
                return 0

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with (
                patch.object(game, "GameSession", FakeSession),
                patch.object(game.time, "sleep") as sleep,
            ):
                result = game.run_spirit_draw_tasks(
                    42, output_dir, 2, lambda _message: None,
                )

        self.assertEqual(draws, [True, True])
        sleep.assert_called_once_with(game.FREE_DRAW_INTERVAL_SECONDS)
        self.assertEqual(result["freeCompleted"], 2)


class LawLooksDrawTaskTests(unittest.TestCase):
    def test_state_enters_feature_when_login_sync_is_missing(self) -> None:
        enter = game.protobuf_int(1, 0) + message_field(
            2, game.protobuf_int(2, 1) + game.protobuf_int(3, 0)
        )
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []
        session._request = lambda message_id, response_id, payload=b"": (
            captured.append((message_id, response_id, payload)) or enter
        )

        self.assertEqual(session.law_looks_state(), {"freeAdTimes": 1, "freeDrawTimes": 0})
        self.assertEqual(captured, [(game.LAW_LOOKS_ENTER, game.LAW_LOOKS_ENTER_RESPONSE, b"")])

    def test_parse_state_and_snapshot_counts(self) -> None:
        payload = game.protobuf_int(2, 1) + game.protobuf_int(3, 0)
        inventory = message_field(
            1, game.protobuf_int(1, game.LAW_LOOKS_TICKET_ITEM) + message_field(2, b"4")
        )

        self.assertEqual(game.parse_law_looks_state(payload), {
            "freeAdTimes": 1, "freeDrawTimes": 0,
        })
        snapshot = game._snapshot_from_frames(42, [
            (301, inventory), (game.LAW_LOOKS_LOGIN_SYNC, payload),
        ])
        self.assertEqual(snapshot["lawLooksFreeRemaining"], 2)
        self.assertEqual(snapshot["lawLooksTicketCount"], 4)

    def test_draw_is_bounded_by_free_quota_and_lamp_inventory(self) -> None:
        requests = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def law_looks_state(self):
                return {"freeAdTimes": 1, "freeDrawTimes": 0}

            def assistant_action(self, action_type, params=None):
                requests.append(("assistant", action_type))
                return {"ret": 0}

            def law_looks_draw(self, count, draw_type=2):
                requests.append((count, draw_type))
                return {"ret": 0}

            def item_count(self, item_id):
                return 3 if item_id == game.LAW_LOOKS_TICKET_ITEM else 0

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_law_looks_draw_tasks(
                    42, output_dir, 1, lambda _message: None, paid_count=5,
                )

        self.assertEqual(requests, [("assistant", game.ASSISTANT_LAW_LOOKS_REWARD), (3, 2)])
        self.assertEqual(result["freeCompleted"], 1)
        self.assertEqual(result["paidCompleted"], 3)
        self.assertEqual(result["remaining"], 0)


class PetKernelDrawTaskTests(unittest.TestCase):
    def test_missing_push_state_does_not_issue_blocking_request(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        session._request = Mock(side_effect=AssertionError("unexpected state request"))

        self.assertIsNone(session.pet_kernel_state())

    def test_parse_state_and_snapshot_counts(self) -> None:
        payload = (
            game.protobuf_int(3, 1)
            + game.protobuf_int(4, 7)
            + game.protobuf_int(5, 2)
        )
        inventory = message_field(
            1, game.protobuf_int(1, game.PET_KERNEL_DRAW_ITEM) + message_field(2, b"13")
        )

        self.assertEqual(game.parse_pet_kernel_state(payload), {
            "freeDrawTimes": 1, "drawCount": 7, "ensureCount": 2,
        })
        snapshot = game._snapshot_from_frames(42, [
            (301, inventory), (game.PET_KERNEL_STATE_RESPONSE, payload),
        ])
        self.assertEqual(snapshot["petKernelFreeRemaining"], 0)
        self.assertEqual(snapshot["petKernelDrawItemCount"], 13)

    def test_draw_uses_free_quota_and_batches_paid_count(self) -> None:
        requests = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def pet_kernel_state(self):
                return {"freeDrawTimes": 0, "drawCount": 0, "ensureCount": 0}

            def pet_kernel_draw(self, ten=False):
                requests.append(ten)
                return {"ret": 0, "count": 10 if ten else 1}

            def item_count(self, item_id):
                return 13 if item_id == game.PET_KERNEL_DRAW_ITEM else 0

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_pet_kernel_draw_tasks(
                    42, output_dir, 1, lambda _message: None, paid_count=20,
                )

        self.assertEqual(requests, [False, True, False, False, False])
        self.assertEqual(result["freeCompleted"], 1)
        self.assertEqual(result["paidCompleted"], 13)
        self.assertEqual(result["remaining"], 0)


class UniverseTaskTests(unittest.TestCase):
    def test_parse_state_and_snapshot_counts(self) -> None:
        state = (
            game.protobuf_int(1, 3)
            + game.protobuf_int(2, 9)
            + game.protobuf_int(7, 1)
            + game.protobuf_int(10, 6)
        )
        payload = message_field(1, state)
        inventory = message_field(
            1, game.protobuf_int(1, game.UNIVERSE_SKILL_DRAW_ITEM) + message_field(2, b"12")
        )

        self.assertEqual(game.parse_universe_state(payload), {
            "level": 3, "stoneNum": 9, "freeDrawTimes": 1, "drawTimes": 6,
        })
        snapshot = game._snapshot_from_frames(42, [
            (301, inventory), (game.UNIVERSE_STATE_RESPONSE, payload),
        ])
        self.assertEqual(snapshot["universeSkillFreeRemaining"], 1)
        self.assertEqual(snapshot["universeSkillDrawItemCount"], 12)
        self.assertEqual(snapshot["universeStoneCount"], 9)

    def test_skill_draw_uses_free_quota_and_paid_inventory(self) -> None:
        requests = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def universe_state(self):
                return {"freeDrawTimes": 1, "stoneNum": 0}

            def universe_skill_draw(self, count=1):
                requests.append(count)
                return {"ret": 0}

            def item_count(self, item_id):
                return 12 if item_id == game.UNIVERSE_SKILL_DRAW_ITEM else 0

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_universe_skill_draw_tasks(
                    42, output_dir, 2, lambda _message: None, paid_count=20,
                )

        self.assertEqual(requests, [1, 10, 2])
        self.assertEqual(result["freeCompleted"], 1)
        self.assertEqual(result["paidCompleted"], 12)

    def test_wheel_draw_is_limited_by_stones(self) -> None:
        requests = []
        snapshots = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def universe_state(self):
                return {"freeDrawTimes": 0, "stoneNum": 3}

            def universe_wheel_draw(self, multiplier=1):
                requests.append(multiplier)
                return {"ret": 0}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id, "universeStoneCount": 3}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_universe_wheel_draw_tasks(
                    42, output_dir, 5, lambda _message: None, snapshot=snapshots.append,
                )

        self.assertEqual(requests, [1, 1, 1])
        self.assertEqual(result["completed"], 3)
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(snapshots[0]["universeStoneCount"], 0)


class RuleTrialTaskTests(unittest.TestCase):
    def test_parse_state_and_quick_reward_request(self) -> None:
        payload = (
            game.protobuf_int(2, 12) + game.protobuf_int(3, 50105)
            + game.protobuf_int(4, 0)
        )
        self.assertEqual(game.parse_rule_trial_state(payload), {
            "totalChallengeTimes": 12, "bestBossId": 50105, "isRepeated": False,
        })
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []

        def request(message_id, response_id, body=b""):
            captured.append((message_id, response_id, body))
            return game.protobuf_int(1, 0) + game.protobuf_string(2, "100003=20")

        session._request = request  # type: ignore[method-assign]
        result = session.rule_trial_quick_repeat()
        self.assertEqual(captured, [(
            game.RULE_TRIAL_ONE_KEY_REPEAT, game.RULE_TRIAL_ONE_KEY_REPEAT_RESPONSE, b"",
        )])
        self.assertEqual(result["rewards"], "100003=20")

    def test_runner_only_uses_quick_repeat_and_skips_when_already_claimed(self) -> None:
        calls = []

        class FakeSession:
            repeated = False
            def __init__(self, *_args, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def rule_trial_state(self):
                return {"bestBossId": 50105, "isRepeated": self.repeated}
            def rule_trial_quick_repeat(self):
                calls.append("quick"); return {"ret": 0, "rewards": "100003=20"}
            def resource_snapshot(self, server_id): return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_rule_trial_tasks(42, output_dir, 1, lambda _message: None)
                FakeSession.repeated = True
                skipped = game.run_rule_trial_tasks(42, output_dir, 1, lambda _message: None)

        self.assertEqual(calls, ["quick"])
        self.assertEqual(result["completed"], 1)
        self.assertEqual(skipped["completed"], 0)


class CaveTrialTaskTests(unittest.TestCase):
    def test_parse_battle_keeps_first_wave_running_after_win(self) -> None:
        payload = (
            game.protobuf_int(1, 0) + game.protobuf_int(2, 1)
            + game.protobuf_int(5, 1) + game.protobuf_int(6, 0)
        )
        result = game.parse_cave_trial_battle(payload)
        self.assertTrue(result["isWin"])
        self.assertFalse(result["isEnd"])

    def test_parse_login_sync_and_snapshot_ticket_count(self) -> None:
        payload = bytes.fromhex("0802103528003002380040004800")
        self.assertEqual(game.parse_cave_trial_state(payload), {
            "curLevel": 53, "ticketCount": 2, "selectPos": 0,
            "freeTicket": 2, "dayRewardCount": 0, "weekTake": 0,
            "inscriptionStar": 0,
        })
        inventory = message_field(
            1, game.protobuf_int(1, game.CAVE_TRIAL_TICKET_ITEM) + game.protobuf_string(2, "7"),
        )
        snapshot = game._snapshot_from_frames(42, [
            (301, inventory), (game.CAVE_TRIAL_PLAYER_DATA_SYNC, payload),
        ])
        self.assertEqual(snapshot["caveTrialTicketCount"], 7)
        self.assertEqual(snapshot["caveTrialCurrentLevel"], 53)

    def test_battle_request_encodes_level_rate_and_wave(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []

        def request(message_id, response_id, payload=b"", timeout=None):
            captured.append((message_id, response_id, payload))
            return game.protobuf_int(1, 0) + game.protobuf_int(2, 1) + game.protobuf_int(5, 1) + game.protobuf_int(6, 1)

        session._request = request  # type: ignore[method-assign]
        session.cave_trial_battle(12, 1)
        session.cave_trial_battle(12, 2)
        self.assertEqual(captured[0][2], (
            game.protobuf_int(1, 12) + game.protobuf_int(2, 1) + game.protobuf_int(3, 1)
        ))
        self.assertEqual(captured[1][2], game.protobuf_int(1, 12) + game.protobuf_int(2, 2))

    def test_zero_challenges_still_claims_daily_ticket_and_reward(self) -> None:
        calls = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def cave_trial_state(self):
                return {"curLevel": 8, "freeTicket": 2, "dayRewardCount": 0}
            def cave_trial_get_ticket(self): calls.append("ticket"); return {"ret": 0}
            def cave_trial_day_reward(self): calls.append("daily"); return {"ret": 0}
            def item_count(self, _item_id): return 7

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_cave_trial_tasks(42, output_dir, 0, lambda _message: None)

        self.assertEqual(calls, ["ticket", "daily"])
        self.assertEqual(result["completed"], 0)

    def test_failed_attempt_does_not_consume_ticket_and_continues_when_enabled(self) -> None:
        battles = []
        settlements = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs): self.tickets = [7, 6, 6, 5]
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def cave_trial_state(self):
                return {"curLevel": 3, "freeTicket": 0, "dayRewardCount": 1}
            def cave_trial_battle(self, level, wave):
                battles.append((level, wave)); return {"ret": 0, "wave": wave, "isEnd": True, "isWin": False}
            def cave_trial_battle_reward(self, won):
                settlements.append(won)
                return {"ret": 0}
            def cave_trial_day_reward(self): return {"ret": 0}
            def item_count(self, _item_id): return self.tickets[0]

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_cave_trial_tasks(42, output_dir, 2, lambda _message: None)

        self.assertEqual(battles, [(3, 1), (3, 1)])
        self.assertEqual(settlements, [False, False])
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["reason"], "finished")

    def test_success_repeats_latest_cleared_level_and_counts_consumed_ticket(self) -> None:
        battles = []
        tickets = [7]

        class FakeSession:
            def __init__(self, *_args, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def cave_trial_state(self):
                return {"curLevel": 8, "freeTicket": 0, "dayRewardCount": 1}
            def item_count(self, _item_id): return tickets.pop(0)
            def cave_trial_battle(self, level, wave):
                battles.append((level, wave)); return {"ret": 0, "wave": wave, "isEnd": True, "isWin": True}
            def cave_trial_battle_reward(self, won): return {"ret": 0}
            def cave_trial_day_reward(self): return {"ret": 0}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_cave_trial_tasks(42, output_dir, 1, lambda _message: None)

        self.assertEqual(battles, [(8, 1)])
        self.assertEqual(result["completed"], 1)

    def test_logs_level_and_each_of_six_waves(self) -> None:
        logs = []
        waves = [
            {"ret": 0, "wave": wave, "isEnd": wave == 6, "isWin": True}
            for wave in range(1, 7)
        ]

        class FakeSession:
            def __init__(self, *_args, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def cave_trial_state(self): return {"curLevel": 12, "freeTicket": 0, "dayRewardCount": 1}
            def cave_trial_day_reward(self): return {"ret": 32807}
            def item_count(self, _item_id): return 10
            def cave_trial_battle(self, level, wave): return waves.pop(0)
            def cave_trial_battle_reward(self, won): return {"ret": 0}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                game.run_cave_trial_tasks(42, output_dir, 1, logs.append)

        for wave in range(1, 7):
            self.assertTrue(any(f"关卡 12，第 {wave}/6 波" in message for message in logs))


class SkyWarTaskTests(unittest.TestCase):
    def test_opponent_parser_uses_player_base_server_id_field_eight(self) -> None:
        def opponent(player_id, server_id):
            base = game.protobuf_int(1, player_id) + game.protobuf_int(2, 99) + game.protobuf_int(8, server_id)
            return message_field(1, message_field(1, base))

        payload = message_field(3, opponent(4000020000001, 4000020))
        payload += message_field(3, opponent(4000030000002, 4000030))
        payload += message_field(3, opponent(4000040000003, 4000040))
        self.assertEqual(game._sky_war_opponents(game.parse_protobuf(payload)), [
            {"playerId": 4000020000001, "serverId": 4000020, "position": 0},
            {"playerId": 4000030000002, "serverId": 4000030, "position": 1},
            {"playerId": 4000040000003, "serverId": 4000040, "position": 2},
        ])

    def test_opponent_parser_ignores_nested_non_enemy_players(self) -> None:
        def opponent(player_id, server_id):
            return message_field(
                1, message_field(1, game.protobuf_int(1, player_id) + game.protobuf_int(8, server_id)),
            )

        payload = message_field(2, opponent(4000099000001, 4000099))
        payload += b"".join(
            message_field(3, opponent(4000020000000 + index, 4000020))
            for index in range(1, 4)
        )
        self.assertEqual(
            [item["playerId"] for item in game._sky_war_opponents(game.parse_protobuf(payload))],
            [4000020000001, 4000020000002, 4000020000003],
        )

    def test_opponent_parser_prefers_enemy_group_without_rank_scores(self) -> None:
        def opponent(player_id, server_id, score=None):
            value = message_field(
                1, message_field(1, game.protobuf_int(1, player_id) + game.protobuf_int(8, server_id)),
            )
            return value if score is None else value + game.protobuf_int(2, score)

        payload = b"".join(
            message_field(2, opponent(4000099000000 + index, 4000099, 1000 - index))
            for index in range(1, 4)
        )
        payload += b"".join(
            message_field(3, opponent(4000020000000 + index, 4000020))
            for index in range(1, 4)
        )
        self.assertEqual(
            [item["playerId"] for item in game._sky_war_opponents(game.parse_protobuf(payload))],
            [4000020000001, 4000020000002, 4000020000003],
        )

    def test_nonzero_fight_result_is_not_counted(self) -> None:
        class FakeSession:
            def __init__(self, *_args, **_kwargs): self.player_id = 1
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def task_data(self): return {}
            def sky_war_remaining_times(self): return 5
            def sky_war_enter(self): return {"ret": 0, "battleTimes": 5, "opponents": [{"playerId": 2, "serverId": 2, "position": 0}]}
            def sky_war_fight(self, _opponent): return {"ret": 2108, "battleTimes": 0}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text('{"wsAddress":"wss://x","playerId":1,"token":"t"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_sky_war_tasks(42, output_dir, 5, lambda _message: None)
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["remaining"], 5)
        self.assertEqual(result["reason"], "sky_war_fight_failed")

    def test_request_payloads_use_free_fight_protocol(self) -> None:
        session = game.GameSession("wss://example.invalid", 123, "token")
        captured = []

        def request(message_id, response_id, payload=b""):
            captured.append((message_id, response_id, payload))
            return game.protobuf_int(1, 0) + game.protobuf_int(2, 4)

        session._request = request  # type: ignore[method-assign]
        session.sky_war_enter()
        session.observed_frames.append((game.SKY_WAR_LOGIN_SYNC, game.protobuf_int(1, 1)))
        self.assertEqual(session.sky_war_remaining_times(), 1)
        session.sky_war_fight({"playerId": 456, "serverId": 789, "position": 2})
        session.claim_task_reward(13501)

        self.assertEqual(captured[0], (
            game.SKY_WAR_ENTER, game.SKY_WAR_ENTER_RESPONSE,
            game.protobuf_int(1, 123),
        ))
        self.assertEqual(captured[1], (
            game.SKY_WAR_FIGHT, game.SKY_WAR_FIGHT_RESPONSE,
            game.protobuf_int(1, 123) + game.protobuf_int(2, 456)
            + game.protobuf_int(3, 789) + game.protobuf_int(4, 2),
        ))
        self.assertEqual(captured[2][0:2], (game.TASK_GET_REWARD, game.TASK_GET_REWARD_RESPONSE))
        self.assertEqual(captured[2][2], game.protobuf_int(1, 13501))

    def test_runner_counts_all_five_attempts_and_claims_changed_task(self) -> None:
        fights = []
        claims = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs):
                self.player_id = 1
                self.after = False
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def task_data(self):
                return {13501: {"value": "5" if self.after else "0", "state": 0}}
            def sky_war_remaining_times(self): return 5 - len(fights)
            def sky_war_enter(self):
                return {"ret": 0, "battleTimes": 5 - len(fights), "opponents": [
                    {"playerId": 2, "serverId": 20, "position": 0},
                    {"playerId": 3, "serverId": 30, "position": 1},
                ]}
            def sky_war_fight(self, opponent):
                fights.append(opponent["playerId"])
                if len(fights) == 5:
                    self.after = True
                return {"ret": 0, "battleTimes": 5 - len(fights)}
            def claim_task_reward(self, task_id):
                claims.append(task_id)
                return {"ret": 0}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_sky_war_tasks(42, output_dir, 5, lambda _message: None)

        self.assertEqual(fights, [2, 3, 2, 3, 2])
        self.assertEqual(result["completed"], 5)
        self.assertEqual(result["claimed"], 1)
        self.assertEqual(claims, [13501])

    def test_runner_stops_at_server_reported_remaining_attempts(self) -> None:
        fights = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs): self.player_id = 1
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def task_data(self): return {}
            def sky_war_remaining_times(self): return 2
            def sky_war_enter(self): return {"ret": 0, "battleTimes": 2, "opponents": [
                {"playerId": 2, "serverId": 20, "position": 0}]}
            def sky_war_fight(self, opponent):
                fights.append(opponent)
                return {"ret": 0, "battleTimes": 2 - len(fights)}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_sky_war_tasks(42, output_dir, 5, lambda _message: None)

        self.assertEqual(len(fights), 2)
        self.assertEqual(result["completed"], 2)

    def test_runner_stops_when_success_response_does_not_consume_attempt(self) -> None:
        fights = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs): self.player_id = 1
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def task_data(self): return {}
            def sky_war_remaining_times(self): return 5
            def sky_war_enter(self): return {"ret": 0, "battleTimes": 5, "opponents": [
                {"playerId": 2, "serverId": 20, "position": 0}]}
            def sky_war_fight(self, opponent):
                fights.append(opponent)
                return {"ret": 0, "battleTimes": 5}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_sky_war_tasks(42, output_dir, 5, lambda _message: None)

        self.assertEqual(len(fights), 1)
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["reason"], "sky_war_not_consumed")

    def test_runner_uses_login_sync_remaining_times_instead_of_enter_field_two(self) -> None:
        fights = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs): self.player_id = 1
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def task_data(self): return {}
            def sky_war_remaining_times(self): return 1
            def sky_war_enter(self): return {"ret": 0, "battleTimes": 5, "opponents": [
                {"playerId": 2, "serverId": 20, "position": 0}]}
            def sky_war_fight(self, opponent):
                fights.append(opponent)
                return {"ret": 0, "battleTimes": 0}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_sky_war_tasks(42, output_dir, 5, lambda _message: None)

        self.assertEqual(len(fights), 1)
        self.assertEqual(result["completed"], 1)


class TowerTaskTests(unittest.TestCase):
    def test_nonzero_challenge_results_continue_when_enabled(self) -> None:
        class FakeSession:
            def __init__(self, *_args, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def tower_state(self): return {"curPassId": 10, "passMaxId": 10, "leftPendingTimes": 0}
            def tower_save_preferences(self): return {"ret": 0}
            def tower_quick_challenge(self): return {"ret": game.TOWER_QUICK_NOT_AVAILABLE, "state": None}
            def tower_challenge(self): return {"ret": 902, "won": False, "state": None}
            def resource_snapshot(self, server_id): return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text('{"wsAddress":"wss://x","playerId":1,"token":"t"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_tower_tasks(42, output_dir, 3, lambda _message: None)
        self.assertEqual(result["completed"], 3)

    def test_loss_continues_by_default_and_counts_attempts(self) -> None:
        outcomes = iter([False, True])

        class FakeSession:
            def __init__(self, *_args, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def tower_state(self): return {"curPassId": 10, "passMaxId": 10, "leftPendingTimes": 0}
            def tower_save_preferences(self): return {"ret": 0}
            def tower_quick_challenge(self): return {"ret": game.TOWER_QUICK_NOT_AVAILABLE, "state": None}
            def tower_challenge(self): return {"ret": 0, "won": next(outcomes), "state": None}
            def resource_snapshot(self, server_id): return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_tower_tasks(42, output_dir, 2, lambda _message: None)

        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["reason"], "finished")

    def test_loss_stops_when_continue_is_disabled(self) -> None:
        class FakeSession:
            def __init__(self, *_args, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def tower_state(self): return {"curPassId": 10, "passMaxId": 10, "leftPendingTimes": 0}
            def tower_save_preferences(self): return {"ret": 0}
            def tower_quick_challenge(self): return {"ret": game.TOWER_QUICK_NOT_AVAILABLE, "state": None}
            def tower_challenge(self): return {"ret": 0, "won": False, "state": None}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_tower_tasks(
                    42, output_dir, 2, lambda _message: None, continue_on_loss=False)

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["reason"], "tower_challenge_lost")

    def test_save_preferences_encodes_nested_messages(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []

        def request(message_id, response_id, payload=b""):
            captured.append((message_id, response_id, payload))
            return game.protobuf_int(1, 0)

        session._request = request  # type: ignore[method-assign]
        result = session.tower_save_preferences((1017, 1018))

        expected = (
            game.protobuf_message(1, game.protobuf_int(1, 1) + game.protobuf_int(2, 1017))
            + game.protobuf_message(1, game.protobuf_int(1, 2) + game.protobuf_int(2, 1018))
        )
        self.assertEqual(result["ret"], 0)
        self.assertEqual(captured, [(game.TOWER_SAVE_PREFERENCE, game.TOWER_SAVE_PREFERENCE_RESPONSE, expected)])

    def test_parse_tower_state_and_snapshot(self) -> None:
        pending = game.protobuf_int(1, 101017) + game.protobuf_int(1, 101018)
        payload = (
            game.protobuf_int(1, 23)
            + game.protobuf_int(3, 58)
            + message_field(4, pending)
            + game.protobuf_int(5, 2)
        )

        self.assertEqual(game.parse_tower_state(payload), {
            "curPassId": 23,
            "passMaxId": 58,
            "pendingBuffIds": [101017, 101018],
            "leftPendingTimes": 2,
        })
        snapshot = game._snapshot_from_frames(42, [(game.TOWER_SYNC, payload)])
        self.assertEqual(snapshot["towerCurrentPass"], 23)
        self.assertEqual(snapshot["towerMaxPass"], 58)

    def test_parse_embedded_tower_response_state(self) -> None:
        state = game.protobuf_int(1, 24) + game.protobuf_int(3, 58) + game.protobuf_int(5, 0)
        response = game.protobuf_int(1, 0) + message_field(5, state)

        self.assertEqual(game.parse_tower_response_state(response, 5), {
            "curPassId": 24,
            "passMaxId": 58,
            "pendingBuffIds": [],
            "leftPendingTimes": 0,
        })

    def test_quick_selects_all_buffs_then_continues_challenge(self) -> None:
        calls = []
        selected_states = [
            {"curPassId": 50, "passMaxId": 80, "pendingBuffIds": [2], "leftPendingTimes": 1},
            {"curPassId": 50, "passMaxId": 80, "pendingBuffIds": [], "leftPendingTimes": 0},
            {"curPassId": 61, "passMaxId": 80, "pendingBuffIds": [], "leftPendingTimes": 0},
        ]
        challenge_states = [
            {"curPassId": 60, "passMaxId": 80, "pendingBuffIds": [3], "leftPendingTimes": 1},
            {"curPassId": 62, "passMaxId": 80, "pendingBuffIds": [], "leftPendingTimes": 0},
        ]

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def tower_state(self):
                return {"curPassId": 0, "passMaxId": 80, "pendingBuffIds": [], "leftPendingTimes": 0}

            def tower_save_preferences(self):
                calls.append("save")
                return {"ret": 0}

            def tower_quick_challenge(self):
                calls.append("quick")
                return {
                    "ret": 0,
                    "state": {"curPassId": 50, "passMaxId": 80, "pendingBuffIds": [1], "leftPendingTimes": 2},
                }

            def tower_select_buff(self, one_key=True):
                calls.append(("select", one_key))
                return {"ret": 0, "state": selected_states.pop(0)}

            def tower_challenge(self):
                calls.append("challenge")
                return {"ret": 0, "won": True, "state": challenge_states.pop(0)}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_tower_tasks(
                    42, output_dir, 2, lambda _message: None, use_preferences=True,
                )

        self.assertEqual(calls, [
            "save", "quick", "save", ("select", True), "save", ("select", True),
            "challenge", "save", ("select", True), "challenge",
        ])
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["reason"], "finished")

    def test_quick_not_available_continues_normal_challenge(self) -> None:
        calls = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def tower_state(self): return {"curPassId": 10, "passMaxId": 10, "pendingBuffIds": [], "leftPendingTimes": 0}
            def tower_save_preferences(self): return {"ret": 0}
            def tower_quick_challenge(self): return {"ret": game.TOWER_QUICK_NOT_AVAILABLE, "state": None}
            def tower_challenge(self):
                calls.append("challenge")
                return {"ret": 0, "won": True, "state": None}
            def resource_snapshot(self, server_id): return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_tower_tasks(42, output_dir, 1, lambda _message: None)

        self.assertEqual(calls, ["challenge"])
        self.assertEqual(result["reason"], "finished")


class AdventureTaskTests(unittest.TestCase):
    def test_nonzero_challenge_results_continue_when_enabled(self) -> None:
        class FakeSession:
            def __init__(self, *_args, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def stage_state(self): return {"passStageId": 10}
            def stage_challenge(self): return {"ret": 30, "won": False}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text('{"wsAddress":"wss://x","playerId":1,"token":"t"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_adventure_tasks(42, output_dir, 3, lambda _message: None)
        self.assertEqual(result["completed"], 3)

    def test_loss_continues_by_default_and_counts_attempts(self) -> None:
        outcomes = iter([False, True])

        class FakeSession:
            def __init__(self, *_args, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def stage_state(self): return {"passStageId": 10}
            def stage_challenge(self): return {"ret": 0, "won": next(outcomes)}
            def resource_snapshot(self, server_id): return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_adventure_tasks(42, output_dir, 2, lambda _message: None)

        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["reason"], "finished")

    def test_loss_stops_when_continue_is_disabled(self) -> None:
        class FakeSession:
            def __init__(self, *_args, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def stage_state(self): return {"passStageId": 10}
            def stage_challenge(self): return {"ret": 0, "won": False}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_adventure_tasks(
                    42, output_dir, 2, lambda _message: None, continue_on_loss=False)

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["reason"], "adventure_challenge_lost")

    def test_challenge_success_is_response_field_three(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        session._request = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
            game.protobuf_int(1, 0) + game.protobuf_int(3, 1)
        )

        result = session.stage_challenge()

        self.assertEqual(result["ret"], 0)
        self.assertTrue(result["won"])

    def test_parse_stage_state_and_snapshot(self) -> None:
        payload = game.protobuf_int(1, 17)

        self.assertEqual(game.parse_stage_state(payload), {"passStageId": 17})
        snapshot = game._snapshot_from_frames(42, [(game.STAGE_SYNC, payload)])
        self.assertEqual(snapshot["adventureCurrentStage"], 18)

    def test_fixed_count_challenges_exact_number(self) -> None:
        calls = 0

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                self.passed = 10

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def stage_state(self):
                return {"passStageId": self.passed}

            def stage_challenge(self):
                nonlocal calls
                calls += 1
                self.passed += 1
                return {"ret": 0, "won": True}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_adventure_tasks(42, output_dir, 3, lambda _message: None)

        self.assertEqual(calls, 3)
        self.assertEqual(result["completed"], 3)
        self.assertEqual(result["reason"], "finished")

    def test_unlimited_stops_on_stop_event(self) -> None:
        stop_event = game.threading.Event()
        calls = 0

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def stage_state(self):
                return {"passStageId": calls}

            def stage_challenge(self):
                nonlocal calls
                calls += 1
                if calls == 2:
                    stop_event.set()
                return {"ret": 0, "won": True}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep"):
                result = game.run_adventure_tasks(
                    42, output_dir, 0, lambda _message: None, stop_event=stop_event,
                )

        self.assertEqual(calls, 2)
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["reason"], "stopped")


class DivineMindCollectionTests(unittest.TestCase):
    def test_collects_periodically_and_accumulates_received_mind(self) -> None:
        calls = 0
        snapshots = []

        class StopAfterTwo:
            def __init__(self) -> None:
                self.waits = 0

            def is_set(self) -> bool:
                return False

            def wait(self, seconds) -> bool:
                self.waits += 1
                self.last_seconds = seconds
                return self.waits >= 2

        stop_event = StopAfterTwo()

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def divine_insight_receive_mind(self):
                nonlocal calls
                calls += 1
                return {"ret": 0, "receiveNum": 10, "inspireAddNum": 2}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_divine_mind_collection_tasks(
                    42, output_dir, 1, lambda _message: None,
                    stop_event=stop_event, snapshot=snapshots.append,
                    interval_minutes=5,
                )

        self.assertEqual(calls, 2)
        self.assertEqual(stop_event.last_seconds, 300)
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["totalReceived"], 24)
        self.assertEqual(result["reason"], "stopped")
        self.assertEqual(snapshots[-1]["divineMindLastCollected"], 12)
        self.assertEqual(snapshots[-1]["divineMindTotalCollected"], 24)

    def test_without_stop_event_collects_once(self) -> None:
        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def divine_insight_receive_mind(self):
                return {"ret": 0, "receiveNum": 7, "inspireAddNum": 0}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_divine_mind_collection_tasks(
                    42, output_dir, 1, lambda _message: None, interval_minutes=60,
                )

        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["reason"], "finished")


class SpiritDrawTaskTestsContinued(unittest.TestCase):
    def test_spirit_draw_treats_missing_sync_and_no_free_quota_as_finished(self) -> None:
        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def spirit_state(self):
                return None

            def spirit_free_draw(self):
                return {"ret": 1111, "spiritIds": []}

            def item_count(self, _item_id):
                return 0

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_spirit_draw_tasks(42, output_dir, 2, lambda _message: None)

        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["remaining"], 2)
        self.assertEqual(result["reason"], "spirit_draw_failed")

    def test_spirit_paid_draw_is_limited_by_summon_tickets(self) -> None:
        paid_requests = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def spirit_state(self):
                return {"drawTimes": 0, "freeAdTimes": 0, "lastAdTime": 0}

            def item_count(self, item_id):
                return 3 if item_id == game.SPIRIT_TICKET_ITEM else 0

            def spirit_draw(self, count, is_ad=False):
                paid_requests.append((count, is_ad))
                return {"ret": 0, "spiritIds": [121001] * count}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_spirit_draw_tasks(
                    42, output_dir, 0, lambda _message: None, paid_count=5,
                )

        self.assertEqual(paid_requests, [(3, False)])
        self.assertEqual(result["paidCompleted"], 3)
        self.assertEqual(result["remaining"], 0)

    def test_yard_draw_runs_ad_free_with_delay_then_normal_without_delay(self) -> None:
        batches = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                pass

            def enter_yard(self):
                return {"ret": 0, "buildings": {}, "drawData": {"freeDrawTimes": 0}}

            def yard_draw(self, ten=False, is_ad=False):
                batches.append((ten, is_ad))
                return {"ret": 0, "count": 10 if ten else 1}

            def resource_snapshot(self, server_id):
                return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}',
                encoding="utf-8",
            )
            with patch.object(game, "GameSession", FakeSession), patch.object(game.time, "sleep") as sleep:
                result = game.run_yard_draw_tasks(42, output_dir, 13, lambda _message: None)

        self.assertEqual(batches, [
            (False, True), (False, True), (False, False), (False, False),
        ])
        sleep.assert_called_once_with(game.FREE_DRAW_INTERVAL_SECONDS)
        self.assertEqual(result["completed"], 4)


class TreasureAuctionTests(unittest.TestCase):
    def test_task_claims_visit_event_then_refreshes_state(self) -> None:
        calls = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs): self.enters = 0
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def treasure_auction_enter(self):
                self.enters += 1
                calls.append("enter")
                return {
                    "ret": 0,
                    "events": ([{"eventId": 1669}] if self.enters == 1 else []),
                    "places": [], "items": [], "warehouseLimit": 50,
                }
            def treasure_auction_select_event(self, event_id, select_index=0):
                calls.append(("event", event_id, select_index)); return {"ret": 0}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_treasure_auction_tasks(
                    42, output_dir, 1, lambda _message: None,
                    claim_rewards=False, begin_explores=False,
                    help_friends=False, identify_treasures=False,
                )

        self.assertEqual(calls, ["enter", ("event", 1669, 0), "enter"])
        self.assertEqual(result["completed"], 1)

    def test_parse_state_separates_visit_events_from_treasure_places(self) -> None:
        event = (
            game.protobuf_int(1, 1669) + game.protobuf_int(2, 1009)
            + game.protobuf_int(3, 0) + game.protobuf_int(4, 60022)
        )
        place = (
            game.protobuf_int(1, 1119) + game.protobuf_int(2, 820002)
            + game.protobuf_int(3, 16) + game.protobuf_int(6, 455)
        )
        player = (
            game.protobuf_int(1, 0) + game.protobuf_int(2, 0)
            + game.protobuf_message(3, event) + game.protobuf_message(4, place)
            + game.protobuf_int(5, 50) + game.protobuf_int(6, 44)
            + game.protobuf_int(12, 1784080396252)
        )
        state = game.parse_treasure_auction_state(
            game.protobuf_int(1, 0) + game.protobuf_message(2, player)
        )

        self.assertEqual(state["events"], [{
            "eventId": 1669, "configId": 1009, "state": 0, "appearance": 60022,
        }])
        self.assertEqual(state["places"][0]["id"], 1119)
        self.assertEqual(state["places"][0]["treasureMapId"], 820002)
        self.assertEqual(state["warehouseLimit"], 50)
        self.assertEqual(state["equipIds"], {44})
        self.assertEqual(state["lastCreateEventTime"], 1784080396252)

    def test_request_payloads(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []

        def request(message_id, response_id, payload=b""):
            captured.append((message_id, response_id, payload))
            return game.protobuf_int(1, 0)

        session._request = request  # type: ignore[method-assign]
        session.treasure_auction_select_event(1669, 0)
        session.treasure_auction_claim_rewards([3, 5])
        session.treasure_auction_help_one_key()
        session.treasure_auction_disassemble([7, 9])

        self.assertEqual(captured[0], (
            game.TREASURE_AUCTION_SELECT_EVENT, game.TREASURE_AUCTION_SELECT_EVENT_RESPONSE,
            game.protobuf_int(1, 1669) + game.protobuf_int(2, 0),
        ))
        self.assertEqual(captured[1][2], game.protobuf_int(1, 3) + game.protobuf_int(1, 5))
        self.assertEqual(captured[2][2], game.protobuf_int(3, 1))
        self.assertEqual(captured[3][2], game.protobuf_int(1, 7) + game.protobuf_int(1, 9))

    def test_task_claims_starts_helps_and_disassembles_selected_quality(self) -> None:
        calls = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs):
                self.enters = 0

            def __enter__(self): return self
            def __exit__(self, *_args): pass

            def treasure_auction_enter(self):
                self.enters += 1
                if self.enters == 1:
                    return {"ret": 0, "places": [
                        {"id": 1, "isCompleted": True, "treasureMapId": 1, "beginTime": 1},
                        {"id": 2, "treasureMapId": 2, "beginTime": 0},
                    ], "items": [], "warehouseLimit": 4}
                return {"ret": 0, "places": [{"id": 2, "treasureMapId": 2, "beginTime": 0}],
                    "warehouseLimit": 4, "equipIds": {13}, "items": [
                        {"id": 10, "isIdentify": True, "quality": 0},
                        {"id": 11, "isIdentify": True, "quality": 1},
                        {"id": 12, "isIdentify": True, "quality": 1, "lock": True},
                        {"id": 13, "isIdentify": True, "quality": 0},
                        {"id": 14, "isIdentify": True, "quality": 2},
                        {"id": 20, "isIdentify": False}, {"id": 21, "isIdentify": False},
                    ]}

            def treasure_auction_select_event(self, event_id, select_index=0):
                calls.append(("event", event_id, select_index)); return {"ret": 0}

            def treasure_auction_claim_rewards(self, ids): calls.append(("claim", ids)); return {"ret": 0}
            def treasure_auction_begin(self, place_id): calls.append(("begin", place_id)); return {"ret": 0}
            def treasure_auction_get_help_list(self): return {"ret": 0, "entries": [{}]}
            def treasure_auction_help_one_key(self): calls.append(("help",)); return {"ret": 0}
            def treasure_auction_disassemble(self, ids): calls.append(("disassemble", ids)); return {"ret": 0}
            def treasure_auction_identify(self, item_id): calls.append(("identify", item_id)); return {"ret": 0}
            def resource_snapshot(self, server_id): return {"serverId": server_id}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_treasure_auction_tasks(
                    42, output_dir, 1, lambda _message: None, disassemble_quality=1)

        self.assertEqual(calls, [
            ("claim", [1]), ("begin", 2), ("help",),
            ("disassemble", [10, 11]), ("identify", 20), ("identify", 21),
        ])
        self.assertEqual(result["ret"], 0)


class GameSessionHeartbeatTests(unittest.TestCase):
    def test_claim_all_mail_rewards_uses_batch_protocol(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        captured = []

        def request(message_id, response_id, payload=b""):
            captured.append((message_id, response_id, payload))
            return game.protobuf_int(1, 0) + game.protobuf_string(2, "100000=50|100003=20")

        session._request = request  # type: ignore[method-assign]
        result = session.claim_all_mail_rewards()
        self.assertEqual(captured, [(
            game.MAIL_GET_ALL_REWARD, game.MAIL_GET_ALL_REWARD_RESPONSE, b"",
        )])
        self.assertEqual(result["rewards"], "100000=50|100003=20")

    def test_background_heartbeat_runs_while_caller_is_blocked(self) -> None:
        sent = []

        class FakeSocket:
            def send_binary(self, payload):
                sent.append(game.parse_frame(payload)[0])

            def close(self):
                pass

        session = game.GameSession("wss://example.invalid", 1, "token")
        session.socket = FakeSocket()  # type: ignore[assignment]
        with patch.object(game, "HEARTBEAT_INTERVAL_SECONDS", 0.01):
            session._start_heartbeat()
            time.sleep(0.06)
            session.close()

        self.assertGreaterEqual(sent.count(game.PLAYER_PING), 2)

    def test_resource_snapshot_does_not_issue_optional_feature_requests(self) -> None:
        session = game.GameSession("wss://example.invalid", 1, "token")
        session.observed_frames = []
        session._request = lambda *_args, **_kwargs: self.fail("unexpected request")  # type: ignore[method-assign]

        snapshot = session.resource_snapshot(42)

        self.assertEqual(snapshot["serverId"], 42)


class ChopDivineMindIntegrationTests(unittest.TestCase):
    def test_chop_and_treasure_monitor_share_one_session(self) -> None:
        instances = 0
        calls = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs):
                nonlocal instances
                instances += 1
                self.equipped_items = []
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def resource_snapshot(self, server_id): return {"serverId": server_id, "jade": 0, "spiritStone": 0}
            def item_count(self, _item_id): return 0
            def get_pending_equipment(self): return []
            def treasure_auction_enter(self):
                calls.append("treasure")
                return {"ret": 0, "events": [], "places": [], "items": [], "warehouseLimit": 50}
            def chop_tree(self, auto=False):
                calls.append("chop")
                return {"ret": 0, "equipment": [], "rewards": []}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_chop_tasks(
                    42, output_dir, 1, 0, "decompose", 5, lambda _message: None,
                    treasure_auction_options={
                        "claim_rewards": False, "begin_explores": False,
                        "help_friends": False, "identify_treasures": False,
                        "disassemble_quality": -1,
                    },
                )

        self.assertEqual(instances, 1)
        self.assertEqual(calls, ["treasure", "chop"])
        self.assertEqual(result["reason"], "finished")

    def test_chop_and_divine_mind_share_one_session(self) -> None:
        instances = 0
        calls = []

        class FakeSession:
            def __init__(self, *_args, **_kwargs):
                nonlocal instances
                instances += 1
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def resource_snapshot(self, server_id): return {"serverId": server_id, "jade": 0, "spiritStone": 0}
            def item_count(self, _item_id): return 0
            def get_pending_equipment(self): return []
            def divine_insight_receive_mind(self):
                calls.append("mind")
                return {"ret": 0, "receiveNum": 10, "inspireAddNum": 2}
            def chop_tree(self, auto=False):
                calls.append("chop")
                return {"ret": 0, "equipment": [], "rewards": []}

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "player-login-42.json").write_text(
                '{"wsAddress":"wss://example.invalid","playerId":1,"token":"token"}', encoding="utf-8")
            with patch.object(game, "GameSession", FakeSession):
                result = game.run_chop_tasks(
                    42, output_dir, 1, 0, "decompose", 5, lambda _message: None,
                    divine_mind_interval_minutes=60,
                )

        self.assertEqual(instances, 1)
        self.assertEqual(calls, ["mind", "chop"])
        self.assertEqual(result["reason"], "finished")


if __name__ == "__main__":
    unittest.main()
