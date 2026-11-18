"""Cinnamon Brain v2 — simple, private member utility hub.

Read-only summaries of existing member-owned state. No AI inference,
unsolicited messages, privileged access or new background jobs.
"""
import datetime as _me_datetime
from cinnamon_modules.brain_private_qa import (
    classify_private_question as _me_classify_private_question,
    build_private_prompt as _me_build_private_prompt,
    sanitize_private_answer as _me_sanitize_private_answer,
)
from cinnamon_modules.brain_personalization import (
    STYLES as _me_styles, validate_style as _me_validate_style,
    validate_teasing as _me_validate_teasing, prompt_guidance as _me_prompt_guidance,
)
from cinnamon_modules.brain_member_v2 import (
    due_today as _me_due_today,
    format_timezone_offset as _me_timezone,
    level_progress as _me_level_progress,
)

_me_group = app_commands.Group(
    name="cinnamon-me",
    description="Private personal tools and privacy controls for Cinnamon",
)



def _me_private_snapshot(guild_id, user_id, scopes):
    """Build bounded, read-only sections from only the requesting member's current-guild state."""
    if not _cb_storage_available():
        return {scope: {"available": False, "reason": "saved storage is not ready"}
                for scope in scopes}
    gid, uid = int(guild_id), int(user_id)
    result = {}

    def safe_int(value, default=0):
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return default

    for scope in scopes:
        if scope == "wallet":
            balance = economy_balances.get((gid, uid))
            inventory = economy_inventory.get((gid, uid), {})
            if not isinstance(inventory, dict):
                inventory = {}
            clean_inventory = {}
            for item_id, quantity in list(inventory.items())[:30]:
                amount = safe_int(quantity)
                if amount:
                    clean_inventory[str(item_id)[:60]] = amount
            result[scope] = {
                "available": balance is not None,
                "catnip": safe_int(balance) if balance is not None else None,
                "inventory": clean_inventory,
            }
        elif scope == "progress":
            xp = safe_int(xp_data.get((gid, uid), 0))
            level = _me_level_progress(
                xp, level_from_xp=level_from_xp,
                total_xp_for_level=total_xp_for_level, max_level=MAX_LEVEL,
            )
            guild_quests = quest_data.get(gid, {})
            if not isinstance(guild_quests, dict):
                guild_quests = {}
            users = guild_quests.get("users", {})
            if not isinstance(users, dict):
                users = {}
            member_quests = users.get(str(uid), {})
            if not isinstance(member_quests, dict):
                member_quests = {}
            history = member_quests.get("completed_history", [])
            progress = {
                "available": True,
                "level": safe_int(level.get("level", 1), 1),
                "max_level": safe_int(MAX_LEVEL, 1),
                "total_xp": safe_int(level.get("total_xp", xp)),
                "xp_remaining": safe_int(level.get("xp_remaining", 0)),
                "quest_points": safe_int(member_quests.get("qp", 0)),
                "quests_completed": len(history) if isinstance(history, list) else 0,
            }

            def quest_rows(board_ids, definitions, member_progress):
                rows = []
                if not isinstance(member_progress, dict):
                    member_progress = {}
                ids = board_ids if isinstance(board_ids, (list, tuple)) else []
                for qid in list(ids)[:5]:
                    if not isinstance(qid, (str, int)):
                        continue
                    definition = definitions.get(qid)
                    if not isinstance(definition, dict):
                        continue
                    state = member_progress.get(qid, {})
                    if not isinstance(state, dict):
                        state = {}
                    try:
                        completed = bool(_completed(definition, state))
                    except (TypeError, ValueError, KeyError):
                        completed = False
                    row = {
                        "name": str(definition.get("name", qid))[:80],
                        "completed": completed,
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
            result[scope] = progress
        elif scope == "reminders":
            reminder_store = advanced_features_data.get("cinnamon_reminders_v1", {})
            if not isinstance(reminder_store, dict):
                reminder_store = {}
            reminder_root = reminder_store.get(str(gid), {})
            if not isinstance(reminder_root, dict):
                reminder_root = {}
            reminder_members = reminder_root.get("members", {})
            if not isinstance(reminder_members, dict):
                reminder_members = {}
            reminder_member = reminder_members.get(str(uid), {})
            if not isinstance(reminder_member, dict):
                reminder_member = {}
            items = []
            for value in list(reminder_member.values())[:30]:
                if not isinstance(value, dict) or value.get("status") != "scheduled":
                    continue
                items.append({
                    "text": str(value.get("text", ""))[:120],
                    "due_at": safe_int(value.get("due_at", 0)),
                    "status": "scheduled",
                })
            result[scope] = {"available": True, "items": items}
        elif scope == "memory":
            memory_store = advanced_features_data.get("cinnamon_memory_v1", {})
            if not isinstance(memory_store, dict):
                memory_store = {}
            memory_root = memory_store.get(str(gid), {})
            if not isinstance(memory_root, dict):
                memory_root = {}
            members = memory_root.get("members", {})
            if not isinstance(members, dict):
                members = {}
            member = members.get(str(uid), {})
            if not isinstance(member, dict):
                member = {}
            enabled = bool(member.get("enabled", True))
            notes = member.get("notes", []) if enabled else []
            result[scope] = {
                "available": True, "enabled": enabled,
                "note_count": len(notes) if isinstance(notes, list) else 0,
            }
        else:
            result[scope] = {"available": False, "reason": "unsupported scope"}
    return result

def _me_generate_private_answer(question, snapshot):
    """Generate a bounded answer from only the selected read-only snapshot."""
    system, prompt = _me_build_private_prompt(question, snapshot)
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL, contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system, max_output_tokens=220),
    )
    return _me_sanitize_private_answer(getattr(response, "text", ""))


