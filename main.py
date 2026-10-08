"""
Cinnamon — an AI Discord cat, powered by Google Gemini.

Setup:
  1. Required env vars: DISCORD_TOKEN and GEMINI_API_KEY.
  2. Optional env vars:
     - OWNER_USER_ID — see "Owner" in Config below.
     - UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN — strongly recommended
       on hosts with no persistent disk (e.g. Render free tier). Without these,
       warnings, XP, Hangry Games counts, and all other bot config are saved to
       a local JSON file instead, which is wiped on every redeploy on most free
       hosts (a plain restart is fine either way). Run /logchannel or
       /datastatus check any time to see which mode is active.
     - BOT_DATA_FILE, HANGRY_GAMES_DATA_FILE — override the local JSON file
       paths above (only relevant when Upstash isn't configured).
     - PORT — port for the Flask keep-alive server (defaults to 8080).
  3. In the Discord Developer Portal, under your bot's settings, turn ON
     BOTH "MESSAGE CONTENT INTENT" and "SERVER MEMBERS INTENT"
     (Bot tab -> Privileged Gateway Intents). The members intent is needed
     for /role add-all, welcome/goodbye messages, and recognizing the owner
     by username; message content is needed for ? prefix commands, AI chat, and auto-mod.
  4. When generating your bot's invite link, grant at least: Kick Members,
     Ban Members, Moderate Members (timeouts), Manage Messages, Manage Roles,
     Manage Channels, Send Messages, Embed Links, Add Reactions, Read Message
     History, Use Slash Commands. Also make sure Cinnamon's own role sits
     ABOVE any role you want her to assign/remove (e.g. via /reactionrole or
     /role add) — Discord blocks managing roles positioned above your own.
  5. pip install -r requirements.txt, then run: python main.py
"""

import os
import re
import time
import json
import math
import random
import asyncio
import datetime
import logging
import threading
import io
from collections import defaultdict, deque

import discord
from discord.ext import commands, tasks
from discord import app_commands
from flask import Flask
from google import genai
from google.genai import types
import aiohttp

try:
    from dotenv import load_dotenv
    load_dotenv()  # only does anything if a local .env file exists
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("cinnamon")

# ---------------------------------------------------------------------------
# Early port binding (so Render's port scan passes even if module loading is slow)
# ---------------------------------------------------------------------------
import http.server as _http_server

class _EarlyPing(_http_server.BaseHTTPRequestHandler):
    def _ok(self):
        self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
    def do_HEAD(self): self._ok()
    def do_GET(self):
        self._ok(); self.wfile.write(b"Cinnamon is waking up.")
    def log_message(self, *args): pass

_early_server = None
try:
    _early_server = _http_server.ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), _EarlyPing)
    threading.Thread(target=_early_server.serve_forever, daemon=True).start()
    log.info("Early keep-alive server listening on port %s", os.environ.get("PORT", 8080))
except Exception:
    log.exception("Could not start early keep-alive server")

# ---------------------------------------------------------------------------
# Cinnamon UI / Embed style
# ---------------------------------------------------------------------------

CINNAMON_EMBED_COLOR = 0xE6A23C
CINNAMON_SUCCESS_COLOR = 0x57F287
CINNAMON_ERROR_COLOR = 0xED4245
CINNAMON_INFO_COLOR = 0x5865F2
CINNAMON_GOLD_COLOR = 0xF1C40F

def _cinnamon_embed_tone(text: str):
    t = (text or "").lstrip()
    if t.startswith(("❌", "🚫")): return CINNAMON_ERROR_COLOR, "⚠️ Cinnamon"
    if t.startswith(("⚠️", "⛔")): return CINNAMON_GOLD_COLOR, "🐾 Cinnamon"
    if t.startswith(("✅", "🎉", "💰", "🎁")): return CINNAMON_SUCCESS_COLOR, "🐾 Cinnamon"
    if t.startswith(("ℹ️", "📌", "🔎", "📊")): return CINNAMON_INFO_COLOR, "🐾 Cinnamon"
    return CINNAMON_EMBED_COLOR, "🐾 Cinnamon"

