"""Offline tests for the member-owned companion progression rules."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "cinnamon_modules" / "companion.py"


def load_pure_helpers():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    wanted = {"_companion_level", "_companion_mood", "_companion_clamp"}
    nodes = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in wanted]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(MODULE), "exec"), namespace)
    return namespace


class CompanionTests(unittest.TestCase):
    def test_progression_levels_and_stat_clamps(self):
        helpers = load_pure_helpers()
        self.assertEqual(helpers["_companion_level"](0), 1)
        self.assertEqual(helpers["_companion_level"](100), 2)
        self.assertEqual(helpers["_companion_level"](300), 3)
        self.assertEqual(helpers["_companion_clamp"](-5), 0)
        self.assertEqual(helpers["_companion_clamp"](150), 100)

    def test_mood_uses_care_state_priority(self):
        mood = load_pure_helpers()["_companion_mood"]
        self.assertEqual(mood({"hunger": 10, "cleanliness": 0, "energy": 0}), "Hungry")
        self.assertEqual(mood({"hunger": 50, "cleanliness": 10, "energy": 0}), "Messy")
        self.assertEqual(mood({"hunger": 50, "cleanliness": 50, "energy": 10}), "Sleepy")
        self.assertEqual(mood({"hunger": 90, "happiness": 90, "cleanliness": 80, "energy": 80}), "Playful")

    def test_all_requested_companion_commands_exist(self):
        source = MODULE.read_text(encoding="utf-8")
        for name in ("pet", "feed", "play", "groom", "dressup", "room",
                     "mood", "catbook", "memories", "catstats"):
            self.assertIn(f'name="{name}"', source)

    def test_companion_shares_existing_inventory_and_snapshot(self):
        source = MODULE.read_text(encoding="utf-8")
        self.assertIn("economy_inventory_for", source)
        self.assertIn("economy_balances", source)
        self.assertIn("bd_save_data()", source)
        self.assertIn('"companion_profiles_v1"', source)
        self.assertNotIn("wildlands_", source)

    def test_accessories_and_room_items_are_shared_catalogue_entries(self):
        source = MODULE.read_text(encoding="utf-8")
        self.assertIn("ECONOMY_ITEMS.setdefault(_room_id", source)
        self.assertIn('"golden_bell_collar": "neck"', source)
        self.assertIn('"dream_wings": "back"', source)


if __name__ == "__main__":
    unittest.main()
