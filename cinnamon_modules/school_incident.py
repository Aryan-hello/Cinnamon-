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
        "A teacher steps away to answer a call. Cinnamon looks at the door.\n**Cinnamon:** “Members.”\n**Member:** “No.”\n**Cinnamon:** “I haven’t said anything.”\n**Member:** “Your face has.”"),
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


class _SIChoiceButton(discord.ui.Button):
    def __init__(self, index, label):
        super().__init__(label=label[:80], style=discord.ButtonStyle.primary, row=index)
        self.choice_index = index

    async def callback(self, interaction):
        await self.view.choose(interaction, self.choice_index)


class _SIView(discord.ui.View):
    def __init__(self, owner_id, stage, choices):
        super().__init__(timeout=900)
        self.owner_id, self.stage = owner_id, stage
        for i, label in enumerate(choices):
            self.add_item(_SIChoiceButton(i, label))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("🐾 This story belongs to someone else. Start your own with /cinnamon school-incident.", ephemeral=True)
            return False
        return True

    async def choose(self, interaction, index):
        if not interaction.guild:
            return await interaction.response.send_message("Play this story inside a server.", ephemeral=True)
        rec = _si_record(interaction.guild.id, interaction.user.id)
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
            return await interaction.edit_original_response(embed=_si_embed(interaction,scene[0],scene[1]),view=_SIView(self.owner_id,rec["stage"],["Continue to the investigation ▶"]))
        if self.stage in ("route_a","route_b","route_c","route_d"):
            history.append({"stage":self.stage,"choice":"continue"})
            if self.stage == "route_a": flags["escaped_office"] = True
            if self.stage == "route_c": flags["principal_consequences"] = True
            rec["stage"] = "investigation"
            await bd_save_data()
            scene = _SI_SCENES["investigation"]
            return await interaction.edit_original_response(embed=_si_embed(interaction,scene[0],scene[1]),view=_SIView(self.owner_id,"investigation",["Call Aryan ▶"]))
        if self.stage == "investigation":
            history.append({"stage":"investigation","choice":"call Aryan"})
            rec["stage"] = "revelation"
            await bd_save_data()
            scene = _SI_SCENES["revelation"]
            return await interaction.edit_original_response(embed=_si_embed(interaction,scene[0],scene[1]),view=_SIView(self.owner_id,"revelation",["Return to the school ▶"]))
        if self.stage == "revelation":
            history.append({"stage":"revelation","choice":"return"})
            rec["stage"] = "final"
            await bd_save_data()
            scene = _SI_SCENES["final"]
            return await interaction.edit_original_response(embed=_si_embed(interaction,scene[0],scene[1]),view=_SIView(self.owner_id,"final",["A — Blame Aryan","B — Planned reconnaissance","C — Apologize","D — Immediate departure"]))
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
                    access = await _wlf_award_story_access(interaction, kind="rod")
                except Exception:
                    log.exception("School Incident completed; Rod Merchant access failed")
                    access = "\n⚠️ Story saved, but Cinnamon could not grant Rod Merchant channel access. Staff can repair permissions."
            return await interaction.edit_original_response(embed=_si_embed(interaction,"🏁 SCHOOL INCIDENT • "+ending.upper(),text+"\n\n"+access+"\n\n🎣 **Fishing Rod Merchant unlocked!**"),view=None)
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
    await interaction.response.send_message(embed=_si_embed(interaction,scene[0],scene[1]),view=_SIView(interaction.user.id,stage,choices),ephemeral=True)


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
    await interaction.response.send_message(embed=_si_embed(interaction,scene[0],scene[1]),view=_SIView(interaction.user.id,"intro",["A — Principal’s son (+1 Danger)","B — Call Aryan","C — Sneak inside (+2 Danger)","D — Cat inspector"]),ephemeral=True)
