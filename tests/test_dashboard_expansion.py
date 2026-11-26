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
        self.assertIn("cinnamon_community_activity_v1", self.source)
        self.assertIn("Seven-day activity", self.source)
        self.assertIn('state.get("PollView")', self.source)
        self.assertIn('state.get("finish_poll")', self.source)

    def test_ticket_dashboard_can_claim_unassign_close_and_reopen(self):
        for action in ("ticket_dashboard_claim", "ticket_dashboard_unclaim",
                       "ticket_dashboard_close", "ticket_dashboard_reopen"):
            self.assertIn(action, self.source)

    def test_new_companion_dashboard_page_does_not_touch_wildlands(self):
        start = self.source.index("def _companions(guild, state):")
        end = self.source.index("def _community(guild,state):", start)
        self.assertNotIn("wildlands_", self.source[start:end])

    def test_public_appeal_portal_requires_discord_oauth_but_allows_former_members(self):
        self.assertIn('def appeal_portal_login(guild_id, token):', self.source)
        self.assertIn('"scope": "identify"', self.source)
        self.assertIn('def appeal_portal_form(guild_id, token):', self.source)
        form_start = self.source.index("def appeal_portal_form(guild_id, token):")
        form_end = self.source.index("def _analytics(guild, state):", form_start)
        form_source = self.source[form_start:form_end]
        self.assertIn('__import__("discord").Object(id=int(user_id))', form_source)
        self.assertNotIn('guild.fetch_member', form_source)
        self.assertIn('_check_appeal_csrf()', form_source)
        self.assertIn('_appeal_portal_config(guild_id, token)', self.source)

    def test_appeal_portal_uses_shared_limits_and_private_submission_service(self):
        self.assertIn('_state().get("submit_moderation_appeal")', self.source)
        self.assertIn('async def _mc_submit_appeal_web(guild, user, details):', (ROOT / "cinnamon_modules" / "moderation_controls.py").read_text(encoding="utf-8"))
        self.assertIn('appeal_public_channel_id', self.source)
        self.assertIn('appeal_channel_id', self.source)
        self.assertIn('class ModerationAppealPortalView', (ROOT / "cinnamon_modules" / "moderation_controls.py").read_text(encoding="utf-8"))
        self.assertIn('appeal_portal_publish', self.source)
        self.assertIn('appeal_portal_rotate', self.source)

    def test_portal_oauth_callback_preserves_appeal_flow(self):
        self.assertIn('portal_flow=session.pop("appeal_oauth",None)', self.source)
        self.assertIn('session["appeal_sid"]=sid', self.source)
        self.assertIn('The previous public link has been revoked.', self.source)


if __name__ == "__main__":
    unittest.main()
