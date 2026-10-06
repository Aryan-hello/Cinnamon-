"""Cinnamon feature module.

Loaded by main.py into Cinnamon's shared runtime namespace. This is still
one Discord bot and one process; this file is not a separate bot.
Do not run this file directly.
"""

import io

MAX_LEVEL = 200
DEFAULT_XP_PER_MESSAGE = 20
XP_COOLDOWN_SECONDS = 30


def total_xp_for_level(level: int) -> int:
    """Cumulative XP required to reach `level` (maximum Level 200).

    Cinnamon uses a softened quadratic progression. The XP cost for each
    level step is approximately:
        2.75*L^2 + 40*L + 100

    This keeps early levels approachable while making Level 200 a long-term
    goal of about 8.09 million total XP.
    """
    level = max(0, min(MAX_LEVEL, int(level)))
    if level <= 0:
        return 0
    n = level - 1
    # Exact integer form of:
    # 11/4 * sum(k^2, k=0..n) + 20*n*(n+1) + 100*level
    return (11 * n * (n + 1) * (2 * n + 1) + 240 * n * (n + 1) + 2400 * level) // 24


def level_from_xp(xp: int) -> int:
    """Return the highest level (0-200) whose cumulative XP is met."""
    xp = max(0, int(xp))
    if xp >= total_xp_for_level(MAX_LEVEL):
        return MAX_LEVEL
    lo, hi = 0, MAX_LEVEL
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if total_xp_for_level(mid) <= xp:
            lo = mid
        else:
            hi = mid - 1
    return lo


def xp_settings_for_guild(guild_id: int) -> tuple[int, set[int]]:
    amount = int(xp_per_message.get(guild_id, DEFAULT_XP_PER_MESSAGE))
    channels = set(xp_channels.get(guild_id, set()))
    return max(1, min(1000, amount)), channels


def xp_allowed_in_channel(guild_id: int, channel_id: int) -> bool:
    channels = xp_channels.get(guild_id, set())
    # An empty list means XP is disabled until an admin explicitly selects channels.
    return bool(channels) and channel_id in channels


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
    guild_id = message.guild.id
    if not xp_allowed_in_channel(guild_id, message.channel.id):
        return
    key = (guild_id, message.author.id)
    now = time.monotonic()
    if now - xp_cooldowns.get(key, 0) < XP_COOLDOWN_SECONDS:
        return
    xp_cooldowns[key] = now
    old_xp = xp_data.get(key, 0)
    old_level = level_from_xp(old_xp)
    xp_amount, _ = xp_settings_for_guild(guild_id)
    new_xp = old_xp + xp_amount
    xp_data[key] = new_xp
    new_level = level_from_xp(new_xp)
    await achievement_record(guild_id, message.author.id, "level", new_level)
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
            await achievement_record(message.guild.id, message.author.id, "catnip_earned", reward_total)
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