@_me_group.command(name="ask", description="Ask privately about your own Cinnamon data")
@app_commands.guild_only()
async def cinnamon_me_ask(interaction: discord.Interaction, question: str):
    scopes = _me_classify_private_question(question)
    if not scopes:
        return await interaction.response.send_message(
            "I can privately summarize only your own wallet, progress, reminders, or saved preferences. "
            "General questions and actions should use normal chat or commands.", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    snapshot = _me_private_snapshot(interaction.guild.id, interaction.user.id, scopes)
    try:
        answer = await asyncio.to_thread(_me_generate_private_answer, question, snapshot)
    except Exception:
        log.exception("Private Cinnamon Q&A failed")
        answer = "I couldn't safely prepare that private summary right now. Please try again later."
    await interaction.followup.send(answer or "I couldn't verify that information.", ephemeral=True,
                                  allowed_mentions=discord.AllowedMentions.none())

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
    if not _cb_storage_available():
        return await interaction.response.send_message(
            "⚠️ Your saved progress is unavailable right now, so I won't guess at your totals.",
            ephemeral=True,
        )
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
        lines.append("🏁 **Maximum level reached.**")
    else:
        lines.append(
            f"Progress: **{summary['xp_into_level']:,}/{summary['xp_for_level']:,} XP** "
            f"· **{summary['xp_remaining']:,} XP** to next level"
        )
    guild_quests = quest_data.get(gid, {})
    member_quests = guild_quests.get("users", {}).get(str(uid), {})
    history = member_quests.get("completed_history", [])
    lines.append(f"📜 Quests completed: **{len(history) if isinstance(history, list) else 0}**")
    lines.append(f"✨ Quest Points: **{max(0, int(member_quests.get('qp', 0))):,}**")
    if guild_quests.get("daily_date") == _today():
        daily_ids = guild_quests.get("daily_ids", [])
        daily_progress = member_quests.get("daily", {})
        done = sum(
            1 for qid in daily_ids
            if qid in DAILY_QUESTS and _completed(DAILY_QUESTS[qid], daily_progress.get(qid, {}))
        )
        lines.append(f"☀️ Daily quests: **{done}/{len(daily_ids)}** completed")
    achievement = achievement_data.get((gid, uid), {})
    unlocked = achievement.get("unlocked", []) if isinstance(achievement, dict) else []
    secret = achievement.get("secret_unlocked", []) if isinstance(achievement, dict) else []
    lines.append(f"🏆 Achievements: **{len(unlocked) if isinstance(unlocked, list) else 0}** unlocked")
    lines.append(f"🔐 Secret achievements: **{len(secret) if isinstance(secret, list) else 0}** discovered")
    lines.extend([
        "",
        "More detail: /rank, /quests progress, and /achievement list.",
        "*Private to you. This is read-only; it never grants XP or rewards.*",
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



# Explicit member-selected presentation preferences (never authorization).
def _me_brain_profile(guild_id, user_id):
    return advanced_features_data.setdefault("cinnamon_brain_member_v1", {}).setdefault(
        str(int(guild_id)), {}).setdefault(str(int(user_id)), {"style": "balanced", "teasing": True})


def _me_prompt_preferences(guild_id, user_id):
    profile = _me_brain_profile(guild_id, user_id)
    try:
        return _me_prompt_guidance(profile.get("style", "balanced"),
                                  profile.get("teasing", True))
    except ValueError:
        # Corrupt preference data falls back to safe defaults.
        return _me_prompt_guidance("balanced", True)


@_me_group.command(name="style", description="Choose how Cinnamon talks to you")
@app_commands.guild_only()
@app_commands.choices(style=[
    app_commands.Choice(name="Balanced", value="balanced"),
    app_commands.Choice(name="Playful", value="playful"),
    app_commands.Choice(name="Calm", value="calm"),
    app_commands.Choice(name="Concise", value="concise"),
    app_commands.Choice(name="Detailed", value="detailed"),
])
async def cinnamon_me_style(interaction: discord.Interaction, style: str):
    try:
        chosen = _me_validate_style(style)
    except ValueError as exc:
        return await interaction.response.send_message(str(exc), ephemeral=True)
    profile = _me_brain_profile(interaction.guild.id, interaction.user.id)
    prior = profile.get("style", "balanced")
    profile["style"] = chosen
    if not await bd_save_data():
        profile["style"] = prior
        return await interaction.response.send_message(
            "⚠️ Storage didn't confirm that preference. Nothing changed.", ephemeral=True)
    await interaction.response.send_message(
        f"🐾 Your Cinnamon reply style is now **{chosen}**. Serious conversations still take priority.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_me_group.command(name="teasing", description="Choose whether Cinnamon may gently tease you")
@app_commands.guild_only()
async def cinnamon_me_teasing(interaction: discord.Interaction, enabled: bool):
    profile = _me_brain_profile(interaction.guild.id, interaction.user.id)
    prior = bool(profile.get("teasing", True))
    profile["teasing"] = _me_validate_teasing(enabled)
    if not await bd_save_data():
        profile["teasing"] = prior
        return await interaction.response.send_message(
            "⚠️ Storage didn't confirm that preference. Nothing changed.", ephemeral=True)
    text = ("Friendly teasing is enabled (never cruelty or sensitive-topic jokes)."
            if enabled else "Friendly teasing is disabled. I'll keep things warm and respectful.")
    await interaction.response.send_message("🐾 " + text, ephemeral=True,
                                           allowed_mentions=discord.AllowedMentions.none())


bot.tree.add_command(_me_group)
