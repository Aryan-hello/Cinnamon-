"""Regression checks for bounded recurring Cinnamon reminders."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "cinnamon_modules" / "cinnamon_reminders.py"


class RecurringReminderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MODULE.read_text(encoding="utf-8")

    def test_recurring_command_is_available_and_bounded(self):
        self.assertIn('name="repeat"', self.source)
        self.assertIn("interval_hours: app_commands.Range[int, 1, 720]", self.source)
        self.assertIn("occurrences: app_commands.Range[int, 2, 100]", self.source)

    def test_repeat_schedule_is_durably_saved_before_confirmation(self):
        helper = self.source[self.source.index("async def _cr_schedule_repeat"):self.source.index("async def _cr_cancel")]
        self.assertIn('"repeat_seconds"', helper)
        self.assertIn('"repeat_remaining"', helper)
        self.assertLess(helper.index("await bd_save_data()"), helper.index('return item, ""'))

    def test_successful_delivery_schedules_next_occurrence(self):
        delivery = self.source[self.source.index("async def _cr_deliver"):self.source.index("async def _cr_tick")]
        self.assertIn('item["status"] = "scheduled"', delivery)
        self.assertIn('item["due_at"]', delivery)
        self.assertIn("repeat_remaining", delivery)
        self.assertIn('"uncertain"', delivery)

    def test_cancel_and_list_cover_recurring_reminders(self):
        self.assertIn("async def _cr_cancel", self.source)
        self.assertIn("repeats every", self.source)
        self.assertIn('name="cancel"', self.source)
        self.assertNotIn("wildlands_", self.source)


if __name__ == "__main__":
    unittest.main()