async def _make_rank_card(member: discord.Member, xp: int, level: int) -> io.BytesIO:
    """Render Cinnamon's 800x200 image rank card."""
    from PIL import Image, ImageDraw, ImageFont
    width, height = 800, 200
    bg = Image.new("RGB", (width, height), (35, 27, 24))
    draw = ImageDraw.Draw(bg)
    draw.rounded_rectangle((12, 12, width - 12, height - 12), radius=24, fill=(49, 37, 31), outline=(255, 176, 46), width=2)
    draw.ellipse((620, -100, 840, 120), fill=(73, 51, 39))
    draw.ellipse((720, 80, 880, 240), fill=(59, 43, 35))
    font_dir = "/usr/share/fonts/truetype/dejavu"
    bold = ImageFont.truetype(f"{font_dir}/DejaVuSans-Bold.ttf", 27)
    regular = ImageFont.truetype(f"{font_dir}/DejaVuSans.ttf", 18)
    small = ImageFont.truetype(f"{font_dir}/DejaVuSans.ttf", 15)
    avatar_size = 120
    avatar = Image.new("RGB", (avatar_size, avatar_size), (75, 55, 45))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(member.display_avatar.replace(size=128).url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    avatar = Image.open(io.BytesIO(await resp.read())).convert("RGB").resize((avatar_size, avatar_size))
    except Exception:
        pass
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
    bg.paste(avatar, (38, 40), mask)
    draw.text((180, 35), member.display_name[:28], font=bold, fill=(255, 244, 231))
    draw.text((180, 72), f"Level {level}", font=regular, fill=(255, 190, 80))
    current = total_xp_for_level(level)
    if level >= MAX_LEVEL:
        progress = 1.0
        progress_text = f"{xp:,} XP • MAX LEVEL"
    else:
        needed = max(1, total_xp_for_level(level + 1) - current)
        progress = max(0.0, min(1.0, (xp - current) / needed))
        progress_text = f"{xp - current:,} / {needed:,} XP to Level {level + 1}"
    bar_x, bar_y, bar_w, bar_h = 180, 116, 555, 25
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=12, fill=(27, 22, 20))
    fill_w = max(0, int((bar_w - 4) * progress))
    if fill_w:
        draw.rounded_rectangle((bar_x + 2, bar_y + 2, bar_x + 2 + fill_w, bar_y + bar_h - 2), radius=10, fill=(255, 176, 46))
    draw.text((180, 151), progress_text, font=small, fill=(224, 211, 201))
    draw.text((620, 69), f"{xp:,} total XP", font=small, fill=(190, 178, 169))
    out = io.BytesIO(); bg.save(out, format="PNG", optimize=True); out.seek(0); return out


@bot.tree.command(name="rank", description="Show your (or someone's) level and XP")
@app_commands.describe(member="Who to check (defaults to you)")
@app_commands.guild_only()
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    xp = xp_data.get((interaction.guild.id, member.id), 0)
    level = level_from_xp(xp)
    this_level_xp = total_xp_for_level(level)
    next_level_xp = total_xp_for_level(level + 1) if level < MAX_LEVEL else this_level_xp
    embed = discord.Embed(title=f"🐾 {member.display_name}'s Rank", color=0xFFB02E)
    embed.add_field(name="Level", value=str(level), inline=True)
    embed.add_field(name="Total XP", value=str(xp), inline=True)
    progress = "MAX LEVEL" if level >= MAX_LEVEL else f"{xp - this_level_xp}/{next_level_xp - this_level_xp} XP to next level"
    embed.add_field(name="Progress", value=progress, inline=True)
    reward = ECONOMY_LEVEL_REWARDS.get(level)
    if reward:
        embed.add_field(name="🌿 Level reward", value=f"+{reward:,} Catnip at this level", inline=True)
    try:
        card = await _make_rank_card(member, xp, level)
        await interaction.response.send_message(embed=embed, file=discord.File(card, filename="cinnamon-rank.png"), allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        log.exception("Rank card rendering failed for %s", member.id)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="leaderboard", description="Show a Cinnamon server leaderboard")
