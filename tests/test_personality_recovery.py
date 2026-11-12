"""Regression tests for Cinnamon's best-effort social recovery."""
import ast
import json
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


class PersonalityRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_naughty_status_recovery_is_saved_without_other_changes(self):
        source = (ROOT / "cinnamon_modules" / "cinnamon_personality.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_cp_recover"
        )

        message = SimpleNamespace(embeds=[SimpleNamespace(
            title="CINNAMON_PEOPLE_LOG",
            fields=[
                SimpleNamespace(name="User ID", value="123"),
                SimpleNamespace(name="Member state", value="{}"),
                SimpleNamespace(name="Naughty until", value="2000"),
            ],
        )])

        class FakeChannel:
            async def history(self, limit=1200, oldest_first=False):
                yield message

        channel = FakeChannel()
        guild = SimpleNamespace(
            id=456,
            text_channels=[channel],
            get_channel=lambda channel_id: channel,
        )
        existing_people = {"123": {"good": 4}}
        member_state = {"naughty_until": 0}
        saves = []

        async def save_data():
            saves.append(True)

        class FakeHTTPException(Exception):
            pass

        class FakeForbidden(Exception):
            pass

        namespace = {
            "discord": SimpleNamespace(
                HTTPException=FakeHTTPException,
                Forbidden=FakeForbidden,
            ),
            "_CP_LOG": "CINNAMON_PEOPLE_LOG",
            "category_log_channels": {456: {"stuff": 789}},
            "advanced_features_data": {
                "cinnamon_mood_v1": {
                    "456": {"score": 0, "updated": 1000, "members": {}}
                }
            },
            "_cp_server": lambda guild_id: {"people": existing_people},
            "_cp_json": json,
            "_cp_time": SimpleNamespace(time=lambda: 1000),
            "_cm_member": lambda guild_id, user_id: member_state,
            "bd_save_data": save_data,
            "log": SimpleNamespace(warning=lambda *args, **kwargs: None),
        }
        module = ast.Module(body=[function], type_ignores=[])
        exec(compile(module, "cinnamon_personality.py", "exec"), namespace)

        result = await namespace["_cp_recover"](guild)

        self.assertEqual(member_state["naughty_until"], 2000)
        self.assertEqual(saves, [True])
        self.assertEqual(result, {"members": 0, "mood": 0, "scanned": 1})


if __name__ == "__main__":
    unittest.main()
