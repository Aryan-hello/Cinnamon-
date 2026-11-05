"""Cinnamon's expansion systems: mystery boxes, crafting, Black Market and richer leaderboards."""

# This module is executed in main.py's shared namespace, after economy.py and
# the existing achievement/quest systems.  It intentionally reuses Cinnamon's
# existing Catnip and inventory instead of creating a second economy.

ADVANCED_FEATURES = globals().setdefault("advanced_features_data", {})
ADVANCED_FEATURES.setdefault("mystery_boxes", {})
ADVANCED_FEATURES.setdefault("crafted_counts", {})
ADVANCED_FEATURES.setdefault("mystery_opened", {})
ADVANCED_FEATURES.setdefault("black_market_purchases", {})

CRAFTING_ITEMS = {
    "moon_fish_scale": {"name": "Moonfish Scale", "price": 900, "emoji": "🌙", "description": "A shimmering scale found in very suspicious fish markets.", "max_per_person": 0, "shop_enabled": False},
    "golden_thread": {"name": "Golden Thread", "price": 1200, "emoji": "🧵", "description": "Ridiculously shiny thread. Cinnamon refuses to explain where it came from.", "max_per_person": 0, "shop_enabled": False},
    "star_dust": {"name": "Star Dust", "price": 1800, "emoji": "✨", "description": "Sparkly crafting dust with questionable cosmic origins.", "max_per_person": 0, "shop_enabled": False},
    "golden_fish": {"name": "Golden Fish", "price": 5000, "emoji": "🐠", "description": "A rare golden fish used in advanced recipes.", "max_per_person": 0, "shop_enabled": False},
    "fish_biscuits": {"name": "Fish Biscuits", "price": 3500, "emoji": "🍪", "description": "Crunchy handcrafted biscuits made for elite cats.", "max_per_person": 0, "shop_enabled": False},
    "cosmic_churu": {"name": "Cosmic Churu", "price": 6500, "emoji": "🥫", "description": "A suspiciously sparkly premium Churu.", "max_per_person": 0, "shop_enabled": False},
    "catnip_crown": {"name": "Catnip Crown", "price": 12000, "emoji": "👑", "description": "The unofficial crown of Cinnamon's economy elite.", "max_per_person": 1, "shop_enabled": False},
    "royal_tuna": {"name": "Royal Tuna", "price": 18000, "emoji": "🐟", "description": "Tuna fit for a cat who thinks she owns the server.", "max_per_person": 0, "shop_enabled": False},
}
for _item_id, _item in CRAFTING_ITEMS.items():
    ECONOMY_ITEMS.setdefault(_item_id, dict(_item))

CRAFTING_RECIPES = {
    "fish_biscuits": {
        "name": "Fish Biscuits",
        "emoji": "🍪",
        "output": "fish_biscuits",
        "ingredients": {"tuna": 2, "treat": 1},
        "description": "Turn ordinary snacks into fancy homemade biscuits.",
    },
    "cosmic_churu": {
        "name": "Cosmic Churu",
        "emoji": "🥫",
        "output": "cosmic_churu",
        "ingredients": {"churu": 2, "moon_fish_scale": 1, "star_dust": 1},
        "description": "A premium Churu infused with suspicious cosmic sparkle.",
    },
    "catnip_crown": {
        "name": "Catnip Crown",
        "emoji": "👑",
        "output": "catnip_crown",
        "ingredients": {"catnip_ball": 2, "golden_thread": 2, "star_dust": 1},
        "description": "Craft Cinnamon's unofficial symbol of economic dominance.",
    },
    "royal_tuna": {
        "name": "Royal Tuna",
        "emoji": "🐟",
        "output": "royal_tuna",
        "ingredients": {"tuna": 3, "golden_fish": 1, "golden_thread": 1},
        "description": "Only the fanciest tuna survives this recipe.",
    },
}

BLACK_MARKET_POOL = [
    "tuna", "treat", "churu", "catnip_ball", "fish",
    "moon_fish_scale", "golden_thread", "star_dust", "golden_fish",
    "fish_biscuits", "cosmic_churu", "catnip_crown", "royal_tuna",
]

