"""Cinnamon Brain v1: conservative, explainable decisions for voluntary activity.

This module is loaded into main.py's shared namespace. It NEVER calls Gemini
or executes moderation/economy actions. A private, bounded activity sample
helps Cinnamon decide when a surprise game would be welcome.
"""
from collections import deque as _cb_deque
import time as _cb_time

_CB_WINDOW_SECONDS = 30 * 60
_CB_FRESH_SECONDS = 10 * 60
_CB_MIN_MESSAGES = 6
_CB_MIN_MEMBERS = 2
_CB_EMPTY_GAME_BACKOFF = 6 * 3600
_CB_ACTIVITY = {}  # guild_id -> bounded deque of (timestamp, user_id), no text.


def _cb_settings(guild_id):
    """Shared persistent config; defaults preserve existing opt-in features."""
    return advanced_features_data.setdefault("cinnamon_brain_v1", {}).setdefault(
        str(guild_id), {"independence_enabled": True})


def _cb_independence_enabled(guild_id):
    return bool(_cb_settings(guild_id).get("independence_enabled", True))


def _cb_storage_available():
    """Unsolicited work must never use permissive defaults after a failed load."""
    store = globals().get("bd_store")
    return bool(store and store.ready and not store.pending_receipt)


def _cb_prune(guild_id, now):
    recent = _CB_ACTIVITY.setdefault(int(guild_id), _cb_deque(maxlen=120))
    while recent and (now - recent[0][0] > _CB_WINDOW_SECONDS):
        recent.popleft()
    return recent


def _cb_observe(guild_id, user_id, *, at=None):
    """Track HUMAN engagement signals only. No message text is retained."""
    now = _cb_time.time() if at is None else float(at)
    recent = _cb_prune(guild_id, now)
    # Rapid spam from the same sender should not make Cinnamon start a game.
    if any(uid == user_id and now - ts < 3 for ts, uid in list(recent)[-12:]):
        return
    recent.append((now, int(user_id)))


def _cb_activity_stats(guild_id, *, now=None):
    """Return safe aggregates, not identifiers or chat contents."""
    now = _cb_time.time() if now is None else float(now)
    recent = _cb_prune(guild_id, now)
    users = {uid for _, uid in recent}
    newest = recent[-1][0] if recent else 0
    return {"messages": len(recent), "members": len(users),
            "seconds_since_message": max(0, now - newest) if newest else None}


def _cb_game_decision(guild_id, *, now=None, cancelled_at=0,
                      auto_enabled=True, channel_ok=True):
    """Return (may_start, reason); all checks are deterministic and auditable."""
    now = _cb_time.time() if now is None else float(now)
    if not _cb_independence_enabled(guild_id):
        return False, "independence_disabled"
    if not auto_enabled:
        return False, "surprise_games_disabled"
    if not channel_ok:
        return False, "channel_unavailable"
    if cancelled_at and now - float(cancelled_at) < _CB_EMPTY_GAME_BACKOFF:
        return False, "cooldown_after_unanswered_game"
    stats = _cb_activity_stats(guild_id, now=now)
    if stats["messages"] < _CB_MIN_MESSAGES:
        return False, "not_enough_recent_conversation"
    if stats["members"] < _CB_MIN_MEMBERS:
        return False, "not_enough_people_engaged"
    if (stats["seconds_since_message"] is None or
            stats["seconds_since_message"] > _CB_FRESH_SECONDS):
        return False, "server_has_gone_quiet"
    return True, "active_conversation"


def _cb_game_eligibility(guild, channel, cog, *, now=None, own_lobby=None,
                         check_due=False, check_activity=True):
    """One runtime gate for diagnostics and every stage of a voluntary lobby."""
    now = _cb_time.time() if now is None else float(now)
    social = _cp_server(guild.id)
    if not _cb_independence_enabled(guild.id):
        return False, "independence_disabled"
    if not social.get("auto_enabled"):
        return False, "surprise_games_disabled"
    if not _cb_storage_available():
        return False, "storage_unavailable"
    if (not channel or int(social.get("auto_channel", 0) or 0) != channel.id
            or not guild_channel_send_allowed(guild, channel)):
        return False, "channel_unavailable"
    if not cog or not discord.utils.get(guild.roles, name="Hangry Games"):
        return False, "game_unavailable"
    # The cog indexes games by channel. Resolve those IDs through THIS guild
    # so a game elsewhere in the same guild also suppresses a surprise.
    for cid in set(getattr(cog, "active", {})) | set(cog.lobbies):
        if (own_lobby is not None and cid == channel.id
                and cog.lobbies.get(cid) is own_lobby
                and cid not in getattr(cog, "active", {})):
            continue
        if guild.get_channel(cid) is not None:
            return False, "another_game_running"
    for cid in _CP_LAUNCHING:
        if cid == channel.id and own_lobby is not None:
            continue
        if guild.get_channel(cid) is not None:
            return False, "another_game_running"
    if check_due and float(social.get("next_at", 0) or 0) > now:
        return False, "waiting_for_opportunity"
    if check_activity:
        return _cb_game_decision(
            guild.id, now=now,
            cancelled_at=social.get("last_unanswered_game_at", 0),
            auto_enabled=True, channel_ok=True)
    return True, "explicit_test"


