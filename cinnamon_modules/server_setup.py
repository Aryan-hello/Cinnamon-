"""Cinnamon feature module.

Loaded by main.py into Cinnamon's shared runtime namespace. This is still
one Discord bot and one process; this file is not a separate bot.
Do not run this file directly.
"""


def get_antiraid(guild_id: int) -> dict:
    return antiraid_config.setdefault(guild_id, dict(DEFAULT_ANTIRAID))


async def check_antiraid(member: discord.Member):
    cfg = antiraid_config.get(member.guild.id)
    if not cfg or not cfg.get("enabled"):
        return
    dq = join_log[member.guild.id]
    now = time.monotonic()
    dq.append(now)
    recent = sum(1 for t in dq if now - t <= cfg.get("window", 10))
    if recent >= cfg.get("threshold", 5):
        await send_log(
            member.guild.id, title="🚨 Possible raid detected", color=discord.Color.red(),
            fields=[("Joins", f"{recent} in {cfg.get('window', 10)}s"), ("Latest member", f"{member} ({member.id})")],
        )


antiraid_group = app_commands.Group(name="antiraid", description="Configure join-spike (raid) alerts")


@antiraid_group.command(name="enable", description="Turn on raid-join alerts to the log channel")
@app_commands.describe(threshold="Alert if this many joins happen...", window_seconds="...within this many seconds")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def antiraid_enable(interaction: discord.Interaction, threshold: int = 5, window_seconds: int = 10):
    cfg = get_antiraid(interaction.guild.id)
    cfg.update({"enabled": True, "threshold": threshold, "window": window_seconds})
    await bd_save_data()
    await cinnamon_send(interaction, 
        f"🐾 Anti-raid alerts on: {threshold} joins within {window_seconds}s triggers a log-channel alert. "
        f"(This only alerts — it doesn't auto-kick or lock the server.)"
    )
    await send_log(interaction.guild.id, title="🚨 Anti-raid configuration changed", interaction=interaction, category="moderation",
                   fields=[("Enabled", "True"), ("Threshold", str(threshold)), ("Window", f"{window_seconds}s")])


@antiraid_group.command(name="disable", description="Turn off raid-join alerts")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def antiraid_disable(interaction: discord.Interaction):
    get_antiraid(interaction.guild.id)["enabled"] = False
    await bd_save_data()
    await cinnamon_send(interaction, "🐾 Anti-raid alerts off.")
    await send_log(interaction.guild.id, title="🚨 Anti-raid disabled", interaction=interaction, category="moderation")


# --- Channel lock / unlock -------------------------------------------------------

@bot.tree.command(name="lock", description="Prevent @everyone from sending messages in a channel")
@app_commands.describe(channel="Channel to lock (defaults to this one)")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
@app_commands.guild_only()
async def lock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"Locked by {interaction.user}")
    await cinnamon_send(interaction, f"🔒 {channel.mention} locked.")
    await send_log(
        interaction.guild.id, title="🔒 Channel locked", color=discord.Color.red(), interaction=interaction,
        fields=[("Channel", channel.mention)],
    )


@bot.tree.command(name="unlock", description="Allow @everyone to send messages in a channel again")
@app_commands.describe(channel="Channel to unlock (defaults to this one)")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
@app_commands.guild_only()
async def unlock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None  # inherit
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"Unlocked by {interaction.user}")
    await cinnamon_send(interaction, f"🔓 {channel.mention} unlocked.")
    await send_log(
        interaction.guild.id, title="🔓 Channel unlocked", color=discord.Color.green(), interaction=interaction,
        fields=[("Channel", channel.mention)],
    )


# --- Mod information (reads the log channel live) --------------------------

_MODINFO_TITLES = {
    "⚠️ Member warned", "🚨 Auto-mod action", "👢 Member kicked", "🔨 Member banned",
    "🔓 Member unbanned", "🔇 Member muted", "🔊 Member unmuted", "⏳ Member temp-banned",
    "⏳ Temp-ban expired — member unbanned",
}


