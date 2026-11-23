"""Member-owned Cinnamon companion pets.

Shares Catnip and inventory; stores profiles in the existing validated snapshot.
No adventure/Wildlands data is accessed.
"""
import asyncio as _companion_asyncio
import copy as _companion_copy
import datetime as _companion_dt
import time as _companion_time

_COMPANION_KEY = "companion_profiles_v1"
companion_group = app_commands.Group(name="companion", description="Care for and customize your personal Cinnamon cat")
_COMPANION_LOCKS = {}
_COMPANION_FOODS = {
    "treat": (12, 8), "tuna": (18, 10), "churu": (20, 12),
    "fish_biscuits": (16, 10), "cosmic_churu": (28, 16),
    "tuna_stew": (22, 14), "honey_fish_treat": (20, 12),
    "pawberry_cake": (24, 16), "moon_jelly": (30, 18),
    "royal_tuna": (26, 16), "fish": (14, 8),
}
_COMPANION_ACCESSORIES = {
    "catnip_crown": "head", "golden_bell_collar": "neck",
    "starlight_hat": "head", "dream_wings": "back",
}
_COMPANION_ROOMS = {
    "room_cloud_bed": ("Cloud Bed", "🛏️", 2500, "A soft cloud-shaped bed."),
    "room_paw_rug": ("Pawprint Rug", "🐾", 1200, "A fluffy rug for tiny paws."),
    "room_fish_lamp": ("Fish Lamp", "🐟", 1800, "A warm lamp shaped like a fish."),
    "room_window_perch": ("Window Perch", "🪟", 2200, "A sunny perch for watching birds."),
    "room_star_mobile": ("Star Mobile", "⭐", 3200, "A ceiling mobile with tiny stars."),
    "room_tea_table": ("Tea Table", "🫖", 2800, "A little table for pretend tea parties."),
}
for _room_id, (_room_name, _room_emoji, _room_price, _room_desc) in _COMPANION_ROOMS.items():
    ECONOMY_ITEMS.setdefault(_room_id, {
        "name": _room_name, "emoji": _room_emoji, "price": _room_price,
        "description": _room_desc, "category": "companion_room",
        "shop_enabled": False, "sellable": False, "max_per_person": 0,
    })

_COMPANION_DEFAULT = {
    "name": "Mochi", "xp": 0, "level": 1, "friendship": 0,
    "hunger": 75, "happiness": 75, "cleanliness": 75, "energy": 80,
    "mood": "Content", "created_at": 0, "last_actions": {},
    "equipped": {}, "room": [], "memories": [],
    "stats": {"feeds": 0, "plays": 0, "grooms": 0},
}

def _companion_root(guild_id):
    return advanced_features_data.setdefault(_COMPANION_KEY, {}).setdefault(str(int(guild_id)), {})

def _companion_lock(guild_id, user_id):
    return _COMPANION_LOCKS.setdefault((int(guild_id), int(user_id)), _companion_asyncio.Lock())

def _companion_profile(guild_id, user_id, create=True):
    root = _companion_root(guild_id)
    key = str(int(user_id))
    profile = root.get(key)
    if not isinstance(profile, dict) and create:
        profile = _companion_copy.deepcopy(_COMPANION_DEFAULT)
        profile["created_at"] = int(_companion_time.time())
        root[key] = profile
    return profile

def _companion_level(xp):
    level, remaining = 1, max(0, int(xp))
    while level < 100 and remaining >= level * 100:
        remaining -= level * 100
        level += 1
    return level

def _companion_mood(profile):
    if int(profile.get("hunger", 0)) < 20: return "Hungry"
    if int(profile.get("cleanliness", 0)) < 20: return "Messy"
    if int(profile.get("energy", 0)) < 20: return "Sleepy"
    if int(profile.get("happiness", 0)) >= 85 and int(profile.get("hunger", 0)) >= 65: return "Playful"
    if int(profile.get("happiness", 0)) < 35: return "Lonely"
    return "Content"

