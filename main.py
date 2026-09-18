"""
Cinnamon — an AI Discord cat, powered by Google Gemini.

Setup:
  1. Set two environment variables where you deploy this: DISCORD_TOKEN and GEMINI_API_KEY.
  2. In the Discord Developer Portal, under your bot's settings, turn ON
     "MESSAGE CONTENT INTENT" (Bot tab -> Privileged Gateway Intents).
  3. pip install -r requirements.txt, then run: python main.py
"""

import os
import asyncio
import datetime
import logging
import threading
from collections import defaultdict, deque

import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask
from google import genai
from google.genai import types

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
- Stay in character as a cat at all times. Never mention being an AI,
  a bot, or a language model.
"""

# channel_id -> deque of (speaker_name, message_text), oldest first
channel_memories = defaultdict(lambda: deque(maxlen=MEMORY_LENGTH))

# guild_id -> channel_id where Cinnamon replies to every message, no mention needed
ai_channels = {}

# guild_id -> set of channel_ids where Cinnamon never responds, even if mentioned
disabled_channels = defaultdict(set)

# NOTE: ai_channels and disabled_channels live only in memory — they reset
# whenever the bot restarts or redeploys. Fine for now; swap in a small JSON
# file or database later if you want these settings to survive a restart.

# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

gemini_client = genai.Client(api_key=GEMINI_API_KEY)


def ask_gemini(channel_id: int, speaker: str, trigger_text: str) -> str:
    """Blocking call to Gemini. Run this off the event loop with asyncio.to_thread."""
    history = channel_memories[channel_id]
    convo = "\n".join(f"{name}: {text}" for name, text in history)

    prompt = (
        f"Recent channel conversation:\n{convo}\n\n"
        f"{speaker} just said: \"{trigger_text}\"\n\n"
        f"Reply as Cinnamon, talking to {speaker}."
    )

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=150,
            temperature=0.9,
        ),
    )
    return (response.text or "*blinks slowly, unsure what just happened*").strip()


# ---------------------------------------------------------------------------
# Discord bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="for treats 🐟"))
    log.info(f"Cinnamon is online as {bot.user}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    speaker = message.author.display_name
    content = message.content.strip()

    # Strip the bot's own mention text out of the message before we store/send it.
    clean_content = content
    if bot.user:
        clean_content = clean_content.replace(f"<@{bot.user.id}>", "").strip()
        clean_content = clean_content.replace(f"<@!{bot.user.id}>", "").strip()

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
        async with message.channel.typing():
            try:
                reply = await asyncio.to_thread(
                    ask_gemini, message.channel.id, speaker, clean_content
                )
            except Exception as e:
                log.error(f"Gemini call failed: {e}")
                reply = "*paws at the screen, confused* ...something smells like tuna gone wrong. Try again in a moment?"

        channel_memories[message.channel.id].append(("Cinnamon", reply))

        # In the dedicated AI channel, chat naturally instead of quote-replying
        # to every single message — but still use a reply if directly pinged.
        if is_ai_channel and not (was_mentioned or was_reply_to_bot):
            await message.channel.send(reply)
        else:
            await message.reply(reply, mention_author=False)


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


@bot.tree.command(name="disableaichannel", description="Turn off Cinnamon's always-on AI channel for this server")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def disableaichannel(interaction: discord.Interaction):
    removed = ai_channels.pop(interaction.guild.id, None)
    if removed:
        await interaction.response.send_message(
            "*stretches and wanders off* Back to needing a mention or reply now."
        )
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


@bot.tree.command(name="enableai", description="Let Cinnamon talk in this channel again")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def enableai(interaction: discord.Interaction):
    disabled_channels[interaction.guild.id].discard(interaction.channel.id)
    await interaction.response.send_message("*perks back up* I can talk here again!")


# ---------------------------------------------------------------------------
# Moderation commands (mods only)
# ---------------------------------------------------------------------------

@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Who to kick", reason="Why are they being kicked?")
@app_commands.guild_only()
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.checks.bot_has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"*escorts {member.mention} out with a paw* Kicked. Reason: {reason}")


@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Who to ban", reason="Why are they being banned?")
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
    await member.ban(reason=reason, delete_message_seconds=0)
    await interaction.response.send_message(f"*hisses and swats {member.mention} out the door* Banned. Reason: {reason}")


@bot.tree.command(name="unban", description="Unban a user using their user ID")
@app_commands.describe(user_id="The numeric ID of the user to unban")
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        await interaction.guild.unban(discord.Object(id=int(user_id)))
        await interaction.response.send_message(f"*nudges the door back open* Unbanned <@{user_id}>.")
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
               reason: str = "No reason given"):
    await member.timeout(datetime.timedelta(minutes=minutes), reason=reason)
    await interaction.response.send_message(
        f"*sits on {member.mention}'s keyboard* Muted for {minutes} minute(s). Reason: {reason}"
    )


@bot.tree.command(name="unmute", description="Remove a member's timeout early")
@app_commands.describe(member="Who to unmute")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(f"*hops off the keyboard* {member.mention} can talk again.")


@bot.tree.command(name="purge", description="Delete a number of recent messages in this channel")
@app_commands.describe(amount="How many messages to delete (1-100)")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"*sweeps up {len(deleted)} messages with her tail* All tidy now!", ephemeral=True)


# ---------------------------------------------------------------------------
# Friendly errors for missing permissions, instead of a raw Discord error
# ---------------------------------------------------------------------------

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "*narrows eyes* You don't have the paws for that command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "*paws helplessly* I don't have permission to do that — check my role's permissions in Server Settings."
    else:
        log.error(f"Command error: {error}")
        msg = "*knocks something off a shelf* Something went wrong running that."

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


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


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(DISCORD_TOKEN)
