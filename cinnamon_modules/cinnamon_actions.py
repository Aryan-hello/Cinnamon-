"""Trusted, confirmed chat actions. Model output is never execution authority.

Loaded into the existing shared runtime. Parsing/types are independently
importable; Discord objects, permissions and persistence stay in this adapter.
"""
import asyncio as _ca_asyncio
import copy as _ca_copy
import datetime as _ca_datetime
import os as _ca_os
import random as _ca_random
import re as _ca_re
import time as _ca_time

from cinnamon_modules.brain_actions import (
    ActionProposal, ActionValidationError, parse_action, validate_proposal,
    MAX_CATNIP, CONFIRM_SECONDS, SOURCE_MAX_AGE_SECONDS,
    RECEIPT_RETENTION_SECONDS,
)
from cinnamon_modules.brain_storage import CommitResult as _CACommitResult

_CA_LOCKS = {}  # existing consent-based prank locks
_CA_PENDING = {}  # (guild, requester) -> confirmation; deliberately expires on restart
_CA_RECENT_SOURCES = {}  # bounded, short-lived rejection/confirmation deduplication
_CA_PENDING_ADJUSTMENT = None  # a single uncertain writer, protected by bd_store.lock
_CA_IN_FLIGHT = 0


def _ca_server(gid):
    return advanced_features_data.setdefault("cinnamon_actions_v1", {}).setdefault(
        str(gid), {"play_enabled": False, "players": {}})


def _ca_settings(gid):
    return advanced_features_data.setdefault("cinnamon_actions_v2", {}).setdefault(
        str(gid), {"enabled": False})


def _ca_user(gid, uid):
    return _ca_server(gid).setdefault("players", {}).setdefault(str(uid), {"consent": False})


def _ca_receipts(gid):
    return advanced_features_data.setdefault("cinnamon_action_receipts_v1", {}).setdefault(str(gid), {})


def _ca_prune_receipts(gid):
    cutoff = _ca_time.time() - RECEIPT_RETENTION_SECONDS
    records = _ca_receipts(gid)
    for key, record in list(records.items()):
        # Source messages older than five minutes are separately ineligible.
        if float(record.get("at", 0)) < cutoff:
            records.pop(key, None)


def _ca_prune_all_receipts():
    """Periodic snapshots enforce retention even in guilds with no new actions."""
    guilds = advanced_features_data.get("cinnamon_action_receipts_v1", {})
    for gid in list(guilds):
        _ca_prune_receipts(gid)


def _ca_storage_ready():
    store = globals().get("bd_store")
    return bool(store and store.ready and (
        store.durable or _ca_os.environ.get("CINNAMON_ALLOW_LOCAL_ACTIONS", "").lower() == "true"))


def _ca_transactions_pending():
    store = globals().get("bd_store")
    return bool(_CA_IN_FLIGHT or _CA_PENDING_ADJUSTMENT or (
        store and (store.pending_receipt or store.status == "uncertain")))


def _ca_publish_adjustment(pending, committed):
    """Only additive updates: never restore a captured absolute balance."""
    key = (pending["gid"], pending["target_id"])
    if committed:
        if pending["add"]:
            economy_balances[key] = int(economy_balances[key]) + pending["actual"]
        _ca_receipts(pending["gid"])[pending["receipt_id"]] = pending["record"]
    elif not pending["add"]:
        economy_balances[key] = int(economy_balances[key]) + pending["actual"]


def _ca_reconcile_pending(result):
    """Storage calls this synchronously under its lock, before another snapshot."""
    global _CA_PENDING_ADJUSTMENT
    pending = _CA_PENDING_ADJUSTMENT
    if not pending or result.receipt_id != pending["receipt_id"]:
        if result.status == "committed" and result.receipt_id and result.snapshot:
            for gid, records in result.snapshot.get("advanced_features", {}).get(
                    "cinnamon_action_receipts_v1", {}).items():
                if result.receipt_id in records:
                    _ca_receipts(int(gid))[result.receipt_id] = records[result.receipt_id]
        return
    if result.status in ("committed", "failed"):
        _ca_publish_adjustment(pending, result.status == "committed")
        _CA_PENDING_ADJUSTMENT = None


