"""Cinnamon feature module.

Loaded by main.py into Cinnamon's shared runtime namespace. This is still
one Discord bot and one process; this file is not a separate bot.
Do not run this file directly.
"""

def level_from_xp(xp: int) -> int:
    # Inverse of total_xp_for_level's quadratic (25*n^2 + 75*n <= xp).
    n = (-75 + math.sqrt(5625 + 100 * xp)) / 50
    return max(0, int(n))


def total_xp_for_level(level: int) -> int:
    return 25 * level * level + 75 * level


async def sync_level_roles(member: discord.Member, level: int) -> list[str]:
    """Give `member` every level role they've earned but don't have yet. Runs on
    each XP award (not just level-ups), so roles added later still reach people
    who are already past that level. Returns the names of roles newly given."""
    cfg = level_roles.get(member.guild.id)
    if not cfg:
        return []
    have = {r.id for r in member.roles}
    top = member.guild.me.top_role
    to_add = []
    for lvl, rid in cfg.items():
        if lvl <= level and rid not in have:
            role = member.guild.get_role(rid)
            if role and not role.managed and role < top:
                to_add.append(role)
    if not to_add:
        return []
    try:
        await member.add_roles(*to_add, reason=f"Reached level {level}")
    except discord.HTTPException:
        return []
    return [r.name for r in to_add]


async def award_xp(message: discord.Message):
    key = (message.guild.id, message.author.id)
    now = time.monotonic()
    if now - xp_cooldowns.get(key, 0) < 60:
        return
    xp_cooldowns[key] = now
    old_xp = xp_data.get(key, 0)
    old_level = level_from_xp(old_xp)
    new_xp = old_xp + random.randint(15, 25)
    xp_data[key] = new_xp
    new_level = level_from_xp(new_xp)
    gained = await sync_level_roles(message.author, new_level)
    await send_log(message.guild.id, title="📈 XP changed", category="levels",
                   fields=[("User", f"{message.author} ({message.author.id})"), ("XP before", str(old_xp)),
                           ("XP gained", str(new_xp - old_xp)), ("XP after", str(new_xp)),
                           ("Level", f"{old_level} → {new_level}"), ("New level roles", ", ".join(gained) if gained else "None")])
    if new_level > old_level:
        text = f"🐾 {message.author.mention} just leveled up to **Level {new_level}**!"
        if gained:
            text += f" New role{'s' if len(gained) > 1 else ''}: **{', '.join(gained)}**"
        reward_levels = [lvl for lvl, amount in ECONOMY_LEVEL_REWARDS.items() if old_level < lvl <= new_level and not economy_level_reward_claimed(message.guild.id, message.author.id, lvl)]
        reward_total = sum(ECONOMY_LEVEL_REWARDS[lvl] for lvl in reward_levels)
        if reward_total:
            economy_balances[(message.guild.id, message.author.id)] = economy_balance(message.guild.id, message.author.id) + reward_total
            for lvl in reward_levels:
                mark_economy_level_reward_claimed(message.guild.id, message.author.id, lvl)
            await economy_log(message.guild.id, title="🏆 Level Catnip reward", fields=[("User", f"{message.author} ({message.author.id})"), ("Levels", ", ".join(map(str, reward_levels))), ("Reward", f"+{reward_total:,} Catnip")])
            text += f"\n🌿 Level reward: **+{reward_total:,} Catnip**!"
            await bd_save_data()
        try:
            await message.channel.send(
                text,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False),
            )
        except discord.HTTPException:
            pass


