"""Five additional replayable Cinnamon adventures. Loaded by main.py into its shared globals."""
import discord
from discord import app_commands

_XS_COLOR = 0xD98B3A
_XS_KEY = "cinnamon_extra_stories_v1"

# Every choice changes the next scene's flavor, flags, or route; the backbone
# converges so a run can always finish. Ending selection is deterministic.
_XS_STORIES = {
 "midnight": {
  "title":"The Midnight Server","icon":"🌒","genre":"Horror / Mystery",
  "intro":"**11:59 PM.** The server status says OFFLINE. Then a message appears in #general: *I can see you.*\n\n**Cinnamon:** “Ghost. Definitely a ghost.”\n**You:** “Could be a scheduled message.”\n**Cinnamon:** “I reject boring explanations.”\n\nA second message arrives—from a channel that was deleted three years ago. Cinnamon grabs your sleeve. “Hero, you are in front. I am behind you. For tactical reasons.”",
  "scenes":[
   ("The Silent Console","A monitor wakes in the dark. The cursor types your username, then **HELP**. Cinnamon's fur stands up.\n\n**Cinnamon:** “If this is a ghost, I am billing it for emotional damages.”",[("Inspect the logs","logs"),("Reply to the ghost","reply"),("Unplug the console","power")]),
   ("A Message from Nowhere","The reply comes back instantly: *You forgot the door.* A map of the server room flickers onto the monitor. Something taps from inside the locked cabinet. Cinnamon is now holding a keyboard as a shield.",[("Open the cabinet carefully","careful"),("Make Cinnamon knock","cat"),("Search the map first","map")]),
   ("The Forgotten Channel","The cabinet contains an old backup drive and a note: *The server remembers every restart.* A shadow crosses the doorway. Cinnamon whispers, “If it asks for a password, try tuna.”",[("Restore the backup","restore"),("Follow the shadow","shadow"),("Ask the voice its name","name")]),
   ("The Last Restart","The server begins counting down. The ghost isn't a person: it's a corrupted welcome-bot loop trapped in an old backup, repeating its first unanswered help request. Your actions decide whether it is freed—or accidentally made louder.",[("Answer its original request","kind"),("Delete the corrupted loop","delete"),("Restart everything blindly","blind")])
  ],
  "true":"You answer the forgotten help request and restore the clean backup. The ghost-message vanishes; a final **THANK YOU** appears. Cinnamon pretends she was never scared. Then the server pings: *Cinnamon has joined voice.* She screams. **TRUE ENDING — The Help That Was Heard**",
  "alt":["The loop is deleted. Silence returns—but the old backup is gone forever. Cinnamon calls it a victory and quietly saves a copy. **ENDING — Clean, Not Quite Kind**","The server restarts. The ghost is gone… and every channel now has 900 unread pings. **ENDING — The Infinite Notification**"]
 },
 "trial": {
  "title":"The Trial of Cinnamon","icon":"⚖️","genre":"Comedy / Detective",
  "intro":"The Royal Court of Catnip convenes. Cinnamon stands accused of stealing **9,001 Catnip** from the treasury.\n\n**Judge:** “How do you plead?”\n**Cinnamon:** “Hungry.”\n**Judge:** “That is not a plea.”\n**Cinnamon:** “It is a lifestyle.”\n\nYou are appointed defense hero. Cinnamon leans over: “Get me acquitted and I will… consider being grateful.”",
  "scenes":[
   ("Exhibit A: The Empty Vault","The vault is empty, but the lock is untouched. A glittering pawprint sits beside a suspicious tuna tin. Cinnamon says the tin is “unrelated evidence.”",[("Inspect the lock","lock"),("Question the guard","guard"),("Examine the tuna tin","tin")]),
   ("Three Very Suspicious Witnesses","The guard, treasurer, and a tiny accountant cat give contradictory statements. Cinnamon keeps objecting whenever anyone says “fish.”",[("Cross-examine the treasurer","treasurer"),("Question the accountant","accountant"),("Let Cinnamon testify","cinnamon")]),
   ("The Evidence Board","Your clues point toward a forged transfer receipt. The signature looks like Cinnamon's—but the ink is fresh and the treasury clock was stopped.",[("Expose the forged receipt","receipt"),("Reveal the clock trick","clock"),("Call for a recess","recess")]),
   ("Final Arguments","The judge asks for your conclusion. Cinnamon has prepared a speech consisting of 47 pages of “I am adorable.” You must present the evidence—not the fluff.",[("Present the complete evidence","truth"),("Blame the guard","blame"),("Use Cinnamon's charm","charm")])
  ],
  "true":"You prove the treasurer forged the transfer and used Cinnamon's pawprint stamp as a frame. The Catnip is recovered; Cinnamon is cleared. **Cinnamon:** “I knew you were brilliant. I have always said that. (I have not.)” **TRUE ENDING — Justice Is Served, Snacks Are Not**",
  "alt":["The guard is blamed without proof. Cinnamon is acquitted, but the real thief escapes. **ENDING — Technically Innocent**","Cinnamon charms the court. The judge acquits her—and orders a mandatory snack audit. **ENDING — Adorable but Accountable**"]
 },
 "heist": {
  "title":"Operation: Billion-Catnip","icon":"🕵️","genre":"Heist / Strategy",
  "intro":"Cinnamon unfolds a blueprint on your table. It is upside down, covered in biscuit crumbs, and titled **THE PERFECT HEIST**.\n\n**Cinnamon:** “The vault contains one billion Catnip.”\n**You:** “How do you know?”\n**Cinnamon:** “I made the number up. The vault is real.”\n\nYou are Chief Strategist. Cinnamon is Mastermind—and insists the getaway vehicle be a shopping trolley.",
  "scenes":[
   ("Recruitment & Recon","The vault sits beneath a museum. Three possible tools: a disguise kit, a silent gadget, or a map of the vents. Cinnamon has already recruited a pigeon.",[("Choose disguises","disguise"),("Choose silent tools","tools"),("Study the vents","vents")]),
   ("The Security Hall","Laser grids sweep the hall. A guard yawns. Cinnamon's pigeon is wearing a tiny headset and has no qualifications.",[("Distract the guard","guard"),("Time the laser cycle","laser"),("Send the pigeon","pigeon")]),
   ("Inside the Vault","The vault has three locks: logic, sound, and a ridiculous riddle. The alarm is not armed yet. Cinnamon is staring at a button labeled DO NOT PRESS.",[("Solve the locks properly","solve"),("Use your acquired gadget","gadget"),("Let Cinnamon press it","button")]),
   ("The Getaway","The treasure is secured. The museum doors begin closing; Clawdius's security team blocks the trolley route. Your last decision determines whether the heist becomes legendary or merely loud.",[("Escape through the planned route","plan"),("Create a clever diversion","diversion"),("Trust Cinnamon's trolley","trolley")])
  ],
  "true":"Your preparation, timing, and calm diversion get the crew out cleanly. The vault's decoy ledger exposes Clawdius's own attempted theft. Cinnamon declares the operation flawless; you quietly correct the blueprint. **TRUE ENDING — The Billion-Catnip Masterplan**",
  "alt":["You escape with the treasure, but the alarm plays Cinnamon's voice saying “I regret nothing” on loop. **ENDING — Loud and Rich**","The trolley crashes into a display of commemorative spoons. You escape with a smaller prize and a very large spoon. **ENDING — Spoon Heist**"]
 },
 "carnival": {
  "title":"The Carnival That Never Closes","icon":"🎪","genre":"Horror / Fantasy",
  "intro":"A carnival appears at the edge of town at 2 AM. Its lights pulse with no electricity. Every ticket reads **ONE MEMORY**.\n\n**Cinnamon:** “Free rides?”\n**You:** “The ticket costs a memory.”\n**Cinnamon:** “I have forgotten where I put lunch. That counts?”\n\nThe gates close behind you. The exit sign turns into an arrow pointing deeper inside.",
  "scenes":[
   ("The Ticket Booth","A masked ticket seller offers three attractions. Behind him, a mirror shows the carnival empty—and a second version of you waving.",[("Ask the seller about the exit","seller"),("Inspect the mirror","mirror"),("Refuse the ticket","refuse")]),
   ("The Carousel of Yesterday","The carousel plays a tune from a memory you recognize. Cinnamon rides a wooden fish and shouts, “THIS IS NOT A FISH. IT IS A HORSE WITH AMBITIONS.”",[("Follow the familiar tune","tune"),("Break the music box","box"),("Read the carved names","names")]),
   ("The Hall of Lost Guests","Portraits whisper clues. One portrait is Cinnamon, wearing a crown and looking deeply unimpressed. The walls rearrange when you blink.",[("Follow the portraits","portraits"),("Mark the walls","mark"),("Ask Cinnamon what she remembers","memory")]),
   ("The Ringmaster's Stage","The Ringmaster reveals the carnival feeds on forgotten promises. The true exit opens only when a guest remembers and keeps one promise. Cinnamon suddenly goes quiet.",[("Keep your promise to leave together","promise"),("Offer a false memory","fake"),("Challenge the Ringmaster","challenge")])
  ],
  "true":"You remember the promise made at the gate—to leave together—and refuse to abandon Cinnamon. The lights stop pulsing; every guest's memory returns. Cinnamon holds your hand for exactly two seconds, then says it was “a tactical grip.” **TRUE ENDING — The Last Honest Ticket**",
  "alt":["A false memory buys freedom for you, but the carnival remains. Cinnamon escapes later and is furious. **ENDING — One Ticket, Two Regrets**","You defeat the Ringmaster, but the carnival dissolves with its memories. **ENDING — The Empty Fairground**"]
 },
 "delivery": {
  "title":"The Last Delivery","icon":"📦","genre":"Fantasy / Adventure",
  "intro":"A courier knocks at Cinnamon's door and hands her a sealed package marked **DELIVER BEFORE MIDNIGHT — NO EXCEPTIONS**.\n\n**Cinnamon:** “Is it food?”\n**Courier:** “No.”\n**Cinnamon:** “Then why am I involved?”\n\nThe address is missing. The package hums softly. You become the hero responsible for delivering it—and Cinnamon immediately appoints herself Head of Parcel Security.",
  "scenes":[
   ("The Addressless Parcel","A tiny star glows beneath the seal. Three clues appear: a map fragment, a feather, and a warm compass. Cinnamon tries to shake the box. You stop her.",[("Study the map fragment","map"),("Inspect the feather","feather"),("Follow the compass","compass")]),
   ("The Bridge of Questions","A bridge guardian asks what the package carries. The box answers with a heartbeat. Cinnamon says, “Probably a very small drum.”",[("Tell the truth","truth"),("Answer with a riddle","riddle"),("Let Cinnamon negotiate","negotiate")]),
   ("The Stormglass Tower","The tower's stairs shift with every lie. At the top, a keeper explains the parcel contains a lost star's final light—not a weapon, but a promise to someone waiting.",[("Climb carefully and protect it","careful"),("Use the feather as a guide","guide"),("Rush before midnight","rush")]),
   ("The Door at Midnight","The recipient waits behind a door that opens only to a sincere delivery. The star's light dims. Cinnamon finally admits she was afraid the package would be empty.",[("Deliver it with the truth","sincere"),("Keep the star for Cinnamon","keep"),("Ask the recipient to wait","wait")])
  ],
  "true":"You deliver the star and its promise just before midnight. A forgotten constellation lights up; the recipient smiles. Cinnamon watches quietly, then claims she was checking parcel integrity. **TRUE ENDING — A Promise Delivered**",
  "alt":["Cinnamon keeps the star. It shines for a night, then fades; she returns it with an apology. **ENDING — Borrowed Starlight**","The recipient waits, but midnight passes. The promise survives—its delivery delayed. **ENDING — Almost on Time**"]
 }
}

