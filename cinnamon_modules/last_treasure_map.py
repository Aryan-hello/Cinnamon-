"""Private branching story: The Last Treasure Map."""
_LTM_KEY = "last_treasure_map_v1"
_LTM_COLOR = 0xD97732
_LTM_SCENES = {
"intro":("Prologue — The Map That Shouldn't Exist", """11:47 PM. Something hits your window.

*THUMP. THUMP. THUMP.*

Outside stands Beans, exhausted, holding a rolled-up parchment.

**Beans:** “OPEN THE WINDOW!”

He climbs inside, trips, and lands face-first.

**Beans:** “...I meant to do that.”

Cinnamon wakes up. Beans unrolls an ancient map. Seven locations are marked, and one symbol looks unmistakably like Cinnamon.

She places her paw over it.

**Beans:** “Oh, that's bad.”

**You:** “Why?”

**Beans:** “Last time she touched something important, a billion-Catnip treasure turned out to be a chew toy.”

Cinnamon looks extremely proud.""", [("Ask what Clawdius found","clawdius"),("Inspect Cinnamon's symbol","symbol"),("Take the map and leave","escape")]),
"clawdius":("The Baron's Discovery", """Beans explains that Baron Clawdius von Scratch III bought the map at an auction.

**Beans:** “He thinks it leads to a treasure bigger than the last one.”

**You:** “And you stole it?”

**Beans:** “Borrowed. Aggressively.”

A note reads: *The map chooses its finder.*""", [("Visit the Ancient Owl","owl"),("Go to the lighthouse","lighthouse"),("Set a trap","trap")]),
"symbol":("A Pawprint in Ancient Ink", """The symbol is a real pawprint pressed into parchment centuries ago.

Cinnamon's fur bristles.

**Cinnamon:** “That is... weird.”

A line appears: *Find the one who remembers.*""", [("Ask the Owl","owl"),("Follow the lighthouse mark","lighthouse"),("Prepare a trap","trap")]),
"escape":("The Sensible Escape", """You pack snacks and leave before Clawdius arrives. Beans follows. Cinnamon follows Beans.

**Beans:** “Why are we following each other?”

**Cinnamon:** “BECAUSE WE ARE A TEAM.”

You reach a crossroads.""", [("Find the Owl","owl"),("Go lighthouse","lighthouse"),("Ambush Clawdius","trap")]),
"lighthouse":("Route A — The Abandoned Lighthouse", """The lighthouse lantern shines only when someone lies.

**Beans:** “Clawdius will glow like a festival.”

An inscription appears: *The first treasure belongs to the one who loses something.*""", [("Sacrifice an item","light_key"),("Let Cinnamon offer something","light_promise"),("Trick the lantern","light_trick")]),
"light_key":("The Lantern Key", """You sacrifice a useful item. The lantern absorbs it and reveals a silver key.

Cinnamon looks at you with genuine respect.

**Cinnamon:** “That was... actually brave.”""", [("Carry the key to the market","market")]),
"light_promise":("Cinnamon's Promise", """Cinnamon places a treasured object beside the lantern. It glows gold.

**Cinnamon:** “I trust you. Don't make me regret it.”

The lantern leaves a silver key and paw-shaped mark.""", [("Take the key together","market")]),
"light_trick":("The Lighthouse Gets Angry", """You trick the lantern. It flashes red; the lighthouse rings like an alarm.

**Beans:** “I think we offended architecture.”

You escape with a silver key, but the lighthouse remembers your deception.""", [("Run to the market","market")]),
"owl":("Route B — The Owl's Forbidden Memory", """The Ancient Owl leads you beneath his tree.

**Owl:** “Seven treasures. Seven guardians. One final secret.”

**You:** “What secret?”

**Owl:** “The treasures were never meant to be collected.”

**Beans:** “Then why make a map?”

**Owl:** “Because cats exist.”

He points to Cinnamon's pawprint.""", [("Trust the Owl","owl_trust"),("Demand the truth","owl_truth"),("Copy the inscription secretly","owl_copy")]),
"owl_trust":("The Owl's Trust", """The Owl reveals a memory: a guardian cat protected seven treasures from greedy hunters.

**Owl:** “The map seeks a protector, not an owner.”

Cinnamon pretends she wasn't listening.""", [("Take the memory to the market","market")]),
"owl_truth":("The Forbidden Truth", """The final treasure can grant one wish—but only if its guardian willingly gives it away.

**Owl:** “Greed breaks the machine. Loyalty restores it.”

Beans looks deeply uncomfortable.""", [("Head to the market","market")]),
"owl_copy":("The Secret Inscription", """You copy the chamber's inscription. The Owl notices but says nothing. A feather falls into your bag.

**Hidden clue:** The Guardian's Choice.""", [("Go to the market","market")]),
"trap":("Route C — Operation: Catch the Baron", """Beans designs a trap: a carrier, biscuits, rope, and a sign reading **FREE ROYAL MASSAGE**.

**You:** “This is your plan?”

**Beans:** “I had six minutes.”

Cinnamon appoints you Chief Trap Inspector.""", [("Follow Beans's plan","trap_success"),("Improve the trap","trap_improved"),("Pretend to ally with Clawdius","trap_ally")]),
"trap_success":("The Carrier Incident", """Clawdius steps into the carrier.

*CLICK.*

**Clawdius:** “WHY IS THE DOOR LOCKED?”

You steal his route notes. He escapes, furious.""", [("Use route notes","market")]),
"trap_improved":("A Trap with Actual Strategy", """Your decoy and hidden exit work. Beans retrieves the route notes.

**Beans:** “I respect your planning skills.”

Cinnamon: “I PLANNED THE BISCUITS.”""", [("Follow the notes","market")]),
"trap_ally":("The Double-Agent Deal", """You pretend to help Clawdius. He gives you the title Deputy Assistant Associate Treasure Consultant.

Beans slips you a second map.

**Beans:** “Betray someone professionally, please.”""", [("Keep the secret route","market")]),
"market":("Chapter 2 — The Market of Impossible Things", """At midnight, a market appears between ruined towers.

The merchant offers a **Mirror of Truth**, **Clockwork Feather**, or **Invisible Bell**.

Clawdius demands the Compass.

**Merchant:** “Payment?”

**Clawdius:** “I AM BARON CLAWDIUS VON SCRATCH III!”

**Merchant:** “That wasn't the question.”""", [("Bargain for the Mirror","market_mirror"),("Steal the Invisible Bell","market_bell"),("Challenge Clawdius","market_game")]),
"market_mirror":("The Merchant's Bargain", """You bargain carefully and receive the Mirror of Truth. It reveals hidden writing and exposes lies—but might reveal one of your own secrets.

Cinnamon: “Excellent. I shall never use it.”""", [("Enter the archive","archive")]),
"market_bell":("The World's Loudest Stealth", """You steal the Invisible Bell. It is invisible and EXTREMELY loud.

The merchant chases you through six stalls. Beans distracts him with premium rocks.

You escape with the bell and a market curse.""", [("Escape to the archive","archive")]),
"market_game":("The Market Game", """Clawdius challenges you to three rounds: crown or paw, key or spoon, treasure or suspicious potato.

You win by choosing the object Clawdius refuses to acknowledge.""", [("Choose suspicious potato","market_win"),("Choose crown","market_loss"),("Choose the chest","market_win")]),
"market_win":("The Baron's Humiliation", """You choose the suspicious potato. Clawdius loses. The crowd laughs so hard Beans sits down.

**Clawdius:** “THIS GAME WAS RIGGED!”

**Merchant:** “You wrote the rules.”

You earn the crowd's support.""", [("Follow a secret passage","archive")]),
"market_loss":("The Baron's Victory", """Clawdius wins and gives a speech about his intelligence.

Beans quietly steals the archive key.

**Beans:** “Losing can be useful. Don't tell him.”""", [("Use Beans's key","archive")]),
"archive":("Chapter 3 — The Underground Archive", """Beneath the market lies an archive of failed expeditions.

One record describes seven guardians and a machine that grants one wish. Another mentions a cat who protected the treasures.

Beans finds his employer's family record.

**Beans:** “My employer's family has chased this for generations.”

**You:** “You knew?”

**Beans:** “I knew they were dramatic. Not HISTORICALLY dramatic.”""", [("Investigate Cinnamon's symbol","archive_cat"),("Investigate Clawdius's family","archive_baron"),("Find the previous expedition","archive_expedition")]),
"archive_cat":("The Guardian's Pawprint", """The symbol matches a guardian's seal. The guardian must choose whether to claim, destroy, or restore the treasures.

Cinnamon is unusually quiet.""", [("Ask Cinnamon directly","beans")]),
"archive_baron":("The Scratch Family Record", """Clawdius's ancestors failed to claim the treasures.

*The next Scratch who seeks the crown will meet the guardian.*

Clawdius has not read this page.""", [("Warn Clawdius","beans")]),
"archive_expedition":("The Expedition That Refused", """The previous expedition reached the final chamber and refused to take the treasure.

*Some things are worth more when they belong to everyone.*

Beans folds the page carefully.""", [("Continue to the Seven Doors","beans")]),
"beans":("Chapter 4 — Beans's Unfortunate Loyalty", """Clawdius catches Beans alone.

**Clawdius:** “You betrayed me.”

**Beans:** “I didn't.”

**Clawdius:** “You joined them!”

**Beans:** “They have better snacks.”

Clawdius looks genuinely hurt. You witness the confrontation.""", [("Protect Beans","beans_protect"),("Let Beans speak","beans_speak"),("Offer Clawdius an alliance","beans_alliance"),("Help Beans escape","beans_escape")]),
"beans_protect":("Beans Stands with You", """You step between them. Beans looks surprised.

**Beans:** “...Thank you.”

Clawdius retreats. Beans joins you openly.""", [("Enter the Seven Doors","doors")]),
"beans_speak":("Beans's Choice", """Beans says he is tired of being treated like a disposable assistant.

Clawdius doesn't answer. Beans walks back to you.

**Beans:** “I think I made the right choice.”""", [("Enter the Seven Doors","doors")]),
"beans_alliance":("A Temporary Alliance", """Clawdius agrees to cooperate—temporarily.

**Clawdius:** “I shall claim the treasure after we survive.”

**Beans:** “Most reasonable thing you've said this year.”

Clawdius joins under suspicious conditions.""", [("Enter the Seven Doors","doors")]),
"beans_escape":("The Secret Escape", """You help Beans slip away. Clawdius argues with an empty chair.

Beans joins you with a secret key and a new sense of freedom.""", [("Enter the Seven Doors","doors")]),
"doors":("Chapter 5 — The Seven Doors", """Seven doors bear the words **GREED, TRUTH, SILENCE, LOYALTY, MEMORY, DECEPTION, GUARDIAN**.

The Owl's feather glows.

*The last door opens only when the finder knows what the treasure is worth.*""", [("Use the Mirror or copied clue","doors_truth"),("Use Beans's key","doors_beans"),("Solve the trials yourself","doors_solve")]),
"doors_truth":("The Door of Truth", """The Mirror reveals:

*The treasure is not gold. It is the promise that someone will protect it.*

The doors open one by one. Cinnamon walks ahead.""", [("Enter the final chamber","final")]),
"doors_beans":("The Door of Loyalty", """Beans's key opens a hidden passage.

**Beans:** “I thought loyalty meant obeying. I think it means choosing who deserves it.”

The final chamber waits.""", [("Enter the final chamber","final")]),
"doors_solve":("The Door of the Guardian", """You solve the trials through patience, observation, and luck.

The final door opens.

*The finder has become the guardian.*""", [("Enter the final chamber","final")]),
"final":("Chapter 6 — The Final Treasure", """The chamber contains seven glowing artifacts. Together, they can grant one wish.

Clawdius arrives—enemy, ally, or reluctant companion depending on your decisions.

Cinnamon steps between him and the machine.

*Choose what the treasure becomes.*""", [("Claim the treasure","ending_claim"),("Destroy the machine","ending_destroy"),("Give it to Cinnamon","ending_cat"),("Give it to Clawdius","ending_baron"),("Restore the guardians","ending_guardians")]),
"ending_claim":("Ending — The Billionaire's Return", """You claim the treasures. The machine grants a fortune beyond counting.

Clawdius stares. Beans asks whether the money includes dental insurance.

Cinnamon is already planning a snack budget.""", [("See the epilogue","epilogue")]),
"ending_destroy":("Ending — Nothing for Greed", """You destroy the machine. The treasures dissolve into harmless light.

Clawdius is furious, but the Owl nods.

**Owl:** “A difficult choice. Perhaps the wisest.”""", [("See the epilogue","epilogue")]),
"ending_cat":("Ending — The Guardian Cat", """You give the treasures to Cinnamon. She becomes their guardian.

For once, she doesn't make a joke.

**Cinnamon:** “I will protect them.”

Beans smiles.""", [("See the epilogue","epilogue")]),
"ending_baron":("Ending — The Baron's Victory", """You hand the treasures to Clawdius. He raises his crown.

The machine asks: *What will you protect?*

Clawdius has no answer. The treasures vanish from his paws.""", [("See the epilogue","epilogue")]),
"ending_guardians":("Ending — The Forgotten Guardians", """You restore the seven guardians. The machine powers down peacefully.

Clawdius lowers his crown. Beans finally looks relieved.

The Owl closes his eyes, remembering.""", [("See the epilogue","epilogue")]),
"epilogue":("Epilogue — A Familiar Human", """The expedition returns home.

Aryan appears briefly at the door.

**Aryan:** “What happened?”

**Beans:** “A long story.”

Clawdius is still arguing with a cat carrier. Cinnamon places Mr. Squeaks on the table.

**Aryan:** “You went on another treasure hunt for that?”

Cinnamon gives a happy meow.

**Aryan:** “Of course you did.”

**THE END.**""", [("Finish the story","complete")]),
"complete":("Story Complete", """**THE LAST TREASURE MAP — COMPLETE**

Your decisions, discoveries, and ending have been saved.

Use the story command to review your ending or restart.""", [("Close controls","close")])
}
_LTM_ENDINGS={"ending_claim","ending_destroy","ending_cat","ending_baron","ending_guardians"}

