"""Regression checks for moderation controls and security safeguards."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTROLS = ROOT / "cinnamon_modules" / "moderation_controls.py"
SECURITY = ROOT / "cinnamon_modules" / "security_guard.py"
GENERAL = ROOT / "cinnamon_modules" / "general_moderation.py"
SETUP = ROOT / "cinnamon_modules" / "server_setup.py"
MAIN = ROOT / "main.py"


class ModerationExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controls = CONTROLS.read_text(encoding="utf-8")
        cls.security = SECURITY.read_text(encoding="utf-8")
        cls.general = GENERAL.read_text(encoding="utf-8")
        cls.setup = SETUP.read_text(encoding="utf-8")
        cls.main = MAIN.read_text(encoding="utf-8")

    def test_private_mod_notes_and_appeals_are_persistent(self):
        self.assertIn('name="modnote"', self.controls)
        self.assertIn('name="appeal"', self.controls)
        self.assertIn("moderate_members=True", self.controls)
        self.assertIn("appeal_channel_id", self.controls)
        self.assertIn("private so member details are not exposed", self.controls)
        self.assertIn("await bd_save_data()", self.controls)
        self.assertIn("_mc_decide_appeal", self.controls)
        self.assertIn("You already have a pending appeal", self.controls)
        self.assertIn("up to two appeals per server every 24 hours", self.controls)
        self.assertIn("Moderation appeal decision", self.controls)
        self.assertIn("Moderation appeal submitted", self.controls)

    def test_verification_autorole_and_onboarding_exist(self):
        self.assertIn('name="verification"', self.controls)
        self.assertIn("class CinnamonVerificationView", self.controls)
        self.assertIn('name="autorole"', self.controls)
        self.assertIn('name="onboarding"', self.controls)
        self.assertIn("on_member_join", self.controls)

    def test_anti_spam_is_configurable_and_disabled_by_default(self):
        self.assertIn('"antispam_enabled", False', self.security)
        self.assertIn('name="antispam"', self.security)
        self.assertIn("member.timeout", self.security)
        self.assertIn("antispam_threshold", self.security)

    def test_anti_nuke_uses_audit_log_burst_alerts_without_auto_punishment(self):
        self.assertIn('name="antinuke"', self.security)
        self.assertIn("guild.audit_logs", self.security)
        self.assertIn("Possible server nuke activity", self.security)
        self.assertIn("will not automatically punish administrators", self.security)

    def test_temporary_roles_are_persisted_and_expire_automatically(self):
        self.assertIn('name="temprole"', self.general)
        self.assertIn('name="grant"', self.general)
        self.assertIn('name="revoke"', self.general)
        self.assertIn("_TEMP_ROLE_KEY", self.general)
        self.assertIn("_temporary_role_expiry_loop", self.general)
        self.assertIn("expires_at", self.general)
        self.assertIn("role >= me.top_role", self.general)
        self.assertIn("await bd_save_data()", self.general)
    def test_antiraid_has_defaults_and_burst_alert_cooldown(self):
        self.assertIn('DEFAULT_ANTIRAID = {"enabled": False', self.setup)
        self.assertIn("_ANTIRAID_ALERT_COOLDOWN", self.setup)
        self.assertIn("now - last_alert < 300", self.setup)
    def test_modules_are_loaded_and_wildlands_is_not_referenced(self):
        self.assertIn('"moderation_controls.py"', self.main)
        self.assertIn('"security_guard.py"', self.main)
        self.assertNotIn("wildlands_", self.controls)
        self.assertNotIn("wildlands_", self.security)


if __name__ == "__main__":
    unittest.main()
