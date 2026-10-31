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
_PRIVATE = {"content", "before", "after", "message", "prompt", "response", "reply",
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
        metadata = {"description": str(description)[:200]} if description else {}
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
        await audit_event(guild_id, category or "general", title, actor_id=actor_id,
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
