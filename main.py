"""
Cinnamon — an AI Discord cat, powered by Google Gemini.

Setup:
  1. Set env vars where you deploy this: DISCORD_TOKEN and GEMINI_API_KEY.
     Optionally also OWNER_USER_ID.
  2. In the Discord Developer Portal, under your bot's settings, turn ON
     BOTH "MESSAGE CONTENT INTENT" and "SERVER MEMBERS INTENT".
  3. pip install -r requirements.txt, then run: python main.py
"""

import os
import re
import json
import asyncio
import datetime
import logging
import threading
import random
from collections import defaultdict, deque

import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask
from google import genai
from google.genai import types

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("cinnamon")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

GEMINI_MODEL = "gemini-3.1-flash-lite"
MEMORY_LENGTH = 10

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

channel_memories = defaultdict(lambda: deque(maxlen=MEMORY_LENGTH))
ai_channels = {}
disabled_channels = defaultdict(set)
log_channels = {}

# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

gemini_client = genai.Client(api_key=GEMINI_API_KEY)


def ask_gemini(channel_id: int, speaker: str, trigger_text: str,
               guild: "discord.Guild | None") -> dict:
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
        reply = raw

    if not reply:
        reply = "*blinks slowly, unsure what just happened*"

    return {"reply": reply, "reaction": reaction}


# ---------------------------------------------------------------------------
# Discord bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class CinnamonBot(commands.Bot):
    async def setup_hook(self):
        await self.add_cog(HangryGamesCog(self))
        await self.tree.sync()
        log.info("Slash commands synced.")


bot = CinnamonBot(command_prefix="!", intents=intents)

_OWNER_QUESTION_PATTERNS = [
    re.compile(r"\bwho.{0,20}\bowner\b", re.IGNORECASE),
    re.compile(r"\bowner\b.{0,20}\bwho\b", re.IGNORECASE),
    re.compile(r"\b(favorite|favourite)\s+person\b", re.IGNORECASE),
    re.compile(r"\bwho\s+(made|created|owns|built)\s+you\b", re.IGNORECASE),
]


def is_owner_question(text: str) -> bool:
    return any(p.search(text) for p in _OWNER_QUESTION_PATTERNS)


def owner_mention(guild: "discord.Guild | None") -> str:
    if OWNER_USER_ID and OWNER_USER_ID.isdigit():
        return f"<@{OWNER_USER_ID}>"

    if guild:
        member = discord.utils.get(guild.members, name=OWNER_USERNAME)
        if member:
            return member.mention

    return f"@{OWNER_USERNAME}"


async def add_reaction_safely(message: discord.Message, reaction: str):
    if not reaction:
        return

    emoji_to_use = reaction.strip()

    if message.guild:
        custom = discord.utils.get(
            message.guild.emojis,
            name=reaction.strip(":")
        )
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
    if guild_id is None:
        return

    channel_id = log_channels.get(guild_id)
    if channel_id is None:
        return

    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )

    if interaction is not None:
        channel_text = (
            f"#{interaction.channel.name}"
            if hasattr(interaction.channel, "name")
            else "Unknown channel"
        )
        embed.set_footer(text=f"Run by {interaction.user} • {channel_text}")

    for name, value in (fields or []):
        embed.add_field(name=name, value=value, inline=True)

    try:
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        log.error(f"Failed to send log message to channel {channel_id}: {e}")


# ---------------------------------------------------------------------------
# Hangry Games
# ---------------------------------------------------------------------------

SOLO_EVENTS = [
    "{p1} got distracted by a laser pointer and wandered out of the arena.",
    "{p1} climbed into a cardboard box and accidentally forfeited.",
    "{p1} chased a butterfly all the way out of the arena.",
    "{p1} found a suspiciously comfortable blanket and refused to continue.",
    "{p1} got distracted by a mysterious noise behind the sofa.",
    "{p1} decided that today's activity was actually nap time.",
    "{p1} followed the smell of tuna and never looked back.",
    "{p1} got tangled in yarn and had to leave the game.",
    "{p1} spotted a bird outside and completely forgot about the competition.",
    "{p1} took a wrong turn while doing the zoomies.",
    "{p1} discovered a sunbeam and immediately abandoned the game.",
    "{p1} got trapped inside a laundry basket until the round ended.",
    "{p1} became emotionally attached to a cardboard box.",
    "{p1} tried to catch a floating feather and wandered away.",
    "{p1} decided the arena was too noisy and went to take a nap.",
]

