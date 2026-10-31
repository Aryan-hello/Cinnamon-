"""Offline behavior regressions for settings and economy persistence.

Extract the real helpers to avoid importing main.py, opening a web server, or
requiring Discord credentials. Snapshots pass through JSON just as storage does.
"""
import ast
import asyncio
from collections import defaultdict
import copy
import json
import math
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cinnamon_modules.brain_storage import (
    SnapshotStore, LocalSnapshotBackend, StorageRejected, StorageUncertain, validate_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]


def persistence_runtime():
    main = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    defaults = next(
        ast.literal_eval(node.value)
        for node in main.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "ECONOMY_ITEMS"
                for target in node.targets)
    )
    ns = {"defaultdict": defaultdict, "advanced_features_data": {},
          "ai_channels": {}, "disabled_channels": defaultdict(set),
          "log_channels": {}, "category_log_channels": {},
          "ECONOMY_ITEMS": copy.deepcopy(defaults), "math": math,
          "time": SimpleNamespace(time=lambda: 1000),
          "asyncio": asyncio, "json": json, "os": os,
          "_bd_validate_snapshot": validate_snapshot,
          "BD_UPSTASH_URL": None, "BD_UPSTASH_TOKEN": None,
          "BD_REDIS_KEY": "test_bot_data", "log": Mock()}
    for filename, wanted in (
        ("dashboard_runtime.py", {"_bd_encode", "_bd_decode", "bd_save_data", "bd_load_data"}),
        ("economy.py", {"economy_cooldown_remaining"}),
    ):
        tree = ast.parse((ROOT / "cinnamon_modules" / filename).read_text(encoding="utf-8"))
        functions = [node for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and node.name in wanted]
        exec(compile(ast.Module(body=functions, type_ignores=[]), filename, "exec"), ns)
    ns["_bd_decode"]({})
    return ns


def restart(source):
    snapshot = json.loads(json.dumps(source["_bd_encode"]()))
    restored = persistence_runtime()
    restored["_bd_decode"](snapshot)
    return restored