class _XSMenu(discord.ui.View):
 def __init__(self,owner): super().__init__(timeout=240); self.owner=owner; self.add_item(_XSSelect())
 async def interaction_check(self,i):
  if i.user.id!=self.owner: await i.response.send_message("🐾 This story menu belongs to its player. Use /cinnamon-adventures for your own.",ephemeral=True); return False
  return True
class _XSSelect(discord.ui.Select):
 def __init__(self):
  super().__init__(placeholder="Choose a new adventure…",min_values=1,max_values=1,options=[discord.SelectOption(label=s["title"],value=k,description=s["genre"],emoji=s["icon"]) for k,s in _XS_STORIES.items()])
 async def callback(self,i):
  await i.response.defer(ephemeral=True)
  await _xs_show(i,self.values[0],0,{},False)
class _XSReplay(discord.ui.View):
 def __init__(self,owner,key):
  super().__init__(timeout=240); self.owner=owner; self.key=key
  b=discord.ui.Button(label="Replay this story",style=discord.ButtonStyle.success)
  async def replay(i):
   await i.response.defer(ephemeral=True)
   await _xs_show(i,self.key,0,{},False)
  b.callback=replay; self.add_item(b)
 async def interaction_check(self,i):
  if i.user.id!=self.owner: await i.response.send_message("🐾 Only the original hero can replay this run.",ephemeral=True); return False
  return True

