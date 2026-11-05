"""Offline contracts for opt-in Cinnamon jokes and authorized chat moderation."""
import ast
import re
import types
import unittest
from pathlib import Path
from cinnamon_modules.brain_actions import ActionValidationError, parse_action

ROOT=Path(__file__).resolve().parents[1]
ACTIONS=(ROOT/"cinnamon_modules"/"cinnamon_actions.py").read_text(encoding="utf8")
TREE=ast.parse(ACTIONS)


def load_rules():
    functions={"_ca_permission_reason"}
    body=[]
    for node in TREE.body:
        if isinstance(node,ast.FunctionDef) and node.name in functions:
            body.append(node)
    ns={"_ca_re":re}
    exec(compile(ast.Module(body=body,type_ignores=[]),"cinnamon_actions.py","exec"),ns)
    return ns


def build_member(guild,uid,rank,admin=False,moderator=False,bot=False):
    return types.SimpleNamespace(
        id=uid,guild=guild,bot=bot,top_role=rank,
        guild_permissions=types.SimpleNamespace(administrator=admin,moderate_members=moderator))


class SafeCinnamonActionsTests(unittest.TestCase):
    def test_exact_staff_instructions_only(self):
        user_id="123456789012345678"
        def parse(text, **kwargs):
            return parse_action(text, requester_id=1, target_ids=[int(user_id)], **kwargs)
        self.assertEqual(parse(f"hey Cinnamon, mute <@{user_id}> for 1 hour").seconds, 3600)
        self.assertEqual(parse(f"Cinnamon: time out <@!{user_id}> 10 seconds").seconds, 10)
        self.assertEqual(parse_action("mute this member for 1 hour", requester_id=1,
                                      target_ids=[], reply_target_id=int(user_id)).seconds, 3600)
        self.assertEqual(parse(f"unmute <@{user_id}>").action, 'moderation.remove_timeout')
        for text in (f"ban <@{user_id}>", f"mute <@{user_id}> for 1 hour and ban someone",
                     "kick everyone", "mute this member", f"mute {user_id} for 1 hour"):
            with self.subTest(text=text), self.assertRaises(ActionValidationError):
                parse(text)

    def test_time_units_and_limits(self):
        target=123456789012345678
        for quantity, unit, expected in ((1,'sec',1),(10,'seconds',10),(60,'minutes',3600),
                                         (1,'hour',3600),(1,'day',86400)):
            self.assertEqual(parse_action(f'mute <@{target}> for {quantity} {unit}',
                                          requester_id=1,target_ids=[target]).seconds,expected)
        for duration in ('0 seconds','29 days','25 hours'):
            with self.assertRaises(ActionValidationError):
                parse_action(f'mute <@{target}> for {duration}',requester_id=1,target_ids=[target])

    def test_permission_levels_and_role_hierarchy(self):
        fn=load_rules()["_ca_permission_reason"]
        guild=types.SimpleNamespace(id=30,owner_id=9000)
        me=build_member(guild,999,100,bot=True)
        me.guild_permissions=types.SimpleNamespace(moderate_members=True,kick_members=True,ban_members=True)
        guild.me=me
        mod=build_member(guild,111,70,moderator=True)
        ordinary=build_member(guild,222,15)
        self.assertIsNone(fn(guild,mod,ordinary,"timeout"))
        self.assertIsNotNone(fn(guild,mod,ordinary,"ban"))
        admin=build_member(guild,333,80,admin=True)
        self.assertIsNotNone(fn(guild,admin,ordinary,"kick"))
        self.assertIsNotNone(fn(guild,admin,build_member(guild,444,90),"timeout"))
        self.assertIsNotNone(fn(guild,admin,build_member(guild,555,20,moderator=True),"timeout"))
        self.assertIsNotNone(fn(guild,admin,build_member(guild,556,20,admin=True),"kick"))
        self.assertIsNotNone(fn(guild,admin,admin,"kick"))
        self.assertIsNotNone(fn(guild,admin,build_member(guild,9000,10),"kick"))
        self.assertIsNotNone(fn(guild,mod,ordinary,"kick"))

    def test_opt_in_and_daily_limit(self):
        self.assertIn('server.get("play_enabled", False)',ACTIONS)
        self.assertIn('rec.get("consent", False)',ACTIONS)
        self.assertIn('rec.get("last_play_day") == utcnow.date().isoformat()',ACTIONS)
        self.assertIn('rec["last_play_day"] = utcnow.date().isoformat()',ACTIONS)
        self.assertIn("_ca_random.randint(1, 10)",ACTIONS)
        self.assertIn("member.guild_permissions.administrator",ACTIONS)
        self.assertIn("member.guild_permissions.moderate_members",ACTIONS)
        self.assertIn("member.top_role >= me.top_role",ACTIONS)
        self.assertIn('reason="Cinnamon consensual mini-prank',ACTIONS)
        self.assertIn('@app_commands.checks.has_permissions(administrator=True)',ACTIONS)

    def test_moderation_requires_actor_confirmation_twice(self):
        self.assertIn("interaction.user.id != self.requester_id",ACTIONS)
        self.assertIn("_ca_permission_reason(guild, actor, target, self.action, me=me)",ACTIONS)
        self.assertIn("async with self.lock:",ACTIONS)
        self.assertIn("self.used = True",ACTIONS)
        self.assertIn("await interaction.response.defer(ephemeral=True)",ACTIONS)
        self.assertIn("await send_log(self.gid, title=",ACTIONS)
        self.assertIn("allowed_mentions=discord.AllowedMentions.none()",ACTIONS)
        self.assertIn("not ref.author.bot and ref.guild and ref.guild.id == message.guild.id",ACTIONS)

    def test_global_integration_and_admin_dashboard(self):
        main=(ROOT/"main.py").read_text(encoding="utf8")
        core=(ROOT/"cinnamon_modules"/"core_events.py").read_text(encoding="utf8")
        dash=(ROOT/"dashboard.py").read_text(encoding="utf8")
        self.assertLess(main.index('"cinnamon_personality.py"'),main.index('"cinnamon_actions.py"'))
        self.assertIn('_ca_maybe_handle',core)
        self.assertIn("for route in plan.route_order",core)
        self.assertIn("plan_intent(clean_content)",core)
        self.assertIn("await _ca_maybe_prank(message)",core)
        self.assertIn("authorize_dashboard_edit",dash)
        self.assertIn('"play_enabled" in request.form',dash)
        self.assertIn("cinnamon_actions",dash)


