"""Hangry Games — isolated Cog. Self-contained; does not touch main.py state."""

import random
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

SOLO_DEATHS = [
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
]

DUO_DEATHS = [
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
]

SURVIVALS = [
    "{p1} took a nice long nap in a sunbeam.",
    "{p1} successfully begged for extra tuna.",
    "{p1} knocked a glass off the table and felt great about it.",
    "{p1} hid under the sofa all day and survived.",
    "{p1} made biscuits on a soft blanket.",
    "{p1} purred loudly to assert dominance.",
]


class LobbyView(discord.ui.View):
    def __init__(self, cog: "HangryGamesCog", prize: str | None = None):
        super().__init__(timeout=600)
        self.cog = cog
        self.prize = prize
        self.players: dict[int, str] = {}
        self.started = False
        self.message: discord.Message | None = None

    def embed(self) -> discord.Embed:
        title = "🐾 Hangry Games — Giveaway" if self.prize else "🐾 Hangry Games"
        names = "\n".join(self.players.values()) or "*(none yet)*"
        desc = f"Tap **Join 🐾** to enter — no backing out!\n\n**Players:**\n{names}"
        if self.prize:
            desc += f"\n\n**Prize:** {self.prize}"
        return discord.Embed(title=title, description=desc, color=0xFFB02E)

    @discord.ui.button(label="Join 🐾", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.started:
            return await interaction.response.send_message("Already started!", ephemeral=True)
        if interaction.user.id in self.players:
            return await interaction.response.send_message("You're already in — no backing out!", ephemeral=True)
        self.players[interaction.user.id] = interaction.user.display_name
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
        self.cog.launch(interaction.channel, self.players, self.prize)

    async def on_timeout(self):
        if self.started or not self.message:
            return
        for c in self.children:
            c.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass


class HangryGamesCog(commands.GroupCog, group_name="hangrygames"):
    """Play a cat-themed elimination minigame"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active: dict[int, asyncio.Task] = {}
        self.game_counts: dict[int, int] = {}  # guild_id -> total games run

    def launch(self, channel: discord.abc.Messageable, players: dict[int, str], prize: str | None):
        self.game_counts[channel.guild.id] = self.game_counts.get(channel.guild.id, 0) + 1
        game_num = self.game_counts[channel.guild.id]
        task = asyncio.create_task(self.run_game(channel, players, prize, game_num))
        self.active[channel.id] = task

    async def run_game(self, channel: discord.abc.Messageable, players: dict[int, str], prize: str | None,
                        game_num: int):
        alive = dict(players)
        rnd = 0
        await channel.send(f"🐾 **Hangry Games #{game_num}** begins with **{len(alive)}** cats in the arena!")
        try:
            while len(alive) > 1:
                rnd += 1
                await asyncio.sleep(5)
                ids = list(alive.keys())
                embed = discord.Embed(title=f"🐾 Game #{game_num} — Round {rnd}", color=0xFFB02E)

                roll = random.random()
                if roll < 0.80:
                    p1_id, p2_id = random.sample(ids, 2)
                    embed.description = random.choice(DUO_DEATHS).format(p1=alive[p1_id], p2=alive[p2_id])
                    del alive[p1_id]
                elif roll < 0.90:
                    p1_id = random.choice(ids)
                    embed.description = random.choice(SOLO_DEATHS).format(p1=alive[p1_id])
                    del alive[p1_id]
                else:
                    p1_id = random.choice(ids)
                    embed.description = random.choice(SURVIVALS).format(p1=alive[p1_id])

                if rnd % 5 == 0:
                    embed.add_field(name="Survivors", value="\n".join(alive.values()) or "None", inline=False)

                await channel.send(embed=embed)

            winner = next(iter(alive.values())) if alive else "No one"
            desc = f"**{winner}** wins **Hangry Games #{game_num}**!"
            if prize:
                desc += f"\n🎁 Prize: **{prize}**"
            await channel.send(embed=discord.Embed(title="🏆 We Have a Winner!", color=0xFEE75C, description=desc))
        except asyncio.CancelledError:
            await channel.send("*knocks the arena over* Game cancelled.")
        finally:
            self.active.pop(channel.id, None)

    @app_commands.command(name="new", description="Start a Hangry Games lobby")
    @app_commands.guild_only()
    async def new(self, interaction: discord.Interaction):
        if interaction.channel.id in self.active:
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        view = LobbyView(self)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="giveaway", description="Run a Hangry Games giveaway")
    @app_commands.describe(prize="What the winner takes home")
    @app_commands.guild_only()
    async def giveaway(self, interaction: discord.Interaction, prize: str):
        if interaction.channel.id in self.active:
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        view = LobbyView(self, prize=prize)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="role", description="Auto-start a game with everyone who has a role")
    @app_commands.describe(role="The role to pull players from")
    @app_commands.guild_only()
    async def role_cmd(self, interaction: discord.Interaction, role: discord.Role):
        if interaction.channel.id in self.active:
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        players = {m.id: m.display_name for m in role.members if not m.bot}
        if len(players) < 2:
            return await interaction.response.send_message(
                "Need at least 2 non-bot members with that role.", ephemeral=True
            )
        await interaction.response.send_message(f"🐾 **{len(players)}** cats from {role.mention} enter the arena!")
        self.launch(interaction.channel, players, None)

    @app_commands.command(name="cancel", description="Cancel the Hangry Games running in this channel")
    @app_commands.guild_only()
    async def cancel(self, interaction: discord.Interaction):
        task = self.active.pop(interaction.channel.id, None)
        if not task:
            return await interaction.response.send_message("No game running here.", ephemeral=True)
        task.cancel()
        await interaction.response.send_message("Game cancelled.")


async def setup(bot: commands.Bot):
    await bot.add_cog(HangryGamesCog(bot))
