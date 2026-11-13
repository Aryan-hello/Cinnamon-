"""Regression guard: slash and button purchases must share a per-member lock."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EconomyPurchaseLockTests(unittest.TestCase):
    def test_slash_purchase_checks_and_mutations_are_inside_member_lock(self):
        tree = ast.parse((ROOT / "cinnamon_modules/economy.py").read_text(encoding="utf-8"))
        command = next(node for node in tree.body
                      if isinstance(node, ast.AsyncFunctionDef)
                      and node.name == "economy_buy_cmd")
        locked = [node for node in command.body if isinstance(node, ast.AsyncWith)]
        self.assertEqual(len(locked), 1, "purchase should have one explicit critical section")
        guard = locked[0]
        source = ast.unparse(guard.items[0].context_expr)
        self.assertIn("_CINNAMON_SHOP_LOCKS.setdefault", source)
        self.assertIn("economy_balances", ast.unparse(guard))
        self.assertIn("economy_inventory_for", ast.unparse(guard))
        self.assertIn("bd_save_data", ast.unparse(guard))
        # Mutations must not accidentally migrate back outside the lock.
        outside = ast.Module(body=[node for node in command.body if node is not guard],
                             type_ignores=[])
        for node in ast.walk(outside):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    self.assertFalse(
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "economy_balances",
                        "wallet debit escaped the lock",
                    )


if __name__ == "__main__":
    unittest.main()