def _ca_store_hook():
    bd_store.on_reconcile = _ca_reconcile_pending


def _ca_adjustment_result(status, reason="", **values):
    return {"status": status, "reason": reason, **values}


async def _ca_adjust_catnip(gid, requester_id, target_id, amount, add, source_id, *,
                           conversational=False, expected_balance=None, channel_id=None):
    """Durably adjust currency once. Caller supplies verified Discord identity.

    Credits remain unavailable until acknowledged. Debits reserve spendable funds
    before I/O. An ambiguous write blocks every later snapshot until reconciliation.
    """
    global _CA_PENDING_ADJUSTMENT, _CA_IN_FLIGHT
    if type(amount) is not int or amount <= 0 or (conversational and amount > MAX_CATNIP):
        return _ca_adjustment_result("invalid", "Catnip amount must be positive" +
            (" and no greater than 1,000,000." if conversational else "."))
    if type(add) is not bool or not str(source_id) or len(str(source_id)) > 128:
        return _ca_adjustment_result("invalid", "Invalid trusted action context.")
    _ca_store_hook()
    async with bd_store.lock:
        await bd_store.ensure_ready_locked()
        if not _ca_storage_ready():
            return _ca_adjustment_result("unavailable", "Durable storage is unavailable; no new adjustment was made.")
        if conversational and not _ca_settings(gid).get("enabled", False):
            return _ca_adjustment_result("disabled", "Conversational actions are switched off.")
        guild = bot.get_guild(gid)
        if not guild:
            return _ca_adjustment_result("refused", "This server is no longer available.")
        try:
            await _ca_refresh_roles(guild)
            actor = await _ca_fresh_member(guild, requester_id)
            target = await _ca_fresh_member(guild, target_id)
        except (discord.HTTPException, AttributeError):
            return _ca_adjustment_result("refused", "Current server membership could not be verified.")
        if not (actor.id == guild.owner_id or actor.guild_permissions.administrator):
            return _ca_adjustment_result("refused", "Administrator permission changed; no adjustment was made.")
        if conversational and target.bot:
            return _ca_adjustment_result("refused", "Choose a human member of this server.")
        if conversational:
            try:
                channel = await guild.fetch_channel(channel_id)
                me = await _ca_fresh_member(guild, guild.me.id)
                permissions = channel.permissions_for(me)
            except (discord.HTTPException, AttributeError, TypeError):
                return _ca_adjustment_result("refused", "The action channel could not be verified.")
            if (channel_id in disabled_channels[gid] or not permissions.view_channel
                    or not permissions.send_messages):
                return _ca_adjustment_result("refused", "This channel is no longer available for conversational actions.")
        if conversational and not _ca_settings(gid).get("enabled", False):
            return _ca_adjustment_result("disabled", "Conversational actions were switched off.")
        _ca_prune_receipts(gid)
        receipt_id = f"{gid}:{source_id}"
        prior = _ca_receipts(gid).get(receipt_id)
        if prior:
            return _ca_adjustment_result("duplicate", "This request was already handled.", **{
                k: prior[k] for k in ("before", "after", "actual") if k in prior}, receipt_id=receipt_id)
        key = (gid, target_id)
        before = economy_balance(gid, target_id)
        if before < 0:
            log.error("Currency adjustment refused: negative stored balance in guild %s member %s", gid, target_id)
            return _ca_adjustment_result("invalid", "That stored balance is invalid. An administrator must resolve it before an adjustment.")
        if conversational and not add and expected_balance is not None and before != expected_balance:
            return _ca_adjustment_result("changed", "The balance changed. Request a fresh confirmation before removing Catnip.")
        if conversational and not add and before < amount:
            return _ca_adjustment_result("changed", "That balance no longer covers the confirmed removal. Request a new confirmation.")
        actual = amount if add else min(before, amount)
        after = before + actual if add else before - actual
        record = {"guild_id": gid, "requester_id": requester_id, "target_id": target_id,
                  "action": "economy.add_catnip" if add else "economy.remove_catnip",
                  "actual": actual, "before": before, "after": after,
                  "at": _ca_time.time(), "outcome": "committed", "source_id": str(source_id)}
        pending = {"gid": gid, "target_id": target_id, "receipt_id": receipt_id,
                   "actual": actual, "add": add, "record": record}
        candidate = _ca_copy.deepcopy(_bd_encode())
        candidate["economy_balances"][f"{gid}:{target_id}"] = after
        candidate.setdefault("advanced_features", {}).setdefault(
            "cinnamon_action_receipts_v1", {}).setdefault(str(gid), {})[receipt_id] = record
        if not add:
            economy_balances[key] = after
        _CA_IN_FLIGHT += 1
        try:
            result = await bd_store.commit_locked(candidate, receipt_id=receipt_id)
        except BaseException:
            # Cancellation may occur after the backend accepted a write. Storage
            # owns the reconciliation barrier; retain the reservation if uncertain.
            if bd_store.pending_receipt == receipt_id:
                _CA_PENDING_ADJUSTMENT = pending
            else:
                _ca_publish_adjustment(pending, False)
            raise
        finally:
            _CA_IN_FLIGHT -= 1
        if result.status == "committed":
            _ca_publish_adjustment(pending, True)
        elif result.status == "uncertain":
            _CA_PENDING_ADJUSTMENT = pending
        else:
            _ca_publish_adjustment(pending, False)
        visible_after = economy_balance(gid, target_id) if result.status == "committed" else after
        return _ca_adjustment_result(result.status, result.reason, before=before,
            after=visible_after, actual=actual, receipt_id=receipt_id)