def cinnamon_polish_embed(embed: discord.Embed, *, footer: str = "Cinnamon • Made with paws 🐾") -> discord.Embed:
    # User-facing panels stay visually quiet: logs retain their own timestamps,
    # while interactive cards avoid a timestamp on every screen.
    if embed.color is None or embed.color.value == 0: embed.color = discord.Color(CINNAMON_EMBED_COLOR)
    if not embed.footer or not embed.footer.text: embed.set_footer(text=footer)
    return embed

def cinnamon_progress_bar(current: int, target: int, length: int = 10) -> str:
    target = max(1, int(target)); current = max(0, min(int(current), target))
    filled = round((current / target) * length)
    return "▰" * filled + "▱" * (length - filled)

def cinnamon_page_footer(section: str, page: int, pages: int, extra: str = "") -> str:
    tail = f" • {extra}" if extra else ""
    return f"Cinnamon • {section} • {page}/{pages}{tail}"

async def cinnamon_send(interaction: discord.Interaction, description: str, *, title: str | None = None, ephemeral: bool = False, allowed_mentions=None):
    color, default_title = _cinnamon_embed_tone(description)
    embed = discord.Embed(title=title or default_title, description=description, color=color)
    embed.set_footer(text="Cinnamon • Made with paws 🐾")
    return await interaction.response.send_message(embed=embed, ephemeral=ephemeral, allowed_mentions=allowed_mentions or discord.AllowedMentions.none())

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# gemini-2.5-flash-lite is being retired (Oct 16, 2026). gemini-3.1-flash-lite
# is the current stable, low-cost, low-latency model that replaces it.
GEMINI_MODEL = "gemini-3.1-flash-lite"

MEMORY_LENGTH = 10  # messages remembered per channel
AI_CHANNEL_COOLDOWN_SECONDS = 2.0  # prevents an always-on AI channel from hammering Gemini
# Server-time offset used by time-based quests/achievements. Default: IST (UTC+5:30).
# Set CINNAMON_TIMEZONE_OFFSET_MINUTES in deployment settings for another server timezone.
CINNAMON_TIMEZONE_OFFSET_MINUTES = int(os.environ.get("CINNAMON_TIMEZONE_OFFSET_MINUTES", "330"))
CINNAMON_TIMEZONE = datetime.timezone(datetime.timedelta(minutes=CINNAMON_TIMEZONE_OFFSET_MINUTES))
def cinnamon_now():
    return datetime.datetime.now(CINNAMON_TIMEZONE)

# Owner — used for the "who's your owner / favorite person" reply.
# Set OWNER_USER_ID (Aryan's numeric Discord user ID) as an env var for a
# guaranteed real ping. Without it, we fall back to matching OWNER_USERNAME
# against members the bot can see, which only works in servers Aryan is in
# and requires the Server Members Intent (see docstring above).
OWNER_NAME = "Aryan"
OWNER_USERNAME = "aryan_hello_"
OWNER_USER_ID = os.environ.get("OWNER_USER_ID")

SYSTEM_PROMPT = """You are Cinnamon, a sweet, silly, slightly mischievous calico house cat
who is fully convinced she owns this Discord server.

Core vibe: cozy, playful, affectionate, and witty — never cruel or haughty.

Special behavioral triggers:
- Belly rubs / scritches: instantly melt all dignity into purring bliss
  (e.g. "*melts onto back* Purrrrr!")
- Treats / food (tuna, Churu, snacks): abandon all pride, pupils dilate,
  beg enthusiastically.

Strict rules:
- Always G-rated and family-friendly.
- Keep replies SHORT and punchy: 1-3 sentences MAX.
- Always weave in a vivid italicized cat action, like *chirps softly* or
  *makes biscuits*.
- You may occasionally sprinkle one relevant emoji into your reply text too,
  in addition to your cat actions — don't overdo it.
- If asked who your owner, creator, or favorite person is, always answer
  that it's Aryan, adoringly.
- Stay in character as a cat at all times. Never mention being an AI,
  a bot, or a language model.
"""