@bot.tree.command(name="modinfo", description="Mods only: a person's full moderation history, read from the log channel")
@app_commands.describe(user="Who to look up (works even if they've left or are banned)")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def modinfo(interaction: discord.Interaction, user: discord.User):
    channel = bot.get_channel(log_channels.get(interaction.guild.id, 0))
    if channel is None:
        return await cinnamon_send(interaction, 
            "Set a log channel first with `/logchannel` — this command reads its history.", ephemeral=True
        )
    await interaction.response.defer(ephemeral=True)

    entries = []  # newest first (channel.history order)
    try:
        async for message in channel.history(limit=2000):
            for embed in message.embeds:
                if embed.title not in _MODINFO_TITLES:
                    continue
                fields = {f.name: f.value for f in embed.fields}
                m = _ID_IN_PARENS_RE.search(fields.get("Member", ""))
                target = int(m.group(1)) if m else (int(fields["User ID"]) if fields.get("User ID", "").isdigit() else None)
                if target != user.id:
                    continue
                footer_m = re.search(r"Run by (.+?) • #", embed.footer.text or "") if embed.footer else None
                extra = f" ({fields['Duration']})" if "Duration" in fields else ""
                entries.append({
                    "ts": embed.timestamp or message.created_at,
                    "case": fields.get("Case", "—"),
                    "title": embed.title,
                    "reason": (fields.get("Reason", "") + extra).strip(),
                    "by": footer_m.group(1) if footer_m else "system",
                })
    except discord.HTTPException as e:
        return await interaction.followup.send(f"Couldn't read the log channel: {e}", ephemeral=True)

    member = interaction.guild.get_member(user.id)
    stored_warns = len(warnings_data.get((interaction.guild.id, user.id), []))
    info = [f"**Account created:** {discord.utils.format_dt(user.created_at, 'D')}"]
    if member and member.joined_at:
        info.append(f"**Joined server:** {discord.utils.format_dt(member.joined_at, 'D')}")
    else:
        info.append("**In server:** No (left, kicked, or banned)")
    info.append(f"**Active warnings on file:** {stored_warns}")
    info.append(f"**Logged actions found:** {len(entries)}")

    lines, used = [], 0
    for e in entries:
        line = f"{discord.utils.format_dt(e['ts'], 'd')} **{e['case']}** {e['title']}"
        if e["reason"]:
            line += f" — {e['reason'][:120]}"
        line += f" · _{e['by']}_"
        if used + len(line) > 3000:
            lines.append(f"…and {len(entries) - len(lines)} older action(s) not shown.")
            break
        lines.append(line)
        used += len(line) + 1

    body = "\n".join(lines) if lines else "No logged moderation actions found for this person."
    embed = discord.Embed(
        title=f"🛡️ Mod information — {user}", description="\n".join(info) + "\n\n" + body,
        color=discord.Color.blurple(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Read live from the log channel (last 2000 messages). Actions logged before case IDs existed show —.")
    await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


# --- Health / status ---------------------------------------------------------

async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await cinnamon_send(interaction, 
        f"🏓 **Pong!** Discord latency: **{latency_ms} ms**",
        ephemeral=True,
    )


@app_commands.guild_only()
async def botstatus(interaction: discord.Interaction):
    guild = interaction.guild
    hg_cog = bot.get_cog("HangryGamesCog")
    storage = await storage_status()
    embed = discord.Embed(title="🐾 Cinnamon status", color=discord.Color.blurple())
    embed.add_field(name="Discord latency", value=f"{round(bot.latency * 1000)} ms", inline=True)
    embed.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="Members here", value=str(guild.member_count or 0), inline=True)
    embed.add_field(name="AI channel", value="Enabled" if ai_channels.get(guild.id) else "Off", inline=True)
    embed.add_field(name="Auto-mod", value="Configured" if guild.id in automod_config else "Off", inline=True)
    embed.add_field(name="Anti-raid", value="Enabled" if antiraid_config.get(guild.id, {}).get("enabled") else "Off", inline=True)
    embed.add_field(name="XP / leveling", value="Active", inline=True)
    embed.add_field(name="Hangry Games", value="Ready" if hg_cog else "Starting", inline=True)
    embed.add_field(name="Storage", value=storage["backend"], inline=True)
    embed.set_footer(text="Use /help for commands. 🐾")
    await interaction.response.send_message(embed=cinnamon_polish_embed(embed), ephemeral=True)


# Category-specific logging controls. Existing /logchannel remains the fallback.
categorylogs_group = app_commands.Group(name="categorylogs", description="Configure separate Cinnamon log channels")

@categorylogs_group.command(name="set", description="Set a category's log channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(category="Which Cinnamon category to log", channel="Text channel receiving its logs")
@app_commands.choices(category=[
    app_commands.Choice(name="Moderation", value="moderation"),
    app_commands.Choice(name="Economy", value="economy"),
    app_commands.Choice(name="AI", value="ai"),
    app_commands.Choice(name="Levels & XP", value="levels"),
    app_commands.Choice(name="Achievements", value="achievements"),
    app_commands.Choice(name="Quests", value="quests"),
    app_commands.Choice(name="Cinnamon Friendship", value="friendship"),
    app_commands.Choice(name="Giveaways & Polls", value="community"),
    app_commands.Choice(name="Roles", value="roles"),
    app_commands.Choice(name="Server Setup", value="setup"),
    app_commands.Choice(name="General utilities", value="general"),
])
async def categorylogs_set(interaction: discord.Interaction, category: app_commands.Choice[str], channel: discord.TextChannel):
    category_log_channels.setdefault(interaction.guild.id, {})[category.value] = channel.id
    await secure_log_channel(channel)
    if category.value == "economy":
        economy_log_channels[interaction.guild.id] = channel.id
    if category.value == "moderation":
        log_channels[interaction.guild.id] = channel.id
    await bd_save_data()
    await cinnamon_send(interaction, f"✅ {category.name} logs will be sent to {channel.mention}.", ephemeral=True)
    await send_log(interaction.guild.id, title="⚙️ Category log channel updated", description=f"{category.name} logging configured.", fields=[("Category", category.value), ("Channel", channel.mention), ("Changed by", f"{interaction.user} ({interaction.user.id})")])

@categorylogs_group.command(name="disable", description="Disable a category-specific log channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.choices(category=[
    app_commands.Choice(name="Moderation", value="moderation"), app_commands.Choice(name="Economy", value="economy"),
    app_commands.Choice(name="AI", value="ai"), app_commands.Choice(name="Levels & XP", value="levels"),
    app_commands.Choice(name="Achievements", value="achievements"), app_commands.Choice(name="Quests", value="quests"), app_commands.Choice(name="Cinnamon Friendship", value="friendship"),
    app_commands.Choice(name="Giveaways & Polls", value="community"), app_commands.Choice(name="Roles", value="roles"),
    app_commands.Choice(name="Server Setup", value="setup"), app_commands.Choice(name="General utilities", value="general"),
])
async def categorylogs_disable(interaction: discord.Interaction, category: app_commands.Choice[str]):
    removed = category_log_channels.get(interaction.guild.id, {}).get(category.value)
    if removed:
        await send_log(interaction.guild.id, title="⚙️ Category log channel disabled", interaction=interaction, category=category.value,
                       fields=[("Category", category.value), ("Previous channel ID", str(removed))])
    category_log_channels.get(interaction.guild.id, {}).pop(category.value, None)
    if category.value == "economy": economy_log_channels.pop(interaction.guild.id, None)
    if category.value == "moderation": log_channels.pop(interaction.guild.id, None)
    await bd_save_data()
    await cinnamon_send(interaction, f"Category-specific {category.name} logs {'disabled' if removed else 'were not configured'}. Existing general logs may still be used as fallback.", ephemeral=True)

bot.tree.add_command(categorylogs_group)


# --- Help + guided setup ------------------------------------------------------

async def _ensure_setup_channel(guild: discord.Guild, category: discord.CategoryChannel, name: str, topic: str):
    """Find or create one of Cinnamon's managed setup channels.

    The setup is deliberately idempotent: running /setup again reuses channels
    instead of creating duplicates.
    """
    existing = discord.utils.get(category.text_channels, name=name)
    is_log = name.endswith("-logs") or name in {"cinnamon-logs", "cinnamon-economy", "cinnamon-hangry"}
    overwrites = None
    if is_log and guild.me is not None:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, read_message_history=True),
        }
    if existing:
        if is_log and overwrites:
            await secure_log_channel(existing)
        return existing, False
    channel = await guild.create_text_channel(name=name, category=category, topic=topic, overwrites=overwrites, reason="Cinnamon guided server setup")
    return channel, True