class _XSChoices(discord.ui.View):
 def __init__(self,owner,key,stage,flags,ending=False):
  super().__init__(timeout=240); self.owner=owner; self.key=key; self.stage=stage; self.flags=flags
  story=_XS_STORIES[key]
  if ending: self.add_item(discord.ui.Button(label="Play again",style=discord.ButtonStyle.success,custom_id="xs_replay_disabled",disabled=True))
  else:
   choices=story["scenes"][stage][2]
   for n,(label,flag) in enumerate(choices):
    b=discord.ui.Button(label=label[:80],style=discord.ButtonStyle.primary,row=n)
    b.callback=self._callback(n); self.add_item(b)
 async def interaction_check(self,i):
  if i.user.id!=self.owner: await i.response.send_message("🐾 Only the hero who started this run can choose.",ephemeral=True); return False
  return True
 def _callback(self,n):
  async def cb(i):
   await i.response.defer(ephemeral=True)
   f=dict(self.flags); f.setdefault("choices",[]); f["choices"].append(_XS_STORIES[self.key]["scenes"][self.stage][2][n][1]); f["hero"]=True
   if self.stage==3:
    outcome=_xs_ending(self.key,f)
    await _xs_show(i,self.key,4,f,True,outcome)
   else: await _xs_show(i,self.key,self.stage+1,f,False)
  return cb

