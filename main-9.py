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
     by username; message content is needed for the AI chat and auto-mod.
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

# In-memory only (session state — fine to lose on restart):
afk_users = {}                          # (guild_id, user_id) -> reason
xp_cooldowns = {}                       # (guild_id, user_id) -> monotonic time of last XP award
spam_tracker = defaultdict(lambda: deque(maxlen=6))   # (guild_id, user_id) -> recent message timestamps
join_log = defaultdict(lambda: deque(maxlen=20))      # guild_id -> recent member-join timestamps (anti-raid)
active_giveaways = {}                   # message_id -> {"view": GiveawayView}

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

bot = commands.Bot(command_prefix="!", intents=intents)


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


async def send_log(guild_id: int | None, *, title: str, description: str = "",
                    color: discord.Color = discord.Color.blurple(),
                    interaction: discord.Interaction | None = None,
                    fields: list[tuple[str, str]] | None = None):
    """Post an embed to the guild's configured log channel, if any. Never raises —
    logging should never be the thing that breaks a command."""
    if guild_id is None:
        return
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


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.guild:
        # --- AFK: clear the sender's own status, and flag anyone AFK they pinged ---
        afk_key = (message.guild.id, message.author.id)
        if afk_key in afk_users:
            del afk_users[afk_key]
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
            await message.reply(reply, mention_author=False)

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
    if removed:
        await interaction.response.send_message("*closes the logbook* Stopped logging actions for this server.")
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
    await interaction.response.send_message(f"*escorts {member.mention} out with a paw* Kicked. Reason: {reason}")
    await send_log(
        interaction.guild.id, title="👢 Member kicked", color=discord.Color.orange(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})"), ("Reason", reason)],
    )


@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Who to ban", reason="Why are they being banned?")
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member,
              reason: app_commands.Range[str, 1, 300] = "No reason given"):
    await member.ban(reason=reason, delete_message_seconds=0)
    await interaction.response.send_message(f"*hisses and swats {member.mention} out the door* Banned. Reason: {reason}")
    await send_log(
        interaction.guild.id, title="🔨 Member banned", color=discord.Color.red(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})"), ("Reason", reason)],
    )


@bot.tree.command(name="unban", description="Unban a user using their user ID")
@app_commands.describe(user_id="The numeric ID of the user to unban")
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        await interaction.guild.unban(discord.Object(id=int(user_id)))
        if temp_bans.pop((interaction.guild.id, int(user_id)), None) is not None:  # was also a tempban
            await bd_save_data()
        await interaction.response.send_message(f"*nudges the door back open* Unbanned <@{user_id}>.")
        await send_log(
            interaction.guild.id, title="🔓 Member unbanned", color=discord.Color.green(), interaction=interaction,
            fields=[("User ID", user_id)],
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
async def mute(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320] = 10,
               reason: app_commands.Range[str, 1, 300] = "No reason given"):
    await member.timeout(datetime.timedelta(minutes=minutes), reason=reason)
    await interaction.response.send_message(
        f"*sits on {member.mention}'s keyboard* Muted for {minutes} minute(s). Reason: {reason}"
    )
    await send_log(
        interaction.guild.id, title="🔇 Member muted", color=discord.Color.orange(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})"), ("Duration", f"{minutes} min"), ("Reason", reason)],
    )


@bot.tree.command(name="unmute", description="Remove a member's timeout early")
@app_commands.describe(member="Who to unmute")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(f"*hops off the keyboard* {member.mention} can talk again.")
    await send_log(
        interaction.guild.id, title="🔊 Member unmuted", color=discord.Color.green(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})")],
    )


@bot.tree.command(name="purge", description="Delete a number of recent messages in this channel")
@app_commands.describe(amount="How many messages to delete (1-100)")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
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
async def slowmode(interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600],
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
    )


# ---------------------------------------------------------------------------
# Keep-alive web server (Koyeb / Render free tiers expect something bound
# to $PORT). Runs in a background thread alongside the bot.
# ---------------------------------------------------------------------------

flask_app = Flask(__name__)


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
    }


