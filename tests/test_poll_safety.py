"""Regression checks for poll command persistence and dashboard management."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
LEVELS = ROOT / "cinnamon_modules" / "levels_games.py"
DASHBOARD = ROOT / "dashboard.py"
COMMUNITY = ROOT / "cinnamon_modules" / "community_interactions.py"


class PollSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.levels = LEVELS.read_text(encoding="utf-8")
        cls.dashboard = DASHBOARD.read_text(encoding="utf-8")
        cls.community = COMMUNITY.read_text(encoding="utf-8")

    def test_single_existing_poll_command_is_preserved(self):
        self.assertIn('@bot.tree.command(name="poll"', self.levels)
        self.assertNotIn('poll_group = app_commands.Group(name="poll"', self.community)
        self.assertIn("class PollView", self.levels)

    def test_poll_options_and_duration_are_validated(self):
        self.assertIn("app_commands.Range[int, 1, 10080]", self.levels)
        self.assertIn("Poll options must be unique", self.levels)

    def test_vote_is_saved_before_message_is_edited_and_rolls_back_on_failure(self):
        callback = self.levels[self.levels.index("class PollView"):self.levels.index("async def finish_poll")]
        self.assertLess(callback.index("await bd_save_data()"), callback.index("interaction.edit_original_response"))
        self.assertIn("before_votes", callback)
        self.assertIn("Your vote couldn't be saved", callback)

    def test_poll_closure_is_persisted_before_results_are_published(self):
        finalizer = self.levels[self.levels.index("async def finish_poll"):self.levels.index('@bot.tree.command(name="poll"')]
        self.assertLess(finalizer.index("await bd_save_data()"), finalizer.index("await message.edit"))
        self.assertIn("poll remains active", finalizer)

    def test_persistent_poll_view_is_registered_after_reconnect(self):
        self.assertIn("restore_persistent_poll_view", self.levels)
        self.assertIn("bot.add_view(PollView())", self.levels)
        self.assertIn("_POLL_VIEW_REGISTERED", self.levels)

    def test_dashboard_can_create_list_and_close_polls(self):
        for action in ("community_poll_create", "community_poll_close"):
            self.assertIn(action, self.dashboard)
        self.assertIn("state.get(\"PollView\")", self.dashboard)
        self.assertIn("state.get(\"finish_poll\")", self.dashboard)
        self.assertIn("active_polls", self.dashboard)


if __name__ == "__main__":
    unittest.main()