def _xs_ending(key,flags):
 choices=flags.get("choices",[])
 if key=="midnight" and any(x in choices for x in ("kind","logs","name")): return 0
 if key=="trial" and "truth" in choices: return 0
 if key=="heist" and all(x in choices for x in ("solve","plan")): return 0
 if key=="carnival" and "promise" in choices: return 0
 if key=="delivery" and "sincere" in choices: return 0
 return 1 if len(choices)%2 else 2

async def _xs_show(i,key,stage,flags,ending,outcome=None):
 story=_XS_STORIES[key]; color=_XS_COLOR
 if stage<4:
  title,text,choices=story["scenes"][stage]
  history=flags.get("choices",[])
  # Choice-specific reactions make the player's previous action visibly matter.
  reaction=""
  if history:
   last=history[-1]
   reaction={
    "logs":"Your log inspection exposes a timestamp that does not belong.",
    "reply":"Your message earns a reply—and a very offended static crackle.",
    "power":"The lights die. Something taps on the backup battery.",
    "careful":"You proceed slowly; a hidden clue survives.",
    "cat":"Cinnamon knocks. The cabinet knocks back. She immediately blames you.",
    "map":"The map reveals a route nobody noticed.",
    "lock":"The lock has no scratches. This was an inside job.",
    "guard":"The guard's story changes halfway through.",
    "tin":"The tin has a treasury seal beneath the label.",
    "treasurer":"The treasurer contradicts the official ledger.",
    "accountant":"The accountant produces a tiny but devastating receipt.",
    "cinnamon":"Cinnamon's testimony is 80% snacks, 20% accidental truth.",
    "receipt":"The ink is fresh. Your evidence board gets a new red string.",
    "clock":"The stopped clock explains the impossible timestamp.",
    "recess":"During recess, you catch the suspect moving a folder.",
    "disguise":"Your disguise works. Cinnamon's moustache does not.",
    "tools":"The silent gadget saves you from an alarm.",
    "vents":"The vents lead to a maintenance hatch—and a pigeon.",
    "guard":"The guard looks away at exactly the right moment.",
    "laser":"You time the laser cycle perfectly.",
    "pigeon":"The pigeon returns with a key and an HR complaint.",
    "solve":"You solve the locks without triggering the alarm.",
    "gadget":"The gadget opens one lock; your logic opens the rest.",
    "button":"Cinnamon presses it. The vault plays elevator music.",
    "plan":"Your planned route gets the team to the exit.",
    "diversion":"The diversion works; Cinnamon improvises a musical number.",
    "trolley":"The trolley is faster than expected and less controllable.",
    "seller":"The seller's mask slips; he knows the exit is fake.",
    "mirror":"The mirror shows a clue in your reflection.",
    "refuse":"Refusing the ticket reveals the carnival's first rule.",
    "tune":"The tune points toward a hidden promise.",
    "box":"The music box stops; the walls stop moving.",
    "names":"The names reveal who has been trapped longest.",
    "portraits":"The portraits form a map when viewed together.",
    "mark":"Your marks prevent the hallway from resetting.",
    "memory":"Cinnamon remembers a promise she tried to forget.",
    "promise":"The promise steadies the stage; the Ringmaster loses control.",
    "fake":"The false memory cracks; the exit becomes unstable.",
    "challenge":"The Ringmaster accepts—and cheats spectacularly.",
    "map":"The map points to a forgotten delivery route.",
    "feather":"The feather points toward the recipient.",
    "compass":"The compass warms when you face the right direction.",
    "truth":"The guardian trusts your honest answer.",
    "riddle":"The riddle opens the bridge, though Cinnamon claims credit.",
    "negotiate":"Cinnamon negotiates three snacks and accidentally tells the truth.",
    "careful":"You protect the parcel from the shifting stairs.",
    "guide":"The feather lights a safe path.",
    "rush":"You reach the top, but the star dims.",
    "sincere":"The sincere delivery restores the star's light.",
    "keep":"The star glows briefly in Cinnamon's paws.",
    "wait":"The recipient agrees to wait, but the clock keeps moving."
   }.get(last,"Your decision changes the route; the adventure continues.")
  desc=text+"\n\n"+reaction+"\n\n**Your move, Hero.**"
  view=_XSChoices(i.user.id,key,stage,flags)
  await i.edit_original_response(embed=discord.Embed(title=title,description=desc[:4000],color=color).set_footer(text="Cinnamon Adventures • Choices matter • Progress is per player"),view=view)
 else:
  endings=[story["true"],*story["alt"]]; ending=endings[outcome or 0]
  embed=discord.Embed(title=("🌟 TRUE ENDING" if outcome==0 else "🎭 ALTERNATE ENDING")+" • "+story["title"],description=ending,color=color)
  embed.add_field(name="Run complete",value=f"Choices made: {len(flags.get('choices',[]))}\nEnding: {'TRUE' if outcome==0 else 'ALTERNATE'}",inline=False)
  embed.set_footer(text="Start another adventure with /cinnamon-adventures")
  await i.edit_original_response(embed=embed,view=_XSReplay(i.user.id,key))

@bot.tree.command(name="cinnamon-adventures",description="Play five new branching Cinnamon stories")
@app_commands.guild_only()
async def cinnamon_extra_adventures(interaction:discord.Interaction):
 embed=discord.Embed(title="🐈 Cinnamon • New Adventures",description="Five new playable adventures. You are the hero; Cinnamon is the chaotic main character. Choices change scenes, and each story has one canon TRUE ENDING.",color=_XS_COLOR)
 for k,s in _XS_STORIES.items(): embed.add_field(name=s["icon"]+" "+s["title"],value=s["genre"],inline=True)
 await interaction.response.send_message(embed=embed,view=_XSMenu(interaction.user.id),ephemeral=True)
