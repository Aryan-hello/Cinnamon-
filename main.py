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
# Config
# ---------------------------------------------------------------------------

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# gemini-2.5-flash-lite is being retired (Oct 16, 2026). gemini-3.1-flash-lite
# is the current stable, low-cost, low-latency model that replaces it.
GEMINI_MODEL = "gemini-3.1-flash-lite"

MEMORY_LENGTH = 10  # messages remembered per channel
AI_CHANNEL_COOLDOWN_SECONDS = 2.0  # prevents an always-on AI channel from hammering Gemini

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
reaction_role_ids = set()               # role_ids with a live self-assign button (re-registered as views on startup)
temp_bans = {}                          # (guild_id, user_id) -> unban unix timestamp
antiraid_config = {}                    # guild_id -> {"enabled": bool, "threshold": int, "window": int}
case_counters = {}                      # guild_id -> last case number issued (warn/kick/ban/unban/mute/unmute/tempban/automod)
level_roles = {}                        # guild_id -> {level: role_id} (roles granted automatically at that level)
active_giveaways = {}                   # message_id -> {"guild_id","channel_id","host_id","winners","prize","ends_at","entrants":[user_ids]}
active_polls = {}                       # message_id -> {"guild_id","channel_id","host_id","host_name","question","options","votes":{user_id_str: idx},"ends_at"}

# --- Economy ---------------------------------------------------------------
# Server-local economy. Currency is Catnip; balances and inventory are persisted
# with the same Upstash/local storage system as the rest of Cinnamon.
economy_balances = {}                    # (guild_id, user_id) -> catnip
economy_inventory = {}                   # (guild_id, user_id) -> {item_id: quantity}
economy_quests = {}                      # (guild_id, user_id) -> {quest_id: progress, ...}
economy_cooldowns = {}                   # (guild_id, user_id, action) -> unix timestamp
economy_log_channels = {}                # guild_id -> channel_id
economy_level_rewards_claimed = {}        # (guild_id, user_id) -> [level numbers already rewarded]
economy_income_roles = {}                 # guild_id -> {role_id: {amount, cooldown}}

ECONOMY_ITEMS = {
    "tuna": {"name": "Tuna", "price": 25, "emoji": "🐟", "description": "A tasty tuna snack for Cinnamon.", "max_per_person": 0},
    "treat": {"name": "Cat Treat", "price": 15, "emoji": "🍪", "description": "A crunchy little reward.", "max_per_person": 0},
    "churu": {"name": "Churu", "price": 40, "emoji": "🥫", "description": "Premium lickable cat snack.", "max_per_person": 0},
    "catnip_ball": {"name": "Catnip Ball", "price": 60, "emoji": "🧶", "description": "Instant zoomies fuel.", "max_per_person": 0},
    "fish": {"name": "Fancy Fish", "price": 90, "emoji": "🐠", "description": "A fancy fish for a very fancy cat.", "max_per_person": 0},
}

ECONOMY_QUESTS = {
    "tuna_time": {"name": "Tuna Time", "item": "tuna", "amount": 3, "reward": 140, "description": "Give Cinnamon 3 tuna."},
    "treat_run": {"name": "Treat Run", "item": "treat", "amount": 5, "reward": 120, "description": "Give Cinnamon 5 cat treats."},
    "royal_snack": {"name": "Royal Snack", "item": "churu", "amount": 2, "reward": 130, "description": "Give Cinnamon 2 Churus."},
    "zoomies": {"name": "Zoomies", "item": "catnip_ball", "amount": 2, "reward": 180, "description": "Give Cinnamon 2 catnip balls."},
}
ECONOMY_ACHIEVEMENTS = {
    "first_feed": {"name": "First Snack", "description": "Feed Cinnamon an item for the first time.", "reward": 50},
    "quest_complete": {"name": "Quest Paw-sitive", "description": "Complete your first economy quest.", "reward": 100},
    "catnip_1000": {"name": "Catnip Hoarder", "description": "Reach 1,000 Catnip in your balance.", "reward": 150},
    "collector_10": {"name": "Snack Collector", "description": "Own at least 10 total economy items at once.", "reward": 100},
    "all_quests": {"name": "Cinnamon's Favorite", "description": "Complete every currently defined economy quest.", "reward": 300},
}
economy_achievements = {}             # (guild_id, user_id) -> set/list of unlocked achievement ids

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


def owner_mention(guild: "discord.Guild | None") -> str:
    """Best-effort mention for the bot's owner. A numeric OWNER_USER_ID always
    works; without one, we try to match the username in this server's member
    cache (requires the Server Members Intent and Aryan being in the server)."""
    if OWNER_USER_ID:
        return f"<@{OWNER_USER_ID}>"
    if guild:
        member = discord.utils.get(guild.members, name=OWNER_USERNAME)
        if member:
            return member.mention
    return f"@{OWNER_USERNAME}"


# --- Reactions ----------------------------------------------------------------

async def add_reaction_safely(message: discord.Message, reaction: str):
    """React to a message with a unicode or custom guild emoji. Never raises —
    a failed reaction shouldn't break the rest of the flow."""
    if not reaction:
        return
    emoji_to_use = reaction
    if message.guild:
        custom = discord.utils.get(message.guild.emojis, name=reaction.strip(":"))
        if custom:
            emoji_to_use = custom
    try:
        await message.add_reaction(emoji_to_use)
    except discord.HTTPException as e:
        log.warning(f"Couldn't add reaction {reaction!r}: {e}")


async def secure_log_channel(channel: discord.TextChannel):
    """Restrict audit channels from @everyone while allowing Cinnamon to post.

    Server Administrators retain access through Discord's Administrator bypass.
    Other moderator roles can be granted View Channel manually in channel permissions.
    """
    guild = channel.guild
    await channel.set_permissions(guild.default_role, view_channel=False, reason="Protect Cinnamon audit logs")
    if guild.me is not None:
        await channel.set_permissions(
            guild.me, view_channel=True, send_messages=True, embed_links=True,
            read_message_history=True, reason="Allow Cinnamon to write audit logs",
        )


async def send_log(guild_id: int | None, *, title: str, description: str = "",
                    color: discord.Color = discord.Color.blurple(),
                    interaction: discord.Interaction | None = None,
                    fields: list[tuple[str, str]] | None = None,
                    category: str | None = None):
    """Post an embed to the guild's configured log channel, if any. Never raises —
    logging should never be the thing that breaks a command."""
    if guild_id is None:
        return
    # Route events to a category-specific channel, falling back to the legacy
    # main log channel when that category has not been configured.
    if category is None:
        lowered = (title + " " + description).lower()
        if any(x in lowered for x in ("economy", "catnip", "shop item", "income role", "cinnamon fed", "tuna")):
            category = "economy"
        elif any(x in lowered for x in ("ai ", " ai", "gemini", "channel re-enabled for ai", "ai channel")):
            category = "ai"
        elif any(x in lowered for x in ("level", "xp", "rank")):
            category = "levels"
        elif any(x in lowered for x in ("giveaway", "poll")):
            category = "community"
        elif any(x in lowered for x in ("role added", "role removed", "reaction role", "role income")):
            category = "roles"
        elif any(x in lowered for x in ("welcome", "goodbye", "setup", "configuration", "log channel")):
            category = "setup"
        elif any(x in lowered for x in ("userinfo", "serverinfo", "afk", "ping", "status", "help")):
            category = "general"
        else:
            category = "moderation"
    channel_id = category_log_channels.get(guild_id, {}).get(category)
    if channel_id is None:
        channel_id = log_channels.get(guild_id)
    if channel_id is None:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    if interaction is not None:
        embed.set_footer(text=f"Run by {interaction.user} • #{interaction.channel}")
    for name, value in (fields or []):
        embed.add_field(name=name, value=value, inline=True)

    try:
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        log.error(f"Failed to send log message to channel {channel_id}: {e}")


def _command_log_category(command_name: str) -> str:
    name = (command_name or "").lower().replace("/", " ").strip()
    root = name.split()[0] if name else ""
    if root in {"economy", "collect"} or "economy" in name:
        return "economy"
    if root in {"ask", "ai", "chat", "aichannel", "disableaichannel", "disableai", "enableai"}:
        return "ai"
    if root in {"rank", "leaderboard", "levelrole"}:
        return "levels"
    if root in {"giveaway", "poll"}:
        return "community"
    if root in {"role", "reactionrole"}:
        return "roles"
    if root in {"setup", "setupstatus", "welcome", "goodbye", "categorylogs", "logchannel", "disablelogchannel"}:
        return "setup"
    if root in {"help", "ping", "botstatus", "userinfo", "serverinfo", "afk"}:
        return "general"
    if root == "hangrygames":
        return "hangrygames"
    return "moderation"


