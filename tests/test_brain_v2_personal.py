"""Cinnamon Brain v2 offline tests — member-controlled utilities.

No network connections, Discord login, Gemini calls, private user data or
production storage are required to run these checks.
"""
import ast
import asyncio
import copy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

from cinnamon_modules.brain_member_v2 import (
    PersonalSettingError, parse_timezone_setting,
    format_timezone_offset, due_today,
)
from cinnamon_modules.brain_memory import (
    MemoryValidationError, validate_preference,
)

ROOT = Path(__file__).resolve().parents[1]


def runtime_functions(path, names, namespace):
    root = ROOT / "cinnamon_modules" / path
    tree = ast.parse(root.read_text(encoding="utf-8"))
    functions = [n for n in tree.body
                 if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                 and n.name in names]
    assert len(functions) == len(names), (path, names)
    exec(compile(ast.Module(body=functions, type_ignores=[]),
                 str(root), "exec"), namespace)
    return namespace


class TimezoneTests(unittest.TestCase):
    def test_fixed_offsets_are_explicit_and_normalized(self):
        self.assertEqual(parse_timezone_setting("UTC+05:30"), 330)
        self.assertEqual(parse_timezone_setting("utc-04:00"), -240)
        self.assertEqual(parse_timezone_setting("UTC"), 0)
        self.assertEqual(parse_timezone_setting("UTC+5:30"), 330)
        self.assertEqual(parse_timezone_setting("UTC-12:00"), -720)
        self.assertEqual(parse_timezone_setting("UTC+14:00"), 840)
        self.assertIsNone(parse_timezone_setting("server"))
        self.assertIsNone(parse_timezone_setting("RESET"))
        self.assertEqual(format_timezone_offset(330), "UTC+05:30")
        self.assertEqual(format_timezone_offset(-240), "UTC-04:00")

    def test_ambiguous_and_invalid_offsets_rejected(self):
        for raw in ("", "+05:30", "Asia/Kolkata", "UTC+14:01",
                    "UTC-12:30", "UTC+99:00", "UTC+05:60",
                    "UTC+13:99", "UTC+5:5", "UTC+05:30 and other things"):
            with self.subTest(value=raw):
                with self.assertRaises(PersonalSettingError):
                    parse_timezone_setting(raw)

    def test_today_selection_respects_member_time_zone(self):
        utc_midnight = int(datetime(2026, 11, 1, 0, 5, tzinfo=timezone.utc).timestamp())
        near_utc_midnight = int(datetime(2026, 10, 31, 18, 40, tzinfo=timezone.utc).timestamp())
        # At 18:40 UTC on Oct 31, it is Nov 1 at UTC+5:30.
        entries = [
            {"id": "one", "status": "scheduled", "due_at": utc_midnight},
            {"id": "two", "status": "sent", "due_at": utc_midnight},
            {"id": "three", "status": "scheduled", "due_at": near_utc_midnight},
            {"id": "bad", "status": "scheduled", "due_at": "invalid"},
        ]
        now = datetime(2026, 10, 31, 18, 35, tzinfo=timezone.utc)
        indian = due_today(entries, now=now, offset_minutes=330)
        utc = due_today(entries, now=now, offset_minutes=0)
        self.assertEqual([item["id"] for item in indian], ["three", "one"])
        self.assertEqual([item["id"] for item in utc], ["three"])

    def test_today_requires_time_zone_aware_now(self):
        with self.assertRaises(ValueError):
            due_today([], now=datetime(2026, 10, 31), offset_minutes=330)


class SettingsStorageTests(unittest.IsolatedAsyncioTestCase):
    def runtime(self, *, saved=True):
        async def save_data():
            return saved
        ns = {
            "advanced_features_data": {},
            "CINNAMON_TIMEZONE_OFFSET_MINUTES": 330,
            "_CR_LOCK": asyncio.Lock(),
            "bd_save_data": save_data,
        }
        return runtime_functions("cinnamon_reminders.py",
                                 {"_cr_server", "_cr_member",
                                  "_cr_offset", "_cr_set_offset"}, ns)

    async def test_setting_is_private_and_can_be_reset(self):
        ns = self.runtime()
        self.assertEqual(ns["_cr_offset"](1, 10), 330)
        self.assertTrue(await ns["_cr_set_offset"](1, 10, -240))
        self.assertEqual(ns["_cr_offset"](1, 10), -240)
        self.assertEqual(ns["_cr_offset"](1, 11), 330)
        self.assertEqual(ns["_cr_offset"](2, 10), 330)
        self.assertTrue(await ns["_cr_set_offset"](1, 10, None))
        self.assertEqual(ns["_cr_offset"](1, 10), 330)

    async def test_storage_failure_rolls_back_timezone_update(self):
        ns = self.runtime(saved=False)
        self.assertFalse(await ns["_cr_set_offset"](1, 10, 60))
        self.assertEqual(ns["_cr_offset"](1, 10), 330)


