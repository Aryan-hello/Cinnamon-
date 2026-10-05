"""Cinnamon achievements. Definitions, unlock logic and /achievements live here."""

ECONOMY_ACHIEVEMENTS = {
    "first_feed": {"name": "First Snack", "description": "Feed Cinnamon an item for the first time.", "reward": 50},
    "quest_complete": {"name": "Quest Paw-sitive", "description": "Complete your first quest.", "reward": 100},
    "catnip_1000": {"name": "Catnip Hoarder", "description": "Reach 1,000 Catnip in your balance.", "reward": 150},
    "collector_10": {"name": "Snack Collector", "description": "Own at least 10 total economy items at once.", "reward": 100},
    "all_quests": {"name": "Cinnamon's Favorite", "description": "Complete every currently defined quest.", "reward": 300},
}

economy_achievements = {}  # (guild_id, user_id) -> [achievement ids]

async def unlock_economy_achievement(guild_id: int, user_id: int, achievement_id: str, *, reason: str = "") -> bool:
    """Unlock one achievement exactly once and persist it. Returns True only on a new unlock."""
    if achievement_id not in ECONOMY_ACHIEVEMENTS:
        return False
    key = economy_key(guild_id, user_id)
    unlocked = economy_achievements.setdefault(key, [])
    if achievement_id in unlocked:
        return False
    unlocked.append(achievement_id)
    reward = int(ECONOMY_ACHIEVEMENTS[achievement_id].get("reward", 0))
    if reward:
        economy_balances[key] = economy_balance(guild_id, user_id) + reward
    await bd_save_data()
    achievement = ECONOMY_ACHIEVEMENTS[achievement_id]
    await economy_log(guild_id, title="🏆 Achievement unlocked", fields=[
        ("User", f"<@{user_id}> ({user_id})"),
        ("Achievement", achievement["name"]),
        ("Reward", f"+{reward:,} Catnip"),
        ("Reason", reason or achievement["description"]),
        ("Balance after", f"{economy_balance(guild_id, user_id):,} Catnip"),
    ])
    return True


async def check_economy_achievements(guild_id: int, user_id: int, *, fed: bool = False, completed_quest: bool = False, member=None) -> list[str]:
    """Check all achievement conditions after an economy/quest action."""
    unlocked = []
    if fed and await unlock_economy_achievement(guild_id, user_id, "first_feed", reason="Fed Cinnamon an item"):
        unlocked.append(ECONOMY_ACHIEVEMENTS["first_feed"]["name"])
    if completed_quest and await unlock_economy_achievement(guild_id, user_id, "quest_complete", reason="Completed a quest"):
        unlocked.append(ECONOMY_ACHIEVEMENTS["quest_complete"]["name"])
    if economy_balance(guild_id, user_id) >= 1000 and await unlock_economy_achievement(guild_id, user_id, "catnip_1000", reason="Reached 1,000 Catnip"):
        unlocked.append(ECONOMY_ACHIEVEMENTS["catnip_1000"]["name"])
    inv = economy_inventory_for(guild_id, user_id)
    if sum(max(0, int(v)) for v in inv.values()) >= 10 and await unlock_economy_achievement(guild_id, user_id, "collector_10", reason="Reached 10 total items"):
        unlocked.append(ECONOMY_ACHIEVEMENTS["collector_10"]["name"])
    progress = economy_quests_for(guild_id, user_id)
    if ECONOMY_QUESTS and all(int(progress.get(qid, 0)) >= int(q.get("amount", 1)) for qid, q in ECONOMY_QUESTS.items()):
        if await unlock_economy_achievement(guild_id, user_id, "all_quests", reason="Completed every configured quest"):
            unlocked.append(ECONOMY_ACHIEVEMENTS["all_quests"]["name"])
    return unlocked


@bot.tree.command(name="achievements", description="View Cinnamon achievements")
@app_commands.guild_only()
async def achievements_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    guild_id = interaction.guild.id
    member = member or interaction.user
    raw = economy_achievements.get((guild_id, member.id), [])
    if not isinstance(raw, (list, tuple, set)):
        raw = []
    unlocked = {str(aid) for aid in raw if str(aid) in ECONOMY_ACHIEVEMENTS}
    lines = []
    for aid, achievement in ECONOMY_ACHIEVEMENTS.items():
        status = "🏆" if aid in unlocked else "🔒"
        lines.append(f"{status} **{achievement['name']}** — {achievement['description']} — **{int(achievement['reward'])} Catnip**")
    embed = discord.Embed(title=f"🏆 {member.display_name}'s achievements", description="\n".join(lines)[:4000], color=discord.Color.gold())
    embed.set_footer(text=f"Unlocked: {len(unlocked)}/{len(ECONOMY_ACHIEVEMENTS)}")
    await interaction.response.send_message(embed=embed)