@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    """Audit successful slash command use without storing arguments or AI text."""
    if interaction.guild is None:
        return
    category = _command_log_category(getattr(command, "qualified_name", getattr(command, "name", "")))
    if category == "hangrygames":
        return  # Hangry Games has its own detailed logger/channel.
    await send_log(
        interaction.guild.id, title="📌 Slash command used", interaction=interaction,
        fields=[("Command", "/" + getattr(command, "qualified_name", getattr(command, "name", "unknown"))),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Channel", getattr(interaction.channel, "mention", "Unknown"))],
        category=category,
    )


@bot.event
async def on_command_completion(ctx: commands.Context):
    """Audit successful prefix command use without storing arguments or AI text."""
    if ctx.guild is None:
        return
    category = _command_log_category(getattr(ctx.command, "qualified_name", ""))
    if category == "hangrygames":
        return
    await send_log(
        ctx.guild.id, title="📌 Prefix command used", fields=[("Command", "?" + getattr(ctx.command, "qualified_name", "unknown")),
            ("User", f"{ctx.author} ({ctx.author.id})"), ("Channel", getattr(ctx.channel, "mention", "Unknown"))],
        category=category,
    )


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Log failed prefix invocations without capturing command arguments."""
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CommandOnCooldown):
        message = f"⏳ Try again in {error.retry_after:.1f} seconds."
    elif isinstance(error, commands.MissingPermissions):
        message = "❌ You don't have permission to use that command."
    elif isinstance(error, commands.BotMissingPermissions):
        message = "❌ Cinnamon is missing a required permission."
    elif isinstance(error, commands.UserInputError):
        message = f"❌ Invalid or missing command argument. Use `?help` for command names and syntax."
    else:
        log.exception("Prefix command failed", exc_info=error)
        message = "❌ That command failed. The issue has been recorded for the bot owner."
    if ctx.guild:
        await send_log(ctx.guild.id, title="⚠️ Prefix command failed", fields=[
            ("Command", "?" + (ctx.command.qualified_name if ctx.command else "unknown")),
            ("User", f"{ctx.author} ({ctx.author.id})"),
            ("Channel", getattr(ctx.channel, "mention", "Unknown")),
            ("Error type", type(error).__name__),
        ], category=_command_log_category(ctx.command.qualified_name if ctx.command else ""))
    try:
        await ctx.reply(message, mention_author=False)
    except discord.HTTPException:
        pass


@bot.event
async def on_ready():
    if bot.get_cog("HangryGamesCog") is None:
        hg_cog = HangryGamesCog(bot)
        await hg_cog.async_init()
        await bot.add_cog(hg_cog)

        # First-run-only setup for the extended features below.
        await bd_load_data()
        for role_id in reaction_role_ids:
            bot.add_view(ReactionRoleView(role_id))
        bot.add_view(GiveawayView())  # persistent: matched by custom_id, state looked up by message ID
        bot.add_view(PollView())
        if not check_timers.is_running():
            check_timers.start()
        if not check_tempbans.is_running():
            check_tempbans.start()
        if not periodic_save.is_running():
            periodic_save.start()

        # --- Data-loss recovery: for any guild with a log channel configured
        # but no matching data loaded (persisted store came back empty), try to
        # rebuild from that channel's own message history before it's needed. ---
        for guild in bot.guilds:
            if guild.id in log_channels and not any(g == guild.id for g, _ in warnings_data.keys()):
                try:
                    recovered = await recover_warnings_from_log(guild)
                    if recovered:
                        log.info(f"Recovered {recovered} warning(s) for guild {guild.id} from its log channel.")
                        await send_log(
                            guild.id, title="🩹 Warnings recovered from log channel", color=discord.Color.gold(),
                            fields=[("Recovered", str(recovered)),
                                    ("Note", "Persisted storage came back empty on startup — rebuilt from this channel's history.")],
                        )
                except Exception as e:
                    log.error(f"Warning recovery failed for guild {guild.id}: {e}")

            if guild.id in hg_cog.hg_log_channels and not hg_cog.game_counts.get(guild.id):
                try:
                    game_num, wins = await hg_cog.recover_from_log(guild)
                    if game_num or wins:
                        log.info(f"Recovered Hangry Games data for guild {guild.id}: game #{game_num}, {wins} win(s).")
                        await hg_cog._log(
                            guild.id, title="🩹 Hangry Games data recovered from log channel", color=discord.Color.gold(),
                            fields=[("Game number restored to", str(game_num)), ("Wins reconstructed", str(wins))],
                        )
                except Exception as e:
                    log.error(f"Hangry Games recovery failed for guild {guild.id}: {e}")

    await bot.tree.sync()
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="for treats 🐟"))
    log.info(f"Cinnamon is online as {bot.user}")


@bot.event
async def on_member_join(member: discord.Member):
    cfg = welcome_config.get(member.guild.id)
    if cfg:
        channel = bot.get_channel(cfg["channel_id"])
        if channel:
            text = cfg["message"].format(member=member.mention, server=member.guild.name)
            try:
                await channel.send(text, allowed_mentions=discord.AllowedMentions(users=True))
            except discord.HTTPException:
                pass
    await check_antiraid(member)
    await send_log(member.guild.id, title="👋 Member joined", fields=[("Member", f"{member} ({member.id})"), ("Account created", discord.utils.format_dt(member.created_at, style="R"))], category="setup")


@bot.event
async def on_member_remove(member: discord.Member):
    cfg = goodbye_config.get(member.guild.id)
    if cfg:
        channel = bot.get_channel(cfg["channel_id"])
        if channel:
            text = cfg["message"].format(member=member.display_name, server=member.guild.name)
            try:
                await channel.send(text)
            except discord.HTTPException:
                pass
    await send_log(member.guild.id, title="🚪 Member left", fields=[("Member", f"{member} ({member.id})")], category="setup")


@bot.event
async def on_message_delete(message: discord.Message):
    if message.guild is None or message.author.bot:
        return
    content = message.content or "*(no text content — embed/attachment only)*"
    await send_log(
        message.guild.id, title="🗑️ Message deleted", color=discord.Color.red(),
        fields=[("Author", f"{message.author} ({message.author.id})"), ("Channel", message.channel.mention),
                ("Content", content[:1000])],
    )


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.guild is None or before.author.bot or before.content == after.content:
        return
    await send_log(
        before.guild.id, title="✏️ Message edited", color=discord.Color.orange(),
        fields=[("Author", f"{before.author} ({before.author.id})"), ("Channel", before.channel.mention),
                ("Before", (before.content or "*(empty)*")[:500]), ("After", (after.content or "*(empty)*")[:500])],
    )



# Main prefix commands. Hangry Games, quests, and achievements stay slash-only.
@bot.command(name="help", aliases=["commands"])
async def prefix_help(ctx):
    e=discord.Embed(title="🐾 Cinnamon — Help",description="Use ? before a command. Mention or ID works for member arguments.",color=discord.Color.blurple())
    e.add_field(name="Moderation",value="`?kick`, `?ban`, `?unban`, `?mute`, `?unmute`, `?warn`, `?warnings`, `?clearwarnings`, `?purge`, `?slowmode`",inline=False)
    e.add_field(name="AI",value="`?ask <message>` (`?ai`, `?chat`)",inline=False)
    e.add_field(name="Normal",value="`?ping`, `?botstatus`, `?userinfo [member]`, `?serverinfo`, `?afk [reason]`, `?rank [member]`, `?leaderboard`",inline=False)
    e.add_field(name="Economy",value="`?balance` (`?bal`, `?wallet`), `?inventory` (`?inv`), `?shop`, `?buy <item> [qty]`, `?daily`, `?work`, `?give <member> <amount>` (`?pay`), `?econlb`",inline=False)
    await ctx.reply(embed=e,mention_author=False)

@bot.command(name="ping")
async def prefix_ping(ctx): await ctx.reply(f"🐾 Pong! {round(bot.latency*1000)} ms",mention_author=False)

@bot.command(name="ask",aliases=["ai","chat"])
@commands.guild_only()
async def prefix_ask(ctx,*,prompt:str):
    if ctx.channel.id in disabled_channels[ctx.guild.id]: return
    async with ctx.typing():
        try: result=await asyncio.to_thread(ask_gemini,ctx.channel.id,ctx.author.display_name,prompt,ctx.guild); reply=result.get("reply") or "*paws at the screen* Try again?"
        except Exception: log.exception("Prefix AI failed"); reply="*paws at the screen, confused* I couldn't answer just now. Try again soon?"
    channel_memories[ctx.channel.id].append((ctx.author.display_name,prompt)); channel_memories[ctx.channel.id].append(("Cinnamon",reply))
    await ctx.reply(reply[:1900],mention_author=False,allowed_mentions=discord.AllowedMentions.none())

@bot.command(name="userinfo",aliases=["whois"])
@commands.guild_only()
async def prefix_userinfo(ctx,member:discord.Member=None):
    m=member or ctx.author; e=discord.Embed(title=f"👤 {m}",color=discord.Color.blurple()); e.add_field(name="ID",value=m.id); e.add_field(name="Joined",value=discord.utils.format_dt(m.joined_at,style="R") if m.joined_at else "Unknown"); e.add_field(name="Created",value=discord.utils.format_dt(m.created_at,style="R")); e.add_field(name="Top role",value=m.top_role.mention); await ctx.reply(embed=e,mention_author=False)

@bot.command(name="serverinfo")
@commands.guild_only()
async def prefix_serverinfo(ctx):
    g=ctx.guild; e=discord.Embed(title=f"🏡 {g.name}",color=discord.Color.blurple()); e.add_field(name="Members",value=str(g.member_count or "Unknown")); e.add_field(name="Created",value=discord.utils.format_dt(g.created_at,style="D")); e.add_field(name="Owner",value=str(g.owner or "Unknown")); e.add_field(name="Channels",value=str(len(g.channels))); await ctx.reply(embed=e,mention_author=False)

@bot.command(name="afk")
@commands.guild_only()
async def prefix_afk(ctx,*,reason="AFK"):
    afk_users[(ctx.guild.id,ctx.author.id)]=reason[:200]
    await ctx.reply(f"🐾 Marked AFK: {reason[:200]}",mention_author=False)
    await send_log(ctx.guild.id,title="💤 AFK status set",fields=[("User",f"{ctx.author} ({ctx.author.id})"),("Reason",reason[:200])],category="general")

@bot.command(name="mute",aliases=["timeout"])
@commands.guild_only()
@commands.has_guild_permissions(moderate_members=True)
@commands.bot_has_guild_permissions(moderate_members=True)
async def prefix_mute(ctx,member:discord.Member,minutes:int=10,*,reason="No reason given"):
    if not 1 <= minutes <= 40320: return await ctx.reply("❌ Minutes must be between 1 and 40,320.",mention_author=False)
    if member==ctx.author or member==ctx.guild.owner or (member.top_role>=ctx.author.top_role and ctx.author.id!=ctx.guild.owner_id) or member.top_role>=ctx.guild.me.top_role: return await ctx.reply("❌ Role hierarchy prevents this action.",mention_author=False)
    await member.timeout(datetime.timedelta(minutes=minutes),reason=reason[:300]); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"🔇 {member.mention} timed out for {minutes} minute(s). Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="🔇 Member muted",color=discord.Color.orange(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})"),("Duration",f"{minutes} min"),("Reason",reason[:300])])

@bot.command(name="unmute",aliases=["untimeout"])
@commands.guild_only()
@commands.has_guild_permissions(moderate_members=True)
@commands.bot_has_guild_permissions(moderate_members=True)
async def prefix_unmute(ctx,member:discord.Member):
    if member.top_role>=ctx.guild.me.top_role: return await ctx.reply("❌ Cinnamon's role must be above the target's role.",mention_author=False)
    await member.timeout(None,reason=f"Unmuted by {ctx.author}"); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"🔊 {member.mention} can talk again. Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="🔊 Member unmuted",color=discord.Color.green(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})")])

@bot.command(name="warn")
@commands.guild_only()
@commands.has_guild_permissions(kick_members=True)
async def prefix_warn(ctx,member:discord.Member,*,reason:str):
    count=add_warning(ctx.guild.id,member.id,reason[:300],ctx.author); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"⚠️ {member.mention} warned — {count} warning(s). Case #{case}.",mention_author=False,allowed_mentions=discord.AllowedMentions(users=True)); await send_log(ctx.guild.id,title="⚠️ Member warned",color=discord.Color.orange(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})"),("Reason",reason[:300]),("Total warnings",str(count))])

@bot.command(name="warnings",aliases=["warns"])
@commands.guild_only()
@commands.has_guild_permissions(kick_members=True)
async def prefix_warnings(ctx,member:discord.Member):
    ws=warnings_data.get((ctx.guild.id,member.id),[])
    if not ws: return await ctx.reply(f"{member.display_name} has no warnings.",mention_author=False)
    e=discord.Embed(title=f"⚠️ Warnings for {member.display_name}",color=discord.Color.orange())
    for i,w in enumerate(ws[-10:],1): e.add_field(name=f"Warning #{i}",value=f"{w.get('reason','No reason')} — {w.get('ts','')[:10]}",inline=False)
    await ctx.reply(embed=e,mention_author=False)

@bot.command(name="clearwarnings",aliases=["clearwarns"])
@commands.guild_only()
@commands.has_guild_permissions(kick_members=True)
async def prefix_clearwarnings(ctx,member:discord.Member):
    removed=len(warnings_data.pop((ctx.guild.id,member.id),[])); await bd_save_data(); await ctx.reply(f"🧹 Cleared {removed} warning(s) for {member.mention}.",mention_author=False); await send_log(ctx.guild.id,title="🧹 Warnings cleared",fields=[("Member",f"{member} ({member.id})"),("Cleared",str(removed))])

@bot.command(name="kick")
@commands.guild_only()
@commands.has_guild_permissions(kick_members=True)
@commands.bot_has_guild_permissions(kick_members=True)
async def prefix_kick(ctx,member:discord.Member,*,reason="No reason given"):
    if member==ctx.author or member==ctx.guild.owner or (member.top_role>=ctx.author.top_role and ctx.author.id!=ctx.guild.owner_id) or member.top_role>=ctx.guild.me.top_role: return await ctx.reply("❌ Role hierarchy prevents this action.",mention_author=False)
    await member.kick(reason=reason[:300]); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"👢 Kicked {member}. Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="👢 Member kicked",color=discord.Color.orange(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})"),("Reason",reason[:300])])

@bot.command(name="ban")
@commands.guild_only()
@commands.has_guild_permissions(ban_members=True)
@commands.bot_has_guild_permissions(ban_members=True)
async def prefix_ban(ctx,member:discord.Member,*,reason="No reason given"):
    if member==ctx.author or member==ctx.guild.owner or (member.top_role>=ctx.author.top_role and ctx.author.id!=ctx.guild.owner_id) or member.top_role>=ctx.guild.me.top_role: return await ctx.reply("❌ Role hierarchy prevents this action.",mention_author=False)
    await member.ban(reason=reason[:300],delete_message_seconds=0); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"🔨 Banned {member}. Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="🔨 Member banned",color=discord.Color.red(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})"),("Reason",reason[:300])])

@bot.command(name="unban")
@commands.guild_only()
@commands.has_guild_permissions(ban_members=True)
@commands.bot_has_guild_permissions(ban_members=True)
async def prefix_unban(ctx,user_id:int):
    await ctx.guild.unban(discord.Object(id=user_id)); temp_bans.pop((ctx.guild.id,user_id),None); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"🔓 Unbanned user `{user_id}`. Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="🔓 Member unbanned",color=discord.Color.green(),fields=[("Case",f"#{case}"),("User ID",str(user_id)),("Moderator",f"{ctx.author} ({ctx.author.id})")])

@bot.command(name="purge",aliases=["clear"])
@commands.guild_only()
@commands.has_guild_permissions(manage_messages=True)
@commands.bot_has_guild_permissions(manage_messages=True)
async def prefix_purge(ctx,amount:int):
    if not 1 <= amount <= 100: return await ctx.reply("❌ Amount must be between 1 and 100.",mention_author=False)
    deleted=await ctx.channel.purge(limit=amount+1); removed=max(0,len(deleted)-1); await ctx.send(f"🧹 Removed {removed} messages.",delete_after=4); await send_log(ctx.guild.id,title="🧹 Messages purged",color=discord.Color.light_grey(),fields=[("Moderator",f"{ctx.author} ({ctx.author.id})"),("Channel",ctx.channel.mention),("Deleted",str(removed))])

@bot.command(name="slowmode")
@commands.guild_only()
@commands.has_guild_permissions(manage_channels=True)
@commands.bot_has_guild_permissions(manage_channels=True)
async def prefix_slowmode(ctx,seconds:int):
    if not 0 <= seconds <= 21600: return await ctx.reply("❌ Seconds must be between 0 and 21,600.",mention_author=False)
    await ctx.channel.edit(slowmode_delay=seconds); await ctx.reply(f"🐌 Slowmode set to {seconds} second(s).",mention_author=False); await send_log(ctx.guild.id,title="🐌 Slowmode changed",fields=[("Moderator",f"{ctx.author} ({ctx.author.id})"),("Channel",ctx.channel.mention),("Seconds",str(seconds))])

@bot.command(name="balance",aliases=["bal","wallet"])
@commands.guild_only()
async def prefix_balance(ctx,member:discord.Member=None):
    m=member or ctx.author; gid=ctx.guild.id; bal=economy_balance(gid,m.id); inv=economy_inventory_for(gid,m.id); total_items=sum(int(v) for v in inv.values()); await ctx.reply(f"👛 **{m.display_name}'s wallet**\n🌿 Catnip: **{bal:,}**\n🎒 Items: **{total_items}**",mention_author=False); await economy_log(gid,title="👛 Economy balance viewed",fields=[("Viewer",f"{ctx.author} ({ctx.author.id})"),("Member",f"{m} ({m.id})"),("Balance",f"{bal:,} Catnip"),("Total items",total_items)]); await bd_save_data()

@bot.command(name="inventory",aliases=["inv","bag"])
@commands.guild_only()
async def prefix_inventory(ctx,member:discord.Member=None):
    m=member or ctx.author; gid=ctx.guild.id; inv=economy_inventory_for(gid,m.id); lines=[f"{ECONOMY_ITEMS[k]['emoji']} **{ECONOMY_ITEMS[k]['name']}** × {v}" for k,v in inv.items() if k in ECONOMY_ITEMS and int(v)>0]; summary="\n".join(f"{ECONOMY_ITEMS[k]['name']}: {int(v)}" for k,v in inv.items() if k in ECONOMY_ITEMS and int(v)>0) or "Empty"; await ctx.reply("\n".join(lines) if lines else "🎒 Inventory is empty. Use `?shop`.",mention_author=False); await economy_log(gid,title="🎒 Economy inventory viewed",fields=[("Viewer",f"{ctx.author} ({ctx.author.id})"),("Member",f"{m} ({m.id})"),("Inventory",summary[:1000]),("Total items",sum(int(v) for v in inv.values())),("Catnip balance",economy_balance(gid,m.id))])

@bot.command(name="shop")
@commands.guild_only()
async def prefix_shop(ctx): await ctx.reply(embed=discord.Embed(title="🐟 Cinnamon's Catnip Shop",description=economy_item_lines(),color=discord.Color.gold()))

@bot.command(name="daily")
@commands.guild_only()
async def prefix_daily(ctx):
    gid,uid=ctx.guild.id,ctx.author.id; rem=economy_cooldown_remaining(gid,uid,"daily")
    if rem: return await ctx.reply(f"🐾 Daily ready in {rem//3600}h {(rem%3600)//60}m.",mention_author=False)
    economy_cooldowns[(gid,uid,"daily")]=time.time()+86400; economy_balances[(gid,uid)]=economy_balance(gid,uid)+ECONOMY_DAILY_REWARD; await bd_save_data(); await economy_log(gid,title="🌿 Daily Catnip",fields=[("User",str(ctx.author)),("Amount",f"+{ECONOMY_DAILY_REWARD}")]); await ctx.reply(f"🌿 +{ECONOMY_DAILY_REWARD} Catnip!",mention_author=False)

@bot.command(name="work")
@commands.guild_only()
async def prefix_work(ctx):
    _,_,msg=await economy_do_work(ctx.guild.id,ctx.author); await ctx.reply(msg,mention_author=False)

@bot.command(name="buy")
@commands.guild_only()
async def prefix_buy(ctx,item:str,quantity:int=1):
    if not 1 <= quantity <= 99: return await ctx.reply("❌ Quantity must be between 1 and 99.",mention_author=False)
    gid,uid=ctx.guild.id,ctx.author.id; item=item.lower().strip(); item=next((k for k,v in ECONOMY_ITEMS.items() if k==item or v["name"].lower()==item),item); data=ECONOMY_ITEMS.get(item)
    if not data: return await ctx.reply("❌ Item not found. Use `?shop`.",mention_author=False)
    bal=economy_balance(gid,uid); cost=data["price"]*quantity
    if bal<cost: return await ctx.reply(f"❌ Need {cost:,} Catnip; you have {bal:,}.",mention_author=False)
    inv=economy_inventory_for(gid,uid); inv[item]=int(inv.get(item,0))+quantity; economy_balances[(gid,uid)]=bal-cost; await bd_save_data(); await economy_log(gid,title="🛒 Economy purchase",fields=[("User",f"{ctx.author} ({uid})"),("Item",f"{data['name']} (`{item}`)"),("Quantity",quantity),("Unit price",data["price"]),("Deducted",f"-{cost:,} Catnip"),("Balance before",bal),("Balance after",bal-cost),("Item quantity after",inv[item])]); await ctx.reply(f"🛒 Bought {quantity}× {data['name']} for {cost:,} Catnip. Balance: {bal-cost:,}.",mention_author=False)

@bot.command(name="give",aliases=["pay","transfer"])
@commands.guild_only()
async def prefix_give(ctx,member:discord.Member,amount:int):
    if not 1 <= amount <= 1000000: return await ctx.reply("❌ Amount must be between 1 and 1,000,000.",mention_author=False)
    if member.bot or member.id==ctx.author.id: return await ctx.reply("❌ Choose another human member.",mention_author=False)
    gid=ctx.guild.id; bal=economy_balance(gid,ctx.author.id)
    if bal<amount: return await ctx.reply("❌ You don't have enough Catnip.",mention_author=False)
    recipient_before=economy_balance(gid,member.id); economy_balances[(gid,ctx.author.id)]=bal-amount; economy_balances[(gid,member.id)]=recipient_before+amount; await bd_save_data(); await economy_log(gid,title="💸 Catnip transfer",fields=[("From",f"{ctx.author} ({ctx.author.id})"),("To",f"{member} ({member.id})"),("Amount",f"{amount:,} Catnip"),("Sender before",bal),("Sender after",bal-amount),("Recipient before",recipient_before),("Recipient after",recipient_before+amount)]); await ctx.reply(f"💸 Sent {amount:,} Catnip to {member.mention}.",mention_author=False)

@bot.command(name="econlb",aliases=["economylb"])
@commands.guild_only()
async def prefix_econlb(ctx):
    rows=sorted(((uid,b) for (gid,uid),b in economy_balances.items() if gid==ctx.guild.id),key=lambda x:x[1],reverse=True)[:10]; lines=[f"**{i}.** {ctx.guild.get_member(uid) or f'User {uid}'} — {bal:,} Catnip" for i,(uid,bal) in enumerate(rows,1)]; await ctx.reply("\n".join(lines) if lines else "No economy balances yet.",mention_author=False)

@bot.command(name="rank")
@commands.guild_only()
async def prefix_rank(ctx,member:discord.Member=None):
    m=member or ctx.author; xp=int(xp_data.get((ctx.guild.id,m.id),0)); level=max(0,int(math.sqrt(max(0,xp)//100))); await ctx.reply(f"🏅 **{m.display_name}** — Level **{level}**, **{xp:,} XP**",mention_author=False)

@bot.command(name="leaderboard",aliases=["lb"])
@commands.guild_only()
async def prefix_leaderboard(ctx):
    rows=sorted(((uid,xp) for (gid,uid),xp in xp_data.items() if gid==ctx.guild.id),key=lambda x:x[1],reverse=True)[:10]; lines=[f"**{i}.** {ctx.guild.get_member(uid) or f'User {uid}'} — {xp:,} XP" for i,(uid,xp) in enumerate(rows,1)]; await ctx.reply("\n".join(lines) if lines else "No XP data yet.",mention_author=False)

@bot.command(name="botstatus",aliases=["status"])
async def prefix_botstatus(ctx): await ctx.reply(f"🐾 Cinnamon is online. Latency: {round(bot.latency*1000)} ms.",mention_author=False)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    # Dispatch ? commands before the regular AI/XP chat pipeline.
    ctx = await bot.get_context(message)
    if ctx.valid:
        await bot.invoke(ctx)
        return

    if message.guild:
        # --- AFK: clear the sender's own status, and flag anyone AFK they pinged ---
        afk_key = (message.guild.id, message.author.id)
        if afk_key in afk_users:
            old_reason = afk_users.pop(afk_key)
            await send_log(message.guild.id, title="💤 AFK status cleared", category="general",
                           fields=[("User", f"{message.author} ({message.author.id})"), ("Previous reason", str(old_reason)[:300])])
            try:
                await message.channel.send(
                    f"🐾 Welcome back, {message.author.mention}! I've cleared your AFK status.",
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            except discord.HTTPException:
                pass
        afk_notes = [
            f"🐾 **{u.display_name}** is AFK: {afk_users[(message.guild.id, u.id)]}"
            for u in message.mentions if (message.guild.id, u.id) in afk_users
        ]
        if afk_notes:
            try:
                await message.channel.send("\n".join(afk_notes), allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

        # --- Auto-moderation: acts first; a removed message skips everything else below ---
        if await run_automod(message):
            return

    speaker = message.author.display_name
    content = message.content.strip()

    # Strip the bot's own mention text out of the message before we store/send it.
    clean_content = content
    if bot.user:
        clean_content = clean_content.replace(f"<@{bot.user.id}>", "").strip()
        clean_content = clean_content.replace(f"<@!{bot.user.id}>", "").strip()

    # --- XP: award for genuine chat messages, at most once per user per 60s ---
    if message.guild and clean_content:
        await award_xp(message)

    if clean_content:
        channel_memories[message.channel.id].append((speaker, clean_content))

    guild_id = message.guild.id if message.guild else None
    channel_id = message.channel.id

    # A disabled channel overrides everything else — Cinnamon stays silent here.
    if guild_id is not None and channel_id in disabled_channels[guild_id]:
        return

    was_mentioned = bot.user is not None and bot.user in message.mentions and not message.mention_everyone

    # Check if this message is a reply to one of Cinnamon's own messages.
    was_reply_to_bot = False
    if message.reference and bot.user:
        ref = message.reference.resolved
        if ref is None:
            try:
                ref = await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.HTTPException):
                ref = None
        if isinstance(ref, discord.Message) and ref.author.id == bot.user.id:
            was_reply_to_bot = True

    is_ai_channel = guild_id is not None and ai_channels.get(guild_id) == channel_id

    if clean_content and (was_mentioned or was_reply_to_bot or is_ai_channel):
        # Keep an always-on AI channel from turning chat bursts into Gemini bursts.
        now = time.monotonic()
        if is_ai_channel and not (was_mentioned or was_reply_to_bot):
            last_ai = ai_cooldowns.get(channel_id, 0.0)
            if now - last_ai < AI_CHANNEL_COOLDOWN_SECONDS:
                return
            ai_cooldowns[channel_id] = now

        if is_owner_question(clean_content):
            # Hard-coded so this is always correct, instead of hoping the model remembers.
            reply = (
                f"*puffs up proudly* {OWNER_NAME} is my human and my favorite person "
                f"in the whole wide world! {owner_mention(message.guild)}"
            )
            reaction = "❤️"
        else:
            async with message.channel.typing():
                try:
                    result = await asyncio.to_thread(
                        ask_gemini, message.channel.id, speaker, clean_content, message.guild
                    )
                except Exception as e:
                    log.error(f"Gemini call failed: {e}")
                    result = {
                        "reply": "*paws at the screen, confused* ...something smells like tuna gone wrong. Try again in a moment?",
                        "reaction": "",
                    }
            reply = result["reply"]
            reaction = result["reaction"]

        channel_memories[message.channel.id].append(("Cinnamon", reply))

        # In the dedicated AI channel, chat naturally instead of quote-replying
        # to every single message — but still use a reply if directly pinged.
        if is_ai_channel and not (was_mentioned or was_reply_to_bot):
            await message.channel.send(reply)
        else:
            await message.reply(
                reply, mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        await add_reaction_safely(message, reaction)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="pet", description="Give Cinnamon some pets")
async def pet(interaction: discord.Interaction):
    await interaction.response.send_message(
        "*melts into a puddle of fluff, purring loudly* Purrrrr... more, please?"
    )


@bot.tree.command(name="treat", description="Offer Cinnamon a treat")
async def treat(interaction: discord.Interaction):
    await interaction.response.send_message(
        "*ears perk up, pupils go huge* Tuna?? Churu?? ANYTHING?? *sits so politely*"
    )


@bot.tree.command(name="nap", description="Let Cinnamon take a nap")
async def nap(interaction: discord.Interaction):
    await interaction.response.send_message(
        "*curls into a tight loaf on the nearest keyboard* Zzz... five more minutes..."
    )


@bot.tree.command(name="zoomies", description="Uh oh, Cinnamon has the zoomies")
async def zoomies(interaction: discord.Interaction):
    await interaction.response.send_message(
        "*tears across the room sideways, tail puffed* WHO TURNED ON THE FLOOR IS LAVA?!"
    )


# ---------------------------------------------------------------------------
# AI channel configuration (mods only)
# ---------------------------------------------------------------------------

@bot.tree.command(name="aichannel", description="Make Cinnamon reply to every message in this channel, no mention needed")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def aichannel(interaction: discord.Interaction):
    ai_channels[interaction.guild.id] = interaction.channel.id
    await bd_save_data()
    await interaction.response.send_message(
        f"*claims {interaction.channel.mention} as her own* I'll chat here without being mentioned now!"
    )
    await send_log(
        interaction.guild.id, title="⚙️ AI channel set", interaction=interaction,
        fields=[("Channel", interaction.channel.mention)],
    )


@bot.tree.command(name="disableaichannel", description="Turn off Cinnamon's always-on AI channel for this server")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def disableaichannel(interaction: discord.Interaction):
    removed = ai_channels.pop(interaction.guild.id, None)
    await bd_save_data()
    if removed:
        await interaction.response.send_message(
            "*stretches and wanders off* Back to needing a mention or reply now."
        )
        await send_log(interaction.guild.id, title="⚙️ AI channel disabled", interaction=interaction)
    else:
        await interaction.response.send_message(
            "*blinks* There wasn't an AI channel set for this server.", ephemeral=True
        )


@bot.tree.command(name="disableai", description="Stop Cinnamon from talking in this channel at all")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def disableai(interaction: discord.Interaction):
    disabled_channels[interaction.guild.id].add(interaction.channel.id)
    await bd_save_data()
    await interaction.response.send_message(
        "*curls up and goes quiet* Won't respond in this channel anymore, even if mentioned."
    )
    await send_log(
        interaction.guild.id, title="⚙️ Channel muted for AI", interaction=interaction,
        fields=[("Channel", interaction.channel.mention)],
    )


@bot.tree.command(name="enableai", description="Let Cinnamon talk in this channel again")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def enableai(interaction: discord.Interaction):
    disabled_channels[interaction.guild.id].discard(interaction.channel.id)
    await bd_save_data()
    await interaction.response.send_message("*perks back up* I can talk here again!")
    await send_log(
        interaction.guild.id, title="⚙️ Channel re-enabled for AI", interaction=interaction,
        fields=[("Channel", interaction.channel.mention)],
    )


@bot.tree.command(name="logchannel", description="Set this channel as Cinnamon's log channel for mod actions and errors")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def logchannel(interaction: discord.Interaction):
    log_channels[interaction.guild.id] = interaction.channel.id
    await secure_log_channel(interaction.channel)
    await bd_save_data()
    status = await storage_status()
    icon = "✅" if status["connected"] else "⚠️"
    await interaction.response.send_message(
        f"*sets up a little logbook in {interaction.channel.mention}* "
        f"I'll post mod actions, config changes, and errors here from now on.\n\n"
        f"{icon} **Storage:** {status['backend']} — {status['detail']}"
    )
    await send_log(
        interaction.guild.id,
        title="📋 Log channel set",
        description=f"This channel is now Cinnamon's log channel.",
        color=discord.Color.blurple(),
        interaction=interaction,
        fields=[("Storage backend", status["backend"]), ("Connected", "Yes" if status["connected"] else "No")],
    )


@bot.tree.command(name="disablelogchannel", description="Stop Cinnamon from posting logs anywhere in this server")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def disablelogchannel(interaction: discord.Interaction):
    removed = log_channels.pop(interaction.guild.id, None)
    await bd_save_data()
    if removed:
        await interaction.response.send_message("*closes the logbook* Stopped logging actions for this server.")
        await send_log(interaction.guild.id, title="📋 Main log channel disabled", interaction=interaction, category="setup",
                       fields=[("Previous channel ID", str(removed))])
    else:
        await interaction.response.send_message(
            "*blinks* There wasn't a log channel set for this server.", ephemeral=True
        )


# ---------------------------------------------------------------------------
# Moderation commands (mods only)
# ---------------------------------------------------------------------------

@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Who to kick", reason="Why are they being kicked?")
@app_commands.guild_only()
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.checks.bot_has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member,
               reason: app_commands.Range[str, 1, 300] = "No reason given"):
    await member.kick(reason=reason)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(f"*escorts {member.mention} out with a paw* Kicked. Reason: {reason}")
    await send_log(
        interaction.guild.id, title="👢 Member kicked", color=discord.Color.orange(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Reason", reason)],
    )


@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Who to ban", reason="Why are they being banned?")
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member,
              reason: app_commands.Range[str, 1, 300] = "No reason given"):
    await member.ban(reason=reason, delete_message_seconds=0)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(f"*hisses and swats {member.mention} out the door* Banned. Reason: {reason}")
    await send_log(
        interaction.guild.id, title="🔨 Member banned", color=discord.Color.red(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Reason", reason)],
    )


@bot.tree.command(name="unban", description="Unban a user using their user ID")
@app_commands.describe(user_id="The numeric ID of the user to unban")
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        await interaction.guild.unban(discord.Object(id=int(user_id)))
        temp_bans.pop((interaction.guild.id, int(user_id)), None)  # in case it was also a tempban
        case_id = next_case(interaction.guild.id)
        await bd_save_data()
        await interaction.response.send_message(f"*nudges the door back open* Unbanned <@{user_id}>.")
        await send_log(
            interaction.guild.id, title="🔓 Member unbanned", color=discord.Color.green(), interaction=interaction,
            fields=[("Case", f"#{case_id}"), ("User ID", str(int(user_id)))],
        )
    except (ValueError, discord.NotFound):
        await interaction.response.send_message(
            "*tilts head* Couldn't find that user ID on the ban list.", ephemeral=True
        )


@bot.tree.command(name="mute", description="Timeout a member so they can't send messages for a while")
@app_commands.describe(member="Who to mute", minutes="How many minutes to mute for", reason="Why are they being muted?")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int = 10,
               reason: app_commands.Range[str, 1, 300] = "No reason given"):
    await member.timeout(datetime.timedelta(minutes=minutes), reason=reason)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(
        f"*sits on {member.mention}'s keyboard* Muted for {minutes} minute(s). Reason: {reason}"
    )
    await send_log(
        interaction.guild.id, title="🔇 Member muted", color=discord.Color.orange(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Duration", f"{minutes} min"), ("Reason", reason)],
    )


@bot.tree.command(name="unmute", description="Remove a member's timeout early")
@app_commands.describe(member="Who to unmute")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(f"*hops off the keyboard* {member.mention} can talk again.")
    await send_log(
        interaction.guild.id, title="🔊 Member unmuted", color=discord.Color.green(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})")],
    )


@bot.tree.command(name="purge", description="Delete a number of recent messages in this channel")
@app_commands.describe(amount="How many messages to delete (1-100)")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"*sweeps up {len(deleted)} messages with her tail* All tidy now!", ephemeral=True)
    await send_log(
        interaction.guild.id, title="🧹 Messages purged", color=discord.Color.light_grey(), interaction=interaction,
        fields=[("Channel", interaction.channel.mention), ("Deleted", str(len(deleted)))],
    )


@bot.tree.command(name="slowmode", description="Set slowmode (message rate limit) for a channel")
@app_commands.describe(
    seconds="Seconds each member must wait between messages (0 turns it off, max 21600 = 6 hours)",
    channel="Channel to apply it to (defaults to this channel)",
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: int,
                    channel: discord.TextChannel = None):
    target = channel or interaction.channel
    await target.edit(slowmode_delay=seconds)
    if seconds == 0:
        msg = f"*stops pacing the room* Slowmode's off in {target.mention}."
    else:
        msg = f"*sets a little hourglass* Slowmode set to {seconds}s in {target.mention}."
    await interaction.response.send_message(msg)
    await send_log(
        interaction.guild.id, title="🐌 Slowmode changed", color=discord.Color.blurple(), interaction=interaction,
        fields=[("Channel", target.mention), ("Seconds", str(seconds))],
    )


# ---------------------------------------------------------------------------
# Role commands (mods only) — grouped under /role
# ---------------------------------------------------------------------------

role_group = app_commands.Group(name="role", description="Add roles to members")


@role_group.command(name="add", description="Add a role to one specific member")
@app_commands.describe(member="Who to give the role to", role="Which role to add")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def role_add(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.add_roles(role, reason=f"/role add run by {interaction.user}")
    await interaction.response.send_message(
        f"*drapes **{role.name}** over {member.mention}* Done!",
        allowed_mentions=discord.AllowedMentions(roles=False),
    )
    await send_log(
        interaction.guild.id, title="🏷️ Role added", color=discord.Color.green(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})"), ("Role", role.name)],
    )


@role_group.command(name="add-all", description="Add a role to every member in the server")
@app_commands.describe(
    role="Which role to add to everyone",
    include_bots="Also give the role to bot accounts (default: no)",
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_roles=True, manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def role_add_all(interaction: discord.Interaction, role: discord.Role, include_bots: bool = False):
    if role.is_default():
        await interaction.response.send_message("*tilts head* Everyone already has @everyone!", ephemeral=True)
        return
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            "*can't quite reach that high* That role sits above (or level with) my own top role — "
            "move my role above it in Server Settings → Roles first.", ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)
    targets = [m for m in interaction.guild.members if role not in m.roles and (include_bots or not m.bot)]

    added, failed = 0, 0
    for member in targets:
        try:
            await member.add_roles(role, reason=f"/role add-all run by {interaction.user}")
            added += 1
        except discord.HTTPException:
            failed += 1

    summary = f"*stamps **{role.name}** onto {added} member(s)* All done!"
    if failed:
        summary += f" ({failed} couldn't be given the role — probably role hierarchy.)"
    await interaction.followup.send(summary, allowed_mentions=discord.AllowedMentions(roles=False))
    await send_log(
        interaction.guild.id, title="🏷️ Role added to all members", color=discord.Color.green(), interaction=interaction,
        fields=[("Role", role.name), ("Added", str(added)), ("Failed", str(failed))],
    )


bot.tree.add_command(role_group)


# ---------------------------------------------------------------------------
# Friendly errors for missing permissions, instead of a raw Discord error
# ---------------------------------------------------------------------------

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Command exceptions arrive wrapped in CommandInvokeError — unwrap to get
    # at the real Discord exception so we can tell what actually went wrong.
    original = error.original if isinstance(error, app_commands.CommandInvokeError) else error

    if isinstance(error, app_commands.MissingPermissions):
        msg = "*narrows eyes* You don't have the paws for that command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "*paws helplessly* I don't have permission to do that — check my role's permissions in Server Settings."
    elif isinstance(original, discord.Forbidden):
        # The classic cause: Discord blocks the action even with the right permission
        # if the bot's role isn't positioned above the target's highest role (or if
        # the target has Administrator, for timeouts specifically).
        msg = (
            "*paws helplessly* Discord won't let me do that to them. This usually means "
            "my role needs to be moved *above* their role in Server Settings → Roles "
            "(drag my role near the top). Members with Administrator also can't be muted, "
            "by Discord's own rules."
        )
    elif isinstance(original, discord.NotFound):
        msg = "*tilts head* Couldn't find that — they may have already left, or it no longer exists."
    else:
        log.error(f"Command error in /{interaction.command.name if interaction.command else '?'}: {original!r}")
        msg = "*knocks something off a shelf* Something went wrong running that."

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)

    await send_log(
        interaction.guild.id if interaction.guild else None,
        title="⚠️ Command error",
        description=(
            f"`/{interaction.command.name if interaction.command else 'unknown'}` "
            f"failed with: `{original!r}`"
        ),
        color=discord.Color.red(),
        interaction=interaction,
        category=_command_log_category(interaction.command.qualified_name if interaction.command else ""),
    )


# ---------------------------------------------------------------------------
# Keep-alive web server (Koyeb / Render free tiers expect something bound
# to $PORT). Runs in a background thread alongside the bot.
# ---------------------------------------------------------------------------

flask_app = Flask(__name__)
flask_app.secret_key = os.environ.get("DASHBOARD_SESSION_SECRET") or os.urandom(32)


@flask_app.route("/")
def home():
    return "Cinnamon is awake and purring. 🐾"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


# ---------------------------------------------------------------------------
# Extended features: warnings, user/server info, AFK, welcome/goodbye,
# edit/delete logging, reaction roles, auto-mod, temp-bans, leveling,
# giveaways, anti-raid, and channel lock/unlock.
# ---------------------------------------------------------------------------

# --- Persistence (same Upstash-or-local-file approach as Hangry Games' data) ---

BD_DATA_FILE = os.environ.get("BOT_DATA_FILE", "cinnamon_data.json")
BD_UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
BD_UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
BD_REDIS_KEY = "cinnamon_bot_data"


def _bd_encode() -> dict:
    return {
        "warnings": {f"{g}:{m}": v for (g, m), v in warnings_data.items()},
        "welcome_config": {str(k): v for k, v in welcome_config.items()},
        "goodbye_config": {str(k): v for k, v in goodbye_config.items()},
        "automod_config": {str(k): v for k, v in automod_config.items()},
        "xp_data": {f"{g}:{m}": v for (g, m), v in xp_data.items()},
        "reaction_role_ids": list(reaction_role_ids),
        "temp_bans": {f"{g}:{m}": v for (g, m), v in temp_bans.items()},
        "antiraid_config": {str(k): v for k, v in antiraid_config.items()},
        "case_counters": {str(k): v for k, v in case_counters.items()},
        "level_roles": {str(g): {str(l): r for l, r in v.items()} for g, v in level_roles.items()},
        "active_giveaways": {str(k): v for k, v in active_giveaways.items()},
        "active_polls": {str(k): v for k, v in active_polls.items()},
        "economy_balances": {f"{g}:{u}": v for (g, u), v in economy_balances.items()},
        "economy_inventory": {f"{g}:{u}": v for (g, u), v in economy_inventory.items()},
        "economy_quests": {f"{g}:{u}": v for (g, u), v in economy_quests.items()},
        "economy_cooldowns": {f"{g}:{u}:{a}": v for (g, u, a), v in economy_cooldowns.items()},
        "economy_log_channels": {str(k): v for k, v in economy_log_channels.items()},
        "economy_level_rewards_claimed": {f"{g}:{u}": list(levels) for (g, u), levels in economy_level_rewards_claimed.items()},
        "economy_income_roles": {str(g): {str(r): cfg for r, cfg in roles.items()} for g, roles in economy_income_roles.items()},
        "economy_achievements": {f"{g}:{u}": list(ids) for (g, u), ids in economy_achievements.items()},
        "economy_items": ECONOMY_ITEMS,
        "economy_quest_definitions": ECONOMY_QUESTS,
        # Server configuration that should survive a restart/redeploy.
        "ai_channels": {str(k): v for k, v in ai_channels.items()},
        "disabled_channels": {str(k): list(v) for k, v in disabled_channels.items()},
        "log_channels": {str(k): v for k, v in log_channels.items()},
        "category_log_channels": {str(g): {str(c): ch for c, ch in cfg.items()} for g, cfg in category_log_channels.items()},
    }


def _bd_decode(raw: dict):
    global warnings_data, welcome_config, goodbye_config, automod_config
    global xp_data, reaction_role_ids, temp_bans, antiraid_config, case_counters
    global level_roles, active_giveaways, active_polls, ai_channels, disabled_channels, log_channels, category_log_channels
    global economy_balances, economy_inventory, economy_quests, economy_cooldowns, economy_log_channels
    global economy_level_rewards_claimed, economy_income_roles, economy_achievements
    warnings_data = defaultdict(list, {tuple(map(int, k.split(":"))): v for k, v in raw.get("warnings", {}).items()})
    welcome_config = {int(k): v for k, v in raw.get("welcome_config", {}).items()}
    goodbye_config = {int(k): v for k, v in raw.get("goodbye_config", {}).items()}
    automod_config = {int(k): v for k, v in raw.get("automod_config", {}).items()}
    xp_data = {tuple(map(int, k.split(":"))): v for k, v in raw.get("xp_data", {}).items()}
    reaction_role_ids = set(raw.get("reaction_role_ids", []))
    temp_bans = {tuple(map(int, k.split(":"))): v for k, v in raw.get("temp_bans", {}).items()}
    antiraid_config = {int(k): v for k, v in raw.get("antiraid_config", {}).items()}
    case_counters = {int(k): v for k, v in raw.get("case_counters", {}).items()}
    level_roles = {int(g): {int(l): r for l, r in v.items()} for g, v in raw.get("level_roles", {}).items()}
    active_giveaways = {int(k): v for k, v in raw.get("active_giveaways", {}).items()}
    active_polls = {int(k): v for k, v in raw.get("active_polls", {}).items()}
    economy_balances = {tuple(map(int, k.split(":"))): v for k, v in raw.get("economy_balances", {}).items()}
    economy_inventory = {tuple(map(int, k.split(":"))): v for k, v in raw.get("economy_inventory", {}).items()}
    economy_quests = {tuple(map(int, k.split(":"))): v for k, v in raw.get("economy_quests", {}).items()}
    economy_cooldowns = {}
    for k, v in raw.get("economy_cooldowns", {}).items():
        parts = k.split(":")
        if len(parts) == 3:
            economy_cooldowns[(int(parts[0]), int(parts[1]), parts[2])] = v
    economy_log_channels = {int(k): v for k, v in raw.get("economy_log_channels", {}).items()}
    economy_level_rewards_claimed = {}
    for k, levels in raw.get("economy_level_rewards_claimed", {}).items():
        parts = k.split(":")
        if len(parts) == 2:
            economy_level_rewards_claimed[(int(parts[0]), int(parts[1]))] = [int(x) for x in levels]
    economy_income_roles = {int(g): {int(r): cfg for r, cfg in roles.items()} for g, roles in raw.get("economy_income_roles", {}).items()}
    economy_achievements = {}
    for k, ids in raw.get("economy_achievements", {}).items():
        parts = k.split(":")
        if len(parts) == 2 and isinstance(ids, list):
            economy_achievements[(int(parts[0]), int(parts[1]))] = [str(x) for x in ids if str(x) in ECONOMY_ACHIEVEMENTS]
    saved_items = raw.get("economy_items")
    if isinstance(saved_items, dict):
        ECONOMY_ITEMS.clear()
        for item_id, item in saved_items.items():
            if isinstance(item, dict):
                ECONOMY_ITEMS[str(item_id)] = {
                    "name": str(item.get("name", item_id))[:80],
                    "price": max(1, int(item.get("price", 1))),
                    "emoji": str(item.get("emoji", "🐾"))[:8],
                    "description": str(item.get("description", ""))[:300],
                    "max_per_person": max(0, int(item.get("max_per_person", 0))),
                }
    saved_quests = raw.get("economy_quest_definitions")
    if isinstance(saved_quests, dict):
        ECONOMY_QUESTS.clear()
        for quest_id, quest in saved_quests.items():
            if isinstance(quest, dict) and str(quest.get("item", "")) in ECONOMY_ITEMS:
                ECONOMY_QUESTS[str(quest_id)] = {
                    "name": str(quest.get("name", quest_id))[:80],
                    "item": str(quest.get("item")),
                    "amount": max(1, int(quest.get("amount", 1))),
                    "reward": max(0, int(quest.get("reward", 0))),
                    "description": str(quest.get("description", ""))[:300],
                }
    ai_channels = {int(k): v for k, v in raw.get("ai_channels", {}).items()}
    disabled_channels = defaultdict(set, {int(k): set(v) for k, v in raw.get("disabled_channels", {}).items()})
    log_channels = {int(k): v for k, v in raw.get("log_channels", {}).items()}
    category_log_channels = {int(g): {str(c): int(ch) for c, ch in cfg.items()} for g, cfg in raw.get("category_log_channels", {}).items() if isinstance(cfg, dict)}


async def bd_load_data():
    """Load persisted settings (warnings, welcome/goodbye, auto-mod config, XP,
    reaction roles, temp-bans, anti-raid config). Uses Upstash Redis if
    configured (survives redeploys), otherwise a local JSON file (restarts
    only). Never raises — a missing/corrupt/unreachable store just means we
    start fresh."""
    if BD_UPSTASH_URL and BD_UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    BD_UPSTASH_URL, json=["GET", BD_REDIS_KEY],
                    headers={"Authorization": f"Bearer {BD_UPSTASH_TOKEN}"},
                ) as resp:
                    result = (await resp.json()).get("result")
            if result:
                _bd_decode(json.loads(result))
            return
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, ValueError) as e:
            log.error(f"Failed to load bot data from Upstash: {e}")
            return
    try:
        with open(BD_DATA_FILE, "r") as f:
            _bd_decode(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass


async def bd_save_data():
    """Persist settings. See bd_load_data for storage choice. Never raises —
    a failed save shouldn't break a command."""
    encoded = _bd_encode()
    if BD_UPSTASH_URL and BD_UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    BD_UPSTASH_URL, json=["SET", BD_REDIS_KEY, json.dumps(encoded)],
                    headers={"Authorization": f"Bearer {BD_UPSTASH_TOKEN}"},
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.error(f"Failed to save bot data to Upstash: {e}")
        return
    try:
        with open(BD_DATA_FILE, "w") as f:
            json.dump(encoded, f)
    except OSError as e:
        log.error(f"Failed to save bot data: {e}")


def dashboard_state_provider() -> dict:
    """Expose live bot state to the Flask dashboard without copying mutable data."""
    hg = bot.get_cog("HangryGamesCog")
    return {
        "warnings_data": warnings_data, "welcome_config": welcome_config,
        "goodbye_config": goodbye_config, "automod_config": automod_config,
        "xp_data": xp_data, "level_roles": level_roles, "antiraid_config": antiraid_config,
        "active_giveaways": active_giveaways, "economy_balances": economy_balances,
        "economy_inventory": economy_inventory, "economy_quests": economy_quests,
        "economy_log_channels": economy_log_channels, "economy_income_roles": economy_income_roles,
        "ECONOMY_ITEMS": ECONOMY_ITEMS, "ECONOMY_QUESTS": ECONOMY_QUESTS, "ECONOMY_ACHIEVEMENTS": ECONOMY_ACHIEVEMENTS, "economy_achievements": economy_achievements,
        "ECONOMY_DAILY_REWARD": ECONOMY_DAILY_REWARD, "ECONOMY_WORK_MIN": ECONOMY_WORK_MIN,
        "ECONOMY_WORK_MAX": ECONOMY_WORK_MAX, "ECONOMY_WORK_COOLDOWN": ECONOMY_WORK_COOLDOWN,
        "ai_channels": ai_channels, "log_channels": log_channels,
        "category_log_channels": category_log_channels,
        "BD_UPSTASH_URL": BD_UPSTASH_URL, "BD_UPSTASH_TOKEN": BD_UPSTASH_TOKEN,
        "bd_save_data": bd_save_data, "send_log": send_log,
        "recall_guild_data": recall_guild_data,
        "level_from_xp": level_from_xp, "giveaway_embed": _giveaway_embed,
        "giveaway_view": GiveawayView, "finish_giveaway": finish_giveaway,
        "cancel_giveaway": cancel_giveaway,
        "hg_cog": hg,
    }


try:
    import dashboard as cinnamon_dashboard
    cinnamon_dashboard.configure_dashboard(bot, dashboard_state_provider)
    flask_app.register_blueprint(cinnamon_dashboard.dashboard_bp)
except Exception as dashboard_error:
    log.exception("Dashboard could not be initialized (%s)", type(dashboard_error).__name__)


@tasks.loop(minutes=5)
async def periodic_save():
    """XP changes on every eligible message, so we batch-save it (and anything
    else pending) every few minutes instead of hitting the store on every
    single message — everything admin-triggered (warn, welcome config, etc.)
    still saves immediately when it happens."""
    await bd_save_data()


def next_case(guild_id: int) -> int:
    """Issue the next sequential moderation case number for this guild
    (warn/kick/ban/unban/mute/tempban/automod all share one counter, so mods
    can reference "case #N" unambiguously). Caller is responsible for saving —
    it's always called right before a send_log/bd_save_data anyway."""
    case_counters[guild_id] = case_counters.get(guild_id, 0) + 1
    return case_counters[guild_id]


async def storage_status() -> dict:
    """Live health check of the persistence backend. Does NOT touch real data —
    just confirms the connection actually works right now. Returns
    {"backend": "Upstash Redis" | "local JSON file", "connected": bool, "detail": str}."""
    if BD_UPSTASH_URL and BD_UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    BD_UPSTASH_URL, json=["PING"],
                    headers={"Authorization": f"Bearer {BD_UPSTASH_TOKEN}"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    data = await resp.json()
            ok = data.get("result") == "PONG"
            return {
                "backend": "Upstash Redis", "connected": ok,
                "detail": "Reachable — data survives restarts and redeploys." if ok
                          else f"Configured but not responding as expected: {data}",
            }
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            return {"backend": "Upstash Redis", "connected": False, "detail": f"Configured but unreachable: {e}"}
    file_writable = True
    try:
        with open(BD_DATA_FILE, "a"):
            pass
    except OSError:
        file_writable = False
    return {
        "backend": "local JSON file", "connected": file_writable,
        "detail": (
            "No UPSTASH_REDIS_REST_URL/TOKEN set. Data survives plain restarts but is "
            "LIKELY WIPED on a Render redeploy (no persistent disk on the free tier)."
        ) if file_writable else "Local file isn't writable — data isn't being saved at all right now.",
    }


# --- Warnings -------------------------------------------------------------

def add_warning(guild_id: int, member_id: int, reason: str, moderator: discord.abc.User) -> int:
    lst = warnings_data[(guild_id, member_id)]
    lst.append({
        "reason": reason, "mod_id": moderator.id, "mod_name": str(moderator),
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    return len(lst)


_WARN_LOG_TITLES = {"⚠️ Member warned", "🚨 Auto-mod action"}
_ID_IN_PARENS_RE = re.compile(r"\((\d+)\)\s*$")


async def recover_warnings_from_log(guild: discord.Guild, limit: int = 2000) -> int:
    """Rebuild this guild's warnings entirely from the mod log channel's message
    history — used when the persisted store comes back empty for a guild that
    has a log channel configured. Only recovers what's still in the channel's
    scanned history (bounded by `limit` messages and Discord's own retention),
    so this is a best-effort recovery, not a guarantee of completeness."""
    channel_id = log_channels.get(guild.id)
    if channel_id is None:
        return 0
    channel = bot.get_channel(channel_id)
    if channel is None:
        return 0

    found: list[tuple[int, dict]] = []  # (member_id, warning_dict)
    max_case = 0
    try:
        async for message in channel.history(limit=limit):
            for embed in message.embeds:
                case_val = next((f.value for f in embed.fields if f.name == "Case"), "")
                if case_val.lstrip("#").isdigit():
                    max_case = max(max_case, int(case_val.lstrip("#")))
                if embed.title not in _WARN_LOG_TITLES:
                    continue
                fields = {f.name: f.value for f in embed.fields}
                member_field = fields.get("Member", "")
                m = _ID_IN_PARENS_RE.search(member_field)
                if not m:
                    continue
                member_id = int(m.group(1))
                reason = fields.get("Reason", "Unknown (recovered from log)")
                if embed.title == "🚨 Auto-mod action":
                    reason = f"[Auto-mod] {reason}"
                    mod_name = "Auto-mod (recovered)"
                    mod_id = bot.user.id if bot.user else 0
                else:
                    footer_m = re.search(r"Run by (.+?) • #", embed.footer.text or "") if embed.footer else None
                    mod_name = footer_m.group(1) if footer_m else "Unknown (recovered from log)"
                    mod_id = 0
                ts = embed.timestamp.isoformat() if embed.timestamp else datetime.datetime.now(datetime.timezone.utc).isoformat()
                found.append((member_id, {"reason": reason, "mod_id": mod_id, "mod_name": mod_name, "ts": ts}))
    except discord.HTTPException as e:
        log.error(f"Failed to scan log channel for warning recovery in guild {guild.id}: {e}")
        return 0

    if max_case > case_counters.get(guild.id, 0):
        case_counters[guild.id] = max_case  # so new cases continue after the highest one logged
        await bd_save_data()
    if not found:
        return 0
    found.sort(key=lambda pair: pair[1]["ts"])  # oldest first, matching normal append order
    recovered_count = 0
    for member_id, warning in found:
        existing = warnings_data[(guild.id, member_id)]
        signature = (warning.get("ts"), warning.get("reason"), warning.get("mod_name"))
        if any((item.get("ts"), item.get("reason"), item.get("mod_name")) == signature for item in existing):
            continue
        existing.append(warning)
        recovered_count += 1
    if recovered_count or max_case > case_counters.get(guild.id, 0):
        await bd_save_data()
    return recovered_count


@bot.tree.command(name="warn", description="Warn a member and log it")
@app_commands.describe(member="Who to warn", reason="Why")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.guild_only()
async def warn(interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 300]):
    count = add_warning(interaction.guild.id, member.id, reason, interaction.user)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 *hisses a warning at* {member.mention} — now has **{count}** warning(s). (Case #{case_id})",
        allowed_mentions=discord.AllowedMentions(users=True),
    )
    await send_log(
        interaction.guild.id, title="⚠️ Member warned", color=discord.Color.orange(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Reason", reason), ("Total warnings", str(count))],
    )


@bot.tree.command(name="warnings", description="View a member's warning history")
@app_commands.describe(member="Whose warnings to view")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.guild_only()
async def warnings_cmd(interaction: discord.Interaction, member: discord.Member):
    lst = warnings_data.get((interaction.guild.id, member.id), [])
    if not lst:
        return await interaction.response.send_message(f"{member.display_name} has no warnings. 🐾", ephemeral=True)
    embed = discord.Embed(title=f"⚠️ Warnings for {member.display_name}", color=discord.Color.orange())
    for i, w in enumerate(lst[-10:], 1):
        embed.add_field(name=f"#{i} — {w['ts'][:10]}", value=f"{w['reason']} (by {w['mod_name']})", inline=False)
    embed.set_footer(text=f"{len(lst)} total warning(s)")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="clearwarnings", description="Clear all warnings for a member")
@app_commands.describe(member="Whose warnings to clear")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    removed = len(warnings_data.pop((interaction.guild.id, member.id), []))
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Cleared **{removed}** warning(s) for {member.display_name}.")
    await send_log(
        interaction.guild.id, title="🧹 Warnings cleared", color=discord.Color.green(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})"), ("Cleared", str(removed))],
    )


# --- User / server info -----------------------------------------------------

@bot.tree.command(name="userinfo", description="Show info about a member")
@app_commands.describe(member="Who to look up (defaults to you)")
@app_commands.guild_only()
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    warn_count = len(warnings_data.get((interaction.guild.id, member.id), []))
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    embed = discord.Embed(
        title=f"🐾 {member.display_name}",
        color=member.color if member.color.value else 0xFFB02E,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
    embed.add_field(
        name="Joined server",
        value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Unknown", inline=True,
    )
    embed.add_field(name="Warnings", value=str(warn_count), inline=True)
    embed.add_field(name=f"Roles ({len(roles)})", value=", ".join(roles) if roles else "None", inline=False)
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="serverinfo", description="Show info about this server")
@app_commands.guild_only()
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(title=f"🐾 {g.name}", color=0xFFB02E)
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, "R"), inline=True)
    embed.add_field(name="Members", value=str(g.member_count), inline=True)
    embed.add_field(name="Boost tier", value=str(g.premium_tier), inline=True)
    embed.add_field(name="Text channels", value=str(len(g.text_channels)), inline=True)
    embed.add_field(name="Voice channels", value=str(len(g.voice_channels)), inline=True)
    embed.add_field(name="Roles", value=str(len(g.roles)), inline=True)
    embed.add_field(name="Owner", value=g.owner.mention if g.owner else "Unknown", inline=True)
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


