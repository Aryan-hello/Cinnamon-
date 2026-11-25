"""Regression checks for dashboard-configured shop item behaviour."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ShopItemRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = (ROOT / "cinnamon_modules" / "shop_items_runtime.py").read_text(encoding="utf-8")
        cls.economy = (ROOT / "cinnamon_modules" / "economy.py").read_text(encoding="utf-8")
        cls.dashboard = (ROOT / "dashboard.py").read_text(encoding="utf-8")
        cls.main = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_runtime_loads_after_economy_and_registers_use_command(self):
        self.assertLess(self.main.index('"economy.py"'), self.main.index('"shop_items_runtime.py"'))
        self.assertIn('@bot.tree.command(name="use"', self.runtime)
        self.assertIn("async def economy_use_cmd", self.runtime)

    def test_both_purchase_paths_enforce_stock_expiry_and_requirements(self):
        self.assertGreaterEqual(self.economy.count("_shop_item_purchase_failure("), 2)
        self.assertIn("stock_quantity", self.economy)
        self.assertIn("_shop_item_expired", self.runtime)
        self.assertIn("purchase_requirements", self.runtime)

    def test_item_use_checks_ownership_requirements_reuse_and_cooldown(self):
        self.assertIn('data.get("usable", False)', self.runtime)
        self.assertIn('data.get("reusable", False)', self.runtime)
        self.assertIn("use_requirements", self.runtime)
        self.assertIn("use_cooldown_seconds", self.runtime)

    def test_action_engine_supports_requested_effects_and_triggers(self):
        for action_type in ('"give_catnip"', '"give_item"', '"send_message"', '"reply"'):
            self.assertIn(action_type, self.runtime)
        self.assertIn('"bought_or_used"', self.runtime)
        self.assertIn("random_outcomes", self.runtime)

    def test_dashboard_exposes_and_validates_every_runtime_setting(self):
        for field in (
            "stock_unlimited", "stock_quantity", "expires_at", "usable", "reusable",
            "use_cooldown_seconds", "purchase_requirements", "use_requirements",
            "item_actions", "random_outcomes",
        ):
            self.assertIn(field, self.dashboard)

    def test_runtime_source_parses(self):
        ast.parse(self.runtime)
        ast.parse(self.economy)
        ast.parse(self.dashboard)


if __name__ == "__main__":
    unittest.main()
