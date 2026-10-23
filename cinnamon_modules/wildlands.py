"""Cinnamon: Wildlands — choice-driven exploration, crafting and camp progression.

Loaded by main.py into Cinnamon's shared runtime namespace. Uses the existing
Catnip wallet, shared item inventory, fishing/cooking recipes, quests and
achievements. All Wildlands state lives inside advanced_features_data so the
existing Upstash/local persistence mechanism stores it automatically.
"""

WILDLANDS_ENERGY_MAX = 100
WILDLANDS_ENERGY_REGEN_SECONDS = 120  # 1 energy every 2 minutes
WILDLANDS_EXPLORE_COST = 10
WILDLANDS_CLUE_REWARD_XP = 18
WILDLANDS_SECRET_REWARD_XP = 28

WILDLANDS_RESOURCES = {
    "branch": {"name": "Branch", "emoji": "🪵", "sell": 8},
    "wood": {"name": "Wood", "emoji": "🌲", "sell": 12},
    "fiber": {"name": "Plant Fiber", "emoji": "🧵", "sell": 10},
    "stone": {"name": "Stone", "emoji": "🪨", "sell": 12},
    "herb": {"name": "Wild Herb", "emoji": "🌿", "sell": 18},
    "berries": {"name": "Wild Berries", "emoji": "🫐", "sell": 10},
    "shell": {"name": "Seashell", "emoji": "🐚", "sell": 20},
    "driftwood": {"name": "Driftwood", "emoji": "🪵", "sell": 14},
    "sea_glass": {"name": "Sea Glass", "emoji": "🟢", "sell": 24},
    "old_coin": {"name": "Old Coin", "emoji": "🪙", "sell": 35},
    "iron_ore": {"name": "Iron Ore", "emoji": "⛏️", "sell": 32},
    "crystal": {"name": "Glow Crystal", "emoji": "💎", "sell": 48},
    "pearl": {"name": "Moon Pearl", "emoji": "🌕", "sell": 90},
    "moon_bloom": {"name": "Moon Bloom", "emoji": "🌸", "sell": 76},
    "frost_shard": {"name": "Frost Shard", "emoji": "❄️", "sell": 115},
    "ancient_fragment": {"name": "Ancient Fragment", "emoji": "🧩", "sell": 160},
}

WILDLANDS_ZONES = {
    "whispering_woods": {
        "name": "Whispering Woods", "emoji": "🌲", "rank": 1,
        "description": "A cozy forest full of rustling leaves, odd pawprints and old explorer trails.",
        "materials": {"branch": 25, "wood": 20, "fiber": 18, "herb": 12, "berries": 14, "stone": 7, "old_coin": 4},
        "encounters": [
            ("The Bent Oak", "A fallen oak rests across the path. Its roots curl around something shiny."),
            ("Fresh Pawprints", "A trail of tiny pawprints circles a mossy boulder, then vanishes."),
            ("The Old Campsite", "You discover a half-buried campsite. A tin cup rattles in the breeze."),
            ("Firefly Hollow", "Fireflies gather around a hollow tree, blinking in a pattern that feels almost deliberate."),
            ("The Unmarked Fork", "Two paths split beneath a wooden sign. One arrow points to nowhere."),
        ],
    },
    "quiet_shore": {
        "name": "Quiet Shore", "emoji": "🏝️", "rank": 2,
        "description": "A peaceful coast with tide pools, smooth glass and tiny messages left by the sea.",
        "materials": {"driftwood": 22, "shell": 22, "sea_glass": 18, "fiber": 8, "old_coin": 8, "pearl": 4, "herb": 6},
        "encounters": [
            ("A Bottle in the Tide", "A glass bottle rolls in with the tide. There's a folded map inside."),
            ("Singing Tidepool", "A tidepool hums softly despite the complete lack of wind."),
            ("The Pebble Arch", "A little arch of pebbles stands untouched by the waves."),
            ("The Empty Boat", "A tiny boat has washed ashore. Its owner left a mark on the seat."),
        ],
    },
    "stoneback_highlands": {
        "name": "Stoneback Highlands", "emoji": "⛰️", "rank": 3,
        "description": "Windy ridges, echoing stone shelves and mineral seams high above the trees.",
        "materials": {"stone": 25, "iron_ore": 22, "crystal": 16, "branch": 7, "old_coin": 10, "herb": 5, "pearl": 2},
        "encounters": [
            ("The Echo Shelf", "A pebble falls from a ledge. A second sound answers from much farther away."),
            ("The Split Boulder", "A split boulder reveals a thin line of crystal light."),
            ("A Cairn of Names", "Someone stacked stones and carved tiny initials into each one."),
            ("Cloudbreak Path", "Clouds part for a moment, revealing steps cut into the mountain."),
        ],
    },
    "moonlit_marsh": {
        "name": "Moonlit Marsh", "emoji": "🌙", "rank": 4,
        "description": "A silver-lit wetland where moon blooms glow and paths shift when nobody is looking.",
        "materials": {"herb": 20, "moon_bloom": 20, "crystal": 16, "pearl": 10, "fiber": 9, "ancient_fragment": 8, "old_coin": 5},
        "encounters": [
            ("The Lantern Mire", "Blue lights hover over the marsh, keeping the exact same distance from you."),
            ("The Moonwell", "A still pool reflects a moon that is not visible in the sky."),
            ("The Reed Maze", "The reeds rustle like someone quietly trying to give directions."),
            ("The Glass Lily", "A transparent lily grows from a patch of dark water."),
        ],
    },
    "frostfall_pass": {
        "name": "Frostfall Pass", "emoji": "❄️", "rank": 5,
        "description": "A frosty mountain pass with blue ice, warm caves and old footprints in the snow.",
        "materials": {"frost_shard": 25, "crystal": 18, "old_coin": 12, "herb": 5, "iron_ore": 10, "ancient_fragment": 4},
        "encounters": [
            ("The Blue Ice Window", "A sheet of blue ice reveals shapes trapped far beneath the surface."),
            ("The Snowcat Shelter", "A warm little cave holds a nest of neatly folded leaves."),
            ("The Frozen Bell", "A bell hangs from an icy branch, yet no rope reaches it."),
            ("The Whiteout Marker", "A line of old markers leads toward a cliff and then stops."),
        ],
    },
    "forgotten_ruins": {
        "name": "Forgotten Ruins", "emoji": "🏛️", "rank": 6,
        "description": "Ancient stone halls full of unfinished notes, star maps and the traces of previous explorers.",
        "materials": {"ancient_fragment": 26, "crystal": 18, "pearl": 15, "old_coin": 15, "iron_ore": 8, "moon_bloom": 7},
        "encounters": [
            ("The Door Without a Wall", "A stone doorway stands alone in a courtyard, with no wall on either side."),
            ("The Starless Room", "The ceiling is painted with constellations that do not exist."),
            ("The Last Explorer's Desk", "A desk is set for someone who seems to have stepped away only moments ago."),
            ("The Quiet Clock", "A stone clock has no hands, but its shadow moves."),
        ],
    },
}

WILDLANDS_CLUES = {
    "woods_sun_mark": {"name": "The Sun-Facing Mark", "zone": "whispering_woods", "text": "A carved paw points toward the last sunlight of the day."},
    "woods_old_route": {"name": "The Explorer's Route", "zone": "whispering_woods", "text": "A torn note says the coast can be reached by following three bent trees."},
    "shore_tide_code": {"name": "The Tide Code", "zone": "quiet_shore", "text": "The tide circles a half-buried stone three times before retreating."},
    "shore_glass_map": {"name": "The Glass Map", "zone": "quiet_shore", "text": "A pattern in the sea glass matches a shape on an old forest note."},
    "highland_echo": {"name": "The Answering Echo", "zone": "stoneback_highlands", "text": "The mountain echoes a phrase: 'look where the moon forgets itself.'"},
    "highland_engraving": {"name": "The Hidden Engraving", "zone": "stoneback_highlands", "text": "A stone engraving shows a lantern held above five small stars."},
    "marsh_song": {"name": "The Marsh Song", "zone": "moonlit_marsh", "text": "A tune describes lights that follow neither moon nor star."},
    "marsh_mirror": {"name": "The Mirror Pool", "zone": "moonlit_marsh", "text": "The pool reflects a doorway and a tiny paw-shaped keyhole."},
    "frost_inscription": {"name": "The Frost Inscription", "zone": "frostfall_pass", "text": "The inscription mentions a warm cloak, a lantern and five memories."},
    "frost_shelter_log": {"name": "The Shelter Log", "zone": "frostfall_pass", "text": "An old explorer's log says the ruins open only after their story is pieced together."},
    "ruin_final_page": {"name": "The Final Page", "zone": "forgotten_ruins", "text": "The final page says the sanctuary was built to be discovered by a community, not one person."},
}