def _bd_decode(raw: dict):
    global warnings_data, welcome_config, goodbye_config, automod_config
    global xp_data, reaction_role_ids, temp_bans, antiraid_config
    warnings_data = defaultdict(list, {tuple(map(int, k.split(":"))): v for k, v in raw.get("warnings", {}).items()})
    welcome_config = {int(k): v for k, v in raw.get("welcome_config", {}).items()}
    goodbye_config = {int(k): v for k, v in raw.get("goodbye_config", {}).items()}
    automod_config = {int(k): v for k, v in raw.get("automod_config", {}).items()}
    xp_data = {tuple(map(int, k.split(":"))): v for k, v in raw.get("xp_data", {}).items()}
    reaction_role_ids = set(raw.get("reaction_role_ids", []))
    temp_bans = {tuple(map(int, k.split(":"))): v for k, v in raw.get("temp_bans", {}).items()}
    antiraid_config = {int(k): v for k, v in raw.get("antiraid_config", {}).items()}


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


@tasks.loop(minutes=5)
async def periodic_save():
    """XP changes on every eligible message, so we batch-save it (and anything
    else pending) every few minutes instead of hitting the store on every
    single message — everything admin-triggered (warn, welcome config, etc.)
    still saves immediately when it happens."""
    await bd_save_data()


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
    try:
        async for message in channel.history(limit=limit):
            for embed in message.embeds:
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

    if not found:
        return 0
    found.sort(key=lambda pair: pair[1]["ts"])  # oldest first, matching normal append order
    for member_id, warning in found:
        warnings_data[(guild.id, member_id)].append(warning)
    await bd_save_data()
    return len(found)


@bot.tree.command(name="warn", description="Warn a member and log it")
@app_commands.describe(member="Who to warn", reason="Why")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.guild_only()
async def warn(interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 300]):
    count = add_warning(interaction.guild.id, member.id, reason, interaction.user)
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 *hisses a warning at* {member.mention} — now has **{count}** warning(s).",
        allowed_mentions=discord.AllowedMentions(users=True),
    )
    await send_log(
        interaction.guild.id, title="⚠️ Member warned", color=discord.Color.orange(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})"), ("Reason", reason), ("Total warnings", str(count))],
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
    afk_users[(interaction.guild.id, interaction.user.id)] = reason
    await interaction.response.send_message(
        f"🐾 {interaction.user.mention} is now AFK: {reason}",
        allowed_mentions=discord.AllowedMentions(users=True),
    )


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


@welcome_group.command(name="disable", description="Turn off welcome messages")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcome_disable(interaction: discord.Interaction):
    welcome_config.pop(interaction.guild.id, None)
    await bd_save_data()
    await interaction.response.send_message("🐾 Welcome messages turned off.")


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


