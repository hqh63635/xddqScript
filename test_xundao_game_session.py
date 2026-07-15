import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import xundao_game_session as game


def message_field(number: int, payload: bytes) -> bytes:
    return game.encode_varint(number << 3 | 2) + game.encode_varint(len(payload)) + payload


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


if __name__ == "__main__":
    unittest.main()