# --- AFK ---------------------------------------------------------------------

@bot.tree.command(name="afk", description="Mark yourself AFK; Cinnamon notifies anyone who pings you")
@app_commands.describe(reason="Optional reason")
@app_commands.guild_only()
async def afk_cmd(interaction: discord.Interaction, reason: str = "AFK"):
    afk_users[(interaction.guild.id, interaction.user.id)] = reason[:200]
    await interaction.response.send_message(
        f"🐾 {interaction.user.mention} is now AFK: {reason}",
        allowed_mentions=discord.AllowedMentions(users=True),
    )
    await send_log(interaction.guild.id, title="💤 AFK status set", interaction=interaction, category="general",
                   fields=[("User", f"{interaction.user} ({interaction.user.id})"), ("Reason", reason[:200])])


# --- Welcome / goodbye messages ----------------------------------------------

welcome_group = app_commands.Group(name="welcome", description="Configure member-join messages")


def _validate_template(message: str) -> str | None:
    """Returns an error string if the template has a bad placeholder, else None."""
    try:
        message.format(member="x", server="y")
        return None
    except (KeyError, IndexError, ValueError) as e:
        return (
            f"That message template isn't valid ({e}). Only `{{member}}` and `{{server}}` "
            f"are supported as placeholders — check for typos or stray `{{`/`}}`."
        )


@welcome_group.command(name="set", description="Set the welcome channel/message")
@app_commands.describe(channel="Channel to post welcomes in", message="Use {member} and {server} as placeholders")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcome_set(interaction: discord.Interaction, channel: discord.TextChannel,
                       message: app_commands.Range[str, 1, 800] = "🐾 Welcome {member} to {server}! Glad you're here."):
    error = _validate_template(message)
    if error:
        return await interaction.response.send_message(error, ephemeral=True)
    welcome_config[interaction.guild.id] = {"channel_id": channel.id, "message": message}
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Welcome messages will post in {channel.mention}.")
    await send_log(interaction.guild.id, title="👋 Welcome configuration changed", interaction=interaction, category="setup",
                   fields=[("Channel", channel.mention), ("Message", message[:900])])


@welcome_group.command(name="disable", description="Turn off welcome messages")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcome_disable(interaction: discord.Interaction):
    welcome_config.pop(interaction.guild.id, None)
    await bd_save_data()
    await interaction.response.send_message("🐾 Welcome messages turned off.")
    await send_log(interaction.guild.id, title="👋 Welcome messages disabled", interaction=interaction, category="setup")


goodbye_group = app_commands.Group(name="goodbye", description="Configure member-leave messages")


@goodbye_group.command(name="set", description="Set the goodbye channel/message")
@app_commands.describe(channel="Channel to post goodbyes in", message="Use {member} and {server} as placeholders")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def goodbye_set(interaction: discord.Interaction, channel: discord.TextChannel,
                       message: app_commands.Range[str, 1, 800] = "🐾 {member} has left {server}. We'll miss you!"):
    error = _validate_template(message)
    if error:
        return await interaction.response.send_message(error, ephemeral=True)
    goodbye_config[interaction.guild.id] = {"channel_id": channel.id, "message": message}
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Goodbye messages will post in {channel.mention}.")
    await send_log(interaction.guild.id, title="🚪 Goodbye configuration changed", interaction=interaction, category="setup",
                   fields=[("Channel", channel.mention), ("Message", message[:900])])


@goodbye_group.command(name="disable", description="Turn off goodbye messages")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def goodbye_disable(interaction: discord.Interaction):
    goodbye_config.pop(interaction.guild.id, None)
    await bd_save_data()
    await interaction.response.send_message("🐾 Goodbye messages turned off.")
    await send_log(interaction.guild.id, title="🚪 Goodbye messages disabled", interaction=interaction, category="setup")


# --- Reaction roles (self-assignable, via button) ----------------------------

class ReactionRoleView(discord.ui.View):
    """timeout=None + a static custom_id makes this a persistent view: it keeps
    working across restarts as long as bot.add_view() is called again for the
    same role_id on startup (done in on_ready, from reaction_role_ids)."""

    def __init__(self, role_id: int, label: str = "Toggle Role 🐾"):
        super().__init__(timeout=None)
        self.role_id = role_id
        button = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary, custom_id=f"rr:{role_id}")
        button.callback = self.toggle
        self.add_item(button)

    async def toggle(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            return await interaction.response.send_message("That role no longer exists.", ephemeral=True)
        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Reaction role toggle")
                await interaction.response.send_message(f"➖ Removed **{role.name}**.", ephemeral=True)
                await send_log(interaction.guild.id, title="🏷️ Self-assign role removed", category="roles",
                               fields=[("Member", f"{member} ({member.id})"), ("Role", f"{role.name} ({role.id})")])
            else:
                await member.add_roles(role, reason="Reaction role toggle")
                await interaction.response.send_message(f"➕ Added **{role.name}**!", ephemeral=True)
                await send_log(interaction.guild.id, title="🏷️ Self-assign role added", category="roles",
                               fields=[("Member", f"{member} ({member.id})"), ("Role", f"{role.name} ({role.id})")])
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to manage that role — check my role position.", ephemeral=True
            )


reactionrole_group = app_commands.Group(name="reactionrole", description="Self-assignable roles via a button")


@reactionrole_group.command(name="create", description="Post a button members can click to toggle a role")
@app_commands.describe(role="The role to toggle", label="Button text", description="Message shown above the button")
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def reactionrole_create(interaction: discord.Interaction, role: discord.Role,
                               label: str = "Toggle Role 🐾", description: str = None):
    if role >= interaction.guild.me.top_role:
        return await interaction.response.send_message(
            "I can't manage a role higher than or equal to my own top role — move my role above it first.",
            ephemeral=True,
        )
    embed = discord.Embed(
        title="🐾 Self-Assignable Role",
        description=description or f"Click below to toggle **{role.name}**.",
        color=0xFFB02E,
    )
    view = ReactionRoleView(role.id, label)
    await interaction.response.send_message(embed=embed, view=view)
    reaction_role_ids.add(role.id)
    await bd_save_data()
    bot.add_view(view)  # re-register for persistence in case this process restarts
    await send_log(interaction.guild.id, title="🏷️ Reaction role created", interaction=interaction, category="roles",
                   fields=[("Role", f"{role.name} ({role.id})"), ("Button label", label[:80])])


@reactionrole_group.command(name="remove", description="Stop a role from being self-assignable")
@app_commands.describe(role="The role to stop tracking")
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guild_only()
async def reactionrole_remove(interaction: discord.Interaction, role: discord.Role):
    reaction_role_ids.discard(role.id)
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 **{role.name}** is no longer tracked as self-assignable. (Existing buttons for it stop working "
        f"after the next restart; this doesn't delete the message.)",
        ephemeral=True,
    )
    await send_log(interaction.guild.id, title="🏷️ Reaction role removed", interaction=interaction, category="roles",
                   fields=[("Role", f"{role.name} ({role.id})")])


# --- Auto-moderation -----------------------------------------------------------

DEFAULT_AUTOMOD = {"words": [], "spam": False, "mentions": False, "invites": False, "mention_threshold": 5}
_INVITE_RE = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)\S+", re.IGNORECASE)


def get_automod(guild_id: int) -> dict:
    return automod_config.setdefault(guild_id, dict(DEFAULT_AUTOMOD))


async def _automod_strike(message: discord.Message, reason: str):
    try:
        await message.delete()
    except discord.HTTPException:
        pass
    count = add_warning(
        message.guild.id, message.author.id, f"[Auto-mod] {reason}",
        bot.user if bot.user else message.author,
    )
    case_id = next_case(message.guild.id)
    await bd_save_data()
    try:
        note = await message.channel.send(
            f"🐾 {message.author.mention}, that got removed for {reason}. Warning #{count} logged.",
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        await asyncio.sleep(6)
        await note.delete()
    except discord.HTTPException:
        pass
    await send_log(
        message.guild.id, title="🚨 Auto-mod action", color=discord.Color.red(),
        fields=[("Case", f"#{case_id}"), ("Member", f"{message.author} ({message.author.id})"), ("Reason", reason),
                ("Channel", message.channel.mention)],
    )


async def run_automod(message: discord.Message) -> bool:
    """Returns True if the message was removed (caller should stop processing it)."""
    if message.author.guild_permissions.manage_messages:
        return False  # mods bypass auto-mod
    cfg = automod_config.get(message.guild.id)
    if not cfg:
        return False

    if cfg.get("invites") and _INVITE_RE.search(message.content):
        await _automod_strike(message, "posting a Discord invite link")
        return True

    content_lower = message.content.lower()
    for w in cfg.get("words", []):
        if w and w.lower() in content_lower:
            await _automod_strike(message, "using a banned word")
            return True

    if cfg.get("mentions") and (len(message.mentions) + len(message.role_mentions)) >= cfg.get("mention_threshold", 5):
        await _automod_strike(message, "mass-mentioning members/roles")
        return True

    if cfg.get("spam"):
        key = (message.guild.id, message.author.id)
        dq = spam_tracker[key]
        dq.append(time.monotonic())
        if len(dq) == dq.maxlen and (dq[-1] - dq[0]) < 5:  # 6 msgs within 5s
            await _automod_strike(message, "spamming messages")
            return True

    return False


automod_group = app_commands.Group(name="automod", description="Configure auto-moderation")
automod_word_group = app_commands.Group(name="word", description="Manage banned words", parent=automod_group)


@automod_word_group.command(name="add", description="Add a banned word/phrase")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_word_add(interaction: discord.Interaction, word: app_commands.Range[str, 1, 100]):
    cfg = get_automod(interaction.guild.id)
    changed = word.lower() not in (w.lower() for w in cfg["words"])
    if changed:
        cfg["words"].append(word)
        await bd_save_data()
    await interaction.response.send_message(f"🐾 Added `{word}` to the banned word list.", ephemeral=True)
    await send_log(interaction.guild.id, title="🛡️ AutoMod banned word added", interaction=interaction, category="moderation",
                   fields=[("Word/phrase", word[:300]), ("Changed", str(changed))])


@automod_word_group.command(name="remove", description="Remove a banned word/phrase")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_word_remove(interaction: discord.Interaction, word: app_commands.Range[str, 1, 100]):
    cfg = get_automod(interaction.guild.id)
    before = len(cfg["words"])
    cfg["words"] = [w for w in cfg["words"] if w.lower() != word.lower()]
    removed = before - len(cfg["words"])
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Removed `{word}` from the banned word list.", ephemeral=True)
    await send_log(interaction.guild.id, title="🛡️ AutoMod banned word removed", interaction=interaction, category="moderation",
                   fields=[("Word/phrase", word[:300]), ("Removed", str(removed))])


@automod_word_group.command(name="list", description="List banned words")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_word_list(interaction: discord.Interaction):
    words = get_automod(interaction.guild.id)["words"]
    await interaction.response.send_message(
        "Banned words: " + (", ".join(f"`{w}`" for w in words) if words else "*(none set)*"), ephemeral=True
    )


@automod_group.command(name="spam", description="Toggle spam detection (rapid repeated messages)")
@app_commands.describe(enabled="On/off")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_spam(interaction: discord.Interaction, enabled: bool):
    get_automod(interaction.guild.id)["spam"] = enabled
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Spam detection turned **{'on' if enabled else 'off'}**.")
    await send_log(interaction.guild.id, title="🛡️ AutoMod spam setting changed", interaction=interaction, category="moderation", fields=[("Enabled", str(enabled))])


@automod_group.command(name="mentions", description="Toggle mass-mention detection")
@app_commands.describe(enabled="On/off", threshold="Mentions in one message that triggers it (default 5)")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_mentions(interaction: discord.Interaction, enabled: bool, threshold: int = 5):
    cfg = get_automod(interaction.guild.id)
    cfg["mentions"] = enabled
    cfg["mention_threshold"] = threshold
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 Mass-mention detection turned **{'on' if enabled else 'off'}** (threshold {threshold})."
    )
    await send_log(interaction.guild.id, title="🛡️ AutoMod mention setting changed", interaction=interaction, category="moderation",
                   fields=[("Enabled", str(enabled)), ("Threshold", str(threshold))])


