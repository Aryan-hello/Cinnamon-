"""Regression checks for community social features."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "cinnamon_modules" / "community_social.py"
MAIN = ROOT / "main.py"


class CommunitySocialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MODULE.read_text(encoding="utf-8")
        cls.main = MAIN.read_text(encoding="utf-8")

    def test_quote_collection_supports_add_list_and_moderated_remove(self):
        self.assertIn('name="quote"', self.source)
        self.assertIn('name="add"', self.source)
        self.assertIn('name="list"', self.source)
        self.assertIn('name="remove"', self.source)
        self.assertIn("submitted_by", self.source)

    def test_reputation_has_daily_cooldown_and_leaderboard(self):
        self.assertIn('name="rep"', self.source)
        self.assertIn("86400", self.source)
        self.assertIn("rep_scores", self.source)
        self.assertIn("rep_given", self.source)

    def test_team_membership_is_limited_and_owner_managed(self):
        self.assertIn('name="team"', self.source)
        self.assertIn(">= 10", self.source)
        self.assertIn("team_members", self.source)
        self.assertIn("community_team_disband", self.source)

    def test_challenges_count_rate_limited_messages_and_pay_claims_once(self):
        self.assertIn('name="challenge"', self.source)
        self.assertIn("now - last < 60", self.source)
        self.assertIn("claimed", self.source)
        self.assertIn("economy_balances[(gid, uid)] = balance + reward", self.source)
        self.assertIn("bd_save_data()", self.source)

    def test_activity_tracking_and_weekly_recap_are_persistent_and_bounded(self):
        self.assertIn('name="recap"', self.source)
        self.assertIn("cinnamon_community_activity_v1", self.source)
        self.assertIn("@tasks.loop(minutes=1)", self.source)
        self.assertIn("_CS_ACTIVITY_DIRTY", self.source)
        self.assertIn("Activity counts begin when this tracking feature is active", self.source)

    def test_module_is_loaded_and_does_not_touch_wildlands(self):
        self.assertIn('"community_social.py"', self.main)
        self.assertNotIn("wildlands_", self.source)


if __name__ == "__main__":
    unittest.main()