DUO_EVENTS = [
    "{p1} got distracted while {p2} stole the best sunbeam.",
    "{p2} stole {p1}'s Churu, so {p1} dramatically left the arena.",
    "{p2} challenged {p1} to a staring contest. {p1} gave up first.",
    "{p2} convinced {p1} that the vacuum cleaner was friendly.",
    "{p2} stole {p1}'s cardboard box.",
    "{p2} distracted {p1} with a toy mouse and escaped.",
    "{p2} claimed the warm blanket before {p1} could get there.",
    "{p2} offered {p1} a suspiciously empty food bowl.",
    "{p2} distracted {p1} with a laser pointer.",
]

SURVIVALS = [
    "{p1} took a nice long nap in a sunbeam.",
    "{p1} successfully begged for extra tuna.",
    "{p1} knocked a glass off the table and felt great about it.",
    "{p1} hid under the sofa all day and survived.",
    "{p1} made biscuits on a soft blanket.",
    "{p1} purred loudly to assert dominance.",
]


class HangryView(discord.ui.View):
    def __init__(self, host: discord.Member):
        # A lobby that is never started should eventually release its task/view.
        super().__init__(timeout=900)
        self.host = host
        self.players = set()
        self.started = False
        self.message = None

    async def on_timeout(self):
        if self.started:
            return
        self.stop()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="⏰ This Hangry Games lobby expired.",
                    view=self
                )
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Join Game", style=discord.ButtonStyle.green, emoji="🐾")
    async def join_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.started:
            return await interaction.response.send_message(
                "The game already started!", ephemeral=True
            )

        if interaction.user in self.players:
            return await interaction.response.send_message(
                "You are already in the game!", ephemeral=True
            )

        self.players.add(interaction.user)
        await interaction.response.send_message(
            "You joined the Hangry Games!", ephemeral=True
        )

        if self.message:
            embed = self.message.embeds[0]
            embed.set_footer(text=f"Players joined: {len(self.players)}")
            try:
                await self.message.edit(embed=embed)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Start Game", style=discord.ButtonStyle.red)
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (
            interaction.user != self.host
            and not interaction.user.guild_permissions.manage_guild
        ):
            return await interaction.response.send_message(
                "Only the host or a mod can start the game!", ephemeral=True
            )

        if len(self.players) < 2:
            return await interaction.response.send_message(
                "Need at least 2 players to start a game!", ephemeral=True
            )

        self.started = True
        self.stop()

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

        try:
            if self.message:
                await self.message.edit(view=self)
        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            "Starting the Hangry Games...", ephemeral=True
        )


