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


level_role_sync_failures = {}

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
    except discord.HTTPException as exc:
        guild_id = member.guild.id
        level_role_sync_failures[guild_id] = int(level_role_sync_failures.get(guild_id, 0)) + 1
        log.warning("Could not sync level roles for member %s in guild %s: %s", member.id, guild_id, type(exc).__name__)
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
    # Do not spam the level log with ordinary XP awards. Only record XP when
    # the award actually caused a level-up or granted one/more configured
    # level roles (including roles added later to an already-high-level user).
    if new_level > old_level or gained:
        await send_log(
            message.guild.id,
            title="📈 Level progress / role reward",
            category="levels",
            fields=[
                ("User", f"{message.author} ({message.author.id})"),
                ("XP gained", f"+{new_xp - old_xp:,}"),
                ("XP", f"{old_xp:,} → {new_xp:,}"),
                ("Level", f"{old_level} → {new_level}"),
                ("Level roles granted", ", ".join(gained) if gained else "None"),
            ],
        )
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
    progress = "MAX LEVEL" if level >= MAX_LEVEL else f"{xp - this_level_xp:,}/{next_level_xp - this_level_xp:,} XP to next level"
    needed = 1 if level >= MAX_LEVEL else max(1, next_level_xp-this_level_xp)
    current = needed if level >= MAX_LEVEL else max(0, xp-this_level_xp)
    embed = cinnamon_embed(f"🐾 {member.display_name}","Your Cinnamon level card.",color=CINNAMON_ORANGE,user=member,footer="Cinnamon • Rank")
    embed.add_field(name="⭐ Level",value=f"**{level}**",inline=True)
    embed.add_field(name="✨ Total XP",value=f"**{xp:,}**",inline=True)
    embed.add_field(name="📈 Progress",value=f"{cinnamon_progress_bar(current,needed,10)}\n**{progress}**",inline=False)
    reward = ECONOMY_LEVEL_REWARDS.get(level)
    if reward:
        embed.add_field(name="🌿 Level reward", value=f"**+{reward:,} Catnip**", inline=True)
    try:
        card = await _make_rank_card(member, xp, level)
        await interaction.response.send_message(embed=cinnamon_polish_embed(embed), file=discord.File(card, filename="cinnamon-rank.png"), allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        log.exception("Rank card rendering failed for %s", member.id)
        await interaction.response.send_message(embed=cinnamon_polish_embed(embed), allowed_mentions=discord.AllowedMentions.none())


class LeaderboardPageView(discord.ui.View):
    def __init__(self,rows,fmt,title,guild_id,user_id,category,page=0):
        super().__init__(timeout=300); self.rows=rows; self.fmt=fmt; self.title=title; self.guild_id=guild_id; self.user_id=user_id; self.category=category; self.page=page; self._refresh()
    def _refresh(self):
        pages=max(1,(len(self.rows)+7)//8); self.page=max(0,min(self.page,pages-1)); self.clear_items(); p=discord.ui.Button(label="Back",emoji="◀️",style=discord.ButtonStyle.secondary,disabled=self.page==0,row=0); n=discord.ui.Button(label="Next",emoji="▶️",style=discord.ButtonStyle.primary,disabled=self.page>=pages-1,row=0); p.callback=self._prev; n.callback=self._next; self.add_item(p); self.add_item(n)
    async def _guard(self,i):
        if i.user.id!=self.user_id: await i.response.send_message("🐾 This leaderboard belongs to the person who opened it.",ephemeral=True); return False
        return True
    def _embed(self):
        per=8; chunk=self.rows[self.page*per:(self.page+1)*per]; e=cinnamon_embed(self.title,"Top members in this category.",color=CINNAMON_GOLD,user=bot.get_guild(self.guild_id).get_member(self.user_id) if bot.get_guild(self.guild_id) else None,footer=cinnamon_page_footer("Leaderboard",self.page+1,max(1,(len(self.rows)+per-1)//per),f"{len(self.rows)} members")); medals=["🥇","🥈","🥉"]; lines=[]
        for i,(uid,v) in enumerate(chunk,self.page*per+1): lines.append(f"{medals[i-1] if i<=3 else f'**{i}.**'} {self._member_name(uid)}  ·  **{self.fmt(uid,v)}**")
        e.add_field(name="Rankings",value="\n".join(lines) if lines else "No rankings yet.",inline=False); return e
    def _member_name(self,uid):
        m=bot.get_guild(self.guild_id).get_member(uid) if bot.get_guild(self.guild_id) else None; return m.display_name if m else f"User {uid}"
    async def _prev(self,i):
        if not await self._guard(i): return
        self.page-=1; self._refresh(); await i.response.edit_message(embed=self._embed(),view=self)
    async def _next(self,i):
        if not await self._guard(i): return
        self.page+=1; self._refresh(); await i.response.edit_message(embed=self._embed(),view=self)

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
    app_commands.Choice(name="Quests Completed",value="quests"),
    app_commands.Choice(name="Hangry Games Wins",value="hangry"),
    app_commands.Choice(name="Items Collected",value="collection"),
    app_commands.Choice(name="Items Crafted",value="crafted"),
    app_commands.Choice(name="Mystery Boxes Opened",value="mystery"),
    app_commands.Choice(name="Black Market Purchases",value="market"),
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
    elif category=="quests":
        rows=[]
        qg=quest_data.get(gid,{})
        for uid, state in qg.get("users", {}).items():
            rows.append((int(uid), len(state.get("completed_history", []))))
        title="📜 Quest Completion Leaderboard"; fmt=lambda uid,v:f"{v:,} quests"
    elif category=="hangry":
        hg=bot.get_cog("HangryGamesCog")
        rows=[(uid,int(w)) for (g,uid),w in getattr(hg,"win_counts",{}).items() if g==gid] if hg else []
        title="🎮 Hangry Games Wins Leaderboard"; fmt=lambda uid,v:f"{v:,} wins"
    elif category=="collection":
        rows=[(uid,sum(int(q) for q in inv.values())) for (g,uid),inv in economy_inventory.items() if g==gid]
        title="📦 Collection Leaderboard"; fmt=lambda uid,v:f"{v:,} items"
    elif category=="crafted":
        af=globals().get("advanced_features_data",{}).get("crafted_counts",{})
        rows=[(int(k.split(":",1)[1]),int(v)) for k,v in af.items() if k.startswith(str(gid)+":")]
        title="🔨 Crafting Leaderboard"; fmt=lambda uid,v:f"{v:,} crafts"
    elif category=="mystery":
        af=globals().get("advanced_features_data",{}).get("mystery_opened",{})
        rows=[(int(k.split(":",1)[1]),int(v)) for k,v in af.items() if k.startswith(str(gid)+":")]
        title="🎁 Mystery Box Leaderboard"; fmt=lambda uid,v:f"{v:,} boxes opened"
    elif category=="market":
        af=globals().get("advanced_features_data",{}).get("black_market_purchases",{})
        rows=[(int(k.split(":",1)[1]),int(v)) for k,v in af.items() if k.startswith(str(gid)+":")]
        title="🕶️ Black Market Leaderboard"; fmt=lambda uid,v:f"{v:,} purchases"
    else:
        rows=[(uid,int(friendship_data.get((gid,uid),{}).get("points",0))) for (g,uid) in achievement_data if g==gid]
        for (g,uid),fs in friendship_data.items():
            if g==gid and uid not in {x[0] for x in rows}: rows.append((uid,int(fs.get("points",0))))
        title="🐾 Cinnamon Friendship Leaderboard"; fmt=lambda uid,v:f"{v:,} Friendship XP"
    rows=sorted(rows,key=lambda x:x[1],reverse=True)
    if not rows: return await cinnamon_send(interaction, "No leaderboard data yet. 🐾",ephemeral=True)
    per=10; pages=max(1,(len(rows)+per-1)//per); chunk=rows[:per]
    embed=discord.Embed(title=title,description="\n".join(f"**#{i}** {interaction.guild.get_member(uid).display_name if interaction.guild.get_member(uid) else f'User {uid}'} — {fmt(uid,v)}" for i,(uid,v) in enumerate(chunk,1)),color=0xFEE75C)
    embed.set_footer(text=f"Page 1/{pages} • {len(rows)} ranked members")
    view=LeaderboardPageView(rows,fmt,title,interaction.guild.id,interaction.user.id,category,0)
    await interaction.response.send_message(embed=embed,view=view,allowed_mentions=discord.AllowedMentions.none())


# --- Level XP settings ----------------------------------------------------------

levelsettings_group = app_commands.Group(name="level-settings", description="Configure Cinnamon XP earning")


@levelsettings_group.command(name="xp", description="Set the fixed XP earned per eligible message")
@app_commands.describe(amount="XP awarded when the member's 30-second XP cooldown is ready (1-1000)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def levelsettings_xp(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1000]):
    xp_per_message[interaction.guild.id] = int(amount)
    await bd_save_data()
    await cinnamon_send(interaction, 
        f"📈 Eligible messages now give **{amount} XP**. A member can earn it once every **{XP_COOLDOWN_SECONDS} seconds**, and only in your configured XP channels.",
        ephemeral=True,
    )


@levelsettings_group.command(name="channel-add", description="Allow a channel to earn XP")
@app_commands.describe(channel="Channel where messages can earn XP")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def levelsettings_channel_add(interaction: discord.Interaction, channel: discord.TextChannel):
    xp_channels.setdefault(interaction.guild.id, set()).add(channel.id)
    await bd_save_data()
    await cinnamon_send(interaction, 
        f"✅ {channel.mention} is now an XP channel. Members can earn XP there once every {XP_COOLDOWN_SECONDS} seconds.",
        ephemeral=True,
    )


@levelsettings_group.command(name="channel-remove", description="Stop a channel from earning XP")
@app_commands.describe(channel="Channel to remove from XP earning")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def levelsettings_channel_remove(interaction: discord.Interaction, channel: discord.TextChannel):
    channels = xp_channels.setdefault(interaction.guild.id, set())
    if channel.id not in channels:
        return await cinnamon_send(interaction, "That channel is not in the XP channel list.", ephemeral=True)
    channels.remove(channel.id)
    await bd_save_data()
    await cinnamon_send(interaction, f"🧹 {channel.mention} was removed from the XP channel list.", ephemeral=True)


@levelsettings_group.command(name="channels", description="Show channels that can earn XP")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def levelsettings_channels(interaction: discord.Interaction):
    channels = sorted(xp_channels.get(interaction.guild.id, set()))
    if not channels:
        return await cinnamon_send(interaction, 
            "📈 **XP channels:** none configured — message XP is currently disabled.\nUse `/level-settings channel-add` to select the channels that can earn XP.",
            ephemeral=True,
        )
    mentions = [f"<#{cid}>" for cid in channels]
    await cinnamon_send(interaction, 
        "📈 **XP channels:**\n" + "\n".join(mentions),
        ephemeral=True,
    )


@levelsettings_group.command(name="channels-clear", description="Disable message XP by clearing the allowed-channel list")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def levelsettings_channels_clear(interaction: discord.Interaction):
    xp_channels.pop(interaction.guild.id, None)
    await bd_save_data()
    await cinnamon_send(interaction, "✅ XP channel list cleared. Message XP is now disabled until you add at least one channel with `/level-settings channel-add`.", ephemeral=True)


@levelsettings_group.command(name="status", description="Show the server's XP settings")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def levelsettings_status(interaction: discord.Interaction):
    amount, channels = xp_settings_for_guild(interaction.guild.id)
    channel_text = "None configured (message XP disabled)" if not channels else f"{len(channels)} configured channel(s)"
    await cinnamon_send(interaction, 
        f"📊 **Cinnamon XP settings**\n• XP per eligible message: **{amount}**\n• Cooldown: **{XP_COOLDOWN_SECONDS}s**\n• XP channels: **{channel_text}**\n• Maximum level: **{MAX_LEVEL}**",
        ephemeral=True,
    )


# --- Level roles ----------------------------------------------------------------

levelrewards_group = app_commands.Group(name="level-rewards", description="Configure automatic roles for level milestones")

@levelrewards_group.command(name="add", description="Give a role automatically at a level")
@app_commands.describe(level="Level required", role="Role to award")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def levelrewards_add(interaction: discord.Interaction, level: app_commands.Range[int,1,200], role: discord.Role):
    if role.is_default() or role.managed or role >= interaction.guild.me.top_role:
        return await cinnamon_send(interaction, "❌ I can't assign that role. Make sure it is a normal role below Cinnamon's highest role.",ephemeral=True)
    level_roles.setdefault(interaction.guild.id,{})[int(level)]=role.id
    await bd_save_data()
    await cinnamon_send(interaction, f"🎖️ **Level {level}** now awards {role.mention}.",allowed_mentions=discord.AllowedMentions.none())
    await send_log(interaction.guild.id, title="🎖️ Level role added", category="levels", interaction=interaction, fields=[("Action","Added"),("Level",str(level)),("Role",role.name),("Role ID",str(role.id))])

@levelrewards_group.command(name="remove", description="Remove a level role reward")
@app_commands.describe(level="Level whose reward should be removed")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def levelrewards_remove(interaction: discord.Interaction, level: int):
    cfg=level_roles.get(interaction.guild.id,{})
    role_id=cfg.pop(int(level),None)
    if role_id is None:
        return await cinnamon_send(interaction, f"❌ No reward is configured for Level {level}.",ephemeral=True)
    role=interaction.guild.get_role(int(role_id))
    await bd_save_data(); await cinnamon_send(interaction, f"🧹 Removed the Level {level} role reward. Members keep roles they already earned.",ephemeral=True)
    await send_log(interaction.guild.id,title="🎖️ Level role removed",category="levels",interaction=interaction,fields=[("Action","Removed"),("Level",str(level)),("Role",role.name if role else "Deleted role"),("Role ID",str(role_id))])

@levelrewards_group.command(name="list", description="List all configured level rewards")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def levelrewards_list(interaction: discord.Interaction):
    cfg=level_roles.get(interaction.guild.id,{})
    if not cfg: return await cinnamon_send(interaction, "No level rewards are configured. Use `/level-rewards add`.",ephemeral=True)
    lines=[]
    for lvl in sorted(cfg):
        role=interaction.guild.get_role(cfg[lvl]); lines.append(f"**Level {lvl}** → {role.mention if role else '❌ Deleted role'}")
    await interaction.response.send_message(embed=discord.Embed(title="🎖️ Level Rewards",description="\n".join(lines),color=discord.Color.blurple()),ephemeral=True)

levelrole_group = app_commands.Group(name="levelrole", description="Give roles automatically at certain levels")


@levelrole_group.command(name="add", description="Give a role automatically when members reach a level")
@app_commands.describe(level="Level that unlocks the role", role="Role to give")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def levelrole_add(interaction: discord.Interaction, level: app_commands.Range[int,1,200], role: discord.Role):
    if role.is_default() or role.managed:
        return await cinnamon_send(interaction, "That role can't be assigned by a bot.", ephemeral=True)
    if role >= interaction.guild.me.top_role:
        return await cinnamon_send(interaction, 
            "That role is above my highest role, so I can't hand it out. Move my role higher in Server Settings → Roles.",
            ephemeral=True,
        )
    level_roles.setdefault(interaction.guild.id, {})[level] = role.id
    await bd_save_data()
    await cinnamon_send(interaction, 
        f"🐾 Members will get **{role.name}** at **Level {level}**. "
        f"Anyone already past that level gets it the next time they earn XP.",
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await send_log(
        interaction.guild.id, title="🎖️ Level role added", color=discord.Color.green(), interaction=interaction, category="levels",
        fields=[("Action", "Added"), ("Level", str(level)), ("Role", role.name), ("Role ID", str(role.id))],
    )


@levelrole_group.command(name="remove", description="Stop giving a role at a level (members keep roles they already have)")
@app_commands.describe(level="The level to remove the reward from")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def levelrole_remove(interaction: discord.Interaction, level: app_commands.Range[int,1,200]):
    cfg = level_roles.get(interaction.guild.id, {})
    role_id = cfg.pop(level, None)
    if role_id is None:
        return await cinnamon_send(interaction, f"No level role is set for level {level}.", ephemeral=True)
    role = interaction.guild.get_role(int(role_id))
    await bd_save_data()
    await cinnamon_send(interaction, f"🐾 Removed the Level {level} reward. Members keep roles they already earned.")
    await send_log(
        interaction.guild.id, title="🎖️ Level role removed", color=discord.Color.orange(), interaction=interaction, category="levels",
        fields=[("Action", "Removed"), ("Level", str(level)), ("Role", role.name if role else "Deleted role"), ("Role ID", str(role_id))],
    )


@levelrole_group.command(name="list", description="Show this server's level roles")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def levelrole_list(interaction: discord.Interaction):
    cfg = level_roles.get(interaction.guild.id, {})
    if not cfg:
        return await cinnamon_send(interaction, "No level roles set. Add one with `/levelrole add`.", ephemeral=True)
    lines = []
    for lvl in sorted(cfg):
        role = interaction.guild.get_role(cfg[lvl])
        lines.append(f"**Level {lvl}** → {role.name if role else '(deleted role)'}")
    await cinnamon_send(interaction, "\n".join(lines), ephemeral=True)


# --- Cinnamon giveaways (persistent, configurable, restart-safe) -----------------
# Giveaway entries are free; eligibility and extra-entry rules are transparent.
# State is saved by dashboard_runtime.py alongside the rest of Cinnamon's data.

def _giveaway_embed(gw: dict, winner_ids: list[int] | None = None) -> discord.Embed:
    prize = str(gw.get("prize", "Giveaway"))[:200]
    custom_title = str(gw.get("embed_title", "")).strip()[:256]
    custom_description = str(gw.get("embed_description", "")).strip()[:3500]
    color_value = gw.get("embed_color", 0xFEE75C)
    try:
        color_value = int(str(color_value).replace("#", ""), 16) if isinstance(color_value, str) else int(color_value)
        color_value = max(0, min(0xFFFFFF, color_value))
    except (TypeError, ValueError):
        color_value = 0xFEE75C
    if winner_ids is None:
        default_desc = (f"**Prize:** {prize}\n**Winners:** {int(gw.get('winners', 1))}\n"
                        f"Ends <t:{int(gw.get('ends_at', time.time()))}:R>\nHosted by <@{int(gw.get('host_id', 0))}>")
        desc = (custom_description + "\n\n" + default_desc) if custom_description else default_desc
        embed = discord.Embed(title=custom_title or "🎉 Giveaway!", description=desc[:4096], color=color_value)
        embed.add_field(name="Entries", value=str(len(set(gw.get("entrants", [])))), inline=True)
        embed.add_field(name="Winners", value=str(int(gw.get("winners", 1))), inline=True)
        embed.add_field(name="Ends", value=f"<t:{int(gw.get('ends_at', time.time()))}:R>", inline=True)
        req = gw.get("required_roles", [])
        if req:
            embed.add_field(name="Entry requirement", value="One of the required roles", inline=False)
        if int(gw.get("min_account_age_days", 0) or 0):
            embed.add_field(name="Account age", value=f"At least {int(gw['min_account_age_days'])} days", inline=True)
        if int(gw.get("min_server_age_days", 0) or 0):
            embed.add_field(name="Server membership", value=f"At least {int(gw['min_server_age_days'])} days", inline=True)
        embed.set_footer(text="Cinnamon • Tap Enter to join or leave • One person can win once")
        return embed
    won = " ".join(f"<@{u}>" for u in winner_ids) if winner_ids else "No eligible entries this time 🐾"
    embed = discord.Embed(
        title="🎉 Giveaway ended",
        description=f"**Prize:** {prize}\n**Winner{'s' if len(winner_ids) != 1 else ''}:** {won}\nHosted by <@{int(gw.get('host_id', 0))}>",
        color=0x57F287 if winner_ids else 0x99AAB5,
    )
    embed.set_footer(text="Cinnamon • Made with paws 🐾")
    return embed


def _giveaway_eligibility(member, gw: dict) -> tuple[bool, str]:
    """Return (eligible, reason). Blacklisted roles always override bypass roles."""
    if getattr(member, "bot", False):
        return False, "Bots cannot enter giveaways."
    role_ids = {int(r.id) for r in getattr(member, "roles", [])}
    blocked = {int(x) for x in gw.get("blacklisted_roles", []) if str(x).isdigit()}
    if role_ids & blocked:
        return False, str(gw.get("denied_message") or "A role on your account makes you ineligible for this giveaway.")[:300]
    bypass = {int(x) for x in gw.get("bypass_roles", []) if str(x).isdigit()}
    has_bypass = bool(role_ids & bypass)
    if not has_bypass:
        required = {int(x) for x in gw.get("required_roles", []) if str(x).isdigit()}
        if required and not (role_ids & required):
            return False, str(gw.get("denied_message") or "You need one of the required server roles to enter.")[:300]
        account_days = max(0, int(gw.get("min_account_age_days", 0) or 0))
        created_at = getattr(getattr(member, "_user", member), "created_at", None)
        if account_days and created_at:
            age = (datetime.datetime.now(datetime.timezone.utc) - created_at).total_seconds() / 86400
            if age < account_days:
                return False, str(gw.get("denied_message") or f"Your Discord account must be at least {account_days} days old.")[:300]
        server_days = max(0, int(gw.get("min_server_age_days", 0) or 0))
        joined_at = getattr(member, "joined_at", None)
        if server_days and joined_at:
            age = (datetime.datetime.now(datetime.timezone.utc) - joined_at).total_seconds() / 86400
            if age < server_days:
                return False, str(gw.get("denied_message") or f"You must be in this server for at least {server_days} days.")[:300]
    return True, ""


def _giveaway_emoji(value):
    value = str(value or "🎉").strip()
    try:
        if value.startswith("<") and value.endswith(">"):
            return discord.PartialEmoji.from_str(value)
        return value or "🎉"
    except (TypeError, ValueError):
        return "🎉"


class GiveawayView(discord.ui.View):
    def __init__(self, disabled: bool = False, emoji: str | None = None):
        super().__init__(timeout=None)
        button = discord.ui.Button(label="Enter", emoji=_giveaway_emoji(emoji), style=discord.ButtonStyle.success,
                                   custom_id="giveaway:enter", disabled=disabled)
        button.callback = self._enter
        self.add_item(button)

    async def _enter(self, interaction: discord.Interaction):
        gw = active_giveaways.get(interaction.message.id)
        if gw is None:
            return await cinnamon_send(interaction, "This giveaway has ended or was cancelled.", ephemeral=True)
        if interaction.guild is None or interaction.guild.id != int(gw.get("guild_id", 0)):
            return await cinnamon_send(interaction, "This giveaway belongs to another server.", ephemeral=True)
        eligible, reason = _giveaway_eligibility(interaction.user, gw)
        uid = interaction.user.id
        entrants = gw.setdefault("entrants", [])
        if uid not in entrants and not eligible:
            return await cinnamon_send(interaction, reason or "You can't enter this giveaway.", ephemeral=True)
        if uid in entrants:
            entrants.remove(uid)
            text = str(gw.get("leave_message") or "You left the giveaway.")[:300]
            action = "Left"
        else:
            entrants.append(uid)
            text = str(gw.get("entry_message") or "🎉 You're entered! Tap the button again if you want to leave.")[:300]
            action = "Entered"
        await cinnamon_send(interaction, text, ephemeral=True)
        if action == "Entered":
            await achievement_record(int(gw.get("guild_id", 0)), uid, "giveaway", 1)
            await quest_event(int(gw.get("guild_id", 0)), uid, "giveaway", 1)
        await bd_save_data()
        await _refresh_giveaway_message(interaction.message, gw)
        await send_log(int(gw.get("guild_id", 0)), title="🎉 Giveaway entry changed", category="community",
                       fields=[("User", f"{interaction.user} ({uid})"), ("Giveaway message", str(interaction.message.id)),
                               ("Action", action), ("Entrants", str(len(entrants))), ("Prize", str(gw.get("prize", "Giveaway"))[:900])])


async def _refresh_giveaway_message(message, gw: dict):
    try:
        await message.edit(embed=_giveaway_embed(gw), view=GiveawayView(emoji=gw.get("entry_emoji")))
    except (discord.HTTPException, AttributeError):
        pass


async def _create_giveaway(*, guild_id: int, channel_id: int, host_id: int, prize: str, winners: int,
                           duration_minutes: int, config: dict | None = None) -> int:
    config = dict(config or {})
    gw = {
        "guild_id": int(guild_id), "channel_id": int(channel_id), "host_id": int(host_id),
        "winners": max(1, min(100, int(winners))), "prize": str(prize)[:200],
        "ends_at": time.time() + max(1, min(525600, int(duration_minutes))) * 60, "entrants": [],
    }
    allowed = ("bonus_roles", "required_roles", "bypass_roles", "blacklisted_roles", "min_account_age_days",
               "min_server_age_days", "entry_message", "leave_message", "denied_message", "embed_title",
               "embed_description", "embed_color", "entry_emoji", "winner_role_id", "winner_role_minutes",
               "winner_thread_minutes", "reaction_entries", "template_name")
    for key in allowed:
        if key in config:
            gw[key] = config[key]
    channel = bot.get_channel(int(channel_id))
    if channel is None or not hasattr(channel, "send"):
        raise ValueError("The giveaway channel is unavailable.")
    message = await channel.send(embed=_giveaway_embed(gw), view=GiveawayView(emoji=gw.get("entry_emoji")),
                                 allowed_mentions=discord.AllowedMentions.none())
    active_giveaways[message.id] = gw
    if gw.get("reaction_entries"):
        try: await message.add_reaction(_giveaway_emoji(gw.get("entry_emoji") or "🎉"))
        except discord.HTTPException: pass
    await bd_save_data()
    return message.id


async def finish_giveaway(mid: int):
    gw = active_giveaways.pop(int(mid), None)
    if gw is None:
        return
    channel = bot.get_channel(int(gw.get("channel_id", 0)))
    message = None
    if channel is not None:
        try:
            message = await channel.fetch_message(int(mid))
        except discord.HTTPException:
            message = None
    entrants = list(dict.fromkeys(int(uid) for uid in gw.get("entrants", []) if str(uid).isdigit()))
    guild = bot.get_guild(int(gw.get("guild_id", 0)))
    bonus_roles = gw.get("bonus_roles", {}) or {}
    tickets = []
    for uid in entrants:
        member = guild.get_member(uid) if guild else None
        if member is None:
            continue
        eligible, _reason = _giveaway_eligibility(member, gw)
        if not eligible:
            continue
        member_role_ids = {str(role.id) for role in member.roles}
        extra = sum(max(0, min(20, int(count))) for role_id, count in bonus_roles.items()
                    if str(role_id) in member_role_ids and str(count).lstrip("-").isdigit())
        tickets.extend([uid] * (1 + min(extra, 100)))
    eligible_ids = sorted(set(tickets))
    winner_ids = []
    while tickets and len(winner_ids) < min(int(gw.get("winners", 1)), len(eligible_ids)):
        winner = random.choice(tickets)
        if winner not in winner_ids:
            winner_ids.append(winner)
        tickets = [uid for uid in tickets if uid != winner]
    if message is not None:
        try:
            await message.edit(embed=_giveaway_embed(gw, winner_ids), view=GiveawayView(disabled=True))
        except discord.HTTPException:
            pass
    # Keep a small persistent history so rerolls are possible after the giveaway ends.
    history = globals().setdefault("giveaway_history", {})
    gw["winner_ids"] = winner_ids
    gw["finished_at"] = time.time()
    gw["eligible_entrants"] = eligible_ids
    history[str(mid)] = gw
    if len(history) > 250:
        for old_id, _ in sorted(history.items(), key=lambda kv: float(kv[1].get("finished_at", 0)))[:len(history)-250]:
            history.pop(old_id, None)
    await bd_save_data()
    if winner_ids:
        text = f"🎉 Congrats {' '.join(f'<@{u}>' for u in winner_ids)}! You won **{gw['prize']}**!"
    else:
        text = "🐾 No eligible entries this time — no winners selected."
    if message is not None:
        try:
            await message.reply(text, allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            pass
        # Optional winner role; duration is tracked for safe automatic removal.
        role_id = gw.get("winner_role_id")
        role = guild.get_role(int(role_id)) if guild and str(role_id).isdigit() else None
        minutes = max(0, min(525600, int(gw.get("winner_role_minutes", 0) or 0)))
        if role and minutes and guild:
            for uid in winner_ids:
                member = guild.get_member(uid)
                if member:
                    try:
                        await member.add_roles(role, reason=f"Won Cinnamon giveaway {mid}")
                        globals().setdefault("giveaway_timed_roles", []).append({"guild_id": guild.id, "user_id": uid,
                            "role_id": role.id, "remove_at": time.time() + minutes * 60, "message_id": int(mid)})
                    except discord.HTTPException:
                        pass
        thread_minutes = max(0, min(10080, int(gw.get("winner_thread_minutes", 0) or 0)))
        if winner_ids and thread_minutes:
            try:
                thread = await message.create_thread(name=f"Winners • {str(gw['prize'])[:70]}", auto_archive_duration=60)
                await thread.send(f"Congratulations {' '.join(f'<@{u}>' for u in winner_ids)}! Please coordinate your prize here.",
                                   allowed_mentions=discord.AllowedMentions(users=True))
                globals().setdefault("giveaway_timed_threads", []).append({"thread_id": thread.id, "archive_at": time.time() + thread_minutes * 60})
            except (discord.HTTPException, AttributeError):
                pass
    await send_log(int(gw.get("guild_id", 0)), title="🏁 Giveaway finished", category="community",
                   fields=[("Message", str(mid)), ("Prize", str(gw.get("prize", "Giveaway"))[:900]),
                           ("Eligible entrants", str(len(set(gw.get("eligible_entrants", []))))),
                           ("Winners", ", ".join(str(x) for x in winner_ids) if winner_ids else "None")])
    # A few joyful, untagged Cinnamon reactions; never disrupt prize delivery.
    for index, uid in enumerate(winner_ids[:10]):
        try:
            member = guild.get_member(uid) if guild else None
            if member:
                await _cp_good_event(guild, member, "Giveaway winner", points=2)
                if index < 2:
                    await _cp_react(guild, member, channel, "giveaway_win")
        except Exception:
            log.exception("Optional Cinnamon giveaway celebration failed")



async def cancel_giveaway(mid: int):
    """Cancel a giveaway without selecting winners."""
    gw = active_giveaways.pop(int(mid), None)
    if gw is None:
        return False
    await bd_save_data()
    channel = bot.get_channel(int(gw.get("channel_id", 0)))
    if channel is not None:
        try:
            message = await channel.fetch_message(int(mid))
            embed = discord.Embed(title="🎉 Giveaway cancelled", description=f"**Prize:** {gw.get('prize', 'Giveaway')}\nThis giveaway was cancelled by a server manager.", color=0x99AAB5)
            await message.edit(embed=embed, view=GiveawayView(disabled=True))
        except discord.HTTPException:
            pass
    await send_log(int(gw.get("guild_id", 0)), title="🚫 Giveaway cancelled", category="community",
                   fields=[("Message", str(mid)), ("Prize", str(gw.get("prize", "Giveaway"))[:900]),
                           ("Entrants", str(len(gw.get("entrants", []))))])
    return True


def _validate_giveaway_config(guild, *, bonus_roles="", required_roles="", bypass_roles="", blacklisted_roles="",
                               min_account_age_days=0, min_server_age_days=0, winner_role_id="", winner_role_minutes=0,
                               winner_thread_minutes=0, embed_color="FEE75C", entry_emoji="🎉", reaction_entries=False) -> dict:
    def role_ids(raw, label, max_count=20):
        ids=[]
        for token in str(raw or "").replace(",", "\n").splitlines():
            token=token.strip().replace("<@&", "").replace(">", "")
            if not token: continue
            if not token.isdigit(): raise ValueError(f"{label} must contain role IDs, separated by commas or lines.")
            role=guild.get_role(int(token))
            if not role or role.is_default() or role.managed: raise ValueError(f"{label} contains a role that is missing or cannot be assigned.")
            ids.append(role.id)
        if len(set(ids)) > max_count: raise ValueError(f"{label} supports at most {max_count} roles.")
        return list(dict.fromkeys(ids))
    bonus={}
    for line in str(bonus_roles or "").splitlines():
        if not line.strip(): continue
        parts=line.strip().split(":",1)
        if len(parts)!=2 or not parts[0].isdigit() or not parts[1].isdigit(): raise ValueError("Bonus roles must use ROLE_ID:EXTRA_ENTRIES, one per line.")
        role=guild.get_role(int(parts[0])); extra=int(parts[1])
        if not role or role.is_default() or role.managed or not 1<=extra<=20: raise ValueError("Each bonus role must exist and grant 1–20 extra entries.")
        bonus[str(role.id)]=extra
    if len(bonus)>20: raise ValueError("Use at most 20 bonus-entry roles.")
    try:
        min_account_age_days=int(min_account_age_days or 0); min_server_age_days=int(min_server_age_days or 0)
        winner_role_minutes=int(winner_role_minutes or 0); winner_thread_minutes=int(winner_thread_minutes or 0)
    except (ValueError, TypeError): raise ValueError("Giveaway age and duration values must be whole numbers.")
    if not 0<=min_account_age_days<=3650 or not 0<=min_server_age_days<=3650: raise ValueError("Account/server age limits must be between 0 and 3,650 days.")
    if not 0<=winner_role_minutes<=525600 or not 0<=winner_thread_minutes<=10080: raise ValueError("Winner role duration must be ≤1 year and winner thread duration ≤7 days.")
    color=str(embed_color or "FEE75C").strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", color): raise ValueError("Embed colour must be a six-digit hex value, like FEE75C.")
    winner_role_id=str(winner_role_id or "").strip()
    if winner_role_id:
        if not winner_role_id.isdigit(): raise ValueError("Choose a valid winner role.")
        winner_role=guild.get_role(int(winner_role_id))
        if not winner_role or winner_role.is_default() or winner_role.managed: raise ValueError("Winner role is missing or cannot be assigned.")
        if not guild.me or winner_role >= guild.me.top_role: raise ValueError("Move Cinnamon's highest role above the winner role first.")
    emoji=str(entry_emoji or "🎉").strip()[:40] or "🎉"
    return {"bonus_roles":bonus, "required_roles":role_ids(required_roles,"Required roles"),
            "bypass_roles":role_ids(bypass_roles,"Bypass roles"), "blacklisted_roles":role_ids(blacklisted_roles,"Blacklisted roles"),
            "min_account_age_days":min_account_age_days, "min_server_age_days":min_server_age_days,
            "winner_role_id":winner_role_id, "winner_role_minutes":winner_role_minutes,
            "winner_thread_minutes":winner_thread_minutes, "embed_color":color, "entry_emoji":emoji,
            "reaction_entries":bool(reaction_entries)}


giveaway_group = app_commands.Group(name="giveaway", description="Manage Cinnamon's server giveaways")


@giveaway_group.command(name="start", description="Start a configurable giveaway in this channel")
@app_commands.describe(duration_minutes="Duration in minutes (up to one year)", winners="Number of unique winners", prize="What's being given away")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def giveaway_start(interaction: discord.Interaction,
                         duration_minutes: app_commands.Range[int, 1, 525600],
                         winners: app_commands.Range[int, 1, 100], prize: app_commands.Range[str, 1, 200]):
    try:
        mid=await _create_giveaway(guild_id=interaction.guild.id, channel_id=interaction.channel.id,
                                   host_id=interaction.user.id, prize=prize, winners=winners,
                                   duration_minutes=duration_minutes)
    except (ValueError, discord.HTTPException) as exc:
        return await cinnamon_send(interaction, f"Couldn't start that giveaway: {exc}", ephemeral=True)
    await cinnamon_send(interaction, f"🎉 Giveaway started! Message ID: `{mid}` • {winners} winner(s) • {duration_minutes} minute(s).")
    await send_log(interaction.guild.id, title="🎉 Giveaway started", interaction=interaction, category="community",
                   fields=[("Message", str(mid)), ("Prize", prize), ("Duration", f"{duration_minutes} minute(s)"), ("Winners", str(winners))])


@giveaway_group.command(name="end", description="End an active giveaway and pick winners now")
@app_commands.describe(message_id="The ID of the giveaway message")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def giveaway_end(interaction: discord.Interaction, message_id: str):
    if not message_id.isdigit(): return await cinnamon_send(interaction, "That doesn't look like a valid message ID.", ephemeral=True)
    mid=int(message_id); gw=active_giveaways.get(mid)
    if not gw or int(gw.get("guild_id",0))!=interaction.guild.id:
        return await cinnamon_send(interaction, "No active giveaway with that message ID in this server.", ephemeral=True)
    await cinnamon_send(interaction, "Ending the giveaway and selecting winners…", ephemeral=True)
    await finish_giveaway(mid)


@giveaway_group.command(name="reroll", description="Choose a new winner from a recently finished giveaway")
@app_commands.describe(message_id="The finished giveaway message ID")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def giveaway_reroll(interaction: discord.Interaction, message_id: str):
    history=globals().setdefault("giveaway_history", {})
    if not message_id.isdigit(): return await cinnamon_send(interaction, "Use the numeric giveaway message ID.", ephemeral=True)
    mid=int(message_id); gw=history.get(str(mid)) or history.get(mid)
    if not gw or int(gw.get("guild_id",0))!=interaction.guild.id:
        return await cinnamon_send(interaction, "I couldn't find a finished giveaway from this server to reroll.", ephemeral=True)
    old=set(int(x) for x in gw.get("winner_ids",[])); candidates=[int(x) for x in gw.get("eligible_entrants",gw.get("entrants",[])) if int(x) not in old]
    if not candidates: return await cinnamon_send(interaction, "There are no eligible non-winning entrants left to reroll.", ephemeral=True)
    winner=random.choice(candidates); gw.setdefault("winner_ids",[]).append(winner); gw["last_reroll_at"]=time.time()
    await bd_save_data()
    channel=bot.get_channel(int(gw.get("channel_id",0)))
    if channel:
        try:
            message=await channel.fetch_message(mid)
            await message.reply(f"🎉 Reroll winner: <@{winner}>! You won **{gw.get('prize','the giveaway prize')}**.", allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException: pass
    await cinnamon_send(interaction, f"🎉 Rerolled successfully: <@{winner}> is the new winner.", allowed_mentions=discord.AllowedMentions(users=True))


@giveaway_group.command(name="template-save", description="Save an active giveaway as a reusable template")
@app_commands.describe(name="Short name for this template", message_id="The active giveaway message ID")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def giveaway_template_save(interaction: discord.Interaction, name: app_commands.Range[str,1,40], message_id: str):
    if not message_id.isdigit(): return await cinnamon_send(interaction,"Use the numeric giveaway message ID.",ephemeral=True)
    gw=active_giveaways.get(int(message_id))
    if not gw or int(gw.get("guild_id",0))!=interaction.guild.id:
        return await cinnamon_send(interaction,"That active giveaway wasn't found in this server.",ephemeral=True)
    templates=globals().setdefault("giveaway_templates",{}).setdefault(interaction.guild.id,{})
    key=name.strip().lower()
    if not key: return await cinnamon_send(interaction,"Give the template a name.",ephemeral=True)
    templates[key]={k:v for k,v in gw.items() if k not in {"guild_id","channel_id","host_id","ends_at","entrants","winner_ids","finished_at"}}
    await bd_save_data()
    await cinnamon_send(interaction,f"📌 Saved giveaway template **{name.strip()}**. Start it with `/giveaway template-start`.")


@giveaway_group.command(name="template-list", description="List this server's saved giveaway templates")
@app_commands.guild_only()
async def giveaway_template_list(interaction: discord.Interaction):
    templates=globals().setdefault("giveaway_templates",{}).get(interaction.guild.id,{}) or globals().setdefault("giveaway_templates",{}).get(str(interaction.guild.id),{})
    if not templates: return await cinnamon_send(interaction,"No giveaway templates saved yet. Start a giveaway, then use `/giveaway template-save`.",ephemeral=True)
    lines=[f"• **{name}** — {cfg.get('prize','Giveaway')} · {cfg.get('winners',1)} winner(s)" for name,cfg in sorted(templates.items())]
    await cinnamon_send(interaction,"\n".join(lines[:30]),ephemeral=True)


@giveaway_group.command(name="template-start", description="Start a giveaway from a saved template")
@app_commands.describe(name="Saved template name", channel="Where to post it", duration_minutes="How long it runs")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def giveaway_template_start(interaction: discord.Interaction, name: app_commands.Range[str,1,40],
                                   channel: discord.TextChannel, duration_minutes: app_commands.Range[int,1,525600]):
    templates=globals().setdefault("giveaway_templates",{}).get(interaction.guild.id,{}) or globals().setdefault("giveaway_templates",{}).get(str(interaction.guild.id),{})
    cfg=templates.get(name.strip().lower())
    if not cfg: return await cinnamon_send(interaction,"Template not found. Run `/giveaway template-list` to see saved names.",ephemeral=True)
    try:
        mid=await _create_giveaway(guild_id=interaction.guild.id,channel_id=channel.id,host_id=interaction.user.id,
                                   prize=str(cfg.get("prize","Giveaway")),winners=int(cfg.get("winners",1)),
                                   duration_minutes=duration_minutes,config=cfg)
    except (ValueError,discord.HTTPException) as exc:
        return await cinnamon_send(interaction,f"Couldn't start the template: {exc}",ephemeral=True)
    await cinnamon_send(interaction,f"🎉 Started **{name.strip()}** in {channel.mention}. Message ID: `{mid}`.")


@giveaway_group.command(name="repeat", description="Schedule a recurring giveaway")
@app_commands.describe(channel="Where to post", prize="Prize", winners="Number of winners", duration_minutes="Each giveaway duration", repeat_every_days="Days between giveaways (1–365)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def giveaway_repeat(interaction: discord.Interaction, channel: discord.TextChannel,
                          prize: app_commands.Range[str,1,200], winners: app_commands.Range[int,1,100],
                          duration_minutes: app_commands.Range[int,1,525600], repeat_every_days: app_commands.Range[int,1,365]):
    schedules=globals().setdefault("giveaway_schedules",{})
    sid=f"{interaction.guild.id}-{int(time.time())}-{interaction.user.id}"
    schedules[sid]={"guild_id":interaction.guild.id,"channel_id":channel.id,"host_id":interaction.user.id,
                    "prize":prize,"winners":winners,"duration_minutes":duration_minutes,
                    "repeat_every_days":repeat_every_days,"next_at":time.time()+repeat_every_days*86400,"enabled":True}
    await bd_save_data()
    await cinnamon_send(interaction,f"🔁 Recurring giveaway saved as `{sid}`. First run is scheduled <t:{int(schedules[sid]['next_at'])}:R>. Stop it with `/giveaway repeat-stop`.")


@giveaway_group.command(name="repeat-stop", description="Stop a recurring giveaway schedule")
@app_commands.describe(schedule_id="The schedule ID returned by /giveaway repeat")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def giveaway_repeat_stop(interaction: discord.Interaction, schedule_id: str):
    schedules=globals().setdefault("giveaway_schedules",{}); cfg=schedules.get(schedule_id)
    if not cfg or int(cfg.get("guild_id",0))!=interaction.guild.id:
        return await cinnamon_send(interaction,"I couldn't find that recurring giveaway in this server.",ephemeral=True)
    schedules.pop(schedule_id,None); await bd_save_data()
    await cinnamon_send(interaction,"Recurring giveaway schedule stopped. Existing active giveaways are unchanged.")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Optional reaction-based entry; disabled unless the giveaway explicitly enables it."""
    if bot.user and payload.user_id == bot.user.id:
        return
    gw=active_giveaways.get(int(payload.message_id))
    if not gw or not gw.get("reaction_entries"):
        return
    if str(payload.emoji) != str(gw.get("entry_emoji") or "🎉"):
        return
    guild=bot.get_guild(int(gw.get("guild_id",0)))
    member=payload.member or (guild.get_member(int(payload.user_id)) if guild else None)
    if member is None:
        return
    eligible, _reason=_giveaway_eligibility(member,gw)
    if not eligible:
        channel=bot.get_channel(int(gw.get("channel_id",0)))
        if channel:
            try:
                message=await channel.fetch_message(int(payload.message_id))
                await message.remove_reaction(payload.emoji,member)
            except discord.HTTPException: pass
        return
    entrants=gw.setdefault("entrants",[])
    if int(member.id) in entrants:
        return
    entrants.append(int(member.id))
    await bd_save_data()
    channel=bot.get_channel(int(gw.get("channel_id",0)))
    if channel:
        try:
            message=await channel.fetch_message(int(payload.message_id))
            await _refresh_giveaway_message(message,gw)
        except discord.HTTPException: pass
    try:
        await achievement_record(int(gw.get("guild_id",0)),int(member.id),"giveaway",1)
        await quest_event(int(gw.get("guild_id",0)),int(member.id),"giveaway",1)
    except Exception as exc:
        log.debug("Giveaway entry progress hook failed: %s",type(exc).__name__)
    await send_log(int(gw.get("guild_id",0)),title="🎉 Giveaway reaction entry",category="community",
                   fields=[("User",f"{member} ({member.id})"),("Message",str(payload.message_id)),("Entrants",str(len(entrants)))])


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    gw=active_giveaways.get(int(payload.message_id))
    if not gw or not gw.get("reaction_entries") or str(payload.emoji)!=str(gw.get("entry_emoji") or "🎉"):
        return
    uid=int(payload.user_id)
    if uid not in gw.setdefault("entrants",[]):
        return
    gw["entrants"].remove(uid)
    await bd_save_data()
    channel=bot.get_channel(int(gw.get("channel_id",0)))
    if channel:
        try:
            message=await channel.fetch_message(int(payload.message_id))
            await _refresh_giveaway_message(message,gw)
        except discord.HTTPException: pass
    await send_log(int(gw.get("guild_id",0)),title="🎉 Giveaway reaction entry removed",category="community",
                   fields=[("User ID",str(uid)),("Message",str(payload.message_id)),("Entrants",str(len(gw["entrants"])))])


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
                return await cinnamon_send(interaction, "This poll has ended.", ephemeral=True)
            if idx >= len(poll["options"]):
                return await cinnamon_send(interaction, "That option doesn't exist.", ephemeral=True)
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
    # Run recurring giveaway schedules after their first due time. Advance next_at
    # before posting so a temporary Discord failure doesn't create duplicates.
    schedules = globals().setdefault("giveaway_schedules", {})
    for sid, cfg in list(schedules.items()):
        if not cfg.get("enabled", True) or float(cfg.get("next_at", 0)) > now:
            continue
        interval = max(1, min(365, int(cfg.get("repeat_every_days", 7)))) * 86400
        while float(cfg.get("next_at", 0)) <= now:
            cfg["next_at"] = float(cfg.get("next_at", now)) + interval
        try:
            await _create_giveaway(guild_id=int(cfg["guild_id"]), channel_id=int(cfg["channel_id"]),
                host_id=int(cfg["host_id"]), prize=str(cfg["prize"]), winners=int(cfg["winners"]),
                duration_minutes=int(cfg["duration_minutes"]))
        except Exception as e:
            log.error("Recurring giveaway %s failed: %s", sid, e)
        await bd_save_data()
    # Remove timed winner roles and archive winner threads when their timers expire.
    timed_roles = globals().setdefault("giveaway_timed_roles", [])
    for item in list(timed_roles):
        if float(item.get("remove_at", 0)) > now: continue
        guild = bot.get_guild(int(item.get("guild_id", 0)))
        member = guild.get_member(int(item.get("user_id", 0))) if guild else None
        role = guild.get_role(int(item.get("role_id", 0))) if guild else None
        if member and role:
            try: await member.remove_roles(role, reason="Cinnamon giveaway winner-role duration ended")
            except discord.HTTPException: pass
        timed_roles.remove(item); await bd_save_data()
    timed_threads = globals().setdefault("giveaway_timed_threads", [])
    for item in list(timed_threads):
        if float(item.get("archive_at", 0)) > now: continue
        thread=bot.get_channel(int(item.get("thread_id", 0)))
        if thread:
            try: await thread.edit(archived=True, locked=True)
            except discord.HTTPException: pass
        timed_threads.remove(item); await bd_save_data()


# --- Anti-raid (join-rate spike alerts) -----------------------------------------

DEFAULT_ANTIRAID = {"enabled": False, "threshold": 5, "window": 10}