@automod_group.command(name="invites", description="Toggle auto-deleting Discord invite links")
@app_commands.describe(enabled="On/off")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_invites(interaction: discord.Interaction, enabled: bool):
    get_automod(interaction.guild.id)["invites"] = enabled
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Invite-link filter turned **{'on' if enabled else 'off'}**.")
    await send_log(interaction.guild.id, title="🛡️ AutoMod invite filter changed", interaction=interaction, category="moderation", fields=[("Enabled", str(enabled))])


# --- Temp-ban ------------------------------------------------------------------

@bot.tree.command(name="tempban", description="Temporarily ban a member; auto-unbanned after the duration")
@app_commands.describe(member="Who to ban", duration_hours="Hours until auto-unban", reason="Why")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
@app_commands.guild_only()
async def tempban(interaction: discord.Interaction, member: discord.Member, duration_hours: float,
                   reason: app_commands.Range[str, 1, 300] = "No reason given"):
    unban_at = time.time() + duration_hours * 3600
    await member.ban(reason=f"Tempban by {interaction.user}: {reason}")
    temp_bans[(interaction.guild.id, member.id)] = unban_at
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 {member.mention} temp-banned for **{duration_hours}h**. Reason: {reason}",
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await send_log(
        interaction.guild.id, title="⏳ Member temp-banned", color=discord.Color.red(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Duration", f"{duration_hours}h"), ("Reason", reason)],
    )


@tasks.loop(minutes=5)
async def check_tempbans():
    now = time.time()
    due = [key for key, unban_at in temp_bans.items() if unban_at <= now]
    for guild_id, user_id in due:
        guild = bot.get_guild(guild_id)
        if guild:
            try:
                await guild.unban(discord.Object(id=user_id), reason="Temp-ban expired")
                await send_log(
                    guild_id, title="⏳ Temp-ban expired — member unbanned", color=discord.Color.green(),
                    fields=[("User ID", str(user_id))],
                )
            except discord.HTTPException:
                pass
        temp_bans.pop((guild_id, user_id), None)
    if due:
        await bd_save_data()


# --- Leveling / XP --------------------------------------------------------------

def level_from_xp(xp: int) -> int:
    # Inverse of total_xp_for_level's quadratic (25*n^2 + 75*n <= xp).
    n = (-75 + math.sqrt(5625 + 100 * xp)) / 50
    return max(0, int(n))


def total_xp_for_level(level: int) -> int:
    return 25 * level * level + 75 * level


async def sync_level_roles(member: discord.Member, level: int) -> list[str]:
    """Give `member` every level role they've earned but don't have yet. Runs on
    each XP award (not just level-ups), so roles added later still reach people
    who are already past that level. Returns the names of roles newly given."""
    cfg = level_roles.get(member.guild.id)
    if not cfg:
        return []
    have = {r.id for r in member.roles}
    top = member.guild.me.top_role
    to_add = []
    for lvl, rid in cfg.items():
        if lvl <= level and rid not in have:
            role = member.guild.get_role(rid)
            if role and not role.managed and role < top:
                to_add.append(role)
    if not to_add:
        return []
    try:
        await member.add_roles(*to_add, reason=f"Reached level {level}")
    except discord.HTTPException:
        return []
    return [r.name for r in to_add]


async def award_xp(message: discord.Message):
    key = (message.guild.id, message.author.id)
    now = time.monotonic()
    if now - xp_cooldowns.get(key, 0) < 60:
        return
    xp_cooldowns[key] = now
    old_xp = xp_data.get(key, 0)
    old_level = level_from_xp(old_xp)
    new_xp = old_xp + random.randint(15, 25)
    xp_data[key] = new_xp
    new_level = level_from_xp(new_xp)
    gained = await sync_level_roles(message.author, new_level)
    await send_log(message.guild.id, title="📈 XP changed", category="levels",
                   fields=[("User", f"{message.author} ({message.author.id})"), ("XP before", str(old_xp)),
                           ("XP gained", str(new_xp - old_xp)), ("XP after", str(new_xp)),
                           ("Level", f"{old_level} → {new_level}"), ("New level roles", ", ".join(gained) if gained else "None")])
    if new_level > old_level:
        text = f"🐾 {message.author.mention} just leveled up to **Level {new_level}**!"
        if gained:
            text += f" New role{'s' if len(gained) > 1 else ''}: **{', '.join(gained)}**"
        reward_levels = [lvl for lvl, amount in ECONOMY_LEVEL_REWARDS.items() if old_level < lvl <= new_level and not economy_level_reward_claimed(message.guild.id, message.author.id, lvl)]
        reward_total = sum(ECONOMY_LEVEL_REWARDS[lvl] for lvl in reward_levels)
        if reward_total:
            economy_balances[(message.guild.id, message.author.id)] = economy_balance(message.guild.id, message.author.id) + reward_total
            for lvl in reward_levels:
                mark_economy_level_reward_claimed(message.guild.id, message.author.id, lvl)
            await economy_log(message.guild.id, title="🏆 Level Catnip reward", fields=[("User", f"{message.author} ({message.author.id})"), ("Levels", ", ".join(map(str, reward_levels))), ("Reward", f"+{reward_total:,} Catnip")])
            text += f"\n🌿 Level reward: **+{reward_total:,} Catnip**!"
            await bd_save_data()
        try:
            await message.channel.send(
                text,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False),
            )
        except discord.HTTPException:
            pass


@bot.tree.command(name="rank", description="Show your (or someone's) level and XP")
@app_commands.describe(member="Who to check (defaults to you)")
@app_commands.guild_only()
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    xp = xp_data.get((interaction.guild.id, member.id), 0)
    level = level_from_xp(xp)
    this_level_xp = total_xp_for_level(level)
    next_level_xp = total_xp_for_level(level + 1)
    embed = discord.Embed(title=f"🐾 {member.display_name}'s Rank", color=0xFFB02E)
    embed.add_field(name="Level", value=str(level), inline=True)
    embed.add_field(name="Total XP", value=str(xp), inline=True)
    embed.add_field(name="Progress", value=f"{xp - this_level_xp}/{next_level_xp - this_level_xp} XP to next level", inline=True)
    reward = ECONOMY_LEVEL_REWARDS.get(level)
    if reward:
        embed.add_field(name="🌿 Level reward", value=f"+{reward:,} Catnip at this level", inline=True)
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="leaderboard", description="Show the top 10 members by XP in this server")
@app_commands.guild_only()
async def leaderboard(interaction: discord.Interaction):
    entries = sorted(
        ((uid, xp) for (gid, uid), xp in xp_data.items() if gid == interaction.guild.id),
        key=lambda e: e[1], reverse=True,
    )[:10]
    if not entries:
        return await interaction.response.send_message("No one has earned XP yet. 🐾", ephemeral=True)
    lines = []
    for i, (uid, xp) in enumerate(entries, 1):
        member = interaction.guild.get_member(uid)
        name = member.display_name if member else f"User {uid}"
        lines.append(f"**#{i}** {name} — Level {level_from_xp(xp)} ({xp} XP)")
    embed = discord.Embed(title="🏆 XP Leaderboard", description="\n".join(lines), color=0xFEE75C)
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


# --- Level roles ----------------------------------------------------------------

levelrole_group = app_commands.Group(name="levelrole", description="Give roles automatically at certain levels")


@levelrole_group.command(name="add", description="Give a role automatically when members reach a level")
@app_commands.describe(level="Level that unlocks the role", role="Role to give")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def levelrole_add(interaction: discord.Interaction, level: int, role: discord.Role):
    if role.is_default() or role.managed:
        return await interaction.response.send_message("That role can't be assigned by a bot.", ephemeral=True)
    if role >= interaction.guild.me.top_role:
        return await interaction.response.send_message(
            "That role is above my highest role, so I can't hand it out. Move my role higher in Server Settings → Roles.",
            ephemeral=True,
        )
    level_roles.setdefault(interaction.guild.id, {})[level] = role.id
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 Members will get **{role.name}** at **Level {level}**. "
        f"Anyone already past that level gets it the next time they earn XP.",
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await send_log(
        interaction.guild.id, title="🎖️ Level role added", color=discord.Color.green(), interaction=interaction,
        fields=[("Level", str(level)), ("Role", role.name)],
    )


@levelrole_group.command(name="remove", description="Stop giving a role at a level (members keep roles they already have)")
@app_commands.describe(level="The level to remove the reward from")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelrole_remove(interaction: discord.Interaction, level: int):
    cfg = level_roles.get(interaction.guild.id, {})
    if cfg.pop(level, None) is None:
        return await interaction.response.send_message(f"No level role is set for level {level}.", ephemeral=True)
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Removed the Level {level} reward. Members keep roles they already earned.")
    await send_log(
        interaction.guild.id, title="🎖️ Level role removed", color=discord.Color.orange(), interaction=interaction,
        fields=[("Level", str(level))],
    )