def _ca_permission_reason(guild, actor, target, action, *, me=None):
    """Authorization independent of phrasing and mood; checked again on click."""
    if not guild or actor.guild.id != guild.id or target.guild.id != guild.id:
        return "This command can only affect a member of this server."
    if action in ("kick", "ban"):
        return "Use the existing /kick or /ban slash command; conversational execution awaits a separate security review."
    if action.startswith("economy."):
        if not (actor.id == guild.owner_id or actor.guild_permissions.administrator):
            return "AWWW, YOU THINK YOU HAVE ADMIN PERMISSIONS. 😼 Only the owner or a server Administrator can adjust Catnip."
        return "Choose a human member of this server." if target.bot else None
    me = me or guild.me
    if not me or target.bot or actor.id == target.id or target.id in (guild.owner_id, me.id):
        return "That member is protected from this action."
    if not (actor.id == guild.owner_id or actor.guild_permissions.administrator or actor.guild_permissions.moderate_members):
        return "You need Timeout Members permission for this request."
    if target.guild_permissions.administrator or target.guild_permissions.moderate_members:
        return "Cinnamon won't apply conversational punishments to staff."
    if actor.id != guild.owner_id and target.top_role >= actor.top_role:
        return "You cannot moderate someone with an equal or higher role."
    if target.top_role >= me.top_role:
        return "Move Cinnamon's role above the target before trying this."
    if not me.guild_permissions.moderate_members:
        return "Cinnamon needs Moderate Members permission."
    return None


async def _ca_fresh_member(guild, uid):
    # A REST refresh avoids authorizing from the old confirmation's Member.
    return await guild.fetch_member(uid)


async def _ca_refresh_roles(guild):
    """Refresh role permissions as well as membership before a protected action."""
    roles = await guild.fetch_roles()
    # discord.py stores guild roles here; Member.guild_permissions/top_role use
    # this same documented Guild role collection through its cache.
    guild._roles = {role.id: role for role in roles}


