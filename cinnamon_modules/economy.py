"""Cinnamon feature module.

Loaded by main.py into Cinnamon's shared runtime namespace. This is still
one Discord bot and one process; this file is not a separate bot.
Do not run this file directly.
"""

# Defined in this module because command decorators execute before advanced_economy.py loads.
# Grow a Garden service products: inventory items are consumed by ticket fulfillment.
GAG_SERVICE_ITEMS = {"gag_nightmare":{"name":"🎃 Nightmare Service","emoji":"🎃","price":1500,"description":"Put Nightmare mutation on your pet.","category":"grow_a_garden","shop_enabled":true,"max_per_person":0,"service_type":"grow_a_garden"},"gag_everchanted":{"name":"🔰 Everchanted Mutation (GAG1)","emoji":"🔰","price":2500,"description":"Get an EVERCHANTED Pet Mutation on one of your pets.","category":"grow_a_garden","shop_enabled":true,"max_per_person":0,"service_type":"grow_a_garden"},"gag_venom":{"name":"🐍 Venom Service","emoji":"🐍","price":2500,"description":"Put Venom mutation on 3 of your COOLDOWN pets. Non-cooldown pets cannot have Venom mutation.","category":"grow_a_garden","shop_enabled":true,"max_per_person":0,"service_type":"grow_a_garden"},"gag_hiero_venom":{"name":"🐍 HIERO VENOM","emoji":"🐍","price":3000,"description":"Get Hiero Venom on 1 of your pets.","category":"grow_a_garden","shop_enabled":true,"max_per_person":0,"service_type":"grow_a_garden"},"gag_haunted":{"name":"💀 HAUNTED","emoji":"💀","price":3500,"description":"Put the HAUNTED mutation on your pet!","category":"grow_a_garden","shop_enabled":true,"max_per_person":0,"service_type":"grow_a_garden"},"gag_age_500":{"name":"🌎 Age 500","emoji":"🌎","price":5000,"description":"Make your pet age 500.","category":"grow_a_garden","shop_enabled":true,"max_per_person":0,"service_type":"grow_a_garden"},"gag_39kg":{"name":"🐘 39kg Boost","emoji":"🐘","price":10000,"description":"Make your pet 39kg.","category":"grow_a_garden","shop_enabled":true,"max_per_person":0,"service_type":"grow_a_garden"},"gag_100_mutations":{"name":"🧬 100+ Mutations","emoji":"🧬","price":20000,"description":"Put 100+ mutations on 1 fruit in your garden.","category":"grow_a_garden","shop_enabled":true,"max_per_person":0,"service_type":"grow_a_garden"},"gag_ember":{"name":"❤️‍🔥 Ember Service","emoji":"❤️‍🔥","price":20000,"description":"Put the Ember mutation on your pet.","category":"grow_a_garden","shop_enabled":true,"max_per_person":0,"service_type":"grow_a_garden"}}
for _gag_id, _gag_item in GAG_SERVICE_ITEMS.items():
    ECONOMY_ITEMS.setdefault(_gag_id, dict(_gag_item))

BOX_TIERS = {
    "common": {"label":"Common", "emoji":"📦", "weight":70, "catnip":(250,900), "items":["treat","tuna","churu","catnip_ball","fish_biscuits"], "materials":["golden_thread","crystal_fishbone"]},
    "rare": {"label":"Rare", "emoji":"🎁", "weight":22, "catnip":(900,2400), "items":["golden_fish","royal_tuna","paw_treasure","golden_bell_collar"], "materials":["moon_fish_scale","star_dust","golden_paw_charm"]},
    "epic": {"label":"Epic", "emoji":"💜", "weight":7, "catnip":(2200,5500), "items":["starlight_hat","pawberry_cake","cinnamon_snow_globe"], "materials":["moonstone","dream_petals"]},
    "legendary": {"label":"Legendary", "emoji":"🌠", "weight":0.9, "catnip":(5000,10000), "items":["catnip_crown","dream_wings","moon_jelly"], "materials":["captured_star"]},
    "mythical": {"label":"Mythical", "emoji":"✨", "weight":0.1, "catnip":(10000,25000), "items":["captured_star","dream_wings"], "materials":["dream_petals","moonstone"]},
}




# ---------------------------------------------------------------------------
# Cinnamon embed design system
# Discord controls the actual font inside embeds; we improve hierarchy with
# spacing, short fields, thumbnails, timestamps, and a consistent palette.
# ---------------------------------------------------------------------------
CINNAMON_ORANGE = 0xE89A3C
CINNAMON_GOLD = 0xF2B84B
CINNAMON_GREEN = 0x7BC96F
CINNAMON_RED = 0xE57373
CINNAMON_BLUE = 0x6EA8FE
CINNAMON_MUTED = 0x8E9AAF

def cinnamon_embed(title: str, description: str = "", *, color=CINNAMON_ORANGE, user=None, footer="Cinnamon"):
    """Compatibility helper for the remaining classic embeds."""
    section = str(footer).split("•")[0].replace("Cinnamon", "").strip() or "Cinnamon"
    return cinnamon_ui_card(section, title, description, color=color, user=user, footer=footer)

def cinnamon_field(e, name, value, inline=False):
    e.add_field(name=name, value=str(value) if value else "—", inline=inline)
    return e

def economy_key(guild_id: int, user_id: int) -> tuple[int, int]:
    return guild_id, user_id


def economy_balance(guild_id: int, user_id: int) -> int:
    key = economy_key(guild_id, user_id)
    if key not in economy_balances:
        economy_balances[key] = ECONOMY_STARTING_BALANCE
    return int(economy_balances[key])


def economy_inventory_for(guild_id: int, user_id: int) -> dict:
    key = economy_key(guild_id, user_id)
    if key not in economy_inventory:
        economy_inventory[key] = {}
    return economy_inventory[key]








def economy_level_reward_claimed(guild_id: int, user_id: int, level: int) -> bool:
    """True if this member already received the Catnip reward for this level."""
    return int(level) in economy_level_rewards_claimed.get((int(guild_id), int(user_id)), [])


def mark_economy_level_reward_claimed(guild_id: int, user_id: int, level: int) -> None:
    claimed = economy_level_rewards_claimed.setdefault((int(guild_id), int(user_id)), [])
    if int(level) not in claimed:
        claimed.append(int(level))
        claimed.sort()


def economy_income_role_lines(guild) -> str:
    """Readable list of the server's Catnip income roles for /economy income list."""
    configs = economy_income_roles.get(guild.id, {})
    if not configs:
        return "No income roles are configured yet.\nUse `/economy add-role-income` to create one."
    lines = []
    for role_id, cfg in configs.items():
        role = guild.get_role(int(role_id))
        label = role.mention if role else f"Deleted role ({role_id})"
        seconds = int(cfg.get("cooldown", 3600))
        if seconds % 604800 == 0: every = f"{seconds // 604800} week(s)"
        elif seconds % 86400 == 0: every = f"{seconds // 86400} day(s)"
        elif seconds % 3600 == 0: every = f"{seconds // 3600} hour(s)"
        else: every = f"{max(1, seconds // 60)} minute(s)"
        lines.append(f"{label}: **{int(cfg.get('amount', 0)):,}** Catnip every **{every}**")
    return "\n".join(lines)


def economy_user_snapshot(guild_id: int, user_id: int) -> dict:
    return {
        "balance": economy_balance(guild_id, user_id),
        "inventory": dict(economy_inventory_for(guild_id, user_id)),
        # Quest progress now lives in quests.py (quest_data); store a JSON-safe copy.
        "quests": json.loads(json.dumps(sanitize_economy_quests(guild_id, user_id), default=str)),
        "achievements": list(economy_achievements.get((guild_id, user_id), [])),
        "level_rewards_claimed": list(economy_level_rewards_claimed.get((guild_id, user_id), [])),
    }


async def economy_log(guild_id: int, *, title: str, description: str = "", fields=None):
    # Persist transaction/event metadata even if no Discord log channel is configured.
    try:
        audit_meta = {str(k)[:48]: str(v)[:200] for k, v in (fields or [])[:20]
                      if str(k).lower() not in {"content", "message", "prompt", "response", "token", "secret"}}
        await audit_event(guild_id, "economy", title, metadata=audit_meta)
    except Exception:
        log.exception("Failed to write economy event to Upstash audit history")
    channel_id = economy_log_channels.get(guild_id) or category_log_channels.get(guild_id, {}).get("economy")
    if not channel_id:
        channel_id = log_channels.get(guild_id)
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        return
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.gold(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    for name, value in (fields or []):
        embed.add_field(name=name, value=str(value), inline=True)
    embed.set_footer(text=f"Cinnamon economy log • Guild {guild_id}")
    try:
        await channel.send(embed=embed)
    except Exception as e:
        # Logging must never make the actual economy command fail.
        log.exception(f"Failed to send economy log in guild {guild_id}: {e}")


def economy_cooldown_remaining(guild_id: int, user_id: int, action: str) -> int:
    until = float(economy_cooldowns.get((guild_id, user_id, action), 0))
    return max(0, math.ceil(until - time.time()))


def economy_item_lines() -> str:
    return "\n".join(
        f"{item['emoji']} **{item['name']}** — `{item_id}` — **{item['price']:,} Catnip**\n{item['description']}"
        for item_id, item in ECONOMY_ITEMS.items() if item.get("shop_enabled", True)
    )


def economy_shop_embed(guild_id: int, user: discord.abc.User, page: int = 0) -> discord.Embed:
    """Clean, app-like shop panel with one product block per visible item."""
    items = [(k, v) for k, v in ECONOMY_ITEMS.items() if v.get("shop_enabled", True)]; per_page = 4
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1)); visible = items[page*per_page:(page+1)*per_page]
    balance = economy_balance(guild_id, user.id)
    e = cinnamon_embed("🛒 Cinnamon's Shop",
        "**Buy instantly** with the buttons below. One click buys one item.",
        color=CINNAMON_ORANGE, user=user,
        footer=cinnamon_page_footer("Shop", page+1, total_pages, f"{len(items)} items"))
    cinnamon_field(e, "🌿 Catnip", f"**{balance:,}**", True)
    cinnamon_field(e, "📦 Items", f"**{len(items)}**", True)
    cinnamon_field(e, "🛍️ Page", f"**{page+1}/{total_pages}**", True)
    if not visible:
        e.description = "The shop is empty right now. Ask an administrator to add some items."
        return cinnamon_polish_embed(e)
    previous_category = None
    for number, (item_id, item) in enumerate(visible, start=page*per_page+1):
        category = item.get("category")
        if category == "grow_a_garden" and previous_category != category:
            e.add_field(name="🌱 Grow a Garden Services", value="Pet boosts & mutation services", inline=False)
        previous_category = category
        limit=int(item.get("max_per_person",0)); owned=int(economy_inventory_for(guild_id,user.id).get(item_id,0))
        limit_text=f" • limit {limit}" if limit else " • no limit"
        e.add_field(
            name=f"{item.get('emoji','🐾')}  {item.get('name',item_id)}",
            value=(f"**{_cm_price(guild_id, user.id, item_id, item.get('price', 0)):,} Catnip**{limit_text}  •  own **{owned}**\n"
                   f"{item.get('description','No description provided.')}")[:1024],
            inline=False)
    return cinnamon_polish_embed(e)


