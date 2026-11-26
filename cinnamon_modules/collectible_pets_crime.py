"""Collectible animal pets and a fictional Catnip crime mini-game."""
import copy as _cp_copy
import random as _cp_random
import time as _cp_time

_COLLECTIBLE_PETS_KEY = "collectible_pets_v1"
_COLLECTIBLE_PET_CATALOG = [
    {"species":"Tabby Cat","emoji":"🐈","rarity":"Common","weight":28,"ability":"work_income"},
    {"species":"Puppy","emoji":"🐕","rarity":"Common","weight":25,"ability":"crime_income"},
    {"species":"Bunny","emoji":"🐇","rarity":"Common","weight":20,"ability":"fine_amount"},
    {"species":"Duck","emoji":"🦆","rarity":"Common","weight":18,"ability":"fine_chance"},
    {"species":"Hamster","emoji":"🐹","rarity":"Uncommon","weight":13,"ability":"mystery_chance"},
    {"species":"Fox","emoji":"🦊","rarity":"Uncommon","weight":11,"ability":"fox"},
    {"species":"Parrot","emoji":"🦜","rarity":"Uncommon","weight":10,"ability":"fish_sale"},
    {"species":"Red Panda","emoji":"🐼","rarity":"Rare","weight":7,"ability":"shop_discount"},
    {"species":"Otter","emoji":"🦦","rarity":"Rare","weight":6,"ability":"rare_fish"},
    {"species":"Wolf Pup","emoji":"🐺","rarity":"Rare","weight":5,"ability":"xp"},
    {"species":"Deer","emoji":"🦌","rarity":"Rare","weight":5,"ability":"forage"},
    {"species":"Penguin","emoji":"🐧","rarity":"Epic","weight":2.5,"ability":"penguin"},
    {"species":"Snow Leopard","emoji":"🐆","rarity":"Epic","weight":2,"ability":"all_rewards"},
    {"species":"Phoenix Chick","emoji":"🐦‍🔥","rarity":"Legendary","weight":0.6,"ability":"ingredient_refund"},
    {"species":"Moon Fox","emoji":"🌙","rarity":"Legendary","weight":0.5,"ability":"box_upgrade"},
    {"species":"Raccoon","emoji":"🦝","rarity":"Mythical","weight":0.15,"ability":"shop_steal"},
]

_PET_ABILITY_MAX_LEVEL = 10
_PET_BASE_SLOTS = 5
_PET_SLOT_MEMBER_KEY = "pet_slot_member_bonus_v1"
_PET_SLOT_ROLE_KEY = "pet_slot_role_bonus_v1"

def _collectible_pet_capacity(guild_id, user_id, member=None):
    """Five base slots plus achievement, purchased, admin and role bonuses."""
    data = _collectible_pet_user(guild_id, user_id)
    capacity = _PET_BASE_SLOTS + max(0, int(data.get("achievement_slots", 0) or 0))
    capacity += max(0, int(data.get("purchased_slots", 0) or 0))
    capacity += max(0, int(data.get("story_slots", 0) or 0))
    member_root = advanced_features_data.get(_PET_SLOT_MEMBER_KEY, {})
    capacity += max(0, int((member_root.get(str(int(guild_id)), {}) or {}).get(str(int(user_id)), 0) or 0))
    role_root = advanced_features_data.get(_PET_SLOT_ROLE_KEY, {})
    role_cfg = role_root.get(str(int(guild_id)), {}) or {}
    if member is None:
        guild_obj = bot.get_guild(int(guild_id)) if "bot" in globals() else None
        member = guild_obj.get_member(int(user_id)) if guild_obj else None
    if member:
        for role in getattr(member, "roles", []):
            capacity += max(0, int(role_cfg.get(str(int(role.id)), 0) or 0))
    return max(_PET_BASE_SLOTS, min(500, capacity))