WILDLANDS_SECRETS = {
    "foxfire_grotto": {"name": "Foxfire Grotto", "zone": "whispering_woods", "emoji": "✨", "text": "A quiet hollow glows with blue-green foxfire. Nothing here seems dangerous; it simply feels ancient."},
    "sleeping_giant_root": {"name": "The Sleeping Giant's Root", "zone": "whispering_woods", "emoji": "🌳", "text": "A root curls into the shape of a sleeping cat. Tiny flowers grow along its outline."},
    "glassbeach_cove": {"name": "Glassbeach Cove", "zone": "quiet_shore", "emoji": "🪸", "text": "A hidden cove is lined with sea glass that shines like stained glass in the sun."},
    "singing_tidepool": {"name": "The Singing Tidepool", "zone": "quiet_shore", "emoji": "🎵", "text": "The tidepool plays a gentle note whenever a wave reaches it."},
    "echo_mine": {"name": "The Echo Mine", "zone": "stoneback_highlands", "emoji": "💎", "text": "A small abandoned mine carries every sound to a chamber of glittering crystal."},
    "cloudbreaker_nest": {"name": "Cloudbreaker's Nest", "zone": "stoneback_highlands", "emoji": "☁️", "text": "A sheltered ledge opens onto a sea of clouds and a nest made entirely of blue grass."},
    "moonwell": {"name": "The Moonwell", "zone": "moonlit_marsh", "emoji": "🌙", "text": "A hidden pool mirrors a moonlit sky at any hour. Its water glows but stays perfectly cool."},
    "lantern_mire": {"name": "The Lantern Mire", "zone": "moonlit_marsh", "emoji": "🏮", "text": "Hundreds of little lights form a path, leading to a dry island in the middle of the marsh."},
    "blue_ice_archive": {"name": "The Blue-Ice Archive", "zone": "frostfall_pass", "emoji": "🧊", "text": "Stories have been preserved inside a blue wall of ice, like pages in a library."},
    "snowcat_shelter": {"name": "The Snowcat Shelter", "zone": "frostfall_pass", "emoji": "🐈", "text": "A hidden shelter is covered in pawprints and has a perfectly dry sleeping nook."},
    "starless_sanctum": {"name": "The Starless Sanctum", "zone": "forgotten_ruins", "emoji": "🌌", "text": "A sanctuary glows under a ceiling with no stars. Your discoveries fit into its walls like a key."},
    "first_explorer_archive": {"name": "The First Explorer's Archive", "zone": "forgotten_ruins", "emoji": "📚", "text": "You find the record of the first Wildlands explorers—and an empty space saved for future names."},
}

WILDLANDS_RECIPES = {
    "field_satchel": {"name": "Field Satchel", "emoji": "🎒", "desc": "A bigger pack for bringing more supplies home.", "needs": {"wood": 4, "fiber": 5}, "effect": "+10 material capacity", "capacity": 10},
    "forager_kit": {"name": "Forager's Kit", "emoji": "🧺", "desc": "A pocket guide and sturdy collecting tools.", "needs": {"branch": 4, "fiber": 3, "herb": 2}, "effect": "A chance to collect an extra material", "bonus_gather": True},
    "sturdy_boots": {"name": "Sturdy Trail Boots", "emoji": "🥾", "desc": "Grippy boots made for steep paths.", "needs": {"fiber": 5, "stone": 5, "wood": 3}, "effect": "Unlocks Stoneback Highlands and reduces exploration cost by 2", "unlocks": "stoneback_highlands"},
    "trail_lantern": {"name": "Trail Lantern", "emoji": "🏮", "desc": "A lantern that reveals markings ordinary light misses.", "needs": {"wood": 5, "shell": 2, "crystal": 3}, "effect": "Improves clue discoveries and opens the Moonlit Marsh", "unlocks": "moonlit_marsh"},
    "warm_cloak": {"name": "Warm Explorer's Cloak", "emoji": "🧥", "desc": "A cozy cloak for chilly high-altitude routes.", "needs": {"fiber": 7, "herb": 4, "crystal": 2}, "effect": "Unlocks Frostfall Pass", "unlocks": "frostfall_pass"},
    "ancient_map": {"name": "Ancient Star Map", "emoji": "🗺️", "desc": "A map that joins several clues into one path.", "needs": {"old_coin": 4, "crystal": 4, "ancient_fragment": 2}, "effect": "Helps unlock the Forgotten Ruins", "unlocks": "forgotten_ruins", "requires_camp": "research_table"},
}

WILDLANDS_CAMP_UPGRADES = {
    "storage_rack": {"name": "Storage Rack", "emoji": "📦", "desc": "Expand your materials capacity by 15.", "catnip": 500, "needs": {"wood": 8, "fiber": 5}, "capacity": 15},
    "field_kitchen": {"name": "Field Kitchen", "emoji": "🍲", "desc": "Packed cooked dishes give a stronger expedition bonus.", "catnip": 900, "needs": {"wood": 5, "stone": 4, "herb": 4}, "food_bonus": 0.05},
    "research_table": {"name": "Research Table", "emoji": "🔭", "desc": "Study clues and open the route toward the Forgotten Ruins.", "catnip": 1500, "needs": {"wood": 4, "stone": 8, "old_coin": 2}, "research": True},
}

WILDLANDS_MATERIAL_SELL_CHOICES = {k: v for k, v in WILDLANDS_RESOURCES.items()}


def _wildlands_root():
    # Fetch this dynamically: persistence restores advanced_features_data in place
    # but replaces its nested dictionaries when loading a saved snapshot.
    root = advanced_features_data.setdefault("wildlands", {})
    root.setdefault("players", {})
    root.setdefault("guilds", {})
    return root


def _wildlands_key(guild_id, user_id):
    return f"{int(guild_id)}:{int(user_id)}"


