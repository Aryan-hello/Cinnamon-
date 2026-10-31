"""Regression tests for ordinary chat's private-data boundaries."""
import ast
from pathlib import Path
import unittest


class OrdinaryChatBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(
            encoding="utf8"
        )
        tree = ast.parse(source)
        assignment = next(
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "SYSTEM_PROMPT"
                    for target in node.targets)
        )
        cls.prompt = ast.literal_eval(assignment.value)

    def test_chat_must_not_invent_private_account_state(self):
        prompt = self.prompt.lower()
        for phrase in (
            "never guess or claim to know those values",
            "catnip balance",
            "quests",
            "reminders",
            "/cinnamon-me ask",
        ):
            self.assertIn(phrase, prompt)

    def test_chat_must_not_reveal_another_members_private_data(self):
        self.assertIn(
            "never reveal another member's private data",
            self.prompt.lower(),
        )
        normalized = " ".join(self.prompt.lower().split())
        self.assertIn(
            "even if it appears in channel conversation history",
            normalized,
        )


if __name__ == "__main__":
    unittest.main()