def _collectible_pet_ability(guild_id, user_id):
    root = advanced_features_data.get(_COLLECTIBLE_PETS_KEY, {})
    guild = root.get(str(int(guild_id)), {}) if isinstance(root, dict) else {}
    data = guild.get(str(int(user_id)), {}) if isinstance(guild, dict) else {}
    pet = _collectible_pet_active(data) if isinstance(data, dict) else None
    if not pet:
        return {"pet": None, "species": None, "ability": None, "level": 0, "value": 0.0}
    catalog = next((p for p in _COLLECTIBLE_PET_CATALOG if p["species"] == pet.get("species")), {})
    level = max(1, min(_PET_ABILITY_MAX_LEVEL, int(pet.get("level", 1) or 1)))
    ability = catalog.get("ability")
    if ability in {"work_income", "crime_income", "fine_amount", "xp", "fish_sale", "forage", "fox"}:
        value = 0.01 * level
    elif ability == "shop_discount":
        value = 0.005 * level
    elif ability in {"fine_chance", "rare_fish", "all_rewards"}:
        value = 0.005 * level
    elif ability == "mystery_chance":
        value = 0.005 + ((level - 1) * (0.02 / 9.0))
    elif ability in {"ingredient_refund", "box_upgrade", "shop_steal", "penguin"}:
        value = 0.01 * level
    else:
        value = 0.0
    secondary = 0.005 * level if ability in {"fox", "penguin"} else 0.0
    return {"pet": pet, "species": pet.get("species"), "ability": ability, "level": level, "value": value, "secondary_value": secondary}


def _collectible_pet_user(guild_id, user_id):
    root = advanced_features_data.setdefault(_COLLECTIBLE_PETS_KEY, {})
    guild = root.setdefault(str(int(guild_id)), {})
    data = guild.setdefault(str(int(user_id)), {"pets": [], "active_id": None})
    if not isinstance(data.get("pets"), list):
        data["pets"] = []
    return data

def _collectible_pet_level(xp):
    level, remaining = 1, max(0, int(xp or 0))
    while level < 10 and remaining >= level * 100:
        remaining -= level * 100
        level += 1
    return min(10, level)

def _collectible_pet_active(data):
    active_id = str(data.get("active_id") or "")
    return next((p for p in data.get("pets", []) if str(p.get("id")) == active_id), None)

async def collectible_pet_work_drop(guild_id, user):
    """Award pet XP/discoveries only when the updated pet state is durably saved."""
    root = advanced_features_data.setdefault(_COLLECTIBLE_PETS_KEY, {})
    guild_key = str(int(guild_id))
    user_key = str(int(user.id))
    guild = root.setdefault(guild_key, {})
    had_user = user_key in guild
    before = _cp_copy.deepcopy(guild.get(user_key)) if had_user else None
    data = _collectible_pet_user(guild_id, user.id)
    active = _collectible_pet_active(data)
    if active:
        active["xp"] = int(active.get("xp", 0)) + 10
        active["level"] = _collectible_pet_level(active["xp"])
    found = None
    capacity_fn = globals().get("_collectible_pet_capacity")
    capacity = capacity_fn(guild_id, user.id) if callable(capacity_fn) else 5
    if len(data["pets"]) < capacity and _cp_random.random() < 0.07:
        species = _cp_random.choices(_COLLECTIBLE_PET_CATALOG, weights=[pet["weight"] for pet in _COLLECTIBLE_PET_CATALOG], k=1)[0]
        found = dict(species)
        found.update({"id": f"{int(_cp_time.time() * 1000)}-{_cp_random.randint(100, 999)}", "xp": 0, "level": 1, "found_at": int(_cp_time.time())})
        data["pets"].append(found)
        if not data.get("active_id"):
            data["active_id"] = found["id"]
    try:
        saved = await bd_save_data()
    except Exception:
        saved = False
        if "log" in globals():
            log.exception("Failed to save collectible pet progress for guild %s user %s", guild_id, user.id)
    if not saved:
        if had_user:
            guild[user_key] = before
        else:
            guild.pop(user_key, None)
        if not guild:
            root.pop(guild_key, None)
        if not root:
            advanced_features_data.pop(_COLLECTIBLE_PETS_KEY, None)
        return None
    if found:
        await economy_log(guild_id, title="🐾 Collectible pet discovered", fields=[
            ("Member", f"{user} ({user.id})"), ("Pet", f"{found['emoji']} {found['species']}"),
            ("Rarity", found["rarity"]), ("Collection size", str(len(data["pets"]))),
        ])
    return found

