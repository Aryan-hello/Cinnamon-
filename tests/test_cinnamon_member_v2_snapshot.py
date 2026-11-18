"""Private Brain snapshots stay member-scoped and expose only verified progress."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_snapshot(namespace):
    path = ROOT / "cinnamon_modules" / "cinnamon_member_v2.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(item for item in tree.body
                if isinstance(item, ast.FunctionDef)
                and item.name == "_me_private_snapshot")
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"),
         namespace)
    return namespace["_me_private_snapshot"]


class PrivateBrainSnapshotTests(unittest.TestCase):
    def test_progress_includes_only_requesters_quest_and_achievement_state(self):
        guild_id, user_id = 123, 456
        namespace = {
            "_cb_storage_available": lambda: True,
            "economy_balances": {},
            "economy_inventory": {},
            "xp_data": {(guild_id, user_id): 725},
            "level_from_xp": lambda xp: 2,
            "total_xp_for_level": lambda level: 1000,
            "MAX_LEVEL": 20,
            "_me_level_progress": lambda xp, **kwargs: {
                "level": 2, "total_xp": xp, "xp_remaining": 275,
            },
            "quest_data": {
                guild_id: {
                    "daily_date": "today",
                    "daily_ids": ["daily-one"],
                    "weekly_key": "week-one",
                    "weekly_ids": ["weekly-one"],
                    "users": {
                        str(user_id): {
                            "qp": 35,
                            "completed_history": [{"id": "old-quest"}],
                            "daily": {"daily-one": {"count": 2}},
                            "weekly": {"weekly-one": {"count": 1}},
                        },
                        "999": {
                            "qp": 999,
                            "completed_history": [{"id": "other-user"}],
                        },
                    },
                },
            },
            "_today": lambda: "today",
            "_week": lambda: "week-one",
            "DAILY_QUESTS": {"daily-one": {"name": "Daily test", "target": 2}},
            "WEEKLY_QUESTS": {"weekly-one": {"name": "Weekly test", "target": 3}},
            "_completed": lambda definition, state: state.get("count", 0) >= definition.get("target", 0),
            "achievement_data": {
                (guild_id, user_id): {
                    "unlocked": ["a", "b"],
                    "secret_unlocked": ["secret-a"],
                },
            },
            "advanced_features_data": {},
        }
        snapshot = load_snapshot(namespace)(guild_id, user_id, ["progress"])
        progress = snapshot["progress"]
        self.assertEqual(progress["total_xp"], 725)
        self.assertEqual(progress["level"], 2)
        self.assertEqual(progress["xp_remaining"], 275)
        self.assertEqual(progress["quest_points"], 35)
        self.assertEqual(progress["quests_completed"], 1)
        self.assertEqual(progress["daily_quests"][0]["name"], "Daily test")
        self.assertTrue(progress["daily_quests"][0]["completed"])
        self.assertFalse(progress["weekly_quests"][0]["completed"])
        self.assertEqual(progress["achievements_unlocked"], 2)
        self.assertEqual(progress["secret_achievements_discovered"], 1)

    def test_storage_unavailable_returns_no_inferred_progress(self):
        snapshot = load_snapshot({"_cb_storage_available": lambda: False})
        result = snapshot(123, 456, ["progress"])
        self.assertFalse(result["progress"]["available"])
        self.assertNotIn("total_xp", result["progress"])


if __name__ == "__main__":
    unittest.main()
