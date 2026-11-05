"""Tests for the shared fail-closed Brain policy decision record."""
import unittest

from cinnamon_modules.brain_route_decision import (
    DecisionInput, DecisionKind, decide,
)


class BrainRouteDecisionTests(unittest.TestCase):
    def test_chat_responds_only_when_enabled_and_not_serious_suppressed(self):
        self.assertEqual(decide(DecisionInput("chat")).kind, DecisionKind.RESPOND)
        self.assertEqual(decide(DecisionInput("chat", feature_enabled=False)).kind,
                         DecisionKind.WAIT)
        self.assertEqual(decide(DecisionInput("chat", serious=True)).kind,
                         DecisionKind.RESPOND_GENTLY)

    def test_action_requires_permission_and_confirmation(self):
        self.assertEqual(decide(DecisionInput("action", permission=False)).kind,
                         DecisionKind.REFUSE)
        self.assertEqual(decide(DecisionInput("action", permission=True)).kind,
                         DecisionKind.CLARIFY)
        self.assertEqual(decide(DecisionInput("action", permission=True,
                                            confirmed=True)).kind,
                         DecisionKind.EXECUTE_CANDIDATE)

    def test_activity_is_wait_by_default_and_fail_closed(self):
        self.assertEqual(decide(DecisionInput("activity")).kind, DecisionKind.WAIT)
        self.assertEqual(decide(DecisionInput("activity", enabled=True,
                                            engaged=True)).kind, DecisionKind.SUGGEST)
        for blocked in (
            DecisionInput("activity", enabled=True, engaged=True, serious=True),
            DecisionInput("activity", enabled=True, engaged=True, quiet=True),
            DecisionInput("activity", enabled=True, engaged=True, storage_ok=False),
        ):
            self.assertEqual(decide(blocked).kind, DecisionKind.WAIT)

    def test_unknown_or_invalid_input_waits(self):
        self.assertEqual(decide(DecisionInput("nonsense")).kind, DecisionKind.WAIT)
        self.assertEqual(decide(None).kind, DecisionKind.WAIT)


if __name__ == "__main__":
    unittest.main()