@app_commands.guild_only()
@app_commands.describe(category="What you want to rank members by")
@app_commands.choices(category=[
    app_commands.Choice(name="XP / Levels",value="xp"),
    app_commands.Choice(name="Catnip",value="catnip"),
    app_commands.Choice(name="Achievement Points",value="achievements"),
    app_commands.Choice(name="Messages",value="messages"),
    app_commands.Choice(name="Work Sessions",value="work"),
    app_commands.Choice(name="Cinnamon Friendship",value="friendship"),
])
async def leaderboard(interaction: discord.Interaction, category: app_commands.Choice[str] | None = None):
    category=(category.value if category else "xp")
    gid=interaction.guild.id
    rows=[]
    if category=="xp":
        rows=[(uid,int(xp)) for (g,uid),xp in xp_data.items() if g==gid]
        title="⭐ XP / Level Leaderboard"; fmt=lambda uid,v:f"Level {level_from_xp(v)} · {v:,} XP"
    elif category=="catnip":
        rows=[(uid,int(v)) for (g,uid),v in economy_balances.items() if g==gid]
        title="🌿 Catnip Leaderboard"; fmt=lambda uid,v:f"{v:,} Catnip"
    elif category=="achievements":
        rows=[(uid,int(s.get("points",0))) for (g,uid),s in achievement_data.items() if g==gid]
        title="🏆 Achievement Points Leaderboard"; fmt=lambda uid,v:f"{v:,} AP"
    elif category=="messages":
        rows=[(uid,int(s.get("stats",{}).get("messages",0))) for (g,uid),s in achievement_data.items() if g==gid]
        title="💬 Message Leaderboard"; fmt=lambda uid,v:f"{v:,} messages"
    elif category=="work":
        rows=[(uid,int(s.get("stats",{}).get("work_sessions",0))) for (g,uid),s in achievement_data.items() if g==gid]
        title="💼 Work Leaderboard"; fmt=lambda uid,v:f"{v:,} work sessions"
    else:
        rows=[(uid,int(friendship_data.get((gid,uid),{}).get("points",0))) for (g,uid) in achievement_data if g==gid]
        for (g,uid),fs in friendship_data.items():
            if g==gid and uid not in {x[0] for x in rows}: rows.append((uid,int(fs.get("points",0))))
        title="🐾 Cinnamon Friendship Leaderboard"; fmt=lambda uid,v:f"{v:,} Friendship XP"
    rows=sorted(rows,key=lambda x:x[1],reverse=True)[:10]
    if not rows: return await interaction.response.send_message("No leaderboard data yet. 🐾",ephemeral=True)
    lines=[]
    for i,(uid,v) in enumerate(rows,1):
        m=interaction.guild.get_member(uid); name=m.display_name if m else f"User {uid}"
        lines.append(f"**#{i}** {name} — {fmt(uid,v)}")
    await interaction.response.send_message(embed=discord.Embed(title=title,description="\n".join(lines),color=0xFEE75C),allowed_mentions=discord.AllowedMentions.none())


# --- Level XP settings ----------------------------------------------------------

levelsettings_group = app_commands.Group(name="level-settings", description="Configure Cinnamon XP earning")


@levelsettings_group.command(name="xp", description="Set the fixed XP earned per eligible message")
@app_commands.describe(amount="XP awarded when the member's 30-second XP cooldown is ready (1-1000)")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelsettings_xp(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1000]):
    xp_per_message[interaction.guild.id] = int(amount)
    await bd_save_data()
    await interaction.response.send_message(
        f"📈 Eligible messages now give **{amount} XP**. A member can earn it once every **{XP_COOLDOWN_SECONDS} seconds**, and only in your configured XP channels.",
        ephemeral=True,
    )


@levelsettings_group.command(name="channel-add", description="Allow a channel to earn XP")
@app_commands.describe(channel="Channel where messages can earn XP")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelsettings_channel_add(interaction: discord.Interaction, channel: discord.TextChannel):
    xp_channels.setdefault(interaction.guild.id, set()).add(channel.id)
    await bd_save_data()
    await interaction.response.send_message(
        f"✅ {channel.mention} is now an XP channel. Members can earn XP there once every {XP_COOLDOWN_SECONDS} seconds.",
        ephemeral=True,
    )


@levelsettings_group.command(name="channel-remove", description="Stop a channel from earning XP")
@app_commands.describe(channel="Channel to remove from XP earning")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelsettings_channel_remove(interaction: discord.Interaction, channel: discord.TextChannel):
    channels = xp_channels.setdefault(interaction.guild.id, set())
    if channel.id not in channels:
        return await interaction.response.send_message("That channel is not in the XP channel list.", ephemeral=True)
    channels.remove(channel.id)
    await bd_save_data()
    await interaction.response.send_message(f"🧹 {channel.mention} was removed from the XP channel list.", ephemeral=True)


@levelsettings_group.command(name="channels", description="Show channels that can earn XP")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelsettings_channels(interaction: discord.Interaction):
    channels = sorted(xp_channels.get(interaction.guild.id, set()))
    if not channels:
        return await interaction.response.send_message(
            "📈 **XP channels:** none configured — message XP is currently disabled.\nUse `/level-settings channel-add` to select the channels that can earn XP.",
            ephemeral=True,
        )
    mentions = [f"<#{cid}>" for cid in channels]
    await interaction.response.send_message(
        "📈 **XP channels:**\n" + "\n".join(mentions),
        ephemeral=True,
    )


