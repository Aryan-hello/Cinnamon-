"""Cinnamon's standalone quest system.

This module owns quest definitions, progress, completion and /quests.
Economy only supplies the items/Catnip that quests interact with.
"""

# Keep the historical variable name because persisted Cinnamon data and the
# dashboard already use it. The quest system is nevertheless separate from
# economy.py and exposes its own public functions.
ECONOMY_QUESTS = {
    "tuna_time": {"name": "Tuna Time", "item": "tuna", "amount": 3, "reward": 140, "description": "Give Cinnamon 3 tuna."},
    "treat_run": {"name": "Treat Run", "item": "treat", "amount": 5, "reward": 120, "description": "Give Cinnamon 5 cat treats."},
    "royal_snack": {"name": "Royal Snack", "item": "churu", "amount": 2, "reward": 130, "description": "Give Cinnamon 2 Churus."},
    "zoomies": {"name": "Zoomies", "item": "catnip_ball", "amount": 2, "reward": 180, "description": "Give Cinnamon 2 catnip balls."},
}

economy_quests = {}  # (guild_id, user_id) -> {quest_id: progress}


def _quest_progress(guild_id: int, user_id: int) -> dict:
    key = (guild_id, user_id)
    raw = economy_quests.get(key)
    if not isinstance(raw, dict):
        raw = {}
    clean = {}
    for qid, quest in ECONOMY_QUESTS.items():
        try:
            clean[qid] = max(0, int(raw.get(qid, 0)))
        except (TypeError, ValueError):
            clean[qid] = 0
    economy_quests[key] = clean
    return clean


def economy_quests_for(guild_id: int, user_id: int) -> dict:
    return _quest_progress(guild_id, user_id)


def sanitize_economy_quests(guild_id: int, user_id: int) -> dict:
    return _quest_progress(guild_id, user_id)


def quest_is_complete(guild_id: int, user_id: int, quest_id: str) -> bool:
    quest = ECONOMY_QUESTS.get(quest_id)
    if not isinstance(quest, dict):
        return False
    return int(_quest_progress(guild_id, user_id).get(quest_id, 0)) >= max(1, int(quest.get("amount", 1)))


def all_quests_complete(guild_id: int, user_id: int) -> bool:
    if not ECONOMY_QUESTS:
        return False
    progress = _quest_progress(guild_id, user_id)
    return all(int(progress.get(qid, 0)) >= max(1, int(q.get("amount", 1))) for qid, q in ECONOMY_QUESTS.items())


@bot.tree.command(name="quests", description="View Cinnamon quests and your progress")
@app_commands.guild_only()
async def quests_cmd(interaction: discord.Interaction):
    """Show quest progress. Nothing in this command can crash the command UI."""
    try:
        guild_id = interaction.guild.id
        user_id = interaction.user.id
        progress = _quest_progress(guild_id, user_id)
        lines = []
        for qid, quest in ECONOMY_QUESTS.items():
            if not isinstance(quest, dict):
                continue
            item_id = str(quest.get("item", ""))
            item = ECONOMY_ITEMS.get(item_id, {})
            amount = max(1, int(quest.get("amount", 1)))
            done = min(amount, max(0, int(progress.get(qid, 0))))
            name = str(quest.get("name", qid))[:80]
            item_name = str(item.get("name", item_id))[:80]
            emoji = str(item.get("emoji", "🐾"))[:8]
            reward = max(0, int(quest.get("reward", 0)))
            status = "✅" if done >= amount else "⬜"
            lines.append(f"{status} **{name}** — {done}/{amount} {emoji} {item_name} → **{reward} Catnip**\n{str(quest.get('description', ''))[:250]}")

        if not lines:
            lines = ["No quests are currently configured."]

        embed = discord.Embed(
            title="📜 Cinnamon's Quests",
            description="\n\n".join(lines)[:4000],
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Give Cinnamon items with /economy feed.")
        await interaction.response.send_message(embed=embed)

        # Logging is deliberately best-effort; it must never turn a successful
        # /quests response into an error.
        try:
            await economy_log(
                guild_id,
                title="📜 Quests viewed",
                fields=[("User", f"{interaction.user} ({user_id})"), ("Quests shown", str(len(lines)))],
            )
        except Exception:
            log.exception("Quest view logging failed in guild %s", guild_id)
    except Exception:
        log.exception("/quests failed in guild %s", getattr(getattr(interaction, "guild", None), "id", None))
        message = "❌ I couldn't load the quests. The quest data is still safe; please try again."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def apply_quest_progress(guild_id: int, user_id: int, item_id: str, quantity: int) -> tuple[list[str], int]:
    """Apply progress and return (newly_completed_quests, total_catnip_reward)."""
    progress = _quest_progress(guild_id, user_id)
    completed = []
    reward_total = 0
    quantity = max(0, int(quantity))

    for qid, quest in ECONOMY_QUESTS.items():
        if not isinstance(quest, dict) or str(quest.get("item", "")) != item_id:
            continue
        target = max(1, int(quest.get("amount", 1)))
        before = min(target, int(progress.get(qid, 0)))
        after = min(target, before + quantity)
        progress[qid] = after
        if before < target <= after:
            reward = max(0, int(quest.get("reward", 0)))
            reward_total += reward
            completed.append(f"**{quest.get('name', qid)}** (+{reward} Catnip)")

    economy_quests[(guild_id, user_id)] = progress
    return completed, reward_total