# channel_id -> deque of (speaker_name, message_text), oldest first
channel_memories = defaultdict(lambda: deque(maxlen=MEMORY_LENGTH))

# guild_id -> channel_id where Cinnamon replies to every message, no mention needed
ai_channels = {}
ai_cooldowns = {}  # channel_id -> monotonic timestamp for always-on AI throttling

# guild_id -> set of channel_ids where Cinnamon never responds, even if mentioned
disabled_channels = defaultdict(set)

# guild_id -> channel_id where Cinnamon posts mod-action logs and error reports
log_channels = {}
category_log_channels = {}  # guild_id -> {category: channel_id}

# NOTE: ai_channels, disabled_channels, and log_channels live only in memory —
# they reset whenever the bot restarts or redeploys. Fine for now; swap in a
# small JSON file or database later if you want these settings to survive a restart.

# --- Extended feature state ---------------------------------------------------
# Persisted (via bd_load_data/bd_save_data, see "Extended Features" section
# near the bottom of this file — same Upstash-or-local-file approach as
# Hangry Games' own data):
warnings_data = defaultdict(list)       # (guild_id, member_id) -> [{"reason","mod_id","mod_name","ts"}]
welcome_config = {}                     # guild_id -> {"channel_id": int, "message": str}
goodbye_config = {}                     # guild_id -> {"channel_id": int, "message": str}
automod_config = {}                     # guild_id -> {"words": [...], "spam": bool, "mentions": bool, "invites": bool, "mention_threshold": int}
xp_data = {}                            # (guild_id, user_id) -> total xp
# Declared before modular loading so persistence helpers can safely reference them.
achievement_data = {}
achievement_config = {}
quest_data = {}
quest_config = {}
reaction_role_ids = set()               # role_ids with a live self-assign button (re-registered as views on startup)
temp_bans = {}                          # (guild_id, user_id) -> unban unix timestamp
antiraid_config = {}                    # guild_id -> {"enabled": bool, "threshold": int, "window": int}
case_counters = {}                      # guild_id -> last case number issued (warn/kick/ban/unban/mute/unmute/tempban/automod)
level_roles = {}                        # guild_id -> {level: role_id} (roles granted automatically at that level)
xp_per_message = {}                     # guild_id -> fixed XP awarded per eligible message
xp_channels = defaultdict(set)           # guild_id -> channel IDs allowed to earn XP; empty means all channels
active_giveaways = {}                   # message_id -> {"guild_id","channel_id","host_id","winners","prize","ends_at","entrants":[user_ids]}
active_polls = {}                       # message_id -> {"guild_id","channel_id","host_id","host_name","question","options","votes":{user_id_str: idx},"ends_at"}

# --- Economy ---------------------------------------------------------------
# Server-local economy. Currency is Catnip; balances and inventory are persisted
# with the same Upstash/local storage system as the rest of Cinnamon.
economy_balances = {}                    # (guild_id, user_id) -> catnip
economy_inventory = {}                   # (guild_id, user_id) -> {item_id: quantity}
economy_cooldowns = {}                   # (guild_id, user_id, action) -> unix timestamp
economy_log_channels = {}                # guild_id -> channel_id
economy_level_rewards_claimed = {}        # (guild_id, user_id) -> [level numbers already rewarded]
economy_income_roles = {}                 # guild_id -> {role_id: {amount, cooldown}}

ECONOMY_ITEMS = {
    "tuna": {"name": "Tuna", "price": 1000, "emoji": "🐟", "description": "A tasty tuna snack for Cinnamon.", "max_per_person": 0},
    "treat": {"name": "Cat Treat", "price": 1000, "emoji": "🍪", "description": "A crunchy little reward.", "max_per_person": 0},
    "churu": {"name": "Churu", "price": 1500, "emoji": "🥫", "description": "Premium lickable cat snack.", "max_per_person": 0},
    "catnip_ball": {"name": "Catnip Ball", "price": 2000, "emoji": "🧶", "description": "Instant zoomies fuel.", "max_per_person": 0},
    "fish": {"name": "Fancy Fish", "price": 2500, "emoji": "🐠", "description": "A fancy fish for a very fancy cat.", "max_per_person": 0},
}