def _command_path(command) -> str:
    parts = []
    current = command
    while current is not None:
        name = getattr(current, "name", None)
        if name:
            parts.append(name)
        current = getattr(current, "parent", None)
    return "/" + " ".join(reversed(parts))


def _all_leaf_commands() -> list:
    """Return every registered slash command, including commands inside groups."""
    leaves = []

    def walk(command):
        children = getattr(command, "commands", None) or []
        if children:
            for child in children:
                walk(child)
        else:
            leaves.append(command)

    for command in bot.tree.get_commands():
        walk(command)
    # Hangry Games is a GroupCog and should already be attached to the tree by
    # the time /help is used, but sorting here makes the output deterministic.
    return sorted(leaves, key=lambda c: _command_path(c).lower())


@bot.tree.command(name="setup", description="Guided first-time setup: create Cinnamon's channels and configure logging")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_channels=True, manage_roles=True, send_messages=True, embed_links=True)
async def setup_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)

    category = discord.utils.get(guild.categories, name="Cinnamon • Logs & Setup")
    created_category = False
    if category is None:
        category = await guild.create_category("Cinnamon • Logs & Setup", reason="Cinnamon guided server setup")
        created_category = True

    specs = [
        ("cinnamon-logs", "Cinnamon moderation, AutoMod, errors, warnings, and general logs."),
        ("cinnamon-economy", "Catnip economy transactions, balance changes, inventory, shop, and snapshots."),
        ("cinnamon-hangry", "Hangry Games starts, winners, cancellations, and recovery logs."),
        ("cinnamon-ai-logs", "Cinnamon AI command usage, settings, and service errors; not private conversation contents."),
        ("cinnamon-level-logs", "XP awards, level-ups, and level-role changes."),
        ("cinnamon-achievement-logs", "Achievement unlocks, secret discoveries, rewards, role assignments, backups, and recovery."),
        ("cinnamon-quest-logs", "Daily/weekly quest rotations, progress, completions, rewards, QP changes, and quest-shop purchases."),
        ("cinnamon-friendship-logs", "Cinnamon Friendship XP, level changes, and related interactions."),
        ("cinnamon-community-logs", "Giveaway and poll events."),
        ("cinnamon-role-logs", "Role management and reaction-role configuration events."),
        ("cinnamon-setup-logs", "Welcome/goodbye, setup, and logging configuration changes."),
        ("cinnamon-general-logs", "General information and utility command usage."),
        ("cinnamon-welcome", "Cinnamon's member welcome messages."),
        ("cinnamon-goodbye", "Cinnamon's member goodbye messages."),
        ("cinnamon-ai", "Cinnamon's always-on AI chat channel."),
    ]
    channels = {}
    created = []
    for name, topic in specs:
        channel, was_created = await _ensure_setup_channel(guild, category, name, topic)
        channels[name] = channel
        if was_created:
            created.append(channel.mention)

    # Create every non-level role used by achievements and the quest shop.
    # Level roles are intentionally excluded; those are configured separately with /level-rewards.
    achievement_role_names = sorted({
        str(a.get("role")).strip()
        for a in list(ACHIEVEMENTS.values()) + list(SECRET_ACHIEVEMENTS.values()) + [ADMIN_ACHIEVEMENT]
        if a.get("role")
    })
    achievement_role_names.append("Quest Master")
    achievement_role_names = list(dict.fromkeys(achievement_role_names))
    created_roles = []
    existing_roles = {r.name: r for r in guild.roles if not r.managed}
    for role_name in achievement_role_names:
        role = existing_roles.get(role_name)
        if role is None:
            try:
                role = await guild.create_role(name=role_name, reason="Cinnamon achievement/quest setup")
                created_roles.append(role.mention)
            except discord.HTTPException as exc:
                log.warning("Could not create Cinnamon reward role %r in guild %s: %s", role_name, guild.id, exc)
    # Configure the systems that have dedicated channel settings.
    log_channels[guild.id] = channels["cinnamon-logs"].id
    economy_log_channels[guild.id] = channels["cinnamon-economy"].id
    category_log_channels[guild.id] = {
        "moderation": channels["cinnamon-logs"].id,
        "economy": channels["cinnamon-economy"].id,
        "ai": channels["cinnamon-ai-logs"].id,
        "levels": channels["cinnamon-level-logs"].id,
        "achievements": channels["cinnamon-achievement-logs"].id,
        "quests": channels["cinnamon-quest-logs"].id,
        "friendship": channels["cinnamon-friendship-logs"].id,
        "community": channels["cinnamon-community-logs"].id,
        "roles": channels["cinnamon-role-logs"].id,
        "setup": channels["cinnamon-setup-logs"].id,
        "general": channels["cinnamon-general-logs"].id,
    }
    ai_channels[guild.id] = channels["cinnamon-ai"].id
    welcome_config[guild.id] = {
        "channel_id": channels["cinnamon-welcome"].id,
        "message": "🐾 Welcome {member} to **{server}**! Cinnamon hopes you brought snacks.",
    }
    goodbye_config[guild.id] = {
        "channel_id": channels["cinnamon-goodbye"].id,
        "message": "🐾 {member} left **{server}**. Cinnamon will miss the head pats!",
    }

    hg_cog = bot.get_cog("HangryGamesCog")
    if hg_cog:
        hg_cog.hg_log_channels[guild.id] = channels["cinnamon-hangry"].id
        hg_cog.log_enabled[guild.id] = True
        await hg_cog._save()

    await bd_save_data()
    await send_log(guild.id, title="⚙️ Cinnamon setup applied", category="setup",
                   fields=[("Main logs", channels["cinnamon-logs"].mention), ("Economy logs", channels["cinnamon-economy"].mention),
                           ("Hangry logs", channels["cinnamon-hangry"].mention), ("AI channel", channels["cinnamon-ai"].mention)])

    # Keep the setup message useful even if someone runs it again later.
    created_text = ", ".join(created) if created else "No channels needed to be created; the setup was already present."
    embed = discord.Embed(
        title="🐾 Cinnamon setup complete",
        description=(
            "I checked the server and configured the main Cinnamon systems. "
            "Running `/setup` again is safe and will reuse these channels.\n\n"
            f"**Created channels:** {created_text}\n\n"
            f"**Reward roles ready:** {len(achievement_role_names)} total"
            + (f"\n**New reward roles:** {', '.join(created_roles)[:1800]}" if created_roles else "\nNo new reward roles were needed; existing roles were reused.")
        ),
        color=discord.Color.green(),
    )
    embed.add_field(name="🛡️ Main logs", value=channels["cinnamon-logs"].mention, inline=True)
    embed.add_field(name="🌿 Economy", value=channels["cinnamon-economy"].mention, inline=True)
    embed.add_field(name="🍔 Hangry Games", value=channels["cinnamon-hangry"].mention, inline=True)
    embed.add_field(name="🤖 AI logs", value=channels["cinnamon-ai-logs"].mention, inline=True)
    embed.add_field(name="🏅 Levels logs", value=channels["cinnamon-level-logs"].mention, inline=True)
    embed.add_field(name="🏆 Achievement logs", value=channels["cinnamon-achievement-logs"].mention, inline=True)
    embed.add_field(name="📜 Quest logs", value=channels["cinnamon-quest-logs"].mention, inline=True)
    embed.add_field(name="🐾 Friendship logs", value=channels["cinnamon-friendship-logs"].mention, inline=True)
    embed.add_field(name="🎉 Community logs", value=channels["cinnamon-community-logs"].mention, inline=True)
    embed.add_field(name="🏷️ Role logs", value=channels["cinnamon-role-logs"].mention, inline=True)
    embed.add_field(name="⚙️ Setup logs", value=channels["cinnamon-setup-logs"].mention, inline=True)
    embed.add_field(name="📌 General logs", value=channels["cinnamon-general-logs"].mention, inline=True)
    embed.add_field(name="👋 Welcome", value=channels["cinnamon-welcome"].mention, inline=True)
    embed.add_field(name="🚪 Goodbye", value=channels["cinnamon-goodbye"].mention, inline=True)
    embed.add_field(name="🐱 AI chat", value=channels["cinnamon-ai"].mention, inline=True)
    embed.add_field(
        name="Next steps",
        value=(
            "Use `/help` to see every command and what it does. "
            "Use `/economy snapshot` before a reset. "
            "Use `/economy restore-snapshot` after a reset if needed."
        ),
        inline=False,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="setupstatus", description="Check Cinnamon's configured channels and systems")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def setupstatus_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    hg_cog = bot.get_cog("HangryGamesCog")
    rows = [
        ("🛡️ Main logs", log_channels.get(guild.id)),
        ("🌿 Economy logs", economy_log_channels.get(guild.id)),
        ("🤖 AI logs", category_log_channels.get(guild.id, {}).get("ai")),
        ("🏅 Levels logs", category_log_channels.get(guild.id, {}).get("levels")),
        ("🏆 Achievement logs", category_log_channels.get(guild.id, {}).get("achievements")),
        ("📜 Quest logs", category_log_channels.get(guild.id, {}).get("quests")),
        ("🐾 Friendship logs", category_log_channels.get(guild.id, {}).get("friendship")),
        ("🎉 Community logs", category_log_channels.get(guild.id, {}).get("community")),
        ("🏷️ Role logs", category_log_channels.get(guild.id, {}).get("roles")),
        ("⚙️ Setup logs", category_log_channels.get(guild.id, {}).get("setup")),
        ("📌 General logs", category_log_channels.get(guild.id, {}).get("general")),
        ("🍔 Hangry logs", hg_cog.hg_log_channels.get(guild.id) if hg_cog else None),
        ("👋 Welcome", welcome_config.get(guild.id, {}).get("channel_id")),
        ("🚪 Goodbye", goodbye_config.get(guild.id, {}).get("channel_id")),
        ("🐱 AI channel", ai_channels.get(guild.id)),
    ]
    lines = []
    for label, channel_id in rows:
        channel = guild.get_channel(channel_id) if channel_id else None
        lines.append(f"{label}: {channel.mention if channel else '❌ Not configured'}")
    embed = discord.Embed(title="🐾 Cinnamon setup status", description="\n".join(lines), color=discord.Color.blurple())
    embed.add_field(name="AutoMod", value="Configured" if guild.id in automod_config else "Not configured", inline=True)
    embed.add_field(name="Anti-raid", value="Enabled" if antiraid_config.get(guild.id, {}).get("enabled") else "Off", inline=True)
    embed.add_field(name="Persistent storage", value=(await storage_status())["backend"], inline=True)
    embed.set_footer(text="Run /setup to create/configure the standard Cinnamon channels.")
    await interaction.response.send_message(embed=cinnamon_polish_embed(embed), ephemeral=True)


