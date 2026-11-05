"""Cinnamon Brain v2 — simple, private member utility hub.

Read-only summaries of existing member-owned state. No AI inference,
unsolicited messages, privileged access or new background jobs.
"""
import datetime as _me_datetime
from cinnamon_modules.brain_member_v2 import (
    due_today as _me_due_today,
    format_timezone_offset as _me_timezone,
    level_progress as _me_level_progress,
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


@_me_group.command(name="progress", description="Privately see your level, XP, quests and achievements")
@app_commands.guild_only()
async def cinnamon_me_progress(interaction: discord.Interaction):
    gid, uid = interaction.guild.id, interaction.user.id
    xp = max(0, int(xp_data.get((gid, uid), 0)))
    summary = _me_level_progress(
        xp, level_from_xp=level_from_xp,
        total_xp_for_level=total_xp_for_level, max_level=MAX_LEVEL,
    )
    lines = [
        "📈 **YOUR CINNAMON PROGRESS**",
        f"⭐ Level: **{summary['level']} / {MAX_LEVEL}**",
        f"✨ Total XP: **{summary['total_xp']:,}**",
    ]
    if summary["max_level"]:
        lines.append("🏁 **Maximum level reached.** Cinnamon is impressed. Slightly.")
    else:
        lines.append(
            f"Progress: **{summary['xp_into_level']:,}/{summary['xp_for_level']:,} XP** "
            f"· **{summary['xp_remaining']:,} XP** to next level"
        )

    if _cb_storage_available():
        qguild = quest_data.get(gid, {})
        quser = qguild.get("users", {}).get(str(uid), {})
        history = quser.get("completed_history", [])
        lines.append(f"📜 Quests completed: **{len(history) if isinstance(history, list) else 0}**")
        lines.append(f"✨ Quest Points: **{max(0, int(quser.get('qp', 0))):,}**")
        if qguild.get("daily_date") == _today():
            daily_ids = qguild.get("daily_ids", [])
            daily = quser.get("daily", {})
            daily_done = sum(
                1 for qid in daily_ids
                if qid in DAILY_QUESTS and _completed(DAILY_QUESTS[qid], daily.get(qid, {}))
            )
            lines.append(f"☀️ Daily quests: **{daily_done}/{len(daily_ids)}** completed")
        if qguild.get("weekly_key") == _week():
            weekly_ids = qguild.get("weekly_ids", [])
            weekly = quser.get("weekly", {})
            weekly_done = sum(
                1 for qid in weekly_ids
                if qid in WEEKLY_QUESTS and _completed(WEEKLY_QUESTS[qid], weekly.get(qid, {}))
            )
            lines.append(f"📅 Weekly quests: **{weekly_done}/{len(weekly_ids)}** completed")
    else:
        lines.append("⚠️ Saved quest data is unavailable, so I won't guess at your quest totals.")

    achievement = achievement_data.get((gid, uid), {})
    unlocked = achievement.get("unlocked", []) if isinstance(achievement, dict) else []
    secret = achievement.get("secret_unlocked", []) if isinstance(achievement, dict) else []
    lines.append(f"🏆 Achievements: **{len(unlocked) if isinstance(unlocked, list) else 0}** unlocked")
    lines.append(f"🔐 Secret achievements: **{len(secret) if isinstance(secret, list) else 0}** discovered")
    lines.extend([
        "",
        "More detail: /rank, /quests progress, and /achievement list.",
        "*Private to you. This is a read-only snapshot; it never grants XP or rewards.*",
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
