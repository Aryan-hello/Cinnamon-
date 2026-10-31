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
from cinnamon_modules.brain_private_qa import (
    build_private_prompt as _me_build_private_prompt,
    classify_private_question as _me_classify_private_question,
    sanitize_private_answer as _me_sanitize_private_answer,
)

_me_group = app_commands.Group(
    name="cinnamon-me",
    description="Private personal tools and privacy controls for Cinnamon",
)


def _me_private_snapshot(gid, uid, scopes):
    """Build a minimal snapshot from only this member's current-guild records."""
    ready = _cb_storage_available()
    snapshot = {}

    if "wallet" in scopes:
        if ready:
            inventory = economy_inventory.get((gid, uid), {})
            items = []
            for item_id, quantity in list(inventory.items())[:20]:
                try:
                    amount = max(0, int(quantity))
                except (TypeError, ValueError):
                    continue
                if amount <= 0:
                    continue
                item = ECONOMY_ITEMS.get(item_id, {})
                items.append({
                    "name": str(item.get("name", item_id))[:60],
                    "quantity": amount,
                })
            snapshot["wallet"] = {
                "available": True,
                "catnip": max(0, int(economy_balances.get((gid, uid), ECONOMY_STARTING_BALANCE))),
                "inventory": items,
            }
        else:
            snapshot["wallet"] = {"available": False, "reason": "saved snapshot unavailable"}

    if "progress" in scopes:
        if ready:
            xp = max(0, int(xp_data.get((gid, uid), 0)))
            level = _me_level_progress(
                xp, level_from_xp=level_from_xp,
                total_xp_for_level=total_xp_for_level, max_level=MAX_LEVEL,
            )
            guild_quests = quest_data.get(gid, {})
            member_quests = guild_quests.get("users", {}).get(str(uid), {})
            history = member_quests.get("completed_history", [])
            progress = {
                "available": True,
                "level": level["level"],
                "max_level": MAX_LEVEL,
                "total_xp": level["total_xp"],
                "xp_remaining": level["xp_remaining"],
                "quest_points": max(0, int(member_quests.get("qp", 0))),
                "quests_completed": len(history) if isinstance(history, list) else 0,
            }

            def quest_rows(board_ids, definitions, member_progress):
                rows = []
                for qid in list(board_ids or [])[:5]:
                    definition = definitions.get(qid)
                    if not isinstance(definition, dict):
                        continue
                    state = member_progress.get(qid, {})
                    if not isinstance(state, dict):
                        state = {}
                    row = {
                        "name": str(definition.get("name", qid))[:80],
                        "completed": bool(_completed(definition, state)),
                    }
                    target = definition.get("target")
                    if type(target) is int:
                        row["target"] = target
                    current = state.get("count", state.get("value"))
                    if type(current) is int:
                        row["current"] = max(0, current)
                    rows.append(row)
                return rows

            if guild_quests.get("daily_date") == _today():
                progress["daily_quests"] = quest_rows(
                    guild_quests.get("daily_ids", []), DAILY_QUESTS,
                    member_quests.get("daily", {}),
                )
            else:
                progress["daily_quests"] = "not_current_or_not_initialized"
            if guild_quests.get("weekly_key") == _week():
                progress["weekly_quests"] = quest_rows(
                    guild_quests.get("weekly_ids", []), WEEKLY_QUESTS,
                    member_quests.get("weekly", {}),
                )
            else:
                progress["weekly_quests"] = "not_current_or_not_initialized"

            achievements = achievement_data.get((gid, uid), {})
            unlocked = achievements.get("unlocked", []) if isinstance(achievements, dict) else []
            secret = achievements.get("secret_unlocked", []) if isinstance(achievements, dict) else []
            progress["achievements_unlocked"] = len(unlocked) if isinstance(unlocked, list) else 0
            progress["secret_achievements_discovered"] = len(secret) if isinstance(secret, list) else 0
            snapshot["progress"] = progress
        else:
            snapshot["progress"] = {"available": False, "reason": "saved snapshot unavailable"}

    if "reminders" in scopes:
        if ready:
            reminders = []
            reminder_root = advanced_features_data.get("cinnamon_reminders_v1", {}).get(str(gid), {})
            reminder_member = reminder_root.get("members", {}).get(str(uid), {})
            active_reminders = [
                item for item in reminder_member.values()
                if isinstance(item, dict) and item.get("status") == "scheduled"
            ]
            for item in active_reminders[:10]:
                try:
                    due_at = int(item.get("due_at", 0))
                except (TypeError, ValueError):
                    continue
                if due_at <= 0:
                    continue
                reminders.append({
                    "id": str(item.get("id", ""))[:16],
                    "task": str(item.get("text", ""))[:120],
                    "due_at_utc": _me_datetime.datetime.fromtimestamp(
                        due_at, tz=_me_datetime.timezone.utc
                    ).isoformat(),
                })
            snapshot["reminders"] = {
                "available": True,
                "timezone": _me_timezone(
                    int(reminder_root.get("timezones", {}).get(str(uid), CINNAMON_TIMEZONE_OFFSET_MINUTES))
                ),
                "scheduled": reminders,
            }
        else:
            snapshot["reminders"] = {"available": False, "reason": "saved snapshot unavailable"}

    if "memory" in scopes:
        if ready:
            memory = advanced_features_data.get("cinnamon_memory_v1", {}).get(str(gid), {}).get("members", {}).get(str(uid), {})
            enabled = bool(memory.get("enabled", True))
            notes = memory.get("notes", []) if enabled else []
            categories = sorted({
                str(note.get("category", ""))[:30]
                for note in notes if isinstance(note, dict) and note.get("category")
            })
            # Preference text is deliberately excluded from the Q&A context.
            snapshot["memory"] = {
                "available": True,
                "enabled": enabled,
                "note_count": len(notes) if isinstance(notes, list) else 0,
                "categories": categories,
            }
        else:
            snapshot["memory"] = {"available": False, "reason": "saved snapshot unavailable"}

    return snapshot, ready


