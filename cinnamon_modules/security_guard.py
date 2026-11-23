"""Security safeguards: configurable anti-spam and audit-log-based anti-nuke alerts."""
import collections as _sg_collections
import datetime as _sg_dt
import time as _sg_time

_SG_KEY = "cinnamon_security_guard_v1"
_SG_MESSAGE_TIMES = _sg_collections.defaultdict(list)
_SG_MESSAGE_COOLDOWNS = {}
_SG_NUKE_ACTIONS = _sg_collections.defaultdict(list)
_SG_NUKE_ALERTS = {}

def _sg_root(gid):
    root = advanced_features_data.setdefault(_SG_KEY, {})
    cfg = root.setdefault(str(int(gid)), {})
    cfg.setdefault("antispam_enabled", False)
    cfg.setdefault("antispam_threshold", 6)
    cfg.setdefault("antispam_window", 8)
    cfg.setdefault("antispam_timeout", 60)
    cfg.setdefault("antinuke_enabled", False)
    cfg.setdefault("antinuke_threshold", 3)
    cfg.setdefault("alert_channel_id", 0)
    return cfg

async def _sg_alert(guild, title, description, fields=()):
    cfg = _sg_root(guild.id)
    channel = guild.get_channel(int(cfg.get("alert_channel_id", 0) or 0))
    embed = discord.Embed(title=title, description=description, color=0xD97777,
                          timestamp=discord.utils.utcnow())
    for name, value in fields:
        embed.add_field(name=str(name), value=str(value)[:1000], inline=True)
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            return
        except discord.HTTPException:
            log.exception("Security alert channel delivery failed")
    try:
        await send_log(guild.id, title=title, description=description,
                       category="security", fields=list(fields))
    except Exception:
        log.exception("Security alert logging failed")

