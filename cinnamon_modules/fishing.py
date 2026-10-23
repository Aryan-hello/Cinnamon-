"""Cinnamon Fishing & Cooking: persistent, quest-aware collection gameplay.

Inspired by genre patterns (weighted rarity, a collection journal, progression,
crafting/cooking and leaderboards) without copying another bot's content.
Loaded into main.py's shared namespace; do not run directly.
"""

def _fishing_root():
    # Always resolve through the shared persisted dictionary: the loader updates
    # advanced_features_data in place when restoring a saved snapshot.
    root = ADVANCED_FEATURES.setdefault("fishing", {})
    root.setdefault("players", {})
    root.setdefault("daily", {})
    return root

_fishing_root()

FISH_SPECIES = {
    "minnow": {"name":"Minnow", "emoji":"🐟", "rarity":"Common", "weight":13, "price":35, "xp":8},
    "anchovy": {"name":"Anchovy", "emoji":"🐟", "rarity":"Common", "weight":13, "price":40, "xp":8},
    "pond_carp": {"name":"Pond Carp", "emoji":"🐠", "rarity":"Common", "weight":13, "price":45, "xp":9},
    "silver_sardine": {"name":"Silver Sardine", "emoji":"🐟", "rarity":"Common", "weight":13, "price":50, "xp":9},
    "bluegill": {"name":"Bluegill", "emoji":"🐠", "rarity":"Common", "weight":13, "price":55, "xp":10},
    "river_trout": {"name":"River Trout", "emoji":"🐟", "rarity":"Uncommon", "weight":7, "price":90, "xp":15},
    "golden_perch": {"name":"Golden Perch", "emoji":"🐠", "rarity":"Uncommon", "weight":7, "price":110, "xp":17},
    "moon_koi": {"name":"Moon Koi", "emoji":"🐟", "rarity":"Uncommon", "weight":8, "price":140, "xp":20},
    "coral_snapper": {"name":"Coral Snapper", "emoji":"🐠", "rarity":"Rare", "weight":3, "price":240, "xp":30},
    "glass_eel": {"name":"Glass Eel", "emoji":"🐍", "rarity":"Rare", "weight":3, "price":280, "xp":35},
    "frost_salmon": {"name":"Frost Salmon", "emoji":"🐟", "rarity":"Rare", "weight":3, "price":320, "xp":38},
    "sunscale_tuna": {"name":"Sunscale Tuna", "emoji":"🐟", "rarity":"Epic", "weight":1, "price":600, "xp":60},
    "storm_ray": {"name":"Storm Ray", "emoji":"🪽", "rarity":"Epic", "weight":1, "price":700, "xp":70},
    "crystal_sturgeon": {"name":"Crystal Sturgeon", "emoji":"🐟", "rarity":"Epic", "weight":1, "price":800, "xp":75},
    "aurora_salmon": {"name":"Aurora Salmon", "emoji":"🌈", "rarity":"Legendary", "weight":0.3, "price":1500, "xp":120},
    "crown_tuna": {"name":"Crown Tuna", "emoji":"👑", "rarity":"Legendary", "weight":0.3, "price":1800, "xp":140},
    "starlight_jelly": {"name":"Starlight Jellyfish", "emoji":"✨", "rarity":"Legendary", "weight":0.2, "price":2000, "xp":150},
    "abyssal_dragonfish": {"name":"Abyssal Dragonfish", "emoji":"🐉", "rarity":"Mythical", "weight":0.1, "price":4000, "xp":250},
    "celestial_whale": {"name":"Celestial Whale", "emoji":"🐋", "rarity":"Mythical", "weight":0.05, "price":5000, "xp":300},
    "cinnamon_goldfish": {"name":"Cinnamon's Golden Fish", "emoji":"🌟", "rarity":"Mythical", "weight":0.05, "price":6500, "xp":350},
}

# Fish sell for 200% more than the original base values (3x total).
# Keep ingredient valuation and cooked-dish prices independent of this multiplier.
FISH_SELL_MULTIPLIER = 3

def _fish_sell_price(fish_id):
    return int(FISH_SPECIES[fish_id]["price"]) * FISH_SELL_MULTIPLIER

