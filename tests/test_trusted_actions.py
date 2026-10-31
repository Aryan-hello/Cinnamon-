"""Exercise trusted adapter callbacks and real snapshot transactions offline."""
import ast
import asyncio
from collections import defaultdict
import copy
import datetime
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from cinnamon_modules.brain_storage import SnapshotStore, StorageRejected, StorageUncertain


ROOT = Path(__file__).resolve().parents[1]
ADMIN = 111111111111111111
TARGET = 222222222222222222
BOT = 999999999999999999


class Backend:
    durable = True
    def __init__(self, raw=None):
        self.raw, self.mode, self.writes = raw, "ok", 0
        self.entered, self.resume = None, None
    async def read(self):
        return self.raw
    async def compare_and_set(self, expected, candidate):
        self.writes += 1
        if self.entered:
            self.entered.set()
            await self.resume.wait()
        if self.mode == "rejected":
            raise StorageRejected()
        if self.mode == "lost-before":
            raise StorageUncertain()
        if self.raw != expected:
            return False
        self.raw = candidate
        if self.mode == "lost-after":
            raise StorageUncertain()
        return True


class HTTPException(Exception):
    pass


class Forbidden(HTTPException):
    pass


class View:
    def __init__(self, **kwargs):
        self.stopped = False
    def stop(self):
        self.stopped = True


class Member:
    def __init__(self, guild, uid, *, admin=False, mod=False, rank=10, bot=False):
        self.guild, self.id, self.bot = guild, uid, bot
        self.guild_permissions = SimpleNamespace(administrator=admin, moderate_members=mod)
        self.top_role = rank
        self.display_name = f"member-{uid}"
        self.mention = f"<@{uid}>"
        self.calls = []
        self.failure = None
    async def timeout(self, until, *, reason):
        self.calls.append((until, reason))
        if self.failure:
            raise self.failure
    def __str__(self):
        return self.display_name


class Channel:
    id = 20
    def __init__(self):
        self.permissions = SimpleNamespace(view_channel=True, send_messages=True)
    def permissions_for(self, member):
        return self.permissions


class Guild:
    id, owner_id = 10, 777777777777777777
    def __init__(self):
        self.channel = Channel()
        self.me = Member(self, BOT, mod=True, rank=100, bot=True)
        self.members = {ADMIN: Member(self, ADMIN, admin=True, rank=90),
                        TARGET: Member(self, TARGET), BOT: self.me}
        self.fresh = dict(self.members)
        self._roles = {}
    def get_member(self, uid):
        return self.members.get(uid)
    async def fetch_member(self, uid):
        if uid not in self.fresh:
            raise HTTPException()
        return self.fresh[uid]
    async def fetch_roles(self):
        return []
    async def fetch_channel(self, cid):
        if cid != self.channel.id:
            raise HTTPException()
        return self.channel


class Response:
    def __init__(self):
        self.messages, self.deferred, self.edits = [], False, []
    async def send_message(self, content, **kwargs):
        self.messages.append(content)
    async def defer(self, **kwargs):
        self.deferred = True
    async def edit_message(self, **kwargs):
        self.edits.append(kwargs)


class Followup:
    def __init__(self):
        self.messages = []
    async def send(self, content, **kwargs):
        self.messages.append(content)


class SentMessage:
    def __init__(self):
        self.edits = []
    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class Message:
    def __init__(self, guild, author=None, mid=30):
        self.guild, self.channel = guild, guild.channel
        self.author, self.id = author or guild.members[ADMIN], mid
        self.mentions = [guild.members[TARGET]]
        self.reference = None
        self.created_at = datetime.datetime.now(datetime.timezone.utc)
        self.replies = []
    async def reply(self, *args, **kwargs):
        self.replies.append((args, kwargs))
        return SentMessage()


class Embed:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
    def set_footer(self, **kwargs):
        self.footer = kwargs