@levelrole_group.command(name="list", description="Show this server's level roles")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelrole_list(interaction: discord.Interaction):
    cfg = level_roles.get(interaction.guild.id, {})
    if not cfg:
        return await interaction.response.send_message("No level roles set. Add one with `/levelrole add`.", ephemeral=True)
    lines = []
    for lvl in sorted(cfg):
        role = interaction.guild.get_role(cfg[lvl])
        lines.append(f"**Level {lvl}** → {role.name if role else '(deleted role)'}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


# --- Standalone giveaways (persistent — survive restarts) --------------------------
# State lives in active_giveaways (saved with everything else); the Enter button
# is a persistent view matched by custom_id and looked up by message ID, so it
# keeps working after a restart, and check_timers ends giveaways on schedule.

def _giveaway_embed(gw: dict, winner_ids: list[int] | None = None) -> discord.Embed:
    if winner_ids is None:
        embed = discord.Embed(
            title="🎉 Giveaway!", color=0xFEE75C,
            description=f"**Prize:** {gw['prize']}\n**Winners:** {gw['winners']}\n"
                        f"Ends <t:{int(gw['ends_at'])}:R>\nHosted by <@{gw['host_id']}>",
        )
    else:
        won = " ".join(f"<@{u}>" for u in winner_ids) if winner_ids else "No one entered 🐾"
        embed = discord.Embed(
            title="🎉 Giveaway ended", color=0x99AAB5,
            description=f"**Prize:** {gw['prize']}\n**Winner{'s' if len(winner_ids) > 1 else ''}:** {won}\n"
                        f"Hosted by <@{gw['host_id']}>",
        )
    return embed


class GiveawayView(discord.ui.View):
    def __init__(self, disabled: bool = False):
        super().__init__(timeout=None)  # persistent: registered on startup via bot.add_view
        btn = discord.ui.Button(label="🎉 Enter", style=discord.ButtonStyle.success,
                                custom_id="giveaway:enter", disabled=disabled)
        btn.callback = self._enter
        self.add_item(btn)

    async def _enter(self, interaction: discord.Interaction):
        gw = active_giveaways.get(interaction.message.id)
        if gw is None:
            return await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
        uid = interaction.user.id
        if uid in gw["entrants"]:
            gw["entrants"].remove(uid)
            text = "You left the giveaway."
        else:
            gw["entrants"].append(uid)
            text = "🎉 You're entered! Click again to leave."
        await interaction.response.send_message(text, ephemeral=True)
        await bd_save_data()  # after responding: Discord only gives us 3s to answer
        guild_id = gw.get("guild_id")
        if guild_id:
            await send_log(int(guild_id), title="🎉 Giveaway entry changed", category="community",
                           fields=[("User", f"{interaction.user} ({interaction.user.id})"),
                                   ("Giveaway message", str(interaction.message.id)),
                                   ("Action", "Entered" if uid in gw["entrants"] else "Left"),
                                   ("Entrants", str(len(gw["entrants"]))),
                                   ("Prize", str(gw.get("prize", "Giveaway"))[:900])])


async def finish_giveaway(mid: int):
    gw = active_giveaways.pop(mid, None)
    if gw is None:
        return
    await bd_save_data()
    channel = bot.get_channel(gw["channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(mid)
    except discord.HTTPException:
        return  # message was deleted — nothing to update
    entrants = list(dict.fromkeys(int(uid) for uid in gw.get("entrants", [])))
    bonus_roles = gw.get("bonus_roles", {})
    tickets = []
    guild = bot.get_guild(int(gw.get("guild_id", 0)))
    for uid in entrants:
        member = guild.get_member(uid) if guild else None
        extra = 0
        if member:
            member_role_ids = {str(role.id) for role in member.roles}
            extra = sum(max(0, min(20, int(count))) for role_id, count in bonus_roles.items() if str(role_id) in member_role_ids)
        tickets.extend([uid] * (1 + min(extra, 100)))
    winner_ids = []
    while tickets and len(winner_ids) < min(int(gw.get("winners", 1)), len(entrants)):
        winner = random.choice(tickets)
        winner_ids.append(winner)
        tickets = [uid for uid in tickets if uid != winner]
    try:
        await message.edit(embed=_giveaway_embed(gw, winner_ids), view=GiveawayView(disabled=True))
    except discord.HTTPException:
        pass
    if winner_ids:
        text = f"🎉 Congrats {' '.join(f'<@{u}>' for u in winner_ids)}! You won **{gw['prize']}**!"
    else:
        text = "🐾 No one entered the giveaway — no winners this time."
    await send_log(int(gw.get("guild_id", 0)), title="🏁 Giveaway finished", category="community",
                   fields=[("Message", str(mid)), ("Prize", str(gw.get("prize", "Giveaway"))[:900]),
                           ("Entrants", str(len(entrants))), ("Winners", ", ".join(str(x) for x in winner_ids) if winner_ids else "None")])
    try:
        await message.reply(text, allowed_mentions=discord.AllowedMentions(users=True))
    except discord.HTTPException:
        pass



async def cancel_giveaway(mid: int):
    """Cancel a giveaway without selecting winners."""
    gw = active_giveaways.pop(mid, None)
    if gw is None:
        return False
    await bd_save_data()
    channel = bot.get_channel(int(gw.get("channel_id", 0)))
    if channel is not None:
        try:
            message = await channel.fetch_message(mid)
            embed = discord.Embed(title="🎉 Giveaway cancelled", description=f"**Prize:** {gw.get('prize', 'Giveaway')}\nThis giveaway was cancelled by a server manager.", color=0x99AAB5)
            await message.edit(embed=embed, view=GiveawayView(disabled=True))
        except discord.HTTPException:
            pass
    await send_log(int(gw.get("guild_id", 0)), title="🚫 Giveaway cancelled", category="community",
                   fields=[("Message", str(mid)), ("Prize", str(gw.get("prize", "Giveaway"))[:900]),
                           ("Entrants", str(len(gw.get("entrants", []))))])
    return True

giveaway_group = app_commands.Group(name="giveaway", description="Run a simple prize giveaway")


@giveaway_group.command(name="start", description="Start a giveaway")
@app_commands.describe(duration_minutes="How long the giveaway runs", winners="Number of winners", prize="What's being given away")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def giveaway_start(interaction: discord.Interaction, duration_minutes: int,
                          winners: int, prize: app_commands.Range[str, 1, 200]):
    gw = {
        "guild_id": interaction.guild.id, "channel_id": interaction.channel.id, "host_id": interaction.user.id,
        "winners": winners, "prize": prize, "ends_at": time.time() + duration_minutes * 60, "entrants": [],
    }
    await interaction.response.send_message(embed=_giveaway_embed(gw), view=GiveawayView())
    msg = await interaction.original_response()
    active_giveaways[msg.id] = gw
    await bd_save_data()
    await send_log(interaction.guild.id, title="🎉 Giveaway started", interaction=interaction, category="community",
                   fields=[("Message", str(msg.id)), ("Prize", prize), ("Duration", f"{duration_minutes} minute(s)"),
                           ("Winners", str(winners))])


@giveaway_group.command(name="end", description="End a giveaway early and pick winners now")
@app_commands.describe(message_id="The ID of the giveaway message")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def giveaway_end(interaction: discord.Interaction, message_id: str):
    try:
        mid = int(message_id)
    except ValueError:
        return await interaction.response.send_message("That doesn't look like a valid message ID.", ephemeral=True)
    gw = active_giveaways.get(mid)
    if not gw or gw["guild_id"] != interaction.guild.id:
        return await interaction.response.send_message("No active giveaway with that message ID.", ephemeral=True)
    await interaction.response.send_message("Ending the giveaway now...", ephemeral=True)
    await finish_giveaway(mid)


# --- Polls (persistent — survive restarts) ---------------------------------------

def _poll_embed(poll: dict, ended: bool = False) -> discord.Embed:
    options, votes = poll["options"], poll["votes"]
    counts = [0] * len(options)
    for idx in votes.values():
        if 0 <= idx < len(options):
            counts[idx] += 1
    total = sum(counts)
    lines = []
    for i, (opt, c) in enumerate(zip(options, counts), 1):
        pct = c / total if total else 0
        filled = round(pct * 10)
        lines.append(f"**{i}. {opt}**\n{'█' * filled}{'░' * (10 - filled)} {c} vote(s) ({pct:.0%})")
    status = "Poll ended" if ended else f"Ends <t:{int(poll['ends_at'])}:R> · tap the same option again to remove your vote"
    embed = discord.Embed(
        title=f"📊 {poll['question']}", description="\n\n".join(lines) + f"\n\n{status}",
        color=0x99AAB5 if ended else 0xFFB02E,
    )
    embed.set_footer(text=f"{total} vote(s) · Started by {poll['host_name']}")
    return embed


class PollView(discord.ui.View):
    def __init__(self, options: list[str] | None = None, disabled: bool = False):
        super().__init__(timeout=None)  # persistent: registered on startup via bot.add_view
        for i in range(len(options) if options else 4):
            label = f"{i + 1}. {options[i]}"[:80] if options else f"Option {i + 1}"
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary,
                                    custom_id=f"poll:{i}", disabled=disabled)
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    @staticmethod
    def _make_callback(idx: int):
        async def callback(interaction: discord.Interaction):
            poll = active_polls.get(interaction.message.id)
            if poll is None:
                return await interaction.response.send_message("This poll has ended.", ephemeral=True)
            if idx >= len(poll["options"]):
                return await interaction.response.send_message("That option doesn't exist.", ephemeral=True)
            uid = str(interaction.user.id)
            if poll["votes"].get(uid) == idx:
                del poll["votes"][uid]  # tapping your current choice again removes your vote
            else:
                poll["votes"][uid] = idx
            await interaction.response.edit_message(embed=_poll_embed(poll))
            await bd_save_data()  # after responding: Discord only gives us 3s to answer
            await send_log(int(poll.get("guild_id", 0)), title="📊 Poll vote changed", category="community",
                           fields=[("User", f"{interaction.user} ({interaction.user.id})"),
                                   ("Poll message", str(interaction.message.id)),
                                   ("Choice", poll["options"][idx]), ("Total votes", str(len(poll["votes"])))])
        return callback


async def finish_poll(mid: int):
    poll = active_polls.pop(mid, None)
    if poll is None:
        return
    await bd_save_data()
    channel = bot.get_channel(poll["channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(mid)
    except discord.HTTPException:
        return
    try:
        await message.edit(embed=_poll_embed(poll, ended=True), view=PollView(poll["options"], disabled=True))
    except discord.HTTPException:
        pass
    counts = [0] * len(poll["options"])
    for idx in poll["votes"].values():
        if 0 <= idx < len(counts):
            counts[idx] += 1
    if not any(counts):
        text = "📊 The poll ended with no votes."
    else:
        top = max(counts)
        winners = [poll["options"][i] for i, c in enumerate(counts) if c == top]
        text = (f"📊 Poll ended — **{winners[0]}** wins with {top} vote(s)!" if len(winners) == 1
                else f"📊 Poll ended in a tie between **{' & '.join(winners)}** ({top} vote(s) each).")
    try:
        await message.reply(text, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass
    await send_log(int(poll.get("guild_id", 0)), title="🏁 Poll finished", category="community",
                   fields=[("Message", str(mid)), ("Question", str(poll.get("question", "Poll"))[:900]),
                           ("Votes", str(sum(counts))), ("Result", text[:900])])


@bot.tree.command(name="poll", description="Start a poll with 2-4 options")
@app_commands.describe(
    question="What are you asking?", option1="First option", option2="Second option",
    option3="Third option (optional)", option4="Fourth option (optional)",
    duration_minutes="How long the poll stays open (default 24 hours, max 7 days)",
)
@app_commands.guild_only()
async def poll(interaction: discord.Interaction, question: app_commands.Range[str, 1, 200],
               option1: app_commands.Range[str, 1, 60], option2: app_commands.Range[str, 1, 60],
               option3: app_commands.Range[str, 1, 60] = None, option4: app_commands.Range[str, 1, 60] = None,
               duration_minutes: int = 1440):
    options = [o for o in (option1, option2, option3, option4) if o]
    p = {
        "guild_id": interaction.guild.id, "channel_id": interaction.channel.id,
        "host_id": interaction.user.id, "host_name": interaction.user.display_name,
        "question": question, "options": options, "votes": {},
        "ends_at": time.time() + duration_minutes * 60,
    }
    await interaction.response.send_message(embed=_poll_embed(p), view=PollView(options),
                                            allowed_mentions=discord.AllowedMentions.none())
    msg = await interaction.original_response()
    active_polls[msg.id] = p
    await bd_save_data()
    await send_log(interaction.guild.id, title="📊 Poll started", interaction=interaction, category="community",
                   fields=[("Message", str(msg.id)), ("Question", question), ("Options", " | ".join(options)),
                           ("Duration", f"{duration_minutes} minute(s)")])


@tasks.loop(seconds=30)
async def check_timers():
    """Ends any giveaway/poll whose time is up. Runs off saved timestamps, so
    anything that came due while the bot was offline is handled on startup."""
    now = time.time()
    for mid, gw in list(active_giveaways.items()):
        if gw["ends_at"] <= now:
            try:
                await finish_giveaway(mid)
            except Exception as e:
                log.error(f"Failed to finish giveaway {mid}: {e}")
    for mid, p in list(active_polls.items()):
        if p["ends_at"] <= now:
            try:
                await finish_poll(mid)
            except Exception as e:
                log.error(f"Failed to finish poll {mid}: {e}")


# --- Anti-raid (join-rate spike alerts) -----------------------------------------

DEFAULT_ANTIRAID = {"enabled": False, "threshold": 5, "window": 10}


def get_antiraid(guild_id: int) -> dict:
    return antiraid_config.setdefault(guild_id, dict(DEFAULT_ANTIRAID))


async def check_antiraid(member: discord.Member):
    cfg = antiraid_config.get(member.guild.id)
    if not cfg or not cfg.get("enabled"):
        return
    dq = join_log[member.guild.id]
    now = time.monotonic()
    dq.append(now)
    recent = sum(1 for t in dq if now - t <= cfg.get("window", 10))
    if recent >= cfg.get("threshold", 5):
        await send_log(
            member.guild.id, title="🚨 Possible raid detected", color=discord.Color.red(),
            fields=[("Joins", f"{recent} in {cfg.get('window', 10)}s"), ("Latest member", f"{member} ({member.id})")],
        )


antiraid_group = app_commands.Group(name="antiraid", description="Configure join-spike (raid) alerts")


@antiraid_group.command(name="enable", description="Turn on raid-join alerts to the log channel")
@app_commands.describe(threshold="Alert if this many joins happen...", window_seconds="...within this many seconds")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def antiraid_enable(interaction: discord.Interaction, threshold: int = 5, window_seconds: int = 10):
    cfg = get_antiraid(interaction.guild.id)
    cfg.update({"enabled": True, "threshold": threshold, "window": window_seconds})
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 Anti-raid alerts on: {threshold} joins within {window_seconds}s triggers a log-channel alert. "
        f"(This only alerts — it doesn't auto-kick or lock the server.)"
    )
    await send_log(interaction.guild.id, title="🚨 Anti-raid configuration changed", interaction=interaction, category="moderation",
                   fields=[("Enabled", "True"), ("Threshold", str(threshold)), ("Window", f"{window_seconds}s")])


@antiraid_group.command(name="disable", description="Turn off raid-join alerts")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def antiraid_disable(interaction: discord.Interaction):
    get_antiraid(interaction.guild.id)["enabled"] = False
    await bd_save_data()
    await interaction.response.send_message("🐾 Anti-raid alerts off.")
    await send_log(interaction.guild.id, title="🚨 Anti-raid disabled", interaction=interaction, category="moderation")


# --- Channel lock / unlock -------------------------------------------------------

@bot.tree.command(name="lock", description="Prevent @everyone from sending messages in a channel")
@app_commands.describe(channel="Channel to lock (defaults to this one)")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
@app_commands.guild_only()
async def lock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"Locked by {interaction.user}")
    await interaction.response.send_message(f"🔒 {channel.mention} locked.")
    await send_log(
        interaction.guild.id, title="🔒 Channel locked", color=discord.Color.red(), interaction=interaction,
        fields=[("Channel", channel.mention)],
    )


@bot.tree.command(name="unlock", description="Allow @everyone to send messages in a channel again")
@app_commands.describe(channel="Channel to unlock (defaults to this one)")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
@app_commands.guild_only()
async def unlock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None  # inherit
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"Unlocked by {interaction.user}")
    await interaction.response.send_message(f"🔓 {channel.mention} unlocked.")
    await send_log(
        interaction.guild.id, title="🔓 Channel unlocked", color=discord.Color.green(), interaction=interaction,
        fields=[("Channel", channel.mention)],
    )


# --- Mod information (reads the log channel live) --------------------------

_MODINFO_TITLES = {
    "⚠️ Member warned", "🚨 Auto-mod action", "👢 Member kicked", "🔨 Member banned",
    "🔓 Member unbanned", "🔇 Member muted", "🔊 Member unmuted", "⏳ Member temp-banned",
    "⏳ Temp-ban expired — member unbanned",
}


@bot.tree.command(name="modinfo", description="Mods only: a person's full moderation history, read from the log channel")
@app_commands.describe(user="Who to look up (works even if they've left or are banned)")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def modinfo(interaction: discord.Interaction, user: discord.User):
    channel = bot.get_channel(log_channels.get(interaction.guild.id, 0))
    if channel is None:
        return await interaction.response.send_message(
            "Set a log channel first with `/logchannel` — this command reads its history.", ephemeral=True
        )
    await interaction.response.defer(ephemeral=True)

    entries = []  # newest first (channel.history order)
    try:
        async for message in channel.history(limit=2000):
            for embed in message.embeds:
                if embed.title not in _MODINFO_TITLES:
                    continue
                fields = {f.name: f.value for f in embed.fields}
                m = _ID_IN_PARENS_RE.search(fields.get("Member", ""))
                target = int(m.group(1)) if m else (int(fields["User ID"]) if fields.get("User ID", "").isdigit() else None)
                if target != user.id:
                    continue
                footer_m = re.search(r"Run by (.+?) • #", embed.footer.text or "") if embed.footer else None
                extra = f" ({fields['Duration']})" if "Duration" in fields else ""
                entries.append({
                    "ts": embed.timestamp or message.created_at,
                    "case": fields.get("Case", "—"),
                    "title": embed.title,
                    "reason": (fields.get("Reason", "") + extra).strip(),
                    "by": footer_m.group(1) if footer_m else "system",
                })
    except discord.HTTPException as e:
        return await interaction.followup.send(f"Couldn't read the log channel: {e}", ephemeral=True)

    member = interaction.guild.get_member(user.id)
    stored_warns = len(warnings_data.get((interaction.guild.id, user.id), []))
    info = [f"**Account created:** {discord.utils.format_dt(user.created_at, 'D')}"]
    if member and member.joined_at:
        info.append(f"**Joined server:** {discord.utils.format_dt(member.joined_at, 'D')}")
    else:
        info.append("**In server:** No (left, kicked, or banned)")
    info.append(f"**Active warnings on file:** {stored_warns}")
    info.append(f"**Logged actions found:** {len(entries)}")

    lines, used = [], 0
    for e in entries:
        line = f"{discord.utils.format_dt(e['ts'], 'd')} **{e['case']}** {e['title']}"
        if e["reason"]:
            line += f" — {e['reason'][:120]}"
        line += f" · _{e['by']}_"
        if used + len(line) > 3000:
            lines.append(f"…and {len(entries) - len(lines)} older action(s) not shown.")
            break
        lines.append(line)
        used += len(line) + 1

    body = "\n".join(lines) if lines else "No logged moderation actions found for this person."
    embed = discord.Embed(
        title=f"🛡️ Mod information — {user}", description="\n".join(info) + "\n\n" + body,
        color=discord.Color.blurple(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Read live from the log channel (last 2000 messages). Actions logged before case IDs existed show —.")
    await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


# --- Health / status ---------------------------------------------------------

@bot.tree.command(name="ping", description="Check Cinnamon's Discord latency")
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(
        f"🏓 **Pong!** Discord latency: **{latency_ms} ms**",
        ephemeral=True,
    )


@bot.tree.command(name="botstatus", description="Show Cinnamon's current health and enabled systems")
@app_commands.guild_only()
async def botstatus(interaction: discord.Interaction):
    guild = interaction.guild
    hg_cog = bot.get_cog("HangryGamesCog")
    storage = await storage_status()
    embed = discord.Embed(title="🐾 Cinnamon status", color=discord.Color.blurple())
    embed.add_field(name="Discord latency", value=f"{round(bot.latency * 1000)} ms", inline=True)
    embed.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="Members here", value=str(guild.member_count or 0), inline=True)
    embed.add_field(name="AI channel", value="Enabled" if ai_channels.get(guild.id) else "Off", inline=True)
    embed.add_field(name="Auto-mod", value="Configured" if guild.id in automod_config else "Off", inline=True)
    embed.add_field(name="Anti-raid", value="Enabled" if antiraid_config.get(guild.id, {}).get("enabled") else "Off", inline=True)
    embed.add_field(name="XP / leveling", value="Active", inline=True)
    embed.add_field(name="Hangry Games", value="Ready" if hg_cog else "Starting", inline=True)
    embed.add_field(name="Storage", value=storage["backend"], inline=True)
    embed.set_footer(text="Use /help for commands. 🐾")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# Category-specific logging controls. Existing /logchannel remains the fallback.
categorylogs_group = app_commands.Group(name="categorylogs", description="Configure separate Cinnamon log channels")

@categorylogs_group.command(name="set", description="Set a category's log channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(category="Which Cinnamon category to log", channel="Text channel receiving its logs")
@app_commands.choices(category=[
    app_commands.Choice(name="Moderation", value="moderation"),
    app_commands.Choice(name="Economy", value="economy"),
    app_commands.Choice(name="AI", value="ai"),
    app_commands.Choice(name="Levels & XP", value="levels"),
    app_commands.Choice(name="Giveaways & Polls", value="community"),
    app_commands.Choice(name="Roles", value="roles"),
    app_commands.Choice(name="Server Setup", value="setup"),
    app_commands.Choice(name="General utilities", value="general"),
])
async def categorylogs_set(interaction: discord.Interaction, category: app_commands.Choice[str], channel: discord.TextChannel):
    category_log_channels.setdefault(interaction.guild.id, {})[category.value] = channel.id
    await secure_log_channel(channel)
    if category.value == "economy":
        economy_log_channels[interaction.guild.id] = channel.id
    if category.value == "moderation":
        log_channels[interaction.guild.id] = channel.id
    await bd_save_data()
    await interaction.response.send_message(f"✅ {category.name} logs will be sent to {channel.mention}.", ephemeral=True)
    await send_log(interaction.guild.id, title="⚙️ Category log channel updated", description=f"{category.name} logging configured.", fields=[("Category", category.value), ("Channel", channel.mention), ("Changed by", f"{interaction.user} ({interaction.user.id})")])

@categorylogs_group.command(name="disable", description="Disable a category-specific log channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.choices(category=[
    app_commands.Choice(name="Moderation", value="moderation"), app_commands.Choice(name="Economy", value="economy"),
    app_commands.Choice(name="AI", value="ai"), app_commands.Choice(name="Levels & XP", value="levels"),
    app_commands.Choice(name="Giveaways & Polls", value="community"), app_commands.Choice(name="Roles", value="roles"),
    app_commands.Choice(name="Server Setup", value="setup"), app_commands.Choice(name="General utilities", value="general"),
])
async def categorylogs_disable(interaction: discord.Interaction, category: app_commands.Choice[str]):
    removed = category_log_channels.get(interaction.guild.id, {}).get(category.value)
    if removed:
        await send_log(interaction.guild.id, title="⚙️ Category log channel disabled", interaction=interaction, category=category.value,
                       fields=[("Category", category.value), ("Previous channel ID", str(removed))])
    category_log_channels.get(interaction.guild.id, {}).pop(category.value, None)
    if category.value == "economy": economy_log_channels.pop(interaction.guild.id, None)
    if category.value == "moderation": log_channels.pop(interaction.guild.id, None)
    await bd_save_data()
    await interaction.response.send_message(f"Category-specific {category.name} logs {'disabled' if removed else 'were not configured'}. Existing general logs may still be used as fallback.", ephemeral=True)

bot.tree.add_command(categorylogs_group)


# --- Help + guided setup ------------------------------------------------------

async def _ensure_setup_channel(guild: discord.Guild, category: discord.CategoryChannel, name: str, topic: str):
    """Find or create one of Cinnamon's managed setup channels.

    The setup is deliberately idempotent: running /setup again reuses channels
    instead of creating duplicates.
    """
    existing = discord.utils.get(category.text_channels, name=name)
    is_log = name.endswith("-logs") or name in {"cinnamon-logs", "cinnamon-economy", "cinnamon-hangry"}
    overwrites = None
    if is_log and guild.me is not None:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, read_message_history=True),
        }
    if existing:
        if is_log and overwrites:
            await secure_log_channel(existing)
        return existing, False
    channel = await guild.create_text_channel(name=name, category=category, topic=topic, overwrites=overwrites, reason="Cinnamon guided server setup")
    return channel, True


def _command_path(command) -> str:
    parts = []
    current = command
    while current is not None:
        name = getattr(current, "name", None)
        if name:
            parts.append(name)
        current = getattr(current, "parent", None)
    return "/" + " ".join(reversed(parts))


def _all_leaf_commands() -> list:
    """Return every registered slash command, including commands inside groups."""
    leaves = []

    def walk(command):
        children = getattr(command, "commands", None) or []
        if children:
            for child in children:
                walk(child)
        else:
            leaves.append(command)

    for command in bot.tree.get_commands():
        walk(command)
    # Hangry Games is a GroupCog and should already be attached to the tree by
    # the time /help is used, but sorting here makes the output deterministic.
    return sorted(leaves, key=lambda c: _command_path(c).lower())


@bot.tree.command(name="setup", description="Guided first-time setup: create Cinnamon's channels and configure logging")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_channels=True, send_messages=True, embed_links=True)
async def setup_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)

    category = discord.utils.get(guild.categories, name="Cinnamon • Logs & Setup")
    created_category = False
    if category is None:
        category = await guild.create_category("Cinnamon • Logs & Setup", reason="Cinnamon guided server setup")
        created_category = True

    specs = [
        ("cinnamon-logs", "Cinnamon moderation, AutoMod, errors, warnings, and general logs."),
        ("cinnamon-economy", "Catnip economy transactions, balance changes, inventory, shop, and snapshots."),
        ("cinnamon-hangry", "Hangry Games starts, winners, cancellations, and recovery logs."),
        ("cinnamon-ai-logs", "Cinnamon AI command usage, settings, and service errors; not private conversation contents."),
        ("cinnamon-level-logs", "XP awards, level-ups, and level-role changes."),
        ("cinnamon-community-logs", "Giveaway and poll events."),
        ("cinnamon-role-logs", "Role management and reaction-role configuration events."),
        ("cinnamon-setup-logs", "Welcome/goodbye, setup, and logging configuration changes."),
        ("cinnamon-general-logs", "General information and utility command usage."),
        ("cinnamon-welcome", "Cinnamon's member welcome messages."),
        ("cinnamon-goodbye", "Cinnamon's member goodbye messages."),
        ("cinnamon-ai", "Cinnamon's always-on AI chat channel."),
    ]
    channels = {}
    created = []
    for name, topic in specs:
        channel, was_created = await _ensure_setup_channel(guild, category, name, topic)
        channels[name] = channel
        if was_created:
            created.append(channel.mention)

    # Configure the systems that have dedicated channel settings.
    log_channels[guild.id] = channels["cinnamon-logs"].id
    economy_log_channels[guild.id] = channels["cinnamon-economy"].id
    category_log_channels[guild.id] = {
        "moderation": channels["cinnamon-logs"].id,
        "economy": channels["cinnamon-economy"].id,
        "ai": channels["cinnamon-ai-logs"].id,
        "levels": channels["cinnamon-level-logs"].id,
        "community": channels["cinnamon-community-logs"].id,
        "roles": channels["cinnamon-role-logs"].id,
        "setup": channels["cinnamon-setup-logs"].id,
        "general": channels["cinnamon-general-logs"].id,
    }
    ai_channels[guild.id] = channels["cinnamon-ai"].id
    welcome_config[guild.id] = {
        "channel_id": channels["cinnamon-welcome"].id,
        "message": "🐾 Welcome {member} to **{server}**! Cinnamon hopes you brought snacks.",
    }
    goodbye_config[guild.id] = {
        "channel_id": channels["cinnamon-goodbye"].id,
        "message": "🐾 {member} left **{server}**. Cinnamon will miss the head pats!",
    }

    hg_cog = bot.get_cog("HangryGamesCog")
    if hg_cog:
        hg_cog.hg_log_channels[guild.id] = channels["cinnamon-hangry"].id
        hg_cog.log_enabled[guild.id] = True
        await hg_cog._save()

    await bd_save_data()
    await send_log(guild.id, title="⚙️ Cinnamon setup applied", category="setup",
                   fields=[("Main logs", channels["cinnamon-logs"].mention), ("Economy logs", channels["cinnamon-economy"].mention),
                           ("Hangry logs", channels["cinnamon-hangry"].mention), ("AI channel", channels["cinnamon-ai"].mention)])

    # Keep the setup message useful even if someone runs it again later.
    created_text = ", ".join(created) if created else "No channels needed to be created; the setup was already present."
    embed = discord.Embed(
        title="🐾 Cinnamon setup complete",
        description=(
            "I checked the server and configured the main Cinnamon systems. "
            "Running `/setup` again is safe and will reuse these channels.\n\n"
            f"**Created:** {created_text}"
        ),
        color=discord.Color.green(),
    )
    embed.add_field(name="🛡️ Main logs", value=channels["cinnamon-logs"].mention, inline=True)
    embed.add_field(name="🌿 Economy", value=channels["cinnamon-economy"].mention, inline=True)
    embed.add_field(name="🍔 Hangry Games", value=channels["cinnamon-hangry"].mention, inline=True)
    embed.add_field(name="🤖 AI logs", value=channels["cinnamon-ai-logs"].mention, inline=True)
    embed.add_field(name="🏅 Levels logs", value=channels["cinnamon-level-logs"].mention, inline=True)
    embed.add_field(name="🎉 Community logs", value=channels["cinnamon-community-logs"].mention, inline=True)
    embed.add_field(name="🏷️ Role logs", value=channels["cinnamon-role-logs"].mention, inline=True)
    embed.add_field(name="⚙️ Setup logs", value=channels["cinnamon-setup-logs"].mention, inline=True)
    embed.add_field(name="📌 General logs", value=channels["cinnamon-general-logs"].mention, inline=True)
    embed.add_field(name="👋 Welcome", value=channels["cinnamon-welcome"].mention, inline=True)
    embed.add_field(name="🚪 Goodbye", value=channels["cinnamon-goodbye"].mention, inline=True)
    embed.add_field(name="🐱 AI chat", value=channels["cinnamon-ai"].mention, inline=True)
    embed.add_field(
        name="Next steps",
        value=(
            "Use `/help` to see every command and what it does. "
            "Use `/economy snapshot` before a reset. "
            "Use `/economy restore-snapshot` after a reset if needed."
        ),
        inline=False,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="setupstatus", description="Check Cinnamon's configured channels and systems")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def setupstatus_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    hg_cog = bot.get_cog("HangryGamesCog")
    rows = [
        ("🛡️ Main logs", log_channels.get(guild.id)),
        ("🌿 Economy logs", economy_log_channels.get(guild.id)),
        ("🤖 AI logs", category_log_channels.get(guild.id, {}).get("ai")),
        ("🏅 Levels logs", category_log_channels.get(guild.id, {}).get("levels")),
        ("🎉 Community logs", category_log_channels.get(guild.id, {}).get("community")),
        ("🏷️ Role logs", category_log_channels.get(guild.id, {}).get("roles")),
        ("⚙️ Setup logs", category_log_channels.get(guild.id, {}).get("setup")),
        ("📌 General logs", category_log_channels.get(guild.id, {}).get("general")),
        ("🍔 Hangry logs", hg_cog.hg_log_channels.get(guild.id) if hg_cog else None),
        ("👋 Welcome", welcome_config.get(guild.id, {}).get("channel_id")),
        ("🚪 Goodbye", goodbye_config.get(guild.id, {}).get("channel_id")),
        ("🐱 AI channel", ai_channels.get(guild.id)),
    ]
    lines = []
    for label, channel_id in rows:
        channel = guild.get_channel(channel_id) if channel_id else None
        lines.append(f"{label}: {channel.mention if channel else '❌ Not configured'}")
    embed = discord.Embed(title="🐾 Cinnamon setup status", description="\n".join(lines), color=discord.Color.blurple())
    embed.add_field(name="AutoMod", value="Configured" if guild.id in automod_config else "Not configured", inline=True)
    embed.add_field(name="Anti-raid", value="Enabled" if antiraid_config.get(guild.id, {}).get("enabled") else "Off", inline=True)
    embed.add_field(name="Persistent storage", value=(await storage_status())["backend"], inline=True)
    embed.set_footer(text="Run /setup to create/configure the standard Cinnamon channels.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- Help ---------------------------------------------------------------------

_HELP_EVERYONE = (
    "`/pet` `/treat` `/nap` `/zoomies` — cat antics\n"
    "`/afk` — set an AFK note (auto-replies when you're pinged)\n"
    "`/rank` · `/leaderboard` — your level, and the top 10\n"
    "`/userinfo` · `/serverinfo` — info about a member or the server\n"
    "`/poll` — start a poll with 2–4 options\n"
    "`/ping` · `/botstatus` — check Cinnamon's health\n"
    "`/help` — this menu\n"
    "Chat with me any time by mentioning me or replying to me. 🐾"
)
_HELP_ECONOMY = (
    "`/economy balance` · `/economy inventory` — your Catnip and items\n"
    "`/economy daily` · `/economy work` · `?work` — earn Catnip\n"
    "`/economy shop` · `/economy buy` · `/economy iteminfo` — view, buy, and inspect items\n"
    "`/economy quest` · `/economy feed` — see quests and give Cinnamon items\n"
    "`/economy give` — give Catnip to another member\n"
    "`/collect` — collect income from your income roles\n"
    "`/economy leaderboard` — richest members\n"
)

_HELP_HANGRY = (
    "`/hangrygames new` — open a lobby (Start needs Manage Messages)\n"
    "`/hangrygames giveaway` — lobby with a prize and optional winner role\n"
    "`/hangrygames role` — start straight away with everyone in a role\n"
    "`/hangrygames stats` · `leaderboard` — wins, kills, and top winners\n"
    "`/hangrygames cancel` — stop the game or lobby in this channel"
)
_HELP_MODS = (
    "`/warn` · `/warnings` — warn someone / see their warnings\n"
    "`/kick` `/ban` `/tempban` `/unban`\n"
    "`/mute` · `/unmute` — timeouts\n"
    "`/modinfo` — someone's full mod history, read from the log channel\n"
    "`/purge` `/slowmode` `/lock` `/unlock` — channel tools\n"
    "`/role add` · `/reactionrole create` `remove` — roles\n"
    "`/aichannel` `/disableaichannel` `/disableai` `/enableai` — where I chat"
)
_HELP_ADMINS = (
    "`/logchannel` · `/disablelogchannel` — mod log\n"
    "`/datastatus check` `recover` · `/recall` — storage health and log recovery scan\n"
    "`/welcome` · `/goodbye` — `set` or `disable` join/leave messages\n"
    "`/automod` — `word add/remove/list`, `spam`, `mentions`, `invites`\n"
    "`/antiraid enable` `disable` — join-spike alerts\n"
    "`/levelrole add` `remove` `list` — roles at certain levels\n"
    "`/giveaway start` `end` — prize giveaways\n"
    "`/clearwarnings` · `/role add-all`\n"
    "`/hangrygames logchannel` `disablelogchannel` `log` — its own log channel\n"
    "`/economy logs` — choose the economy transaction log channel\n"
    "`/economy snapshot` — create a complete pre-reset backup\n"
    "`/economy restore-snapshot` — restore the latest backup from economy logs\n"
    "`/economy admin addcatnip` · `removecatnip` — admin balance controls\n"
    "`/economy income` — admin income-role management\n"
    "`/economy item-add` · `/economy item-remove` — admin inventory controls\n`/economy add-item-shop` · `/economy edit-shop-item` · `/economy remove-item-shop` — admin shop controls\n`/economy add-role-income` · `/economy remove-role-income` — admin role income controls\n`/economy iteminfo` — detailed item information"
)


@bot.tree.command(name="help", description="See every Cinnamon command and what it does")
@app_commands.guild_only()
async def help_cmd(interaction: discord.Interaction):
    commands_list = _all_leaf_commands()
    pages = []
    current_lines = []
    current_len = 0
    last_root = None

    for command in commands_list:
        path = _command_path(command)
        root = path.split()[0].lstrip("/")
        description = getattr(command, "description", None) or "No description provided."
        line = f"**{path}** — {description}"
        if len(line) > 900:
            line = line[:897] + "..."
        heading = "" if root == last_root else f"\n**{root.replace('-', ' ').replace('_', ' ').title()}**"
        extra = len(heading) + len(line) + 1
        # Pack multiple command groups into each page so the help command can
        # show the entire bot, not just the first few groups.
        if current_lines and current_len + extra > 3500:
            pages.append("\n".join(current_lines))
            current_lines = []
            current_len = 0
            heading = f"**{root.replace('-', ' ').replace('_', ' ').title()}**"
            extra = len(heading) + len(line) + 1
        current_lines.append(heading)
        current_lines.append(line)
        current_len += extra
        last_root = root
    if current_lines:
        pages.append("\n".join(current_lines))

    embeds = []
    total = len(commands_list)
    for index, body in enumerate(pages, start=1):
        embed = discord.Embed(title=f"🐾 Cinnamon command directory ({index}/{len(pages)})", description=body, color=0xFFB02E)
        embed.set_footer(text=f"/help • {total} commands • Use /setup for guided server setup")
        embeds.append(embed)

    # Add a compact guide as the final page if there is room.
    guide = discord.Embed(
        title="📖 How to use Cinnamon",
        description=(
            "**New server?** Run `/setup` first. It creates and configures the standard log/welcome/AI channels.\n\n"
            "**Looking for something?** Discord's slash-command search also filters these commands as you type.\n\n"
            "**Admin tools:** Most moderation, setup, logging, recovery, and configuration commands require the appropriate Discord permission.\n\n"
            "**Reset protection:** Run `/economy snapshot` before a reset, then `/economy restore-snapshot` afterward.\n\n"
            "**AI:** Mention Cinnamon or reply to her, or use the configured AI channel."
        ),
        color=discord.Color.blurple(),
    )
    if len(embeds) < 10:
        embeds.append(guide)
    await interaction.response.send_message(embeds=embeds, ephemeral=True)


# --- Data status / recovery -------------------------------------------------

datastatus_group = app_commands.Group(name="datastatus", description="Check or recover Cinnamon's persisted data")


@datastatus_group.command(name="check", description="Check whether persistent storage is actually connected right now")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def datastatus_check(interaction: discord.Interaction):
    status = await storage_status()
    icon = "✅" if status["connected"] else "⚠️"
    guild_warnings = sum(1 for g, _ in warnings_data.keys() if g == interaction.guild.id)
    hg_cog = bot.get_cog("HangryGamesCog")
    hg_game_num = hg_cog.game_counts.get(interaction.guild.id, 0) if hg_cog else 0
    embed = discord.Embed(title=f"{icon} Storage status", color=discord.Color.green() if status["connected"] else discord.Color.orange())
    embed.add_field(name="Backend", value=status["backend"], inline=True)
    embed.add_field(name="Connected", value="Yes" if status["connected"] else "No", inline=True)
    embed.add_field(name="Detail", value=status["detail"], inline=False)
    embed.add_field(name="This server's warnings tracked", value=str(guild_warnings), inline=True)
    embed.add_field(name="This server's Hangry Games count", value=str(hg_game_num), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def recall_guild_data(guild: discord.Guild) -> dict:
    """Best-effort recovery from configured Discord log channels.

    Warnings are merged idempotently, Hangry Games counters are rebuilt without
    incrementing the same winners on every scan, and economy snapshots are used
    only when this guild currently has no economy accounts (avoids overwriting
    newer live balances with an older backup).
    """
    warnings_restored = await recover_warnings_from_log(guild)
    hg_cog = bot.get_cog("HangryGamesCog")
    game_num, wins = await hg_cog.recover_from_log(guild) if hg_cog else (0, 0)
    economy_present = any(gid == guild.id for gid, _uid in economy_balances)
    economy_restored = 0
    snapshot_detail = "Skipped: live economy data already exists."
    if not economy_present and economy_log_channels.get(guild.id):
        economy_restored, snapshot_detail = await economy_restore_from_snapshot(guild)
    await bd_save_data()
    return {
        "warnings": warnings_restored,
        "hangry_game_count": game_num,
        "hangry_wins_seen": wins,
        "economy_accounts": economy_restored,
        "economy_detail": snapshot_detail,
        "economy_skipped_existing": economy_present,
    }


@bot.tree.command(name="recall", description="Recover recorded data from Cinnamon's configured log channels")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def recall_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    result = await recall_guild_data(interaction.guild)
    await send_log(interaction.guild.id, title="🩹 Log recovery completed", interaction=interaction, category="setup",
                   fields=[("Warnings restored", str(result["warnings"])), ("Hangry games found", str(result["hangry_game_count"])),
                           ("Hangry wins found", str(result["hangry_wins_seen"])), ("Economy accounts restored", str(result["economy_accounts"]))])
    await interaction.followup.send(
        "🩹 **Cinnamon's log recovery scan is complete.**\n"
        f"• New warnings reconstructed: **{result['warnings']}**\n"
        f"• Hangry Games count found: **#{result['hangry_game_count']}**; wins found in history: **{result['hangry_wins_seen']}**\n"
        f"• Economy accounts restored: **{result['economy_accounts']}**\n"
        f"• Economy snapshot: {result['economy_detail']}\n\n"
        "Recovery is best-effort and limited to messages/files still available in configured log channels. "
        "XP, active AI conversation memory, and events never logged cannot be reconstructed from channel history. "
        "Use `/datastatus check` to inspect persistent storage.",
        ephemeral=True,
    )


@datastatus_group.command(name="recover", description="Recover recorded data from this server's configured log channels")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def datastatus_recover(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    result = await recall_guild_data(interaction.guild)
    await send_log(interaction.guild.id, title="🩹 Data recovery completed", interaction=interaction, category="setup",
                   fields=[("Warnings restored", str(result["warnings"])), ("Hangry games found", str(result["hangry_game_count"])),
                           ("Hangry wins found", str(result["hangry_wins_seen"])), ("Economy accounts restored", str(result["economy_accounts"]))])
    await interaction.followup.send(
        f"🩹 Recovery scan complete. Warnings reconstructed: **{result['warnings']}**; "
        f"Hangry Games count: **#{result['hangry_game_count']}**; wins found: **{result['hangry_wins_seen']}**; "
        f"economy accounts restored: **{result['economy_accounts']}**.\n"
        "Only recoverable records still available in configured log channels can be rebuilt.",
        ephemeral=True,
    )


bot.tree.add_command(welcome_group)
bot.tree.add_command(goodbye_group)
bot.tree.add_command(reactionrole_group)
bot.tree.add_command(automod_group)
bot.tree.add_command(giveaway_group)
bot.tree.add_command(levelrole_group)
bot.tree.add_command(antiraid_group)
bot.tree.add_command(datastatus_group)



# ---------------------------------------------------------------------------
# Economy — Catnip, items, quests, transaction logs, and reset-safe snapshots
# ---------------------------------------------------------------------------


def economy_key(guild_id: int, user_id: int) -> tuple[int, int]:
    return guild_id, user_id


def economy_balance(guild_id: int, user_id: int) -> int:
    key = economy_key(guild_id, user_id)
    if key not in economy_balances:
        economy_balances[key] = ECONOMY_STARTING_BALANCE
    return int(economy_balances[key])


def economy_inventory_for(guild_id: int, user_id: int) -> dict:
    key = economy_key(guild_id, user_id)
    if key not in economy_inventory:
        economy_inventory[key] = {}
    return economy_inventory[key]


def economy_quests_for(guild_id: int, user_id: int) -> dict:
    return sanitize_economy_quests(guild_id, user_id)


async def unlock_economy_achievement(guild_id: int, user_id: int, achievement_id: str, *, reason: str = "") -> bool:
    """Unlock one achievement exactly once and persist it. Returns True only on a new unlock."""
    if achievement_id not in ECONOMY_ACHIEVEMENTS:
        return False
    key = economy_key(guild_id, user_id)
    unlocked = economy_achievements.setdefault(key, [])
    if achievement_id in unlocked:
        return False
    unlocked.append(achievement_id)
    reward = int(ECONOMY_ACHIEVEMENTS[achievement_id].get("reward", 0))
    if reward:
        economy_balances[key] = economy_balance(guild_id, user_id) + reward
    await bd_save_data()
    achievement = ECONOMY_ACHIEVEMENTS[achievement_id]
    await economy_log(guild_id, title="🏆 Achievement unlocked", fields=[
        ("User", f"<@{user_id}> ({user_id})"),
        ("Achievement", achievement["name"]),
        ("Reward", f"+{reward:,} Catnip"),
        ("Reason", reason or achievement["description"]),
        ("Balance after", f"{economy_balance(guild_id, user_id):,} Catnip"),
    ])
    return True


def sanitize_economy_quests(guild_id: int, user_id: int) -> dict:
    """Return a valid quest-progress dict even if old/corrupt persisted data exists."""
    key = economy_key(guild_id, user_id)
    raw = economy_quests.get(key)
    if not isinstance(raw, dict):
        raw = {}
        economy_quests[key] = raw
    clean = {}
    for qid, q in ECONOMY_QUESTS.items():
        try:
            clean[qid] = max(0, int(raw.get(qid, 0)))
        except (TypeError, ValueError):
            clean[qid] = 0
    economy_quests[key] = clean
    return clean


def economy_user_snapshot(guild_id: int, user_id: int) -> dict:
    return {
        "balance": economy_balance(guild_id, user_id),
        "inventory": dict(economy_inventory_for(guild_id, user_id)),
        "quests": dict(sanitize_economy_quests(guild_id, user_id)),
        "achievements": list(economy_achievements.get((guild_id, user_id), [])),
        "level_rewards_claimed": list(economy_level_rewards_claimed.get((guild_id, user_id), [])),
    }


async def economy_log(guild_id: int, *, title: str, description: str = "", fields=None):
    channel_id = economy_log_channels.get(guild_id) or category_log_channels.get(guild_id, {}).get("economy")
    if not channel_id:
        channel_id = log_channels.get(guild_id)
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        return
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.gold(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    for name, value in (fields or []):
        embed.add_field(name=name, value=str(value), inline=True)
    embed.set_footer(text=f"Cinnamon economy log • Guild {guild_id}")
    try:
        await channel.send(embed=embed)
    except Exception as e:
        # Logging must never make the actual economy command fail.
        log.exception(f"Failed to send economy log in guild {guild_id}: {e}")


def economy_cooldown_remaining(guild_id: int, user_id: int, action: str) -> int:
    until = float(economy_cooldowns.get((guild_id, user_id, action), 0))
    return max(0, math.ceil(until - time.time()))


def economy_item_lines() -> str:
    return "\n".join(
        f"{item['emoji']} **{item['name']}** — `{item_id}` — **{item['price']} Catnip**\n{item['description']}"
        for item_id, item in ECONOMY_ITEMS.items()
    )


async def economy_do_work(guild_id: int, user: discord.abc.User) -> tuple[bool, int, str]:
    user_id = user.id
    remaining = economy_cooldown_remaining(guild_id, user_id, "work")
    if remaining:
        return False, 0, f"🐾 You're on a work cooldown. Try again in **{remaining // 60}m {remaining % 60}s**."
    balance_before = economy_balance(guild_id, user_id)
    amount = random.randint(ECONOMY_WORK_MIN, ECONOMY_WORK_MAX)
    jobs = [
        "sorted Cinnamon's treats", "guarded the tuna cupboard", "cleaned the cat tree",
        "chased a suspicious cardboard box", "organized the yarn drawer",
        "polished Cinnamon's food bowl", "delivered a mysterious package of kibble",
    ]
    job = random.choice(jobs)
    economy_cooldowns[(guild_id, user_id, "work")] = time.time() + ECONOMY_WORK_COOLDOWN
    economy_balances[(guild_id, user_id)] = balance_before + amount
    await bd_save_data()
    await economy_log(guild_id, title="💼 Economy work", fields=[("User", f"{user} ({user_id})"), ("Job", job), ("Earned", f"+{amount} Catnip"), ("Balance before", f"{balance_before:,}"), ("Balance after", f"{balance_before+amount:,}")])
    return True, amount, f"💼 You **{job}** and earned **{amount} Catnip**! *Cinnamon inspects the work proudly.*"


def economy_level_reward_claimed(guild_id: int, user_id: int, level: int) -> bool:
    return level in economy_level_rewards_claimed.get((guild_id, user_id), [])


def mark_economy_level_reward_claimed(guild_id: int, user_id: int, level: int):
    key = (guild_id, user_id)
    economy_level_rewards_claimed.setdefault(key, [])
    if level not in economy_level_rewards_claimed[key]:
        economy_level_rewards_claimed[key].append(level)


def economy_income_role_lines(guild: discord.Guild) -> str:
    cfg = economy_income_roles.get(guild.id, {})
    if not cfg:
        return "No income roles are configured."
    lines = []
    for role_id, data in cfg.items():
        role = guild.get_role(int(role_id))
        name = role.mention if role else f"Deleted role ({role_id})"
        cooldown = int(data.get("cooldown", 3600))
        amount = int(data.get("amount", 0))
        interval = int(data.get("interval", max(1, cooldown // 3600)))
        unit = str(data.get("unit", "hour"))
        lines.append(f"{name} — **{amount:,} Catnip / {interval} {unit}(s)**")
    return "\n".join(lines)


economy_group = app_commands.Group(name="economy", description="Cinnamon's Catnip economy, items, quests, and backups")

# Discord allows at most 25 direct children under one application-command group.
# Keep the two Catnip admin balance controls under a nested admin group so the
# main /economy group stays within that limit.
economy_admin_group = app_commands.Group(
    name="admin",
    description="Economy administration commands",
    parent=economy_group,
)


@economy_group.command(name="balance", description="Check your Catnip balance")
@app_commands.guild_only()
async def economy_balance_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    balance = economy_balance(interaction.guild.id, member.id)
    inv = economy_inventory_for(interaction.guild.id, member.id)
    item_count = sum(int(v) for v in inv.values())
    embed = discord.Embed(title=f"🐾 {member.display_name}'s wallet", color=discord.Color.gold())
    embed.add_field(name="Catnip", value=f"🌿 **{balance:,}**", inline=True)
    embed.add_field(name="Items", value=f"🎒 **{item_count}**", inline=True)
    await interaction.response.send_message(embed=embed)
    await economy_log(interaction.guild.id, title="👛 Economy balance viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Balance", f"{balance:,} Catnip")])
    await bd_save_data()


@economy_group.command(name="inventory", description="See your Cinnamon items")
@app_commands.guild_only()
async def economy_inventory_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    inv = economy_inventory_for(interaction.guild.id, member.id)
    lines = []
    for item_id, qty in inv.items():
        if qty > 0 and item_id in ECONOMY_ITEMS:
            item = ECONOMY_ITEMS[item_id]
            lines.append(f"{item['emoji']} **{item['name']}** × **{qty}** (`{item_id}`)")
    embed = discord.Embed(title=f"🎒 {member.display_name}'s inventory", color=discord.Color.blurple())
    embed.description = "\n".join(lines) if lines else "Your inventory is empty. Visit `/economy shop`!"
    await interaction.response.send_message(embed=embed)
    inv_summary = "\n".join(f"{ECONOMY_ITEMS[k]['name']}: {int(v)}" for k, v in inv.items() if k in ECONOMY_ITEMS and int(v) > 0) or "Empty"
    await economy_log(interaction.guild.id, title="🎒 Economy inventory viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Inventory", inv_summary[:1000]), ("Total items", str(sum(int(v) for v in inv.values()))), ("Catnip balance", f"{economy_balance(interaction.guild.id, member.id):,}")])


@economy_group.command(name="shop", description="View Cinnamon's shop")
@app_commands.guild_only()
async def economy_shop_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🐟 Cinnamon's Catnip Shop", description=economy_item_lines(), color=discord.Color.gold())
    embed.set_footer(text="Buy with /economy buy item:<item_id> quantity:<number>")
    await interaction.response.send_message(embed=embed)
    await economy_log(interaction.guild.id, title="🛒 Economy shop viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})")])


@economy_group.command(name="buy", description="Buy an item with Catnip")
@app_commands.describe(item="Item ID or item name from /economy shop", quantity="How many to buy")
@app_commands.guild_only()
async def economy_buy_cmd(interaction: discord.Interaction, item: str, quantity: int = 1):
    guild_id, user_id = interaction.guild.id, interaction.user.id
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await interaction.response.send_message("❌ That item isn't in the shop. Use `/economy shop` to see available items.", ephemeral=True)
        return
    current_qty = int(economy_inventory_for(guild_id, user_id).get(item_id, 0))
    max_per_person = int(data.get("max_per_person", 0))
    if max_per_person and current_qty + quantity > max_per_person:
        await interaction.response.send_message(f"❌ This item has a limit of **{max_per_person}** per person. You already have **{current_qty}**.", ephemeral=True)
        return
    cost = data["price"] * quantity
    balance = economy_balance(guild_id, user_id)
    if balance < cost:
        await interaction.response.send_message(f"❌ You need **{cost:,} Catnip**, but you only have **{balance:,}**.", ephemeral=True)
        return
    economy_balances[(guild_id, user_id)] = balance - cost
    inv = economy_inventory_for(guild_id, user_id)
    inv[item_id] = current_qty + quantity
    await bd_save_data()
    await economy_log(guild_id, title="🛒 Economy purchase", fields=[("User", f"{interaction.user} ({user_id})"), ("Item", f"{data['name']} (`{item_id}`)"), ("Quantity", quantity), ("Unit price", f"{data['price']:,} Catnip"), ("Deducted", f"-{cost:,} Catnip"), ("Balance before", f"{balance:,} Catnip"), ("Balance after", f"{balance-cost:,} Catnip"), ("Item quantity after", str(inv[item_id]))])
    await interaction.response.send_message(f"🛒 Bought **{quantity}× {data['emoji']} {data['name']}** for **{cost:,} Catnip**. Balance: **{economy_balances[(guild_id, user_id)]:,}**")


@economy_group.command(name="daily", description="Claim your daily Catnip")
@app_commands.guild_only()
async def economy_daily_cmd(interaction: discord.Interaction):
    guild_id, user_id = interaction.guild.id, interaction.user.id
    remaining = economy_cooldown_remaining(guild_id, user_id, "daily")
    if remaining:
        await interaction.response.send_message(f"🐾 Cinnamon already gave you your daily Catnip. Come back in **{remaining // 3600}h {(remaining % 3600) // 60}m**.", ephemeral=True)
        return
    economy_cooldowns[(guild_id, user_id, "daily")] = time.time() + 86400
    balance_before = economy_balance(guild_id, user_id)
    economy_balances[(guild_id, user_id)] = balance_before + ECONOMY_DAILY_REWARD
    await bd_save_data()
    await economy_log(guild_id, title="🌿 Daily Catnip", fields=[("User", f"{interaction.user} ({user_id})"), ("Amount", f"+{ECONOMY_DAILY_REWARD} Catnip"), ("Balance before", f"{balance_before:,}"), ("Balance after", f"{balance_before+ECONOMY_DAILY_REWARD:,}")])
    await interaction.response.send_message(f"🌿 **+{ECONOMY_DAILY_REWARD} Catnip!** Cinnamon has approved your daily snack budget.")


@economy_group.command(name="work", description="Work for Cinnamon and earn 50-150 Catnip every 10 minutes")
@app_commands.guild_only()
async def economy_work_cmd(interaction: discord.Interaction):
    ok, amount, message = await economy_do_work(interaction.guild.id, interaction.user)
    await interaction.response.send_message(message, ephemeral=not ok)


@economy_group.command(name="give", description="Give Catnip to another member")
@app_commands.guild_only()
async def economy_give_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    guild_id = interaction.guild.id
    if member.bot:
        await interaction.response.send_message("❌ Bot accounts can't receive Catnip.", ephemeral=True)
        return
    if member.id == interaction.user.id:
        await interaction.response.send_message("🐾 You can't give Catnip to yourself.", ephemeral=True)
        return
    sender_balance = economy_balance(guild_id, interaction.user.id)
    if sender_balance < amount:
        await interaction.response.send_message(f"❌ You only have **{sender_balance:,} Catnip**.", ephemeral=True)
        return
    recipient_before = economy_balance(guild_id, member.id)
    economy_balances[(guild_id, interaction.user.id)] = sender_balance - amount
    economy_balances[(guild_id, member.id)] = recipient_before + amount
    await bd_save_data()
    await economy_log(guild_id, title="🎁 Catnip transfer", fields=[("From", f"{interaction.user} ({interaction.user.id})"), ("To", f"{member} ({member.id})"), ("Amount", f"{amount:,} Catnip"), ("Sender before", f"{sender_balance:,}"), ("Sender after", f"{sender_balance-amount:,}"), ("Recipient before", f"{recipient_before:,}"), ("Recipient after", f"{recipient_before+amount:,}")])
    await interaction.response.send_message(f"🎁 Gave **{amount:,} Catnip** to {member.mention}.")


@economy_group.command(name="leaderboard", description="Show the richest members")
@app_commands.guild_only()
async def economy_leaderboard_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    rows = [(uid, bal) for (gid, uid), bal in economy_balances.items() if gid == guild_id]
    rows.sort(key=lambda x: x[1], reverse=True)
    lines = []
    for i, (uid, bal) in enumerate(rows[:10], 1):
        member = interaction.guild.get_member(uid)
        name = member.display_name if member else f"User {uid}"
        lines.append(f"**{i}.** {name} — 🌿 **{bal:,}**")
    embed = discord.Embed(title="🏆 Catnip leaderboard", description="\n".join(lines) if lines else "No economy users yet.", color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)


@economy_group.command(name="quest", description="View Cinnamon quests and your progress")
@app_commands.guild_only()
async def economy_quest_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    user_id = interaction.user.id
    try:
        progress = sanitize_economy_quests(guild_id, user_id)
        lines = []
        for qid, q in ECONOMY_QUESTS.items():
            if not isinstance(q, dict):
                continue
            item_id = str(q.get("item", ""))
            item = ECONOMY_ITEMS.get(item_id)
            if not isinstance(item, dict):
                continue
            amount = max(1, int(q.get("amount", 1)))
            done = min(max(0, int(progress.get(qid, 0))), amount)
            emoji = str(item.get("emoji", "🐾"))[:8]
            item_name = str(item.get("name", item_id))[:80]
            reward = max(0, int(q.get("reward", 0)))
            lines.append(
                f"**{q.get('name', qid)}** — {done}/{amount} {emoji} {item_name} → **{reward} Catnip**\n"
                f"{q.get('description', '')}"
            )
        if not lines:
            lines.append("No economy quests are currently configured.")
        embed = discord.Embed(
            title="📜 Cinnamon's quests",
            description="\n\n".join(lines)[:4000],
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Use /economy feed to give Cinnamon the required item.")
        await interaction.response.send_message(embed=embed)
        # Logging is deliberately after the user response and is non-fatal.
        await economy_log(guild_id, title="📜 Economy quests viewed", fields=[
            ("User", f"{interaction.user} ({user_id})"),
            ("Quests shown", str(len(lines))),
        ])
    except Exception:
        log.exception("Economy quest command failed for guild %s", guild_id)
        msg = "❌ I couldn't load the quests right now. The quest data may need to be reset or repaired."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            log.exception("Could not send economy quest error response for guild %s", guild_id)


@economy_group.command(name="feed", description="Give Cinnamon an item and progress matching quests")
@app_commands.describe(item="Item to give Cinnamon", quantity="How many to give")
@app_commands.choices(item=[app_commands.Choice(name=v["name"], value=k) for k, v in ECONOMY_ITEMS.items()])
@app_commands.guild_only()
async def economy_feed_cmd(interaction: discord.Interaction, item: app_commands.Choice[str], quantity: app_commands.Range[int, 1, 99] = 1):
    try:
        guild_id, user_id = interaction.guild.id, interaction.user.id
        item_id = str(item.value)
        data = ECONOMY_ITEMS.get(item_id)
        if not data:
            await interaction.response.send_message("❌ That item no longer exists. Refresh the command choices and try again.", ephemeral=True)
            return
        inv = economy_inventory_for(guild_id, user_id)
        have = max(0, int(inv.get(item_id, 0)))
        if have < quantity:
            await interaction.response.send_message(f"❌ You only have **{have}× {data['name']}**.", ephemeral=True)
            return
        balance_before = economy_balance(guild_id, user_id)
        inv[item_id] = have - quantity
        progress = sanitize_economy_quests(guild_id, user_id)
        completed = []
        for qid, q in list(ECONOMY_QUESTS.items()):
            if str(q.get("item", "")) != item_id:
                continue
            amount = max(1, int(q.get("amount", 1)))
            before = min(int(progress.get(qid, 0)), amount)
            after = min(amount, before + quantity)
            progress[qid] = after
            if before < amount <= after:
                reward = max(0, int(q.get("reward", 0)))
                economy_balances[(guild_id, user_id)] = economy_balance(guild_id, user_id) + reward
                completed.append(f"**{q.get('name', qid)}** (+{reward} Catnip)")
        await bd_save_data()
        balance_after = economy_balance(guild_id, user_id)
        unlocked = []
        if await unlock_economy_achievement(guild_id, user_id, "first_feed", reason=f"Fed {quantity}× {data['name']} to Cinnamon"):
            unlocked.append(ECONOMY_ACHIEVEMENTS["first_feed"]["name"])
        if completed and await unlock_economy_achievement(guild_id, user_id, "quest_complete", reason="Completed an economy quest"):
            unlocked.append(ECONOMY_ACHIEVEMENTS["quest_complete"]["name"])
        if balance_after >= 1000 and await unlock_economy_achievement(guild_id, user_id, "catnip_1000", reason="Reached 1,000 Catnip"):
            unlocked.append(ECONOMY_ACHIEVEMENTS["catnip_1000"]["name"])
        total_items = sum(max(0, int(v)) for v in inv.values())
        if total_items >= 10 and await unlock_economy_achievement(guild_id, user_id, "collector_10", reason="Reached 10 total items"):
            unlocked.append(ECONOMY_ACHIEVEMENTS["collector_10"]["name"])
        if ECONOMY_QUESTS and all(int(progress.get(qid, 0)) >= int(q.get("amount", 1)) for qid, q in ECONOMY_QUESTS.items()):
            if await unlock_economy_achievement(guild_id, user_id, "all_quests", reason="Completed every configured economy quest"):
                unlocked.append(ECONOMY_ACHIEVEMENTS["all_quests"]["name"])
        await economy_log(guild_id, title="🐟 Cinnamon fed", fields=[("User", f"{interaction.user} ({user_id})"), ("Item", f"{data['name']} (`{item_id}`)"), ("Quantity fed", quantity), ("Quantity remaining", inv.get(item_id, 0)), ("Catnip before", f"{balance_before:,}"), ("Catnip after", f"{economy_balance(guild_id, user_id):,}"), ("Quest rewards", ", ".join(completed) if completed else "None"), ("Achievements", ", ".join(unlocked) if unlocked else "None")])
        text = f"🐾 Cinnamon happily accepted **{quantity}× {data['name']}**!"
        if completed:
            text += "\n🎉 Quest complete: " + ", ".join(completed)
        if unlocked:
            text += "\n🏆 Achievement unlocked: **" + ", ".join(unlocked) + "**"
        await interaction.response.send_message(text)
    except Exception as exc:
        log.exception("Economy feed command failed for guild %s", interaction.guild.id if interaction.guild else None)
        if interaction.response.is_done():
            await interaction.followup.send("❌ I couldn't process that feed/quest action. No further changes were made by the failed step.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ I couldn't process that feed/quest action. Please try again.", ephemeral=True)


@economy_group.command(name="achievements", description="View your unlocked Cinnamon economy achievements")
@app_commands.guild_only()
async def economy_achievements_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    guild_id = interaction.guild.id
    try:
        member = member or interaction.user
        raw_unlocked = economy_achievements.get((guild_id, member.id), [])
        if not isinstance(raw_unlocked, (list, tuple, set)):
            raw_unlocked = []
        unlocked = {str(aid) for aid in raw_unlocked if str(aid) in ECONOMY_ACHIEVEMENTS}
        lines = []
        for aid, achievement in ECONOMY_ACHIEVEMENTS.items():
            status = "🏆" if aid in unlocked else "🔒"
            reward = max(0, int(achievement.get("reward", 0)))
            lines.append(
                f"{status} **{achievement.get('name', aid)}** — "
                f"{achievement.get('description', '')} — **{reward} Catnip**"
            )
        embed = discord.Embed(
            title=f"🏆 {member.display_name}'s achievements",
            description="\n".join(lines)[:4000] if lines else "No achievements are currently configured.",
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"Unlocked: {len(unlocked)}/{len(ECONOMY_ACHIEVEMENTS)}")
        await interaction.response.send_message(embed=embed)
        await economy_log(guild_id, title="🏆 Economy achievements viewed", fields=[
            ("Viewer", f"{interaction.user} ({interaction.user.id})"),
            ("Member", f"{member} ({member.id})"),
            ("Unlocked", f"{len(unlocked)}/{len(ECONOMY_ACHIEVEMENTS)}"),
        ])
    except Exception:
        log.exception("Economy achievements command failed for guild %s", guild_id)
        msg = "❌ I couldn't load the achievements right now. The achievement data may need to be repaired."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            log.exception("Could not send economy achievements error response for guild %s", guild_id)


@economy_group.command(name="logs", description="Set or disable the economy transaction log channel")
@app_commands.describe(channel="Channel where economy transactions and backups will be logged; omit to disable")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def economy_logs_cmd(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    guild_id = interaction.guild.id
    if channel is None:
        removed = economy_log_channels.pop(guild_id, None)
        category_log_channels.get(guild_id, {}).pop("economy", None)
        await bd_save_data()
        await interaction.response.send_message("🧾 Economy logs disabled." if removed else "🧾 Economy logs are already disabled.", ephemeral=True)
        if removed:
            # The economy destination has just been removed, so this is intentionally routed through the remaining setup/main logger.
            await send_log(guild_id, title="🧾 Economy logging disabled", interaction=interaction, category="setup", fields=[("Previous channel ID", str(removed))])
        return
    economy_log_channels[guild_id] = channel.id
    category_log_channels.setdefault(guild_id, {})["economy"] = channel.id
    await secure_log_channel(channel)
    await bd_save_data()
    await economy_log(guild_id, title="🧾 Economy logging enabled", description=f"Economy transactions and backup snapshots will be posted here: {channel.mention}")
    await interaction.response.send_message(f"✅ Economy logs will now go to {channel.mention}.", ephemeral=True)


async def economy_snapshot_payload(guild_id: int) -> dict:
    users = {}
    user_ids = set()
    for (gid, uid) in economy_balances:
        if gid == guild_id: user_ids.add(uid)
    for (gid, uid) in economy_inventory:
        if gid == guild_id: user_ids.add(uid)
    for (gid, uid) in economy_quests:
        if gid == guild_id: user_ids.add(uid)
    for uid in user_ids:
        users[str(uid)] = economy_user_snapshot(guild_id, uid)
    return {
        "schema": 1,
        "type": "cinnamon_economy_snapshot",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "guild_id": guild_id,
        "currency": "Catnip",
        "users": users,
        "items": ECONOMY_ITEMS,
        "quests": ECONOMY_QUESTS,
        "level_rewards": ECONOMY_LEVEL_REWARDS,
        "income_roles": economy_income_roles.get(guild_id, {}),
    }


@economy_group.command(name="snapshot", description="Create one complete economy backup before resetting the bot")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def economy_snapshot_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    channel_id = economy_log_channels.get(guild_id)
    channel = bot.get_channel(channel_id) if channel_id else None
    if channel is None:
        await interaction.response.send_message("❌ Set an economy log channel first with `/economy logs #channel`.", ephemeral=True)
        return
    payload = await economy_snapshot_payload(guild_id)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    file = discord.File(io.BytesIO(raw), filename=f"cinnamon_economy_snapshot_{guild_id}.json")
    user_count = len(payload["users"])
    embed = discord.Embed(title="💾 Cinnamon economy snapshot", description="Complete Catnip balances, inventories, quest progress, item definitions, and quest definitions for this server. Keep this message/file before a reset.", color=discord.Color.green(), timestamp=datetime.datetime.now(datetime.timezone.utc))
    embed.add_field(name="Users backed up", value=str(user_count), inline=True)
    embed.add_field(name="Currency", value="Catnip", inline=True)
    embed.add_field(name="Items", value=str(len(ECONOMY_ITEMS)), inline=True)
    rows = []
    for uid_text, user in sorted(payload["users"].items(), key=lambda pair: int(pair[1].get("balance", 0)), reverse=True)[:10]:
        member = guild_id and bot.get_guild(guild_id).get_member(int(uid_text))
        name = member.display_name if member else f"User {uid_text}"
        rows.append(f"{len(rows)+1}. {name} — {int(user.get('balance', 0)):,} Catnip")
    embed.add_field(name="🏆 Leaderboard at backup time", value="\n".join(rows) if rows else "No users yet.", inline=False)
    item_text = "\n".join(f"{v['emoji']} {v['name']} (`{k}`) — {v['price']} Catnip" for k, v in ECONOMY_ITEMS.items())
    embed.add_field(name="🛒 Item information", value=item_text, inline=False)
    quest_text = "\n".join(f"{q['name']} — {q['amount']}× {ECONOMY_ITEMS[q['item']]['name']} → {q['reward']} Catnip" for q in ECONOMY_QUESTS.values())
    embed.add_field(name="📜 Quest information", value=quest_text, inline=False)
    embed.add_field(name="How to restore", value="After the reset, run `/economy restore-snapshot` in this server. The bot will scan this log channel for the newest snapshot.", inline=False)
    await interaction.response.defer(ephemeral=True)
    await channel.send(embed=embed, file=file)
    await bd_save_data()
    await economy_log(guild_id, title="💾 Economy snapshot created", fields=[("Created by", f"{interaction.user} ({interaction.user.id})"), ("Users backed up", str(user_count)), ("Items", str(len(ECONOMY_ITEMS))), ("Channel", channel.mention)])
    await interaction.followup.send(f"✅ Snapshot saved to {channel.mention}. **{user_count}** users are included. You can reset the bot and later run `/economy restore-snapshot`.", ephemeral=True)


async def economy_restore_from_snapshot(guild: discord.Guild, limit: int = 5000) -> tuple[int, str]:
    channel_id = economy_log_channels.get(guild.id)
    if not channel_id:
        return 0, "No economy log channel is configured."
    channel = bot.get_channel(channel_id)
    if channel is None:
        return 0, "The configured economy log channel could not be found."
    latest = None
    try:
        async for message in channel.history(limit=limit):
            for attachment in message.attachments:
                if attachment.filename.startswith("cinnamon_economy_snapshot_") and attachment.filename.endswith(".json"):
                    try:
                        data = json.loads((await attachment.read()).decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError, discord.HTTPException):
                        continue
                    if data.get("type") == "cinnamon_economy_snapshot" and int(data.get("guild_id", 0)) == guild.id:
                        latest = data
                        break
            if latest:
                break
    except discord.HTTPException as e:
        return 0, f"Could not read the economy log channel: {e}"
    if latest is None:
        return 0, "No economy snapshot was found in the log channel."

    restored = 0
    for uid_text, user in latest.get("users", {}).items():
        try:
            uid = int(uid_text)
            economy_balances[(guild.id, uid)] = int(user.get("balance", ECONOMY_STARTING_BALANCE))
            economy_inventory[(guild.id, uid)] = {str(k): int(v) for k, v in user.get("inventory", {}).items() if int(v) > 0}
            economy_quests[(guild.id, uid)] = {str(k): int(v) for k, v in user.get("quests", {}).items()}
            economy_level_rewards_claimed[(guild.id, uid)] = [int(x) for x in user.get("level_rewards_claimed", [])]
            restored += 1
        except (ValueError, TypeError):
            continue
    snapshot_income = latest.get("income_roles")
    if isinstance(snapshot_income, dict):
        economy_income_roles[guild.id] = {int(r): cfg for r, cfg in snapshot_income.items()}
    snapshot_items = latest.get("items")
    if isinstance(snapshot_items, dict):
        ECONOMY_ITEMS.clear()
        for item_id, item in snapshot_items.items():
            if isinstance(item, dict):
                ECONOMY_ITEMS[str(item_id)] = {
                    "name": str(item.get("name", item_id))[:80],
                    "price": max(1, int(item.get("price", 1))),
                    "emoji": str(item.get("emoji", "🐾"))[:8],
                    "description": str(item.get("description", ""))[:300],
                    "max_per_person": max(0, int(item.get("max_per_person", 0))),
                }
    await bd_save_data()
    created = latest.get("created_at", "unknown time")
    return restored, created


@economy_admin_group.command(name="addcatnip", description="Admin: add Catnip to a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def economy_addcatnip_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    guild_id = interaction.guild.id
    before = economy_balance(guild_id, member.id)
    economy_balances[(guild_id, member.id)] = before + amount
    await bd_save_data()
    await economy_log(guild_id, title="🛠️ Admin Catnip added", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Amount", f"+{amount:,} Catnip"), ("Balance before", f"{before:,}"), ("Balance after", f"{before+amount:,}")])
    await interaction.response.send_message(f"✅ Added **{amount:,} Catnip** to {member.mention}. New balance: **{economy_balance(guild_id, member.id):,}**.", ephemeral=True)


@economy_admin_group.command(name="removecatnip", description="Admin: remove Catnip from a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def economy_removecatnip_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    guild_id = interaction.guild.id
    current = economy_balance(guild_id, member.id)
    removed = min(current, amount)
    economy_balances[(guild_id, member.id)] = current - removed
    await bd_save_data()
    await economy_log(guild_id, title="🛠️ Admin Catnip removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Amount", f"-{removed:,} Catnip"), ("Balance before", f"{current:,}"), ("Balance after", f"{current-removed:,}")])
    await interaction.response.send_message(f"✅ Removed **{removed:,} Catnip** from {member.mention}. New balance: **{economy_balance(guild_id, member.id):,}**.", ephemeral=True)


@economy_group.command(name="income", description="Admin: manage Catnip income roles")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(action="add, remove, or list", role="Role that earns Catnip", amount="Catnip paid each collection", minutes="Cooldown in minutes")
@app_commands.choices(action=[app_commands.Choice(name="add", value="add"), app_commands.Choice(name="remove", value="remove"), app_commands.Choice(name="list", value="list")])
async def economy_income_cmd(interaction: discord.Interaction, action: app_commands.Choice[str], role: discord.Role | None = None, amount: int | None = None, minutes: int | None = None):
    guild_id = interaction.guild.id
    cfg = economy_income_roles.setdefault(guild_id, {})
    if action.value == "list":
        embed = discord.Embed(title="💰 Catnip income roles", description=economy_income_role_lines(interaction.guild), color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if role is None:
        await interaction.response.send_message("❌ Choose a role.", ephemeral=True)
        return
    if action.value == "remove":
        removed = cfg.pop(role.id, None)
        await bd_save_data()
        await interaction.response.send_message(f"🗑️ Removed {role.mention} from Catnip income roles." if removed else f"ℹ️ {role.mention} was not an income role.", ephemeral=True)
        return
    if amount is None or minutes is None:
        await interaction.response.send_message("❌ For `add`, provide both `amount` and `minutes`.", ephemeral=True)
        return
    cfg[role.id] = {"amount": int(amount), "cooldown": int(minutes) * 60}
    await bd_save_data()
    await economy_log(guild_id, title="💰 Income role configured", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Role", role.name), ("Income", f"{amount:,} Catnip / {minutes} min")])
    await interaction.response.send_message(f"✅ {role.mention} now earns **{amount:,} Catnip every {minutes} minutes** when members use `/collect`.", ephemeral=True)


async def economy_collect(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    configs = economy_income_roles.get(guild_id, {})
    if not configs:
        await interaction.response.send_message("ℹ️ This server has no income roles configured yet.", ephemeral=True)
        return
    total = 0
    collected = []
    now = time.time()
    for role in interaction.user.roles:
        data = configs.get(role.id)
        if not data:
            continue
        action = f"income:{role.id}"
        remaining = economy_cooldown_remaining(guild_id, interaction.user.id, action)
        if remaining:
            continue
        amount = int(data.get("amount", 0))
        cooldown = int(data.get("cooldown", 3600))
        if amount <= 0:
            continue
        economy_cooldowns[(guild_id, interaction.user.id, action)] = now + cooldown
        total += amount
        collected.append(f"{role.name}: +{amount:,}")
    if not collected:
        await interaction.response.send_message("⏳ None of your income roles are ready to collect yet.", ephemeral=True)
        return
    balance_before = economy_balance(guild_id, interaction.user.id)
    economy_balances[(guild_id, interaction.user.id)] = balance_before + total
    await bd_save_data()
    await economy_log(guild_id, title="💰 Income collected", fields=[("User", f"{interaction.user} ({interaction.user.id})"), ("Total", f"+{total:,} Catnip"), ("Balance before", f"{balance_before:,}"), ("Balance after", f"{balance_before+total:,}"), ("Sources", "\n".join(collected))])
    await interaction.response.send_message(f"💰 You collected **{total:,} Catnip**!\n" + "\n".join(f"• {x}" for x in collected))


@economy_group.command(name="collect", description="Collect Catnip from all income roles you have")
@app_commands.guild_only()
async def economy_collect_cmd(interaction: discord.Interaction):
    await economy_collect(interaction)


@bot.tree.command(name="collect", description="Collect Catnip from all income roles you have")
@app_commands.guild_only()
async def collect_cmd(interaction: discord.Interaction):
    await economy_collect(interaction)


@economy_group.command(name="item-add", description="Admin: add an item directly to a member's inventory")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(member="Member receiving the item", item="Item ID or item name", quantity="Number of items to add")
async def economy_item_add_cmd(interaction: discord.Interaction, member: discord.Member, item: str, quantity: int = 1):
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await interaction.response.send_message("❌ That item doesn't exist. Use `/economy shop` first.", ephemeral=True)
        return
    inv = economy_inventory_for(interaction.guild.id, member.id)
    max_per_person = int(data.get("max_per_person", 0))
    current = int(inv.get(item_id, 0))
    if max_per_person and current + quantity > max_per_person:
        await interaction.response.send_message(f"❌ {member.mention} cannot hold more than **{max_per_person}** of this item.", ephemeral=True)
        return
    inv[item_id] = current + quantity
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🛠️ Admin item added", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Item", f"{data['name']} (`{item_id}`)"), ("Quantity added", f"+{quantity}"), ("Quantity before", current), ("Quantity after", inv[item_id]), ("Catnip balance", economy_balance(interaction.guild.id, member.id))])
    await interaction.response.send_message(f"✅ Added **{quantity}× {data['emoji']} {data['name']}** to {member.mention}.", ephemeral=True)


@economy_group.command(name="item-remove", description="Admin: remove an item from a member's inventory")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(member="Member losing the item", item="Item ID or item name", quantity="Number of items to remove")
async def economy_item_remove_cmd(interaction: discord.Interaction, member: discord.Member, item: str, quantity: int = 1):
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await interaction.response.send_message("❌ That item doesn't exist.", ephemeral=True)
        return
    inv = economy_inventory_for(interaction.guild.id, member.id)
    current = int(inv.get(item_id, 0))
    removed = min(current, quantity)
    if removed <= 0:
        await interaction.response.send_message(f"❌ {member.mention} doesn't have that item.", ephemeral=True)
        return
    inv[item_id] = current - removed
    if inv[item_id] <= 0:
        inv.pop(item_id, None)
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🛠️ Admin item removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Item", f"{data['name']} (`{item_id}`)"), ("Quantity removed", f"-{removed}"), ("Quantity before", current), ("Quantity after", inv.get(item_id, 0)), ("Catnip balance", economy_balance(interaction.guild.id, member.id))])
    await interaction.response.send_message(f"✅ Removed **{removed}× {data['emoji']} {data['name']}** from {member.mention}.", ephemeral=True)


@economy_group.command(name="add-item-shop", description="Admin: add an item to the Catnip shop")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(item_id="Unique shop ID", name="Item name", price="Price in Catnip", description="Optional item description", per_person_limit="Optional maximum quantity one member can own", emoji="Optional emoji")
async def economy_add_item_shop_cmd(interaction: discord.Interaction, item_id: str, name: str, price: int, description: str | None = None, per_person_limit: int | None = None, emoji: str = "🐾"):
    item_id = re.sub(r"[^a-z0-9_-]", "", item_id.lower())[:32]
    if not item_id or item_id in ECONOMY_ITEMS:
        await interaction.response.send_message("❌ That item ID is invalid or already exists.", ephemeral=True)
        return
    ECONOMY_ITEMS[item_id] = {"name": name[:80], "price": int(price), "emoji": emoji[:8], "description": (description or "No description provided.")[:300], "max_per_person": int(per_person_limit or 0)}
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🛒 Shop item added", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Item", f"{emoji} {name}"), ("ID", item_id), ("Price", f"{price:,} Catnip"), ("Per-person limit", per_person_limit or "Unlimited")])
    await interaction.response.send_message(f"✅ Added **{emoji} {name}** (`{item_id}`) to the shop.", ephemeral=True)


async def autocomplete_shop_item_ids(interaction: discord.Interaction, current: str):
    current = current.lower().strip()
    choices = []
    for item_id, item in ECONOMY_ITEMS.items():
        if current and current not in item_id.lower() and current not in str(item.get("name", "")).lower():
            continue
        choices.append(app_commands.Choice(
            name=f"{str(item.get('name', item_id))[:80]} ({item_id})",
            value=item_id,
        ))
        if len(choices) >= 25:
            break
    return choices


@economy_group.command(name="edit-shop-item", description="Admin: edit a Catnip shop item")
@app_commands.autocomplete(item_id=autocomplete_shop_item_ids)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(item_id="Item ID to edit", name="New name", price="New price", description="New description", per_person_limit="New per-person limit; 0 means unlimited", emoji="New emoji")
async def economy_edit_shop_item_cmd(interaction: discord.Interaction, item_id: str, name: str | None = None, price: int | None = None, description: str | None = None, per_person_limit: int | None = None, emoji: str | None = None):
    item_id = item_id.lower().strip()
    item = ECONOMY_ITEMS.get(item_id)
    if item is None:
        await interaction.response.send_message("❌ That shop item doesn't exist.", ephemeral=True)
        return
    if all(x is None for x in (name, price, description, per_person_limit, emoji)):
        await interaction.response.send_message("❌ Choose at least one property to edit.", ephemeral=True)
        return
    if name is not None: item["name"] = name[:80]
    if price is not None: item["price"] = int(price)
    if description is not None: item["description"] = description[:300]
    if per_person_limit is not None: item["max_per_person"] = int(per_person_limit)
    if emoji is not None: item["emoji"] = emoji[:8]
    await bd_save_data()
    await economy_log(interaction.guild.id, title="✏️ Shop item edited", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Item ID", item_id), ("New name", item["name"]), ("New price", f"{item['price']:,} Catnip"), ("Per-person limit", item.get("max_per_person", 0) or "Unlimited")])
    await interaction.response.send_message(f"✅ Updated **{item['emoji']} {item['name']}** (`{item_id}`).", ephemeral=True)


@economy_group.command(name="remove-item-shop", description="Admin: remove an item from the Catnip shop")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(item_id="Item ID to remove", remove_from_inventories="Whether all copies should also be removed from member inventories")
async def economy_remove_item_shop_cmd(interaction: discord.Interaction, item_id: str, remove_from_inventories: bool = False):
    guild_id = interaction.guild.id
    item_id = item_id.lower().strip()
    item = ECONOMY_ITEMS.get(item_id)
    if item is None:
        await interaction.response.send_message("❌ That shop item doesn't exist.", ephemeral=True)
        return
    removed_inventory = 0
    if remove_from_inventories:
        for (gid, uid), inv in economy_inventory.items():
            if gid == guild_id and item_id in inv:
                removed_inventory += int(inv.pop(item_id, 0))
    ECONOMY_ITEMS.pop(item_id, None)
    await bd_save_data()
    await economy_log(guild_id, title="🗑️ Shop item removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Item", f"{item['emoji']} {item['name']}"), ("ID", item_id), ("Inventory copies removed", removed_inventory), ("Removed from inventories", remove_from_inventories)])
    await interaction.response.send_message(f"🗑️ Removed **{item['name']}** from the shop. " + (f"Also removed **{removed_inventory}** copies from inventories." if remove_from_inventories else "Existing inventory copies were kept."), ephemeral=True)