@levelsettings_group.command(name="channels-clear", description="Disable message XP by clearing the allowed-channel list")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelsettings_channels_clear(interaction: discord.Interaction):
    xp_channels.pop(interaction.guild.id, None)
    await bd_save_data()
    await interaction.response.send_message("✅ XP channel list cleared. Message XP is now disabled until you add at least one channel with `/level-settings channel-add`.", ephemeral=True)


@levelsettings_group.command(name="status", description="Show the server's XP settings")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelsettings_status(interaction: discord.Interaction):
    amount, channels = xp_settings_for_guild(interaction.guild.id)
    channel_text = "None configured (message XP disabled)" if not channels else f"{len(channels)} configured channel(s)"
    await interaction.response.send_message(
        f"📊 **Cinnamon XP settings**\n• XP per eligible message: **{amount}**\n• Cooldown: **{XP_COOLDOWN_SECONDS}s**\n• XP channels: **{channel_text}**\n• Maximum level: **{MAX_LEVEL}**",
        ephemeral=True,
    )


# --- Level roles ----------------------------------------------------------------

levelrewards_group = app_commands.Group(name="level-rewards", description="Configure automatic roles for level milestones")

@levelrewards_group.command(name="add", description="Give a role automatically at a level")
@app_commands.describe(level="Level required", role="Role to award")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def levelrewards_add(interaction: discord.Interaction, level: app_commands.Range[int,1,200], role: discord.Role):
    if role.is_default() or role.managed or role >= interaction.guild.me.top_role:
        return await interaction.response.send_message("❌ I can't assign that role. Make sure it is a normal role below Cinnamon's highest role.",ephemeral=True)
    level_roles.setdefault(interaction.guild.id,{})[int(level)]=role.id
    await bd_save_data()
    await interaction.response.send_message(f"🎖️ **Level {level}** now awards {role.mention}.",allowed_mentions=discord.AllowedMentions.none())

@levelrewards_group.command(name="remove", description="Remove a level role reward")
@app_commands.describe(level="Level whose reward should be removed")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelrewards_remove(interaction: discord.Interaction, level: int):
    if level_roles.get(interaction.guild.id,{}).pop(int(level),None) is None:
        return await interaction.response.send_message(f"❌ No reward is configured for Level {level}.",ephemeral=True)
    await bd_save_data(); await interaction.response.send_message(f"🧹 Removed the Level {level} role reward. Members keep roles they already earned.",ephemeral=True)

@levelrewards_group.command(name="list", description="List all configured level rewards")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def levelrewards_list(interaction: discord.Interaction):
    cfg=level_roles.get(interaction.guild.id,{})
    if not cfg: return await interaction.response.send_message("No level rewards are configured. Use `/levelrewards add`.",ephemeral=True)
    lines=[]
    for lvl in sorted(cfg):
        role=interaction.guild.get_role(cfg[lvl]); lines.append(f"**Level {lvl}** → {role.mention if role else '❌ Deleted role'}")
    await interaction.response.send_message(embed=discord.Embed(title="🎖️ Level Rewards",description="\n".join(lines),color=discord.Color.blurple()),ephemeral=True)

levelrole_group = app_commands.Group(name="levelrole", description="Give roles automatically at certain levels")


@levelrole_group.command(name="add", description="Give a role automatically when members reach a level")
@app_commands.describe(level="Level that unlocks the role", role="Role to give")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def levelrole_add(interaction: discord.Interaction, level: app_commands.Range[int,1,200], role: discord.Role):
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
async def levelrole_remove(interaction: discord.Interaction, level: app_commands.Range[int,1,200]):
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
        if text.startswith("🎉 You're entered"):
            await achievement_record(int(gw.get("guild_id",0)), interaction.user.id, "giveaway", 1)
            await quest_event(int(gw.get("guild_id",0)), interaction.user.id, "giveaway", 1)
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
            # Count a distinct vote action once per user per poll; changing a vote
            # still represents participation in the poll.
            if uid not in poll.setdefault("achievement_voters", []):
                poll["achievement_voters"].append(uid)
                await achievement_record(int(poll.get("guild_id",0)), interaction.user.id, "poll_vote", 1, poll_id=str(interaction.message.id))
                await quest_event(int(poll.get("guild_id",0)), interaction.user.id, "poll_vote", 1, poll_id=str(interaction.message.id))
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

