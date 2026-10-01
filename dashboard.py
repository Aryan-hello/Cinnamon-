"""Cinnamon's server management dashboard.

Uses Discord OAuth for identity, re-checks guild access on each request, and
runs Discord operations on the bot's event loop. The bot's data persistence
functions are injected by main.py through configure_dashboard().
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import html
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from flask import Blueprint, abort, redirect, render_template_string, request, session, url_for

log = logging.getLogger("cinnamon.dashboard")
dashboard_bp = Blueprint("cinnamon_dashboard", __name__)
_bot = None
_state_provider = None
_tokens: dict[str, dict[str, Any]] = {}
BASE_URL = "https://discord.com/api/v10"
DEFAULT_REDIRECT = "https://cinnamon-c328.onrender.com/oauth/callback"


def configure_dashboard(bot, state_provider=None):
    """Attach the live bot and a callable returning main.py's current globals."""
    global _bot, _state_provider
    _bot = bot
    _state_provider = state_provider


def _state():
    return _state_provider() if callable(_state_provider) else {}


def _esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def _request_json(url, method="GET", data=None, headers=None):
    request_headers = {
        "User-Agent": "CinnamonDashboard/1.0 (https://cinnamon-c328.onrender.com)",
        "Accept": "application/json",
        **(headers or {}),
    }
    body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _token_exchange(data):
    client_id = os.environ["DISCORD_CLIENT_ID"]
    client_secret = os.environ["DISCORD_CLIENT_SECRET"]
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    return _request_json(
        f"{BASE_URL}/oauth2/token", method="POST", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}"},
    )


def _access_token(sid):
    record = _tokens.get(sid)
    if not record:
        abort(401)
    if record.get("expires_at", 0) < time.time() + 60:
        refresh = record.get("refresh_token")
        if not refresh:
            _tokens.pop(sid, None)
            abort(401)
        updated = _token_exchange({"grant_type": "refresh_token", "refresh_token": refresh})
        record["access_token"] = updated["access_token"]
        record["refresh_token"] = updated.get("refresh_token", refresh)
        record["expires_at"] = time.time() + int(updated.get("expires_in", 3600))
    return record["access_token"]


def _discord_get(sid, path):
    return _request_json(f"{BASE_URL}{path}", headers={"Authorization": "Bearer " + _access_token(sid)})


def _run_bot(coro, timeout=20):
    if not _bot or not _bot.is_ready():
        coro.close()
        raise RuntimeError("Cinnamon is not ready yet")
    loop = getattr(_bot, "loop", None)
    if not loop or not loop.is_running():
        coro.close()
        raise RuntimeError("Cinnamon event loop is unavailable")
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


def _save():
    save_fn = _state().get("bd_save_data")
    if not callable(save_fn):
        raise RuntimeError("Dashboard storage callback is not configured")
    _run_bot(save_fn())


def _audit(guild_id, actor, title, detail):
    send_log = _state().get("send_log")
    if callable(send_log):
        try:
            _run_bot(send_log(
                guild_id, title=title,
                description=detail[:900],
                fields=[("Dashboard actor", str(actor)[:100])],
            ))
        except Exception:
            log.exception("Dashboard audit log failed for guild %s", guild_id)