@goodbye_group.command(name="disable", description="Turn off goodbye messages")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def goodbye_disable(interaction: discord.Interaction):
    goodbye_config.pop(interaction.guild.id, None)
    await bd_save_data()
    await interaction.response.send_message("🐾 Goodbye messages turned off.")


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
            else:
                await member.add_roles(role, reason="Reaction role toggle")
                await interaction.response.send_message(f"➕ Added **{role.name}**!", ephemeral=True)
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
        fields=[("Member", f"{message.author} ({message.author.id})"), ("Reason", reason),
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
    if word.lower() not in (w.lower() for w in cfg["words"]):
        cfg["words"].append(word)
        await bd_save_data()
    await interaction.response.send_message(f"🐾 Added `{word}` to the banned word list.", ephemeral=True)


@automod_word_group.command(name="remove", description="Remove a banned word/phrase")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_word_remove(interaction: discord.Interaction, word: app_commands.Range[str, 1, 100]):
    cfg = get_automod(interaction.guild.id)
    cfg["words"] = [w for w in cfg["words"] if w.lower() != word.lower()]
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Removed `{word}` from the banned word list.", ephemeral=True)


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


@automod_group.command(name="invites", description="Toggle auto-deleting Discord invite links")
@app_commands.describe(enabled="On/off")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_invites(interaction: discord.Interaction, enabled: bool):
    get_automod(interaction.guild.id)["invites"] = enabled
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Invite-link filter turned **{'on' if enabled else 'off'}**.")


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
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 {member.mention} temp-banned for **{duration_hours}h**. Reason: {reason}",
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await send_log(
        interaction.guild.id, title="⏳ Member temp-banned", color=discord.Color.red(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})"), ("Duration", f"{duration_hours}h"), ("Reason", reason)],
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
    if new_level > old_level:
        try:
            await message.channel.send(
                f"🐾 {message.author.mention} just leveled up to **Level {new_level}**!",
                allowed_mentions=discord.AllowedMentions(users=True),
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


# --- Standalone giveaways (in-memory — don't survive a restart mid-giveaway) ----

class GiveawayView(discord.ui.View):
    def __init__(self, host_id: int, winners: int, prize: str, duration_seconds: float):
        # A finite timeout (not None) on purpose: timeout=None marks a view as
        # "persistent" to discord.py, which then REQUIRES every component to have
        # an explicit custom_id and the view to be re-registered via bot.add_view()
        # on every startup — neither of which we do here, since giveaways are
        # explicitly a session-only feature (see module comment above) that
        # doesn't survive a restart anyway. A real timeout matching the giveaway's
        # own duration keeps this a normal, safely-behaved per-message view.
        super().__init__(timeout=duration_seconds + 5)
        self.entrants: set[int] = set()
        self.host_id = host_id
        self.winners = winners
        self.prize = prize

    @discord.ui.button(label="🎉 Enter", style=discord.ButtonStyle.success)
    async def enter(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id in self.entrants:
            self.entrants.discard(interaction.user.id)
            return await interaction.response.send_message("You left the giveaway.", ephemeral=True)
        self.entrants.add(interaction.user.id)
        await interaction.response.send_message("🎉 You're entered! Click again to leave.", ephemeral=True)


async def _finish_giveaway(message: discord.Message, view: "GiveawayView"):
    active_giveaways.pop(message.id, None)
    for c in view.children:
        c.disabled = True
    try:
        await message.edit(view=view)
    except discord.HTTPException:
        pass
    if not view.entrants:
        return await message.reply("🐾 No one entered the giveaway — no winners this time.")
    winner_ids = random.sample(list(view.entrants), min(view.winners, len(view.entrants)))
    mentions = " ".join(f"<@{uid}>" for uid in winner_ids)
    await message.reply(
        f"🎉 Congrats {mentions}! You won **{view.prize}**!",
        allowed_mentions=discord.AllowedMentions(users=True),
    )


async def _end_giveaway_after(message: discord.Message, delay: float, view: "GiveawayView"):
    await asyncio.sleep(delay)
    if message.id in active_giveaways:
        await _finish_giveaway(message, view)


giveaway_group = app_commands.Group(name="giveaway", description="Run a simple prize giveaway")


@giveaway_group.command(name="start", description="Start a giveaway")
@app_commands.describe(duration_minutes="How long the giveaway runs", winners="Number of winners", prize="What's being given away")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def giveaway_start(interaction: discord.Interaction, duration_minutes: int, winners: int, prize: str):
    ends_at = discord.utils.utcnow() + datetime.timedelta(minutes=duration_minutes)
    embed = discord.Embed(
        title="🎉 Giveaway!",
        description=f"**Prize:** {prize}\n**Winners:** {winners}\nEnds {discord.utils.format_dt(ends_at, 'R')}",
        color=0xFEE75C,
    )
    embed.set_footer(text=f"Hosted by {interaction.user}")
    view = GiveawayView(interaction.user.id, winners, prize, duration_minutes * 60)
    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    active_giveaways[msg.id] = {"view": view}
    asyncio.create_task(_end_giveaway_after(msg, duration_minutes * 60, view))


@giveaway_group.command(name="end", description="End a giveaway early and pick winners now")
@app_commands.describe(message_id="The ID of the giveaway message")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def giveaway_end(interaction: discord.Interaction, message_id: str):
    try:
        mid = int(message_id)
    except ValueError:
        return await interaction.response.send_message("That doesn't look like a valid message ID.", ephemeral=True)
    entry = active_giveaways.get(mid)
    if not entry:
        return await interaction.response.send_message("No active giveaway with that message ID.", ephemeral=True)
    try:
        message = await interaction.channel.fetch_message(mid)
    except discord.HTTPException:
        return await interaction.response.send_message("Couldn't find that giveaway message in this channel.", ephemeral=True)
    await interaction.response.send_message("Ending the giveaway now...", ephemeral=True)
    await _finish_giveaway(message, entry["view"])


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


@antiraid_group.command(name="disable", description="Turn off raid-join alerts")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def antiraid_disable(interaction: discord.Interaction):
    get_antiraid(interaction.guild.id)["enabled"] = False
    await bd_save_data()
    await interaction.response.send_message("🐾 Anti-raid alerts off.")


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


@datastatus_group.command(name="recover", description="Force a rebuild of this server's warnings/Hangry Games data from the log channels' history")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def datastatus_recover(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    warn_recovered = await recover_warnings_from_log(interaction.guild)
    hg_cog = bot.get_cog("HangryGamesCog")
    game_num, wins = (await hg_cog.recover_from_log(interaction.guild)) if hg_cog else (0, 0)
    await interaction.followup.send(
        f"🩹 Recovery scan complete.\n"
        f"• Warnings reconstructed: **{warn_recovered}**\n"
        f"• Hangry Games: game count restored to **#{game_num}**, **{wins}** win(s) reconstructed\n\n"
        f"This only rebuilds from what's still visible in the log channels' message history — "
        f"it can't recover anything older than that or anything never logged (like XP).",
        ephemeral=True,
    )


bot.tree.add_command(welcome_group)
bot.tree.add_command(goodbye_group)
bot.tree.add_command(reactionrole_group)
bot.tree.add_command(automod_group)
bot.tree.add_command(giveaway_group)
bot.tree.add_command(antiraid_group)
bot.tree.add_command(datastatus_group)



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
    return {
        "game_counts": {int(k): v for k, v in raw.get("game_counts", {}).items()},
        "win_counts": {tuple(map(int, k.split(":"))): v for k, v in raw.get("win_counts", {}).items()},
        "log_channels": {int(k): v for k, v in raw.get("log_channels", {}).items()},
    }


def _hg_encode(game_counts: dict, win_counts: dict, log_channels_: dict) -> dict:
    return {
        "game_counts": {str(k): v for k, v in game_counts.items()},
        "win_counts": {f"{g}:{m}": v for (g, m), v in win_counts.items()},
        "log_channels": {str(k): v for k, v in log_channels_.items()},
    }


async def hg_load_data() -> dict:
    """Load persisted game/win counts and the dedicated Hangry Games log channel.
    Uses Upstash Redis (survives redeploys on hosts with no persistent disk, e.g.
    Render free tier) when UPSTASH_REDIS_REST_URL/UPSTASH_REDIS_REST_TOKEN are
    set; otherwise falls back to a local JSON file (only survives plain
    restarts, not redeploys, on most free hosts). Never raises — a missing/
    corrupt/unreachable store just means we start fresh."""
    empty = {"game_counts": {}, "win_counts": {}, "log_channels": {}}
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


async def hg_save_data(game_counts: dict, win_counts: dict, log_channels_: dict):
    """Persist game/win counts and the log channel. See hg_load_data for storage
    choice. Never raises — a failed save shouldn't crash a game."""
    encoded = _hg_encode(game_counts, win_counts, log_channels_)
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


class HangryGamesCog(commands.GroupCog, group_name="hangrygames"):
    """Play a cat-themed elimination minigame"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active: dict[int, asyncio.Task] = {}
        self.lobbies: dict[int, "HGLobbyView"] = {}  # channel_id -> lobby not yet started
        self.game_counts: dict[int, int] = {}  # guild_id -> total games run
        self.win_counts: dict[tuple[int, int], int] = {}  # (guild_id, member_id) -> total wins
        self.hg_log_channels: dict[int, int] = {}  # guild_id -> dedicated Hangry Games log channel_id
        self.log_enabled: dict[int, bool] = {}  # guild_id -> whether HG activity is logged (default: on once a channel is set)

    async def async_init(self):
        """Load persisted counts. Call once, before add_cog, since __init__ can't await."""
        data = await hg_load_data()
        self.game_counts = data["game_counts"]
        self.win_counts = data["win_counts"]
        self.hg_log_channels = data["log_channels"]

    async def _save(self):
        await hg_save_data(self.game_counts, self.win_counts, self.hg_log_channels)

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
        for winner_id in wins:
            key = (guild.id, winner_id)
            self.win_counts[key] = self.win_counts.get(key, 0) + 1
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
            await channel.send(
                content=winner.mention, embed=winner_embed,
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
        await self.launch(interaction.channel, players, host, prize, winner_role)

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