def adapter_runtime(guild=None):
    guild = guild or Guild()
    balances, features = {(guild.id, TARGET): 100}, {}
    logs = []
    async def log(gid, **kwargs):
        logs.append((gid, kwargs))
    def balance(gid, uid):
        return balances.setdefault((gid, uid), 100)
    def encode():
        return {"economy_balances": {f"{g}:{u}": value for (g, u), value in balances.items()},
                "advanced_features": features}
    ns = {"advanced_features_data": features, "economy_balances": balances,
          "economy_balance": balance, "_bd_encode": encode, "send_log": log,
          "economy_log": log, "disabled_channels": defaultdict(set), "log": Mock(),
          "bot": SimpleNamespace(user=SimpleNamespace(id=BOT), get_guild=lambda gid: guild if gid == guild.id else None),
          "discord": SimpleNamespace(ui=SimpleNamespace(View=View, button=lambda **kw: lambda f: f),
              ButtonStyle=SimpleNamespace(danger=1, secondary=2), Member=Member, Message=Message,
              HTTPException=HTTPException, Forbidden=Forbidden, Embed=Embed,
              AllowedMentions=SimpleNamespace(none=lambda: None))}
    tree = ast.parse((ROOT / "cinnamon_modules/cinnamon_actions.py").read_text())
    body = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            body.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id.startswith("_CA_") for t in node.targets):
            body.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("_ca_"):
            body.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == "_CAConfirm":
            body.append(node)
    exec(compile(ast.Module(body=body, type_ignores=[]), "cinnamon_actions.py", "exec"), ns)
    ns["_ca_settings"](guild.id)["enabled"] = True
    ns["test_guild"], ns["test_logs"] = guild, logs
    return ns


async def storage(ns, backend=None):
    backend = backend or Backend()
    ns["bd_store"] = SnapshotStore(backend)
    loaded = await ns["bd_store"].load()
    if loaded and loaded.snapshot:
        raw = loaded.snapshot
        ns["economy_balances"].clear()
        ns["economy_balances"].update({tuple(map(int, k.split(":"))): v for k, v in raw["economy_balances"].items()})
        ns["advanced_features_data"].update(copy.deepcopy(raw["advanced_features"]))
    return backend


def interaction(ns, *, user_id=ADMIN):
    guild = ns["test_guild"]
    return SimpleNamespace(guild=guild, user=guild.members[user_id], response=Response(),
                           followup=Followup(), message=SentMessage())


