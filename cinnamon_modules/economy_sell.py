"""Safe item resale for Cinnamon's shared Catnip economy.

Loaded after advanced_economy.py in main.py's shared namespace. This module
reuses the existing inventory, wallet, persistence and economy audit log.
"""
import math

# Mystery-box accessories are priced using the box tier that actually awarded
# them. The rate is applied to the catalogue value, so valuable accessories
# remain more valuable without ignoring the source box's rarity.
SELL_BOX_TIER_RATES = {
    "common": 0.25,
    "rare": 0.35,
    "epic": 0.50,
    "legendary": 0.65,
    "mythical": 0.80,
}
SELL_DEFAULT_RATE = 0.50

# EXPANSION_ITEMS' final tuple field marks profile accessories/collectibles.
SELL_ACCESSORY_IDS = {
    item_id
    for item_id, definition in EXPANSION_ITEMS.items()
    if bool(definition[5])
}
SELL_ACCESSORY_IDS.update(
    item_id for item_id, item in ECONOMY_ITEMS.items()
    if item.get("is_accessory") is True
)

_MYSTERY_ITEM_SOURCES_KEY = "mystery_item_sources"
_original_open_one_for_sell = _open_one


async def _open_one_with_item_provenance(guild_id, user, tier="common"):
    """Record the source tier for each accessory added by a box opening."""
    tier = str(tier or "common").lower()
    if tier not in SELL_BOX_TIER_RATES:
        tier = "common"
    inventory = economy_inventory_for(guild_id, user.id)
    before = {
        item_id: int(inventory.get(item_id, 0))
        for item_id in SELL_ACCESSORY_IDS
    }
    result = await _original_open_one_for_sell(guild_id, user, tier)
    source_root = advanced_features_data.setdefault(_MYSTERY_ITEM_SOURCES_KEY, {})
    account_key = f"{int(guild_id)}:{int(user.id)}"
    account_sources = source_root.setdefault(account_key, {})
    for item_id in SELL_ACCESSORY_IDS:
        gained = max(0, int(inventory.get(item_id, 0)) - before[item_id])
        if gained:
            account_sources.setdefault(item_id, []).extend([tier] * gained)
    return result


# mystery_cmd resolves _open_one when the command is invoked, so replacing this
# shared helper here transparently tracks future box rewards without a second
# mystery-box command or a second inventory.
_open_one = _open_one_with_item_provenance


def economy_sell_quote(guild_id: int, user_id: int, item_id: str, quantity: int):
    """Return (total, unit_prices, source_tiers, error) without mutating state."""
    item = ECONOMY_ITEMS.get(item_id)
    if not item:
        return 0, [], [], "That item is no longer in Cinnamon's item catalogue."
    if item.get("sellable", True) is False:
        return 0, [], [], "This item cannot be sold back to Cinnamon."
    inventory = economy_inventory_for(guild_id, user_id)
    owned = max(0, int(inventory.get(item_id, 0)))
    if quantity < 1 or owned < quantity:
        return 0, [], [], f"You own {owned} × {item.get('name', item_id)}, so you cannot sell {quantity}."
    base_price = max(0, int(item.get("price", 0)))
    if base_price <= 0:
        return 0, [], [], "This item has no resale value configured."

    if item_id in SELL_ACCESSORY_IDS:
        account_key = f"{int(guild_id)}:{int(user_id)}"
        source_root = advanced_features_data.setdefault(_MYSTERY_ITEM_SOURCES_KEY, {})
        account_sources = source_root.get(account_key, {})
        recorded = list(account_sources.get(item_id, []))
        if len(recorded) < quantity:
            return 0, [], [], (
                "Cinnamon cannot verify which Mystery Box awarded every copy of this "
                "accessory. Ask an administrator to verify its original box source first."
            )
        tiers = [str(value).lower() for value in recorded[:quantity]]
        if any(tier not in SELL_BOX_TIER_RATES for tier in tiers):
            return 0, [], [], "This accessory has an invalid Mystery Box source record."
        unit_prices = [
            max(1, math.floor(base_price * SELL_BOX_TIER_RATES[tier]))
            for tier in tiers
        ]
        return sum(unit_prices), unit_prices, tiers, None

    # Ordinary shop items and Grow a Garden service items receive a 50% resale
    # value. Services are inventory items until a ticket fulfils/consumes them.
    unit = max(1, math.floor(base_price * SELL_DEFAULT_RATE))
    return unit * quantity, [unit] * quantity, [], None