MYSTERY_REWARDS = [
    (29, "catnip_small"),
    (28, "item_common"),
    (14, "xp"),
    (12, "material"),
    (9, "catnip_big"),
    (6, "item_rare"),
    (2, "rare_crown"),
]

_mystery_roll_cooldowns = {}


def _af_key(guild_id, user_id):
    return f"{int(guild_id)}:{int(user_id)}"


BOX_TIERS = {
    "common": {"label":"Common", "emoji":"📦", "weight":70, "catnip":(250,900), "items":["treat","tuna","churu","catnip_ball","fish_biscuits"], "materials":["golden_thread","crystal_fishbone"]},
    "rare": {"label":"Rare", "emoji":"🎁", "weight":22, "catnip":(900,2400), "items":["golden_fish","royal_tuna","paw_treasure","golden_bell_collar"], "materials":["moon_fish_scale","star_dust","golden_paw_charm"]},
    "epic": {"label":"Epic", "emoji":"💜", "weight":7, "catnip":(2200,5500), "items":["starlight_hat","pawberry_cake","cinnamon_snow_globe"], "materials":["moonstone","dream_petals"]},
    "legendary": {"label":"Legendary", "emoji":"🌠", "weight":0.9, "catnip":(5000,10000), "items":["catnip_crown","dream_wings","moon_jelly"], "materials":["captured_star"]},
    "mythical": {"label":"Mythical", "emoji":"✨", "weight":0.1, "catnip":(10000,25000), "items":["captured_star","dream_wings"], "materials":["dream_petals","moonstone"]},
}
def _box_count(guild_id, user_id, tier="common"):
    raw=ADVANCED_FEATURES["mystery_boxes"].get(_af_key(guild_id,user_id),0)
    if isinstance(raw,dict): return max(0,int(raw.get(tier,0)))
    return max(0,int(raw)) if tier=="common" else 0

def _set_box_count(guild_id,user_id,count,tier="common"):
    key=_af_key(guild_id,user_id); raw=ADVANCED_FEATURES["mystery_boxes"].get(key,0)
    if not isinstance(raw,dict): raw={"common":max(0,int(raw))}
    raw=dict(raw); raw[tier]=max(0,int(count)); raw={k:v for k,v in raw.items() if v>0}
    if raw: ADVANCED_FEATURES["mystery_boxes"][key]=raw
    else: ADVANCED_FEATURES["mystery_boxes"].pop(key,None)


async def advanced_maybe_award_box(guild_id: int, user, source: str, chance: float = 0.08):
    """Award an earned mystery box from selected normal activities.

    Daily/work rewards use this directly; message activity has a much smaller
    separate chance below.  No real-money purchase or gambling is involved.
    """
    if random.random() > chance:
        return False
    _set_box_count(guild_id, user.id, _box_count(guild_id, user.id) + 1)
    await bd_save_data()
    await economy_log(guild_id, title="🎁 Mystery Box earned", fields=[
        ("User", f"{user} ({user.id})"), ("Source", source), ("Boxes", str(_box_count(guild_id, user.id)))
    ])
    return True


def _recipe_line(recipe_id, recipe):
    ingredients = []
    for item_id, qty in recipe["ingredients"].items():
        item = ECONOMY_ITEMS.get(item_id, {})
        ingredients.append(f"{item.get('emoji', '🐾')} {item.get('name', item_id)} ×{qty}")
    out = ECONOMY_ITEMS.get(recipe["output"], {})
    return f"{recipe['emoji']} **{recipe['name']}** — " + ", ".join(ingredients) + f" → {out.get('emoji','🐾')} **{out.get('name', recipe['output'])}**"


