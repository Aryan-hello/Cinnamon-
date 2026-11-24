"""Dashboard expansion regression checks."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard.py"
RUNTIME = ROOT / "cinnamon_modules" / "dashboard_runtime.py"


class DashboardExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = DASHBOARD.read_text(encoding="utf-8")
        cls.runtime = RUNTIME.read_text(encoding="utf-8")

    def test_companion_page_is_registered_and_reads_persistent_profiles(self):
        self.assertIn("def _companions(guild, state):", self.source)
        self.assertIn('"companions":_companions', self.source)
        self.assertIn("companion_profiles_v1", self.source)
        self.assertIn('advanced.get("companion_profiles_v1", {})', self.source)
        self.assertIn("Companions", self.source)

    def test_community_settings_and_event_controls_are_wired(self):
        for action in ("community_features_settings", "community_event_create", "community_event_cancel"):
            self.assertIn(action, self.source)
        self.assertIn("CommunityEventView", self.runtime)
        self.assertIn("starboard_threshold", self.source)
        self.assertIn("confession_channel_id", self.source)

    def test_security_and_onboarding_controls_are_wired(self):
        for action in ("security_settings", "moderation_controls_settings", "verification_publish", "appeal_settings", "dashboard_appeal_review"):
            self.assertIn(action, self.source)
        self.assertIn("CinnamonVerificationView", self.runtime)
        self.assertIn("antispam_enabled", self.source)
        self.assertIn("antinuke_enabled", self.source)

    def test_community_dashboard_can_create_and_close_existing_polls(self):
        self.assertIn("community_poll_create", self.source)
        self.assertIn("community_poll_close", self.source)
        self.assertIn("state.get(\\"PollView\\")", self.source)
        self.assertIn("state.get(\\"finish_poll\\")", self.source)

    def test_ticket_dashboard_can_claim_unassign_close_and_reopen(self):
        for action in ("ticket_dashboard_claim", "ticket_dashboard_unclaim",
                       "ticket_dashboard_close", "ticket_dashboard_reopen"):
            self.assertIn(action, self.source)

    def test_new_companion_dashboard_page_does_not_touch_wildlands(self):
        start = self.source.index("def _companions(guild, state):")
        end = self.source.index("def _community(guild,state):", start)
        self.assertNotIn("wildlands_", self.source[start:end])


if __name__ == "__main__":
    unittest.main()
