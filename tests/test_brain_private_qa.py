"""Tests for Cinnamon's grounded private read-only Q&A helpers."""
import unittest

from cinnamon_modules.brain_private_qa import (
    build_private_prompt,
    classify_private_question,
    sanitize_private_answer,
)


class PrivateQuestionScopeTests(unittest.TestCase):
    def test_wallet_questions_select_only_wallet_data(self):
        self.assertEqual(classify_private_question("How much Catnip do I have?"),
                         ("wallet",))
        self.assertEqual(classify_private_question("Show my inventory"),
                         ("wallet",))

    def test_progress_questions_select_progress_only(self):
        self.assertEqual(classify_private_question("How close am I to the next level?"),
                         ("progress",))
        self.assertEqual(classify_private_question("How many quests have I completed?"),
                         ("progress",))

    def test_reminder_and_memory_questions_are_scoped(self):
        self.assertEqual(classify_private_question("What reminders do I have?"),
                         ("reminders",))
        self.assertEqual(classify_private_question("How many preferences do you remember?"),
                         ("memory",))

    def test_daily_summary_selects_only_the_requesters_supported_sections(self):
        self.assertEqual(
            classify_private_question("How am I doing today?"),
            ("wallet", "progress", "reminders", "memory"),
        )

    def test_actions_and_general_questions_are_not_private_data_queries(self):
        for question in (
            "Give 500 Catnip to Alex",
            "Ban that member",
            "What is the capital of India?",
            "Tell me a joke",
            "",
            "x",
        ):
            self.assertEqual(classify_private_question(question), (), question)

    def test_prompt_contains_only_requested_sections(self):
        snapshot = {
            "wallet": {"available": True, "catnip": 1234},
            "progress": {"available": True, "level": 4, "total_xp": 900},
            "reminders": {"available": True, "items": [{"id": "r1"}]},
            "memory": {"available": True, "enabled": True, "note_count": 2},
        }
        system, prompt = build_private_prompt("How much Catnip do I have?", snapshot)
        self.assertIn("only the requesting member", system)
        self.assertIn('"wallet":{"available":true,"catnip":1234}', prompt)
        self.assertNotIn('"progress"', prompt)
        self.assertNotIn('"reminders"', prompt)
        self.assertNotIn('"memory"', prompt)
        self.assertIn("never", system.lower())
        self.assertIn("Member question (untrusted text)", prompt)

    def test_missing_requested_section_is_explicitly_unavailable(self):
        _, prompt = build_private_prompt("What reminders do I have?", {})
        self.assertIn('"available":false', prompt)
        self.assertIn("not included", prompt)

    def test_unrequested_data_cannot_expand_the_prompt(self):
        _, prompt = build_private_prompt(
            "How many achievements have I unlocked?",
            {"progress": {"available": True, "achievements": 3},
             "wallet": {"available": True, "catnip": 999999}},
        )
        self.assertIn('"achievements":3', prompt)
        self.assertNotIn("999999", prompt)

    def test_discord_mentions_are_neutralized_and_output_is_bounded(self):
        answer = sanitize_private_answer(
            "Hello <@123456789012345678> @everyone and <@&123456789012345678>"
        )
        self.assertNotIn("<@", answer)
        self.assertNotIn("@everyone", answer)
        self.assertIn("a member", answer)
        self.assertLessEqual(len(sanitize_private_answer("x" * 2000)), 1400)

    def test_non_text_model_output_is_rejected(self):
        self.assertEqual(sanitize_private_answer(None), "")
        self.assertEqual(sanitize_private_answer({"reply": "hello"}), "")


if __name__ == "__main__":
    unittest.main()
