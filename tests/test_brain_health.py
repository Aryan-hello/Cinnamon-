import unittest
from types import SimpleNamespace

from cinnamon_modules.brain_health import build_brain_health, command_name_counts


class BrainHealthTests(unittest.TestCase):
    def test_health_checks_include_all_expected_subsystems(self):
        checks = build_brain_health(
            storage_ready=True, model_configured=True,
            modules={name: True for name in ("actions", "help", "memory", "reminders",
                                             "member", "incidents", "activity")})
        self.assertTrue(all(check.ready for check in checks))
        self.assertEqual(len(checks), 10)

    def test_missing_storage_and_duplicate_commands_are_visible(self):
        checks = build_brain_health(storage_ready=False, model_configured=False,
                                    modules={}, duplicate_commands={"help": 2})
        by_name = {check.name: check for check in checks}
        self.assertFalse(by_name["Persistent storage"].ready)
        self.assertFalse(by_name["Gemini configuration"].ready)
        self.assertFalse(by_name["Slash command names"].ready)
        self.assertIn("help×2", by_name["Slash command names"].detail)

    def test_duplicate_names_are_counted_without_command_details(self):
        commands = [SimpleNamespace(name="help"), SimpleNamespace(name="help"),
                    SimpleNamespace(name="ping")]
        self.assertEqual(command_name_counts(commands), {"help": 2})


if __name__ == "__main__":
    unittest.main()