# --- Help ---------------------------------------------------------------------

_HELP_EVERYONE = (
    "`/pet` `/treat` `/nap` `/zoomies` — cat antics\n"
    "`/afk` — set an AFK note (auto-replies when you're pinged)\n"
    "`/rank` · `/leaderboard` — your level, and the top 10\n"
    "`/userinfo` · `/serverinfo` — info about a member or the server\n"
    "`/poll` — start a poll with 2–4 options\n"
    "`/ping` · `/botstatus` — check Cinnamon's health\n"
    "`/help` — this menu\n"
    "Chat with me any time by mentioning me or replying to me. 🐾"
)
_HELP_ECONOMY = (
    "`/economy balance` · `/economy inventory` — your Catnip and items\n"
    "`/economy daily` · `/economy work` · `?work` — earn Catnip\n"
    "`/economy shop` · `/economy buy` · `/economy iteminfo` — view, buy, and inspect items\n"
    "`/economy feed` — give Cinnamon items\n"
    "`/economy give` — give Catnip to another member\n"
    "`/collect` — collect income from your income roles\n"
    "`/economy leaderboard` — richest members\n"
)

_HELP_HANGRY = (
    "`/hangrygames new` — open a lobby (Start needs Manage Messages)\n"
    "`/hangrygames giveaway` — lobby with a prize and optional winner role\n"
    "`/hangrygames role` — start straight away with everyone in a role\n"
    "`/hangrygames stats` · `leaderboard` — wins, kills, and top winners\n"
    "`/hangrygames cancel` — stop the game or lobby in this channel"
)
_HELP_MODS = (
    "`/warn` · `/warnings` — warn someone / see their warnings\n"
    "`/kick` `/ban` `/tempban` `/unban`\n"
    "`/mute` · `/unmute` — timeouts\n"
    "`/modinfo` — someone's full mod history, read from the log channel\n"
    "`/purge` `/slowmode` `/lock` `/unlock` — channel tools\n"
    "`/role add` · `/reactionrole create` `remove` — roles\n"
    "`/aichannel` `/disableaichannel` `/disableai` `/enableai` — where I chat"
)
_HELP_ADMINS = (
    "`/logchannel` · `/disablelogchannel` — mod log\n"
    "`/datastatus check` `recover` · `/recall` — storage health and log recovery scan\n"
    "`/welcome` · `/goodbye` — `set` or `disable` join/leave messages\n"
    "`/automod` — `word add/remove/list`, `spam`, `mentions`, `invites`\n"
    "`/antiraid enable` `disable` — join-spike alerts\n"
    "`/levelrole add` `remove` `list` — roles at certain levels\n"
    "`/giveaway start` `end` — prize giveaways\n"
    "`/clearwarnings` · `/role add-all`\n"
    "`/hangrygames logchannel` `disablelogchannel` `log` — its own log channel\n"
    "`/economy logs` — choose the economy transaction log channel\n"
    "`/economy snapshot` — create a complete pre-reset backup\n"
    "`/economy restore-snapshot` — restore the latest backup from economy logs\n"
    "`/economy admin addcatnip` · `removecatnip` — admin balance controls\n"
    "`/economy income` — admin income-role management\n"
    "`/economy item-add` · `/economy item-remove` — admin inventory controls\n`/economy add-item-shop` · `/economy edit-shop-item` · `/economy remove-item-shop` — admin shop controls\n`/economy add-role-income` · `/economy remove-role-income` — admin role income controls\n`/economy iteminfo` — detailed item information"
)


