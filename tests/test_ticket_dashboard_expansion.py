"""Regression coverage for ticket persistence and dashboard controls."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TICKETS = ROOT / "cinnamon_modules" / "ticket_system.py"
DASHBOARD = ROOT / "dashboard.py"


class TicketDashboardExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tickets = TICKETS.read_text(encoding="utf-8")
        cls.dashboard = DASHBOARD.read_text(encoding="utf-8")

    def test_ticket_ratings_assignments_priorities_and_notes_rollback_on_save_failure(self):
        self.assertIn("before_ticket = _copy.deepcopy(ticket)", self.tickets)
        self.assertIn("Your rating could not be saved", self.tickets)
        self.assertIn("Assignment could not be saved", self.tickets)
        self.assertIn("Priority could not be saved", self.tickets)
        self.assertIn("The private note could not be saved", self.tickets)

    def test_close_and_reopen_require_durable_state_before_confirmation(self):
        self.assertIn("Ticket closure could not be saved", self.tickets)
        self.assertIn("Ticket reopen could not be saved", self.tickets)
        self.assertIn("await bd_save_data()", self.tickets)

    def test_dashboard_can_search_assign_and_prioritize_active_tickets(self):
        for action in ("ticket_dashboard_assign", "ticket_dashboard_priority"):
            self.assertIn(action, self.dashboard)
        self.assertIn("ticket_q", self.dashboard)
        self.assertIn("assigned_to", self.dashboard)
        self.assertIn("priority_order", self.dashboard)
        self.assertIn("Assign tickets only to configured ticket staff", self.dashboard)

    def test_ticket_dashboard_exposes_transcript_and_rating_controls(self):
        self.assertIn("transcript_on_close", self.dashboard)
        self.assertIn("rating_enabled", self.dashboard)
        self.assertIn("ticket_panel_publish", self.dashboard)
        self.assertIn("ticket_dashboard_reopen", self.dashboard)

    def test_wildlands_is_not_part_of_ticket_expansion(self):
        self.assertNotIn("wildlands_", self.tickets)


if __name__ == "__main__":
    unittest.main()
