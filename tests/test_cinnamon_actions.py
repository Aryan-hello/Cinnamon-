"""Offline contracts for opt-in Cinnamon jokes and authorized chat moderation."""
import ast
import re
import types
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ACTIONS=(ROOT/"cinnamon_modules"/"cinnamon_actions.py").read_text(encoding="utf8")
TREE=ast.parse(ACTIONS)


def load_rules():
    names={"_CA_MENTION","_CA_TARGET","_CA_TIMEOUT","_CA_SIMPLE",
           "_CA_DANGEROUS_INTENT"}
    functions={"_ca_wake_text","_ca_seconds","_ca_permission_reason"}
    body=[]
    for node in TREE.body:
        if isinstance(node,ast.Assign) and any(
            isinstance(t,ast.Name) and t.id in names for t in node.targets):
            body.append(node)
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
        ns=load_rules()
        wake=ns["_ca_wake_text"]
        m=ns["_CA_TIMEOUT"]
        s=ns["_CA_SIMPLE"]
        user_id="123456789012345678"
        self.assertIsNotNone(m.fullmatch(wake(f"hey Cinnamon, mute <@{user_id}> for 1 hour")))
        self.assertIsNotNone(m.fullmatch(wake(f"Cinnamon: time out <@!{user_id}> 10 seconds")))
        self.assertIsNotNone(m.fullmatch("mute this member for 1 hour"))
        self.assertIsNotNone(s.fullmatch(f"unmute <@{user_id}>"))
        self.assertIsNotNone(s.fullmatch(f"ban <@{user_id}>"))
        self.assertIsNone(m.fullmatch(f"mute <@{user_id}> for 1 hour and ban someone"))
        self.assertIsNone(s.fullmatch("kick everyone"))
        self.assertIsNone(m.fullmatch("mute this member"))
        self.assertIsNone(ns["_CA_TIMEOUT"].fullmatch("mute 123456789012345678 for 1 hour"))

    def test_time_units_and_limits(self):
        f=load_rules()["_ca_seconds"]
        self.assertEqual(f("1","sec"),1)
        self.assertEqual(f("10","seconds"),10)
        self.assertEqual(f("60","minutes"),3600)
        self.assertEqual(f("1","hour"),3600)
        self.assertEqual(f("1","day"),86400)
        self.assertIsNone(f("0","seconds"))
        self.assertIsNone(f("29","days"))
        self.assertIsNone(f("25","hours"))

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
        self.assertIsNone(fn(guild,admin,ordinary,"kick"))
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
        self.assertIn("if interaction.user.id != self.requester_id",ACTIONS)
        self.assertIn("_ca_permission_reason(guild, actor, target, self.action)",ACTIONS)
        self.assertIn("async with self.lock:",ACTIONS)
        self.assertIn("self.used = True",ACTIONS)
        self.assertIn("await interaction.response.defer(ephemeral=True)",ACTIONS)
        self.assertIn("await send_log(guild.id, title=",ACTIONS)
        self.assertIn("allowed_mentions=discord.AllowedMentions.none()",ACTIONS)
        self.assertIn("if not isinstance(ref, discord.Message) or ref.author.bot:",ACTIONS)

    def test_global_integration_and_admin_dashboard(self):
        main=(ROOT/"main.py").read_text(encoding="utf8")
        core=(ROOT/"cinnamon_modules"/"core_events.py").read_text(encoding="utf8")
        dash=(ROOT/"dashboard.py").read_text(encoding="utf8")
        self.assertLess(main.index('"cinnamon_personality.py"'),main.index('"cinnamon_actions.py"'))
        self.assertIn("await _ca_maybe_handle(message, clean_content)",core)
        self.assertIn("await _ca_maybe_prank(message)",core)
        self.assertIn("authorize_dashboard_edit",dash)
        self.assertIn('"play_enabled" in request.form',dash)
        self.assertIn("cinnamon_actions",dash)


if __name__=="__main__":
    unittest.main()