def _me_generate_private_answer(question, snapshot):
    """Synchronous Gemini call; invoked in a worker thread by the command."""
    system_instruction, contents = _me_build_private_prompt(question, snapshot)
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=260,
            temperature=0.25,
        ),
    )
    return _me_sanitize_private_answer(getattr(response, "text", ""))


@_me_group.command(name="ask", description="Privately ask AI about your own Cinnamon data")
@app_commands.guild_only()
@app_commands.describe(question="Ask about your Catnip, progress, quests, reminders, or saved settings")
async def cinnamon_me_ask(interaction: discord.Interaction, question: str):
    question = str(question or "").strip()
    scopes = _me_classify_private_question(question)
    if not scopes:
        return await interaction.response.send_message(
            "🐾 I can answer private, read-only questions about your own Catnip, "
            "inventory, level, XP, quests, achievements, reminders, and memory settings. "
            "I can't perform actions or answer general questions here. Try asking "
            "something like 'How close am I to the next level?'",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    snapshot, ready = _me_private_snapshot(
        interaction.guild.id, interaction.user.id, scopes
    )
    if not ready:
        return await interaction.response.send_message(
            "⚠️ My saved data snapshot isn't ready, so I can't verify that information "
            "right now. I won't guess. Please try again after storage is healthy.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        answer = await asyncio.to_thread(
            _me_generate_private_answer, question, snapshot
        )
    except Exception as exc:
        log.warning("Private member Q&A failed (%s)", type(exc).__name__)
        answer = ""
    if not answer:
        answer = (
            "🐾 I couldn't produce a verified answer just now. "
            "Your data wasn't changed; please try again in a moment."
        )
    await interaction.followup.send(
        answer[:1400], ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
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
