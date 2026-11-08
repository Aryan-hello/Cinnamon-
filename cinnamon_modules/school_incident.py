"""Playable School Incident story for Cinnamon's /cinnamon school-incident command."""
_SI_COLOR = 0xD98B3A
_SI_ROOT_KEY = "school_incident_story_v1"


def _si_record(guild_id, user_id):
    root = advanced_features_data.setdefault(_SI_ROOT_KEY, {})
    guild = root.setdefault(str(guild_id), {})
    rec = guild.setdefault(str(user_id), {})
    rec.setdefault("stage", "intro")
    rec.setdefault("route", None)
    rec.setdefault("danger", 0)
    rec.setdefault("flags", {})
    rec.setdefault("history", [])
    rec.setdefault("complete", False)
    rec.setdefault("ending", None)
    return rec


def _si_embed(interaction, title, description):
    e = discord.Embed(title=title, description=description[:4000], color=_SI_COLOR)
    e.set_author(name="🐈 CINNAMON • SCHOOL INCIDENT")
    e.set_footer(text="Your choices save automatically • /cinnamon school-incident")
    return e


_SI_SCENES = {
    "intro": ("Chapter 1 — The Wrong School",
        "Monday, 9:17 AM. Cinnamon has checked Discord 47 times, annoyed three members, and started an argument over whether tuna counts as breakfast.\n\n"
        "**Cinnamon:** “WAIT. Aryan goes to school.”\n**Member:** “And?”\n**Cinnamon:** “WE’RE GOING TO VISIT HIM.”\n\n"
        "She summons server members and marches toward a random school. At the entrance:\n\n"
        "**Guard:** “Students only. Why are you here?”\n**Cinnamon:** “We’re here to meet Aryan.”\n**Guard:** “Which Aryan?”\n**Cinnamon:** “THE Aryan.”\n**Guard:** “I don’t know any Aryan.”"),
    "route_a": ("Route A — The Principal’s Son",
        "The guard calls the principal. Five minutes later, Cinnamon is in his office, members lined up behind her.\n\n"
        "**Principal:** “I don’t have a son named Aryan.”\n**Cinnamon:** “That’s exactly what someone hiding their son would say.”\n**Principal:** “WHAT?”\n**Cinnamon:** “Nothing.”\n\n"
        "A teacher steps away to answer a call. Cinnamon looks at the door.\n**Cinnamon:** “Members.”\n**Member:** “No.”\n**Cinnamon:** “I haven’t said anything.”\n**Member:** “Your face has.”\n\nCinnamon gets up. A member knocks over a stack of papers. The teacher returns.\n**Teacher:** “HEY!”\nCinnamon runs into the corridor.\n**Member:** “WHY ARE WE RUNNING?!”\n**Cinnamon:** “BECAUSE WE’RE FREE!”\n\nThey reach the courtyard.\n**Member:** “We escaped the principal’s office.”\n**Cinnamon:** “I was never detained.”"),
    "route_c": ("Route C — Sneak Inside",
        "Cinnamon whispers, **“Operation Aryan.”** A member replies, “This is a terrible idea.”\n\n"
        "They attempt to enter without permission. A teacher notices almost immediately.\n"
        "**Teacher:** “STOP!”\n**Cinnamon:** “We are students.”\n**Teacher:** “WHICH CLASS?”\n**Cinnamon:** “Cat class.”\n\n"
        "The teacher escorts everyone to the principal’s office.\n**Principal:** “First you claim to be visiting my son. Then you attempt to enter without permission.”\n"
        "**Cinnamon:** “When you say it like that, it sounds bad.”\n**Principal:** “BECAUSE IT IS BAD.”"),
    "route_b": ("Route B — Call Aryan",
        "The guard calls the school office.\n\n**Receptionist:** “There is no student named Aryan here.”\n**Cinnamon:** “Check again.”\n**Receptionist:** “We did.”\n**Cinnamon:** “Check emotionally.”\n\nThe receptionist hangs up.\n**Member:** “Maybe Aryan doesn’t study here?”\n**Cinnamon:** “Impossible.”\n**Member:** “You literally picked a random school.”\n**Cinnamon:** “I PICKED WITH CONFIDENCE.”"),
    "route_d": ("Route D — Cat Inspector",
        "**Guard:** “Students only.”\n**Cinnamon:** “I’m here to inspect the school’s cat population.”\n**Guard:** “We don’t have cats.”\n**Cinnamon:** “That’s precisely why the inspection is necessary.”\n\n"
        "A teacher escorts Cinnamon to the courtyard. They find three cats sleeping near a garden.\n"
        "**Cinnamon:** “Cat one: sleeping.”\n**Member:** “Cat two: also sleeping.”\n**Cinnamon:** “Cat three: suspicious.”\n\nThe third cat opens one eye. Cinnamon steps backward.\n**Cinnamon:** “THIS INDIVIDUAL IS DANGEROUS.”"),
    "investigation": ("Chapter 2 — The Investigation",
        "All routes converge at the student directory.\n\n**Member:** “Okay. Let’s actually check whether Aryan studies here.”\n\nARYAN — *Searching...*\n**Directory:** 0 results.\n\n**Cinnamon:** “Search again.”\nARYAN — **0 results.**\n\n**Cinnamon:** “Search emotionally.”\n**Member:** “THAT IS NOT HOW DATABASES WORK.”\n\nNo Aryan. Not in any class.\n**Member:** “Cinnamon. I think you brought us to the wrong school.”\n**Cinnamon:** “Impossible.”\nShe finally calls Aryan."),
    "revelation": ("Chapter 3 — The Revelation",
        "**Aryan:** “Hello?”\n**Cinnamon:** “WHERE ARE YOU?”\n**Aryan:** “Home?”\n\nSilence.\n**Cinnamon:** “WHAT?!”\n**Aryan:** “Why?”\n**Cinnamon:** “WE’RE AT YOUR SCHOOL.”\n**Aryan:** “Which school?”\n\nCinnamon slowly looks at the building, the directory, and her members.\n**Cinnamon:** “...YOU DON’T EVEN GO HERE?!”\n**Aryan:** “I NEVER SAID I DID.”\n\nThe members burst into laughter.\n**Member:** “WE CAME TO THE WRONG SCHOOL.”\n**Cinnamon:** “I WILL REMEMBER THIS.”\n**Aryan:** “Remember what? You came to the wrong school.”"),
    "final": ("Chapter 4 — The Return",
        "Cinnamon must decide how to handle the humiliation. The principal is still watching from the office window. What does she do?"),
}