_cb_group = app_commands.Group(
    name="cinnamon-mind",
    description="Cinnamon's independent activity controls and diagnostics",
)


@_cb_group.command(name="status", description="Admin: see whether Cinnamon feels a game is appropriate")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_mind_status(interaction: discord.Interaction):
    gid = interaction.guild.id
    social = _cp_server(gid)
    channel = interaction.guild.get_channel(int(social.get("auto_channel", 0) or 0))
    allowed, reason = _cb_game_eligibility(
        interaction.guild, channel, bot.get_cog("HangryGamesCog"), check_due=True)
    stats = _cb_activity_stats(gid)
    reason_labels = {
        "independence_disabled": "Independence is switched off by an admin.",
        "surprise_games_disabled": "Automatic games are disabled.",
        "channel_unavailable": "The game channel is missing, disabled or not writable.",
        "cooldown_after_unanswered_game": "Giving everyone space after an unanswered game.",
        "not_enough_recent_conversation": "Waiting for a little more conversation.",
        "not_enough_people_engaged": "Waiting for more people to participate.",
        "server_has_gone_quiet": "The conversation has gone quiet.",
        "active_conversation": "The server has enough activity for an occasional game.",
        "storage_unavailable": "Durable activity state is unavailable; staying quiet.",
        "game_unavailable": "The game system or opt-in notification role is missing.",
        "another_game_running": "A game or lobby is already active in this server.",
        "waiting_for_opportunity": "Waiting for the next activity opportunity.",
    }
    await interaction.response.send_message(
        "🧠 **Cinnamon Mind**\n"
        f"Independent activities: **{'ON' if _cb_independence_enabled(gid) else 'OFF'}**\n"
        f"Surprise games: **{'ON' if social.get('auto_enabled') else 'OFF'}**\n"
        f"Recent conversation: **{stats['messages']}** messages from **{stats['members']}** members "
        "over the past 30 minutes.\n"
        f"Conversational actions: **{'ON' if _ca_settings(gid).get('enabled') else 'OFF'}**\n"
        f"Storage: **{getattr(globals().get('bd_store'), 'status', 'unavailable')}**\n"
        f"Decision: **{'READY' if allowed else 'WAIT'}** — {reason_labels[reason]}\n"
        "This is only a readiness check, not a promise to start a game immediately.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


def guild_channel_send_allowed(guild, channel):
    if channel is None or channel.id in disabled_channels[guild.id]:
        return False
    me = guild.me
    if me is None:
        return False
    permissions = channel.permissions_for(me)
    return bool(permissions.view_channel and permissions.send_messages
                and permissions.embed_links)


@_cb_group.command(name="independence", description="Admin: permit or pause Cinnamon's voluntary activities")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_mind_independence(interaction: discord.Interaction, enabled: bool):
    await interaction.response.defer(ephemeral=True)
    _cb_settings(interaction.guild.id)["independence_enabled"] = bool(enabled)
    saved = await bd_save_data()
    if not saved:
        # An emergency OFF remains effective in this process. Enabling cannot
        # take effect when its boundaries could not be saved.
        _cb_settings(interaction.guild.id)["independence_enabled"] = False
        return await interaction.followup.send(
            "🐈 Independence is paused here. Storage did not confirm the setting; "
            "check diagnostics before restarting or re-enabling it.", ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())
    await send_log(
        interaction.guild.id, title="🧠 Cinnamon independence changed",
        category="setup", fields=[
            ("Administrator", f"{interaction.user} ({interaction.user.id})"),
            ("Enabled", str(bool(enabled))),
        ])
    await interaction.followup.send(
        ("🐱 I can take initiative again, but only when the server is ready for it!"
         if enabled else
         "🐈 Fine! No spontaneous games, questions or cameos until an admin re-enables me. "
         "I will still answer direct requests."),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@_cb_group.command(name="actions", description="Admin: enable or disable confirmed conversational actions")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_mind_actions(interaction: discord.Interaction, enabled: bool):
    await interaction.response.defer(ephemeral=True)
    settings = _ca_settings(interaction.guild.id)
    settings["enabled"] = bool(enabled)
    if not await bd_save_data():
        settings["enabled"] = False
        return await interaction.followup.send(
            "🐈 Conversational actions are OFF. Storage did not confirm the change.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    await send_log(interaction.guild.id, title="🧠 Conversational actions changed",
                   category="setup", fields=[
                       ("Administrator", str(interaction.user.id)),
                       ("Enabled", str(bool(enabled)))])
    await interaction.followup.send(
        "🐈 Confirmed conversational actions are " + ("ON" if enabled else "OFF") +
        ". Permissions and confirmation still apply to every request.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


bot.tree.add_command(_cb_group)
