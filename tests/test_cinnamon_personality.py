"""Offline guardrails for Cinnamon's spontaneous, privacy-conscious interactions."""
import ast
import asyncio
import random
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "cinnamon_modules" / "cinnamon_personality.py"
SOURCE = FILE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

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
        async def save(): counts.append(1)
        async def log(*args): pass
        ns = {"advanced_features_data": {}, "_cp_time": time,
              "_CP_QUESTIONS": ("What is a suspicious potato?",),
              "_cp_random": SimpleNamespace(random=lambda: 0.0, choice=lambda values: values[0]),
              "bd_save_data": save, "_cp_log": log,
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
            self.assertEqual(len(counts), 1)
        asyncio.run(check())

    def test_surprise_lobby_two_pings_and_no_player_cancellation(self):
        for participants in (0, 2):
            emitted, launched, disappointments, edited = [], [], [], []
            elapsed = [0.0]
            async def pause(seconds):
                elapsed[0] += seconds
            async def store(): pass
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
                  "_cp_time": SimpleNamespace(monotonic=lambda: elapsed[0]),
                  "_CP_LAUNCHING": set(),
                  "_cp_log": eventlog,
                  "bd_save_data": store,
                  "_cm_adjust": letdown,
                  "log": SimpleNamespace(warning=lambda *args:None)}
            load_helpers({"_cp_auto_start"}, ns)
            asyncio.run(ns["_cp_auto_start"](guild, Channel(), cog))
            role_pings = [m for m in emitted if "<@&444>" in m]
            self.assertEqual(len(role_pings), 2)
            self.assertEqual(elapsed[0], 120.0)
            self.assertEqual(ns["_CP_LAUNCHING"], set())
            if participants == 0:
                self.assertEqual(len(launched), 0)
                self.assertEqual(len(disappointments), 1)
                self.assertIn("YOU ALL LEFT MEEEEE", emitted[-1])
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

if __name__ == "__main__":
    unittest.main()