def _sell_price_breakdown(unit_prices, source_tiers):
    if not source_tiers:
        return f"{unit_prices[0]:,} Catnip each"
    counts = {}
    for tier, price in zip(source_tiers, unit_prices):
        counts.setdefault(tier, []).append(price)
    return " · ".join(
        f"{tier.title()} Box: {len(prices)} × {sum(prices):,} Catnip"
        for tier, prices in counts.items()
    )


class EconomySellConfirmView(discord.ui.View):
    def __init__(self, guild_id, user_id, item_id, quantity, total, unit_prices, source_tiers):
        super().__init__(timeout=60)
        self.guild_id = int(guild_id)
        self.user_id = int(user_id)
        self.item_id = str(item_id)
        self.quantity = int(quantity)
        self.preview_total = int(total)
        self.preview_unit_prices = list(unit_prices)
        self.preview_source_tiers = list(source_tiers)

    async def _guard(self, interaction):
        if interaction.user.id != self.user_id or not interaction.guild or interaction.guild.id != self.guild_id:
            await interaction.response.send_message("This resale confirmation belongs to another player.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm sale", emoji="💰", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        await interaction.response.defer()
        lock = _CINNAMON_SHOP_LOCKS.setdefault((self.guild_id, self.user_id), asyncio.Lock())
        async with lock:
            total, unit_prices, source_tiers, error = economy_sell_quote(
                self.guild_id, self.user_id, self.item_id, self.quantity
            )
            if error:
                await interaction.edit_original_response(
                    content=f"Sale cancelled: {error}", embed=None, view=None
                )
                return
            inventory = economy_inventory_for(self.guild_id, self.user_id)
            wallet_key = (self.guild_id, self.user_id)
            old_wallet_present = wallet_key in economy_balances
            old_wallet = economy_balances.get(wallet_key)
            old_quantity = int(inventory.get(self.item_id, 0))
            source_root = advanced_features_data.setdefault(_MYSTERY_ITEM_SOURCES_KEY, {})
            account_key = f"{self.guild_id}:{self.user_id}"
            account_sources = source_root.setdefault(account_key, {})
            old_sources = list(account_sources.get(self.item_id, []))
            new_balance = economy_balance(self.guild_id, self.user_id) + total

            inventory[self.item_id] = old_quantity - self.quantity
            if inventory[self.item_id] <= 0:
                inventory.pop(self.item_id, None)
            if source_tiers:
                remaining_sources = old_sources[self.quantity:]
                if remaining_sources:
                    account_sources[self.item_id] = remaining_sources
                else:
                    account_sources.pop(self.item_id, None)
                if not account_sources:
                    source_root.pop(account_key, None)
            economy_balances[wallet_key] = new_balance

            saved = await bd_save_data()
            if not saved:
                if old_quantity:
                    inventory[self.item_id] = old_quantity
                else:
                    inventory.pop(self.item_id, None)
                if old_wallet_present:
                    economy_balances[wallet_key] = old_wallet
                else:
                    economy_balances.pop(wallet_key, None)
                if old_sources:
                    source_root.setdefault(account_key, {})[self.item_id] = old_sources
                else:
                    source_root.get(account_key, {}).pop(self.item_id, None)
                await interaction.edit_original_response(
                    content="Cinnamon could not safely save this sale. Your inventory and balance were restored; please try again later.",
                    embed=None, view=None
                )
                return

        item = ECONOMY_ITEMS[self.item_id]
        embed = cinnamon_embed(
            "✅ Item sold",
            f"Cinnamon bought **{self.quantity} × {item.get('name', self.item_id)}** from you.",
            color=CINNAMON_GREEN, user=interaction.user, footer="Cinnamon Economy • Resale"
        )
        cinnamon_field(embed, "💰 Catnip received", f"**+{total:,}**", True)
        cinnamon_field(embed, "🌿 New balance", f"**{new_balance:,}**", True)
        cinnamon_field(embed, "📦 Remaining", f"**{max(0, old_quantity - self.quantity)} ×**", True)
        if source_tiers:
            cinnamon_field(embed, "🎁 Box source", _sell_price_breakdown(unit_prices, source_tiers), False)
        else:
            cinnamon_field(embed, "Resale rate", "50% of catalogue price", False)
        await interaction.edit_original_response(embed=cinnamon_polish_embed(embed), content=None, view=None)
        await economy_log(
            self.guild_id,
            title="💰 Item sold back",
            fields=[
                ("User", f"{interaction.user} ({self.user_id})"),
                ("Item", f"{item.get('name', self.item_id)} ({self.item_id})"),
                ("Quantity", str(self.quantity)),
                ("Paid", f"{total:,} Catnip"),
                ("Box sources", ", ".join(source_tiers) if source_tiers else "Not applicable"),
                ("Balance after", f"{new_balance:,} Catnip"),
            ],
        )

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        await interaction.response.edit_message(
            content="Sale cancelled. Your item and Catnip balance are unchanged.",
            embed=None, view=None
        )


@economy_group.command(name="sell", description="Sell an item back to Cinnamon for Catnip")
@app_commands.guild_only()
@app_commands.describe(item="Search for the item you want to sell", quantity="How many copies to sell")
@app_commands.autocomplete(item=cinnamon_item_autocomplete)
async def economy_sell_cmd(
    interaction: discord.Interaction,
    item: str,
    quantity: app_commands.Range[int, 1, 99] = 1,
):
    item_id = str(item).lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [
            key for key, value in ECONOMY_ITEMS.items()
            if str(value.get("name", "")).lower() == item_id
        ]
        if len(matches) == 1:
            item_id = matches[0]
    total, unit_prices, source_tiers, error = economy_sell_quote(
        interaction.guild.id, interaction.user.id, item_id, quantity
    )
    if error:
        return await cinnamon_send(interaction, f"❌ {error}", ephemeral=True)

    data = ECONOMY_ITEMS[item_id]
    embed = cinnamon_embed(
        "Sell item to Cinnamon?",
        f"Sell **{quantity} × {data.get('emoji', '🐾')} {data.get('name', item_id)}** back to Cinnamon?",
        color=CINNAMON_GOLD, user=interaction.user, footer="Cinnamon Economy • Resale"
    )
    cinnamon_field(embed, "💰 You will receive", f"**{total:,} Catnip**", True)
    cinnamon_field(embed, "🌿 Current balance", f"**{economy_balance(interaction.guild.id, interaction.user.id):,} Catnip**", True)
    cinnamon_field(embed, "📦 Owned", f"**{int(economy_inventory_for(interaction.guild.id, interaction.user.id).get(item_id, 0))} ×**", True)
    if source_tiers:
        cinnamon_field(embed, "🎁 Original Mystery Box", _sell_price_breakdown(unit_prices, source_tiers), False)
    else:
        cinnamon_field(embed, "Resale rate", "50% of the item's catalogue price (including Grow a Garden services).", False)
    embed.set_footer(text="Confirm within 60 seconds. Selling cannot be undone.")
    view = EconomySellConfirmView(
        interaction.guild.id, interaction.user.id, item_id, quantity,
        total, unit_prices, source_tiers
    )
    await interaction.response.send_message(
        embed=cinnamon_polish_embed(embed), view=view, ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none()
    )
