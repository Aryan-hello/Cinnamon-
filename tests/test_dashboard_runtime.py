"""Offline behavior checks for dashboard actions and server navigation."""
import ast
import asyncio
import datetime
import html
import threading
import types
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ast.parse((ROOT / "dashboard.py").read_text(encoding="utf8"))


def load_dashboard_functions(*names, **namespace):
    functions = [
        node for node in DASHBOARD.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    ns = {"asyncio": asyncio, "dt": datetime, **namespace}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "dashboard.py", "exec"), ns)
    return ns


class DashboardRegistrationTests(unittest.TestCase):
    def test_dashboard_blueprint_is_registered_exactly_once(self):
        runtime = (ROOT / "cinnamon_modules" / "dashboard_runtime.py").read_text(encoding="utf-8")
        self.assertEqual(runtime.count("flask_app.register_blueprint("), 1)
        self.assertEqual(runtime.count("configure_dashboard(bot,"), 1)


class DashboardCoroutineTests(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        ready = threading.Event()
        self.loop.call_soon_threadsafe(ready.set)
        self.assertTrue(ready.wait(1))
        self.bot = types.SimpleNamespace(is_ready=lambda: True, loop=self.loop)
        self.run_bot = load_dashboard_functions("_run_bot", _bot=self.bot)["_run_bot"]

    def tearDown(self):
        async def clean_up():
            pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        asyncio.run_coroutine_threadsafe(clean_up(), self.loop).result(timeout=1)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=1)
        self.loop.close()

    def test_timeout_cancels_pending_discord_action(self):
        started = threading.Event()
        cancelled = threading.Event()
        action_completed = threading.Event()

        async def delayed_action():
            try:
                started.set()
                await asyncio.Event().wait()
                action_completed.set()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with self.assertRaises(TimeoutError):
            self.run_bot(delayed_action(), timeout=0.05)
        self.assertTrue(started.is_set())
        self.assertTrue(cancelled.wait(1), "Timed-out action kept running on the bot loop")
        self.assertFalse(action_completed.is_set())

    def test_successful_action_returns_its_result(self):
        async def action():
            return "saved"

        self.assertEqual(self.run_bot(action()), "saved")

    def test_not_ready_bot_closes_unused_coroutine(self):
        self.bot.is_ready = lambda: False

        async def action():
            raise AssertionError("Not-ready bot must not run the action")

        coro = action()
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            self.run_bot(coro)
        self.assertIsNone(coro.cr_frame)


class DashboardModerationTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        async def kick(**kwargs):
            self.calls.append(("kick", kwargs))

        async def ban(**kwargs):
            self.calls.append(("ban", kwargs))

        permissions = types.SimpleNamespace(
            administrator=True, manage_guild=True, kick_members=True, ban_members=True,
        )
        self.actor = types.SimpleNamespace(
            id=111111111111111111, top_role=10, guild_permissions=permissions,
        )
        self.target = types.SimpleNamespace(
            id=222222222222222222, top_role=20, kick=kick, ban=ban,
        )
        me = types.SimpleNamespace(
            id=333333333333333333, top_role=30, guild_permissions=permissions,
        )
        members = {self.actor.id: self.actor, self.target.id: self.target}
        self.guild = types.SimpleNamespace(
            owner_id=444444444444444444, me=me, get_member=members.get,
        )
        self.moderate_fn = load_dashboard_functions(
            "_moderate", _bot=types.SimpleNamespace(user=me), _run_bot=asyncio.run,
        )["_moderate"]

    def moderate(self, action):
        return self.moderate_fn(self.guild, self.actor.id, {
            "mod_action": action, "member_id": str(self.target.id),
        })

    def test_administrator_cannot_kick_or_ban_equal_or_higher_role(self):
        for action in ("kick", "ban"):
            for rank in (10, 20):
                with self.subTest(action=action, target_rank=rank):
                    self.target.top_role = rank
                    with self.assertRaisesRegex(PermissionError, "equal or higher role"):
                        self.moderate(action)
        self.assertEqual(self.calls, [])

    def test_administrator_can_moderate_lower_role(self):
        self.target.top_role = 5
        self.moderate("kick")
        self.assertEqual([action for action, _ in self.calls], ["kick"])

    def test_owner_keeps_hierarchy_override(self):
        self.guild.owner_id = self.actor.id
        self.moderate("ban")
        self.assertEqual([action for action, _ in self.calls], ["ban"])


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"attrs": attrs, "elements": []}
            self.forms.append(self.current)
        elif self.current is not None:
            self.current["elements"].append((tag, attrs))

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


class DashboardNavigationTests(unittest.TestCase):
    def test_server_selector_can_submit_without_inline_script(self):
        guild = types.SimpleNamespace(id=100, name="First server")
        other = types.SimpleNamespace(id=200, name="Second server")
        shell = load_dashboard_functions(
            "_shell", _bot=types.SimpleNamespace(guilds=[guild, other]),
            _esc=lambda value: html.escape(str(value), quote=True),
            _nav=lambda *args: "", _header=lambda: "", _page=lambda body, title: body,
        )["_shell"]
        parser = FormParser()
        parser.feed(shell(guild, [
            {"id": "100", "name": guild.name, "owner": True},
            {"id": "200", "name": other.name, "owner": True},
        ], "overview", ""))
        form = next(form for form in parser.forms if form["attrs"].get("action") == "/dashboard")
        self.assertEqual(form["attrs"].get("method"), "get")
        selects = [attrs for tag, attrs in form["elements"] if tag == "select"]
        self.assertEqual(selects[0]["name"], "guild_id")
        self.assertNotIn("onchange", selects[0])
        options = [attrs["value"] for tag, attrs in form["elements"] if tag == "option"]
        self.assertEqual(options, ["100", "200"])
        buttons = [attrs for tag, attrs in form["elements"] if tag == "button"]
        self.assertTrue(any(attrs.get("type") == "submit" for attrs in buttons))


if __name__ == "__main__":
    unittest.main()
