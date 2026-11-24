"""Cinnamon's server management dashboard.

Uses Discord OAuth for identity, re-checks guild access on each request, and
runs Discord operations on the bot's event loop. The bot's data persistence
functions are injected by main.py through configure_dashboard().
"""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import html
import json
import logging
import os
import re
import secrets
import hashlib
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from flask import Blueprint, abort, make_response, redirect, render_template_string, request, session, url_for

log = logging.getLogger("cinnamon.dashboard")
dashboard_bp = Blueprint("cinnamon_dashboard", __name__)
_bot = None
_state_provider = None
_tokens: dict[str, dict[str, Any]] = {}
BASE_URL = "https://discord.com/api/v10"
DEFAULT_REDIRECT = (os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/") or "https://cinnamon-c328.onrender.com") + "/oauth/callback"


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


def _oauth_redirect_uri():
    # Keep the authorization request and token exchange byte-for-byte consistent.
    # Discord requires the redirect_uri used during the code exchange to match
    # the one used to obtain the authorization code.
    return os.getenv("DASHBOARD_REDIRECT_URI", DEFAULT_REDIRECT).strip()


def _token_exchange(data):
    client_id = os.environ["DISCORD_CLIENT_ID"].strip()
    client_secret = os.environ["DISCORD_CLIENT_SECRET"].strip()
    payload = {"client_id": client_id, "client_secret": client_secret, **data}
    return _request_json(
        f"{BASE_URL}/oauth2/token",
        method="POST",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
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
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        # Stop pending work when the request gives up so a retry does not leave
        # a second moderation action or message running in the background.
        future.cancel()
        raise


def _save():
    save_fn = _state().get("bd_save_data")
    if not callable(save_fn):
        raise RuntimeError("Dashboard storage callback is not configured")
    if not _run_bot(save_fn()):
        raise ValueError("The durable save could not be verified. Check storage before trying again.")


def _audit(guild_id, actor, title, detail):
    send_log = _state().get("send_log")
    if callable(send_log):
        try:
            text = f"{title} {detail}".lower()
            if any(x in text for x in ("achievement", "achievement role", "secret achievement")):
                category = "achievements"
            elif any(x in text for x in ("friendship", "cinnamon friendship")):
                category = "friendship"
            elif any(x in text for x in ("quest", "quest shop", "daily quest", "weekly quest")):
                category = "quests"
            elif any(x in text for x in ("economy", "shop item", "catnip")):
                category = "economy"
            elif any(x in text for x in ("giveaway", "poll")):
                category = "community"
            elif any(x in text for x in ("hangry", "hangry games")):
                category = "hangrygames"
            elif any(x in text for x in ("level reward", "level role", "xp")):
                category = "levels"
            elif any(x in text for x in ("role", "reaction")):
                category = "roles"
            elif any(x in text for x in ("welcome", "goodbye", "channel setting", "log channel", "recovery", "setup")):
                category = "setup"
            elif any(x in text for x in ("ai", "gemini")):
                category = "ai"
            elif any(x in text for x in ("moderation", "moderate", "automod", "anti-raid")):
                category = "moderation"
            else:
                category = "general"
            if category == "hangrygames":
                hg = _state().get("hg_cog")
                if hg is not None:
                    _run_bot(hg._log(guild_id, title=title, fields=[("Dashboard actor", str(actor)[:100]), ("Detail", detail[:800])]))
                else:
                    _run_bot(send_log(guild_id, title=title, description=detail[:900], fields=[("Dashboard actor", str(actor)[:100])], category="moderation"))
            else:
                _run_bot(send_log(
                    guild_id, title=title,
                    description=detail[:900],
                    fields=[("Dashboard actor", str(actor)[:100])],
                    category=category,
                ))
            # Every dashboard mutation also gets a copy in the dedicated dashboard audit channel.
            # This is separate from feature-specific logs so admins have one complete audit trail.
            if category != "dashboard":
                _run_bot(send_log(
                    guild_id, title="🧭 Dashboard audit • " + title[:180],
                    description=detail[:900],
                    fields=[("Dashboard actor", str(actor)[:100]), ("Feature log category", category)],
                    category="dashboard",
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
        + STYLE + """</style><script src='/static/dashboard-search.js' defer></script></head><body>{{body|safe}}</body></html>""",
        title=title, body=body,
    ), status


STYLE = r"""
:root{--cream:#fbf2e4;--beige:#f7ebd9;--orange:#b96b2c;--orange2:#d88b45;--brown:#38251d;--taupe:#897765;--white:#fffdf9;--line:#e4d5c0;--green:#36734d;--red:#a53f32;--shadow:0 12px 34px #38251d0c}
*{box-sizing:border-box}body{margin:0;background:var(--cream);color:var(--brown);font:15px "Trebuchet MS",system-ui,-apple-system,Segoe UI,sans-serif}a{color:inherit;text-decoration:none}button,input,select,textarea{font:inherit}.layout{min-height:100vh;display:grid;grid-template-columns:248px minmax(0,1fr)}.side{background:#f3e5d0;border-right:1px solid var(--line);padding:20px 14px;display:flex;flex-direction:column;gap:18px}.brand{display:flex;align-items:center;gap:11px;font-size:19px;font-weight:850;padding:4px 8px}.mascot{width:45px;height:45px;object-fit:cover;border-radius:15px;border:2px solid #ead7b8;background:var(--beige)}.serverbox{padding:12px;background:#fff9f0;border:1px solid var(--line);border-radius:14px}.serverbox label{display:block;font-size:11px;color:var(--taupe);font-weight:800;text-transform:uppercase;letter-spacing:.08em;margin-bottom:7px}.serverbox select{width:100%;border:1px solid var(--line);border-radius:9px;background:white;padding:10px;color:var(--brown)}.navlabel{font-size:11px;color:var(--taupe);font-weight:800;letter-spacing:.1em;text-transform:uppercase;padding:0 10px;margin:5px 0}.nav-search{margin:0 0 7px;padding:0 2px}.nav-search input{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:9px;background:#fffdf9;color:var(--brown)}.nav{display:grid;gap:4px}.nav a{padding:10px 12px;border-radius:10px;color:#654d3d;font-weight:650;display:flex;gap:10px;align-items:center}.nav a.active,.nav a:hover{background:#e9d5b8;color:var(--brown)}.sidefoot{margin-top:auto;font-size:12px;color:var(--taupe);padding:8px}.main{min-width:0;padding:24px clamp(16px,3vw,38px) 40px;max-width:1500px;width:100%;margin:auto}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:24px}.crumb{font-size:13px;color:var(--taupe)}.profile{display:flex;align-items:center;gap:10px;font-weight:700}.avatar{width:34px;height:34px;border-radius:50%;background:var(--beige)}h1,h2,h3,p{margin-top:0}h1{font:700 clamp(27px,3vw,36px) Georgia,serif;margin-bottom:7px}h2{font:700 23px Georgia,serif;margin-bottom:12px}h3{font-size:16px;margin-bottom:8px}.muted{color:var(--taupe);line-height:1.55}.hero{background:linear-gradient(115deg,#f7e6ce,#fff7e9);border:1px solid var(--line);border-radius:22px;padding:25px;display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:20px;box-shadow:var(--shadow)}.hero p{margin:0;color:#78624e}.heroimg{width:100px;height:100px;object-fit:cover;border-radius:24px}.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:14px;margin:15px 0 22px}.card{grid-column:span 4;min-width:0;background:var(--white);border:1px solid var(--line);border-radius:17px;padding:18px;box-shadow:var(--shadow)}.card.half{grid-column:span 6}.card.full{grid-column:1/-1}.card.third{grid-column:span 4}.stat{font:700 30px Georgia,serif;margin:8px 0 2px}.statlabel{font-size:12px;color:var(--taupe);font-weight:750;text-transform:uppercase;letter-spacing:.06em}.iconbox{width:38px;height:38px;display:grid;place-items:center;background:#f7ead7;border-radius:12px;font-size:19px;margin-bottom:13px}.btn{display:inline-block;border:0;border-radius:10px;background:var(--orange);color:white;padding:10px 14px;font-weight:750;cursor:pointer}.btn:hover{background:#a75e26}.btn.secondary{background:#f0e2cd;color:var(--brown);border:1px solid var(--line)}.btn.danger{background:var(--red)}.btn.small{padding:7px 10px;font-size:13px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.formgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.field{display:grid;gap:6px;margin:10px 0}.field label{font-size:13px;font-weight:750}.field input,.field select,.field textarea{width:100%;border:1px solid var(--line);border-radius:10px;background:#fff;padding:11px 12px;color:var(--brown);min-width:0}.field textarea{min-height:92px;resize:vertical}.field small{font-size:12px;color:var(--taupe);line-height:1.4}.toggle{display:flex;gap:10px;align-items:flex-start;padding:12px 0;border-bottom:1px solid #f0e6d9}.toggle input{accent-color:var(--orange);width:17px;height:17px;margin-top:2px}.toggle span{display:grid;gap:3px}.toggle small{color:var(--taupe)}.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;min-width:460px;background:#fffdf9}th,td{text-align:left;padding:11px 13px;border-bottom:1px solid #f0e6d9;font-size:13px}th{color:var(--taupe);background:#fbf4e9;text-transform:uppercase;font-size:11px;letter-spacing:.05em}tr:last-child td{border-bottom:0}.pill{display:inline-block;border-radius:30px;padding:4px 9px;background:#efe4d2;color:#6b543e;font-size:11px;font-weight:800}.pill.good{background:#e3f0e5;color:var(--green)}.pill.warn{background:#f9e8d9;color:#99591f}.notice{padding:12px 14px;border-radius:12px;background:#f4e8d4;border:1px solid var(--line);margin-bottom:15px;color:#6e553e}.empty{padding:25px;text-align:center;color:var(--taupe)}.rule{height:1px;background:var(--line);margin:16px 0}.sectionhead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:23px 0 8px}.servericon{width:38px;height:38px;border-radius:12px;background:#f4e5cf;display:grid;place-items:center;font-weight:800;color:var(--orange);overflow:hidden;flex-shrink:0}.servericon img{width:100%;height:100%;object-fit:cover}.serverlist{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}.serveritem{background:var(--white);border:1px solid var(--line);padding:15px;border-radius:15px;display:flex;align-items:center;gap:12px}.serveritem .grow{flex:1;min-width:0}.serveritem h3{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:0 0 4px}.mobilebrand{display:none}.footer{font-size:12px;color:var(--taupe);margin-top:25px}.dangerzone{border-color:#e8c6be}.dangerzone h3{color:var(--red)}@media(max-width:900px){.layout{grid-template-columns:205px minmax(0,1fr)}.card{grid-column:span 6}.card.third{grid-column:span 6}}@media(max-width:650px){.layout{display:block}.side{position:sticky;top:0;z-index:4;border-right:0;border-bottom:1px solid var(--line);padding:9px 12px;display:block}.brand{padding:2px 4px;margin-bottom:8px}.brand .mascot{width:35px;height:35px}.serverbox{padding:8px;margin-bottom:7px}.serverbox label{display:none}.serverbox select{padding:8px}.navlabel{display:none}.nav-search{margin:0 0 7px}.nav{display:flex;overflow-x:auto;gap:5px;padding-bottom:3px}.nav a{white-space:nowrap;padding:8px 10px;font-size:12px}.sidefoot{display:none}.main{padding:17px 13px 30px}.top{margin-bottom:16px}.hero{padding:18px}.heroimg{width:68px;height:68px}.card,.card.half,.card.third{grid-column:1/-1}.formgrid{grid-template-columns:1fr}h1{font-size:28px}.stat{font-size:26px}}
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
/* Lovable consultation: calm cream/orange, clear card hierarchy, accessible controls. */
:root{--focus:#1f5fbf;--surface2:#fffaf2;--accent:#a9531a}
body{font-size:16px;line-height:1.52}
h1,h2,.stat{font-family:"Trebuchet MS",system-ui,-apple-system,Segoe UI,sans-serif;letter-spacing:-.035em}
.main{max-width:1240px}.card{box-shadow:0 2px 0 #e4d5c0,0 7px 18px #38251d10}
.card h2{font-size:20px;line-height:1.25}.stat{font-weight:850}
.btn{min-height:44px;background:#a9531a}
.btn:hover{background:#84401a}
.btn.secondary{background:#fff7ec;color:#432817}
.field input,.field select,.field textarea{min-height:44px}
.nav a{min-height:44px}
:focus-visible{outline:3px solid var(--focus)!important;outline-offset:2px!important}
.card .toggle{min-height:44px}
.pill{font-size:12px}
.searchable-select{display:grid;gap:6px;margin-bottom:9px}
.searchable-select input{min-height:40px;width:100%;background:#fffaf2;border:1px solid var(--line);border-radius:8px;padding:9px}
@media(max-width:650px){.hero{flex-direction:column;align-items:flex-start}.heroimg{align-self:flex-end}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;transition-duration:.01ms!important}}
/* Mobile navigation drawer: keep every category reachable on short screens. */
.mobile-nav-toggle{display:none;border:1px solid var(--line);background:var(--white);color:var(--brown);border-radius:10px;min-height:42px;min-width:44px;padding:8px 12px;font-size:20px;line-height:1;cursor:pointer}
.mobile-nav-close{display:none}
.nav-backdrop{display:none}
@media(max-width:650px){
  body.nav-open{overflow:hidden}
  .side{position:fixed!important;inset:0 auto 0 0;width:min(86vw,310px);height:100vh;height:100dvh;max-height:100dvh;overflow-y:auto;overflow-x:hidden;-webkit-overflow-scrolling:touch;overscroll-behavior-y:contain;touch-action:pan-y;transform:translateX(-105%);transition:transform .22s ease;z-index:100;display:flex!important;flex-direction:column;gap:14px;padding:calc(12px + env(safe-area-inset-top)) 12px calc(16px + env(safe-area-inset-bottom))!important;border-right:1px solid var(--line);border-bottom:0;box-shadow:12px 0 35px #38251d20}
  .side.mobile-open{transform:translateX(0)}
  .side>form,.side>div{flex-shrink:0}
  .side .nav{display:grid!important;overflow:visible!important;flex-shrink:0;gap:4px;padding-bottom:8px;scroll-snap-type:none}
  .side .nav a{white-space:normal;flex:initial;width:100%;min-height:44px;font-size:13px;padding:11px 12px;scroll-snap-align:none}
  .side .navlabel{display:block}
  .side .sidefoot{display:block;margin-top:auto;padding-top:12px}
  .mobile-nav-toggle{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto}
  .top{justify-content:flex-start;flex-wrap:wrap}
  .top .crumb{flex:1;min-width:0;align-self:center}
  .profile{margin-left:auto}
  .nav-backdrop{display:block;position:fixed;inset:0;background:rgba(38,25,18,.42);z-index:99;opacity:0;visibility:hidden;transition:opacity .2s,visibility .2s;border:0;padding:0}
  .nav-backdrop.visible{opacity:1;visibility:visible}
  .mobile-nav-close{display:inline-flex;align-items:center;justify-content:center;align-self:flex-end;border:1px solid var(--line);border-radius:9px;background:var(--white);color:var(--brown);min-height:40px;min-width:44px;font-size:20px;margin-bottom:-4px}
}

/* Cinnamon dashboard refresh: calmer hierarchy, consistent controls, responsive surfaces. */
:root{--cream:#f8f5ef;--beige:#f0e8dc;--orange:#a9531a;--orange2:#d18a48;--brown:#30251f;--taupe:#786d63;--white:#fffefa;--line:#e7dfd4;--surface2:#fbf8f2;--shadow:0 8px 24px rgba(48,37,31,.055);--focus:#285f9f;--green:#32744d;--red:#a53f32}
body{background:#f7f5f1;color:var(--brown);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.55}
.layout{grid-template-columns:264px minmax(0,1fr);background:transparent}
.side{background:#fffefa;border-right:1px solid #e9e2d9;box-shadow:2px 0 18px rgba(48,37,31,.025);padding:22px 16px}
.brand{font-size:18px;letter-spacing:-.025em;padding:5px 7px 12px}
.mascot{border-radius:14px;border:1px solid #eadfce}
.serverbox{background:#faf7f1;border-color:#e8e0d5;border-radius:12px}
.navlabel{font-size:10px;letter-spacing:.12em;color:#8a7c70}
.nav a{min-height:42px;border-radius:9px;color:#65584d;font-size:13px;transition:background .15s,color .15s}
.nav a.active{background:#f5e8d8;color:#8d4517;box-shadow:inset 3px 0 #b96b2c}
.nav a:hover{background:#f8f0e6}
.main{max-width:1320px;padding:28px clamp(18px,3vw,44px) 48px}
.top{margin-bottom:28px;padding-bottom:15px;border-bottom:1px solid #eae4db}
.crumb{font-size:13px;color:#887b70}
h1{font-size:clamp(27px,3vw,34px);font-weight:780;letter-spacing:-.045em;line-height:1.18;margin-bottom:8px}
h2{font-size:19px;font-weight:740;letter-spacing:-.025em}
h3{font-size:15px;font-weight:730}
.muted{color:#81766c}
.hero{background:linear-gradient(110deg,#fff5e8 0%,#fffdfa 82%);border:1px solid #eee2d2;border-radius:18px;padding:24px;box-shadow:none}
.card{background:#fffefa;border:1px solid #e9e2d9;border-radius:15px;padding:20px;box-shadow:0 3px 12px rgba(48,37,31,.035)}
.card:hover{border-color:#dfd2c2}
.grid{gap:15px;margin:17px 0 24px}
.stat{font-size:29px;letter-spacing:-.04em}
.iconbox{background:#f8eee1;border:1px solid #f0e2d0}
.btn{background:#a9531a;border-radius:9px;box-shadow:none;transition:background .15s,transform .15s}
.btn:hover{background:#874313;transform:translateY(-1px)}
.btn.secondary{background:#fff9f1;border-color:#e9ddce;color:#594333}
.btn.danger{background:#a53f32}
.field{gap:7px;margin:12px 0}
.field label{font-size:12px;color:#55463a;letter-spacing:.01em}
.field input,.field select,.field textarea,.searchable-select input{background:#fff;border:1px solid #e4dbcf;border-radius:9px;color:#30251f;transition:border-color .15s,box-shadow .15s}
.field input:focus,.field select:focus,.field textarea:focus,.searchable-select input:focus,.choice-search:focus{border-color:#bd7a42;box-shadow:0 0 0 3px rgba(185,107,44,.12);outline:0}
.tablewrap{border-color:#e9e2d9;border-radius:11px}
th{background:#faf7f1;color:#81766c}
td{border-bottom-color:#f0ebe4}
.notice{background:#fff5e8;border-color:#edddc9;color:#76502f}
.pill{background:#f1ece4;color:#67594c}
.choice-picker{display:grid;gap:10px;padding:12px;border:1px solid #e8e0d5;border-radius:12px;background:#fffefa}
.choice-toolbar{display:flex;align-items:center;gap:10px;min-width:0}
.choice-search{width:100%;min-width:0;min-height:43px;padding:10px 12px;border:1px solid #e4dbcf;border-radius:9px;background:#fff;color:var(--brown);font:inherit}
.choice-count{flex:0 0 auto;color:#83766b;font-size:12px;font-weight:700;white-space:nowrap}
.choice-selected{display:flex;gap:6px;flex-wrap:wrap;min-height:25px}
.choice-chip{border:1px solid #ead7c2;background:#fbf0e2;color:#79441f;border-radius:99px;padding:5px 9px;font-size:12px;font-weight:650;cursor:pointer}
.choice-chip:hover{background:#f5e2cc}
.choice-options{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:7px;max-height:260px;overflow:auto;padding:2px;overscroll-behavior:contain}
.choice-option{display:flex;align-items:center;gap:9px;min-width:0;padding:10px 11px;border:1px solid #eee7de;border-radius:9px;background:#fff;cursor:pointer;transition:border-color .12s,background .12s}
.choice-option:hover{border-color:#d6b38f;background:#fffaf3}
.choice-option[hidden]{display:none!important}
.choice-option input{width:18px;height:18px;flex:0 0 18px;accent-color:#a9531a}
.choice-option span{overflow-wrap:anywhere;font-size:13px}
.choice-help{color:#85796e;font-size:12px;line-height:1.45}
.searchable-select{margin-bottom:7px}
.searchable-select input{min-height:42px;padding:10px 12px}
@media(max-width:900px){.layout{grid-template-columns:220px minmax(0,1fr)}.main{padding:22px 18px 38px}}
@media(max-width:650px){
 .main{padding:14px 12px calc(28px + env(safe-area-inset-bottom))}
 .top{gap:8px;padding-bottom:12px;margin-bottom:18px}
 .crumb{font-size:12px}.profile{font-size:12px}
 .hero{padding:17px;border-radius:14px;gap:12px}.heroimg{width:56px;height:56px}
 .grid{gap:11px;margin:13px 0 19px}
 .card,.card.half,.card.third{padding:15px;border-radius:13px}
 .card h2{font-size:18px}.formgrid{grid-template-columns:minmax(0,1fr);gap:8px}
 .choice-picker{padding:10px}.choice-options{grid-template-columns:minmax(0,1fr);max-height:240px}
 .choice-toolbar{align-items:stretch;flex-wrap:wrap}.choice-count{padding:2px 1px}
 .choice-option{min-height:44px}.actions .btn{min-height:44px}
 .tablewrap{border-radius:9px}.tablewrap table{min-width:520px}
}

/* Brighter pastel colour pattern — keep the interface light, never dark. */
:root{
 --cream:#fffaf2;--beige:#fff0df;--orange:#df8b45;--orange2:#f2b36f;
 --brown:#51443b;--taupe:#8b7b70;--white:#fffefa;--line:#eee3d7;
 --surface2:#fff8ee;--focus:#77a9cf;--green:#6b9c78;--red:#cf8178
}
body{background:#fffaf4;color:#51443b}
.side{background:#fffdf9;border-right-color:#f0e5da}
.serverbox{background:#fff5e9;border-color:#f2dfca}
.navlabel,.crumb,.muted{color:#928174}
.nav a{color:#76675c}
.nav a.active{background:#ffedda;color:#9a5c2d;box-shadow:inset 3px 0 #e9a15f}
.nav a:hover{background:#fff3e6}
.hero{background:linear-gradient(115deg,#fff0dc 0%,#fff8eb 52%,#f0f7ee 100%);border-color:#f0dfca}
.card{background:#fffefa;border-color:#eee4da}
.card:nth-child(4n+1){border-top:3px solid #efbd83}
.card:nth-child(4n+2){border-top:3px solid #b9d7c0}
.card:nth-child(4n+3){border-top:3px solid #b9d6e9}
.card:nth-child(4n){border-top:3px solid #d8c9e9}
.iconbox{background:#fff0dc;border-color:#f4dfc4}
.btn{background:#df914e;color:#fffdf8}
.btn:hover{background:#cb7b38}
.btn.secondary{background:#fff4e7;border-color:#efdcc7;color:#72543d}
.btn.danger{background:#d4867d;color:#fff}
.field label{color:#6f5e50}
.field input,.field select,.field textarea,.searchable-select input{border-color:#eee0d1;color:#51443b;background:#fffefa}
.field input:focus,.field select:focus,.field textarea:focus,.searchable-select input:focus,.choice-search:focus{border-color:#e5a96d;box-shadow:0 0 0 3px rgba(229,169,109,.16)}
th{background:#fff5e9;color:#837164}
.notice{background:#fff3df;border-color:#f1dfc5;color:#765b40}
.pill{background:#f5eee5;color:#776658}
.choice-picker{background:#fffefa;border-color:#eee1d3}
.choice-search{border-color:#eee0d1;color:#51443b}
.choice-count{color:#918072}
.choice-chip{border-color:#f0d9bf;background:#fff1df;color:#8b572f}
.choice-chip:hover{background:#ffe8ce}
.choice-option{border-color:#f0e7dd;background:#fffefa}
.choice-option:hover{border-color:#e8c69f;background:#fff7ed}
.choice-option input{accent-color:#df914e}
.choice-help{color:#928276}
@media(max-width:650px){
 body{background:#fffaf4}
 .hero{background:linear-gradient(140deg,#fff0dc,#fff8ec 62%,#f1f8ef)}
 .card:nth-child(n){border-top-width:2px}
}

@media(prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;scroll-behavior:auto!important}}

"""


def _header():
    return "<header class='top'><button class='mobile-nav-toggle' id='liveMenuBtn' type='button' aria-label='Open categories' aria-controls='liveSidebar' aria-expanded='false'>☰</button><div class='crumb'>Cinnamon / Server dashboard</div><div class='profile'>" + _esc(session.get("display_name", "Discord user")) + " <a class='btn secondary small' href='/logout'>Log out</a></div></header>"


def _nav(guild_id, tab):
    items = [("overview", "⌂", "Overview"), ("mind", "🐈", "Cinnamon Mind"), ("adventure", "🎣", "Adventures & Fishing"), ("automation", "⚡", "Automation Studio"), ("moderation", "🛡", "Moderation & Security"), ("engagement", "✦", "Levels & XP"), ("achievements", "🏆", "Achievements"), ("quests", "📜", "Quests"), ("friendship", "🐾", "Friendship"), ("companions", "🐱", "Companions"), ("economy", "🌿", "Catnip Economy"), ("giveaways", "🎉", "Giveaways"), ("hangry", "🐾", "Hangry Games"), ("community", "☻", "Community & AI"), ("message_studio", "✉", "Message Studio"), ("analytics", "▥", "Analytics"), ("activity_logs", "≋", "Activity Logs"), ("system", "⚙", "Settings & Logs")]
    links = "".join(
        f"<a class='{'active' if tab == key else ''}' href='/dashboard?guild_id={guild_id}&tab={key}'><span>{ico}</span>{label}</a>" for key, ico, label in items
    )
    return "<div class='navlabel'>Workspace</div><label class='field nav-search'><input id='dashboardNavSearch' type='search' placeholder='Search settings…' aria-label='Search dashboard settings'></label><nav class='nav' id='dashboardNav'>" + links + "</nav>"


def _shell(guild, guilds, tab, body, notice=None):
    gid = guild.id
    options = []
    for item in guilds:
        if str(item.get("id")) in {str(g.id) for g in (_bot.guilds if _bot else [])} and (item.get("owner") or (int(item.get("permissions", "0")) & 0x8)):
            selected = " selected" if str(item.get("id")) == str(gid) else ""
            options.append(f"<option value='{_esc(item['id'])}'{selected}>{_esc(item.get('name','Server'))}</option>")
    select = "<form action='/dashboard' method='get'><input type='hidden' name='tab' value='overview'><div class='serverbox'><label for='dashboardGuildSelect'>Selected server</label><select id='dashboardGuildSelect' name='guild_id'>" + "".join(options) + "</select><button class='btn secondary small' type='submit'>Switch server</button></div></form>"
    side = "<aside class='side' id='liveSidebar' aria-label='Dashboard categories'><button class='mobile-nav-close' id='liveMenuClose' type='button' aria-label='Close categories'>×</button><div class='brand'><img class='mascot' src='/static/cinnamon_mascot.svg' alt=''><span>Cinnamon <span style='font-weight:500;color:var(--taupe)'>Control</span></span></div>" + select + _nav(gid, tab) + "<div class='sidefoot'>Cozy controls, careful paws. 🐾<br>Changes are logged where configured.</div></aside><button class='nav-backdrop' id='liveNavBackdrop' type='button' aria-label='Close categories'></button>"
    notice_html = f"<div class='notice'>{_esc(notice)}</div>" if notice else ""
    title = f"{guild.name} • Cinnamon Dashboard"
    nav_script = "<script src='/static/dashboard-mobile.js' defer></script>"
    return _page("<div class='layout'>" + side + "<main class='main'>" + _header() + notice_html + body + "<div class='footer'>Cinnamon • Server controls are permission-checked. Keep your Discord account secure.</div></main></div>" + nav_script, title)


def _channel_select(guild, name, selected=None, allow_none=True, multiple=False, size=7):
    """Render a channel picker; multi-select is used for settings like XP."""
    channels = [c for c in guild.text_channels if c.permissions_for(guild.me).view_channel] if guild.me else guild.text_channels
    if multiple:
        if selected is None:
            selected_ids = set()
        elif isinstance(selected, (set, list, tuple)):
            selected_ids = {int(x) for x in selected}
        else:
            selected_ids = {int(selected)}
        boxes=[]
        for ch in channels:
            checked = " checked" if ch.id in selected_ids else ""
            boxes.append(
                f"<label class='choice-option' data-choice-label='{_esc(ch.name.lower())}'>"
                f"<input type='checkbox' name='{_esc(name)}' value='{ch.id}'{checked}>"
                f"<span>#{_esc(ch.name)}</span></label>"
            )
        selected_names = ", ".join("#" + ch.name for ch in channels if ch.id in selected_ids)
        return (
            "<div class='choice-picker' data-choice-picker>"
            f"<div class='choice-toolbar'><input class='choice-search' type='search' "
            f"placeholder='Search channels…' aria-label='Search channels for { _esc(name) }' "
            "autocomplete='off'><span class='choice-count' aria-live='polite'></span></div>"
            f"<div class='choice-selected' aria-live='polite'>{_esc(selected_names) if selected_names else 'No channels selected yet'}</div>"
            "<div class='choice-options'>" + "".join(boxes) + "</div>"
            "<small class='choice-help'>Search by channel name, then tick the channels you want. Your existing selections stay selected while you search.</small>"
            "</div>"
        )
    opts = ["<option value=''>— Not set —</option>"] if allow_none else []
    for ch in channels:
        try:
            sel = " selected" if selected is not None and int(selected) == ch.id else ""
        except (TypeError, ValueError):
            sel = ""
        opts.append(f"<option value='{ch.id}'{sel}>#{_esc(ch.name)}</option>")
    return f"<select name='{_esc(name)}'>" + "".join(opts) + "</select>"


def _member_select(guild, name="member_id", selected=None, allow_none=False, size=7):
    """Display member names in the dashboard while submitting their IDs internally."""
    members = sorted((m for m in guild.members if not m.bot), key=lambda m: (m.display_name or m.name or "").lower())
    selected_id = str(selected) if selected is not None else ""
    opts = ["<option value=''>— Select a member —</option>"] if allow_none else []
    for member in members:
        label = member.display_name or member.name
        tag = member.name if member.name != label else ""
        suffix = f" · @{tag}" if tag else ""
        sel = " selected" if str(member.id) == selected_id else ""
        opts.append(f"<option value='{member.id}'{sel}>{_esc(label + suffix)}</option>")
    return f"<select name='{_esc(name)}' size='{max(4, min(int(size), 15))}'>" + "".join(opts) + "</select>"

def _role_select(guild, name, selected=None, allow_none=True):
    roles = sorted([r for r in guild.roles if not r.is_default() and not r.managed], key=lambda r: r.position, reverse=True)
    opts = ["<option value=''>— Not set —</option>"] if allow_none else []
    for role in roles:
        try: sel = " selected" if selected is not None and str(selected).isdigit() and int(selected) == role.id else ""
        except (TypeError, ValueError): sel = ""
        opts.append(f"<option value='{role.id}'{sel}>@{_esc(role.name)}</option>")
    return f"<select name='{_esc(name)}'>" + "".join(opts) + "</select>"


def _role_multi_select(guild, name, selected=None):
    """Accessible checkbox picker that submits role IDs, not names typed by hand."""
    try: selected_ids={int(x) for x in (selected or [])}
    except (TypeError,ValueError): selected_ids=set()
    roles=sorted([r for r in guild.roles if not r.is_default() and not r.managed],key=lambda r:r.position,reverse=True)
    if not roles: return "<p class='muted'>No assignable roles found.</p>"
    boxes=[]
    for role in roles:
        checked=" checked" if role.id in selected_ids else ""
        boxes.append(
            f"<label class='choice-option' data-choice-label='{_esc(role.name.lower())}'>"
            f"<input type='checkbox' name='{_esc(name)}' value='{role.id}'{checked}>"
            f"<span>@{_esc(role.name)}</span></label>"
        )
    selected_names = ", ".join("@" + role.name for role in roles if role.id in selected_ids)
    return (
        "<div class='choice-picker' data-choice-picker>"
        f"<div class='choice-toolbar'><input class='choice-search' type='search' "
        f"placeholder='Search roles…' aria-label='Search roles for {_esc(name)}' autocomplete='off'>"
        "<span class='choice-count' aria-live='polite'></span></div>"
        f"<div class='choice-selected' aria-live='polite'>{_esc(selected_names) if selected_names else 'No roles selected yet'}</div>"
        "<div class='choice-options'>" + "".join(boxes) + "</div>"
        "<small class='choice-help'>Search by role name and select one or more. Existing selections are kept while filtering.</small>"
        "</div>"
    )


def _form(guild_id, action, content, button="Save changes", danger=False):
    style = " danger" if danger else ""
    return f"<form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{guild_id}'><input type='hidden' name='action' value='{_esc(action)}'>{content}<div class='actions'><button class='btn{style}' type='submit'>{_esc(button)}</button></div></form>"


async def _dashboard_is_admin(guild, uid):
    """Recheck membership and role permissions without trusting an OAuth/cache claim."""
    if uid == guild.owner_id:
        return True
    try:
        member = await guild.fetch_member(uid)
        roles = await guild.fetch_roles()
        member_role_ids = {role.id for role in member.roles}
        return any(role.permissions.administrator for role in roles
                   if role.id == guild.id or role.id in member_role_ids)
    except Exception:
        return False


def _get_access(sid, guilds, guild_id):
    guild_item = next((g for g in guilds if str(g.get("id")) == str(guild_id)), None)
    guild = _bot.get_guild(int(guild_id)) if _bot and str(guild_id).isdigit() else None
    if not guild_item or not guild or str(guild.id) not in {str(g.get("id")) for g in guilds}:
        abort(404)
    perms = int(guild_item.get("permissions", "0"))
    oauth_allowed = bool(guild_item.get("owner") or (perms & 0x8))
    if not oauth_allowed:
        abort(403)
    uid = int(_tokens[sid]["user"]["id"])
    if not _run_bot(_dashboard_is_admin(guild, uid)):
        abort(403)
    return guild, guild_item


def _dashboard_context():
    sid = session.get("dash_sid")
    if not sid or sid not in _tokens:
        return None
    guilds = _discord_get(sid, "/users/@me/guilds")
    bot_ids = {str(g.id) for g in (_bot.guilds if _bot else [])}
    eligible = [g for g in guilds if str(g.get("id")) in bot_ids and (g.get("owner") or (int(g.get("permissions", "0")) & 0x8))]
    return sid, guilds, eligible


def _count(mapping, gid):
    return sum(1 for key in mapping if isinstance(key, tuple) and key[0] == gid)


async def _apply_brain_settings(state, gid, *, independence_enabled, chat_actions_enabled,
                                prompts_enabled=None, ai_judgment_enabled=None):
    """A failed save can never turn a protective pause back on in this process."""
    advanced = state["advanced_features_data"]
    brain = advanced.setdefault("cinnamon_brain_v1", {}).setdefault(
        str(gid), {"independence_enabled": True})
    actions = advanced.setdefault("cinnamon_actions_v2", {}).setdefault(
        str(gid), {"enabled": False})
    previous_brain = bool(brain.get("independence_enabled", True))
    previous_actions = bool(actions.get("enabled", False))
    previous_prompts = bool(brain.get("prompts_enabled", False))
    previous_reasoning = bool(brain.get("ai_judgment_enabled", False))
    brain["independence_enabled"] = bool(independence_enabled)
    actions["enabled"] = bool(chat_actions_enabled)
    if prompts_enabled is not None:
        brain["prompts_enabled"] = bool(prompts_enabled)
    if ai_judgment_enabled is not None:
        brain["ai_judgment_enabled"] = bool(ai_judgment_enabled)
    saved = False
    try:
        saved = await state["bd_save_data"]()
    except Exception:
        pass
    finally:
        if not saved:
            # Also runs when a timed-out web request cancels this coroutine.
            if not independence_enabled:
                brain["independence_enabled"] = False
            elif brain.get("independence_enabled"):
                brain["independence_enabled"] = previous_brain
            if not chat_actions_enabled:
                actions["enabled"] = False
            elif actions.get("enabled"):
                actions["enabled"] = previous_actions
            if prompts_enabled is not None:
                brain["prompts_enabled"] = previous_prompts if prompts_enabled else False
            if ai_judgment_enabled is not None:
                brain["ai_judgment_enabled"] = previous_reasoning if ai_judgment_enabled else False
    if not saved:
        raise ValueError("The durable save could not be verified. Disabled switches remain off in this session; an unacknowledged write may still persist. Verify storage before restarting.")


def _mind(guild, state):
    """Server-local personality controls, with clearly locked safety boundaries."""
    gid = guild.id
    cfg = state.get("cinnamon_social", {}).get(str(gid), {}) or {}
    play = state.get("cinnamon_actions", {}).get(str(gid), {}) or {}
    advanced = state.get("advanced_features_data", {})
    brain = state.get("cinnamon_brain", advanced.get("cinnamon_brain_v1", {})).get(str(gid), {}) or {}
    actions = state.get("cinnamon_trusted_actions", advanced.get("cinnamon_actions_v2", {})).get(str(gid), {}) or {}
    storage = state.get("brain_storage", {})
    mood = state.get("cinnamon_moods", {}).get(str(gid), {}) or {}
    score = int(mood.get("score", 0))
    tier = "Delighted 😻" if score >= 35 else "Grumpy 😾" if score <= -35 else "Normal 🐈"
    channel = guild.get_channel(int(cfg.get("auto_channel", 0) or 0))
    next_at = int(cfg.get("next_at", 0) or 0)
    next_text = dt.datetime.fromtimestamp(next_at, dt.timezone.utc).strftime("%d %b · %H:%M UTC") if next_at > 0 else "Not scheduled"
    logs = state.get("category_log_channels", {}).get(gid, {})
    people = cfg.get("people", {}) or {}
    top = sorted(((str(uid), int(x.get("good", 0))) for uid, x in people.items()),
                 key=lambda v: -v[1])[:8]
    ranked = "".join("<div class='toggle'><span><b>" + _esc((guild.get_member(int(uid)).display_name if guild.get_member(int(uid)) else "Member "+uid)) +
                     "</b><small>" + str(points) + " nice points</small></span></div>" for uid, points in top) or "<p class='muted'>No visitor milestones recorded yet.</p>"
    name = _channel_select(guild, "channel_id", cfg.get("auto_channel"), allow_none=False)
    toggles = "".join(
        "<label class='toggle'><input type='checkbox' name='" + key + "'" + (" checked" if cfg.get(key, default) else "") +
        "><span><b>" + label + "</b><small>" + desc + "</small></span></label>"
        for key,default,label,desc in [
            ("auto_enabled", False, "Automatic Hangry Games", "Requires recent engagement and available permissions; often stays quiet. Two opt-in role pings maximum."),
            ("cameos_enabled", True, "Rare jealous one-liners", "Maximum one six-hour cameo per server; never tags anyone."),
            ("questions_enabled", True, "Funny questions after being called", "One per person per day; members can individually opt out."),
        ])
    form = ("<div class='field'><label>Surprise game destination</label>" + name +
            "<small>Choose an existing public channel by name. Cinnamon must be able to send there.</small></div>" + toggles +
            "<label class='toggle'><input type='checkbox' name='play_enabled'" +
            (" checked" if play.get("play_enabled", False) else "") +
            "><span><b>Consent-only cat jokes</b><small>Off by default. Each member must opt in, with a strict once-per-day limit.</small></span></label>")
    log_text = "".join("<div class='toggle'><b>" + _esc(label) + "</b><span>" +
                       _esc(guild.get_channel(logs.get(cat)).mention if logs.get(cat) and guild.get_channel(logs.get(cat)) else "Run /setup") +
                       "</span></div>" for cat,label in [("stuff","Personality"),("mood","Mood & Naughty List")])
    boundary_controls = (
        "<label class='toggle'><input type='checkbox' name='independence_enabled'" +
        (" checked" if brain.get("independence_enabled", True) else "") +
        "><span><b>Independent activities</b><small>Pause spontaneous games, questions and cameos. Direct requests remain available.</small></span></label>" +
        "<label class='toggle'><input type='checkbox' name='chat_actions_enabled'" +
        (" checked" if actions.get("enabled", False) else "") +
        "><span><b>Conversational actions</b><small>Off by default. Authorized Catnip adjustments and timeouts require confirmation and reliable storage.</small></span></label>" +
        "<label class='toggle'><input type='checkbox' name='prompts_enabled'" +
        (" checked" if brain.get("prompts_enabled", False) else "") +
        "><span><b>Community questions</b><small>Optional no-ping questions, only in Cinnamon's approved activity channel.</small></span></label>" +
        "<label class='toggle'><input type='checkbox' name='ai_judgment_enabled'" +
        (" checked" if brain.get("ai_judgment_enabled", False) else "") +
        "><span><b>AI activity advice</b><small>Optional Gemini decision from counts and mood only, never raw member conversations. Cinnamon may decide to stay quiet.</small></span></label>")
    health_text = "Ready" if storage.get("ready") else "Unavailable"
    if storage.get("pending"):
        health_text = "Waiting for transaction reconciliation"
    last_reason = str(cfg.get("last_brain_reason", "No activity decision yet")).replace("_", " ")
    return (f"<h1>🐈 Cinnamon Mind</h1><p class='muted'>Cinnamon's playful character, with hard limits on what she may do."
            f" AI writes dialogue; it cannot independently transfer Catnip, punish users or broadcast @everyone.</p>"
            f"<div class='grid'><article class='card third'><div class='statlabel'>Current mood</div><div class='stat'>{_esc(tier)}</div><p class='muted'>Score {score:+d}</p></article>"
            f"<article class='card third'><div class='statlabel'>Next activity check</div><div class='stat' style='font-size:18px'>{_esc(next_text)}</div></article>"
            f"<article class='card third'><div class='statlabel'>Favourite visitors</div><div class='stat'>{len(top)}</div></article>"
            f"<article class='card half'><h2>Activity and action boundaries</h2>{_form(gid,'brain_settings',boundary_controls,'Save boundaries')}"
            f"<p class='muted'>Storage: {_esc(health_text)} · {'Durable' if storage.get('durable') else 'Local or unavailable'} · {_esc(storage.get('status', 'unknown'))}</p>"
            f"<p class='muted'>Last activity decision: {_esc(last_reason)}</p></article>"
            f"<article class='card half'><h2>Autonomy & gameplay</h2>{_form(gid,'mind_settings',form,'Save Cinnamon settings')}</article>"
            f"<article class='card half'><h2>Safety lock</h2><p class='pill good'>🔒 AI @everyone: disabled</p>"
            f"<p class='muted'>Mass announcements require Discord Administrator + an explicit 60-second confirmation in Discord. "
            f"Conversation participation requires a direct ping, reply or Cinnamon's name; voluntary jealousy is only a rare one-line aside.</p>"
            f"<p class='muted'>No autonomous punishments or currency changes. Staff-requested conversational actions are separately checked and confirmed.</p></article>"
            f"<article class='card half'><h2>Favourite people</h2>{ranked}</article>"
            f"<article class='card half'><h2>Cinnamon's private logs</h2>{log_text}"
            f"<p class='muted'>Use /recall to fill missing mood/visitor snapshots without overwriting live state.</p></article></div>")


def _adventure(guild, state):
    gid = guild.id
    fish = state.get("cinnamon_wildlands_fishing", {}).get(str(gid), {}) or {}
    story = state.get("cinnamon_wildlands_story", {}).get(str(gid), {}) or {}
    windows = fish.get("merchant_windows", {}) or {}
    now = time.time()
    cards = []
    for kind,label,name in (("rod","Fishing Rod Merchant","fishing-rod-merchant"),
                            ("bait","Fishing Bait Merchant","fishing-bait-merchant")):
        rec = windows.get(kind, {}) or {}
        ch = guild.get_channel(int(rec.get("channel_id", 0) or 0))
        if ch is None:
            ch = next((c for c in guild.text_channels if c.name == name), None)
        ends = float(rec.get("ends_at", 0) or 0)
        is_public = bool(rec.get("manual_public", False) or ends > now)
        status = "Public" if is_public else "Private"
        ends_text = ("Until staff closes" if rec.get("manual_public") else
                     dt.datetime.fromtimestamp(ends,dt.timezone.utc).strftime("%H:%M UTC") if ends > now else "—")
        finder = rec.get("finder_id")
        finder_name = guild.get_member(int(finder)).display_name if str(finder).isdigit() and guild.get_member(int(finder)) else "No discoverer"
        opts = "".join("<option value='" + k + "'>" + text + "</option>" for k,text in [
            ("private","Hide from visitors"),("two_hours","Open for two hours"),("public","Keep public")])
        content = ("<input type='hidden' name='merchant_kind' value='" + kind + "'>"
                   "<div class='field'><label>Merchant visibility</label><select name='access'>" + opts +
                   "</select></div><label class='toggle'><input type='checkbox' name='announce'><span>"
                   "<b>Announce to merchant role</b><small>Off by default. Opening a channel never automatically pings a role.</small></span></label>")
        cards.append("<article class='card half'><h2>🏪 " + _esc(label) + "</h2><p class='pill " +
                     ("good" if is_public else "warn") + "'>" + status + "</p><div class='toggle'>"
                     "<b>Channel</b><span>" + _esc(ch.mention if ch else "Run /setup") +
                     "</span></div><div class='toggle'><b>Closes</b><span>" + _esc(ends_text) +
                     "</span></div><div class='toggle'><b>Finder</b><span>" + _esc(finder_name) +
                     "</span></div>" + _form(gid,"merchant_access",content,"Apply merchant access") + "</article>")
    catch_count = sum(sum(int(v) for v in p.get("fish", {}).values()) for p in fish.get("members", {}).values())
    finished = sum(bool(p.get("complete", False)) for p in story.values())
    rod_rows = "".join("<tr><td>" + _esc(x.get("name")) + "</td><td>" + str(x.get("price",0)) +
                       "</td><td>" + str(x.get("bonus",0)) + "</td></tr>" for x in state.get("wlf_rods", []))
    return (f"<h1>🎣 Adventures & Fishing</h1><p class='muted'>The Billion-Catnip Mystery, fishing, equipment and "
            f"the two private merchant channels. Shop visibility is managed separately from finder commissions.</p>"
            f"<div class='grid'><article class='card third'><div class='statlabel'>Story explorers</div><div class='stat'>{len(story)}</div></article>"
            f"<article class='card third'><div class='statlabel'>Story completions</div><div class='stat'>{finished}</div></article>"
            f"<article class='card third'><div class='statlabel'>Fish caught</div><div class='stat'>{catch_count}</div></article>"
            + "".join(cards) +
            f"<article class='card full'><h2>🎣 Fishing gear</h2><p class='muted'>Use /fishing cast to choose your bait and reel technique."
            f" Mood influences rarity, but technique does not change the underlying fish roll.</p>"
            f"<div class='tablewrap'><table><thead><tr><th>Rod</th><th>Base Catnip</th><th>Luck bonus</th></tr></thead>"
            f"<tbody>{rod_rows}</tbody></table></div></article>"
            f"<article class='card full'><h2>📖 Cinnamon story</h2><p class='muted'>26 choice-driven scenes across six regions."
            f" Story progress is tracked per member and the 100,000 Catnip finale remains a one-time reward."
            f" Members continue their personal story with /adventure story.</p></article></div>")


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
        ("Hangry Games", bool(state.get("hg_cog")), "hangry"),
    ]
    status_cards = "".join(f"<div class='toggle'><span><b>{_esc(name)}</b><small>{'Configured / enabled' if enabled else 'Not configured / disabled'}</small></span><span class='pill {'good' if enabled else 'warn'}'>{'ON' if enabled else 'OFF'}</span></div>" for name,enabled,_ in flags)
    ready = bool(_bot and _bot.is_ready())
    latency = f"{round(_bot.latency*1000)} ms" if ready else "Unavailable"
    storage = "Upstash configured" if state.get("BD_UPSTASH_URL") and state.get("BD_UPSTASH_TOKEN") else "Local file mode — redeploys may reset data"
    body = f"<section class='hero'><div><h1>Welcome to { _esc(guild.name) }</h1><p>Here's a quick look at your server and Cinnamon's connected systems.</p><div class='actions'><a class='btn' href='/dashboard?guild_id={gid}&tab=moderation'>Manage moderation</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=system'>Configure Cinnamon</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=message_studio'>Message Studio</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=analytics'>Analytics</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=activity_logs'>Activity logs</a></div></div><img class='heroimg' src='/static/cinnamon_mascot.svg' alt='Cinnamon'></section><div class='grid'>{cards}<article class='card half'><h2>Feature status</h2>{status_cards}</article><article class='card half'><h2>Cinnamon health</h2><p class='muted'>Live connection status from the running bot.</p><div class='toggle'><b>Gateway</b><span class='pill {'good' if ready else 'warn'}'>{'Online' if ready else 'Not ready'}</span></div><div class='toggle'><b>Storage</b><span class='pill {'good' if state.get('BD_UPSTASH_URL') and state.get('BD_UPSTASH_TOKEN') else 'warn'}'>{_esc(storage)}</span></div><div class='toggle'><b>Latency</b><span>{latency}</span></div><p class='muted'>For deeper diagnostics, use <b>/diagnostics</b> in Discord.</p></article></div>"
    return body


def _moderation(guild, state):
    gid = guild.id
    automod = state.get("automod_config", {}).get(gid, {}) or state.get("automod_config", {}).get(str(gid), {})
    antiraid = state.get("antiraid_config", {}).get(gid, {}) or state.get("antiraid_config", {}).get(str(gid), {})
    warns = state.get("warnings_data", {})
    warning_count = sum(len(v) for k, v in warns.items() if isinstance(k, tuple) and k[0] == gid)
    advanced = state.get("advanced_features_data", {}) or {}
    security = (advanced.get("cinnamon_security_guard_v1", {}) or {}).get(str(gid), {}) or {}
    controls = (advanced.get("cinnamon_moderation_controls_v1", {}) or {}).get(str(gid), {}) or {}
    onboarding = controls.get("onboarding", {}) or {}
    verify_channel = guild.get_channel(int(controls.get("verification_channel_id", 0) or 0))
    verify_role = guild.get_role(int(controls.get("verification_role_id", 0) or 0))
    autorole = guild.get_role(int(controls.get("autorole_id", 0) or 0))
    alert_channel = guild.get_channel(int(security.get("alert_channel_id", 0) or 0))
    welcome_channel = guild.get_channel(int(onboarding.get("welcome_channel_id", 0) or 0))
    rules_channel = guild.get_channel(int(onboarding.get("rules_channel_id", 0) or 0))
    appeal_channel = guild.get_channel(int(controls.get("appeal_channel_id", 0) or 0))
    appeals = controls.get("appeals", {}) or {}
    notes = controls.get("notes", {}) or {}

    modform = "<div class='formgrid'><div class='field'><label>Member</label>" + _member_select(guild, "member_id", allow_none=False) + "<small>Select the Discord name; Cinnamon keeps the user ID internally.</small></div><div class='field'><label>Action</label><select name='mod_action'><option value='timeout'>Timeout</option><option value='kick'>Kick</option><option value='ban'>Ban</option></select></div><div class='field'><label>Timeout duration (minutes)</label><input name='duration' type='number' min='1' max='40320' value='60'></div><div class='field'><label>Reason</label><input name='reason' maxlength='400' placeholder='Reason for moderation action'></div></div><p class='muted'>Actions require the matching Discord permission and bot role hierarchy. Bans and kicks cannot be undone from this page.</p>"
    modcard = "<article class='card half'><h2>Member moderation</h2><p class='muted'>Apply a Discord moderation action by selecting the member name.</p>" + _form(gid, "moderate", modform, "Apply action", True) + "</article>"

    words = "\n".join(str(w) for w in automod.get("words", []))
    automodform = "<div class='field'><label>Banned words or phrases</label><textarea name='words' maxlength='3000' placeholder='One per line'>" + _esc(words) + "</textarea><small>One phrase per line; maximum 50 entries, each up to 100 characters.</small></div>"
    for key, label, desc in [("spam", "Spam detection", "Remove rapid repeated messages."), ("mentions", "Mass mention protection", "Flag messages over the mention threshold."), ("invites", "Discord invite protection", "Remove Discord invite links.")]:
        automodform += f"<label class='toggle'><input type='checkbox' name='{key}' {'checked' if automod.get(key) else ''}><span><b>{label}</b><small>{desc}</small></span></label>"
    automodform += "<div class='field'><label>Mention threshold</label><input name='mention_threshold' type='number' min='2' max='20' value='" + _esc(automod.get("mention_threshold", 5)) + "'></div>"
    automodcard = "<article class='card half'><h2>AutoMod</h2><p class='muted'>These options map to Cinnamon's existing AutoMod settings.</p>" + _form(gid, "automod", automodform) + "</article>"

    raidform = "<label class='toggle'><input type='checkbox' name='enabled' " + ("checked" if antiraid.get("enabled") else "") + "><span><b>Enable join-spike alerts</b><small>Alerts only; does not automatically kick or lock the server.</small></span></label><div class='formgrid'><div class='field'><label>Join threshold</label><input type='number' name='threshold' min='2' max='100' value='" + _esc(antiraid.get("threshold", 5)) + "'></div><div class='field'><label>Time window (seconds)</label><input type='number' name='window' min='2' max='120' value='" + _esc(antiraid.get("window", 10)) + "'></div></div>"
    raidcard = "<article class='card full'><h2>Anti-raid alerts</h2>" + _form(gid, "antiraid", raidform) + "</article>"

    securityform = (
        "<label class='toggle'><input type='checkbox' name='antispam_enabled' " + ("checked" if security.get("antispam_enabled") else "") + "><span><b>Enable anti-spam timeouts</b><small>Timeouts members who exceed the configured message rate. Disabled by default.</small></span></label>"
        "<label class='toggle'><input type='checkbox' name='antinuke_enabled' " + ("checked" if security.get("antinuke_enabled") else "") + "><span><b>Enable anti-nuke audit alerts</b><small>Detect bursts of destructive admin actions and alert moderators; no automatic admin punishment.</small></span></label>"
        "<div class='formgrid'><div class='field'><label>Spam message threshold</label><input name='antispam_threshold' type='number' min='4' max='15' value='" + str(max(4, min(15, int(security.get("antispam_threshold", 6))))) + "'></div>"
        "<div class='field'><label>Spam time window (seconds)</label><input name='antispam_window' type='number' min='3' max='30' value='" + str(max(3, min(30, int(security.get("antispam_window", 8))))) + "'></div>"
        "<div class='field'><label>Timeout duration (seconds)</label><input name='antispam_timeout' type='number' min='30' max='3600' value='" + str(max(30, min(3600, int(security.get("antispam_timeout", 60))))) + "'></div>"
        "<div class='field'><label>Anti-nuke action threshold</label><input name='antinuke_threshold' type='number' min='2' max='8' value='" + str(max(2, min(8, int(security.get("antinuke_threshold", 3))))) + "'></div>"
        "<div class='field'><label>Private security alert channel</label>" + _channel_select(guild, "alert_channel_id", security.get("alert_channel_id")) + "</div></div>"
    )
    securitycard = "<article class='card full'><h2>Anti-spam & anti-nuke</h2><p class='muted'>Anti-spam is opt-in. Anti-nuke monitors the Discord audit log and alerts on rapid destructive actions. Cinnamon does not automatically remove administrator roles or punish server owners.</p><p class='muted'>Current alert channel: " + _esc(alert_channel.mention if alert_channel else "Use the main moderation log") + "</p>" + _form(gid, "security_settings", securityform, "Save security settings") + "</article>"

    onboardingform = (
        "<div class='formgrid'><div class='field'><label>Automatic role for new members</label>" + _role_select(guild, "autorole_id", controls.get("autorole_id")) + "</div>"
        "<div class='field'><label>Verification panel channel</label>" + _channel_select(guild, "verification_channel_id", controls.get("verification_channel_id")) + "</div>"
        "<div class='field'><label>Verified role</label>" + _role_select(guild, "verification_role_id", controls.get("verification_role_id")) + "</div>"
        "<div class='field'><label>Welcome channel</label>" + _channel_select(guild, "welcome_channel_id", onboarding.get("welcome_channel_id")) + "</div>"
        "<div class='field'><label>Rules channel</label>" + _channel_select(guild, "rules_channel_id", onboarding.get("rules_channel_id")) + "</div></div>"
        "<p class='muted'>Verification channel and role must either both be selected or both be blank. The verified role must be below Cinnamon's bot role.</p>"
    )
    verify_button = "<form method='post' action='/dashboard/action'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='verification_publish'><button class='btn secondary' type='submit'>Publish verification panel</button></form>"
    onboardingcard = "<article class='card full'><h2>Verification & member onboarding</h2><div class='toggle'><span>Verification panel</span><b>" + _esc(verify_channel.mention if verify_channel else "Not configured") + "</b></div><div class='toggle'><span>Verified role</span><b>" + _esc(verify_role.mention if verify_role else "Not configured") + "</b></div><div class='toggle'><span>Autorole</span><b>" + _esc(autorole.mention if autorole else "Disabled") + "</b></div><div class='toggle'><span>Welcome / rules</span><b>" + _esc((welcome_channel.mention if welcome_channel else "No welcome") + " · " + (rules_channel.mention if rules_channel else "No rules")) + "</b></div>" + _form(gid, "moderation_controls_settings", onboardingform, "Save onboarding settings") + verify_button + "</article>"

    appeal_rows = []
    for appeal_id, appeal in list(appeals.items())[-15:][::-1]:
        decision = str(appeal.get("status", "pending"))
        action_forms = ""
        if decision == "pending":
            action_forms = "<div class='actions'>"
            for label, value in (("Approve", "approved"), ("Decline", "declined")):
                action_forms += "<form method='post' action='/dashboard/action'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='dashboard_appeal_review'><input type='hidden' name='appeal_id' value='" + _esc(str(appeal_id)) + "'><input type='hidden' name='decision' value='" + value + "'><button class='btn " + ("secondary" if value == "approved" else "danger") + " small'>" + label + "</button></form>"
            action_forms += "</div>"
        appeal_rows.append("<tr><td>" + _esc(str(appeal_id)) + "</td><td>" + _esc(str(appeal.get("user_id", ""))) + "</td><td>" + _esc(str(appeal.get("details", ""))[:180]) + "</td><td>" + _esc(decision.title()) + "</td><td>" + action_forms + "</td></tr>")
    appeal_rows_html = "".join(appeal_rows) or "<tr><td colspan='5'>No appeals have been submitted.</td></tr>"
    appeal_form = "<div class='field'><label>Private appeal channel</label>" + _channel_select(guild, "appeal_channel_id", controls.get("appeal_channel_id")) + "</div><p class='muted'>Members submit appeals in a direct message to Cinnamon using /appeal submit. This channel must be private to moderators.</p>"
    appeal_card = "<article class='card full'><h2>Moderation appeals</h2><p class='muted'>Current channel: " + _esc(appeal_channel.mention if appeal_channel else "Disabled") + " · Pending: " + str(sum(1 for a in appeals.values() if a.get("status") == "pending")) + "</p>" + _form(gid, "appeal_settings", appeal_form, "Save appeal channel") + "<div class='tablewrap'><table><thead><tr><th>Appeal ID</th><th>Member ID</th><th>Details preview</th><th>Status</th><th>Review</th></tr></thead><tbody>" + appeal_rows_html + "</tbody></table></div></article>"
    note_rows = []
    for member_id, member_notes in notes.items():
        for note_id, note in list((member_notes or {}).items())[-10:]:
            note_rows.append("<tr><td>" + _esc(str(member_id)) + "</td><td>" + _esc(str(note_id)) + "</td><td>" + _esc(str(note.get("text", ""))[:180]) + "</td><td>" + _esc(str(note.get("created_by", ""))) + "</td></tr>")
    note_rows_html = "".join(note_rows[-30:]) or "<tr><td colspan='4'>No private moderator notes.</td></tr>"
    notes_card = "<article class='card full'><h2>Private moderator notes</h2><p class='muted'>Only administrators and moderators with the appropriate permissions can view or edit these notes.</p><div class='tablewrap'><table><thead><tr><th>Member ID</th><th>Note ID</th><th>Note preview</th><th>Added by</th></tr></thead><tbody>" + note_rows_html + "</tbody></table></div></article>"
    body = f"<h1>Moderation & safety</h1><p class='muted'>Manage member actions, message filters, join-spike alerts, anti-spam, anti-nuke, private moderator notes, appeals, verification and onboarding.</p><div class='grid'><article class='card third'><div class='statlabel'>Recorded warnings</div><div class='stat'>{warning_count:,}</div></article><article class='card third'><div class='statlabel'>AutoMod</div><div class='stat'><span class='pill {'good' if automod else 'warn'}'>{'Configured' if automod else 'Off'}</span></div></article><article class='card third'><div class='statlabel'>Anti-raid</div><div class='stat'><span class='pill {'good' if antiraid.get('enabled') else 'warn'}'>{'Enabled' if antiraid.get('enabled') else 'Disabled'}</span></div></article>{modcard}{automodcard}{raidcard}{securitycard}{onboardingcard}{appeal_card}{notes_card}</div>"
    return body


def _engagement(guild,state):
    gid=guild.id; xp=state.get("xp_data",{}); levels=state.get("level_roles",{}).get(gid,{})
    channels=state.get("xp_channels",{}).get(gid,set()); per=state.get("xp_per_message",{}).get(gid,20)
    top=sorted(((uid,val) for (g,uid),val in xp.items() if g==gid),key=lambda x:x[1],reverse=True)[:10]
    level_fn=state.get("level_from_xp",lambda n:0)
    rows="".join(f"<tr><td>{i}</td><td>{_esc((guild.get_member(uid).display_name if guild.get_member(uid) else 'Member '+str(uid)))}</td><td>{int(val):,}</td><td>{int(level_fn(val))}</td></tr>" for i,(uid,val) in enumerate(top,1)) or "<tr><td colspan='4'>No XP data yet.</td></tr>"
    role_rows="".join(f"<tr><td>{level}</td><td>{_esc((guild.get_role(rid).name if guild.get_role(rid) else 'Missing role'))}</td><td><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='levelrole_remove'><input type='hidden' name='level' value='{level}'><button class='btn secondary small' type='submit'>Remove</button></form></td></tr>" for level,rid in sorted(levels.items()) if str(level).isdigit()) or "<tr><td colspan='3'>No level roles configured.</td></tr>"
    channel_list="".join(f"<span class='pill good'>#{_esc(guild.get_channel(cid).name if guild.get_channel(cid) else str(cid))}</span> " for cid in sorted(channels)) or "<span class='pill warn'>No channels selected — XP is disabled</span>"
    add_channels=_channel_select(guild,"channel_id",selected=channels,allow_none=False,multiple=True,size=8)
    formcontent="<div class='formgrid'><div class='field'><label>Level (1–200)</label><input name='level' type='number' min='1' max='200' required></div><div class='field'><label>Reward role</label>"+_role_select(guild,"role_id",allow_none=False)+"</div></div>"
    xpcontent=f"<div class='formgrid'><div class='field'><label>XP per eligible message</label><input name='xp_per_message' type='number' min='1' max='1000' value='{int(per)}' required></div><div class='field'><label>XP channels</label>{add_channels}<small>Hold Ctrl/Cmd to select multiple channels. Saving replaces the current XP channel set.</small></div></div><p class='muted'>Cinnamon awards XP only in selected channels, with its built-in 30-second per-member cooldown. Remove channels below when needed.</p>"
    channel_rows="".join(f"<tr><td>#{_esc(guild.get_channel(cid).name if guild.get_channel(cid) else str(cid))}</td><td><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='xp_channel_remove'><input type='hidden' name='channel_id' value='{cid}'><button class='btn secondary small' type='submit'>Remove</button></form></td></tr>" for cid in sorted(channels)) or "<tr><td colspan='2'>No XP channels configured.</td></tr>"
    body=f"<h1>Levels & XP</h1><p class='muted'>Control Cinnamon's message XP, eligible channels and level-role rewards. Level roles are intentionally not created by setup.</p><div class='grid'><article class='card third'><div class='statlabel'>Members with XP</div><div class='stat'>{_count(xp,gid):,}</div></article><article class='card third'><div class='statlabel'>XP per message</div><div class='stat'>{int(per):,}</div></article><article class='card third'><div class='statlabel'>XP channels</div><div class='stat'>{len(channels):,}</div></article><article class='card half'><h2>XP settings</h2>{_form(gid,'xp_settings',xpcontent,'Save XP settings')}<div class='rule'></div><div>{channel_list}</div><div class='tablewrap'><table><thead><tr><th>Eligible channel</th><th></th></tr></thead><tbody>{channel_rows}</tbody></table></div></article><article class='card half'><h2>Level rewards</h2><div class='tablewrap'><table><thead><tr><th>Level</th><th>Role</th><th></th></tr></thead><tbody>{role_rows}</tbody></table></div><div class='rule'></div>{_form(gid,'levelrole_add',formcontent,'Add level reward')}</article><article class='card full'><h2>XP leaderboard</h2><div class='tablewrap'><table><thead><tr><th>#</th><th>Member</th><th>XP</th><th>Level</th></tr></thead><tbody>{rows}</tbody></table></div></article></div>"
    return body


def _achievements(guild,state):
    gid=guild.id; data=state.get("achievement_data",{}); cfg=state.get("achievement_config",{}).get(gid,{})
    normal=state.get("ACHIEVEMENTS",{}); secret=state.get("SECRET_ACHIEVEMENTS",{}); admin=state.get("ADMIN_ACHIEVEMENT",{}) or {}
    users=[(uid,v) for (g,uid),v in data.items() if g==gid and isinstance(v,dict)]
    unlocked=sum(len(v.get("unlocked",[])) for _,v in users); unique_users=len(users)
    log_id=cfg.get("log_channel") or state.get("category_log_channels",{}).get(gid,{}).get("achievements")
    logch=guild.get_channel(log_id) if log_id else None
    role_names=sorted({str(a.get("role")).strip() for a in list(normal.values())+list(secret.values())+[admin] if a.get("role")})
    missing=[n for n in role_names if not any(r.name==n for r in guild.roles)]
    rows="".join(f"<tr><td><b>{_esc(aid)}</b><div class='muted'>{_esc(a.get('name','Unnamed'))}</div></td><td>{_esc(a.get('description',''))}</td><td>{'Secret' if aid in secret else 'Normal'}</td><td>{'Enabled' if a.get('enabled',True) else 'Disabled'}</td></tr>" for aid,a in list(normal.items())[:100]) or "<tr><td colspan='4'>No achievement definitions exposed.</td></tr>"
    secrets_count=len(secret); enabled=cfg.get("enabled",True)
    achievement_form="<div class='formgrid'><div class='field'><label>Achievement log channel</label>"+_channel_select(guild,"channel_id",log_id)+"</div></div><label class='toggle'><input type='checkbox' name='enabled' "+("checked" if enabled else "")+"><span><b>Enable achievement tracking</b><small>Disabling pauses achievement processing; existing unlock data is retained.</small></span></label>"
    role_readiness_rows = ''.join(f"<tr><td>@{_esc(n)}</td><td><span class='pill {'good' if n not in missing else 'warn'}'>{'Ready' if n not in missing else 'Missing'}</span></td></tr>" for n in role_names)
    return f"<h1>Achievements</h1><p class='muted'>Monitor achievements and manage the server-level configuration without exposing every achievement command in the web panel.</p><div class='grid'><article class='card third'><div class='statlabel'>Normal achievements</div><div class='stat'>{len(normal):,}</div></article><article class='card third'><div class='statlabel'>Secret achievements</div><div class='stat'>{secrets_count:,}</div></article><article class='card third'><div class='statlabel'>Members tracked</div><div class='stat'>{unique_users:,}</div></article><article class='card half'><h2>Achievement system</h2><div class='toggle'><b>Status</b><span class='pill {'good' if enabled else 'warn'}'>{'Enabled' if enabled else 'Disabled'}</span></div><div class='toggle'><b>Total unlock records</b><span>{unlocked:,}</span></div><div class='toggle'><b>Achievement logs</b><span>{_esc(logch.mention if logch else 'Not configured')}</span></div><div class='toggle'><b>Reward roles missing</b><span>{len(missing):,}</span></div><p class='muted'>Use Discord's achievement commands for individual awards, revokes and definition editing. The dashboard focuses on server configuration and visibility.</p>{_form(gid,'achievement_settings',achievement_form,'Save achievement settings')}</article><article class='card half'><h2>Reward-role readiness</h2><div class='tablewrap'><table><thead><tr><th>Role</th><th>Status</th></tr></thead><tbody>{role_readiness_rows}</tbody></table></div></article><article class='card full'><h2>Achievement catalog</h2><div class='tablewrap'><table><thead><tr><th>ID / Name</th><th>Description</th><th>Type</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div></article></div>"


def _quests(guild,state):
    gid=guild.id; qdata=state.get("quest_data",{}).get(gid,{}) or {}; qcfg=state.get("quest_config",{}).get(gid,{}) or {}
    daily_defs=state.get("DAILY_QUESTS",{}); weekly_defs=state.get("WEEKLY_QUESTS",{})
    daily_ids=qdata.get("daily_ids",[]) if isinstance(qdata,dict) else []; weekly_ids=qdata.get("weekly_ids",[]) if isinstance(qdata,dict) else []
    log_id=state.get("category_log_channels",{}).get(gid,{}).get("quests"); logch=guild.get_channel(log_id) if log_id else None
    def rows(ids,pool):
        out=[]
        for qid in ids if isinstance(ids,list) else []:
            q=pool.get(qid,{})
            out.append(f"<tr><td><b>{_esc(q.get('name',qid))}</b></td><td>{_esc(q.get('desc',q.get('description','')))}</td><td>{int(q.get('qp',0)):,} QP + {int(q.get('xp',0)):,} XP</td></tr>")
        return ''.join(out) or "<tr><td colspan='3'>No rotation has been generated yet.</td></tr>"
    role=qcfg.get("quest_master_role"); role_obj=guild.get_role(int(role)) if str(role).isdigit() else None
    role_form="<div class='field'><label>Quest Master role</label>"+_role_select(guild,"role_id",role)+"</div>"
    return f"<h1>Quests</h1><p class='muted'>Daily and weekly quest visibility, Quest Master configuration and logging. Quest completion remains in Discord.</p><div class='grid'><article class='card third'><div class='statlabel'>Daily active</div><div class='stat'>{len(daily_ids):,}</div></article><article class='card third'><div class='statlabel'>Weekly active</div><div class='stat'>{len(weekly_ids):,}</div></article><article class='card third'><div class='statlabel'>Quest log</div><div class='stat'>{_esc(logch.name if logch else 'Off')}</div></article><article class='card half'><h2>Daily rotation</h2><div class='tablewrap'><table><thead><tr><th>Quest</th><th>Description</th><th>Reward</th></tr></thead><tbody>{rows(daily_ids,daily_defs)}</tbody></table></div></article><article class='card half'><h2>Weekly rotation</h2><div class='tablewrap'><table><thead><tr><th>Quest</th><th>Description</th><th>Reward</th></tr></thead><tbody>{rows(weekly_ids,weekly_defs)}</tbody></table></div></article><article class='card full'><h2>Quest settings</h2><div class='toggle'><b>Quest Master role</b><span>{_esc(role_obj.mention if role_obj else 'Not configured')}</span></div>{_form(gid,'quest_settings',role_form,'Save Quest Master role')}<p class='muted'>The full quest-definition editor stays in Discord so the dashboard does not become a duplicate of every Cinnamon command.</p></article></div>"


def _friendship(guild,state):
    gid=guild.id; fd=state.get("friendship_data",{}); entries=[]
    thresholds=[(0,'Stranger'),(25,'Familiar Face'),(75,'Friend'),(200,'Trusted Human'),(500,"Cinnamon's Best Friend"),(1000,"Cinnamon's Chosen Human")]
    for (g,u),v in fd.items():
        if g==gid and isinstance(v,dict): entries.append((u,int(v.get('points',0)),int(v.get('level',0))))
    entries.sort(key=lambda x:x[1],reverse=True); rows=''.join(f"<tr><td>{i}</td><td>{_esc(guild.get_member(u).display_name if guild.get_member(u) else 'Member '+str(u))}</td><td>{pts:,}</td><td>{lvl}</td></tr>" for i,(u,pts,lvl) in enumerate(entries[:25],1)) or "<tr><td colspan='4'>No friendship data yet.</td></tr>"
    log_id=state.get("category_log_channels",{}).get(gid,{}).get("friendship"); ch=guild.get_channel(log_id) if log_id else None
    levels=''.join(f"<div class='toggle'><b>{name}</b><span>{points:,} points</span></div>" for points,name in thresholds)
    return f"<h1>Cinnamon Friendship</h1><p class='muted'>See friendship progress and server-level logging. Individual friendship interactions stay in Discord.</p><div class='grid'><article class='card third'><div class='statlabel'>Tracked humans</div><div class='stat'>{len(entries):,}</div></article><article class='card third'><div class='statlabel'>Friendship log</div><div class='stat'>{_esc(ch.name if ch else 'Off')}</div></article><article class='card third'><div class='statlabel'>Highest points</div><div class='stat'>{entries[0][1] if entries else 0:,}</div></article><article class='card half'><h2>Friendship levels</h2>{levels}</article><article class='card half'><h2>Leaderboard</h2><div class='tablewrap'><table><thead><tr><th>#</th><th>Member</th><th>Points</th><th>Level</th></tr></thead><tbody>{rows}</tbody></table></div></article></div>"


def _economy(guild,state):
    gid=guild.id; balances=state.get("economy_balances",{}); inventory=state.get("economy_inventory",{})
    entries=sorted(((uid,val) for (g,uid),val in balances.items() if g==gid),key=lambda x:x[1],reverse=True)[:10]
    rows="".join(f"<tr><td>{i}</td><td>{_esc(guild.get_member(uid).display_name if guild.get_member(uid) else 'Member '+str(uid))}</td><td>{int(val):,} 🌿</td><td>{sum(int(q) for q in inventory.get((gid,uid),{}).values())}</td></tr>" for i,(uid,val) in enumerate(entries,1)) or "<tr><td colspan='4'>No economy balances yet.</td></tr>"
    total=sum(int(v) for (g,_),v in balances.items() if g==gid); users=_count(balances,gid)
    shop=state.get("ECONOMY_ITEMS",{}); items=[]
    for key,item in shop.items():
        form=f"<form method='post' action='/dashboard/action' class='formgrid'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='economy_item_save'><input type='hidden' name='item_id' value='{_esc(key)}'><div class='field'><label>Name</label><input name='name' maxlength='80' value='{_esc(item.get('name',key))}' required></div><div class='field'><label>Price (Catnip)</label><input name='price' type='number' min='1' max='10000000' value='{int(item.get('price',1))}' required></div><div class='field'><label>Emoji</label><input name='emoji' maxlength='8' value='{_esc(item.get('emoji','🐾'))}'></div><div class='field'><label>Per-member limit (0 = unlimited)</label><input name='max_per_person' type='number' min='0' max='999999' value='{int(item.get('max_per_person',0))}'></div><div class='field' style='grid-column:1/-1'><label>Description</label><input name='description' maxlength='300' value='{_esc(item.get('description',''))}'></div><div class='actions' style='grid-column:1/-1'><button class='btn small' type='submit'>Save item</button></div></form><form method='post' action='/dashboard/action' onsubmit='return confirm(&quot;Remove this shop item? Existing inventory will be kept but the item can no longer be purchased or used.&quot;);'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='economy_item_remove'><input type='hidden' name='item_id' value='{_esc(key)}'><button class='btn danger small' type='submit'>Remove item</button></form>"
        items.append(f"<tr><td>{_esc(key)}<div class='muted'>{_esc(item.get('emoji','🐾'))} {_esc(item.get('name',key))}</div></td><td colspan='2'>{form}</td></tr>")
    item_rows="".join(items) or "<tr><td colspan='3'>No shop items available.</td></tr>"
    add_form="<div class='formgrid'><div class='field'><label>Item ID (unique)</label><input name='item_id' maxlength='40' pattern='[a-zA-Z0-9_-]+' required></div><div class='field'><label>Name</label><input name='name' maxlength='80' required></div><div class='field'><label>Price</label><input name='price' type='number' min='1' max='10000000' required></div><div class='field'><label>Emoji</label><input name='emoji' maxlength='8' value='🐾'></div><div class='field'><label>Per-member limit (0 = unlimited)</label><input name='max_per_person' type='number' min='0' max='999999' value='0'></div><div class='field'><label>Description</label><input name='description' maxlength='300'></div></div>"
    add_card="<article class='card full'><h2>Add shop item</h2>"+_form(gid,"economy_item_add",add_form,"Create item")+"</article>"
    income_cfg=state.get("economy_income_roles",{}).get(gid,{}) or state.get("economy_income_roles",{}).get(str(gid),{})
    income_rows=[]
    for role_id,cfg in income_cfg.items():
        role=guild.get_role(int(role_id)) if str(role_id).isdigit() else None
        if not role: role_name=f"Missing role ({role_id})"
        else: role_name=role.mention
        amount=max(0,int(cfg.get("amount",0))); cooldown=max(60,int(cfg.get("cooldown",3600)))
        interval=int(cfg.get("interval",max(1,cooldown//60))); unit=str(cfg.get("unit","minute"))
        income_rows.append(f"<div class='toggle'><span><b>{_esc(role_name)}</b><small>{amount:,} Catnip every {interval} {_esc(unit)}(s)</small></span><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='economy_income_remove'><input type='hidden' name='role_id' value='{_esc(role_id)}'><button class='btn danger small' type='submit'>Remove</button></form></div>")
    income_add="<div class='formgrid'><div class='field'><label>Income role</label>"+_role_select(guild,"role_id",allow_none=False)+"</div><div class='field'><label>Catnip per collection</label><input name='amount' type='number' min='1' max='1000000' value='100' required></div><div class='field'><label>Interval</label><input name='interval' type='number' min='1' max='1000' value='1' required></div><div class='field'><label>Time unit</label><select name='unit'><option value='minute'>Minutes</option><option value='hour'>Hours</option><option value='day'>Days</option><option value='week'>Weeks</option></select></div></div>"
    income_card="<article class='card full'><h2>Role-based Catnip income</h2><p class='muted'>Members with a configured role can collect its recurring income using Cinnamon's existing collect command. Role income changes are audited and saved to the bot's data store.</p>"+(''.join(income_rows) or "<p class='muted'>No role income rules configured.</p>")+_form(gid,"economy_income_add",income_add,"Save role income")+"</article>"
    body=f"<h1>Catnip economy</h1><p class='muted'>Manage the shared shop catalog, role income rules, and live economy statistics. Member balances and inventories are preserved.</p><div class='grid'><article class='card third'><div class='statlabel'>Economy members</div><div class='stat'>{users:,}</div></article><article class='card third'><div class='statlabel'>Total Catnip in circulation</div><div class='stat'>{total:,} 🌿</div></article><article class='card third'><div class='statlabel'>Shop items</div><div class='stat'>{len(shop)}</div></article><article class='card half'><h2>Top balances</h2><div class='tablewrap'><table><thead><tr><th>#</th><th>Member</th><th>Balance</th><th>Items</th></tr></thead><tbody>{rows}</tbody></table></div></article><article class='card half'><h2>Economy configuration</h2><p class='muted'>Daily reward: <b>{int(state.get('ECONOMY_DAILY_REWARD',150)):,} Catnip</b></p><p class='muted'>Work range: <b>{int(state.get('ECONOMY_WORK_MIN',50)):,}–{int(state.get('ECONOMY_WORK_MAX',150)):,}</b></p><p class='muted'>Work cooldown: <b>{int(state.get('ECONOMY_WORK_COOLDOWN',600))//60} minutes</b></p><p class='muted'>Economy logs: {_esc(guild.get_channel(state.get('economy_log_channels',{}).get(gid)).mention if guild.get_channel(state.get('economy_log_channels',{}).get(gid)) else 'Not configured')}</p></article><article class='card full'><h2>Catnip shop catalog</h2><div class='tablewrap'><table><thead><tr><th>Item</th><th colspan='2'>Edit fields</th></tr></thead><tbody>{item_rows}</tbody></table></article>{add_card}{income_card}</div>"
    gift_form=(
        "<div class='field'><label>Choose a member by name</label>" +
        _member_select(guild,"member_id",allow_none=True,size=7) +
        "<small>Names are displayed, Discord IDs are submitted internally. This transfers Catnip from your OWN wallet.</small></div>"
        "<div class='field'><label>Catnip amount</label><input type='number' name='amount' min='1' max='10000000' required></div>"
        "<input type='hidden' name='transfer_nonce' value='" + _esc(secrets.token_urlsafe(24)) + "'>"
        "<p class='muted'>A positive-only transfer; saved with an idempotency key and recorded in Economy Logs.</p>")
    body=body.replace("</div>", "</div>", 1)  # keep old layout unchanged.
    body=body[:-6] + "<article class='card full'><h2>🌿 Give Catnip to a member</h2>" + _form(gid,"economy_transfer",gift_form,"Transfer Catnip") + "</article></div>"
    return body


def _automation(guild,state):
    gid=guild.id
    welcome=state.get("welcome_config",{}).get(gid,{}) or state.get("welcome_config",{}).get(str(gid),{})
    goodbye=state.get("goodbye_config",{}).get(gid,{}) or state.get("goodbye_config",{}).get(str(gid),{})
    ai=state.get("ai_channels",{}).get(gid) or state.get("ai_channels",{}).get(str(gid))
    automod=state.get("automod_config",{}).get(gid,{}) or state.get("automod_config",{}).get(str(gid),{})
    antiraid=state.get("antiraid_config",{}).get(gid,{}) or state.get("antiraid_config",{}).get(str(gid),{})
    schedules=[cfg for cfg in (state.get("giveaway_schedules",{}) or {}).values() if int(cfg.get("guild_id",0))==gid and cfg.get("enabled",True)]
    def pill(on): return "<span class='pill good'>Active</span>" if on else "<span class='pill warn'>Not configured</span>"
    cards=(f"<article class='card third'><div class='statlabel'>Welcome messages</div><div class='stat'>{'On' if welcome else 'Off'}</div>{pill(bool(welcome))}</article>"
           f"<article class='card third'><div class='statlabel'>Goodbye messages</div><div class='stat'>{'On' if goodbye else 'Off'}</div>{pill(bool(goodbye))}</article>"
           f"<article class='card third'><div class='statlabel'>Cinnamon conversations</div><div class='stat'>{'On' if ai else 'Off'}</div>{pill(bool(ai))}</article>"
           f"<article class='card third'><div class='statlabel'>AutoMod rules</div><div class='stat'>{'On' if automod else 'Off'}</div>{pill(bool(automod))}</article>"
           f"<article class='card third'><div class='statlabel'>Anti-raid</div><div class='stat'>{'On' if antiraid.get('enabled') else 'Off'}</div>{pill(bool(antiraid.get('enabled')))}</article>"
           f"<article class='card third'><div class='statlabel'>Recurring giveaways</div><div class='stat'>{len(schedules)}</div>{pill(bool(schedules))}</article>")
    welcome_content="<div class='formgrid'><div class='field'><label>Welcome channel</label>"+_channel_select(guild,"channel_id",welcome.get("channel_id"))+"</div><div class='field'><label>Message template</label><input name='message' maxlength='800' required value='"+_esc(welcome.get("message","Welcome {member} to {server}! 🐾"))+"'></div></div><p class='muted'>Supported placeholders: {member} and {server}.</p>"
    goodbye_content="<div class='formgrid'><div class='field'><label>Goodbye channel</label>"+_channel_select(guild,"channel_id",goodbye.get("channel_id"))+"</div><div class='field'><label>Message template</label><input name='message' maxlength='800' required value='"+_esc(goodbye.get("message","Goodbye {member}. Thanks for visiting {server}! 🐾"))+"'></div></div><p class='muted'>Supported placeholders: {member} and {server}.</p>"
    ai_content="<div class='field'><label>Cinnamon conversation channel (invitation-only)</label>"+_channel_select(guild,"channel_id",ai)+"</div><p class='muted'>Cinnamon only responds when someone pings, replies to her, or calls her by name. Use the Community & AI page to configure related options.</p>"
    quick="<div class='actions'><a class='btn secondary' href='/dashboard?guild_id="+str(gid)+"&tab=moderation'>Configure AutoMod & anti-raid</a><a class='btn secondary' href='/dashboard?guild_id="+str(gid)+"&tab=giveaways'>Manage giveaway schedules</a><a class='btn secondary' href='/dashboard?guild_id="+str(gid)+"&tab=system'>Manage logs & recovery</a></div>"
    return ("<h1>Automation Studio</h1><p class='muted'>A single place to monitor Cinnamon's event-driven automations and jump into their detailed settings. Changes are permission-checked and saved through the existing bot data store.</p><div class='grid'>"+cards+"</div><div class='grid'><article class='card half'><h2>Welcome automation</h2>"+_form(gid,"welcome",welcome_content,"Save welcome rule")+"</article><article class='card half'><h2>Goodbye automation</h2>"+_form(gid,"goodbye",goodbye_content,"Save goodbye rule")+"</article><article class='card full'><h2>Cinnamon conversations</h2>"+_form(gid,"ai_channel",ai_content,"Save AI channel")+"</article><article class='card full'><h2>Rule management</h2><p class='muted'>AutoMod, anti-raid, XP filters, scheduled giveaways, and log routing are managed by their dedicated pages. This hub shows their current state without pretending disabled rules are running.</p>"+quick+"</article></div>")



def _tickets(guild,state):
    gid=guild.id
    root=(state.get("advanced_features_data",{}) or {}).get("cinnamon_tickets_v1",{}) or {}
    cfg=root.get(str(gid),{}) or {}
    settings=cfg.get("settings",{}) or {}
    panels=cfg.get("panels",{}) or {}
    tickets=cfg.get("tickets",{}) or {}
    open_count=sum(1 for t in tickets.values() if t.get("status")=="open")
    closed_count=len(cfg.get("closed",{}) or {})
    log_form="<div class='formgrid'><div class='field'><label>Ticket log channel</label>"+_channel_select(guild,"log_channel_id",settings.get("log_channel_id"))+"</div><div class='field'><label>Ticket parent category</label>"+_category_select(guild,"ticket_category_id",settings.get("ticket_category_id"))+"</div><div class='field'><label>Maximum open tickets per member</label><input name='max_open_per_user' type='number' min='1' max='10' value='"+str(max(1,min(10,int(settings.get("max_open_per_user",3)))))+"'></div><div class='field'><label>Opening cooldown (seconds)</label><input name='cooldown_seconds' type='number' min='0' max='86400' value='"+str(max(0,min(86400,int(settings.get("cooldown_seconds",60)))))+"'></div><div class='field'><label>Auto-close after inactivity (hours; 0 disables)</label><input name='auto_close_hours' type='number' min='0' max='720' value='"+str(max(0,min(720,int(settings.get("auto_close_hours",0)))))+"'></div></div><div class='toggle'><input type='checkbox' name='transcript_on_close'"+(" checked" if settings.get("transcript_on_close",True) else "")+"><span><b>Attach HTML transcript to logs on close</b><small>Transcript is sent to the configured log channel.</small></span></div>"
    log_form+= "<div class='field'><label>General ticket staff roles</label>"+_role_multi_select(guild,"staff_role_ids",settings.get("staff_role_ids",[]))+"</div><div class='field'><label>Trusted Booster roles</label>"+_role_multi_select(guild,"trusted_booster_role_ids",settings.get("trusted_booster_role_ids",[]))+"</div>"
    settings_card="<article class='card full'><h2>Ticket settings</h2><p class='muted'>Changes are validated and saved together. Ticket settings and metadata live inside Cinnamon's Upstash-backed snapshot.</p>"+_form(gid,"ticket_settings_save",log_form,"Save ticket settings")+"</article>"
    create="<div class='formgrid'><div class='field'><label>Panel name (dashboard label)</label><input name='panel_name' maxlength='60' required placeholder='Support Center'></div><div class='field'><label>Publish channel</label>"+_channel_select(guild,"channel_id",allow_none=False)+"</div><div class='field'><label>Panel title</label><input name='panel_title' maxlength='256' required value='Cinnamon Support Center'></div><div class='field'><label>Embed color (hex)</label><input name='panel_color' maxlength='7' value='#D99048'></div><div class='field full'><label>Panel description</label><textarea name='panel_description' maxlength='3500'>Choose a category below to open a private support ticket.</textarea></div><div class='field'><label>First category name</label><input name='category_label' maxlength='60' required value='General Support'></div><div class='field'><label>Button label</label><input name='button_label' maxlength='80' required value='Open Support Ticket'></div><div class='field'><label>Button emoji (optional)</label><input name='button_emoji' maxlength='100' placeholder='🎫'></div><div class='field'><label>Routing</label><select name='routing'><option value='support'>General support</option><option value='shop'>Shop support</option><option value='grow_a_garden'>Grow a Garden / boosting</option></select></div><div class='field full'><label>Welcome message</label><textarea name='welcome_message' maxlength='1500'>Thanks for opening a ticket. Staff will help you here.</textarea></div><div class='field'><label>Question 1</label><input name='question1' maxlength='45' placeholder='What do you need help with?'></div><div class='field'><label>Question 2</label><input name='question2' maxlength='45' placeholder='What did you purchase?'></div><div class='field'><label>Question 3</label><input name='question3' maxlength='45' placeholder='Order ID'></div><div class='field'><label>Question 4</label><input name='question4' maxlength='45' placeholder='Describe the issue'></div><div class='field'><label>Question 5</label><input name='question5' maxlength='45' placeholder='Anything else?'></div><div class='field full'><label>Optional multi-category JSON (overrides the single category above)</label><textarea name='categories_json' maxlength='12000' placeholder='Paste a JSON category list here'></textarea><small>Each category can have its own modal questions, routing (support/shop/grow_a_garden), button emoji/style, welcome text and ticket naming format.</small></div></div>"
    create_card="<article class='card full'><h2>Create ticket panel</h2><p class='muted'>Create a panel configuration first, then publish it separately. Modal questions are asked before the private channel is created.</p>"+_form(gid,"ticket_panel_save",create,"Save panel draft")+"</article>"
    panel_rows=[]
    for pid,p in sorted(panels.items()):
        state_label="Published" if p.get("published") else "Draft"
        ch=guild.get_channel(int(p.get("channel_id",0) or 0))
        cats=p.get("categories",[]) or []
        panel_rows.append("<article class='card full'><h3>"+_esc(p.get("name","Ticket panel"))+" <span class='pill'>"+state_label+"</span></h3><p class='muted'>"+_esc("#"+ch.name if ch else "No channel")+" · "+str(len(cats))+" categories · ID "+_esc(pid)+"</p>"+_form(gid,"ticket_panel_update","<input type='hidden' name='panel_id' value='"+_esc(pid)+"'><div class='formgrid'><div class='field'><label>Panel name</label><input name='panel_name' maxlength='60' required value='"+_esc(p.get("name",""))+"'></div><div class='field'><label>Channel</label>"+_channel_select(guild,"channel_id",p.get("channel_id"),allow_none=False)+"</div><div class='field'><label>Title</label><input name='panel_title' maxlength='256' required value='"+_esc(p.get("title","Support Center"))+"'></div><div class='field'><label>Color</label><input name='panel_color' maxlength='7' value='"+_esc(p.get("color","#D99048"))+"'></div><div class='field full'><label>Description</label><textarea name='panel_description' maxlength='3500'>"+_esc(p.get("description",""))+"</textarea></div><div class='field full'><label>Categories & modal questions (JSON)</label><textarea name='categories_json' maxlength='12000'>"+_esc(json.dumps(p.get("categories",[]),ensure_ascii=False,indent=2))+"</textarea><small>Edit all panel buttons/categories here. Each category supports its own questions and staff routing.</small></div></div>","Save panel settings")+
        "<div class='actions'><form method='post' action='/dashboard/action'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='ticket_panel_publish'><input type='hidden' name='panel_id' value='"+_esc(pid)+"'><button class='btn'>"+("Update published panel" if p.get("published") else "Publish panel")+"</button></form><form method='post' action='/dashboard/action' onsubmit='return confirm(&quot;Delete this panel configuration?&quot;);'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='ticket_panel_delete'><input type='hidden' name='panel_id' value='"+_esc(pid)+"'><button class='btn danger small'>Delete</button></form></div></article>")
    panel_card="<article class='card full'><h2>Ticket panels</h2>"+("".join(panel_rows) or "<p class='empty'>No panels yet.</p>")+"</article>"
    active_parts=[]
    for t in tickets.values():
        if t.get("status")!="open": continue
        ch=guild.get_channel(int(t.get("channel_id",0) or 0))
        channel_name=("#"+ch.name) if ch else ("Unknown channel "+str(t.get("channel_id","")))
        claimed_member=guild.get_member(int(t.get("claimed_by",0) or 0)) if t.get("claimed_by") else None
        claim_form="<form method='post' action='/dashboard/action'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='ticket_dashboard_claim'><input type='hidden' name='channel_id' value='"+str(t.get("channel_id"))+"'><button class='btn secondary small'>Claim as me</button></form>"
        unclaim_form="<form method='post' action='/dashboard/action'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='ticket_dashboard_unclaim'><input type='hidden' name='channel_id' value='"+str(t.get("channel_id"))+"'><button class='btn secondary small'>Unassign</button></form>"
        close_form="<form method='post' action='/dashboard/action'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='ticket_dashboard_close'><input type='hidden' name='channel_id' value='"+str(t.get("channel_id"))+"'><button class='btn danger small'>Close</button></form>"
        assigned=_esc(claimed_member.display_name if claimed_member else ("Member "+str(t.get("claimed_by"))) if t.get("claimed_by") else "Unclaimed")
        actions="<div class='actions'>"+claim_form+unclaim_form+close_form+"</div>"
        active_parts.append("<tr><td>"+_esc(channel_name)+"</td><td>"+_esc(t.get("category_label","Support"))+"</td><td>"+_esc(str(t.get("creator_id","")))+"</td><td>"+_esc(t.get("status","open"))+"</td><td>"+assigned+"</td><td>"+actions+"</td></tr>")
    active_rows="".join(active_parts) or "<tr><td colspan='6'>No active tickets.</td></tr>"
    closed_parts=[]
    for channel_id,t in list((cfg.get("closed",{}) or {}).items())[-50:]:
        ch=guild.get_channel(int(channel_id)) if str(channel_id).isdigit() else None
        cname="#"+ch.name if ch else "Ticket "+str(channel_id)
        reopen="<form method='post' action='/dashboard/action'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='ticket_dashboard_reopen'><input type='hidden' name='channel_id' value='"+_esc(channel_id)+"'><button class='btn secondary small'>Reopen</button></form>"
        closed_parts.append("<tr><td>"+_esc(cname)+"</td><td>"+_esc(t.get("category_label","Support"))+"</td><td>"+_esc(str(t.get("creator_id","")))+"</td><td>"+_esc(t.get("close_reason",""))+"</td><td>"+reopen+"</td></tr>")
    closed_rows="".join(closed_parts) or "<tr><td colspan='5'>No closed tickets.</td></tr>"
    closed_card="<article class='card full'><h2>Recently closed tickets (up to 50)</h2><div class='tablewrap'><table><thead><tr><th>Channel</th><th>Category</th><th>Creator ID</th><th>Close reason</th><th>Action</th></tr></thead><tbody>"+closed_rows+"</tbody></table></div></article>"
    active="<article class='card full'><h2>Active tickets ("+str(open_count)+")</h2><div class='tablewrap'><table><thead><tr><th>Channel</th><th>Category</th><th>Creator ID</th><th>Status</th><th>Claimed by</th><th>Actions</th></tr></thead><tbody>"+active_rows+"</tbody></table></div><p class='muted'>Ticket conversations and staff replies stay inside Discord. Dashboard is for configuration and management.</p></article>"
    body="<h1>Tickets</h1><p class='muted'>Discord-native private tickets, modal intake, automatic staff routing, transcripts, and durable records.</p><div class='grid'><article class='card third'><div class='statlabel'>Panels</div><div class='stat'>"+str(len(panels))+"</div></article><article class='card third'><div class='statlabel'>Open tickets</div><div class='stat'>"+str(open_count)+"</div></article><article class='card third'><div class='statlabel'>Closed records</div><div class='stat'>"+str(closed_count)+"</div></article>"+settings_card+create_card+panel_card+active+closed_card+"</div>"
    return body


def _roles_setup(guild,state):
    gid=guild.id; root=(state.get("advanced_features_data",{}) or {}).get("cinnamon_role_permissions_v1",{}) or {}; config=root.get(str(gid),{}) or {}
    categories=[("giveaway_creator","Giveaway Creator","Create, edit, end and reroll giveaways."),("hangry_runner","Hangry Games Runner","Start and manage Hangry Games."),("trusted_booster","Trusted Booster","Handle Grow a Garden boosting tickets."),("ticket_staff","Ticket Staff","Claim, assign and resolve support tickets."),("ticket_admin","Ticket Administrator","Manage all ticket settings and tickets."),("shop_manager","Shop Manager","Manage shop support and orders."),("economy_admin","Economy Administrator","Manage economy tools."),("quest_manager","Quest Manager","Manage quests and challenges."),("event_manager","Event Manager","Manage server events."),("moderator","Moderator","Moderation commands.")]
    cards=[]
    for key,label,desc in categories:
        cards.append("<article class='card half'><h3>"+_esc(label)+"</h3><p class='muted'>"+_esc(desc)+"</p>"+_role_multi_select(guild,"role_"+key,config.get(key,[]))+"</article>")
    content="<p class='muted'>Select one or more roles per permission category. A member with any selected role receives that category's permission. Discord Administrators retain the universal override.</p>"+"".join(cards)
    return "<h1>Roles Setup</h1><p class='muted'>Central server-side permission mapping for Cinnamon features. Saved role IDs persist in the Upstash snapshot and are logged.</p>"+_form(gid,"roles_setup_save",content,"Save all role permissions")


def _category_select(guild,name,selected=None):
    cats=[c for c in guild.categories]
    opts=["<option value=''>— Not set —</option>"]
    for c in cats:
        sel=" selected" if selected is not None and str(selected)==str(c.id) else ""
        opts.append(f"<option value='{c.id}'{sel}>📁 {_esc(c.name)}</option>")
    return "<select name='"+_esc(name)+"'>"+"".join(opts)+"</select>"


def _giveaways(guild,state):
    gid=guild.id; active=state.get("active_giveaways",{}) or {}; history=state.get("giveaway_history",{}) or {}
    cards=[]
    for mid,gw in active.items():
        if int(gw.get("guild_id",0))!=gid: continue
        remain=max(0,int((float(gw.get('ends_at',0))-time.time())//60))
        entry_message = _esc(gw.get("entry_message", "🎉 You're entered! Tap again to leave."))
        denied_message = _esc(gw.get("denied_message", "You do not meet this giveaway's entry requirements."))
        content=(f"<p class='muted'>Message ID: <code>{int(mid)}</code> · Entries: {len(set(gw.get('entrants',[])))} · Ends in approx. {remain} min</p>"
        f"<div class='formgrid'><div class='field'><label>Prize</label><input name='prize' maxlength='200' value='{_esc(gw.get('prize',''))}' required></div>"
        f"<div class='field'><label>Winners</label><input name='winners' type='number' min='1' max='100' value='{int(gw.get('winners',1))}' required></div>"
        f"<div class='field'><label>Reset duration (minutes from save)</label><input name='duration_minutes' type='number' min='1' max='525600' value='{max(1,remain)}' required></div>"
        f"<div class='field'><label>Entry button / reaction emoji</label><input name='entry_emoji' maxlength='40' value='{_esc(gw.get('entry_emoji','🎉'))}'></div>"
        f"<div class='field'><label><input type='checkbox' name='reaction_entries' value='1'{(' checked' if gw.get('reaction_entries') else '')}> Also allow reaction entry</label><small>Bot must have Add Reactions and Manage Messages to remove ineligible entries.</small></div>"
        f"<div class='field full'><label>Bonus entries by role</label><textarea name='bonus_roles' maxlength='2400' placeholder='ROLE_ID:EXTRA_ENTRIES, one per line'>{_esc(chr(10).join(f'{rid}:{count}' for rid,count in (gw.get('bonus_roles',{}) or {}).items()))}</textarea><small>Each listed role adds 1–20 entries. Only the highest bonus among a member's matching roles applies.</small></div>"
        f"<div class='field'><label>Minimum Discord account age (days, 0 = none)</label><input name='min_account_age_days' type='number' min='0' max='3650' value='{int(gw.get('min_account_age_days',0) or 0)}'></div>"
        f"<div class='field'><label>Minimum server membership (days, 0 = none)</label><input name='min_server_age_days' type='number' min='0' max='3650' value='{int(gw.get('min_server_age_days',0) or 0)}'></div>"
        f"<div class='field full'><label>Required roles (member needs at least one)</label>{_role_multi_select(guild,'required_roles',gw.get('required_roles',[]))}</div>"
        f"<div class='field full'><label>Requirement-bypass roles (skip required roles and age checks)</label>{_role_multi_select(guild,'bypass_roles',gw.get('bypass_roles',[]))}</div>"
        f"<div class='field full'><label>Blacklisted roles (always blocked, even if bypass role is present)</label>{_role_multi_select(guild,'blacklisted_roles',gw.get('blacklisted_roles',[]))}</div>"
        f"<div class='field'><label>Winner role (optional)</label>{_role_select(guild,'winner_role_id',gw.get('winner_role_id'),True)}</div>"
        f"<div class='field'><label>Remove winner role after (minutes, 0 = keep)</label><input name='winner_role_minutes' type='number' min='0' max='525600' value='{int(gw.get('winner_role_minutes',0) or 0)}'></div>"
        f"<div class='field'><label>Winner thread auto-close (minutes, 0 = off)</label><input name='winner_thread_minutes' type='number' min='0' max='10080' value='{int(gw.get('winner_thread_minutes',0) or 0)}'></div>"
        f"<div class='field'><label>Claim deadline (minutes, 0 = off)</label><input name='claim_minutes' type='number' min='0' max='10080' value='{int(gw.get('claim_minutes',0) or 0)}'></div>"
        f"<div class='field'><label>Embed colour (hex)</label><input name='embed_color' maxlength='7' value='{_esc(str(gw.get('embed_color','FEE75C')).lstrip('#'))}'></div>"
        f"<div class='field'><label>Embed title (optional)</label><input name='embed_title' maxlength='256' value='{_esc(gw.get('embed_title',''))}'></div>"
        f"<div class='field full'><label>Embed description (optional)</label><textarea name='embed_description' maxlength='3500'>{_esc(gw.get('embed_description',''))}</textarea></div>"
        f"<div class='field'><label>Entry confirmation</label><input name='entry_message' maxlength='300' value='{entry_message}'></div>"
        f"<div class='field'><label>Leave confirmation</label><input name='leave_message' maxlength='300' value='{_esc(gw.get('leave_message','You left the giveaway.'))}'></div>"
        f"<div class='field full'><label>Eligibility-denied message</label><input name='denied_message' maxlength='300' value='{denied_message}'></div></div>")
        edit=_form(gid,"giveaway_edit",f"<input type='hidden' name='message_id' value='{int(mid)}'>{content}","Save giveaway")
        template_form=_form(gid,"giveaway_template_save",f"<input type='hidden' name='message_id' value='{int(mid)}'><div class='field'><label>Template name</label><input name='template_name' maxlength='40' required placeholder='e.g. Monthly Tuna'></div>","Save as template")
        end=(f"<form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='giveaway_end'><input type='hidden' name='message_id' value='{int(mid)}'><button class='btn secondary small'>End & pick winners</button></form>"
             f"<form method='post' action='/dashboard/action' onsubmit='return confirm(&quot;Cancel this giveaway without winners?&quot;);'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='giveaway_cancel'><input type='hidden' name='message_id' value='{int(mid)}'><button class='btn danger small'>Cancel giveaway</button></form>")
        cards.append(f"<article class='card full'><h3>🎉 {_esc(gw.get('prize','Giveaway'))}</h3>{edit}<div class='grid'><article class='card half'><h3>Reusable template</h3>{template_form}</article><article class='card half'><h3>Finish or cancel</h3><div class='actions'>{end}</div></article></div></article>")
    channels=_channel_select(guild,"channel_id",allow_none=False)
    create=("<div class='formgrid'><div class='field'><label>Post in</label>"+channels+"</div><div class='field'><label>Prize</label><input name='prize' maxlength='200' required></div>"
    "<div class='field'><label>Winners</label><input name='winners' type='number' min='1' max='100' value='1' required></div><div class='field'><label>Duration (minutes; max 1 year)</label><input name='duration_minutes' type='number' min='1' max='525600' value='60' required></div>"
    "<div class='field'><label>Entry button / reaction emoji</label><input name='entry_emoji' maxlength='40' value='🎉'></div><div class='field'><label>Embed colour (hex)</label><input name='embed_color' maxlength='7' value='FEE75C'></div>"
    "<div class='field'><label><input type='checkbox' name='reaction_entries' value='1'> Also allow reaction entry</label><small>Bot needs Add Reactions and Manage Messages to remove ineligible entries.</small></div>"
    "<div class='field'><label>Minimum account age (days)</label><input name='min_account_age_days' type='number' min='0' max='3650' value='0'></div><div class='field'><label>Minimum server membership (days)</label><input name='min_server_age_days' type='number' min='0' max='3650' value='0'></div>"
    "<div class='field full'><label>Bonus entries by role</label><textarea name='bonus_roles' maxlength='2400' placeholder='ROLE_ID:EXTRA_ENTRIES, one per line'></textarea><small>Role IDs can be copied from Discord with Developer Mode enabled. Each listed role adds 1–20 entries.</small></div>"
    "<div class='field full'><label>Required roles (member needs at least one)</label>"+_role_multi_select(guild,"required_roles")+"</div>"
    "<div class='field full'><label>Requirement-bypass roles</label>"+_role_multi_select(guild,"bypass_roles")+"</div>"
    "<div class='field full'><label>Blacklisted roles (always blocked)</label>"+_role_multi_select(guild,"blacklisted_roles")+"</div>"
    "<div class='field'><label>Winner role (optional)</label>"+_role_select(guild,"winner_role_id",None,True)+"</div><div class='field'><label>Remove winner role after (minutes; 0 = keep)</label><input name='winner_role_minutes' type='number' min='0' max='525600' value='0'></div>"
    "<div class='field'><label>Winner thread auto-close (minutes; 0 = off)</label><input name='winner_thread_minutes' type='number' min='0' max='10080' value='0'></div><div class='field'><label>Embed title (optional)</label><input name='embed_title' maxlength='256'></div>"
    "<div class='field full'><label>Embed description (optional)</label><textarea name='embed_description' maxlength='3500' placeholder='Additional details for your giveaway'></textarea></div>"
    "<div class='field'><label>Entry confirmation</label><input name='entry_message' maxlength='300' value='🎉 You are entered! Tap again to leave.'></div><div class='field'><label>Leave confirmation</label><input name='leave_message' maxlength='300' value='You left the giveaway.'></div>"
    "<div class='field full'><label>Eligibility-denied message</label><input name='denied_message' maxlength='300' value='You do not meet this giveaway\'s entry requirements.'></div></div>")
    def _giveaway_form_fields(prize,winners,duration,config):
        c=config or {}
        bonus="\\n".join(f"{rid}:{count}" for rid,count in (c.get("bonus_roles",{}) or {}).items())
        roles=lambda key:"\\n".join(str(x) for x in (c.get(key,[]) or []))
        return ("<div class='formgrid'><div class='field'><label>Prize</label><input name='prize' maxlength='200' required value='"+_esc(prize)+"'></div>"
        "<div class='field'><label>Winners</label><input name='winners' type='number' min='1' max='100' value='"+str(int(winners))+"'></div>"
        "<div class='field'><label>Duration (minutes)</label><input name='duration_minutes' type='number' min='1' max='525600' value='"+str(int(duration))+"'></div>"
        "<div class='field'><label>Role bonuses (ROLE_ID:EXTRA per line)</label><textarea name='bonus_roles'>"+_esc(bonus)+"</textarea></div>"
        "<div class='field'><label>Required roles (IDs/mentions)</label><textarea name='required_roles'>"+_esc(roles('required_roles'))+"</textarea></div>"
        "<div class='field'><label>Bypass roles</label><textarea name='bypass_roles'>"+_esc(roles('bypass_roles'))+"</textarea></div>"
        "<div class='field'><label>Blacklisted roles</label><textarea name='blacklisted_roles'>"+_esc(roles('blacklisted_roles'))+"</textarea></div>"
        "<div class='field'><label>Minimum account age (days)</label><input name='min_account_age_days' type='number' min='0' max='3650' value='"+str(int(c.get('min_account_age_days',0) or 0))+"'></div>"
        "<div class='field'><label>Minimum server age (days)</label><input name='min_server_age_days' type='number' min='0' max='3650' value='"+str(int(c.get('min_server_age_days',0) or 0))+"'></div>"
        "<div class='field'><label>Winner role ID</label><input name='winner_role_id' value='"+_esc(c.get('winner_role_id',''))+"'></div>"
        "<div class='field'><label>Winner role duration (minutes)</label><input name='winner_role_minutes' type='number' min='0' max='525600' value='"+str(int(c.get('winner_role_minutes',0) or 0))+"'></div>"
        "<div class='field'><label>Winner thread duration (minutes)</label><input name='winner_thread_minutes' type='number' min='0' max='10080' value='"+str(int(c.get('winner_thread_minutes',0) or 0))+"'></div>"
        "<div class='field'><label>Claim deadline (minutes; 0 = off)</label><input name='claim_minutes' type='number' min='0' max='10080' value='"+str(int(c.get('claim_minutes',0) or 0))+"'></div>"
        "<div class='field'><label>Embed color (hex)</label><input name='embed_color' value='"+_esc(c.get('embed_color','FEE75C'))+"'></div>"
        "<div class='field'><label>Entry emoji</label><input name='entry_emoji' value='"+_esc(c.get('entry_emoji','🎉'))+"'></div>"
        "<div class='field'><label>Entry message</label><input name='entry_message' maxlength='300' value='"+_esc(c.get('entry_message','🎉 You are entered! Tap again to leave.'))+"'></div>"
        "<div class='field'><label>Leave message</label><input name='leave_message' maxlength='300' value='"+_esc(c.get('leave_message','You left the giveaway.'))+"'></div>"
        "<div class='field full'><label>Denied message</label><input name='denied_message' maxlength='300' value='"+_esc(c.get('denied_message','You do not meet this giveaway requirements.'))+"'></div>"
        "<div class='field'><label>Embed title</label><input name='embed_title' maxlength='256' value='"+_esc(c.get('embed_title',''))+"'></div>"
        "<div class='field full'><label>Embed description</label><textarea name='embed_description' maxlength='3500'>"+_esc(c.get('embed_description',''))+"</textarea></div>"
        "<div class='field'><label><input type='checkbox' name='reaction_entries' "+("checked" if c.get('reaction_entries') else "")+"> Enable reaction entries</label></div></div>")
    create_card="<article class='card full'><h2>Build giveaway (save draft first)</h2>"+_form(gid,"giveaway_draft_save",create,"Save draft")+"<p class='muted'>Features include eligibility rules, bypass/blacklisted roles, bonus entries, custom embeds and messages, timed winner roles, winner threads, reusable templates, recurring schedules, and rerolls.</p></article>"
    schedules=state.get("giveaway_schedules",{}) or {}; schedule_rows=[]
    for sid,cfg in schedules.items():
        if int(cfg.get("guild_id",0))!=gid: continue
        ch=guild.get_channel(int(cfg.get("channel_id",0))); next_at=int(cfg.get("next_at",0))
        schedule_rows.append(f"<div class='toggle'><span><b>{_esc(cfg.get('prize','Giveaway'))}</b><small>{_esc('#'+ch.name if ch else 'Missing channel')} · every {int(cfg.get('repeat_every_days',7))} day(s) · next <t:{next_at}:R></small><small>ID: <code>{_esc(sid)}</code></small></span><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='giveaway_repeat_stop'><input type='hidden' name='schedule_id' value='{_esc(sid)}'><button class='btn danger small'>Stop</button></form></div>")
    repeat_form=("<div class='formgrid'><div class='field'><label>Post in</label>"+_channel_select(guild,"channel_id",allow_none=False)+"</div><div class='field'><label>Prize</label><input name='prize' maxlength='200' required></div><div class='field'><label>Winners</label><input name='winners' type='number' min='1' max='100' value='1' required></div><div class='field'><label>Giveaway duration (minutes)</label><input name='duration_minutes' type='number' min='1' max='525600' value='1440' required></div><div class='field'><label>Repeat every (days)</label><input name='repeat_every_days' type='number' min='1' max='365' value='7' required></div></div>")
    repeat_card="<article class='card half'><h2>Recurring giveaways</h2><p class='muted'>Schedules are saved with bot data and continue after restarts.</p>"+(''.join(schedule_rows) or "<p class='muted'>No recurring giveaways configured.</p>")+_form(gid,"giveaway_repeat_create",repeat_form,"Save recurring schedule")+"</article>"
    templates=state.get("giveaway_templates",{}) or {}; templates=templates.get(gid,templates.get(str(gid),{})) or {}; template_rows=[]
    for name,cfg in sorted(templates.items()):
        template_rows.append(f"<div class='toggle'><span><b>{_esc(name)}</b><small>{_esc(cfg.get('prize','Giveaway'))} · {int(cfg.get('winners',1))} winner(s)</small></span><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='giveaway_template_delete'><input type='hidden' name='template_name' value='{_esc(name)}'><button class='btn danger small'>Delete</button></form></div>")
    template_card="<article class='card half'><h2>Saved templates</h2>"+(''.join(template_rows) or "<p class='muted'>Save any active giveaway as a reusable template.</p>")+"</article>"
    finished=[(mid,gw) for mid,gw in history.items() if int(gw.get('guild_id',0))==gid]
    finished.sort(key=lambda x:float(x[1].get('finished_at',0)),reverse=True)
    hist_rows=''.join(f"<tr><td>{_esc(gw.get('prize','Giveaway'))}</td><td>{len(set(gw.get('eligible_entrants',gw.get('entrants',[]))))}</td><td>{', '.join(str(x) for x in gw.get('winner_ids',[])) or 'No winner'}</td><td><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='giveaway_reroll'><input type='hidden' name='message_id' value='{_esc(mid)}'><button class='btn secondary small'>Reroll</button></form></td></tr>" for mid,gw in finished[:20]) or "<tr><td colspan='4'>No finished giveaways in history yet.</td></tr>"
    history_card="<article class='card full'><h2>Recent finished giveaways</h2><div class='tablewrap'><table><thead><tr><th>Prize</th><th>Eligible entries</th><th>Winner IDs</th><th>Action</th></tr></thead><tbody>"+hist_rows+"</tbody></table></div><p class='muted'>Reroll selects a different eligible entrant from the saved history. History keeps the latest 250 finished giveaways.</p></article>"
    drafts=(state.get("giveaway_drafts",{}) or {}).get(gid,(state.get("giveaway_drafts",{}) or {}).get(str(gid),{})) or {}
    draft_rows=[]
    for did,d in drafts.items():
        draft_form="<input type='hidden' name='draft_id' value='"+_esc(did)+"'><input type='hidden' name='channel_id' value='"+str(int(d.get('channel_id',0)))+"'>"+_giveaway_form_fields(d.get('prize','Giveaway'),d.get('winners',1),d.get('duration_minutes',60),d.get('config',{}))
        draft_rows.append("<article class='card full'><h3>Draft editor & preview: "+_esc(d.get('prize','Giveaway'))+"</h3><p class='muted'>Edit settings, then save changes to this draft. Publishing is a separate action.</p>"+_form(gid,"giveaway_draft_update",draft_form,"Save draft changes")+"<div class='actions'><form method='post' action='/dashboard/action'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='giveaway_draft_publish'><input type='hidden' name='draft_id' value='"+_esc(did)+"'><button class='btn'>Publish giveaway</button></form><form method='post' action='/dashboard/action'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='giveaway_draft_delete'><input type='hidden' name='draft_id' value='"+_esc(did)+"'><button class='btn danger small'>Discard</button></form></div></article>")
    draft_card="<article class='card full'><h2>Drafts · preview before publishing</h2><div class='grid'>"+(''.join(draft_rows) or "<p class='muted'>No saved drafts.</p>")+"</div></article>"
    body="<h1>Giveaways</h1><p class='muted'>Configure, save a draft, preview it, then publish. Active giveaway changes take effect only after Save giveaway.</p><div class='grid'>"+(''.join(cards) or "<article class='card full'><div class='empty'>No active giveaways in this server.</div></article>")+create_card+draft_card+repeat_card+template_card+history_card+"</div>"
    return body


def _hangry(guild,state):
    gid=guild.id; cog=state.get("hg_cog")
    if not cog: return "<h1>Hangry Games</h1><p class='muted'>Hangry Games statistics are not loaded yet. Reload after Cinnamon is ready.</p>"
    wins=sorted(((uid,n) for (g,uid),n in cog.win_counts.items() if g==gid),key=lambda x:x[1],reverse=True)[:10]
    rows=''.join(f"<tr><td>{i}</td><td>{_esc(guild.get_member(uid).display_name if guild.get_member(uid) else 'Member '+str(uid))}</td><td>{n}</td><td>{cog.played_counts.get((gid,uid),0)}</td><td>{cog.kill_counts.get((gid,uid),0)}</td></tr>" for i,(uid,n) in enumerate(wins,1)) or "<tr><td colspan='5'>No completed games recorded.</td></tr>"
    ch=cog.hg_log_channels.get(gid); enabled=cog.log_enabled.get(gid,True)
    channel_form="<div class='field'><label>Hangry Games log channel</label>"+_channel_select(guild,"channel_id",ch)+"</div><label class='toggle'><input type='checkbox' name='enabled' "+("checked" if enabled else "")+"><span><b>Enable activity logs</b><small>Applies when a log channel is selected.</small></span></label>"
    body=f"<h1>Hangry Games</h1><p class='muted'>Game statistics and log routing from the live Hangry Games module.</p><div class='grid'><article class='card third'><div class='statlabel'>Games run</div><div class='stat'>{int(cog.game_counts.get(gid,0)):,}</div></article><article class='card third'><div class='statlabel'>Members with wins</div><div class='stat'>{sum(1 for g,u in cog.win_counts if g==gid):,}</div></article><article class='card third'><div class='statlabel'>Logging</div><div class='stat'>{'On' if enabled and ch else 'Off'}</div></article><article class='card half'><h2>Win leaderboard</h2><div class='tablewrap'><table><thead><tr><th>#</th><th>Member</th><th>Wins</th><th>Played</th><th>KOs</th></tr></thead><tbody>{rows}</tbody></table></div></article><article class='card half'><h2>Game log settings</h2>{_form(gid,'hangry_logs',channel_form,'Save settings')}</article></div>"
    return body



def _companions(guild, state):
    gid = str(guild.id)
    advanced = state.get("advanced_features_data", {}) or {}
    profiles = (advanced.get("companion_profiles_v1", {}) or {}).get(gid, {}) or {}
    records = []
    total_friendship = total_feeds = total_plays = total_grooms = 0
    for user_id, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        stats = profile.get("stats", {}) or {}
        friendship = int(profile.get("friendship", 0))
        feeds, plays, grooms = int(stats.get("feeds", 0)), int(stats.get("plays", 0)), int(stats.get("grooms", 0))
        total_friendship += friendship
        total_feeds += feeds
        total_plays += plays
        total_grooms += grooms
        member = guild.get_member(int(user_id)) if str(user_id).isdigit() else None
        records.append((str(profile.get("name", "Mochi")), member.display_name if member else "Member " + str(user_id),
                        int(profile.get("level", 1)), str(profile.get("mood", "Content")), friendship,
                        feeds, plays, grooms, len(profile.get("equipped", {}) or {}), len(profile.get("room", []) or [])))
    records.sort(key=lambda x: (x[2], x[4]), reverse=True)
    rows = "".join(
        "<tr><td>" + _esc(member) + "</td><td>" + _esc(name) + "</td><td>" + str(level) +
        "</td><td>" + _esc(mood) + "</td><td>" + f"{friendship:,}" +
        "</td><td>" + str(feeds) + " / " + str(plays) + " / " + str(grooms) +
        "</td><td>" + str(accessories) + "</td><td>" + str(decor) + "</td></tr>"
        for name, member, level, mood, friendship, feeds, plays, grooms, accessories, decor in records[:100]
    ) or "<tr><td colspan='8'>No personal companion profiles yet.</td></tr>"
    return (
        "<h1>Companions</h1><p class='muted'>Member-owned cats, friendship progression, care activity, accessories and room decorations. Personal memory text is private and is not displayed here.</p>"
        "<div class='grid'>"
        "<article class='card third'><div class='statlabel'>Companion profiles</div><div class='stat'>" + f"{len(records):,}" + "</div></article>"
        "<article class='card third'><div class='statlabel'>Friendship points</div><div class='stat'>" + f"{total_friendship:,}" + "</div></article>"
        "<article class='card third'><div class='statlabel'>Care actions</div><div class='stat'>" + f"{total_feeds + total_plays + total_grooms:,}" + "</div></article>"
        "<article class='card full'><h2>Member companion roster</h2><div class='tablewrap'><table><thead><tr><th>Member</th><th>Cat</th><th>Level</th><th>Mood</th><th>Friendship</th><th>Feed / Play / Groom</th><th>Accessories</th><th>Room decor</th></tr></thead><tbody>"
        + rows + "</tbody></table></div><p class='muted'>Members manage their own cat with /pet, /feed, /play, /groom, /dressup and /room. Shared accessories and furniture are managed through the Catnip economy.</p></article>"
        "<article class='card half'><h2>Companion care totals</h2><p>Feeds: <b>" + f"{total_feeds:,}" + "</b></p><p>Play sessions: <b>" + f"{total_plays:,}" + "</b></p><p>Grooming sessions: <b>" + f"{total_grooms:,}" + "</b></p></article>"
        "<article class='card half'><h2>Companion item catalogue</h2><p class='muted'>Accessories and room furniture use the same member inventory as the rest of the economy. Items remain in inventory when equipped; furniture moves between inventory and the room.</p><div class='actions'><a class='btn secondary' href='/dashboard?guild_id=" + str(guild.id) + "&tab=economy'>Open Catnip Economy</a></div></article>"
        "</div>"
    )


def _community(guild,state):
    gid = guild.id
    welcome = state.get("welcome_config", {}).get(gid, {}) or state.get("welcome_config", {}).get(str(gid), {})
    goodbye = state.get("goodbye_config", {}).get(gid, {}) or state.get("goodbye_config", {}).get(str(gid), {})
    ai = state.get("ai_channels", {}).get(gid) or state.get("ai_channels", {}).get(str(gid))
    logs = state.get("log_channels", {}).get(gid) or state.get("log_channels", {}).get(str(gid))
    advanced = state.get("advanced_features_data", {}) or {}
    board = (advanced.get("cinnamon_community_tools_v1", {}) or {}).get(str(gid), {}) or {}
    social = (advanced.get("cinnamon_community_interactions_v1", {}) or {}).get(str(gid), {}) or {}
    polls = social.get("polls", {}) or {}
    active_polls = [(str(mid), p) for mid, p in polls.items() if isinstance(p, dict) and p.get("status") == "active"]
    events = social.get("events", {}) or {}
    confessions = social.get("confessions", {}) or {}
    activity_root = (advanced.get("cinnamon_community_activity_v1", {}) or {}).get(str(gid), {}) or {}
    activity_days = activity_root.get("days", {}) or {}
    recent_activity_keys = [time.strftime("%Y-%m-%d", time.gmtime(time.time() - day * 86400)) for day in range(7)]
    recent_activity = [activity_days.get(day_key, {}) for day_key in recent_activity_keys]
    activity_messages = sum(int(day.get("messages", 0)) for day in recent_activity)
    activity_members = set()
    for day in recent_activity:
        activity_members.update((day.get("members", {}) or {}).keys())

    def message_form(kind, cfg, action):
        ch = _channel_select(guild, "channel_id", cfg.get("channel_id"))
        msg = _esc(cfg.get("message", ""))
        fields = f"<div class='field'><label>Post in</label>{ch}</div><div class='field'><label>Message template</label><textarea name='message' maxlength='800' placeholder='Use {{member}} and {{server}}'>{msg}</textarea><small>Supported placeholders: {{member}} and {{server}}.</small></div>"
        current = guild.get_channel(cfg.get("channel_id")) if cfg.get("channel_id") else None
        disable = ("<form method='post' action='/dashboard/action'>" + _csrf_input() +
            f"<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='{action}_disable'><button class='btn secondary small' type='submit'>Disable</button></form>") if cfg else ""
        return f"<article class='card half'><h2>{kind}</h2><p class='muted'>Current: {_esc(current.mention if current else 'Disabled')}</p>" + _form(gid, action, fields) + disable + "</article>"

    ai_channel = guild.get_channel(ai) if ai else None
    log_channel = guild.get_channel(logs) if logs else None
    ai_form = "<div class='field'><label>Cinnamon conversation channel (responds when called)</label>" + _channel_select(guild, "channel_id", ai) + "</div>"
    log_form = "<div class='field'><label>Main moderation and error log channel</label>" + _channel_select(guild, "channel_id", logs) + "</div>"
    ai_card = "<article class='card half'><h2>AI channel</h2><p class='muted'>Current: " + _esc(ai_channel.mention if ai_channel else "Not set") + "</p>" + _form(gid, "ai_channel", ai_form) + "</article>"
    log_card = "<article class='card half'><h2>Main logging</h2><p class='muted'>Current: " + _esc(log_channel.mention if log_channel else "Not set") + "</p>" + _form(gid, "log_channel", log_form) + "</article>"

    suggestion_channel = guild.get_channel(int(board.get("suggestion_channel_id", 0) or 0))
    starboard_channel = guild.get_channel(int(board.get("starboard_channel_id", 0) or 0))
    confession_channel = guild.get_channel(int(social.get("confession_channel_id", 0) or 0))
    event_rows = []
    for event_id, event in sorted(events.items(), key=lambda pair: int(pair[1].get("starts_at", 0))):
        if event.get("status") != "scheduled":
            continue
        event_rows.append("<tr><td>" + _esc(event.get("title", "Event")) + "</td><td>" + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(event.get("starts_at", 0)))) + "</td><td>" + _esc(str(event_id)) + "</td><td><form method='post' action='/dashboard/action'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='community_event_cancel'><input type='hidden' name='event_id' value='" + _esc(str(event_id)) + "'><button class='btn danger small'>Cancel</button></form></td></tr>")
    event_rows_html = "".join(event_rows) or "<tr><td colspan='4'>No scheduled events.</td></tr>"
    event_form = "<div class='formgrid'><div class='field'><label>Event title</label><input name='title' maxlength='120' required></div><div class='field'><label>Start time (ISO 8601 with timezone)</label><input name='start_at' placeholder='2026-12-01T18:30:00+05:30' required></div><div class='field full'><label>Description</label><textarea name='description' maxlength='1500'></textarea></div><div class='field'><label>Event channel</label>" + _channel_select(guild, "channel_id", None) + "</div></div><p class='muted'>Use an explicit timezone offset, for example +05:30 or Z. Members RSVP on the event post and receive 24-hour and 1-hour reminders.</p>"
    event_card = "<article class='card full'><h2>Server events</h2><div class='tablewrap'><table><thead><tr><th>Event</th><th>Unix start time</th><th>Event ID</th><th>Action</th></tr></thead><tbody>" + event_rows_html + "</tbody></table></div>" + _form(gid, "community_event_create", event_form, "Create event") + "</article>"
    poll_rows = []
    for message_id, poll in active_polls[:20]:
        poll_rows.append("<tr><td>" + _esc(poll.get("question", "Poll")) + "</td><td>" + _esc(str(len(poll.get("votes", {}) or {}))) + "</td><td><a href='https://discord.com/channels/" + str(gid) + "/" + str(poll.get("channel_id", 0)) + "/" + _esc(str(message_id)) + "' target='_blank' rel='noopener'>Open poll</a></td><td><form method='post' action='/dashboard/action'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='community_poll_close'><input type='hidden' name='message_id' value='" + _esc(str(message_id)) + "'><button class='btn danger small'>Close</button></form></td></tr>")
    poll_rows_html = "".join(poll_rows) or "<tr><td colspan='4'>No active polls.</td></tr>"
    poll_form = "<div class='formgrid'><div class='field full'><label>Poll question</label><input name='question' maxlength='200' required></div><div class='field'><label>Option 1</label><input name='option1' maxlength='60' required></div><div class='field'><label>Option 2</label><input name='option2' maxlength='60' required></div><div class='field'><label>Option 3 (optional)</label><input name='option3' maxlength='60'></div><div class='field'><label>Option 4 (optional)</label><input name='option4' maxlength='60'></div><div class='field'><label>Duration (minutes)</label><input name='duration_minutes' type='number' min='1' max='10080' value='1440' required></div><div class='field'><label>Post in</label>" + _channel_select(guild, "channel_id", None) + "</div></div><p class='muted'>Members can change or remove their vote until the poll closes. Results are shown on the poll post.</p>"
    poll_card = "<article class='card full'><h2>Polls</h2><div class='tablewrap'><table><thead><tr><th>Question</th><th>Votes</th><th>Post</th><th>Action</th></tr></thead><tbody>" + poll_rows_html + "</tbody></table></div>" + _form(gid, "community_poll_create", poll_form, "Create poll") + "</article>"
    features = (
        "<div class='formgrid'>"
        "<div class='field'><label>Suggestion board channel</label>" + _channel_select(guild, "suggestion_channel_id", board.get("suggestion_channel_id")) + "</div>"
        "<div class='field'><label>Starboard channel</label>" + _channel_select(guild, "starboard_channel_id", board.get("starboard_channel_id")) + "</div>"
        "<div class='field'><label>Starboard reaction threshold</label><input name='starboard_threshold' type='number' min='2' max='20' value='" + str(max(2, min(20, int(board.get("starboard_threshold", 3)))) ) + "'></div>"
        "<div class='field'><label>Starboard emoji</label><input name='starboard_emoji' maxlength='20' value='" + _esc(str(board.get("starboard_emoji", "⭐"))) + "'></div>"
        "<div class='field'><label>Anonymous confession channel</label>" + _channel_select(guild, "confession_channel_id", social.get("confession_channel_id")) + "</div>"
        "</div><p class='muted'>Members use /suggest, /poll, /event, /confess and /quote. Confession channels should be moderated; confession submitters are not identified in public posts.</p>"
    )
    feature_card = "<article class='card full'><h2>Community boards and activities</h2><div class='toggle'><span>Suggestions</span><b>" + _esc(suggestion_channel.mention if suggestion_channel else "Disabled") + "</b></div><div class='toggle'><span>Starboard</span><b>" + _esc(starboard_channel.mention if starboard_channel else "Disabled") + "</b></div><div class='toggle'><span>Confessions</span><b>" + _esc(confession_channel.mention if confession_channel else "Disabled") + "</b></div><div class='grid'><article class='card third'><div class='statlabel'>Saved polls</div><div class='stat'>" + str(len(active_polls)) + "</div></article><article class='card third'><div class='statlabel'>Scheduled events</div><div class='stat'>" + str(sum(1 for e in events.values() if e.get("status") == "scheduled")) + "</div></article><article class='card third'><div class='statlabel'>Published confessions</div><div class='stat'>" + str(sum(1 for e in confessions.values() if e.get("status") == "published")) + "</div></article></div>" + _form(gid, "community_features_settings", features, "Save community settings") + "</article>"
    activity_card = "<article class='card full'><h2>Seven-day activity</h2><div class='grid'><article class='card half'><div class='statlabel'>Messages recorded</div><div class='stat'>" + f"{activity_messages:,}" + "</div></article><article class='card half'><div class='statlabel'>Active members</div><div class='stat'>" + f"{len(activity_members):,}" + "</div></article></div><p class='muted'>Use /community recap to share the same rolling seven-day summary. Activity tracking starts with this version; older messages are not backfilled.</p></article>"
    return "<h1>Community</h1><p class='muted'>Welcome and goodbye messages, Cinnamon's AI channel, suggestions, polls, starboard, events, anonymous confessions and server logging.</p><div class='grid'>" + message_form("Welcome messages", welcome, "welcome") + message_form("Goodbye messages", goodbye, "goodbye") + ai_card + log_card + feature_card + activity_card + poll_card + event_card + "</div>"


def _system(guild,state):
    gid=guild.id; hg=state.get("hg_cog"); category_channels=state.get("category_log_channels",{}).get(gid,{})
    categories=[("moderation","Main moderation"),("economy","Economy"),("ai","AI"),("levels","Levels & XP"),("achievements","Achievements"),("quests","Quests"),("friendship","Cinnamon Friendship"),("community","Giveaways & polls"),("roles","Role management"),("setup","Server setup"),("general","General utilities"),("dashboard","Dashboard audit trail")]
    configured=[]
    for key,label in categories:
        cid=state.get("log_channels",{}).get(gid) if key=="moderation" else (state.get("economy_log_channels",{}).get(gid) if key=="economy" else category_channels.get(key))
        configured.append((key,label,cid))
    if hg: configured.append(("hangry","Hangry Games",hg.hg_log_channels.get(gid)))
    options=[]
    for key,label,cid in configured:
        options.append(f"<option value='{_esc(key)}'>{_esc(label)} — {_esc((guild.get_channel(cid).name if cid and guild.get_channel(cid) else 'not configured'))}</option>")
    editor=f"<div class='formgrid'><div class='field'><label>Log category</label><select name='log_category'>{''.join(options)}</select></div><div class='field'><label>Channel</label>{_channel_select(guild,'channel_id')}</div></div><p class='muted'>Selecting a channel replaces that category's dedicated log route. Use Disable to remove it.</p>"
    disable="<form method='post' action='/dashboard/action'>"+_csrf_input()+f"<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='category_log_disable'><button class='btn secondary' type='submit'>Disable selected category</button></form>"
    items=''.join(f"<div class='toggle'><b>{_esc(label)}</b><span>{_esc(guild.get_channel(cid).mention if cid and guild.get_channel(cid) else 'Not configured')}</span></div>" for _,label,cid in configured)
    status=bool(_bot and _bot.is_ready()); storage='Upstash Redis' if state.get('BD_UPSTASH_URL') and state.get('BD_UPSTASH_TOKEN') else 'Local JSON file (may not survive redeploys)'
    setup_content="<p class='muted'>This is safe to run again; existing managed channels and roles are reused.</p>"
    setup="<article class='card full'><h2>Guided Cinnamon setup</h2><p class='muted'>Run the same idempotent setup flow as <b>/setup</b>. It creates/reuses Cinnamon's managed log channels and achievement/quest reward roles, but never creates level roles.</p>"+_form(gid,'run_setup',setup_content,'Run /setup from dashboard')+"</article>"
    recall_content="<p class='muted'>Best-effort recovery. Deleted Discord history cannot be recovered.</p>"
    recall="<p class='muted'>Scan configured log channels and merge recoverable warnings, XP, economy state, achievements, quests and Hangry data without intentionally overwriting existing account balances.</p>"+_form(gid,'recall',recall_content,'Run recovery scan')
    backup_form=(f"<form method='post' action='/dashboard/action' enctype='multipart/form-data'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='config_backup_restore'><div class='field'><label>Choose a Cinnamon configuration backup (.json)</label><input type='file' name='backup_file' accept='.json,application/json' required></div><p class='muted'>Only settings for this server are restored. Balances, inventories, user data, active giveaways, tokens, and secrets are never overwritten by a configuration import.</p><div class='actions'><button class='btn secondary' type='submit'>Validate & restore configuration</button></div></form>")
    backup=(f"<article class='card full'><h2>Configuration backup</h2><p class='muted'>Export this server's dashboard settings to a JSON file before making major changes. Import accepts only validated configuration keys for this same server.</p><div class='actions'><a class='btn' href='/dashboard/backup?guild_id={gid}'>Download configuration backup</a></div><div class='rule'></div>{backup_form}</article>")
    gateway_pill="<span class='pill good'>Connected</span>" if status else "<span class='pill warn'>Not ready</span>"
    return f"<h1>Settings & system</h1><p class='muted'>Cinnamon's server control center: logging, setup, persistence and recovery.</p><div class='grid'><article class='card half'><h2>Log routing</h2>{_form(gid,'category_log_set',editor,'Save log route')}{disable}</article><article class='card half'><h2>System health</h2><div class='toggle'><b>Bot Gateway</b>{gateway_pill}</div><div class='toggle'><b>Storage</b><span>{storage}</span></div><div class='toggle'><b>Guild ID</b><span>{gid}</span></div><p class='muted'>Use <b>/diagnostics</b> in Discord for the complete permission/runtime diagnostic.</p></article><article class='card full'><h2>Configured log channels</h2>{items}</article>{setup}<article class='card full'><h2>Recovery</h2>{recall}</article>{backup}</div>"


async def _dashboard_setup(guild,state):
    """Idempotent dashboard equivalent of /setup. Keeps level roles out."""
    discord=__import__("discord")
    category=discord.utils.get(guild.categories,name="Cinnamon • Logs & Setup")
    if category is None: category=await guild.create_category("Cinnamon • Logs & Setup",reason="Cinnamon dashboard setup")
    specs=[
        ("cinnamon-logs","Cinnamon moderation, AutoMod, errors, warnings, and general logs."),
        ("cinnamon-economy","Catnip economy transactions, balances, inventory and shop."),
        ("cinnamon-hangry","Hangry Games starts, winners, cancellations and recovery."),
        ("cinnamon-ai-logs","Cinnamon AI usage/settings logs; not private conversation contents."),
        ("cinnamon-level-logs","XP awards, level-ups and level-role changes."),
        ("cinnamon-achievement-logs","Achievement unlocks, rewards, roles and recovery."),
        ("cinnamon-quest-logs","Daily/weekly quest rotations, completions and rewards."),
        ("cinnamon-friendship-logs","Cinnamon Friendship level changes and related events."),
        ("cinnamon-stuff-logs","Cinnamon personality and favourites."),
        ("cinnamon-mood-logs","Private Cinnamon mood and Naughty List logs."),
        ("cinnamon-community-logs","Giveaway and poll events."),
        ("cinnamon-role-logs","Role management events."),
        ("cinnamon-setup-logs","Setup and configuration changes."),
        ("cinnamon-general-logs","General utility command usage."),
        ("cinnamon-dashboard-logs","Dashboard changes, Message Studio sends and audit events."),
        ("cinnamon-welcome","Cinnamon member welcome messages."),
        ("cinnamon-goodbye","Cinnamon member goodbye messages."),
        ("cinnamon-ai","Cinnamon's chat channel (responds only when invited)."),
        ("cinnamon-games","Public Hangry Games lobby and Catnip prizes."),
    ]
    channels={}
    for name,topic in specs:
        ch=discord.utils.get(category.text_channels,name=name)
        if ch is None:
            ch=await guild.create_text_channel(name=name,category=category,topic=topic,reason="Cinnamon dashboard setup")
        if name.endswith("-logs") or name in {"cinnamon-logs","cinnamon-economy","cinnamon-hangry"}:
            try:
                await ch.set_permissions(guild.default_role,view_channel=False)
                if guild.me: await ch.set_permissions(guild.me,view_channel=True,send_messages=True,embed_links=True,read_message_history=True)
            except Exception: pass
        if name=="cinnamon-games":
            await ch.set_permissions(guild.default_role,view_channel=True,send_messages=False,read_message_history=True)
            if guild.me:
                await ch.set_permissions(guild.me,view_channel=True,send_messages=True,embed_links=True,read_message_history=True)
        channels[name]=ch
    normal=state.get("ACHIEVEMENTS",{}); secret=state.get("SECRET_ACHIEVEMENTS",{}); admin=state.get("ADMIN_ACHIEVEMENT",{}) or {}
    role_names=sorted({str(a.get("role")).strip() for a in list(normal.values())+list(secret.values())+[admin] if a.get("role")})+ ["Quest Master","Hangry Games","Fishing Rod Merchant","Fishing Bait Merchant","Adventure • Treasure Hunter","Cinnamon's Naughty List"]
    existing={r.name:r for r in guild.roles if not r.managed}
    for name in dict.fromkeys(role_names):
        if name not in existing:
            try: await guild.create_role(name=name,reason="Cinnamon achievement/quest setup",mentionable=(name=="Hangry Games"))
            except Exception: pass
    gid=guild.id; state.setdefault("log_channels",{})[gid]=channels["cinnamon-logs"].id; state.setdefault("economy_log_channels",{})[gid]=channels["cinnamon-economy"].id
    state.setdefault("category_log_channels",{})[gid]={"moderation":channels["cinnamon-logs"].id,"economy":channels["cinnamon-economy"].id,"ai":channels["cinnamon-ai-logs"].id,"levels":channels["cinnamon-level-logs"].id,"achievements":channels["cinnamon-achievement-logs"].id,"quests":channels["cinnamon-quest-logs"].id,"friendship":channels["cinnamon-friendship-logs"].id,"stuff":channels["cinnamon-stuff-logs"].id,"mood":channels["cinnamon-mood-logs"].id,"community":channels["cinnamon-community-logs"].id,"roles":channels["cinnamon-role-logs"].id,"setup":channels["cinnamon-setup-logs"].id,"general":channels["cinnamon-general-logs"].id,"dashboard":channels["cinnamon-dashboard-logs"].id}
    state.setdefault("ai_channels",{})[gid]=channels["cinnamon-ai"].id
    social=state.setdefault("cinnamon_social",{}).setdefault(str(gid),{"people":{}})
    previous=guild.get_channel(int(social.get("auto_channel",0) or 0))
    if previous is None:
        social["auto_channel"]=channels["cinnamon-games"].id
    if not social.get("setup_configured",False):
        social["auto_enabled"]=True
        social["setup_configured"]=True
    social.setdefault("next_at",time.time()+__import__("random").randint(3600,7200))
    refresh=state.get("wlf_refresh_channel")
    if refresh:
        for kind in ("rod","bait"):
            await refresh(guild,kind)
    state.setdefault("welcome_config",{})[gid]={"channel_id":channels["cinnamon-welcome"].id,"message":"🐾 Welcome {member} to **{server}**! Cinnamon hopes you brought snacks."}
    state.setdefault("goodbye_config",{})[gid]={"channel_id":channels["cinnamon-goodbye"].id,"message":"🐾 {member} left **{server}**. Cinnamon will miss the head pats!"}
    hg=state.get("hg_cog")
    if hg:
        hg.hg_log_channels[gid]=channels["cinnamon-hangry"].id; hg.log_enabled[gid]=True
        try: await hg._save()
        except Exception: pass
    await state["bd_save_data"]()
    return "Cinnamon setup complete: mood/personality logs, public games and private fishing merchants are ready."


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
        if actor_id != guild.owner_id and not actor.guild_permissions.administrator:
            raise PermissionError("Your current server permissions do not allow dashboard moderation.")
        if target.top_role >= actor.top_role and actor.id != guild.owner_id:
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
    params={"client_id":os.environ["DISCORD_CLIENT_ID"].strip(),"response_type":"code","redirect_uri":_oauth_redirect_uri(),"scope":"identify guilds","state":state}
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
        redirect_uri=_oauth_redirect_uri()
        client_id_present=bool(os.getenv("DISCORD_CLIENT_ID", "").strip())
        client_secret_present=bool(os.getenv("DISCORD_CLIENT_SECRET", "").strip())
        log.info(
            "Discord OAuth exchange starting status=%s redirect_uri=%s redirect_sha256=%s client_id_present=%s client_secret_present=%s code_length=%s",
            "authorization_code",
            redirect_uri,
            hashlib.sha256(redirect_uri.encode("utf-8")).hexdigest()[:12],
            client_id_present,
            client_secret_present,
            len(code),
        )
        token=_token_exchange({"grant_type":"authorization_code","code":code,"redirect_uri":redirect_uri})
        user=_request_json(f"{BASE_URL}/users/@me",headers={"Authorization":"Bearer "+token["access_token"]})
        sid=secrets.token_urlsafe(32)
        _tokens[sid]={"access_token":token["access_token"],"refresh_token":token.get("refresh_token"),"expires_at":time.time()+int(token.get("expires_in",3600)),"user":user}
        session.clear(); session["dash_sid"]=sid; session["display_name"]=user.get("global_name") or user.get("username") or "Discord user"; _csrf()
        return redirect(url_for("cinnamon_dashboard.dashboard_home"))
    except urllib.error.HTTPError as exc:
        try: payload=json.loads(exc.read().decode("utf-8"))
        except Exception: payload={}
        oauth_error=str(payload.get("error", "unknown"))[:120]
        oauth_description=str(payload.get("error_description", "unavailable"))[:240]
        log.error(
            "Discord OAuth HTTP error status=%s error=%s description=%s redirect_sha256=%s",
            exc.code, oauth_error, oauth_description,
            hashlib.sha256(_oauth_redirect_uri().encode("utf-8")).hexdigest()[:12],
        )
        safe_error=html.escape(oauth_error, quote=True)
        return _page(f"<main class='main'><article class='card'><h1>Discord login failed</h1><p class='muted'>Discord rejected the OAuth exchange.</p><p class='muted'><strong>Error:</strong> {safe_error}</p><p class='muted'>The sanitized Discord error is also in the Render logs.</p><a class='btn' href='/login'>Try again</a></article></main>",status=502)
    except Exception as exc:
        log.exception("Discord OAuth callback failed (%s)",type(exc).__name__)
        return _page("<main class='main'><article class='card'><h1>Discord login failed</h1><p class='muted'>An unexpected login error occurred. Check Render logs.</p><a class='btn' href='/login'>Try again</a></article></main>",status=502)


def _analytics(guild, state):
    """Live, read-only analytics based on the running bot's current state."""
    gid = guild.id
    xp = state.get("xp_data", {})
    xp_users = [(key, value) for key, value in xp.items() if isinstance(key, tuple) and len(key) >= 2 and key[0] == gid]
    total_xp = sum(max(0, int(value or 0)) for _, value in xp_users)
    warns = state.get("warnings_data", {})
    warning_count = sum(len(value) for key, value in warns.items() if isinstance(key, tuple) and key[0] == gid and isinstance(value, list))
    ach = state.get("achievement_data", {})
    ach_users = [(key, value) for key, value in ach.items() if isinstance(key, tuple) and len(key) >= 2 and key[0] == gid and isinstance(value, dict)]
    unlocked = sum(len(value.get("unlocked", [])) for _, value in ach_users)
    qdata = state.get("quest_data", {})
    quest_users = [(key, value) for key, value in qdata.items() if isinstance(key, tuple) and len(key) >= 2 and key[0] == gid]
    balances = state.get("economy_balances", {})
    guild_balances = [(key, value) for key, value in balances.items() if isinstance(key, tuple) and len(key) >= 2 and key[0] == gid]
    total_catnip = sum(max(0, int(value or 0)) for _, value in guild_balances)
    giveaways = state.get("active_giveaways", {})
    active_giveaways = sum(1 for value in giveaways.values() if isinstance(value, dict) and int(value.get("guild_id", 0) or 0) == gid)
    polls = state.get("active_polls", {})
    active_polls = sum(1 for value in polls.values() if isinstance(value, dict) and int(value.get("guild_id", 0) or 0) == gid)
    cards = [
        ("Members", guild.member_count or len(guild.members), "Server size"),
        ("Members with XP", len(xp_users), f"{total_xp:,} total XP tracked"),
        ("Warnings", warning_count, "Tracked moderation warnings"),
        ("Achievements", unlocked, f"Across {len(ach_users)} tracked member records"),
        ("Quest profiles", len(quest_users), "Members with quest state"),
        ("Catnip in circulation", total_catnip, f"Across {len(guild_balances)} tracked accounts"),
        ("Active giveaways", active_giveaways, "Currently tracked giveaways"),
        ("Active polls", active_polls, "Currently tracked polls"),
    ]
    card_html = "".join(f"<article class='card third'><div class='statlabel'>{_esc(label)}</div><div class='stat'>{int(value):,}</div><p class='muted'>{_esc(note)}</p></article>" for label, value, note in cards)
    body = ("<h1>Server analytics</h1><p class='muted'>Live counters read from Cinnamon's current runtime. These are not historical charts; counters may reset if the bot's non-persistent state is lost.</p>"
            f"<div class='grid'>{card_html}<article class='card full'><h2>Explore a feature</h2><p class='muted'>Jump into the live controls behind each metric.</p><div class='actions'><a class='btn' href='/dashboard?guild_id={gid}&tab=engagement'>Levels & XP</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=achievements'>Achievements</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=quests'>Quests</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=economy'>Catnip economy</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=activity_logs'>Activity logs</a></div></article></div>")
    return body


def _message_studio(guild, state):
    gid = guild.id
    channel_select = _channel_select(guild, "channel_id", allow_none=False)
    form = ("<div class='formgrid'><div class='field'><label>Destination channel</label>" + channel_select + "<small>Choose a text channel Cinnamon can send messages to.</small></div>"
            "<div class='field'><label>Embed accent colour</label><input name='embed_color' type='color' value='#D97732' required></div>"
            "<div class='field'><label>Embed title</label><input name='embed_title' maxlength='256' placeholder='A message from Cinnamon' required></div>"
            "<div class='field'><label>Footer</label><input name='embed_footer' maxlength='200' value='Cinnamon • Made with paws 🐾'></div>"
            "<div class='field' style='grid-column:1/-1'><label>Message text</label><textarea name='embed_description' maxlength='4000' rows='5' placeholder='Write the message content here…' required></textarea><small>Discord embed descriptions support up to 4,000 characters. Mentions are disabled for safety.</small></div>"
            "<div class='field' style='grid-column:1/-1'><label>Optional image URL (HTTPS)</label><input name='embed_image' type='url' maxlength='500' placeholder='https://…'><small>Optional. Only HTTPS image URLs are accepted.</small></div></div>"
            "<label class='toggle'><input type='checkbox' name='send_confirmation' value='yes' required><span><b>I checked the destination and message</b><small>Sending is immediate and cannot be undone.</small></span></label>")
    guide = ("<article class='card half'><h2>Embed checklist</h2><div class='toggle'><span><b>Readable title</b><small>Short, specific and easy to scan.</small></span></div>"
             "<div class='toggle'><span><b>Clear body text</b><small>Use line breaks and avoid walls of text.</small></span></div>"
             "<div class='toggle'><span><b>Consistent Cinnamon look</b><small>Warm orange accent, friendly footer, no surprise mentions.</small></span></div>"
             "<div class='rule'></div><p class='muted'>The studio sends a real Discord embed. The dashboard action and destination are recorded in the dedicated dashboard audit log.</p></article>")
    return ("<h1>Message Studio</h1><p class='muted'>Compose and publish a polished Cinnamon embed to a channel in this server.</p><div class='grid'>"
            "<article class='card half'><h2>Compose an embed</h2>" + _form(gid, "message_send", form, "Send embed") + "</article>" + guide + "</div>")


def _activity_logs(guild, state):
    gid = guild.id
    reader = state.get("audit_recent")
    status_reader = state.get("audit_storage_status")
    entries = []
    source_note = "External Upstash activity history"
    storage_status = {}
    if callable(reader):
        try:
            events = _run_bot(reader(gid, limit=100), timeout=20)
            if callable(status_reader):
                storage_status = _run_bot(status_reader(), timeout=12) or {}
            for event in events:
                try:
                    when = dt.datetime.fromisoformat(str(event.get("timestamp", "")).replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    when = None
                metadata = event.get("metadata") or {}
                detail_parts = []
                if event.get("actor_id"):
                    detail_parts.append("Actor ID: " + str(event["actor_id"]))
                if event.get("target_id"):
                    detail_parts.append("Target ID: " + str(event["target_id"]))
                if event.get("channel_id"):
                    detail_parts.append("Channel ID: " + str(event["channel_id"]))
                detail_parts.extend(str(k) + ": " + str(v) for k, v in list(metadata.items())[:5])
                entries.append((when, str(event.get("category", "general")), "Upstash",
                                str(event.get("action", "Activity")), " · ".join(detail_parts), ""))
        except Exception:
            log.exception("External activity log read failed for guild %s", gid)
            source_note = "External history unavailable — showing recent Discord log messages instead"
    if not entries:
        routes = state.get("category_log_channels", {}).get(gid, {}) or state.get("category_log_channels", {}).get(str(gid), {})
        configured = []
        for category, channel_id in routes.items():
            channel = guild.get_channel(int(channel_id)) if str(channel_id).isdigit() else None
            if channel and hasattr(channel, "history"):
                configured.append((str(category), channel))
        for category, channel_id in [("moderation", state.get("log_channels", {}).get(gid)),
                                      ("economy", state.get("economy_log_channels", {}).get(gid))]:
            channel = guild.get_channel(int(channel_id)) if channel_id and str(channel_id).isdigit() else None
            if channel and hasattr(channel, "history") and all(ch.id != channel.id for _, ch in configured):
                configured.append((category, channel))
        hg = state.get("hg_cog")
        if hg:
            channel = guild.get_channel(hg.hg_log_channels.get(gid, 0))
            if channel and hasattr(channel, "history") and all(ch.id != channel.id for _, ch in configured):
                configured.append(("hangry", channel))
        async def read_recent():
            rows = []
            for category, channel in configured[:15]:
                try:
                    async for message in channel.history(limit=8, oldest_first=False):
                        if not message.embeds:
                            continue
                        embed = message.embeds[0]
                        rows.append((message.created_at, category, channel.name,
                                     embed.title or "Cinnamon log event", embed.description or "",
                                     str(message.jump_url)))
                except Exception as exc:
                    rows.append((None, category, channel.name, "Could not read this log channel",
                                 type(exc).__name__, ""))
            rows.sort(key=lambda item: item[0] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
            return rows[:40]
        try:
            entries = _run_bot(read_recent(), timeout=25)
        except Exception:
            log.exception("Discord activity log fallback failed")
            entries = []
        source_note = "Discord log-channel fallback (limited history)"
    query = request.args.get("q", "").strip()[:100].casefold()
    category_filter = request.args.get("category", "all").strip().casefold()
    categories = sorted({row[1].casefold() for row in entries})
    if category_filter not in categories and category_filter != "all":
        category_filter = "all"
    if category_filter != "all":
        entries = [row for row in entries if row[1].casefold() == category_filter]
    if query:
        entries = [row for row in entries if query in " ".join(map(str, row[1:5])).casefold()]
    category_options = "<option value='all'>All categories</option>" + "".join(
        f"<option value='{_esc(category)}'{' selected' if category == category_filter else ''}>{_esc(category.title())}</option>"
        for category in categories
    )
    filters_html = (f"<form method='get' action='/dashboard' class='formgrid'><input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='tab' value='activity_logs'>"
                    f"<div class='field'><label>Search recent events</label><input name='q' maxlength='100' value='{_esc(query)}' placeholder='Search event, actor ID, details…'></div>"
                    f"<div class='field'><label>Category</label><select name='category'>{category_options}</select></div><div class='field'><label>&nbsp;</label><button class='btn' type='submit'>Filter events</button> <a class='btn secondary' href='/dashboard?guild_id={gid}&tab=activity_logs'>Clear</a></div></form>")
    if not entries:
        rows_html = "<tr><td colspan='4'>No external records found yet. New events will appear after external audit storage is connected.</td></tr>"
    else:
        rows = []
        for when, category, channel_name, title, description, jump_url in entries[:100]:
            timestamp = when.strftime("%Y-%m-%d %H:%M UTC") if when else "Unavailable"
            link = f"<a class='btn secondary small' href='{_esc(jump_url)}' target='_blank' rel='noopener noreferrer'>Open in Discord</a>" if jump_url.startswith("https://discord.com/") else "External record"
            rows.append(f"<tr><td>{_esc(timestamp)}</td><td>{_esc(category.title())}<br><small>{_esc(channel_name)}</small></td><td><b>{_esc(title[:180])}</b><br><small>{_esc(description[:260])}</small></td><td>{link}</td></tr>")
        rows_html = "".join(rows)
    health = ("Connected" if storage_status.get("connected") else
              "Not verified" if not storage_status else "Unavailable")
    return ("<h1>Activity logs</h1><p class='muted'>Searchable external audit records stored separately from Cinnamon's bot snapshot. Private message text and AI prompts/replies are not stored by the shared logger.</p>"
            f"<article class='card full'><h2>External storage</h2><div class='toggle'><b>Upstash audit connection</b><span class='pill {'good' if storage_status.get('connected') else 'warn'}'>{_esc(health)}</span></div>"
            f"<p class='muted'>{_esc(source_note)} · {len(entries)} record(s) currently loaded · Retention: {_esc(storage_status.get('retention_days', 'unknown'))} days · Per-server cap: {_esc(storage_status.get('max_events', 'unknown'))}</p></article>"
            f"<article class='card full'><h2>Find an event</h2>{filters_html}</article>"
            f"<article class='card full'><h2>Recent events</h2><div class='tablewrap'><table><thead><tr><th>Time</th><th>Category / source</th><th>Event</th><th>Location</th></tr></thead><tbody>{rows_html}</tbody></table></div></article>"
            f"<div class='actions'><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=system'>Manage log routing</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=analytics'>View analytics</a></div>")


def _backup_guild_value(state, key, gid):
    mapping=state.get(key,{}) or {}
    return mapping.get(gid, mapping.get(str(gid)))


def _backup_json_safe(value):
    if isinstance(value,dict): return {str(k):_backup_json_safe(v) for k,v in value.items()}
    if isinstance(value,(set,tuple,list)): return [_backup_json_safe(v) for v in value]
    if value is None or isinstance(value,(str,int,float,bool)): return value
    return str(value)


def _guild_config_payload(guild, state):
    gid=int(guild.id)
    keys=("welcome_config","goodbye_config","automod_config","antiraid_config","xp_per_message","xp_channels",
          "level_roles","achievement_config","quest_config","ai_channels","disabled_channels","log_channels",
          "category_log_channels","economy_log_channels","economy_income_roles")
    config={}
    for key in keys:
        value=_backup_guild_value(state,key,gid)
        if value is not None:
            config[key]=_backup_json_safe(value)
    templates=state.get("giveaway_templates",{}) or {}
    config["giveaway_templates"]=_backup_json_safe(templates.get(gid,templates.get(str(gid),{})) or {})
    schedules=state.get("giveaway_schedules",{}) or {}
    config["giveaway_schedules"]=_backup_json_safe({str(k):v for k,v in schedules.items() if int(v.get("guild_id",0))==gid})
    return {"format":"cinnamon-config-backup","schema_version":1,"guild_id":gid,
            "guild_name":str(guild.name),"created_at":dt.datetime.now(dt.timezone.utc).isoformat(),
            "notes":"Configuration only. Balances, inventories, user progress, active giveaways, tokens and secrets are excluded.",
            "config":config}


@dashboard_bp.get("/dashboard/backup")
def dashboard_backup_download():
    sid=session.get("dash_sid")
    if not sid or sid not in _tokens: return redirect(url_for("cinnamon_dashboard.login"))
    context=_dashboard_context()
    if not context: return redirect(url_for("cinnamon_dashboard.login"))
    sid,guilds,eligible=context
    if not eligible: abort(403)
    guild_id=request.args.get("guild_id") or eligible[0]["id"]
    guild,_=_get_access(sid,guilds,guild_id)
    payload=_guild_config_payload(guild,_state())
    response=make_response(json.dumps(payload,ensure_ascii=False,indent=2))
    response.headers["Content-Type"]="application/json; charset=utf-8"
    response.headers["Content-Disposition"]=f'attachment; filename="cinnamon-config-{guild.id}.json"'
    return response


def _restore_guild_config_impl(guild, state, payload):
    if not isinstance(payload,dict) or payload.get("format")!="cinnamon-config-backup" or payload.get("schema_version")!=1:
        raise ValueError("This file is not a supported Cinnamon configuration backup.")
    if str(payload.get("guild_id"))!=str(guild.id):
        raise ValueError("This backup belongs to a different Discord server. Nothing was changed.")
    config=payload.get("config")
    if not isinstance(config,dict): raise ValueError("The backup's config section is missing or invalid.")
    allowed={"welcome_config","goodbye_config","automod_config","antiraid_config","xp_per_message","xp_channels",
             "level_roles","achievement_config","quest_config","ai_channels","disabled_channels","log_channels",
             "category_log_channels","economy_log_channels","economy_income_roles"}
    changed=[]
    for key in allowed:
        if key not in config: continue
        value=config[key]
        target=state.setdefault(key,{})
        if key in {"welcome_config","goodbye_config"}:
            if value is not None:
                if not isinstance(value,dict) or not str(value.get("message","")) or len(str(value.get("message","")))>800:
                    raise ValueError(f"Backup section {key} has an invalid message template.")
                channel_id=value.get("channel_id")
                if not str(channel_id).isdigit() or not guild.get_channel(int(channel_id)):
                    raise ValueError(f"Backup section {key} refers to a channel that is not in this server.")
                value={"channel_id":int(channel_id),"message":str(value["message"])}
        elif key in {"ai_channels","log_channels","economy_log_channels"}:
            if value is not None:
                if not str(value).isdigit() or not guild.get_channel(int(value)):
                    raise ValueError(f"Backup section {key} refers to a channel that is not in this server.")
                value=int(value)
        elif key in {"xp_per_message"}:
            if not isinstance(value,int) or isinstance(value,bool) or not 0<=value<=100:
                raise ValueError("XP per message must be a whole number between 0 and 100.")
        elif key in {"xp_channels","disabled_channels"}:
            if not isinstance(value,list): raise ValueError(f"Backup section {key} must be a list of channel IDs.")
            clean=[]
            for item in value:
                if str(item).isdigit() and guild.get_channel(int(item)):
                    clean.append(int(item))
            value=set(dict.fromkeys(clean))
        elif key=="level_roles":
            if not isinstance(value,dict): raise ValueError("Level roles must be a mapping of level to role ID.")
            clean={}
            for level,role_id in value.items():
                if not str(level).isdigit() or not 1<=int(level)<=200 or not str(role_id).isdigit(): continue
                role=guild.get_role(int(role_id))
                if role and not role.is_default() and not role.managed and guild.me and role < guild.me.top_role:
                    clean[int(level)]=role.id
            value=clean
        elif key=="category_log_channels":
            if not isinstance(value,dict): raise ValueError("Category log routing must be an object.")
            value={str(category):int(channel_id) for category,channel_id in value.items()
                   if str(channel_id).isdigit() and guild.get_channel(int(channel_id))}
        elif key=="economy_income_roles":
            if not isinstance(value,dict): raise ValueError("Role income settings must be an object.")
            clean={}
            for role_id,cfg in value.items():
                role=guild.get_role(int(role_id)) if str(role_id).isdigit() else None
                if not role or role.is_default() or role.managed or not isinstance(cfg,dict): continue
                try: amount=int(cfg.get("amount",0)); cooldown=int(cfg.get("cooldown",3600))
                except (TypeError,ValueError): continue
                if 1<=amount<=1_000_000 and 60<=cooldown<=31_536_000:
                    clean[role.id]={"amount":amount,"cooldown":cooldown,
                                    "interval":max(1,int(cfg.get("interval",max(1,cooldown//60)))),
                                    "unit":str(cfg.get("unit","minute"))[:10]}
            value=clean
        elif key in {"automod_config","antiraid_config","achievement_config","quest_config"}:
            if not isinstance(value,dict): raise ValueError(f"Backup section {key} must be an object.")
            if key=="automod_config":
                words=value.get("words",[])
                if not isinstance(words,list): words=[]
                value={"words":[str(w)[:100] for w in words[:50] if str(w).strip()],
                       "spam":bool(value.get("spam")),"mentions":bool(value.get("mentions")),
                       "invites":bool(value.get("invites")),"mention_threshold":max(2,min(20,int(value.get("mention_threshold",5))))}
            elif key=="antiraid_config":
                value={"enabled":bool(value.get("enabled")),"threshold":max(2,min(100,int(value.get("threshold",5)))),
                       "window":max(2,min(300,int(value.get("window",10))))}
        if value is None:
            target.pop(guild.id,None); target.pop(str(guild.id),None)
        else:
            target[guild.id]=value
        changed.append(key)
    if "giveaway_templates" in config:
        templates=config["giveaway_templates"]
        if not isinstance(templates,dict) or len(templates)>100: raise ValueError("Giveaway templates must be an object with at most 100 entries.")
        clean={}
        for name,cfg in templates.items():
            if not isinstance(cfg,dict): continue
            name=str(name).strip().lower()[:40]
            prize=str(cfg.get("prize","Giveaway"))[:200]
            try: winners=max(1,min(100,int(cfg.get("winners",1))))
            except (TypeError,ValueError): winners=1
            clean[name]=dict(cfg,prize=prize,winners=winners)
        state.setdefault("giveaway_templates",{})[guild.id]=clean
        changed.append("giveaway_templates")
    if "giveaway_schedules" in config:
        schedules=config["giveaway_schedules"]
        if not isinstance(schedules,dict) or len(schedules)>50: raise ValueError("Recurring giveaway schedules must be an object with at most 50 entries.")
        target=state.setdefault("giveaway_schedules",{})
        for sid,item in list(target.items()):
            if int(item.get("guild_id",0))==guild.id: target.pop(sid,None)
        for sid,item in schedules.items():
            if not isinstance(item,dict) or int(item.get("guild_id",0))!=guild.id: continue
            try:
                channel_id=int(item.get("channel_id",0)); winners=max(1,min(100,int(item.get("winners",1))))
                duration=max(1,min(525600,int(item.get("duration_minutes",1440))))
                repeat_days=max(1,min(365,int(item.get("repeat_every_days",7))))
                next_at=max(time.time()+60,float(item.get("next_at",time.time()+86400)))
            except (TypeError,ValueError): continue
            channel=guild.get_channel(channel_id); prize=str(item.get("prize",""))[:200]
            if not channel or not prize: continue
            target[str(sid)]=dict(item,channel_id=channel_id,prize=prize,guild_id=guild.id,winners=winners,
                duration_minutes=duration,repeat_every_days=repeat_days,next_at=next_at,enabled=bool(item.get("enabled",True)))
        changed.append("giveaway_schedules")
    return sorted(set(changed))


def _restore_guild_config(guild, state, payload):
    """Restore config atomically: invalid files must not leave partial changes in memory."""
    keys=("welcome_config","goodbye_config","automod_config","antiraid_config","xp_per_message","xp_channels",
          "level_roles","achievement_config","quest_config","ai_channels","disabled_channels","log_channels",
          "category_log_channels","economy_log_channels","economy_income_roles","giveaway_templates","giveaway_schedules")
    present={key for key in keys if key in state}
    snapshots={key:copy.deepcopy(state[key]) for key in present if isinstance(state[key],dict)}
    try:
        return _restore_guild_config_impl(guild,state,payload)
    except Exception:
        for key in keys:
            if key not in present:
                state.pop(key,None)
                continue
            snapshot=snapshots.get(key)
            current=state.get(key)
            if snapshot is not None and isinstance(current,dict):
                current.clear(); current.update(snapshot)
            elif snapshot is not None:
                state[key]=snapshot
        raise


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
        body="<section class='hero'><div><h1>No manageable server found</h1><p>Add Cinnamon to a server where you are the owner or have Administrator permission, then reload.</p></div><img class='heroimg' src='/static/cinnamon_mascot.svg' alt='Cinnamon'></section>"
        return _page("<main class='main'>"+_header()+body+"</main>")
    guild_id=request.args.get("guild_id") or eligible[0]["id"]
    guild,guild_item=_get_access(sid,guilds,guild_id)
    tab=request.args.get("tab","overview"); allowed={"overview","mind","adventure","automation","moderation","engagement","achievements","quests","friendship","companions","economy","giveaways","tickets","roles_setup","hangry","community","message_studio","analytics","activity_logs","system"}
    if tab not in allowed: tab="overview"
    state=_state(); notice=session.pop("dashboard_notice",None)
    pages={"overview":_overview,"mind":_mind,"adventure":_adventure,"automation":_automation,"moderation":_moderation,"engagement":_engagement,"achievements":_achievements,"quests":_quests,"friendship":_friendship,"companions":_companions,"economy":_economy,"giveaways":_giveaways,"tickets":_tickets,"roles_setup":_roles_setup,"hangry":_hangry,"community":_community,"message_studio":_message_studio,"analytics":_analytics,"activity_logs":_activity_logs,"system":_system}
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
        async def authorize_dashboard_edit():
            uid=int(_tokens[sid]["user"]["id"])
            return await _dashboard_is_admin(guild, uid)
        if not _run_bot(authorize_dashboard_edit()):
            raise PermissionError("Dashboard changes require Administrator permission.")
        if action in {"welcome","goodbye","ai_channel","log_channel","special_logs","automod","antiraid","levelrole_add","levelrole_remove","economy_item_add","economy_item_save","economy_item_remove","economy_income_add","economy_income_remove","giveaway_create","giveaway_edit","giveaway_draft_save","giveaway_draft_update","giveaway_draft_publish","giveaway_draft_delete","giveaway_end","giveaway_cancel","giveaway_template_save","giveaway_template_delete","giveaway_repeat_create","giveaway_repeat_stop","giveaway_reroll","config_backup_restore","hangry_logs","recall","message_send","community_features_settings","community_event_create","community_event_cancel","community_poll_create","community_poll_close","security_settings","moderation_controls_settings","verification_publish","appeal_settings","dashboard_appeal_review","ticket_dashboard_claim","ticket_dashboard_unclaim"}:
            if not _tokens[sid]["user"].get("id"): abort(401)
        if action=="brain_settings":
            _run_bot(_apply_brain_settings(
                state, gid, independence_enabled="independence_enabled" in request.form,
                chat_actions_enabled="chat_actions_enabled" in request.form,
                prompts_enabled="prompts_enabled" in request.form,
                ai_judgment_enabled="ai_judgment_enabled" in request.form))
            _audit(gid,actor,"Dashboard: Cinnamon boundaries updated",
                   f"Independence={bool('independence_enabled' in request.form)}; conversational actions={bool('chat_actions_enabled' in request.form)}.")
            session["dashboard_notice"]="Cinnamon's activity and action boundaries saved."
        elif action=="mind_settings":
            raw=request.form.get("channel_id","").strip()
            if not raw.isdigit(): raise ValueError("Choose a valid Hangry Games channel.")
            channel=guild.get_channel(int(raw))
            if not isinstance(channel,__import__("discord").TextChannel):
                raise ValueError("Choose a text channel in this server.")
            if not channel.permissions_for(guild.default_role).view_channel:
                raise ValueError("Surprise games must run in a public channel. Members need to see the join button.")
            perms = channel.permissions_for(guild.me) if guild.me else None
            if not perms or not (perms.view_channel and perms.send_messages and perms.embed_links):
                raise ValueError("Cinnamon needs View Channel, Send Messages and Embed Links in the selected game channel.")
            flags={k:k in request.form for k in ("auto_enabled","cameos_enabled","questions_enabled")}
            play_on="play_enabled" in request.form
            async def apply_mind():
                social=state["cinnamon_social"].setdefault(str(gid),{"people":{}})
                old=social.get("auto_channel")
                social.update(flags)
                state["cinnamon_actions"].setdefault(str(gid), {"players": {}})["play_enabled"]=play_on
                social["auto_channel"]=channel.id
                if old!=channel.id or (flags["auto_enabled"] and not social.get("next_at")):
                    social["next_at"]=time.time()+__import__("random").randint(3600,7200)
                if not await state["bd_save_data"]():
                    raise ValueError("The durable settings save could not be verified. Check storage before trying again.")
            _run_bot(apply_mind())
            _audit(gid,actor,"Dashboard: Cinnamon Mind settings updated",
                   f"Hangry channel #{channel.name}; flags={flags}.")
            session["dashboard_notice"]="Cinnamon Mind controls saved."
        elif action=="merchant_access":
            kind=request.form.get("merchant_kind","")
            mode=request.form.get("access","")
            if kind not in ("rod","bait") or mode not in ("private","two_hours","public"):
                raise ValueError("Choose a known fishing merchant and visibility option.")
            announce="announce" in request.form
            async def apply_merchant():
                import discord
                import time as _time
                root=state["cinnamon_wildlands_fishing"].setdefault(str(gid),{})
                window=root.setdefault("merchant_windows",{}).setdefault(kind,{})
                old=dict(window)
                window.update({"finder_id":None,"manual_public":mode=="public",
                               "ends_at":_time.time()+7200 if mode=="two_hours" else 0,
                               "closed_notice":mode=="private"})
                try:
                    channel=await state["wlf_refresh_channel"](guild,kind)
                    await state["bd_save_data"]()
                except Exception:
                    window.clear();window.update(old)
                    raise
                if mode!="private":
                    role=discord.utils.get(guild.roles,name=state["wlf_merchant_names"][kind])
                    line="🐈 The "+state["wlf_merchant_names"][kind]+" is open in "+channel.mention+"!"
                    if mode=="two_hours": line+=" Two-hour limited opening."
                    if announce and role: line=role.mention+" "+line
                    await channel.send(line,allowed_mentions=discord.AllowedMentions(
                        everyone=False,users=False,roles=[role] if announce and role else []))
                return channel.name
            name=_run_bot(apply_merchant(),timeout=40)
            _audit(gid,actor,"Dashboard: fishing merchant access",
                   f"Merchant={kind}; action={mode}; channel=#{name}; role announcement={announce}.")
            session["dashboard_notice"]="Merchant access updated for #"+name+"."
        elif action=="economy_transfer":
            target_raw=request.form.get("member_id","").strip()
            nonce=request.form.get("transfer_nonce","").strip()
            try: amount=int(request.form.get("amount",""))
            except ValueError: raise ValueError("Catnip amount must be a positive whole number.")
            if not 1<=amount<=10000000 or not target_raw.isdigit() or len(nonce)<16 or len(nonce)>100:
                raise ValueError("Choose a member and 1–10,000,000 Catnip.")
            recipient=guild.get_member(int(target_raw))
            actor_id=int(_tokens[sid]["user"]["id"])
            if not recipient or recipient.bot or recipient.id==actor_id:
                raise ValueError("Choose a different non-bot member by name.")
            async def transfer():
                lock=getattr(_bot,"_dashboard_catnip_lock",None)
                if lock is None:
                    lock=asyncio.Lock()
                    _bot._dashboard_catnip_lock=lock
                async with lock:
                    root=state["advanced_features_data"].setdefault("dashboard_transfer_ids_v1",{})
                    used=root.setdefault(str(gid),[])
                    if nonce in used: raise ValueError("This transfer was already submitted.")
                    balances=state["economy_balances"]
                    before=int(balances.get((gid,actor_id),0))
                    if before<amount: raise ValueError("Your own Catnip balance is too low for that gift.")
                    recv_before=int(balances.get((gid,recipient.id),0))
                    balances[(gid,actor_id)]=before-amount
                    balances[(gid,recipient.id)]=recv_before+amount
                    used.append(nonce)
                    del used[:-100]
                    await state["bd_save_data"]()
                    return before,recv_before
            before,recv_before=_run_bot(transfer())
            send_log=state["send_log"]
            _run_bot(send_log(gid,title="🎁 Catnip transfer",category="economy",fields=[
                ("From",f"{actor} ({actor_id})"),("To",f"{recipient} ({recipient.id})"),
                ("Amount",f"{amount:,} Catnip"),("Sender after",str(before-amount)),
                ("Recipient after",str(recv_before+amount))]))
            _audit(gid,actor,"Dashboard: Catnip gift",
                   f"Sent {amount:,} Catnip to {recipient} ({recipient.id}) from actor's wallet.")
            session["dashboard_notice"]=f"Sent {amount:,} Catnip to {recipient.display_name}."
        elif action=="appeal_settings":
            raw=request.form.get("appeal_channel_id","").strip()
            channel=guild.get_channel(int(raw)) if raw.isdigit() else None
            if raw and not isinstance(channel,__import__("discord").TextChannel):
                raise ValueError("Choose a valid appeal text channel.")
            if channel and channel.permissions_for(guild.default_role).view_channel:
                raise ValueError("Appeal channels must be private to moderators.")
            async def save_appeal_channel():
                root=state["advanced_features_data"].setdefault("cinnamon_moderation_controls_v1",{})
                cfg=root.setdefault(str(gid),{})
                before=cfg.get("appeal_channel_id",0)
                cfg["appeal_channel_id"]=int(channel.id) if channel else 0
                if not await state["bd_save_data"]():
                    cfg["appeal_channel_id"]=before
                    raise ValueError("Couldn't durably save the appeal channel.")
            _run_bot(save_appeal_channel())
            _audit(gid,actor,"Dashboard: appeal channel updated",f"Appeal channel={channel.id if channel else 0}.")
            session["dashboard_notice"]="Private appeal channel saved."
        elif action=="dashboard_appeal_review":
            appeal_id=request.form.get("appeal_id","").strip()
            decision=request.form.get("decision","").strip()
            if decision not in {"approved","declined"}: raise ValueError("Choose an appeal decision.")
            async def review_dashboard_appeal():
                root=state["advanced_features_data"].setdefault("cinnamon_moderation_controls_v1",{})
                cfg=root.setdefault(str(gid),{})
                record=cfg.setdefault("appeals",{}).get(appeal_id)
                if not isinstance(record,dict) or record.get("status")!="pending":
                    raise ValueError("That appeal is no longer pending.")
                before=__import__("copy").deepcopy(record)
                reviewer_id=int(_tokens[sid]["user"]["id"])
                record["status"],record["reviewed_by"]=decision,reviewer_id
                record["review_note"]="Reviewed from the dashboard."
                record["reviewed_at"]=int(time.time())
                if not await state["bd_save_data"]():
                    record.clear();record.update(before)
                    raise ValueError("Could not durably save the appeal decision.")
                try:
                    user=await state["bot"].fetch_user(int(record.get("user_id",0)))
                    await user.send(f"Your moderation appeal for {guild.name} was {decision}.")
                except Exception:
                    pass
                channel=guild.get_channel(int(record.get("channel_id",0) or 0))
                view_class=state.get("ModerationAppealView")
                if channel and callable(view_class):
                    try:
                        message=await channel.fetch_message(int(record.get("message_id",0)))
                        embed=__import__("discord").Embed(title="Moderation appeal "+decision.title(),
                            description="The appeal has been reviewed by server moderation.",color=0x69A982 if decision=="approved" else 0xD97777)
                        await message.edit(embed=embed,view=view_class(gid,appeal_id,disabled=True))
                    except __import__("discord").HTTPException:
                        pass
            _run_bot(review_dashboard_appeal())
            _audit(gid,actor,"Dashboard: moderation appeal reviewed",f"Appeal {appeal_id} marked {decision}.")
            session["dashboard_notice"]="Appeal "+appeal_id+" marked "+decision+"."
        elif action=="security_settings":
            def optional_security_channel():
                raw=request.form.get("alert_channel_id","").strip()
                if not raw: return 0
                if not raw.isdigit(): raise ValueError("Choose a valid private security alert channel.")
                channel=guild.get_channel(int(raw))
                if not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Choose a text channel in this server.")
                if channel.permissions_for(guild.default_role).view_channel:
                    raise ValueError("Security alert channels should be private to moderators.")
                return int(channel.id)
            try:
                spam_threshold=int(request.form.get("antispam_threshold","6"))
                spam_window=int(request.form.get("antispam_window","8"))
                spam_timeout=int(request.form.get("antispam_timeout","60"))
                nuke_threshold=int(request.form.get("antinuke_threshold","3"))
            except ValueError:
                raise ValueError("Security thresholds and durations must be whole numbers.")
            if not 4<=spam_threshold<=15 or not 3<=spam_window<=30 or not 30<=spam_timeout<=3600 or not 2<=nuke_threshold<=8:
                raise ValueError("Check anti-spam and anti-nuke ranges.")
            alert_channel_id=optional_security_channel()
            async def apply_security_settings():
                root=state["advanced_features_data"].setdefault("cinnamon_security_guard_v1",{})
                cfg=root.setdefault(str(gid),{})
                before=__import__("copy").deepcopy(cfg)
                cfg.update({"antispam_enabled":"antispam_enabled" in request.form,
                            "antispam_threshold":spam_threshold,"antispam_window":spam_window,
                            "antispam_timeout":spam_timeout,"antinuke_enabled":"antinuke_enabled" in request.form,
                            "antinuke_threshold":nuke_threshold,"alert_channel_id":alert_channel_id})
                if not await state["bd_save_data"]():
                    cfg.clear();cfg.update(before)
                    raise ValueError("The durable security settings save could not be verified. No changes were kept.")
            _run_bot(apply_security_settings())
            _audit(gid,actor,"Dashboard: security safeguards updated",
                   f"Anti-spam={'enabled' if 'antispam_enabled' in request.form else 'disabled'}; anti-nuke={'enabled' if 'antinuke_enabled' in request.form else 'disabled'}; alert channel={alert_channel_id}.")
            session["dashboard_notice"]="Anti-spam and anti-nuke settings saved."
        elif action=="moderation_controls_settings":
            def optional_role(field):
                raw=request.form.get(field,"").strip()
                if not raw: return 0
                if not raw.isdigit(): raise ValueError("Choose a valid role.")
                role=guild.get_role(int(raw))
                if not role or role.is_default() or role.managed: raise ValueError("Choose a valid assignable role.")
                if role>=guild.me.top_role: raise ValueError("Cinnamon's bot role must be above each role it assigns.")
                return int(role.id)
            def optional_channel(field):
                raw=request.form.get(field,"").strip()
                if not raw: return 0
                if not raw.isdigit(): raise ValueError("Choose a valid channel.")
                channel=guild.get_channel(int(raw))
                if not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Choose a text channel from this server.")
                return int(channel.id)
            autorole_id=optional_role("autorole_id")
            verification_role_id=optional_role("verification_role_id")
            verification_channel_id=optional_channel("verification_channel_id")
            welcome_channel_id=optional_channel("welcome_channel_id")
            rules_channel_id=optional_channel("rules_channel_id")
            if bool(verification_role_id)!=bool(verification_channel_id):
                raise ValueError("Choose both a verification channel and role, or leave both blank.")
            if verification_channel_id:
                channel=guild.get_channel(verification_channel_id)
                perms=channel.permissions_for(guild.me)
                if not (perms.view_channel and perms.send_messages and perms.embed_links):
                    raise ValueError("Cinnamon needs View Channel, Send Messages and Embed Links in the verification channel.")
            async def apply_moderation_controls():
                root=state["advanced_features_data"].setdefault("cinnamon_moderation_controls_v1",{})
                cfg=root.setdefault(str(gid),{})
                before=__import__("copy").deepcopy(cfg)
                cfg.update({"autorole_id":autorole_id,"verification_role_id":verification_role_id,
                            "verification_channel_id":verification_channel_id})
                cfg["onboarding"]={"welcome_channel_id":welcome_channel_id,"rules_channel_id":rules_channel_id}
                if not await state["bd_save_data"]():
                    cfg.clear();cfg.update(before)
                    raise ValueError("The durable onboarding settings save could not be verified. No changes were kept.")
            _run_bot(apply_moderation_controls())
            _audit(gid,actor,"Dashboard: verification and onboarding settings updated",
                   f"Autorole={autorole_id}; verification role={verification_role_id}; verification channel={verification_channel_id}; welcome={welcome_channel_id}; rules={rules_channel_id}.")
            session["dashboard_notice"]="Verification, autorole and onboarding settings saved."
        elif action=="verification_publish":
            async def publish_verification():
                root=state["advanced_features_data"].setdefault("cinnamon_moderation_controls_v1",{})
                cfg=root.setdefault(str(gid),{})
                channel=guild.get_channel(int(cfg.get("verification_channel_id",0) or 0))
                role=guild.get_role(int(cfg.get("verification_role_id",0) or 0))
                view_class=state.get("CinnamonVerificationView")
                if not isinstance(channel,__import__("discord").TextChannel) or not role or not callable(view_class):
                    raise ValueError("Configure a verification channel and role before publishing the panel.")
                if role>=guild.me.top_role or not guild.me.guild_permissions.manage_roles:
                    raise ValueError("Cinnamon's bot role must be above the verification role and have Manage Roles.")
                embed=__import__("discord").Embed(title="🔐 Server Verification",
                    description=f"Press Verify below to receive {role.mention} and finish server verification.",
                    color=0x91B5A2)
                old_channel_id=int(cfg.get("verification_channel_id",0) or 0)
                old_message_id=int(cfg.get("verification_message_id",0) or 0)
                message=await channel.send(embed=embed,view=view_class(gid),
                    allowed_mentions=__import__("discord").AllowedMentions.none())
                before=old_message_id
                cfg["verification_message_id"]=int(message.id)
                if not await state["bd_save_data"]():
                    cfg["verification_message_id"]=before
                    try: await message.delete()
                    except __import__("discord").HTTPException: pass
                    raise ValueError("Could not save the published verification panel. The new post was removed.")
                if old_message_id:
                    old_channel=guild.get_channel(old_channel_id)
                    if old_channel:
                        try:
                            old_message=await old_channel.fetch_message(old_message_id)
                            await old_message.edit(view=view_class(gid,disabled=True))
                        except __import__("discord").HTTPException:
                            pass
                return channel.mention
            channel_mention=_run_bot(publish_verification())
            _audit(gid,actor,"Dashboard: verification panel published",f"Posted in {channel_mention}.")
            session["dashboard_notice"]="Verification panel published in "+channel_mention+"."
        elif action=="community_poll_create":
            question=request.form.get("question","").strip()[:240]
            options=[request.form.get("option_"+str(i),"").strip()[:80] for i in range(1,6)]
            options=[value for value in options if value]
            raw_channel=request.form.get("channel_id","").strip()
            try: duration=int(request.form.get("duration_minutes","1440"))
            except ValueError: raise ValueError("Poll duration must be a whole number of minutes.")
            if not question or len(options)<2 or not 1<=duration<=10080 or not raw_channel.isdigit():
                raise ValueError("Provide a question, at least two options, a valid channel and a duration from 1 to 10080 minutes.")
            if len({value.casefold() for value in options})!=len(options):
                raise ValueError("Poll options must be unique.")
            channel=guild.get_channel(int(raw_channel))
            if not isinstance(channel,__import__("discord").TextChannel):
                raise ValueError("Choose a text channel in this server.")
            perms=channel.permissions_for(guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                raise ValueError("Cinnamon needs View Channel, Send Messages and Embed Links in the poll channel.")
            async def create_dashboard_poll():
                advanced=state["advanced_features_data"]
                root=advanced.setdefault("cinnamon_community_interactions_v1",{})
                cfg=root.setdefault(str(gid),{})
                polls=cfg.setdefault("polls",{})
                view_class=state.get("CommunityPollView")
                embed_fn=state.get("_ci_poll_embed")
                if not callable(view_class) or not callable(embed_fn):
                    raise ValueError("Poll voting controls are unavailable.")
                now=int(time.time())
                record={"question":question,"options":options,"creator_id":int(_tokens[sid]["user"]["id"]),"channel_id":int(channel.id),"votes":{},"status":"active","created_at":now,"ends_at":now+duration*60}
                message=await channel.send(embed=embed_fn(record),view=view_class(options),allowed_mentions=__import__("discord").AllowedMentions.none())
                message_id=str(message.id)
                record["message_id"]=int(message.id)
                polls[message_id]=record
                if not await state["bd_save_data"]():
                    polls.pop(message_id,None)
                    try: await message.delete()
                    except __import__("discord").HTTPException: pass
                    raise ValueError("Could not durably save the poll. Its post was removed.")
                return message_id
            message_id=_run_bot(create_dashboard_poll())
            _audit(gid,actor,"Dashboard: community poll created",f"Poll message {message_id}; channel {channel.id}.")
            session["dashboard_notice"]="Poll created and published."
        elif action=="community_poll_close":
            message_id=request.form.get("message_id","").strip()
            if not message_id.isdigit(): raise ValueError("Choose a valid poll.")
            async def close_dashboard_poll():
                advanced=state["advanced_features_data"]
                cfg=(advanced.get("cinnamon_community_interactions_v1",{}) or {}).get(str(gid),{})
                polls=cfg.get("polls",{}) or {}
                record=polls.get(message_id)
                if not isinstance(record,dict) or record.get("status")!="active":
                    raise ValueError("That poll is no longer active.")
                before=__import__("copy").deepcopy(record)
                record["status"]="ended"
                record["ended_at"]=int(time.time())
                if not await state["bd_save_data"]():
                    record.clear(); record.update(before)
                    raise ValueError("Could not save poll closure.")
                channel=guild.get_channel(int(record.get("channel_id",0) or 0))
                view_class=state.get("CommunityPollView")
                embed_fn=state.get("_ci_poll_embed")
                if channel and callable(view_class) and callable(embed_fn):
                    try:
                        message=await channel.fetch_message(int(message_id))
                        await message.edit(embed=embed_fn(record),view=view_class(record.get("options",[]),disabled=True))
                    except __import__("discord").HTTPException: pass
            _run_bot(close_dashboard_poll())
            _audit(gid,actor,"Dashboard: community poll closed",f"Poll message {message_id}.")
            session["dashboard_notice"]="Poll closed."
        elif action=="community_event_create":
            title=request.form.get("title","").strip()
            start_raw=request.form.get("start_at","").strip()
            description=request.form.get("description","").strip()[:1500]
            raw_channel=request.form.get("channel_id","").strip()
            if not title or len(title)>120 or not raw_channel.isdigit():
                raise ValueError("Provide an event title and a valid text channel.")
            try:
                start=__import__("datetime").datetime.fromisoformat(start_raw.replace("Z","+00:00"))
            except ValueError:
                raise ValueError("Use an ISO date/time including a timezone offset.")
            if start.tzinfo is None:
                raise ValueError("Event start time must include a timezone offset such as +05:30 or Z.")
            starts_at=int(start.astimezone(__import__("datetime").timezone.utc).timestamp())
            if starts_at<=int(time.time()) or starts_at>int(time.time())+366*86400:
                raise ValueError("Choose a future time within the next 366 days.")
            channel=guild.get_channel(int(raw_channel))
            if not isinstance(channel,__import__("discord").TextChannel):
                raise ValueError("Choose a text channel in this server.")
            perms=channel.permissions_for(guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                raise ValueError("Cinnamon needs View Channel, Send Messages and Embed Links in the event channel.")
            async def create_dashboard_event():
                advanced=state["advanced_features_data"]
                root=advanced.setdefault("cinnamon_community_interactions_v1",{})
                cfg=root.setdefault(str(gid),{})
                events=cfg.setdefault("events",{})
                view_class=state.get("CommunityEventView")
                if not callable(view_class): raise ValueError("Community event RSVP controls are unavailable.")
                event_id=__import__("uuid").uuid4().hex[:8]
                record={"creator_id":int(_tokens[sid]["user"]["id"]),"title":title,
                        "description":description,"starts_at":starts_at,"channel_id":int(channel.id),
                        "rsvps":{},"status":"scheduled","created_at":int(time.time()),
                        "reminders_sent":[]}
                embed=__import__("discord").Embed(title="📅 "+title,
                    description=(description+"\\n\\n" if description else "")+f"Starts <t:{starts_at}:F> (<t:{starts_at}:R>)",
                    color=0x91B5A2)
                message=await channel.send(embed=embed,view=view_class(gid,event_id),
                    allowed_mentions=__import__("discord").AllowedMentions.none())
                record["message_id"]=int(message.id)
                events[event_id]=record
                if not await state["bd_save_data"]():
                    events.pop(event_id,None)
                    try: await message.delete()
                    except __import__("discord").HTTPException: pass
                    raise ValueError("Could not durably save the event. Its post was removed.")
                return event_id
            event_id=_run_bot(create_dashboard_event())
            _audit(gid,actor,"Dashboard: community event created",f"Event {event_id}; channel {channel.id}; starts {starts_at}.")
            session["dashboard_notice"]="Event created and published. ID: "+event_id
        elif action=="community_event_cancel":
            event_id=request.form.get("event_id","").strip()
            if not event_id: raise ValueError("Choose an event to cancel.")
            async def cancel_dashboard_event():
                advanced=state["advanced_features_data"]
                cfg=(advanced.get("cinnamon_community_interactions_v1",{}) or {}).get(str(gid),{})
                record=(cfg.get("events",{}) or {}).get(event_id)
                if not isinstance(record,dict) or record.get("status")!="scheduled":
                    raise ValueError("That event is no longer scheduled.")
                before=__import__("copy").deepcopy(record)
                record["status"]="cancelled"
                record["cancelled_at"]=int(time.time())
                if not await state["bd_save_data"]():
                    record.clear();record.update(before)
                    raise ValueError("Could not save event cancellation.")
                channel=guild.get_channel(int(record.get("channel_id",0) or 0))
                view_class=state.get("CommunityEventView")
                if channel and callable(view_class):
                    try:
                        message=await channel.fetch_message(int(record.get("message_id",0)))
                        embed=__import__("discord").Embed(title="📅 "+str(record.get("title","Event")),
                            description="This event has been cancelled.",color=0xD97777)
                        await message.edit(embed=embed,view=view_class(gid,event_id,disabled=True))
                    except __import__("discord").HTTPException:
                        pass
            _run_bot(cancel_dashboard_event())
            _audit(gid,actor,"Dashboard: community event cancelled",f"Event {event_id}.")
            session["dashboard_notice"]="Event cancelled."
        elif action=="community_features_settings":
            def optional_text_channel(field):
                raw=request.form.get(field,"").strip()
                if not raw: return 0
                if not raw.isdigit(): raise ValueError("Choose a valid channel.")
                channel=guild.get_channel(int(raw))
                if not isinstance(channel,__import__("discord").TextChannel):
                    raise ValueError("Choose a text channel from this server.")
                return int(channel.id)
            suggestion_id=optional_text_channel("suggestion_channel_id")
            starboard_id=optional_text_channel("starboard_channel_id")
            confession_id=optional_text_channel("confession_channel_id")
            try:
                threshold=int(request.form.get("starboard_threshold","3"))
            except ValueError:
                raise ValueError("Starboard threshold must be a whole number.")
            emoji=request.form.get("starboard_emoji","⭐").strip()
            if not 2<=threshold<=20 or not 1<=len(emoji)<=20:
                raise ValueError("Use a starboard threshold from 2–20 and an emoji value of 1–20 characters.")
            async def apply_community_features():
                advanced=state["advanced_features_data"]
                board_root=advanced.setdefault("cinnamon_community_tools_v1",{})
                social_root=advanced.setdefault("cinnamon_community_interactions_v1",{})
                board=board_root.setdefault(str(gid),{})
                social=social_root.setdefault(str(gid),{})
                before_board=__import__("copy").deepcopy(board)
                before_social=__import__("copy").deepcopy(social)
                board.update({"suggestion_channel_id":suggestion_id,
                              "starboard_channel_id":starboard_id,
                              "starboard_threshold":threshold,
                              "starboard_emoji":emoji})
                social["confession_channel_id"]=confession_id
                if not await state["bd_save_data"]():
                    board.clear();board.update(before_board)
                    social.clear();social.update(before_social)
                    raise ValueError("The durable community settings save could not be verified. No changes were kept.")
            _run_bot(apply_community_features())
            _audit(gid,actor,"Dashboard: community features updated",
                   f"Suggestions={suggestion_id}; starboard={starboard_id}; threshold={threshold}; confessions={confession_id}.")
            session["dashboard_notice"]="Community boards and confession settings saved."
        elif action in {"welcome","goodbye"}:
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
            value=request.form.get("economy_log","").strip()
            if value and (not value.isdigit() or not isinstance(guild.get_channel(int(value)),__import__("discord").TextChannel)): raise ValueError("Choose a valid text channel from this server.")
            if value: state["economy_log_channels"][gid]=int(value)
            else: state["economy_log_channels"].pop(gid,None)
            _save(); _audit(gid,actor,"Dashboard: economy log channel updated",value or "disabled")
            session["dashboard_notice"]="Economy log channel saved."
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
        elif action=="achievement_settings":
            enabled="enabled" in request.form; channel_id=request.form.get("channel_id","").strip()
            if channel_id and (not channel_id.isdigit() or not isinstance(guild.get_channel(int(channel_id)),__import__("discord").TextChannel)): raise ValueError("Choose a valid achievement log channel.")
            cfg=state.setdefault("achievement_config",{}).setdefault(gid,{})
            cfg["enabled"]=enabled
            if channel_id:
                cfg["log_channel"]=int(channel_id); state.setdefault("category_log_channels",{}).setdefault(gid,{})["achievements"]=int(channel_id)
            else: cfg.pop("log_channel",None)
            _save(); _audit(gid,actor,"Dashboard: achievement settings updated",f"enabled={enabled}; channel={channel_id or 'disabled'}"); session["dashboard_notice"]="Achievement settings saved."
        elif action=="quest_settings":
            role_id=request.form.get("role_id","").strip()
            role=guild.get_role(int(role_id)) if role_id.isdigit() else None
            if not role or role.is_default() or role.managed: raise ValueError("Choose a valid assignable Quest Master role.")
            state.setdefault("quest_config",{}).setdefault(gid,{})["quest_master_role"]=role.id
            _save(); _audit(gid,actor,"Dashboard: Quest Master role updated",role.name); session["dashboard_notice"]="Quest Master role saved."
        elif action=="xp_settings":
            per=int(request.form.get("xp_per_message","20")); channel_ids=request.form.getlist("channel_id")
            if not 1<=per<=1000: raise ValueError("XP per message must be between 1 and 1,000.")
            chosen=set()
            for raw in channel_ids:
                raw=raw.strip()
                if not raw.isdigit(): raise ValueError("Choose valid text channels for XP.")
                ch=guild.get_channel(int(raw))
                if not isinstance(ch,__import__("discord").TextChannel): raise ValueError("Choose valid text channels for XP.")
                chosen.add(ch.id)
            state.setdefault("xp_per_message",{})[gid]=per
            state.setdefault("xp_channels",{})[gid]=chosen
            _save(); _audit(gid,actor,"Dashboard: XP settings updated",f"XP/message={per}; channels={','.join(str(x) for x in sorted(chosen)) or 'none'}")
            session["dashboard_notice"]="XP settings saved with the selected channels."
        elif action=="xp_channel_remove":
            channel_id=request.form.get("channel_id","").strip()
            if not channel_id.isdigit(): raise ValueError("Invalid XP channel.")
            state.setdefault("xp_channels",{}).setdefault(gid,set()).discard(int(channel_id)); _save(); _audit(gid,actor,"Dashboard: XP channel removed",channel_id)
            session["dashboard_notice"]="XP channel removed."
        elif action=="category_log_set":
            category=request.form.get("log_category","").strip(); channel_id=request.form.get("channel_id","").strip()
            allowed={"moderation","economy","ai","levels","achievements","quests","friendship","community","roles","setup","general","dashboard"}
            if category not in allowed: raise ValueError("Unknown log category.")
            if not channel_id.isdigit() or not isinstance(guild.get_channel(int(channel_id)),__import__("discord").TextChannel): raise ValueError("Choose a valid text channel.")
            cid=int(channel_id); state.setdefault("category_log_channels",{}).setdefault(gid,{})[category]=cid
            if category=="moderation": state.setdefault("log_channels",{})[gid]=cid
            if category=="economy": state.setdefault("economy_log_channels",{})[gid]=cid
            _save(); _audit(gid,actor,"Dashboard: log route updated",f"{category} -> {cid}"); session["dashboard_notice"]=f"{category.title()} log channel saved."
        elif action=="category_log_disable":
            category=request.form.get("log_category","").strip(); allowed={"moderation","economy","ai","levels","achievements","quests","friendship","community","roles","setup","general","dashboard"}
            if category not in allowed: raise ValueError("Unknown log category.")
            state.setdefault("category_log_channels",{}).setdefault(gid,{}).pop(category,None)
            if category=="moderation": state.setdefault("log_channels",{}).pop(gid,None)
            if category=="economy": state.setdefault("economy_log_channels",{}).pop(gid,None)
            _save(); _audit(gid,actor,"Dashboard: log route disabled",category); session["dashboard_notice"]=f"{category.title()} log route disabled."
        elif action=="run_setup":
            result=_run_bot(_dashboard_setup(guild,state),timeout=120); _audit(gid,actor,"Dashboard: Cinnamon setup applied",str(result)); session["dashboard_notice"]=result
        elif action=="levelrole_add":
            level=int(request.form.get("level","0")); role_id=request.form.get("role_id","")
            role=guild.get_role(int(role_id)) if role_id.isdigit() else None
            if not 1<=level<=200 or not role or role.is_default() or role.managed: raise ValueError("Choose a valid level (1–100) and assignable role.")
            if not guild.me or role>=guild.me.top_role: raise ValueError("Move Cinnamon's highest role above the reward role first.")
            state["level_roles"].setdefault(gid,{})[level]=role.id
            _save(); _audit(gid,actor,"Dashboard: level reward added",f"Level {level}: {role.name}")
            send_log=state.get("send_log")
            if callable(send_log): _run_bot(send_log(gid,title="🎖️ Level role added",category="levels",fields=[("Action","Added"),("Level",str(level)),("Role",role.name),("Role ID",str(role.id)),("Dashboard actor",str(actor))]))
            session["dashboard_notice"]="Level reward saved."
        elif action=="levelrole_remove":
            level=int(request.form.get("level","0")); mapping=state["level_roles"].get(gid,{})
            role_id=mapping.pop(level,None)
            if role_id is None: raise ValueError("No reward is configured for that level.")
            role=guild.get_role(int(role_id))
            _save(); _audit(gid,actor,"Dashboard: level reward removed",f"Level {level}")
            send_log=state.get("send_log")
            if callable(send_log): _run_bot(send_log(gid,title="🎖️ Level role removed",category="levels",fields=[("Action","Removed"),("Level",str(level)),("Role",role.name if role else "Deleted role"),("Role ID",str(role_id)),("Dashboard actor",str(actor))]))
            session["dashboard_notice"]="Level reward removed. Members keep roles already earned."
        elif action in {"economy_item_add","economy_item_save"}:
            item_id=request.form.get("item_id","").strip().lower(); items=state["ECONOMY_ITEMS"]
            if not item_id or len(item_id)>40 or not all(c.isalnum() or c in "_-" for c in item_id): raise ValueError("Item ID must use letters, numbers, _ or - (max 40).")
            if action=="economy_item_add" and item_id in items: raise ValueError("That item ID already exists.")
            if action=="economy_item_save" and item_id not in items: raise ValueError("That shop item no longer exists.")
            name=request.form.get("name","").strip(); price=int(request.form.get("price","0")); limit=int(request.form.get("max_per_person","0"))
            if not name or len(name)>80 or not 1<=price<=10000000 or not 0<=limit<=999999: raise ValueError("Check item name, price (1–10,000,000) and limit (0–999,999).")
            items[item_id]={"name":name,"price":price,"emoji":request.form.get("emoji","🐾")[:8] or "🐾","description":request.form.get("description","")[:300],"max_per_person":limit,"shop_enabled":True}
            _save(); _audit(gid,actor,"Dashboard: shop item saved",f"{item_id}: {name}, {price} Catnip")
            send_log=state.get("send_log")
            if callable(send_log): _run_bot(send_log(gid,title="🛒 Shop item added" if action=="economy_item_add" else "✏️ Shop item edited",category="economy",fields=[("Action","Added" if action=="economy_item_add" else "Edited"),("Admin",str(actor)),("Item ID",item_id),("Name",name),("Price",str(price)),("Emoji",items[item_id]["emoji"]),("Description",items[item_id]["description"]),("Per-person limit",str(limit)),("Shop enabled","true"),("Catalog scope","Global shared shop")]))
            session["dashboard_notice"]="Shop item saved."
        elif action=="economy_item_remove":
            item_id=request.form.get("item_id","").strip()
            if item_id not in state["ECONOMY_ITEMS"]: raise ValueError("That shop item no longer exists.")
            removed_item=state["ECONOMY_ITEMS"].pop(item_id)
            _save(); _audit(gid,actor,"Dashboard: shop item removed",f"Removed catalog item {item_id}; existing member inventories were preserved.")
            send_log=state.get("send_log")
            if callable(send_log): _run_bot(send_log(gid,title="🗑️ Shop item removed",category="economy",fields=[("Action","Removed"),("Admin",str(actor)),("Item ID",item_id),("Name",removed_item.get("name",item_id)),("Price",str(removed_item.get("price",1))),("Emoji",removed_item.get("emoji","🐾")),("Description",removed_item.get("description","")[:300]),("Per-person limit",str(removed_item.get("max_per_person",0))),("Catalog scope","Global shared shop")]))
            session["dashboard_notice"]="Shop item removed. Existing inventories were preserved."
        elif action=="economy_income_add":
            role_id=request.form.get("role_id","").strip(); role=guild.get_role(int(role_id)) if role_id.isdigit() else None
            try: amount=int(request.form.get("amount","0")); interval=int(request.form.get("interval","0"))
            except ValueError: raise ValueError("Income amount and interval must be whole numbers.")
            unit=request.form.get("unit","minute"); multipliers={"minute":60,"hour":3600,"day":86400,"week":604800}
            if not role or role.is_default() or role.managed: raise ValueError("Choose a valid, assignable server role.")
            if not 1<=amount<=1000000 or not 1<=interval<=1000 or unit not in multipliers: raise ValueError("Use 1–1,000,000 Catnip and an interval from 1–1,000 minutes/hours/days/weeks.")
            income_cfg={"amount":amount,"cooldown":interval*multipliers[unit],"interval":interval,"unit":unit}
            state.setdefault("economy_income_roles",{}).setdefault(gid,{})[role.id]=income_cfg
            _save(); _audit(gid,actor,"Dashboard: role income saved",f"Role {role.name} ({role.id}); {amount} Catnip every {interval} {unit}(s).")
            send_log=state.get("send_log")
            if callable(send_log): _run_bot(send_log(gid,title="💰 Role income added/updated",category="economy",fields=[("Action","Added/Updated"),("Admin",str(actor)),("Role",role.name),("Role ID",str(role.id)),("Amount",str(amount)),("Interval",str(interval)),("Unit",unit),("Cooldown seconds",str(income_cfg["cooldown"]))]))
            session["dashboard_notice"]=f"Role income saved for {role.name}."
        elif action=="economy_income_remove":
            role_id=request.form.get("role_id","").strip(); cfg=state.setdefault("economy_income_roles",{}).setdefault(gid,{})
            removed_income=cfg.pop(int(role_id),None) if role_id.isdigit() else None
            if removed_income is None: raise ValueError("That role income rule no longer exists.")
            role=guild.get_role(int(role_id))
            _save(); _audit(gid,actor,"Dashboard: role income removed",f"Role ID {role_id}.")
            if not role_id.isdigit() or cfg.pop(int(role_id),None) is None: raise ValueError("That role income rule no longer exists.")
            _save(); _audit(gid,actor,"Dashboard: role income removed",f"Role ID {role_id}.")
            session["dashboard_notice"]="Role income rule removed."
        elif action in {"giveaway_create","giveaway_edit","giveaway_draft_save","giveaway_draft_update"}:
            prize=request.form.get("prize","").strip()
            try: winners=int(request.form.get("winners","1")); duration=int(request.form.get("duration_minutes","60"))
            except ValueError: raise ValueError("Winner count and duration must be whole numbers.")
            if not prize or len(prize)>200 or not 1<=winners<=100 or not 1<=duration<=525600:
                raise ValueError("Check prize (1–200 chars), winners (1–100), and duration (1–525,600 minutes).")
            validate=state.get("validate_giveaway_config")
            if not callable(validate): raise RuntimeError("Giveaway settings validation is not available.")
            role_text=lambda field: "\n".join(request.form.getlist(field))
            config=validate(guild, bonus_roles=request.form.get("bonus_roles",""),
                required_roles=role_text("required_roles"), bypass_roles=role_text("bypass_roles"),
                blacklisted_roles=role_text("blacklisted_roles"),
                min_account_age_days=request.form.get("min_account_age_days","0"),
                min_server_age_days=request.form.get("min_server_age_days","0"),
                winner_role_id=request.form.get("winner_role_id",""),
                winner_role_minutes=request.form.get("winner_role_minutes","0"),
                winner_thread_minutes=request.form.get("winner_thread_minutes","0"),
                embed_color=request.form.get("embed_color","FEE75C"), entry_emoji=request.form.get("entry_emoji","🎉"),
                reaction_entries="reaction_entries" in request.form)
            config.update({"claim_minutes":int(request.form.get("claim_minutes","0") or 0),"entry_message":request.form.get("entry_message","")[:300],
                "leave_message":request.form.get("leave_message","")[:300],
                "denied_message":request.form.get("denied_message","")[:300],
                "embed_title":request.form.get("embed_title","")[:256],
                "embed_description":request.form.get("embed_description","")[:3500]})
            if action=="giveaway_draft_update":
                draft_id=request.form.get("draft_id",""); drafts=state.setdefault("giveaway_drafts",{}).setdefault(gid,{})
                draft=drafts.get(draft_id)
                if not draft or int(draft.get("guild_id",0))!=gid: raise ValueError("That giveaway draft was not found.")
                draft.update({"prize":prize,"winners":winners,"duration_minutes":duration,"config":config,"updated_at":time.time()})
                _save(); _audit(gid,actor,"Dashboard: giveaway draft edited",f"Draft {draft_id}; prize {prize}; {winners} winner(s).")
                session["dashboard_notice"]="Draft updated. Discord has not been changed."
            elif action=="giveaway_draft_save":
                channel_id=request.form.get("channel_id","").strip(); channel=guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
                if not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Choose a valid text channel in this server.")
                drafts=state.setdefault("giveaway_drafts",{}).setdefault(gid,{})
                draft_id=secrets.token_urlsafe(8)
                drafts[draft_id]={"guild_id":gid,"channel_id":channel.id,"host_id":int(_tokens[sid]["user"]["id"]),"prize":prize,"winners":winners,"duration_minutes":duration,"config":config,"created_at":time.time()}
                _save(); _audit(gid,actor,"Dashboard: giveaway draft saved",f"Draft {draft_id}; prize {prize}; {winners} winner(s); {duration} minutes.")
                session["dashboard_notice"]="Draft saved; it has not been posted to Discord."
            elif action=="giveaway_create":
                raise ValueError("Use Save draft and publish from the saved draft preview.")
            else:
                raw_mid=request.form.get("message_id","0")
                if not raw_mid.isdigit(): raise ValueError("Invalid giveaway message ID.")
                mid=int(raw_mid); gw=state["active_giveaways"].get(mid)
                if not gw or int(gw.get("guild_id",0))!=gid: raise ValueError("Active giveaway not found in this server.")
                channel=_bot.get_channel(int(gw.get("channel_id",0)))
                if channel is None: raise ValueError("Giveaway channel is unavailable.")
                async def update_giveaway():
                    msg=await channel.fetch_message(mid)
                    gw.update(config); gw.update({"prize":prize,"winners":winners,"ends_at":time.time()+duration*60})
                    await msg.edit(embed=state["giveaway_embed"](gw),view=state["giveaway_view"](emoji=gw.get("entry_emoji")))
                    await state["bd_save_data"]()
                _run_bot(update_giveaway())
                _audit(gid,actor,"Dashboard: giveaway edited",f"Message {mid}; prize, duration, entry rules and embed settings updated.")
                session["dashboard_notice"]="Giveaway updated. Existing entrants were retained; entry rules apply to future entries and final eligibility."
        elif action=="giveaway_draft_publish":
            draft_id=request.form.get("draft_id",""); drafts=state.setdefault("giveaway_drafts",{}).setdefault(gid,{})
            draft=drafts.get(draft_id)
            if not draft or int(draft.get("guild_id",0))!=gid: raise ValueError("That giveaway draft was not found.")
            channel=guild.get_channel(int(draft.get("channel_id",0)))
            if not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Draft channel is unavailable.")
            mid=_run_bot(state["create_giveaway"](guild_id=gid,channel_id=channel.id,host_id=int(draft.get("host_id",_tokens[sid]["user"]["id"])),prize=draft["prize"],winners=int(draft["winners"]),duration_minutes=int(draft["duration_minutes"]),config=draft.get("config",{})))
            drafts.pop(draft_id,None); _save(); _audit(gid,actor,"Dashboard: giveaway draft published",f"Draft {draft_id}; message {mid}")
            session["dashboard_notice"]="Draft published; giveaway is live in Discord."
        elif action=="giveaway_draft_delete":
            draft_id=request.form.get("draft_id",""); drafts=state.setdefault("giveaway_drafts",{}).setdefault(gid,{})
            draft=drafts.get(draft_id)
            if not draft or int(draft.get("guild_id",0))!=gid: raise ValueError("That giveaway draft was not found.")
            drafts.pop(draft_id,None); _save(); _audit(gid,actor,"Dashboard: giveaway draft discarded",draft_id)
            session["dashboard_notice"]="Draft discarded."
        elif action=="giveaway_template_save":
            raw_mid=request.form.get("message_id","0"); name=request.form.get("template_name","").strip()
            if not raw_mid.isdigit() or not name or len(name)>40: raise ValueError("Choose an active giveaway and a template name (1–40 characters).")
            gw=state.get("active_giveaways",{}).get(int(raw_mid))
            if not gw or int(gw.get("guild_id",0))!=gid: raise ValueError("Active giveaway not found in this server.")
            templates=state.setdefault("giveaway_templates",{}).setdefault(gid,{})
            template_key=name.lower()
            templates[template_key]={k:v for k,v in gw.items() if k not in {"guild_id","channel_id","host_id","ends_at","entrants","winner_ids","finished_at","eligible_entrants"}}
            _save(); _audit(gid,actor,"Dashboard: giveaway template saved",f"Template {name}; prize {gw.get('prize','Giveaway')}")
            session["dashboard_notice"]=f"Saved giveaway template '{name}'."
        elif action=="giveaway_template_delete":
            name=request.form.get("template_name","").strip().lower(); templates=state.setdefault("giveaway_templates",{}).setdefault(gid,{})
            if not name or templates.pop(name,None) is None: raise ValueError("That giveaway template no longer exists.")
            _save(); _audit(gid,actor,"Dashboard: giveaway template deleted",name)
            session["dashboard_notice"]="Giveaway template deleted."
        elif action=="giveaway_repeat_create":
            channel_id=request.form.get("channel_id","").strip(); channel=guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
            prize=request.form.get("prize","").strip()
            try: winners=int(request.form.get("winners","1")); duration=int(request.form.get("duration_minutes","1440")); repeat_days=int(request.form.get("repeat_every_days","7"))
            except ValueError: raise ValueError("Recurring giveaway values must be whole numbers.")
            if not isinstance(channel,__import__("discord").TextChannel) or not prize or len(prize)>200 or not 1<=winners<=100 or not 1<=duration<=525600 or not 1<=repeat_days<=365:
                raise ValueError("Choose a valid channel and prize, 1–100 winners, duration up to 1 year, and repeat interval 1–365 days.")
            schedules=state.setdefault("giveaway_schedules",{}); schedule_id=f"{gid}-{int(time.time())}-{secrets.token_hex(2)}"
            schedules[schedule_id]={"guild_id":gid,"channel_id":channel.id,"host_id":int(_tokens[sid]["user"]["id"]),"prize":prize,
                "winners":winners,"duration_minutes":duration,"repeat_every_days":repeat_days,"next_at":time.time()+repeat_days*86400,"enabled":True}
            _save(); _audit(gid,actor,"Dashboard: recurring giveaway scheduled",f"{prize}; every {repeat_days} day(s); schedule {schedule_id}")
            session["dashboard_notice"]="Recurring giveaway schedule saved."
        elif action=="giveaway_repeat_stop":
            schedule_id=request.form.get("schedule_id",""); schedules=state.setdefault("giveaway_schedules",{}); cfg=schedules.get(schedule_id)
            if not cfg or int(cfg.get("guild_id",0))!=gid: raise ValueError("That recurring giveaway schedule was not found.")
            schedules.pop(schedule_id,None); _save(); _audit(gid,actor,"Dashboard: recurring giveaway stopped",schedule_id)
            session["dashboard_notice"]="Recurring giveaway schedule stopped. Existing active giveaways are unchanged."
        elif action=="giveaway_reroll":
            raw_mid=request.form.get("message_id","")
            if not raw_mid.isdigit(): raise ValueError("Invalid giveaway message ID.")
            mid=int(raw_mid); history=state.setdefault("giveaway_history",{}); gw=history.get(str(mid)) or history.get(mid)
            if not gw or int(gw.get("guild_id",0))!=gid: raise ValueError("Finished giveaway not found in this server.")
            old=set(int(x) for x in gw.get("winner_ids",[])); candidates=[int(x) for x in gw.get("eligible_entrants",gw.get("entrants",[])) if int(x) not in old]
            if not candidates: raise ValueError("No eligible non-winning entrants remain to reroll.")
            import random as _random
            winner=_random.choice(candidates); gw.setdefault("winner_ids",[]).append(winner); gw["last_reroll_at"]=time.time()
            channel=_bot.get_channel(int(gw.get("channel_id",0)))
            async def post_reroll():
                if channel:
                    try:
                        msg=await channel.fetch_message(mid)
                        await msg.reply(f"🎉 Reroll winner: <@{winner}>! You won **{gw.get('prize','the giveaway prize')}**.",allowed_mentions=__import__("discord").AllowedMentions(users=True))
                    except __import__("discord").HTTPException: pass
                await state["bd_save_data"]()
            _run_bot(post_reroll()); _audit(gid,actor,"Dashboard: giveaway rerolled",f"Message {mid}; new winner {winner}")
            session["dashboard_notice"]=f"Rerolled giveaway. New winner ID: {winner}."
        elif action=="giveaway_end":
            mid=int(request.form.get("message_id","0")); gw=state["active_giveaways"].get(mid)
            if not gw or int(gw.get("guild_id",0))!=gid: raise ValueError("Active giveaway not found in this server.")
            _run_bot(state["finish_giveaway"](mid)); _audit(gid,actor,"Dashboard: giveaway ended",f"Message {mid}")
            session["dashboard_notice"]="Giveaway ended and winners were selected."
        elif action=="giveaway_cancel":
            mid=int(request.form.get("message_id","0")); gw=state["active_giveaways"].get(mid)
            if not gw or int(gw.get("guild_id",0))!=gid: raise ValueError("Active giveaway not found in this server.")
            _run_bot(state["cancel_giveaway"](mid)); _audit(gid,actor,"Dashboard: giveaway cancelled",f"Message {mid}")
            session["dashboard_notice"]="Giveaway cancelled without selecting winners."
        elif action=="config_backup_restore":
            upload=request.files.get("backup_file")
            if not upload or not upload.filename or not upload.filename.lower().endswith(".json"):
                raise ValueError("Choose a .json Cinnamon configuration backup file.")
            raw=upload.stream.read(1_000_001)
            if len(raw)>1_000_000: raise ValueError("Backup file is too large (maximum 1 MB).")
            try: payload=json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError,json.JSONDecodeError): raise ValueError("Backup file is not valid UTF-8 JSON.")
            changed=_restore_guild_config(guild,state,payload)
            _save(); _audit(gid,actor,"Dashboard: configuration backup restored",f"Sections restored: {', '.join(changed) or 'none'}")
            session["dashboard_notice"]="Configuration restored for this server. Member balances, inventories, progress, active giveaways and secrets were preserved."
        elif action=="hangry_logs":
            cog=state.get("hg_cog"); value=request.form.get("channel_id","").strip()
            if not cog: raise ValueError("Hangry Games is not ready.")
            if value and (not value.isdigit() or not isinstance(guild.get_channel(int(value)),__import__("discord").TextChannel)): raise ValueError("Choose a valid text channel in this server.")
            enabled_now="enabled" in request.form
            async def save_hangry():
                if value: cog.hg_log_channels[gid]=int(value)
                else: cog.hg_log_channels.pop(gid,None); cog.log_enabled.pop(gid,None)
                if value: cog.log_enabled[gid]=enabled_now
                await cog._save()
            _run_bot(save_hangry()); _audit(gid,actor,"Dashboard: Hangry Games logging updated",f"Channel {value or 'disabled'}; enabled={enabled_now}")
            session["dashboard_notice"]="Hangry Games log settings saved."
        elif action=="recall":
            recall_fn=state.get("recall_guild_data")
            if not callable(recall_fn): raise RuntimeError("Recovery service is not connected to the dashboard.")
            result=_run_bot(recall_fn(guild),timeout=120)
            _audit(gid,actor,"Dashboard: log recovery scan completed",
                   f"Channels scanned={result.get('channels_scanned',0)}/{result.get('channels_configured',0)}; "
                   f"embeds={result.get('embeds_scanned',0)}; warnings={result.get('warnings',0)}; "
                   f"XP users={result.get('xp_users_restored',0)}; economy accounts={result.get('economy_accounts',0)}; "
                   f"achievements={result.get('achievements_restored',0)}; quests={result.get('quests_restored',0)}; "
                   f"Hangry games=#{result.get('hangry_game_count',0)}; wins={result.get('hangry_wins_seen',0)}")
            session["dashboard_notice"]=(f"Recovery scanned {result.get('embeds_scanned',0)} log embeds across "
                f"{result.get('channels_scanned',0)} channel(s). Restored/updated: {result.get('warnings',0)} warnings, "
                f"{result.get('xp_users_restored',0)} XP users, {result.get('economy_accounts',0)} economy account(s), "
                f"{result.get('achievements_restored',0)} achievement(s), {result.get('quests_restored',0)} completed quest(s); "
                f"Hangry Games #{result.get('hangry_game_count',0)} with {result.get('hangry_wins_seen',0)} win(s) found. "
                "Only retained logs/snapshots can be recovered.")
        elif action=="message_send":
            if not request.form.get("send_confirmation"):
                raise ValueError("Confirm the destination and message before sending.")
            channel_id=request.form.get("channel_id","").strip()
            channel=guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
            discord=__import__("discord")
            if not isinstance(channel, discord.TextChannel): raise ValueError("Choose a valid text channel in this server.")
            title=request.form.get("embed_title","").strip()
            description=request.form.get("embed_description","").strip()
            footer=request.form.get("embed_footer","Cinnamon • Made with paws 🐾").strip()
            color_text=request.form.get("embed_color","#D97732").strip()
            image_url=request.form.get("embed_image","").strip()
            if not title or len(title)>256: raise ValueError("Embed title must be 1–256 characters.")
            if not description or len(description)>4000: raise ValueError("Message text must be 1–4,000 characters.")
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", color_text): raise ValueError("Choose a valid six-digit hex accent colour.")
            if len(footer)>200: raise ValueError("Footer must be no longer than 200 characters.")
            # Discord limits the combined text across embed title, description, footer,
            # author and fields to 6,000 characters. This studio currently creates no
            # author/fields, so validate the complete text we actually send.
            total_embed_text = len(title) + len(description) + len(footer)
            if total_embed_text > 6000:
                raise ValueError(f"Embed text totals {total_embed_text:,} characters; Discord allows 6,000 across the embed.")
            if image_url and (not image_url.startswith("https://") or len(image_url)>500): raise ValueError("Optional image must be an HTTPS URL under 500 characters.")
            bot_member=guild.me
            perms=channel.permissions_for(bot_member) if bot_member else None
            if not perms or not perms.send_messages or not perms.embed_links:
                raise PermissionError("Cinnamon needs Send Messages and Embed Links in the selected channel.")
            embed=discord.Embed(title=title,description=description,color=int(color_text[1:],16))
            if footer: embed.set_footer(text=footer)
            if image_url: embed.set_image(url=image_url)
            embed.timestamp=dt.datetime.now(dt.timezone.utc)
            async def send_studio_embed():
                return await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            message=_run_bot(send_studio_embed(),timeout=25)
            _audit(gid,actor,"Dashboard: Message Studio embed sent",f"Destination #{channel.name} ({channel.id}); title: {title[:150]}; message ID {message.id}.")
            session["dashboard_notice"]=f"Embed sent to #{channel.name}."


        elif action in {"ticket_dashboard_claim","ticket_dashboard_unclaim"}:
            raw_channel=request.form.get("channel_id","").strip()
            if not raw_channel.isdigit(): raise ValueError("Invalid ticket channel.")
            root=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_tickets_v1",{})
            cfg=root.get(str(gid),{})
            ticket=cfg.get("tickets",{}).get(raw_channel)
            channel=guild.get_channel(int(raw_channel))
            if not ticket or not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Ticket record/channel not found.")
            if ticket.get("status")!="open": raise ValueError("Only open tickets can be assigned.")
            actor_id=int(_tokens[sid]["user"]["id"])
            before=__import__("copy").deepcopy(ticket)
            if action=="ticket_dashboard_claim":
                if ticket.get("claimed_by") not in (None,actor_id): raise ValueError("This ticket is already claimed by another staff member.")
                ticket["claimed_by"]=actor_id
            else:
                ticket["claimed_by"]=None
            async def save_ticket_assignment():
                if not await state["bd_save_data"]():
                    ticket.clear();ticket.update(before)
                    raise ValueError("Ticket assignment could not be durably saved.")
            _run_bot(save_ticket_assignment())
            await_message = "claimed by dashboard staff." if action=="ticket_dashboard_claim" else "unassigned by dashboard staff."
            async def notify_ticket_assignment():
                await channel.send("Ticket "+await_message)
            _run_bot(notify_ticket_assignment())
            _audit(gid,actor,"Dashboard ticket "+("claimed" if action=="ticket_dashboard_claim" else "unassigned"),f"Channel {channel.id}; assigned staff ID {ticket.get('claimed_by')}.")
            session["dashboard_notice"]="Ticket "+("claimed" if action=="ticket_dashboard_claim" else "unassigned")+"."
        elif action in {"ticket_dashboard_close","ticket_dashboard_reopen","ticket_dashboard_claim","ticket_dashboard_unclaim"}:
            raw_channel=request.form.get("channel_id","").strip()
            if not raw_channel.isdigit(): raise ValueError("Invalid ticket channel.")
            root=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_tickets_v1",{}); cfg=root.get(str(gid),{})
            ticket=cfg.get("tickets",{}).get(raw_channel)
            channel=guild.get_channel(int(raw_channel))
            if not ticket or not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Ticket record/channel not found.")
            creator=guild.get_member(int(ticket.get("creator_id",0)))
            async def dashboard_ticket_change():
                if action=="ticket_dashboard_close":
                    if ticket.get("status")!="open": raise ValueError("Ticket is already closed.")
                    ticket.update({"status":"closed","closed_at":time.time(),"close_reason":"Closed by dashboard administrator"})
                    if creator: await channel.set_permissions(creator,view_channel=True,send_messages=False,read_message_history=True)
                    await channel.send("Ticket closed by a dashboard administrator.",view=state["ticket_control_view"](ticket.get("ticket_id")))
                    transcript=await state["ticket_transcript"](channel)
                    logch=guild.get_channel(int(cfg.get("settings",{}).get("log_channel_id") or 0))
                    if transcript and cfg.get("settings",{}).get("transcript_on_close",True) and logch: await logch.send(content=f"Dashboard close transcript for {channel.mention}",file=__import__("discord").File(transcript,filename=f"ticket-{channel.id}.html"))
                    cfg.setdefault("closed",{})[raw_channel]=dict(ticket)
                else:
                    if ticket.get("status")!="closed": raise ValueError("Ticket is not closed.")
                    ticket.update({"status":"open","closed_at":None})
                    cfg.setdefault("closed",{}).pop(raw_channel,None)
                    if creator: await channel.set_permissions(creator,view_channel=True,send_messages=True,read_message_history=True,attach_files=True,embed_links=True)
                    await channel.send("Ticket reopened by a dashboard administrator.",view=state["ticket_control_view"](ticket.get("ticket_id")))
                if not await state["bd_save_data"](): raise ValueError("Ticket change could not be durably saved.")
            _run_bot(dashboard_ticket_change(),timeout=40)
            _audit(gid,actor,"Dashboard ticket "+("closed" if action=="ticket_dashboard_close" else "reopened"),f"Channel {channel.id}; creator {ticket.get('creator_id')}.")
            session["dashboard_notice"]="Ticket "+("closed" if action=="ticket_dashboard_close" else "reopened")+" in Discord."

        elif action=="ticket_settings_save":
            raw_log=request.form.get("log_channel_id","").strip(); raw_parent=request.form.get("ticket_category_id","").strip()
            log_channel=guild.get_channel(int(raw_log)) if raw_log.isdigit() else None
            parent=guild.get_channel(int(raw_parent)) if raw_parent.isdigit() else None
            if raw_log and not isinstance(log_channel,__import__("discord").TextChannel): raise ValueError("Choose a valid ticket log text channel.")
            if raw_parent and not isinstance(parent,__import__("discord").CategoryChannel): raise ValueError("Choose a valid ticket category.")
            try: maximum=int(request.form.get("max_open_per_user","3")); cooldown=int(request.form.get("cooldown_seconds","60")); auto_close=int(request.form.get("auto_close_hours","0"))
            except ValueError: raise ValueError("Ticket limits must be whole numbers.")
            if not 1<=maximum<=10 or not 0<=cooldown<=86400 or not 0<=auto_close<=720: raise ValueError("Ticket limits are outside allowed ranges.")
            staff=[]; trusted=[]
            for field,target in (("staff_role_ids",staff),("trusted_booster_role_ids",trusted)):
                for raw in request.form.getlist(field):
                    if not raw.isdigit(): raise ValueError("Invalid role selection.")
                    role=guild.get_role(int(raw))
                    if not role or role.is_default() or role.managed: raise ValueError("A selected ticket role is unavailable or managed.")
                    target.append(role.id)
            cfg=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_tickets_v1",{}).setdefault(str(gid),{})
            cfg.setdefault("panels",{}); cfg.setdefault("tickets",{}); cfg.setdefault("closed",{}); cfg.setdefault("cooldowns",{})
            cfg["settings"]={"log_channel_id":log_channel.id if log_channel else None,"ticket_category_id":parent.id if parent else None,"staff_role_ids":staff,"trusted_booster_role_ids":trusted,"max_open_per_user":maximum,"cooldown_seconds":cooldown,"auto_close_hours":auto_close,"transcript_on_close":"transcript_on_close" in request.form,"rating_enabled":True}
            _save(); _audit(gid,actor,"Ticket settings updated",f"Log channel {raw_log or 'disabled'}; parent {raw_parent or 'not set'}; staff roles {len(staff)}; trusted booster roles {len(trusted)}.")
            session["dashboard_notice"]="Ticket settings saved to durable storage."
        elif action in {"ticket_panel_save","ticket_panel_update"}:
            panel_id=request.form.get("panel_id","").strip()
            cfg=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_tickets_v1",{}).setdefault(str(gid),{})
            panels=cfg.setdefault("panels",{})
            if action=="ticket_panel_update":
                panel=panels.get(panel_id)
                if not panel: raise ValueError("Ticket panel not found.")
            else:
                panel_id=secrets.token_hex(6); panel={"id":panel_id,"published":False,"categories":[]}
            name=request.form.get("panel_name","").strip(); title=request.form.get("panel_title","").strip(); description=request.form.get("panel_description","").strip(); color=request.form.get("panel_color","#D99048").strip()
            raw_channel=request.form.get("channel_id","").strip(); channel=guild.get_channel(int(raw_channel)) if raw_channel.isdigit() else None
            if not name or len(name)>60 or not title or len(title)>256 or len(description)>3500 or not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Panel name, title, description or channel is invalid.")
            if not re.fullmatch(r"#[0-9a-fA-F]{6}",color): raise ValueError("Panel color must be a six-digit hex color.")
            raw_categories=request.form.get("categories_json","").strip()
            if raw_categories:
                try: categories=json.loads(raw_categories)
                except json.JSONDecodeError: raise ValueError("Categories must be valid JSON.")
                if not isinstance(categories,list) or not 1<=len(categories)<=25: raise ValueError("Provide 1–25 ticket categories.")
                clean_categories=[]
                for item in categories:
                    if not isinstance(item,dict): raise ValueError("Each category must be a JSON object.")
                    label=str(item.get("label","")).strip(); button=str(item.get("button_label",label)).strip(); routing=str(item.get("routing","support")).lower()
                    if not label or len(label)>60 or not button or len(button)>80 or routing not in {"support","shop","grow_a_garden","gag","boosting","faq"}: raise ValueError("Category label, button or routing is invalid.")
                    questions=item.get("questions",[])
                    if not isinstance(questions,list) or len(questions)>5: raise ValueError("Each category supports up to five modal questions.")
                    clean_questions=[]
                    for q in questions:
                        if not isinstance(q,dict) or not str(q.get("label","")).strip() or len(str(q.get("label","")))>45: raise ValueError("Question labels must be 1–45 characters.")
                        clean_questions.append({"label":str(q["label"]).strip(),"required":bool(q.get("required",True)),"paragraph":bool(q.get("paragraph",True)),"max_length":max(1,min(1000,int(q.get("max_length",400)))),"placeholder":str(q.get("placeholder","Your answer"))[:100]})
                    raw_staff=item.get("staff_role_ids",[])
                    if not isinstance(raw_staff,list) or len(raw_staff)>20: raise ValueError("Category staff_role_ids must be a list of at most 20 roles.")
                    category_staff=[]
                    for rid in raw_staff:
                        if not str(rid).isdigit() or not guild.get_role(int(rid)) or guild.get_role(int(rid)).managed: raise ValueError("A category staff role is invalid.")
                        category_staff.append(int(rid))
                    clean_categories.append({"id":str(item.get("id") or secrets.token_hex(4))[:40],"label":label,"button_label":button,"emoji":str(item.get("emoji",""))[:100],"button_style":str(item.get("button_style","primary")).lower(),"routing":routing,"trusted_booster_routing":bool(item.get("trusted_booster_routing",routing in {"grow_a_garden","gag","boosting"})),"staff_role_ids":category_staff,"faq_answer":str(item.get("faq_answer",""))[:2000],"welcome_title":str(item.get("welcome_title",""))[:256],"welcome_message":str(item.get("welcome_message",""))[:1500],"channel_category_id":int(item.get("channel_category_id",0) or 0),"channel_name_format":str(item.get("channel_name_format","ticket-{username}"))[:80],"questions":clean_questions})
                panel["categories"]=clean_categories
            elif action=="ticket_panel_save":
                label=request.form.get("category_label","").strip(); button=request.form.get("button_label","").strip(); routing=request.form.get("routing","support").strip()
                if not label or len(label)>60 or not button or len(button)>80 or routing not in {"support","shop","grow_a_garden"}: raise ValueError("Ticket category/button/routing is invalid.")
                custom_questions=[]
                for i in range(1,6):
                    q=request.form.get("question"+str(i),"").strip()
                    if q: custom_questions.append({"label":q,"required":True,"paragraph":True,"max_length":400})
                questions=custom_questions
                if not questions and routing in {"shop","grow_a_garden"}:
                    defaults=(["What item or service did you purchase?","Order ID or purchase proof (if available)","What issue are you experiencing?"] if routing=="shop" else ["What Grow a Garden service did you purchase?","Order ID or purchase proof (if available)","What do you need help with?"])
                    questions=[{"label":label,"required":True,"paragraph":True,"max_length":400} for label in defaults]
                category={"id":secrets.token_hex(4),"label":label,"button_label":button,"emoji":request.form.get("button_emoji","").strip()[:100],"button_style":"primary","routing":routing,"trusted_booster_routing":routing=="grow_a_garden","welcome_message":request.form.get("welcome_message","").strip()[:1500],"questions":questions}
                panel["categories"]=[category]
            panel.update({"id":panel_id,"name":name,"channel_id":channel.id,"title":title,"description":description,"color":color,"updated_at":int(time.time())})
            panels[panel_id]=panel
            _save(); _audit(gid,actor,"Ticket panel configuration saved",f"Panel {name} ({panel_id}); published={bool(panel.get('published'))}.")
            session["dashboard_notice"]="Panel configuration saved. Publish separately to update Discord."
        elif action=="ticket_panel_publish":
            panel_id=request.form.get("panel_id","").strip(); cfg=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_tickets_v1",{}).setdefault(str(gid),{}); panel=cfg.setdefault("panels",{}).get(panel_id)
            if not panel or not panel.get("categories"): raise ValueError("Save a panel with at least one category before publishing.")
            channel=guild.get_channel(int(panel.get("channel_id",0)))
            if not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Panel channel is unavailable.")
            embed=__import__("discord").Embed(title=panel.get("title","Support Center"),description=panel.get("description","Choose a category below."),color=int(panel.get("color","#D99048")[1:],16))
            embed.set_footer(text="Cinnamon Tickets")
            async def publish_panel():
                view=state["ticket_panel_view"](gid,panel_id,panel)
                message=None
                if panel.get("message_id"):
                    try: message=await channel.fetch_message(int(panel["message_id"]))
                    except Exception: message=None
                if message: await message.edit(embed=embed,view=view)
                else: message=await channel.send(embed=embed,view=view)
                panel["message_id"]=message.id; panel["published"]=True; panel["published_at"]=int(time.time())
                if not await state["bd_save_data"](): raise ValueError("Could not verify durable panel publish.")
                return message.id
            mid=_run_bot(publish_panel(),timeout=40); _audit(gid,actor,"Ticket panel published",f"{panel.get('name')} in #{channel.name}; message {mid}.")
            session["dashboard_notice"]="Ticket panel published/updated in Discord."
        elif action=="ticket_panel_delete":
            panel_id=request.form.get("panel_id","").strip(); cfg=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_tickets_v1",{}).setdefault(str(gid),{}); panel=cfg.setdefault("panels",{}).pop(panel_id,None)
            if not panel: raise ValueError("Ticket panel not found.")
            async def remove_panel_message():
                channel=guild.get_channel(int(panel.get("channel_id",0)))
                if channel and panel.get("message_id"):
                    try: msg=await channel.fetch_message(int(panel["message_id"])); await msg.edit(view=None)
                    except Exception: pass
                await state["bd_save_data"]()
            _run_bot(remove_panel_message()); _audit(gid,actor,"Ticket panel deleted",str(panel.get("name",panel_id)))
            session["dashboard_notice"]="Panel configuration deleted; old panel message has been disabled."
        elif action=="roles_setup_save":
            root=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_role_permissions_v1",{}); cfg={}
            role_keys=("giveaway_creator","hangry_runner","trusted_booster","ticket_staff","ticket_admin","shop_manager","economy_admin","quest_manager","event_manager","moderator")
            for key in role_keys:
                ids=[]
                for raw in request.form.getlist("role_"+key):
                    if not raw.isdigit(): raise ValueError("Invalid role selection.")
                    role=guild.get_role(int(raw))
                    if not role or role.is_default() or role.managed: raise ValueError("A selected permission role is unavailable or managed.")
                    ids.append(role.id)
                cfg[key]=sorted(set(ids))
            root[str(gid)]=cfg; _save(); _audit(gid,actor,"Roles Setup permissions saved",", ".join(f"{k}: {len(v)} role(s)" for k,v in cfg.items()))
            session["dashboard_notice"]="All role permissions saved to durable storage and logged."

        elif action=="moderate":
            target,mod_action=_moderate(guild,_tokens[sid]["user"]["id"],request.form)
            _audit(gid,actor,f"Dashboard moderation: {mod_action}",f"Target {target}; reason: {request.form.get('reason','No reason provided')[:350]}")
            session["dashboard_notice"]=f"{mod_action.title()} action completed for {target}."
        else:
            raise ValueError("Unknown dashboard action.")
        tab={"brain_settings":"mind","mind_settings":"mind","economy_item_add":"economy","economy_item_save":"economy","economy_item_remove":"economy","economy_income_add":"economy","economy_income_remove":"economy","giveaway_create":"giveaways","giveaway_edit":"giveaways","giveaway_draft_save":"giveaways","giveaway_draft_update":"giveaways","giveaway_draft_publish":"giveaways","giveaway_draft_delete":"giveaways","giveaway_end":"giveaways","giveaway_cancel":"giveaways","giveaway_template_save":"giveaways","giveaway_template_delete":"giveaways","giveaway_repeat_create":"giveaways","giveaway_repeat_stop":"giveaways","giveaway_reroll":"giveaways","config_backup_restore":"system","hangry_logs":"hangry","welcome":"community","goodbye":"community","community_features_settings":"community","community_event_create":"community","community_event_cancel":"community","security_settings":"moderation","moderation_controls_settings":"moderation","verification_publish":"moderation","appeal_settings":"moderation","dashboard_appeal_review":"moderation","ticket_dashboard_claim":"tickets","ticket_dashboard_unclaim":"tickets","welcome_disable":"community","goodbye_disable":"community","ai_channel":"community","log_channel":"community","special_logs":"system","automod":"moderation","antiraid":"moderation","moderate":"moderation","levelrole_add":"engagement","levelrole_remove":"engagement","achievement_settings":"achievements","quest_settings":"quests","xp_settings":"engagement","xp_channel_remove":"engagement","category_log_set":"system","category_log_disable":"system","run_setup":"system","recall":"system","message_send":"message_studio"}.get(action,"overview")
        return redirect(url_for("cinnamon_dashboard.dashboard_home",guild_id=gid,tab=tab))
    except (ValueError,PermissionError) as exc:
        session["dashboard_notice"]=str(exc)[:300]
        return redirect(url_for("cinnamon_dashboard.dashboard_home",guild_id=request.form.get("guild_id",""),tab={"brain_settings":"mind","mind_settings":"mind","economy_item_add":"economy","economy_item_save":"economy","economy_item_remove":"economy","economy_income_add":"economy","economy_income_remove":"economy","giveaway_create":"giveaways","giveaway_edit":"giveaways","giveaway_end":"giveaways","giveaway_cancel":"giveaways","giveaway_template_save":"giveaways","giveaway_template_delete":"giveaways","giveaway_repeat_create":"giveaways","giveaway_repeat_stop":"giveaways","giveaway_reroll":"giveaways","ticket_settings_save":"tickets","ticket_panel_save":"tickets","ticket_panel_update":"tickets","ticket_panel_publish":"tickets","ticket_panel_delete":"tickets","ticket_dashboard_claim":"tickets","ticket_dashboard_unclaim":"tickets","roles_setup_save":"roles_setup","config_backup_restore":"system","hangry_logs":"hangry","moderate":"moderation","automod":"moderation","antiraid":"moderation","achievement_settings":"achievements","quest_settings":"quests","xp_settings":"engagement","xp_channel_remove":"engagement","category_log_set":"system","category_log_disable":"system","run_setup":"system","message_send":"message_studio"}.get(request.form.get("action"),"community")))
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
