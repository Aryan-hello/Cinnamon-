"""Offline checks for Cinnamon's engagement-aware independence policy.

No Discord login, network calls, or Gemini requests are required.
"""
import ast
import time
import unittest
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN_FILE = ROOT / "cinnamon_modules" / "cinnamon_brain.py"
BRAIN_SOURCE = BRAIN_FILE.read_text(encoding="utf-8")
TREE = ast.parse(BRAIN_SOURCE)


def policy_namespace():
    names = {
        "_cb_settings", "_cb_independence_enabled", "_cb_prune",
        "_cb_observe", "_cb_activity_stats", "_cb_game_decision",
    }
    nodes = [
        node for node in TREE.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    ns = {
        "advanced_features_data": {},
        "_CB_ACTIVITY": {},
        "_CB_WINDOW_SECONDS": 1800,
        "_CB_FRESH_SECONDS": 600,
        "_CB_MIN_MESSAGES": 6,
        "_CB_MIN_MEMBERS": 2,
        "_CB_EMPTY_GAME_BACKOFF": 21600,
        "_cb_deque": deque,
        "_cb_time": time,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]),
                 str(BRAIN_FILE), "exec"), ns)
    return ns


class CinnamonBrainPolicyTests(unittest.TestCase):
    def test_no_autonomous_game_without_live_engagement(self):
        ns = policy_namespace()
        allowed, why = ns["_cb_game_decision"](123, now=1000)
        self.assertFalse(allowed)
        self.assertEqual(why, "not_enough_recent_conversation")

    def test_active_multi_member_conversation_qualifies(self):
        ns = policy_namespace()
        observe = ns["_cb_observe"]
        for i in range(6):
            observe(123, 10 + i % 2, at=1000 + i * 5)
        allowed, why = ns["_cb_game_decision"](123, now=1030)
        self.assertTrue(allowed)
        self.assertEqual(why, "active_conversation")
        self.assertEqual(ns["_cb_activity_stats"](123, now=1030)["members"], 2)

    def test_one_talker_or_spam_does_not_create_fake_activity(self):
        ns = policy_namespace()
        observe = ns["_cb_observe"]
        for i in range(10):
            observe(123, 10, at=1000 + i * 5)
        allowed, why = ns["_cb_game_decision"](123, now=1050)
        self.assertFalse(allowed)
        self.assertEqual(why, "not_enough_people_engaged")
        for i in range(30):
            observe(456, 20, at=1000 + i * 0.05)
        self.assertEqual(ns["_cb_activity_stats"](456, now=1002)["messages"], 1)

    def test_server_can_go_quiet_after_being_active(self):
        ns = policy_namespace()
        for i in range(6):
            ns["_cb_observe"](1, i % 2, at=1000 + i * 5)
        allowed, reason = ns["_cb_game_decision"](1, now=1700)
        self.assertFalse(allowed)
        self.assertEqual(reason, "server_has_gone_quiet")
        self.assertEqual(ns["_cb_activity_stats"](1, now=4000)["messages"], 0)

    def test_unanswered_game_backoff_prevents_repeat_pings(self):
        ns = policy_namespace()
        for i in range(6):
            ns["_cb_observe"](1, 10 + i % 2, at=25000 + i * 5)
        allowed, reason = ns["_cb_game_decision"](
            1, now=25030, cancelled_at=25000)
        self.assertFalse(allowed)
        self.assertEqual(reason, "cooldown_after_unanswered_game")
        allowed, reason = ns["_cb_game_decision"](
            1, now=25030, auto_enabled=False)
        self.assertFalse(allowed)
        self.assertEqual(reason, "surprise_games_disabled")
        allowed, reason = ns["_cb_game_decision"](
            1, now=25030, channel_ok=False)
        self.assertFalse(allowed)
        self.assertEqual(reason, "channel_unavailable")

    def test_admin_switch_persists_in_shared_config_and_cuts_autonomy(self):
        ns = policy_namespace()
        settings = ns["_cb_settings"](88)
        self.assertTrue(ns["_cb_independence_enabled"](88))
        settings["independence_enabled"] = False
        allowed, reason = ns["_cb_game_decision"](88, now=1000)
        self.assertFalse(allowed)
        self.assertEqual(reason, "independence_disabled")
        self.assertFalse(ns["advanced_features_data"][
            "cinnamon_brain_v1"]["88"]["independence_enabled"])

    def test_channel_content_never_stored_in_brain_signals(self):
        ns = policy_namespace()
        ns["_cb_observe"](2, 21, at=1050)
        self.assertEqual(list(ns["_CB_ACTIVITY"][2]), [(1050.0, 21)])
        self.assertNotIn("message.content", str(ns["_CB_ACTIVITY"]))

    def test_single_scheduler_and_no_unrestricted_ai_actions(self):
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        personality = (ROOT / "cinnamon_modules" / "cinnamon_personality.py").read_text(
            encoding="utf-8")
        self.assertIn('"cinnamon_brain.py"', main)
        self.assertIn("_cb_game_eligibility(", personality)
        self.assertIn("last_unanswered_game_at", personality)
        self.assertIn('bot.tree.add_command(_cb_group)', BRAIN_SOURCE)
        self.assertIn("_cb_observe(guild_id, message.author.id)", (ROOT / "cinnamon_modules" / "core_events.py").read_text(encoding="utf-8"))
        self.assertNotIn("ask_gemini(", BRAIN_SOURCE)
        self.assertNotIn("target.timeout(", BRAIN_SOURCE)


if __name__ == "__main__":
    unittest.main()