class CurrencyTransactions(unittest.IsolatedAsyncioTestCase):
    async def test_periodic_snapshot_prunes_old_receipts_in_inactive_guilds(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        now = ns["_ca_time"].time()
        old = now - ns["RECEIPT_RETENTION_SECONDS"] - 1
        ns["_ca_receipts"](10).update({"old": {"at": old}, "recent": {"at": now}})
        ns["_ca_receipts"](99)["old-other-guild"] = {"at": old}
        tree = ast.parse((ROOT / 'cinnamon_modules/dashboard_runtime.py').read_text())
        function = next(node for node in tree.body
                        if isinstance(node, ast.AsyncFunctionDef) and node.name == 'bd_save_data')
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'dashboard_runtime.py', 'exec'), ns)
        self.assertTrue(await ns['bd_save_data']())
        receipts = json.loads(backend.raw)['advanced_features']['cinnamon_action_receipts_v1']
        self.assertEqual(set(receipts['10']), {'recent'})
        self.assertEqual(receipts['99'], {})

    async def test_grant_and_duplicate_survive_restart_without_replay(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        result = await ns["_ca_adjust_catnip"](10, ADMIN, TARGET, 20000, True, "chat:30", conversational=True, channel_id=20)
        self.assertEqual(result["status"], "committed")
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 20100)
        self.assertEqual(json.loads(backend.raw)["economy_balances"][f"10:{TARGET}"], 20100)
        restored = adapter_runtime()
        await storage(restored, backend)
        result = await restored["_ca_adjust_catnip"](10, ADMIN, TARGET, 20000, True, "chat:30", conversational=True, channel_id=20)
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(restored["economy_balances"][(10, TARGET)], 20100)
        self.assertEqual(backend.writes, 1)

    async def test_ordinary_member_and_negative_amount_never_change_currency(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        self.assertEqual((await ns["_ca_adjust_catnip"](10, TARGET, TARGET, 20, True, "one"))["status"], "refused")
        for amount in (0, -10, True):
            self.assertEqual((await ns["_ca_adjust_catnip"](10, ADMIN, TARGET, amount, False, "two"))["status"], "invalid")
        self.assertEqual(backend.writes, 0)
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 100)

    async def test_fresh_permissions_inside_lock_override_old_member(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        ns["test_guild"].fresh[ADMIN] = Member(ns["test_guild"], ADMIN)
        result = await ns["_ca_adjust_catnip"](10, ADMIN, TARGET, 20, True, "three")
        self.assertEqual(result["status"], "refused")
        self.assertEqual(backend.writes, 0)

    async def test_credit_is_unavailable_until_ack_and_preserves_concurrent_changes(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        backend.entered, backend.resume = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(ns["_ca_adjust_catnip"](10, ADMIN, TARGET, 50, True, "four"))
        await backend.entered.wait()
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 100)
        ns["economy_balances"][(10, TARGET)] -= 30  # existing purchase
        ns["economy_balances"][(10, TARGET)] += 5   # existing reward
        backend.resume.set()
        self.assertEqual((await pending)["after"], 125)
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 125)

    async def test_debit_reserves_funds_and_failed_write_refunds_additively(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        backend.mode = "rejected"
        backend.entered, backend.resume = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(ns["_ca_adjust_catnip"](10, ADMIN, TARGET, 70, False, "five"))
        await backend.entered.wait()
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 30)
        ns["economy_balances"][(10, TARGET)] += 5
        ns["economy_balances"][(10, TARGET)] -= 10
        backend.resume.set()
        self.assertEqual((await pending)["status"], "failed")
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 95)

    async def test_uncertain_credit_reconciles_once_before_next_snapshot(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        backend.mode = "lost-after"
        result = await ns["_ca_adjust_catnip"](10, ADMIN, TARGET, 50, True, "six")
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 100)
        self.assertTrue(ns["_ca_transactions_pending"]())
        ns["economy_balances"][(10, TARGET)] -= 10
        backend.mode = "ok"
        async with ns["bd_store"].lock:
            await ns["bd_store"].ensure_ready_locked()
            await ns["bd_store"].commit_locked(ns["_bd_encode"]())
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 140)
        self.assertEqual(json.loads(backend.raw)["economy_balances"][f"10:{TARGET}"], 140)
        async with ns["bd_store"].lock:
            await ns["bd_store"].reconcile_locked()
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 140)

    async def test_uncertain_unwritten_debit_refunds_after_reconciliation(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        backend.mode = "lost-before"
        self.assertEqual((await ns["_ca_adjust_catnip"](10, ADMIN, TARGET, 70, False, "seven"))["status"], "uncertain")
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 30)
        ns["economy_balances"][(10, TARGET)] += 5
        backend.mode = "ok"
        async with ns["bd_store"].lock:
            await ns["bd_store"].reconcile_locked()
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 105)
        self.assertFalse(ns["_ca_transactions_pending"]())

    async def test_cancelled_commit_keeps_reconciliation_and_no_provisional_credit(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        backend.entered, backend.resume = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(ns["_ca_adjust_catnip"](10, ADMIN, TARGET, 50, True, "eight"))
        await backend.entered.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 100)
        backend.resume.set()
        await asyncio.sleep(0)
        async with ns["bd_store"].lock:
            await ns["bd_store"].reconcile_locked()
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 150)

    async def test_expected_removal_balance_is_checked_after_writer_wait(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        await ns["bd_store"].lock.acquire()
        pending = asyncio.create_task(ns["_ca_adjust_catnip"](10, ADMIN, TARGET, 30, False, "nine",
                    conversational=True, expected_balance=100, channel_id=20))
        await asyncio.sleep(0)
        ns["economy_balances"][(10, TARGET)] += 10
        ns["bd_store"].lock.release()
        self.assertEqual((await pending)["status"], "changed")
        self.assertEqual(backend.writes, 0)

    async def test_channel_disabled_while_waiting_for_writer_refuses_chat_adjustment(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        await ns["bd_store"].lock.acquire()
        pending = asyncio.create_task(ns["_ca_adjust_catnip"](10, ADMIN, TARGET, 30, True, "disabled",
                    conversational=True, channel_id=20))
        await asyncio.sleep(0)
        ns["disabled_channels"][10].add(20)
        ns["bd_store"].lock.release()
        self.assertEqual((await pending)["status"], "refused")
        self.assertEqual(backend.writes, 0)
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 100)

    async def test_negative_existing_balance_is_not_turned_into_a_negative_removal(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        ns["economy_balances"][(10, TARGET)] = -100
        result = await ns["_ca_adjust_catnip"](10, ADMIN, TARGET, 30, False, "invalid-balance")
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(ns["economy_balances"][(10, TARGET)], -100)
        self.assertEqual(backend.writes, 0)

    async def test_uncertain_moderation_receipt_publishes_before_generic_save(self):
        ns = adapter_runtime()
        backend = await storage(ns)
        backend.mode = "lost-after"
        rid = "10:chat:moderation"
        record = {"action": "moderation.timeout", "outcome": "executing", "at": 100}
        result = await ns["_ca_record_moderation"](10, rid, record, initial=True)
        self.assertEqual(result.status, "uncertain")
        self.assertNotIn(rid, ns["_ca_receipts"](10))
        backend.mode = "ok"
        async with ns["bd_store"].lock:
            await ns["bd_store"].ensure_ready_locked()
            await ns["bd_store"].commit_locked(ns["_bd_encode"]())
        self.assertEqual(ns["_ca_receipts"](10)[rid]["outcome"], "executing")
        self.assertIn(rid, json.loads(backend.raw)["advanced_features"]["cinnamon_action_receipts_v1"]["10"])


class ConfirmationCallbacks(unittest.IsolatedAsyncioTestCase):
    async def make_view(self, action="economy.add_catnip", *, amount=20, seconds=0):
        ns = adapter_runtime()
        backend = await storage(ns)
        view = ns["_CAConfirm"](10, ADMIN, TARGET, action, seconds, amount=amount,
                    source_id=30, channel_id=20, balance_before=100)
        ns["_CA_PENDING"][(10, ADMIN)] = view
        return ns, backend, view

    async def test_only_original_requester_can_confirm(self):
        ns, backend, view = await self.make_view()
        other = interaction(ns, user_id=TARGET)
        await view.confirm(other, None)
        self.assertTrue(other.response.messages)
        self.assertFalse(view.used)
        self.assertEqual(backend.writes, 0)

    async def test_cancel_then_confirm_cannot_execute(self):
        ns, backend, view = await self.make_view()
        cancel = interaction(ns)
        await view.cancel(cancel, None)
        self.assertEqual(view.state, "cancelled")
        await view.confirm(interaction(ns), None)
        self.assertEqual(backend.writes, 0)
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 100)

    async def test_confirm_cancel_race_never_claims_no_action_after_execution(self):
        ns, backend, view = await self.make_view()
        backend.entered, backend.resume = asyncio.Event(), asyncio.Event()
        confirming = asyncio.create_task(view.confirm(interaction(ns), None))
        await backend.entered.wait()
        cancel = interaction(ns)
        cancelling = asyncio.create_task(view.cancel(cancel, None))
        backend.resume.set()
        await asyncio.gather(confirming, cancelling)
        self.assertEqual(view.state, "committed")
        self.assertFalse(cancel.response.edits)
        self.assertIn("already handled", cancel.response.messages[0])
        self.assertEqual(ns["economy_balances"][(10, TARGET)], 120)
        await view.confirm(interaction(ns), None)
        self.assertEqual(backend.writes, 1)

    async def test_permissions_changed_before_confirmation_refuses(self):
        ns, backend, view = await self.make_view()
        ns["test_guild"].fresh[ADMIN] = Member(ns["test_guild"], ADMIN)
        await view.confirm(interaction(ns), None)
        self.assertEqual(view.state, "refused")
        self.assertEqual(backend.writes, 0)

    async def test_bot_role_loss_and_disabled_channel_refuse_timeout(self):
        for disabled in (False, True):
            ns, backend, view = await self.make_view("moderation.timeout", amount=0, seconds=60)
            if disabled:
                ns["disabled_channels"][10].add(20)
            else:
                ns["test_guild"].fresh[BOT] = Member(ns["test_guild"], BOT, bot=True, rank=100)
            await view.confirm(interaction(ns), None)
            self.assertEqual(view.state, "refused")
            self.assertFalse(ns["test_guild"].members[TARGET].calls)
            self.assertEqual(backend.writes, 0)

    async def test_timeout_and_removal_execute_only_after_durable_intent(self):
        for action in ("moderation.timeout", "moderation.remove_timeout"):
            ns, backend, view = await self.make_view(action, amount=0, seconds=60 if action.endswith(".timeout") else 0)
            await view.confirm(interaction(ns), None)
            target = ns["test_guild"].members[TARGET]
            self.assertEqual(len(target.calls), 1)
            self.assertEqual(view.state, "committed")
            receipt = ns["_ca_receipts"](10)["10:chat:30"]
            self.assertEqual(receipt["outcome"], "committed")
            self.assertEqual(backend.writes, 2)
            if action.endswith(".timeout"):
                self.assertIsInstance(target.calls[0][0], datetime.datetime)
            else:
                self.assertIsNone(target.calls[0][0])

    async def test_uncertain_discord_outcome_is_not_retried(self):
        ns, backend, view = await self.make_view("moderation.timeout", amount=0, seconds=60)
        ns["test_guild"].members[TARGET].failure = HTTPException()
        await view.confirm(interaction(ns), None)
        await view.confirm(interaction(ns), None)
        self.assertEqual(len(ns["test_guild"].members[TARGET].calls), 1)
        self.assertEqual(view.state, "uncertain")
        self.assertEqual(ns["_ca_receipts"](10)["10:chat:30"]["outcome"], "uncertain")

    async def test_duplicate_message_and_second_pending_request_are_not_duplicated(self):
        ns = adapter_runtime()
        await storage(ns)
        message = Message(ns["test_guild"])
        text = f"add 20 Catnip to <@{TARGET}>"
        self.assertTrue(await ns["_ca_maybe_handle"](message, text))
        self.assertEqual(len(message.replies), 1)
        self.assertTrue(await ns["_ca_maybe_handle"](message, text))
        self.assertEqual(len(message.replies), 1)
        second = Message(ns["test_guild"], mid=31)
        await ns["_ca_maybe_handle"](second, text)
        self.assertIn("existing confirmation", second.replies[0][0][0])

    async def test_expired_source_and_ban_never_open_confirmation(self):
        ns = adapter_runtime()
        await storage(ns)
        message = Message(ns["test_guild"])
        message.created_at -= datetime.timedelta(minutes=10)
        await ns["_ca_maybe_handle"](message, f"add 20 Catnip to <@{TARGET}>")
        self.assertIn("too old", message.replies[0][0][0])
        ban = Message(ns["test_guild"], mid=32)
        await ns["_ca_maybe_handle"](ban, f"ban <@{TARGET}>")
        self.assertIn("slash", ban.replies[0][0][0])
        self.assertFalse(ns["_CA_PENDING"])


if __name__ == "__main__":
    unittest.main()