def _ltm_record(guild_id,user_id):
    root=advanced_features_data.setdefault(_LTM_KEY,{})
    rec=root.setdefault(str(guild_id),{}).setdefault(str(user_id),{})
    rec.setdefault("stage","intro")
    rec.setdefault("flags",{})
    rec.setdefault("history",[])
    rec.setdefault("complete",False)
    rec.setdefault("ending",None)
    return rec


def _ltm_embed(stage,rec):
    title, _text, choices = _LTM_SCENES[stage]
    total=len(_LTM_SCENES)
    current=list(_LTM_SCENES).index(stage)+1
    e=cinnamon_story_controls_embed(title,
        "The narration is in the normal message above.\n\n**Choose what happens next using these buttons.**",
        color=_LTM_COLOR,footer=f"The Last Treasure Map • Scene {current}/{total} • Progress saves automatically")
    e.add_field(name="Expedition",value=f"{current}/{total} scenes",inline=True)
    e.add_field(name="Decisions",value=str(len(rec.get("history",[]))),inline=True)
    return e


async def _ltm_send_scene(user,guild_id,rec,stage):
    title,narration,choices=_LTM_SCENES[stage]
    await cinnamon_story_send_dm(user,narration,_ltm_embed(stage,rec),_LTMView(user.id,guild_id,stage))