@app_commands.guild_only()
async def help_cmd(interaction: discord.Interaction):
    commands_list = _all_leaf_commands()
    pages = []
    current_lines = []
    current_len = 0
    last_root = None

    for command in commands_list:
        path = _command_path(command)
        root = path.split()[0].lstrip("/")
        description = getattr(command, "description", None) or "No description provided."
        line = f"**{path}** — {description}"
        if len(line) > 900:
            line = line[:897] + "..."
        heading = "" if root == last_root else f"\n**{root.replace('-', ' ').replace('_', ' ').title()}**"
        extra = len(heading) + len(line) + 1
        # Pack multiple command groups into each page so the help command can
        # show the entire bot, not just the first few groups.
        if current_lines and current_len + extra > 3500:
            pages.append("\n".join(current_lines))
            current_lines = []
            current_len = 0
            heading = f"**{root.replace('-', ' ').replace('_', ' ').title()}**"
            extra = len(heading) + len(line) + 1
        current_lines.append(heading)
        current_lines.append(line)
        current_len += extra
        last_root = root
    if current_lines:
        pages.append("\n".join(current_lines))

    embeds = []
    total = len(commands_list)
    for index, body in enumerate(pages, start=1):
        embed = discord.Embed(title=f"🐾 Cinnamon command directory ({index}/{len(pages)})", description=body, color=0xFFB02E)
        embed.set_footer(text=f"/help • {total} commands • Use /setup for guided server setup")
        embeds.append(embed)

    # Add a compact guide as the final page if there is room.
    guide = discord.Embed(
        title="📖 How to use Cinnamon",
        description=(
            "**New server?** Run `/setup` first. It creates and configures the standard log/welcome/AI channels.\n\n"
            "**Looking for something?** Discord's slash-command search also filters these commands as you type.\n\n"
            "**Admin tools:** Most moderation, setup, logging, recovery, and configuration commands require the appropriate Discord permission.\n\n"
            "**Reset protection:** Run `/economy snapshot` before a reset, then `/economy restore-snapshot` afterward.\n\n"
            "**AI:** Mention Cinnamon or reply to her, or use the configured AI channel."
        ),
        color=discord.Color.blurple(),
    )
    if len(embeds) < 10:
        embeds.append(guide)
    await interaction.response.send_message(embeds=embeds, ephemeral=True)


