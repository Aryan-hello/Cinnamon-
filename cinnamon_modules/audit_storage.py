"""Separate bounded Upstash activity store. Never touches the bot snapshot key."""
import asyncio
import datetime as dt
import json
import logging
import os
import uuid

_audit_log = logging.getLogger("cinnamon.audit")
_AUDIT_PREFIX = "cinnamon:activity:v1:"
_AUDIT_MAX = max(100, min(50000, int(os.getenv("CINNAMON_AUDIT_MAX_EVENTS", "10000"))))
_AUDIT_TTL = max(86400, min(31536000, int(os.getenv("CINNAMON_AUDIT_TTL_SECONDS", "15552000"))))
_AUDIT_SCRIPT = (
    "redis.call('LPUSH', KEYS[1], ARGV[1]); "
    "redis.call('LTRIM', KEYS[1], 0, tonumber(ARGV[2])-1); "
    "redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3])); "
    "return redis.call('LLEN', KEYS[1])"
)
_PRIVATE = {"content", "before", "after", "message", "reason", "details", "prompt", "response", "reply",
            "transcript", "conversation", "chat history", "attachment", "token", "secret"}


async def _redis(command):
    url = globals().get("BD_UPSTASH_URL") or os.getenv("UPSTASH_REDIS_REST_URL")
    token = globals().get("BD_UPSTASH_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        raise RuntimeError("Upstash audit credentials are not configured")
    import aiohttp
    timeout = aiohttp.ClientTimeout(total=4)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=command, headers={"Authorization": f"Bearer {token}"}) as response:
            response.raise_for_status()
            payload = await response.json()
            if not isinstance(payload, dict) or payload.get("error") or "result" not in payload:
                raise RuntimeError("Invalid Upstash response")
            return payload["result"]


def _safe_metadata(metadata):
    result = {}
    if not isinstance(metadata, dict):
        return result
    for key, value in list(metadata.items())[:20]:
        name = str(key).strip()[:48]
        low = name.lower()
        if not name or low in _PRIVATE or any(x in low for x in ("prompt", "response", "content", "secret", "token", "transcript")):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[name] = value[:240] if isinstance(value, str) else value
    return result


