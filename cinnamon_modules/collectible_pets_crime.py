"""Collectible animal pets and a fictional Catnip crime mini-game."""
import random as _cp_random
import time as _cp_time

_COLLECTIBLE_PETS_KEY = "collectible_pets_v1"
_COLLECTIBLE_PET_CATALOG = [
    {"species":"Tabby Cat","emoji":"🐈","rarity":"Common","weight":28,"crime_luck":0.01,"crime_reward":0.03},
    {"species":"Puppy","emoji":"🐕","rarity":"Common","weight":25,"crime_luck":0.01,"fine_guard":0.05},
    {"species":"Bunny","emoji":"🐇","rarity":"Common","weight":20,"crime_luck":0.02},
    {"species":"Duckling","emoji":"🦆","rarity":"Common","weight":18,"crime_luck":0.01},
    {"species":"Hamster","emoji":"🐹","rarity":"Uncommon","weight":13,"crime_luck":0.02},
    {"species":"Fox","emoji":"🦊","rarity":"Uncommon","weight":11,"crime_luck":0.06},
    {"species":"Red Panda","emoji":"🦝","rarity":"Rare","weight":7,"crime_luck":0.04,"crime_reward":0.05},
    {"species":"Otter","emoji":"🦦","rarity":"Rare","weight":6,"crime_luck":0.03,"fine_guard":0.08},
    {"species":"Wolf Pup","emoji":"🐺","rarity":"Rare","weight":5,"crime_luck":0.04,"fine_guard":0.08},
    {"species":"Penguin","emoji":"🐧","rarity":"Epic","weight":2.5,"crime_luck":0.05},
    {"species":"Snow Leopard","emoji":"🐆","rarity":"Epic","weight":2,"crime_luck":0.06,"crime_reward":0.06},
    {"species":"Phoenix Chick","emoji":"🐦‍🔥","rarity":"Legendary","weight":0.6,"crime_luck":0.08,"fine_guard":0.12},
    {"species":"Moon Fox","emoji":"🌙","rarity":"Legendary","weight":0.5,"crime_luck":0.09,"crime_reward":0.08},
]

def _collectible_pet_user(guild_id, user_id):
    root = advanced_features_data.setdefault(_COLLECTIBLE_PETS_KEY, {})
    guild = root.setdefault(str(int(guild_id)), {})
    data = guild.setdefault(str(int(user_id)), {"pets": [], "active_id": None})
    if not isinstance(data.get("pets"), list):
        data["pets"] = []
    return data

def _collectible_pet_level(xp):
    level, remaining = 1, max(0, int(xp or 0))
    while level < 50 and remaining >= level * 100:
        remaining -= level * 100
        level += 1
    return level

def _collectible_pet_active(data):
    active_id = str(data.get("active_id") or "")
    return next((p for p in data.get("pets", []) if str(p.get("id")) == active_id), None)

async def collectible_pet_work_drop(guild_id, user):
    data = _collectible_pet_user(guild_id, user.id)
    active = _collectible_pet_active(data)
    if active:
        active["xp"] = int(active.get("xp", 0)) + 10
        active["level"] = _collectible_pet_level(active["xp"])
    found = None
    if len(data["pets"]) < 50 and _cp_random.random() < 0.07:
        species = _cp_random.choices(_COLLECTIBLE_PET_CATALOG, weights=[p["weight"] for p in _COLLECTIBLE_PET_CATALOG], k=1)[0]
        found = dict(species)
        found.update({"id":f"{int(_cp_time.time()*1000)}-{_cp_random.randint(100,999)}","xp":0,"level":1,"found_at":int(_cp_time.time())})
        data["pets"].append(found)
        if not data.get("active_id"):
            data["active_id"] = found["id"]
    await bd_save_data()
    if found:
        await economy_log(guild_id,title="🐾 Collectible pet discovered",fields=[
            ("Member",f"{user} ({user.id})"),("Pet",f"{found['emoji']} {found['species']}"),
            ("Rarity",found["rarity"]),("Collection size",str(len(data["pets"])))
        ])
    return found

def _collectible_pet_perks(guild_id, user_id):
    pet = _collectible_pet_active(_collectible_pet_user(guild_id,user_id))
    if not pet:
        return {"luck":0.0,"fine_guard":0.0,"reward":0.0,"pet":None}
    species = next((p for p in _COLLECTIBLE_PET_CATALOG if p["species"] == pet.get("species")), {})
    return {"luck":float(species.get("crime_luck",0.0)),
            "fine_guard":float(species.get("fine_guard",0.0)),
            "reward":float(species.get("crime_reward",0.0)),"pet":pet}

def _collectible_pet_embed(owner, data):
    pets = data.get("pets", [])
    active = _collectible_pet_active(data)
    description = f"**{len(pets)}/50 collected**\\n"
    description += (f"Active: {active['emoji']} **{active.get('nickname') or active['species']}** · {active.get('rarity','Common')} · Level {int(active.get('level',1))}"
                    if active else "No active pet yet. Find one with ?work.")
    embed = discord.Embed(title=f"🐾 {owner.display_name}'s Pet Collection",description=description,color=0xE89A3C)
    if not pets:
        embed.add_field(name="Empty collection",value="Use ?work for a chance to discover an animal companion.",inline=False)
    else:
        lines=[]
        for index, pet in enumerate(pets[:20],1):
            active_mark=" ⭐" if active and str(active.get("id"))==str(pet.get("id")) else ""
            lines.append(f"**{index}.** {pet.get('emoji','🐾')} **{pet.get('nickname') or pet.get('species','Unknown')}** · {pet.get('rarity','Common')} · Lv. {int(pet.get('level',1))}{active_mark}")
        embed.add_field(name="Collection",value="\\n".join(lines),inline=False)
    return embed

