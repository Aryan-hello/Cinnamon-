"""Source-level regression tests for the confirmed inventory resale flow."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cinnamon_modules" / "economy.py"


class EconomySellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_sell_command_is_registered_under_economy(self):
        commands = [
            node for node in ast.walk(self.tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "economy_sell_cmd"
        ]
        self.assertEqual(len(commands), 1)
        self.assertTrue(any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "command"
            and any(keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value == "sell" for keyword in decorator.keywords)
            for decorator in commands[0].decorator_list
        ))

    def test_sale_requires_confirmation_and_checks_current_inventory(self):
        self.assertIn("class EconomySellConfirmView", self.source)
        self.assertIn("async def confirm", self.source)
        self.assertIn("owned = int(inv.get(self.item_id, 0))", self.source)
        self.assertIn("if owned < self.quantity", self.source)
        self.assertIn("await bd_save_data()", self.source)
        self.assertIn("economy_log(self.guild_id, title=\"💰 Economy item sold\"", self.source)

    def test_service_and_mystery_rewards_are_not_sold_without_provenance(self):
        self.assertIn('item.get("service_type")', self.source)
        self.assertIn('item.get("category") == "grow_a_garden"', self.source)
        self.assertIn('item_id in (tier.get("items", []) + tier.get("materials", []))', self.source)
        self.assertIn("need their provenance rules first", self.source)

    def test_resale_price_uses_configured_value_or_half_shop_price(self):
        self.assertIn('configured = item.get("sell_price")', self.source)
        self.assertIn('int(item.get("price", 0)) // 2', self.source)


if __name__ == "__main__":
    unittest.main()