@bot.tree.command(name="security-alerts", description="Configure the private channel for Cinnamon security alerts")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(channel="Private channel for anti-spam and anti-nuke alerts; omit to disable")
async def security_alert_channel(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    cfg = _sg_root(interaction.guild.id)
    if channel and channel.permissions_for(interaction.guild.default_role).view_channel:
        return await cinnamon_send(interaction, "Security alert channels should be private to moderators.", ephemeral=True)
    old = int(cfg.get("alert_channel_id", 0) or 0)
    cfg["alert_channel_id"] = int(channel.id) if channel else 0
    if not await bd_save_data():
        cfg["alert_channel_id"] = old
        return await cinnamon_send(interaction, "Couldn't save security alert settings.", ephemeral=True)
    await cinnamon_send(interaction, "Security alerts will be sent to " + channel.mention + "." if channel else "Security alert channel disabled; alerts will use the configured moderation log.", ephemeral=True)

antispam_group = app_commands.Group(name="antispam", description="Configure message-rate protection")

@antispam_group.command(name="enable", description="Enable anti-spam protection")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def security_antispam_enable(interaction: discord.Interaction):
    cfg = _sg_root(interaction.guild.id)
    old = bool(cfg.get("antispam_enabled"))
    cfg["antispam_enabled"] = True
    if not await bd_save_data():
        cfg["antispam_enabled"] = old
        return await cinnamon_send(interaction, "Couldn't enable anti-spam.", ephemeral=True)
    await cinnamon_send(interaction, f"Anti-spam enabled: {cfg['antispam_threshold']} messages in {cfg['antispam_window']} seconds triggers a {cfg['antispam_timeout']}-second timeout.", ephemeral=True)

@antispam_group.command(name="disable", description="Disable anti-spam protection")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def security_antispam_disable(interaction: discord.Interaction):
    cfg = _sg_root(interaction.guild.id)
    old = bool(cfg.get("antispam_enabled"))
    cfg["antispam_enabled"] = False
    if not await bd_save_data():
        cfg["antispam_enabled"] = old
        return await cinnamon_send(interaction, "Couldn't disable anti-spam.", ephemeral=True)
    await cinnamon_send(interaction, "Anti-spam disabled.", ephemeral=True)

@antispam_group.command(name="configure", description="Set message threshold, time window and timeout duration")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def security_antispam_configure(interaction: discord.Interaction,
        threshold: app_commands.Range[int, 4, 15],
        window_seconds: app_commands.Range[int, 3, 30],
        timeout_seconds: app_commands.Range[int, 30, 3600]):
    cfg = _sg_root(interaction.guild.id)
    old = (cfg["antispam_threshold"], cfg["antispam_window"], cfg["antispam_timeout"])
    cfg["antispam_threshold"], cfg["antispam_window"], cfg["antispam_timeout"] = int(threshold), int(window_seconds), int(timeout_seconds)
    if not await bd_save_data():
        cfg["antispam_threshold"], cfg["antispam_window"], cfg["antispam_timeout"] = old
        return await cinnamon_send(interaction, "Couldn't save anti-spam configuration.", ephemeral=True)
    await cinnamon_send(interaction, f"Anti-spam configured: {threshold} messages in {window_seconds}s; timeout {timeout_seconds}s.", ephemeral=True)

bot.tree.add_command(antispam_group)

antinuke_group = app_commands.Group(name="antinuke", description="Detect bursts of destructive server administration actions")

@antinuke_group.command(name="enable", description="Enable audit-log-based anti-nuke alerts")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def security_antinuke_enable(interaction: discord.Interaction):
    if not interaction.guild.me.guild_permissions.view_audit_log:
        return await cinnamon_send(interaction, "Cinnamon needs View Audit Log to detect destructive admin bursts.", ephemeral=True)
    cfg = _sg_root(interaction.guild.id)
    old = bool(cfg.get("antinuke_enabled"))
    cfg["antinuke_enabled"] = True
    if not await bd_save_data():
        cfg["antinuke_enabled"] = old
        return await cinnamon_send(interaction, "Couldn't enable anti-nuke alerts.", ephemeral=True)
    await cinnamon_send(interaction, "Anti-nuke alerts enabled. Cinnamon will detect rapid destructive actions and alert moderators; it will not automatically punish administrators.", ephemeral=True)

@antinuke_group.command(name="disable", description="Disable anti-nuke alerts")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def security_antinuke_disable(interaction: discord.Interaction):
    cfg = _sg_root(interaction.guild.id)
    old = bool(cfg.get("antinuke_enabled"))
    cfg["antinuke_enabled"] = False
    if not await bd_save_data():
        cfg["antinuke_enabled"] = old
        return await cinnamon_send(interaction, "Couldn't disable anti-nuke alerts.", ephemeral=True)
    await cinnamon_send(interaction, "Anti-nuke alerts disabled.", ephemeral=True)

@antinuke_group.command(name="threshold", description="Set how many destructive actions trigger an alert")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def security_antinuke_threshold(interaction: discord.Interaction, actions: app_commands.Range[int, 2, 8]):
    cfg = _sg_root(interaction.guild.id)
    old = int(cfg.get("antinuke_threshold", 3))
    cfg["antinuke_threshold"] = int(actions)
    if not await bd_save_data():
        cfg["antinuke_threshold"] = old
        return await cinnamon_send(interaction, "Couldn't save anti-nuke threshold.", ephemeral=True)
    await cinnamon_send(interaction, f"Anti-nuke alert threshold set to {actions} destructive actions in 15 seconds.", ephemeral=True)

bot.tree.add_command(antinuke_group)

@bot.listen("on_message")
async def security_antispam_message(message):
    if not message.guild or message.author.bot:
        return
    cfg = _sg_root(message.guild.id)
    if not cfg.get("antispam_enabled"):
        return
    member = message.author
    if member.guild_permissions.administrator or member.guild_permissions.manage_messages or member.guild_permissions.moderate_members:
        return
    if not message.guild.me.guild_permissions.moderate_members:
        return
    now = _sg_time.monotonic()
    key = (message.guild.id, member.id)
    cooldown = _SG_MESSAGE_COOLDOWNS.get(key, 0)
    if now < cooldown:
        return
    window = max(3, int(cfg.get("antispam_window", 8)))
    times = [stamp for stamp in _SG_MESSAGE_TIMES[key] if now - stamp <= window]
    times.append(now)
    _SG_MESSAGE_TIMES[key] = times
    if len(times) < max(4, int(cfg.get("antispam_threshold", 6))):
        return
    duration = max(30, min(3600, int(cfg.get("antispam_timeout", 60))))
    _SG_MESSAGE_COOLDOWNS[key] = now + duration
    _SG_MESSAGE_TIMES[key].clear()
    try:
        await member.timeout(_sg_dt.timedelta(seconds=duration), reason="Cinnamon anti-spam: message-rate threshold exceeded")
    except discord.HTTPException:
        log.exception("Anti-spam timeout failed for member %s", member.id)
        return
    await _sg_alert(message.guild, "🚨 Anti-spam timeout",
        f"{member.mention} exceeded the configured message-rate threshold and was timed out.",
        fields=[("Member ID", member.id), ("Messages", len(times)),
                ("Window", f"{window} seconds"), ("Timeout", f"{duration} seconds")])

async def _security_audit_action(guild, target, action, label):
    cfg = _sg_root(guild.id)
    if not cfg.get("antinuke_enabled") or not guild.me.guild_permissions.view_audit_log:
        return
    target_id = getattr(target, "id", None)
    if target_id is None:
        return
    actor = None
    try:
        async for entry in guild.audit_logs(limit=5, action=action):
            if getattr(getattr(entry, "target", None), "id", None) == target_id:
                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if 0 <= age <= 15:
                    actor = entry.user
                    break
    except discord.Forbidden:
        return
    except discord.HTTPException:
        log.exception("Could not inspect audit log for anti-nuke")
        return
    if actor is None or actor.bot or actor.id == guild.owner_id or (bot.user and actor.id == bot.user.id):
        return
    now = _sg_time.monotonic()
    key = (guild.id, actor.id)
    recent = [stamp for stamp in _SG_NUKE_ACTIONS[key] if now - stamp <= 15]
    recent.append(now)
    _SG_NUKE_ACTIONS[key] = recent
    threshold = max(2, min(8, int(cfg.get("antinuke_threshold", 3))))
    last_alert = _SG_NUKE_ALERTS.get(key, 0)
    if len(recent) >= threshold and now - last_alert >= 300:
        _SG_NUKE_ALERTS[key] = now
        await _sg_alert(guild, "🚨 Possible server nuke activity",
            f"{actor.mention} performed {len(recent)} destructive administration actions within 15 seconds. Cinnamon has not automatically punished the actor; moderators should review the audit log.",
            fields=[("Actor ID", actor.id), ("Latest action", label), ("Actions in window", len(recent))])

@bot.listen("on_guild_channel_delete")
async def security_channel_delete(channel):
    await _security_audit_action(channel.guild, channel, discord.AuditLogAction.channel_delete, "Channel deleted")

@bot.listen("on_guild_role_delete")
async def security_role_delete(role):
    await _security_audit_action(role.guild, role, discord.AuditLogAction.role_delete, "Role deleted")

@bot.listen("on_member_ban")
async def security_member_ban(guild, user):
    await _security_audit_action(guild, user, discord.AuditLogAction.ban, "Member banned")

@bot.listen("on_member_remove")
async def security_member_remove(member):
    await _security_audit_action(member.guild, member, discord.AuditLogAction.kick, "Member removed")

@bot.listen("on_guild_role_update")
async def security_role_permission_change(before, after):
    dangerous = ("administrator", "manage_guild", "manage_roles", "manage_channels",
                 "ban_members", "kick_members", "manage_webhooks", "manage_messages")
    gained = [name for name in dangerous
              if getattr(after.permissions, name, False) and not getattr(before.permissions, name, False)]
    if gained:
        await _security_audit_action(after.guild, after, discord.AuditLogAction.role_update,
                                     "Dangerous role permissions granted: " + ", ".join(gained))

@bot.listen("on_webhooks_update")
async def security_webhook_change(channel):
    guild = channel.guild
    cfg = _sg_root(guild.id)
    if not cfg.get("antinuke_enabled") or not guild.me.guild_permissions.view_audit_log:
        return
    try:
        async for entry in guild.audit_logs(limit=5):
            if entry.action in (discord.AuditLogAction.webhook_create, discord.AuditLogAction.webhook_delete):
                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if 0 <= age <= 15:
                    target = entry.target
                    await _security_audit_action(guild, target, entry.action, "Webhook " + entry.action.name)
                    break
    except (discord.Forbidden, discord.HTTPException):
        return