def collectible_pet_raccoon_steal(guild_id, user_id):
    """Roll once on a completed work/shop action; only explicitly eligible items qualify."""
    pet = _collectible_pet_ability(guild_id, user_id)
    if pet.get("ability") != "shop_steal" or _cp_random.random() >= float(pet.get("value", 0.0)):
        return None
    inventory = economy_inventory_for(guild_id, user_id)
    expired_fn = globals().get("_shop_item_expired")
    eligible = []
    for item_id, item in ECONOMY_ITEMS.items():
        if not isinstance(item, dict) or not item.get("shop_enabled", True) or not item.get("pet_abilities_enabled", False):
            continue
        if not item.get("stock_unlimited", True) and int(item.get("stock_quantity", 0) or 0) <= 0:
            continue
        if callable(expired_fn) and expired_fn(item):
            continue
        limit = max(0, int(item.get("max_per_person", 0) or 0))
        if limit and int(inventory.get(str(item_id), 0)) >= limit:
            continue
        eligible.append((str(item_id), item))
    if not eligible:
        return None
    # Price-weighted odds: expensive eligible items are possible but progressively rarer.
    weights = [1.0 / max(1, int(item.get("price", 1))) for _, item in eligible]
    item_id, item = _cp_random.choices(eligible, weights=weights, k=1)[0]
    inventory[item_id] = int(inventory.get(item_id, 0)) + 1
    return str(item.get("name", item_id))

def collectible_pet_catnip_bonus(guild_id, user_id, amount):
    """Apply the equipped Snow Leopard's universal Catnip reward bonus."""
    amount = max(0, int(amount))
    pet = _collectible_pet_ability(guild_id, user_id)
    if pet.get("ability") == "all_rewards":
        return amount + int(amount * float(pet.get("value", 0.0)))
    return amount

def _collectible_pet_perks(guild_id, user_id):
    """Compatibility adapter; only the equipped pet contributes an ability."""
    result = _collectible_pet_ability(guild_id, user_id)
    return {"luck": 0.0, "fine_guard": 0.0, "reward": 0.0, **result}