class SnoozeTests(unittest.IsolatedAsyncioTestCase):
    def runtime(self, *, saved=True, now=1000000):
        async def save_data():
            return saved
        ns = {
            "advanced_features_data": {},
            "_CR_LOCK": asyncio.Lock(),
            "_cr_time": SimpleNamespace(time=lambda: now),
            "bd_save_data": save_data,
        }
        ns = runtime_functions("cinnamon_reminders.py",
                               {"_cr_server", "_cr_member", "_cr_snooze"}, ns)
        ns["_cr_member"](1, 10)["abc"] = {
            "id": "abc", "text": "check my quests",
            "due_at": now + 600, "status": "scheduled"
        }
        return ns

    async def test_snooze_only_own_scheduled_reminder(self):
        ns = self.runtime()
        ok, result = await ns["_cr_snooze"](1, 11, "abc", 15)
        self.assertFalse(ok)
        ok, result = await ns["_cr_snooze"](2, 10, "abc", 15)
        self.assertFalse(ok)
        ok, result = await ns["_cr_snooze"](1, 10, "abc", 15)
        self.assertTrue(ok)
        self.assertEqual(ns["_cr_member"](1, 10)["abc"]["due_at"], 1001500)
        self.assertEqual(ns["_cr_member"](1, 10)["abc"]["snoozes"], 1)

    async def test_status_and_time_limits_cannot_be_bypassed(self):
        ns = self.runtime()
        for minutes in (0, -15, 1441, True, 2.5):
            ok, _ = await ns["_cr_snooze"](1, 10, "abc", minutes)
            self.assertFalse(ok)
        ns["_cr_member"](1, 10)["abc"]["status"] = "sending"
        ok, _ = await ns["_cr_snooze"](1, 10, "abc", 15)
        self.assertFalse(ok)

    async def test_failed_save_keeps_original_due_time(self):
        ns = self.runtime(saved=False)
        ok, _ = await ns["_cr_snooze"](1, 10, "abc", 30)
        self.assertFalse(ok)
        self.assertEqual(ns["_cr_member"](1, 10)["abc"]["due_at"], 1000600)
        self.assertNotIn("snoozed_at", ns["_cr_member"](1, 10)["abc"])

    async def test_overdue_but_unsent_reminder_snoozes_from_now(self):
        ns = self.runtime()
        ns["_cr_member"](1, 10)["abc"]["due_at"] = 999000
        ok, _ = await ns["_cr_snooze"](1, 10, "abc", 10)
        self.assertTrue(ok)
        self.assertEqual(ns["_cr_member"](1, 10)["abc"]["due_at"], 1000600)


class MemorySelfEditTests(unittest.IsolatedAsyncioTestCase):
    def runtime(self, *, saved=True):
        async def save_data():
            return saved
        ns = {
            "advanced_features_data": {},
            "_CMEM_LOCK": asyncio.Lock(),
            "_cmem_copy": copy,
            "_cmem_time": SimpleNamespace(time=lambda: 1100000),
            "_cmem_validate": validate_preference,
            "bd_save_data": save_data,
        }
        ns = runtime_functions("cinnamon_memory.py",
                               {"_cmem_root", "_cmem_member", "_cmem_edit"}, ns)
        ns["_cmem_member"](1, 10)["notes"].append(
            {"id": "abcd1234", "category": "stories",
             "detail": "mystery stories", "saved_at": 1000000})
        return ns

    async def test_member_can_correct_own_note_without_owner(self):
        ns = self.runtime()
        ok, _ = await ns["_cmem_edit"](1, 10, "abcd1234", "fantasy stories")
        self.assertTrue(ok)
        self.assertEqual(ns["_cmem_member"](1, 10)["notes"][0]["detail"], "fantasy stories")
        self.assertEqual(ns["_cmem_member"](1, 11)["notes"], [])
        self.assertEqual(ns["_cmem_member"](2, 10)["notes"], [])

    async def test_other_members_and_guilds_cannot_edit(self):
        ns = self.runtime()
        for guild, member in ((2, 10), (1, 11), (2, 11)):
            ok, _ = await ns["_cmem_edit"](guild, member, "abcd1234", "new stuff")
            self.assertFalse(ok)
        self.assertEqual(ns["_cmem_member"](1, 10)["notes"][0]["detail"], "mystery stories")

    async def test_edit_withdraws_pending_ticket_and_scrubs_old_text(self):
        ns = self.runtime()
        tickets = ns["_cmem_root"](1)["tickets"]
        tickets["ticket1"] = {
            "uid": 10, "note_id": "abcd1234", "status": "open",
            "original": "mystery stories", "detail": "other story",
        }
        ok, _ = await ns["_cmem_edit"](1, 10, "abcd1234", "adventure stories")
        self.assertTrue(ok)
        self.assertEqual(tickets["ticket1"]["status"], "withdrawn")
        self.assertEqual(tickets["ticket1"]["original"], "")
        self.assertEqual(tickets["ticket1"]["detail"], "")

    async def test_validation_rejects_sensitive_details(self):
        ns = self.runtime()
        with self.assertRaises(MemoryValidationError):
            await ns["_cmem_edit"](1, 10, "abcd1234", "my password is SECRET")
        self.assertEqual(ns["_cmem_member"](1, 10)["notes"][0]["detail"], "mystery stories")

    async def test_failed_save_restores_note_and_ticket(self):
        ns = self.runtime(saved=False)
        ticket = {"uid": 10, "note_id": "abcd1234", "status": "open",
                  "original": "mystery stories", "detail": "fantasy"}
        ns["_cmem_root"](1)["tickets"]["ticket1"] = ticket
        ok, _ = await ns["_cmem_edit"](1, 10, "abcd1234", "adventure stories")
        self.assertFalse(ok)
        self.assertEqual(ns["_cmem_member"](1, 10)["notes"][0]["detail"], "mystery stories")
        self.assertEqual(ns["_cmem_root"](1)["tickets"]["ticket1"]["status"], "open")


if __name__ == "__main__":
    unittest.main()