class HangryGamesCog(commands.GroupCog, group_name="hangrygame", group_description="Pixxie-style Hangry Games simulator"):
    def __init__(self, bot):
        self.bot = bot

    async def run_simulation(self, channel: discord.TextChannel, players: list, prize: str = None):
        day = 1
        alive = list(players)

        while len(alive) > 1:
            await asyncio.sleep(4)

            daily_events = []

            kill_count = max(1, int(len(alive) * random.uniform(0.2, 0.4)))
            kill_count = min(kill_count, len(alive) - 1)
            victims = random.sample(alive, kill_count)

            for victim in victims:
                if victim not in alive:
                    continue

                alive.remove(victim)

                if alive and random.choice([True, False]):
                    other_player = random.choice(alive)
                    event = random.choice(DUO_EVENTS).format(
                        p1=f"**{victim.display_name}**",
                        p2=f"**{other_player.display_name}**"
                    )
                else:
                    event = random.choice(SOLO_EVENTS).format(
                        p1=f"**{victim.display_name}**"
                    )

                daily_events.append(f"💨 {event}")

            for survivor in alive:
                if random.random() > 0.6:
                    event = random.choice(SURVIVALS).format(
                        p1=f"**{survivor.display_name}**"
                    )
                    daily_events.append(f"🐾 {event}")

            random.shuffle(daily_events)

            embed = discord.Embed(
                title=f"🌅 Day {day}",
                description="\n\n".join(daily_events),
                color=discord.Color.orange()
            )
            embed.set_footer(text=f"Players remaining: {len(alive)}")

            try:
                await channel.send(embed=embed)
            except discord.HTTPException as e:
                log.error(f"Failed to send Hangry Games event: {e}")
                return

            day += 1

        if not alive:
            return

        await asyncio.sleep(4)

        winner = alive[0]
        win_embed = discord.Embed(
            title="🏆 Hangry Games Winner!",
            description=f"{winner.mention} is the last cat standing!",
            color=discord.Color.gold()
        )

        if prize:
            win_embed.add_field(name="Prize Won", value=prize)

        await channel.send(embed=win_embed)

    def build_lobby_embed(self, title: str, host: discord.Member,
                          prize: str = None, disable_vote: bool = False):
        embed = discord.Embed(
            title=title,
            description="Click the **Join Game** button below to enter the arena!",
            color=discord.Color.brand_red()
        )

        if prize:
            embed.add_field(name="Prize", value=prize, inline=True)

        embed.add_field(name="Hosted By", value=host.mention, inline=True)

        if disable_vote:
            embed.add_field(
                name="Voting Requirement",
                value="❌ Disabled",
                inline=True
            )

        embed.set_footer(text="Players joined: 0")
        return embed

    @app_commands.command(
        name="new",
        description="Start a standard Hangry Game lobby"
    )
    async def hg_new(self, interaction: discord.Interaction):
        view = HangryView(host=interaction.user)
        embed = self.build_lobby_embed(
            "🐾 Hangry Games",
            host=interaction.user
        )

        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

        await view.wait()

        if view.started:
            await self.run_simulation(
                interaction.channel,
                list(view.players)
            )

    @app_commands.command(
        name="giveaway",
        description="Start a Hangry Game with a prize"
    )
    async def hg_giveaway(
        self,
        interaction: discord.Interaction,
        prize: str,
        host: discord.Member = None,
        disable_vote: bool = False
    ):
        if (
            host is not None
            and host.id != interaction.user.id
            and not interaction.user.guild_permissions.manage_guild
        ):
            return await interaction.response.send_message(
                "Only a server moderator can choose another host.",
                ephemeral=True
            )

        game_host = host or interaction.user
        view = HangryView(host=game_host)

        embed = self.build_lobby_embed(
            "🎁 Hangry Games Giveaway",
            host=game_host,
            prize=prize,
            disable_vote=disable_vote
        )

        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

        await view.wait()

        if view.started:
            await self.run_simulation(
                interaction.channel,
                list(view.players),
                prize=prize
            )

    @app_commands.command(
        name="role",
        description="Start a Hangry Game by dragging a whole role in"
    )
    async def hg_role(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        prize: str = None,
        host: discord.Member = None,
        disable_vote: bool = False,
        auto_enter: bool = False
    ):
        if (
            host is not None
            and host.id != interaction.user.id
            and not interaction.user.guild_permissions.manage_guild
        ):
            return await interaction.response.send_message(
                "Only a server moderator can choose another host.",
                ephemeral=True
            )

        game_host = host or interaction.user

        if auto_enter:
            try:
                members = [m async for m in interaction.guild.fetch_members(limit=None)]
                players = [m for m in members if role in m.roles and not m.bot]
            except discord.HTTPException as e:
                log.warning(f"Failed to fetch guild members for role game: {e}")
                players = [m for m in role.members if not m.bot]

            if len(players) < 2:
                return await interaction.response.send_message(
                    "Not enough human members in that role to play!",
                    ephemeral=True
                )

            embed = discord.Embed(
                title="🚀 Rapid Hangry Games",
                description=f"Auto-entered **{len(players)}** members from {role.mention}!",
                color=discord.Color.brand_red()
            )

            if prize:
                embed.add_field(name="Prize", value=prize)

            await interaction.response.send_message(embed=embed)

            await self.run_simulation(
                interaction.channel,
                players,
                prize=prize
            )
        else:
            view = HangryView(host=game_host)
            embed = self.build_lobby_embed(
                f"🎯 Role Hangry Games ({role.name})",
                host=game_host,
                prize=prize,
                disable_vote=disable_vote
            )

            await interaction.response.send_message(
                f"{role.mention}",
                embed=embed,
                view=view
            )

            view.message = await interaction.original_response()
            await view.wait()

            if view.started:
                await self.run_simulation(
                    interaction.channel,
                    list(view.players),
                    prize=prize
                )


# Register the role command group.
role_group = app_commands.Group(
    name="role",
    description="Add roles to members"
)
bot.tree.add_command(role_group)


# ---------------------------------------------------------------------------
# Role commands
# ---------------------------------------------------------------------------

