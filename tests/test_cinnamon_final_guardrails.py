"""Final pre-deployment guardrails for Cinnamon's permissions and virtual economy.

No Discord connection or real Catnip balances are used in these tests.
"""
import ast
import re
import types
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODS = ROOT / "cinnamon_modules"


def source(name):
    return (MODS / name).read_text(encoding="utf8")


def extracted(name, wanted, env):
    tree = ast.parse(source(name))
    body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name in wanted]
    exec(compile(ast.Module(body=body, type_ignores=[]), name, "exec"), env)
    return env


class FinalPreDeploymentTests(unittest.TestCase):
    def test_definite_user_chosen_catnip_transfer_and_nonnegative_items(self):
        econ = source("economy.py")
        self.assertIn("member: discord.Member, amount: app_commands.Range[int, 1, 10000000]", econ)
        self.assertIn("if not isinstance(amount, int) or not 1 <= amount <= 10000000:", econ)
        self.assertIn("quantity: app_commands.Range[int, 1, 10000] = 1", econ)
        self.assertIn("@app_commands.autocomplete(item=cinnamon_item_autocomplete)", econ)

    def test_explicit_mentions_never_implicitly_allow_everyone(self):
        main = (ROOT / "main.py").read_text(encoding="utf8")
        self.assertIn("allowed_mentions=discord.AllowedMentions.none()", main)
        explicit = []
        for module in (MODS).glob("*.py"):
            tree = ast.parse(module.read_text(encoding="utf8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "AllowedMentions":
                    if any(k.arg == "everyone" and isinstance(k.value, ast.Constant)
                           and k.value.value is True for k in node.keywords):
                        explicit.append(module.name)
        self.assertEqual(explicit, ["cinnamon_personality.py"],
                         "Only confirmed administrator announcements can enable @everyone")
        mind = source("cinnamon_personality.py")
        self.assertIn("interaction.user.guild_permissions.administrator", mind)
        self.assertIn('name="announce"', mind)
        self.assertIn("_CPAdminAnnouncementConfirm", mind)
        self.assertIn('name="cameos"', mind)

    def test_cinnamon_name_called_directly_not_as_food(self):
        ns=extracted("cinnamon_personality.py", {"_cp_direct_name"}, {"_cp_re": re})
        called=ns["_cp_direct_name"]
        for text in ("Cinnamon", "Cinnamon!", "Cinnamon, come here!", "hey Cinnamon",
                     "yo Cinnamon, are you there?", "what about you, Cinnamon?"):
            self.assertTrue(called(text), text)
        for text in ("These cinnamon rolls look good", "Let's buy cinnamon powder",
                     "I prefer cinnamon bread", "we like Cinnamon rolls"):
            self.assertFalse(called(text), text)

    def test_human_chat_needs_invitation_and_cameos_are_extremely_limited(self):
        core = source("core_events.py")
        self.assertIn("called_by_name = _cp_direct_name(clean_content)", core)
        self.assertIn("if not invited:", core)
        self.assertIn("await _cp_maybe_cameo(message)", core)
        self.assertNotIn("or is_ai_channel):", core)
        mind = source("cinnamon_personality.py")
        self.assertIn('_cp_random.random() >= 0.02', mind)
        self.assertIn("21600", mind)
        self.assertIn("discord.AllowedMentions.none()", mind)

    def test_merchant_staff_override_and_setup_idempotency(self):
        fish = source("cinnamon_adventure_fishing.py")
        self.assertIn("manual_public", fish)
        self.assertIn('name="merchant-access"', fish)
        self.assertIn("perms.administrator", fish)
        self.assertIn("finder_id", fish)
        ns=extracted("cinnamon_adventure_fishing.py", {"_wlf_active"},
                     {"_wlf_window":lambda gid,k: {"ends_at":0,"manual_public":True},
                      "_wlf_time":types.SimpleNamespace(time=lambda:50)})
        self.assertTrue(ns["_wlf_active"](1,"rod"))
        setup = source("server_setup.py")
        self.assertIn("hangry_games_channel: discord.TextChannel | None = None",setup)
        self.assertIn('await _wlf_refresh_channel(guild, merchant_kind)',setup)
        self.assertIn('"cinnamon-mood-logs"',setup)
        self.assertIn('channels["cinnamon-stuff-logs"]',setup)

    def test_story_embeds_and_fishing_interaction(self):
        story=source("cinnamon_adventure_story.py")
        self.assertIn("e.add_field(name='Story progress'", story)
        self.assertIn("e.add_field(name='Clues'", story)
        fish=source("cinnamon_adventure_fishing.py")
        for x in ("_WLFReelView", "Choose which bait to use", "Reel gently",
                  "Keep steady", "YANK!", "asyncio.Lock()", "self.used = True",
                  "No bait is spent until you reel."):
            self.assertIn(x,fish)

    def test_dashboard_real_controls_and_protected_actions(self):
        dashboard=(ROOT/"dashboard.py").read_text(encoding="utf8")
        runtime=source("dashboard_runtime.py")
        for name in ("_mind(", "_adventure(", "mind_settings", "merchant_access",
                     "economy_transfer", "_get_access(", "_check_csrf()",
                     "_member_select(", "_channel_select("):
            self.assertIn(name,dashboard)
        for name in ("cinnamon_social", "cinnamon_moods", "cinnamon_adventure_fishing",
                     "wlf_refresh_channel", "bd_save_data"):
            self.assertIn(name,runtime)
        self.assertIn("if nonce in used:", dashboard)
        self.assertIn("if before<amount:", dashboard)
        self.assertIn('await state["bd_save_data"]()',dashboard)

if __name__ == "__main__":
    unittest.main()
