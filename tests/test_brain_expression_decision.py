"""Focused behavior tests for Cinnamon's optional AI adviser and expression layers."""
import ast
import asyncio
import copy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import time
import unittest

from cinnamon_modules.brain_actions import parse_action
from cinnamon_modules.brain_reminders import parse_reminder_request
from cinnamon_modules.brain_memory import parse_explicit_preference
from cinnamon_modules.brain_decision import (
    ActivitySignals, default_activity, interpret_activity_choice,
)
from cinnamon_modules.brain_expression import curated_emoji_names, safe_reaction

ROOT = Path(__file__).resolve().parents[1]
MENTION = "<@123456789012345678>"


def functions_in(filename, names, namespace):
    source = (ROOT / "cinnamon_modules" / filename).read_text(encoding="utf-8")
    tree = ast.parse(source)
    body = [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name in names]
    assert len(body) == len(names), filename
    exec(compile(ast.Module(body=body, type_ignores=[]), filename, "exec"), namespace)
    return namespace


class BrainLanguageTests(unittest.TestCase):
    def test_polite_admin_actions_still_use_typed_allowlist(self):
        parsed = parse_action(
            f"Cinnamon, could you please add 20,000 Catnip to {MENTION}?",
            requester_id=100, target_ids=[123456789012345678])
        self.assertEqual(parsed.action, "economy.add_catnip")
        self.assertEqual(parsed.amount, 20000)

    def test_polite_reminders_and_explicit_memory(self):
        from datetime import datetime, timezone
        due = parse_reminder_request(
            "Cinnamon could you please remind me to finish my story in 2 hours",
            now=datetime(2026, 10, 31, 6, 0, tzinfo=timezone.utc))
        self.assertEqual(due.text, "finish my story")
        note = parse_explicit_preference(
            "Cinnamon, could you please remember I like mystery stories")
        self.assertEqual(note.category, "stories")

    def test_large_server_emoji_list_is_curated(self):
        names = [f"image_{n}" for n in range(1000)] + [
            "cinnamonPurr", "catHappy", "grumpyCat", "tunaFish", "@everyone"
        ]
        delighted = curated_emoji_names(names, mood="delighted", limit=12)
        self.assertEqual(len(delighted), 12)
        self.assertIn("catHappy", delighted)
        self.assertNotIn("@everyone", delighted)
        grumpy = curated_emoji_names(names, mood="grumpy", limit=12)
        self.assertIn("grumpyCat", grumpy)

    def test_reaction_allowlist_and_serious_silence(self):
        self.assertEqual(safe_reaction("grumpyCat", ["grumpyCat"]), "grumpyCat")
        self.assertEqual(safe_reaction("not a real emoji", []), "")
        self.assertEqual(safe_reaction("<@123456>", []), "")
        self.assertEqual(safe_reaction("grumpyCat", ["grumpyCat"], serious=True), "")

    def test_ai_choice_is_not_authorization(self):
        self.assertEqual(interpret_activity_choice('{"choice": "game"}',
                                                   prompt_allowed=False), "game")
        self.assertEqual(interpret_activity_choice('{"choice": "prompt"}',
                                                   prompt_allowed=False), "wait")
        self.assertEqual(interpret_activity_choice('{"choice": "prompt"}',
                                                   prompt_allowed=True), "prompt")
        for bad in ('{"choice": "ban_member"}', "not json", '{"choice":"exec"}'):
            self.assertEqual(interpret_activity_choice(bad, prompt_allowed=True), "wait")

    def test_fallback_choice_prefers_silence_without_engagement(self):
        self.assertEqual(default_activity(ActivitySignals(0, 0, "normal", True), 2),
                         "wait")
        self.assertEqual(default_activity(ActivitySignals(6, 2, "normal", True), 2),
                         "prompt")
        self.assertEqual(default_activity(ActivitySignals(6, 2, "normal", False), 2),
                         "game")


