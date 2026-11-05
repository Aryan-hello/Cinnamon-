"""Persistent, self-addressed reminders with at-most-once delivery semantics.

Loaded into main.py's shared namespace after the Brain and action modules.
No model output is permitted to schedule reminders. The existing activity
scheduler calls _cr_tick; no second ticking task or Discord login is created.
"""
import asyncio as _cr_asyncio
import datetime as _cr_datetime
import time as _cr_time
import uuid as _cr_uuid
from cinnamon_modules.brain_reminders import (
    parse_reminder_request as _cr_parse,
    ReminderRequestError as _cr_parse_error,
)
from cinnamon_modules.brain_member_v2 import (
    parse_timezone_setting as _cr_parse_timezone,
    format_timezone_offset as _cr_format_timezone,
    PersonalSettingError as _cr_setting_error,
)

_CR_LOCK = _cr_asyncio.Lock()
_CR_MAX_ACTIVE = 10
_CR_BATCH = 6
_CR_STALE_RECORD_SECONDS = 30 * 86400
_CR_MAX_LATE_SECONDS = 24 * 3600


def _cr_server(gid):
    return advanced_features_data.setdefault("cinnamon_reminders_v1", {}).setdefault(
        str(gid), {"members": {}})


def _cr_member(gid, uid):
    return _cr_server(gid).setdefault("members", {}).setdefault(str(uid), {})


def _cr_offset(gid, uid):
    """The user's explicitly chosen offset, otherwise the server default."""
    saved = _cr_server(gid).setdefault("timezones", {}).get(str(uid))
    try:
        minutes = int(saved) if saved is not None else CINNAMON_TIMEZONE_OFFSET_MINUTES
        return minutes if -720 <= minutes <= 840 else CINNAMON_TIMEZONE_OFFSET_MINUTES
    except (TypeError, ValueError):
        return CINNAMON_TIMEZONE_OFFSET_MINUTES


async def _cr_set_offset(gid, uid, offset):
    async with _CR_LOCK:
        settings = _cr_server(gid).setdefault("timezones", {})
        key = str(uid)
        prior = settings.get(key)
        if offset is None:
            settings.pop(key, None)
        else:
            settings[key] = int(offset)
        if not await bd_save_data():
            if prior is None:
                settings.pop(key, None)
            else:
                settings[key] = prior
            return False
        return True


def _cr_active(gid, uid):
    return [item for item in _cr_member(gid, uid).values()
            if item.get("status") == "scheduled"]


def _cr_format(item):
    return (f"`{item['id']}` — **{discord.utils.escape_markdown(item['text'])}** "
            f"· <t:{int(item['due_at'])}:F> (<t:{int(item['due_at'])}:R>)"
            f" · {item.get('status', 'unknown')}")


async def _cr_schedule(gid, uid, spec, *, source_id=None):
    """Atomically acknowledge in the snapshot before claiming a reminder."""
    async with _CR_LOCK:
        member = _cr_member(gid, uid)
        # Re-delivery of the same Discord request must not schedule again.
        if source_id is not None:
            for prior in member.values():
                if prior.get("source_id") == int(source_id):
                    return prior, ""
        if len(_cr_active(gid, uid)) >= _CR_MAX_ACTIVE:
            return None, "I can keep up to 10 active reminders per member. Cancel an old one first."
        rid = _cr_uuid.uuid4().hex[:10]
        while rid in member:
            rid = _cr_uuid.uuid4().hex[:10]
        item = {"id": rid, "text": spec.text,
                "due_at": int(spec.due_at), "timezone": spec.timezone_label,
                "status": "scheduled", "created_at": int(_cr_time.time()),
                "source_id": int(source_id) if source_id is not None else None}
        member[rid] = item
        if not await bd_save_data():
            member.pop(rid, None)
            return None, "My reminder storage didn't confirm the save. Nothing is scheduled."
        return item, ""


async def _cr_cancel(gid, uid, rid):
    async with _CR_LOCK:
        member = _cr_member(gid, uid)
        item = member.get(str(rid).strip().lower())
        if not item:
            return False, "I can't find that reminder in your list."
        if item.get("status") != "scheduled":
            return False, "That reminder is already being delivered or has finished."
        item["status"] = "cancelled"
        if not await bd_save_data():
            item["status"] = "scheduled"
            return False, "Storage didn't confirm the cancellation. Try again later."
        return True, "Reminder cancelled. No surprise alarm-cat from me. 🐾"