@economy_group.command(name="add-role-income", description="Admin: give a role a recurring Catnip income")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(role="Role receiving the income", amount="Catnip earned each collection", interval="How many time units between collections", unit="Time unit")
@app_commands.choices(unit=[app_commands.Choice(name="Minutes", value="minute"), app_commands.Choice(name="Hours", value="hour"), app_commands.Choice(name="Days", value="day"), app_commands.Choice(name="Weeks", value="week")])
async def economy_add_role_income_cmd(interaction: discord.Interaction, role: discord.Role, amount: int, interval: int, unit: app_commands.Choice[str]):
    multipliers = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800}
    cooldown = int(interval) * multipliers[unit.value]
    economy_income_roles.setdefault(interaction.guild.id, {})[role.id] = {"amount": int(amount), "cooldown": cooldown, "interval": int(interval), "unit": unit.value}
    await bd_save_data()
    await economy_log(interaction.guild.id, title="💰 Role income added/updated", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Role", f"{role} ({role.id})"), ("Income", f"{amount:,} Catnip / {interval} {unit.name.lower()}")])
    await interaction.response.send_message(f"✅ {role.mention} now provides **{amount:,} Catnip every {interval} {unit.name.lower()}** via `/collect`.", ephemeral=True)


@economy_group.command(name="remove-role-income", description="Admin: remove a role's recurring Catnip income")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(role="Role whose income should be removed")
async def economy_remove_role_income_cmd(interaction: discord.Interaction, role: discord.Role):
    cfg = economy_income_roles.setdefault(interaction.guild.id, {})
    removed = cfg.pop(role.id, None)
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🗑️ Role income removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Role", f"{role} ({role.id})"), ("Was configured", bool(removed))])
    await interaction.response.send_message(f"🗑️ Removed {role.mention} from recurring Catnip income." if removed else f"ℹ️ {role.mention} wasn't configured for income.", ephemeral=True)


@economy_group.command(name="iteminfo", description="Show complete information about a Catnip item")
@app_commands.guild_only()
@app_commands.describe(item="Item ID or item name")
async def economy_iteminfo_cmd(interaction: discord.Interaction, item: str):
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await interaction.response.send_message("❌ That item doesn't exist. Use `/economy shop` to see the item IDs.", ephemeral=True)
        return
    limit = int(data.get("max_per_person", 0))
    embed = discord.Embed(title=f"{data['emoji']} {data['name']}", description=data["description"], color=discord.Color.gold())
    embed.add_field(name="Item ID", value=f"`{item_id}`", inline=True)
    embed.add_field(name="Price", value=f"{data['price']:,} Catnip", inline=True)
    embed.add_field(name="Per-person limit", value=str(limit) if limit else "Unlimited", inline=True)
    await interaction.response.send_message(embed=embed)
    await economy_log(interaction.guild.id, title="🔎 Economy item info viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})"), ("Item", f"{item['name']} (`{item_id}`)")])


