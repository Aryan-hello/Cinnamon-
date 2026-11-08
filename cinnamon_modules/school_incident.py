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


async def _si_dm_scene(user, stage, view):
    scene = _SI_SCENES[stage]
    await cinnamon_story_send_dm(user,scene[1],_si_controls(scene[0],"Narration is in the normal message above.\n\n**Choose your next move below.**"),view)


class _SIChoiceButton(discord.ui.Button):
    def __init__(self, index, label):
        super().__init__(label=label[:80], style=discord.ButtonStyle.primary, row=index)
        self.choice_index = index

    async def callback(self, interaction):
        await self.view.choose(interaction, self.choice_index)


class _SIView(discord.ui.View):
    def __init__(self, owner_id, stage, choices, guild_id=None):
        super().__init__(timeout=900)
        self.owner_id, self.stage, self.guild_id = owner_id, stage, guild_id
        for i, label in enumerate(choices):
            self.add_item(_SIChoiceButton(i, label))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("🐾 This story belongs to someone else. Start your own with /cinnamon school-incident.", ephemeral=True)
            return False
        return True

    async def choose(self, interaction, index):
        if not self.guild_id:
            return await interaction.response.send_message("Story session context missing. Start it again from /story.",ephemeral=True)
        rec = _si_record(self.guild_id, interaction.user.id)
        if rec.get("complete") or rec.get("stage") != self.stage:
            return await interaction.response.send_message("Your story has moved on. Use /cinnamon school-incident to resume.", ephemeral=True)
        await interaction.response.defer()
        flags = rec["flags"]
        history = rec["history"]
        if self.stage == "intro":
            route = ["A", "B", "C", "D"][index]
            rec["route"] = route
            history.append({"stage":"intro","choice":route})
            if route == "A":
                rec["danger"] += 1
                rec["stage"] = "route_a"
            elif route == "B":
                rec["stage"] = "route_b"
            elif route == "C":
                rec["danger"] += 2
                rec["stage"] = "route_c"
            else:
                flags["cats_seen"] = True
                rec["stage"] = "route_d"
            await bd_save_data()
            scene = _SI_SCENES[rec["stage"]]
            await interaction.user.send(content=scene[1],allowed_mentions=discord.AllowedMentions.none())
            return await interaction.edit_original_response(embed=_si_controls(scene[0],"Your route is saved. Continue when ready."),view=_SIView(self.owner_id,rec["stage"],["Continue to the investigation ▶"],self.guild_id))
        if self.stage in ("route_a","route_b","route_c","route_d"):
            history.append({"stage":self.stage,"choice":"continue"})
            if self.stage == "route_a": flags["escaped_office"] = True
            if self.stage == "route_c": flags["principal_consequences"] = True
            rec["stage"] = "investigation"
            await bd_save_data()
            scene = _SI_SCENES["investigation"]
            await interaction.user.send(content=scene[1],allowed_mentions=discord.AllowedMentions.none())
            return await interaction.edit_original_response(embed=_si_controls(scene[0],"Your route is saved. Continue when ready."),view=_SIView(self.owner_id,"investigation",["Call Aryan ▶"],self.guild_id))
        if self.stage == "investigation":
            history.append({"stage":"investigation","choice":"call Aryan"})
            rec["stage"] = "revelation"
            await bd_save_data()
            scene = _SI_SCENES["revelation"]
            await interaction.user.send(content=scene[1],allowed_mentions=discord.AllowedMentions.none())
            return await interaction.edit_original_response(embed=_si_controls(scene[0],"Continue when ready."),view=_SIView(self.owner_id,"revelation",["Return to the school ▶"],self.guild_id))
        if self.stage == "revelation":
            history.append({"stage":"revelation","choice":"return"})
            rec["stage"] = "final"
            await bd_save_data()
            scene = _SI_SCENES["final"]
            await interaction.user.send(content=scene[1],allowed_mentions=discord.AllowedMentions.none())
            return await interaction.edit_original_response(embed=_si_controls(scene[0],"Choose how to handle the aftermath."),view=_SIView(self.owner_id,"final",["A — Blame Aryan","B — Planned reconnaissance","C — Apologize","D — Immediate departure"],self.guild_id))
        if self.stage == "final":
            history.append({"stage":"final","choice":["blame","recon","apologize","leave"][index]})
            if index == 0: rec["danger"] += 1
            if rec["danger"] >= 3:
                ending, text = "bad", "**Principal:** “YOU ARE BANNED FROM THIS SCHOOL.”\n**Cinnamon:** “I WAS NEVER ENROLLED.”\n\n**GAME OVER**"
            elif rec["route"] == "D" and index == 2 and flags.get("cats_seen"):
                ending, text = "secret", "🐈 **SECRET ENDING — THE CAT DISTRIBUTION SYSTEM**\n\nCinnamon adopts a mysterious school cat as the server mascot. Aryan is officially replaced as the server’s favorite.\n\n**Aryan:** “I’M ACTUALLY LEAVING.”"
            elif index == 2:
                ending, text = "good", "**GOOD ENDING — THE LEGENDARY CAT**\n\nCinnamon admits the mistake. Everyone leaves peacefully. Aryan laughs at the entire server."
            else:
                ending, text = "normal", "**NORMAL ENDING — ADMINISTRATIVE DISASTER**\n\nThe principal remembers Cinnamon forever. Aryan refuses to answer her calls for ten minutes."
            rec.update({"stage":"complete","complete":True,"ending":ending})
            await bd_save_data()
            access = ""
            if ending != "bad":
                try:
                    access = await _wlf_award_story_access(interaction, kind="rod", guild_id=self.guild_id)
                except Exception:
                    log.exception("School Incident completed; Rod Merchant access failed")
                    access = "\n⚠️ Story saved, but Cinnamon could not grant Rod Merchant channel access. Staff can repair permissions."
            await interaction.user.send(content=text+"\n\n"+access+"\n\n🎣 **Fishing Rod Merchant unlocked!**",allowed_mentions=discord.AllowedMentions.none())
            return await interaction.edit_original_response(embed=_si_controls("🏁 SCHOOL INCIDENT • "+ending.upper(),"Ending details were sent as a normal message."),view=None)
        return await interaction.edit_original_response(embed=_si_embed(interaction,"🐾 Story error","Use /cinnamon school-incident to resume."),view=None)


