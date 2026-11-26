"""Regression tests for cancellation-safe locks and durable progression rewards."""
import ast
import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def extract_function(path, name, namespace):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


class EconomySafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_market_lock_cancellation_releases_only_locks_acquired_here(self):
        namespace = {"asyncio": asyncio}
        acquire = extract_function(ROOT / "cinnamon_modules/economy_marketplace.py", "_market_acquire", namespace)
        release = extract_function(ROOT / "cinnamon_modules/economy_marketplace.py", "_market_release", namespace)

        first = asyncio.Lock()
        second = asyncio.Lock()
        await second.acquire()
        locks = [first, second]
        task = asyncio.create_task(acquire(locks))
        while not first.locked():
            await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertFalse(first.locked())
        self.assertTrue(second.locked())
        release(locks)
        self.assertTrue(second.locked())
        second.release()

    async def test_level_reward_claim_rolls_back_and_can_retry_after_storage_failure(self):
        balances = {(1, 7): 20}
        claims = {}
        save_state = {"ok": False}

        async def save():
            if not save_state["ok"]:
                raise OSError("storage unavailable")
            return True

        namespace = {
            "asyncio": asyncio,
            "_CINNAMON_SHOP_LOCKS": {},
            "ECONOMY_LEVEL_REWARDS": {2: 100, 5: 300},
            "economy_level_rewards_claimed": claims,
            "economy_balances": balances,
            "economy_balance": lambda guild_id, user_id: balances.get((int(guild_id), int(user_id)), 1000),
            "economy_level_reward_claimed": lambda guild_id, user_id, level: int(level) in claims.get((int(guild_id), int(user_id)), []),
            "mark_economy_level_reward_claimed": lambda guild_id, user_id, level: claims.setdefault((int(guild_id), int(user_id)), []).append(int(level)),
            "bd_save_data": save,
        }
        claim = extract_function(ROOT / "cinnamon_modules/levels_games.py", "_claim_level_rewards", namespace)
        failed = await claim(1, 7, 5)
        self.assertEqual(failed, (0, []))
        self.assertEqual(balances[(1, 7)], 20)
        self.assertEqual(claims, {})

        save_state["ok"] = True
        success = await claim(1, 7, 5)
        self.assertEqual(success, (400, [2, 5]))
        self.assertEqual(balances[(1, 7)], 420)
        self.assertEqual(set(claims[(1, 7)]), {2, 5})

    async def test_concurrent_level_reward_claims_pay_only_once(self):
        balances = {(1, 7): 20}
        claims = {}

        async def save():
            await asyncio.sleep(0)
            return True

        namespace = {
            "asyncio": asyncio,
            "_CINNAMON_SHOP_LOCKS": {},
            "ECONOMY_LEVEL_REWARDS": {2: 100},
            "economy_level_rewards_claimed": claims,
            "economy_balances": balances,
            "economy_balance": lambda guild_id, user_id: balances.get((int(guild_id), int(user_id)), 1000),
            "economy_level_reward_claimed": lambda guild_id, user_id, level: int(level) in claims.get((int(guild_id), int(user_id)), []),
            "mark_economy_level_reward_claimed": lambda guild_id, user_id, level: claims.setdefault((int(guild_id), int(user_id)), []).append(int(level)),
            "bd_save_data": save,
        }
        claim = extract_function(ROOT / "cinnamon_modules/levels_games.py", "_claim_level_rewards", namespace)
        results = await asyncio.gather(claim(1, 7, 2), claim(1, 7, 2))
        self.assertEqual(sorted(result[0] for result in results), [0, 100])
        self.assertEqual(balances[(1, 7)], 120)
        self.assertEqual(claims[(1, 7)], [2])

    async def test_market_transaction_rolls_back_when_storage_raises(self):
        balances = {(1, 7): 900}
        inventory = {7: {"tuna": 2}}
        records = {"listing": {"status": "active"}}

        async def broken_save():
            raise OSError("storage unavailable")

        namespace = {
            "bd_save_data": broken_save,
            "economy_balances": balances,
            "economy_inventory_for": lambda guild_id, user_id: inventory.setdefault(int(user_id), {}),
            "log": SimpleNamespace(exception=lambda *args, **kwargs: None),
        }
        persist = extract_function(
            ROOT / "cinnamon_modules/economy_marketplace.py",
            "_market_persist_or_rollback",
            namespace,
        )
        inventory[7]["tuna"] = 0
        balances[(1, 7)] = 100
        records["listing"]["status"] = "sold"
        saved = await persist(
            1,
            {7: (900, {"tuna": 2})},
            records,
            {"listing": {"status": "active"}},
        )

        self.assertFalse(saved)
        self.assertEqual(balances[(1, 7)], 900)
        self.assertEqual(inventory[7], {"tuna": 2})
        self.assertEqual(records["listing"]["status"], "active")

    async def test_repair_rod_rolls_back_inventory_and_state_when_save_fails(self):
        inventory = {"fishing_line": 1}
        player = {"rod_broken": True}

        async def failed_save():
            return False

        namespace = {
            "asyncio": asyncio,
            "_CINNAMON_SHOP_LOCKS": {},
            "economy_inventory_for": lambda guild_id, user_id: inventory,
            "_wlf_player": lambda guild_id, user_id: player,
            "bd_save_data": failed_save,
        }
        craft = extract_function(ROOT / "cinnamon_modules/advanced_economy.py", "craft_item", namespace)
        ok, message = await craft(1, SimpleNamespace(id=7), "repair_rod", 1)

        self.assertFalse(ok)
        self.assertIn("could not save", message.lower())
        self.assertEqual(inventory, {"fishing_line": 1})
        self.assertEqual(player, {"rod_broken": True})


    async def test_generic_craft_rolls_back_when_storage_raises(self):
        inventory = {"wood": 3, "stone": 2}
        crafted = {}

        async def broken_save():
            raise OSError("storage unavailable")

        namespace = {
            "asyncio": asyncio,
            "_CINNAMON_SHOP_LOCKS": {},
            "economy_inventory_for": lambda guild_id, user_id: inventory,
            "CRAFTING_RECIPES": {"test": {"ingredients": {"wood": 2, "stone": 1}, "output": "plank", "name": "Test Plank"}},
            "ECONOMY_ITEMS": {"plank": {"name": "Plank", "emoji": "🪵", "max_per_person": 0}},
            "ADVANCED_FEATURES": {"crafted_counts": crafted},
            "_af_key": lambda guild_id, user_id: f"{guild_id}:{user_id}",
            "bd_save_data": broken_save,
        }
        craft = extract_function(ROOT / "cinnamon_modules/advanced_economy.py", "craft_item", namespace)
        ok, message = await craft(1, SimpleNamespace(id=7), "test", 1)
        self.assertFalse(ok)
        self.assertIn("restored", message.lower())
        self.assertEqual(inventory, {"wood": 3, "stone": 2})
        self.assertEqual(crafted, {})

    async def test_achievement_reward_rolls_back_when_snapshot_is_not_saved(self):
        state = {"stats": {}, "unlocked": [], "secret_unlocked": [], "points": 0, "showcase": []}
        expected_state = copy.deepcopy(state)
        states = {(1, 7): state}
        balances = {(1, 7): 20}
        xp = {(1, 7): 5}

        async def failed_save():
            return False

        async def noop(*args, **kwargs):
            return None

        namespace = {
            "_ach_copy": copy,
            "asyncio": asyncio,
            "_CINNAMON_SHOP_LOCKS": {},
            "SECRET_ACHIEVEMENTS": {},
            "ACHIEVEMENTS": {"first": {"catnip": 100, "xp": 50, "points": 2}},
            "_state": lambda guild_id, user_id: states.setdefault((int(guild_id), int(user_id)), {}),
            "_key": lambda guild_id, user_id: (int(guild_id), int(user_id)),
            "_achievement_guard": set(),
            "achievement_data": states,
            "economy_balances": balances,
            "economy_balance": lambda guild_id, user_id: balances.get((int(guild_id), int(user_id)), 0),
            "xp_data": xp,
            "bd_save_data": failed_save,
            "achievement_log": noop,
            "_assign_role": noop,
            "bot": SimpleNamespace(get_guild=lambda guild_id: None),
            "sync_level_roles": noop,
            "level_from_xp": lambda value: value,
        }
        unlock = extract_function(ROOT / "cinnamon_modules/achievements.py", "_unlock", namespace)
        ok = await unlock(1, 7, "first")

        self.assertFalse(ok)
        self.assertEqual(states[(1, 7)], expected_state)
        self.assertEqual(balances[(1, 7)], 20)
        self.assertEqual(xp[(1, 7)], 5)


    async def test_concurrent_appeal_decisions_allow_only_one_winner(self):
        from datetime import datetime, timezone

        cfg = {"appeals": {"abc12345": {"user_id": 7, "status": "pending"}}}

        async def saved():
            await asyncio.sleep(0)
            return True

        namespace = {
            "_MC_LOCKS": {},
            "asyncio": asyncio,
            "_mc_root": lambda guild_id: cfg,
            "_mc_copy": copy,
            "_mc_time": SimpleNamespace(time=lambda: 1234),
            "bd_save_data": saved,
        }
        decide = extract_function(
            ROOT / "cinnamon_modules/moderation_controls.py",
            "_mc_decide_appeal",
            namespace,
        )
        results = await asyncio.gather(
            decide(1, "abc12345", "approved", 10),
            decide(1, "abc12345", "declined", 11),
        )

        self.assertEqual(sorted(result[0] for result in results), ["not_pending", "ok"])
        self.assertIn(cfg["appeals"]["abc12345"]["status"], {"approved", "declined"})
        self.assertIn(cfg["appeals"]["abc12345"]["reviewed_by"], {10, 11})

    async def test_season_xp_is_scoped_by_month_and_bounded_to_twelve_months(self):
        from datetime import datetime, timezone

        current = [datetime(2026, 11, 26, tzinfo=timezone.utc)]
        data = {}
        namespace = {
            "cinnamon_now": lambda: current[0],
            "advanced_features_data": data,
        }
        record = extract_function(
            ROOT / "cinnamon_modules/levels_games.py",
            "_record_season_xp",
            namespace,
        )
        record(1, 7, 20)
        record(1, 7, 30)
        self.assertEqual(data["leaderboard_seasons_v1"]["2026-11"]["1"]["7"], 50)

        for month in range(1, 14):
            current[0] = datetime(2025 + (month - 1) // 12, ((month - 1) % 12) + 1, 1, tzinfo=timezone.utc)
            record(1, 7, 1)
        self.assertLessEqual(len(data["leaderboard_seasons_v1"]), 12)

    def test_xp_anti_abuse_filters_bots_webhooks_and_prefix_commands(self):
        source = (ROOT / "cinnamon_modules/levels_games.py").read_text(encoding="utf-8")
        self.assertIn("message.author.bot", source)
        self.assertIn('getattr(message, "webhook_id", None)', source)
        self.assertIn('content.startswith("?")', source)
        self.assertIn("XP_COOLDOWN_SECONDS = 30", source)

    def test_temporary_role_mutations_share_a_guild_lock(self):
        source = (ROOT / "cinnamon_modules/general_moderation.py").read_text(encoding="utf-8")
        self.assertIn("_TEMP_ROLE_LOCKS", source)
        self.assertIn("@_temp_role_serialized", source)
        self.assertIn("async with lock:", source)


if __name__ == "__main__":
    unittest.main()