def _collectible_pet_embed(owner, data):
    pets = data.get("pets", [])
    active = _collectible_pet_active(data)
    capacity = _collectible_pet_capacity(owner.guild.id, owner.id, owner) if getattr(owner, "guild", None) else 5
    description = f"**{len(pets)}/{capacity} collected**\n"
    description += (f"Active: {active['emoji']} **{active.get('nickname') or active['species']}** · {active.get('rarity','Common')} · Level {min(10, int(active.get('level',1)))}"
                    if active else "No active pet yet. Find one with ?work.")
    if active:
        ability = _collectible_pet_ability(owner.guild.id, owner.id) if getattr(owner, "guild", None) else {}
        ability_names = {
            "work_income":"Work income", "crime_income":"Crime income", "fine_amount":"Fine reduction",
            "fine_chance":"Fine chance reduction", "mystery_chance":"Mystery Box chance", "fox":"Crime income + fine chance",
            "fish_sale":"Fish sale bonus", "shop_discount":"Shop discount", "rare_fish":"Rare fish chance",
            "xp":"XP bonus", "forage":"Bonus ingredients", "penguin":"Double fish + fish return",
            "all_rewards":"XP + Catnip bonus", "ingredient_refund":"Crafting ingredient refund",
            "box_upgrade":"Mystery Box tier upgrade", "shop_steal":"Shop item theft"
        }
        description += "\\nAbility: **" + ability_names.get(ability.get("ability"), "Companion ability") + "** · " + f"{ability.get('value',0)*100:.1f}% at this level"
    accessory_catalog = globals().get("_PET_ACCESSORIES", {})
    active_accessory = accessory_catalog.get(active.get("accessory_id")) if active else None
    if active_accessory:
        description += f"\nAccessory: {active_accessory.get('emoji', '✨')} **{active_accessory.get('name', 'Accessory')}**"
    embed = discord.Embed(title=f"🐾 {owner.display_name}'s Pet Collection",description=description,color=0xE89A3C)
    if not pets:
        embed.add_field(name="Empty collection",value="Use ?work for a chance to discover an animal companion.",inline=False)
    else:
        lines=[]
        for index, pet in enumerate(pets[:20],1):
            active_mark=" ⭐" if active and str(active.get("id"))==str(pet.get("id")) else ""
            lines.append(f"**{index}.** {pet.get('emoji','🐾')} **{pet.get('nickname') or pet.get('species','Unknown')}** · {pet.get('rarity','Common')} · Lv. {int(pet.get('level',1))}{active_mark}")
        embed.add_field(name="Collection",value="\n".join(lines),inline=False)
    owned_accessories = data.get("accessories", [])
    if isinstance(owned_accessories, list) and owned_accessories:
        accessory_lines = []
        for accessory_id in owned_accessories:
            accessory = accessory_catalog.get(accessory_id)
            if accessory:
                accessory_lines.append(f"{accessory.get('emoji', '✨')} **{accessory.get('name', 'Accessory')}**")
        if accessory_lines:
            embed.add_field(name="Accessory collection", value="\n".join(accessory_lines[:10]), inline=False)
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
    gid, uid = ctx.guild.id, ctx.author.id
    cooldown_key = (gid, uid, "crime")
    balance_key = (gid, uid)
    remaining = economy_cooldown_remaining(gid, uid, "crime")
    if remaining:
        return await ctx.reply(f"⏳ Your cartoon caper needs a break. Try again in **{remaining // 60}m {remaining % 60}s**.", mention_author=False)
    had_balance = balance_key in economy_balances
    previous_balance = economy_balances.get(balance_key)
    had_cooldown = cooldown_key in economy_cooldowns
    previous_cooldown = economy_cooldowns.get(cooldown_key)
    perks = _collectible_pet_perks(gid, uid)
    ability = perks.get("ability")
    # Duck and Fox reduce fine probability; Bunny reduces fine size.
    fine_chance_reduction = perks.get("value", 0.0) if ability == "fine_chance" else (perks.get("secondary_value", 0.0) if ability == "fox" else 0.0)
    chance = min(0.72, 0.55 + fine_chance_reduction)
    caper = _cp_random.choice([
        "entered Cinnamon's imaginary cookie tournament",
        "tried to borrow a cardboard crown in a pretend story",
        "joined a suspicious game-show scavenger hunt",
        "tried to sneak an extra fish biscuit past the fictional snack inspector",
        "challenged an arcade prize machine to a dramatic duel",
    ])
    before = economy_balance(gid, uid)
    if _cp_random.random() < chance:
        reward_bonus = perks.get("value", 0.0) if ability in {"crime_income", "fox"} else 0.0
        reward = int(_cp_random.randint(100, 260) * (1.0 + reward_bonus))
        if ability == "all_rewards":
            bonus_fn = globals().get("collectible_pet_catnip_bonus")
            if callable(bonus_fn):
                reward = bonus_fn(gid, uid, reward)
        economy_balances[balance_key] = before + reward
        outcome = f"**Success!** Your fictional caper {caper} and you got **+{reward:,} Catnip**."
        change = reward
    else:
        fine_reduction = perks.get("value", 0.0) if ability == "fine_amount" else 0.0
        fine = min(before, int(_cp_random.randint(40, 100) * (1.0 - fine_reduction)))
        economy_balances[balance_key] = before - fine
        outcome = f"**Caught!** The pretend snack inspector stopped the caper. Your cartoon fine was **-{fine:,} Catnip**."
        change = -fine
    economy_cooldowns[cooldown_key] = _cp_time.time() + 1800
    try:
        saved = await bd_save_data()
    except Exception:
        saved = False
        if "log" in globals():
            log.exception("Failed to save cartoon caper transaction for guild %s user %s", gid, uid)
    if not saved:
        if had_balance:
            economy_balances[balance_key] = previous_balance
        else:
            economy_balances.pop(balance_key, None)
        if had_cooldown:
            economy_cooldowns[cooldown_key] = previous_cooldown
        else:
            economy_cooldowns.pop(cooldown_key, None)
        return await ctx.reply("⚠️ Cinnamon couldn't save this caper, so no Catnip or cooldown change was applied. Please try again.",
            mention_author=False, allowed_mentions=discord.AllowedMentions.none())
    box = False
    box_fn = globals().get("advanced_maybe_award_box")
    if callable(box_fn):
        try:
            box = await box_fn(gid, ctx.author, "crime")
        except Exception:
            log.exception("Mystery Box award failed after fictional crime game")
    await economy_log(gid, title="🎭 Fictional crime game", fields=[
        ("User", f"{ctx.author} ({uid})"), ("Scenario", caper),
        ("Outcome", "Success" if change >= 0 else "Caught"),
        ("Catnip change", f"{change:+,}"), ("Balance", f"{economy_balance(gid, uid):,}"),
    ])
    embed = cinnamon_embed("🎭 Cinnamon's Cartoon Caper", outcome,
        color=CINNAMON_GREEN if change >= 0 else CINNAMON_RED, user=ctx.author,
        footer="Fictional economy mini-game • 30 minute cooldown")
    if perks["pet"]:
        pet = perks["pet"]
        cinnamon_field(embed, "🐾 Pet sidekick",
            f"{pet.get('emoji', '🐾')} **{pet.get('nickname') or pet.get('species')}** · Level {int(pet.get('level', 1))}", True)
    cinnamon_field(embed, "🌿 Catnip balance", f"**{economy_balance(gid, uid):,}**", True)
    if box:
        cinnamon_field(embed, "🎁 Mystery Box", "A Mystery Box was found during the caper!")
    await ctx.reply(embed=embed, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
