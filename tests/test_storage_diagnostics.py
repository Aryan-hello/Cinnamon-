"""Read-only transaction readiness diagnostics for Cinnamon's storage system.

Tests use fake Redis responses and local temporary paths: no real credentials,
Discord connection, Gemini request, or production data writes are needed.
"""
import ast
import asyncio
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_RUNTIME = ROOT / "cinnamon_modules" / "dashboard_runtime.py"
SERVER_SETUP = ROOT / "cinnamon_modules" / "server_setup.py"


class FakeUpstash:
    durable = True


class FakeLocal:
    durable = False


class FakeResponse:
    def __init__(self, *, status=200, payload=None):
        self.status = status
        self.payload = payload if payload is not None else {"result": "PONG"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.called = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def post(self, url, **kwargs):
        self.called.append((url, kwargs))
        return self.response


def make_runtime(*, upstash, url=None, token=None, ready=True,
                 status="ready", pending=None, file_path="/tmp/cinnamon-test.json",
                 remote_response=None):
    contents = DASHBOARD_RUNTIME.read_text(encoding="utf-8")
    parsed = ast.parse(contents)
    fn = next(node for node in parsed.body if isinstance(node, ast.AsyncFunctionDef)
              and node.name == "storage_status")
    session = FakeSession(remote_response)
    class FakeAiohttp:
        ClientError = OSError
        @staticmethod
        def ClientTimeout(**kwargs):
            return object()
        @staticmethod
        def ClientSession():
            return session

    store = types.SimpleNamespace(
        backend=FakeUpstash() if upstash else FakeLocal(),
        durable=upstash, ready=ready, status=status, pending_receipt=pending,
    )
    namespace = {
        "bd_store": store,
        "_BDUpstashBackend": FakeUpstash,
        "BD_UPSTASH_URL": url,
        "BD_UPSTASH_TOKEN": token,
        "BD_DATA_FILE": file_path,
        "aiohttp": FakeAiohttp,
        "os": os,
        "asyncio": asyncio,
    }
    exec(compile(ast.Module(body=[fn], type_ignores=[]),
                 str(DASHBOARD_RUNTIME), "exec"), namespace)
    return namespace["storage_status"], session


class StorageDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_json_does_not_claim_confirmed_catnip_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            local_file = Path(directory) / "never-create-just-to-test.json"
            diagnose, session = make_runtime(
                upstash=False, file_path=str(local_file))
            with patch.dict(os.environ, {"CINNAMON_ALLOW_LOCAL_ACTIONS": ""}):
                result = await diagnose()
            self.assertEqual(result["backend"], "Local JSON file")
            self.assertTrue(result["connected"])
            self.assertFalse(result["durable"])
            self.assertFalse(result["transactions_ready"])
            self.assertIn("Upstash", result["detail"])
            self.assertFalse(local_file.exists(), "A status check must not create data files")
            self.assertEqual(session.called, [])

    async def test_only_upstash_url_is_not_misreported_as_local(self):
        diagnose, session = make_runtime(
            upstash=True, url="https://redis.example.invalid", token=None)
        result = await diagnose()
        self.assertEqual(result["backend"], "Upstash Redis")
        self.assertEqual(result["upstash_configuration"], "REST token missing")
        self.assertFalse(result["connected"])
        self.assertFalse(result["transactions_ready"])
        self.assertEqual(session.called, [])

    async def test_only_upstash_token_is_not_misreported_as_local(self):
        diagnose, session = make_runtime(upstash=True, url=None, token="SECRET")
        result = await diagnose()
        self.assertEqual(result["upstash_configuration"], "REST URL missing")
        self.assertFalse(result["transactions_ready"])
        self.assertNotIn("SECRET", str(result))
        self.assertEqual(session.called, [])

    async def test_upstash_ping_is_not_the_same_as_ready_snapshot(self):
        diagnose, session = make_runtime(
            upstash=True, url="https://redis.example.invalid", token="SECRET",
            ready=False, status="unavailable")
        result = await diagnose()
        self.assertTrue(result["connected"])
        self.assertFalse(result["snapshot_ready"])
        self.assertFalse(result["transactions_ready"])
        self.assertIn("not ready", result["detail"])
        self.assertNotIn("SECRET", str(result))
        self.assertNotIn("redis.example.invalid", str(result))
        self.assertEqual(len(session.called), 1)

    async def test_good_upstash_and_loaded_snapshot_are_action_ready(self):
        diagnose, _ = make_runtime(
            upstash=True, url="https://redis.example.invalid", token="SECRET",
            ready=True, status="ready")
        result = await diagnose()
        self.assertTrue(result["connected"])
        self.assertTrue(result["snapshot_ready"])
        self.assertTrue(result["transactions_ready"])

    async def test_pending_receipt_blocks_action_even_with_good_ping(self):
        diagnose, _ = make_runtime(
            upstash=True, url="https://redis.example.invalid", token="SECRET",
            ready=True, status="ready", pending="private-receipt-id")
        result = await diagnose()
        self.assertFalse(result["transactions_ready"])
        self.assertTrue(result["pending_transaction"])
        self.assertNotIn("private-receipt-id", str(result))

    async def test_failed_upstash_ping_reports_no_private_response(self):
        diagnose, _ = make_runtime(
            upstash=True, url="https://redis.example.invalid", token="SECRET",
            remote_response=FakeResponse(
                status=401, payload={"error": "SECRET"}))
        result = await diagnose()
        self.assertFalse(result["connected"])
        self.assertFalse(result["transactions_ready"])
        self.assertIn("PING failed", result["detail"])
        self.assertNotIn("SECRET", str(result))

    async def test_local_testing_override_is_explicit_and_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            diagnose, _ = make_runtime(
                upstash=False, file_path=str(Path(directory) / "bot.json"))
            with patch.dict(os.environ, {"CINNAMON_ALLOW_LOCAL_ACTIONS": "true"}):
                result = await diagnose()
            self.assertTrue(result["transactions_ready"])
            self.assertFalse(result["durable"])
            self.assertTrue(result["local_override"])

    def test_slash_diagnostic_uses_deferred_private_response(self):
        content = SERVER_SETUP.read_text(encoding="utf-8")
        self.assertIn('name="check", description="Check snapshot health', content)
        self.assertIn("await interaction.response.defer(ephemeral=True)", content)
        self.assertIn("await interaction.followup.send(", content)
        self.assertIn('status["transactions_ready"]', content)
        self.assertIn("CINNAMON_ALLOW_LOCAL_ACTIONS is enabled", content)


if __name__ == "__main__":
    unittest.main()
