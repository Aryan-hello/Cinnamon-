"""Cinnamon Brain v2 — simple, private member utility hub.

Read-only summaries of existing member-owned state. No AI inference,
unsolicited messages, privileged access or new background jobs.
"""
import datetime as _me_datetime
from cinnamon_modules.brain_member_v2 import (
    due_today as _me_due_today,
    format_timezone_offset as _me_timezone,
)

_me_group = app_commands.Group(
    name="cinnamon-me",
    description="Private personal tools and privacy controls for Cinnamon",
)


@_me_group.command(name="today", description="Privately see today's reminders and your Cinnamon settings")
@app_commands.guild_only()
async def cinnamon_me_today(interaction: discord.Interaction):
    gid, uid = interaction.guild.id, interaction.user.id
    now = _me_datetime.datetime.now(_me_datetime.timezone.utc)
    offset = _cr_offset(gid, uid)
    user_reminders = list(_cr_member(gid, uid).values())
    today = _me_due_today(user_reminders, now=now, offset_minutes=offset)
    pending_count = sum(1 for item in user_reminders if item.get("status") == "scheduled")
    preference = _cmem_member(gid, uid)
    enabled = bool(preference.get("enabled", True))
    note_count = len(preference.get("notes", [])) if enabled else 0

    lines = [
        "🐈 **CINNAMON'S PRIVATE DAILY CHECK-IN**",
        f"🕒 Your fixed timezone: **{_me_timezone(offset)}**",
        f"⏰ Pending reminders: **{pending_count}** · Due today: **{len(today)}**",
        "",
        "**Today's reminders:**",
    ]
    if today:
        for item in today:
            label = discord.utils.escape_markdown(str(item.get("text", ""))[:100])
            lines.append(f"• <t:{int(item['due_at'])}:t> · {label}")
    else:
        lines.append("• None due today. A suspiciously peaceful calendar.")
    lines.extend([
        "",
        f"🧠 Saved preferences: **{note_count}** "
        + ("(memory enabled)" if enabled else "(memory disabled)"),
    ])
    # Display READ-ONLY summaries of the member's existing, loaded economy
    # and quests. Do not rotate/reset quests, grant rewards or fake balances.
    if _cb_storage_available():
        balance = int(economy_balances.get((gid, uid), ECONOMY_STARTING_BALANCE))
        guild_quests = quest_data.get(gid, {})
        quest_member = guild_quests.get("users", {}).get(str(uid), {})
        qp = int(quest_member.get("qp", 0))
        lines.append(f"🌿 Your Catnip: **{balance:,}** · Quest Points: **{qp:,}**")
        if guild_quests.get("daily_date") == _today():
            daily_ids = guild_quests.get("daily_ids", [])
            daily_progress = quest_member.get("daily", {})
            complete = sum(
                1 for qid in daily_ids
                if qid in DAILY_QUESTS and
                _completed(DAILY_QUESTS[qid], daily_progress.get(qid, {}))
            )
            lines.append(
                f"📜 Daily quests: **{complete}/{len(daily_ids)}** completed. "
                "Open `/quests daily` for details.")
        else:
            lines.append("📜 Today's quest rotation hasn't been checked yet. "
                         "Open `/quests daily` for the current board.")
    else:
        lines.append("⚠️ Saved economy and quest data is not ready; "
                     "I won't guess about your balances.")
    lines.extend([
        "",
        "Use `/cinnamon-reminder create` to add a reminder, "
        "`/cinnamon-reminder snooze` to delay one, or "
        "`/cinnamon-reminder timezone` for your local clock.",
        "Use `/cinnamon-memory view` or `/cinnamon-memory edit` to manage notes.",
        "",
        "*Delivery depends on Cinnamon being online and your DMs allowing messages.*",
    ])
    await interaction.response.send_message(
        "\n".join(lines)[:1800], ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@_me_group.command(name="privacy", description="Explain and manage what Cinnamon remembers about you")
@app_commands.guild_only()
async def cinnamon_me_privacy(interaction: discord.Interaction):
    gid, uid = interaction.guild.id, interaction.user.id
    memo = _cmem_member(gid, uid)
    note_count = len(memo.get("notes", [])) if memo.get("enabled", True) else 0
    timezone_saved = str(uid) in _cr_server(gid).get("timezones", {})
    await interaction.response.send_message(
        "🔒 **Cinnamon's personal data controls**\n"
        "• Preference notes are saved only when you explicitly ask. "
        f"You have **{note_count}** saved in this server.\n"
        "• Only your notes are shown to Gemini when **you** ask Cinnamon to chat.\n"
        "• Your timezone is "
        + ("a personal fixed UTC offset.\n" if timezone_saved
           else "the shared server default.\n")
        + "• Your reminder list and saved notes are private slash-command replies.\n"
        "• `/cinnamon-memory view` — inspect; `/cinnamon-memory edit` — correct; "
        "`/cinnamon-memory clear` — erase; "
        "`/cinnamon-memory enable enabled:false` — turn off and erase.\n"
        "• `/cinnamon-reminder cancel` — cancel a pending reminder. "
        "`/cinnamon-reminder timezone offset:server` — reset your timezone.\n"
        "• Cinnamon does not automatically archive your messages as preference notes. "
        "Bot operators and the storage provider may still have access to stored server data.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
    )


bot.tree.add_command(_me_group)