# Recipes unlock by fishing level. All dishes are original Cinnamon-themed recipes.
DISH_RECIPES = {
    "minnow_skewers": {"name":"Minnow Skewers", "emoji":"🍢", "level":1, "needs":{"minnow":2}, "price":100, "desc":"Tiny fish, enormous confidence."},
    "sardine_toast": {"name":"Sardine Toast", "emoji":"🍞", "level":2, "needs":{"silver_sardine":2}, "price":130, "desc":"A crunchy riverside breakfast."},
    "carp_dumplings": {"name":"Carp Dumplings", "emoji":"🥟", "level":3, "needs":{"pond_carp":2,"minnow":1}, "price":180, "desc":"Little dumplings with a big splash."},
    "bluegill_bites": {"name":"Bluegill Bites", "emoji":"🍘", "level":4, "needs":{"bluegill":2}, "price":220, "desc":"Crispy bites approved by picky paws."},
    "anchovy_pasta": {"name":"Anchovy Pasta", "emoji":"🍝", "level":5, "needs":{"anchovy":3}, "price":260, "desc":"A twirly bowl of tiny-fish goodness."},
    "trout_chowder": {"name":"River Trout Chowder", "emoji":"🍲", "level":6, "needs":{"river_trout":2,"minnow":1}, "price":350, "desc":"Warm, creamy, and river-fresh."},
    "golden_perch_pie": {"name":"Golden Perch Pie", "emoji":"🥧", "level":7, "needs":{"golden_perch":2}, "price":420, "desc":"A golden crust hiding a golden catch."},
    "moon_koi_sushi": {"name":"Moon Koi Sushi", "emoji":"🍣", "level":8, "needs":{"moon_koi":2,"silver_sardine":1}, "price":500, "desc":"Moonlit sushi with a gentle shimmer."},
    "coral_curry": {"name":"Coral Snapper Curry", "emoji":"🍛", "level":9, "needs":{"coral_snapper":2,"bluegill":1}, "price":650, "desc":"A colourful curry with a little kick."},
    "glass_eel_roll": {"name":"Glass Eel Roll", "emoji":"🍙", "level":10, "needs":{"glass_eel":2}, "price":750, "desc":"A delicate roll that almost disappears."},
    "frost_salmon_bagel": {"name":"Frost Salmon Bagel", "emoji":"🥯", "level":11, "needs":{"frost_salmon":2}, "price":900, "desc":"Chilly salmon on a toasty bagel."},
    "sunscale_sashimi": {"name":"Sunscale Sashimi", "emoji":"🍱", "level":12, "needs":{"sunscale_tuna":1,"river_trout":1}, "price":1200, "desc":"A bright, premium tasting plate."},
    "storm_ray_tacos": {"name":"Storm Ray Tacos", "emoji":"🌮", "level":13, "needs":{"storm_ray":1,"anchovy":2}, "price":1350, "desc":"A stormy catch tucked into soft tacos."},
    "crystal_sturgeon_soup": {"name":"Crystal Sturgeon Soup", "emoji":"🥣", "level":14, "needs":{"crystal_sturgeon":1,"pond_carp":2}, "price":1600, "desc":"Clear broth with a sparkling finish."},
    "aurora_hotpot": {"name":"Aurora Salmon Hotpot", "emoji":"🍲", "level":15, "needs":{"aurora_salmon":1,"frost_salmon":1}, "price":2400, "desc":"Colourful comfort food for expert anglers."},
    "crown_tuna_feast": {"name":"Crown Tuna Feast", "emoji":"🍽️", "level":16, "needs":{"crown_tuna":1,"sunscale_tuna":1}, "price":3000, "desc":"A royal plate worthy of Cinnamon."},
    "starlight_jelly_pudding": {"name":"Starlight Jelly Pudding", "emoji":"🍮", "level":17, "needs":{"starlight_jelly":1,"moon_koi":1}, "price":3500, "desc":"A wobbly dessert with a starry glow."},
    "abyssal_hotpot": {"name":"Abyssal Dragonfish Hotpot", "emoji":"♨️", "level":18, "needs":{"abyssal_dragonfish":1,"crystal_sturgeon":1}, "price":5000, "desc":"A legendary deep-water recipe."},
    "celestial_sushi_boat": {"name":"Celestial Sushi Boat", "emoji":"🛶", "level":19, "needs":{"celestial_whale":1,"crown_tuna":1,"moon_koi":1}, "price":6500, "desc":"A grand platter for a master angler."},
    "cinnamons_royal_bouillabaisse": {"name":"Cinnamon's Royal Bouillabaisse", "emoji":"👑", "level":20, "needs":{"cinnamon_goldfish":1,"abyssal_dragonfish":1,"aurora_salmon":1}, "price":10000, "desc":"The ultimate feast. Cinnamon claims she invented it."},
}

# Cooking is a collection/feeding feature, not a Catnip-printing exploit.
# A cooked dish sells for at most 70% of its ingredients' base fish value.
for _recipe in DISH_RECIPES.values():
    _ingredient_value = sum(FISH_SPECIES[_fish_id]["price"] * int(_qty) for _fish_id, _qty in _recipe["needs"].items())
    _recipe["price"] = min(int(_recipe["price"]), max(1, int(_ingredient_value * 0.70)))

# Register catches and recipes in Cinnamon's existing item catalogue. They are
# deliberately excluded from the shop: members obtain them through fishing/cooking.
# Fishing species are not registered as shop stock. Players obtain fish by fishing;
# feeding and selling still use Cinnamon's shared economy inventory.
for _fish_id, _fish in FISH_SPECIES.items():
    ECONOMY_ITEMS.setdefault(_fish_id, {
        "name": _fish["name"], "price": _fish_sell_price(_fish_id), "emoji": _fish["emoji"],
        "description": f"{_fish['rarity']} fish. Catch it, feed it to Cinnamon, or sell it for {_fish_sell_price(_fish_id):,} Catnip.",
        "max_per_person": 0, "shop_enabled": False,
    })
    # Ensure an older version's fish cannot remain purchasable after this update.
    ECONOMY_ITEMS[_fish_id]["shop_enabled"] = False
    ECONOMY_ITEMS[_fish_id]["price"] = _fish_sell_price(_fish_id)
    ECONOMY_ITEMS[_fish_id]["description"] = f"{_fish['rarity']} fish. Catch it, feed it to Cinnamon, or sell it for {_fish_sell_price(_fish_id):,} Catnip."
for _dish_id, _dish in DISH_RECIPES.items():
    ECONOMY_ITEMS.setdefault(_dish_id, {
        "name": _dish["name"], "price": _dish["price"], "emoji": _dish["emoji"],
        "description": _dish["desc"] + " Feed it to Cinnamon or sell it.",
        "max_per_person": 0, "shop_enabled": False,
    })
    ECONOMY_ITEMS[_dish_id]["shop_enabled"] = False

FISH_RARITY_ORDER = {"Common":1,"Uncommon":2,"Rare":3,"Epic":4,"Legendary":5,"Mythical":6}
FISH_COOLDOWN = 45


def _fish_key(guild_id, user_id):
    return f"{int(guild_id)}:{int(user_id)}"


