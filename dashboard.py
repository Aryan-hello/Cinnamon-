"""Cinnamon dashboard starter: Discord OAuth2 login and read-only server overview."""
import os
import secrets
import urllib.parse
import urllib.request
import json
import html
from flask import Blueprint, render_template_string, redirect, request, session, url_for

dashboard_bp = Blueprint("cinnamon_dashboard", __name__)
_bot = None
_tokens = {}  # server-side token cache; never place OAuth access tokens in browser cookies


def configure_dashboard(bot):
    global _bot
    _bot = bot


def _request_json(url, method="GET", data=None, headers=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


BASE_STYLE = """
:root{--cream:#fbf2e4;--beige:#f7ebd9;--orange:#b96b2c;--brown:#38251d;--taupe:#897765;--white:#fff;--line:#e4d5c0}
*{box-sizing:border-box}body{margin:0;background:var(--cream);color:var(--brown);font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1050px;margin:auto;padding:24px}.top{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:25px}.brand{display:flex;align-items:center;gap:12px;font-weight:800;font-size:21px}.mascot{width:56px;height:56px;border-radius:18px;object-fit:cover;border:2px solid #ead7b8}.btn{display:inline-block;text-decoration:none;border:0;border-radius:12px;background:var(--orange);color:white;padding:12px 17px;font-weight:700}.btn.secondary{background:#efe1cc;color:var(--brown)}.hero{background:var(--beige);border:1px solid var(--line);border-radius:24px;padding:28px;display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:22px}.hero h1{font-family:Georgia,serif;font-size:clamp(28px,5vw,42px);margin:0 0 8px}.muted{color:var(--taupe);line-height:1.6}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:15px}.card{background:var(--white);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 3px 12px #38251d08}.card h2,.card h3{margin:0 0 8px}.big{font:700 32px Georgia,serif}.server{display:flex;align-items:center;gap:13px}.guildicon{width:48px;height:48px;border-radius:15px;background:var(--beige);display:grid;place-items:center;font-weight:800;color:var(--orange);overflow:hidden}.guildicon img{width:100%;height:100%;object-fit:cover}.note{background:#f5e7d2;border-radius:14px;padding:13px 16px;color:#725b45;font-size:14px;margin-top:18px}.center{min-height:90vh;display:grid;place-items:center}.login{max-width:500px;width:100%;text-align:center}.login .mascot{width:145px;height:145px;border-radius:35px;margin-bottom:14px}@media(max-width:560px){.wrap{padding:16px}.hero{align-items:flex-start}.hero .mascot{width:74px;height:74px}}
"""


def _page(body, title="Cinnamon Dashboard"):
    return render_template_string("""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{{title}}</title><style>""" + BASE_STYLE + """</style></head><body>{{body|safe}}</body></html>""", title=title, body=body)


@dashboard_bp.get("/dashboard")
def dashboard_home():
    sid = session.get("dash_sid")
    if not sid or sid not in _tokens:
        return redirect(url_for("cinnamon_dashboard.login"))
    user = _tokens[sid]["user"]
    try:
        user_guilds = _request_json("https://discord.com/api/users/@me/guilds", headers={"Authorization": "Bearer " + _tokens[sid]["access_token"]})
    except Exception:
        _tokens.pop(sid, None)
        session.pop("dash_sid", None)
        return _page("<main class='wrap'><div class='card'><h2>Discord session expired</h2><p class='muted'>Please log in again.</p><a class='btn' href='/login'>Login with Discord</a></div></main>")
    bot_guild_ids = {str(g.id) for g in _bot.guilds} if _bot else set()
    manageable = [g for g in user_guilds if str(g.get("id")) in bot_guild_ids and (g.get("owner") or (int(g.get("permissions", "0")) & (0x8 | 0x20)))]
    cards = []
    for g in manageable:
        icon = (f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png?size=96" if g.get("icon") else "")
        mark = f"<img src='{icon}' alt=''>" if icon else (g.get("name", "?")[:2].upper())
        cards.append(f"<article class='card server'><div class='guildicon'>{mark}</div><div><h3>{html.escape(g.get('name','Discord server'))}</h3><p class='muted' style='margin:3px 0 0'>Cinnamon is in this server</p></div><span style='margin-left:auto;color:var(--taupe);font-size:13px'>Overview</span></article>")
    if not cards:
        cards.append("<article class='card'><h3>No manageable servers found</h3><p class='muted'>Cinnamon must be in the server, and your Discord account needs Manage Server or Administrator permission.</p></article>")
    ready = bool(_bot and _bot.is_ready())
    status = "Online" if ready else "Connecting"
    content = f"""<main class='wrap'><header class='top'><div class='brand'><img class='mascot' src='/static/cinnamon_mascot.jpg' alt='Cinnamon'><span>Cinnamon <span style='font-weight:500;color:var(--taupe)'>Dashboard</span></span></div><div><span style='margin-right:12px;color:var(--taupe)'>{html.escape(user.get('username','Discord user'))}</span><a class='btn secondary' href='/logout'>Log out</a></div></header><section class='hero'><div><h1>Hello, {html.escape(user.get('global_name') or user.get('username','friend'))}! 🐾</h1><p class='muted'>Welcome to Cinnamon's cozy command center. Choose a server to view its dashboard.</p><span style='font-size:13px;color:var(--taupe)'>Bot status: <b>{status}</b></span></div><img class='mascot' style='width:105px;height:105px' src='/static/cinnamon_mascot.jpg' alt='Cinnamon'></section><h2 style='font-family:Georgia,serif;margin:24px 0 13px'>Your servers</h2><section class='grid'>{''.join(cards)}</section><div class='note'>This is the first dashboard version: Discord login and server access checks are in place. Server settings and controls are not connected yet.</div></main>"""
    return _page(content)


@dashboard_bp.get("/login")
def login():
    client_id = os.getenv("DISCORD_CLIENT_ID")
    client_secret = os.getenv("DISCORD_CLIENT_SECRET")
    redirect_uri = os.getenv("DASHBOARD_REDIRECT_URI", "https://cinnamon-c328.onrender.com/oauth/callback")
    if not client_id or not client_secret:
        body = "<main class='wrap center'><section class='card login'><img class='mascot' src='/static/cinnamon_mascot.jpg' alt='Cinnamon'><h1>Almost ready!</h1><p class='muted'>Add DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET to your Render environment variables to enable Discord login. Never share the Client Secret publicly.</p><a class='btn secondary' href='/'>Back</a></section></main>"
        return _page(body, "Set up Cinnamon login")
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    params = {"client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri, "scope": "identify guilds", "state": state}
    return redirect("https://discord.com/oauth2/authorize?" + urllib.parse.urlencode(params))


@dashboard_bp.get("/oauth/callback")
def oauth_callback():
    error = request.args.get("error")
    if error:
        return _page("<main class='wrap'><div class='card'><h2>Login cancelled</h2><a class='btn' href='/login'>Try again</a></div></main>")
    state = request.args.get("state", "")
    if not state or not secrets.compare_digest(state, session.pop("oauth_state", "")):
        return _page("<main class='wrap'><div class='card'><h2>Login could not be verified</h2><p class='muted'>Please restart the login process.</p><a class='btn' href='/login'>Try again</a></div></main>"), 400
    code = request.args.get("code")
    if not code:
        return _page("<main class='wrap'><div class='card'><h2>Missing authorization code</h2><a class='btn' href='/login'>Try again</a></div></main>"), 400
    try:
        redirect_uri = os.getenv("DASHBOARD_REDIRECT_URI", "https://cinnamon-c328.onrender.com/oauth/callback")
        token = _request_json("https://discord.com/api/oauth2/token", method="POST", data={"client_id": os.environ["DISCORD_CLIENT_ID"], "client_secret": os.environ["DISCORD_CLIENT_SECRET"], "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}, headers={"Content-Type": "application/x-www-form-urlencoded"})
        access_token = token["access_token"]
        user = _request_json("https://discord.com/api/users/@me", headers={"Authorization": "Bearer " + access_token})
        sid = secrets.token_urlsafe(32)
        _tokens[sid] = {"access_token": access_token, "user": user}
        session["dash_sid"] = sid
        return redirect(url_for("cinnamon_dashboard.dashboard_home"))
    except Exception:
        return _page("<main class='wrap'><div class='card'><h2>Discord login failed</h2><p class='muted'>Check your OAuth2 settings and Render environment variables, then try again.</p><a class='btn' href='/login'>Try again</a></div></main>"), 502


@dashboard_bp.get("/logout")
def logout():
    sid = session.pop("dash_sid", None)
    if sid:
        _tokens.pop(sid, None)
    session.pop("oauth_state", None)
    return redirect(url_for("cinnamon_dashboard.login"))
