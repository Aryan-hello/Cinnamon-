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
        self.assertIn("?todays", entries[0].description)
        self.assertNotIn("secret-command", str(entries))

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
        self.assertIn('@bot.tree.command(name="ping"', src)
        self.assertIn('@bot.tree.command(name="botstatus"', src)
        self.assertIn('name="help", description="Browse Cinnamon commands', src)
        self.assertIn("_help_slash_entries(_all_leaf_commands())", src)
        self.assertIn("_help_command_pages(entries, max_chars=940", src)
        self.assertNotIn("_HELP_EVERYONE =", src)
        self.assertNotIn("current_len+extra>3000", src)

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
        for source in (slash, prefix):
            self.assertIn('storage["transactions_ready"]', source)
            self.assertIn("storage_status()", source)
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
