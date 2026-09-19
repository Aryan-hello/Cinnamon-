"""
Cinnamon — an AI Discord cat, powered by Google Gemini.

Setup:
  1. Set env vars where you deploy this: DISCORD_TOKEN and GEMINI_API_KEY.
     Optionally also OWNER_USER_ID (see "Owner" in Config below).
  2. In the Discord Developer Portal, under your bot's settings, turn ON
     BOTH "MESSAGE CONTENT INTENT" and "SERVER MEMBERS INTENT"
     (Bot tab -> Privileged Gateway Intents). The members intent is needed
     for /role add-all and for recognizing the owner by username.
  3. pip install -r requirements.txt, then run: python main.py
"""

import os
import re
import json
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
    if "hangry_games" not in bot.extensions:
        await bot.load_extension("hangry_games")
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
    await interaction.response.send_message(
        f"*sets up a little logbook in {interaction.channel.mention}* "
        f"I'll post mod actions, config changes, and errors here from now on."
    )
    await send_log(
        interaction.guild.id,
        title="📋 Log channel set",
        description=f"This channel is now Cinnamon's log channel.",
        color=discord.Color.blurple(),
        interaction=interaction,
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
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
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
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
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
               reason: str = "No reason given"):
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
    await interaction.response.send_message(f"*drapes {role.mention} over {member.mention}* Done!")
    await send_log(
        interaction.guild.id, title="🏷️ Role added", color=discord.Color.green(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})"), ("Role", role.mention)],
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

    summary = f"*stamps {role.mention} onto {added} member(s)* All done!"
    if failed:
        summary += f" ({failed} couldn't be given the role — probably role hierarchy.)"
    await interaction.followup.send(summary)
    await send_log(
        interaction.guild.id, title="🏷️ Role added to all members", color=discord.Color.green(), interaction=interaction,
        fields=[("Role", role.mention), ("Added", str(added)), ("Failed", str(failed))],
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


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(DISCORD_TOKEN)
