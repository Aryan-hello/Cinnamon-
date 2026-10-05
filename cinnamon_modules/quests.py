"""Cinnamon quests. Quest definitions, progress, completion and /quests live here."""

ECONOMY_QUESTS = {
    "tuna_time": {"name": "Tuna Time", "item": "tuna", "amount": 3, "reward": 140, "description": "Give Cinnamon 3 tuna."},
    "treat_run": {"name": "Treat Run", "item": "treat", "amount": 5, "reward": 120, "description": "Give Cinnamon 5 cat treats."},
    "royal_snack": {"name": "Royal Snack", "item": "churu", "amount": 2, "reward": 130, "description": "Give Cinnamon 2 Churus."},
    "zoomies": {"name": "Zoomies", "item": "catnip_ball", "amount": 2, "reward": 180, "description": "Give Cinnamon 2 catnip balls."},
}

economy_quests = {}  # (guild_id, user_id) -> {quest_id: progress}

def economy_quests_for(guild_id: int, user_id: int) -> dict:
    return sanitize_economy_quests(guild_id, user_id)


def sanitize_economy_quests(guild_id: int, user_id: int) -> dict:
    """Return a valid quest-progress dict even if old/corrupt persisted data exists."""
    key = economy_key(guild_id, user_id)
    raw = economy_quests.get(key)
    if not isinstance(raw, dict):
        raw = {}
        economy_quests[key] = raw
    clean = {}
    for qid, q in ECONOMY_QUESTS.items():
        try:
            clean[qid] = max(0, int(raw.get(qid, 0)))
        except (TypeError, ValueError):
            clean[qid] = 0
    economy_quests[key] = clean
    return clean


@bot.tree.command(name="quests", description="View Cinnamon quests and your progress")
@app_commands.guild_only()
async def quests_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    user_id = interaction.user.id
    try:
        progress = sanitize_economy_quests(guild_id, user_id)
        lines = []
        for qid, q in ECONOMY_QUESTS.items():
            if not isinstance(q, dict):
                continue
            item_id = str(q.get("item", ""))
            item = ECONOMY_ITEMS.get(item_id)
            if not isinstance(item, dict):
                continue
            amount = max(1, int(q.get("amount", 1)))
            done = min(max(0, int(progress.get(qid, 0))), amount)
            emoji = str(item.get("emoji", "🐾"))[:8]
            item_name = str(item.get("name", item_id))[:80]
            reward = max(0, int(q.get("reward", 0)))
            lines.append(
                f"**{q.get('name', qid)}** — {done}/{amount} {emoji} {item_name} → **{reward} Catnip**\n"
                f"{q.get('description', '')}"
            )
        if not lines:
            lines.append("No economy quests are currently configured.")
        embed = discord.Embed(
            title="📜 Cinnamon's quests",
            description="\n\n".join(lines)[:4000],
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Use /economy feed to give Cinnamon the required item.")
        await interaction.response.send_message(embed=embed)
        # Logging is deliberately after the user response and is non-fatal.
        await economy_log(guild_id, title="📜 Economy quests viewed", fields=[
            ("User", f"{interaction.user} ({user_id})"),
            ("Quests shown", str(len(lines))),
        ])
    except Exception:
        log.exception("Economy quest command failed for guild %s", guild_id)
        msg = "❌ I couldn't load the quests right now. The quest data may need to be reset or repaired."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            log.exception("Could not send economy quest error response for guild %s", guild_id)


async def apply_quest_progress(guild_id: int, user_id: int, item_id: str, quantity: int) -> tuple[list[str], int]:
    """Apply item-based quest progress and return completed quest messages.

    Economy owns the Catnip transaction; this module owns quest progress and
    completion detection.
    """
    progress = economy_quests_for(guild_id, user_id)
    completed = []
    reward_total = 0
    for qid, q in ECONOMY_QUESTS.items():
        if str(q.get("item", "")) != item_id:
            continue
        amount = max(1, int(q.get("amount", 1)))
        before = min(int(progress.get(qid, 0)), amount)
        after = min(amount, before + max(0, int(quantity)))
        progress[qid] = after
        if before < amount <= after:
            reward = max(0, int(q.get("reward", 0)))
            reward_total += reward
            completed.append(f"**{q.get('name', qid)}** (+{reward} Catnip)")
    return completed, reward_total