class PersistenceBehaviorTests(unittest.TestCase):
    def test_channel_settings_and_log_routes_survive_restart_for_each_guild(self):
        ns = persistence_runtime()
        ns["ai_channels"].update({11: 101, 22: 202})
        ns["disabled_channels"].update({11: {103, 104}, 22: {203}})
        ns["log_channels"].update({11: 105, 22: 205})
        ns["category_log_channels"].update({
            11: {"economy": 106, "moderation": 107},
            22: {"economy": 206, "ai": 207},
        })

        restored = restart(ns)

        for name in ("ai_channels", "disabled_channels", "log_channels",
                     "category_log_channels"):
            self.assertEqual(restored[name], ns[name], name)
        # New guilds must retain the set-valued default used by /disableai.
        restored["disabled_channels"][33].add(303)
        self.assertEqual(restored["disabled_channels"][33], {303})

    def test_role_income_and_recipient_transfer_cooldowns_survive_restart(self):
        ns = persistence_runtime()
        ns["economy_cooldowns"].update({
            (11, 42, "daily"): 2000,
            (11, 42, "income:12345"): 2100,
            (11, 42, "give:67890"): 2200,
            (22, 42, "income:12345"): 2300,
        })

        restored = restart(ns)

        self.assertEqual(restored["economy_cooldowns"], ns["economy_cooldowns"])
        remaining = restored["economy_cooldown_remaining"]
        self.assertEqual(remaining(11, 42, "daily"), 1000)
        self.assertEqual(remaining(11, 42, "income:12345"), 1100)
        self.assertEqual(remaining(11, 42, "give:67890"), 1200)
        self.assertEqual(remaining(22, 42, "income:12345"), 1300)

    def test_catalog_preserves_custom_items_edits_and_removals(self):
        ns = persistence_runtime()
        del ns["ECONOMY_ITEMS"]["tuna"]
        ns["ECONOMY_ITEMS"]["treat"].update({"price": 3500, "shop_enabled": False})
        ns["ECONOMY_ITEMS"]["fancy_box"] = {
            "name": "Fancy Box", "price": 4500, "emoji": "📦",
            "description": "A very important box.", "max_per_person": 2,
        }
        ns["economy_balances"][(11, 42)] = 8000
        ns["economy_inventory"][(11, 42)] = {"fancy_box": 1}

        restored = restart(ns)

        self.assertEqual(restored["ECONOMY_ITEMS"], ns["ECONOMY_ITEMS"])
        self.assertNotIn("tuna", restored["ECONOMY_ITEMS"])
        self.assertEqual(restored["economy_inventory"], ns["economy_inventory"])
        self.assertEqual(restored["economy_balances"], ns["economy_balances"])

    def test_saved_empty_catalog_stays_empty_and_shared_reference_is_preserved(self):
        ns = persistence_runtime()
        catalog = ns["ECONOMY_ITEMS"]

        ns["_bd_decode"]({"economy_items": {}})

        self.assertIs(ns["ECONOMY_ITEMS"], catalog)
        self.assertEqual(catalog, {})
        self.assertEqual(restart(ns)["ECONOMY_ITEMS"], {})

    def test_saved_prices_below_default_floors_survive_restart(self):
        ns = persistence_runtime()
        ns["ECONOMY_ITEMS"]["fish"]["price"] = 1000
        ns["ECONOMY_ITEMS"]["small_box"] = {
            "name": "Small Box", "price": 50, "emoji": "📦",
            "description": "A small box.", "max_per_person": 0,
        }

        restored = restart(ns)

        self.assertEqual(restored["ECONOMY_ITEMS"], ns["ECONOMY_ITEMS"])
        self.assertEqual(restored["ECONOMY_ITEMS"]["fish"]["price"], 1000)
        self.assertEqual(restored["ECONOMY_ITEMS"]["small_box"]["price"], 50)

    def test_legacy_snapshots_keep_defaults_and_shop_price_migration(self):
        ns = persistence_runtime()
        catalog = copy.deepcopy(ns["ECONOMY_ITEMS"])

        ns["_bd_decode"]({"economy_balances": {"11:42": 5000}})

        self.assertEqual(ns["ECONOMY_ITEMS"], catalog)
        self.assertEqual(ns["economy_balances"][(11, 42)], 5000)
        for name in ("ai_channels", "disabled_channels", "log_channels",
                     "category_log_channels"):
            self.assertEqual(ns[name], {}, name)
        ns["ECONOMY_ITEMS"]["tuna"]["price"] = 10
        ns["ECONOMY_ITEMS"]["legacy_custom"] = {"name": "Legacy item", "price": 50}
        ns["_bd_decode"]({})
        self.assertEqual(ns["ECONOMY_ITEMS"]["tuna"]["price"], 1000)
        self.assertEqual(ns["ECONOMY_ITEMS"]["legacy_custom"]["price"], 1000)


class MemoryBackend:
    durable = True

    def __init__(self, raw=None):
        self.raw = raw
        self.writes = []
        self.failure = None
        self.read_failure = False
        self.enter = None

    async def read(self):
        if self.read_failure:
            raise StorageRejected("unavailable")
        return self.raw

    async def compare_and_set(self, expected, candidate):
        self.writes.append(candidate)
        if self.enter is not None:
            await self.enter()
        if self.failure:
            raise self.failure
        if self.raw != expected:
            return False
        self.raw = candidate
        return True


def storage_runtime(backend):
    ns = persistence_runtime()
    ns["bd_store"] = SnapshotStore(backend)
    return ns


class PersistenceWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_saves_wait_for_prior_write_and_capture_latest_state(self):
        first_started, release_first = asyncio.Event(), asyncio.Event()
        backend = MemoryBackend()
        async def enter():
            if len(backend.writes) == 1:
                first_started.set()
                await release_first.wait()
        backend.enter = enter
        ns = storage_runtime(backend)
        await ns["bd_load_data"]()
        ns["economy_balances"][(11, 42)] = 100
        first = asyncio.create_task(ns["bd_save_data"]())
        await asyncio.wait_for(first_started.wait(), 1)
        ns["economy_balances"][(11, 42)] = 200
        second = asyncio.create_task(ns["bd_save_data"]())
        await asyncio.sleep(0)
        self.assertEqual(len(backend.writes), 1)
        self.assertFalse(second.done())
        ns["economy_balances"][(11, 42)] = 300
        release_first.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), 1)
        self.assertTrue(all(results))
        self.assertEqual([json.loads(raw)["economy_balances"]["11:42"]
                          for raw in backend.writes], [100, 300])

    async def test_startup_read_failure_blocks_all_later_saves(self):
        backend = MemoryBackend('{"economy_balances":{"11:42":5000}}')
        backend.read_failure = True
        ns = storage_runtime(backend)
        ns["economy_balances"][(11, 42)] = 900
        self.assertFalse(await ns["bd_load_data"]())
        backend.read_failure = False
        self.assertFalse(await ns["bd_save_data"]())
        self.assertEqual(backend.writes, [])
        self.assertEqual(ns["economy_balances"][(11, 42)], 900)

    async def test_invalid_snapshot_does_not_partially_replace_live_state(self):
        ns = persistence_runtime()
        ns["economy_balances"][(11, 42)] = 5000
        ns["welcome_config"][11] = {"channel_id": 7}
        with self.assertRaises(ValueError):
            ns["_bd_decode"]({"welcome_config": {"22": {}},
                               "economy_balances": {"bad:key": 100}})
        self.assertEqual(ns["welcome_config"], {11: {"channel_id": 7}})
        self.assertEqual(ns["economy_balances"][(11, 42)], 5000)

    async def test_local_commit_is_atomic_and_survives_real_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "bot.json"
            ns = storage_runtime(LocalSnapshotBackend(str(destination)))
            await ns["bd_load_data"]()
            ns["economy_balances"][(11, 42)] = 5000
            self.assertTrue(await ns["bd_save_data"]())
            restored = storage_runtime(LocalSnapshotBackend(str(destination)))
            self.assertTrue(await restored["bd_load_data"]())
            self.assertEqual(restored["economy_balances"][(11, 42)], 5000)
            self.assertEqual(list(Path(directory).iterdir()), [destination])

    async def test_failed_local_replacement_preserves_last_good_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "bot.json"
            previous = '{"economy_balances":{"11:42":5000}}'
            destination.write_text(previous)
            ns = storage_runtime(LocalSnapshotBackend(str(destination)))
            await ns["bd_load_data"]()
            ns["economy_balances"][(11, 42)] = 8000
            with patch("cinnamon_modules.brain_storage.os.replace", side_effect=OSError("disk full")):
                result = await ns["bd_save_data"]()
            self.assertEqual(result.status, "failed")
            self.assertEqual(destination.read_text(), previous)
            self.assertEqual(list(Path(directory).iterdir()), [destination])

    async def test_reconciled_credit_is_published_before_queued_save_encodes(self):
        backend = MemoryBackend()
        ns = storage_runtime(backend)
        await ns["bd_load_data"]()
        ns["economy_balances"][(11, 42)] = 100
        candidate = ns["_bd_encode"]()
        candidate["economy_balances"]["11:42"] = 200
        # Simulate an acknowledged-lost action, then a legacy purchase.
        async def uncertain(expected, raw):
            backend.raw = raw
            raise StorageUncertain("ack lost")
        backend.compare_and_set = uncertain
        async with ns["bd_store"].lock:
            result = await ns["bd_store"].commit_locked(candidate, receipt_id="action")
        self.assertEqual(result.status, "uncertain")
        ns["economy_balances"][(11, 42)] -= 20
        def publish(result):
            self.assertEqual(result.receipt_id, "action")
            ns["economy_balances"][(11, 42)] += 100
        ns["bd_store"].on_reconcile = publish
        backend.compare_and_set = MemoryBackend.compare_and_set.__get__(backend)
        self.assertTrue(await ns["bd_save_data"]())
        self.assertEqual(json.loads(backend.raw)["economy_balances"]["11:42"], 180)


if __name__ == "__main__":
    unittest.main()