class _LTMChoice(discord.ui.Button):
    def __init__(self,index,label):
        super().__init__(label=label[:80],style=discord.ButtonStyle.primary,row=0)
        self.choice_index=index
    async def callback(self,interaction):
        await self.view.choose(interaction,self.choice_index)


class _LTMView(discord.ui.View):
    def __init__(self,owner_id,guild_id,stage):
        super().__init__(timeout=1800)
        self.owner_id,self.guild_id,self.stage=owner_id,guild_id,stage
        for i,(label,_next) in enumerate(_LTM_SCENES[stage][2]):
            self.add_item(_LTMChoice(i,label))
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner_id:
            await interaction.response.send_message("🐾 This adventure belongs to another member. Start your own with /cinnamon last-treasure-map.",ephemeral=True)
            return False
        return True
    async def choose(self,interaction,index):
        rec=_ltm_record(self.guild_id,interaction.user.id)
        if rec.get("complete") or rec.get("stage")!=self.stage:
            return await interaction.response.send_message("Your story has moved on. Run /cinnamon last-treasure-map to resume.",ephemeral=True)
        await interaction.response.defer()
        label,next_stage=_LTM_SCENES[self.stage][2][index]
        rec["history"].append({"scene":self.stage,"choice":label})
        rec["history"]=rec["history"][-100:]
        rec["flags"][self.stage+"_"+str(index)]=True
        if self.stage=="final":
            rec["ending"]=next_stage
        if next_stage=="complete":
            rec["complete"]=True
        rec["stage"]=next_stage
        await bd_save_data()
        if next_stage=="close":
            return await interaction.edit_original_response(embed=cinnamon_story_controls_embed("🐾 Adventure closed","Your progress is saved. Run /cinnamon last-treasure-map to resume."),view=None)
        await _ltm_send_scene(interaction.user,self.guild_id,rec,next_stage)
        await interaction.edit_original_response(embed=cinnamon_story_controls_embed("✨ Decision saved",f"**{label}**\n\nThe next scene was sent as a normal message. Continue with its buttons.",color=_LTM_COLOR),view=None)