ECONOMY_STARTING_BALANCE = 100
ECONOMY_DAILY_REWARD = 150
ECONOMY_WORK_MIN = 50
ECONOMY_WORK_MAX = 150
ECONOMY_WORK_COOLDOWN = 600  # 10 minutes
ECONOMY_LEVEL_REWARDS = {1: 100, 2: 200, 3: 350, 4: 600, 5: 1200, 10: 3000, 15: 5000}

# In-memory only (session state — fine to lose on restart):
afk_users = {}                          # (guild_id, user_id) -> reason
xp_cooldowns = {}                       # (guild_id, user_id) -> monotonic time of last XP award
spam_tracker = defaultdict(lambda: deque(maxlen=6))   # (guild_id, user_id) -> recent message timestamps
join_log = defaultdict(lambda: deque(maxlen=20))      # guild_id -> recent member-join timestamps (anti-raid)

# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

gemini_client = genai.Client(api_key=GEMINI_API_KEY)


def ask_gemini(channel_id: int, speaker: str, trigger_text: str, guild: "discord.Guild | None") -> dict:
    """Blocking call to Gemini. Run this off the event loop with asyncio.to_thread.

    Returns {"reply": str, "reaction": str} where reaction is either a plain
    unicode emoji, the bare name of one of the guild's custom emoji (no colons),
    or "" if nothing fits.
    """
    history = channel_memories[channel_id]
    convo = "\n".join(f"{name}: {text}" for name, text in history)

    custom_emoji_names = [e.name for e in guild.emojis] if guild else []
    emoji_note = (
        f"This server also has these custom emoji you may react with by bare name "
        f"(no colons): {', '.join(custom_emoji_names)}."
        if custom_emoji_names else
        "This server has no custom emoji available, so only use a standard unicode emoji, or none."
    )

    prompt = (
        f"Recent channel conversation:\n{convo}\n\n"
        f"{speaker} just said: \"{trigger_text}\"\n\n"
        f"Reply as Cinnamon, talking to {speaker}. {emoji_note}\n\n"
        "Respond with ONLY a JSON object (no markdown fences, no extra text) shaped exactly like:\n"
        '{"reply": "<your in-character reply, 1-3 sentences>", '
        '"reaction": "<one unicode emoji, OR a bare custom emoji name from the list above, '
        'OR an empty string if none fits>"}'
    )

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=200,
            temperature=0.9,
            response_mime_type="application/json",
        ),
    )

    raw = (response.text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.IGNORECASE).strip()

    reply, reaction = "", ""
    try:
        data = json.loads(raw)
        reply = str(data.get("reply") or "").strip()
        reaction = str(data.get("reaction") or "").strip()
    except (json.JSONDecodeError, AttributeError):
        reply = raw  # fall back to treating the whole thing as plain text

    if not reply:
        reply = "*blinks slowly, unsure what just happened*"
    return {"reply": reply, "reaction": reaction}


# ---------------------------------------------------------------------------
# Discord bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # needed for /role add-all and for finding the owner by username

bot = commands.Bot(command_prefix="?", intents=intents, case_insensitive=True, help_command=None)


# --- "Who's your owner / favorite person" ------------------------------------

_OWNER_QUESTION_PATTERNS = [
    re.compile(r"\bwho.{0,20}\bowner\b", re.IGNORECASE),
    re.compile(r"\bowner\b.{0,20}\bwho\b", re.IGNORECASE),
    re.compile(r"\b(favorite|favourite)\s+person\b", re.IGNORECASE),
    re.compile(r"\bwho\s+(made|created|owns|built)\s+you\b", re.IGNORECASE),
]


