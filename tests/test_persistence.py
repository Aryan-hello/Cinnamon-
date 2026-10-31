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
from unittest.mock import Mock


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
          "_bd_tempfile": tempfile, "_BD_SAVE_LOCK": asyncio.Lock(),
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


class FakeClientError(Exception):
    pass


class FakeResponse:
    def __init__(self, payload=None, *, http_error=None, json_error=None, enter=None):
        self.payload = payload
        self.http_error = http_error
        self.json_error = json_error
        self.enter = enter

    def __await__(self):
        # aiohttp's request context supports both `await session.post(...)`
        # and `async with session.post(...)`, including the baseline helper.
        return self.__aenter__().__await__()

    async def __aenter__(self):
        if self.enter is not None:
            await self.enter()
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        if self.http_error is not None:
            raise self.http_error

    async def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, post):
        self.post = post

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def remote_runtime(post):
    ns = persistence_runtime()
    ns.update({"BD_UPSTASH_URL": "https://storage.invalid",
               "BD_UPSTASH_TOKEN": "test-placeholder",
               "aiohttp": SimpleNamespace(
                   ClientError=FakeClientError,
                   ClientSession=lambda: FakeSession(post))})
    return ns


class PersistenceWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_saves_wait_for_prior_write_and_capture_latest_state(self):
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        requests = []
        stored = []

        def post(url, **kwargs):
            snapshot = json.loads(kwargs["json"][2])
            requests.append(snapshot)

            async def enter():
                if len(requests) == 1:
                    first_started.set()
                    await release_first.wait()
                stored.append(snapshot)

            return FakeResponse({"result": "OK"}, enter=enter)

        ns = remote_runtime(post)
        ns["economy_balances"][(11, 42)] = 100
        first = asyncio.create_task(ns["bd_save_data"]())
        await asyncio.wait_for(first_started.wait(), timeout=1)
        ns["economy_balances"][(11, 42)] = 200
        second = asyncio.create_task(ns["bd_save_data"]())
        await asyncio.sleep(0)
        try:
            self.assertEqual(len(requests), 1, "The second request must wait for the first write")
            self.assertFalse(second.done())
            # Waiting saves must encode after acquiring the lock, rather than
            # submit the stale 200-Catnip snapshot when they eventually run.
            ns["economy_balances"][(11, 42)] = 300
        finally:
            release_first.set()
            await asyncio.wait_for(asyncio.gather(first, second), timeout=1)
        self.assertEqual([item["economy_balances"]["11:42"] for item in stored], [100, 300])
        ns["log"].error.assert_not_called()

    async def test_http_redis_and_invalid_json_failures_are_logged_and_lock_released(self):
        responses = (
            FakeResponse(http_error=FakeClientError("HTTP 503")),
            FakeResponse({"error": "storage unavailable"}),
            FakeResponse(json_error=ValueError("invalid JSON")),
            FakeResponse({"result": "unexpected"}),
            FakeResponse(["unexpected response shape"]),
        )
        for response in responses:
            with self.subTest(response=response):
                pending = [response, FakeResponse({"result": "OK"})]
                ns = remote_runtime(lambda *args, **kwargs: pending.pop(0))
                await ns["bd_save_data"]()
                ns["log"].error.assert_called_once()
                self.assertFalse(ns["_BD_SAVE_LOCK"].locked())
                await ns["bd_save_data"]()
                self.assertEqual(pending, [])
                ns["log"].error.assert_called_once()

    async def test_local_save_replaces_complete_json_and_cleans_temporary_file(self):
        ns = persistence_runtime()
        ns["economy_balances"][(11, 42)] = 5000
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "bot.json"
            destination.write_text('{"previous": true}', encoding="utf-8")
            ns["BD_DATA_FILE"] = str(destination)

            def replace(source, target):
                self.assertEqual(json.loads(destination.read_text()), {"previous": True})
                self.assertEqual(json.loads(Path(source).read_text())["economy_balances"]["11:42"], 5000)
                self.assertEqual(Path(source).parent, destination.parent)
                os.replace(source, target)

            ns["os"] = SimpleNamespace(path=os.path, fsync=os.fsync,
                                        unlink=os.unlink, replace=Mock(side_effect=replace))
            await ns["bd_save_data"]()

            ns["os"].replace.assert_called_once()
            self.assertEqual(json.loads(destination.read_text())["economy_balances"]["11:42"], 5000)
            self.assertEqual(list(Path(directory).iterdir()), [destination])
            ns["log"].error.assert_not_called()

    async def test_failed_local_write_keeps_last_good_snapshot(self):
        for failure in ("serialize", "replace"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                ns = persistence_runtime()
                destination = Path(directory) / "bot.json"
                previous = '{"economy_balances": {"11:42": 5000}}'
                destination.write_text(previous, encoding="utf-8")
                ns["BD_DATA_FILE"] = str(destination)

                if failure == "serialize":
                    def fail_dump(value, stream):
                        stream.write('{"incomplete":')
                        raise OSError("disk full")
                    ns["json"] = SimpleNamespace(dump=fail_dump)
                else:
                    ns["os"] = SimpleNamespace(
                        path=os.path, fsync=os.fsync, unlink=os.unlink,
                        replace=Mock(side_effect=OSError("replace failed")))

                await ns["bd_save_data"]()

                self.assertEqual(destination.read_text(encoding="utf-8"), previous)
                self.assertEqual(list(Path(directory).iterdir()), [destination])
                ns["log"].error.assert_called_once()
                self.assertFalse(ns["_BD_SAVE_LOCK"].locked())

    async def test_remote_load_errors_leave_current_state_intact_and_are_logged(self):
        for response in (
            FakeResponse(http_error=FakeClientError("HTTP 503")),
            FakeResponse({"error": "storage unavailable"}),
            FakeResponse(json_error=ValueError("invalid JSON")),
        ):
            with self.subTest(response=response):
                ns = remote_runtime(lambda *args, **kwargs: response)
                ns["economy_balances"][(11, 42)] = 5000

                await ns["bd_load_data"]()

                self.assertEqual(ns["economy_balances"][(11, 42)], 5000)
                ns["log"].error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