@_cinnamon_stories_group.command(name="school-incident", description="Play or resume the branching School Incident story")
@app_commands.guild_only()
async def school_incident(interaction: discord.Interaction):
    rec = _si_record(interaction.guild.id, interaction.user.id)
    if rec.get("complete"):
        await interaction.response.send_message(embed=_si_embed(interaction,"🏁 School Incident Complete",
            f"Your ending: **{str(rec.get('ending','normal')).title()}**. Replay it with /cinnamon school-incident-restart."),ephemeral=True)
        return
    stage = rec.get("stage","intro")
    scene = _SI_SCENES.get(stage)
    if not scene:
        rec["stage"]="intro"; stage="intro"; scene=_SI_SCENES[stage]
    choices = {
        "intro":["A — Principal’s son (+1 Danger)","B — Call Aryan","C — Sneak inside (+2 Danger)","D — Cat inspector"],
        "route_a":["Escape the principal’s office ▶"],"route_b":["Continue ▶"],"route_c":["Leave the principal’s office ▶"],"route_d":["Finish the inspection ▶"],
        "investigation":["Call Aryan ▶"],"revelation":["Return to the school ▶"],
        "final":["A — Blame Aryan","B — Planned reconnaissance","C — Apologize","D — Immediate departure"]
    }.get(stage,["Continue ▶"])
    await interaction.response.defer(ephemeral=True)
    try:
        await _si_dm_scene(interaction.user,stage,_SIView(interaction.user.id,stage,choices,interaction.guild.id))
        await interaction.followup.send("🐾 **School Incident** was sent to your DMs. Check your private messages to play!",ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("I couldn't DM you. Please enable server-member DMs, then run /cinnamon school-incident again.",ephemeral=True)


@_cinnamon_stories_group.command(name="school-incident-restart", description="Restart your School Incident decisions")
@app_commands.guild_only()
@app_commands.describe(confirm="Set True to erase your current School Incident progress")
async def school_incident_restart(interaction: discord.Interaction, confirm: bool = False):
    rec = _si_record(interaction.guild.id, interaction.user.id)
    if not confirm:
        return await interaction.response.send_message("This resets your School Incident choices and ending (it does not remove merchant access). Run /cinnamon school-incident-restart confirm:True to confirm.",ephemeral=True)
    rec.clear()
    rec.update({"stage":"intro","route":None,"danger":0,"flags":{},"history":[],"complete":False,"ending":None})
    await bd_save_data()
    scene=_SI_SCENES["intro"]
    await interaction.response.defer(ephemeral=True)
    try:
        await _si_dm_scene(interaction.user,"intro",_SIView(interaction.user.id,"intro",["A — Principal’s son (+1 Danger)","B — Call Aryan","C — Sneak inside (+2 Danger)","D — Cat inspector"],interaction.guild.id))
        await interaction.followup.send("🐾 Restarted School Incident in your DMs.",ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("I couldn't DM you. Enable server-member DMs and try again.",ephemeral=True)


class _StoryPicker(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="Choose a Cinnamon story…", min_values=1, max_values=1,
            options=[
                discord.SelectOption(label="The Treasure Worth Billions", value="treasure",
                    description="A mystery, a fish-shaped map, and a billion-Catnip claim", emoji="💰"),
                discord.SelectOption(label="School Incident", value="school",
                    description="Cinnamon visits the wrong school looking for Aryan", emoji="🏫"),
                discord.SelectOption(label="The Last Treasure Map", value="last_map",
                    description="Seven forgotten treasures, secrets, and a final wish", emoji="🗺️"),
            ])

    async def callback(self, interaction):
        guild_id = interaction.guild.id
        choice = self.values[0]
        await interaction.response.defer(ephemeral=True)
        try:
            if choice == "treasure":
                rec = _wls_player(guild_id, interaction.user.id)
                if rec.get("complete"):
                    return await interaction.edit_original_response(content="🏆 The Treasure Worth Billions is already complete. Use /cinnamon stories to replay.",embed=None,view=None)
                idx = min(len(_WLS_SCENES)-1,max(0,int(rec["index"])))
                await _wls_dm_scene(interaction.user,rec,_WLSChoiceView(interaction.user.id,idx,rec.get("branch"),guild_id))
                message = "🐾 **The Treasure Worth Billions** has been sent to your DMs. Read the normal message, then use its separate control embed."
            elif choice == "school":
                rec = _si_record(guild_id, interaction.user.id)
                if rec.get("complete"):
                    return await interaction.edit_original_response(content=f"🏁 School Incident is complete ({str(rec.get('ending','normal')).title()}). Restart with /cinnamon school-incident-restart.",embed=None,view=None)
                stage = rec.get("stage","intro")
                scene = _SI_SCENES.get(stage,_SI_SCENES["intro"])
                choices = {
                    "intro":["A — Principal’s son (+1 Danger)","B — Call Aryan","C — Sneak inside (+2 Danger)","D — Cat inspector"],
                    "route_a":["Escape the principal’s office ▶"],"route_b":["Continue ▶"],
                    "route_c":["Leave the principal’s office ▶"],"route_d":["Finish the inspection ▶"],
                    "investigation":["Call Aryan ▶"],"revelation":["Return to the school ▶"],
                    "final":["A — Blame Aryan","B — Planned reconnaissance","C — Apologize","D — Immediate departure"]
                }.get(stage,["Continue ▶"])
                await _si_dm_scene(interaction.user,stage,_SIView(interaction.user.id,stage,choices,guild_id))
                message = "🐾 **School Incident** has been sent to your DMs. Read the normal message, then use its separate control embed."
            else:
                rec = _ltm_record(guild_id,interaction.user.id)
                if rec.get("complete"):
                    return await interaction.edit_original_response(content="🏆 The Last Treasure Map is complete. Restart with /cinnamon last-treasure-map-restart confirm:True.",embed=None,view=None)
                await _ltm_send_scene(interaction.user,guild_id,rec,rec.get("stage","intro"))
                message = "🗺️ **The Last Treasure Map** has been sent to your DMs. Narration is a normal message; choices are in its control embed."
            await interaction.edit_original_response(content=message,embed=None,view=None)
        except discord.Forbidden:
            await interaction.edit_original_response(content="I couldn't DM you. Enable server-member DMs and choose the story again.",embed=None,view=None)


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