_CINNAMON_SHOP_LOCKS = {}  # One purchase at a time per member.


class CinnamonShopView(discord.ui.LayoutView):
    """Components V2 shop: every product has its purchase button attached to it."""
    def __init__(self, guild_id: int, user_id: int, page: int = 0):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user_id = user_id
        self.page = page
        self._build()

    def _build(self):
        items = [(k, v) for k, v in ECONOMY_ITEMS.items() if v.get("shop_enabled", True)]
        per_page = 5
        total_pages = max(1, (len(items) + per_page - 1) // per_page)
        self.page = max(0, min(self.page, total_pages - 1))
        visible = items[self.page * per_page:(self.page + 1) * per_page]
        balance = economy_balance(self.guild_id, self.user_id)

        container = discord.ui.Container(accent_color=CINNAMON_ORANGE)
        container.add_item(discord.ui.TextDisplay(
            f"# 🛒 Cinnamon's Shop\n"
            f"Spend your Catnip wisely. Each button buys **1 item**.\n\n"
            f"🌿 **{balance:,} Catnip**  •  📦 **{len(items)} items**  •  **Page {self.page + 1}/{total_pages}**"
        ))
        container.add_item(discord.ui.Separator())

        if not visible:
            container.add_item(discord.ui.TextDisplay("The shop is empty right now. Ask an administrator to add some items."))
        else:
            previous_category = None
            for item_id, item in visible:
                category = item.get("category")
                if category == "grow_a_garden" and previous_category != category:
                    container.add_item(discord.ui.TextDisplay("## 🌱 Grow a Garden Services"))
                    container.add_item(discord.ui.TextDisplay("Pet boosts & mutation services"))
                previous_category = category
                limit = int(item.get("max_per_person", 0))
                owned = int(economy_inventory_for(self.guild_id, self.user_id).get(item_id, 0))
                limit_text = f"Limit: {limit}" if limit else "No limit"
                price = _cm_price(self.guild_id, self.user_id, item_id, item.get("price", 0))
                name = item.get("name", item_id)
                emoji = item.get("emoji", "🐾")
                desc = cinnamon_ui_literal(item.get("description", "No description provided."), 210)
                can_buy = price <= balance and (not limit or owned < limit)
                button = discord.ui.Button(
                    label="Buy 1" if can_buy else "Unavailable",
                    style=discord.ButtonStyle.success if can_buy else discord.ButtonStyle.secondary,
                    disabled=not can_buy,
                )
                button.callback = self._make_buy_callback(item_id)
                section = discord.ui.Section(
                    f"### {cinnamon_ui_literal(emoji, 20)} {cinnamon_ui_literal(name, 85)}",
                    f"{desc}\n**{price:,} Catnip**  ·  {limit_text}  ·  Owned: **{owned}**",
                    accessory=button,
                )
                container.add_item(section)
                container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))

        nav = discord.ui.ActionRow()
        previous = discord.ui.Button(label="Previous", emoji="◀️", style=discord.ButtonStyle.secondary, disabled=self.page <= 0, custom_id=f"cinnamon_v2_shop_prev_{self.page}")
        next_button = discord.ui.Button(label="Next", emoji="▶️", style=discord.ButtonStyle.primary, disabled=self.page >= total_pages - 1, custom_id=f"cinnamon_v2_shop_next_{self.page}")
        inventory = discord.ui.Button(label="Inventory", emoji="🎒", style=discord.ButtonStyle.secondary, custom_id=f"cinnamon_v2_shop_inventory_{self.page}")
        close = discord.ui.Button(label="Close", emoji="✖️", style=discord.ButtonStyle.danger, custom_id=f"cinnamon_v2_shop_close_{self.page}")
        previous.callback = self._previous_callback
        next_button.callback = self._next_callback
        inventory.callback = self._inventory_callback
        close.callback = self._close_callback
        nav.add_item(previous); nav.add_item(next_button); nav.add_item(inventory); nav.add_item(close)
        container.add_item(nav)
        self.add_item(container)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if (interaction.user.id != self.user_id or not interaction.guild or
                interaction.guild.id != self.guild_id):
            await interaction.response.send_message(
                "This shop panel belongs to a different player.", ephemeral=True)
            return False
        return True

    def _make_buy_callback(self, item_id: str):
        async def callback(interaction: discord.Interaction):
            if not await self._guard(interaction):
                return
            # ACK first: persistence and logging must never consume the
            # three-second interaction response window.
            await interaction.response.defer()
            guild_id, user_id = self.guild_id, self.user_id
            lock = _CINNAMON_SHOP_LOCKS.setdefault((guild_id, user_id), asyncio.Lock())
            async with lock:
                data = ECONOMY_ITEMS.get(item_id)
                if not data or not data.get("shop_enabled", True):
                    return await interaction.followup.send(
                        "This item is no longer available.", ephemeral=True)
                inv = economy_inventory_for(guild_id, user_id)
                current_qty = int(inv.get(item_id, 0))
                limit = int(data.get("max_per_person", 0))
                if limit and current_qty >= limit:
                    return await interaction.followup.send(
                        f"You've reached the {limit}-per-person purchase limit.",
                        ephemeral=True)
                price = _cm_price(guild_id, user_id, item_id, data.get("price", 0))
                balance = economy_balance(guild_id, user_id)
                if balance < price:
                    return await interaction.followup.send(
                        f"Not enough Catnip. You need {price:,}, but have {balance:,}.",
                        ephemeral=True)
                economy_balances[(guild_id, user_id)] = balance - price
                inv[item_id] = current_qty + 1
                await bd_save_data()

            fresh = CinnamonShopView(guild_id, user_id, self.page)
            await interaction.edit_original_response(view=fresh)
            await interaction.followup.send(
                f"Purchased **1 × {cinnamon_ui_literal(data.get('name', item_id), 90)}** "
                f"for **{price:,} Catnip**. Remaining: **{balance - price:,}**.",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            try:
                await economy_log(guild_id, title="🛒 Economy purchase", fields=[
                    ("User", f"{interaction.user} ({user_id})"),
                    ("Item", f"{data['name']} (`{item_id}`)"),
                    ("Quantity", "1"),
                    ("Deducted", f"-{price:,} Catnip"),
                    ("Balance before", f"{balance:,} Catnip"),
                    ("Balance after", f"{balance-price:,} Catnip"),
                    ("Item quantity after", str(inv[item_id])),
                ])
                await _cp_react(interaction.guild, interaction.user, interaction.channel,
                                "big_purchase", value=price)
            except Exception:
                log.exception("Optional shop purchase activity could not be posted")
        return callback
    async def _previous_callback(self, interaction: discord.Interaction):
        if not await self._guard(interaction): return
        fresh = CinnamonShopView(self.guild_id, self.user_id, self.page - 1)
        await interaction.response.edit_message(view=fresh)

    async def _next_callback(self, interaction: discord.Interaction):
        if not await self._guard(interaction): return
        fresh = CinnamonShopView(self.guild_id, self.user_id, self.page + 1)
        await interaction.response.edit_message(view=fresh)

    async def _inventory_callback(self, interaction: discord.Interaction):
        if not await self._guard(interaction): return
        # Components V2 cannot be converted back to embeds by message edit.
        await interaction.response.edit_message(
            view=CinnamonInventoryView(self.guild_id, self.user_id, self.user_id))

    async def _close_callback(self, interaction: discord.Interaction):
        if not await self._guard(interaction): return
        for child in self.walk_children():
            if hasattr(child, "disabled"):
                child.disabled = True
        await interaction.response.edit_message(view=self)


class CinnamonInventoryView(discord.ui.LayoutView):
    """Inventory and shop share a V2 layout, so switching never drops message flags."""

    def __init__(self, guild_id, member_id, viewer_id, page=0):
        super().__init__(timeout=300)
        self.guild_id, self.member_id, self.viewer_id, self.page = guild_id, member_id, viewer_id, page
        self._build()

    def _build(self):
        self.clear_items()
        inventory = economy_inventory_for(self.guild_id, self.member_id)
        items = [(key, int(quantity)) for key, quantity in inventory.items()
                 if int(quantity) > 0 and key in ECONOMY_ITEMS]
        page_size = 5
        pages = max(1, (len(items) + page_size - 1) // page_size)
        self.page = max(0, min(self.page, pages - 1))
        guild = bot.get_guild(self.guild_id)
        member = guild.get_member(self.member_id) if guild else None
        label = cinnamon_ui_literal(member.display_name, 80) if member else "Member"

        panel = discord.ui.Container(accent_color=CINNAMON_UI["info"])
        panel.add_item(discord.ui.TextDisplay(
            f"# 🎒 {label}'s Inventory\n"
            f"**{len(items)} item types**  ·  "
            f"**{sum(qty for _, qty in items):,} total items**\n"
            f"🌿 **{economy_balance(self.guild_id, self.member_id):,} Catnip**  ·  "
            f"Page **{self.page + 1}/{pages}**"
        ))
        panel.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        visible = items[self.page * page_size:(self.page + 1) * page_size]
        if not visible:
            panel.add_item(discord.ui.TextDisplay("No items yet. Visit the shop to get started."))
        for item_id, qty in visible:
            item = ECONOMY_ITEMS[item_id]
            panel.add_item(discord.ui.TextDisplay(
                f"**{cinnamon_ui_literal(item.get('emoji', '🐾'), 20)} "
                f"{cinnamon_ui_literal(item.get('name', item_id), 95)}**  ·  **×{qty:,}**"
            ))
            panel.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))

        nav = discord.ui.ActionRow()
        prev = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
        nxt = discord.ui.Button(label="Next", style=discord.ButtonStyle.primary, disabled=self.page >= pages - 1)
        shop = discord.ui.Button(label="Open shop", style=discord.ButtonStyle.success)
        close = discord.ui.Button(label="Close", style=discord.ButtonStyle.secondary)
        prev.callback = self._prev
        nxt.callback = self._next
        shop.callback = self._shop
        close.callback = self._close
        for button in (prev, nxt, shop, close):
            nav.add_item(button)
        panel.add_item(nav)
        self.add_item(panel)

    async def _guard(self, interaction):
        if (interaction.user.id != self.viewer_id or not interaction.guild or
                interaction.guild.id != self.guild_id):
            await interaction.response.send_message(
                "This inventory panel belongs to a different viewer.", ephemeral=True)
            return False
        return True

    async def _show(self, interaction, page):
        if await self._guard(interaction):
            await interaction.response.edit_message(
                view=CinnamonInventoryView(
                    self.guild_id, self.member_id, self.viewer_id, page))

    async def _prev(self, interaction):
        await self._show(interaction, self.page - 1)

    async def _next(self, interaction):
        await self._show(interaction, self.page + 1)

    async def _shop(self, interaction):
        if await self._guard(interaction):
            await interaction.response.edit_message(
                view=CinnamonShopView(self.guild_id, self.viewer_id))

    async def _close(self, interaction):
        if await self._guard(interaction):
            for child in self.walk_children():
                if hasattr(child, "disabled"):
                    child.disabled = True
            await interaction.response.edit_message(view=self)