async def _cr_snooze(gid, uid, rid, minutes):
    """Postpone only a member's scheduled reminder; never replay a sent DM."""
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        return False, "Snooze by 1–1,440 minutes (up to 24 hours)."
    async with _CR_LOCK:
        item = _cr_member(gid, uid).get(str(rid).strip().lower())
        if not item:
            return False, "That reminder ID isn't in your personal list."
        if item.get("status") != "scheduled":
            return False, "This reminder was already delivered, cancelled, or is being sent."
        now = int(_cr_time.time())
        old_due = int(item.get("due_at", 0))
        due_at = max(now, old_due) + minutes * 60
        if due_at > now + 30 * 86400:
            return False, "The new reminder must be within 30 days."
        previous = dict(item)
        item["due_at"] = due_at
        item["snoozed_at"] = now
        item["snoozes"] = min(1000, int(item.get("snoozes", 0)) + 1)
        if not await bd_save_data():
            item.clear()
            item.update(previous)
            return False, "Storage didn't confirm the snooze. The original time is unchanged."
        return True, f"🐱 Snoozed! Your new reminder time is <t:{due_at}:F>."


async def _cr_deliver(gid, uid, rid):
    """A durably marked 'sending' reminder must never be blindly repeated.

    Crash after recording sending but before/after Discord delivery is
    intentionally uncertain, not an automatic duplicate DM.
    """
    async with _CR_LOCK:
        item = _cr_member(gid, uid).get(rid)
        if not item or item.get("status") != "scheduled":
            return
        if int(item.get("due_at", 0)) > int(_cr_time.time()):
            return
        item["status"] = "sending"
        item["attempted_at"] = int(_cr_time.time())
        if not await bd_save_data():
            item["status"] = "scheduled"
            item.pop("attempted_at", None)
            return
    delivered = False
    try:
        user = bot.get_user(int(uid))
        if user is None:
            user = await bot.fetch_user(int(uid))
        await user.send(
            "🐱 **CINNAMON REMINDER!**\n" +
            discord.utils.escape_markdown(item["text"]) +
            "\n*I remembered. YOU'RE WELCOME. 😼*",
            allowed_mentions=discord.AllowedMentions.none())
        delivered = True
    except (discord.Forbidden, discord.HTTPException, AttributeError) as exc:
        log.warning("Reminder DM unavailable for guild %s member %s (%s)",
                    gid, uid, type(exc).__name__)
    async with _CR_LOCK:
        # Never rewrite a concurrently changed or recovered status.
        if item.get("status") != "sending":
            return
        item["status"] = "sent" if delivered else "failed"
        item["finished_at"] = int(_cr_time.time())
        if not await bd_save_data():
            # Durable 'sending' remains a safe, non-retryable uncertain result.
            item["status"] = "uncertain"
            log.error("Reminder delivery result could not be durably saved: %s", rid)


async def _cr_tick():
    """Called by the existing Cinnamon social scheduler every tick."""
    if not _cb_storage_available():
        return
    now = int(_cr_time.time())
    # Expire reminders that would arrive more than a day late after downtime.
    # Completed history older than 30 days is discarded to bound stored data.
    async with _CR_LOCK:
        changed = []
        for guild in advanced_features_data.get("cinnamon_reminders_v1", {}).values():
            if not isinstance(guild, dict):
                continue
            for member in guild.get("members", {}).values():
                if not isinstance(member, dict):
                    continue
                for rid, item in list(member.items()):
                    status = item.get("status")
                    if status == "scheduled" and now - int(item.get("due_at", now)) > _CR_MAX_LATE_SECONDS:
                        old = dict(item)
                        item["status"], item["finished_at"] = "missed", now
                        changed.append((member, rid, old))
                    elif status in ("sent", "failed", "cancelled", "missed", "uncertain", "sending"):
                        last = int(item.get("finished_at", item.get("attempted_at",
                               item.get("created_at", now))))
                        if now - last > _CR_STALE_RECORD_SECONDS:
                            changed.append((member, rid, dict(item)))
                            member.pop(rid, None)
        if changed and not await bd_save_data():
            for member, rid, old in changed:
                member[rid] = old
            return
    due = []
    for gid, guild in list(advanced_features_data.get("cinnamon_reminders_v1", {}).items()):
        if not isinstance(guild, dict):
            continue
        for uid, member in list(guild.get("members", {}).items()):
            if not isinstance(member, dict):
                continue
            for rid, item in list(member.items()):
                if not isinstance(item, dict):
                    continue
                if (item.get("status") == "scheduled"
                        and int(item.get("due_at", 0)) <= now):
                    due.append((gid, uid, rid, int(item.get("due_at", 0))))
    for gid, uid, rid, _ in sorted(due, key=lambda row: row[3])[:_CR_BATCH]:
        try:
            await _cr_deliver(gid, uid, rid)
        except _cr_asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Cinnamon reminder delivery failed unexpectedly (id %s)", rid)


async def _cr_maybe_handle(message, clean_content):
    """Recognize only the current member's explicit reminder request."""
    if not message.guild:
        return False
    try:
        spec = _cr_parse(
            clean_content, now=_cr_datetime.datetime.now(_cr_datetime.timezone.utc),
            offset_minutes=_cr_offset(message.guild.id, message.author.id))
    except _cr_parse_error as exc:
        await message.reply("🐾 " + str(exc), mention_author=False,
                            allowed_mentions=discord.AllowedMentions.none())
        return True
    if spec is None:
        return False
    item, error = await _cr_schedule(message.guild.id, message.author.id, spec,
                                     source_id=message.id)
    if error:
        response = "🐈 " + error
    else:
        response = (f"🐱 Reminder saved! I'll DM you about **{discord.utils.escape_markdown(item['text'])}** "
                    f"on <t:{item['due_at']}:F> ({spec.timezone_label}). "
                    f"Your reminder ID is `{item['id']}`. "
                    "You can view it with `/cinnamon-reminder list` or cancel it with `/cinnamon-reminder cancel`.")
    await message.reply(response[:1800], mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none())
    return True