@bot.tree.command(name="rank", description="Show your (or someone's) level and XP")
@app_commands.describe(member="Who to check (defaults to you)")
@app_commands.guild_only()
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    xp = xp_data.get((interaction.guild.id, member.id), 0)
    level = level_from_xp(xp)
    this_level_xp = total_xp_for_level(level)
    next_level_xp = total_xp_for_level(level + 1)
    embed = discord.Embed(title=f"🐾 {member.display_name}'s Rank", color=0xFFB02E)
    embed.add_field(name="Level", value=str(level), inline=True)
    embed.add_field(name="Total XP", value=str(xp), inline=True)
    embed.add_field(name="Progress", value=f"{xp - this_level_xp}/{next_level_xp - this_level_xp} XP to next level", inline=True)
    reward = ECONOMY_LEVEL_REWARDS.get(level)
    if reward:
        embed.add_field(name="🌿 Level reward", value=f"+{reward:,} Catnip at this level", inline=True)
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="leaderboard", description="Show the top 10 members by XP in this server")
@app_commands.guild_only()
async def leaderboard(interaction: discord.Interaction):
    entries = sorted(
        ((uid, xp) for (gid, uid), xp in xp_data.items() if gid == interaction.guild.id),
        key=lambda e: e[1], reverse=True,
    )[:10]
    if not entries:
        return await interaction.response.send_message("No one has earned XP yet. 🐾", ephemeral=True)
    lines = []
    for i, (uid, xp) in enumerate(entries, 1):
        member = interaction.guild.get_member(uid)
        name = member.display_name if member else f"User {uid}"
        lines.append(f"**#{i}** {name} — Level {level_from_xp(xp)} ({xp} XP)")
    embed = discord.Embed(title="🏆 XP Leaderboard", description="\n".join(lines), color=0xFEE75C)
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


# --- Level roles ----------------------------------------------------------------

levelrole_group = app_commands.Group(name="levelrole", description="Give roles automatically at certain levels")


@levelrole_group.command(name="add", description="Give a role automatically when members reach a level")
@app_commands.describe(level="Level that unlocks the role", role="Role to give")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def levelrole_add(interaction: discord.Interaction, level: int, role: discord.Role):
    if role.is_default() or role.managed:
        return await interaction.response.send_message("That role can't be assigned by a bot.", ephemeral=True)
    if role >= interaction.guild.me.top_role:
        return await interaction.response.send_message(
            "That role is above my highest role, so I can't hand it out. Move my role higher in Server Settings → Roles.",
            ephemeral=True,
        )
    level_roles.setdefault(interaction.guild.id, {})[level] = role.id
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 Members will get **{role.name}** at **Level {level}**. "
        f"Anyone already past that level gets it the next time they earn XP.",
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await send_log(
        interaction.guild.id, title="🎖️ Level role added", color=discord.Color.green(), interaction=interaction,
        fields=[("Level", str(level)), ("Role", role.name)],
    )


@levelrole_group.command(name="remove", description="Stop giving a role at a level (members keep roles they already have)")
@app_commands.describe(level="The level to remove the reward from")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelrole_remove(interaction: discord.Interaction, level: int):
    cfg = level_roles.get(interaction.guild.id, {})
    if cfg.pop(level, None) is None:
        return await interaction.response.send_message(f"No level role is set for level {level}.", ephemeral=True)
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Removed the Level {level} reward. Members keep roles they already earned.")
    await send_log(
        interaction.guild.id, title="🎖️ Level role removed", color=discord.Color.orange(), interaction=interaction,
        fields=[("Level", str(level))],
    )