def _companion_embed(guild, user, profile):
    profile["level"] = _companion_level(profile.get("xp", 0))
    profile["mood"] = _companion_mood(profile)
    level = int(profile["level"])
    e = discord.Embed(
        title=f"🐾 {str(profile.get('name', 'Mochi'))[:32]}",
        description=f"Your companion • Level **{level}** • **{profile['mood']}**",
        color=0xE8A05A,
        timestamp=_companion_dt.datetime.now(_companion_dt.timezone.utc),
    )
    e.add_field(name="🍗 Hunger", value=f"{int(profile.get('hunger', 0))}/100", inline=True)
    e.add_field(name="💛 Happiness", value=f"{int(profile.get('happiness', 0))}/100", inline=True)
    e.add_field(name="🧼 Cleanliness", value=f"{int(profile.get('cleanliness', 0))}/100", inline=True)
    e.add_field(name="⚡ Energy", value=f"{int(profile.get('energy', 0))}/100", inline=True)
    e.add_field(name="✨ Friendship", value=f"{int(profile.get('friendship', 0)):,} points", inline=True)
    e.add_field(name="⭐ Experience", value=f"{int(profile.get('xp', 0)):,} XP", inline=True)
    e.set_footer(text=f"{guild.name} • Your personal Cinnamon companion")
    return e

def _companion_clamp(value):
    return max(0, min(100, int(value)))

async def _companion_save_or_restore(guild_id, user_id, before_profile, before_inventory=None, before_balance=None):
    if await bd_save_data():
        return True
    root = _companion_root(guild_id)
    key = str(int(user_id))
    if before_profile is None: root.pop(key, None)
    else: root[key] = before_profile
    if before_inventory is not None:
        inventory = economy_inventory_for(guild_id, user_id)
        inventory.clear()
        inventory.update(before_inventory)
    if before_balance is not None:
        economy_balances[(int(guild_id), int(user_id))] = int(before_balance)
    return False

async def _companion_award(profile, xp, friendship):
    profile["xp"] = int(profile.get("xp", 0)) + int(xp)
    profile["friendship"] = int(profile.get("friendship", 0)) + int(friendship)
    profile["level"] = _companion_level(profile["xp"])
    profile["mood"] = _companion_mood(profile)

async def companion_food_autocomplete(interaction, current):
    if not interaction.guild: return []
    inv = economy_inventory_for(interaction.guild.id, interaction.user.id)
    query, results = str(current or "").lower(), []
    for item_id, qty in inv.items():
        if int(qty) < 1 or item_id not in _COMPANION_FOODS: continue
        label = str(ECONOMY_ITEMS.get(item_id, {}).get("name", item_id))
        if query in item_id.lower() or query in label.lower():
            results.append(app_commands.Choice(name=f"{label} • {int(qty)} owned", value=item_id))
    return results[:25]

async def companion_accessory_autocomplete(interaction, current):
    if not interaction.guild: return []
    inv, query, results = economy_inventory_for(interaction.guild.id, interaction.user.id), str(current or "").lower(), []
    for item_id, slot in _COMPANION_ACCESSORIES.items():
        if int(inv.get(item_id, 0)) < 1: continue
        label = str(ECONOMY_ITEMS.get(item_id, {}).get("name", item_id))
        if query in item_id.lower() or query in label.lower():
            results.append(app_commands.Choice(name=f"{label} • {slot}", value=item_id))
    return results[:25]

async def companion_room_autocomplete(interaction, current):
    query = str(current or "").lower()
    return [app_commands.Choice(name=f"{ECONOMY_ITEMS[item_id]['name']} • {price:,} Catnip", value=item_id)
            for item_id, (_, _, price, _) in _COMPANION_ROOMS.items()
            if query in item_id.lower() or query in ECONOMY_ITEMS[item_id]["name"].lower()][:25]