def _fish_player(guild_id, user_id):
    players = _fishing_root().setdefault("players", {})
    rec = players.setdefault(_fish_key(guild_id, user_id), {
        "fish": {}, "dishes": {}, "xp": 0, "total_catches": 0,
        "total_sold": 0, "dishes_cooked": 0, "discovered": [], "last_cast": 0,
        "rarity_catches": {}, "largest_catch": 0, "fishing_points": 0,
        "upgrades": {}, "cinnamon_memory": 0, "rare_fish_fed": 0,
    })
    for key, default in (("fish",{}),("dishes",{}),("xp",0),("total_catches",0),("total_sold",0),
                         ("dishes_cooked",0),("discovered",[]),("last_cast",0),("rarity_catches",{}),
                         ("largest_catch",0),("inventory_migrated",False),("fishing_points",0),
                         ("upgrades",{}),("cinnamon_memory",0),("rare_fish_fed",0)):
        rec.setdefault(key, default)
    # One-time migration from the first version's private bucket into Cinnamon's
    # shared inventory. After this, fish and dishes have one source of truth, so
    # feeding, crafting, inventory, and selling cannot duplicate the same items.
    inv = economy_inventory_for(guild_id, user_id)
    if not rec.get("inventory_migrated"):
        for item_id, qty in list(rec.get("fish", {}).items()) + list(rec.get("dishes", {}).items()):
            if item_id in FISH_SPECIES or item_id in DISH_RECIPES:
                inv[item_id] = int(inv.get(item_id, 0)) + max(0, int(qty))
        rec["inventory_migrated"] = True
        rec["fish"] = {}
        rec["dishes"] = {}
    return rec


def _fish_inventory(guild_id, user_id):
    return economy_inventory_for(guild_id, user_id)


def _owned_fish(guild_id, user_id):
    inv = _fish_inventory(guild_id, user_id)
    return {k: int(v) for k, v in inv.items() if k in FISH_SPECIES and int(v) > 0}


def _owned_dishes(guild_id, user_id):
    inv = _fish_inventory(guild_id, user_id)
    return {k: int(v) for k, v in inv.items() if k in DISH_RECIPES and int(v) > 0}


