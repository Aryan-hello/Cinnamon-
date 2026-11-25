"""Regression checks for the no-code Shop & Items workshop."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard.py"
RUNTIME = ROOT / "cinnamon_modules" / "dashboard_runtime.py"
ADVANCED = ROOT / "cinnamon_modules" / "advanced_economy.py"


class ShopWorkshopSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = DASHBOARD.read_text(encoding="utf-8")
        cls.runtime = RUNTIME.read_text(encoding="utf-8")
        cls.advanced = ADVANCED.read_text(encoding="utf-8")

    def test_workshop_page_and_actions_are_registered(self):
        self.assertIn("def _shop_items(guild, state):", self.dashboard)
        self.assertIn('"shop_items":_shop_items', self.dashboard)
        self.assertIn('"shop_items","giveaways"', self.dashboard)
        for action in (
            "shop_item_add", "shop_item_save", "shop_item_disable",
            "shop_recipe_save", "shop_recipe_remove",
            "shop_box_reward_add", "shop_box_reward_remove",
            "shop_box_weight", "shop_box_distribution",
            "shop_items_log_channel",
        ):
            self.assertIn(action, self.dashboard)

    def test_shop_mutations_require_upstash_and_commit_audit_events(self):
        self.assertIn("def _shop_workshop_commit", self.dashboard)
        self.assertIn("UPSTASH_REDIS_REST_URL", self.dashboard)
        self.assertIn("UPSTASH_REDIS_REST_TOKEN", self.dashboard)
        self.assertIn("shop_item_audit_v1", self.dashboard)
        self.assertIn('"Audit storage", "Upstash snapshot committed"', self.dashboard)
        self.assertIn('"shop_items"', self.dashboard)

    def test_crafting_recipe_definitions_are_restored_after_snapshot_load(self):
        self.assertIn('"CRAFTING_RECIPES": globals().get("CRAFTING_RECIPES", {})', self.runtime)
        self.assertIn("custom_crafting_recipes_v1", self.runtime)
        self.assertIn("disabled_crafting_recipes_v1", self.runtime)
        self.assertIn("Reapply administrator-managed recipes", self.runtime)

    def test_mystery_box_pools_support_exclusions_and_relative_weights(self):
        self.assertIn("def _box_reward_pool", self.advanced)
        self.assertIn("disabled_items", self.dashboard)
        self.assertIn("disabled_materials", self.dashboard)
        self.assertIn("def _weighted_box_choice", self.advanced)
        self.assertIn("outcome_weights", self.advanced)
        self.assertIn("category_weights", self.advanced)
        self.assertIn("_weighted_reward(guild_id)", self.advanced)

    def test_legacy_catalogue_migrates_gag_services_without_overriding_saved_choices(self):
        self.assertIn("Saved catalogs are authoritative", self.runtime)
        self.assertIn("if saved_items and isinstance(gag_defaults, dict):", self.runtime)
        self.assertIn('current["category"] = "grow_a_garden"', self.runtime)
        self.assertIn('current["category"] = "grow_a_garden"', (ROOT / "cinnamon_modules" / "economy.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