def _craft_embed(guild_id, user, recipe_id, quantity=1):
    recipe = CRAFTING_RECIPES[recipe_id]
    e = cinnamon_embed(f"{recipe['emoji']} {recipe['name']}", recipe["description"], color=CINNAMON_ORANGE, user=user, footer="Cinnamon Crafting")
    lines = []
    inv = economy_inventory_for(guild_id, user.id)
    for item_id, needed in recipe["ingredients"].items():
        item = ECONOMY_ITEMS[item_id]
        have = int(inv.get(item_id, 0))
        total = needed * quantity
        mark = "✅" if have >= total else "❌"
        lines.append(f"{mark} {item['emoji']} {item['name']}: **{have:,} / {total:,}**")
    cinnamon_field(e, "🧪 Ingredients", "\n".join(lines), False)
    output = ECONOMY_ITEMS[recipe["output"]]
    cinnamon_field(e, "📦 Output", f"{output['emoji']} **{output['name']} ×{quantity:,}**", True)
    return cinnamon_polish_embed(e)


async def craft_item(guild_id, user, recipe_id, quantity=1):
    recipe = CRAFTING_RECIPES.get(recipe_id)
    if not recipe:
        return False, "❌ I don't know that recipe. Use `/craft` to see the recipes."
    quantity = max(1, min(int(quantity), 25))
    inv = economy_inventory_for(guild_id, user.id)
    missing = []
    for item_id, needed in recipe["ingredients"].items():
        have = int(inv.get(item_id, 0))
        total = needed * quantity
        if have < total:
            item = ECONOMY_ITEMS[item_id]
            missing.append(f"{item['emoji']} {item['name']}: need **{total}**, have **{have}**")
    if missing:
        return False, "❌ Not enough ingredients:\n" + "\n".join(missing)
    output = ECONOMY_ITEMS[recipe["output"]]
    max_owned = int(output.get("max_per_person", 0))
    if max_owned and int(inv.get(recipe["output"], 0)) + quantity > max_owned:
        return False, f"❌ You can own at most **{max_owned}× {output['name']}**."
    for item_id, needed in recipe["ingredients"].items():
        inv[item_id] = int(inv.get(item_id, 0)) - needed * quantity
        if inv[item_id] <= 0:
            inv.pop(item_id, None)
    inv[recipe["output"]] = int(inv.get(recipe["output"], 0)) + quantity
    key = _af_key(guild_id, user.id)
    ADVANCED_FEATURES["crafted_counts"][key] = int(ADVANCED_FEATURES["crafted_counts"].get(key, 0)) + quantity
    await bd_save_data()
    await economy_log(guild_id, title="🔨 Item crafted", fields=[
        ("User", f"{user} ({user.id})"), ("Recipe", recipe["name"]), ("Quantity", str(quantity)), ("Output", f"{output['name']} ×{quantity}")
    ])
    return True, f"✅ Crafted **{quantity:,}× {output['emoji']} {output['name']}**!"


@bot.tree.command(name="craft", description="Craft an item from ingredients")
@app_commands.guild_only()
@app_commands.describe(recipe="Recipe to craft", quantity="Number of crafts (1-25)")
async def craft_cmd(interaction: discord.Interaction, recipe: str, quantity: app_commands.Range[int, 1, 25] = 1):
    recipe_id = recipe.lower().strip()
    if recipe_id not in CRAFTING_RECIPES:
        matches = [k for k, r in CRAFTING_RECIPES.items() if r["name"].lower() == recipe_id]
        if len(matches) == 1:
            recipe_id = matches[0]
    if recipe_id not in CRAFTING_RECIPES:
        await interaction.response.send_message(embed=cinnamon_embed("🔨 Crafting Recipes", "\n".join(_recipe_line(k, r) for k, r in CRAFTING_RECIPES.items()), color=CINNAMON_ORANGE, footer="Cinnamon Crafting"), allowed_mentions=discord.AllowedMentions.none())
        return
    ok, message = await craft_item(interaction.guild.id, interaction.user, recipe_id, quantity)
    await interaction.response.send_message(embed=cinnamon_embed("🔨 Crafting Complete" if ok else "🔨 Crafting", message, color=CINNAMON_GREEN if ok else CINNAMON_RED, user=interaction.user, footer="Cinnamon Crafting"), allowed_mentions=discord.AllowedMentions.none())


async def craft_autocomplete(interaction, current: str):
    current = current.lower().strip()
    return [app_commands.Choice(name=f"{r['emoji']} {r['name']}", value=k) for k, r in CRAFTING_RECIPES.items() if current in k.lower() or current in r['name'].lower()][:25]
