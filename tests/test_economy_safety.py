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

    async def test_achievement_reward_rolls_back_when_snapshot_is_not_saved(self):
        state = {"stats": {}, "unlocked": [], "secret_unlocked": [], "points": 0, "showcase": []}
        states = {(1, 7): state}
        balances = {(1, 7): 20}
        xp = {(1, 7): 5}

        async def failed_save():
            return False

        async def noop(*args, **kwargs):
            return None

        namespace = {
            "_ach_copy": copy,
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
        self.assertEqual(states[(1, 7)], state)
        self.assertEqual(balances[(1, 7)], 20)
        self.assertEqual(xp[(1, 7)], 5)


if __name__ == "__main__":
    unittest.main()