@levelrole_group.command(name="list", description="Show this server's level roles")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelrole_list(interaction: discord.Interaction):
    cfg = level_roles.get(interaction.guild.id, {})
    if not cfg:
        return await interaction.response.send_message("No level roles set. Add one with `/levelrole add`.", ephemeral=True)
    lines = []
    for lvl in sorted(cfg):
        role = interaction.guild.get_role(cfg[lvl])
        lines.append(f"**Level {lvl}** → {role.name if role else '(deleted role)'}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


# --- Standalone giveaways (persistent — survive restarts) --------------------------
# State lives in active_giveaways (saved with everything else); the Enter button
# is a persistent view matched by custom_id and looked up by message ID, so it
# keeps working after a restart, and check_timers ends giveaways on schedule.

def _giveaway_embed(gw: dict, winner_ids: list[int] | None = None) -> discord.Embed:
    if winner_ids is None:
        embed = discord.Embed(
            title="🎉 Giveaway!", color=0xFEE75C,
            description=f"**Prize:** {gw['prize']}\n**Winners:** {gw['winners']}\n"
                        f"Ends <t:{int(gw['ends_at'])}:R>\nHosted by <@{gw['host_id']}>",
        )
    else:
        won = " ".join(f"<@{u}>" for u in winner_ids) if winner_ids else "No one entered 🐾"
        embed = discord.Embed(
            title="🎉 Giveaway ended", color=0x99AAB5,
            description=f"**Prize:** {gw['prize']}\n**Winner{'s' if len(winner_ids) > 1 else ''}:** {won}\n"
                        f"Hosted by <@{gw['host_id']}>",
        )
    return embed


class GiveawayView(discord.ui.View):
    def __init__(self, disabled: bool = False):
        super().__init__(timeout=None)  # persistent: registered on startup via bot.add_view
        btn = discord.ui.Button(label="🎉 Enter", style=discord.ButtonStyle.success,
                                custom_id="giveaway:enter", disabled=disabled)
        btn.callback = self._enter
        self.add_item(btn)

    async def _enter(self, interaction: discord.Interaction):
        gw = active_giveaways.get(interaction.message.id)
        if gw is None:
            return await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
        uid = interaction.user.id
        if uid in gw["entrants"]:
            gw["entrants"].remove(uid)
            text = "You left the giveaway."
        else:
            gw["entrants"].append(uid)
            text = "🎉 You're entered! Click again to leave."
        await interaction.response.send_message(text, ephemeral=True)
        await bd_save_data()  # after responding: Discord only gives us 3s to answer
        guild_id = gw.get("guild_id")
        if guild_id:
            await send_log(int(guild_id), title="🎉 Giveaway entry changed", category="community",
                           fields=[("User", f"{interaction.user} ({interaction.user.id})"),
                                   ("Giveaway message", str(interaction.message.id)),
                                   ("Action", "Entered" if uid in gw["entrants"] else "Left"),
                                   ("Entrants", str(len(gw["entrants"]))),
                                   ("Prize", str(gw.get("prize", "Giveaway"))[:900])])


async def finish_giveaway(mid: int):
    gw = active_giveaways.pop(mid, None)
    if gw is None:
        return
    await bd_save_data()
    channel = bot.get_channel(gw["channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(mid)
    except discord.HTTPException:
        return  # message was deleted — nothing to update
    entrants = list(dict.fromkeys(int(uid) for uid in gw.get("entrants", [])))
    bonus_roles = gw.get("bonus_roles", {})
    tickets = []
    guild = bot.get_guild(int(gw.get("guild_id", 0)))
    for uid in entrants:
        member = guild.get_member(uid) if guild else None
        extra = 0
        if member:
            member_role_ids = {str(role.id) for role in member.roles}
            extra = sum(max(0, min(20, int(count))) for role_id, count in bonus_roles.items() if str(role_id) in member_role_ids)
        tickets.extend([uid] * (1 + min(extra, 100)))
    winner_ids = []
    while tickets and len(winner_ids) < min(int(gw.get("winners", 1)), len(entrants)):
        winner = random.choice(tickets)
        winner_ids.append(winner)
        tickets = [uid for uid in tickets if uid != winner]
    try:
        await message.edit(embed=_giveaway_embed(gw, winner_ids), view=GiveawayView(disabled=True))
    except discord.HTTPException:
        pass
    if winner_ids:
        text = f"🎉 Congrats {' '.join(f'<@{u}>' for u in winner_ids)}! You won **{gw['prize']}**!"
    else:
        text = "🐾 No one entered the giveaway — no winners this time."
    await send_log(int(gw.get("guild_id", 0)), title="🏁 Giveaway finished", category="community",
                   fields=[("Message", str(mid)), ("Prize", str(gw.get("prize", "Giveaway"))[:900]),
                           ("Entrants", str(len(entrants))), ("Winners", ", ".join(str(x) for x in winner_ids) if winner_ids else "None")])
    try:
        await message.reply(text, allowed_mentions=discord.AllowedMentions(users=True))
    except discord.HTTPException:
        pass



async def cancel_giveaway(mid: int):
    """Cancel a giveaway without selecting winners."""
    gw = active_giveaways.pop(mid, None)
    if gw is None:
        return False
    await bd_save_data()
    channel = bot.get_channel(int(gw.get("channel_id", 0)))
    if channel is not None:
        try:
            message = await channel.fetch_message(mid)
            embed = discord.Embed(title="🎉 Giveaway cancelled", description=f"**Prize:** {gw.get('prize', 'Giveaway')}\nThis giveaway was cancelled by a server manager.", color=0x99AAB5)
            await message.edit(embed=embed, view=GiveawayView(disabled=True))
        except discord.HTTPException:
            pass
    await send_log(int(gw.get("guild_id", 0)), title="🚫 Giveaway cancelled", category="community",
                   fields=[("Message", str(mid)), ("Prize", str(gw.get("prize", "Giveaway"))[:900]),
                           ("Entrants", str(len(gw.get("entrants", []))))])
    return True

giveaway_group = app_commands.Group(name="giveaway", description="Run a simple prize giveaway")


@giveaway_group.command(name="start", description="Start a giveaway")
@app_commands.describe(duration_minutes="How long the giveaway runs", winners="Number of winners", prize="What's being given away")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def giveaway_start(interaction: discord.Interaction, duration_minutes: int,
                          winners: int, prize: app_commands.Range[str, 1, 200]):
    gw = {
        "guild_id": interaction.guild.id, "channel_id": interaction.channel.id, "host_id": interaction.user.id,
        "winners": winners, "prize": prize, "ends_at": time.time() + duration_minutes * 60, "entrants": [],
    }
    await interaction.response.send_message(embed=_giveaway_embed(gw), view=GiveawayView())
    msg = await interaction.original_response()
    active_giveaways[msg.id] = gw
    await bd_save_data()
    await send_log(interaction.guild.id, title="🎉 Giveaway started", interaction=interaction, category="community",
                   fields=[("Message", str(msg.id)), ("Prize", prize), ("Duration", f"{duration_minutes} minute(s)"),
                           ("Winners", str(winners))])


@giveaway_group.command(name="end", description="End a giveaway early and pick winners now")
@app_commands.describe(message_id="The ID of the giveaway message")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def giveaway_end(interaction: discord.Interaction, message_id: str):
    try:
        mid = int(message_id)
    except ValueError:
        return await interaction.response.send_message("That doesn't look like a valid message ID.", ephemeral=True)
    gw = active_giveaways.get(mid)
    if not gw or gw["guild_id"] != interaction.guild.id:
        return await interaction.response.send_message("No active giveaway with that message ID.", ephemeral=True)
    await interaction.response.send_message("Ending the giveaway now...", ephemeral=True)
    await finish_giveaway(mid)


# --- Polls (persistent — survive restarts) ---------------------------------------

def _poll_embed(poll: dict, ended: bool = False) -> discord.Embed:
    options, votes = poll["options"], poll["votes"]
    counts = [0] * len(options)
    for idx in votes.values():
        if 0 <= idx < len(options):
            counts[idx] += 1
    total = sum(counts)
    lines = []
    for i, (opt, c) in enumerate(zip(options, counts), 1):
        pct = c / total if total else 0
        filled = round(pct * 10)
        lines.append(f"**{i}. {opt}**\n{'█' * filled}{'░' * (10 - filled)} {c} vote(s) ({pct:.0%})")
    status = "Poll ended" if ended else f"Ends <t:{int(poll['ends_at'])}:R> · tap the same option again to remove your vote"
    embed = discord.Embed(
        title=f"📊 {poll['question']}", description="\n\n".join(lines) + f"\n\n{status}",
        color=0x99AAB5 if ended else 0xFFB02E,
    )
    embed.set_footer(text=f"{total} vote(s) · Started by {poll['host_name']}")
    return embed


class PollView(discord.ui.View):
    def __init__(self, options: list[str] | None = None, disabled: bool = False):
        super().__init__(timeout=None)  # persistent: registered on startup via bot.add_view
        for i in range(len(options) if options else 4):
            label = f"{i + 1}. {options[i]}"[:80] if options else f"Option {i + 1}"
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary,
                                    custom_id=f"poll:{i}", disabled=disabled)
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    @staticmethod
    def _make_callback(idx: int):
        async def callback(interaction: discord.Interaction):
            poll = active_polls.get(interaction.message.id)
            if poll is None:
                return await interaction.response.send_message("This poll has ended.", ephemeral=True)
            if idx >= len(poll["options"]):
                return await interaction.response.send_message("That option doesn't exist.", ephemeral=True)
            uid = str(interaction.user.id)
            if poll["votes"].get(uid) == idx:
                del poll["votes"][uid]  # tapping your current choice again removes your vote
            else:
                poll["votes"][uid] = idx
            await interaction.response.edit_message(embed=_poll_embed(poll))
            await bd_save_data()  # after responding: Discord only gives us 3s to answer
            await send_log(int(poll.get("guild_id", 0)), title="📊 Poll vote changed", category="community",
                           fields=[("User", f"{interaction.user} ({interaction.user.id})"),
                                   ("Poll message", str(interaction.message.id)),
                                   ("Choice", poll["options"][idx]), ("Total votes", str(len(poll["votes"])))])
        return callback


async def finish_poll(mid: int):
    poll = active_polls.pop(mid, None)
    if poll is None:
        return
    await bd_save_data()
    channel = bot.get_channel(poll["channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(mid)
    except discord.HTTPException:
        return
    try:
        await message.edit(embed=_poll_embed(poll, ended=True), view=PollView(poll["options"], disabled=True))
    except discord.HTTPException:
        pass
    counts = [0] * len(poll["options"])
    for idx in poll["votes"].values():
        if 0 <= idx < len(counts):
            counts[idx] += 1
    if not any(counts):
        text = "📊 The poll ended with no votes."
    else:
        top = max(counts)
        winners = [poll["options"][i] for i, c in enumerate(counts) if c == top]
        text = (f"📊 Poll ended — **{winners[0]}** wins with {top} vote(s)!" if len(winners) == 1
                else f"📊 Poll ended in a tie between **{' & '.join(winners)}** ({top} vote(s) each).")
    try:
        await message.reply(text, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass
    await send_log(int(poll.get("guild_id", 0)), title="🏁 Poll finished", category="community",
                   fields=[("Message", str(mid)), ("Question", str(poll.get("question", "Poll"))[:900]),
                           ("Votes", str(sum(counts))), ("Result", text[:900])])


@bot.tree.command(name="poll", description="Start a poll with 2-4 options")
@app_commands.describe(
    question="What are you asking?", option1="First option", option2="Second option",
    option3="Third option (optional)", option4="Fourth option (optional)",
    duration_minutes="How long the poll stays open (default 24 hours, max 7 days)",
)
@app_commands.guild_only()
async def poll(interaction: discord.Interaction, question: app_commands.Range[str, 1, 200],
               option1: app_commands.Range[str, 1, 60], option2: app_commands.Range[str, 1, 60],
               option3: app_commands.Range[str, 1, 60] = None, option4: app_commands.Range[str, 1, 60] = None,
               duration_minutes: int = 1440):
    options = [o for o in (option1, option2, option3, option4) if o]
    p = {
        "guild_id": interaction.guild.id, "channel_id": interaction.channel.id,
        "host_id": interaction.user.id, "host_name": interaction.user.display_name,
        "question": question, "options": options, "votes": {},
        "ends_at": time.time() + duration_minutes * 60,
    }
    await interaction.response.send_message(embed=_poll_embed(p), view=PollView(options),
                                            allowed_mentions=discord.AllowedMentions.none())
    msg = await interaction.original_response()
    active_polls[msg.id] = p
    await bd_save_data()
    await send_log(interaction.guild.id, title="📊 Poll started", interaction=interaction, category="community",
                   fields=[("Message", str(msg.id)), ("Question", question), ("Options", " | ".join(options)),
                           ("Duration", f"{duration_minutes} minute(s)")])


@tasks.loop(seconds=30)
async def check_timers():
    """Ends any giveaway/poll whose time is up. Runs off saved timestamps, so
    anything that came due while the bot was offline is handled on startup."""
    now = time.time()
    for mid, gw in list(active_giveaways.items()):
        if gw["ends_at"] <= now:
            try:
                await finish_giveaway(mid)
            except Exception as e:
                log.error(f"Failed to finish giveaway {mid}: {e}")
    for mid, p in list(active_polls.items()):
        if p["ends_at"] <= now:
            try:
                await finish_poll(mid)
            except Exception as e:
                log.error(f"Failed to finish poll {mid}: {e}")


# --- Anti-raid (join-rate spike alerts) -----------------------------------------

DEFAULT_ANTIRAID = {"enabled": False, "threshold": 5, "window": 10}

