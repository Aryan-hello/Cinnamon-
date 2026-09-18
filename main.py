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

    was_mentioned = bot.user is not None and bot.user in message.mentions and not message.mention_everyone

    if was_mentioned and clean_content:
        async with message.channel.typing():
            try:
                reply = await asyncio.to_thread(
                    ask_gemini, message.channel.id, speaker, clean_content
                )
            except Exception as e:
                log.error(f"Gemini call failed: {e}")
                reply = "*paws at the screen, confused* ...something smells like tuna gone wrong. Try again in a moment?"

        channel_memories[message.channel.id].append(("Cinnamon", reply))
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
