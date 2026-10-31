"""Cinnamon's transparent, server-scoped and member-controlled preference memory.

No passive chat capture. Users can inspect/delete their own notes, and
request corrections through private owner-reviewed tickets. Raw messages,
health data, addresses and contact info are not written into memories.
"""
import asyncio as _cmem_asyncio
import copy as _cmem_copy
import re as _cmem_re
import time as _cmem_time
import uuid as _cmem_uuid
from cinnamon_modules.brain_memory import (
    ALLOWED_CATEGORIES as _CMEM_CATEGORIES,
    MAX_NOTES as _CMEM_MAX,
    MemoryValidationError as _CMEM_ERROR,
    parse_explicit_preference as _cmem_parse,
    safe_context as _cmem_safe_context,
    validate_preference as _cmem_validate,
)

_CMEM_LOCK = _cmem_asyncio.Lock()
_CMEM_MAX_OPEN_TICKETS = 5


def _cmem_root(gid):
    return advanced_features_data.setdefault("cinnamon_memory_v1", {}).setdefault(
        str(gid), {"members": {}, "tickets": {}})


def _cmem_member(gid, uid):
    return _cmem_root(gid).setdefault("members", {}).setdefault(
        str(uid), {"enabled": True, "notes": []})


def _cmem_public_note(note):
    return (f"`{note.get('id', '?')}` [{note.get('category', '?')}] "
            f"{discord.utils.escape_markdown(str(note.get('detail', ''))[:120])}")


def _cmem_context(gid, uid):
    """Private data for this single member in this guild only."""
    member = _cmem_member(gid, uid)
    return (_cmem_safe_context(member.get("notes", []))
            if member.get("enabled", True) else "")


async def _cmem_save(gid, uid, category, detail):
    preference = _cmem_validate(category, detail)
    async with _CMEM_LOCK:
        member = _cmem_member(gid, uid)
        if not member.get("enabled", True):
            return None, "Memory is off for you. Use /cinnamon-memory enable first."
        notes = member.setdefault("notes", [])
        if len(notes) >= _CMEM_MAX:
            return None, "Your memory is full (12 preferences). Remove one first."
        if any(n.get("category") == preference.category
               and n.get("detail", "").lower() == preference.detail.lower()
               for n in notes):
            return None, "I already have that preference saved."
        rid = _cmem_uuid.uuid4().hex[:8]
        note = {"id": rid, "category": preference.category,
                "detail": preference.detail, "saved_at": int(_cmem_time.time())}
        notes.append(note)
        if not await bd_save_data():
            notes.pop()
            return None, "Memory storage didn't confirm the save. I didn't add it."
        return note, ""


async def _cmem_edit(gid, uid, note_id, updated):
    """Member-only self-correction; no owner review or cross-guild access."""
    async with _CMEM_LOCK:
        member = _cmem_member(gid, uid)
        if not member.get("enabled", True):
            return False, "Your memory is disabled."
        note = next((item for item in member.get("notes", [])
                     if item.get("id") == str(note_id).strip().lower()), None)
        if note is None:
            return False, "That preference ID isn't in your private memory."
        preference = _cmem_validate(note.get("category"), updated)
        if any(other is not note and other.get("category") == preference.category
               and str(other.get("detail", "")).lower() == preference.detail.lower()
               for other in member.get("notes", [])):
            return False, "You already saved an identical preference."
        if note.get("detail") == preference.detail:
            return True, "That preference already says exactly that."
        old_note = _cmem_copy.deepcopy(note)
        tickets = _cmem_root(gid).setdefault("tickets", {})
        old_tickets = _cmem_copy.deepcopy(tickets)
        note["detail"] = preference.detail
        note["saved_at"] = int(_cmem_time.time())
        # The member's own correction supersedes any pending owner's review.
        for ticket in tickets.values():
            if (ticket.get("uid") == int(uid)
                    and ticket.get("note_id") == note.get("id")
                    and ticket.get("status") == "open"):
                ticket["status"] = "withdrawn"
                ticket["original"] = ""
                ticket["detail"] = ""
        if not await bd_save_data():
            note.clear()
            note.update(old_note)
            tickets.clear()
            tickets.update(old_tickets)
            return False, "Storage didn't confirm your edit. The old preference is unchanged."
        return True, "Preference updated. You're in control of what I remember. 🐾"