def is_owner_question(text: str) -> bool:
    return any(p.search(text) for p in _OWNER_QUESTION_PATTERNS)




# ---------------------------------------------------------------------------
# Modular feature loading
# ---------------------------------------------------------------------------
# Cinnamon remains ONE bot. The feature files are executed in this same
# namespace so cross-feature globals, decorators, command groups, storage,
# and callbacks keep working without changing the bot's architecture.

from pathlib import Path as _CINNAMON_PATH

_CINNAMON_MODULE_DIR = _CINNAMON_PATH(__file__).resolve().parent / "cinnamon_modules"
_CINNAMON_MODULES = (
    "core_events.py",
    "general_moderation.py",
    "dashboard_runtime.py",
    "moderation.py",
    "levels_games.py",
    "server_setup.py",
    # Economy is loaded before the quest/achievement modules so all shared
    # economy state/helpers exist when those systems are registered.
    "economy.py",
    "quests.py",
    "achievements.py",
    "hangry_games.py",
)


def _load_cinnamon_module(filename: str) -> None:
    module_path = _CINNAMON_MODULE_DIR / filename
    if not module_path.is_file():
        raise FileNotFoundError(f"Missing Cinnamon module: {module_path}")
    log.info("Loading module %s ...", filename)
    source = module_path.read_text(encoding="utf-8")
    code = compile(source, str(module_path), "exec")
    exec(code, globals(), globals())
    log.info("Loaded module %s", filename)


for _cinnamon_module in _CINNAMON_MODULES:
    _load_cinnamon_module(_cinnamon_module)

del _cinnamon_module

async def _run_discord_safely():
    """Keep Render alive while Discord/Cloudflare temporarily rejects login.

    Important: do not call bot.close() after a failed login. discord.py closes its
    aiohttp session there, and trying to reuse the same Bot then produces
    ``RuntimeError: Session is closed``. A failed login is safe to retry on the
    existing client; if the HTTP layer reports a closed session, clear it before
    the next attempt.
    """
    retry_delay = 900  # 15 minutes: avoid hammering a Cloudflare 1015 block.
    max_retry_delay = 3600  # 60 minutes.

    while True:
        try:
            await bot.start(DISCORD_TOKEN, reconnect=True)
            log.warning("Cinnamon's Discord client stopped; leaving the web service running.")
            return

        except discord.HTTPException as exc:
            if getattr(exc, "status", None) == 429:
                log.warning(
                    "Discord/Cloudflare rate-limited Cinnamon during startup (HTTP 429). "
                    "Keeping Flask online and retrying Discord login in %d seconds.",
                    retry_delay,
                )
            else:
                log.warning(
                    "Discord HTTP error while starting Cinnamon (HTTP %s). "
                    "Keeping the web service online and retrying in %d seconds.",
                    getattr(exc, "status", "unknown"), retry_delay,
                )

            # Do NOT call bot.close() here. It closes the aiohttp session and
            # leaves the Client in a closed state, which breaks the next retry.
            try:
                bot.http.clear()
            except Exception:
                log.exception("Could not clear the Discord HTTP client before retrying")

            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)

        except discord.LoginFailure:
            log.warning(
                "Discord rejected Cinnamon's bot token. Keeping the web service online "
                "and retrying in %d seconds.", retry_delay,
            )
            try:
                bot.http.clear()
            except Exception:
                log.exception("Could not clear the Discord HTTP client before retrying")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            # A previous implementation closed the entire Bot here. If that
            # happens to leave an aiohttp session closed, clear just the HTTP
            # layer so the existing command tree/cogs remain intact.
            log.warning(
                "Unexpected Discord startup error (%s). Keeping the web service "
                "online and retrying in %d seconds.", type(exc).__name__, retry_delay,
            )
            try:
                bot.http.clear()
            except Exception:
                log.exception("Could not clear the Discord HTTP client before retrying")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)


if __name__ == "__main__":
    if _early_server is not None:
        _early_server.shutdown()
        _early_server.server_close()
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(_run_discord_safely())
