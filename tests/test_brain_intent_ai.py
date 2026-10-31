"""Tests for the bounded Gemini intent suggestion fallback."""
import asyncio
import json
import unittest

from cinnamon_modules.brain_intent import IntentPlan, plan_intent
from cinnamon_modules.brain_intent_ai import parse_intent_suggestion, classify_intent_with_fallback


class IntentSuggestionTests(unittest.TestCase):
    def test_parse_valid_suggestion(self):
        item = parse_intent_suggestion(json.dumps({"intent":"private_data","confidence":0.91,"phrase":"my balance"}))
        self.assertIsNotNone(item)
        self.assertEqual(item.intent, "private_data")
        self.assertEqual(item.confidence, 0.91)

    def test_parse_fenced_json(self):
        fence = chr(96) * 3
        raw = fence + "json\n" + json.dumps({"intent":"help","confidence":0.9,"phrase":"help"}) + "\n" + fence
        item = parse_intent_suggestion(raw)
        self.assertIsNotNone(item)
        self.assertEqual(item.intent, "help")

    def test_reject_invalid_unknown_low_confidence_and_oversized(self):
        self.assertIsNone(parse_intent_suggestion("not json"))
        self.assertIsNone(parse_intent_suggestion('{"intent":"execute_shell","confidence":1,"phrase":"x"}'))
        self.assertIsNone(parse_intent_suggestion('{"intent":"private_data","confidence":0.4,"phrase":"balance"}'))
        self.assertIsNone(parse_intent_suggestion('{"intent":"help","confidence":0.9,"phrase":"' + ("x" * 300) + '"}'))

    def test_fallback_only_called_for_chat_plan(self):
        async def run():
            calls = []
            async def model(prompt):
                calls.append(prompt)
                return '{"intent":"private_data","confidence":0.95,"phrase":"my balance"}'
            deterministic = plan_intent("finances are confusing")
            result = await classify_intent_with_fallback("finances are confusing", deterministic_plan=deterministic, model_call=model)
            self.assertEqual(deterministic.intent, "chat")
            self.assertEqual(result.intent, "private_data")
            self.assertEqual(len(calls), 1)
            known = IntentPlan("help", "deterministic", ("help", "chat"))
            self.assertIs(await classify_intent_with_fallback("help me", deterministic_plan=known, model_call=model), known)
            self.assertEqual(len(calls), 1)
        asyncio.run(run())

    def test_model_failure_returns_deterministic_plan(self):
        async def run():
            original = plan_intent("finances are confusing")
            async def broken(prompt):
                raise TimeoutError("offline")
            self.assertIs(await classify_intent_with_fallback("finances are confusing", deterministic_plan=original, model_call=broken), original)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