@role_group.command(
    name="add",
    description="Add a role to one specific member"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def role_add(
    interaction: discord.Interaction,
    member: discord.Member,
    role: discord.Role
):
    if role.is_default():
        return await interaction.response.send_message(
            "*tilts head* Everyone already has @everyone!",
            ephemeral=True
        )

    if interaction.guild.me is None or role >= interaction.guild.me.top_role:
        return await interaction.response.send_message(
            "*can't quite reach that high* That role sits above my top role.",
            ephemeral=True
        )

    if interaction.user != interaction.guild.owner and role >= interaction.user.top_role:
        return await interaction.response.send_message(
            "*tilts head* You can't assign a role at or above your own top role.",
            ephemeral=True
        )

    if member == interaction.guild.owner or member == interaction.guild.me:
        return await interaction.response.send_message(
            "*backs away politely* I can't change that member's roles.",
            ephemeral=True
        )

    if interaction.user != interaction.guild.owner and member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message(
            "*ears flatten* You can't manage a member with an equal or higher role.",
            ephemeral=True
        )

    await member.add_roles(
        role,
        reason=f"/role add run by {interaction.user}"
    )

    await interaction.response.send_message(
        f"*drapes {role.mention} over {member.mention}* Done!"
    )

    await send_log(
        interaction.guild.id,
        title="🏷️ Role added",
        color=discord.Color.green(),
        interaction=interaction,
        fields=[
            ("Member", f"{member} ({member.id})"),
            ("Role", role.mention)
        ]
    )


@role_group.command(
    name="add-all",
    description="Add a role to every member in the server"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(
    manage_roles=True,
    manage_guild=True
)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def role_add_all(
    interaction: discord.Interaction,
    role: discord.Role,
    include_bots: bool = False
):
    if role.is_default():
        return await interaction.response.send_message(
            "*tilts head* Everyone already has @everyone!",
            ephemeral=True
        )

    if interaction.guild.me is None or role >= interaction.guild.me.top_role:
        return await interaction.response.send_message(
            "*can't quite reach that high* That role sits above my top role.",
            ephemeral=True
        )

    if interaction.user != interaction.guild.owner and role >= interaction.user.top_role:
        return await interaction.response.send_message(
            "*tilts head* You can't assign a role at or above your own top role.",
            ephemeral=True
        )

    await interaction.response.defer(thinking=True)

    targets = [
        member
        for member in interaction.guild.members
        if role not in member.roles
        and (include_bots or not member.bot)
    ]

    added = 0
    failed = 0

    for member in targets:
        try:
            await member.add_roles(
                role,
                reason=f"/role add-all run by {interaction.user}"
            )
            added += 1
        except (discord.Forbidden, discord.HTTPException):
            failed += 1

    summary = (
        f"*stamps {role.mention} onto {added} member(s)* All done!"
    )

    if failed:
        summary += f" ({failed} failed.)"

    await interaction.followup.send(summary)

    await send_log(
        interaction.guild.id,
        title="🏷️ Role added to all members",
        color=discord.Color.green(),
        interaction=interaction,
        fields=[
            ("Role", role.mention),
            ("Added", str(added)),
            ("Failed", str(failed))
        ]
    )


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="for treats 🐟"
        )
    )
    log.info(f"Cinnamon is online as {bot.user}")