# --- Data status / recovery -------------------------------------------------

datastatus_group = app_commands.Group(name="datastatus", description="Check or recover Cinnamon's persisted data")


@datastatus_group.command(name="check", description="Check whether persistent storage is actually connected right now")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def datastatus_check(interaction: discord.Interaction):
    status = await storage_status()
    icon = "✅" if status["connected"] else "⚠️"
    guild_warnings = sum(1 for g, _ in warnings_data.keys() if g == interaction.guild.id)
    hg_cog = bot.get_cog("HangryGamesCog")
    hg_game_num = hg_cog.game_counts.get(interaction.guild.id, 0) if hg_cog else 0
    embed = discord.Embed(title=f"{icon} Storage status", color=discord.Color.green() if status["connected"] else discord.Color.orange())
    embed.add_field(name="Backend", value=status["backend"], inline=True)
    embed.add_field(name="Connected", value="Yes" if status["connected"] else "No", inline=True)
    embed.add_field(name="Detail", value=status["detail"], inline=False)
    embed.add_field(name="This server's warnings tracked", value=str(guild_warnings), inline=True)
    embed.add_field(name="This server's Hangry Games count", value=str(hg_game_num), inline=True)
    await interaction.response.send_message(embed=cinnamon_polish_embed(embed), ephemeral=True)