def _csrf():
    token = session.get("dashboard_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["dashboard_csrf"] = token
    return token


def _csrf_input():
    return f"<input type='hidden' name='csrf_token' value='{_esc(_csrf())}'>"


def _check_csrf():
    supplied = request.form.get("csrf_token", "")
    expected = session.get("dashboard_csrf", "")
    if not supplied or not expected or not secrets.compare_digest(supplied, expected):
        abort(400, "The form expired. Reload the page and try again.")


def _page(body, title="Cinnamon Dashboard", status=200):
    return render_template_string(
        """<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<meta name='color-scheme' content='light'><title>{{title}}</title><style>"""
        + STYLE + """</style></head><body>{{body|safe}}</body></html>""",
        title=title, body=body,
    ), status


STYLE = r"""
:root{--cream:#fbf2e4;--beige:#f7ebd9;--orange:#b96b2c;--orange2:#d88b45;--brown:#38251d;--taupe:#897765;--white:#fffdf9;--line:#e4d5c0;--green:#36734d;--red:#a53f32;--shadow:0 12px 34px #38251d0c}
*{box-sizing:border-box}body{margin:0;background:var(--cream);color:var(--brown);font:15px Inter,system-ui,-apple-system,Segoe UI,sans-serif}a{color:inherit;text-decoration:none}button,input,select,textarea{font:inherit}.layout{min-height:100vh;display:grid;grid-template-columns:248px minmax(0,1fr)}.side{background:#f3e5d0;border-right:1px solid var(--line);padding:20px 14px;display:flex;flex-direction:column;gap:18px}.brand{display:flex;align-items:center;gap:11px;font-size:19px;font-weight:850;padding:4px 8px}.mascot{width:45px;height:45px;object-fit:cover;border-radius:15px;border:2px solid #ead7b8;background:var(--beige)}.serverbox{padding:12px;background:#fff9f0;border:1px solid var(--line);border-radius:14px}.serverbox label{display:block;font-size:11px;color:var(--taupe);font-weight:800;text-transform:uppercase;letter-spacing:.08em;margin-bottom:7px}.serverbox select{width:100%;border:1px solid var(--line);border-radius:9px;background:white;padding:10px;color:var(--brown)}.navlabel{font-size:11px;color:var(--taupe);font-weight:800;letter-spacing:.1em;text-transform:uppercase;padding:0 10px;margin:5px 0}.nav{display:grid;gap:4px}.nav a{padding:10px 12px;border-radius:10px;color:#654d3d;font-weight:650;display:flex;gap:10px;align-items:center}.nav a.active,.nav a:hover{background:#e9d5b8;color:var(--brown)}.sidefoot{margin-top:auto;font-size:12px;color:var(--taupe);padding:8px}.main{min-width:0;padding:24px clamp(16px,3vw,38px) 40px;max-width:1500px;width:100%;margin:auto}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:24px}.crumb{font-size:13px;color:var(--taupe)}.profile{display:flex;align-items:center;gap:10px;font-weight:700}.avatar{width:34px;height:34px;border-radius:50%;background:var(--beige)}h1,h2,h3,p{margin-top:0}h1{font:700 clamp(27px,3vw,36px) Georgia,serif;margin-bottom:7px}h2{font:700 23px Georgia,serif;margin-bottom:12px}h3{font-size:16px;margin-bottom:8px}.muted{color:var(--taupe);line-height:1.55}.hero{background:linear-gradient(115deg,#f7e6ce,#fff7e9);border:1px solid var(--line);border-radius:22px;padding:25px;display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:20px;box-shadow:var(--shadow)}.hero p{margin:0;color:#78624e}.heroimg{width:100px;height:100px;object-fit:cover;border-radius:24px}.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:14px;margin:15px 0 22px}.card{grid-column:span 4;min-width:0;background:var(--white);border:1px solid var(--line);border-radius:17px;padding:18px;box-shadow:var(--shadow)}.card.half{grid-column:span 6}.card.full{grid-column:1/-1}.card.third{grid-column:span 4}.stat{font:700 30px Georgia,serif;margin:8px 0 2px}.statlabel{font-size:12px;color:var(--taupe);font-weight:750;text-transform:uppercase;letter-spacing:.06em}.iconbox{width:38px;height:38px;display:grid;place-items:center;background:#f7ead7;border-radius:12px;font-size:19px;margin-bottom:13px}.btn{display:inline-block;border:0;border-radius:10px;background:var(--orange);color:white;padding:10px 14px;font-weight:750;cursor:pointer}.btn:hover{background:#a75e26}.btn.secondary{background:#f0e2cd;color:var(--brown);border:1px solid var(--line)}.btn.danger{background:var(--red)}.btn.small{padding:7px 10px;font-size:13px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.formgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.field{display:grid;gap:6px;margin:10px 0}.field label{font-size:13px;font-weight:750}.field input,.field select,.field textarea{width:100%;border:1px solid var(--line);border-radius:10px;background:#fff;padding:11px 12px;color:var(--brown);min-width:0}.field textarea{min-height:92px;resize:vertical}.field small{font-size:12px;color:var(--taupe);line-height:1.4}.toggle{display:flex;gap:10px;align-items:flex-start;padding:12px 0;border-bottom:1px solid #f0e6d9}.toggle input{accent-color:var(--orange);width:17px;height:17px;margin-top:2px}.toggle span{display:grid;gap:3px}.toggle small{color:var(--taupe)}.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;min-width:460px;background:#fffdf9}th,td{text-align:left;padding:11px 13px;border-bottom:1px solid #f0e6d9;font-size:13px}th{color:var(--taupe);background:#fbf4e9;text-transform:uppercase;font-size:11px;letter-spacing:.05em}tr:last-child td{border-bottom:0}.pill{display:inline-block;border-radius:30px;padding:4px 9px;background:#efe4d2;color:#6b543e;font-size:11px;font-weight:800}.pill.good{background:#e3f0e5;color:var(--green)}.pill.warn{background:#f9e8d9;color:#99591f}.notice{padding:12px 14px;border-radius:12px;background:#f4e8d4;border:1px solid var(--line);margin-bottom:15px;color:#6e553e}.empty{padding:25px;text-align:center;color:var(--taupe)}.rule{height:1px;background:var(--line);margin:16px 0}.sectionhead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:23px 0 8px}.servericon{width:38px;height:38px;border-radius:12px;background:#f4e5cf;display:grid;place-items:center;font-weight:800;color:var(--orange);overflow:hidden;flex-shrink:0}.servericon img{width:100%;height:100%;object-fit:cover}.serverlist{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}.serveritem{background:var(--white);border:1px solid var(--line);padding:15px;border-radius:15px;display:flex;align-items:center;gap:12px}.serveritem .grow{flex:1;min-width:0}.serveritem h3{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:0 0 4px}.mobilebrand{display:none}.footer{font-size:12px;color:var(--taupe);margin-top:25px}.dangerzone{border-color:#e8c6be}.dangerzone h3{color:var(--red)}@media(max-width:900px){.layout{grid-template-columns:205px minmax(0,1fr)}.card{grid-column:span 6}.card.third{grid-column:span 6}}@media(max-width:650px){.layout{display:block}.side{position:sticky;top:0;z-index:4;border-right:0;border-bottom:1px solid var(--line);padding:9px 12px;display:block}.brand{padding:2px 4px;margin-bottom:8px}.brand .mascot{width:35px;height:35px}.serverbox{padding:8px;margin-bottom:7px}.serverbox label{display:none}.serverbox select{padding:8px}.navlabel{display:none}.nav{display:flex;overflow-x:auto;gap:5px;padding-bottom:3px}.nav a{white-space:nowrap;padding:8px 10px;font-size:12px}.sidefoot{display:none}.main{padding:17px 13px 30px}.top{margin-bottom:16px}.hero{padding:18px}.heroimg{width:68px;height:68px}.card,.card.half,.card.third{grid-column:1/-1}.formgrid{grid-template-columns:1fr}h1{font-size:28px}.stat{font-size:26px}}
/* Extra mobile ergonomics: safe-area spacing, touch targets, readable forms, and clear focus. */
html{scroll-padding-top:150px;-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{overflow-x:hidden}
button,a,select,input[type=checkbox]{touch-action:manipulation}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid var(--orange2);outline-offset:2px}
@media(max-width:650px){
  .side{padding-top:max(8px,env(safe-area-inset-top));padding-left:max(11px,env(safe-area-inset-left));padding-right:max(11px,env(safe-area-inset-right));}
  .nav{scrollbar-width:thin;overscroll-behavior-x:contain;-webkit-overflow-scrolling:touch;scroll-snap-type:x proximity}
  .nav a{flex:0 0 auto;min-height:40px;scroll-snap-align:start}
  .serverbox select{min-height:42px;font-size:14px}
  .main{padding-left:max(12px,env(safe-area-inset-left));padding-right:max(12px,env(safe-area-inset-right));}
  .top{align-items:flex-start;flex-wrap:wrap}
  .crumb{font-size:12px}
  .profile{font-size:13px;max-width:100%;flex-wrap:wrap;justify-content:flex-end}
  .hero{align-items:center;min-width:0}
  .hero>div{min-width:0}
  .hero p{font-size:14px}
  .heroimg{flex:0 0 58px;width:58px;height:58px;border-radius:17px}
  .card{padding:16px;border-radius:15px}
  .actions{gap:9px}
  .actions .btn{min-height:42px;display:inline-flex;align-items:center;justify-content:center;flex:1 1 125px;text-align:center}
  .field input,.field select,.field textarea{font-size:16px;min-height:44px}
  .field textarea{min-height:100px}
  .toggle{min-height:52px;align-items:center}
  .toggle input{width:20px;height:20px;flex:0 0 20px}
  .tablewrap{max-width:100%;overscroll-behavior-x:contain;-webkit-overflow-scrolling:touch}
  th,td{padding:10px 11px}
  .serverlist{grid-template-columns:minmax(0,1fr)}
}
@media(max-width:380px){
  .brand{font-size:17px}
  .top{gap:8px}
  .profile{gap:6px}
  .hero{padding:14px;gap:10px}
  h1{font-size:25px}
  h2{font-size:21px}
  .card{padding:14px}
  .nav a{font-size:11px;padding:8px 9px}
}
@media(orientation:landscape) and (max-height:500px) and (max-width:900px){
  .side{position:relative}
}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;transition-duration:.01ms!important}}

"""


def _header():
    return "<header class='top'><div class='crumb'>Cinnamon / Server dashboard</div><div class='profile'>" + _esc(session.get("display_name", "Discord user")) + " <a class='btn secondary small' href='/logout'>Log out</a></div></header>"


def _nav(guild_id, tab):
    items = [("overview", "⌂", "Overview"), ("moderation", "🛡", "Moderation"), ("engagement", "✦", "Engagement"), ("economy", "🌿", "Catnip Economy"), ("community", "☻", "Community"), ("system", "⚙", "Settings & Logs")]
    return "<div class='navlabel'>Workspace</div><nav class='nav'>" + "".join(
        f"<a class='{'active' if tab == key else ''}' href='/dashboard?guild_id={guild_id}&tab={key}'><span>{ico}</span>{label}</a>" for key, ico, label in items
    ) + "</nav>"


def _shell(guild, guilds, tab, body, notice=None):
    gid = guild.id
    options = []
    for item in guilds:
        if str(item.get("id")) in {str(g.id) for g in (_bot.guilds if _bot else [])} and (item.get("owner") or (int(item.get("permissions", "0")) & (0x8 | 0x20))):
            selected = " selected" if str(item.get("id")) == str(gid) else ""
            options.append(f"<option value='{_esc(item['id'])}'{selected}>{_esc(item.get('name','Server'))}</option>")
    select = "<form action='/dashboard' method='get'><input type='hidden' name='tab' value='overview'><div class='serverbox'><label>Selected server</label><select name='guild_id' onchange='this.form.submit()'>" + "".join(options) + "</select></div></form>"
    side = "<aside class='side'><div class='brand'><img class='mascot' src='/static/cinnamon_mascot.jpg' alt=''><span>Cinnamon <span style='font-weight:500;color:var(--taupe)'>Control</span></span></div>" + select + _nav(gid, tab) + "<div class='sidefoot'>Cozy controls, careful paws. 🐾<br>Changes are logged where configured.</div></aside>"
    notice_html = f"<div class='notice'>{_esc(notice)}</div>" if notice else ""
    title = f"{guild.name} • Cinnamon Dashboard"
    return _page("<div class='layout'>" + side + "<main class='main'>" + _header() + notice_html + body + "<div class='footer'>Cinnamon • Server controls are permission-checked. Keep your Discord account secure.</div></main></div>", title)


def _channel_select(guild, name, selected=None, allow_none=True):
    channels = [c for c in guild.text_channels if c.permissions_for(guild.me).view_channel] if guild.me else guild.text_channels
    opts = ["<option value=''>— Not set —</option>"] if allow_none else []
    for ch in channels:
        sel = " selected" if selected is not None and int(selected) == ch.id else ""
        opts.append(f"<option value='{ch.id}'{sel}>#{_esc(ch.name)}</option>")
    return f"<select name='{_esc(name)}'>" + "".join(opts) + "</select>"


def _role_select(guild, name, selected=None, allow_none=True):
    roles = sorted([r for r in guild.roles if not r.is_default() and not r.managed], key=lambda r: r.position, reverse=True)
    opts = ["<option value=''>— Not set —</option>"] if allow_none else []
    for role in roles:
        sel = " selected" if selected is not None and int(selected) == role.id else ""
        opts.append(f"<option value='{role.id}'{sel}>@{_esc(role.name)}</option>")
    return f"<select name='{_esc(name)}'>" + "".join(opts) + "</select>"


def _form(guild_id, action, content, button="Save changes", danger=False):
    style = " danger" if danger else ""
    return f"<form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{guild_id}'><input type='hidden' name='action' value='{_esc(action)}'>{content}<div class='actions'><button class='btn{style}' type='submit'>{_esc(button)}</button></div></form>"


def _get_access(sid, guilds, guild_id):
    guild_item = next((g for g in guilds if str(g.get("id")) == str(guild_id)), None)
    guild = _bot.get_guild(int(guild_id)) if _bot and str(guild_id).isdigit() else None
    if not guild_item or not guild or str(guild.id) not in {str(g.get("id")) for g in guilds}:
        abort(404)
    perms = int(guild_item.get("permissions", "0"))
    oauth_allowed = bool(guild_item.get("owner") or (perms & (0x8 | 0x20)))
    if not oauth_allowed:
        abort(403)
    uid = int(_tokens[sid]["user"]["id"])
    async def verify():
        if uid == guild.owner_id:
            return True
        try:
            member = guild.get_member(uid) or await guild.fetch_member(uid)
        except Exception:
            return False
        return bool(member.guild_permissions.administrator or member.guild_permissions.manage_guild)
    if not _run_bot(verify()):
        abort(403)
    return guild, guild_item


def _dashboard_context():
    sid = session.get("dash_sid")
    if not sid or sid not in _tokens:
        return None
    guilds = _discord_get(sid, "/users/@me/guilds")
    bot_ids = {str(g.id) for g in (_bot.guilds if _bot else [])}
    eligible = [g for g in guilds if str(g.get("id")) in bot_ids and (g.get("owner") or (int(g.get("permissions", "0")) & (0x8 | 0x20)))]
    return sid, guilds, eligible


def _count(mapping, gid):
    return sum(1 for key in mapping if isinstance(key, tuple) and key[0] == gid)


def _overview(guild, state):
    gid = guild.id
    member_count = guild.member_count or len(guild.members)
    stats = [("Members", member_count, "👥"), ("Channels", len(guild.channels), "#"), ("Roles", len(guild.roles), "♙"), ("Commands", len(_bot.tree.get_commands()) if _bot else 0, "⌘")]
    cards = "".join(f"<article class='card third'><div class='iconbox'>{ico}</div><div class='statlabel'>{label}</div><div class='stat'>{int(value):,}</div></article>" for label,value,ico in stats)
    flags = [
        ("Welcome messages", bool(state.get("welcome_config", {}).get(gid)), "community"),
        ("Goodbye messages", bool(state.get("goodbye_config", {}).get(gid)), "community"),
        ("AutoMod", bool(state.get("automod_config", {}).get(gid)), "moderation"),
        ("Anti-raid alerts", bool(state.get("antiraid_config", {}).get(gid, {}).get("enabled")), "moderation"),
        ("AI channel", bool(state.get("ai_channels", {}).get(gid)), "community"),
        ("Daily / weekly quests", bool(state.get("quest_config", {}).get(gid, {}).get("enabled")), "engagement"),
        ("Achievements", bool(state.get("achievement_config", {}).get(gid, {}).get("enabled")), "engagement"),
    ]
    status_cards = "".join(f"<div class='toggle'><span><b>{_esc(name)}</b><small>{'Configured / enabled' if enabled else 'Not configured / disabled'}</small></span><span class='pill {'good' if enabled else 'warn'}'>{'ON' if enabled else 'OFF'}</span></div>" for name,enabled,_ in flags)
    body = f"<section class='hero'><div><h1>Welcome to { _esc(guild.name) }</h1><p>Here's a quick look at your server and Cinnamon's connected systems.</p><div class='actions'><a class='btn' href='/dashboard?guild_id={gid}&tab=moderation'>Manage moderation</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=system'>Configure Cinnamon</a></div></div><img class='heroimg' src='/static/cinnamon_mascot.jpg' alt='Cinnamon'></section><div class='grid'>{cards}<article class='card half'><h2>Feature status</h2>{status_cards}</article><article class='card half'><h2>Cinnamon health</h2><p class='muted'>Live connection status from the running bot.</p><div class='toggle'><b>Gateway</b><span class='pill good'>Online</span></div><div class='toggle'><b>Storage</b><span class='pill'>{'Upstash configured' if state.get('BD_UPSTASH_URL') and state.get('BD_UPSTASH_TOKEN') else 'Local file mode'}</span></div><div class='toggle'><b>Latency</b><span>{round(_bot.latency*1000)} ms</span></div><p class='muted'>For deeper diagnostics, use <b>/diagnostics</b> in Discord.</p></article></div>"
    return body


def _moderation(guild, state):
    gid=guild.id
    automod=state.get("automod_config",{}).get(gid,{})
    antiraid=state.get("antiraid_config",{}).get(gid,{})
    warns=state.get("warnings_data",{})
    warning_count=sum(len(v) for k,v in warns.items() if isinstance(k,tuple) and k[0]==gid)
    modform="<div class='formgrid'><div class='field'><label>Member ID</label><input name='member_id' inputmode='numeric' required pattern='[0-9]{15,22}' placeholder='Discord user ID'></div><div class='field'><label>Action</label><select name='mod_action'><option value='timeout'>Timeout</option><option value='kick'>Kick</option><option value='ban'>Ban</option></select></div><div class='field'><label>Timeout duration (minutes)</label><input name='duration' type='number' min='1' max='40320' value='60'></div><div class='field'><label>Reason</label><input name='reason' maxlength='400' placeholder='Reason for moderation action'></div></div><p class='muted'>Actions require the matching Discord permission and bot role hierarchy. Bans and kicks cannot be undone from this page.</p>"
    modcard="<article class='card half'><h2>Member moderation</h2><p class='muted'>Apply a Discord moderation action by member ID.</p>"+_form(gid,"moderate",modform,"Apply action",True)+"</article>"
    words="\n".join(str(w) for w in automod.get("words",[]))
    automodform="<div class='field'><label>Banned words or phrases</label><textarea name='words' maxlength='3000' placeholder='One per line'>"+_esc(words)+"</textarea><small>One phrase per line; maximum 50 entries, each up to 100 characters.</small></div>"
    for key,label,desc in [("spam","Spam detection","Remove rapid repeated messages."),("mentions","Mass mention protection","Flag messages over the mention threshold."),("invites","Discord invite protection","Remove Discord invite links.")]:
        automodform+=f"<label class='toggle'><input type='checkbox' name='{key}' {'checked' if automod.get(key) else ''}><span><b>{label}</b><small>{desc}</small></span></label>"
    automodform+="<div class='field'><label>Mention threshold</label><input name='mention_threshold' type='number' min='2' max='20' value='"+_esc(automod.get("mention_threshold",5))+"'></div>"
    automodcard="<article class='card half'><h2>AutoMod</h2><p class='muted'>These options map to Cinnamon's existing AutoMod settings.</p>"+_form(gid,"automod",automodform)+"</article>"
    raidform="<label class='toggle'><input type='checkbox' name='enabled' "+("checked" if antiraid.get("enabled") else "")+"><span><b>Enable join-spike alerts</b><small>Alerts only; does not automatically kick or lock the server.</small></span></label><div class='formgrid'><div class='field'><label>Join threshold</label><input type='number' name='threshold' min='2' max='100' value='"+_esc(antiraid.get("threshold",5))+"'></div><div class='field'><label>Time window (seconds)</label><input type='number' name='window' min='2' max='120' value='"+_esc(antiraid.get("window",10))+"'></div></div>"
    raidcard="<article class='card full'><h2>Anti-raid alerts</h2>"+_form(gid,"antiraid",raidform)+"</article>"
    body=f"<h1>Moderation & safety</h1><p class='muted'>Manage member actions, message filters and join-spike alerts.</p><div class='grid'><article class='card third'><div class='statlabel'>Recorded warnings</div><div class='stat'>{warning_count:,}</div></article><article class='card third'><div class='statlabel'>AutoMod</div><div class='stat'><span class='pill {'good' if automod else 'warn'}'>{'Configured' if automod else 'Off'}</span></div></article><article class='card third'><div class='statlabel'>Anti-raid</div><div class='stat'><span class='pill {'good' if antiraid.get('enabled') else 'warn'}'>{'Enabled' if antiraid.get('enabled') else 'Disabled'}</span></div></article>{modcard}{automodcard}{raidcard}</div>"
    return body


def _engagement(guild,state):
    gid=guild.id; xp=state.get("xp_data",{}); levels=state.get("level_roles",{}).get(gid,{})
    top=sorted(((uid,val) for (g,uid),val in xp.items() if g==gid),key=lambda x:x[1],reverse=True)[:10]
    rows="".join(f"<tr><td>{i}</td><td>{_esc((guild.get_member(uid).display_name if guild.get_member(uid) else 'Member '+str(uid)))}</td><td>{int(val):,}</td><td>{int(state.get('level_from_xp',lambda n:0)(val))}</td></tr>" for i,(uid,val) in enumerate(top,1)) or "<tr><td colspan='4'>No XP data yet.</td></tr>"
    role_rows="".join(f"<tr><td>{level}</td><td>{_esc((guild.get_role(rid).name if guild.get_role(rid) else 'Missing role'))}</td><td><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='levelrole_remove'><input type='hidden' name='level' value='{level}'><button class='btn secondary small' type='submit'>Remove</button></form></td></tr>" for level,rid in sorted(levels.items()) if str(level).isdigit()) or "<tr><td colspan='3'>No level roles configured.</td></tr>"
    formcontent="<div class='formgrid'><div class='field'><label>Level (1–100)</label><input name='level' type='number' min='1' max='100' required></div><div class='field'><label>Reward role</label>"+_role_select(guild,"role_id",allow_none=False)+"</div></div>"
    cfg=state.get("quest_config",{}).get(gid,{})
    qcount=len(state.get("quest_definitions",{}).get("daily",{}))+len(state.get("quest_definitions",{}).get("weekly",{}))
    qp=sum(v for (g,_),v in state.get("quest_points",{}).items() if g==gid)
    ach=state.get("achievement_config",{}).get(gid,{})
    body=f"<h1>Engagement</h1><p class='muted'>Level progression, daily and weekly quests, and achievements.</p><div class='grid'><article class='card third'><div class='statlabel'>Members with XP</div><div class='stat'>{_count(xp,gid):,}</div></article><article class='card third'><div class='statlabel'>Quest points held</div><div class='stat'>{qp:,}</div></article><article class='card third'><div class='statlabel'>Quest definitions</div><div class='stat'>{qcount:,}</div></article><article class='card half'><h2>XP leaderboard</h2><div class='tablewrap'><table><thead><tr><th>#</th><th>Member</th><th>XP</th><th>Level</th></tr></thead><tbody>{rows}</tbody></table></div></article><article class='card half'><h2>Level rewards</h2><div class='tablewrap'><table><thead><tr><th>Level</th><th>Role</th><th></th></tr></thead><tbody>{role_rows}</tbody></table></div><div class='rule'></div>"+_form(gid,"levelrole_add",formcontent,"Add level reward")+f"</article><article class='card half'><h2>Daily & weekly quests</h2><p class='muted'>Status: <span class='pill {'good' if cfg.get('enabled') else 'warn'}'>{'Enabled' if cfg.get('enabled') else 'Not enabled'}</span></p><p class='muted'>Use <b>/quests setup</b> in Discord to initialize or repair the quest cycle. Quest editing is handled by the existing bot commands.</p></article><article class='card half'><h2>Achievements</h2><p class='muted'>Status: <span class='pill {'good' if ach.get('enabled') else 'warn'}'>{'Enabled' if ach.get('enabled') else 'Not enabled'}</span></p><p class='muted'>Use <b>/achievement setup</b> to configure achievement rewards and definitions.</p></article></div>"
    return body


def _economy(guild,state):
    gid=guild.id; balances=state.get("economy_balances",{}); inventory=state.get("economy_inventory",{})
    entries=sorted(((uid,val) for (g,uid),val in balances.items() if g==gid),key=lambda x:x[1],reverse=True)[:10]
    rows="".join(f"<tr><td>{i}</td><td>{_esc(guild.get_member(uid).display_name if guild.get_member(uid) else 'Member '+str(uid))}</td><td>{int(val):,} 🌿</td><td>{sum(int(q) for q in inventory.get((gid,uid),{}).values())}</td></tr>" for i,(uid,val) in enumerate(entries,1)) or "<tr><td colspan='4'>No economy balances yet.</td></tr>"
    total=sum(int(v) for (g,_),v in balances.items() if g==gid)
    users=_count(balances,gid)
    shop=state.get("ECONOMY_ITEMS",{})
    items="".join(f"<tr><td>{_esc(item.get('emoji','🐾'))} {_esc(item.get('name',key))}</td><td>{int(item.get('price',0)):,} Catnip</td><td>{_esc(item.get('description',''))}</td></tr>" for key,item in shop.items()) or "<tr><td colspan='3'>No shop items available.</td></tr>"
    body=f"<h1>Catnip economy</h1><p class='muted'>A read-only view of Cinnamon's server economy and shop.</p><div class='grid'><article class='card third'><div class='statlabel'>Economy members</div><div class='stat'>{users:,}</div></article><article class='card third'><div class='statlabel'>Total Catnip in circulation</div><div class='stat'>{total:,} 🌿</div></article><article class='card third'><div class='statlabel'>Shop items</div><div class='stat'>{len(shop)}</div></article><article class='card half'><h2>Top balances</h2><div class='tablewrap'><table><thead><tr><th>#</th><th>Member</th><th>Balance</th><th>Items</th></tr></thead><tbody>{rows}</tbody></table></div></article><article class='card half'><h2>Economy configuration</h2><p class='muted'>Daily reward: <b>{int(state.get('ECONOMY_DAILY_REWARD',150)):,} Catnip</b></p><p class='muted'>Work range: <b>{int(state.get('ECONOMY_WORK_MIN',50)):,}–{int(state.get('ECONOMY_WORK_MAX',150)):,}</b></p><p class='muted'>Work cooldown: <b>{int(state.get('ECONOMY_WORK_COOLDOWN',600))//60} minutes</b></p><p class='muted'>Economy logs: {_esc(guild.get_channel(state.get('economy_log_channels',{}).get(gid)).mention if guild.get_channel(state.get('economy_log_channels',{}).get(gid)) else 'Not configured')}</p><p class='muted'>Balances and shop transactions remain managed by Cinnamon's Discord commands to preserve its existing reward and quest accounting.</p></article><article class='card full'><h2>Catnip shop</h2><div class='tablewrap'><table><thead><tr><th>Item</th><th>Price</th><th>Description</th></tr></thead><tbody>{items}</tbody></table></div></article></div>"
    return body


def _community(guild,state):
    gid=guild.id; welcome=state.get("welcome_config",{}).get(gid,{}); goodbye=state.get("goodbye_config",{}).get(gid,{})
    ai=state.get("ai_channels",{}).get(gid); logs=state.get("log_channels",{}).get(gid)
    def message_form(kind,cfg,action):
        ch=_channel_select(guild,"channel_id",cfg.get("channel_id"))
        msg=_esc(cfg.get("message", ""))
        fields=f"<div class='field'><label>Post in</label>{ch}</div><div class='field'><label>Message template</label><textarea name='message' maxlength='800' placeholder='Use {{member}} and {{server}}'>{msg}</textarea><small>Supported placeholders: {{member}} and {{server}}.</small></div>"
        return f"<article class='card half'><h2>{kind}</h2><p class='muted'>Current: {_esc(guild.get_channel(cfg.get('channel_id')).mention if cfg.get('channel_id') and guild.get_channel(cfg.get('channel_id')) else 'Disabled')}</p>"+_form(gid,action,fields)+("<form method='post' action='/dashboard/action'>"+_csrf_input()+f"<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='{action}_disable'><button class='btn secondary small' type='submit'>Disable</button></form>" if cfg else "")+"</article>"
    ai_form="<div class='field'><label>Always-on AI channel</label>"+_channel_select(guild,"channel_id",ai)+"</div>"
    log_form="<div class='field'><label>Main moderation and error log channel</label>"+_channel_select(guild,"channel_id",logs)+"</div>"
    ai_card="<article class='card half'><h2>AI channel</h2><p class='muted'>Current: "+_esc(guild.get_channel(ai).mention if ai and guild.get_channel(ai) else 'Not set')+"</p>"+_form(gid,"ai_channel",ai_form)+"</article>"
    log_card="<article class='card half'><h2>Main logging</h2><p class='muted'>Current: "+_esc(guild.get_channel(logs).mention if logs and guild.get_channel(logs) else 'Not set')+"</p>"+_form(gid,"log_channel",log_form)+"</article>"
    return "<h1>Community</h1><p class='muted'>Welcome and goodbye messages, Cinnamon's AI channel and server logging.</p><div class='grid'>"+message_form("Welcome messages",welcome,"welcome")+message_form("Goodbye messages",goodbye,"goodbye")+ai_card+log_card+"</div>"


def _system(guild,state):
    gid=guild.id; q=state.get("quest_config",{}).get(gid,{}); a=state.get("achievement_config",{}).get(gid,{})
    qlog=q.get("log_channel_id"); alog=a.get("log_channel_id"); elog=state.get("economy_log_channels",{}).get(gid)
    def current(cid):
        ch=guild.get_channel(cid) if cid else None
        return _esc(ch.mention if ch else "Not configured")
    channels="<div class='formgrid'>"
    for key,label,cid in [("quest_log","Quest logs",qlog),("achievement_log","Achievement logs",alog),("economy_log","Economy logs",elog)]:
        channels+=f"<div class='field'><label>{label}</label>{_channel_select(guild,key,cid)}</div>"
    channels+="</div>"
    logsform=_form(gid,"special_logs",channels,"Save log channels")
    logitems=[]
    for label,cid in [("Main logs",state.get("log_channels",{}).get(gid)),("Quest logs",qlog),("Achievement logs",alog),("Economy logs",elog)]:
        logitems.append(f"<div class='toggle'><b>{label}</b><span>{current(cid)}</span></div>")
    status=bool(_bot and _bot.is_ready())
    storage="Upstash Redis" if state.get("BD_UPSTASH_URL") and state.get("BD_UPSTASH_TOKEN") else "Local JSON file (may not survive redeploys)"
    return f"<h1>Settings & system</h1><p class='muted'>Channel routing, persistence status and recovery guidance.</p><div class='grid'><article class='card half'><h2>Dedicated log channels</h2>{logsform}</article><article class='card half'><h2>Current system status</h2><div class='toggle'><b>Bot Gateway</b><span class='pill {'good' if status else 'warn'}'>{'Connected' if status else 'Not ready'}</span></div><div class='toggle'><b>Storage backend</b><span>{storage}</span></div><div class='toggle'><b>Guild ID</b><span>{gid}</span></div><div class='toggle'><b>Bot permissions</b><span>Use <b>/diagnostics</b> in Discord for the detailed check.</span></div></article><article class='card full'><h2>Channel configuration</h2>{''.join(logitems)}<div class='rule'></div><p class='muted'>The dashboard saves settings through Cinnamon's existing persistence function. For backup and recovery, use <b>/backup</b> and <b>/recall</b> in Discord. Restoring backups from a browser is intentionally not enabled.</p><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=overview'>Back to overview</a></article></div>"


def _moderate(guild, actor_id, form):
    action=form.get("mod_action","").lower(); raw_id=form.get("member_id","").strip(); reason=form.get("reason","No reason provided")[:400]
    if not raw_id.isdigit() or not 15 <= len(raw_id) <= 22: raise ValueError("Enter a valid Discord member ID.")
    if action not in {"kick","ban","timeout"}: raise ValueError("Choose a supported moderation action.")
    uid=int(raw_id); actor_id=int(actor_id)
    if uid in {actor_id, guild.owner_id, _bot.user.id if _bot.user else -1}: raise ValueError("This member cannot be moderated from the dashboard.")
    async def perform():
        actor=guild.get_member(actor_id) or await guild.fetch_member(actor_id)
        target=guild.get_member(uid) or await guild.fetch_member(uid)
        me=guild.me
        if not actor.guild_permissions.administrator and not actor.guild_permissions.manage_guild:
            raise PermissionError("Your current server permissions do not allow dashboard moderation.")
        if target.top_role >= actor.top_role and actor.id != guild.owner_id and not actor.guild_permissions.administrator:
            raise PermissionError("You cannot moderate a member with an equal or higher role.")
        if target.top_role >= me.top_role: raise PermissionError("Cinnamon's highest role must be above the target member's role.")
        if action=="kick":
            if not actor.guild_permissions.kick_members or not me.guild_permissions.kick_members: raise PermissionError("Both you and Cinnamon need Kick Members permission.")
            await target.kick(reason=f"Dashboard by {actor} ({actor.id}): {reason}")
        elif action=="ban":
            if not actor.guild_permissions.ban_members or not me.guild_permissions.ban_members: raise PermissionError("Both you and Cinnamon need Ban Members permission.")
            await target.ban(reason=f"Dashboard by {actor} ({actor.id}): {reason}", delete_message_seconds=0)
        else:
            if not actor.guild_permissions.moderate_members or not me.guild_permissions.moderate_members: raise PermissionError("Both you and Cinnamon need Moderate Members permission.")
            try: minutes=int(form.get("duration","60"))
            except ValueError: raise ValueError("Timeout duration must be a number of minutes.")
            if not 1 <= minutes <= 40320: raise ValueError("Timeout duration must be between 1 and 40,320 minutes (28 days).")
            await target.timeout(dt.timedelta(minutes=minutes), reason=f"Dashboard by {actor} ({actor.id}): {reason}")
        return str(target), action
    return _run_bot(perform())


@dashboard_bp.get("/login")
def login():
    if not os.getenv("DISCORD_CLIENT_ID") or not os.getenv("DISCORD_CLIENT_SECRET"):
        return _page("<main class='main'><article class='card'><h1>Almost ready</h1><p>Add the Discord OAuth client settings to Render's environment variables.</p></article></main>","Cinnamon Login")
    state=secrets.token_urlsafe(32); session["oauth_state"]=state
    params={"client_id":os.environ["DISCORD_CLIENT_ID"],"response_type":"code","redirect_uri":os.getenv("DASHBOARD_REDIRECT_URI",DEFAULT_REDIRECT),"scope":"identify guilds","state":state}
    return redirect("https://discord.com/oauth2/authorize?"+urllib.parse.urlencode(params))


@dashboard_bp.get("/oauth/callback")
def oauth_callback():
    if request.args.get("error"):
        return _page("<main class='main'><article class='card'><h1>Login cancelled</h1><a class='btn' href='/login'>Try again</a></article></main>")
    state=request.args.get("state",""); saved=session.pop("oauth_state","")
    if not state or not saved or not secrets.compare_digest(state,saved):
        return _page("<main class='main'><article class='card'><h1>Login could not be verified</h1><a class='btn' href='/login'>Restart login</a></article></main>",status=400)
    code=request.args.get("code")
    if not code: return _page("<main class='main'><article class='card'><h1>Missing authorization code</h1><a class='btn' href='/login'>Try again</a></article></main>",status=400)
    try:
        redirect_uri=os.getenv("DASHBOARD_REDIRECT_URI",DEFAULT_REDIRECT)
        token=_token_exchange({"grant_type":"authorization_code","code":code,"redirect_uri":redirect_uri})
        user=_request_json(f"{BASE_URL}/users/@me",headers={"Authorization":"Bearer "+token["access_token"]})
        sid=secrets.token_urlsafe(32)
        _tokens[sid]={"access_token":token["access_token"],"refresh_token":token.get("refresh_token"),"expires_at":time.time()+int(token.get("expires_in",3600)),"user":user}
        session.clear(); session["dash_sid"]=sid; session["display_name"]=user.get("global_name") or user.get("username") or "Discord user"; _csrf()
        return redirect(url_for("cinnamon_dashboard.dashboard_home"))
    except urllib.error.HTTPError as exc:
        try: payload=json.loads(exc.read().decode("utf-8"))
        except Exception: payload={}
        log.error("Discord OAuth HTTP error status=%s error=%s description=%s",exc.code,str(payload.get("error","unknown"))[:120],str(payload.get("error_description","unavailable"))[:240])
        return _page("<main class='main'><article class='card'><h1>Discord login failed</h1><p class='muted'>Discord rejected the login exchange. Check Render logs for a sanitized error detail.</p><a class='btn' href='/login'>Try again</a></article></main>",status=502)
    except Exception as exc:
        log.exception("Discord OAuth callback failed (%s)",type(exc).__name__)
        return _page("<main class='main'><article class='card'><h1>Discord login failed</h1><p class='muted'>An unexpected login error occurred. Check Render logs.</p><a class='btn' href='/login'>Try again</a></article></main>",status=502)


@dashboard_bp.get("/dashboard")
def dashboard_home():
    sid=session.get("dash_sid")
    if not sid or sid not in _tokens: return redirect(url_for("cinnamon_dashboard.login"))
    try:
        context=_dashboard_context()
    except Exception as exc:
        log.exception("Dashboard identity/guild lookup failed (%s)",type(exc).__name__)
        session.pop("dash_sid",None); return redirect(url_for("cinnamon_dashboard.login"))
    if not context: return redirect(url_for("cinnamon_dashboard.login"))
    sid,guilds,eligible=context
    if not eligible:
        body="<section class='hero'><div><h1>No manageable server found</h1><p>Add Cinnamon to a server where you have Manage Server or Administrator permission, then reload.</p></div><img class='heroimg' src='/static/cinnamon_mascot.jpg' alt='Cinnamon'></section>"
        return _page("<main class='main'>"+_header()+body+"</main>")
    guild_id=request.args.get("guild_id") or eligible[0]["id"]
    guild,guild_item=_get_access(sid,guilds,guild_id)
    tab=request.args.get("tab","overview"); allowed={"overview","moderation","engagement","economy","community","system"}
    if tab not in allowed: tab="overview"
    state=_state(); notice=session.pop("dashboard_notice",None)
    pages={"overview":_overview,"moderation":_moderation,"engagement":_engagement,"economy":_economy,"community":_community,"system":_system}
    return _shell(guild,eligible,tab,pages[tab](guild,state),notice)


@dashboard_bp.post("/dashboard/action")
def dashboard_action():
    _check_csrf()
    sid=session.get("dash_sid")
    if not sid or sid not in _tokens: return redirect(url_for("cinnamon_dashboard.login"))
    try:
        context=_dashboard_context()
        if not context: abort(401)
        sid,guilds,eligible=context
        guild_id=request.form.get("guild_id","")
        guild,_=_get_access(sid,guilds,guild_id)
        gid=guild.id; state=_state(); action=request.form.get("action","")
        actor=_tokens[sid]["user"].get("username","dashboard user")
        if action in {"welcome","goodbye","ai_channel","log_channel","special_logs","automod","antiraid","levelrole_add","levelrole_remove"}:
            if not _tokens[sid]["user"].get("id"): abort(401)
        if action in {"welcome","goodbye"}:
            channel_id=request.form.get("channel_id","").strip(); message=request.form.get("message","")
            config_key="welcome_config" if action=="welcome" else "goodbye_config"
            if not channel_id: raise ValueError("Choose a channel or use Disable.")
            if not channel_id.isdigit() or not guild.get_channel(int(channel_id)): raise ValueError("Choose a valid text channel from this server.")
            if not message or len(message)>800: raise ValueError("Message must be between 1 and 800 characters.")
            try: message.format(member="member",server="server")
            except (KeyError,ValueError,IndexError): raise ValueError("Only {member} and {server} placeholders are supported; check the braces.")
            state[config_key][gid]={"channel_id":int(channel_id),"message":message}
            _save(); _audit(gid,actor,f"Dashboard: {action} message updated",f"Channel ID {channel_id}; message template changed.")
            session["dashboard_notice"]=f"{action.title()} message saved."
        elif action in {"welcome_disable","goodbye_disable"}:
            key="welcome_config" if action.startswith("welcome") else "goodbye_config"
            state[key].pop(gid,None); _save(); _audit(gid,actor,"Dashboard: messages disabled",action)
            session["dashboard_notice"]="Message setting disabled."
        elif action in {"ai_channel","log_channel"}:
            channel_id=request.form.get("channel_id","").strip(); key="ai_channels" if action=="ai_channel" else "log_channels"
            if channel_id and (not channel_id.isdigit() or not guild.get_channel(int(channel_id))): raise ValueError("Choose a valid channel from this server.")
            if channel_id: state[key][gid]=int(channel_id)
            else: state[key].pop(gid,None)
            _save(); _audit(gid,actor,"Dashboard: channel setting updated",f"{action}: {channel_id or 'disabled'}")
            session["dashboard_notice"]="Channel setting saved."
        elif action=="special_logs":
            for field,key in [("quest_log","quest_config"),("achievement_log","achievement_config"),("economy_log","economy_log_channels")]:
                value=request.form.get(field,"").strip()
                if value and (not value.isdigit() or not guild.get_channel(int(value))): raise ValueError("Choose valid channels from this server.")
                if key=="quest_config":
                    cfg=state[key].setdefault(gid,{"enabled":True,"log_channel_id":None,"daily":{},"weekly":{},"history":[]})
                    cfg["log_channel_id"]=int(value) if value else None
                elif key=="achievement_config":
                    cfg=state[key].setdefault(gid,{"enabled":True,"log_channel_id":None}); cfg["log_channel_id"]=int(value) if value else None
                else:
                    if value: state[key][gid]=int(value)
                    else: state[key].pop(gid,None)
            _save(); _audit(gid,actor,"Dashboard: dedicated log channels updated","Quest, achievement, and economy log routing changed.")
            session["dashboard_notice"]="Dedicated log channels saved."
        elif action=="automod":
            raw=request.form.get("words",""); words=[]
            for line in raw.splitlines():
                word=line.strip()
                if word and word not in words: words.append(word[:100])
            if len(words)>50: raise ValueError("Use no more than 50 unique words or phrases.")
            threshold=int(request.form.get("mention_threshold","5"))
            if not 2<=threshold<=20: raise ValueError("Mention threshold must be between 2 and 20.")
            cfg=state["automod_config"].setdefault(gid,{"words":[],"spam":False,"mentions":False,"invites":False,"mention_threshold":5})
            cfg.update({"words":words,"spam":"spam" in request.form,"mentions":"mentions" in request.form,"invites":"invites" in request.form,"mention_threshold":threshold})
            if not (words or cfg["spam"] or cfg["mentions"] or cfg["invites"]): state["automod_config"].pop(gid,None)
            _save(); _audit(gid,actor,"Dashboard: AutoMod updated",f"{len(words)} word/phrase filters; spam={cfg['spam']}; mentions={cfg['mentions']}; invites={cfg['invites']}.")
            session["dashboard_notice"]="AutoMod settings saved."
        elif action=="antiraid":
            threshold=int(request.form.get("threshold","5")); window=int(request.form.get("window","10"))
            if not 2<=threshold<=100 or not 2<=window<=120: raise ValueError("Threshold must be 2–100 and time window 2–120 seconds.")
            cfg=state["antiraid_config"].setdefault(gid,{"enabled":False,"threshold":5,"window":10})
            cfg.update({"enabled":"enabled" in request.form,"threshold":threshold,"window":window})
            _save(); _audit(gid,actor,"Dashboard: anti-raid updated",f"Enabled={cfg['enabled']}, threshold={threshold}, window={window}s. Alert-only.")
            session["dashboard_notice"]="Anti-raid settings saved."
        elif action=="levelrole_add":
            level=int(request.form.get("level","0")); role_id=request.form.get("role_id","")
            role=guild.get_role(int(role_id)) if role_id.isdigit() else None
            if not 1<=level<=100 or not role or role.is_default() or role.managed: raise ValueError("Choose a valid level (1–100) and assignable role.")
            if not guild.me or role>=guild.me.top_role: raise ValueError("Move Cinnamon's highest role above the reward role first.")
            state["level_roles"].setdefault(gid,{})[level]=role.id
            _save(); _audit(gid,actor,"Dashboard: level reward added",f"Level {level}: {role.name}")
            session["dashboard_notice"]="Level reward saved."
        elif action=="levelrole_remove":
            level=int(request.form.get("level","0")); mapping=state["level_roles"].get(gid,{})
            if mapping.pop(level,None) is None: raise ValueError("No reward is configured for that level.")
            _save(); _audit(gid,actor,"Dashboard: level reward removed",f"Level {level}")
            session["dashboard_notice"]="Level reward removed. Members keep roles already earned."
        elif action=="moderate":
            target,mod_action=_moderate(guild,_tokens[sid]["user"]["id"],request.form)
            _audit(gid,actor,f"Dashboard moderation: {mod_action}",f"Target {target}; reason: {request.form.get('reason','No reason provided')[:350]}")
            session["dashboard_notice"]=f"{mod_action.title()} action completed for {target}."
        else:
            raise ValueError("Unknown dashboard action.")
        tab={"welcome":"community","goodbye":"community","welcome_disable":"community","goodbye_disable":"community","ai_channel":"community","log_channel":"community","special_logs":"system","automod":"moderation","antiraid":"moderation","moderate":"moderation","levelrole_add":"engagement","levelrole_remove":"engagement"}.get(action,"overview")
        return redirect(url_for("cinnamon_dashboard.dashboard_home",guild_id=gid,tab=tab))
    except (ValueError,PermissionError) as exc:
        session["dashboard_notice"]=str(exc)[:300]
        return redirect(url_for("cinnamon_dashboard.dashboard_home",guild_id=request.form.get("guild_id",""),tab="moderation" if request.form.get("action") in {"moderate","automod","antiraid"} else "community"))
    except Exception as exc:
        log.exception("Dashboard action failed (%s)",type(exc).__name__)
        session["dashboard_notice"]="The change could not be completed. Check Cinnamon's Render logs and bot permissions."
        return redirect(url_for("cinnamon_dashboard.dashboard_home",guild_id=request.form.get("guild_id",""),tab="overview"))


@dashboard_bp.get("/logout")
def logout():
    sid=session.pop("dash_sid",None)
    if sid: _tokens.pop(sid,None)
    session.pop("oauth_state",None); session.pop("dashboard_csrf",None); session.pop("display_name",None)
    return redirect(url_for("cinnamon_dashboard.login"))


@dashboard_bp.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
    response.headers["Cache-Control"]="no-store"
    response.headers["Content-Security-Policy"]="default-src 'self' https://cdn.discordapp.com; img-src 'self' https://cdn.discordapp.com data:; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    return response
