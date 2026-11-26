"""Regression checks for removal of the old quest currency and XP level payouts."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function_source(path, name):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return ast.unparse(node)


class QuestCurrencyRemovalTests(unittest.TestCase):
    def test_quest_currency_and_redemption_command_are_gone(self):
        quests = (ROOT / "cinnamon_modules/quests.py").read_text(encoding="utf-8")
        dashboard = (ROOT / "dashboard.py").read_text(encoding="utf-8")
        core_events = (ROOT / "cinnamon_modules/core_events.py").read_text(encoding="utf-8")

        for removed in ("QUEST_SHOP", "questshop_cmd", "Quest Points"):
            self.assertNotIn(removed, quests)
            self.assertNotIn(removed, dashboard)
        self.assertNotIn("questshop", core_events)

        # The only remaining qp references are intentional one-time legacy-data cleanup.
        for line in quests.splitlines():
            if "qp" in line.lower():
                self.assertIn('pop("qp", None)', line)

    def test_legacy_qp_is_stripped_from_loaded_quest_records(self):
        user = function_source("cinnamon_modules/quests.py", "_user")
        restore = (ROOT / "cinnamon_modules/economy.py").read_text(encoding="utf-8")
        migration = function_source("cinnamon_modules/quests.py", "migrate_legacy_quest_currency")
        on_ready = function_source("cinnamon_modules/core_events.py", "on_ready")
        self.assertIn("pop('qp', None)", user)
        self.assertIn("pop('qp', None)", migration)
        self.assertIn("migrate_legacy_quest_currency", on_ready)
        self.assertIn('snap_quests.pop("qp", None)', restore)

    def test_every_xp_reward_path_checks_for_level_catnip(self):
        checks = [
            ("cinnamon_modules/levels_games.py", "award_xp", "_claim_level_rewards"),
            ("cinnamon_modules/quests.py", "_grant_quest_xp", "_claim_level_rewards"),
            ("cinnamon_modules/core_events.py", "_change_xp_prefix", "_claim_level_rewards_for_xp"),
            ("cinnamon_modules/core_events.py", "add_xp_cmd", "_claim_level_rewards_for_xp"),
            ("cinnamon_modules/achievements.py", "_add_xp", "_claim_achievement_level_rewards"),
            ("cinnamon_modules/achievements.py", "_unlock", "_claim_achievement_level_rewards"),
            ("cinnamon_modules/achievements.py", "_unlock_custom_admin", "_claim_achievement_level_rewards"),
        ]
        for path, function, helper in checks:
            with self.subTest(path=path, function=function):
                self.assertIn(helper, function_source(path, function))

    def test_rank_page_distinguishes_pending_from_claimed_rewards(self):
        levels = (ROOT / "cinnamon_modules/levels_games.py").read_text(encoding="utf-8")
        self.assertIn("Pending level rewards", levels)
        self.assertIn("All earned level rewards have been claimed.", levels)


if __name__ == "__main__":
    unittest.main()
