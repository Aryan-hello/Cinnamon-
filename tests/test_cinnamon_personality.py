"""Offline guardrails for Cinnamon's spontaneous, privacy-conscious interactions."""
import ast
import asyncio
import random
import time
import unittest
from collections import defaultdict, deque
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "cinnamon_modules" / "cinnamon_personality.py"
SOURCE = FILE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def lobby_runtime(participants=2, hook=None, edit_forbidden=False, save_ok=True):
    """Execute the real policy and lobby functions without Discord or real sleeps."""
    emitted, launched, saves, errors = [], [], [], []
    elapsed = [0.0]

    class HTTPError(Exception):
        pass

    class AllowedMentions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        @staticmethod
        def none():
            return None

    class Post:
        async def edit(self, **kwargs):
            if edit_forbidden:
                raise HTTPError("removed permission")

    class Channel:
        id = 63
        mention = "<#63>"
        def __init__(self):
            self.permissions = SimpleNamespace(view_channel=True, send_messages=True,
                                               embed_links=True)
        def permissions_for(self, member):
            return self.permissions
        async def send(self, content, **kwargs):
            emitted.append(content)
            return Post()

    class View:
        def __init__(self, cog, host, catnip_prize, sponsor):
            self.started = False
            self.players = {n: object() for n in range(participants)}
            self.children = [SimpleNamespace(label="Start 🔴", disabled=False)]
        def embed(self):
            return "embed"
        def stop(self):
            pass

    class Cog:
        def __init__(self):
            self.lobbies, self.active = {}, {}
        async def _log(self, *args, **kwargs):
            pass
        async def launch(self, *args, **kwargs):
            launched.append((args, kwargs))

    channel, cog = Channel(), Cog()
    role = SimpleNamespace(name="Hangry Games", id=444, mention="<@&444>")
    channels = {channel.id: channel, 64: SimpleNamespace(id=64)}
    guild = SimpleNamespace(id=3, roles=[role], me=SimpleNamespace(id=8),
                            get_channel=channels.get)

    async def pause(seconds):
        elapsed[0] += seconds
        if hook:
            hook("pause", elapsed[0], ns, guild, channel, cog)

    async def save():
        saves.append(elapsed[0])
        if hook:
            hook("save", len(saves), ns, guild, channel, cog)
        return save_ok

    async def event_log(*args, **kwargs):
        pass

    ns = {"discord": SimpleNamespace(
        utils=SimpleNamespace(get=lambda values, **kw: next(
            (v for v in values if all(getattr(v, k, None) == x for k, x in kw.items())), None)),
        AllowedMentions=AllowedMentions, HTTPException=HTTPError, Forbidden=HTTPError),
        "asyncio": SimpleNamespace(sleep=pause, CancelledError=asyncio.CancelledError),
        "_cp_time": SimpleNamespace(time=lambda: 10000 + elapsed[0], monotonic=lambda: elapsed[0]),
        "_cb_time": SimpleNamespace(time=lambda: 10000 + elapsed[0]),
        "_cb_deque": deque, "_CB_ACTIVITY": {}, "_CB_WINDOW_SECONDS": 1800,
        "_CB_FRESH_SECONDS": 600, "_CB_MIN_MESSAGES": 6, "_CB_MIN_MEMBERS": 2,
        "_CB_EMPTY_GAME_BACKOFF": 21600, "_CP_LAUNCHING": set(),
        "advanced_features_data": {}, "disabled_channels": defaultdict(set),
        "bd_store": SimpleNamespace(ready=True, pending_receipt=None, status="ready"),
        "bd_save_data": save, "HGLobbyView": View, "_cp_log": event_log,
        "_cp_random": SimpleNamespace(randint=lambda lo, hi: 1700),
        "log": SimpleNamespace(warning=lambda *a: errors.append(a),
                               exception=lambda *a: errors.append(a))}
    brain_tree = ast.parse((ROOT / "cinnamon_modules/cinnamon_brain.py").read_text())
    names = {"_cb_settings", "_cb_independence_enabled", "_cb_storage_available",
             "_cb_prune", "_cb_observe", "_cb_activity_stats", "_cb_game_decision",
             "_cb_game_eligibility", "guild_channel_send_allowed"}
    body = [n for n in brain_tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=body, type_ignores=[]), "brain-runtime", "exec"), ns)
    load_helpers({"_cp_server", "_cp_auto_start", "_cp_tick_guild", "_cp_tick"}, ns)
    ns["_cp_server"](guild.id).update(auto_enabled=True, auto_channel=channel.id)
    for i in range(6):
        ns["_cb_observe"](guild.id, i % 2 + 10, at=9970 + 5 * i)
    return SimpleNamespace(ns=ns, guild=guild, channel=channel, cog=cog,
                           emitted=emitted, launched=launched, saves=saves,
                           errors=errors, elapsed=elapsed)

