"""Hangry Games — isolated Cog. Self-contained; does not touch main.py state."""

import time
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

SURVIVALS = [
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


class LobbyView(discord.ui.View):
    def __init__(self, cog: "HangryGamesCog", host: discord.Member, prize: str | None = None):
        super().__init__(timeout=600)
        self.cog = cog
        self.host = host
        self.prize = prize
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
        self.cog.launch(interaction.channel, self.players, self.host, self.prize)

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

    def launch(self, channel: discord.abc.Messageable, players: dict[int, discord.Member],
               host: discord.Member, prize: str | None):
        task = asyncio.create_task(self.run_game(channel, players, host, prize))
        self.active[channel.id] = task

    async def run_game(self, channel: discord.abc.Messageable, players: dict[int, discord.Member],
                        host: discord.Member, prize: str | None):
        alive = dict(players)
        kills: dict[int, int] = {pid: 0 for pid in alive}
        start = time.monotonic()
        rnd = 0
        await channel.send(f"🐾 **Hangry Games** begins with **{len(alive)}** cats in the arena, hosted by {host.mention}!")
        try:
            while len(alive) > 1:
                rnd += 1
                await asyncio.sleep(5)
                ids = list(alive.keys())
                embed = discord.Embed(color=0xFFB02E)
                roll = random.random()

                if roll < 0.85:
                    p1_id, p2_id = random.sample(ids, 2)
                    p1, p2 = alive[p1_id], alive[p2_id]
                    content = f"{p1.mention} {p2.mention}"
                    embed.description = f"⚔️ {random.choice(DUO_DEATHS).format(p1=p1.display_name, p2=p2.display_name)}"
                    embed.set_thumbnail(url=p1.display_avatar.url)
                    embed.set_image(url=p2.display_avatar.url)
                    kills[p2_id] = kills.get(p2_id, 0) + 1
                    del alive[p1_id]
                elif roll < 0.925:
                    p1_id = random.choice(ids)
                    p1 = alive[p1_id]
                    content = p1.mention
                    embed.title = "🐾 A cat-astrophe occurred! 🙀"
                    embed.description = f"👉 {random.choice(SOLO_DEATHS).format(p1=p1.display_name)}"
                    embed.set_image(url=p1.display_avatar.url)
                    del alive[p1_id]
                else:
                    p1_id = random.choice(ids)
                    p1 = alive[p1_id]
                    content = p1.mention
                    embed.title = "🐾 A cat-astrophe occurred! 🙀"
                    embed.description = f"👉 {random.choice(SURVIVALS).format(p1=p1.display_name)}"
                    embed.set_image(url=p1.display_avatar.url)

                if rnd % 5 == 0:
                    survivors = "\n".join(m.display_name for m in alive.values()) or "None"
                    embed.add_field(name="Survivors", value=survivors, inline=False)

                await channel.send(content=content, embed=embed)

            winner_id, winner = next(iter(alive.items())) if alive else (None, None)
            winner_kills = kills.get(winner_id, 0)
            elapsed = int(time.monotonic() - start)
            mm, ss = divmod(elapsed, 60)
            mock_wins = random.randint(1, 99)

            desc = f"🎉 **{winner.display_name}** won **{host.display_name}**'s Hangry Games"
            if prize:
                desc += f" and **{prize}**"
            desc += "!\n"
            desc += f"💀 **Total kills:** {winner_kills}\n"
            desc += f"⏱️ **Time survived:** {mm}m {ss}s\n"
            desc += f"🏆 **Total wins in server:** {mock_wins}"

            winner_embed = discord.Embed(title="🏆 Winner!", color=0xFEE75C, description=desc)
            winner_embed.set_image(url=winner.display_avatar.url)
            await channel.send(content=winner.mention, embed=winner_embed)
        except asyncio.CancelledError:
            await channel.send("*knocks the arena over* Game cancelled.")
        finally:
            self.active.pop(channel.id, None)

    @app_commands.command(name="new", description="Start a Hangry Games lobby")
    @app_commands.describe(host="Who's hosting (defaults to you)")
    @app_commands.guild_only()
    async def new(self, interaction: discord.Interaction, host: discord.Member = None):
        if interaction.channel.id in self.active:
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        view = LobbyView(self, host or interaction.user)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="giveaway", description="Run a Hangry Games giveaway")
    @app_commands.describe(prize="What the winner takes home", host="Who's hosting (defaults to you)")
    @app_commands.guild_only()
    async def giveaway(self, interaction: discord.Interaction, prize: str, host: discord.Member = None):
        if interaction.channel.id in self.active:
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        view = LobbyView(self, host or interaction.user, prize=prize)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="role", description="Auto-start a game with everyone who has a role")
    @app_commands.describe(role="The role to pull players from", host="Who's hosting (defaults to you)")
    @app_commands.guild_only()
    async def role_cmd(self, interaction: discord.Interaction, role: discord.Role, host: discord.Member = None):
        if interaction.channel.id in self.active:
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        players = {m.id: m for m in role.members if not m.bot}
        if len(players) < 2:
            return await interaction.response.send_message(
                "Need at least 2 non-bot members with that role.", ephemeral=True
            )
        host = host or interaction.user
        await interaction.response.send_message(f"🐾 **{len(players)}** cats from {role.mention} enter the arena, hosted by {host.mention}!")
        self.launch(interaction.channel, players, host, None)

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