def _si_controls(title, description="Choose an option below."):
    e = discord.Embed(title=title,description=description[:3500],color=_SI_COLOR)
    e.set_author(name="🐈 CINNAMON • SCHOOL INCIDENT")
    e.set_footer(text="Story controls • Your choices save automatically")
    return e


async def _si_private_scene(interaction, stage, view, *, replace_original=False):
    scene = _SI_SCENES[stage]
    if replace_original:
        await interaction.edit_original_response(content=scene[1], embed=None, view=None)
    else:
        await interaction.followup.send(content=scene[1], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    await interaction.followup.send(embed=_si_controls(scene[0], "**Choose your next move below.**"), view=view, ephemeral=True)


class _SIChoiceButton(discord.ui.Button):
    def __init__(self, index, label):
        super().__init__(label=label[:80], style=discord.ButtonStyle.primary, row=index)
        self.choice_index = index

    async def callback(self, interaction):
        guild_id = interaction.guild.id
        choice = self.values[0]
        await interaction.response.defer(ephemeral=True)
        if choice == "treasure":
            rec = _wls_player(guild_id, interaction.user.id)
            if rec.get("complete"):
                return await interaction.edit_original_response(content="🏆 The Treasure Worth Billions is already complete. Use /cinnamon stories to replay.",embed=None,view=None)
            idx = min(len(_WLS_SCENES)-1,max(0,int(rec["index"])))
            await _wls_private_scene(interaction,rec,_WLSChoiceView(interaction.user.id,idx,rec.get("branch"),guild_id),replace_original=True)
        elif choice == "school":
            rec = _si_record(guild_id, interaction.user.id)
            if rec.get("complete"):
                return await interaction.edit_original_response(content=f"🏁 School Incident is complete ({str(rec.get('ending','normal')).title()}). Restart with /cinnamon school-incident-restart.",embed=None,view=None)
            stage = rec.get("stage","intro")
            choices = {
                "intro":["A — Principal’s son (+1 Danger)","B — Call Aryan","C — Sneak inside (+2 Danger)","D — Cat inspector"],
                "route_a":["Escape the principal’s office ▶"],"route_b":["Continue ▶"],
                "route_c":["Leave the principal’s office ▶"],"route_d":["Finish the inspection ▶"],
                "investigation":["Call Aryan ▶"],"revelation":["Return to the school ▶"],
                "final":["A — Blame Aryan","B — Planned reconnaissance","C — Apologize","D — Immediate departure"]
            }.get(stage,["Continue ▶"])
            await _si_private_scene(interaction,stage,_SIView(interaction.user.id,stage,choices,guild_id),replace_original=True)
        else:
            rec = _ltm_record(guild_id,interaction.user.id)
            if rec.get("complete"):
                return await interaction.edit_original_response(content="🏆 The Last Treasure Map is complete. Restart with /cinnamon last-treasure-map-restart confirm:True.",embed=None,view=None)
            await _ltm_private_scene(interaction,guild_id,rec,rec.get("stage","intro"),replace_original=True)


class _StoryPickerView(discord.ui.View):
    def __init__(self, owner_id):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.add_item(_StoryPicker())

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("🐾 Open /story to choose your own adventure.", ephemeral=True)
            return False
        return True


@bot.tree.command(name="story", description="Choose and play a Cinnamon interactive story")
@app_commands.guild_only()
async def cinnamon_story_picker(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🐈 Cinnamon Story Library",
        description="Pick an adventure below. Your progress is saved separately for each story, so you can switch and come back anytime.",
        color=_SI_COLOR)
    embed.add_field(name="💰 The Treasure Worth Billions", value="Cinnamon's missing chew toy • 100,000 Catnip reward", inline=False)
    embed.add_field(name="🏫 School Incident", value="A wrong-school visit • multiple routes and endings • Fishing Rod Merchant unlock", inline=False)
    embed.add_field(name="🗺️ The Last Treasure Map", value="Seven forgotten treasures • branching routes • multiple endings", inline=False)
    await interaction.response.send_message(embed=embed, view=_StoryPickerView(interaction.user.id), ephemeral=True)
