"""Regression tests for daily and weekly quest rotation boundaries."""
import ast
import asyncio
from datetime import datetime, timedelta, timezone
import random
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QuestRotationTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_rotation_preserves_weekly_progress_and_weekly_rotation_resets(self):
        source = (ROOT / "cinnamon_modules" / "quests.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        node = next(
            item for item in tree.body
            if isinstance(item, ast.FunctionDef) and item.name == "_ensure_rolls"
        )
        current = [datetime(2026, 11, 26, 12, tzinfo=timezone.utc)]
        quest_data = {}
        daily = {f"d{i}": {"name": f"Daily {i}"} for i in range(8)}
        weekly = {f"w{i}": {"name": f"Weekly {i}"} for i in range(8)}

        def guild_state(guild_id):
            state = quest_data.setdefault(int(guild_id), {})
            state.setdefault("users", {})
            return state

        async def send_log(*args, **kwargs):
            return None

        namespace = {
            "_guild": guild_state,
            "_today": lambda: current[0].date().isoformat(),
            "_week": lambda: current[0].date().isocalendar().year * 100 + current[0].date().isocalendar().week,
            "DAILY_QUESTS": daily,
            "WEEKLY_QUESTS": weekly,
            "asyncio": asyncio,
            "random": random.Random(42),
            "send_log": send_log,
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "quests.py", "exec"), namespace)
        ensure = namespace["_ensure_rolls"]

        state = guild_state(1)
        state["users"]["7"] = {
            "daily": {"old_daily": {"count": 2}},
            "weekly": {"old_weekly": {"count": 4}},
            "week_counters": {"work": 6},
            "daily_completed_week": 3,
            "completed_history": [{"scope": "daily", "id": "finished"}],
        }
        ensure(1)
        await asyncio.sleep(0)
        first_daily = list(state["daily_ids"])
        first_weekly = list(state["weekly_ids"])
        self.assertEqual(len(first_daily), 5)
        self.assertEqual(len(first_weekly), 5)
        self.assertEqual(state["users"]["7"]["daily"], {})
        self.assertEqual(state["users"]["7"]["weekly"], {})
        self.assertEqual(state["users"]["7"]["completed_history"], [{"scope": "daily", "id": "finished"}])

        state["users"]["7"]["daily"]["progress"] = {"count": 2}
        state["users"]["7"]["weekly"]["progress"] = {"count": 4}
        state["users"]["7"]["daily_completed_week"] = 3
        ensure(1)
        self.assertEqual(state["daily_ids"], first_daily)
        self.assertEqual(state["weekly_ids"], first_weekly)
        self.assertEqual(state["users"]["7"]["daily"]["progress"]["count"], 2)

        current[0] += timedelta(days=1)
        ensure(1)
        await asyncio.sleep(0)
        self.assertEqual(state["users"]["7"]["daily"], {})
        self.assertEqual(state["users"]["7"]["weekly"]["progress"]["count"], 4)
        self.assertEqual(state["users"]["7"]["daily_completed_week"], 3)

        # Advance to the next Monday: the weekly key changes and weekly counters reset.
        while current[0].weekday() != 0:
            current[0] += timedelta(days=1)
        ensure(1)
        await asyncio.sleep(0)
        self.assertEqual(state["users"]["7"]["weekly"], {})
        self.assertEqual(state["users"]["7"]["week_counters"], {})
        self.assertEqual(state["users"]["7"]["daily_completed_week"], 0)
        self.assertEqual(len(state["weekly_ids"]), 5)

    def test_reset_worker_is_started_by_core_events_after_ready(self):
        source = (ROOT / "cinnamon_modules" / "core_events.py").read_text(encoding="utf-8")
        self.assertIn("quest_reset_loop.is_running()", source)
        self.assertIn("quest_reset_loop.start()", source)


if __name__ == "__main__":
    unittest.main()
