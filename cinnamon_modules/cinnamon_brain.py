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
    channel_ok = bool(
        channel and guild_channel_send_allowed(interaction.guild, channel))
    allowed, reason = _cb_game_decision(
        gid, cancelled_at=social.get("last_unanswered_game_at", 0),
        auto_enabled=bool(social.get("auto_enabled")), channel_ok=channel_ok)
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
    }
    await interaction.response.send_message(
        "🧠 **Cinnamon Mind**\n"
        f"Independent activities: **{'ON' if _cb_independence_enabled(gid) else 'OFF'}**\n"
        f"Surprise games: **{'ON' if social.get('auto_enabled') else 'OFF'}**\n"
        f"Recent conversation: **{stats['messages']}** messages from **{stats['members']}** members "
        "over the past 30 minutes.\n"
        f"Decision: **{'READY' if allowed else 'WAIT'}** — {reason_labels[reason]}\n"
        "This is only a readiness check, not a promise to start a game immediately.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


def guild_channel_send_allowed(guild, channel):
    if channel.id in disabled_channels[guild.id]:
        return False
    me = guild.me
    return bool(me and channel.permissions_for(me).send_messages)


@_cb_group.command(name="independence", description="Admin: permit or pause Cinnamon's voluntary activities")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_mind_independence(interaction: discord.Interaction, enabled: bool):
    _cb_settings(interaction.guild.id)["independence_enabled"] = bool(enabled)
    await bd_save_data()
    await send_log(
        interaction.guild.id, title="🧠 Cinnamon independence changed",
        category="setup", fields=[
            ("Administrator", f"{interaction.user} ({interaction.user.id})"),
            ("Enabled", str(bool(enabled))),
        ])
    await interaction.response.send_message(
        ("🐱 I can take initiative again, but only when the server is ready for it!"
         if enabled else
         "🐈 Fine! No spontaneous games, questions or cameos until an admin re-enables me. "
         "I will still answer direct requests."),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


bot.tree.add_command(_cb_group)
