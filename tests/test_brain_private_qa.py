"""Tests for Cinnamon's grounded private read-only Q&A helpers."""
import ast
from pathlib import Path
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


    def test_runtime_snapshot_uses_read_only_lookups(self):
        source = (Path(__file__).resolve().parents[1]
                  / "cinnamon_modules" / "cinnamon_member_v2.py").read_text(encoding="utf8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_me_private_snapshot"
        )
        called = {
            node.func.id if isinstance(node.func, ast.Name)
            else node.func.attr if isinstance(node.func, ast.Attribute)
            else ""
            for node in ast.walk(function) if isinstance(node, ast.Call)
        }
        forbidden = {
            "bd_save_data", "economy_balance", "economy_inventory_for",
            "_ensure_rolls", "_cr_active", "_cr_member", "_cr_offset",
            "_cmem_member", "_cmem_context",
        }
        self.assertFalse(called & forbidden, sorted(called & forbidden))
        self.assertIn("_cb_storage_available", called)

    def test_private_ask_command_is_ephemeral_and_never_calls_action_handlers(self):
        source = (Path(__file__).resolve().parents[1]
                  / "cinnamon_modules" / "cinnamon_member_v2.py").read_text(encoding="utf8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "cinnamon_me_ask"
        )
        source_text = ast.get_source_segment(source, function)
        self.assertIn("ephemeral=True", source_text)
        self.assertIn("asyncio.to_thread", source_text)
        self.assertNotIn("_ca_maybe_handle", source_text)
        self.assertNotIn("bd_save_data", source_text)

    def test_non_text_model_output_is_rejected(self):
        self.assertEqual(sanitize_private_answer(None), "")
        self.assertEqual(sanitize_private_answer({"reply": "hello"}), "")


if __name__ == "__main__":
    unittest.main()