class InventoryPageView(discord.ui.View):
    def __init__(self,guild_id,user_id,page=0):
        super().__init__(timeout=300); self.guild_id=guild_id; self.user_id=user_id; self.page=page; self._refresh()
    def _items(self):
        inv=economy_inventory_for(self.guild_id,self.user_id)
        return [(k,int(v)) for k,v in inv.items() if int(v)>0 and k in ECONOMY_ITEMS]
    def _refresh(self):
        pages=max(1,(len(self._items())+5)//6); self.page=max(0,min(self.page,pages-1)); self.clear_items()
        p=discord.ui.Button(label="Back",emoji="◀️",style=discord.ButtonStyle.secondary,disabled=self.page==0,row=0)
        n=discord.ui.Button(label="Next",emoji="▶️",style=discord.ButtonStyle.primary,disabled=self.page>=pages-1,row=0)
        shop=discord.ui.Button(label="Shop",emoji="🛒",style=discord.ButtonStyle.success,row=0)
        close=discord.ui.Button(label="Close",emoji="✖️",style=discord.ButtonStyle.danger,row=0)
        p.callback=self._prev; n.callback=self._next; shop.callback=self._shop; close.callback=self._close
        for b in (p,n,shop,close): self.add_item(b)
    async def _guard(self,i):
        if i.user.id!=self.user_id: await i.response.send_message("🐾 This panel belongs to the person who opened it.",ephemeral=True); return False
        return True
    async def _prev(self,i):
        if not await self._guard(i): return
        self.page-=1; self._refresh(); await i.response.edit_message(embed=inventory_embed(self.guild_id,self.user_id,self.page),view=self)
    async def _next(self,i):
        if not await self._guard(i): return
        self.page+=1; self._refresh(); await i.response.edit_message(embed=inventory_embed(self.guild_id,self.user_id,self.page),view=self)
    async def _shop(self,i):
        if not await self._guard(i): return
        # Existing legacy messages cannot safely morph into a V2 panel.
        await i.response.send_message(
            view=CinnamonShopView(self.guild_id, i.user.id), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())
    async def _close(self,i):
        if not await self._guard(i): return
        for child in self.children: child.disabled=True
        await i.response.edit_message(view=self)

def inventory_embed(guild_id,user_id,page=0):
    member=bot.get_guild(guild_id).get_member(user_id) if bot.get_guild(guild_id) else None
    inv=economy_inventory_for(guild_id,user_id); items=[(k,int(v)) for k,v in inv.items() if int(v)>0 and k in ECONOMY_ITEMS]
    per=6; pages=max(1,(len(items)+per-1)//per); page=max(0,min(page,pages-1)); chunk=items[page*per:(page+1)*per]
    lines=[f"{ECONOMY_ITEMS[k]['emoji']} **{ECONOMY_ITEMS[k]['name']}**  × **{v}**" for k,v in chunk]
    e=cinnamon_embed("🎒 Inventory", "Your collected Cinnamon items.", color=CINNAMON_BLUE, user=member, footer=cinnamon_page_footer("Inventory",page+1,pages))
    cinnamon_field(e,"🌿 Catnip",f"**{economy_balance(guild_id,user_id):,}**",True)
    cinnamon_field(e,"📦 Unique",f"**{len(items)}**",True)
    cinnamon_field(e,"🔢 Total",f"**{sum(v for _,v in items):,}**",True)
    e.add_field(name="Items",value="\n".join(lines) if lines else "Your inventory is empty. Open **Shop** below to start collecting.",inline=False)
    return cinnamon_polish_embed(e)


# Application-command group for all Cinnamon economy features.
economy_group = app_commands.Group(
    name="economy",
    description="Cinnamon's Catnip economy, items, transactions, and backups",
)

# Keep the two admin balance controls under a nested group so the main
# /economy group stays within Discord's 25 direct-child command limit.
economy_admin_group = app_commands.Group(
    name="admin",
    description="Economy administration commands",
    parent=economy_group,
)


@economy_group.command(name="balance", description="Check your Catnip balance")
@app_commands.guild_only()
async def economy_balance_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    balance = economy_balance(interaction.guild.id, member.id)
    inv = economy_inventory_for(interaction.guild.id, member.id)
    item_count = sum(int(v) for v in inv.values())
    embed = cinnamon_embed(
        "🌿 Catnip Wallet",
        f"**{member.mention}**\n\nYour current Cinnamon economy status is shown below.",
        color=CINNAMON_GOLD, user=member, footer="Cinnamon Economy • Wallet"
    )
    cinnamon_field(embed, "🌿 Catnip", f"**{balance:,}**", True)
    cinnamon_field(embed, "🎒 Items", f"**{item_count:,}**", True)
    cinnamon_field(embed, "​", "​", True)
    await interaction.response.send_message(
        embed=cinnamon_polish_embed(embed),
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await economy_log(
        interaction.guild.id,
        title="👛 Economy balance viewed",
        fields=[
            ("Viewer", f"{interaction.user} ({interaction.user.id})"),
            ("Member", f"{member} ({member.id})"),
            ("Balance", f"{balance:,} Catnip"),
        ],
    )
    await bd_save_data()


@economy_group.command(name="inventory", description="See your Cinnamon items")
@app_commands.guild_only()
async def economy_inventory_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    await interaction.response.send_message(
        view=CinnamonInventoryView(interaction.guild.id, member.id, interaction.user.id),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())



@economy_group.command(name="diagnose", description="Check economy data consistency (administrator)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def economy_diagnose_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("Administrator permission is required.", ephemeral=True)
    target = member or interaction.user
    key = economy_key(interaction.guild.id, target.id)
    stored = economy_balances.get(key)
    embed = cinnamon_embed(
        "🧰 Economy consistency check",
        "Read-only diagnostics; this command never changes or repairs balances.",
        color=CINNAMON_BLUE, user=interaction.user, footer="Cinnamon Economy • Diagnostics")
    cinnamon_field(embed, "Target", f"{target.mention} ({target.id})")
    cinnamon_field(embed, "Guild key", str(interaction.guild.id))
    cinnamon_field(embed, "Balance map entry", "Present" if key in economy_balances else "Missing")
    cinnamon_field(embed, "Raw loaded value", f"{stored:,}" if isinstance(stored, int) else repr(stored))
    cinnamon_field(embed, "Accessor value", f"{int(stored if stored is not None else ECONOMY_STARTING_BALANCE):,} Catnip (default only if missing)")
    cinnamon_field(embed, "Loaded account entries", str(len(economy_balances)))
    cinnamon_field(embed, "Snapshot status", f"{bd_store.status} — {bd_store.reason}")
    cinnamon_field(embed, "Backend durable", str(bd_store.durable))
    await interaction.response.send_message(embed=embed, ephemeral=True)

@economy_group.command(name="shop", description="Open Cinnamon's interactive Catnip shop")
@app_commands.guild_only()
async def economy_shop_cmd(interaction: discord.Interaction):
    # Components V2 owns the complete shop layout, so do not attach the old
    # embed underneath it. This keeps product buttons visually attached to
    # their products like the modern Discord shop UI.
    view = CinnamonShopView(interaction.guild.id, interaction.user.id, 0)
    await interaction.response.send_message(
        view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
    )
    await economy_log(
        interaction.guild.id,
        title="🛒 Economy shop viewed",
        fields=[("Viewer", f"{interaction.user} ({interaction.user.id})"), ("Items shown", str(len(ECONOMY_ITEMS)))]
    )


async def cinnamon_item_autocomplete(interaction: discord.Interaction, current: str):
    """Search current item names; no manually memorised inventory IDs."""
    term = (current or "").lower().strip()
    options = []
    for item_id, item in ECONOMY_ITEMS.items():
        name = str(item.get("name", item_id))
        if term and term not in item_id.lower() and term not in name.lower():
            continue
        options.append(app_commands.Choice(name=f"{name[:78]} ({item_id})"[:100], value=item_id))
        if len(options) >= 25:
            break
    return options


@economy_group.command(name="buy", description="Buy an item with Catnip")
@app_commands.describe(item="Search the item by name", quantity="How many to buy")
@app_commands.autocomplete(item=cinnamon_item_autocomplete)
@app_commands.guild_only()
async def economy_buy_cmd(interaction: discord.Interaction, item: str, quantity: int = 1):
    guild_id, user_id = interaction.guild.id, interaction.user.id
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await cinnamon_send(interaction, "❌ That item isn't in the shop. Use `/economy shop` to see available items.", ephemeral=True)
        return
    current_qty = int(economy_inventory_for(guild_id, user_id).get(item_id, 0))
    max_per_person = int(data.get("max_per_person", 0))
    if max_per_person and current_qty + quantity > max_per_person:
        await cinnamon_send(interaction, f"❌ This item has a limit of **{max_per_person}** per person. You already have **{current_qty}**.", ephemeral=True)
        return
    if quantity < 1 or quantity > 99:
        return await cinnamon_send(interaction, "❌ Quantity must be between 1 and 99.", ephemeral=True)
    unit_price = _cm_price(guild_id, user_id, item_id, data["price"])
    cost = unit_price * quantity
    balance = economy_balance(guild_id, user_id)
    if balance < cost:
        await cinnamon_send(interaction, f"❌ You need **{cost:,} Catnip**, but you only have **{balance:,}**.", ephemeral=True)
        return
    economy_balances[(guild_id, user_id)] = balance - cost
    inv = economy_inventory_for(guild_id, user_id)
    inv[item_id] = current_qty + quantity
    await bd_save_data()
    await economy_log(guild_id, title="🛒 Economy purchase", fields=[("User", f"{interaction.user} ({user_id})"), ("Item", f"{data['name']} (`{item_id}`)"), ("Quantity", quantity), ("Unit price", f"{unit_price:,} Catnip"), ("Deducted", f"-{cost:,} Catnip"), ("Balance before", f"{balance:,} Catnip"), ("Balance after", f"{balance-cost:,} Catnip"), ("Item quantity after", str(inv[item_id]))])
    embed = cinnamon_embed("🛒 Purchase Complete", f"You bought **{quantity:,}× {data['emoji']} {data['name']}**.", color=CINNAMON_GREEN, user=interaction.user, footer="Cinnamon Economy • Purchase")
    cinnamon_field(embed, "💸 Cost", f"**{cost:,} Catnip**", True)
    cinnamon_field(embed, "🌿 New balance", f"**{economy_balances[(guild_id, user_id)]:,} Catnip**", True)
    cinnamon_field(embed, "📦 You now own", f"**{inv[item_id]:,}×**", True)
    await interaction.response.send_message(embed=cinnamon_polish_embed(embed), allowed_mentions=discord.AllowedMentions.none())
    await _cp_react(interaction.guild, interaction.user, interaction.channel, "big_purchase", value=cost)


@economy_group.command(name="daily", description="Claim your daily Catnip")
@app_commands.guild_only()
async def economy_daily_cmd(interaction: discord.Interaction):
    guild_id, user_id = interaction.guild.id, interaction.user.id
    remaining = economy_cooldown_remaining(guild_id, user_id, "daily")
    if remaining:
        embed = cinnamon_embed("⏳ Daily Catnip Cooldown", f"Cinnamon has already given you today's Catnip.\n\nCome back in **{remaining // 3600}h {(remaining % 3600) // 60}m**.", color=CINNAMON_MUTED, user=interaction.user, footer="Cinnamon Economy • Daily")
        await interaction.response.send_message(embed=cinnamon_polish_embed(embed), ephemeral=True)
        return
    economy_cooldowns[(guild_id, user_id, "daily")] = time.time() + 86400
    balance_before = economy_balance(guild_id, user_id)
    economy_balances[(guild_id, user_id)] = balance_before + ECONOMY_DAILY_REWARD
    box_awarded = await advanced_maybe_award_box(guild_id, interaction.user, "daily", chance=0.20) if "advanced_maybe_award_box" in globals() else False
    await bd_save_data()
    await economy_log(guild_id, title="🌿 Daily Catnip", fields=[("User", f"{interaction.user} ({user_id})"), ("Amount", f"+{ECONOMY_DAILY_REWARD} Catnip"), ("Balance before", f"{balance_before:,}"), ("Balance after", f"{balance_before+ECONOMY_DAILY_REWARD:,}")])
    embed = cinnamon_embed("🌿 Daily Catnip Claimed", "Cinnamon has approved your daily snack budget.\n\n**Come back tomorrow for another reward!**", color=CINNAMON_GREEN, user=interaction.user, footer="Cinnamon Economy • Daily Reward")
    cinnamon_field(embed, "Reward", f"**+{ECONOMY_DAILY_REWARD:,} Catnip**", True)
    cinnamon_field(embed, "New balance", f"**{balance_before + ECONOMY_DAILY_REWARD:,} Catnip**", True)
    if box_awarded:
        cinnamon_field(embed, "🎁 Bonus", "**1 Mystery Box**", True)
    await interaction.response.send_message(embed=cinnamon_polish_embed(embed), allowed_mentions=discord.AllowedMentions.none())


@economy_group.command(name="work", description="Work for Cinnamon and earn 50-150 Catnip every 10 minutes")
@app_commands.guild_only()
async def economy_work_cmd(interaction: discord.Interaction):
    ok, amount, message = await economy_do_work(interaction.guild.id, interaction.user)
    if not ok:
        embed = cinnamon_embed("⏳ Work Cooldown", message, color=CINNAMON_MUTED, user=interaction.user, footer="Cinnamon Economy • Work")
        await interaction.response.send_message(embed=cinnamon_polish_embed(embed), ephemeral=True)
        return
    balance = economy_balance(interaction.guild.id, interaction.user.id)
    job = message.replace("💼 You **", "").split("** and earned", 1)[0] if "** and earned" in message else "worked for Cinnamon"
    embed = cinnamon_embed("💼 Shift Complete", "Cinnamon inspected your work and approved the payment. 🐾", color=CINNAMON_GREEN, user=interaction.user, footer="Cinnamon Economy • Work • 10 minute cooldown")
    cinnamon_field(embed, "💼 Job", f"{job}", False)
    cinnamon_field(embed, "🌿 Earned", f"**+{amount:,} Catnip**", True)
    cinnamon_field(embed, "💰 New balance", f"**{balance:,} Catnip**", True)
    await interaction.response.send_message(embed=cinnamon_polish_embed(embed), allowed_mentions=discord.AllowedMentions.none())


@economy_group.command(name="give", description="Give Catnip to another member")
@app_commands.guild_only()
async def economy_give_cmd(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 10000000]):
    guild_id = interaction.guild.id
    # Defence in depth: client-side range validation is not a substitute for
    # server-side checks. A negative transfer used to CREATE Catnip.
    if not isinstance(amount, int) or not 1 <= amount <= 10000000:
        return await cinnamon_send(interaction, "🐈 Transfers must be between 1 and 10,000,000 Catnip.", ephemeral=True)
    if member.bot:
        await cinnamon_send(interaction, "❌ Bot accounts can't receive Catnip.", ephemeral=True)
        return
    if member.id == interaction.user.id:
        await cinnamon_send(interaction, "🐾 You can't give Catnip to yourself.", ephemeral=True)
        return
    sender_balance = economy_balance(guild_id, interaction.user.id)
    if sender_balance < amount:
        await cinnamon_send(interaction, f"❌ You only have **{sender_balance:,} Catnip**.", ephemeral=True)
        return
    recipient_before = economy_balance(guild_id, member.id)
    economy_balances[(guild_id, interaction.user.id)] = sender_balance - amount
    economy_balances[(guild_id, member.id)] = recipient_before + amount
    await bd_save_data()
    await economy_log(guild_id, title="🎁 Catnip transfer", fields=[("From", f"{interaction.user} ({interaction.user.id})"), ("To", f"{member} ({member.id})"), ("Amount", f"{amount:,} Catnip"), ("Sender before", f"{sender_balance:,}"), ("Sender after", f"{sender_balance-amount:,}"), ("Recipient before", f"{recipient_before:,}"), ("Recipient after", f"{recipient_before+amount:,}")])
    await cinnamon_send(interaction, f"🎁 Gave **{amount:,} Catnip** to {member.mention}.")


class EconomyLeaderboardView(discord.ui.View):
    def __init__(self,guild_id,user_id,rows,page=0):
        super().__init__(timeout=300); self.guild_id=guild_id; self.user_id=user_id; self.rows=rows; self.page=page; self._refresh()
    def _refresh(self):
        pages=max(1,(len(self.rows)+7)//8); self.page=max(0,min(self.page,pages-1)); self.clear_items(); p=discord.ui.Button(label="Back",emoji="◀️",style=discord.ButtonStyle.secondary,disabled=self.page==0,row=0); n=discord.ui.Button(label="Next",emoji="▶️",style=discord.ButtonStyle.primary,disabled=self.page>=pages-1,row=0); p.callback=self._prev; n.callback=self._next; self.add_item(p); self.add_item(n)
    def _embed(self):
        chunk=self.rows[self.page*10:(self.page+1)*10]; lines=[]
        for i,(uid,bal) in enumerate(chunk,self.page*10+1):
            m=bot.get_guild(self.guild_id).get_member(uid) if bot.get_guild(self.guild_id) else None; lines.append(f"**{i}.** {m.display_name if m else f'User {uid}'} — 🌿 **{bal:,}**")
        e=cinnamon_embed("🏆 Catnip Leaderboard","The richest humans in this server, according to Cinnamon. 🐱\n\n"+"\n".join(lines),color=CINNAMON_GOLD,footer=f"Cinnamon Economy • Page {self.page+1}/{max(1,(len(self.rows)+9)//10)}")
        return cinnamon_polish_embed(e)
    async def _guard(self,i):
        if i.user.id!=self.user_id: await i.response.send_message("🐾 This leaderboard belongs to the person who opened it.",ephemeral=True); return False
        return True
    async def _prev(self,i):
        if not await self._guard(i): return
        self.page-=1; self._refresh(); await i.response.edit_message(embed=self._embed(),view=self)
    async def _next(self,i):
        if not await self._guard(i): return
        self.page+=1; self._refresh(); await i.response.edit_message(embed=self._embed(),view=self)

@economy_group.command(name="leaderboard", description="Show the richest members")
@app_commands.guild_only()
async def economy_leaderboard_cmd(interaction: discord.Interaction):
    guild_id=interaction.guild.id; rows=sorted([(uid,int(bal)) for (gid,uid),bal in economy_balances.items() if gid==guild_id],key=lambda x:x[1],reverse=True)
    if not rows: return await cinnamon_send(interaction,"No economy users yet. Start with `/economy daily` or `/economy work`. ",ephemeral=True)
    view=EconomyLeaderboardView(guild_id,interaction.user.id,rows,0)
    await interaction.response.send_message(embed=view._embed(),view=view,allowed_mentions=discord.AllowedMentions.none())


@economy_group.command(name="feed", description="Give Cinnamon an item")
@app_commands.describe(item="Item to give Cinnamon", quantity="How many to give")
@app_commands.autocomplete(item=cinnamon_item_autocomplete)
@app_commands.guild_only()
async def economy_feed_cmd(interaction: discord.Interaction, item: str, quantity: app_commands.Range[int, 1, 99] = 1):
    # Quests, achievements, logs and Upstash saves can exceed Discord's 3s ACK window.
    await interaction.response.defer()
    try:
        guild_id, user_id = interaction.guild.id, interaction.user.id
        item_id = str(item).strip().lower()
        data = ECONOMY_ITEMS.get(item_id)
        if not data:
            await cinnamon_send(interaction, "❌ That item no longer exists. Refresh the command choices and try again.", ephemeral=True)
            return
        inv = economy_inventory_for(guild_id, user_id)
        have = max(0, int(inv.get(item_id, 0)))
        if have < quantity:
            await cinnamon_send(interaction, f"❌ You only have **{have}× {data['name']}**.", ephemeral=True)
            return
        balance_before = economy_balance(guild_id, user_id)
        inv[item_id] = have - quantity
        completed, quest_reward = await apply_quest_progress(guild_id, user_id, item_id, quantity)
        if quest_reward:
            economy_balances[(guild_id, user_id)] = economy_balance(guild_id, user_id) + quest_reward
        await bd_save_data()
        balance_after = economy_balance(guild_id, user_id)
        unlocked = await check_economy_achievements(
            guild_id, user_id, fed=True, completed_quest=bool(completed), member=interaction.user
        )
        await economy_log(guild_id, title="🐟 Cinnamon fed", fields=[("User", f"{interaction.user} ({user_id})"), ("Item", f"{data['name']} (`{item_id}`)"), ("Quantity fed", quantity), ("Quantity remaining", inv.get(item_id, 0)), ("Catnip before", f"{balance_before:,}"), ("Catnip after", f"{economy_balance(guild_id, user_id):,}"), ("Quest rewards", ", ".join(completed) if completed else "None"), ("Achievements", ", ".join(unlocked) if unlocked else "None")])
        mood_note = await _cm_action(interaction.guild, interaction.user, "feed", quantity)
        text = f"🐾 Cinnamon accepted **{quantity}× {data['name']}**!\n{mood_note}"
        if completed:
            text += "\n🎉 Quest complete: " + ", ".join(completed)
        if unlocked:
            text += "\n🏆 Achievement unlocked: **" + ", ".join(unlocked) + "**"
        await cinnamon_send(interaction, text)
    except Exception as exc:
        log.exception("Economy feed command failed for guild %s", interaction.guild.id if interaction.guild else None)
        if interaction.response.is_done():
            await interaction.followup.send("❌ A step in feeding failed. Please check your inventory before retrying; the item may already have been used.", ephemeral=True)
        else:
            await cinnamon_send(interaction, "❌ I couldn't process that feed/quest action. Please try again.", ephemeral=True)



@economy_group.command(name="logs", description="Set or disable the economy transaction log channel")
@app_commands.describe(channel="Channel where economy transactions and backups will be logged; omit to disable")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def economy_logs_cmd(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    guild_id = interaction.guild.id
    if channel is None:
        removed = economy_log_channels.pop(guild_id, None)
        category_log_channels.get(guild_id, {}).pop("economy", None)
        await bd_save_data()
        await cinnamon_send(interaction, "🧾 Economy logs disabled." if removed else "🧾 Economy logs are already disabled.", ephemeral=True)
        if removed:
            # The economy destination has just been removed, so this is intentionally routed through the remaining setup/main logger.
            await send_log(guild_id, title="🧾 Economy logging disabled", interaction=interaction, category="setup", fields=[("Previous channel ID", str(removed))])
        return
    economy_log_channels[guild_id] = channel.id
    category_log_channels.setdefault(guild_id, {})["economy"] = channel.id
    await secure_log_channel(channel)
    await bd_save_data()
    await economy_log(guild_id, title="🧾 Economy logging enabled", description=f"Economy transactions and backup snapshots will be posted here: {channel.mention}")
    await cinnamon_send(interaction, f"✅ Economy logs will now go to {channel.mention}.", ephemeral=True)


async def economy_snapshot_payload(guild_id: int) -> dict:
    users = {}
    user_ids = set()
    for (gid, uid) in economy_balances:
        if gid == guild_id: user_ids.add(uid)
    for (gid, uid) in economy_inventory:
        if gid == guild_id: user_ids.add(uid)
    for uid_text in quest_data.get(guild_id, {}).get("users", {}):
        try: user_ids.add(int(uid_text))
        except (TypeError, ValueError): pass
    for uid in user_ids:
        users[str(uid)] = economy_user_snapshot(guild_id, uid)
    return {
        "schema": 1,
        "type": "cinnamon_economy_snapshot",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "guild_id": guild_id,
        "currency": "Catnip",
        "users": users,
        "items": ECONOMY_ITEMS,
        "quests": ECONOMY_QUESTS,
        "level_rewards": ECONOMY_LEVEL_REWARDS,
        "income_roles": economy_income_roles.get(guild_id, {}),
    }


@economy_group.command(name="snapshot", description="Create one complete economy backup before resetting the bot")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def economy_snapshot_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    channel_id = economy_log_channels.get(guild_id)
    channel = bot.get_channel(channel_id) if channel_id else None
    if channel is None:
        await cinnamon_send(interaction, "❌ Set an economy log channel first with `/economy logs #channel`.", ephemeral=True)
        return
    payload = await economy_snapshot_payload(guild_id)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    file = discord.File(io.BytesIO(raw), filename=f"cinnamon_economy_snapshot_{guild_id}.json")
    user_count = len(payload["users"])
    embed = discord.Embed(title="💾 Cinnamon economy snapshot", description="Complete Catnip balances, inventories, quest progress, item definitions, and quest definitions for this server. Keep this message/file before a reset.", color=discord.Color.green(), timestamp=datetime.datetime.now(datetime.timezone.utc))
    embed.add_field(name="Users backed up", value=str(user_count), inline=True)
    embed.add_field(name="Currency", value="Catnip", inline=True)
    embed.add_field(name="Items", value=str(len(ECONOMY_ITEMS)), inline=True)
    rows = []
    for uid_text, user in sorted(payload["users"].items(), key=lambda pair: int(pair[1].get("balance", 0)), reverse=True)[:10]:
        member = guild_id and bot.get_guild(guild_id).get_member(int(uid_text))
        name = member.display_name if member else f"User {uid_text}"
        rows.append(f"{len(rows)+1}. {name} — {int(user.get('balance', 0)):,} Catnip")
    embed.add_field(name="🏆 Leaderboard at backup time", value="\n".join(rows) if rows else "No users yet.", inline=False)
    item_text = "\n".join(f"{v['emoji']} {v['name']} (`{k}`) — {v['price']} Catnip" for k, v in ECONOMY_ITEMS.items())
    embed.add_field(name="🛒 Item information", value=item_text, inline=False)
    quest_text = "\n".join(f"{q['name']} — {q['amount']}× {ECONOMY_ITEMS[q['item']]['name']} → {q['reward']} Catnip" for q in ECONOMY_QUESTS.values())
    embed.add_field(name="📜 Quest information", value=quest_text, inline=False)
    embed.add_field(name="How to restore", value="After the reset, run `/economy restore-snapshot` in this server. The bot will scan this log channel for the newest snapshot.", inline=False)
    await interaction.response.defer(ephemeral=True)
    await channel.send(embed=embed, file=file)
    await bd_save_data()
    await economy_log(guild_id, title="💾 Economy snapshot created", fields=[("Created by", f"{interaction.user} ({interaction.user.id})"), ("Users backed up", str(user_count)), ("Items", str(len(ECONOMY_ITEMS))), ("Channel", channel.mention)])
    await interaction.followup.send(f"✅ Snapshot saved to {channel.mention}. **{user_count}** users are included. You can reset the bot and later run `/economy restore-snapshot`.", ephemeral=True)


async def economy_restore_from_snapshot(guild: discord.Guild, limit: int = 5000, *, merge_only: bool = False) -> tuple[int, str]:
    """Restore a snapshot. merge_only fills missing state without overwriting live accounts."""
    if not merge_only and globals().get("_ca_transactions_pending", lambda: False)():
        return 0, "A currency transaction needs reconciliation; full restoration is temporarily blocked."
    channel_id = economy_log_channels.get(guild.id) or category_log_channels.get(guild.id, {}).get("economy") or log_channels.get(guild.id)
    if not channel_id:
        return 0, "No economy log channel is configured."
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.HTTPException, discord.NotFound, discord.Forbidden) as exc:
            return 0, f"Cannot access the configured economy log channel ({type(exc).__name__})."
    latest = None
    try:
        async for message in channel.history(limit=limit):
            for attachment in message.attachments:
                if attachment.filename.startswith("cinnamon_economy_snapshot_") and attachment.filename.endswith(".json"):
                    try:
                        data = json.loads((await attachment.read()).decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError, discord.HTTPException):
                        continue
                    if data.get("type") == "cinnamon_economy_snapshot" and int(data.get("guild_id", 0)) == guild.id:
                        latest = data
                        break
            if latest:
                break
    except discord.HTTPException as e:
        return 0, f"Could not read the economy log channel: {e}"
    if latest is None:
        return 0, "No economy snapshot was found in the log channel."

    # Reading Discord attachments awaited I/O; recheck before absolute writes.
    if not merge_only and globals().get("_ca_transactions_pending", lambda: False)():
        return 0, "A currency transaction began during the scan; retry restoration after reconciliation."
    restored = 0
    for uid_text, user in latest.get("users", {}).items():
        try:
            uid = int(uid_text)
            key = (guild.id, uid)
            had_balance = key in economy_balances
            if not merge_only or not had_balance:
                economy_balances[key] = int(user.get("balance", ECONOMY_STARTING_BALANCE))
            snap_inventory = {str(k): int(v) for k, v in user.get("inventory", {}).items() if int(v) > 0}
            if merge_only:
                live_inventory = economy_inventory.setdefault(key, {})
                for item_id, quantity in snap_inventory.items():
                    live_inventory.setdefault(item_id, quantity)
            else:
                economy_inventory[key] = snap_inventory
            snap_quests = user.get("quests", {})
            if isinstance(snap_quests, dict) and any(k in snap_quests for k in ("qp", "daily", "weekly")):
                quest_users = quest_data.setdefault(guild.id, {}).setdefault("users", {})
                if not merge_only or str(uid) not in quest_users:
                    quest_users[str(uid)] = json.loads(json.dumps(snap_quests))
            snap_levels = [int(x) for x in user.get("level_rewards_claimed", [])]
            if merge_only:
                economy_level_rewards_claimed[key] = sorted(set(economy_level_rewards_claimed.get(key, [])) | set(snap_levels))
            else:
                economy_level_rewards_claimed[key] = snap_levels
            snap_achievements = [str(x) for x in user.get("achievements", []) if str(x) in ECONOMY_ACHIEVEMENTS]
            if merge_only:
                economy_achievements[key] = sorted(set(economy_achievements.get(key, [])) | set(snap_achievements))
            else:
                economy_achievements[key] = snap_achievements
            if not had_balance:
                restored += 1
        except (ValueError, TypeError):
            continue
    snapshot_income = latest.get("income_roles")
    if isinstance(snapshot_income, dict):
        economy_income_roles[guild.id] = {int(r): cfg for r, cfg in snapshot_income.items()}
    snapshot_items = latest.get("items")
    if isinstance(snapshot_items, dict):
        restored_items = {}
        for item_id, item in snapshot_items.items():
            if isinstance(item, dict):
                restored_items[str(item_id)] = {
                    "name": str(item.get("name", item_id))[:80],
                    "price": max(1, int(item.get("price", 1))),
                    "emoji": str(item.get("emoji", "🐾"))[:8],
                    "description": str(item.get("description", ""))[:300],
                    "max_per_person": max(0, int(item.get("max_per_person", 0))),
                }
        if merge_only:
            for item_id, item in restored_items.items():
                ECONOMY_ITEMS.setdefault(item_id, item)
        else:
            ECONOMY_ITEMS.clear()
            ECONOMY_ITEMS.update(restored_items)
    snapshot_quests = latest.get("quests")
    if isinstance(snapshot_quests, dict):
        valid_quests = {}
        for quest_id, quest in snapshot_quests.items():
            if isinstance(quest, dict) and str(quest.get("item", "")) in ECONOMY_ITEMS:
                valid_quests[str(quest_id)] = {
                    "name": str(quest.get("name", quest_id))[:80],
                    "item": str(quest.get("item")),
                    "amount": max(1, int(quest.get("amount", 1))),
                    "reward": max(0, int(quest.get("reward", 0))),
                    "description": str(quest.get("description", ""))[:300],
                }
        if merge_only:
            for quest_id, quest in valid_quests.items():
                ECONOMY_QUESTS.setdefault(quest_id, quest)
        elif valid_quests:
            ECONOMY_QUESTS.clear()
            ECONOMY_QUESTS.update(valid_quests)
    await bd_save_data()
    created = latest.get("created_at", "unknown time")
    return restored, created


@economy_admin_group.command(name="addcatnip", description="Admin: add Catnip to a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def economy_addcatnip_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    await _ca_admin_catnip_command(interaction, member, amount, True)


@economy_admin_group.command(name="removecatnip", description="Admin: remove Catnip from a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def economy_removecatnip_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    await _ca_admin_catnip_command(interaction, member, amount, False)


@economy_group.command(name="income", description="Admin: manage Catnip income roles")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(action="add, remove, or list", role="Role that earns Catnip", amount="Catnip paid each collection", minutes="Cooldown in minutes")
@app_commands.choices(action=[app_commands.Choice(name="add", value="add"), app_commands.Choice(name="remove", value="remove"), app_commands.Choice(name="list", value="list")])
async def economy_income_cmd(interaction: discord.Interaction, action: app_commands.Choice[str], role: discord.Role | None = None, amount: int | None = None, minutes: int | None = None):
    guild_id = interaction.guild.id
    cfg = economy_income_roles.setdefault(guild_id, {})
    if action.value == "list":
        embed = discord.Embed(title="💰 Catnip income roles", description=economy_income_role_lines(interaction.guild), color=discord.Color.gold())
        await interaction.response.send_message(embed=cinnamon_polish_embed(embed), ephemeral=True)
        return
    if role is None:
        await cinnamon_send(interaction, "❌ Choose a role.", ephemeral=True)
        return
    if action.value == "remove":
        removed = cfg.pop(role.id, None)
        await bd_save_data()
        await cinnamon_send(interaction, f"🗑️ Removed {role.mention} from Catnip income roles." if removed else f"ℹ️ {role.mention} was not an income role.", ephemeral=True)
        return
    if amount is None or minutes is None:
        await cinnamon_send(interaction, "❌ For `add`, provide both `amount` and `minutes`.", ephemeral=True)
        return
    cfg[role.id] = {"amount": int(amount), "cooldown": int(minutes) * 60}
    await bd_save_data()
    await economy_log(guild_id, title="💰 Income role configured", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Role", role.name), ("Income", f"{amount:,} Catnip / {minutes} min")])
    await cinnamon_send(interaction, f"✅ {role.mention} now earns **{amount:,} Catnip every {minutes} minutes** when members use `/economy collect`.", ephemeral=True)


async def economy_collect(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    configs = economy_income_roles.get(guild_id, {})
    if not configs:
        await cinnamon_send(interaction, "ℹ️ This server has no income roles configured yet.", ephemeral=True)
        return
    total = 0
    collected = []
    now = time.time()
    for role in interaction.user.roles:
        data = configs.get(role.id)
        if not data:
            continue
        action = f"income:{role.id}"
        remaining = economy_cooldown_remaining(guild_id, interaction.user.id, action)
        if remaining:
            continue
        amount = int(data.get("amount", 0))
        cooldown = int(data.get("cooldown", 3600))
        if amount <= 0:
            continue
        economy_cooldowns[(guild_id, interaction.user.id, action)] = now + cooldown
        total += amount
        collected.append(f"{role.name}: +{amount:,}")
    if not collected:
        await cinnamon_send(interaction, "⏳ None of your income roles are ready to collect yet.", ephemeral=True)
        return
    balance_before = economy_balance(guild_id, interaction.user.id)
    economy_balances[(guild_id, interaction.user.id)] = balance_before + total
    await bd_save_data()
    await economy_log(guild_id, title="💰 Income collected", fields=[("User", f"{interaction.user} ({interaction.user.id})"), ("Total", f"+{total:,} Catnip"), ("Balance before", f"{balance_before:,}"), ("Balance after", f"{balance_before+total:,}"), ("Sources", "\n".join(collected))])
    await cinnamon_send(interaction, f"💰 You collected **{total:,} Catnip**!\n" + "\n".join(f"• {x}" for x in collected))


@economy_group.command(name="collect", description="Collect Catnip from all income roles you have")
@app_commands.guild_only()
async def economy_collect_cmd(interaction: discord.Interaction):
    await economy_collect(interaction)


@app_commands.guild_only()
async def collect_cmd(interaction: discord.Interaction):
    await economy_collect(interaction)


@economy_group.command(name="item-add", description="Admin: add an item or Mystery Box to a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(member="Member receiving the reward", item="Search item name OR select Mystery Box", quantity="Number of items/boxes to add", box_tier="Mystery Box rarity (only for Mystery Box)", reward_tier="Add item to this Mystery Box reward pool instead", reward_type="Reward category (item/material)")
@app_commands.choices(box_tier=[app_commands.Choice(name=cfg["label"],value=t) for t,cfg in BOX_TIERS.items()])
@app_commands.choices(reward_tier=[app_commands.Choice(name=cfg["label"],value=t) for t,cfg in BOX_TIERS.items()])
@app_commands.choices(reward_type=[app_commands.Choice(name="Item",value="items"),app_commands.Choice(name="Material",value="materials")])
@app_commands.autocomplete(item=cinnamon_item_autocomplete)
async def economy_item_add_cmd(interaction: discord.Interaction, member: discord.Member, item: str, quantity: app_commands.Range[int, 1, 10000] = 1, box_tier: app_commands.Choice[str] | None = None, reward_tier: app_commands.Choice[str] | None = None, reward_type: app_commands.Choice[str] | None = None):
    guild_id=interaction.guild.id
    raw=item.lower().strip()
    # Box mode accepts a clear label, or the explicit box_tier selector.
    is_box=raw in {"mystery box","mystery boxes","box","boxes","mystery_box"} or box_tier is not None
    if is_box:
        tier_name=box_tier.value if box_tier else "common"
        before=_box_count(guild_id,member.id,tier_name)
        _set_box_count(guild_id,member.id,before+quantity,tier_name)
        await bd_save_data()
        await economy_log(guild_id,title="🛠️ Admin Mystery Boxes added",fields=[("Admin",f"{interaction.user} ({interaction.user.id})"),("Member",f"{member} ({member.id})"),("Tier",tier_name.title()),("Added",f"+{quantity}"),("Before",before),("After",before+quantity)])
        return await cinnamon_send(interaction,f"✅ Added **{quantity}× {BOX_TIERS[tier_name]['emoji']} {BOX_TIERS[tier_name]['label']} Mystery Box** to {member.mention}.",ephemeral=True)
    item_id=raw
    if item_id not in ECONOMY_ITEMS:
        matches=[k for k,v in ECONOMY_ITEMS.items() if str(v.get("name","")).lower()==raw]
        if len(matches)==1:item_id=matches[0]
    data=ECONOMY_ITEMS.get(item_id)
    if data is None:
        return await cinnamon_send(interaction,"❌ That item doesn't exist. Search a catalogue item, or choose **Mystery Box** and its tier.",ephemeral=True)
    if reward_tier is not None:
        chosen_pool=reward_type.value if reward_type else "items"
        pool_key=f"{guild_id}:{reward_tier.value}"
        pools=ADVANCED_FEATURES.setdefault("custom_box_rewards",{}).setdefault(pool_key,{"items":[],"materials":[]})
        pool=pools.setdefault(chosen_pool,[])
        if item_id in pool or item_id in BOX_TIERS[reward_tier.value][chosen_pool]:
            return await cinnamon_send(interaction,"ℹ️ That reward is already in this Mystery Box pool.",ephemeral=True)
        pool.append(item_id)
        await bd_save_data()
        await economy_log(guild_id,title="🎁 Mystery Box reward pool updated",fields=[("Admin",f"{interaction.user} ({interaction.user.id})"),("Tier",reward_tier.value.title()),("Pool",chosen_pool),("Item",f"{data.get('name',item_id)} ({item_id})")])
        return await cinnamon_send(interaction,f"✅ Added **{data.get('emoji','🐾')} {data.get('name',item_id)}** to the **{BOX_TIERS[reward_tier.value]['label']} Mystery Box** {chosen_pool} pool.",ephemeral=True)
    inv=economy_inventory_for(guild_id,member.id); maximum=int(data.get("max_per_person",0)); current=int(inv.get(item_id,0))
    if maximum and current+quantity>maximum:
        return await cinnamon_send(interaction,f"❌ {member.mention} cannot hold more than **{maximum}** of this item.",ephemeral=True)
    inv[item_id]=current+quantity
    await bd_save_data()
    await economy_log(guild_id,title="🛠️ Admin item added",fields=[("Admin",f"{interaction.user} ({interaction.user.id})"),("Member",f"{member} ({member.id})"),("Item",f"{data['name']} (`{item_id}`)"),("Quantity added",f"+{quantity}"),("Quantity before",current),("Quantity after",inv[item_id]),("Catnip balance",economy_balance(guild_id,member.id))])
    await cinnamon_send(interaction,f"✅ Added **{quantity}× {data['emoji']} {data['name']}** to {member.mention}.",ephemeral=True)


@economy_group.command(name="item-remove", description="Admin: remove an item from a member's inventory")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(member="Member losing the item", item="Search item by name", quantity="Number of items to remove")
@app_commands.autocomplete(item=cinnamon_item_autocomplete)
async def economy_item_remove_cmd(interaction: discord.Interaction, member: discord.Member, item: str, quantity: app_commands.Range[int, 1, 10000] = 1):
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await cinnamon_send(interaction, "❌ That item doesn't exist.", ephemeral=True)
        return
    inv = economy_inventory_for(interaction.guild.id, member.id)
    current = int(inv.get(item_id, 0))
    removed = min(current, quantity)
    if removed <= 0:
        await cinnamon_send(interaction, f"❌ {member.mention} doesn't have that item.", ephemeral=True)
        return
    inv[item_id] = current - removed
    if inv[item_id] <= 0:
        inv.pop(item_id, None)
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🛠️ Admin item removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Item", f"{data['name']} (`{item_id}`)"), ("Quantity removed", f"-{removed}"), ("Quantity before", current), ("Quantity after", inv.get(item_id, 0)), ("Catnip balance", economy_balance(interaction.guild.id, member.id))])
    await cinnamon_send(interaction, f"✅ Removed **{removed}× {data['emoji']} {data['name']}** from {member.mention}.", ephemeral=True)


@economy_group.command(name="add-item-shop", description="Admin: add an item to the Catnip shop")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(item_id="Unique shop ID", name="Item name", price="Price in Catnip", description="Optional item description", per_person_limit="Optional maximum quantity one member can own", emoji="Optional emoji")
async def economy_add_item_shop_cmd(interaction: discord.Interaction, item_id: str, name: str, price: app_commands.Range[int, 1, 10000000], description: str | None = None, per_person_limit: int | None = None, emoji: str = "🐾"):
    item_id = re.sub(r"[^a-z0-9_-]", "", item_id.lower())[:32]
    if not item_id or item_id in ECONOMY_ITEMS:
        await cinnamon_send(interaction, "❌ That item ID is invalid or already exists.", ephemeral=True)
        return
    ECONOMY_ITEMS[item_id] = {"name": name[:80], "price": int(price), "emoji": emoji[:8], "description": (description or "No description provided.")[:300], "max_per_person": int(per_person_limit or 0)}
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🛒 Shop item added", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Item", f"{emoji} {name}"), ("ID", item_id), ("Price", f"{price:,} Catnip"), ("Per-person limit", per_person_limit or "Unlimited")])
    await cinnamon_send(interaction, f"✅ Added **{emoji} {name}** (`{item_id}`) to the shop.", ephemeral=True)


async def autocomplete_shop_item_ids(interaction: discord.Interaction, current: str):
    current = current.lower().strip()
    choices = []
    for item_id, item in ECONOMY_ITEMS.items():
        if current and current not in item_id.lower() and current not in str(item.get("name", "")).lower():
            continue
        choices.append(app_commands.Choice(
            name=f"{str(item.get('name', item_id))[:80]} ({item_id})",
            value=item_id,
        ))
        if len(choices) >= 25:
            break
    return choices


@economy_group.command(name="edit-shop-item", description="Admin: edit a Catnip shop item")
@app_commands.autocomplete(item_id=autocomplete_shop_item_ids)
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(item_id="Item ID to edit", name="New name", price="New price", description="New description", per_person_limit="New per-person limit; 0 means unlimited", emoji="New emoji")
async def economy_edit_shop_item_cmd(interaction: discord.Interaction, item_id: str, name: str | None = None, price: int | None = None, description: str | None = None, per_person_limit: int | None = None, emoji: str | None = None):
    item_id = item_id.lower().strip()
    item = ECONOMY_ITEMS.get(item_id)
    if item is None:
        await cinnamon_send(interaction, "❌ That shop item doesn't exist.", ephemeral=True)
        return
    if all(x is None for x in (name, price, description, per_person_limit, emoji)):
        await cinnamon_send(interaction, "❌ Choose at least one property to edit.", ephemeral=True)
        return
    if name is not None: item["name"] = name[:80]
    if price is not None:
        if not 1 <= price <= 10000000:
            return await cinnamon_send(interaction, "Item price must be 1–10,000,000 Catnip.", ephemeral=True)
        item["price"] = int(price)
    if description is not None: item["description"] = description[:300]
    if per_person_limit is not None: item["max_per_person"] = int(per_person_limit)
    if emoji is not None: item["emoji"] = emoji[:8]
    await bd_save_data()
    await economy_log(interaction.guild.id, title="✏️ Shop item edited", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Item ID", item_id), ("New name", item["name"]), ("New price", f"{item['price']:,} Catnip"), ("Per-person limit", item.get("max_per_person", 0) or "Unlimited")])
    await cinnamon_send(interaction, f"✅ Updated **{item['emoji']} {item['name']}** (`{item_id}`).", ephemeral=True)


@economy_group.command(name="remove-item-shop", description="Admin: remove an item from the Catnip shop")
@app_commands.autocomplete(item_id=autocomplete_shop_item_ids)
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(item_id="Item ID to remove", remove_from_inventories="Whether all copies should also be removed from member inventories")
async def economy_remove_item_shop_cmd(interaction: discord.Interaction, item_id: str, remove_from_inventories: bool = False):
    guild_id = interaction.guild.id
    item_id = item_id.lower().strip()
    item = ECONOMY_ITEMS.get(item_id)
    if item is None:
        await cinnamon_send(interaction, "❌ That shop item doesn't exist.", ephemeral=True)
        return
    removed_inventory = 0
    if remove_from_inventories:
        for (gid, uid), inv in economy_inventory.items():
            if gid == guild_id and item_id in inv:
                removed_inventory += int(inv.pop(item_id, 0))
    ECONOMY_ITEMS.pop(item_id, None)
    await bd_save_data()
    await economy_log(guild_id, title="🗑️ Shop item removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Item", f"{item['emoji']} {item['name']}"), ("ID", item_id), ("Inventory copies removed", removed_inventory), ("Removed from inventories", remove_from_inventories)])
    await cinnamon_send(interaction, f"🗑️ Removed **{item['name']}** from the shop. " + (f"Also removed **{removed_inventory}** copies from inventories." if remove_from_inventories else "Existing inventory copies were kept."), ephemeral=True)


@economy_group.command(name="add-role-income", description="Admin: give a role a recurring Catnip income")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(role="Role receiving the income", amount="Catnip earned each collection", interval="How many time units between collections", unit="Time unit")
@app_commands.choices(unit=[app_commands.Choice(name="Minutes", value="minute"), app_commands.Choice(name="Hours", value="hour"), app_commands.Choice(name="Days", value="day"), app_commands.Choice(name="Weeks", value="week")])
async def economy_add_role_income_cmd(interaction: discord.Interaction, role: discord.Role, amount: int, interval: int, unit: app_commands.Choice[str]):
    multipliers = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800}
    cooldown = int(interval) * multipliers[unit.value]
    economy_income_roles.setdefault(interaction.guild.id, {})[role.id] = {"amount": int(amount), "cooldown": cooldown, "interval": int(interval), "unit": unit.value}
    await bd_save_data()
    await economy_log(interaction.guild.id, title="💰 Role income added/updated", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Role", f"{role} ({role.id})"), ("Income", f"{amount:,} Catnip / {interval} {unit.name.lower()}")])
    await cinnamon_send(interaction, f"✅ {role.mention} now provides **{amount:,} Catnip every {interval} {unit.name.lower()}** via `/economy collect`.", ephemeral=True)


@economy_group.command(name="remove-role-income", description="Admin: remove a role's recurring Catnip income")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(role="Role whose income should be removed")
async def economy_remove_role_income_cmd(interaction: discord.Interaction, role: discord.Role):
    cfg = economy_income_roles.setdefault(interaction.guild.id, {})
    removed = cfg.pop(role.id, None)
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🗑️ Role income removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Role", f"{role} ({role.id})"), ("Was configured", bool(removed))])
    await cinnamon_send(interaction, f"🗑️ Removed {role.mention} from recurring Catnip income." if removed else f"ℹ️ {role.mention} wasn't configured for income.", ephemeral=True)


@economy_group.command(name="iteminfo", description="Show complete information about a Catnip item")
@app_commands.guild_only()
@app_commands.describe(item="Item ID or item name")
async def economy_iteminfo_cmd(interaction: discord.Interaction, item: str):
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await cinnamon_send(interaction, "❌ That item doesn't exist. Use `/economy shop` to see the item IDs.", ephemeral=True)
        return
    limit = int(data.get("max_per_person", 0))
    embed = discord.Embed(title=f"{data['emoji']} {data['name']}", description=data["description"], color=discord.Color.gold())
    embed.add_field(name="Item ID", value=f"`{item_id}`", inline=True)
    embed.add_field(name="Price", value=f"{data['price']:,} Catnip", inline=True)
    embed.add_field(name="Per-person limit", value=str(limit) if limit else "Unlimited", inline=True)
    await interaction.response.send_message(embed=cinnamon_polish_embed(embed))
    await economy_log(interaction.guild.id, title="🔎 Economy item info viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})"), ("Item", f"{item['name']} (`{item_id}`)")])


@economy_group.command(name="restore-snapshot", description="Restore the latest complete economy snapshot from the economy log channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def economy_restore_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    restored, detail = await economy_restore_from_snapshot(interaction.guild)
    if restored <= 0:
        await interaction.followup.send(f"⚠️ Economy recovery did not restore any users. {detail}", ephemeral=True)
        return
    await economy_log(interaction.guild.id, title="🩹 Economy restored", description=f"Restored {restored} user account(s) from the latest snapshot.", fields=[("Snapshot", detail), ("Restored users", restored)])
    await interaction.followup.send(f"🩹 Economy recovery complete. Restored **{restored}** user account(s) from the latest snapshot (**{detail}**).", ephemeral=True)


bot.tree.add_command(economy_group)


# ---------------------------------------------------------------------------
# Hangry Games — isolated Cog, bolted on at the bottom. Self-contained;
# does not touch any of Cinnamon's state above.
# ---------------------------------------------------------------------------

HG_SOLO_DEATHS = [
    "{p1} got stuck in a cardboard box and was shipped to Abu Dhabi.",
    "{p1} misjudged a jump to the fridge and fell into the abyss.",
    "{p1} got the 3 AM zoomies and ran straight into a closed glass door.",
    "{p1} was hypnotized by a laser pointer and wandered off a cliff.",
    "{p1} forgot how to land on their feet.",
    "{p1} was startled by a cucumber and had a fatal heart attack.",
    "{p1} got stuck climbing the curtains and never came down.",
    "{p1} tried to catch a spicy fly (wasp) and lost.",
    "{p1} fell asleep on a warm laptop and melted into a puddle.",
    "{p1} inhaled too much catnip and ascended to another plane of existence.",
    "{p1} fell into a bathtub full of water.",
    "{p1} sneezed too hard and exploded.",
    "{p1} refused to use the new litter box and imploded from spite.",
    "{p1} jumped after a bird through a closed window.",
    "{p1} choked on a furball the size of a tennis ball.",
    "{p1} got their claw stuck in the carpet and starved to death.",
    "{p1} fell into the trash can and was taken out with the garbage.",
    "{p1} chased a fly right into a wall.",
    "{p1} tried to jump on the TV and pulled it down on themselves.",
    "{p1} got trapped inside a pillowcase.",
    "{p1} licked a spicy pepper that fell on the kitchen floor.",
    "{p1} got tangled in the window blinds.",
    "{p1} tried to sleep in a frying pan and cooked.",
    "{p1} smelled a sock and passed out forever.",
    "{p1} saw their own shadow and died of fright.",
    "{p1} tried to eat a fake plastic plant.",
    "{p1} jumped into a box of packing peanuts and disappeared.",
    "{p1} got their head stuck in a tissue box.",
    "{p1} slipped on a wet countertop and went flying.",
    "{p1} heard a loud noise and phased out of reality.",
    "{p1} tried to catch a snowflake and froze.",
    "{p1} got lost underneath the bed forever.",
    "{p1} fell asleep on the radiator.",
    "{p1} watched the washing machine spin until they got dizzy and perished.",
    "{p1} tried to drink from the fish tank and fell in."
]

HG_DUO_DEATHS = [
    "{p2} ate all the tuna, leaving {p1} to starve.",
    "{p1} ate all the tuna, so {p2} pushed them out a window.",
    "{p1} was swatted off the kitchen counter by {p2}.",
    "{p2} stole {p1}'s Churu, leading to a fatal heartbreak.",
    "{p2} pushed {p1} down the stairs while maintaining direct eye contact.",
    "{p2} ambushed {p1} from under the sofa with lethal force.",
    "{p2} challenged {p1} to a staring contest; {p1} spontaneously combusted.",
    "{p2} accidentally locked {p1} in the closet for a month.",
    "{p2} forced {p1} to take a bath, causing a total system failure.",
    "{p2} stole {p1}'s warm sunbeam, freezing them to death.",
    "{p2} betrayed {p1} for a single piece of premium kibble.",
    "{p2} convinced {p1} that the vacuum cleaner was friendly.",
    "{p2} framed {p1} for scratching the good sofa, leading to permanent exile.",
    "{p2} convinced {p1} that the neighborhood dog wanted to play.",
    "{p2} dropped a heavy potted plant directly onto {p1}.",
    "{p2} refused to share the heating pad, and {p1} froze.",
    "{p1} tried to steal {p2}'s toy mouse and caught these paws.",
    "{p2} lured {p1} into a cardboard box and mailed them to Antarctica.",
    "{p2} closed the door right as {p1} was walking through it.",
    "{p2} sneaked up and popped a paper bag behind {p1}, giving them a heart attack.",
    "{p2} stared at {p1} until {p1} forgot how to breathe.",
    "{p1} fell asleep, and {p2} piled heavy laundry on them.",
    "{p2} swatted {p1} right into the spinning ceiling fan.",
    "{p1} looked away for one second, and {p2} struck.",
    "{p2} told {p1} the laser pointer was real; {p1} ran into traffic.",
    "{p2} pushed {p1} right into the dreaded Roomba's path.",
    "{p2} weaponized a cucumber against {p1}.",
    "{p2} sat on {p1}'s face while they were sleeping.",
    "{p1} tried to groom {p2} but got their throat bitten instead.",
    "{p2} trapped {p1} under a laundry basket forever.",
    "{p2} claimed the highest cat tree perch and Sparta-kicked {p1} off of it.",
    "{p1} complained about the food, so {p2} made them the food.",
    "{p1} let their guard down, and {p2} pounced from the shadows.",
    "{p2} aggressively made biscuits on {p1}'s vital organs.",
    "{p2} convinced {p1} to jump into the empty bathtub, then turned on the faucet.",
    "{p2} 'accidentally' knocked a heavy vase directly onto {p1}.",
    "{p1} tripped over {p2} during the 3 AM zoomies and flew out the window.",
    "{p1} tried to steal a bite of {p2}'s wet food and was instantly vaporized.",
    "{p2} told {p1} the vet clinic was a spa. {p1} never returned.",
    "{p2} hissed at {p1} so aggressively that {p1}'s soul left their body.",
    "{p1} was sleeping peacefully until {p2} used their face as a trampoline.",
    "{p2} knocked a flat-screen TV onto {p1} just to see what would happen.",
    "{p2} pushed {p1} into a room full of toddlers and locked the door.",
    "{p1} playfully bit {p2}'s tail and was swiftly eradicated.",
    "{p2} dragged {p1} into the dreaded cat carrier of doom.",
    "{p2} refused to let {p1} use the clean litter box, resulting in a fatal implosion.",
    "{p1} sniffed {p2}'s unwashed paws and passed out forever.",
    "{p2} used {p1} as a scratching post.",
    "{p1} thought {p2} wanted to cuddle, but it was a bunny-kick death trap.",
    "{p2} dropped a live spider on {p1}'s nose, causing a fatal panic attack.",
    "{p2} tricked {p1} into eating the spicy dog kibble.",
    "{p2} sat directly on {p1} and refused to get up until it was too late.",
    "{p2} challenged {p1} to a race down the stairs and tripped them on step two.",
    "{p2} hypnotized {p1} with a swinging pocket watch and ordered them to walk into the fridge.",
    "{p2} told {p1} the red dot was real, sending them straight into a wall.",
    "{p2} pushed {p1} off the bed for taking up too much space.",
    "{p2} tricked {p1} into jumping onto a ceiling fan.",
    "{p1} tried to sneak up on {p2}, but received a swift ninja kick to the face.",
    "{p2} meowed aggressively until {p1}'s ears exploded.",
    "{p1} stole {p2}'s favorite feather toy and paid the ultimate price.",
    "{p2} locked {p1} outside in the rain.",
    "{p2} dropped a half-eaten mouse on {p1}'s face.",
    "{p1} refused to groom {p2} and was promptly banished to the shadow realm.",
    "{p2} body-slammed {p1} from the top of the fridge.",
    "{p1} sneezed, and {p2} took it as a declaration of war.",
    "{p2} swiped {p1}'s nose, causing a fatal system reboot.",
    "{p1} tried to share {p2}'s hammock and was violently evicted.",
    "{p2} convinced {p1} to jump into the toilet bowl.",
    "{p1} interrupted {p2}'s bath time and was destroyed.",
    "{p2} bit {p1}'s ear a little too hard during playtime.",
    "{p2} led {p1} into a room with a closed door, trapping them forever.",
    "{p1} got caught sniffing {p2}'s food bowl.",
    "{p2} swatted {p1} into the dreaded dog's territory.",
    "{p2} tricked {p1} into sniffing a lemon.",
    "{p1} stared at {p2} for too long and spontaneously combusted.",
    "{p2} pushed {p1} into a full bathtub while they were sleeping.",
    "{p1} tried to groom {p2}'s belly, a fatal mistake.",
    "{p2} performed a perfect wrestling takedown on {p1}.",
    "{p2} shoved {p1} off the windowsill.",
    "{p1} thought {p2} was asleep, but {p2} was just waiting to strike.",
    "{p2} trapped {p1} in the laundry basket and sat on the lid.",
    "{p1} took a bite of {p2}'s cat grass and was obliterated.",
    "{p2} convinced {p1} that the vet was just giving out free treats.",
    "{p1} tried to steal {p2}'s collar.",
    "{p2} lured {p1} into a pile of catnip and watched them transcend reality.",
    "{p2} told {p1} the vacuum cleaner was a friend.",
    "{p1} got jump-scared by {p2} and had a heart attack.",
    "{p2} sat on {p1}'s favorite toy until {p1} died of a broken heart.",
    "{p2} tackled {p1} down the hallway.",
    "{p1} tried to walk past {p2} in a narrow hallway.",
    "{p2} pushed {p1} into the empty pool.",
    "{p1} looked at {p2} funny.",
    "{p2} convinced {p1} to chase a laser pointer out the front door.",
    "{p1} sneaked up on {p2} and was roundhouse kicked.",
    "{p2} threw a toy mouse so hard it knocked {p1} out cold.",
    "{p1} refused to wake up, so {p2} used the heavy paws.",
    "{p2} trapped {p1} in a corner and booped them to death.",
    "{p2} lured {p1} into a trap made of cardboard boxes.",
    "{p1} tried to play with {p2}'s tail and was incinerated.",
    "{p2} forced {p1} to listen to the neighbor's dog barking.",
    "{p1} was buried under a mountain of pillows by {p2}.",
    "{p2} showed {p1} a mirror, causing a fatal existential crisis.",
    "{p1} drank from {p2}'s water bowl.",
    "{p2} pushed {p1} into a pile of wet laundry."
]

HG_SURVIVALS = [
    "{p1} took a nice long nap in a sunbeam.",
    "{p1} successfully begged for extra tuna.",
    "{p1} knocked a glass off the table and felt great about it.",
    "{p1} hid under the sofa all day and survived.",
    "{p1} made biscuits on a soft blanket.",
    "{p1} purred loudly to assert dominance.",
    "{p1} found a secret stash of treats and feasted.",
    "{p1} successfully ignored all humans for 24 hours.",
    "{p1} slept inside a warm laundry basket.",
    "{p1} caught the red dot!",
    "{p1} stared out the window at birds all day.",
    "{p1} received excellent chin scritches.",
    "{p1} successfully woke their owner up at 4 AM for food.",
    "{p1} found the perfect empty cardboard box.",
    "{p1} knocked a pen off the desk and survived to tell the tale.",
    "{p1} bathed perfectly in a square of sunlight.",
    "{p1} got a fresh bowl of cold water.",
    "{p1} performed a perfect loaf on the couch.",
    "{p1} successfully camouflaged themselves on a rug.",
    "{p1} found a discarded bottle cap and played with it for hours.",
    "{p1} stretched really, really far.",
    "{p1} watched a spider crawl across the ceiling peacefully.",
    "{p1} got brushed and purred like a motor.",
    "{p1} claimed the highest spot on the cat tree.",
    "{p1} sniffed the air and decided everything was fine.",
    "{p1} successfully avoided the vacuum cleaner."
]


HG_DATA_FILE = os.environ.get("HANGRY_GAMES_DATA_FILE", "hangry_games_data.json")
HG_UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
HG_UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
HG_REDIS_KEY = "hangry_games_data"


