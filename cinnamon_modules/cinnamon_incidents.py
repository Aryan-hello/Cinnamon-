"""Serious-conversation quiet hours and human-requested neutral incident review.

No independent punishment, no AI determination of guilt, and no automatic
incident transcript storage. A private, moderator-requested recap reads only
messages the moderator and Cinnamon can already access.
"""
import datetime as _cx_datetime
import time as _cx_time
from cinnamon_modules.brain_context import (
    context_looks_serious as _cx_looks_serious,
    conversation_tone as _cx_tone,
)

_CX_SERIOUS_UNTIL = {}  # guild ID -> Unix timestamp; no chat text or member ID
_CX_QUIET_SECONDS = 15 * 60


def _cx_alert_settings(gid):
    return advanced_features_data.setdefault("cinnamon_incident_alerts_v1", {}).setdefault(
        str(int(gid)), {"enabled": False, "channel_id": 0, "last_alert_at": 0})


async def _cx_alert_serious(guild, source_channel):
    """Send one content-free, rate-limited signal to an admin-chosen channel."""
    cfg = _cx_alert_settings(guild.id)
    if not cfg.get("enabled") or not int(cfg.get("channel_id", 0) or 0):
        return False
    now = _cx_time.time()
    if now - float(cfg.get("last_alert_at", 0) or 0) < 900:
        return False
    destination = guild.get_channel(int(cfg["channel_id"]))
    if (not isinstance(destination, discord.TextChannel)\n            or destination.permissions_for(guild.default_role).view_channel is not False\n            or not guild_channel_send_allowed(guild, destination)):
        return False
    prior = cfg.get("last_alert_at", 0)
    cfg["last_alert_at"] = now
    if not await bd_save_data():
        cfg["last_alert_at"] = prior
        return False
    try:
        await destination.send(
            "🛡️ **Cinnamon Brain · possible serious conversation**\\n"
            f"A cautious text signal was detected in {source_channel.mention} "
            f"(<t:{int(now)}:R>). This may be a false positive. "
            "No message content was copied, no member was pinged, and no one was judged. "
            "Use /cinnamon-incident review if a human moderator needs a neutral recap.",
            allowed_mentions=discord.AllowedMentions.none())
        return True
    except discord.HTTPException:
        return False


def _cx_observe(gid, text, *, now=None):
    now = _cx_time.time() if now is None else float(now)
    if _cx_looks_serious(text):
        _CX_SERIOUS_UNTIL[int(gid)] = now + _CX_QUIET_SECONDS
        return True
    return False


def _cx_serious(gid, *, now=None):
    now = _cx_time.time() if now is None else float(now)
    until = float(_CX_SERIOUS_UNTIL.get(int(gid), 0))
    if until <= now:
        _CX_SERIOUS_UNTIL.pop(int(gid), None)
        return False
    return True


_cx_group = app_commands.Group(
    name="cinnamon-incident",
    description="Non-judgmental moderation assistance for real human staff",
)


@_cx_group.command(name="review", description="Moderator: privately recap recent messages in a channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
async def cinnamon_incident_review(interaction: discord.Interaction,
                                   channel: discord.TextChannel | None = None):
    channel = channel or interaction.channel
    member = interaction.user
    if not channel or channel.guild.id != interaction.guild.id:
        return await interaction.response.send_message(
            "Choose a channel in this server.", ephemeral=True)
    human_perms = channel.permissions_for(member)
    bot_perms = channel.permissions_for(interaction.guild.me)
    if not (human_perms.view_channel and human_perms.read_message_history
            and bot_perms.view_channel and bot_perms.read_message_history):
        return await interaction.response.send_message(
            "Both you and Cinnamon need access to that channel's message history.",
            ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    cutoff = _cx_datetime.datetime.now(_cx_datetime.timezone.utc) - _cx_datetime.timedelta(minutes=30)
    observed = []
    try:
        async for message in channel.history(limit=50, oldest_first=False):
            if message.created_at < cutoff:
                break
            if message.author.bot or not message.content.strip():
                continue
            observed.append(message)
            if len(observed) >= 12:
                break
    except (discord.Forbidden, discord.HTTPException):
        return await interaction.followup.send(
            "I couldn't retrieve that channel's recent messages.",
            ephemeral=True)
    lines = []
    for message in reversed(observed):
        excerpt = discord.utils.escape_markdown(message.content.replace("\n", " ").strip()[:105])
        lines.append(f"<t:{int(message.created_at.timestamp())}:t> "
                     f"Member `{message.author.id}`: {excerpt}")
    await interaction.followup.send(
        "**🛡️ Cinnamon · Neutral recent-message recap**\n"
        f"Channel: {channel.mention} · last 30 minutes · up to 12 messages\n"
        "These are excerpts, **not** verified facts or conclusions. "
        "Human staff must review the original context before taking action.\n\n" +
        ("\n".join(lines)[:1450] if lines else "No recent human messages found."),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cx_group.command(name="policy", description="Explain how Cinnamon treats disagreements")
@app_commands.guild_only()
async def cinnamon_incident_policy(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🐾 I don't decide who's right or automatically punish people for arguing. "
        "I hold back on games when a discussion seems serious. "
        "Authorized human moderators can request a private chronological recap "
        "with /cinnamon-incident review. It is an aid, not a verdict.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cx_group.command(name="alerts", description="Admin: configure private serious-conversation signals")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_incident_alerts(interaction: discord.Interaction, enabled: bool,
                                  channel: discord.TextChannel | None = None):
    cfg = _cx_alert_settings(interaction.guild.id)
    if enabled and channel is None and not int(cfg.get("channel_id", 0) or 0):
        return await interaction.response.send_message(
            "Choose a private staff channel when enabling alerts for the first time.",
            ephemeral=True)
    chosen = channel or interaction.guild.get_channel(int(cfg.get("channel_id", 0) or 0))
    if enabled and (not chosen or chosen.guild.id != interaction.guild.id
                    or not guild_channel_send_allowed(interaction.guild, chosen)):
        return await interaction.response.send_message(
            "Cinnamon needs permission to send in a staff channel from this server.",
            ephemeral=True)
    old = dict(cfg)
    cfg["enabled"] = bool(enabled)
    if channel is not None:
        cfg["channel_id"] = int(channel.id)
    if not await bd_save_data():
        cfg.clear()
        cfg.update(old)
        return await interaction.response.send_message(
            "⚠️ Storage didn't confirm the alert settings. Nothing changed.", ephemeral=True)
    await interaction.response.send_message(
        ("🛡️ Content-free serious-topic signals are enabled" if enabled
         else "🔕 Serious-topic staff signals are disabled")
        + (f" in {chosen.mention}." if chosen else ".")
        + " Alerts are rate-limited to one per 15 minutes and never include message text.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


bot.tree.add_command(_cx_group)