async def _cmem_remove(gid, uid, note_id=None):
    async with _CMEM_LOCK:
        member = _cmem_member(gid, uid)
        before = _cmem_copy.deepcopy(member.get("notes", []))
        tickets = _cmem_root(gid).setdefault("tickets", {})
        prior_tickets = _cmem_copy.deepcopy(tickets)
        if note_id is None:
            member["notes"] = []
            for ticket in tickets.values():
                if ticket.get("uid") == int(uid) and ticket.get("status") == "open":
                    ticket["status"] = "withdrawn"
                    ticket["original"] = ""
                    ticket["detail"] = ""
        else:
            member["notes"] = [n for n in before if n.get("id") != str(note_id).strip().lower()]
            if len(before) == len(member["notes"]):
                return False, "I couldn't find that memory ID in your notes."
            for ticket in tickets.values():
                if (ticket.get("uid") == int(uid)
                        and ticket.get("note_id") == str(note_id).strip().lower()
                        and ticket.get("status") == "open"):
                    ticket["status"] = "withdrawn"
                    ticket["original"] = ""
                    ticket["detail"] = ""
        if not await bd_save_data():
            member["notes"] = before
            tickets.clear()
            tickets.update(prior_tickets)
            return False, "Memory storage didn't confirm the change. Try again later."
        return True, ("All your Cinnamon notes were cleared." if note_id is None
                      else "That note was removed from your memory.")


async def _cmem_set_enabled(gid, uid, enabled):
    async with _CMEM_LOCK:
        member = _cmem_member(gid, uid)
        before = _cmem_copy.deepcopy(member)
        tickets = _cmem_root(gid).setdefault("tickets", {})
        old_tickets = _cmem_copy.deepcopy(tickets) if not enabled else None
        member["enabled"] = bool(enabled)
        if not enabled:
            member["notes"] = []
            # Remove open correction tickets containing that user's preferences.
            for ticket_id, ticket in list(tickets.items()):
                if (ticket.get("uid") == int(uid) and
                        ticket.get("status") == "open"):
                    ticket["status"] = "withdrawn"
                    ticket["original"] = ""
                    ticket["detail"] = ""
        if not await bd_save_data():
            member.clear()
            member.update(before)
            if old_tickets is not None:
                tickets.clear()
                tickets.update(old_tickets)
            return False
        return True


async def _cmem_ticket(gid, uid, note_id, proposed):
    async with _CMEM_LOCK:
        member = _cmem_member(gid, uid)
        if not member.get("enabled", True):
            return None, "Memory is off for you."
        note = next((n for n in member.get("notes", [])
                     if n.get("id") == str(note_id).strip().lower()), None)
        if not note:
            return None, "That note ID isn't in your memory."
        fixed = _cmem_validate(note["category"], proposed)
        tickets = _cmem_root(gid).setdefault("tickets", {})
        if sum(1 for v in tickets.values() if v.get("uid") == int(uid)
               and v.get("status") == "open") >= _CMEM_MAX_OPEN_TICKETS:
            return None, "You already have five pending correction requests."
        ticket_id = _cmem_uuid.uuid4().hex[:8]
        ticket = {"id": ticket_id, "uid": int(uid), "note_id": note["id"],
                  "category": note["category"], "original": note["detail"],
                  "detail": fixed.detail, "status": "open",
                  "created_at": int(_cmem_time.time())}
        tickets[ticket_id] = ticket
        if not await bd_save_data():
            tickets.pop(ticket_id, None)
            return None, "Storage didn't confirm your request. Try again later."
        return ticket, ""


async def _cmem_resolve(gid, ticket_id, approve):
    async with _CMEM_LOCK:
        root = _cmem_root(gid)
        ticket = root.setdefault("tickets", {}).get(str(ticket_id).strip().lower())
        if not ticket or ticket.get("status") != "open":
            return False, "That correction request isn't open."
        uid = ticket["uid"]
        member = _cmem_member(gid, uid)
        note = next((n for n in member.get("notes", [])
                     if n.get("id") == ticket.get("note_id")), None)
        if approve and (not member.get("enabled", True) or not note or
                        note.get("detail") != ticket.get("original")):
            return False, "The original note changed. Ask the member to submit a new request."
        old_note = _cmem_copy.deepcopy(note) if note else None
        if approve:
            try:
                fixed = _cmem_validate(ticket["category"], ticket["detail"])
            except _CMEM_ERROR:
                return False, "That correction no longer passes validation."
            note["detail"] = fixed.detail
            note["saved_at"] = int(_cmem_time.time())
        old_ticket = _cmem_copy.deepcopy(ticket)
        ticket["status"] = "approved" if approve else "declined"
        ticket["resolved_at"] = int(_cmem_time.time())
        # Do not retain superseded private preference text in ticket history.
        ticket["original"] = ""
        ticket["detail"] = ""
        if not await bd_save_data():
            if old_note is not None:
                note.clear()
                note.update(old_note)
            ticket.clear()
            ticket.update(old_ticket)
            return False, "Storage didn't confirm the decision."
        return True, "Correction approved." if approve else "Correction declined."