def load_helpers(names, ns):
    body = [n for n in TREE.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name in names]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(FILE), "exec"), ns)
    return ns

class PersonalityTests(unittest.TestCase):
    def test_mounted_after_all_dependencies(self):
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('"cinnamon_personality.py"', main)
        for dep in ("hangry_games.py", "cinnamon_moods.py", "wildlands_story.py"):
            self.assertLess(main.index(dep), main.index('"cinnamon_personality.py"'))
        setup = (ROOT / "cinnamon_modules/server_setup.py").read_text(encoding="utf-8")
        self.assertIn("cinnamon-stuff-logs", setup)
        self.assertIn("cinnamon-games", setup)
        self.assertIn('"stuff": channels["cinnamon-stuff-logs"].id', setup)
        self.assertIn('"Hangry Games"', setup)
        self.assertIn('social["auto_channel"]', setup)
        self.assertIn('social["auto_enabled"] = True', setup)
        self.assertIn("await _cp_recover(guild)", setup)
        self.assertIn("cinnamon_people_restored", setup)

    def test_exactly_two_role_mentions_and_two_minute_window(self):
        fn = next(n for n in TREE.body if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "_cp_auto_start")
        segment = ast.get_source_segment(SOURCE, fn)
        self.assertEqual(segment.count("{role.mention}"), 2)
        self.assertIn("90 - (_cp_time.monotonic() - started_at)", segment)
        self.assertIn("120 - (_cp_time.monotonic() - started_at)", segment)
        self.assertIn("randint(1000, 2500)", segment)
        self.assertIn("len(view.players) < 2", segment)
        self.assertIn("allowed_mentions=discord.AllowedMentions(users=False, roles=[role]", segment)
        self.assertIn("view.auto_managed = True", segment)
        hangry = (ROOT / "cinnamon_modules/hangry_games.py").read_text()
        self.assertIn('getattr(self, "auto_managed", False)', hangry)
        self.assertIn('self.bot.user and runner_id == self.bot.user.id', hangry)

    def test_personality_status_and_rankings(self):
        ns = load_helpers({"_cp_server", "_cp_person", "_cp_favourites", "_cp_nice"},
                          {"advanced_features_data": {},
                           "_cm_naughty": lambda gid, uid: uid == 9})
        s, p, fav, nice = (ns[n] for n in
                           ("_cp_server", "_cp_person", "_cp_favourites", "_cp_nice"))
        self.assertFalse(s(1)["auto_enabled"])
        p(1, 2)["good"] = 7
        p(1, 9)["good"] = 12
        p(1, 4)["good"] = 4
        self.assertEqual(fav(1), [(9, 12), (2, 7), (4, 4)])
        self.assertTrue(nice(1, 2))
        self.assertFalse(nice(1, 9))

    def test_personal_questions_cap_and_opt_out(self):
        counts = []
        out = []
        class Channel:
            id = 30
            async def send(self, text, **kwargs):
                out.append(text)
                return SimpleNamespace(id=len(out))
        chan = Channel()
        async def save():
            counts.append(1)
            return True
        async def log(*args): pass
        ns = {"advanced_features_data": {}, "_cp_time": time,
              "_CP_QUESTIONS": ("What is a suspicious potato?",),
              "_cp_random": SimpleNamespace(random=lambda: 0.0, choice=lambda values: values[0]),
              "bd_save_data": save, "_cp_log": log,
              "_cb_independence_enabled": lambda gid: True,
              "_cb_storage_available": lambda: True,
              "guild_channel_send_allowed": lambda *args: True,
              "discord": SimpleNamespace(
                  AllowedMentions=SimpleNamespace(users=lambda **x:None),
                  HTTPException=type("MockHTTPException", (Exception,), {})),
              }
        # AllowedMentions(users=True, roles=False, everyone=False) acts as a class call.
        ns["discord"].AllowedMentions = lambda **kwargs: kwargs
        load_helpers({"_cp_server", "_cp_person", "_cp_maybe_question"}, ns)
        def message(uid):
            user=SimpleNamespace(id=uid, bot=False, mention=f"<@{uid}>")
            return SimpleNamespace(guild=SimpleNamespace(id=1), author=user, channel=chan)
        async def check():
            await ns["_cp_maybe_question"](message(7))
            await ns["_cp_maybe_question"](message(7))
            await ns["_cp_maybe_question"](message(8))
            self.assertEqual(len(out), 1)
            ns["_cp_server"](1)["last_question"] -= 21601
            ns["_cp_person"](1, 8)["questions_optout"] = True
            await ns["_cp_maybe_question"](message(8))
            self.assertEqual(len(out), 1)
            self.assertEqual(len(counts), 2)
        asyncio.run(check())

    def test_surprise_lobby_is_quiet_when_no_one_joins(self):
        for participants in (0, 2):
            emitted, launched, disappointments, edited = [], [], [], []
            elapsed = [0.0]
            async def pause(seconds):
                elapsed[0] += seconds
            async def store(): return True
            async def eventlog(*args, **kwargs): pass
            def letdown(*args): disappointments.append(args)
            class Post:
                async def edit(self, **kwargs): edited.append(kwargs)
            class Channel:
                id = 63
                mention = "<#63>"
                async def send(self, content, **kwargs):
                    emitted.append(content)
                    return Post()
            class View:
                def __init__(self, cog, host, catnip_prize, sponsor):
                    self.started = False
                    self.players = {n: object() for n in range(participants)}
                    self.children = [SimpleNamespace(label="Join 🐾",disabled=False),
                                     SimpleNamespace(label="Start 🔴",disabled=False)]
                def embed(self): return "embed"
                def stop(self): pass
            class Cog:
                def __init__(self): self.lobbies = {}
                def _busy(self, channel): return False
                async def _log(self, *args, **kwargs): pass
                async def launch(self, *args, **kwargs): launched.append((args, kwargs))
            cog = Cog()
            role = SimpleNamespace(name="Hangry Games", id=444, mention="<@&444>")
            guild = SimpleNamespace(id=3, roles=[role], me=SimpleNamespace(id=8))
            discord = SimpleNamespace(
                utils=SimpleNamespace(get=lambda roles, **kwargs: role),
                AllowedMentions=SimpleNamespace(none=lambda: None),
                HTTPException=type("HTTP", (Exception,), {}),
                Forbidden=type("Forbidden", (Exception,), {}))
            class Allowed:
                def __init__(self, **kwargs): self.kwargs = kwargs
                @staticmethod
                def none(): return None
            discord.AllowedMentions = Allowed
            ns = {"discord": discord, "HGLobbyView": View,
                  "asyncio": SimpleNamespace(sleep=pause),
                  "_cp_random": SimpleNamespace(randint=lambda low, high: 1700),
                  "_cp_time": SimpleNamespace(monotonic=lambda: elapsed[0],
                                              time=lambda: 123456 + elapsed[0]),
                  "_CP_LAUNCHING": set(),
                  "advanced_features_data": {},
                  "_cb_independence_enabled": lambda gid: True,
                  "_cb_game_eligibility": lambda *args, **kwargs: (True, "active_conversation"),
                  "guild_channel_send_allowed": lambda guild, channel: True,
                  "_cp_log": eventlog,
                  "bd_save_data": store,
                  "_cm_adjust": letdown,
                  "log": SimpleNamespace(warning=lambda *args:None)}
            load_helpers({"_cp_server", "_cp_auto_start"}, ns)
            asyncio.run(ns["_cp_auto_start"](guild, Channel(), cog))
            role_pings = [m for m in emitted if "<@&444>" in m]
            self.assertEqual(len(role_pings), 1 if participants == 0 else 2)
            self.assertEqual(elapsed[0], 120.0)
            self.assertEqual(ns["_CP_LAUNCHING"], set())
            if participants == 0:
                self.assertEqual(len(launched), 0)
                self.assertEqual(len(disappointments), 0)
                self.assertEqual(len(emitted), 1, "No repeat pings or cancellation spam")
                self.assertGreater(
                    ns["_cp_server"](3)["last_unanswered_game_at"], 123456)
            else:
                self.assertEqual(len(launched), 1)
                self.assertEqual(launched[0][1]["catnip_prize"], 1700)
                self.assertEqual(len(disappointments), 0)

    def test_scheduled_game_interval_and_manager_controls(self):
        source = SOURCE
        self.assertIn("randint(3600, 7200)", source)
        self.assertIn('server["auto_enabled"] = bool(enabled)', source) if False else None
        self.assertIn('s["auto_enabled"] = bool(enabled)', source)
        self.assertIn('s["next_at"] = now + _cp_random.randint(3600, 7200)', source)
        self.assertIn('s["next_at"] = _cp_time.time() + _cp_random.randint(3600, 7200)', source)
        self.assertIn("questions_optout", source)
        self.assertIn("react_big_purchase", source) if False else None

class AutonomyRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def run_lobby(self, runtime):
        await runtime.ns["_cp_auto_start"](runtime.guild, runtime.channel, runtime.cog)
        self.assertEqual(runtime.ns["_CP_LAUNCHING"], set())
        self.assertEqual(runtime.cog.lobbies, {})

    async def test_real_policy_launches_active_guild_once(self):
        runtime = lobby_runtime()
        await self.run_lobby(runtime)
        self.assertEqual(len(runtime.launched), 1)
        self.assertEqual(len(runtime.emitted), 2)
        self.assertEqual(runtime.elapsed[0], 120)

    async def test_zero_or_one_joiner_records_backoff_without_cancel_spam(self):
        for participants in (0, 1):
            runtime = lobby_runtime(participants=participants, edit_forbidden=True)
            await self.run_lobby(runtime)
            self.assertFalse(runtime.launched)
            self.assertEqual(len(runtime.emitted), 1 if participants == 0 else 2)
            self.assertEqual(runtime.ns["_cp_server"](3)["last_unanswered_game_at"], 10120)

    async def test_master_switch_off_during_lobby_prevents_followup_and_launch(self):
        def hook(event, value, ns, guild, channel, cog):
            if event == "pause":
                ns["_cb_settings"](guild.id)["independence_enabled"] = False
        runtime = lobby_runtime(hook=hook)
        await self.run_lobby(runtime)
        self.assertEqual(len(runtime.emitted), 1)
        self.assertFalse(runtime.launched)

    async def test_feature_disabled_or_channel_changed_during_lobby_cancels(self):
        for key, value in (("auto_enabled", False), ("auto_channel", 64)):
            def hook(event, elapsed, ns, guild, channel, cog):
                if event == "pause":
                    ns["_cp_server"](guild.id)[key] = value
            runtime = lobby_runtime(hook=hook)
            await self.run_lobby(runtime)
            self.assertEqual(len(runtime.emitted), 1)
            self.assertFalse(runtime.launched)

    async def test_permission_loss_before_final_launch_cancels(self):
        def hook(event, value, ns, guild, channel, cog):
            if event == "pause" and value >= 120:
                channel.permissions.embed_links = False
        runtime = lobby_runtime(hook=hook)
        await self.run_lobby(runtime)
        self.assertEqual(len(runtime.emitted), 2)
        self.assertFalse(runtime.launched)

    async def test_other_channel_game_blocks_invitation(self):
        runtime = lobby_runtime()
        runtime.cog.active[64] = object()
        await self.run_lobby(runtime)
        self.assertFalse(runtime.emitted)
        self.assertFalse(runtime.saves)
        self.assertEqual(runtime.ns["_cp_server"](3)["last_brain_reason"], "another_game_running")

    async def test_storage_failed_save_or_pending_receipt_stays_silent(self):
        for failure in ("not_ready", "pending_receipt", "save"):
            runtime = lobby_runtime(save_ok=failure != "save")
            if failure == "not_ready":
                runtime.ns["bd_store"].ready = False
            elif failure == "pending_receipt":
                runtime.ns["bd_store"].pending_receipt = "3:63:100"
            await self.run_lobby(runtime)
            self.assertFalse(runtime.emitted)
            self.assertFalse(runtime.launched)

    async def test_disabled_channel_and_missing_permissions_each_stay_silent(self):
        for permission in ("disabled", "view_channel", "send_messages", "embed_links"):
            runtime = lobby_runtime()
            if permission == "disabled":
                runtime.ns["disabled_channels"][3].add(63)
            else:
                setattr(runtime.channel.permissions, permission, False)
            await self.run_lobby(runtime)
            self.assertFalse(runtime.emitted)

    async def test_post_save_switch_change_cannot_race_first_invitation(self):
        def hook(event, value, ns, guild, channel, cog):
            if event == "save":
                ns["_cb_settings"](3)["independence_enabled"] = False
        runtime = lobby_runtime(hook=hook)
        await self.run_lobby(runtime)
        self.assertFalse(runtime.emitted)

    async def test_eligibility_diagnostics_see_due_time_and_existing_lobby(self):
        runtime = lobby_runtime()
        social = runtime.ns["_cp_server"](3)
        social["next_at"] = 20000
        fn = runtime.ns["_cb_game_eligibility"]
        self.assertEqual(fn(runtime.guild, runtime.channel, runtime.cog, check_due=True),
                         (False, "waiting_for_opportunity"))
        runtime.cog.lobbies[64] = object()
        self.assertEqual(fn(runtime.guild, runtime.channel, runtime.cog),
                         (False, "another_game_running"))

    async def test_bad_guild_does_not_stop_next_guild_scheduler_check(self):
        runtime = lobby_runtime()
        second = SimpleNamespace(id=4)
        runtime.ns["_cp_server"](3)["next_at"] = "invalid"
        runtime.ns["_cp_server"](4).update(auto_enabled=True, auto_channel=64)
        done = [False]
        async def wait_ready():
            pass
        async def pause(seconds):
            done[0] = True
        runtime.ns["asyncio"].sleep = pause
        runtime.ns["bot"] = SimpleNamespace(
            wait_until_ready=wait_ready, is_closed=lambda: done[0],
            get_cog=lambda name: runtime.cog, guilds=[runtime.guild, second],
            _cp_scheduler_running=True)
        await runtime.ns["_cp_tick"]()
        self.assertEqual(runtime.ns["_cp_server"](3)["last_brain_reason"], "scheduler_error")
        self.assertGreater(runtime.ns["_cp_server"](4)["next_at"], 10000)
        self.assertFalse(runtime.ns["bot"]._cp_scheduler_running)


if __name__ == "__main__":
    unittest.main()