def _ca_action_label(action, seconds=0, amount=0):
    if action in ("timeout", "moderation.timeout"):
        return f"Time out for {seconds} seconds"
    if action in ("untimeout", "moderation.remove_timeout"):
        return "Remove timeout"
    if action == "economy.add_catnip":
        return f"Add {amount:,} Catnip"
    if action == "economy.remove_catnip":
        return f"Remove {amount:,} Catnip"
    raise ValueError("Disallowed action")


async def _ca_record_moderation(gid, receipt_id, record, *, initial=False):
    """Record status before/after Discord independently of the best-effort log."""
    _ca_store_hook()
    async with bd_store.lock:
        await bd_store.ensure_ready_locked()
        if not _ca_storage_ready():
            return None
        _ca_prune_receipts(gid)
        if initial and receipt_id in _ca_receipts(gid):
            return _CACommitResult("failed", "An execution receipt already exists.", receipt_id=receipt_id)
        candidate = _ca_copy.deepcopy(_bd_encode())
        candidate.setdefault("advanced_features", {}).setdefault(
            "cinnamon_action_receipts_v1", {}).setdefault(str(gid), {})[receipt_id] = record
        result = await bd_store.commit_locked(candidate, receipt_id=receipt_id)
        if result.status == "committed":
            _ca_receipts(gid)[receipt_id] = record
        return result