class DailyPrankSimulation(unittest.IsolatedAsyncioTestCase):
    async def test_single_consent_based_event_per_utc_day(self):
        import asyncio
        import datetime
        from types import SimpleNamespace

        class Member:
            def __init__(self, guild, uid, staff=False):
                self.guild = guild
                self.id = uid
                self.bot = False
                self.top_role = 10
                self.timed_out_until = None
                self.guild_permissions = SimpleNamespace(administrator=False, moderate_members=staff)
                self.calls = 0

            async def timeout(self, duration, reason):
                self.calls += 1
                self.duration = duration

        class Channel:
            def __init__(self):
                self.messages = []
            async def reply(self, *args, **kwargs):
                self.messages.append((args, kwargs))

        guild = SimpleNamespace(id=50,owner_id=999)
        guild.me = SimpleNamespace(id=51,top_role=100,
                                   guild_permissions=SimpleNamespace(moderate_members=True))
        visitor = Member(guild, 77)
        source=Channel()
        source.guild = guild
        source.author = visitor

        stored = {}
        logs = []
        async def save():
            pass
        async def log(gid, **kwargs):
            logs.append((gid, kwargs))
        relevant={"_ca_server","_ca_user","_ca_maybe_prank"}
        body=[n for n in TREE.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
              and n.name in relevant]
        ns={
            "advanced_features_data":stored,
            "_ca_asyncio":asyncio,
            "_ca_datetime":datetime,
            "_ca_random":SimpleNamespace(random=lambda:0, randint=lambda a,b:5),
            "_CA_LOCKS":{},
            "bd_save_data":save,
            "send_log":log,
            "discord":SimpleNamespace(Member=Member,Forbidden=Exception,HTTPException=Exception,
                AllowedMentions=SimpleNamespace(none=lambda:None)),
        }
        exec(compile(ast.Module(body=body,type_ignores=[]),"cinnamon_actions.py","exec"),ns)
        record=ns["_ca_user"](guild.id,visitor.id)
        record["consent"]=True
        ns["_ca_server"](guild.id)["play_enabled"]=True
        self.assertTrue(await ns["_ca_maybe_prank"](source))
        self.assertEqual(visitor.calls,1)
        self.assertEqual(visitor.duration.total_seconds(),5)
        self.assertFalse(await ns["_ca_maybe_prank"](source))
        self.assertEqual(visitor.calls,1)
        self.assertEqual(len(logs),1)
        record["consent"]=False
        record["last_play_day"]="1900-01-01"
        self.assertFalse(await ns["_ca_maybe_prank"](source))
        self.assertEqual(visitor.calls,1)


if __name__=="__main__":
    unittest.main()