@economy_group.command(name="restore-snapshot", description="Restore the latest complete economy snapshot from the economy log channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def economy_restore_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    restored, detail = await economy_restore_from_snapshot(interaction.guild)
    if restored <= 0:
        await interaction.followup.send(f"⚠️ Economy recovery did not restore any users. {detail}", ephemeral=True)
        return
    await economy_log(interaction.guild.id, title="🩹 Economy restored", description=f"Restored {restored} user account(s) from the latest snapshot.", fields=[("Snapshot", detail), ("Restored users", restored)])
    await interaction.followup.send(f"🩹 Economy recovery complete. Restored **{restored}** user account(s) from the latest snapshot (**{detail}**).", ephemeral=True)


bot.tree.add_command(economy_group)


# ---------------------------------------------------------------------------
# Hangry Games — isolated Cog, bolted on at the bottom. Self-contained;
# does not touch any of Cinnamon's state above.
# ---------------------------------------------------------------------------

HG_SOLO_DEATHS = [
    "{p1} got stuck in a cardboard box and was shipped to Abu Dhabi.",
    "{p1} misjudged a jump to the fridge and fell into the abyss.",
    "{p1} got the 3 AM zoomies and ran straight into a closed glass door.",
    "{p1} was hypnotized by a laser pointer and wandered off a cliff.",
    "{p1} forgot how to land on their feet.",
    "{p1} was startled by a cucumber and had a fatal heart attack.",
    "{p1} got stuck climbing the curtains and never came down.",
    "{p1} tried to catch a spicy fly (wasp) and lost.",
    "{p1} fell asleep on a warm laptop and melted into a puddle.",
    "{p1} inhaled too much catnip and ascended to another plane of existence.",
    "{p1} fell into a bathtub full of water.",
    "{p1} sneezed too hard and exploded.",
    "{p1} refused to use the new litter box and imploded from spite.",
    "{p1} jumped after a bird through a closed window.",
    "{p1} choked on a furball the size of a tennis ball.",
    "{p1} got their claw stuck in the carpet and starved to death.",
    "{p1} fell into the trash can and was taken out with the garbage.",
    "{p1} chased a fly right into a wall.",
    "{p1} tried to jump on the TV and pulled it down on themselves.",
    "{p1} got trapped inside a pillowcase.",
    "{p1} licked a spicy pepper that fell on the kitchen floor.",
    "{p1} got tangled in the window blinds.",
    "{p1} tried to sleep in a frying pan and cooked.",
    "{p1} smelled a sock and passed out forever.",
    "{p1} saw their own shadow and died of fright.",
    "{p1} tried to eat a fake plastic plant.",
    "{p1} jumped into a box of packing peanuts and disappeared.",
    "{p1} got their head stuck in a tissue box.",
    "{p1} slipped on a wet countertop and went flying.",
    "{p1} heard a loud noise and phased out of reality.",
    "{p1} tried to catch a snowflake and froze.",
    "{p1} got lost underneath the bed forever.",
    "{p1} fell asleep on the radiator.",
    "{p1} watched the washing machine spin until they got dizzy and perished.",
    "{p1} tried to drink from the fish tank and fell in."
]

HG_DUO_DEATHS = [
    "{p2} ate all the tuna, leaving {p1} to starve.",
    "{p1} ate all the tuna, so {p2} pushed them out a window.",
    "{p1} was swatted off the kitchen counter by {p2}.",
    "{p2} stole {p1}'s Churu, leading to a fatal heartbreak.",
    "{p2} pushed {p1} down the stairs while maintaining direct eye contact.",
    "{p2} ambushed {p1} from under the sofa with lethal force.",
    "{p2} challenged {p1} to a staring contest; {p1} spontaneously combusted.",
    "{p2} accidentally locked {p1} in the closet for a month.",
    "{p2} forced {p1} to take a bath, causing a total system failure.",
    "{p2} stole {p1}'s warm sunbeam, freezing them to death.",
    "{p2} betrayed {p1} for a single piece of premium kibble.",
    "{p2} convinced {p1} that the vacuum cleaner was friendly.",
    "{p2} framed {p1} for scratching the good sofa, leading to permanent exile.",
    "{p2} convinced {p1} that the neighborhood dog wanted to play.",
    "{p2} dropped a heavy potted plant directly onto {p1}.",
    "{p2} refused to share the heating pad, and {p1} froze.",
    "{p1} tried to steal {p2}'s toy mouse and caught these paws.",
    "{p2} lured {p1} into a cardboard box and mailed them to Antarctica.",
    "{p2} closed the door right as {p1} was walking through it.",
    "{p2} sneaked up and popped a paper bag behind {p1}, giving them a heart attack.",
    "{p2} stared at {p1} until {p1} forgot how to breathe.",
    "{p1} fell asleep, and {p2} piled heavy laundry on them.",
    "{p2} swatted {p1} right into the spinning ceiling fan.",
    "{p1} looked away for one second, and {p2} struck.",
    "{p2} told {p1} the laser pointer was real; {p1} ran into traffic.",
    "{p2} pushed {p1} right into the dreaded Roomba's path.",
    "{p2} weaponized a cucumber against {p1}.",
    "{p2} sat on {p1}'s face while they were sleeping.",
    "{p1} tried to groom {p2} but got their throat bitten instead.",
    "{p2} trapped {p1} under a laundry basket forever.",
    "{p2} claimed the highest cat tree perch and Sparta-kicked {p1} off of it.",
    "{p1} complained about the food, so {p2} made them the food.",
    "{p1} let their guard down, and {p2} pounced from the shadows.",
    "{p2} aggressively made biscuits on {p1}'s vital organs.",
    "{p2} convinced {p1} to jump into the empty bathtub, then turned on the faucet.",
    "{p2} 'accidentally' knocked a heavy vase directly onto {p1}.",
    "{p1} tripped over {p2} during the 3 AM zoomies and flew out the window.",
    "{p1} tried to steal a bite of {p2}'s wet food and was instantly vaporized.",
    "{p2} told {p1} the vet clinic was a spa. {p1} never returned.",
    "{p2} hissed at {p1} so aggressively that {p1}'s soul left their body.",
    "{p1} was sleeping peacefully until {p2} used their face as a trampoline.",
    "{p2} knocked a flat-screen TV onto {p1} just to see what would happen.",
    "{p2} pushed {p1} into a room full of toddlers and locked the door.",
    "{p1} playfully bit {p2}'s tail and was swiftly eradicated.",
    "{p2} dragged {p1} into the dreaded cat carrier of doom.",
    "{p2} refused to let {p1} use the clean litter box, resulting in a fatal implosion.",
    "{p1} sniffed {p2}'s unwashed paws and passed out forever.",
    "{p2} used {p1} as a scratching post.",
    "{p1} thought {p2} wanted to cuddle, but it was a bunny-kick death trap.",
    "{p2} dropped a live spider on {p1}'s nose, causing a fatal panic attack.",
    "{p2} tricked {p1} into eating the spicy dog kibble.",
    "{p2} sat directly on {p1} and refused to get up until it was too late.",
    "{p2} challenged {p1} to a race down the stairs and tripped them on step two.",
    "{p2} hypnotized {p1} with a swinging pocket watch and ordered them to walk into the fridge.",
    "{p2} told {p1} the red dot was real, sending them straight into a wall.",
    "{p2} pushed {p1} off the bed for taking up too much space.",
    "{p2} tricked {p1} into jumping onto a ceiling fan.",
    "{p1} tried to sneak up on {p2}, but received a swift ninja kick to the face.",
    "{p2} meowed aggressively until {p1}'s ears exploded.",
    "{p1} stole {p2}'s favorite feather toy and paid the ultimate price.",
    "{p2} locked {p1} outside in the rain.",
    "{p2} dropped a half-eaten mouse on {p1}'s face.",
    "{p1} refused to groom {p2} and was promptly banished to the shadow realm.",
    "{p2} body-slammed {p1} from the top of the fridge.",
    "{p1} sneezed, and {p2} took it as a declaration of war.",
    "{p2} swiped {p1}'s nose, causing a fatal system reboot.",
    "{p1} tried to share {p2}'s hammock and was violently evicted.",
    "{p2} convinced {p1} to jump into the toilet bowl.",
    "{p1} interrupted {p2}'s bath time and was destroyed.",
    "{p2} bit {p1}'s ear a little too hard during playtime.",
    "{p2} led {p1} into a room with a closed door, trapping them forever.",
    "{p1} got caught sniffing {p2}'s food bowl.",
    "{p2} swatted {p1} into the dreaded dog's territory.",
    "{p2} tricked {p1} into sniffing a lemon.",
    "{p1} stared at {p2} for too long and spontaneously combusted.",
    "{p2} pushed {p1} into a full bathtub while they were sleeping.",
    "{p1} tried to groom {p2}'s belly, a fatal mistake.",
    "{p2} performed a perfect wrestling takedown on {p1}.",
    "{p2} shoved {p1} off the windowsill.",
    "{p1} thought {p2} was asleep, but {p2} was just waiting to strike.",
    "{p2} trapped {p1} in the laundry basket and sat on the lid.",
    "{p1} took a bite of {p2}'s cat grass and was obliterated.",
    "{p2} convinced {p1} that the vet was just giving out free treats.",
    "{p1} tried to steal {p2}'s collar.",
    "{p2} lured {p1} into a pile of catnip and watched them transcend reality.",
    "{p2} told {p1} the vacuum cleaner was a friend.",
    "{p1} got jump-scared by {p2} and had a heart attack.",
    "{p2} sat on {p1}'s favorite toy until {p1} died of a broken heart.",
    "{p2} tackled {p1} down the hallway.",
    "{p1} tried to walk past {p2} in a narrow hallway.",
    "{p2} pushed {p1} into the empty pool.",
    "{p1} looked at {p2} funny.",
    "{p2} convinced {p1} to chase a laser pointer out the front door.",
    "{p1} sneaked up on {p2} and was roundhouse kicked.",
    "{p2} threw a toy mouse so hard it knocked {p1} out cold.",
    "{p1} refused to wake up, so {p2} used the heavy paws.",
    "{p2} trapped {p1} in a corner and booped them to death.",
    "{p2} lured {p1} into a trap made of cardboard boxes.",
    "{p1} tried to play with {p2}'s tail and was incinerated.",
    "{p2} forced {p1} to listen to the neighbor's dog barking.",
    "{p1} was buried under a mountain of pillows by {p2}.",
    "{p2} showed {p1} a mirror, causing a fatal existential crisis.",
    "{p1} drank from {p2}'s water bowl.",
    "{p2} pushed {p1} into a pile of wet laundry."
]

HG_SURVIVALS = [
    "{p1} took a nice long nap in a sunbeam.",
    "{p1} successfully begged for extra tuna.",
    "{p1} knocked a glass off the table and felt great about it.",
    "{p1} hid under the sofa all day and survived.",
    "{p1} made biscuits on a soft blanket.",
    "{p1} purred loudly to assert dominance.",
    "{p1} found a secret stash of treats and feasted.",
    "{p1} successfully ignored all humans for 24 hours.",
    "{p1} slept inside a warm laundry basket.",
    "{p1} caught the red dot!",
    "{p1} stared out the window at birds all day.",
    "{p1} received excellent chin scritches.",
    "{p1} successfully woke their owner up at 4 AM for food.",
    "{p1} found the perfect empty cardboard box.",
    "{p1} knocked a pen off the desk and survived to tell the tale.",
    "{p1} bathed perfectly in a square of sunlight.",
    "{p1} got a fresh bowl of cold water.",
    "{p1} performed a perfect loaf on the couch.",
    "{p1} successfully camouflaged themselves on a rug.",
    "{p1} found a discarded bottle cap and played with it for hours.",
    "{p1} stretched really, really far.",
    "{p1} watched a spider crawl across the ceiling peacefully.",
    "{p1} got brushed and purred like a motor.",
    "{p1} claimed the highest spot on the cat tree.",
    "{p1} sniffed the air and decided everything was fine.",
    "{p1} successfully avoided the vacuum cleaner."
]


HG_DATA_FILE = os.environ.get("HANGRY_GAMES_DATA_FILE", "hangry_games_data.json")
HG_UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
HG_UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
HG_REDIS_KEY = "hangry_games_data"


def _hg_decode(raw: dict) -> dict:
    pair = lambda d: {tuple(map(int, k.split(":"))): v for k, v in d.items()}
    return {
        "game_counts": {int(k): v for k, v in raw.get("game_counts", {}).items()},
        "win_counts": pair(raw.get("win_counts", {})),
        "kill_counts": pair(raw.get("kill_counts", {})),
        "played_counts": pair(raw.get("played_counts", {})),
        "log_channels": {int(k): v for k, v in raw.get("log_channels", {}).items()},
        "log_enabled": {int(k): v for k, v in raw.get("log_enabled", {}).items()},
    }


def _hg_encode(state: dict) -> dict:
    pair = lambda d: {f"{g}:{m}": v for (g, m), v in d.items()}
    return {
        "game_counts": {str(k): v for k, v in state["game_counts"].items()},
        "win_counts": pair(state["win_counts"]),
        "kill_counts": pair(state["kill_counts"]),
        "played_counts": pair(state["played_counts"]),
        "log_channels": {str(k): v for k, v in state["log_channels"].items()},
        "log_enabled": {str(k): v for k, v in state["log_enabled"].items()},
    }


async def hg_load_data() -> dict:
    """Load persisted game/win counts and the dedicated Hangry Games log channel.
    Uses Upstash Redis (survives redeploys on hosts with no persistent disk, e.g.
    Render free tier) when UPSTASH_REDIS_REST_URL/UPSTASH_REDIS_REST_TOKEN are
    set; otherwise falls back to a local JSON file (only survives plain
    restarts, not redeploys, on most free hosts). Never raises — a missing/
    corrupt/unreachable store just means we start fresh."""
    empty = _hg_decode({})
    if HG_UPSTASH_URL and HG_UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    HG_UPSTASH_URL, json=["GET", HG_REDIS_KEY],
                    headers={"Authorization": f"Bearer {HG_UPSTASH_TOKEN}"},
                ) as resp:
                    result = (await resp.json()).get("result")
            return _hg_decode(json.loads(result)) if result else empty
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, ValueError) as e:
            log.error(f"Failed to load Hangry Games data from Upstash: {e}")
            return empty
    try:
        with open(HG_DATA_FILE, "r") as f:
            return _hg_decode(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return empty


async def hg_save_data(state: dict):
    """Persist Hangry Games state (counts, stats, log settings). See hg_load_data
    for storage choice. Never raises — a failed save shouldn't crash a game."""
    encoded = _hg_encode(state)
    if HG_UPSTASH_URL and HG_UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    HG_UPSTASH_URL, json=["SET", HG_REDIS_KEY, json.dumps(encoded)],
                    headers={"Authorization": f"Bearer {HG_UPSTASH_TOKEN}"},
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.error(f"Failed to save Hangry Games data to Upstash: {e}")
        return
    try:
        with open(HG_DATA_FILE, "w") as f:
            json.dump(encoded, f)
    except OSError as e:
        log.error(f"Failed to save Hangry Games data: {e}")


class HGLobbyView(discord.ui.View):
    def __init__(self, cog: "HangryGamesCog", host: discord.Member, prize: str | None = None,
                 winner_role: discord.Role | None = None):
        super().__init__(timeout=600)
        self.cog = cog
        self.host = host
        self.prize = prize
        self.winner_role = winner_role
        self.players: dict[int, discord.Member] = {}
        self.started = False
        self.message: discord.Message | None = None

    def embed(self) -> discord.Embed:
        title = "🐾 Hangry Games — Giveaway" if self.prize else "🐾 Hangry Games"
        names = "\n".join(m.display_name for m in self.players.values()) or "*(none yet)*"
        desc = f"Host: {self.host.mention}\nTap **Join 🐾** to enter — no backing out!\n\n**Players:**\n{names}"
        if self.prize:
            desc += f"\n\n**Prize:** {self.prize}"
        return discord.Embed(title=title, description=desc, color=0xFFB02E)

    @discord.ui.button(label="Join 🐾", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.started:
            return await interaction.response.send_message("Already started!", ephemeral=True)
        if interaction.user.id in self.players:
            return await interaction.response.send_message("You're already in — no backing out!", ephemeral=True)
        self.players[interaction.user.id] = interaction.user
        await interaction.response.edit_message(embed=self.embed(), view=self)
        await self.cog._log(interaction.guild.id, title="🐾 Hangry Games player joined",
                            fields=[("Channel", interaction.channel.mention), ("Player", f"{interaction.user} ({interaction.user.id})"),
                                    ("Players", str(len(self.players)))])

    @discord.ui.button(label="Start 🔴", style=discord.ButtonStyle.danger)
    async def start(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Need Manage Messages to start.", ephemeral=True)
        if len(self.players) < 2:
            return await interaction.response.send_message("Need at least 2 players.", ephemeral=True)
        self.started = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(embed=self.embed(), view=self)
        self.stop()
        self.cog.lobbies.pop(interaction.channel.id, None)
        await self.cog.launch(interaction.channel, self.players, self.host, self.prize, self.winner_role)

    async def on_timeout(self):
        if self.started or not self.message:
            return
        for c in self.children:
            c.disabled = True
        self.cog.lobbies.pop(self.message.channel.id, None)
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass
        await self.cog._log(
            self.host.guild.id, title="⏰ Hangry Games lobby timed out", color=discord.Color.orange(),
            fields=[("Channel", self.message.channel.mention), ("Host", f"{self.host} ({self.host.id})"),
                    ("Players signed up", str(len(self.players)))],
        )


class HGRematchView(discord.ui.View):
    """Button under the winner embed: the host (or a mod) restarts with the same cats."""

    def __init__(self, cog: "HangryGamesCog", players: dict[int, discord.Member], host: discord.Member):
        super().__init__(timeout=300)
        self.cog, self.players, self.host = cog, players, host
        self.message: discord.Message | None = None

    @discord.ui.button(label="Rematch 🔁", style=discord.ButtonStyle.primary)
    async def rematch(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.host.id and not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Only the host or a mod can start a rematch.", ephemeral=True)
        if self.cog._busy(interaction.channel.id):
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        for c in self.children:
            c.disabled = True
        self.stop()
        await interaction.response.edit_message(view=self)
        await self.cog.launch(interaction.channel, dict(self.players), self.host, None, None)

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class HangryGamesCog(commands.GroupCog, group_name="hangrygames"):
    """Play a cat-themed elimination minigame"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active: dict[int, asyncio.Task] = {}
        self.lobbies: dict[int, "HGLobbyView"] = {}  # channel_id -> lobby not yet started
        self.game_counts: dict[int, int] = {}  # guild_id -> total games run
        self.win_counts: dict[tuple[int, int], int] = {}  # (guild_id, member_id) -> total wins
        self.kill_counts: dict[tuple[int, int], int] = {}  # (guild_id, member_id) -> total kills (completed games)
        self.played_counts: dict[tuple[int, int], int] = {}  # (guild_id, member_id) -> completed games played
        self.hg_log_channels: dict[int, int] = {}  # guild_id -> dedicated Hangry Games log channel_id
        self.log_enabled: dict[int, bool] = {}  # guild_id -> whether HG activity is logged (default: on once a channel is set)

    async def async_init(self):
        """Load persisted counts. Call once, before add_cog, since __init__ can't await."""
        data = await hg_load_data()
        self.game_counts = data["game_counts"]
        self.win_counts = data["win_counts"]
        self.kill_counts = data["kill_counts"]
        self.played_counts = data["played_counts"]
        self.hg_log_channels = data["log_channels"]
        self.log_enabled = data["log_enabled"]

    async def _save(self):
        await hg_save_data({
            "game_counts": self.game_counts, "win_counts": self.win_counts,
            "kill_counts": self.kill_counts, "played_counts": self.played_counts,
            "log_channels": self.hg_log_channels, "log_enabled": self.log_enabled,
        })

    async def _log(self, guild_id: int, *, title: str, color: discord.Color = discord.Color.blurple(),
                    fields: list[tuple[str, str]] | None = None):
        """Post a Hangry Games event to this guild's dedicated log channel
        (set via /hangrygames logchannel), unless logging's been turned off."""
        if not self.log_enabled.get(guild_id, True):
            return
        channel_id = self.hg_log_channels.get(guild_id)
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return
        embed = discord.Embed(title=title, color=color, timestamp=datetime.datetime.now(datetime.timezone.utc))
        for name, value in (fields or []):
            embed.add_field(name=name, value=value, inline=True)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            log.warning(f"Failed to post Hangry Games log: {e}")

    async def recover_from_log(self, guild: discord.Guild, limit: int = 2000) -> tuple[int, int]:
        """Rebuild this guild's game count and win totals from its Hangry Games
        log channel's message history — used when the persisted store comes back
        empty for a guild that has a log channel configured. Best-effort, bounded
        by `limit` messages and Discord's own retention. Returns
        (reconstructed_game_count, wins_reconstructed)."""
        channel_id = self.hg_log_channels.get(guild.id)
        if channel_id is None:
            return (0, 0)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return (0, 0)

        max_game_num = 0
        wins: list[int] = []  # winner_id per win found
        game_num_re = re.compile(r"Hangry Games #(\d+)")
        id_re = re.compile(r"\((\d+)\)\s*$")
        try:
            async for message in channel.history(limit=limit):
                for embed in message.embeds:
                    if not embed.title:
                        continue
                    m = game_num_re.search(embed.title)
                    if not m:
                        continue
                    max_game_num = max(max_game_num, int(m.group(1)))
                    if embed.title.startswith("🏆 Hangry Games"):
                        fields = {f.name: f.value for f in embed.fields}
                        wm = id_re.search(fields.get("Winner", ""))
                        if wm:
                            wins.append(int(wm.group(1)))
        except discord.HTTPException as e:
            log.error(f"Failed to scan Hangry Games log channel for recovery in guild {guild.id}: {e}")
            return (0, 0)

        if max_game_num:
            self.game_counts[guild.id] = max_game_num
        wins_by_member = defaultdict(int)
        for winner_id in wins:
            wins_by_member[winner_id] += 1
        for winner_id, recovered_total in wins_by_member.items():
            key = (guild.id, winner_id)
            self.win_counts[key] = max(self.win_counts.get(key, 0), recovered_total)
        if max_game_num or wins:
            await self._save()
        return (max_game_num, len(wins))

    async def launch(self, channel: discord.abc.Messageable, players: dict[int, discord.Member],
                      host: discord.Member, prize: str | None, winner_role: discord.Role | None = None):
        self.game_counts[channel.guild.id] = self.game_counts.get(channel.guild.id, 0) + 1
        game_num = self.game_counts[channel.guild.id]
        await self._save()
        task = asyncio.create_task(self.run_game(channel, players, host, prize, game_num, winner_role))
        self.active[channel.id] = task

        fields = [
            ("Channel", channel.mention), ("Host", f"{host} ({host.id})"),
            ("Players", str(len(players))),
        ]
        if prize:
            fields.append(("Prize", prize))
        if winner_role:
            fields.append(("Winner role", winner_role.name))
        await self._log(
            channel.guild.id, title=f"🐾 Hangry Games #{game_num} started", color=discord.Color.gold(),
            fields=fields,
        )

    async def run_game(self, channel: discord.abc.Messageable, players: dict[int, discord.Member],
                        host: discord.Member, prize: str | None, game_num: int,
                        winner_role: discord.Role | None = None):
        alive = dict(players)
        kills: dict[int, int] = {pid: 0 for pid in alive}
        start = time.monotonic()
        rnd = 0
        await channel.send(f"🐾 **Hangry Games #{game_num}** begins with **{len(alive)}** cats in the arena, hosted by {host.mention}!")
        try:
            while len(alive) > 1:
                rnd += 1
                await asyncio.sleep(5)
                ids = list(alive.keys())
                embed = discord.Embed(color=0xFFB02E)
                embed.set_footer(text=f"Game #{game_num} · Round {rnd}")
                roll = random.random()

                if roll < 0.85:
                    p1_id, p2_id = random.sample(ids, 2)
                    p1, p2 = alive[p1_id], alive[p2_id]
                    content = f"{p1.mention} {p2.mention}"
                    embed.description = f"⚔️ {random.choice(HG_DUO_DEATHS).format(p1=p1.display_name, p2=p2.display_name)}"
                    embed.set_thumbnail(url=p1.display_avatar.url)
                    embed.set_image(url=p2.display_avatar.url)
                    kills[p2_id] = kills.get(p2_id, 0) + 1
                    del alive[p1_id]
                elif roll < 0.925:
                    p1_id = random.choice(ids)
                    p1 = alive[p1_id]
                    content = p1.mention
                    embed.title = "🐾 A cat-astrophe occurred! 🙀"
                    embed.description = f"👉 {random.choice(HG_SOLO_DEATHS).format(p1=p1.display_name)}"
                    embed.set_image(url=p1.display_avatar.url)
                    del alive[p1_id]
                else:
                    p1_id = random.choice(ids)
                    p1 = alive[p1_id]
                    content = p1.mention
                    embed.title = "🐾 A cat-astrophe occurred! 🙀"
                    embed.description = f"👉 {random.choice(HG_SURVIVALS).format(p1=p1.display_name)}"
                    embed.set_image(url=p1.display_avatar.url)

                if rnd % 5 == 0:
                    survivors = "\n".join(m.display_name for m in alive.values()) or "None"
                    embed.add_field(name="Survivors", value=survivors, inline=False)

                await channel.send(content=content, embed=embed)

            winner_id, winner = next(iter(alive.items())) if alive else (None, None)
            winner_kills = kills.get(winner_id, 0)
            elapsed = int(time.monotonic() - start)
            mm, ss = divmod(elapsed, 60)

            win_key = (channel.guild.id, winner_id)
            self.win_counts[win_key] = self.win_counts.get(win_key, 0) + 1
            total_wins = self.win_counts[win_key]
            for pid, k in kills.items():
                pkey = (channel.guild.id, pid)
                self.played_counts[pkey] = self.played_counts.get(pkey, 0) + 1
                if k:
                    self.kill_counts[pkey] = self.kill_counts.get(pkey, 0) + k
            await self._save()

            desc = f"🎉 **{winner.display_name}** won **{host.display_name}**'s Hangry Games"
            if prize:
                desc += f" and **{prize}**"
            desc += "!\n"
            desc += f"💀 **Total kills:** {winner_kills}\n"
            desc += f"⏱️ **Time survived:** {mm}m {ss}s\n"
            desc += f"🏆 **Total wins in server:** {total_wins}"

            if winner_role:
                try:
                    await winner.add_roles(winner_role, reason=f"Won Hangry Games #{game_num}")
                    desc += f"\n🎗️ **{winner.display_name}** was crowned with the **{winner_role.name}** role!"
                except discord.HTTPException:
                    pass

            winner_embed = discord.Embed(title="🏆 Winner!", color=0xFEE75C, description=desc)
            winner_embed.set_image(url=winner.display_avatar.url)
            winner_embed.set_footer(text=f"Game #{game_num}")
            rematch = HGRematchView(self, players, host)
            rematch.message = await channel.send(
                content=winner.mention, embed=winner_embed, view=rematch,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False),
            )

            log_fields = [
                ("Channel", channel.mention), ("Host", f"{host} ({host.id})"),
                ("Winner", f"{winner} ({winner.id})"), ("Kills", str(winner_kills)),
                ("Time survived", f"{mm}m {ss}s"), ("Total wins (server)", str(total_wins)),
            ]
            if prize:
                log_fields.append(("Prize", prize))
            if winner_role:
                log_fields.append(("Winner role", winner_role.name))
            await self._log(
                channel.guild.id, title=f"🏆 Hangry Games #{game_num} ended", color=discord.Color.gold(),
                fields=log_fields,
            )
        except asyncio.CancelledError:
            await channel.send(
                f"🙀 *the arena collapses mid-brawl!* Hangry Games #{game_num} was cancelled — "
                f"no winner this time, you scaredy-cats."
            )
            await self._log(
                channel.guild.id, title=f"🚫 Hangry Games #{game_num} cancelled mid-game",
                color=discord.Color.red(),
                fields=[("Channel", channel.mention), ("Host", f"{host} ({host.id})"),
                        ("Players remaining", str(len(alive)))],
            )
        finally:
            self.active.pop(channel.id, None)

    def _busy(self, channel_id: int) -> bool:
        return channel_id in self.active or channel_id in self.lobbies

    @app_commands.command(name="new", description="Start a Hangry Games lobby")
    @app_commands.describe(host="Who's hosting (defaults to you)")
    @app_commands.guild_only()
    async def new(self, interaction: discord.Interaction, host: discord.Member = None):
        if self._busy(interaction.channel.id):
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        view = HGLobbyView(self, host or interaction.user)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()
        self.lobbies[interaction.channel.id] = view
        await self._log(interaction.guild.id, title="🐾 Hangry Games lobby created",
                        fields=[("Channel", interaction.channel.mention), ("Host", f"{view.host} ({view.host.id})"), ("Mode", "Normal")])

    @app_commands.command(name="giveaway", description="Run a Hangry Games giveaway")
    @app_commands.describe(prize="What the winner takes home (optional)", host="Who's hosting (defaults to you)",
                            winner_role="Role to give the winner (optional)")
    @app_commands.guild_only()
    async def giveaway(self, interaction: discord.Interaction, prize: str = None, host: discord.Member = None,
                        winner_role: discord.Role = None):
        if self._busy(interaction.channel.id):
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        view = HGLobbyView(self, host or interaction.user, prize=prize, winner_role=winner_role)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()
        self.lobbies[interaction.channel.id] = view
        await self._log(interaction.guild.id, title="🐾 Hangry Games giveaway lobby created",
                        fields=[("Channel", interaction.channel.mention), ("Host", f"{view.host} ({view.host.id})"),
                                ("Prize", str(prize)[:900] if prize else "None"),
                                ("Winner role", winner_role.name if winner_role else "None")])

    @app_commands.command(name="role", description="Auto-start a game with everyone who has a role")
    @app_commands.describe(role="The role to pull players from", prize="What the winner takes home (optional)",
                            host="Who's hosting (defaults to you)", winner_role="Role to give the winner (optional)")
    @app_commands.guild_only()
    async def role_cmd(self, interaction: discord.Interaction, role: discord.Role, prize: str = None,
                        host: discord.Member = None, winner_role: discord.Role = None):
        if self._busy(interaction.channel.id):
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        players = {m.id: m for m in role.members if not m.bot}
        if len(players) < 2:
            return await interaction.response.send_message(
                "Need at least 2 non-bot members with that role.", ephemeral=True
            )
        host = host or interaction.user
        await interaction.response.send_message(
            f"🐾 **{len(players)}** cats from **{role.name}** enter the arena, hosted by {host.mention}!",
            allowed_mentions=discord.AllowedMentions(roles=False),
        )
        await self._log(interaction.guild.id, title="🐾 Hangry Games role launch",
                        fields=[("Channel", interaction.channel.mention), ("Role", f"{role.name} ({role.id})"),
                                ("Players", str(len(players))), ("Host", f"{host} ({host.id})")])
        await self.launch(interaction.channel, players, host, prize, winner_role)

    @app_commands.command(name="leaderboard", description="Top Hangry Games winners in this server")
    @app_commands.guild_only()
    async def hg_leaderboard(self, interaction: discord.Interaction):
        gid = interaction.guild.id
        top = sorted(((m, w) for (g, m), w in self.win_counts.items() if g == gid), key=lambda e: e[1], reverse=True)[:10]
        if not top:
            return await interaction.response.send_message("No Hangry Games winners yet. 🐾", ephemeral=True)
        lines = []
        for i, (uid, wins) in enumerate(top, 1):
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"
            kills = self.kill_counts.get((gid, uid), 0)
            lines.append(f"**#{i}** {name} — {wins} win(s), {kills} kill(s)")
        embed = discord.Embed(title="🏆 Hangry Games Leaderboard", description="\n".join(lines), color=0xFEE75C)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="stats", description="A member's Hangry Games stats")
    @app_commands.describe(member="Who to check (defaults to you)")
    @app_commands.guild_only()
    async def hg_stats(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        gid, key = interaction.guild.id, (interaction.guild.id, member.id)
        wins, kills = self.win_counts.get(key, 0), self.kill_counts.get(key, 0)
        played = self.played_counts.get(key, 0)
        ranked = sorted({m: w for (g, m), w in self.win_counts.items() if g == gid}.items(), key=lambda e: e[1], reverse=True)
        place = next((i for i, (m, _) in enumerate(ranked, 1) if m == member.id), None)
        embed = discord.Embed(title=f"🐾 {member.display_name}'s Hangry Games stats", color=0xFFB02E)
        embed.add_field(name="Wins", value=str(wins), inline=True)
        embed.add_field(name="Kills", value=str(kills), inline=True)
        embed.add_field(name="Games played", value=str(played) if played else "—", inline=True)
        embed.add_field(name="Win rate", value=f"{wins / played:.0%}" if played else "—", inline=True)
        embed.add_field(name="Server rank", value=f"#{place}" if place else "Unranked", inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Kills and games played count from completed games since stats tracking began.")
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="cancel", description="Cancel the Hangry Games running in this channel")
    @app_commands.guild_only()
    async def cancel(self, interaction: discord.Interaction):
        task = self.active.pop(interaction.channel.id, None)
        if task:
            task.cancel()
            return await interaction.response.send_message(
                "🐾 *pulls the emergency lever* Calling off the Hangry Games mid-fight!"
            )

        lobby = self.lobbies.pop(interaction.channel.id, None)
        if lobby:
            lobby.started = True  # blocks a stray Join/Start click racing the cancel
            for c in lobby.children:
                c.disabled = True
            lobby.stop()
            if lobby.message:
                try:
                    await lobby.message.edit(view=lobby)
                except discord.HTTPException:
                    pass
            await self._log(
                interaction.guild.id, title="🚫 Hangry Games lobby cancelled", color=discord.Color.red(),
                fields=[("Channel", interaction.channel.mention), ("Host", f"{lobby.host} ({lobby.host.id})"),
                        ("Cancelled by", f"{interaction.user} ({interaction.user.id})"),
                        ("Players signed up", str(len(lobby.players)))],
            )
            return await interaction.response.send_message(
                "🐾 *knocks the lobby sign-up sheet off the table* The Hangry Games were cancelled before they even began!"
            )

        await interaction.response.send_message("No game running here.", ephemeral=True)

    @app_commands.command(name="logchannel", description="Set (or reset) this channel as Hangry Games' dedicated log channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def hg_logchannel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        target = channel or interaction.channel
        guild_id = interaction.guild.id

        self.hg_log_channels[guild_id] = target.id
        self.log_enabled[guild_id] = True
        await secure_log_channel(target)

        # Fresh start: reset this server's game number back to 1 and wipe its win totals.
        self.game_counts.pop(guild_id, None)
        self.win_counts = {k: v for k, v in self.win_counts.items() if k[0] != guild_id}
        await self._save()

        await interaction.response.send_message(
            f"🐾 Hangry Games will now log to {target.mention}. Game numbers and win totals for this "
            f"server have been reset — the next game will be **Game #1**.",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self._log(
            guild_id, title="🐾 Hangry Games log channel set", color=discord.Color.gold(),
            fields=[("Channel", target.mention), ("Set by", f"{interaction.user} ({interaction.user.id})")],
        )

    @app_commands.command(name="disablelogchannel", description="Stop Hangry Games from posting logs anywhere in this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def hg_disablelogchannel(self, interaction: discord.Interaction):
        removed = self.hg_log_channels.pop(interaction.guild.id, None)
        self.log_enabled.pop(interaction.guild.id, None)
        await self._save()
        if removed is None:
            return await interaction.response.send_message("No Hangry Games log channel was set.", ephemeral=True)
        await interaction.response.send_message("🐾 Hangry Games log channel disabled. Game numbers and win totals are unaffected.")

    @app_commands.command(name="log", description="Turn Hangry Games activity logging on/off without changing the channel")
    @app_commands.describe(enabled="On: log game starts, winners, and cancellations to the log channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def log_toggle(self, interaction: discord.Interaction, enabled: bool):
        if interaction.guild.id not in self.hg_log_channels:
            return await interaction.response.send_message(
                "Set a Hangry Games log channel first with `/hangrygames logchannel`, then toggle this.",
                ephemeral=True,
            )
        self.log_enabled[interaction.guild.id] = enabled
        await self._save()
        state = "on" if enabled else "off"
        await interaction.response.send_message(f"🐾 Hangry Games logging turned **{state}**.", ephemeral=True)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(DISCORD_TOKEN)
