"""Offline guards for community polls, events and anonymous confessions."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "cinnamon_modules" / "community_interactions.py"
MAIN = ROOT / "main.py"


class CommunityInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MODULE.read_text(encoding="utf-8")
        cls.main = MAIN.read_text(encoding="utf-8")

    def test_polls_have_persistent_voting_and_close_controls(self):
        self.assertIn('name="poll"', self.source)
        self.assertIn('name="poll-close"', self.source)
        self.assertIn('name="poll-results"', self.source)
        self.assertIn("class CommunityPollView", self.source)
        self.assertIn("record.setdefault(\"votes\", {})", self.source)
        self.assertIn("await bd_save_data()", self.source)

    def test_events_have_timezone_validation_rsvp_and_reminders(self):
        self.assertIn('name="event"', self.source)
        self.assertIn("start.tzinfo is None", self.source)
        self.assertIn("class CommunityEventView", self.source)
        self.assertIn("_community_event_reminders", self.source)
        self.assertIn("reminders_sent", self.source)

    def test_confessions_are_anonymous_and_moderatable(self):
        self.assertIn('name="confess"', self.source)
        self.assertIn('name="confession-settings"', self.source)
        self.assertIn("class ConfessionModerationView", self.source)
        self.assertIn('"author_id": int(interaction.user.id)', self.source)
        self.assertIn("Anonymous to server members", self.source)
        self.assertIn("Manage Messages permission is required", self.source)

    def test_module_is_loaded_without_wildlands_references(self):
        self.assertIn('"community_interactions.py"', self.main)
        self.assertNotIn("wildlands_", self.source)


if __name__ == "__main__":
    unittest.main()
