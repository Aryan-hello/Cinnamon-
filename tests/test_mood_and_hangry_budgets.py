"""Offline mood pricing and Hangry Games persistence tests, without Discord login."""
import ast
import asyncio
import hashlib
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


BASE = Path(__file__).resolve().parents[1] / "cinnamon_modules"


def extract(path, names, ns):
    tree = ast.parse((BASE / path).read_text(encoding="utf-8"))
    selected = [node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in names]
    exec(compile(ast.Module(body=selected, type_ignores=[]), path, "exec"), ns)
    return ns


class MoodRulesTests(unittest.TestCase):
    def setup_mood(self):
        ns = {"advanced_features_data": {}, "time": time,
              "_cm_hashlib": hashlib, "random": __import__("random")}
        return extract("cinnamon_moods.py", {
            "_cm_root", "_cm_state", "_cm_member", "_cm_tier",
            "_cm_adjust", "_cm_naughty", "_cm_price", "_cm_fishing_bonus",
        }, ns)

    def test_base_discount_surcharge_and_naughty_expiry(self):
        ns = self.setup_mood()
        price = ns["_cm_price"]
        self.assertEqual(price(1, 10, "tuna", 1000), 1000)
        self.assertEqual(ns["_cm_fishing_bonus"](1), 0)
        ns["_cm_adjust"](1, 60)
        self.assertIn(price(1, 10, "tuna", 1000), {750, 900})
        self.assertEqual(price(1, 10, "tuna", 1000), price(1, 10, "tuna", 1000))
        self.assertEqual(ns["_cm_fishing_bonus"](1), 1)
        ns["_cm_adjust"](1, -120)
        self.assertEqual(price(1, 10, "tuna", 1000), 1200)
        self.assertLess(ns["_cm_fishing_bonus"](1), 0)
        ns["_cm_member"](1, 10)["naughty_until"] = time.time() + 1800
        self.assertEqual(price(1, 10, "tuna", 1000), 2200)
        ns["_cm_member"](1, 10)["naughty_until"] = time.time() - 1
        self.assertEqual(price(1, 10, "tuna", 1000), 1200)
        self.assertEqual(price(1, 10, "freebie", 0), 0)

    def test_mood_recovers_toward_normal_after_inactivity(self):
        ns = self.setup_mood()
        ns["_cm_adjust"](3, -60)
        state = ns["_cm_state"](3)
        state["updated"] -= 12 * 1800
        self.assertEqual(ns["_cm_tier"](3), "normal")
        self.assertGreaterEqual(state["score"], 0)


class HangryGameBudgetTests(unittest.TestCase):
    def test_legacy_saved_stats_remain_compatible(self):
        ns = extract("hangry_games.py", {"_hg_decode", "_hg_encode"}, {})
        legacy = {"game_counts": {"1": 22},
                  "win_counts": {"1:10": 4},
                  "kill_counts": {},
                  "played_counts": {},
                  "log_channels": {"1": 42},
                  "log_enabled": {"1": True}}
        decoded = ns["_hg_decode"](legacy)
        self.assertEqual(decoded["game_counts"][1], 22)
        self.assertEqual(decoded["budget_records"], {})
        decoded["budget_records"][(1, 10)] = {"week": "2026-W44", "spent": 12000}
        decoded["host_records"][(1, 10)] = {"week": "2026-W44", "completed": 5, "bonus": 500}
        encoded = ns["_hg_encode"](decoded)
        decoded_again = ns["_hg_decode"](encoded)
        self.assertEqual(decoded_again["win_counts"][(1, 10)], 4)
        self.assertEqual(decoded_again["budget_records"][(1, 10)]["spent"], 12000)
        self.assertEqual(decoded_again["host_records"][(1, 10)]["completed"], 5)

    def test_budget_permissions_and_lobby_signatures(self):
        source = (BASE / "hangry_games.py").read_text()
        tree = ast.parse(source)
        cog = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "HangryGamesCog")
        method = next(n for n in cog.body if isinstance(n, ast.FunctionDef) and n.name == "_budget_limit")
        ns = {"staticmethod": staticmethod}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "budget", "exec"), ns)
        limit = ns["_budget_limit"]
        def member(**perms):
            p = dict(administrator=False, moderate_members=False, manage_messages=False)
            p.update(perms)
            return SimpleNamespace(guild_permissions=SimpleNamespace(**p))
        self.assertEqual(limit(member(manage_messages=True)), 20000)
        self.assertEqual(limit(member(moderate_members=True, manage_messages=True)), 30000)
        self.assertIsNone(limit(member(administrator=True)))
        self.assertEqual(limit(member()), 0)


if __name__ == "__main__":
    unittest.main()
