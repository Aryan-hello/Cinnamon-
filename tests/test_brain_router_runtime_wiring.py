"""Regression test for Brain router runtime wiring."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BrainRouterRuntimeWiringTests(unittest.TestCase):
    def test_core_events_uses_deterministic_router_and_keeps_private_data_fallback(self):
        source = (ROOT / "cinnamon_modules" / "core_events.py").read_text(encoding="utf-8")
        self.assertIn("from cinnamon_modules.brain_router import classify_intent, Intent", source)
        self.assertIn("route = classify_intent(clean_content)", source)
        self.assertIn('private_redirect = globals().get("_ch_private_data_redirect")', source)
        self.assertIn("route.intent is Intent.ACTION", source)
        self.assertIn("route.intent is Intent.REMINDER", source)


if __name__ == "__main__":
    unittest.main()