async def audit_event(guild_id, category, action, *, actor_id=None, target_id=None, channel_id=None, metadata=None):
    """Record a structured event; private message and AI text is excluded by default."""
    try:
        gid = int(guild_id)
        if gid <= 0:
            return False
        now = dt.datetime.now(dt.timezone.utc)
        event = {
            "event_id": uuid.uuid4().hex,
            "timestamp": now.isoformat(timespec="milliseconds"),
            "timestamp_unix": int(now.timestamp()),
            "guild_id": gid,
            "category": str(category or "general")[:40].lower(),
            "action": str(action or "activity")[:180],
            "actor_id": int(actor_id) if actor_id is not None else None,
            "target_id": int(target_id) if target_id is not None else None,
            "channel_id": int(channel_id) if channel_id is not None else None,
            "metadata": _safe_metadata(metadata),
            "schema_version": 1,
        }
        result = await _redis([
            "EVAL", _AUDIT_SCRIPT, 1, f"{_AUDIT_PREFIX}{gid}",
            json.dumps(event, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
            str(_AUDIT_MAX), str(_AUDIT_TTL),
        ])
        return isinstance(result, int) and not isinstance(result, bool) and result > 0
    except Exception as exc:
        _audit_log.warning("External audit append failed (%s)", type(exc).__name__)
        return False


async def audit_recent(guild_id, *, limit=20, category=None):
    gid = int(guild_id)
    limit = max(1, min(100, int(limit)))
    raw = await _redis(["LRANGE", f"{_AUDIT_PREFIX}{gid}", 0, min(_AUDIT_MAX - 1, limit * 5 - 1)])
    if not isinstance(raw, list):
        raise RuntimeError("Invalid audit history response")
    events = []
    for item in raw:
        try:
            event = json.loads(item) if isinstance(item, str) else None
            if not isinstance(event, dict) or int(event.get("guild_id", 0)) != gid:
                continue
            if category and str(event.get("category", "")).lower() != category.lower():
                continue
            events.append(event)
            if len(events) >= limit:
                break
        except (ValueError, TypeError):
            continue
    return events


async def audit_storage_status():
    try:
        pong = await _redis(["PING"])
        return {"configured": True, "connected": str(pong).upper() == "PONG",
                "max_events": _AUDIT_MAX, "retention_days": round(_AUDIT_TTL / 86400, 1)}
    except Exception as exc:
        return {"configured": bool(globals().get("BD_UPSTASH_URL") and globals().get("BD_UPSTASH_TOKEN")),
                "connected": False, "error": type(exc).__name__,
                "max_events": _AUDIT_MAX, "retention_days": round(_AUDIT_TTL / 86400, 1)}


# Wrap the established logger. Existing feature modules need no edits.
_original_send_log = send_log

async def send_log(guild_id, *, title, description="", color=discord.Color.blurple(),
                   interaction=None, fields=None, category=None):
    if guild_id is not None:
        actor_id = getattr(getattr(interaction, "user", None), "id", None)
        channel_id = getattr(getattr(interaction, "channel", None), "id", None)
        # Do not persist descriptions: some legacy log descriptions contain user-written text.
        metadata = {}
        for name, value in (fields or []):
            key = str(name).strip()
            low = key.lower()
            if low in _PRIVATE or any(x in low for x in ("content", "prompt", "response", "transcript", "secret", "token")):
                continue
            metadata[key[:48]] = str(value)[:200]
            if actor_id is None and low in {"user", "member", "actor", "moderator", "dashboard actor"}:
                import re
                match = re.search(r"\((\d{5,25})\)", str(value))
                if match:
                    actor_id = int(match.group(1))
        lowered = (str(title) + " " + str(description)).lower()
        inferred = category
        if inferred is None:
            rules = [
                (("economy", "catnip", "shop item", "income role", "cinnamon fed", "tuna"), "economy"),
                (("ai ", " ai", "gemini", "ai channel"), "ai"),
                (("achievement",), "achievements"),
                (("quest",), "quests"),
                (("level", "xp", "rank"), "levels"),
                (("giveaway", "poll"), "community"),
                (("hangry",), "hangrygames"),
                (("role added", "role removed", "reaction role", "role income"), "roles"),
                (("welcome", "goodbye", "setup", "configuration", "log channel"), "setup"),
                (("dashboard", "message studio", "web dashboard"), "dashboard"),
            ]
            inferred = next((label for needles, label in rules if any(n in lowered for n in needles)), "moderation")
        await audit_event(guild_id, inferred, title, actor_id=actor_id,
                          channel_id=channel_id, metadata=metadata)
    return await _original_send_log(guild_id, title=title, description=description, color=color,
                                    interaction=interaction, fields=fields, category=category)


@bot.tree.command(name="auditlogs", description="View recent external activity records for this server")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(category="Optional category filter", limit="How many records to show (1–20)")
async def auditlogs_cmd(interaction: discord.Interaction, category: str = None, limit: app_commands.Range[int, 1, 20] = 10):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        events = await audit_recent(interaction.guild.id, limit=limit, category=category)
        status = await audit_storage_status()
    except Exception as exc:
        return await interaction.followup.send(
            f"External activity history is unavailable ({type(exc).__name__}). Existing snapshots are untouched.",
            ephemeral=True)
    if not events:
        return await interaction.followup.send(
            "No matching external records found. Check the audit-store connection and whether the event occurred after this feature was enabled.",
            ephemeral=True)
    lines = []
    for event in events:
        stamp = str(event.get("timestamp", ""))[:19].replace("T", " ")
        actor = event.get("actor_id")
        who = f"<@{actor}>" if actor else "System/unknown"
        meta = event.get("metadata") or {}
        extra = " · ".join(f"{str(k)[:20]}: {str(v)[:55]}" for k, v in list(meta.items())[:2])
        lines.append(f"**{stamp} UTC** · {event.get('category','general')} · {who}\n{str(event.get('action','Activity'))[:100]}{(' — ' + extra) if extra else ''}")
    embed = discord.Embed(title="🧾 Cinnamon external activity",
                          description="\n\n".join(lines)[:3900], color=discord.Color.orange())
    embed.set_footer(text=f"Upstash audit history • {len(events)} record(s) • {status.get('retention_days','?')} day retention")
    await interaction.followup.send(embed=embed, ephemeral=True)


# Future AI modules should call audit_event(guild_id, "ai", "response_generated",
# actor_id=member_id, metadata={"model": GEMINI_MODEL, "memory_used": True}).
# Never pass prompts, replies, private memory, credentials, or full conversation text.


@bot.tree.command(name="auditstatus", description="Check Cinnamon's separate external activity store")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def auditstatus_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    status = await audit_storage_status()
    if status.get("connected"):
        message = (
            "✅ External activity storage is reachable.\\n"
            f"**Backend:** Upstash Redis\\n"
            f"**Per-server cap:** {status['max_events']:,} events\\n"
            f"**Retention:** {status['retention_days']} days\\n"
            "This store is separate from Cinnamon's bot snapshot."
        )
    else:
        message = (
            "⚠️ External activity storage is not reachable.\\n"
            f"**Configured:** {status.get('configured')}\\n"
            f"**Reason:** {status.get('error', 'Not configured')}\\n"
            "Discord logs and the bot snapshot are not modified by this check."
        )
    await interaction.followup.send(message, ephemeral=True)


# Command-wide audit hooks: record command names and outcomes, never message text.
async def _audit_prefix_command(ctx):
    if ctx.guild:
        await audit_event(ctx.guild.id, "commands", "prefix_command",
            actor_id=ctx.author.id, channel_id=ctx.channel.id,
            metadata={"command": ctx.command.qualified_name if ctx.command else "unknown",
                      "message_id": ctx.message.id})

async def _audit_prefix_error(ctx, error):
    if ctx.guild:
        await audit_event(ctx.guild.id, "errors", "prefix_command_error",
            actor_id=ctx.author.id, channel_id=ctx.channel.id,
            metadata={"command": ctx.command.qualified_name if ctx.command else "unknown",
                      "error_type": type(error).__name__})

async def _audit_interaction(interaction):
    if interaction.guild_id:
        data = getattr(interaction, "data", {}) or {}
        await audit_event(interaction.guild_id, "interactions", "discord_interaction",
            actor_id=interaction.user.id, channel_id=interaction.channel_id,
            metadata={"name": str(data.get("name") or data.get("custom_id") or interaction.type)[:120],
                      "interaction_id": interaction.id})

# Broad Discord audit listeners; metadata only, never message body/attachments.
async def _audit_listener_safe(gid, category, action, **kw):
    try:
        if gid: await audit_event(gid,category,action,**kw)
    except Exception: _audit_log.exception("Audit listener failed: %s",action)
async def _audit_msg_create(m):
    if m.guild and not m.author.bot: await _audit_listener_safe(m.guild.id,"messages","message_created",actor_id=m.author.id,channel_id=m.channel.id,metadata={"message_id":m.id,"attachment_count":len(m.attachments),"embed_count":len(m.embeds)})
async def _audit_msg_edit(b,a):
    if a.guild and not a.author.bot: await _audit_listener_safe(a.guild.id,"messages","message_edited",actor_id=a.author.id,channel_id=a.channel.id,metadata={"message_id":a.id})
async def _audit_msg_delete(m):
    if m.guild: await _audit_listener_safe(m.guild.id,"messages","message_deleted",actor_id=getattr(m.author,"id",None),channel_id=m.channel.id,metadata={"message_id":m.id})
async def _audit_bulk_delete(ms):
    groups={}
    for m in ms:
        if m.guild: groups[(m.guild.id,m.channel.id)]=groups.get((m.guild.id,m.channel.id),0)+1
    for (g,c),n in groups.items(): await _audit_listener_safe(g,"messages","bulk_delete",channel_id=c,metadata={"count":n})
async def _audit_join(m): await _audit_listener_safe(m.guild.id,"members","member_joined",target_id=m.id,metadata={"bot":m.bot})
async def _audit_leave(m): await _audit_listener_safe(m.guild.id,"members","member_left_or_removed",target_id=m.id,metadata={"bot":m.bot})
async def _audit_member_update(b,a):
    ch=[k for k in ("nick","roles","pending","timed_out_until") if getattr(b,k,None)!=getattr(a,k,None)]
    if ch: await _audit_listener_safe(a.guild.id,"members","member_updated",target_id=a.id,metadata={"changed":",".join(ch)})
async def _audit_ch_create(c):
    if c.guild: await _audit_listener_safe(c.guild.id,"channels","created",target_id=c.id,metadata={"name":c.name,"type":str(c.type)})
async def _audit_ch_delete(c):
    if c.guild: await _audit_listener_safe(c.guild.id,"channels","deleted",target_id=c.id,metadata={"name":c.name,"type":str(c.type)})
async def _audit_ch_update(b,a):
    ch=[k for k in ("name","topic","category_id","position","slowmode_delay","nsfw") if getattr(b,k,None)!=getattr(a,k,None)]
    if ch: await _audit_listener_safe(a.guild.id,"channels","updated",target_id=a.id,metadata={"changed":",".join(ch),"name":a.name})
async def _audit_role_create(r): await _audit_listener_safe(r.guild.id,"roles","created",target_id=r.id,metadata={"name":r.name})
async def _audit_role_delete(r): await _audit_listener_safe(r.guild.id,"roles","deleted",target_id=r.id,metadata={"name":r.name})
async def _audit_role_update(b,a):
    ch=[k for k in ("name","permissions","color","hoist","mentionable","position") if getattr(b,k,None)!=getattr(a,k,None)]
    if ch: await _audit_listener_safe(a.guild.id,"roles","updated",target_id=a.id,metadata={"changed":",".join(ch),"name":a.name})
async def _audit_voice(m,b,a):
    if b.channel!=a.channel or b.mute!=a.mute or b.deaf!=a.deaf: await _audit_listener_safe(m.guild.id,"voice","state_changed",actor_id=m.id,channel_id=getattr(a.channel or b.channel,"id",None),metadata={"from":getattr(b.channel,"id",None),"to":getattr(a.channel,"id",None),"mute":a.mute,"deaf":a.deaf})
async def _audit_guild_update(b,a):
    ch=[k for k in ("name","description","verification_level","explicit_content_filter","default_notifications") if getattr(b,k,None)!=getattr(a,k,None)]
    if ch: await _audit_listener_safe(a.id,"server","settings_updated",metadata={"changed":",".join(ch),"name":a.name})
async def _audit_react_add(r,u):
    if r.message.guild and not u.bot: await _audit_listener_safe(r.message.guild.id,"reactions","added",actor_id=u.id,channel_id=r.message.channel.id,metadata={"message_id":r.message.id,"emoji":str(r.emoji)[:80]})
async def _audit_react_remove(r,u):
    if r.message.guild and not u.bot: await _audit_listener_safe(r.message.guild.id,"reactions","removed",actor_id=u.id,channel_id=r.message.channel.id,metadata={"message_id":r.message.id,"emoji":str(r.emoji)[:80]})
async def _audit_thread_create(t):
    if t.guild: await _audit_listener_safe(t.guild.id,"threads","created",target_id=t.id,channel_id=t.parent_id,metadata={"name":t.name})
async def _audit_thread_delete(t):
    if t.guild: await _audit_listener_safe(t.guild.id,"threads","deleted",target_id=t.id,channel_id=t.parent_id,metadata={"name":t.name})
async def _audit_invite_create(i):
    if i.guild: await _audit_listener_safe(i.guild.id,"invites","created",actor_id=getattr(i.inviter,"id",None),channel_id=getattr(i.channel,"id",None),metadata={"code":i.code,"max_uses":i.max_uses})
async def _audit_invite_delete(i):
    if i.guild: await _audit_listener_safe(i.guild.id,"invites","deleted",channel_id=getattr(i.channel,"id",None),metadata={"code":i.code})
async def _audit_emojis(b,a): await _audit_listener_safe(a.id,"server","emoji_sticker_assets_updated",metadata={"emojis_before":len(b.emojis),"emojis_after":len(a.emojis),"stickers_before":len(b.stickers),"stickers_after":len(a.stickers)})
async def _audit_ban(g,u): await _audit_listener_safe(g.id,"moderation","member_banned",target_id=u.id,metadata={"user":str(u)[:100]})
async def _audit_unban(g,u): await _audit_listener_safe(g.id,"moderation","member_unbanned",target_id=u.id,metadata={"user":str(u)[:100]})
for _ev,_fn in (("on_message",_audit_msg_create),("on_message_edit",_audit_msg_edit),("on_message_delete",_audit_msg_delete),("on_bulk_message_delete",_audit_bulk_delete),("on_member_join",_audit_join),("on_member_remove",_audit_leave),("on_member_update",_audit_member_update),("on_guild_channel_create",_audit_ch_create),("on_guild_channel_delete",_audit_ch_delete),("on_guild_channel_update",_audit_ch_update),("on_guild_role_create",_audit_role_create),("on_guild_role_delete",_audit_role_delete),("on_guild_role_update",_audit_role_update),("on_voice_state_update",_audit_voice),("on_guild_update",_audit_guild_update),("on_reaction_add",_audit_react_add),("on_reaction_remove",_audit_react_remove),("on_thread_create",_audit_thread_create),("on_thread_delete",_audit_thread_delete),("on_invite_create",_audit_invite_create),("on_invite_delete",_audit_invite_delete),("on_guild_emojis_update",_audit_emojis),("on_member_ban",_audit_ban),("on_member_unban",_audit_unban)):
    bot.add_listener(_fn,_ev)


bot.add_listener(_audit_prefix_command, "on_command")
bot.add_listener(_audit_prefix_error, "on_command_error")
bot.add_listener(_audit_interaction, "on_interaction")