craft_cmd.autocomplete("recipe")(craft_autocomplete)


@bot.command(name="craft")
@commands.guild_only()
async def prefix_craft(ctx, recipe: str = "", quantity: int = 1):
    if not recipe:
        return await ctx.reply("🔨 **Crafting Recipes**\n" + "\n".join(_recipe_line(k, r) for k, r in CRAFTING_RECIPES.items()), mention_author=False)
    rid = recipe.lower().strip()
    if rid not in CRAFTING_RECIPES:
        return await ctx.reply("❌ Unknown recipe. Use `?craft` to see recipes.", mention_author=False)
    ok, message = await craft_item(ctx.guild.id, ctx.author, rid, quantity)
    await ctx.reply(message, mention_author=False)


# ---------------------------------------------------------------------------
# Mystery Boxes
# ---------------------------------------------------------------------------

def _weighted_reward():
    roll = random.randint(1, 100)
    total = 0
    for weight, kind in MYSTERY_REWARDS:
        total += weight
        if roll <= total:
            return kind
    return "catnip_small"


async def _open_one(guild_id, user, tier="common"):
    inv=economy_inventory_for(guild_id,user.id)
    if tier != "common":
        cfg=BOX_TIERS[tier]
        roll=random.random()
        if roll < .55:
            amount=random.randint(*cfg["catnip"]); economy_balances[(guild_id,user.id)]=economy_balance(guild_id,user.id)+amount
            return f"🌿 **+{amount:,} Catnip**"
        if roll < .90:
            item_id=random.choice(cfg["items"]); item=ECONOMY_ITEMS[item_id]
            limit=int(item.get("max_per_person",0))
            if limit and int(inv.get(item_id,0))>=limit:
                amount=random.randint(500,1800); economy_balances[(guild_id,user.id)]=economy_balance(guild_id,user.id)+amount
                return f"🪙 Duplicate protection: **+{amount:,} Catnip** (already own {item['name']})"
            inv[item_id]=int(inv.get(item_id,0))+1
            return f"{item['emoji']} **1× {item['name']}**"
        item_id=random.choice(cfg["materials"]); inv[item_id]=int(inv.get(item_id,0))+1; item=ECONOMY_ITEMS[item_id]
        return f"🧪 **1× {item['name']}**"
    kind=_weighted_reward(); 
    if kind=="catnip_small":
        amount=random.randint(250,700); economy_balances[(guild_id,user.id)]=economy_balance(guild_id,user.id)+amount; return f"🌿 **+{amount:,} Catnip**"
    if kind=="catnip_big":
        amount=random.randint(1200,3000); economy_balances[(guild_id,user.id)]=economy_balance(guild_id,user.id)+amount; return f"💰 **+{amount:,} Catnip**"
    if kind=="xp":
        amount=random.randint(100,500); xp_data[(guild_id,user.id)]=int(xp_data.get((guild_id,user.id),0))+amount; return f"⭐ **+{amount:,} XP**"
    if kind=="item_common":
        item_id=random.choice(["treat","tuna","churu","catnip_ball","fish_biscuits"]); qty=random.randint(1,3); inv[item_id]=int(inv.get(item_id,0))+qty; item=ECONOMY_ITEMS[item_id]; return f"{item['emoji']} **{qty}× {item['name']}**"
    if kind=="item_rare":
        item_id=random.choice(["fish","golden_fish","moon_fish_scale"]); qty=random.randint(1,2); inv[item_id]=int(inv.get(item_id,0))+qty; item=ECONOMY_ITEMS[item_id]; return f"{item['emoji']} **{qty}× {item['name']}**"
    if kind=="material":
        item_id=random.choice(["moon_fish_scale","golden_thread","star_dust"]); qty=random.randint(1,2); inv[item_id]=int(inv.get(item_id,0))+qty; item=ECONOMY_ITEMS[item_id]; return f"{item['emoji']} **{qty}× {item['name']}**"
    if int(inv.get("catnip_crown",0))>=1:
        inv["golden_fish"]=int(inv.get("golden_fish",0))+1; return "🐠 **1× Golden Fish** — duplicate legendary converted."
    inv["catnip_crown"]=1; return "👑 **1× Catnip Crown** — legendary!"


