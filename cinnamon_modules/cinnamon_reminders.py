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

_CR_LOCK = _cr_asyncio.Lock()
_CR_MAX_ACTIVE = 10
_CR_BATCH = 6
_CR_STALE_RECORD_SECONDS = 30 * 86400


def _cr_server(gid):
    return advanced_features_data.setdefault("cinnamon_reminders_v1", {}).setdefault(
        str(gid), {"members": {}})


def _cr_member(gid, uid):
    return _cr_server(gid).setdefault("members", {}).setdefault(str(uid), {})


def _cr_active(gid, uid):
    return [item for item in _cr_member(gid, uid).values()
            if item.get("status") == "scheduled"]


def _cr_format(item):
    return (f"`{item['id']}` — **{discord.utils.escape_markdown(item['text'])}** "
            f"· <t:{int(item['due_at'])}:F> (<t:{int(item['due_at'])}:R>)"
            f" · {item.get('status', 'unknown')}")


async def _cr_schedule(gid, uid, spec):
    """Atomically acknowledge in the snapshot before claiming a reminder."""
    async with _CR_LOCK:
        member = _cr_member(gid, uid)
        if len(_cr_active(gid, uid)) >= _CR_MAX_ACTIVE:
            return None, "I can keep up to 10 active reminders per member. Cancel an old one first."
        rid = _cr_uuid.uuid4().hex[:10]
        while rid in member:
            rid = _cr_uuid.uuid4().hex[:10]
        item = {"id": rid, "text": spec.text,
                "due_at": int(spec.due_at), "timezone": spec.timezone_label,
                "status": "scheduled", "created_at": int(_cr_time.time())}
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
            offset_minutes=CINNAMON_TIMEZONE_OFFSET_MINUTES)
    except _cr_parse_error as exc:
        await message.reply("🐾 " + str(exc), mention_author=False,
                            allowed_mentions=discord.AllowedMentions.none())
        return True
    if spec is None:
        return False
    item, error = await _cr_schedule(message.guild.id, message.author.id, spec)
    if error:
        response = "🐈 " + error
    else:
        response = (f"🐱 Reminder saved! I'll DM you about **{discord.utils.escape_markdown(item['text'])}** "
                    f"on <t:{item['due_at']}:F> ({spec.timezone_label}). "
                    f"Your reminder ID is `{item['id']}`. "
                    "You can see or cancel it with `/cinnamon-reminder`.")
    await message.reply(response[:1800], mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none())
    return True


_cr_group = app_commands.Group(
    name="cinnamon-reminder",
    description="Create, view, and cancel your personal Cinnamon reminders",
)


@_cr_group.command(name="create", description="Remind yourself about something in the future")
@app_commands.guild_only()
async def cinnamon_reminder_create(interaction: discord.Interaction, text: str, when: str):
    await interaction.response.defer(ephemeral=True)
    try:
        spec = _cr_parse(
            f"remind me to {text} {when}",
            now=_cr_datetime.datetime.now(_cr_datetime.timezone.utc),
            offset_minutes=CINNAMON_TIMEZONE_OFFSET_MINUTES)
    except _cr_parse_error as exc:
        return await interaction.followup.send(
            "🐾 " + str(exc), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())
    if spec is None:
        return await interaction.followup.send(
            "Use a time like 'in 1 hour' or 'tomorrow at 6 PM'.", ephemeral=True)
    item, error = await _cr_schedule(interaction.guild.id, interaction.user.id, spec)
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


bot.tree.add_command(_cr_group)
