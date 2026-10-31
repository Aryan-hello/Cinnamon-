"""Behavior tests of snapshot commit boundaries without services or credentials."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from cinnamon_modules.brain_storage import (
    SnapshotStore, StorageRejected, StorageUncertain, UpstashSnapshotBackend,
    LocalSnapshotBackend, validate_snapshot, describe_action_storage_blocker,
)


class Backend:
    durable = True
    def __init__(self, raw=None):
        self.raw = raw
        self.writes = 0
        self.fail_read = False
        self.mode = "ok"
    async def read(self):
        if self.fail_read:
            raise StorageRejected("network unavailable")
        return self.raw
    async def compare_and_set(self, expected, candidate):
        self.writes += 1
        if self.mode == "rejected":
            raise StorageRejected("HTTP 403")
        if self.mode == "lost-before":
            raise StorageUncertain("timeout")
        if self.raw != expected:
            return False
        self.raw = candidate
        if self.mode == "lost-after":
            raise StorageUncertain("timeout")
        return True


class ActionStorageDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_blocker_identifies_real_required_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            local = SnapshotStore(
                LocalSnapshotBackend(str(Path(directory) / "bot.json")))
            loaded = await local.load()
            self.assertTrue(loaded)
            text = describe_action_storage_blocker(local)
            self.assertIn("local JSON file", text)
            self.assertIn("UPSTASH_REDIS_REST_URL", text)
            self.assertIn("UPSTASH_REDIS_REST_TOKEN", text)
            self.assertIn("Back up", text)
            self.assertIsNone(
                describe_action_storage_blocker(local, allow_local=True))

    async def test_incomplete_upstash_is_secret_free(self):
        storage = SnapshotStore(
            UpstashSnapshotBackend("https://secret.invalid", "", "cinnamon_bot_data"))
        text = describe_action_storage_blocker(storage)
        self.assertIn("partly configured", text)
        self.assertNotIn("secret.invalid", text)

    async def test_ready_remote_store_has_no_reason_to_block(self):
        storage = SnapshotStore(Backend())
        self.assertTrue(await storage.load())
        self.assertIsNone(describe_action_storage_blocker(storage))

    async def test_failed_snapshot_load_is_not_treated_as_available(self):
        storage = SnapshotStore(Backend())
        storage.disable("Stored snapshot could not be validated")
        text = describe_action_storage_blocker(storage)
        self.assertIn("safely load", text)
        self.assertIn("/datastatus check", text)

    async def test_conflict_and_uncertain_storage_are_explained(self):
        storage = SnapshotStore(Backend())
        self.assertTrue(await storage.load())
        storage.status = "uncertain"
        self.assertIn("unresolved outcome", describe_action_storage_blocker(storage))
        storage.status = "conflict"
        self.assertIn("conflicting", describe_action_storage_blocker(storage))


class SnapshotStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_store_refuses_writes_until_successfully_loaded(self):
        backend = Backend()
        store = SnapshotStore(backend)
        async with store.lock:
            result = await store.commit_locked({"economy_balances": {"1:2": 20}})
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(backend.writes, 0)
        self.assertTrue(await store.load())  # Missing is distinct from unreadable.
        async with store.lock:
            self.assertTrue(await store.commit_locked({"economy_balances": {"1:2": 20}}))
        self.assertEqual(json.loads(backend.raw)["economy_balances"]["1:2"], 20)

    async def test_invalid_or_unreadable_loaded_data_never_becomes_fresh_defaults(self):
        for raw in ('broken', '[]', '{"economy_balances":{"bad:key":10}}',
                    '{"reaction_role_ids":[[]]}', '{"xp_channels":{"1":null}}'):
            backend = Backend(raw)
            store = SnapshotStore(backend)
            self.assertFalse(await store.load())
            async with store.lock:
                self.assertFalse(await store.commit_locked({}))
            self.assertEqual(backend.raw, raw)
            self.assertEqual(backend.writes, 0)
        backend = Backend()
        backend.fail_read = True
        store = SnapshotStore(backend)
        self.assertFalse(await store.load())
        backend.fail_read = False
        async with store.lock:
            self.assertFalse(await store.commit_locked({}))
        self.assertEqual(backend.writes, 0)

    async def test_rejected_write_is_definite_and_can_be_retried(self):
        backend = Backend()
        store = SnapshotStore(backend)
        await store.load()
        backend.mode = "rejected"
        async with store.lock:
            self.assertEqual((await store.commit_locked({})).status, "failed")
        self.assertTrue(store.ready)
        backend.mode = "ok"
        async with store.lock:
            self.assertTrue(await store.commit_locked({}))

    async def test_uncertain_write_has_barrier_until_receipt_can_publish(self):
        backend = Backend()
        store = SnapshotStore(backend)
        await store.load()
        backend.mode = "lost-after"
        async with store.lock:
            result = await store.commit_locked({"advanced_features": {"receipt": "applied"}}, receipt_id="17")
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(store.pending_receipt, "17")
        backend.mode = "ok"
        async with store.lock:
            self.assertEqual((await store.commit_locked({})).status, "uncertain")
        self.assertEqual(backend.writes, 1)
        callbacks = []
        store.on_reconcile = callbacks.append
        async with store.lock:
            resolved = await store.reconcile_locked()
            self.assertTrue(resolved)
            self.assertTrue(await store.commit_locked({"advanced_features": {"receipt": "applied"}}))
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0].receipt_id, "17")
        self.assertEqual(callbacks[0].snapshot["advanced_features"]["receipt"], "applied")
        self.assertIsNone(store.pending_receipt)

    async def test_unwritten_uncertain_candidate_is_resolved_as_failed_once(self):
        backend = Backend('{"economy_balances":{"1:2":10}}')
        store = SnapshotStore(backend)
        await store.load()
        backend.mode = "lost-before"
        async with store.lock:
            self.assertEqual((await store.commit_locked({"economy_balances":{"1:2":20}}, receipt_id="21")).status, "uncertain")
        calls = []
        store.on_reconcile = calls.append
        backend.mode = "ok"
        async with store.lock:
            result = await store.reconcile_locked()
            self.assertEqual(result.status, "failed")
            self.assertTrue(await store.ensure_ready_locked())
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].status, "failed")
        self.assertTrue(store.ready)

    async def test_repeated_fence_acknowledgement_failure_keeps_one_candidate(self):
        backend = Backend()
        store = SnapshotStore(backend)
        await store.load()
        backend.mode = "lost-before"
        async with store.lock:
            await store.commit_locked({"economy_balances":{"1:2":10}}, receipt_id="offline")
        store.on_reconcile = lambda result: None
        for _ in range(12):
            async with store.lock:
                self.assertEqual((await store.reconcile_locked()).status, "uncertain")
        self.assertEqual(len(store._pending_fences), 1)
        self.assertFalse(store.ready)

    async def test_unreadable_reconciliation_never_retries_write(self):
        backend = Backend()
        store = SnapshotStore(backend)
        await store.load()
        backend.mode = "lost-after"
        async with store.lock:
            await store.commit_locked({})
        backend.fail_read = True
        async with store.lock:
            self.assertEqual((await store.commit_locked({"xp_data":{}})).status, "uncertain")
        self.assertEqual(backend.writes, 1)

    async def test_competing_worker_causes_conflict_without_overwrite(self):
        backend = Backend()
        one, two = SnapshotStore(backend), SnapshotStore(backend)
        await one.load(); await two.load()
        async with one.lock:
            self.assertTrue(await one.commit_locked({"economy_balances":{"1:2":10}}))
        async with two.lock:
            self.assertEqual((await two.commit_locked({"economy_balances":{"1:2":100}})).status, "conflict")
            self.assertEqual((await two.commit_locked({})).status, "conflict")
        self.assertEqual(json.loads(backend.raw)["economy_balances"]["1:2"], 10)

    async def test_cancelled_inflight_write_establishes_reconciliation_barrier(self):
        backend = Backend()
        store = SnapshotStore(backend)
        await store.load()
        entered, release = asyncio.Event(), asyncio.Event()
        async def write(expected, raw):
            entered.set()
            await release.wait()
            if backend.raw != expected:
                return False
            backend.raw = raw
            return True
        backend.compare_and_set = write
        async def commit():
            async with store.lock:
                await store.commit_locked({"economy_balances":{"1:2":10}}, receipt_id="cancelled")
        task = asyncio.create_task(commit())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(store.status, "uncertain")
        self.assertEqual(store.pending_receipt, "cancelled")
        resolved = []
        store.on_reconcile = resolved.append
        async with store.lock:
            self.assertEqual((await store.reconcile_locked()).status, "uncertain")
        self.assertEqual(resolved, [])
        release.set()
        await store._pending_write_task
        async with store.lock:
            self.assertTrue(await store.reconcile_locked())
        self.assertEqual(len(resolved), 1)

    async def test_fence_prevents_late_timed_out_write_from_adding_currency(self):
        backend = Backend('{"economy_balances":{"1:2":10}}')
        store = SnapshotStore(backend)
        await store.load()
        old_raw = backend.raw
        backend.mode = "lost-before"
        candidate = {"economy_balances":{"1:2":20}}
        async with store.lock:
            await store.commit_locked(candidate, receipt_id="late")
        late_candidate = store._pending[1]
        backend.mode = "ok"
        seen = []
        store.on_reconcile = seen.append
        async with store.lock:
            result = await store.reconcile_locked()
        self.assertEqual(result.status, "failed")
        # Even if the timed-out server request arrives after reconciliation,
        # its original expected raw value no longer matches the fenced snapshot.
        self.assertFalse(await backend.compare_and_set(old_raw, late_candidate))
        self.assertEqual(json.loads(backend.raw)["economy_balances"]["1:2"], 10)
        self.assertEqual(len(seen), 1)

    async def test_snapshot_is_frozen_before_awaiting_backend(self):
        backend = Backend()
        store = SnapshotStore(backend)
        await store.load()
        entered, release = asyncio.Event(), asyncio.Event()
        original = backend.compare_and_set
        async def write(expected, raw):
            entered.set()
            await release.wait()
            return await original(expected, raw)
        backend.compare_and_set = write
        source = {"advanced_features":{"value":1}}
        async def commit():
            async with store.lock:
                return await store.commit_locked(source)
        task = asyncio.create_task(commit())
        await entered.wait()
        source["advanced_features"]["value"] = 2
        release.set()
        result = await task
        self.assertEqual(result.snapshot["advanced_features"]["value"], 1)
        self.assertEqual(json.loads(backend.raw)["advanced_features"]["value"], 1)

    async def test_local_corrupt_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/"bot.json"
            file.write_text("corrupt")
            store = SnapshotStore(LocalSnapshotBackend(str(file)))
            self.assertFalse(store.durable)
            self.assertFalse(await store.load())
            async with store.lock:
                self.assertFalse(await store.commit_locked({}))
            self.assertEqual(file.read_text(), "corrupt")


class UpstashWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_incomplete_upstash_configuration_fails_closed(self):
        for url, token in (("https://example.invalid", ""), ("", "redacted")):
            backend = UpstashSnapshotBackend(url, token, "bot")
            with self.assertRaises(StorageRejected):
                await backend.read()

    async def test_atomic_cas_uses_one_script_with_expected_and_replacement(self):
        backend = UpstashSnapshotBackend("https://example.invalid", "redacted", "bot")
        calls = []
        async def command(value, *, writing=False):
            calls.append((value, writing))
            return 1
        backend._command = command
        self.assertTrue(await backend.compare_and_set(None, '{"value":1}'))
        self.assertTrue(await backend.compare_and_set('{"value":1}', '{"value":2}'))
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(command[0][0] == "EVAL" and command[1] for command in calls))
        self.assertEqual(calls[0][0][2:], [1, "bot", "missing", "", '{"value":1}'])
        self.assertEqual(calls[1][0][4:], ["present", '{"value":1}', '{"value":2}'])

    async def test_malformed_http_success_is_uncertain_but_redis_error_is_definite(self):
        class Response:
            status = 200
            def __init__(self, payload):
                self.payload = payload
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def raise_for_status(self): pass
            async def json(self): return self.payload
        class Session:
            def __init__(self, payload): self.payload = payload
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def post(self, *args, **kwargs): return Response(self.payload)
        for payload in (None, {}, [], {"unrelated":"value"}):
            backend = UpstashSnapshotBackend("https://example.invalid", "redacted", "bot",
                        session_factory=lambda: Session(payload))
            with self.assertRaises(StorageUncertain):
                await backend.compare_and_set(None, "{}")
        backend = UpstashSnapshotBackend("https://example.invalid", "redacted", "bot",
                    session_factory=lambda: Session({"error":"forbidden"}))
        with self.assertRaises(StorageRejected):
            await backend.compare_and_set(None, "{}")

    async def test_bad_write_acknowledgement_is_uncertain(self):
        backend = UpstashSnapshotBackend("https://example.invalid", "redacted", "bot")
        async def command(*args, **kwargs):
            return "OK"
        backend._command = command
        with self.assertRaises(StorageUncertain):
            await backend.compare_and_set(None, "{}")


if __name__ == "__main__":
    unittest.main()