async def _scan_recovery_log_channels(guild: discord.Guild, limit: int = 2000) -> dict:
    """Scan every distinct configured log channel and collect recoverable absolute state.

    Discord log messages are evidence, not a database: only fields that record an
    absolute after-value are used to reconstruct state. Messages are de-duplicated
    by channel ID, and history/permission failures are reported to the caller.
    """
    channel_map: dict[int, set[str]] = {}
    def add_channel(channel_id, label):
        if channel_id:
            channel_map.setdefault(int(channel_id), set()).add(label)

    add_channel(log_channels.get(guild.id), "moderation")
    for category, channel_id in category_log_channels.get(guild.id, {}).items():
        add_channel(channel_id, str(category))
    add_channel(economy_log_channels.get(guild.id), "economy")
    hg = bot.get_cog("HangryGamesCog")
    if hg:
        add_channel(hg.hg_log_channels.get(guild.id), "hangry")

    result = {
        "channels_configured": len(channel_map), "channels_scanned": 0,
        "messages_scanned": 0, "embeds_scanned": 0,
        "title_counts": defaultdict(int), "category_counts": defaultdict(int),
        "scan_errors": [], "xp_users_restored": 0,
        "economy_users_from_events": 0,
    }
    events = []
    for channel_id, labels in channel_map.items():
        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except (discord.HTTPException, discord.NotFound, discord.Forbidden) as exc:
                result["scan_errors"].append(f"Channel {channel_id}: {type(exc).__name__}")
                continue
        if not hasattr(channel, "history"):
            result["scan_errors"].append(f"Channel {channel_id}: not a message-history channel")
            continue
        result["channels_scanned"] += 1
        try:
            async for message in channel.history(limit=limit, oldest_first=False):
                result["messages_scanned"] += 1
                for embed in message.embeds:
                    if not embed.title and not embed.fields and not embed.description:
                        continue
                    result["embeds_scanned"] += 1
                    title = (embed.title or "(untitled)").strip()
                    result["title_counts"][title] += 1
                    for label in labels:
                        result["category_counts"][label] += 1
                    events.append((message.created_at, channel_id, embed))
        except (discord.HTTPException, discord.Forbidden) as exc:
            result["scan_errors"].append(f"Channel {channel_id}: {type(exc).__name__}")

    # Process newest-to-oldest so each missing value is reconstructed from its
    # latest absolute log value, never by replaying deltas (which double-count).
    events.sort(key=lambda item: item[0], reverse=True)
    seen_xp, seen_balances, seen_inventory = set(), set(), set()
    economy_keys_before = {uid for gid, uid in economy_balances if gid == guild.id}
    for created_at, channel_id, embed in events:
        fields = {str(f.name).strip(): str(f.value).strip() for f in embed.fields}
        title = (embed.title or "").strip()

        # XP logs contain absolute XP after each award, making safe recovery possible.
        if title == "📈 XP changed":
            user_text = fields.get("User", "")
            match = re.search(r"\((\d+)\)\s*$", user_text)
            xp_match = re.search(r"-?\d+", fields.get("XP after", ""))
            if match and xp_match:
                uid, xp_after = int(match.group(1)), max(0, int(xp_match.group(0)))
                key = (guild.id, uid)
                if uid not in seen_xp:
                    seen_xp.add(uid)
                    old = int(xp_data.get(key, 0) or 0)
                    if xp_after > old:
                        xp_data[key] = xp_after
                        result["xp_users_restored"] += 1
        # Economy quest/achievement recovery intentionally removed.

        # Rebuild missing balances only from absolute post-transaction values.
        candidates = []
        if title == "🎁 Catnip transfer":
            for field_name, value_name in (("From", "Sender after"), ("To", "Recipient after")):
                user_match = re.search(r"\((\d+)\)\s*$", fields.get(field_name, ""))
                value_match = re.search(r"-?[\d,]+", fields.get(value_name, ""))
                if user_match and value_match:
                    candidates.append((int(user_match.group(1)), int(value_match.group(0).replace(",", ""))))
        else:
            user_text = fields.get("User") or fields.get("Member")
            user_match = re.search(r"\((\d+)\)\s*$", user_text or "")
            value_text = fields.get("Balance after") or fields.get("Catnip after")
            value_match = re.search(r"-?[\d,]+", value_text or "")
            if user_match and value_match:
                candidates.append((int(user_match.group(1)), int(value_match.group(0).replace(",", ""))))
        for uid, balance_after in candidates:
            if uid not in seen_balances:
                seen_balances.add(uid)
                key = (guild.id, uid)
                if uid not in economy_keys_before and key not in economy_balances:
                    economy_balances[key] = max(0, balance_after)
                    result["economy_users_from_events"] += 1

        # Absolute item quantity after/remaining values recover individual item counts.
        if title in {"🛒 Economy purchase", "🛠️ Admin item added", "🛠️ Admin item removed", "🐟 Cinnamon fed"}:
            user_text = fields.get("User") or fields.get("Member")
            user_match = re.search(r"\((\d+)\)\s*$", user_text or "")
            item_text = fields.get("Item", "")
            item_match = re.search(r"`([^`]+)`", item_text)
            quantity_text = fields.get("Item quantity after") or fields.get("Quantity after") or fields.get("Quantity remaining")
            quantity_match = re.search(r"-?\d+", quantity_text or "")
            if user_match and item_match and quantity_match:
                uid, item_id, quantity = int(user_match.group(1)), item_match.group(1), max(0, int(quantity_match.group(0)))
                item_key = (uid, item_id)
                if item_key not in seen_inventory:
                    seen_inventory.add(item_key)
                    key = (guild.id, uid)
                    # Preserve a live quantity; only fill missing inventory/item values.
                    current = economy_inventory.get(key)
                    if current is None or item_id not in current:
                        economy_inventory.setdefault(key, {})[item_id] = quantity

    return result