@bot.tree.command(name="mystery", description="Open your earned Cinnamon Mystery Boxes")
@app_commands.guild_only()
@app_commands.describe(action="open or check", quantity="How many boxes to open")
@app_commands.choices(action=[app_commands.Choice(name="Open boxes", value="open"), app_commands.Choice(name="Check boxes", value="check")])
async def mystery_cmd(interaction: discord.Interaction, action: app_commands.Choice[str] | None = None, quantity: app_commands.Range[int, 1, 5] = 1):
    action_value = action.value if action else "check"
    count = _box_count(interaction.guild.id, interaction.user.id)
    if action_value == "check":
        e = cinnamon_embed("🎁 Mystery Boxes", f"You currently have **{count}** unopened Mystery Box(es).", color=CINNAMON_ORANGE, user=interaction.user, footer="Cinnamon Mystery Boxes")
        e.add_field(name="How to earn them", value="Daily rewards, work shifts, and normal server activity can occasionally award boxes.")
        await interaction.response.send_message(embed=cinnamon_polish_embed(e), ephemeral=True)
        return
    if count <= 0:
        await interaction.response.send_message("🎁 You don't have any Mystery Boxes yet. Keep using Cinnamon's normal systems to earn one!", ephemeral=True)
        return
    quantity = min(quantity, count)
    rewards = []
    for _ in range(quantity):
        rewards.append(await _open_one(interaction.guild.id, interaction.user))
    _set_box_count(interaction.guild.id, interaction.user.id, count - quantity)
    key = _af_key(interaction.guild.id, interaction.user.id)
    ADVANCED_FEATURES["mystery_opened"][key] = int(ADVANCED_FEATURES["mystery_opened"].get(key, 0)) + quantity
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🎁 Mystery Box opened", fields=[("User", f"{interaction.user} ({interaction.user.id})"), ("Opened", str(quantity)), ("Remaining", str(_box_count(interaction.guild.id, interaction.user.id)))])
    e = cinnamon_embed("🎁 Mystery Box Results", "Cinnamon shook the box very aggressively.\n\n" + "\n".join(f"• {r}" for r in rewards), color=CINNAMON_GOLD, user=interaction.user, footer="Cinnamon Mystery Boxes")
    e.add_field(name="Boxes remaining", value=f"**{_box_count(interaction.guild.id, interaction.user.id)}**")
    await interaction.response.send_message(embed=cinnamon_polish_embed(e), allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="mystery", aliases=["boxes", "box"])
@commands.guild_only()
async def prefix_mystery(ctx, action: str = "check", quantity: int = 1):
    count = _box_count(ctx.guild.id, ctx.author.id)
    if action.lower() != "open":
        return await ctx.reply(f"🎁 You have **{count}** Mystery Box(es). Use `?mystery open [quantity]` to open them.", mention_author=False)
    if count <= 0:
        return await ctx.reply("🎁 You don't have any Mystery Boxes yet.", mention_author=False)
    quantity = max(1, min(int(quantity), min(5, count)))
    rewards = [await _open_one(ctx.guild.id, ctx.author) for _ in range(quantity)]
    _set_box_count(ctx.guild.id, ctx.author.id, count - quantity)
    key = _af_key(ctx.guild.id, ctx.author.id); ADVANCED_FEATURES["mystery_opened"][key] = int(ADVANCED_FEATURES["mystery_opened"].get(key, 0)) + quantity
    await bd_save_data()
    await ctx.reply("🎁 **Mystery Box Results**\n" + "\n".join(f"• {r}" for r in rewards) + f"\n\nBoxes remaining: **{_box_count(ctx.guild.id, ctx.author.id)}**", mention_author=False)


# ---------------------------------------------------------------------------
# Black Market
# ---------------------------------------------------------------------------

def _market_date():
    return cinnamon_now().date().isoformat()


