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
@app_commands.checks.has_permissions(administrator=True)
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
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def antiraid_disable(interaction: discord.Interaction):
    get_antiraid(interaction.guild.id)["enabled"] = False
    await bd_save_data()
    await cinnamon_send(interaction, "🐾 Anti-raid alerts off.")
    await send_log(interaction.guild.id, title="🚨 Anti-raid disabled", interaction=interaction, category="moderation")


# --- Channel lock / unlock -------------------------------------------------------

@bot.tree.command(name="lock", description="Prevent @everyone from sending messages in a channel")
@app_commands.describe(channel="Channel to lock (defaults to this one)")
@app_commands.checks.has_permissions(administrator=True)
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
@app_commands.checks.has_permissions(administrator=True)
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

@bot.tree.command(name="ping", description="Check Cinnamon's Discord latency")
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await cinnamon_send(interaction, 
        f"🏓 **Pong!** Discord latency: **{latency_ms} ms**",
        ephemeral=True,
    )


@bot.tree.command(name="botstatus", description="Check Cinnamon's system status")
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
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(category="Which Cinnamon category to log", channel="Text channel receiving its logs")
@app_commands.choices(category=[
    app_commands.Choice(name="Moderation", value="moderation"),
    app_commands.Choice(name="Economy", value="economy"),
    app_commands.Choice(name="AI", value="ai"),
    app_commands.Choice(name="Levels & XP", value="levels"),
    app_commands.Choice(name="Achievements", value="achievements"),
    app_commands.Choice(name="Quests", value="quests"),
    app_commands.Choice(name="Cinnamon Friendship", value="friendship"),
    app_commands.Choice(name="Cinnamon Stuff", value="stuff"),
    app_commands.Choice(name="Giveaways & Polls", value="community"),
    app_commands.Choice(name="Roles", value="roles"),
    app_commands.Choice(name="Server Setup", value="setup"),
    app_commands.Choice(name="General utilities", value="general"), app_commands.Choice(name="Dashboard audit trail", value="dashboard"),
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
    await send_log(interaction.guild.id, title="⚙️ Category log channel updated", description=f"{category.name} logging configured.", fields=[("Category", category.value), ("Channel", channel.mention), ("Changed by", f"{interaction.user} ({interaction.user.id})")], category="dashboard" if category.value == "dashboard" else "setup")
    if category.value != "dashboard":
        await send_log(interaction.guild.id, title="🧭 Dashboard audit • Log route updated", description=f"{category.name} logging route changed to {channel.mention}.", fields=[("Changed by", f"{interaction.user} ({interaction.user.id})")], category="dashboard")

@categorylogs_group.command(name="disable", description="Disable a category-specific log channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(category=[
    app_commands.Choice(name="Moderation", value="moderation"), app_commands.Choice(name="Economy", value="economy"),
    app_commands.Choice(name="AI", value="ai"), app_commands.Choice(name="Levels & XP", value="levels"),
    app_commands.Choice(name="Cinnamon Stuff", value="stuff"),
    app_commands.Choice(name="Achievements", value="achievements"), app_commands.Choice(name="Quests", value="quests"), app_commands.Choice(name="Cinnamon Friendship", value="friendship"),
    app_commands.Choice(name="Giveaways & Polls", value="community"), app_commands.Choice(name="Roles", value="roles"),
    app_commands.Choice(name="Server Setup", value="setup"), app_commands.Choice(name="General utilities", value="general"), app_commands.Choice(name="Dashboard audit trail", value="dashboard"),
])
async def categorylogs_disable(interaction: discord.Interaction, category: app_commands.Choice[str]):
    removed = category_log_channels.get(interaction.guild.id, {}).get(category.value)
    if removed:
        await send_log(interaction.guild.id, title="⚙️ Category log channel disabled", interaction=interaction, category="dashboard" if category.value == "dashboard" else category.value,
                       fields=[("Category", category.value), ("Previous channel ID", str(removed))])
        if category.value != "dashboard":
            await send_log(interaction.guild.id, title="🧭 Dashboard audit • Log route disabled", description=f"The {category.name} category log route was disabled.", interaction=interaction, category="dashboard",
                           fields=[("Category", category.value), ("Previous channel ID", str(removed))])
    category_log_channels.get(interaction.guild.id, {}).pop(category.value, None)
    if category.value == "economy": economy_log_channels.pop(interaction.guild.id, None)
    if category.value == "moderation": log_channels.pop(interaction.guild.id, None)
    await bd_save_data()
    await cinnamon_send(interaction, f"Category-specific {category.name} logs {'disabled' if removed else 'were not configured'}. Existing general logs may still be used as fallback.", ephemeral=True)

bot.tree.add_command(categorylogs_group)


# --- Web dashboard entry point -------------------------------------------------

@bot.tree.command(name="dashboard", description="Open Cinnamon's web control panel")
@app_commands.guild_only()
async def dashboard_cmd(interaction: discord.Interaction):
    base_url = (os.environ.get("DASHBOARD_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "https://cinnamon-c328.onrender.com").rstrip("/")
    url = f"{base_url}/dashboard"
    embed = discord.Embed(title="🐾 Cinnamon Control", description=f"[Open the web dashboard]({url})\n\nManage server settings, moderation, progression, economy, Message Studio, analytics, and activity logs. Sign in with Discord; dashboard permissions are checked again on every request.", color=discord.Color(0xD97732))
    embed.add_field(name="Audit trail", value="Dashboard actions are copied to the configured dashboard audit channel. Run `/setup` to create `#cinnamon-dashboard-logs`.", inline=False)
    embed.set_footer(text="Cinnamon • Made with paws 🐾")
    await interaction.response.send_message(embed=embed, ephemeral=True)
    try:
        await send_log(interaction.guild.id, title="🧭 Web dashboard opened", description=f"{interaction.user} ({interaction.user.id}) requested the dashboard link.", interaction=interaction, category="dashboard")
    except Exception:
        log.exception("Could not log dashboard command use")


# --- Help + guided setup ------------------------------------------------------

async def _ensure_setup_channel(guild: discord.Guild, category: discord.CategoryChannel, name: str, topic: str):
    """Find or create one of Cinnamon's managed setup channels.

    The setup is deliberately idempotent: running /setup again reuses channels
    instead of creating duplicates.
    """
    existing = discord.utils.get(category.text_channels, name=name)
    is_log = name.endswith("-logs") or name in {"cinnamon-logs", "cinnamon-economy", "cinnamon-hangry"}
    is_public_game = name == "cinnamon-games"
    overwrites = None
    if is_log and guild.me is not None:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, read_message_history=True),
        }
    if is_public_game and guild.me is not None:
        # The parent category contains PRIVATE logs. Explicitly keep this game
        # channel readable for all members and writable only by Cinnamon.
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, read_message_history=True),
        }
    if existing:
        if is_log and overwrites:
            await secure_log_channel(existing)
        if is_public_game and overwrites:
            for target, perms in overwrites.items():
                await existing.set_permissions(target, overwrite=perms,
                                               reason="Keep Cinnamon surprise games visible but orderly")
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
async def setup_cmd(interaction: discord.Interaction, hangry_games_channel: discord.TextChannel | None = None):
    # Do the permission checks inside the command instead of decorator checks.
    # This guarantees that /setup is actually invokable and lets Cinnamon give
    # a useful error instead of Discord silently rejecting the interaction.
    guild = interaction.guild
    if guild is None:
        return await interaction.response.send_message("🐾 /setup can only be used inside a server.", ephemeral=True)
    if hangry_games_channel is not None and hangry_games_channel.guild.id != guild.id:
        return await interaction.response.send_message("🐈 Choose a channel in this server.", ephemeral=True)
    user_perms = interaction.user.guild_permissions
    if not user_perms.administrator:
        return await interaction.response.send_message(
            "🐾 You need **Administrator** to run `/setup`.",
            ephemeral=True,
        )
    me = guild.me
    if me is None:
        return await interaction.response.send_message(
            "🐾 I couldn't resolve my member permissions in this server. Please reinvite/restart Cinnamon and try again.",
            ephemeral=True,
        )
    missing = []
    if not me.guild_permissions.manage_channels:
        missing.append("Manage Channels")
    if not me.guild_permissions.send_messages:
        missing.append("Send Messages")
    if missing:
        return await interaction.response.send_message(
            "🐾 Cinnamon is missing: **" + ", ".join(missing) + "**. Give the bot role those permissions and run `/setup` again.",
            ephemeral=True,
        )
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
        ("cinnamon-stuff-logs", "Private mood, favourite, nice/naughty, questions and personality event logs."),
        ("cinnamon-mood-logs", "Private detailed Cinnamon mood changes, naughty status and forgiveness logs."),
        ("cinnamon-community-logs", "Giveaway and poll events."),
        ("cinnamon-role-logs", "Role management and reaction-role configuration events."),
        ("cinnamon-setup-logs", "Welcome/goodbye, setup, and logging configuration changes."),
        ("cinnamon-general-logs", "General information and utility command usage."),
        ("cinnamon-dashboard-logs", "Dashboard settings changes, Message Studio sends, and dashboard audit events."),
        ("cinnamon-welcome", "Cinnamon's member welcome messages."),
        ("cinnamon-goodbye", "Cinnamon's member goodbye messages."),
        ("cinnamon-ai", "Cinnamon's always-on AI chat channel."),
        ("cinnamon-games", "Public surprise Hangry Games with Catnip prizes and a join button."),
    ]
    channels = {}
    created = []
    failed = []
    for name, topic in specs:
        try:
            channel, was_created = await _ensure_setup_channel(guild, category, name, topic)
            channels[name] = channel
            if was_created:
                created.append(channel.mention)
        except (discord.Forbidden, discord.HTTPException) as exc:
            failed.append(f"#{name}: {type(exc).__name__}")
            log.warning("/setup could not prepare #%s in guild %s: %s", name, guild.id, exc)

    # Every channel below is referenced later when routing Cinnamon's systems.
    # If Discord blocked even one, stop here with the exact channel names rather
    # than crashing later with a misleading KeyError.
    missing_channels = [name for name, _topic in specs if name not in channels]
    if missing_channels:
        details = ", ".join(f"#{name}" for name in missing_channels)
        raise RuntimeError(
            f"Discord would not let Cinnamon create/access these setup channels: {details}. "
            "Check Manage Channels and the bot role/category permissions."
        )

    # Create every non-level role used by achievements and the quest shop.
    # Level roles are intentionally excluded; those are configured separately with /level-rewards.
    # Role creation is optional: /setup should still configure channels when the bot
    # has Manage Channels but not Manage Roles.
    can_manage_roles = bool(guild.me and guild.me.guild_permissions.manage_roles)
    achievement_role_names = sorted({
        str(a.get("role")).strip()
        for a in list(ACHIEVEMENTS.values()) + list(SECRET_ACHIEVEMENTS.values()) + [ADMIN_ACHIEVEMENT]
        if a.get("role")
    })
    achievement_role_names.append("Quest Master")
    # Fishing titles and the two server-wide merchants are core Wildlands roles.
    achievement_role_names.extend(_wlf_required_roles())
    achievement_role_names.append(_CM_NAUGHTY_ROLE)  # playful temporary penalty role
    achievement_role_names.append("Hangry Games")
    achievement_role_names = list(dict.fromkeys(achievement_role_names))
    created_roles = []
    existing_roles = {r.name: r for r in guild.roles if not r.managed}
    if can_manage_roles:
        for role_name in achievement_role_names:
            role = existing_roles.get(role_name)
            if role is None:
                try:
                    role = await guild.create_role(name=role_name, reason="Cinnamon achievement/quest setup",
                                                   mentionable=(role_name == "Hangry Games"))
                    created_roles.append(role.mention)
                except discord.HTTPException as exc:
                    log.warning("Could not create Cinnamon reward role %r in guild %s: %s", role_name, guild.id, exc)
            elif role_name == "Hangry Games" and not role.mentionable:
                try:
                    await role.edit(mentionable=True, reason="Allow Cinnamon's two Hangry Games opt-in alerts")
                except discord.HTTPException as exc:
                    log.warning("Could not enable Hangry Games role mentions in guild %s: %s", guild.id, exc)
    # Pre-create both fishing merchant channels PRIVATELY. Keep any active
    # two-hour discovery windows unchanged when /setup runs again.
    merchant_channels = {}
    for merchant_kind in _WLF_MERCHANTS:
        try:
            merchant_channels[merchant_kind] = await _wlf_refresh_channel(guild, merchant_kind)
        except (discord.HTTPException, PermissionError) as exc:
            failed.append(f"#{_WLF_SHOP_NAMES[merchant_kind]}: {type(exc).__name__}")
            log.warning("Merchant setup failed for %s: %s", merchant_kind, exc)

    # Always restore the dedicated level log route, even on servers that ran an
    # older setup before the level-log channel existed. _ensure_setup_channel
    # above has already created/reused cinnamon-level-logs.
    state_category_logs = category_log_channels.setdefault(guild.id, {})
    state_category_logs["levels"] = channels["cinnamon-level-logs"].id
    await bd_save_data()

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
        "stuff": channels["cinnamon-stuff-logs"].id,
        "mood": channels["cinnamon-mood-logs"].id,
        "community": channels["cinnamon-community-logs"].id,
        "roles": channels["cinnamon-role-logs"].id,
        "setup": channels["cinnamon-setup-logs"].id,
        "general": channels["cinnamon-general-logs"].id,
        "dashboard": channels["cinnamon-dashboard-logs"].id,
    }
    ai_channels[guild.id] = channels["cinnamon-ai"].id
    social = _cp_server(guild.id)
    previous_channel = guild.get_channel(int(social.get("auto_channel", 0) or 0))
    chosen_channel = hangry_games_channel or previous_channel or channels["cinnamon-games"]
    if not chosen_channel.permissions_for(guild.me).send_messages or not chosen_channel.permissions_for(guild.default_role).view_channel:
        raise RuntimeError("Hangry Games channel must be public and allow Cinnamon to send messages. Choose another channel in /setup.")
    social["auto_channel"] = chosen_channel.id
    if not social.get("setup_configured", False):
        social["auto_enabled"] = True
        social["setup_configured"] = True
    social.setdefault("next_at", time.time() + random.randint(3600, 7200))
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
    await send_log(guild.id, title="🧭 Dashboard audit • Cinnamon setup applied", category="dashboard",
                   description="The guided /setup flow configured Cinnamon's channels and logging routes.",
                   fields=[("Dashboard audit log", channels["cinnamon-dashboard-logs"].mention),
                           ("Setup actor", f"{interaction.user} ({interaction.user.id})")])

    # Keep the setup message useful even if someone runs it again later.
    created_text = ", ".join(created) if created else "No channels needed to be created; the setup was already present."
    failed_text = ", ".join(failed) if failed else "None"
    embed = discord.Embed(
        title="🐾 Cinnamon setup complete",
        description=(
            "I checked the server and configured the main Cinnamon systems. "
            "Running `/setup` again is safe and will reuse these channels.\n\n"
            f"**Created channels:** {created_text}\n\n"
            f"**Channels that could not be prepared:** {failed_text}\n\n"
            f"**Reward roles ready:** {len(achievement_role_names)} total"
            + (f"\n**New reward roles:** {', '.join(created_roles)[:1800]}" if created_roles else ("\nNo new reward roles were needed; existing roles were reused." if can_manage_roles else "\n⚠️ I could not create reward roles because I do not have **Manage Roles**. Channels were configured normally."))
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
    embed.add_field(name="😾 Cinnamon stuff logs", value=channels["cinnamon-stuff-logs"].mention, inline=True)
    embed.add_field(name="🐈 Mood logs", value=channels["cinnamon-mood-logs"].mention, inline=True)
    for _kind, _channel in merchant_channels.items():
        embed.add_field(name="🏪 " + ("Rod" if _kind=="rod" else "Bait") + " Merchant", value=_channel.mention + (" • **Public**" if _wlf_active(guild.id,_kind) else " • **Private**"), inline=True)
    embed.add_field(name="🎮 Surprise games", value=chosen_channel.mention, inline=True)
    embed.add_field(name="🎉 Community logs", value=channels["cinnamon-community-logs"].mention, inline=True)
    embed.add_field(name="🏷️ Role logs", value=channels["cinnamon-role-logs"].mention, inline=True)
    embed.add_field(name="⚙️ Setup logs", value=channels["cinnamon-setup-logs"].mention, inline=True)
    embed.add_field(name="📌 General logs", value=channels["cinnamon-general-logs"].mention, inline=True)
    embed.add_field(name="🧭 Dashboard audit", value=channels["cinnamon-dashboard-logs"].mention, inline=True)
    embed.add_field(name="👋 Welcome", value=channels["cinnamon-welcome"].mention, inline=True)
    embed.add_field(name="🚪 Goodbye", value=channels["cinnamon-goodbye"].mention, inline=True)
    embed.add_field(name="🐱 AI chat", value=channels["cinnamon-ai"].mention, inline=True)
    embed.add_field(
        name="Next steps",
        value=(
            "Use `/fishing start` and `/wildlands gather` for Wildlands fishing, or `/help` for all commands. "
            "Use `/dashboard` to open Cinnamon Control. "
            "Dashboard actions are recorded in the dashboard audit channel. Use `/economy snapshot` before a reset. "
            "Use `/economy restore-snapshot` after a reset if needed."
        ),
        inline=False,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@setup_cmd.error
async def setup_cmd_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
    if isinstance(error, app_commands.MissingPermissions):
        msg = (
            "🐾 You need **Manage Server** (or Administrator) to run `/setup`. "
            "If you already have it, make sure you are running this command in the server where Cinnamon is installed."
        )
    elif isinstance(error, app_commands.BotMissingPermissions):
        missing = ", ".join(str(p).replace("_", " ").title() for p in getattr(error, "missing_permissions", [])) or "Manage Channels / Send Messages / Embed Links"
        msg = f"🐾 Cinnamon is missing these permissions: **{missing}**. Give Cinnamon the required permissions and run `/setup` again."
    elif isinstance(original, discord.Forbidden):
        msg = (
            "🐾 Discord refused one of the setup actions. Cinnamon needs **Manage Channels**, "
            "**Send Messages**, and its role must not be blocked by a channel/category permission override."
        )
    elif isinstance(original, RuntimeError):
        log.error("/setup failed: %s", original)
        msg = f"🐾 `/setup` could not finish: **{str(original)[:1800]}**"
    else:
        log.exception("/setup failed", exc_info=original)
        msg = f"🐾 `/setup` hit **{type(original).__name__}**. Check Render logs for the exact Discord error."

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)
    await _send_admin_error_dm(
        interaction.user,
        command_name="/setup",
        error=error,
        context=f"Server: {interaction.guild.name if interaction.guild else 'DM'} | Setup command",
    )


@bot.command(name="setup")
@commands.guild_only()
async def prefix_setup(ctx: commands.Context):
    """Fallback for servers where Discord has not refreshed /setup yet."""
    if not (ctx.author.guild_permissions.manage_guild or ctx.author.guild_permissions.administrator):
        msg = "🐾 You need **Manage Server** (or **Administrator**) to run `?setup`."
        await ctx.reply(msg, mention_author=False)
        await _send_admin_error_dm(ctx.author, command_name="?setup", error=commands.MissingPermissions(["manage_guild"]), context=f"Server: {ctx.guild.name} | Prefix setup")
        return
    me = ctx.guild.me
    if me is None or not me.guild_permissions.manage_channels or not me.guild_permissions.send_messages:
        msg = "🐾 Cinnamon needs **Manage Channels** and **Send Messages** before setup can run."
        await ctx.reply(msg, mention_author=False)
        missing = []
        if me is None or not me.guild_permissions.manage_channels:
            missing.append("manage_channels")
        if me is None or not me.guild_permissions.send_messages:
            missing.append("send_messages")
        await _send_admin_error_dm(ctx.author, command_name="?setup", error=commands.BotMissingPermissions(missing), context=f"Server: {ctx.guild.name} | Prefix setup")
        return

    # The slash command contains the full setup workflow. The prefix fallback
    # intentionally only handles the registration/cache problem: it tells the
    # owner to use the slash command once Discord has refreshed its command list.
    await ctx.reply(
        "🐾 Cinnamon is online, but Discord's slash-command cache may be stale. "
        "Use `/setup` from the slash-command menu after restarting Discord. "
        "If `/setup` is still missing, check the Render log for **Guild-synced 55 Cinnamon slash commands**.",
        mention_author=False,
    )


@bot.tree.command(name="setupstatus", description="Check Cinnamon's configured channels and systems")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
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
        ("😾 Cinnamon stuff logs", category_log_channels.get(guild.id, {}).get("stuff")),
        ("🎮 Surprise games", _cp_server(guild.id).get("auto_channel")),
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
    "`/mood status` · `talk` · `play` · `apologize` — cheer up Cinnamon and make amends\n"
    "`/economy give` — give Catnip to another member\n"
    "`/collect` — collect income from your income roles\n"
    "`/economy leaderboard` — richest members\n"
)

_HELP_HANGRY = (
    "`/hangrygames new` — open a lobby (Start needs Manage Messages)\n"
    "`/hangrygames giveaway` — lobby with a prize and optional winner role\n"
    "`/hangrygames role` — start straight away with everyone in a role\n"
    "`/hangrygames stats` · `leaderboard` — wins, kills, and top winners\n"
    "`/hangrygames cancel` — stop the game or lobby in this channel\n"
    "`/hangrygames budget` — weekly hosted Catnip prize budget and completed games\n"
    "`/cinnamon-events status` · `auto` · `channel` · `notify` · `questions` · `cameos` · `announce` · `people` · `test-game` — surprise games and interactions"
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


class HelpPagesView(discord.ui.View):
    def __init__(self, user_id: int, embeds: list[discord.Embed], page: int = 0):
        super().__init__(timeout=300); self.user_id=user_id; self.embeds=embeds; self.page=page; self._refresh()
    def _refresh(self):
        self.page=max(0,min(self.page,len(self.embeds)-1)); self.clear_items()
        back=discord.ui.Button(label="Back",emoji="◀️",style=discord.ButtonStyle.secondary,disabled=self.page==0,row=0)
        nxt=discord.ui.Button(label="Next",emoji="▶️",style=discord.ButtonStyle.primary,disabled=self.page>=len(self.embeds)-1,row=0)
        close=discord.ui.Button(label="Close",emoji="✖️",style=discord.ButtonStyle.danger,row=0)
        back.callback=self._back; nxt.callback=self._next; close.callback=self._close
        self.add_item(back); self.add_item(nxt); self.add_item(close)
    async def _guard(self,i):
        if i.user.id!=self.user_id:
            await i.response.send_message("🐾 This help panel belongs to the person who opened it.",ephemeral=True); return False
        return True
    async def _back(self,i):
        if not await self._guard(i): return
        self.page-=1; self._refresh(); await i.response.edit_message(embed=self.embeds[self.page],view=self)
    async def _next(self,i):
        if not await self._guard(i): return
        self.page+=1; self._refresh(); await i.response.edit_message(embed=self.embeds[self.page],view=self)
    async def _close(self,i):
        if not await self._guard(i): return
        for child in self.children: child.disabled=True
        await i.response.edit_message(view=self)


@app_commands.guild_only()
async def help_cmd(interaction: discord.Interaction):
    commands_list = _all_leaf_commands(); pages=[]; current_lines=[]; current_len=0; last_root=None
    for command in commands_list:
        path=_command_path(command); root=path.split()[0].lstrip("/"); description=getattr(command,"description",None) or "No description provided."
        line=f"**{path}** — {description}"; line=line[:897]+"..." if len(line)>900 else line
        heading="" if root==last_root else f"\n**{root.replace('-', ' ').replace('_', ' ').title()}**"
        extra=len(heading)+len(line)+1
        if current_lines and current_len+extra>3000:
            pages.append("\n".join(current_lines)); current_lines=[]; current_len=0; heading=f"**{root.replace('-', ' ').replace('_', ' ').title()}**"; extra=len(heading)+len(line)+1
        current_lines.extend([heading,line]); current_len+=extra; last_root=root
    if current_lines: pages.append("\n".join(current_lines))

    embeds=[]; total=len(commands_list)
    for index,body in enumerate(pages,start=1):
        e=cinnamon_embed(f"📖 Cinnamon Help","Browse Cinnamon's commands with the buttons below.",color=CINNAMON_BLUE,footer=cinnamon_page_footer("Help",index,len(pages)+1,f"{total} commands"))
        e.add_field(name="Commands",value=body,inline=False); embeds.append(e)
    guide=cinnamon_embed("🐾 Using Cinnamon","A quick guide to the bot.",color=CINNAMON_ORANGE,footer=cinnamon_page_footer("Help",len(embeds)+1,len(embeds)+1,"Guide"))
    guide.add_field(name="🚀 Start here",value="Run `/setup` in a new server. Then use `/help` whenever you need the command directory. Open the web control panel with `/dashboard`.",inline=False)
    guide.add_field(name="🎮 Everyday",value="Use `/pet`, `/mood status`, `/mood play`, `/rank`, `/economy shop`, `/quests daily`, and `/achievement list`. Cinnamon’s mood changes shop prices and fishing luck! Stories begin with `/cinnamon stories`; fishing starts with `/fishing start`.",inline=False)
    guide.add_field(name="🛡️ Admin",value="Moderation, logging, recovery, and configuration commands require the appropriate Discord permissions.",inline=False)
    guide.add_field(name="🧭 Web dashboard",value="`/dashboard` opens Cinnamon Control. Message Studio, analytics, activity logs, and every dashboard change are linked to the `cinnamon-dashboard-logs` audit channel created by `/setup`.",inline=False)
    guide.add_field(name="💾 Reset protection",value="Run `/economy snapshot` before a reset and restore it afterward if needed.",inline=False)
    embeds.append(guide)
    view=HelpPagesView(interaction.user.id,embeds,0)
    await interaction.response.send_message(embed=embeds[0],view=view,ephemeral=True)
    try:
        await send_log(interaction.guild.id, title="📖 Slash help opened", description=f"{interaction.user} ({interaction.user.id}) opened the slash-command guide.", interaction=interaction, category="dashboard")
    except Exception:
        log.exception("Could not log help command use")


# Explicit registration is required because help_cmd uses a reusable callback
# rather than the @bot.tree.command decorator.
try:
    bot.tree.add_command(app_commands.Command(name="help", description="Browse Cinnamon commands and dashboard guide", callback=help_cmd))
except Exception as help_registration_error:
    log.warning("Could not register slash /help command: %s", help_registration_error)


# --- Data status / recovery -------------------------------------------------

datastatus_group = app_commands.Group(name="datastatus", description="Check or recover Cinnamon's persisted data")


@datastatus_group.command(name="check", description="Check snapshot health and why Catnip actions are blocked")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def datastatus_check(interaction: discord.Interaction):
    # A remote Redis PING may take several seconds. Acknowledge the slash
    # command immediately, and keep diagnostics private to this admin.
    await interaction.response.defer(ephemeral=True)
    status = await storage_status()
    ready = status["transactions_ready"]
    icon = "✅" if ready else "⚠️"
    guild_warnings = sum(1 for g, _ in warnings_data.keys() if g == interaction.guild.id)
    hg_cog = bot.get_cog("HangryGamesCog")
    hg_game_num = hg_cog.game_counts.get(interaction.guild.id, 0) if hg_cog else 0

    embed = discord.Embed(
        title=f"{icon} Cinnamon storage & Catnip diagnostics",
        description="Read-only status. This command never changes balances or saved data.",
        color=discord.Color.green() if ready else discord.Color.orange(),
    )
    embed.add_field(name="Actual backend", value=status["backend"], inline=True)
    embed.add_field(name="Upstash configuration",
                    value=status["upstash_configuration"], inline=True)
    embed.add_field(
        name="Backend check",
        value=("Connected" if status["connected"] else "Unavailable")
              if status["durable"] else
              ("Local path appears writable" if status["connected"]
               else "Local path not writable"),
        inline=True,
    )
    embed.add_field(name="Persistent across Render redeploys",
                    value="Yes" if status["durable"] else "No guarantee",
                    inline=True)
    embed.add_field(name="Snapshot loaded",
                    value="Yes" if status["snapshot_ready"] else "No",
                    inline=True)
    embed.add_field(name="Snapshot state",
                    value=status["snapshot_status"], inline=True)
    embed.add_field(name="Confirmed Catnip actions",
                    value="✅ READY" if ready else "🔒 BLOCKED",
                    inline=True)
    embed.add_field(name="Unresolved transaction",
                    value="Yes — investigate before retrying"
                          if status["pending_transaction"] else "No",
                    inline=True)
    embed.add_field(name="This server's warnings",
                    value=str(guild_warnings), inline=True)
    embed.add_field(name="This server's Hangry Games count",
                    value=str(hg_game_num), inline=True)
    embed.add_field(name="What this means / how to fix",
                    value=status["detail"][:900], inline=False)
    if status["local_override"] and not status["durable"]:
        embed.add_field(
            name="⚠️ Unsafe local override",
            value="CINNAMON_ALLOW_LOCAL_ACTIONS is enabled. Do not use it on "
                  "Render's ephemeral filesystem; use durable storage instead.",
            inline=False,
        )
    embed.set_footer(text="Never share database tokens or secret environment values.")
    await interaction.followup.send(
        embed=cinnamon_polish_embed(embed), ephemeral=True)


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
    # The new Cinnamon Stuff log is recoverable even when its saved channel mapping vanished.
    social_recovered = await _cp_recover(guild)
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
        "cinnamon_people_restored": social_recovered["members"],
        "cinnamon_mood_restored": social_recovered["mood"],
        "cinnamon_snapshots_scanned": social_recovered["scanned"],
        "hangry_game_count": game_num,
        "hangry_wins_seen": wins,
        "economy_accounts": economy_restored + scan.get("economy_users_from_events", 0),
        "economy_snapshot_detail": snapshot_detail,
    })
    return scan