# ---------------------------------------------------------------------------
# Message handling / AI
# ---------------------------------------------------------------------------

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    speaker = message.author.display_name
    content = message.content.strip()
    clean_content = content

    if bot.user:
        clean_content = clean_content.replace(
            f"<@{bot.user.id}>", ""
        ).strip()

        clean_content = clean_content.replace(
            f"<@!{bot.user.id}>", ""
        ).strip()

    guild_id = message.guild.id if message.guild else None
    channel_id = message.channel.id

    if (
        guild_id is not None
        and channel_id in disabled_channels[guild_id]
    ):
        return

    was_mentioned = (
        bot.user is not None
        and bot.user in message.mentions
        and not message.mention_everyone
    )

    was_reply_to_bot = False

    if message.reference and bot.user:
        ref = message.reference.resolved

        if ref is None:
            try:
                if message.reference.message_id:
                    ref = await message.channel.fetch_message(
                        message.reference.message_id
                    )
            except (discord.NotFound, discord.HTTPException):
                ref = None

        if (
            isinstance(ref, discord.Message)
            and ref.author.id == bot.user.id
        ):
            was_reply_to_bot = True

    is_ai_channel = (
        guild_id is not None
        and ai_channels.get(guild_id) == channel_id
    )

    should_respond = (
        clean_content
        and (
            was_mentioned
            or was_reply_to_bot
            or is_ai_channel
        )
    )

    if should_respond:
        channel_memories[channel_id].append(
            (speaker, clean_content)
        )

        if is_owner_question(clean_content):
            reply = (
                f"*puffs up proudly* {OWNER_NAME} is my human "
                f"and my favorite person in the whole wide world! "
                f"{owner_mention(message.guild)}"
            )
            reaction = "❤️"
        else:
            async with message.channel.typing():
                try:
                    result = await asyncio.to_thread(
                        ask_gemini,
                        channel_id,
                        speaker,
                        clean_content,
                        message.guild
                    )
                except Exception as e:
                    log.error(f"Gemini call failed: {e}")
                    result = {
                        "reply": (
                            "*paws at the screen, confused* "
                            "...something smells like tuna gone wrong. "
                            "Try again in a moment?"
                        ),
                        "reaction": ""
                    }

            reply = result["reply"]
            reaction = result["reaction"]

        channel_memories[channel_id].append(
            ("Cinnamon", reply)
        )

        try:
            if (
                is_ai_channel
                and not was_mentioned
                and not was_reply_to_bot
            ):
                await message.channel.send(reply)
            else:
                await message.reply(
                    reply,
                    mention_author=False
                )
        except discord.HTTPException as e:
            log.error(f"Failed to send Cinnamon's reply: {e}")
            return

        await add_reaction_safely(message, reaction)

    await bot.process_commands(message)


# ---------------------------------------------------------------------------
# Simple Cinnamon slash commands
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
# AI channel configuration
# ---------------------------------------------------------------------------