def _market(guild_id):
    date = _market_date()
    state = ADVANCED_FEATURES.setdefault("black_market", {})
    current = state.get(str(guild_id))
    if isinstance(current, dict) and current.get("date") == date and isinstance(current.get("stock"), dict):
        return current
    rng = random.Random(f"cinnamon-market:{guild_id}:{date}")
    pool = list(BLACK_MARKET_POOL); rng.shuffle(pool)
    selected = pool[:7]
    stock = {}
    for item_id in selected:
        base = max(100, int(ECONOMY_ITEMS[item_id].get("price", 1000)))
        multiplier = rng.choice([0.65, 0.8, 0.9, 1.1, 1.25, 1.5])
        stock[item_id] = {"quantity": rng.randint(1, 6), "price": max(100, int(base * multiplier))}
    current = {"date": date, "stock": stock}
    state[str(guild_id)] = current
    return current


class BlackMarketView(discord.ui.View):
    def __init__(self, guild_id, user_id):
        super().__init__(timeout=300); self.guild_id = guild_id; self.user_id = user_id
        market = _market(guild_id)
        options = []
        for item_id, listing in market["stock"].items():
            item = ECONOMY_ITEMS[item_id]
            options.append(discord.SelectOption(label=item["name"][:100], value=item_id, emoji=item.get("emoji", "🐾"), description=f"{listing['price']:,} Catnip • {listing['quantity']} in stock"))
        if options:
            select = discord.ui.Select(placeholder="Choose an item to buy", options=options, min_values=1, max_values=1)
            select.callback = self._buy
            self.add_item(select)
        close = discord.ui.Button(label="Close", emoji="✖️", style=discord.ButtonStyle.danger)
        close.callback = self._close; self.add_item(close)

    async def _guard(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("🐾 This Black Market panel belongs to the person who opened it.", ephemeral=True); return False
        return True

    async def _buy(self, interaction):
        if not await self._guard(interaction): return
        item_id = interaction.data["values"][0]
        market = _market(self.guild_id); listing = market["stock"].get(item_id)
        if not listing or int(listing.get("quantity", 0)) <= 0:
            await interaction.response.send_message("🕶️ That listing has sold out.", ephemeral=True); return
        price = int(listing["price"]); balance = economy_balance(self.guild_id, self.user_id)
        if balance < price:
            await interaction.response.send_message(f"🕶️ You need **{price:,} Catnip**, but you only have **{balance:,}**.", ephemeral=True); return
        item = ECONOMY_ITEMS[item_id]; inv = economy_inventory_for(self.guild_id, self.user_id)
        limit = int(item.get("max_per_person", 0))
        if limit and int(inv.get(item_id, 0)) + 1 > limit:
            await interaction.response.send_message(f"🕶️ You can only own **{limit}× {item['name']}**.", ephemeral=True); return
        economy_balances[(self.guild_id, self.user_id)] = balance - price
        inv[item_id] = int(inv.get(item_id, 0)) + 1
        listing["quantity"] = int(listing["quantity"]) - 1
        key = _af_key(self.guild_id, self.user_id); ADVANCED_FEATURES["black_market_purchases"][key] = int(ADVANCED_FEATURES["black_market_purchases"].get(key, 0)) + 1
        await bd_save_data(); await economy_log(self.guild_id, title="🕶️ Black Market purchase", fields=[("User", f"{interaction.user} ({self.user_id})"), ("Item", item["name"]), ("Price", f"{price:,} Catnip"), ("Stock left", str(listing["quantity"]))])
        await interaction.response.send_message(f"🕶️ Bought **1× {item['emoji']} {item['name']}** for **{price:,} Catnip**. Cinnamon saw nothing.", ephemeral=True)

    async def _close(self, interaction):
        if not await self._guard(interaction): return
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(view=self)


@bot.tree.command(name="black-market", description="Visit Cinnamon's rotating Black Market")
@app_commands.guild_only()
async def black_market_cmd(interaction: discord.Interaction):
    market = _market(interaction.guild.id)
    e = cinnamon_embed("🕶️ Cinnamon's Black Market", "A rotating market with limited stock. Listings change every day.", color=0x2F3136, user=interaction.user, footer=f"Black Market • {market['date']} • Daily rotation")
    lines=[]
    for item_id, listing in market["stock"].items():
        item=ECONOMY_ITEMS[item_id]; lines.append(f"{item['emoji']} **{item['name']}** — **{listing['price']:,} Catnip** · Stock **{listing['quantity']}**")
    e.add_field(name="Today's Listings", value="\n".join(lines) or "Sold out.", inline=False)
    await interaction.response.send_message(embed=cinnamon_polish_embed(e, footer="Cinnamon Black Market • Rotates daily"), view=BlackMarketView(interaction.guild.id, interaction.user.id), allowed_mentions=discord.AllowedMentions.none())


@bot.command(name="blackmarket", aliases=["black-market"])
@commands.guild_only()
async def prefix_black_market(ctx):
    market = _market(ctx.guild.id)
    lines=[]
    for item_id, listing in market["stock"].items():
        item=ECONOMY_ITEMS[item_id]; lines.append(f"{item['emoji']} **{item['name']}** — **{listing['price']:,} Catnip** · Stock **{listing['quantity']}**")
    await ctx.reply("🕶️ **Cinnamon's Black Market**\n" + "\n".join(lines) + "\n\nUse `/black-market` for the interactive purchase panel.", mention_author=False)


# Normal activity can very occasionally discover a box. This listener is kept
# deliberately rare so it doesn't spam users or create a huge economy faucet.
@bot.listen("on_message")
async def advanced_mystery_message_listener(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    key = (message.guild.id, message.author.id)
    now = time.time()
    if now - float(_mystery_roll_cooldowns.get(key, 0)) < 900:
        return
    _mystery_roll_cooldowns[key] = now
    if random.random() <= 0.03:
        _set_box_count(message.guild.id, message.author.id, _box_count(message.guild.id, message.author.id) + 1)
        await bd_save_data()
        try:
            await message.channel.send(f"🎁 {message.author.mention} found a **Mystery Box**! Use `/mystery` to check it.", allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            pass


# Missing work helper in older builds: define it here so both slash and prefix
# work commands use the same economy implementation.
WORK_MESSAGES = [
    "💼 You **organized Cinnamon's tuna paperwork** and earned **{amount:,} Catnip**.",
    "💼 You **guarded the sacred cat tree** and earned **{amount:,} Catnip**.",
    "💼 You **sorted Cinnamon's treat drawer** and earned **{amount:,} Catnip**.",
    "💼 You **answered Cinnamon's completely unnecessary emails** and earned **{amount:,} Catnip**.",
    "💼 You **polished the server's imaginary golden bowl** and earned **{amount:,} Catnip**.",
]

async def economy_do_work(guild_id: int, user):
    remaining = economy_cooldown_remaining(guild_id, user.id, "work")
    if remaining:
        return False, 0, f"⏳ Cinnamon already has you on shift. Come back in **{remaining // 60}m {remaining % 60}s**."
    amount = random.randint(ECONOMY_WORK_MIN, ECONOMY_WORK_MAX)
    economy_cooldowns[(guild_id, user.id, "work")] = time.time() + ECONOMY_WORK_COOLDOWN
    before = economy_balance(guild_id, user.id)
    economy_balances[(guild_id, user.id)] = before + amount
    try:
        s = achievement_stats(guild_id, user.id)
        s["work_sessions"] = int(s.get("work_sessions", 0)) + 1
        s["lifetime_catnip"] = int(s.get("lifetime_catnip", 0)) + amount
        await achievement_check_all(guild_id, user.id)
    except Exception:
        pass
    box = await advanced_maybe_award_box(guild_id, user, "work", chance=0.12)
    await bd_save_data()
    await economy_log(guild_id, title="💼 Work completed", fields=[("User", f"{user} ({user.id})"), ("Earned", f"+{amount:,} Catnip"), ("Balance", f"{before+amount:,}"), ("Mystery Box", "Yes" if box else "No")])
    message = random.choice(WORK_MESSAGES).format(amount=amount)
    if box:
        message += " 🎁 Cinnamon also found a Mystery Box in your paperwork."
    return True, amount, message