async def recall_guild_data(guild: discord.Guild) -> dict:
    """Scan all configured log channels, then merge only safely recoverable state."""
    scan = await _scan_recovery_log_channels(guild)
    warnings_restored = await recover_warnings_from_log(guild)
    hg_cog = bot.get_cog("HangryGamesCog")
    game_num, wins = await hg_cog.recover_from_log(guild) if hg_cog else (0, 0)

    # Snapshot merge fills missing users/state, rather than refusing recovery just
    # because one live economy account exists. It never overwrites existing accounts.
    economy_restored = 0
    snapshot_detail = "No economy snapshot restored."
    if economy_log_channels.get(guild.id) or category_log_channels.get(guild.id, {}).get("economy") or log_channels.get(guild.id):
        economy_restored, snapshot_detail = await economy_restore_from_snapshot(guild, merge_only=True)
    await bd_save_data()
    scan.update({
        "warnings": warnings_restored,
        "hangry_game_count": game_num,
        "hangry_wins_seen": wins,
        "economy_accounts": economy_restored + scan.get("economy_users_from_events", 0),
        "economy_snapshot_detail": snapshot_detail,
    })
    return scan

@bot.tree.command(name="recall", description="Scan configured logs and recover reconstructable Cinnamon data")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def recall_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        result = await recall_guild_data(interaction.guild)
    except Exception:
        log.exception("Cinnamon recall failed in guild %s", interaction.guild.id)
        return await interaction.followup.send(
            "❌ Recovery hit an unexpected error. No full restore can be confirmed; check the Render logs for the traceback.",
            ephemeral=True,
        )
    await send_log(interaction.guild.id, title="🩹 Log recovery completed", interaction=interaction, category="setup",
                   fields=[("Log embeds scanned", str(result["embeds_scanned"])), ("Warnings restored", str(result["warnings"])),
                           ("XP users restored", str(result["xp_users_restored"])), ("Economy accounts restored", str(result["economy_accounts"])),
                           ("Hangry games found", str(result["hangry_game_count"]))])
    titles = sorted(result["title_counts"].items(), key=lambda pair: pair[1], reverse=True)[:8]
    title_summary = "\n".join(f"• {name[:65]}: **{count}**" for name, count in titles) or "• No embeds found in scanned history."
    errors = "\n".join(f"• {e}" for e in result["scan_errors"][:4]) or "None"
    await interaction.followup.send(
        "🩹 **Cinnamon recovery scan complete**\n"
        f"**Log scan**\n• Configured channels: **{result['channels_configured']}**\n"
        f"• Channels scanned: **{result['channels_scanned']}**\n"
        f"• Messages scanned: **{result['messages_scanned']}**; log embeds: **{result['embeds_scanned']}**\n\n"
        f"**Data recovered**\n• Warnings reconstructed: **{result['warnings']}**\n"
        f"• XP users restored/updated from absolute XP logs: **{result['xp_users_restored']}**\n"
        f"• Economy accounts filled from events/snapshot: **{result['economy_accounts']}**\n"
        f"• Economy snapshot: {result['economy_snapshot_detail']}\n"
        f"• Hangry game counter: **#{result['hangry_game_count']}**; wins found: **{result['hangry_wins_seen']}**\n\n"
        f"**Most common log types found**\n{title_summary}\n\n"
        f"**Channel scan issues**\n{errors}\n\n"
        "Recovery is idempotent for reconstructed counts and only uses absolute values or snapshots where possible. "
        "It cannot recreate deleted messages, AI chat memory, or state that was never logged. Review the counts above to see what was actually found.",
        ephemeral=True,
    )

@datastatus_group.command(name="recover", description="Scan configured logs and recover reconstructable Cinnamon data")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def datastatus_recover(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        result = await recall_guild_data(interaction.guild)
    except Exception:
        log.exception("Cinnamon datastatus recovery failed in guild %s", interaction.guild.id)
        return await interaction.followup.send("❌ Recovery hit an unexpected error. Check Render logs for the traceback.", ephemeral=True)
    await interaction.followup.send(
        f"🩹 Recovery scan complete: **{result['embeds_scanned']}** log embeds across **{result['channels_scanned']}** channels.\n"
        f"Warnings: **{result['warnings']}** · XP users restored/updated: **{result['xp_users_restored']}** · "
        f"Economy accounts filled: **{result['economy_accounts']}** · Hangry games: **#{result['hangry_game_count']}**, wins: **{result['hangry_wins_seen']}**.\n"
        f"Snapshot: {result['economy_snapshot_detail']}\n"
        "Only data supported by retained logs or snapshots can be recovered; see `/recall` for the full scan report.",
        ephemeral=True,
    )


bot.tree.add_command(welcome_group)
bot.tree.add_command(goodbye_group)
bot.tree.add_command(reactionrole_group)
bot.tree.add_command(automod_group)
bot.tree.add_command(giveaway_group)
bot.tree.add_command(levelrole_group)
try: bot.tree.add_command(levelrewards_group)
except Exception: pass
try: bot.tree.add_command(levelsettings_group)
except Exception: pass
bot.tree.add_command(antiraid_group)
bot.tree.add_command(datastatus_group)



# ---------------------------------------------------------------------------
# Economy — Catnip, items, transaction logs, and reset-safe snapshots
# ---------------------------------------------------------------------------