# --- Admin member-data backup export ----------------------------------------
def _mb_guild_map(mapping, guild_id):
    """Extract guild member records from tuple-keyed or nested maps."""
    out = {}
    for key, value in mapping.items():
        if isinstance(key, tuple) and len(key) >= 2 and int(key[0]) == int(guild_id):
            out[str(key[1])] = value
        elif str(key) == str(guild_id) and isinstance(value, dict):
            users = value.get("users", value)
            if isinstance(users, dict):
                out.update({str(uid): item for uid, item in users.items()})
    return out

def _mb_json_safe(value):
    if isinstance(value, dict): return {str(k): _mb_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)): return [_mb_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None: return value
    return str(value)

@bot.tree.command(name="member-backup", description="Export recoverable member data as a JSON file")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def member_backup_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None: return await interaction.response.send_message("🐾 Run this inside a server.", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    # Server recovery records only; private preferences, reminders, AI chats and tickets are excluded.
    sources = {
        "xp": _mb_guild_map(xp_data, guild.id),
        "catnip": _mb_guild_map(economy_balances, guild.id),
        "inventory": _mb_guild_map(economy_inventory, guild.id),
        "achievements": _mb_guild_map(achievement_data, guild.id),
        "warnings": _mb_guild_map(warnings_data, guild.id),
    }
    members = {}
    for source, records in sources.items():
        for uid, value in records.items(): members.setdefault(uid, {})[source] = _mb_json_safe(value)
    qguild = quest_data.get(guild.id, quest_data.get(str(guild.id), {}))
    if isinstance(qguild, dict) and isinstance(qguild.get("users", {}), dict):
        for uid, value in qguild.get("users", {}).items(): members.setdefault(str(uid), {})["quests"] = _mb_json_safe(value)
    social = advanced_features_data.get("cinnamon_social_v1", {}).get(str(guild.id), {})
    people = social.get("people", {}) if isinstance(social, dict) else {}
    if isinstance(people, dict):
        for uid, value in people.items(): members.setdefault(str(uid), {})["cinnamon_social"] = _mb_json_safe(value)
    names = {str(m.id): str(m) for m in guild.members}
    for uid, record in members.items(): record["username_at_export"] = names.get(uid, "not currently cached")
    payload = {
        "format": "cinnamon-member-backup", "version": 1, "guild_id": guild.id, "guild_name": guild.name,
        "exported_at_utc": _mb_datetime.datetime.now(_mb_datetime.timezone.utc).isoformat(),
        "member_records": members, "member_record_count": len(members),
        "included": list(sources) + ["quests", "cinnamon_social", "username_at_export"],
        "excluded_private_data": ["member preference memory", "private reminders", "AI conversations", "private correction tickets"],
        "note": "Only currently stored values are exported; this is not a guaranteed full restore file.",
    }
    raw = _mb_json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    stamp = int(_mb_datetime.datetime.now().timestamp())
    file = discord.File(_mb_io.BytesIO(raw), filename=f"cinnamon-members-{guild.id}-{stamp}.json")
    try:
        await interaction.channel.send(content=f"🧾 **Cinnamon member-data backup** — {len(members)} records. Keep this channel private.", file=file, allowed_mentions=discord.AllowedMentions.none())
        await send_log(guild.id, title="🧾 Member data backup exported", interaction=interaction, category="setup", fields=[("Records", str(len(members))), ("Channel", interaction.channel.mention)])
        await interaction.followup.send(f"Backup file sent to {interaction.channel.mention}. **{len(members)}** records exported.", ephemeral=True)
    except discord.HTTPException:
        await interaction.followup.send("❌ Discord couldn't upload the backup file. Check channel permissions and file-size limits.", ephemeral=True)
@bot.tree.command(name="recall", description="Scan configured logs and recover reconstructable Cinnamon data")
@app_commands.checks.has_permissions(administrator=True)
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
                           ("Hangry games found", str(result["hangry_game_count"])),
                           ("Cinnamon people restored", str(result["cinnamon_people_restored"])),
                           ("Mood restored", str(result["cinnamon_mood_restored"]))])
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
        f"• Hangry game counter: **#{result['hangry_game_count']}**; wins found: **{result['hangry_wins_seen']}**\n"
        f"• Cinnamon Stuff: **{result['cinnamon_people_restored']}** people and **{result['cinnamon_mood_restored']}** mood snapshots restored from **{result['cinnamon_snapshots_scanned']}** records\n\n"
        f"**Most common log types found**\n{title_summary}\n\n"
        f"**Channel scan issues**\n{errors}\n\n"
        "Recovery is idempotent for reconstructed counts and only uses absolute values or snapshots where possible. "
        "It cannot recreate deleted messages, AI chat memory, or state that was never logged. Review the counts above to see what was actually found.",
        ephemeral=True,
    )

@datastatus_group.command(name="recover", description="Scan configured logs and recover reconstructable Cinnamon data")
@app_commands.checks.has_permissions(administrator=True)
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