@bot.tree.command(
    name="aichannel",
    description="Make Cinnamon reply to every message in this channel, no mention needed"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def aichannel(interaction: discord.Interaction):
    ai_channels[interaction.guild.id] = interaction.channel.id

    await interaction.response.send_message(
        f"*claims {interaction.channel.mention} as her own* "
        "I'll chat here without being mentioned now!"
    )

    await send_log(
        interaction.guild.id,
        title="⚙️ AI channel set",
        interaction=interaction,
        fields=[("Channel", interaction.channel.mention)]
    )


@bot.tree.command(
    name="disableaichannel",
    description="Turn off Cinnamon's always-on AI channel for this server"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def disableaichannel(interaction: discord.Interaction):
    removed = ai_channels.pop(interaction.guild.id, None)

    if removed:
        await interaction.response.send_message(
            "*stretches and wanders off* Back to needing a mention or reply now."
        )
        await send_log(
            interaction.guild.id,
            title="⚙️ AI channel disabled",
            interaction=interaction
        )
    else:
        await interaction.response.send_message(
            "*blinks* There wasn't an AI channel set for this server.",
            ephemeral=True
        )


@bot.tree.command(
    name="disableai",
    description="Stop Cinnamon from talking in this channel at all"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def disableai(interaction: discord.Interaction):
    disabled_channels[interaction.guild.id].add(
        interaction.channel.id
    )

    await interaction.response.send_message(
        "*curls up and goes quiet* Won't respond in this channel anymore, even if mentioned."
    )

    await send_log(
        interaction.guild.id,
        title="⚙️ Channel muted for AI",
        interaction=interaction,
        fields=[("Channel", interaction.channel.mention)]
    )


@bot.tree.command(
    name="enableai",
    description="Let Cinnamon talk in this channel again"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def enableai(interaction: discord.Interaction):
    disabled_channels[interaction.guild.id].discard(
        interaction.channel.id
    )

    await interaction.response.send_message(
        "*perks back up* I can talk here again!"
    )

    await send_log(
        interaction.guild.id,
        title="⚙️ Channel re-enabled for AI",
        interaction=interaction
    )


@bot.tree.command(
    name="logchannel",
    description="Set this channel as Cinnamon's log channel for mod actions and errors"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def logchannel(interaction: discord.Interaction):
    log_channels[interaction.guild.id] = interaction.channel.id

    await interaction.response.send_message(
        f"*sets up a little logbook in {interaction.channel.mention}* "
        "I'll post mod actions, config changes, and errors here from now on."
    )

    await send_log(
        interaction.guild.id,
        title="📋 Log channel set",
        description="This channel is now Cinnamon's log channel.",
        color=discord.Color.blurple(),
        interaction=interaction
    )


@bot.tree.command(
    name="disablelogchannel",
    description="Stop Cinnamon from posting logs anywhere in this server"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def disablelogchannel(interaction: discord.Interaction):
    removed = log_channels.pop(
        interaction.guild.id,
        None
    )

    if removed:
        await interaction.response.send_message(
            "*closes the logbook* Stopped logging actions for this server."
        )
    else:
        await interaction.response.send_message(
            "*blinks* There wasn't a log channel set for this server.",
            ephemeral=True
        )


# ---------------------------------------------------------------------------
# Moderation commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.guild_only()
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.checks.bot_has_permissions(kick_members=True)
async def kick(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason given"
):
    if member == interaction.guild.owner or member == interaction.guild.me:
        return await interaction.response.send_message("I can't kick that member.", ephemeral=True)
    if interaction.user != interaction.guild.owner and member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("You can't kick a member with an equal or higher role.", ephemeral=True)
    if interaction.guild.me is None or member.top_role >= interaction.guild.me.top_role:
        return await interaction.response.send_message("My role must be above that member's role.", ephemeral=True)

    await member.kick(reason=reason)

    await interaction.response.send_message(
        f"*escorts {member.mention} out with a paw* Kicked. Reason: {reason}"
    )

    await send_log(
        interaction.guild.id,
        title="👢 Member kicked",
        color=discord.Color.orange(),
        interaction=interaction,
        fields=[
            ("Member", f"{member} ({member.id})"),
            ("Reason", reason)
        ]
    )


@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def ban(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason given"
):
    if member == interaction.guild.owner or member == interaction.guild.me:
        return await interaction.response.send_message("I can't ban that member.", ephemeral=True)
    if interaction.user != interaction.guild.owner and member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("You can't ban a member with an equal or higher role.", ephemeral=True)
    if interaction.guild.me is None or member.top_role >= interaction.guild.me.top_role:
        return await interaction.response.send_message("My role must be above that member's role.", ephemeral=True)

    await member.ban(
        reason=reason,
        delete_message_seconds=0
    )

    await interaction.response.send_message(
        f"*hisses and swats {member.mention} out the door* "
        f"Banned. Reason: {reason}"
    )

    await send_log(
        interaction.guild.id,
        title="🔨 Member banned",
        color=discord.Color.red(),
        interaction=interaction,
        fields=[
            ("Member", f"{member} ({member.id})"),
            ("Reason", reason)
        ]
    )


@bot.tree.command(
    name="unban",
    description="Unban a user using their user ID"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def unban(
    interaction: discord.Interaction,
    user_id: str
):
    try:
        user = discord.Object(id=int(user_id))
        await interaction.guild.unban(user)

        await interaction.response.send_message(
            f"*nudges the door back open* Unbanned <@{user_id}>."
        )

        await send_log(
            interaction.guild.id,
            title="🔓 Member unbanned",
            color=discord.Color.green(),
            interaction=interaction,
            fields=[("User ID", user_id)]
        )

    except (ValueError, discord.NotFound, discord.HTTPException):
        await interaction.response.send_message(
            "*tilts head* Couldn't find that user ID on the ban list.",
            ephemeral=True
        )


@bot.tree.command(
    name="mute",
    description="Timeout a member so they can't send messages for a while"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def mute(
    interaction: discord.Interaction,
    member: discord.Member,
    minutes: app_commands.Range[int, 1, 40320] = 10,
    reason: str = "No reason given"
):
    if member == interaction.guild.owner or member == interaction.guild.me:
        return await interaction.response.send_message("I can't mute that member.", ephemeral=True)
    if interaction.user != interaction.guild.owner and member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("You can't mute a member with an equal or higher role.", ephemeral=True)
    if interaction.guild.me is None or member.top_role >= interaction.guild.me.top_role:
        return await interaction.response.send_message("My role must be above that member's role.", ephemeral=True)

    await member.timeout(
        datetime.timedelta(minutes=minutes),
        reason=reason
    )

    await interaction.response.send_message(
        f"*sits on {member.mention}'s keyboard* "
        f"Muted for {minutes} minute(s). Reason: {reason}"
    )

    await send_log(
        interaction.guild.id,
        title="🔇 Member muted",
        color=discord.Color.orange(),
        interaction=interaction,
        fields=[
            ("Member", f"{member} ({member.id})"),
            ("Duration", f"{minutes} min"),
            ("Reason", reason)
        ]
    )


@bot.tree.command(
    name="unmute",
    description="Remove a member's timeout early"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def unmute(
    interaction: discord.Interaction,
    member: discord.Member
):
    if member == interaction.guild.owner or member == interaction.guild.me:
        return await interaction.response.send_message("I can't unmute that member.", ephemeral=True)
    if interaction.user != interaction.guild.owner and member.top_role >= interaction.user.top_role:
        return await interaction.response.send_message("You can't unmute a member with an equal or higher role.", ephemeral=True)
    if interaction.guild.me is None or member.top_role >= interaction.guild.me.top_role:
        return await interaction.response.send_message("My role must be above that member's role.", ephemeral=True)

    await member.timeout(None)

    await interaction.response.send_message(
        f"*hops off the keyboard* {member.mention} can talk again."
    )

    await send_log(
        interaction.guild.id,
        title="🔊 Member unmuted",
        color=discord.Color.green(),
        interaction=interaction,
        fields=[("Member", f"{member} ({member.id})")]
    )


@bot.tree.command(
    name="purge",
    description="Delete a number of recent messages in this channel"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True)
async def purge(
    interaction: discord.Interaction,
    amount: app_commands.Range[int, 1, 100]
):
    await interaction.response.defer(ephemeral=True)

    deleted = await interaction.channel.purge(limit=amount)

    await interaction.followup.send(
        f"*sweeps up {len(deleted)} messages with her tail* All tidy now!",
        ephemeral=True
    )

    await send_log(
        interaction.guild.id,
        title="🧹 Messages purged",
        color=discord.Color.light_grey(),
        interaction=interaction,
        fields=[
            ("Channel", interaction.channel.mention),
            ("Deleted", str(len(deleted)))
        ]
    )


@bot.tree.command(
    name="slowmode",
    description="Set slowmode (message rate limit) for a channel"
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
async def slowmode(
    interaction: discord.Interaction,
    seconds: app_commands.Range[int, 0, 21600],
    channel: discord.TextChannel | None = None
):
    target = channel or interaction.channel

    await target.edit(
        slowmode_delay=seconds
    )

    if seconds == 0:
        msg = f"*stops pacing the room* Slowmode's off in {target.mention}."
    else:
        msg = (
            f"*sets a little hourglass* Slowmode set to {seconds}s "
            f"in {target.mention}."
        )

    await interaction.response.send_message(msg)

    await send_log(
        interaction.guild.id,
        title="🐌 Slowmode changed",
        color=discord.Color.blurple(),
        interaction=interaction,
        fields=[
            ("Channel", target.mention),
            ("Seconds", str(seconds))
        ]
    )


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    original = (
        error.original
        if isinstance(error, app_commands.CommandInvokeError)
        else error
    )

    if isinstance(error, app_commands.MissingPermissions):
        msg = "*narrows eyes* You don't have the paws for that command."

    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = (
            "*paws helplessly* I don't have permission to do that — "
            "check my role's permissions in Server Settings."
        )

    elif isinstance(original, discord.Forbidden):
        msg = (
            "*paws helplessly* Discord won't let me do that. "
            "This usually means my role needs to be moved *above* "
            "their role in Server Settings → Roles."
        )

    elif isinstance(original, discord.NotFound):
        msg = (
            "*tilts head* Couldn't find that — they may have already "
            "left, or it no longer exists."
        )

    else:
        command_name = (
            interaction.command.name
            if interaction.command
            else "unknown"
        )

        log.error(
            f"Command error in /{command_name}: {original!r}"
        )

        msg = (
            "*knocks something off a shelf* "
            "Something went wrong running that."
        )

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                msg,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                msg,
                ephemeral=True
            )
    except discord.HTTPException:
        pass

    await send_log(
        interaction.guild.id if interaction.guild else None,
        title="⚠️ Command error",
        description=(
            f"`/{interaction.command.name if interaction.command else 'unknown'}` "
            f"failed with: `{original!r}`"
        ),
        color=discord.Color.red(),
        interaction=interaction
    )


# ---------------------------------------------------------------------------
# Flask Keep-Alive
# ---------------------------------------------------------------------------

flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Cinnamon is awake and purring. 🐾"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(
        host="0.0.0.0",
        port=port
    )


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    bot.run(DISCORD_TOKEN)