class ReminderAtMostOnceTests(unittest.IsolatedAsyncioTestCase):
    def runtime(self, *, save_ok=True, delivery_success=True):
        entries = {}
        states, sent = [], []
        async def save():
            states.append({k:v.get("status") for k,v in entries.items()})
            return save_ok
        class FakeUser:
            async def send(self, content, **kwargs):
                sent.append(content)
                if not delivery_success:
                    raise FakeForbidden("Cannot DM")
        class FakeForbidden(Exception):
            pass
        ns = {
            "_CR_LOCK": asyncio.Lock(),
            "_cr_time": time,
            "_cr_member": lambda gid, uid: entries,
            "bd_save_data": save,
            "bot": SimpleNamespace(get_user=lambda uid: FakeUser()),
            "discord": SimpleNamespace(
                Forbidden=FakeForbidden, HTTPException=FakeForbidden,
                AllowedMentions=SimpleNamespace(none=lambda: None),
                utils=SimpleNamespace(escape_markdown=lambda t: t)),
            "log": SimpleNamespace(warning=lambda *args: None,
                                   error=lambda *args: None),
        }
        functions_in("cinnamon_reminders.py", {"_cr_deliver"}, ns)
        rid = "abc"
        entries[rid] = {"id": rid, "text": "check quests",
                        "due_at": int(time.time()) - 30, "status": "scheduled"}
        return ns, entries, states, sent

    async def test_delivery_claim_is_saved_before_dm_and_does_not_repeat(self):
        ns, entries, states, sent = self.runtime()
        await ns["_cr_deliver"](1, 99, "abc")
        self.assertEqual([x["abc"] for x in states], ["sending", "sent"])
        self.assertEqual(len(sent), 1)
        await ns["_cr_deliver"](1, 99, "abc")
        self.assertEqual(len(sent), 1)

    async def test_crash_state_is_never_blindly_redelivered(self):
        ns, entries, states, sent = self.runtime()
        entries["abc"]["status"] = "sending"
        await ns["_cr_deliver"](1, 99, "abc")
        self.assertEqual(len(sent), 0)

    async def test_failed_claim_never_sends_dm(self):
        ns, entries, states, sent = self.runtime(save_ok=False)
        await ns["_cr_deliver"](1, 99, "abc")
        self.assertEqual(len(sent), 0)
        self.assertEqual(entries["abc"]["status"], "scheduled")

    async def test_discord_dm_refusal_marks_failed_without_spam(self):
        ns, entries, states, sent = self.runtime(delivery_success=False)
        await ns["_cr_deliver"](1, 99, "abc")
        self.assertEqual(entries["abc"]["status"], "failed")
        await ns["_cr_deliver"](1, 99, "abc")
        self.assertEqual(len(sent), 1)


class CommunityActivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_community_prompt_is_optin_no_ping_and_claimed_before_send(self):
        sends, saves = [], []
        now = time.time()
        social = {"auto_enabled": True, "auto_channel": 7}
        class Channel:
            id = 7
            async def send(self, content, **kwargs):
                sends.append((content, kwargs))
        async def save():
            saves.append(copy.deepcopy(social))
            return True
        async def log(*args, **kwargs):
            pass
        ns = {
            "_cb_prompt_allowed": lambda gid: True,
            "_cb_game_eligibility": lambda *args, **kwargs: (True, "active"),
            "_cb_settings": lambda gid: {"prompts_enabled": True},
            "_cp_server": lambda gid: social,
            "_cp_time": SimpleNamespace(time=lambda: now),
            "_cp_random": SimpleNamespace(choice=lambda values: values[0]),
            "_CP_QUESTIONS": ["Are cucumbers evil?"],
            "bd_save_data": save, "_cp_log": log,
            "discord": SimpleNamespace(
                AllowedMentions=SimpleNamespace(none=lambda: None),
                Forbidden=type("Forbidden", (Exception,), {}),
                HTTPException=type("HTTP", (Exception,), {})),
        }
        functions_in("cinnamon_personality.py", {"_cp_auto_prompt"}, ns)
        posted = await ns["_cp_auto_prompt"](SimpleNamespace(id=1), Channel(), object())
        self.assertTrue(posted)
        self.assertEqual(len(sends), 1)
        self.assertIn("Are cucumbers evil", sends[0][0])
        self.assertNotIn("@everyone", sends[0][0])
        self.assertTrue(saves)
        self.assertIn("last_public_prompt_at", saves[0])


if __name__ == "__main__":
    unittest.main()
