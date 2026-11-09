"""Dependency-free checks for Cinnamon's Discord presentation contracts.

Live Discord rendering still needs a staging server; these tests cover pure
formatting and prevent regressions at the components/message boundary.
"""
import ast
import datetime
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "cinnamon_modules"


def load_function(path, name, namespace):
    root = ast.parse(path.read_text(encoding="utf-8"))
    body = [node for node in root.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    if len(body) != 1:
        raise AssertionError(f"Expected one function named {name} in {path}")
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


class PresentationTests(unittest.TestCase):
    def test_module_order(self):
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertLess(main.index('"ui_system.py"'), main.index('"economy.py"'))
        self.assertLess(main.index('"ui_system.py"'), main.index('"quests.py"'))
        self.assertLess(main.index('"ui_system.py"'), main.index('"achievements.py"'))

    def test_progress_clamps_and_shows_numbers(self):
        progress = load_function(MODULES / "ui_system.py", "cinnamon_ui_progress", {})
        self.assertIn("5/10", progress(5, 10))
        self.assertEqual(progress(50, 10).count("▰"), 8)
        self.assertEqual(progress(-2, 10).count("▰"), 0)
        self.assertIn("0/1", progress(0, 0))

    def test_literal_text_is_bounded_and_escaped(self):
        fake_utils = SimpleNamespace(
            escape_markdown=lambda s: s.replace("*", "\\*"),
            escape_mentions=lambda s: s.replace("@", "@\\u200b"),
        )
        literal = load_function(MODULES / "ui_system.py", "cinnamon_ui_literal",
                                {"discord": SimpleNamespace(utils=fake_utils)})
        control = chr(1)
        self.assertNotIn(control, literal("bad" + control + "text"))
        self.assertEqual(literal("a" * 60, 20), "a" * 19 + "…")
        self.assertIn("\\*", literal("*sale*", 100))

    def test_quest_combo_progress_is_not_stuck_at_zero(self):
        values = load_function(MODULES / "quests.py", "_quest_ui_values", {})
        self.assertEqual(values(
            {"needs": {"pet": 3, "feed": 1}}, {"pet": 2, "feed": 1}), (3, 4))
        self.assertEqual(values(
            {"needs": {"pet": 3, "feed": 1}}, {"pet": 99, "feed": 12}), (4, 4))
        self.assertEqual(values({"target": 5}, {"count": 3}), (3, 5))
        self.assertEqual(values({"target": 5}, {"count": -2}), (0, 5))

    def test_reset_timestamps_use_server_timezone(self):
        timezone = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        fake = datetime.datetime(2026, 10, 29, 19, 32, tzinfo=timezone)
        reset = load_function(
            MODULES / "quests.py", "_quest_next_reset",
            {"cinnamon_now": lambda: fake, "datetime": datetime})
        daily = int(reset("daily").split(":")[1])
        weekly = int(reset("weekly").split(":")[1])
        self.assertEqual(
            datetime.datetime.fromtimestamp(daily, tz=timezone).isoformat(),
            "2026-10-30T00:00:00+05:30")
        self.assertEqual(
            datetime.datetime.fromtimestamp(weekly, tz=timezone).date().isoformat(),
            "2026-11-02")

    def test_active_collections_use_components_v2_without_embeds(self):
        achievements = (MODULES / "achievements.py").read_text()
        quests = (MODULES / "quests.py").read_text()
        economy = (MODULES / "economy.py").read_text()
        self.assertIn("view=CinnamonAchievementCollection(", achievements)
        self.assertIn("view=CinnamonQuestBoard(", quests)
        self.assertIn("view=CinnamonInventoryView(", economy)
        self.assertNotIn(
            "edit_message(embed=inventory_embed(", economy.split("class CinnamonShopView")[1].split("class InventoryPageView")[0])
        self.assertIn("_CINNAMON_SHOP_LOCKS", economy)
        self.assertIn("await interaction.response.defer()", economy)

    def test_story_resume_keeps_its_branch_buttons(self):
        story = (MODULES / "cinnamon_adventure_story.py").read_text()
        self.assertIn("_WLSChoiceView(interaction.user.id, idx, rec.get('branch'))", story)
        self.assertIn("cinnamon_ui_card(", story)

    def test_general_notices_use_shared_presentation(self):
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('embed = cinnamon_ui_card("Notice"', main)
        self.assertIn('allowed_mentions=mentions', main)
        self.assertIn('CINNAMON_EMBED_COLOR = 0xD97732', main)

    def test_branch_cleanup_only_removes_integrated_work(self):
        workflow = (ROOT / ".github/workflows/remove-merged-branches.yml").read_text()
        self.assertIn("Boolean(pr.merged_at)", workflow)
        self.assertIn("pr.head.sha === branch.commit.sha", workflow)
        self.assertIn("compare.data.ahead_by === 0", workflow)
        self.assertIn("branch.name === main || branch.protected", workflow)
        self.assertIn("contents: write", workflow)

    def test_fishing_displays_text_progress(self):
        game = (MODULES / "cinnamon_fishing_game.py").read_text()
        self.assertIn("cinnamon_ui_progress(tension, 100", game)
        self.assertIn("cinnamon_ui_progress(state['progress'], state['goal']", game)


if __name__ == "__main__":
    unittest.main()