@bot.tree.command(name="pet", description="View and optionally rename your personal cat companion")
@app_commands.guild_only()
@app_commands.describe(name="Optional new name for your cat")
async def companion_pet(interaction: discord.Interaction, name: str | None = None):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _companion_lock(gid, uid):
        old = _companion_copy.deepcopy(_companion_profile(gid, uid, create=False))
        profile = _companion_profile(gid, uid)
        if name is not None:
            clean = " ".join(str(name).split()).strip()
            if not 1 <= len(clean) <= 24:
                return await cinnamon_send(interaction, "Your cat's name must be 1–24 characters.", ephemeral=True)
            profile["name"] = clean
        if old is None or name is not None:
            if not await _companion_save_or_restore(gid, uid, old):
                return await cinnamon_send(interaction, "I couldn't save your companion profile. No changes were kept.", ephemeral=True)
        embed = _companion_embed(interaction.guild, interaction.user, profile)
    await interaction.response.send_message(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

@companion_group.command(name="feed", description="Feed your personal cat companion with food you own")
@app_commands.guild_only()
@app_commands.describe(item="Choose food from your inventory")
@app_commands.autocomplete(item=companion_food_autocomplete)
async def companion_feed(interaction: discord.Interaction, item: str):
    gid, uid, item_id = interaction.guild.id, interaction.user.id, str(item).strip().lower()
    if item_id not in _COMPANION_FOODS:
        return await cinnamon_send(interaction, "That item isn't a companion food.", ephemeral=True)
    async with _companion_lock(gid, uid):
        inv = economy_inventory_for(gid, uid)
        if int(inv.get(item_id, 0)) < 1:
            return await cinnamon_send(interaction, "You don't own that food item.", ephemeral=True)
        before, before_inv = _companion_copy.deepcopy(_companion_profile(gid, uid, False)), dict(inv)
        profile = _companion_profile(gid, uid)
        inv[item_id] = int(inv[item_id]) - 1
        if inv[item_id] <= 0: inv.pop(item_id, None)
        hunger, happiness = _COMPANION_FOODS[item_id]
        profile["hunger"] = _companion_clamp(profile.get("hunger", 75) + hunger)
        profile["happiness"] = _companion_clamp(profile.get("happiness", 75) + happiness)
        profile.setdefault("stats", {}).setdefault("feeds", 0)
        profile["stats"]["feeds"] += 1
        await _companion_award(profile, 12, 8)
        if not await _companion_save_or_restore(gid, uid, before, before_inv):
            return await cinnamon_send(interaction, "The feed couldn't be saved. Your food and companion stats were restored.", ephemeral=True)
        embed = _companion_embed(interaction.guild, interaction.user, profile)
    await interaction.response.send_message(content=f"🍽️ You fed **{profile['name']}** with **{ECONOMY_ITEMS[item_id]['name']}**.", embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

@companion_group.command(name="play", description="Play with your personal cat companion")
@app_commands.guild_only()
async def companion_play(interaction: discord.Interaction):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _companion_lock(gid, uid):
        before = _companion_copy.deepcopy(_companion_profile(gid, uid, False))
        profile, now = _companion_profile(gid, uid), int(_companion_time.time())
        remaining = max(0, int(profile.get("last_actions", {}).get("play", 0)) + 180 - now)
        if remaining: return await cinnamon_send(interaction, f"Your cat needs a break. Try again in {remaining // 60}m {remaining % 60}s.", ephemeral=True)
        profile.setdefault("last_actions", {})["play"] = now
        profile["happiness"] = _companion_clamp(profile.get("happiness", 75) + 18)
        profile["energy"] = _companion_clamp(profile.get("energy", 80) - 8)
        profile.setdefault("stats", {}).setdefault("plays", 0)
        profile["stats"]["plays"] += 1
        await _companion_award(profile, 20, 12)
        if not await _companion_save_or_restore(gid, uid, before):
            return await cinnamon_send(interaction, "Couldn't save playtime; your companion's stats were restored.", ephemeral=True)
        embed = _companion_embed(interaction.guild, interaction.user, profile)
    await interaction.response.send_message(content=f"🧶 You played with **{profile['name']}**!", embed=embed, ephemeral=True)

@companion_group.command(name="groom", description="Brush and groom your personal cat companion")
@app_commands.guild_only()
async def companion_groom(interaction: discord.Interaction):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _companion_lock(gid, uid):
        before = _companion_copy.deepcopy(_companion_profile(gid, uid, False))
        profile, now = _companion_profile(gid, uid), int(_companion_time.time())
        remaining = max(0, int(profile.get("last_actions", {}).get("groom", 0)) + 120 - now)
        if remaining: return await cinnamon_send(interaction, f"Your cat is already tidy. Try again in {remaining // 60}m {remaining % 60}s.", ephemeral=True)
        profile.setdefault("last_actions", {})["groom"] = now
        profile["cleanliness"] = _companion_clamp(profile.get("cleanliness", 75) + 25)
        profile.setdefault("stats", {}).setdefault("grooms", 0)
        profile["stats"]["grooms"] += 1
        await _companion_award(profile, 12, 8)
        if not await _companion_save_or_restore(gid, uid, before):
            return await cinnamon_send(interaction, "Couldn't save grooming; your companion's stats were restored.", ephemeral=True)
        embed = _companion_embed(interaction.guild, interaction.user, profile)
    await interaction.response.send_message(content=f"🪮 **{profile['name']}** is looking tidy.", embed=embed, ephemeral=True)

@companion_group.command(name="dressup", description="Equip or remove accessories from your personal cat")
@app_commands.guild_only()
@app_commands.choices(action=[app_commands.Choice(name="Equip", value="equip"), app_commands.Choice(name="Unequip", value="unequip")])
@app_commands.describe(action="Choose whether to equip or remove an accessory", item="An accessory you own")
@app_commands.autocomplete(item=companion_accessory_autocomplete)
async def companion_dressup(interaction: discord.Interaction, action: app_commands.Choice[str], item: str | None = None):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _companion_lock(gid, uid):
        before = _companion_copy.deepcopy(_companion_profile(gid, uid, False))
        profile = _companion_profile(gid, uid)
        equipped = profile.setdefault("equipped", {})
        if action.value == "equip":
            item_id = str(item or "").strip().lower()
            slot = _COMPANION_ACCESSORIES.get(item_id)
            if not slot or int(economy_inventory_for(gid, uid).get(item_id, 0)) < 1:
                return await cinnamon_send(interaction, "Choose an accessory you own from autocomplete.", ephemeral=True)
            equipped[slot] = item_id
            message = f"Your cat is now wearing {ECONOMY_ITEMS[item_id]['name']}."
        else:
            if item:
                item_id = str(item).strip().lower()
                slot = _COMPANION_ACCESSORIES.get(item_id)
                if slot and equipped.get(slot) == item_id: equipped.pop(slot, None)
                elif item_id in equipped: equipped.pop(item_id, None)
                else: return await cinnamon_send(interaction, "That accessory isn't equipped.", ephemeral=True)
            else:
                equipped.clear()
            message = "Your cat's accessories have been removed."
        if not await _companion_save_or_restore(gid, uid, before):
            return await cinnamon_send(interaction, "Couldn't save the outfit; your previous outfit was restored.", ephemeral=True)
        names = [ECONOMY_ITEMS.get(v, {}).get("name", v) for v in equipped.values()]
    e = _companion_embed(interaction.guild, interaction.user, profile)
    e.add_field(name="Accessories", value=", ".join(names) if names else "No accessories equipped", inline=False)
    await interaction.response.send_message(content=message, embed=e, ephemeral=True)

@companion_group.command(name="room", description="Customize your companion's room with Catnip furniture")
@app_commands.guild_only()
@app_commands.choices(action=[
    app_commands.Choice(name="View room", value="view"), app_commands.Choice(name="Buy furniture", value="buy"),
    app_commands.Choice(name="Place furniture", value="place"), app_commands.Choice(name="Remove furniture", value="remove")])
@app_commands.describe(action="What would you like to do?", item="Furniture item")
@app_commands.autocomplete(item=companion_room_autocomplete)
async def companion_room(interaction: discord.Interaction, action: app_commands.Choice[str], item: str | None = None):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _companion_lock(gid, uid):
        before = _companion_copy.deepcopy(_companion_profile(gid, uid, False))
        profile = _companion_profile(gid, uid)
        inv = economy_inventory_for(gid, uid)
        before_inv, before_balance = dict(inv), economy_balance(gid, uid)
        rooms, item_id = profile.setdefault("room", []), str(item or "").strip().lower()
        if action.value != "view" and item_id not in _COMPANION_ROOMS:
            return await cinnamon_send(interaction, "Choose a known room item from autocomplete.", ephemeral=True)
        if action.value == "buy":
            price = _COMPANION_ROOMS[item_id][2]
            if before_balance < price: return await cinnamon_send(interaction, f"You need {price:,} Catnip to buy that furniture.", ephemeral=True)
            economy_balances[(gid, uid)] = before_balance - price
            inv[item_id] = int(inv.get(item_id, 0)) + 1
        elif action.value == "place":
            if int(inv.get(item_id, 0)) < 1: return await cinnamon_send(interaction, "You need to own that furniture before placing it.", ephemeral=True)
            if item_id in rooms: return await cinnamon_send(interaction, "That furniture is already in your room.", ephemeral=True)
            inv[item_id] = int(inv[item_id]) - 1
            if inv[item_id] <= 0: inv.pop(item_id, None)
            rooms.append(item_id)
        elif action.value == "remove":
            if item_id not in rooms: return await cinnamon_send(interaction, "That furniture isn't currently placed in your room.", ephemeral=True)
            rooms.remove(item_id)
            inv[item_id] = int(inv.get(item_id, 0)) + 1
        if action.value != "view" and not await _companion_save_or_restore(gid, uid, before, before_inv, before_balance if action.value == "buy" else None):
            return await cinnamon_send(interaction, "Couldn't save the room change; your Catnip and furniture were restored.", ephemeral=True)
        lines = [f"{ECONOMY_ITEMS[x]['emoji']} {ECONOMY_ITEMS[x]['name']}" for x in rooms if x in ECONOMY_ITEMS]
        balance = economy_balance(gid, uid)
    e = discord.Embed(title=f"🏡 {profile['name']}'s Room", description="\n".join(lines) or "An empty room, ready for decorating.", color=0xB6C9A5)
    e.add_field(name="Catnip", value=f"{balance:,}", inline=True)
    e.add_field(name="Furniture placed", value=str(len(rooms)), inline=True)
    await interaction.response.send_message(embed=e, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

@companion_group.command(name="mood", description="See your personal cat companion's current mood")
@app_commands.guild_only()
async def companion_mood(interaction: discord.Interaction):
    profile = _companion_profile(interaction.guild.id, interaction.user.id, False)
    if profile is None: return await cinnamon_send(interaction, "You don't have a companion yet. Use /pet to meet your cat.", ephemeral=True)
    mood = _companion_mood(profile)
    descriptions = {"Hungry":"Your cat would appreciate a snack.", "Messy":"A little grooming would help.",
                    "Sleepy":"Your cat could use some rest.", "Playful":"Your cat is ready for fun.",
                    "Lonely":"Spend a little time playing together.", "Content":"Your cat is comfortable and doing well."}
    await cinnamon_send(interaction, f"**{profile['name']} is {mood.lower()}.**\n{descriptions[mood]}", ephemeral=True)

@companion_group.command(name="catbook", description="View your companion collection and equipped accessories")
@app_commands.guild_only()
async def companion_catbook(interaction: discord.Interaction):
    gid, uid = interaction.guild.id, interaction.user.id
    profile = _companion_profile(gid, uid, False)
    if profile is None: return await cinnamon_send(interaction, "Use /pet to meet your companion first.", ephemeral=True)
    inv = economy_inventory_for(gid, uid)
    collected = [f"{ECONOMY_ITEMS[k]['emoji']} {ECONOMY_ITEMS[k]['name']} ×{int(inv.get(k, 0))}"
                 for k in _COMPANION_ACCESSORIES if int(inv.get(k, 0)) > 0]
    equipped = [f"{slot.title()}: {ECONOMY_ITEMS.get(item, {}).get('name', item)}"
                for slot, item in profile.get("equipped", {}).items()]
    e = discord.Embed(title=f"📖 {profile['name']}'s Catbook", color=0xE8A05A)
    e.add_field(name="Owned accessories", value="\n".join(collected) or "No accessories collected yet.", inline=False)
    e.add_field(name="Currently wearing", value="\n".join(equipped) or "Nothing equipped.", inline=False)
    e.add_field(name="Room", value=f"{len(profile.get('room', []))} decorations placed.", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

@companion_group.command(name="memories", description="Save and revisit private memories with your companion")
@app_commands.guild_only()
@app_commands.choices(action=[
    app_commands.Choice(name="Add memory", value="add"), app_commands.Choice(name="List memories", value="list"),
    app_commands.Choice(name="Delete memory", value="delete")])
@app_commands.describe(action="Choose an action", text="Memory text (for Add)", memory_id="Memory number (for Delete)")
async def companion_memories(interaction: discord.Interaction, action: app_commands.Choice[str], text: str | None = None, memory_id: app_commands.Range[int, 1, 20] | None = None):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _companion_lock(gid, uid):
        before = _companion_copy.deepcopy(_companion_profile(gid, uid, False))
        profile = _companion_profile(gid, uid)
        memories = profile.setdefault("memories", [])
        if action.value == "add":
            clean = " ".join(str(text or "").split()).strip()
            if not 1 <= len(clean) <= 300: return await cinnamon_send(interaction, "A memory must be 1–300 characters.", ephemeral=True)
            memories.append({"text": clean, "created_at": int(_companion_time.time())})
            del memories[:-20]
            if not await _companion_save_or_restore(gid, uid, before): return await cinnamon_send(interaction, "Couldn't save that memory.", ephemeral=True)
            response = "Saved a new companion memory."
        elif action.value == "delete":
            if memory_id is None or memory_id > len(memories): return await cinnamon_send(interaction, "Choose a memory number shown in /memories list.", ephemeral=True)
            memories.pop(memory_id - 1)
            if not await _companion_save_or_restore(gid, uid, before): return await cinnamon_send(interaction, "Couldn't delete that memory; it was restored.", ephemeral=True)
            response = "Memory deleted."
        else:
            response = "\n".join(f"**{i}.** {m.get('text', '')}" for i, m in enumerate(memories, 1)) or "No memories saved yet."
    await cinnamon_send(interaction, response[:1800], ephemeral=True)

@companion_group.command(name="catstats", description="See your companion's progression and care statistics")
@app_commands.guild_only()
async def companion_catstats(interaction: discord.Interaction):
    profile = _companion_profile(interaction.guild.id, interaction.user.id, False)
    if profile is None: return await cinnamon_send(interaction, "Use /pet to meet your companion first.", ephemeral=True)
    e = _companion_embed(interaction.guild, interaction.user, profile)
    stats = profile.get("stats", {})
    e.add_field(name="Care history", value=f"Feeds: {int(stats.get('feeds', 0))}\nPlays: {int(stats.get('plays', 0))}\nGrooms: {int(stats.get('grooms', 0))}", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


bot.tree.add_command(companion_group)