_cr_group = app_commands.Group(
    name="cinnamon-reminder",
    description="Create, snooze, and manage your private Cinnamon reminders",
)


@_cr_group.command(name="create", description="Remind yourself about something in the future")
@app_commands.guild_only()
async def cinnamon_reminder_create(interaction: discord.Interaction, text: str, when: str):
    await interaction.response.defer(ephemeral=True)
    try:
        spec = _cr_parse(
            f"remind me to {text} {when}",
            now=_cr_datetime.datetime.now(_cr_datetime.timezone.utc),
            offset_minutes=_cr_offset(interaction.guild.id, interaction.user.id))
    except _cr_parse_error as exc:
        return await interaction.followup.send(
            "🐾 " + str(exc), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())
    if spec is None:
        return await interaction.followup.send(
            "Use a time like 'in 1 hour' or 'tomorrow at 6 PM'.", ephemeral=True)
    item, error = await _cr_schedule(interaction.guild.id, interaction.user.id, spec,
                                     source_id=interaction.id)
    await interaction.followup.send(
        ("🐈 " + error) if error else
        f"🐱 Saved reminder `{item['id']}` for <t:{item['due_at']}:F>. "
        "I'll DM you when it's due!",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cr_group.command(name="list", description="Privately list your recent reminders")
@app_commands.guild_only()
async def cinnamon_reminder_list(interaction: discord.Interaction):
    member = _cr_member(interaction.guild.id, interaction.user.id)
    items = sorted(member.values(), key=lambda i: int(i.get("created_at", 0)), reverse=True)[:12]
    lines = [_cr_format(i) for i in items]
    await interaction.response.send_message(
        "🐈 **Your personal reminders**\n" +
        ("\n".join(lines)[:1700] if lines else "No reminders yet. My calendar is suspiciously empty."),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cr_group.command(name="cancel", description="Cancel your pending reminder by its ID")
@app_commands.guild_only()
async def cinnamon_reminder_cancel(interaction: discord.Interaction, reminder_id: str):
    success, text = await _cr_cancel(interaction.guild.id, interaction.user.id, reminder_id)
    await interaction.response.send_message(
        ("✅ " if success else "🐾 ") + text,
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cr_group.command(name="timezone", description="View or set your personal fixed UTC reminder timezone")
@app_commands.guild_only()
@app_commands.describe(offset="UTC+05:30, UTC-04:00, UTC, or 'server' to reset; omit to view")
async def cinnamon_reminder_timezone(interaction: discord.Interaction,
                                     offset: str | None = None):
    gid, uid = interaction.guild.id, interaction.user.id
    if offset is None:
        label = _cr_format_timezone(_cr_offset(gid, uid))
        custom = str(uid) in _cr_server(gid).get("timezones", {})
        return await interaction.response.send_message(
            f"🕒 Your reminder timezone is **{label}** "
            + ("(your personal setting)." if custom else "(this server's default).")
            + " This is a fixed UTC offset; it doesn't automatically adjust for daylight saving.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    try:
        minutes = _cr_parse_timezone(offset)
    except _cr_setting_error as exc:
        return await interaction.response.send_message(
            "🐾 " + str(exc), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())
    await interaction.response.defer(ephemeral=True)
    if not await _cr_set_offset(gid, uid, minutes):
        return await interaction.followup.send(
            "⚠️ Storage didn't confirm the timezone change. Your previous setting remains.",
            ephemeral=True)
    new_value = _cr_format_timezone(_cr_offset(gid, uid))
    await interaction.followup.send(
        f"🕒 Your future reminder times now use **{new_value}**. "
        "Previously scheduled reminders keep their UTC delivery times. "
        "Fixed offsets don't automatically adjust for daylight saving.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cr_group.command(name="snooze", description="Postpone one of your pending reminders")
@app_commands.guild_only()
@app_commands.describe(reminder_id="Your reminder ID from /cinnamon-reminder list",
                       minutes="How many minutes to delay it (1–1440)")
async def cinnamon_reminder_snooze(interaction: discord.Interaction,
                                  reminder_id: str,
                                  minutes: app_commands.Range[int, 1, 1440]):
    await interaction.response.defer(ephemeral=True)
    ok, result = await _cr_snooze(interaction.guild.id, interaction.user.id,
                                  reminder_id, int(minutes))
    await interaction.followup.send(
        result if ok else "🐾 " + result,
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


bot.tree.add_command(_cr_group)