@bot.group(name="pets",aliases=["petcollection","collection"],invoke_without_command=True)
@commands.guild_only()
async def prefix_pets(ctx,member:discord.Member=None):
    owner=member or ctx.author
    await ctx.reply(embed=_collectible_pet_embed(owner,_collectible_pet_user(ctx.guild.id,owner.id)),
                    mention_author=False,allowed_mentions=discord.AllowedMentions.none())

@prefix_pets.command(name="equip")
async def prefix_pets_equip(ctx,index:int):
    data=_collectible_pet_user(ctx.guild.id,ctx.author.id); pets=data.get("pets",[])
    if not 1<=index<=len(pets):
        return await ctx.reply(f"Choose a pet number from 1 to {len(pets)}. Use ?pets to view your collection.",mention_author=False)
    old=data.get("active_id"); data["active_id"]=pets[index-1]["id"]
    if not await bd_save_data():
        data["active_id"]=old
        return await ctx.reply("I couldn't save that pet selection. No changes were kept.",mention_author=False)
    pet=pets[index-1]
    await ctx.reply(f"⭐ {pet['emoji']} **{pet.get('nickname') or pet['species']}** is now your active pet!",mention_author=False)

@prefix_pets.command(name="rename")
async def prefix_pets_rename(ctx,index:int,*,name:str):
    data=_collectible_pet_user(ctx.guild.id,ctx.author.id); pets=data.get("pets",[])
    if not 1<=index<=len(pets):
        return await ctx.reply(f"Choose a pet number from 1 to {len(pets)}. Use ?pets to view your collection.",mention_author=False)
    clean=" ".join(str(name).split()).strip()
    if not 1<=len(clean)<=24:
        return await ctx.reply("Pet names must be between 1 and 24 characters.",mention_author=False)
    old=pets[index-1].get("nickname"); pets[index-1]["nickname"]=clean
    if not await bd_save_data():
        if old is None: pets[index-1].pop("nickname",None)
        else: pets[index-1]["nickname"]=old
        return await ctx.reply("I couldn't save that name. Please try again later.",mention_author=False)
    await ctx.reply(f"🐾 Pet #{index} is now called **{clean}**.",mention_author=False)

@bot.command(name="crime")
@commands.guild_only()
async def prefix_crime(ctx):
    gid,uid=ctx.guild.id,ctx.author.id
    remaining=economy_cooldown_remaining(gid,uid,"crime")
    if remaining:
        return await ctx.reply(f"⏳ Your cartoon caper needs a break. Try again in **{remaining//60}m {remaining%60}s**.",mention_author=False)
    economy_cooldowns[(gid,uid,"crime")]=_cp_time.time()+1800
    perks=_collectible_pet_perks(gid,uid)
    chance=min(0.72,0.55+perks["luck"])
    caper=_cp_random.choice([
        "entered Cinnamon's imaginary cookie tournament",
        "tried to borrow a cardboard crown in a pretend story",
        "joined a suspicious game-show scavenger hunt",
        "tried to sneak an extra fish biscuit past the fictional snack inspector",
        "challenged an arcade prize machine to a dramatic duel",
    ])
    before=economy_balance(gid,uid)
    if _cp_random.random()<chance:
        reward=int(_cp_random.randint(100,260)*(1.0+perks["reward"]))
        economy_balances[(gid,uid)]=before+reward
        outcome=f"**Success!** Your fictional caper {caper} and you got **+{reward:,} Catnip**."
        change=reward
    else:
        fine=min(before,int(_cp_random.randint(40,100)*(1.0-perks["fine_guard"])))
        economy_balances[(gid,uid)]=before-fine
        outcome=f"**Caught!** The pretend snack inspector stopped the caper. Your cartoon fine was **-{fine:,} Catnip**."
        change=-fine
    await bd_save_data()
    await economy_log(gid,title="🎭 Fictional crime game",fields=[
        ("User",f"{ctx.author} ({uid})"),("Scenario",caper),("Outcome","Success" if change>=0 else "Caught"),
        ("Catnip change",f"{change:+,}"),("Balance",f"{economy_balance(gid,uid):,}")
    ])
    embed=cinnamon_embed("🎭 Cinnamon's Cartoon Caper",outcome,
        color=CINNAMON_GREEN if change>=0 else CINNAMON_RED,user=ctx.author,
        footer="Fictional economy mini-game • 30 minute cooldown")
    if perks["pet"]:
        pet=perks["pet"]
        cinnamon_field(embed,"🐾 Pet sidekick",f"{pet.get('emoji','🐾')} **{pet.get('nickname') or pet.get('species')}** · Level {int(pet.get('level',1))}",True)
    cinnamon_field(embed,"🌿 Catnip balance",f"**{economy_balance(gid,uid):,}**",True)
    await ctx.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none())
