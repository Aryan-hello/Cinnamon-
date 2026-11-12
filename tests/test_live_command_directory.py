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
    def read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_slash_ping_and_botstatus_exist_in_registry_source(self):
        src = self.read("cinnamon_modules/server_setup.py")
        self.assertIn("async def ping(interaction: discord.Interaction):", src)
        self.assertIn("async def botstatus(interaction: discord.Interaction):", src)
        # The help command is registered in server_setup; the exact copy and
        # pagination implementation are covered by separate unit tests.
        self.assertIn('name="help"', src)

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
