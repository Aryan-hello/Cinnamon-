"""Tests for deterministic Brain v2 intent routing."""
import unittest

from cinnamon_modules.brain_intent import plan_intent


class IntentPlannerTests(unittest.TestCase):
    def test_reminder_requests_are_routed_before_chat(self):
        for text in ("remind me to study in 20 minutes",
                     "Cinnamon, set a reminder for tomorrow",
                     "show my reminders", "my reminders"):
            self.assertEqual(plan_intent(text).intent, "reminder")

    def test_memory_requests_are_routed_without_saving_anything(self):
        for text in ("remember that I like strategy games",
                     "what do you remember about me?",
                     "turn my memory off",
                     "forget my saved preference",
                     "show my notes",
                     "Cinnamon, please save that I like mystery stories"):
            self.assertEqual(plan_intent(text).intent, "memory")

    def test_help_questions_and_slash_explanations_are_routed_to_help(self):
        self.assertEqual(plan_intent("how do I fish?").intent, "help")
        self.assertEqual(plan_intent("explain /quests progress").intent, "help")
        self.assertEqual(plan_intent("show my progress").intent, "help")
        self.assertEqual(plan_intent("my day").intent, "help")

    def test_action_like_requests_never_fall_through_as_ordinary_chat(self):
        for text in ("add 500 Catnip to @member", "mute @member for 5 minutes",
                     "kick @member", "delete the channel"):
            plan = plan_intent(text)
            self.assertEqual(plan.intent, "action")
            self.assertEqual(plan.route_order[0], "action")

    def test_casual_chat_remains_chat(self):
        plan = plan_intent("I had a nice day and played a game.")
        self.assertEqual(plan.intent, "chat")
        self.assertEqual(plan.route_order[-1], "chat")

    def test_plans_are_bounded_and_never_authorize(self):
        plan = plan_intent("Cinnamon, add 500 Catnip to @member")
        self.assertEqual(plan.intent, "action")
        self.assertEqual(plan.route_order[-1], "chat")
        self.assertFalse(hasattr(plan, "authorized"))
        self.assertFalse(hasattr(plan, "execute"))


if __name__ == "__main__":
    unittest.main()