@_cinnamon_stories_group.command(name="last-treasure-map",description="Play or resume The Last Treasure Map")
@app_commands.guild_only()
async def last_treasure_map(interaction:discord.Interaction):
    rec=_ltm_record(interaction.guild.id,interaction.user.id)
    if rec.get("complete"):
        return await interaction.response.send_message("🏆 The Last Treasure Map is complete. Restart with /cinnamon last-treasure-map-restart confirm:True.",ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    try:
        await _ltm_send_scene(interaction.user,interaction.guild.id,rec,rec["stage"])
        await interaction.followup.send("🐾 **The Last Treasure Map** has been sent to your DMs. Story narration is a normal message; controls are a separate embed.",ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("I couldn't DM you. Enable server-member DMs, then run this command again.",ephemeral=True)


@_cinnamon_stories_group.command(name="last-treasure-map-restart",description="Restart The Last Treasure Map")
@app_commands.guild_only()
@app_commands.describe(confirm="Confirm erasing this story's choices and restarting")
async def last_treasure_map_restart(interaction:discord.Interaction,confirm:bool=False):
    rec=_ltm_record(interaction.guild.id,interaction.user.id)
    if not confirm:
        return await interaction.response.send_message("This resets The Last Treasure Map decisions and ending. Run /cinnamon last-treasure-map-restart confirm:True to confirm.",ephemeral=True)
    rec.update({"stage":"intro","flags":{},"history":[],"complete":False,"ending":None})
    await bd_save_data()
    await interaction.response.defer(ephemeral=True)
    try:
        await _ltm_send_scene(interaction.user,interaction.guild.id,rec,"intro")
        await interaction.followup.send("🐾 Restarted The Last Treasure Map in your DMs.",ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("I couldn't DM you. Enable server-member DMs and try again.",ephemeral=True)
