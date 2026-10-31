"""Checked, single-writer snapshots for Cinnamon's existing persistence format.

No Discord or Gemini imports. Backends contain no business logic; callers hold
``store.lock`` while preparing a transaction and publishing its result.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import tempfile
import uuid
from typing import Callable


@dataclass(frozen=True)
class CommitResult:
    status: str
    reason: str = ""
    snapshot: dict | None = None
    receipt_id: str | None = None

    def __bool__(self):
        return self.status == "committed"

    @property
    def committed(self):
        return bool(self)


class StorageRejected(Exception):
    """The backend positively rejected an operation before changing data."""


class StorageUncertain(Exception):
    """A write may have reached the backend; read before doing anything else."""


def _strict_json(raw: str) -> dict:
    def reject_constant(value):
        raise ValueError("Non-finite JSON value")
    value = json.loads(raw, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("Snapshot must be an object")
    return value


def validate_snapshot(raw: dict) -> None:
    """Validate every conversion used by the legacy decoder before it mutates state.

    Additional feature records remain additive. We validate their container rather
    than interpreting another feature's private schema here.
    """
    if not isinstance(raw, dict):
        raise ValueError("Snapshot must be an object")
    mapping_fields = {
        "warnings", "welcome_config", "goodbye_config", "automod_config", "xp_data",
        "xp_per_message", "xp_channels", "temp_bans", "antiraid_config", "case_counters",
        "level_roles", "active_giveaways", "active_polls", "giveaway_history",
        "giveaway_templates", "giveaway_schedules", "economy_balances", "economy_inventory",
        "economy_cooldowns", "economy_log_channels", "economy_level_rewards_claimed",
        "economy_income_roles", "economy_items", "achievement_data", "achievement_config",
        "friendship_data", "quest_data", "quest_config", "advanced_features", "ai_channels",
        "disabled_channels", "log_channels", "category_log_channels",
    }
    for field in mapping_fields:
        if field in raw and not isinstance(raw[field], dict):
            raise ValueError("Invalid snapshot mapping")
    for field in ("reaction_role_ids", "giveaway_timed_roles", "giveaway_timed_threads"):
        if field in raw and not isinstance(raw[field], list):
            raise ValueError("Invalid snapshot list")
    numeric_keys = {
        "welcome_config", "goodbye_config", "automod_config", "xp_per_message", "xp_channels",
        "antiraid_config", "case_counters", "level_roles", "active_giveaways", "active_polls",
        "economy_log_channels", "economy_income_roles", "achievement_config", "quest_data",
        "quest_config", "ai_channels", "disabled_channels", "log_channels", "category_log_channels",
    }
    for field in numeric_keys:
        for key in raw.get(field, {}):
            int(key)
    pairs = {"warnings", "xp_data", "temp_bans", "economy_balances", "economy_inventory",
             "economy_level_rewards_claimed", "achievement_data", "friendship_data"}
    for field in pairs:
        for key in raw.get(field, {}):
            if not isinstance(key, str) or len(key.split(":")) != 2:
                raise ValueError("Invalid member key")
            for part in key.split(":"):
                int(part)
    for key in raw.get("economy_cooldowns", {}):
        parts = key.split(":", 2)
        if len(parts) != 3 or not parts[2]:
            raise ValueError("Invalid cooldown key")
        int(parts[0]); int(parts[1])
    for value in raw.get("reaction_role_ids", []):
        if not isinstance(value, (int, str)):
            raise ValueError("Invalid reaction role")
        int(value)
    for key in raw.get("giveaway_templates", {}):
        if str(key).isdigit():
            int(key)
    for field in ("xp_channels", "disabled_channels"):
        for ids in raw.get(field, {}).values():
            if not isinstance(ids, list):
                raise ValueError("Invalid channel list")
            for value in ids:
                int(value)
    for field in ("level_roles", "economy_income_roles", "category_log_channels"):
        for items in raw.get(field, {}).values():
            if not isinstance(items, dict):
                raise ValueError("Invalid guild configuration")
            if field != "category_log_channels":
                for key in items:
                    int(key)
    for value in raw.get("xp_per_message", {}).values():
        int(value)
    for levels in raw.get("economy_level_rewards_claimed", {}).values():
        if not isinstance(levels, list):
            raise ValueError("Invalid reward record")
        for level in levels:
            int(level)
    for item in raw.get("economy_items", {}).values():
        if not isinstance(item, dict):
            raise ValueError("Invalid shop item")
        if "price" in item:
            int(item["price"])
    for value in raw.get("economy_balances", {}).values():
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("Invalid balance")
        int(value)
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Invalid balance")
    # Ensure direct callers cannot provide unserializable or non-finite records.
    json.dumps(raw, allow_nan=False)


class LocalSnapshotBackend:
    durable = False  # A file path alone cannot prove a durable Render disk.

    def __init__(self, path: str):
        self.path = Path(path)

    async def read(self):
        def read():
            try:
                return self.path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return None
        return await asyncio.to_thread(read)

    async def compare_and_set(self, expected, candidate):
        def write():
            try:
                current = self.path.read_text(encoding="utf-8")
            except FileNotFoundError:
                current = None
            if current != expected:
                return False
            temporary = None
            replaced = False
            try:
                destination = self.path.absolute()
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                        dir=destination.parent, prefix=".cinnamon-", suffix=".tmp", delete=False) as stream:
                    temporary = stream.name
                    stream.write(candidate)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
                replaced = True
                # Commit the directory entry as well as the file's contents.
                directory_fd = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError as exc:
                if replaced:
                    raise StorageUncertain("Local replacement acknowledgement failed") from exc
                raise StorageRejected("Local snapshot write failed") from exc
            finally:
                if temporary is not None:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
            return True
        return await asyncio.to_thread(write)


class UpstashSnapshotBackend:
    durable = True
    # Compare and replace in one atomic Redis operation, including absent keys.
    CAS_SCRIPT = (
        "local current = redis.call('GET', KEYS[1]); "
        "if ARGV[1] == 'missing' then if current then return 0 end "
        "elseif current ~= ARGV[2] then return 0 end; "
        "redis.call('SET', KEYS[1], ARGV[3]); return 1"
    )

    def __init__(self, url: str, token: str, key: str, *, session_factory=None):
        self.url, self.token, self.key = url, token, key
        self.session_factory = session_factory

    async def _command(self, command, *, writing=False):
        if not self.url or not self.token:
            raise StorageRejected("Upstash configuration is incomplete")
        # Lazy import keeps pure policy tests independent of discord.py/aiohttp.
        import aiohttp
        factory = self.session_factory or aiohttp.ClientSession
        try:
            async with factory() as session:
                async with session.post(self.url, json=command,
                        headers={"Authorization": f"Bearer {self.token}"},
                        timeout=aiohttp.ClientTimeout(total=8)) as response:
                    if 400 <= getattr(response, "status", 200) < 500:
                        raise StorageRejected("Storage rejected the request")
                    response.raise_for_status()
                    payload = await response.json()
                    if isinstance(payload, dict) and payload.get("error"):
                        raise StorageRejected("Storage rejected the command")
                    if not isinstance(payload, dict) or "result" not in payload:
                        if writing:
                            raise StorageUncertain("Storage write acknowledgement malformed")
                        raise StorageRejected("Storage read acknowledgement malformed")
                    return payload["result"]
        except StorageRejected:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            if writing:
                raise StorageUncertain("Storage write acknowledgement unavailable") from exc
            raise StorageRejected("Storage read unavailable") from exc

    async def read(self):
        result = await self._command(["GET", self.key])
        if result is not None and not isinstance(result, str):
            raise StorageRejected("Unexpected storage value")
        return result

    async def compare_and_set(self, expected, candidate):
        result = await self._command(["EVAL", self.CAS_SCRIPT, 1, self.key,
            "missing" if expected is None else "present", expected or "", candidate], writing=True)
        if type(result) is not int or result not in (0, 1):
            raise StorageUncertain("Unexpected storage write acknowledgement")
        return result == 1


class SnapshotStore:
    """Ordered snapshots with a barrier after any ambiguous write.

    ``on_reconcile`` is a synchronous, non-raising hook used to publish a staged
    business transaction before another caller captures live memory. It receives
    the resolved result under ``lock`` exactly once.
    """
    def __init__(self, backend, *, validator: Callable = validate_snapshot):
        self.backend = backend
        self.validator = validator
        self.lock = asyncio.Lock()
        self.ready = False
        self.status = "unloaded"
        self.reason = "Storage has not loaded"
        self.expected_raw = None
        self._pending = None
        self._pending_write_task = None
        self._pending_fences = set()
        self.on_reconcile = None

    @property
    def durable(self):
        return bool(self.backend.durable)

    @property
    def pending_receipt(self):
        return self._pending[2] if self._pending else None

    def disable(self, reason="Storage unavailable"):
        self.ready = False
        self.status, self.reason = "unavailable", reason

    async def load(self):
        async with self.lock:
            if self._pending is not None:
                return CommitResult("uncertain", "Reconcile pending write before reloading",
                                    receipt_id=self.pending_receipt)
            try:
                raw = await self.backend.read()
                snapshot = {} if raw is None else _strict_json(raw)
                self.validator(snapshot)
            except (StorageRejected, OSError, ValueError, TypeError, AttributeError):
                self.disable("Stored snapshot could not be loaded or validated")
                return CommitResult("unavailable", self.reason)
            self.expected_raw = raw
            self._pending = None
            self.ready = True
            self.status, self.reason = "ready", "Snapshot loaded"
            return CommitResult("committed", self.reason, snapshot)

    async def ensure_ready_locked(self):
        if self._pending:
            if self.pending_receipt is not None and self.on_reconcile is None:
                return CommitResult("uncertain", "Action reconciliation required",
                                    receipt_id=self.pending_receipt)
            return await self.reconcile_locked()
        if not self.ready:
            return CommitResult("unavailable" if self.status != "conflict" else "conflict", self.reason)
        return CommitResult("committed", "Storage ready")

    async def commit_locked(self, candidate: dict, *, receipt_id: str | None = None):
        available = await self.ensure_ready_locked()
        if not available:
            return available
        try:
            self.validator(candidate)
            frozen = json.dumps(candidate, allow_nan=False, separators=(",", ":"), sort_keys=True)
            snapshot = _strict_json(frozen)
        except (ValueError, TypeError, AttributeError):
            return CommitResult("failed", "Candidate snapshot is invalid", receipt_id=receipt_id)
        task = asyncio.create_task(self.backend.compare_and_set(self.expected_raw, frozen))
        self._pending_write_task = task
        try:
            # Client cancellation must not detach a still-running local thread or
            # HTTP operation from the reconciliation barrier.
            accepted = await asyncio.shield(task)
        except asyncio.CancelledError:
            self._pending = (self.expected_raw, frozen, receipt_id)
            self.ready = False
            self.status, self.reason = "uncertain", "Cancelled write requires reconciliation"
            raise
        except StorageRejected:
            self._pending_write_task = None
            return CommitResult("failed", "Storage rejected the write", receipt_id=receipt_id)
        except (StorageUncertain, OSError, asyncio.TimeoutError):
            self._pending = (self.expected_raw, frozen, receipt_id)
            self.ready = False
            self.status, self.reason = "uncertain", "Write requires reconciliation"
            return CommitResult("uncertain", self.reason, snapshot, receipt_id)
        self._pending_write_task = None
        if not accepted:
            self.ready = False
            self.status, self.reason = "conflict", "Another writer changed the stored snapshot"
            return CommitResult("conflict", self.reason, receipt_id=receipt_id)
        self.expected_raw = frozen
        self.status, self.reason = "ready", "Snapshot committed"
        return CommitResult("committed", self.reason, snapshot, receipt_id)

    async def reconcile_locked(self):
        if not self._pending:
            return await self.ensure_ready_locked()
        expected, candidate, receipt_id = self._pending
        task = self._pending_write_task
        if task is not None:
            if not task.done():
                return CommitResult("uncertain", "Previous write is still in flight", receipt_id=receipt_id)
            # Retrieve exceptions from shielded tasks even when their original
            # caller was cancelled. A settled request can still have an uncertain
            # server result; the checked read and fence below decide it.
            try:
                task.result()
            except (Exception, asyncio.CancelledError):
                pass
            self._pending_write_task = None
        try:
            observed = await self.backend.read()
            snapshot = {} if observed is None else _strict_json(observed)
            self.validator(snapshot)
        except (StorageRejected, OSError, ValueError, TypeError, AttributeError):
            return CommitResult("uncertain", "Storage reconciliation unavailable", receipt_id=receipt_id)
        if observed == candidate:
            result = CommitResult("committed", "Previous write committed", snapshot, receipt_id)
        elif observed in self._pending_fences:
            result = CommitResult("failed", "Previous write was fenced out", snapshot, receipt_id)
        elif observed == expected:
            # An HTTP timeout is not proof that Redis stopped processing the
            # original CAS. Atomically advance unchanged old state first: whichever
            # operation wins, the other can no longer match the expected raw value.
            fence_raw = next(iter(self._pending_fences), None)
            if fence_raw is None:
                fenced = dict(snapshot)
                fenced["_cinnamon_snapshot_fence"] = uuid.uuid4().hex
                fence_raw = json.dumps(fenced, allow_nan=False, separators=(",", ":"), sort_keys=True)
                self._pending_fences.add(fence_raw)
            else:
                # Reuse one fence across repeated acknowledgement failures;
                # retaining whole snapshots per attempt would grow unbounded.
                fenced = _strict_json(fence_raw)
            fence_task = asyncio.create_task(self.backend.compare_and_set(expected, fence_raw))
            self._pending_write_task = fence_task
            try:
                accepted = await asyncio.shield(fence_task)
            except asyncio.CancelledError:
                raise
            except (StorageRejected, StorageUncertain, OSError, asyncio.TimeoutError):
                return CommitResult("uncertain", "Reconciliation fence acknowledgement unavailable",
                                    receipt_id=receipt_id)
            self._pending_write_task = None
            if not accepted:
                return CommitResult("uncertain", "Snapshot changed before reconciliation fence",
                                    receipt_id=receipt_id)
            observed, snapshot = fence_raw, fenced
            result = CommitResult("failed", "Previous write was fenced out", snapshot, receipt_id)
        else:
            self.status, self.reason = "conflict", "Stored snapshot changed during reconciliation"
            self.ready = False
            return CommitResult("conflict", self.reason, snapshot, receipt_id)
        if receipt_id is not None and self.on_reconcile is None:
            return CommitResult("uncertain", "Action publication hook unavailable", snapshot, receipt_id)
        if self.on_reconcile is not None:
            try:
                self.on_reconcile(result)
            except Exception:
                return CommitResult("uncertain", "Action publication requires attention", snapshot, receipt_id)
        self.expected_raw = observed
        self._pending = None
        self._pending_fences.clear()
        self.ready = True
        self.status, self.reason = "ready", result.reason
        return result



def describe_action_storage_blocker(store, *, allow_local=False):
    """Explain why a confirmed action is blocked; do not expose secrets.

    Diagnostic only. Actual execution must continue to use store.ready and
    the existing durable/explicit-local gate inside its transaction lock.
    """
    if store is None:
        return "Storage has not initialized. Check the bot startup logs; no action was taken."
    backend = getattr(store, "backend", None)
    if isinstance(backend, UpstashSnapshotBackend) and (
            not backend.url or not backend.token):
        return ("Upstash configuration is incomplete. Set both "
                "UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN in your "
                "Render service Environment, then deploy. No action was taken.")
    if not store.durable and not allow_local:
        return ("Cinnamon is using a local file, not verified durable storage. "
                "On Render, configure UPSTASH_REDIS_REST_URL and "
                "UPSTASH_REDIS_REST_TOKEN before using confirmed actions. "
                "Back up any existing local data before switching storage. "
                "Do not enable the local-action bypass on temporary storage. "
                "No action was taken.")
    if store.status == "uncertain" or store.pending_receipt:
        return ("A previous storage write has an unresolved outcome. "
                "Cinnamon is blocking new actions to prevent duplicate changes. "
                "Check private logs and reconcile storage before retrying. "
                "No new action was taken.")
    if store.status == "conflict":
        return ("Storage changed outside this bot process (possible second bot "
                "instance). Stop conflicting writers and investigate the saved "
                "data before restarting; no action was taken.")
    if not store.ready:
        return ("Stored data has not loaded safely (status: " +
                str(getattr(store, "status", "unavailable"))[:40] + "). "
                "Run /datastatus check as an Administrator and inspect Render "
                "startup logs. A working connection alone does not mean "
                "balances loaded successfully. No action was taken.")
    return None