async def _ca_admin_catnip_command(interaction, member, amount, add):
    """Existing slash entrypoints retain their names and direct invocation."""
    if type(amount) is not int or amount <= 0:
        return await cinnamon_send(interaction, "❌ Amount must be greater than 0.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    try:
        await _ca_refresh_roles(interaction.guild)
        actor = await _ca_fresh_member(interaction.guild, interaction.user.id)
        target = await _ca_fresh_member(interaction.guild, member.id)
    except (discord.HTTPException, AttributeError):
        return await cinnamon_send(interaction, "❌ Current server membership could not be verified. No adjustment was made.", ephemeral=True)
    if not (actor.id == interaction.guild.owner_id or actor.guild_permissions.administrator):
        return await cinnamon_send(interaction, "❌ You need current Administrator permission. No adjustment was made.", ephemeral=True)
    result = await _ca_adjust_catnip(interaction.guild.id, actor.id, target.id, amount,
                                    add, f"slash:{interaction.id}")
    if result["status"] != "committed":
        return await cinnamon_send(interaction, "⚠️ " + (result["reason"] or
            "The adjustment was not acknowledged. Check storage diagnostics before trying again."), ephemeral=True)
    await economy_log(interaction.guild.id, title="🛠️ Admin Catnip adjusted", fields=[
        ("Admin", f"{actor} ({actor.id})"), ("Member", f"{target} ({target.id})"),
        ("Amount", f"{'+' if add else '-'}{result['actual']:,} Catnip"),
        ("Balance before", str(result["before"])), ("Balance after", str(result["after"])),
        ("Receipt", result["receipt_id"])])
    await cinnamon_send(interaction,
        f"✅ {'Added' if add else 'Removed'} **{result['actual']:,} Catnip** "
        f"{'to' if add else 'from'} {target.mention}. Balance: **{result['after']:,}**.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class _CAConfirm(discord.ui.View):
    def __init__(self, gid, requester_id, target_id, action, seconds=0, *, amount=0,
                 source_id=None, channel_id=None, balance_before=None):
        super().__init__(timeout=CONFIRM_SECONDS)
        self.gid, self.requester_id, self.target_id = gid, requester_id, target_id
        self.action, self.seconds, self.amount = action, seconds, amount
        self.source_id, self.channel_id = source_id, channel_id
        self.balance_before = balance_before
        self.used = False
        self.state = "pending"
        self.expires_at = _ca_time.monotonic() + CONFIRM_SECONDS
        self.lock = _ca_asyncio.Lock()
        self.message = None

    async def interaction_check(self, interaction):
        if (not interaction.guild or interaction.guild.id != self.gid
                or interaction.user.id != self.requester_id):
            await interaction.response.send_message(
                "🐈 Only the original requesting staff member can confirm.", ephemeral=True)
            return False
        return True

    def _finish(self, state):
        self.used = True
        self.state = state
        if state != "executing" and _CA_PENDING.get((self.gid, self.requester_id)) is self:
            _CA_PENDING.pop((self.gid, self.requester_id), None)
        self.stop()

    async def on_timeout(self):
        async with self.lock:
            if self.used:
                return
            self._finish("expired")
            if self.message:
                try:
                    await self.message.edit(content="🐾 Confirmation expired. No action was taken.", embed=None, view=None)
                except discord.HTTPException:
                    pass

    @discord.ui.button(label="Confirm action", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        if not await self.interaction_check(interaction):
            return
        async with self.lock:
            if self.used:
                return await interaction.response.send_message("This action was already handled.", ephemeral=True)
            if _ca_time.monotonic() >= self.expires_at:
                self._finish("expired")
                return await interaction.response.send_message("Confirmation expired. Request it again.", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild
            try:
                await _ca_refresh_roles(guild)
                actor = await _ca_fresh_member(guild, self.requester_id)
                target = await _ca_fresh_member(guild, self.target_id)
                me = await _ca_fresh_member(guild, guild.me.id)
                channel = await guild.fetch_channel(self.channel_id)
            except (discord.HTTPException, AttributeError):
                self._finish("failed")
                return await interaction.followup.send("I couldn't refresh server permissions. No action was taken.", ephemeral=True)
            problem = _ca_permission_reason(guild, actor, target, self.action, me=me)
            permissions = channel.permissions_for(me)
            if (not _ca_settings(self.gid).get("enabled", False)
                    or self.channel_id in disabled_channels[self.gid]
                    or not permissions.view_channel or not permissions.send_messages):
                problem = "Conversational actions or this channel are no longer available."
            if problem:
                self._finish("refused")
                return await interaction.followup.send("⛔ " + problem, ephemeral=True)
            try:
                validate_proposal(ActionProposal(self.action, self.target_id, amount=self.amount, seconds=self.seconds))
            except ActionValidationError as exc:
                self._finish("refused")
                return await interaction.followup.send(str(exc), ephemeral=True)
            receipt_id = f"{self.gid}:chat:{self.source_id}"
            if _ca_receipts(self.gid).get(receipt_id):
                self._finish("duplicate")
                return await interaction.followup.send("This request already has an execution receipt; it won't run again.", ephemeral=True)
            self._finish("executing")  # Cancel cannot claim success while I/O is in flight.
            label = _ca_action_label(self.action, self.seconds, self.amount)
            if self.action.startswith("economy."):
                if (self.action == "economy.remove_catnip" and
                        economy_balance(self.gid, self.target_id) != self.balance_before):
                    self._finish("changed")
                    return await interaction.followup.send("The balance changed. Request a fresh confirmation before removing Catnip.", ephemeral=True)
                result = await _ca_adjust_catnip(self.gid, actor.id, target.id, self.amount,
                    self.action == "economy.add_catnip", f"chat:{self.source_id}", conversational=True,
                    expected_balance=self.balance_before, channel_id=self.channel_id)
                self.state = result["status"]
                accepted = self.state == "committed"
                detail = (f"Balance: {result['after']:,} Catnip." if accepted else result["reason"])
            else:
                record = {"guild_id": self.gid, "requester_id": actor.id, "target_id": target.id,
                          "action": self.action, "seconds": self.seconds, "at": _ca_time.time(),
                          "outcome": "executing", "source_id": str(self.source_id)}
                prepared = await _ca_record_moderation(self.gid, receipt_id, record, initial=True)
                if not prepared or prepared.status != "committed":
                    self._finish("unavailable")
                    return await interaction.followup.send("I couldn't durably record the request. No Discord action was attempted.", ephemeral=True)
                # Recording the intent awaited storage: verify current authority
                # once more immediately before contacting Discord.
                try:
                    await _ca_refresh_roles(guild)
                    actor = await _ca_fresh_member(guild, self.requester_id)
                    target = await _ca_fresh_member(guild, self.target_id)
                    me = await _ca_fresh_member(guild, guild.me.id)
                    problem = _ca_permission_reason(guild, actor, target, self.action, me=me)
                    channel = await guild.fetch_channel(self.channel_id)
                    perms = channel.permissions_for(me)
                    if self.channel_id in disabled_channels[self.gid] or not perms.view_channel or not perms.send_messages:
                        problem = "This channel is no longer available for conversational actions."
                except (discord.HTTPException, AttributeError):
                    problem = "I couldn't verify current moderation authority."
                if not _ca_settings(self.gid).get("enabled", False):
                    problem = "Conversational actions were switched off."
                if problem:
                    self._finish("refused")
                    await _ca_record_moderation(self.gid, receipt_id, dict(record, outcome="refused"))
                    return await interaction.followup.send("⛔ " + problem + " No Discord action was attempted.", ephemeral=True)
                reason = f"Cinnamon delegated timeout; requester {actor.id}; receipt {receipt_id}"
                # Use an absolute deadline. A retry must never extend a timeout.
                deadline = _ca_datetime.datetime.now(_ca_datetime.timezone.utc) + _ca_datetime.timedelta(seconds=self.seconds)
                try:
                    await target.timeout(deadline if self.action == "moderation.timeout" else None, reason=reason)
                    self.state, accepted = "committed", True
                    detail = "Discord accepted the action."
                except discord.Forbidden:
                    self.state, accepted = "failed", False
                    detail = "Discord refused the action. Check permissions and role hierarchy."
                except (discord.HTTPException, _ca_asyncio.TimeoutError, OSError):
                    self.state, accepted = "uncertain", False
                    detail = "Discord's result is uncertain. Check the member and audit log; this request will not run again."
                record = dict(record, outcome=self.state)
                saved = await _ca_record_moderation(self.gid, receipt_id, record)
                if not saved or saved.status != "committed":
                    detail += " The durable receipt still needs reconciliation."
            self._finish(self.state)
            audit_fields = [("Guild ID", str(self.gid)), ("Requester ID", str(actor.id)),
                ("Target ID", str(target.id)), ("Action", label),
                ("Source message ID", str(self.source_id)), ("Receipt", receipt_id), ("Status", self.state)]
            if self.action.startswith("economy."):
                audit_fields.extend((name, str(result[key])) for name, key in (
                    ("Amount", "actual"), ("Balance before", "before"), ("Balance after", "after")) if key in result)
            await send_log(self.gid, title="🛡️ Cinnamon confirmed action", category=(
                "economy" if self.action.startswith("economy.") else "moderation"), fields=audit_fields)
            try:
                await interaction.message.edit(content=(
                    ("✅ Completed: " if accepted else "⚠️ Result: ") + label + " · " + detail),
                    embed=None, view=None, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass
            await interaction.followup.send(("✅ " if accepted else "⚠️ ") + detail, ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        if not await self.interaction_check(interaction):
            return
        async with self.lock:
            if self.used:
                return await interaction.response.send_message("This action was already handled.", ephemeral=True)
            self._finish("cancelled")
            await interaction.response.edit_message(content="Cancelled. No action taken.", embed=None, view=None)


async def _ca_maybe_handle(message, clean_content):
    """Consume actions before model generation; never parse generated prose."""
    if not message.guild or not isinstance(message.author, discord.Member):
        return False
    ids = [member.id for member in message.mentions if not bot.user or member.id != bot.user.id]
    reply_id = None
    if _ca_re.search(r"\b(?:this|that)\s+(?:member|user|person)\b", clean_content, _ca_re.I):
        ref = message.reference.resolved if message.reference else None
        if ref is None and message.reference and message.reference.message_id:
            try:
                ref = await message.channel.fetch_message(message.reference.message_id)
            except discord.HTTPException:
                pass
        if isinstance(ref, discord.Message) and not ref.author.bot and ref.guild and ref.guild.id == message.guild.id:
            reply_id = ref.author.id
    try:
        proposal = parse_action(clean_content, requester_id=message.author.id,
                                target_ids=ids, reply_target_id=reply_id)
    except ActionValidationError as exc:
        await message.reply("🐾 " + str(exc), mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        return True
    if proposal is None:
        return False
    async def refuse(text):
        await message.reply("🐾 " + text, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
    gid = message.guild.id
    target = message.guild.get_member(proposal.target_user_id)
    if not target:
        await refuse("I can't find that member in this server.")
        return True
    problem = _ca_permission_reason(message.guild, message.author, target, proposal.action)
    if problem:
        await refuse(problem)
        return True
    if not _ca_settings(gid).get("enabled", False):
        await refuse("Conversational actions are switched off. An Administrator can enable them with `/cinnamon-mind actions`. Existing slash commands are available.")
        return True
    _ca_store_hook()
    async with bd_store.lock:
        await bd_store.ensure_ready_locked()
    if not _ca_storage_ready():
        await refuse("Durable storage isn't ready for a confirmed action. No action was taken.")
        return True
    created_at = getattr(message, "created_at", None)
    if not created_at or abs((_ca_datetime.datetime.now(_ca_datetime.timezone.utc) - created_at).total_seconds()) > SOURCE_MAX_AGE_SECONDS:
        await refuse("That request is too old. Send a fresh instruction.")
        return True
    key, now = (gid, message.author.id), _ca_time.monotonic()
    for source, expires in list(_CA_RECENT_SOURCES.items()):
        if expires <= now:
            _CA_RECENT_SOURCES.pop(source, None)
    source = (gid, message.id)
    if source in _CA_RECENT_SOURCES or f"{gid}:chat:{message.id}" in _ca_receipts(gid):
        return True
    pending = _CA_PENDING.get(key)
    if pending and (pending.state == "executing" or (pending.state == "pending" and pending.expires_at > now)):
        await refuse("Finish or cancel your existing confirmation first.")
        return True
    before = economy_balance(gid, target.id) if proposal.action.startswith("economy.") else None
    if proposal.action == "economy.remove_catnip" and before < proposal.amount:
        await refuse(f"That member has {before:,} Catnip. Request an amount within that balance.")
        return True
    view = _CAConfirm(gid, message.author.id, target.id, proposal.action, proposal.seconds,
        amount=proposal.amount, source_id=message.id, channel_id=message.channel.id, balance_before=before)
    _CA_PENDING[key] = view
    if len(_CA_RECENT_SOURCES) >= 10000:
        _CA_RECENT_SOURCES.pop(next(iter(_CA_RECENT_SOURCES)))
    _CA_RECENT_SOURCES[source] = now + SOURCE_MAX_AGE_SECONDS
    label = _ca_action_label(proposal.action, proposal.seconds, proposal.amount)
    card = discord.Embed(title="🐈 Cinnamon · Confirm this magnificent responsibility",
        description=f"**Action:** {label}\n**Target:** {target.display_name} ({target.id})\n"
                    f"**Requester:** {message.author.display_name} ({message.author.id})\n\n"
                    "No action happens until the original requester confirms.", color=0xD97732)
    card.set_footer(text="Expires after 60 seconds or restart · Permissions checked again on click")
    try:
        view.message = await message.reply(embed=card, view=view, mention_author=False,
                                            allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        view._finish("failed")
        raise
    return True



async def _ca_maybe_prank(message):
    """Opt-in tiny timeout: <=1 per member per UTC day, at most 10 seconds."""
    if not message.guild or not isinstance(message.author, discord.Member):
        return False
    gid, member = message.guild.id, message.author
    server = _ca_server(gid)
    rec = _ca_user(gid, member.id)
    if not server.get("play_enabled", False) or not rec.get("consent", False):
        return False
    if _ca_random.random() >= 0.015:
        return False
    key = (gid, member.id)
    lock = _CA_LOCKS.setdefault(key, _ca_asyncio.Lock())
    async with lock:
        utcnow = _ca_datetime.datetime.now(_ca_datetime.timezone.utc)
        if rec.get("last_play_day") == utcnow.date().isoformat():
            return False
        me = message.guild.me
        if (not me or not me.guild_permissions.moderate_members
                or member.id == message.guild.owner_id
                or member.guild_permissions.administrator
                or member.guild_permissions.moderate_members
                or member.top_role >= me.top_role):
            return False
        if member.timed_out_until and member.timed_out_until > utcnow:
            return False
        seconds = _ca_random.randint(1, 10)
        try:
            await member.timeout(_ca_datetime.timedelta(seconds=seconds),
                reason="Cinnamon consensual mini-prank; member opted in; once per UTC day")
        except (discord.Forbidden, discord.HTTPException):
            return False
        rec["last_play_day"] = utcnow.date().isoformat()
        await bd_save_data()
        await send_log(gid,title="🐈 Consensual Cinnamon prank timeout",category="mood",
            fields=[("Member",f"{member} ({member.id})"),
                    ("Seconds",str(seconds)),("Consent","Member opted in; staff opted in server"),
                    ("Daily count","1 / UTC day")])
    await message.reply(
        f"😼 COURT OF CAT LAW! A tiny **{seconds}-second** nap sentence! "
        "You opted into my jokes, so this counts as today's one little prank. 🐾",
        mention_author=False,allowed_mentions=discord.AllowedMentions.none())
    return True


_ca_group = app_commands.Group(name="cinnamon-prank",description="Manage Cinnamon's opt-in tiny timeouts")


@_ca_group.command(name="consent",description="Allow or refuse Cinnamon's once-a-day 1–10 second joke")
@app_commands.guild_only()
async def cinnamon_prank_consent(interaction: discord.Interaction, enabled: bool):
    rec = _ca_user(interaction.guild.id, interaction.user.id)
    rec["consent"] = bool(enabled)
    await bd_save_data()
    await interaction.response.send_message(
        ("🐈 You opted in. Cinnamon might play ONE 1–10 second timeout joke per UTC day when you call her."
         if enabled else "🔒 Opted out. Cinnamon won't play timeout jokes on you."),
        ephemeral=True)


@_ca_group.command(name="enable",description="Admin: enable or disable consent-based timeout jokes for this server")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_prank_enable(interaction: discord.Interaction, enabled: bool):
    _ca_server(interaction.guild.id)["play_enabled"] = bool(enabled)
    await bd_save_data()
    await send_log(interaction.guild.id,title="🐈 Cinnamon prank config",category="mood",
        fields=[("Administrator",f"{interaction.user} ({interaction.user.id})"),
                ("Enabled",str(bool(enabled)))])
    await interaction.response.send_message(
        "🐈 Playful 1–10 second timeouts " + ("enabled" if enabled else "disabled") +
        ". Members must personally opt in; staff, owners and already-timed-out people are protected.",
        ephemeral=True)


@_ca_group.command(name="status",description="See whether Cinnamon's tiny timeouts are available to you")
@app_commands.guild_only()
async def cinnamon_prank_status(interaction: discord.Interaction):
    server = _ca_server(interaction.guild.id)
    member = _ca_user(interaction.guild.id,interaction.user.id)
    today = _ca_datetime.datetime.now(_ca_datetime.timezone.utc).date().isoformat()
    await interaction.response.send_message(
        f"🐈 Server enabled: **{bool(server.get('play_enabled',False))}**\n"
        f"Your consent: **{bool(member.get('consent',False))}**\n"
        f"Prank already used today: **{member.get('last_play_day')==today}**\n"
        "One per UTC day, 1–10 seconds, only when you invite Cinnamon.",
        ephemeral=True)


bot.tree.add_command(_ca_group)
