"""Load the real shared runtime with its installed dependencies, entirely offline.

The subprocess prevents bot globals, command registrations, and Flask state from
leaking into other tests. Pure-only developer environments skip this check; CI
installs the runtime dependencies and must execute it.
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def runtime_dependencies_available():
    try:
        return all(importlib.util.find_spec(name) is not None
                   for name in ("discord", "flask", "google.genai", "aiohttp", "PIL"))
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


STARTUP_SCRIPT = r'''
import asyncio
import http.server
import socket
from unittest.mock import patch

network_attempts = []

def forbidden_network(*args, **kwargs):
    network_attempts.append(True)
    raise AssertionError("Runtime startup attempted a network connection")

class NoListener:
    def __init__(self, *args, **kwargs):
        pass
    def serve_forever(self):
        pass
    def shutdown(self):
        pass
    def server_close(self):
        pass

async def check_runtime():
    import main
    from cinnamon_modules.brain_actions import ACTION_REGISTRY

    try:
        assert "cinnamon_dashboard" in main.flask_app.blueprints, "Dashboard failed to attach"
        assert main.flask_app.secret_key == "offline-startup-session-secret"
        assert main._ca_settings(123456789012345678)["enabled"] is False
        assert set(ACTION_REGISTRY) == {
            "economy.add_catnip", "economy.remove_catnip",
            "moderation.timeout", "moderation.remove_timeout",
        }

        # Attach the actual GroupCog without its data-loading async_init or the
        # on_ready callback, both of which belong to live-service lifecycle work.
        await main.bot.add_cog(main.HangryGamesCog(main.bot))
        leaves = main._all_leaf_commands()
        paths = [main._command_path(command) for command in leaves]
        assert len(paths) == len(set(paths)), "Duplicate slash command path"
        root_names = [command.name for command in main.bot.tree.get_commands()]
        assert len(root_names) == len(set(root_names)), "Duplicate slash root"
        for path in ("/help", "/hangrygames new", "/fishing start", "/fishing cast",
                     "/recall", "/cinnamon stories", "/cinnamon-mind status",
                     "/cinnamon-mind actions"):
            assert path in paths, "Missing command " + path
        assert main.bot.get_command("ask") is not None
        assert main.bot.get_command("ai") is main.bot.get_command("ask")
        assert main.bot.get_command("chat") is main.bot.get_command("ask")

        catalog = main.build_command_catalog(leaves)
        fishing = main.answer_help("how do I fish?", catalog)
        recall = main.answer_help("what does /recall do?", catalog)
        assert "/fishing start" in fishing and "/fishing cast" in fishing
        assert "Administrator-only recovery" in recall

        loaded = await main.bd_load_data()
        assert loaded.status == "committed", loaded.status
        assert main.bd_store.ready and not main.bd_store.durable
        assert main._ca_storage_ready(), "Explicit local-action test opt-in not respected"
        saved = await main.bd_save_data()
        assert saved.status == "committed", saved.status
        with main.flask_app.test_client() as client:
            response = client.get("/")
            assert response.status_code == 200
    finally:
        await main.bot.close()
        main.gemini_client.close()

with patch.object(http.server, "ThreadingHTTPServer", NoListener), \
     patch.object(socket.socket, "connect", forbidden_network), \
     patch.object(socket.socket, "connect_ex", forbidden_network), \
     patch.object(socket.socket, "bind", forbidden_network):
    asyncio.run(check_runtime())

assert not network_attempts, "Startup touched a network socket"
print("Cinnamon runtime startup verified offline")
'''


@unittest.skipUnless(runtime_dependencies_available(), "Runtime dependencies are not installed")
class RuntimeStartupTests(unittest.TestCase):
    def test_real_bot_dashboard_and_command_tree_load_without_network(self):
        with tempfile.TemporaryDirectory(prefix="cinnamon-startup-") as directory:
            environment = os.environ.copy()
            environment.update({
                "DISCORD_TOKEN": "offline-startup-token",
                "GEMINI_API_KEY": "offline-startup-gemini-key",
                "DISCORD_CLIENT_ID": "123456789012345678",
                "DISCORD_CLIENT_SECRET": "offline-startup-oauth-secret",
                "DASHBOARD_SECRET_KEY": "offline-startup-session-secret",
                "DASHBOARD_SESSION_SECRET": "",
                "BOT_DATA_FILE": str(Path(directory) / "bot-data.json"),
                "HANGRY_GAMES_DATA_FILE": str(Path(directory) / "hangry-data.json"),
                "UPSTASH_REDIS_REST_URL": "",
                "UPSTASH_REDIS_REST_TOKEN": "",
                "CINNAMON_ALLOW_LOCAL_ACTIONS": "true",
                "PYTHONDONTWRITEBYTECODE": "1",
            })
            result = subprocess.run(
                [sys.executable, "-c", STARTUP_SCRIPT], cwd=ROOT, env=environment,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Cinnamon runtime startup verified offline", result.stdout)


if __name__ == "__main__":
    unittest.main()
