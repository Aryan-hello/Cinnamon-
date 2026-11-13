"""Quest Shop safety regressions: serialized spending and role failures don't charge QP."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QuestShopSafetyTests(unittest.TestCase):
    def test_redemption_is_serialized_and_role_is_verified_before_qp_debit(self):
        tree = ast.parse((ROOT / "cinnamon_modules/quests.py").read_text(encoding="utf-8"))
        command = next(node for node in tree.body
                      if isinstance(node, ast.AsyncFunctionDef) and node.name == "questshop_cmd")
        sections = [node for node in command.body if isinstance(node, ast.AsyncWith)]
        self.assertEqual(len(sections), 1)
        section = sections[0]
        self.assertIn("_QUEST_SHOP_LOCKS.setdefault", ast.unparse(section.items[0].context_expr))
        body = ast.unparse(section)
        self.assertLess(body.index("_assign_quest_role"), body.index("u['qp'] -="))
        self.assertIn("bd_save_data", body)
        self.assertIn("getattr(result", body)


if __name__ == "__main__":
    unittest.main()
