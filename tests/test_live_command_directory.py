"""Regression checks for Cinnamon's current prefix/slash help and status.

The directory itself is pure and reads registered metadata, not stale lists.
The real startup test separately checks actual discord.py command registration.
"""
from pathlib import Path
from types import SimpleNamespace
import unittest

from cinnamon_modules.brain_command_directory import (
    DirectoryEntry, slash_entries, prefix_entries, command_pages,
    available_shortcuts, registered_paths,
)

ROOT = Path(__file__).resolve().parents[1]


def slash_leaf(name, description, *, parent=None):
    return SimpleNamespace(
        name=name, description=description, parent=parent, commands=[],
        parameters=[SimpleNamespace(name="member", required=False)]
    )


class LiveDirectoryTests(unittest.TestCase):
    def test_slash_ping_and_botstatus_exist_in_registry_source(self):
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('@bot.tree.command(name="ping"', main)
        self.assertIn('@bot.tree.command(name="botstatus"', main)

    def test_grouped_slash_metadata_has_exact_registered_paths(self):
        group = SimpleNamespace(name="economy", parent=None, commands=[])
        admin = SimpleNamespace(name="admin", parent=group, commands=[])
        group.commands = [slash_leaf("balance", "See Catnip", parent=group), admin]
        admin.commands = [slash_leaf("addcatnip", "Give Catnip", parent=admin)]
        roots = [group, slash_leaf("botstatus", "Live bot status")]
        entries = slash_entries(roots)
        self.assertEqual({e.path for e in entries}, {
            "/economy balance", "/economy admin addcatnip", "/botstatus",
        })
        self.assertIn("/economy admin addcatnip", registered_paths(entries))
        self.assertEqual(
            available_shortcuts(registered_paths(entries),
                                ("/botstatus", "/not-registered")),
            "`/botstatus`")

    def test_large_slash_directory_never_overflows_embed_fields(self):
        entries = [
            DirectoryEntry(f"/economy check-{n:03d}",
                           "An accurate real command description " + "Z" * 80)
            for n in range(220)
        ]
        pages = command_pages(entries, max_chars=940, group_roots=True)
        self.assertGreater(len(pages), 15)
        self.assertTrue(all(1 <= len(page) <= 940 for page in pages))
        for entry in entries:
            self.assertEqual(sum(page.count("**" + entry.path + "**") for page in pages), 1)

    def test_prefix_directory_uses_qualified_names_signatures_and_aliases(self):
        command = SimpleNamespace(
            qualified_name="quest daily", aliases=["todays"], signature="[member]",
            help="View daily quests", brief=None, hidden=False)
        hidden = SimpleNamespace(
            qualified_name="secret-command", aliases=[], signature="", help="",
            brief="", hidden=True)
        entries = prefix_entries((command, hidden))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].path, "?quest daily")
        self.assertIn("Args: [member]", entries[0].description)
        self.assertIn("?quest todays", entries[0].description)
        self.assertNotIn("also ?todays", entries[0].description)
        self.assertNotIn("secret-command", str(entries))

    def test_group_aliases_and_top_level_aliases_are_not_mislabeled(self):
        group = SimpleNamespace(
            qualified_name="automod word add", aliases=["insert"],
            signature="<word>", brief="", help="Add banned word", hidden=False,
        )
        top = SimpleNamespace(
            qualified_name="balance", aliases=["bal"], signature="",
            brief="", help="Check wallet", hidden=False,
        )
        entries = prefix_entries([group, top])
        texts = {item.path: item.description for item in entries}
        self.assertIn("?automod word insert", texts["?automod word add"])
        self.assertIn("?bal", texts["?balance"])
        self.assertNotIn("also ?insert", texts["?automod word add"])

    def test_remaining_user_facing_references_use_real_subcommands(self):
        levels = (ROOT / "cinnamon_modules/levels_games.py").read_text(encoding="utf-8")
        reminders = (ROOT / "cinnamon_modules/cinnamon_reminders.py").read_text(encoding="utf-8")
        memory = (ROOT / "cinnamon_modules/cinnamon_memory.py").read_text(encoding="utf-8")
        personality = (ROOT / "cinnamon_modules/cinnamon_personality.py").read_text(encoding="utf-8")
        self.assertNotIn("`/levelrewards add`", levels)
        self.assertIn("`/level-rewards add`", levels)
        self.assertIn("`/cinnamon-reminder list`", reminders)
        self.assertIn("`/cinnamon-reminder cancel`", reminders)
        self.assertIn("`/cinnamon-memory view`", memory)
        self.assertIn("`/cinnamon-memory forget`", memory)
        self.assertNotIn("Only two role alerts", personality)
        self.assertIn("up to two opt-in role alerts", personality)

    def test_empty_directory_is_still_displayable(self):
        self.assertEqual(command_pages([]), [
            "Cinnamon has no registered commands in this category yet."])
        with self.assertRaises(ValueError):
            command_pages([], max_chars=1025)

    def test_prefix_display_limits_and_no_lost_commands(self):
        entries = [DirectoryEntry(f"?command{n}", "test") for n in range(180)]
        pages = command_pages(entries, max_chars=700)
        self.assertTrue(all(len(page) <= 700 for page in pages))
        for entry in entries:
            self.assertEqual(sum(page.count("**" + entry.path + "**") for page in pages), 1)


class CommandWiringTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_slash_ping_and_botstatus_exist_in_registry_source(self):
        src = self.read("cinnamon_modules/server_setup.py")
        self.assertIn("async def ping(interaction: discord.Interaction):", src)
        self.assertIn("async def botstatus(interaction: discord.Interaction):", src)
        self.assertIn('name="help", description="Browse Cinnamon commands', src)
        self.assertIn("commands_list = _all_leaf_commands()", src)
        self.assertIn("command_catalog", src.lower())
        self.assertIn("Usage: `{guide.syntax}`", src)
        self.assertIn("live slash + prefix command registry", src)
        self.assertIn("Member memory and reminders are private", src)
        self.assertIn("_HELP_EVERYONE =", src)
        self.assertIn("/ping", src)
        self.assertIn("/botstatus", src)
        self.assertIn("current_len + extra > 3000", src)

    def test_prefix_help_comes_from_current_bot_commands(self):
        src = self.read("cinnamon_modules/core_events.py")
        self.assertIn("_help_prefix_entries(bot.walk_commands())", src)
        self.assertIn("_help_command_pages(entries, max_chars=940)", src)
        self.assertIn('view=HelpPagesView(ctx.author.id, embeds)', src)
        self.assertNotIn("Use ?level for the image rank card", src)
        self.assertNotIn("Everything looks good from the bot's side", src)

    def test_status_commands_use_transaction_readiness_not_just_backend_label(self):
        slash = self.read("cinnamon_modules/server_setup.py")
        prefix = self.read("cinnamon_modules/core_events.py")
        self.assertIn('status["transactions_ready"]', slash)
        self.assertIn('storage["transactions_ready"]', prefix)
        self.assertIn("storage_status()", slash)
        self.assertIn("storage_status()", prefix)
        self.assertIn("await interaction.response.defer(ephemeral=True)", slash)
        self.assertIn("await interaction.followup.send(", slash)

    def test_public_income_guidance_uses_real_collector_path(self):
        economy = self.read("cinnamon_modules/economy.py")
        quests = self.read("cinnamon_modules/quests.py")
        self.assertIn("`/economy collect`", economy)
        self.assertNotIn("`/collect`", economy)
        self.assertNotIn("Use /collect on your income roles", quests)
        self.assertIn("Use /economy collect", quests)

    def test_privileged_actions_keep_durable_storage_guards(self):
        actions = self.read("cinnamon_modules/cinnamon_actions.py")
        self.assertIn("if not _ca_storage_ready():", actions)
        self.assertIn("store.durable", actions)


if __name__ == "__main__":
    unittest.main()