def _fish_level(rec):
    return min(20, 1 + int(rec.get("xp", 0)) // 100)


def _unlocked_dishes(rec):
    level = _fish_level(rec)
    return {rid: recipe for rid, recipe in DISH_RECIPES.items() if int(recipe["level"]) <= level}


def _fish_luck_bonus(rec):
    """Return a bounded, understandable luck bonus from Cinnamon Memory + Lucky Rod."""
    memory = max(0, min(100, int(rec.get("cinnamon_memory", 0))))
    rod_level = max(0, min(5, int(rec.get("upgrades", {}).get("lucky_rod", 0))))
    return min(0.30, memory * 0.002 + rod_level * 0.02)


def _fish_odds(rec=None):
    """Per-species probabilities, normalized to 100%; base weights stay exact at zero luck."""
    rec = rec or {}
    luck = _fish_luck_bonus(rec)
    weighted = {}
    for fish_id, fish in FISH_SPECIES.items():
        rarity = fish["rarity"]
        tier = FISH_RARITY_ORDER[rarity] - 1  # Common=0 ... Mythical=5
        if tier == 0:
            multiplier = max(0.70, 1.0 - luck * 0.35)
        else:
            multiplier = 1.0 + luck * (0.65 + 0.35 * tier)
        weighted[fish_id] = float(fish["weight"]) * multiplier
    total = sum(weighted.values()) or 1.0
    return {fish_id: weight / total * 100.0 for fish_id, weight in weighted.items()}


def _fish_weighted_catch(rec=None):
    odds = _fish_odds(rec)
    return random.choices(list(odds), weights=list(odds.values()), k=1)[0]


FISH_POINT_REWARDS = {"Common": 1, "Uncommon": 2, "Rare": 3, "Epic": 5, "Legendary": 8, "Mythical": 12}
FISH_UPGRADES = {
    "lucky_rod": {"name": "Lucky Rod", "emoji": "🍀", "description": "Improves the odds of higher-rarity catches; stacks with Cinnamon Memory.", "costs": [10, 20, 35, 50, 70]},
    "quick_cast": {"name": "Quick Cast", "emoji": "⏱️", "description": "Reduces fishing cooldown by 5 seconds per level (minimum 20 seconds).", "costs": [12, 24, 40]},
    "angler_instinct": {"name": "Angler's Instinct", "emoji": "🧠", "description": "+1 Fishing Point per level on every successful catch.", "costs": [15, 25, 40, 60, 80]},
    "steady_hands": {"name": "Steady Hands", "emoji": "🪝", "description": "Reduces the chance of a missed bite by 1 percentage point per level (minimum 2%).", "costs": [12, 22, 35, 50, 70]},
    "golden_hook": {"name": "Golden Hook", "emoji": "✨", "description": "+10% fishing XP per level (maximum +50%).", "costs": [15, 30, 45, 65, 90]},
    "market_sense": {"name": "Market Sense", "emoji": "💰", "description": "+5% Catnip when selling fish per level (maximum +25%).", "costs": [20, 35, 55, 80, 110]},
}

async def _quest_progress(guild_id, user_id, event, value=1, **kwargs):
    fn = globals().get("quest_event")
    if fn:
        try:
            return await fn(guild_id, user_id, event, value, **kwargs)
        except Exception:
            log.exception("Fishing quest progress event failed: %s", event)


def _fish_inventory_text(guild_id, user_id, *, limit=18):
    rows=[]
    for fish_id, qty in sorted(_owned_fish(guild_id, user_id).items(), key=lambda x: (-FISH_RARITY_ORDER[FISH_SPECIES[x[0]]["rarity"]], FISH_SPECIES[x[0]]["name"])):
        if int(qty) > 0:
            f=FISH_SPECIES[fish_id]
            rows.append(f"{f['emoji']} **{f['name']}** ×{int(qty)} · {f['rarity']}")
    return "\n".join(rows[:limit]) or "Your bucket is empty. Use `/fish catch` to cast a line!"


def _dish_inventory_text(guild_id, user_id, *, limit=18):
    rows=[]
    for dish_id, qty in sorted(_owned_dishes(guild_id, user_id).items(), key=lambda x: DISH_RECIPES[x[0]]["name"]):
        if int(qty)>0:
            d=DISH_RECIPES[dish_id]
            rows.append(f"{d['emoji']} **{d['name']}** ×{int(qty)} · Sell value {d['price']:,} Catnip each")
    return "\n".join(rows[:limit]) or "No cooked dishes yet. Check `/cookbook` to see what you can make."


def _recipe_ingredients_text(recipe):
    return ", ".join(f"{FISH_SPECIES[k]['name']} ×{v}" for k,v in recipe["needs"].items())


async def _award_fish_catch(interaction, fish_id):
    rec = _fish_player(interaction.guild.id, interaction.user.id)
    fish=FISH_SPECIES[fish_id]
    new_species=fish_id not in rec["discovered"]
    old_level = _fish_level(rec)
    inv = _fish_inventory(interaction.guild.id, interaction.user.id)
    inv[fish_id] = int(inv.get(fish_id, 0)) + 1
    rec["total_catches"] += 1
    xp_multiplier = 1.0 + 0.10 * int(rec.get("upgrades", {}).get("golden_hook", 0))
    xp_earned = max(1, int(round(int(fish["xp"]) * xp_multiplier)))
    rec["xp"] += xp_earned
    points_earned = FISH_POINT_REWARDS[fish["rarity"]] + int(rec.get("upgrades", {}).get("angler_instinct", 0))
    rec["fishing_points"] = int(rec.get("fishing_points", 0)) + points_earned
    rec["rarity_catches"][fish["rarity"]]=int(rec["rarity_catches"].get(fish["rarity"],0))+1
    if new_species: rec["discovered"].append(fish_id)
    new_level=_fish_level(rec)
    await bd_save_data()
    await _quest_progress(interaction.guild.id, interaction.user.id, "fish_caught", 1, fish_id=fish_id, rarity=fish["rarity"])
    await _quest_progress(interaction.guild.id, interaction.user.id, "items_owned", sum(max(0, int(v)) for v in inv.values()))
    await achievement_record(interaction.guild.id, interaction.user.id, "inventory")
    if new_species:
        await _quest_progress(interaction.guild.id, interaction.user.id, "fish_discovered", 1, fish_id=fish_id, rarity=fish["rarity"])
    await _quest_progress(interaction.guild.id, interaction.user.id, "fish_rarity", 1, rarity=fish["rarity"])
    if fish["rarity"] == "Mythical":
        await _quest_progress(interaction.guild.id, interaction.user.id, "fish_mythical", 1, fish_id=fish_id)
    e=cinnamon_embed(f"🎣 You caught a {fish['name']}!", f"{fish['emoji']} **{fish['name']}**\nRarity: **{fish['rarity']}**\nSell value: **{_fish_sell_price(fish_id):,} Catnip**\nFishing XP: **+{xp_earned}**\nFishing Points: **+{points_earned}**", color=CINNAMON_GOLD if fish["rarity"] in {"Legendary","Mythical"} else CINNAMON_ORANGE, user=interaction.user, footer="Cinnamon Fishing • Catch, collect, cook")
    if new_species: e.add_field(name="📖 New discovery!", value="This species has been added to your Fish Journal.", inline=False)
    if new_level>old_level: e.add_field(name="⬆️ Fishing level up!", value=f"You reached fishing level **{new_level}**. New dishes may be available in `/cookbook`!", inline=False)
    await interaction.followup.send(embed=cinnamon_polish_embed(e), ephemeral=False)


fish_group = app_commands.Group(name="fish", description="Catch fish, build your journal, and sell your catches")

@fish_group.command(name="catch", description="Cast a line and try to catch a fish")
@app_commands.guild_only()
async def fish_catch_cmd(interaction: discord.Interaction):
    rec=_fish_player(interaction.guild.id, interaction.user.id)
    now=time.time(); cooldown=max(20, FISH_COOLDOWN - 5 * int(rec.get("upgrades", {}).get("quick_cast", 0))); remaining=cooldown-(now-float(rec.get("last_cast",0)))
    if remaining>0:
        return await cinnamon_send(interaction, f"⏳ Your line is still drying! Try fishing again in **{int(remaining)+1} seconds**.", ephemeral=True)
    rec["last_cast"]=now
    await bd_save_data()
    await interaction.response.defer(thinking=True)
    # A small chance of a missed bite adds variety without punishing the player economically.
    miss_chance = max(0.02, 0.07 - 0.01 * int(rec.get("upgrades", {}).get("steady_hands", 0)))
    if random.random() < miss_chance:
        await _quest_progress(interaction.guild.id, interaction.user.id, "fish_cast", 1)
        return await interaction.followup.send(f"🌊 **No catch this time, {interaction.user.mention}.** Something nibbled the line and escaped. Try again when your cooldown ends!", allowed_mentions=discord.AllowedMentions.none())
    await _award_fish_catch(interaction, _fish_weighted_catch(rec))


@fish_group.command(name="inventory", description="View fish in your bucket")
@app_commands.guild_only()
async def fish_inventory_cmd(interaction: discord.Interaction):
    rec=_fish_player(interaction.guild.id, interaction.user.id)
    await bd_save_data()
    e=cinnamon_embed("🪣 Your Fishing Bucket", _fish_inventory_text(interaction.guild.id, interaction.user.id), user=interaction.user, footer=f"{sum(_owned_fish(interaction.guild.id, interaction.user.id).values())} fish in bucket")
    e.add_field(name="Fishing Level", value=f"**{_fish_level(rec)}** · {int(rec['xp'])} XP", inline=True)
    e.add_field(name="Species Discovered", value=f"**{len(rec['discovered'])}/{len(FISH_SPECIES)}**", inline=True)
    await interaction.response.send_message(embed=cinnamon_polish_embed(e), ephemeral=True)


@fish_group.command(name="journal", description="Browse all fish species and your discoveries")
@app_commands.guild_only()
async def fish_journal_cmd(interaction: discord.Interaction):
    rec=_fish_player(interaction.guild.id, interaction.user.id)
    await bd_save_data()
    lines=[]
    for fid,f in FISH_SPECIES.items():
        found=fid in rec["discovered"]
        lines.append(f"{'✅' if found else '🔒'} {f['emoji']} **{f['name'] if found else 'Undiscovered species'}** · {f['rarity']} · {_fish_sell_price(fid):,} Catnip")
    e=cinnamon_embed("📖 Cinnamon Fish Journal", "\n".join(lines), user=interaction.user, footer=f"Discovered {len(rec['discovered'])}/{len(FISH_SPECIES)} species")
    await interaction.response.send_message(embed=cinnamon_polish_embed(e), ephemeral=True)


async def fish_name_autocomplete(interaction: discord.Interaction, current: str):
    inv = _fish_inventory(interaction.guild.id, interaction.user.id) if interaction.guild else {}
    options=[]
    for fid,f in FISH_SPECIES.items():
        if int(inv.get(fid,0))>0 and current.lower() in f["name"].lower():
            options.append(app_commands.Choice(name=f"{f['name']} ×{inv[fid]}", value=fid))
    return options[:25]


@fish_group.command(name="sell", description="Sell fish from your bucket for Catnip")
@app_commands.guild_only()
@app_commands.describe(fish="Choose a fish you own", amount="How many to sell")
@app_commands.autocomplete(fish=fish_name_autocomplete)
async def fish_sell_cmd(interaction: discord.Interaction, fish: str, amount: app_commands.Range[int,1,999]=1):
    rec=_fish_player(interaction.guild.id, interaction.user.id)
    if fish not in FISH_SPECIES: return await cinnamon_send(interaction,"❌ I couldn't find that fish. Open `/fish inventory` and choose a fish you own.",ephemeral=True)
    inv = _fish_inventory(interaction.guild.id, interaction.user.id)
    owned=int(inv.get(fish,0))
    if owned<amount: return await cinnamon_send(interaction,f"❌ You have **{owned}** {FISH_SPECIES[fish]['name']}, not **{amount}**.",ephemeral=True)
    inv[fish]=owned-amount
    if inv[fish]<=0: inv.pop(fish,None)
    base_value = _fish_sell_price(fish) * amount
    market_level = max(0, min(5, int(rec.get("upgrades", {}).get("market_sense", 0))))
    value = int(base_value * (1.0 + 0.05 * market_level))
    economy_balances[(interaction.guild.id,interaction.user.id)]=economy_balance(interaction.guild.id,interaction.user.id)+value
    rec["total_sold"]+=amount
    await bd_save_data()
    await _quest_progress(interaction.guild.id,interaction.user.id,"fish_sold",amount,fish_id=fish)
    await _quest_progress(interaction.guild.id,interaction.user.id,"items_owned",sum(max(0, int(v)) for v in inv.values()))
    await achievement_record(interaction.guild.id,interaction.user.id,"catnip_earned",value)
    await achievement_record(interaction.guild.id,interaction.user.id,"inventory")
    e=cinnamon_embed("💰 Fish sold!",f"Sold **{amount}× {FISH_SPECIES[fish]['name']}** for **{value:,} Catnip**.\nBase value: {base_value:,} Catnip · Market Sense bonus: +{value-base_value:,}\nWallet: **{economy_balance(interaction.guild.id,interaction.user.id):,} Catnip**",user=interaction.user)
    await interaction.response.send_message(embed=cinnamon_polish_embed(e),ephemeral=True)
    await economy_log(interaction.guild.id,title="🎣 Fish sold",fields=[("User",f"{interaction.user} ({interaction.user.id})"),("Fish",FISH_SPECIES[fish]["name"]),("Quantity",amount),("Catnip",f"+{value:,}")])


@fish_group.command(name="odds", description="See your current fish catch chances with luck bonuses")
@app_commands.guild_only()
async def fish_odds_cmd(interaction: discord.Interaction):
    rec = _fish_player(interaction.guild.id, interaction.user.id)
    odds = _fish_odds(rec)
    grouped = {}
    for fish_id, chance in odds.items():
        rarity = FISH_SPECIES[fish_id]["rarity"]
        grouped[rarity] = grouped.get(rarity, 0.0) + chance
    lines = [f"**{rarity}:** {grouped.get(rarity, 0.0):.3f}%" for rarity in FISH_RARITY_ORDER]
    e = cinnamon_embed("🎯 Your Fishing Odds", "\n".join(lines) + f"\n\nYour current luck strength is **{_fish_luck_bonus(rec)*100:.1f}%**. This shifts odds toward rarer catches; it never guarantees one.", user=interaction.user, footer="Percentages reflect your current upgrades and Cinnamon Memory")
    await interaction.response.send_message(embed=cinnamon_polish_embed(e), ephemeral=True)


@fish_group.command(name="stats", description="View your fishing stats and rarity catches")
@app_commands.guild_only()
async def fish_stats_cmd(interaction: discord.Interaction):
    rec=_fish_player(interaction.guild.id,interaction.user.id)
    rarities=[f"{r}: **{int(rec['rarity_catches'].get(r,0))}**" for r in FISH_RARITY_ORDER]
    e=cinnamon_embed("🎣 Fishing Stats",f"**Level:** {_fish_level(rec)}\n**Fishing XP:** {int(rec['xp']):,}\n**Fishing Points:** {int(rec.get('fishing_points',0)):,}\n**Cinnamon Memory:** {int(rec.get('cinnamon_memory',0))}/100\n**Rare fish fed:** {int(rec.get('rare_fish_fed',0))}\n**Fishing luck strength:** {_fish_luck_bonus(rec)*100:.1f}%\n**Total catches:** {int(rec['total_catches']):,}\n**Fish sold:** {int(rec['total_sold']):,}\n**Dishes cooked:** {int(rec['dishes_cooked']):,}\n**Species discovered:** {len(rec['discovered'])}/{len(FISH_SPECIES)}",user=interaction.user)
    e.add_field(name="Catches by rarity",value="\n".join(rarities),inline=False)
    await interaction.response.send_message(embed=cinnamon_polish_embed(e),ephemeral=True)


async def fish_upgrade_autocomplete(interaction: discord.Interaction, current: str):
    query=(current or "").casefold()
    return [app_commands.Choice(name=f"{data['emoji']} {data['name']}"[:100], value=key)
            for key,data in FISH_UPGRADES.items() if query in key.casefold() or query in data['name'].casefold()][:25]

@fish_group.command(name="points", description="Check your Fishing Points and upgrades")
@app_commands.guild_only()
async def fish_points_cmd(interaction: discord.Interaction):
    rec=_fish_player(interaction.guild.id,interaction.user.id)
    lines=[f"{data['emoji']} **{data['name']}** — Level {int(rec.get('upgrades',{}).get(key,0))}/{len(data['costs'])}" for key,data in FISH_UPGRADES.items()]
    e=cinnamon_embed("🎣 Fishing Points",f"You have **{int(rec.get('fishing_points',0))} Fishing Points**.\n\nEarn points by catching fish; rarer catches award more.\n\n"+"\n".join(lines),user=interaction.user,footer="Spend points with /fish upgrade")
    await interaction.response.send_message(embed=cinnamon_polish_embed(e),ephemeral=True)

@fish_group.command(name="bond", description="See Cinnamon Memory and your rare-fish bond milestones")
@app_commands.guild_only()
async def fish_bond_cmd(interaction: discord.Interaction):
    rec = _fish_player(interaction.guild.id, interaction.user.id)
    memory = max(0, min(100, int(rec.get("cinnamon_memory", 0))))
    milestones = [(10, "Recognized Face"), (25, "Trusted Human"), (50, "Cinnamon's Fishing Buddy"), (75, "Beloved Angler"), (100, "Cinnamon's Favourite Angler")]
    next_goal = next(((goal, title) for goal, title in milestones if memory < goal), None)
    milestone_text = f"Next milestone: **{next_goal[1]}** at **{next_goal[0]} Memory** ({next_goal[0]-memory} to go)." if next_goal else "🏆 **All bond milestones reached!**"
    e = cinnamon_embed("💗 Cinnamon Memory", f"Memory: **{memory}/100**\nRare fish fed: **{int(rec.get('rare_fish_fed', 0))}**\nFishing luck contribution: **+{min(20.0, memory * 0.2):.1f}%**\n\n{milestone_text}\n\nRare fish are worth feeding when you want to build your bond; you can sell them instead when you need Catnip.", user=interaction.user)
    await interaction.response.send_message(embed=cinnamon_polish_embed(e), ephemeral=True)


@fish_group.command(name="upgrades", description="Browse fishing upgrades and their costs")
@app_commands.guild_only()
async def fish_upgrades_cmd(interaction: discord.Interaction):
    rec=_fish_player(interaction.guild.id,interaction.user.id)
    lines=[]
    for key,data in FISH_UPGRADES.items():
        level=int(rec.get('upgrades',{}).get(key,0)); max_level=len(data['costs'])
        next_cost=data['costs'][level] if level<max_level else None
        lines.append(f"{data['emoji']} **{data['name']}** — Level {level}/{max_level}\n{data['description']}\n"+(f"Next level: **{next_cost} FP**" if next_cost is not None else "**MAX LEVEL**"))
    e=cinnamon_embed("🛠️ Fishing Upgrades","\n\n".join(lines),user=interaction.user,footer="Fishing Points are earned from successful catches")
    await interaction.response.send_message(embed=cinnamon_polish_embed(e),ephemeral=True)

@fish_group.command(name="upgrade", description="Spend Fishing Points on a fishing upgrade")
@app_commands.guild_only()
@app_commands.describe(upgrade="Choose an upgrade by name")
@app_commands.autocomplete(upgrade=fish_upgrade_autocomplete)
async def fish_upgrade_cmd(interaction: discord.Interaction, upgrade: str):
    rec=_fish_player(interaction.guild.id,interaction.user.id)
    data=FISH_UPGRADES.get(upgrade)
    if not data:
        return await cinnamon_send(interaction,"❌ Choose an upgrade from the autocomplete list or use `/fish upgrades`.",ephemeral=True)
    levels=rec.setdefault('upgrades',{}); level=int(levels.get(upgrade,0))
    if level>=len(data['costs']):
        return await cinnamon_send(interaction,f"✅ **{data['name']}** is already at maximum level.",ephemeral=True)
    cost=int(data['costs'][level]); points=int(rec.get('fishing_points',0))
    if points<cost:
        return await cinnamon_send(interaction,f"You need **{cost} Fishing Points**, but you have **{points}**. Catch more fish and try again!",ephemeral=True)
    rec['fishing_points']=points-cost; levels[upgrade]=level+1
    await bd_save_data()
    e=cinnamon_embed("🛠️ Upgrade purchased!",f"{data['emoji']} **{data['name']}** is now level **{level+1}/{len(data['costs'])}**.\nSpent: **{cost} Fishing Points**\nRemaining: **{rec['fishing_points']} Fishing Points**",user=interaction.user)
    await interaction.response.send_message(embed=cinnamon_polish_embed(e),ephemeral=True)

bot.tree.add_command(fish_group)


cook_group = app_commands.Group(name="cook", description="Cook and sell dishes unlocked through fishing")

@bot.tree.command(name="cookbook", description="Browse 20 dishes and see how to unlock them")
@app_commands.guild_only()
async def cookbook_cmd(interaction: discord.Interaction):
    rec=_fish_player(interaction.guild.id,interaction.user.id)
    await bd_save_data()
    level=_fish_level(rec)
    lines=[]
    for rid,r in DISH_RECIPES.items():
        unlocked=level>=int(r["level"])
        lines.append(f"{'🍽️' if unlocked else '🔒'} **{r['name']}** · Unlock at fishing level **{r['level']}**\nIngredients: {_recipe_ingredients_text(r)} · Sell: {r['price']:,} Catnip")
    pages=[lines[i:i+5] for i in range(0,len(lines),5)]
    page=discord.Embed(title=f"📖 Cinnamon Cookbook · Level {level}",description="\n\n".join(pages[0]),color=discord.Color.orange())
    page.set_footer(text=f"20 dishes • Page 1/{len(pages)} • Level up by catching fish")
    await interaction.response.send_message(embed=cinnamon_polish_embed(page),view=CookbookView(interaction.user.id,pages,len(pages)),ephemeral=True)


class CookbookView(discord.ui.View):
    def __init__(self,user_id,pages,page_count):
        super().__init__(timeout=180)
        self.user_id=user_id; self.pages=pages; self.page=0; self.page_count=page_count
        self.previous.disabled=True; self.next.disabled=page_count<=1
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.user_id:
            await interaction.response.send_message("This cookbook belongs to another angler. Use `/cookbook` to open your own!",ephemeral=True)
            return False
        return True
    async def _render(self,interaction):
        rec=_fish_player(interaction.guild.id,interaction.user.id)
        e=discord.Embed(title=f"📖 Cinnamon Cookbook · Level {_fish_level(rec)}",description="\n\n".join(self.pages[self.page]),color=discord.Color.orange())
        e.set_footer(text=f"20 dishes • Page {self.page+1}/{self.page_count} • Level up by catching fish")
        self.previous.disabled=self.page<=0; self.next.disabled=self.page>=self.page_count-1
        await interaction.response.edit_message(embed=cinnamon_polish_embed(e),view=self)
    @discord.ui.button(label="Previous",style=discord.ButtonStyle.secondary,emoji="⬅️")
    async def previous(self,interaction,button):
        self.page=max(0,self.page-1); await self._render(interaction)
    @discord.ui.button(label="Next",style=discord.ButtonStyle.primary,emoji="➡️")
    async def next(self,interaction,button):
        self.page=min(self.page_count-1,self.page+1); await self._render(interaction)


async def dish_autocomplete(interaction: discord.Interaction, current: str):
    rec=_fish_player(interaction.guild.id,interaction.user.id) if interaction.guild else {"dishes":{}}
    options=[]
    for rid,r in DISH_RECIPES.items():
        if current.lower() in r["name"].lower() and _fish_level(rec)>=int(r["level"]):
            options.append(app_commands.Choice(name=f"{r['name']} (Lv. {r['level']})",value=rid))
    return options[:25]


@cook_group.command(name="make", description="Cook a dish from a recipe you've unlocked")
@app_commands.guild_only()
@app_commands.describe(dish="Choose an unlocked dish", amount="How many servings to cook")
@app_commands.autocomplete(dish=dish_autocomplete)
async def cook_make_cmd(interaction: discord.Interaction,dish: str,amount: app_commands.Range[int,1,10]=1):
    rec=_fish_player(interaction.guild.id,interaction.user.id)
    recipe=DISH_RECIPES.get(dish)
    if not recipe: return await cinnamon_send(interaction,"❌ Unknown recipe. Use `/cookbook` to browse the 20 dishes.",ephemeral=True)
    if _fish_level(rec)<int(recipe["level"]): return await cinnamon_send(interaction,f"🔒 **{recipe['name']}** unlocks at fishing level **{recipe['level']}**. You're level **{_fish_level(rec)}**.",ephemeral=True)
    missing=[]
    inv = _fish_inventory(interaction.guild.id, interaction.user.id)
    for fish_id,qty in recipe["needs"].items():
        needed=qty*amount; have=int(inv.get(fish_id,0))
        if have<needed: missing.append(f"{FISH_SPECIES[fish_id]['name']}: need {needed}, have {have}")
    if missing: return await cinnamon_send(interaction,"❌ Not enough fish to cook that.\n"+"\n".join(missing),ephemeral=True)
    for fish_id,qty in recipe["needs"].items():
        inv[fish_id]=int(inv.get(fish_id,0))-qty*amount
        if inv[fish_id]<=0: inv.pop(fish_id,None)
    inv[dish]=int(inv.get(dish,0))+amount
    rec["dishes_cooked"]+=amount
    await bd_save_data()
    await _quest_progress(interaction.guild.id,interaction.user.id,"dish_cooked",amount,dish_id=dish)
    await _quest_progress(interaction.guild.id,interaction.user.id,"dish_discovered",1,dish_id=dish)
    await _quest_progress(interaction.guild.id,interaction.user.id,"items_owned",sum(max(0, int(v)) for v in inv.values()))
    await achievement_record(interaction.guild.id,interaction.user.id,"inventory")
    e=cinnamon_embed(f"{recipe['emoji']} Freshly cooked!",f"You made **{amount}× {recipe['name']}**.\nIngredients used: {_recipe_ingredients_text(recipe)} × {amount}\nSell value: **{recipe['price']*amount:,} Catnip**\n\nUse `/cook inventory` to see your dishes or `/cook sell` to sell them.",user=interaction.user)
    await interaction.response.send_message(embed=cinnamon_polish_embed(e),ephemeral=True)
    await economy_log(interaction.guild.id, title="🍳 Dish cooked", fields=[
        ("User", f"{interaction.user} ({interaction.user.id})"),
        ("Recipe", recipe["name"]), ("Quantity", amount),
        ("Ingredients", _recipe_ingredients_text(recipe)),
    ])


@cook_group.command(name="inventory", description="View your cooked dishes")
@app_commands.guild_only()
async def cook_inventory_cmd(interaction: discord.Interaction):
    rec=_fish_player(interaction.guild.id,interaction.user.id)
    dishes = _owned_dishes(interaction.guild.id, interaction.user.id)
    e=cinnamon_embed("🍽️ Your Dish Collection",_dish_inventory_text(interaction.guild.id, interaction.user.id),user=interaction.user,footer=f"{sum(dishes.values())} servings ready")
    await interaction.response.send_message(embed=cinnamon_polish_embed(e),ephemeral=True)


async def dish_inventory_autocomplete(interaction: discord.Interaction,current: str):
    inv = _fish_inventory(interaction.guild.id, interaction.user.id) if interaction.guild else {}
    return [app_commands.Choice(name=f"{DISH_RECIPES[rid]['name']} ×{qty}",value=rid) for rid,qty in inv.items() if rid in DISH_RECIPES and int(qty)>0 and current.lower() in DISH_RECIPES[rid]["name"].lower()][:25]


@cook_group.command(name="sell", description="Sell cooked dishes for Catnip")
@app_commands.guild_only()
@app_commands.describe(dish="Choose a dish you own",amount="How many servings to sell")
@app_commands.autocomplete(dish=dish_inventory_autocomplete)
async def cook_sell_cmd(interaction: discord.Interaction,dish: str,amount: app_commands.Range[int,1,999]=1):
    rec=_fish_player(interaction.guild.id,interaction.user.id)
    if dish not in DISH_RECIPES: return await cinnamon_send(interaction,"❌ I couldn't find that dish. Use `/cook inventory`.",ephemeral=True)
    inv = _fish_inventory(interaction.guild.id, interaction.user.id)
    owned=int(inv.get(dish,0))
    if owned<amount: return await cinnamon_send(interaction,f"❌ You have **{owned}** servings of {DISH_RECIPES[dish]['name']}, not **{amount}**.",ephemeral=True)
    inv[dish]=owned-amount
    if inv[dish]<=0: inv.pop(dish,None)
    value=DISH_RECIPES[dish]["price"]*amount
    economy_balances[(interaction.guild.id,interaction.user.id)]=economy_balance(interaction.guild.id,interaction.user.id)+value
    await bd_save_data()
    await _quest_progress(interaction.guild.id,interaction.user.id,"dish_sold",amount,dish_id=dish)
    await _quest_progress(interaction.guild.id,interaction.user.id,"items_owned",sum(max(0, int(v)) for v in inv.values()))
    await achievement_record(interaction.guild.id,interaction.user.id,"catnip_earned",value)
    await achievement_record(interaction.guild.id,interaction.user.id,"inventory")
    e=cinnamon_embed("💰 Dishes sold!",f"Sold **{amount}× {DISH_RECIPES[dish]['name']}** for **{value:,} Catnip**.\nWallet: **{economy_balance(interaction.guild.id,interaction.user.id):,} Catnip**",user=interaction.user)
    await interaction.response.send_message(embed=cinnamon_polish_embed(e),ephemeral=True)
    await economy_log(interaction.guild.id,title="🍽️ Cooked dishes sold",fields=[("User",f"{interaction.user} ({interaction.user.id})"),("Dish",DISH_RECIPES[dish]["name"]),("Quantity",amount),("Catnip",f"+{value:,}")])

bot.tree.add_command(cook_group)


# Add feature-driven quests to the existing rotating pools. The core quest
# engine already handles counter metrics, completion rewards, and persistence.
DAILY_QUESTS.update({
    "first_catch": {"name":"First Catch","desc":"Catch 1 fish using `/fish catch`.","kind":"counter","metric":"fish_caught","target":1,"qp":100,"xp":300,"rarity":"Common"},
    "bucket_builder": {"name":"Bucket Builder","desc":"Catch 3 fish.","kind":"counter","metric":"fish_caught","target":3,"qp":180,"xp":450,"rarity":"Uncommon"},
    "new_species": {"name":"New Waters","desc":"Discover 2 different fish species.","kind":"counter","metric":"fish_discovered","target":2,"qp":200,"xp":500,"rarity":"Uncommon"},
    "cook_up": {"name":"Cook Up","desc":"Cook 1 dish you've unlocked.","kind":"counter","metric":"dish_cooked","target":1,"qp":180,"xp":500,"rarity":"Uncommon"},
    "fish_seller": {"name":"Fish Seller","desc":"Sell 3 fish for Catnip.","kind":"counter","metric":"fish_sold","target":3,"qp":170,"xp":400,"rarity":"Common"},
})
WEEKLY_QUESTS.update({
    "angler_week": {"name":"Angler of the Week","desc":"Catch 20 fish during the week.","kind":"counter","metric":"fish_caught","target":20,"qp":700,"xp":2500,"rarity":"Rare"},
    "fishdex_filler": {"name":"Journal Filler","desc":"Discover 8 different fish species.","kind":"counter","metric":"fish_discovered","target":8,"qp":900,"xp":3000,"rarity":"Epic"},
    "kitchen_cat": {"name":"Kitchen Cat","desc":"Cook 10 dishes during the week.","kind":"counter","metric":"dish_cooked","target":10,"qp":1000,"xp":3500,"rarity":"Epic"},
    "mythical_meal": {"name":"Mythical Meal","desc":"Catch a Mythical fish.","kind":"counter","metric":"fish_mythical","target":1,"qp":1300,"xp":4500,"rarity":"Legendary"},
})
