"""Regression checks for tiered Mystery Box wiring (source-level, no Discord boot)."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cinnamon_modules" / "advanced_economy.py"

class MysteryTierSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_all_five_tiers_are_declared(self):
        for tier in ("common", "rare", "epic", "legendary", "mythical"):
            self.assertIn(f'"{tier}": {{', self.source)

    def test_tier_drop_weights_and_source_chances_exist(self):
        self.assertIn("MYSTERY_DROP_TIER_WEIGHTS", self.source)
        self.assertIn("MYSTERY_SOURCE_CHANCES", self.source)
        self.assertIn("def _roll_box_tier", self.source)
        self.assertIn('"rare": 25', self.source)
        self.assertIn('"epic": 10', self.source)
        self.assertIn('"legendary": 4', self.source)
        self.assertIn('"mythical": 1', self.source)

    def test_prefix_and_slash_commands_accept_tier(self):
        self.assertIn("tier: app_commands.Choice[str] | None", self.source)
        self.assertIn("quantity: int = 1, tier: str = \"common\"", self.source)
        self.assertIn("_open_one(ctx.guild.id, ctx.author, tier)", self.source)

    def test_expansion_items_are_registered_and_unwired_consumables_disabled(self):
        for item_id in ("moonstone", "dream_petals", "captured_star", "dream_wings", "treasure_map", "starry_elixir"):
            self.assertIn(f'"{item_id}":', self.source)
        self.assertIn("Disabled: XP boost effect is not wired yet.", self.source)
        # Box-exclusive items are registered but intentionally not purchasable.
        self.assertIn('"shop_enabled": False', self.source)
        self.assertIn("50% tier items", self.source)

    def test_reward_openings_are_saved_and_logged(self):
        self.assertIn("await bd_save_data()", self.source)
        self.assertIn("await economy_log(", self.source)
        self.assertIn("ADVANCED_FEATURES[\"mystery_opened\"]", self.source)

if __name__ == "__main__":
    unittest.main()