async def _cmem_maybe_handle(message, clean_content):
    if not message.guild:
        return False
    text = str(clean_content or "").strip()

    # Natural-language privacy controls are always scoped to the current member.
    # Only unambiguous opt-in/opt-out requests change settings. A vague "forget
    # this" never guesses which saved preference should be deleted.
    if _cmem_re.search(
            r"^(?:turn|switch)\s+(?:my\s+)?memory\s+off[.! ]*$|"
            r"^forget\s+everything\s+about\s+me[.! ]*$",
            text, _cmem_re.I):
        saved = await _cmem_set_enabled(message.guild.id, message.author.id, False)
        reply = ("🔒 Memory is off and your saved preferences were cleared."
                 if saved else
                 "⚠️ Storage didn't confirm that change. Your previous memory setting remains.")
        await message.reply(reply, mention_author=False,
                            allowed_mentions=discord.AllowedMentions.none())
        return True
    if _cmem_re.search(
            r"^(?:turn|switch)\s+(?:my\s+)?memory\s+on[.! ]*$",
            text, _cmem_re.I):
        saved = await _cmem_set_enabled(message.guild.id, message.author.id, True)
        reply = ("🧠 Memory is enabled. I'll only save preferences you explicitly ask me to keep."
                 if saved else
                 "⚠️ Storage didn't confirm that change. Your previous memory setting remains.")
        await message.reply(reply, mention_author=False,
                            allowed_mentions=discord.AllowedMentions.none())
        return True
    if _cmem_re.search(
            r"^(?:forget|delete|remove)\s+(?:my\s+)?(?:saved\s+)?(?:preference|note|memory|notes)[.! ]*$",
            text, _cmem_re.I):
        await message.reply(
            "🐾 I won't guess which note you mean. Use /cinnamon-memory view "
            "then /cinnamon-memory forget note_id:<ID>, or /cinnamon-memory clear "
            "to erase all your saved preferences.",
            mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        return True
    if _cmem_re.search(
            r"^(?:show|view)\s+my\s+(?:memories|memory|notes|preferences)[.! ]*$",
            text, _cmem_re.I) or _cmem_re.search(
            r"^what\s+do\s+you\s+remember\s+about\s+me[?!. ]*$",
            text, _cmem_re.I):
        await message.reply(
            "🐈 Your notes are private! Use /cinnamon-memory view to inspect, "
            "/cinnamon-memory edit to correct, or /cinnamon-memory forget to remove one.",
            mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        return True
    try:
        pref = _cmem_parse(text)
    except _CMEM_ERROR as exc:
        await message.reply(
            "🐾 " + str(exc), mention_author=False,
            allowed_mentions=discord.AllowedMentions.none())
        return True
    if pref is None:
        return False
    note, error = await _cmem_save(message.guild.id, message.author.id,
                                   pref.category, pref.detail)
    await message.reply(
        "🐱 " + error if error else
        f"🐈 Saved a {pref.category} preference! View or delete it privately "
        "with `/cinnamon-memory view` or `/cinnamon-memory forget`. I only save what you explicitly ask me to keep.",
        mention_author=False, allowed_mentions=discord.AllowedMentions.none())
    return True


_cmem_group = app_commands.Group(
    name="cinnamon-memory", description="Private preference memory and correction requests")


@_cmem_group.command(name="status", description="See your personal memory setting and note count")
@app_commands.guild_only()
async def cinnamon_memory_status(interaction: discord.Interaction):
    member = _cmem_member(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message(
        "🧠 **Cinnamon's private preference memory**\n"
        f"Enabled: **{member.get('enabled', True)}** · "
        f"Saved notes: **{len(member.get('notes', []))} / {_CMEM_MAX}**\n"
        "Only preferences you deliberately ask me to save are stored. "
        "Your notes are scoped to this server. You can inspect, correct, remove, "
        "or turn off memory whenever you want. Conversation excerpts are temporary.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cmem_group.command(name="enable", description="Allow Cinnamon to save preferences you explicitly share")
@app_commands.guild_only()
async def cinnamon_memory_enable(interaction: discord.Interaction, enabled: bool):
    await interaction.response.defer(ephemeral=True)
    saved = await _cmem_set_enabled(interaction.guild.id, interaction.user.id, enabled)
    await interaction.followup.send(
        ("🧠 Memory enabled. Only intentionally saved preferences are remembered."
         if enabled else
         "🔒 Memory off. Your saved preferences have been cleared.")
        if saved else "⚠️ Storage didn't confirm that change. Check again later.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cmem_group.command(name="save", description="Privately save an ordinary preference")
@app_commands.guild_only()
async def cinnamon_memory_save(interaction: discord.Interaction, category: str, detail: str):
    await interaction.response.defer(ephemeral=True)
    try:
        note, error = await _cmem_save(interaction.guild.id, interaction.user.id,
                                      category, detail)
    except _CMEM_ERROR as exc:
        error, note = str(exc), None
    await interaction.followup.send(
        "🐾 " + error if error else
        f"✅ Saved preference `{note['id']}`. You can view or remove it anytime.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cmem_group.command(name="edit", description="Correct your own saved preference immediately and privately")
@app_commands.guild_only()
@app_commands.describe(note_id="Your preference ID from /cinnamon-memory view",
                       new_text="Your corrected preference (same category)")
async def cinnamon_memory_edit(interaction: discord.Interaction,
                               note_id: str, new_text: str):
    await interaction.response.defer(ephemeral=True)
    try:
        success, message = await _cmem_edit(
            interaction.guild.id, interaction.user.id, note_id, new_text)
    except _CMEM_ERROR as exc:
        success, message = False, str(exc)
    await interaction.followup.send(
        ("✅ " if success else "🐾 ") + message,
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cmem_group.command(name="view", description="Privately view everything Cinnamon saved about you")
@app_commands.guild_only()
async def cinnamon_memory_view(interaction: discord.Interaction):
    member = _cmem_member(interaction.guild.id, interaction.user.id)
    notes = member.get("notes", []) if member.get("enabled", True) else []
    await interaction.response.send_message(
        "🧠 **Your Cinnamon notes**\n" +
        ("\n".join(_cmem_public_note(n) for n in notes)[:1700] if notes
         else "No saved preferences. You can add one with /cinnamon-memory save."),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cmem_group.command(name="forget", description="Delete one of your saved preferences")
@app_commands.guild_only()
async def cinnamon_memory_forget(interaction: discord.Interaction, note_id: str):
    await interaction.response.defer(ephemeral=True)
    success, text = await _cmem_remove(interaction.guild.id, interaction.user.id, note_id)
    await interaction.followup.send(("✅ " if success else "🐾 ") + text,
                                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cmem_group.command(name="clear", description="Delete all Cinnamon preference notes for yourself")
@app_commands.guild_only()
async def cinnamon_memory_clear(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    success, text = await _cmem_remove(interaction.guild.id, interaction.user.id)
    await interaction.followup.send(("✅ " if success else "🐾 ") + text,
                                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cmem_group.command(name="correct", description="Privately request the owner to correct a note")
@app_commands.guild_only()
async def cinnamon_memory_correct(interaction: discord.Interaction, note_id: str, new_text: str):
    await interaction.response.defer(ephemeral=True)
    try:
        ticket, error = await _cmem_ticket(interaction.guild.id,
                                          interaction.user.id, note_id, new_text)
    except _CMEM_ERROR as exc:
        ticket, error = None, str(exc)
    await interaction.followup.send(
        "🐾 " + error if error else
        f"🐾 Private correction request `{ticket['id']}` saved for the server owner. "
        "You can also forget the note without waiting for approval.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cmem_group.command(name="tickets", description="Server owner: privately review correction requests")
@app_commands.guild_only()
async def cinnamon_memory_tickets(interaction: discord.Interaction):
    if interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message(
            "Only the server owner can review private correction requests.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    tickets = _cmem_root(interaction.guild.id).get("tickets", {})
    pending = [t for t in tickets.values() if t.get("status") == "open"][:10]
    lines = [
        f"`{t['id']}` Member ID `{t['uid']}` · {t['category']}\n"
        f"From: {discord.utils.escape_markdown(t['original'])}\n"
        f"To: {discord.utils.escape_markdown(t['detail'])}"
        for t in pending
    ]
    await interaction.response.send_message(
        "🧠 **Private memory corrections**\n" +
        ("\n\n".join(lines)[:1700] if lines else "No pending correction requests."),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cmem_group.command(name="resolve", description="Server owner: approve or decline a correction")
@app_commands.guild_only()
async def cinnamon_memory_resolve(interaction: discord.Interaction, ticket_id: str, approve: bool):
    if interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message(
            "Only the server owner may resolve a private correction.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    await interaction.response.defer(ephemeral=True)
    success, text = await _cmem_resolve(interaction.guild.id, ticket_id, approve)
    await interaction.followup.send(("✅ " if success else "🐾 ") + text,
                                    ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


bot.tree.add_command(_cmem_group)
