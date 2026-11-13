"""Regression tests for Hangry Games command access checks."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_runner_check():
    source = (ROOT / "cinnamon_modules" / "hangry_games.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "_hangry_runner_allowed")
    # The real helper has a discord.Interaction annotation; supply only the
    # annotation symbol so this isolated test does not import discord.py.
    ns = {"discord": SimpleNamespace(Interaction=object)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "hangry_games.py", "exec"), ns)
    return ns[node.name]


class HangryRunnerPermissionTests(unittest.TestCase):
    def setUp(self):
        self.allowed = load_runner_check()

    def interaction(self, *, administrator=False, manage_messages=False, moderate_members=False):
        return SimpleNamespace(user=SimpleNamespace(guild_permissions=SimpleNamespace(
            administrator=administrator, manage_messages=manage_messages,
            moderate_members=moderate_members)))

    def test_administrator_allowed(self):
        self.assertTrue(self.allowed(self.interaction(administrator=True)))

    def test_manage_messages_allowed(self):
        self.assertTrue(self.allowed(self.interaction(manage_messages=True)))

    def test_moderate_members_allowed(self):
        self.assertTrue(self.allowed(self.interaction(moderate_members=True)))

    def test_regular_member_denied(self):
        self.assertFalse(self.allowed(self.interaction()))


if __name__ == "__main__":
    unittest.main()