def _wildlands_player(guild_id, user_id):
    players = _wildlands_root()["players"]
    key = _wildlands_key(guild_id, user_id)
    rec = players.setdefault(key, {
        "level": 1, "xp": 0, "energy": WILDLANDS_ENERGY_MAX,
        "energy_at": time.time(), "location": "whispering_woods",
        "unlocked_zones": ["whispering_woods"], "materials": {}, "gear": [],
        "camp_upgrades": [], "explores": 0, "gathered": 0, "crafted": 0,
        "clues": [], "discoveries": [], "firsts": [], "prepared_ration": None,
        "stats": {"gather_choices": 0, "investigate_choices": 0, "track_choices": 0,
                  "material_units": 0, "rare_find_count": 0, "routes_travelled": 0},
        "pending_encounter": None,
    })
    defaults = {
        "level": 1, "xp": 0, "energy": WILDLANDS_ENERGY_MAX, "energy_at": time.time(),
        "location": "whispering_woods", "unlocked_zones": ["whispering_woods"],
        "materials": {}, "gear": [], "camp_upgrades": [], "explores": 0,
        "gathered": 0, "crafted": 0, "clues": [], "discoveries": [],
        "firsts": [], "prepared_ration": None, "pending_encounter": None,
    }
    for k, v in defaults.items():
        rec.setdefault(k, v)
    stats_defaults = {"gather_choices": 0, "investigate_choices": 0, "track_choices": 0,
                      "material_units": 0, "rare_find_count": 0, "routes_travelled": 0}
    stats = rec.setdefault("stats", {})
    for k, v in stats_defaults.items():
        stats.setdefault(k, v)
    rec["xp"] = max(0, int(rec.get("xp", 0)))
    rec["level"] = min(20, 1 + rec["xp"] // 100)
    rec["energy"] = max(0, min(WILDLANDS_ENERGY_MAX, int(rec.get("energy", WILDLANDS_ENERGY_MAX))))
    rec["materials"] = {str(k): max(0, int(v)) for k, v in rec.get("materials", {}).items() if k in WILDLANDS_RESOURCES and int(v) > 0}
    return rec


def _wildlands_energy(rec):
    now = time.time()
    energy = max(0, min(WILDLANDS_ENERGY_MAX, int(rec.get("energy", WILDLANDS_ENERGY_MAX))))
    last = float(rec.get("energy_at", now))
    if energy >= WILDLANDS_ENERGY_MAX:
        rec["energy"] = WILDLANDS_ENERGY_MAX
        rec["energy_at"] = now
        return WILDLANDS_ENERGY_MAX
    gained = max(0, int((now - last) // WILDLANDS_ENERGY_REGEN_SECONDS))
    if gained:
        energy = min(WILDLANDS_ENERGY_MAX, energy + gained)
        rec["energy"] = energy
        rec["energy_at"] = last + gained * WILDLANDS_ENERGY_REGEN_SECONDS
        if energy >= WILDLANDS_ENERGY_MAX:
            rec["energy_at"] = now
    return int(rec["energy"])


def _wildlands_capacity(rec):
    capacity = 20
    if "field_satchel" in rec.get("gear", []):
        capacity += 10
    if "storage_rack" in rec.get("camp_upgrades", []):
        capacity += 15
    return capacity


def _wildlands_material_total(rec):
    return sum(max(0, int(v)) for v in rec.get("materials", {}).values())


def _wildlands_level(rec):
    rec["level"] = min(20, 1 + max(0, int(rec.get("xp", 0))) // 100)
    return int(rec["level"])


def _wildlands_add_xp(rec, amount):
    before = _wildlands_level(rec)
    rec["xp"] = max(0, int(rec.get("xp", 0))) + max(0, int(amount))
    after = _wildlands_level(rec)
    return after, after > before


def _wildlands_unlocked(guild_id, user_id, rec=None):
    rec = rec or _wildlands_player(guild_id, user_id)
    unlocked = set(rec.get("unlocked_zones", ["whispering_woods"]))
    gear = set(rec.get("gear", []))
    clues = set(rec.get("clues", []))
    if int(rec.get("explores", 0)) >= 2:
        unlocked.add("quiet_shore")
    if "sturdy_boots" in gear:
        unlocked.add("stoneback_highlands")
    if "trail_lantern" in gear and len(clues) >= 2:
        unlocked.add("moonlit_marsh")
    if "warm_cloak" in gear:
        unlocked.add("frostfall_pass")
    if ("research_table" in rec.get("camp_upgrades", []) and "ancient_map" in gear
            and len(clues) >= 5 and _wildlands_level(rec) >= 6):
        unlocked.add("forgotten_ruins")
    # Persist unlock order consistently for maps and travel autocompletion.
    rec["unlocked_zones"] = [z for z in WILDLANDS_ZONES if z in unlocked]
    return set(rec["unlocked_zones"])


def _wildlands_unlock_messages(old, new):
    newly = [z for z in WILDLANDS_ZONES if z in new and z not in old]
    return [f"{WILDLANDS_ZONES[z]['emoji']} **New area unlocked: {WILDLANDS_ZONES[z]['name']}!**" for z in newly]


def _wildlands_clue_for_zone(zone, rec):
    found = set(rec.get("clues", []))
    options = [k for k, v in WILDLANDS_CLUES.items() if v["zone"] == zone and k not in found]
    return random.choice(options) if options else None


def _wildlands_unique_for_zone(zone, rec):
    found = set(rec.get("discoveries", []))
    options = [k for k, v in WILDLANDS_SECRETS.items() if v["zone"] == zone and k not in found]
    return random.choice(options) if options else None


def _wildlands_roll_material(zone, rec, *, bonus=0):
    zone_data = WILDLANDS_ZONES[zone]
    weighted = dict(zone_data["materials"])
    if "forager_kit" in rec.get("gear", []):
        weighted["fiber"] = weighted.get("fiber", 0) + 3
        weighted["herb"] = weighted.get("herb", 0) + 2
    if bonus > 0:
        if "crystal" in weighted:
            weighted["crystal"] += int(bonus * 100)
        else:
            weighted["old_coin"] = weighted.get("old_coin", 0) + int(bonus * 100)
    keys = list(weighted)
    weights = [max(1, int(weighted[k])) for k in keys]
    return random.choices(keys, weights=weights, k=1)[0]


def _wildlands_add_materials(rec, material_id, amount):
    amount = max(0, int(amount))
    capacity = _wildlands_capacity(rec)
    room = max(0, capacity - _wildlands_material_total(rec))
    accepted = min(room, amount)
    if accepted:
        inv = rec.setdefault("materials", {})
        inv[material_id] = int(inv.get(material_id, 0)) + accepted
        rec["gathered"] = int(rec.get("gathered", 0)) + accepted
        stats = rec.setdefault("stats", {})
        stats["material_units"] = int(stats.get("material_units", 0)) + accepted
    return accepted, amount - accepted


def _wildlands_rewards_text(rewards):
    rows = []
    for material_id, qty in rewards.items():
        if qty > 0 and material_id in WILDLANDS_RESOURCES:
            item = WILDLANDS_RESOURCES[material_id]
            rows.append(f"{item['emoji']} **{item['name']} ×{qty}**")
    return "\n".join(rows) or "No materials this time—but you learned something useful."


def _wildlands_ration_bonus(rec):
    packed = rec.get("prepared_ration")
    if not packed:
        return 0.0, None
    dish_id = str(packed.get("dish", ""))
    dish = DISH_RECIPES.get(dish_id, {}) if "DISH_RECIPES" in globals() else {}
    level = int(dish.get("level", packed.get("level", 1)))
    bonus = min(0.20, 0.04 + level * 0.006)
    if "field_kitchen" in rec.get("camp_upgrades", []):
        bonus = min(0.25, bonus + 0.05)
    return bonus, packed


def _wildlands_recipe_line(recipe_id, recipe, rec=None):
    parts = []
    mats = (rec or {}).get("materials", {})
    for material_id, amount in recipe["needs"].items():
        item = WILDLANDS_RESOURCES[material_id]
        have = int(mats.get(material_id, 0))
        parts.append(f"{item['emoji']} {item['name']} {have}/{amount}")
    status = "✅ Crafted" if recipe_id in (rec or {}).get("gear", []) else "📐 Blueprint"
    return f"{recipe['emoji']} **{recipe['name']}** — {recipe['desc']}\n{status} · " + " · ".join(parts) + f"\nEffect: {recipe['effect']}"


def _wildlands_camp_line(upgrade_id, upgrade, rec):
    mats = rec.get("materials", {})
    costs = [f"{WILDLANDS_RESOURCES[m]['emoji']} {WILDLANDS_RESOURCES[m]['name']} {int(mats.get(m, 0))}/{n}" for m, n in upgrade["needs"].items()]
    price = int(upgrade["catnip"])
    return f"{upgrade['emoji']} **{upgrade['name']}** — {upgrade['desc']}\nCost: **{price:,} Catnip** · " + " · ".join(costs)


async def _wildlands_reward_milestone(guild_id, user_id, name):
    """Record a one-time Wildlands milestone in Cinnamon's shared interaction history."""
    # This is intentionally called only for unique clues/locations, not for every
    # exploration click, so the normal interaction quests cannot be farmed.
    try:
        await achievement_record(guild_id, user_id, "interaction", 1, name=f"wildlands_{name}")
    except Exception:
        pass


async def _wildlands_resolve(guild_id, user, action):
    uid = user.id
    rec = _wildlands_player(guild_id, uid)
    pending = rec.get("pending_encounter")
    if not isinstance(pending, dict):
        return cinnamon_embed("🐾 Wildlands", "That encounter has already ended. Use `/adventure explore` to find another.", color=CINNAMON_ORANGE, user=user)
    zone = pending.get("zone", rec.get("location", "whispering_woods"))
    if zone not in WILDLANDS_ZONES:
        zone = "whispering_woods"
    before_unlocked = set(rec.get("unlocked_zones", ["whispering_woods"]))
    bonus, packed = _wildlands_ration_bonus(rec)
    if packed:
        rec["prepared_ration"] = None
    rewards = {}
    lines = []
    xp = random.randint(9, 14)
    first_discovery_text = ""
    capacity_note = ""

    def add_mat(material_id, amount):
        nonlocal capacity_note
        accepted, overflow = _wildlands_add_materials(rec, material_id, amount)
        if accepted:
            rewards[material_id] = rewards.get(material_id, 0) + accepted
        if overflow:
            capacity_note = f"\n🎒 Your pack had room for only {accepted} of that stack; the rest was left safely at the site."
        return accepted

    def find_clue(force=False):
        clue_id = _wildlands_clue_for_zone(zone, rec)
        if clue_id and (force or random.random() < 0.60 + (0.15 if "trail_lantern" in rec.get("gear", []) else 0) + bonus):
            clue = WILDLANDS_CLUES[clue_id]
            rec.setdefault("clues", []).append(clue_id)
            lines.append(f"📜 **Clue found: {clue['name']}**\n_{clue['text']}_")
            return True
        return False

    def find_secret(force=False):
        nonlocal first_discovery_text
        secret_id = _wildlands_unique_for_zone(zone, rec)
        if secret_id and (force or random.random() < 0.35 + bonus + (0.10 if "trail_lantern" in rec.get("gear", []) else 0)):
            secret = WILDLANDS_SECRETS[secret_id]
            rec.setdefault("discoveries", []).append(secret_id)
            rec.setdefault("firsts", [])
            guild_data = _wildlands_root()["guilds"].setdefault(str(guild_id), {"first_discoveries": {}, "discovery_count": 0})
            firsts = guild_data.setdefault("first_discoveries", {})
            if secret_id not in firsts:
                firsts[secret_id] = {"user_id": int(uid), "at": time.time()}
                guild_data["discovery_count"] = int(guild_data.get("discovery_count", 0)) + 1
                rec["firsts"].append(secret_id)
                first_discovery_text = f"\n🏆 **First in this server!** {user.display_name} is the first explorer to record this place."
            lines.append(f"{secret['emoji']} **Secret discovered: {secret['name']}**\n_{secret['text']}_")
            rec.setdefault("stats", {})["rare_find_count"] = int(rec["stats"].get("rare_find_count", 0)) + 1
            return True
        return False

    # The actions deliberately differ: gather is reliable, investigate finds lore,
    # and following tracks is the higher-variance route to a rare location.
    if action == "gather":
        rec.setdefault("stats", {})["gather_choices"] = int(rec["stats"].get("gather_choices", 0)) + 1
        rolls = 2 + (1 if "forager_kit" in rec.get("gear", []) and random.random() < 0.65 else 0)
        for _ in range(rolls):
            material_id = _wildlands_roll_material(zone, rec)
            add_mat(material_id, random.randint(1, 2))
        lines.append("🧺 You take a careful harvest and leave the area tidy.")
        if random.random() < (0.05 + bonus):
            find_secret()
        xp += 3
    elif action == "investigate":
        rec.setdefault("stats", {})["investigate_choices"] = int(rec["stats"].get("investigate_choices", 0)) + 1
        roll = random.random()
        if roll < min(0.52, 0.28 + bonus + (0.12 if "trail_lantern" in rec.get("gear", []) else 0)):
            if not find_clue():
                if not find_secret():
                    material_id = _wildlands_roll_material(zone, rec)
                    add_mat(material_id, random.randint(1, 2))
                    lines.append("🔎 The trail was already familiar, but you found something useful nearby.")
        elif roll < 0.78:
            if not find_secret():
                material_id = _wildlands_roll_material(zone, rec)
                add_mat(material_id, random.randint(1, 3))
                lines.append("🔎 You turn up a useful material among the odd little details.")
        else:
            material_id = _wildlands_roll_material(zone, rec)
            add_mat(material_id, random.randint(1, 2))
            lines.append("🔎 No grand answer yet. A small useful find makes the detour worthwhile.")
        xp += 6
    else:  # follow tracks
        rec.setdefault("stats", {})["track_choices"] = int(rec["stats"].get("track_choices", 0)) + 1
        roll = random.random()
        if roll < min(0.52, 0.26 + bonus + (0.12 if "trail_lantern" in rec.get("gear", []) else 0)):
            if not find_secret():
                material_id = _wildlands_roll_material(zone, rec, bonus=bonus)
                add_mat(material_id, random.randint(1, 3))
                lines.append("🐾 The tracks led to a good foraging spot, even if their owner stayed hidden.")
        elif roll < 0.78:
            if not find_clue():
                material_id = _wildlands_roll_material(zone, rec)
                add_mat(material_id, random.randint(1, 2))
                lines.append("🐾 The trail ended at a patch of useful materials.")
        else:
            material_id = _wildlands_roll_material(zone, rec, bonus=bonus)
            add_mat(material_id, random.randint(2, 3))
            lines.append("🐾 You follow the prints to a hidden patch and gather what you can.")
        xp += 5

    # Any ration boosts the rare-find chance above. Higher-tier cooked dishes add
    # a little extra XP; the Field Kitchen improves the clue/secret odds.
    if packed:
        dish_id = str(packed.get("dish", ""))
        dish = DISH_RECIPES.get(dish_id, {}) if "DISH_RECIPES" in globals() else {}
        dish_name = dish.get("name", packed.get("name", "packed meal"))
        dish_level = int(dish.get("level", packed.get("level", 1)))
        xp += min(8, 2 + dish_level // 4)
        lines.append(f"🍲 Your packed **{dish_name}** kept you focused (+{min(8, 2 + dish_level // 4)} Wildlands XP).")

    new_level, level_up = _wildlands_add_xp(rec, xp)
    rec["explores"] = int(rec.get("explores", 0)) + 1
    rec["location"] = zone
    rec["pending_encounter"] = None
    new_unlocked = _wildlands_unlocked(guild_id, uid, rec)
    gathered_this_encounter = sum(int(qty) for qty in rewards.values())
    new_clues = [x for x in rec.get("clues", []) if x not in pending.get("clues_before", [])]
    new_secrets = [x for x in rec.get("discoveries", []) if x not in pending.get("discoveries_before", [])]
    try:
        await achievement_record(guild_id, uid, "wildlands_explore", 1)
        await quest_event(guild_id, uid, "wildlands_explore", 1)
        if gathered_this_encounter:
            await achievement_record(guild_id, uid, "wildlands_material_units", gathered_this_encounter)
            await quest_event(guild_id, uid, "wildlands_material_units", gathered_this_encounter)
        for _ in new_clues:
            await achievement_record(guild_id, uid, "wildlands_clue", 1)
            await quest_event(guild_id, uid, "wildlands_clue", 1)
        for _ in new_secrets:
            await achievement_record(guild_id, uid, "wildlands_secret", 1)
            await quest_event(guild_id, uid, "wildlands_secret", 1)
        if packed:
            await achievement_record(guild_id, uid, "wildlands_ration", 1)
            await quest_event(guild_id, uid, "wildlands_ration", 1)
    except Exception:
        log.exception("Could not update Wildlands quest/achievement progress")
    unlock_lines = _wildlands_unlock_messages(before_unlocked, new_unlocked)
    # Record true discoveries as distinct Cinnamon interaction milestones only.
    if any("Clue found:" in line for line in lines):
        clue_name = next((x for x in rec.get("clues", []) if x not in pending.get("clues_before", [])), None)
        if clue_name:
            await _wildlands_reward_milestone(guild_id, uid, f"clue_{clue_name}")
    if any("Secret discovered:" in line for line in lines):
        secret_name = next((x for x in rec.get("discoveries", []) if x not in pending.get("discoveries_before", [])), None)
        if secret_name:
            await _wildlands_reward_milestone(guild_id, uid, f"secret_{secret_name}")
    await bd_save_data()

    title = f"{WILDLANDS_ZONES[zone]['emoji']} {pending.get('title', 'Wildlands Encounter')}"
    description = "\n\n".join(lines)
    if rewards:
        description += "\n\n**Gathered**\n" + _wildlands_rewards_text(rewards)
    description += f"\n\n⭐ Wildlands XP: **+{xp}** · Level **{new_level}**"
    if level_up:
        description += f"\n🎉 **Wildlands Level Up!** You reached Level {new_level}."
    if bonus and packed:
        description += f"\n🍲 Ration bonus used: **+{int(bonus * 100)}% rare-find chance**."
    if capacity_note:
        description += capacity_note
    if unlock_lines:
        description += "\n\n" + "\n".join(unlock_lines)
    if first_discovery_text:
        description += first_discovery_text
        description += "\nThe server discovery record has been updated."
    embed = cinnamon_embed(title, description, color=CINNAMON_GREEN if rewards or "Secret discovered:" in description else CINNAMON_ORANGE, user=user, footer="Cinnamon Wildlands • Choice resolved")
    embed.add_field(name="🎒 Pack", value=f"{_wildlands_material_total(rec)}/{_wildlands_capacity(rec)} materials", inline=True)
    embed.add_field(name="⚡ Energy", value=f"{rec['energy']}/{WILDLANDS_ENERGY_MAX}", inline=True)
    return embed


class WildlandsEncounterView(discord.ui.View):
    def __init__(self, guild_id, user_id):
        super().__init__(timeout=180)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)

    async def _choose(self, interaction: discord.Interaction, action: str):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("🐾 This little expedition belongs to the person who started it.", ephemeral=True)
            return
        rec = _wildlands_player(self.guild_id, self.user_id)
        if not isinstance(rec.get("pending_encounter"), dict):
            await interaction.response.send_message("That encounter has already ended. Start a new one with `/adventure explore`.", ephemeral=True)
            return
        await interaction.response.defer()
        embed = await _wildlands_resolve(self.guild_id, interaction.user, action)
        for child in self.children:
            child.disabled = True
        await interaction.edit_original_response(embed=embed, view=WildlandsResultView(self.guild_id, self.user_id))

    @discord.ui.button(label="Gather supplies", emoji="🧺", style=discord.ButtonStyle.success)
    async def gather_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "gather")

    @discord.ui.button(label="Investigate", emoji="🔎", style=discord.ButtonStyle.primary)
    async def investigate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "investigate")

    @discord.ui.button(label="Follow tracks", emoji="🐾", style=discord.ButtonStyle.secondary)
    async def tracks_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._choose(interaction, "tracks")


def _wildlands_pending_embed(user, rec):
    pending = rec.get("pending_encounter")
    if not isinstance(pending, dict):
        return None
    zone = pending.get("zone", rec.get("location", "whispering_woods"))
    z = WILDLANDS_ZONES.get(zone, WILDLANDS_ZONES["whispering_woods"])
    packed = rec.get("prepared_ration")
    ration_text = ""
    if packed:
        dish = DISH_RECIPES.get(str(packed.get("dish", "")), {}) if "DISH_RECIPES" in globals() else {}
        ration_text = f"\n🍲 Packed ration: **{dish.get('name', packed.get('name', 'Meal'))}** (bonus applies to this choice)."
    embed = cinnamon_embed(
        f"{z['emoji']} {pending.get('title', 'Wildlands Encounter')}",
        f"**{z['name']}**\n{pending.get('story', z['description'])}\n\nChoose your approach. Each route has different chances of materials, clues and secret places.{ration_text}\n\n⚡ Energy already spent: **{pending.get('cost', WILDLANDS_EXPLORE_COST)}**",
        color=CINNAMON_ORANGE, user=user, footer="Cinnamon Wildlands • Pick a route",
    )
    embed.add_field(name="🧺 Gather supplies", value="Reliable materials; low secret chance.", inline=True)
    embed.add_field(name="🔎 Investigate", value="Best for clues and lore.", inline=True)
    embed.add_field(name="🐾 Follow tracks", value="Higher-variance route with a better secret chance.", inline=True)
    return embed


async def _wildlands_send_pending(interaction, rec):
    embed = _wildlands_pending_embed(interaction.user, rec)
    if embed is None:
        return False
    await interaction.response.send_message(embed=embed, view=WildlandsEncounterView(interaction.guild.id, interaction.user.id), allowed_mentions=discord.AllowedMentions.none())
    return True


def _wildlands_hub_embed(guild_id, user):
    rec = _wildlands_player(guild_id, user.id)
    energy = _wildlands_energy(rec)
    unlocked = _wildlands_unlocked(guild_id, user.id, rec)
    zone = WILDLANDS_ZONES.get(rec.get("location"), WILDLANDS_ZONES["whispering_woods"])
    level = _wildlands_level(rec)
    xp_into = int(rec.get("xp", 0)) % 100
    gear_count = sum(1 for x in rec.get("gear", []) if x in WILDLANDS_RECIPES)
    upgrades_count = sum(1 for x in rec.get("camp_upgrades", []) if x in WILDLANDS_CAMP_UPGRADES)
    lines = [
        f"**Where you are:** {zone['emoji']} {zone['name']}",
        f"**Level:** {level}/20 · {xp_into}/100 XP  |  **Energy:** {energy}/{WILDLANDS_ENERGY_MAX}",
        f"**Pack:** {_wildlands_material_total(rec)}/{_wildlands_capacity(rec)} materials",
        f"**Discoveries:** {len(rec.get('discoveries', []))}/{len(WILDLANDS_SECRETS)} secrets · {len(rec.get('clues', []))}/{len(WILDLANDS_CLUES)} clues",
        f"**Build:** {gear_count} gear pieces · {upgrades_count} camp upgrades · {len(unlocked)} areas opened",
    ]
    if rec.get("pending_encounter"):
        lines.append("\n⏳ **An encounter is waiting.** Press Explore to resume it without paying energy again.")
    else:
        lines.append("\nChoose **Explore** to start an encounter, or use the other buttons to inspect your progress without flooding the channel.")
    embed = cinnamon_embed("🐈 Cinnamon: Wildlands", "\n".join(lines), color=CINNAMON_ORANGE, user=user, footer="Personal journey • Server-wide first discoveries • Button-driven hub")
    embed.add_field(name="🧭 Your next steps", value="Find materials → craft gear → unlock regions → piece together the Sanctuary mystery.", inline=False)
    return embed


class WildlandsHubView(discord.ui.View):
    """Low-noise, player-owned menu inspired by one-message Discord RPG hubs."""
    def __init__(self, guild_id, user_id):
        super().__init__(timeout=900)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)

    async def _guard(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("🐾 This Wildlands hub belongs to the explorer who opened it. Use `/adventure play` to open your own.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Explore", emoji="🧭", style=discord.ButtonStyle.success, row=0)
    async def explore_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        rec = _wildlands_player(self.guild_id, self.user_id)
        _wildlands_energy(rec)
        _wildlands_unlocked(self.guild_id, self.user_id, rec)
        if rec.get("pending_encounter"):
            await interaction.response.edit_message(embed=_wildlands_pending_embed(interaction.user, rec), view=WildlandsEncounterView(self.guild_id, self.user_id))
            return
        zone_id = rec.get("location", "whispering_woods")
        if zone_id not in WILDLANDS_ZONES:
            zone_id = "whispering_woods"
        cost = max(5, WILDLANDS_EXPLORE_COST - (2 if "sturdy_boots" in rec.get("gear", []) else 0))
        if int(rec.get("energy", 0)) < cost:
            missing = cost - int(rec.get("energy", 0))
            mins = max(1, (missing * WILDLANDS_ENERGY_REGEN_SECONDS + 59) // 60)
            await interaction.response.send_message(f"😴 You need **{cost} energy** but have **{rec['energy']}**. Energy regenerates automatically; check back in about **{mins} minute(s)**. Nothing is lost.", ephemeral=True)
            await bd_save_data()
            return
        await interaction.response.defer()
        rec["energy"] = int(rec["energy"]) - cost
        rec["energy_at"] = time.time()
        encounter_id, encounter = random.choice(list(enumerate(WILDLANDS_ZONES[zone_id]["encounters"])))
        title, story = encounter
        rec["pending_encounter"] = {
            "zone": zone_id, "encounter_id": encounter_id, "title": title, "story": story,
            "cost": cost, "created_at": time.time(), "clues_before": list(rec.get("clues", [])),
            "discoveries_before": list(rec.get("discoveries", [])),
        }
        await bd_save_data()
        await interaction.edit_original_response(embed=_wildlands_pending_embed(interaction.user, rec), view=WildlandsEncounterView(self.guild_id, self.user_id))

    @discord.ui.button(label="Status", emoji="📊", style=discord.ButtonStyle.primary, row=0)
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        await interaction.response.send_message(embed=_wildlands_hub_embed(self.guild_id, interaction.user), ephemeral=True)

    @discord.ui.button(label="Map", emoji="🗺️", style=discord.ButtonStyle.secondary, row=0)
    async def map_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        rec = _wildlands_player(self.guild_id, self.user_id)
        unlocked = _wildlands_unlocked(self.guild_id, self.user_id, rec)
        conditions = {
            "whispering_woods": "Starting area", "quiet_shore": "Complete 2 expeditions",
            "stoneback_highlands": "Craft Sturdy Trail Boots", "moonlit_marsh": "Craft a Trail Lantern and discover 2 clues",
            "frostfall_pass": "Craft a Warm Explorer's Cloak",
            "forgotten_ruins": "Level 6, 5 clues, Ancient Star Map and Research Table",
        }
        rows = []
        for zid, zone in WILDLANDS_ZONES.items():
            mark = "🟢" if zid in unlocked else "🔒"
            suffix = "**OPEN**" if zid in unlocked else f"Unlock: {conditions[zid]}"
            current = " · **YOU ARE HERE**" if rec.get("location") == zid else ""
            rows.append(f"{mark} {zone['emoji']} **{zone['name']}**{current}\n_{zone['description']}_\n{suffix}")
        embed = cinnamon_embed("🗺️ The Wildlands Map", "\n\n".join(rows), color=CINNAMON_ORANGE, user=interaction.user, footer="Travel with `/adventure travel`")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Pack", emoji="🎒", style=discord.ButtonStyle.secondary, row=1)
    async def inventory_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        rec = _wildlands_player(self.guild_id, self.user_id)
        mats = [f"{WILDLANDS_RESOURCES[k]['emoji']} {WILDLANDS_RESOURCES[k]['name']} ×{int(v)}" for k, v in rec.get("materials", {}).items() if k in WILDLANDS_RESOURCES and int(v) > 0]
        inv = economy_inventory_for(self.guild_id, self.user_id)
        fish = []
        for fid, qty in inv.items():
            if int(qty) > 0 and fid in globals().get("FISH_SPECIES", {}):
                species = FISH_SPECIES[fid]
                fish.append(f"{species['emoji']} {species['name']} ×{int(qty)}")
        dishes = []
        for did, qty in inv.items():
            if int(qty) > 0 and did in globals().get("DISH_RECIPES", {}):
                dish = DISH_RECIPES[did]
                dishes.append(f"{dish['emoji']} {dish['name']} ×{int(qty)}")
        embed = cinnamon_embed("🎒 Wildlands Pack", f"**Materials:** {_wildlands_material_total(rec)}/{_wildlands_capacity(rec)}\n\n" + ("\n".join(mats[:10]) or "No gathered materials yet."), color=CINNAMON_ORANGE, user=interaction.user, footer="Fish and dishes come from Cinnamon's shared fishing/cooking inventory")
        embed.add_field(name="🎣 Fish", value="\n".join(fish[:6]) or "No fish in shared inventory.", inline=True)
        embed.add_field(name="🍲 Cooked dishes", value="\n".join(dishes[:6]) or "No dishes yet. Use `/cook make`.", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Journal", emoji="📖", style=discord.ButtonStyle.secondary, row=1)
    async def journal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        rec = _wildlands_player(self.guild_id, self.user_id)
        clue_lines = [f"📜 {WILDLANDS_CLUES[c]['name']}" for c in rec.get("clues", []) if c in WILDLANDS_CLUES]
        secret_lines = [f"{WILDLANDS_SECRETS[x]['emoji']} {WILDLANDS_SECRETS[x]['name']}" for x in rec.get("discoveries", []) if x in WILDLANDS_SECRETS]
        gd = _wildlands_root()["guilds"].get(str(self.guild_id), {})
        firsts = gd.get("first_discoveries", {})
        desc = f"**Personal:** {len(secret_lines)}/{len(WILDLANDS_SECRETS)} secrets · {len(clue_lines)}/{len(WILDLANDS_CLUES)} clues\n**Server-first discoveries:** {len(firsts)}/{len(WILDLANDS_SECRETS)}\n\n**Clues**\n" + ("\n".join(clue_lines[:7]) or "No clues collected yet.") + "\n\n**Secret places**\n" + ("\n".join(secret_lines[:7]) or "No secrets found yet.")
        embed = cinnamon_embed("📖 Wildlands Discovery Journal", desc, color=CINNAMON_ORANGE, user=interaction.user, footer="Clues and secrets are permanent records")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class WildlandsResultView(discord.ui.View):
    def __init__(self, guild_id, user_id):
        super().__init__(timeout=600)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)

    @discord.ui.button(label="Return to Wildlands Hub", emoji="🐈", style=discord.ButtonStyle.primary)
    async def return_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("🐾 This adventure belongs to another explorer.", ephemeral=True)
            return
        rec = _wildlands_player(self.guild_id, self.user_id)
        await interaction.response.edit_message(embed=_wildlands_hub_embed(self.guild_id, interaction.user), view=WildlandsHubView(self.guild_id, self.user_id))


adventure_group = app_commands.Group(name="adventure", description="Explore Cinnamon's Wildlands, craft gear and discover secrets")


@adventure_group.command(name="play", description="Open your interactive Wildlands hub")
@app_commands.guild_only()
async def wildlands_play(interaction: discord.Interaction):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    if not rec.get("started"):
        await interaction.response.send_message("First use `/adventure start` to register and receive your starter supplies.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    embed = _wildlands_hub_embed(interaction.guild.id, interaction.user)
    await bd_save_data()
    await interaction.edit_original_response(embed=embed, view=WildlandsHubView(interaction.guild.id, interaction.user.id), allowed_mentions=discord.AllowedMentions.none())


@adventure_group.command(name="start", description="Start your personal Wildlands adventure")
@app_commands.guild_only()
async def wildlands_start(interaction: discord.Interaction):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    await interaction.response.defer(thinking=True)
    first_start = not bool(rec.get("started"))
    if first_start:
        rec["started"] = True
        rec["materials"]["branch"] = int(rec["materials"].get("branch", 0)) + 2
        rec["materials"]["fiber"] = int(rec["materials"].get("fiber", 0)) + 2
        rec["materials"]["berries"] = int(rec["materials"].get("berries", 0)) + 1
        intro = "Welcome to **Cinnamon: Wildlands**! Cinnamon has appointed you as the server's unofficial explorer.\n\nYou start in Whispering Woods with a small pack and a few supplies. Every expedition offers three choices: gather supplies, investigate a mystery, or follow strange tracks.\n\nCrafted gear is automatically active; food you cook can be packed for a one-expedition bonus. Discoveries are yours, while the server keeps a shared record of first finds.\n\n**Starter supplies:** 🪵 Branch ×2 · 🧵 Plant Fiber ×2 · 🫐 Wild Berries ×1\n\nStart with `/adventure play` for the interactive hub or `/adventure explore` to go straight to your first encounter."
    else:
        intro = "You're already registered, explorer! Your camp and discoveries are safe. Use `/adventure play` to continue from the interactive hub, or `/adventure status` to inspect your progress."
    # Backfill the origin visit once for existing records created before the hub update.
    seen = rec.setdefault("visited_zones", [])
    if "whispering_woods" not in seen:
        seen.append("whispering_woods")
        try:
            await achievement_record(interaction.guild.id, interaction.user.id, "wildlands_zone", 1, zone="whispering_woods")
            await quest_event(interaction.guild.id, interaction.user.id, "wildlands_zone", 1)
        except Exception:
            log.exception("Could not seed starting Wildlands zone progress")
    await bd_save_data()
    await interaction.edit_original_response(embed=cinnamon_embed("🐈 Welcome to Cinnamon: Wildlands", intro, color=CINNAMON_GREEN, user=interaction.user, footer="Wildlands • Your journey, your discoveries"), allowed_mentions=discord.AllowedMentions.none())


@adventure_group.command(name="status", description="View your energy, level, gear and current area")
@app_commands.guild_only()
async def wildlands_status(interaction: discord.Interaction):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    _wildlands_energy(rec)
    unlocked = _wildlands_unlocked(interaction.guild.id, interaction.user.id, rec)
    zone_id = rec.get("location", "whispering_woods")
    zone = WILDLANDS_ZONES.get(zone_id, WILDLANDS_ZONES["whispering_woods"])
    gear = [WILDLANDS_RECIPES[g]["name"] for g in rec.get("gear", []) if g in WILDLANDS_RECIPES]
    upgrades = [WILDLANDS_CAMP_UPGRADES[u]["name"] for u in rec.get("camp_upgrades", []) if u in WILDLANDS_CAMP_UPGRADES]
    level = _wildlands_level(rec)
    xp_into = int(rec.get("xp", 0)) % 100
    capacity = _wildlands_capacity(rec)
    lines = [f"**Current area:** {zone['emoji']} {zone['name']}", f"**Wildlands level:** {level}/20 · {xp_into}/100 XP to next level", f"**Energy:** {_wildlands_energy(rec)}/{WILDLANDS_ENERGY_MAX} · restores 1 every 2 minutes", f"**Material pack:** {_wildlands_material_total(rec)}/{capacity}", f"**Expeditions:** {int(rec.get('explores', 0)):,} · **Clues:** {len(rec.get('clues', []))}/{len(WILDLANDS_CLUES)} · **Secrets:** {len(rec.get('discoveries', []))}/{len(WILDLANDS_SECRETS)}"]
    embed = cinnamon_embed("🧭 Wildlands Explorer Card", "\n".join(lines), color=CINNAMON_ORANGE, user=interaction.user, footer="Cinnamon Wildlands • Personal progress")
    embed.add_field(name="🧰 Crafted gear", value="\n".join(f"{WILDLANDS_RECIPES[g]['emoji']} {WILDLANDS_RECIPES[g]['name']}" for g in rec.get("gear", []) if g in WILDLANDS_RECIPES) or "No crafted gear yet. Use `/adventure recipes`.", inline=True)
    embed.add_field(name="🏕️ Camp upgrades", value="\n".join(f"{WILDLANDS_CAMP_UPGRADES[u]['emoji']} {WILDLANDS_CAMP_UPGRADES[u]['name']}" for u in rec.get("camp_upgrades", []) if u in WILDLANDS_CAMP_UPGRADES) or "A simple campsite for now.", inline=True)
    embed.add_field(name="🗺️ Areas unlocked", value=", ".join(WILDLANDS_ZONES[z]["name"] for z in WILDLANDS_ZONES if z in unlocked), inline=False)
    if rec.get("pending_encounter"):
        embed.add_field(name="⏳ Encounter waiting", value="You have an unfinished encounter. Run `/adventure explore` to reopen its choices without spending energy again.", inline=False)
    if rec.get("prepared_ration"):
        dish = DISH_RECIPES.get(str(rec["prepared_ration"].get("dish", "")), {}) if "DISH_RECIPES" in globals() else {}
        embed.add_field(name="🍲 Packed ration", value=f"{dish.get('name', 'Meal')} — bonus applies to your next encounter.", inline=False)
    await interaction.response.defer(thinking=True)
    await bd_save_data()
    await interaction.edit_original_response(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@adventure_group.command(name="map", description="View all Wildlands areas and unlock conditions")
@app_commands.guild_only()
async def wildlands_map(interaction: discord.Interaction):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    unlocked = _wildlands_unlocked(interaction.guild.id, interaction.user.id, rec)
    conditions = {
        "whispering_woods": "Starting area",
        "quiet_shore": "Complete 2 expeditions",
        "stoneback_highlands": "Craft Sturdy Trail Boots",
        "moonlit_marsh": "Craft a Trail Lantern and discover 2 clues",
        "frostfall_pass": "Craft a Warm Explorer's Cloak",
        "forgotten_ruins": "Reach Wildlands Level 6, find 5 clues, craft the Ancient Star Map and build a Research Table",
    }
    rows = []
    for zid, zone in WILDLANDS_ZONES.items():
        mark = "🟢" if zid in unlocked else "🔒"
        suffix = "**UNLOCKED**" if zid in unlocked else f"Unlock: {conditions[zid]}"
        current = " · **YOU ARE HERE**" if rec.get("location") == zid else ""
        rows.append(f"{mark} {zone['emoji']} **{zone['name']}**{current}\n_{zone['description']}_\n{suffix}")
    embed = cinnamon_embed("🗺️ The Wildlands Map", "\n\n".join(rows), color=CINNAMON_ORANGE, user=interaction.user, footer="Travel with `/adventure travel`")
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def wildlands_zone_autocomplete(interaction: discord.Interaction, current: str):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    unlocked = _wildlands_unlocked(interaction.guild.id, interaction.user.id, rec)
    current = (current or "").lower().strip()
    choices = []
    for zid, zone in WILDLANDS_ZONES.items():
        if zid in unlocked and (current in zid.lower() or current in zone["name"].lower()):
            choices.append(app_commands.Choice(name=f"{zone['emoji']} {zone['name']}", value=zid))
    return choices[:25]


@adventure_group.command(name="travel", description="Travel to an area you've unlocked")
@app_commands.guild_only()
@app_commands.describe(area="Choose an unlocked Wildlands area")
async def wildlands_travel(interaction: discord.Interaction, area: str):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    unlocked = _wildlands_unlocked(interaction.guild.id, interaction.user.id, rec)
    area = area.lower().strip()
    if area not in WILDLANDS_ZONES or area not in unlocked:
        await interaction.response.send_message(embed=cinnamon_embed("🔒 Area not unlocked", "Check `/adventure map` for the requirements. Your progress is saved; no supplies were lost.", color=CINNAMON_ORANGE, user=interaction.user), ephemeral=True)
        return
    if rec.get("pending_encounter"):
        await interaction.response.send_message("Finish your current encounter first. Run `/adventure explore` to reopen its choices.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    previous = rec.get("location", "whispering_woods")
    rec["location"] = area
    rec.setdefault("stats", {})["routes_travelled"] = int(rec["stats"].get("routes_travelled", 0)) + (previous != area)
    seen_zones = rec.setdefault("visited_zones", [])
    first_visit = area not in seen_zones
    if first_visit:
        seen_zones.append(area)
        try:
            await achievement_record(interaction.guild.id, interaction.user.id, "wildlands_zone", 1, zone=area)
            await quest_event(interaction.guild.id, interaction.user.id, "wildlands_zone", 1)
        except Exception:
            log.exception("Could not update Wildlands zone progress")
    await bd_save_data()
    zone = WILDLANDS_ZONES[area]
    await interaction.edit_original_response(embed=cinnamon_embed(f"🧭 Arrived at {zone['name']}", f"{zone['emoji']} {zone['description']}\n\nThe scenery changes, so the resource mix and encounters change too. Use `/adventure explore` to look around.", color=CINNAMON_GREEN, user=interaction.user, footer="Wildlands • Choose your next path"), allowed_mentions=discord.AllowedMentions.none())
wildlands_travel.autocomplete("area")(wildlands_zone_autocomplete)


@adventure_group.command(name="explore", description="Start or resume a choice-driven expedition")
@app_commands.guild_only()
async def wildlands_explore(interaction: discord.Interaction):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    if not rec.get("started"):
        await interaction.response.send_message("Start your adventure first with `/adventure start` so Cinnamon can give you your starter supplies.", ephemeral=True)
        return
    _wildlands_energy(rec)
    _wildlands_unlocked(interaction.guild.id, interaction.user.id, rec)
    if rec.get("pending_encounter"):
        await _wildlands_send_pending(interaction, rec)
        return
    zone_id = rec.get("location", "whispering_woods")
    if zone_id not in WILDLANDS_ZONES:
        zone_id = "whispering_woods"
    zone = WILDLANDS_ZONES[zone_id]
    cost = WILDLANDS_EXPLORE_COST - (2 if "sturdy_boots" in rec.get("gear", []) else 0)
    cost = max(5, cost)
    if int(rec.get("energy", 0)) < cost:
        missing = cost - int(rec.get("energy", 0))
        mins = max(1, missing * WILDLANDS_ENERGY_REGEN_SECONDS // 60)
        await interaction.response.send_message(embed=cinnamon_embed("😴 Cinnamon says: paws up, explorer", f"You need **{cost} energy** to explore, but have **{rec['energy']}**. Energy regenerates automatically; check back in about **{mins} minute(s)**. Nothing is lost.", color=CINNAMON_ORANGE, user=interaction.user), ephemeral=True)
        await bd_save_data()
        return
    await interaction.response.defer(thinking=True)
    rec["energy"] = int(rec["energy"]) - cost
    rec["energy_at"] = time.time()
    encounter_id, encounter = random.choice(list(enumerate(zone["encounters"])))
    title, story = encounter
    rec["pending_encounter"] = {
        "zone": zone_id, "encounter_id": encounter_id, "title": title, "story": story,
        "cost": cost, "created_at": time.time(), "clues_before": list(rec.get("clues", [])),
        "discoveries_before": list(rec.get("discoveries", [])),
    }
    await bd_save_data()
    await interaction.edit_original_response(embed=_wildlands_pending_embed(interaction.user, rec), view=WildlandsEncounterView(interaction.guild.id, interaction.user.id), allowed_mentions=discord.AllowedMentions.none())


@adventure_group.command(name="inventory", description="View your gathered materials, gear and shared fish/food")
@app_commands.guild_only()
async def wildlands_inventory(interaction: discord.Interaction):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    mats = rec.get("materials", {})
    mat_rows = [f"{WILDLANDS_RESOURCES[k]['emoji']} **{WILDLANDS_RESOURCES[k]['name']} ×{int(v)}**" for k, v in sorted(mats.items(), key=lambda pair: WILDLANDS_RESOURCES[pair[0]]["name"]) if int(v) > 0]
    inv = economy_inventory_for(interaction.guild.id, interaction.user.id)
    fish_rows = []
    if "FISH_SPECIES" in globals():
        for fid, qty in inv.items():
            if fid in FISH_SPECIES and int(qty) > 0:
                fish_rows.append(f"{FISH_SPECIES[fid]['emoji']} {FISH_SPECIES[fid]['name']} ×{int(qty)}")
    dish_rows = []
    if "DISH_RECIPES" in globals():
        for did, qty in inv.items():
            if did in DISH_RECIPES and int(qty) > 0:
                dish_rows.append(f"{DISH_RECIPES[did]['emoji']} {DISH_RECIPES[did]['name']} ×{int(qty)}")
    embed = cinnamon_embed("🎒 Wildlands Pack", f"**Materials:** {_wildlands_material_total(rec)}/{_wildlands_capacity(rec)}", color=CINNAMON_ORANGE, user=interaction.user, footer="Shared Catnip inventory remains separate from gathered materials")
    embed.add_field(name="🌿 Gathered materials", value="\n".join(mat_rows[:18]) or "No materials yet. Start with `/adventure explore`.", inline=True)
    gear_rows = [f"{WILDLANDS_RECIPES[g]['emoji']} {WILDLANDS_RECIPES[g]['name']}" for g in rec.get("gear", []) if g in WILDLANDS_RECIPES]
    embed.add_field(name="🧰 Gear (always active)", value="\n".join(gear_rows) or "No gear crafted yet.", inline=True)
    embed.add_field(name="🎣 Fish from Cinnamon's shared inventory", value="\n".join(fish_rows[:8]) or "No fish in your shared inventory.", inline=False)
    embed.add_field(name="🍲 Cooked dishes (pack one for a bonus)", value="\n".join(dish_rows[:8]) or "No cooked dishes yet. See `/cookbook` and `/cook make`.", inline=False)
    if rec.get("prepared_ration"):
        d = DISH_RECIPES.get(str(rec["prepared_ration"].get("dish", "")), {}) if "DISH_RECIPES" in globals() else {}
        embed.add_field(name="🥡 Packed for your next expedition", value=d.get("name", "Meal"), inline=False)
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@adventure_group.command(name="recipes", description="Browse gear blueprints and their material costs")
@app_commands.guild_only()
async def wildlands_recipes(interaction: discord.Interaction):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    lines = [_wildlands_recipe_line(rid, recipe, rec) for rid, recipe in WILDLANDS_RECIPES.items()]
    embed = cinnamon_embed("🧰 Wildlands Blueprints", "\n\n".join(lines), color=CINNAMON_ORANGE, user=interaction.user, footer="Crafted gear stays active; no equipment micromanagement")
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def wildlands_recipe_autocomplete(interaction: discord.Interaction, current: str):
    current = (current or "").lower().strip()
    return [app_commands.Choice(name=f"{r['emoji']} {r['name']}", value=rid) for rid, r in WILDLANDS_RECIPES.items() if current in rid.lower() or current in r["name"].lower()][:25]


@adventure_group.command(name="craft", description="Craft a permanent piece of exploration gear")
@app_commands.guild_only()
@app_commands.describe(recipe="Choose a blueprint by name")
async def wildlands_craft(interaction: discord.Interaction, recipe: str):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    recipe_id = recipe.lower().strip()
    if recipe_id not in WILDLANDS_RECIPES:
        await interaction.response.send_message("I couldn't find that blueprint. Use `/adventure recipes` to browse them.", ephemeral=True)
        return
    data = WILDLANDS_RECIPES[recipe_id]
    if recipe_id in rec.get("gear", []):
        await interaction.response.send_message(f"You've already crafted **{data['name']}**. Its effect is always active.", ephemeral=True)
        return
    if data.get("requires_camp") and data["requires_camp"] not in rec.get("camp_upgrades", []):
        await interaction.response.send_message(f"🔒 This blueprint needs the **{WILDLANDS_CAMP_UPGRADES[data['requires_camp']]['name']}** first. Use `/adventure camp` to review upgrades.", ephemeral=True)
        return
    missing = []
    for mid, need in data["needs"].items():
        have = int(rec.get("materials", {}).get(mid, 0))
        if have < int(need):
            item = WILDLANDS_RESOURCES[mid]
            missing.append(f"{item['emoji']} {item['name']}: need **{need}**, have **{have}**")
    if missing:
        await interaction.response.send_message(embed=cinnamon_embed("🧰 Missing materials", f"To craft **{data['name']}**, gather:\n" + "\n".join(missing) + "\n\nMaterials are found in different areas. Use `/adventure map` to see routes.", color=CINNAMON_ORANGE, user=interaction.user), ephemeral=True)
        return
    before_unlocked = set(rec.get("unlocked_zones", ["whispering_woods"]))
    await interaction.response.defer(thinking=True)
    for mid, need in data["needs"].items():
        rec["materials"][mid] = int(rec["materials"].get(mid, 0)) - int(need)
        if rec["materials"][mid] <= 0:
            rec["materials"].pop(mid, None)
    rec.setdefault("gear", []).append(recipe_id)
    rec["crafted"] = int(rec.get("crafted", 0)) + 1
    _wildlands_add_xp(rec, 25)
    unlocked = _wildlands_unlocked(interaction.guild.id, interaction.user.id, rec)
    unlocks = _wildlands_unlock_messages(before_unlocked, unlocked)
    try:
        await achievement_record(interaction.guild.id, interaction.user.id, "wildlands_craft", 1)
        await quest_event(interaction.guild.id, interaction.user.id, "wildlands_craft", 1)
    except Exception:
        log.exception("Could not update Wildlands crafting progress")
    await bd_save_data()
    msg = f"You crafted **{data['emoji']} {data['name']}**!\n\n**Effect:** {data['effect']}\n\nThe gear is now active permanently."
    if unlocks:
        msg += "\n\n" + "\n".join(unlocks)
    embed = cinnamon_embed("🔨 Gear crafted!", msg, color=CINNAMON_GREEN, user=interaction.user, footer="Wildlands Crafting • Your next path just opened")
    await interaction.edit_original_response(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    await _wildlands_reward_milestone(interaction.guild.id, interaction.user.id, f"crafted_{recipe_id}")
wildlands_craft.autocomplete("recipe")(wildlands_recipe_autocomplete)


async def wildlands_camp_autocomplete(interaction: discord.Interaction, current: str):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    current = (current or "").lower().strip()
    return [app_commands.Choice(name=f"{u['emoji']} {u['name']} · {u['catnip']:,} Catnip", value=uid) for uid, u in WILDLANDS_CAMP_UPGRADES.items() if uid not in rec.get("camp_upgrades", []) and (current in uid.lower() or current in u["name"].lower())][:25]


@adventure_group.command(name="camp", description="Upgrade your camp with materials and Catnip")
@app_commands.guild_only()
@app_commands.describe(upgrade="Choose a camp upgrade")
async def wildlands_camp(interaction: discord.Interaction, upgrade: str = ""):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    upgrade_id = upgrade.lower().strip()
    if upgrade_id not in WILDLANDS_CAMP_UPGRADES:
        embed = cinnamon_embed("🏕️ Camp Upgrades", "\n\n".join(_wildlands_camp_line(uid, item, rec) for uid, item in WILDLANDS_CAMP_UPGRADES.items()), color=CINNAMON_ORANGE, user=interaction.user, footer="Catnip + materials • Pick an upgrade by name")
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        return
    if upgrade_id in rec.get("camp_upgrades", []):
        await interaction.response.send_message("That camp upgrade is already built.", ephemeral=True)
        return
    data = WILDLANDS_CAMP_UPGRADES[upgrade_id]
    missing = []
    for mid, need in data["needs"].items():
        have = int(rec.get("materials", {}).get(mid, 0))
        if have < int(need):
            item = WILDLANDS_RESOURCES[mid]
            missing.append(f"{item['emoji']} {item['name']}: need {need}, have {have}")
    balance = economy_balance(interaction.guild.id, interaction.user.id)
    if balance < int(data["catnip"]):
        missing.append(f"🌿 Catnip: need {data['catnip']:,}, have {balance:,}")
    if missing:
        await interaction.response.send_message(embed=cinnamon_embed("🏕️ Your camp needs more supplies", "\n".join(missing) + "\n\nNo items or Catnip were deducted.", color=CINNAMON_ORANGE, user=interaction.user), ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    for mid, need in data["needs"].items():
        rec["materials"][mid] = int(rec["materials"].get(mid, 0)) - int(need)
        if rec["materials"][mid] <= 0:
            rec["materials"].pop(mid, None)
    economy_balances[(interaction.guild.id, interaction.user.id)] = balance - int(data["catnip"])
    rec.setdefault("camp_upgrades", []).append(upgrade_id)
    _wildlands_add_xp(rec, 20)
    await achievement_record(interaction.guild.id, interaction.user.id, "purchase", 0, spent=int(data["catnip"]))
    await achievement_record(interaction.guild.id, interaction.user.id, "wildlands_camp_upgrade", 1)
    await achievement_record(interaction.guild.id, interaction.user.id, "balance")
    try:
        await quest_event(interaction.guild.id, interaction.user.id, "spent", int(data["catnip"]), spent=int(data["catnip"]))
        await quest_event(interaction.guild.id, interaction.user.id, "wildlands_camp_upgrade", 1)
        await quest_event(interaction.guild.id, interaction.user.id, "balance", balance - int(data["catnip"]))
    except Exception:
        pass
    await bd_save_data()
    embed = cinnamon_embed(f"🏕️ {data['name']} built!", f"Your camp has a new upgrade.\n\n{data['desc']}\n\nPaid: **{data['catnip']:,} Catnip** + materials.\nNew pack capacity: **{_wildlands_capacity(rec)}** materials.", color=CINNAMON_GREEN, user=interaction.user, footer="Wildlands Camp • A better base for future expeditions")
    await interaction.edit_original_response(embed=embed, allowed_mentions=discord.AllowedMentions.none())
wildlands_camp.autocomplete("upgrade")(wildlands_camp_autocomplete)


async def wildlands_dish_autocomplete(interaction: discord.Interaction, current: str):
    inv = economy_inventory_for(interaction.guild.id, interaction.user.id)
    current = (current or "").lower().strip()
    dishes = globals().get("DISH_RECIPES", {})
    choices = []
    for dish_id, qty in inv.items():
        if int(qty) <= 0 or dish_id not in dishes:
            continue
        dish = dishes[dish_id]
        if current in dish_id.lower() or current in dish["name"].lower():
            choices.append(app_commands.Choice(name=f"{dish['emoji']} {dish['name']} ×{qty}", value=dish_id))
    return choices[:25]


@adventure_group.command(name="pack", description="Pack one cooked dish from your shared inventory for an expedition bonus")
@app_commands.guild_only()
@app_commands.describe(dish="Choose a cooked dish you own; it will be consumed on your next expedition")
async def wildlands_pack(interaction: discord.Interaction, dish: str):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    if rec.get("pending_encounter"):
        await interaction.response.send_message("Finish your current encounter before packing another ration.", ephemeral=True)
        return
    if rec.get("prepared_ration"):
        old = rec["prepared_ration"]
        old_dish = DISH_RECIPES.get(str(old.get("dish", "")), {}) if "DISH_RECIPES" in globals() else {}
        await interaction.response.send_message(f"You already packed **{old_dish.get('name', 'a meal')}**. It will be used on your next encounter.", ephemeral=True)
        return
    dishes = globals().get("DISH_RECIPES", {})
    dish_id = dish.lower().strip()
    if dish_id not in dishes:
        await interaction.response.send_message("Choose a cooked dish from your inventory. See `/cook inventory`.", ephemeral=True)
        return
    inv = economy_inventory_for(interaction.guild.id, interaction.user.id)
    owned = int(inv.get(dish_id, 0))
    if owned < 1:
        await interaction.response.send_message("You don't have that dish in your shared Cinnamon inventory.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    inv[dish_id] = owned - 1
    if inv[dish_id] <= 0:
        inv.pop(dish_id, None)
    d = dishes[dish_id]
    rec["prepared_ration"] = {"dish": dish_id, "name": d["name"], "level": int(d.get("level", 1)), "packed_at": time.time()}
    await bd_save_data()
    bonus, _ = _wildlands_ration_bonus(rec)
    embed = cinnamon_embed("🥡 Ration packed", f"Packed **{d['emoji']} {d['name']}** from your shared inventory. It will be used on your next encounter and adds about **+{int(bonus * 100)}% rare-find chance**.\n\nThe dish has been consumed from inventory now, so it cannot be sold or used twice.", color=CINNAMON_GREEN, user=interaction.user, footer="Wildlands Preparation • Cooking has an adventure purpose")
    await interaction.edit_original_response(embed=embed, allowed_mentions=discord.AllowedMentions.none())
wildlands_pack.autocomplete("dish")(wildlands_dish_autocomplete)


async def wildlands_material_autocomplete(interaction: discord.Interaction, current: str):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    current = (current or "").lower().strip()
    choices = []
    for mid, qty in rec.get("materials", {}).items():
        if int(qty) > 0 and mid in WILDLANDS_RESOURCES:
            item = WILDLANDS_RESOURCES[mid]
            if current in mid.lower() or current in item["name"].lower():
                choices.append(app_commands.Choice(name=f"{item['emoji']} {item['name']} ×{qty}", value=mid))
    return choices[:25]


@adventure_group.command(name="sell", description="Trade gathered materials for a small amount of Catnip")
@app_commands.guild_only()
@app_commands.describe(material="Choose a material you own", amount="How many to trade")
async def wildlands_sell(interaction: discord.Interaction, material: str, amount: app_commands.Range[int, 1, 100] = 1):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    material_id = material.lower().strip()
    if material_id not in WILDLANDS_RESOURCES:
        await interaction.response.send_message("Choose a gathered material from `/adventure inventory`.", ephemeral=True)
        return
    owned = int(rec.get("materials", {}).get(material_id, 0))
    amount = int(amount)
    if owned < amount:
        await interaction.response.send_message(f"You own **{owned}×** {WILDLANDS_RESOURCES[material_id]['name']}, not {amount}.", ephemeral=True)
        return
    item = WILDLANDS_RESOURCES[material_id]
    await interaction.response.defer(thinking=True)
    value = int(item["sell"]) * amount
    rec["materials"][material_id] = owned - amount
    if rec["materials"][material_id] <= 0:
        rec["materials"].pop(material_id, None)
    before = economy_balance(interaction.guild.id, interaction.user.id)
    economy_balances[(interaction.guild.id, interaction.user.id)] = before + value
    await achievement_record(interaction.guild.id, interaction.user.id, "catnip_earned", value)
    await achievement_record(interaction.guild.id, interaction.user.id, "balance")
    await quest_event(interaction.guild.id, interaction.user.id, "balance", before + value)
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🌿 Wildlands material traded", fields=[("User", f"{interaction.user} ({interaction.user.id})"), ("Material", f"{item['name']} ×{amount}"), ("Catnip", f"+{value:,}"), ("Balance", f"{before:,} → {before + value:,}")])
    embed = cinnamon_embed("💰 Materials traded", f"Traded **{item['emoji']} {item['name']} ×{amount}** for **{value:,} Catnip**.\n\nWallet: **{before + value:,} Catnip**\nPack space freed: **{amount}**.", color=CINNAMON_GREEN, user=interaction.user, footer="Wildlands Trading • Rare materials are usually more useful for crafting")
    await interaction.edit_original_response(embed=embed, allowed_mentions=discord.AllowedMentions.none())
wildlands_sell.autocomplete("material")(wildlands_material_autocomplete)


@adventure_group.command(name="journal", description="Review your clues, secret discoveries and server-first finds")
@app_commands.guild_only()
async def wildlands_journal(interaction: discord.Interaction):
    rec = _wildlands_player(interaction.guild.id, interaction.user.id)
    clues = rec.get("clues", [])
    discoveries = rec.get("discoveries", [])
    clue_lines = [f"📜 **{WILDLANDS_CLUES[c]['name']}** — {WILDLANDS_CLUES[c]['text']}" for c in clues if c in WILDLANDS_CLUES]
    secret_lines = []
    for sid in discoveries:
        if sid in WILDLANDS_SECRETS:
            s = WILDLANDS_SECRETS[sid]
            tag = " · 🏆 Server first" if sid in rec.get("firsts", []) else ""
            secret_lines.append(f"{s['emoji']} **{s['name']}**{tag} — {s['text']}")
    gdata = _wildlands_root()["guilds"].get(str(interaction.guild.id), {})
    firsts = gdata.get("first_discoveries", {})
    total_firsts = len(rec.get("firsts", []))
    embed = cinnamon_embed("📖 Wildlands Discovery Journal", f"**Personal progress:** {len(discoveries)}/{len(WILDLANDS_SECRETS)} secret places · {len(clues)}/{len(WILDLANDS_CLUES)} clues\n**Server history:** {len(firsts)}/{len(WILDLANDS_SECRETS)} unique places first recorded\n**Your server-first finds:** {total_firsts}", color=CINNAMON_ORANGE, user=interaction.user, footer="Wildlands • Every clue moves the story forward")
    embed.add_field(name="📜 Collected clues", value="\n\n".join(clue_lines[:8]) or "No clues yet. Try **Investigate** or **Follow tracks** during an expedition.", inline=False)
    embed.add_field(name="✨ Secret places", value="\n\n".join(secret_lines[:8]) or "No secret places discovered yet. Some are very rare.", inline=False)
    if len(clue_lines) > 8 or len(secret_lines) > 8:
        embed.set_footer(text="Use this journal again as you explore; it shows your latest discoveries.")
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@adventure_group.command(name="leaderboard", description="Compare Wildlands progress with other explorers in this server")
@app_commands.guild_only()
async def wildlands_leaderboard(interaction: discord.Interaction):
    prefix = f"{interaction.guild.id}:"
    players = _wildlands_root()["players"]
    rows = []
    for key, rec in players.items():
        if not str(key).startswith(prefix):
            continue
        try:
            uid = int(str(key).split(":", 1)[1])
        except (ValueError, IndexError):
            continue
        rows.append((uid, rec))
    rows.sort(key=lambda pair: (len(pair[1].get("discoveries", [])), len(pair[1].get("clues", [])), int(pair[1].get("level", 1)), int(pair[1].get("explores", 0))), reverse=True)
    lines = []
    for rank, (uid, rec) in enumerate(rows[:10], 1):
        member = interaction.guild.get_member(uid)
        label = member.display_name if member else f"Explorer {str(uid)[-4:]}"
        lines.append(f"**{rank}.** {label} — ✨ {len(rec.get('discoveries', []))} secrets · 📜 {len(rec.get('clues', []))} clues · Level {int(rec.get('level', 1))}")
    if not lines:
        lines = ["No explorers yet. Use `/adventure start` to begin!"]
    gdata = _wildlands_root()["guilds"].get(str(interaction.guild.id), {})
    embed = cinnamon_embed("🏆 Wildlands Explorers", "\n".join(lines) + f"\n\n**Server-first discoveries:** {len(gdata.get('first_discoveries', {}))}/{len(WILDLANDS_SECRETS)}", color=CINNAMON_ORANGE, user=interaction.user, footer="Discovery first, grind second")
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def wildlands_help(interaction: discord.Interaction):
    text = (
        "**Your first few steps**\n"
        "1. `/adventure start` — receive starter supplies.\n"
        "2. `/adventure play` — open the button-driven hub for exploration, map, inventory, and journal.\n"
        "3. `/adventure craft` and `/adventure camp` — make permanent gear and improve your base.\n"
        "4. `/adventure pack` — bring a cooked dish from Cinnamon's existing cooking system.\n"
        "5. `/adventure map` and `/adventure travel` — unlock and visit new areas.\n\n"
        "**Connects with Cinnamon**\n"
        "• `/fish catch` builds your shared fish collection; `/cook make` turns catches into dishes.\n"
        "• `/adventure pack` consumes one cooked dish from the shared inventory for a rare-find bonus on your next expedition.\n"
        "• Catnip buys camp upgrades; extra materials can be traded back for modest Catnip.\n"
        "• Clues and secret places are recorded in your journal; the server remembers first discoveries.\n\n"
        "Energy restores 1 point every 2 minutes. If you leave a choice unfinished, `/adventure explore` reopens it without charging energy again. You do not lose gathered supplies when an encounter goes badly."
    )
    await interaction.response.send_message(embed=cinnamon_embed("🐾 Wildlands Field Guide", text, color=CINNAMON_ORANGE, user=interaction.user, footer="Cinnamon Wildlands • Built for short sessions and long mysteries"), ephemeral=True)


@adventure_group.command(name="help", description="Read the Wildlands quick-start guide")
@app_commands.guild_only()
async def wildlands_help_command(interaction: discord.Interaction):
    await wildlands_help(interaction)


bot.tree.add_command(adventure_group)
