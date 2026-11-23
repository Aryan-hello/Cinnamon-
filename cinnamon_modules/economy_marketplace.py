"""Player marketplace, escrow trades, collections and wishlists."""
import asyncio as _market_asyncio
import copy as _market_copy
import time as _market_time
import uuid as _market_uuid

_MARKET_KEY = "player_market_v1"
_TRADE_KEY = "player_trades_v1"
_WISHLIST_KEY = "player_wishlists_v1"
_MARKET_LOCKS = {}

def _market_root(key, gid):
    return advanced_features_data.setdefault(key, {}).setdefault(str(int(gid)), {})

def _market_lock(gid):
    return _MARKET_LOCKS.setdefault(int(gid), _market_asyncio.Lock())

def _market_member_locks(gid, users):
    return [_CINNAMON_SHOP_LOCKS.setdefault((int(gid), int(uid)), _market_asyncio.Lock())
            for uid in sorted(set(int(x) for x in users))]

async def _market_acquire(locks):
    for lock in locks:
        await lock.acquire()

def _market_release(locks):
    for lock in reversed(locks):
        if lock.locked():
            lock.release()

def _market_item_ok(item_id):
    item = ECONOMY_ITEMS.get(str(item_id), {})
    return bool(item and economy_sell_value(str(item_id), item) > 0
                and not item.get("service_type")
                and item.get("category") != "grow_a_garden")

async def _market_item_autocomplete(interaction, current):
    if not interaction.guild:
        return []
    inv = economy_inventory_for(interaction.guild.id, interaction.user.id)
    query, results = str(current or "").lower(), []
    for item_id, quantity in inv.items():
        if int(quantity) < 1 or not _market_item_ok(item_id):
            continue
        item = ECONOMY_ITEMS.get(item_id, {})
        name = str(item.get("name", item_id))
        if query in name.lower() or query in item_id.lower():
            results.append(app_commands.Choice(name=f"{name} • {int(quantity)} owned", value=item_id))
    return results[:25]

async def _market_listing_autocomplete(interaction, current):
    if not interaction.guild:
        return []
    root = _market_root(_MARKET_KEY, interaction.guild.id)
    query, results = str(current or "").lower(), []
    for listing_id, rec in root.items():
        if rec.get("status") != "active":
            continue
        item = ECONOMY_ITEMS.get(rec.get("item_id"), {})
        label = f"{item.get('name', rec.get('item_id'))} • {int(rec.get('total_price', 0)):,} Catnip • {listing_id}"
        if query in label.lower() or query in listing_id.lower():
            results.append(app_commands.Choice(name=label[:100], value=listing_id))
    return results[:25]

async def _market_persist_or_rollback(gid, snapshots, records, old_records):
    if await bd_save_data():
        return True
    for uid, (balance, inventory) in snapshots.items():
        economy_balances[(int(gid), int(uid))] = int(balance)
        target = economy_inventory_for(gid, uid)
        target.clear()
        target.update(inventory)
    records.clear()
    records.update(old_records)
    return False

market_group = app_commands.Group(name="market", description="Buy and sell member-owned Cinnamon items")

@market_group.command(name="create", description="List an item you own on the member marketplace")
@app_commands.guild_only()
@app_commands.describe(item="Item to list", quantity="Quantity to escrow", total_price="Total Catnip price for the whole listing")
@app_commands.autocomplete(item=_market_item_autocomplete)
async def market_create(interaction: discord.Interaction, item: str,
                        quantity: app_commands.Range[int, 1, 99],
                        total_price: app_commands.Range[int, 1, 10000000]):
    gid, uid, item_id = interaction.guild.id, interaction.user.id, str(item).strip().lower()
    if not _market_item_ok(item_id):
        return await cinnamon_send(interaction, "That item cannot be listed. Services and items without resale eligibility are excluded.", ephemeral=True)
    async with _market_lock(gid):
        locks = _market_member_locks(gid, [uid])
        await _market_acquire(locks)
        try:
            inv = economy_inventory_for(gid, uid)
            owned = int(inv.get(item_id, 0))
            if owned < quantity:
                return await cinnamon_send(interaction, f"You own {owned} of that item, not {quantity}.", ephemeral=True)
            root = _market_root(_MARKET_KEY, gid)
            old_records = _market_copy.deepcopy(root)
            snapshots = {uid: (economy_balance(gid, uid), dict(inv))}
            inv[item_id] = owned - quantity
            if inv[item_id] <= 0:
                inv.pop(item_id, None)
            listing_id = _market_uuid.uuid4().hex[:8]
            root[listing_id] = {
                "seller_id": uid, "item_id": item_id, "quantity": int(quantity),
                "total_price": int(total_price), "status": "active",
                "created_at": int(_market_time.time()),
            }
            if not await _market_persist_or_rollback(gid, snapshots, root, old_records):
                return await cinnamon_send(interaction, "The listing couldn't be saved. Your item was returned.", ephemeral=True)
        finally:
            _market_release(locks)
    await economy_log(gid, title="Marketplace listing created", fields=[
        ("Seller", f"{interaction.user} ({uid})"), ("Item", ECONOMY_ITEMS[item_id]["name"]),
        ("Quantity", quantity), ("Total asking price", f"{total_price:,} Catnip"),
        ("Listing ID", listing_id),
    ])
    await cinnamon_send(interaction, f"Listed {quantity}× {ECONOMY_ITEMS[item_id]['name']} for {total_price:,} Catnip. Listing ID: {listing_id}.", ephemeral=True)

@market_group.command(name="browse", description="Browse active member marketplace listings")
@app_commands.guild_only()
async def market_browse(interaction: discord.Interaction):
    root = _market_root(_MARKET_KEY, interaction.guild.id)
    active = [(lid, rec) for lid, rec in root.items() if rec.get("status") == "active"]
    active.sort(key=lambda pair: int(pair[1].get("created_at", 0)), reverse=True)
    lines = []
    for listing_id, rec in active[:20]:
        item = ECONOMY_ITEMS.get(rec.get("item_id"), {})
        seller = interaction.guild.get_member(int(rec.get("seller_id", 0)))
        seller_name = seller.display_name if seller else f"Member {rec.get('seller_id')}"
        lines.append(f"#{listing_id} — {item.get('emoji', '📦')} {item.get('name', rec.get('item_id'))} ×{int(rec.get('quantity', 0))}\n{int(rec.get('total_price', 0)):,} Catnip · Seller: {seller_name}")
    e = discord.Embed(title="🛍️ Cinnamon Member Marketplace",
                      description="\n\n".join(lines) or "No active listings yet.",
                      color=0xE8A05A)
    e.set_footer(text=f"{len(active)} active listing(s) • Use /market buy")
    await interaction.response.send_message(embed=e, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

@market_group.command(name="buy", description="Purchase an active marketplace listing")
@app_commands.guild_only()
@app_commands.describe(listing_id="Choose the listing to purchase")
@app_commands.autocomplete(listing_id=_market_listing_autocomplete)
async def market_buy(interaction: discord.Interaction, listing_id: str):
    gid, buyer_id = interaction.guild.id, interaction.user.id
    async with _market_lock(gid):
        root = _market_root(_MARKET_KEY, gid)
        rec = root.get(str(listing_id))
        if not isinstance(rec, dict) or rec.get("status") != "active":
            return await cinnamon_send(interaction, "That listing is no longer available.", ephemeral=True)
        seller_id = int(rec.get("seller_id", 0))
        if seller_id == buyer_id:
            return await cinnamon_send(interaction, "You cannot buy your own listing.", ephemeral=True)
        locks = _market_member_locks(gid, [buyer_id, seller_id])
        await _market_acquire(locks)
        try:
            rec = root.get(str(listing_id))
            if not isinstance(rec, dict) or rec.get("status") != "active":
                return await cinnamon_send(interaction, "That listing was just purchased or cancelled.", ephemeral=True)
            seller_id = int(rec["seller_id"])
            item_id, quantity, price = str(rec["item_id"]), int(rec["quantity"]), int(rec["total_price"])
            buyer_inv, seller_inv = economy_inventory_for(gid, buyer_id), economy_inventory_for(gid, seller_id)
            buyer_balance, seller_balance = economy_balance(gid, buyer_id), economy_balance(gid, seller_id)
            if buyer_balance < price:
                return await cinnamon_send(interaction, f"You need {price:,} Catnip; your balance is {buyer_balance:,}.", ephemeral=True)
            old_records = _market_copy.deepcopy(root)
            snapshots = {buyer_id: (buyer_balance, dict(buyer_inv)), seller_id: (seller_balance, dict(seller_inv))}
            economy_balances[(gid, buyer_id)] = buyer_balance - price
            economy_balances[(gid, seller_id)] = seller_balance + price
            buyer_inv[item_id] = int(buyer_inv.get(item_id, 0)) + quantity
            rec["status"], rec["buyer_id"] = "sold", buyer_id
            rec["sold_at"] = int(_market_time.time())
            if not await _market_persist_or_rollback(gid, snapshots, root, old_records):
                return await cinnamon_send(interaction, "The purchase couldn't be saved. No Catnip or items changed.", ephemeral=True)
        finally:
            _market_release(locks)
    await economy_log(gid, title="Marketplace purchase completed", fields=[
        ("Buyer", f"{interaction.user} ({buyer_id})"), ("Seller ID", seller_id),
        ("Item", ECONOMY_ITEMS.get(item_id, {}).get("name", item_id)),
        ("Quantity", quantity), ("Price", f"{price:,} Catnip"), ("Listing ID", listing_id),
    ])
    await cinnamon_send(interaction, f"Purchased {quantity}× {ECONOMY_ITEMS.get(item_id, {}).get('name', item_id)} for {price:,} Catnip.", ephemeral=True)

@market_group.command(name="cancel", description="Cancel your listing and return its escrowed items")
@app_commands.guild_only()
@app_commands.describe(listing_id="Choose one of your active listings")
@app_commands.autocomplete(listing_id=_market_listing_autocomplete)
async def market_cancel(interaction: discord.Interaction, listing_id: str):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _market_lock(gid):
        locks = _market_member_locks(gid, [uid])
        await _market_acquire(locks)
        try:
            root = _market_root(_MARKET_KEY, gid)
            rec = root.get(str(listing_id))
            if not isinstance(rec, dict) or rec.get("status") != "active" or int(rec.get("seller_id", 0)) != uid:
                return await cinnamon_send(interaction, "That isn't one of your active listings.", ephemeral=True)
            old_records = _market_copy.deepcopy(root)
            inv = economy_inventory_for(gid, uid)
            snapshots = {uid: (economy_balance(gid, uid), dict(inv))}
            item_id, qty = str(rec["item_id"]), int(rec["quantity"])
            inv[item_id] = int(inv.get(item_id, 0)) + qty
            rec["status"] = "cancelled"
            rec["cancelled_at"] = int(_market_time.time())
            if not await _market_persist_or_rollback(gid, snapshots, root, old_records):
                return await cinnamon_send(interaction, "Couldn't save cancellation; the listing remains active.", ephemeral=True)
        finally:
            _market_release(locks)
    await cinnamon_send(interaction, f"Cancelled listing {listing_id} and returned {qty}× {ECONOMY_ITEMS[item_id]['name']}.", ephemeral=True)

bot.tree.add_command(market_group)

trade_group = app_commands.Group(name="trade", description="Offer and accept direct member-to-member item trades")

@trade_group.command(name="offer", description="Offer an item and/or Catnip in exchange for another item or Catnip")
@app_commands.guild_only()
@app_commands.describe(member="Member to trade with", offer_item="Item you are offering",
    offer_quantity="Quantity of your offered item", offer_catnip="Catnip you are offering",
    request_item="Item you want", request_quantity="Quantity you want", request_catnip="Catnip you want")
@app_commands.autocomplete(offer_item=_market_item_autocomplete, request_item=_market_item_autocomplete)
async def trade_offer(interaction: discord.Interaction, member: discord.Member,
                      offer_item: str | None = None,
                      offer_quantity: app_commands.Range[int, 0, 99] = 0,
                      offer_catnip: app_commands.Range[int, 0, 10000000] = 0,
                      request_item: str | None = None,
                      request_quantity: app_commands.Range[int, 0, 99] = 0,
                      request_catnip: app_commands.Range[int, 0, 10000000] = 0):
    gid, sender_id, recipient_id = interaction.guild.id, interaction.user.id, member.id
    offered_id, requested_id = str(offer_item or "").strip().lower(), str(request_item or "").strip().lower()
    if member.bot or recipient_id == sender_id:
        return await cinnamon_send(interaction, "Choose another human member in this server.", ephemeral=True)
    if not (offer_catnip or (offered_id and offer_quantity)) or not (request_catnip or (requested_id and request_quantity)):
        return await cinnamon_send(interaction, "Both sides of the trade must include an item or Catnip.", ephemeral=True)
    if (offered_id and not _market_item_ok(offered_id)) or (requested_id and not _market_item_ok(requested_id)):
        return await cinnamon_send(interaction, "Services and items without resale eligibility cannot be traded.", ephemeral=True)
    async with _market_lock(gid):
        locks = _market_member_locks(gid, [sender_id, recipient_id])
        await _market_acquire(locks)
        try:
            inv = economy_inventory_for(gid, sender_id)
            balance = economy_balance(gid, sender_id)
            if offered_id and int(inv.get(offered_id, 0)) < offer_quantity:
                return await cinnamon_send(interaction, "You don't own enough of the offered item.", ephemeral=True)
            if balance < offer_catnip:
                return await cinnamon_send(interaction, "You don't have enough Catnip for that offer.", ephemeral=True)
            trades = _market_root(_TRADE_KEY, gid)
            old_records = _market_copy.deepcopy(trades)
            snapshots = {sender_id: (balance, dict(inv))}
            if offered_id and offer_quantity:
                inv[offered_id] = int(inv[offered_id]) - offer_quantity
                if inv[offered_id] <= 0: inv.pop(offered_id, None)
            economy_balances[(gid, sender_id)] = balance - offer_catnip
            offer_id = _market_uuid.uuid4().hex[:8]
            trades[offer_id] = {
                "sender_id": sender_id, "recipient_id": recipient_id,
                "offer_item": offered_id, "offer_quantity": int(offer_quantity),
                "offer_catnip": int(offer_catnip), "request_item": requested_id,
                "request_quantity": int(request_quantity), "request_catnip": int(request_catnip),
                "status": "pending", "created_at": int(_market_time.time()),
                "expires_at": int(_market_time.time()) + 172800,
            }
            if not await _market_persist_or_rollback(gid, snapshots, trades, old_records):
                return await cinnamon_send(interaction, "Couldn't save the offer; your escrow was restored.", ephemeral=True)
        finally:
            _market_release(locks)
    await cinnamon_send(interaction, f"Trade offer {offer_id} sent to {member.mention}. Your offered items and Catnip are held until the offer is accepted, declined or expires.", ephemeral=True)

async def _trade_return_escrow(gid, offer_id, status):
    trades = _market_root(_TRADE_KEY, gid)
    rec = trades.get(offer_id)
    if not isinstance(rec, dict) or rec.get("status") != "pending":
        return False
    sender_id = int(rec["sender_id"])
    locks = _market_member_locks(gid, [sender_id])
    await _market_acquire(locks)
    try:
        rec = trades.get(offer_id)
        if not isinstance(rec, dict) or rec.get("status") != "pending":
            return False
        old_records = _market_copy.deepcopy(trades)
        inv = economy_inventory_for(gid, sender_id)
        balance = economy_balance(gid, sender_id)
        snapshots = {sender_id: (balance, dict(inv))}
        item_id, qty = str(rec.get("offer_item", "")), int(rec.get("offer_quantity", 0))
        if item_id and qty:
            inv[item_id] = int(inv.get(item_id, 0)) + qty
        economy_balances[(gid, sender_id)] = balance + int(rec.get("offer_catnip", 0))
        rec["status"], rec["closed_at"] = status, int(_market_time.time())
        return await _market_persist_or_rollback(gid, snapshots, trades, old_records)
    finally:
        _market_release(locks)

@trade_group.command(name="accept", description="Accept a trade offer sent to you")
@app_commands.guild_only()
async def trade_accept(interaction: discord.Interaction, offer_id: str):
    gid, recipient_id = interaction.guild.id, interaction.user.id
    async with _market_lock(gid):
        trades = _market_root(_TRADE_KEY, gid)
        rec = trades.get(str(offer_id))
        if not isinstance(rec, dict) or rec.get("status") != "pending" or int(rec.get("recipient_id", 0)) != recipient_id:
            return await cinnamon_send(interaction, "That pending offer isn't addressed to you.", ephemeral=True)
        if int(rec.get("expires_at", 0)) <= int(_market_time.time()):
            await _trade_return_escrow(gid, str(offer_id), "expired")
            return await cinnamon_send(interaction, "That offer expired and the sender's escrow was returned.", ephemeral=True)
        sender_id = int(rec["sender_id"])
        locks = _market_member_locks(gid, [sender_id, recipient_id])
        await _market_acquire(locks)
        try:
            rec = trades.get(str(offer_id))
            if not isinstance(rec, dict) or rec.get("status") != "pending":
                return await cinnamon_send(interaction, "That offer is no longer pending.", ephemeral=True)
            sinv, rinv = economy_inventory_for(gid, sender_id), economy_inventory_for(gid, recipient_id)
            sbal, rbal = economy_balance(gid, sender_id), economy_balance(gid, recipient_id)
            req_item, req_qty = str(rec.get("request_item", "")), int(rec.get("request_quantity", 0))
            req_catnip = int(rec.get("request_catnip", 0))
            if req_item and int(rinv.get(req_item, 0)) < req_qty:
                return await cinnamon_send(interaction, "You don't own enough of the requested item.", ephemeral=True)
            if rbal < req_catnip:
                return await cinnamon_send(interaction, "You don't have enough Catnip to accept this trade.", ephemeral=True)
            old_records = _market_copy.deepcopy(trades)
            snapshots = {sender_id: (sbal, dict(sinv)), recipient_id: (rbal, dict(rinv))}
            if req_item and req_qty:
                rinv[req_item] = int(rinv[req_item]) - req_qty
                if rinv[req_item] <= 0: rinv.pop(req_item, None)
                sinv[req_item] = int(sinv.get(req_item, 0)) + req_qty
            offer_item, offer_qty = str(rec.get("offer_item", "")), int(rec.get("offer_quantity", 0))
            if offer_item and offer_qty:
                rinv[offer_item] = int(rinv.get(offer_item, 0)) + offer_qty
            offer_catnip = int(rec.get("offer_catnip", 0))
            economy_balances[(gid, sender_id)] = sbal + req_catnip
            economy_balances[(gid, recipient_id)] = rbal - req_catnip + offer_catnip
            rec["status"], rec["accepted_at"] = "accepted", int(_market_time.time())
            if not await _market_persist_or_rollback(gid, snapshots, trades, old_records):
                return await cinnamon_send(interaction, "Couldn't save the trade. Both sides were restored.", ephemeral=True)
        finally:
            _market_release(locks)
    await economy_log(gid, title="Member trade completed", fields=[
        ("Offer ID", offer_id), ("Sender ID", sender_id), ("Recipient", f"{interaction.user} ({recipient_id})")])
    await cinnamon_send(interaction, "Trade accepted. Both sides' items and Catnip have been transferred.", ephemeral=True)

@trade_group.command(name="decline", description="Decline a trade offer sent to you")
@app_commands.guild_only()
async def trade_decline(interaction: discord.Interaction, offer_id: str):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _market_lock(gid):
        rec = _market_root(_TRADE_KEY, gid).get(str(offer_id))
        if not isinstance(rec, dict) or rec.get("status") != "pending" or int(rec.get("recipient_id", 0)) != uid:
            return await cinnamon_send(interaction, "That pending offer isn't addressed to you.", ephemeral=True)
        if not await _trade_return_escrow(gid, str(offer_id), "declined"):
            return await cinnamon_send(interaction, "Couldn't save the decline; the offer remains pending.", ephemeral=True)
    await cinnamon_send(interaction, "Trade declined. The sender's escrow was returned.", ephemeral=True)

@trade_group.command(name="cancel", description="Cancel your own pending trade offer")
@app_commands.guild_only()
async def trade_cancel(interaction: discord.Interaction, offer_id: str):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _market_lock(gid):
        rec = _market_root(_TRADE_KEY, gid).get(str(offer_id))
        if not isinstance(rec, dict) or rec.get("status") != "pending" or int(rec.get("sender_id", 0)) != uid:
            return await cinnamon_send(interaction, "That isn't your pending offer.", ephemeral=True)
        if not await _trade_return_escrow(gid, str(offer_id), "cancelled"):
            return await cinnamon_send(interaction, "Couldn't save cancellation; the offer remains pending.", ephemeral=True)
    await cinnamon_send(interaction, "Trade cancelled. Your escrow was returned.", ephemeral=True)

bot.tree.add_command(trade_group)

@bot.tree.command(name="collection", description="View the items you have collected in this server")
@app_commands.guild_only()
async def economy_collection(interaction: discord.Interaction, page: app_commands.Range[int, 1, 20] = 1):
    inv = economy_inventory_for(interaction.guild.id, interaction.user.id)
    entries = [(k, int(v)) for k, v in inv.items() if int(v) > 0 and k in ECONOMY_ITEMS]
    entries.sort(key=lambda x: (str(ECONOMY_ITEMS[x[0]].get("category", "")), str(ECONOMY_ITEMS[x[0]].get("name", x[0])).lower()))
    pages = max(1, (len(entries) + 9) // 10)
    page = min(int(page), pages)
    selected = entries[(page - 1) * 10:page * 10]
    lines = [f"{ECONOMY_ITEMS[k].get('emoji', '📦')} {ECONOMY_ITEMS[k].get('name', k)} ×{q}" for k, q in selected]
    e = discord.Embed(title="📚 Your Cinnamon Collection",
        description="\n".join(lines) or "Your collection is empty. Visit /economy shop to get started.",
        color=0xE8A05A)
    e.set_footer(text=f"Page {page}/{pages} • {len(entries)} owned item types")
    await interaction.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="wishlist", description="Manage your personal Cinnamon item wishlist")
@app_commands.guild_only()
@app_commands.choices(action=[app_commands.Choice(name="View wishlist", value="view"),
    app_commands.Choice(name="Add item", value="add"), app_commands.Choice(name="Remove item", value="remove")])
@app_commands.describe(action="Choose an action", item="Item to add or remove")
async def economy_wishlist(interaction: discord.Interaction, action: app_commands.Choice[str], item: str | None = None):
    gid, uid = interaction.guild.id, interaction.user.id
    root = _market_root(_WISHLIST_KEY, gid)
    key, values = str(uid), root.setdefault(str(uid), [])
    if action.value in {"add", "remove"}:
        item_id = str(item or "").strip().lower()
        if item_id not in ECONOMY_ITEMS:
            return await cinnamon_send(interaction, "Choose a valid catalogue item.", ephemeral=True)
        before = list(values)
        if action.value == "add":
            if item_id not in values:
                if len(values) >= 25:
                    return await cinnamon_send(interaction, "Your wishlist can contain up to 25 items.", ephemeral=True)
                values.append(item_id)
        else:
            if item_id not in values:
                return await cinnamon_send(interaction, "That item isn't on your wishlist.", ephemeral=True)
            values.remove(item_id)
        if not await bd_save_data():
            root[key] = before
            return await cinnamon_send(interaction, "Couldn't save your wishlist change.", ephemeral=True)
        result = "Added to your wishlist." if action.value == "add" else "Removed from your wishlist."
    else:
        result = "\n".join(f"• {ECONOMY_ITEMS.get(x, {}).get('name', x)}" for x in values) or "Your wishlist is empty."
    await cinnamon_send(interaction, result[:1800], ephemeral=True)


# Auctions: bids are reserved in Catnip until the auction resolves.
_AUCTION_KEY = "player_auctions_v1"

async def _auction_finalize_locked(gid, auction_id):
    auctions = _market_root(_AUCTION_KEY, gid)
    rec = auctions.get(str(auction_id))
    if not isinstance(rec, dict) or rec.get("status") != "active":
        return False
    seller_id = int(rec["seller_id"])
    bidder_id = int(rec.get("highest_bidder_id") or 0)
    users = [seller_id] + ([bidder_id] if bidder_id else [])
    locks = _market_member_locks(gid, users)
    await _market_acquire(locks)
    try:
        rec = auctions.get(str(auction_id))
        if not isinstance(rec, dict) or rec.get("status") != "active":
            return False
        old_records = _market_copy.deepcopy(auctions)
        item_id, qty = str(rec["item_id"]), int(rec["quantity"])
        seller_inv = economy_inventory_for(gid, seller_id)
        seller_balance = economy_balance(gid, seller_id)
        snapshots = {seller_id: (seller_balance, dict(seller_inv))}
        if bidder_id:
            bidder_inv = economy_inventory_for(gid, bidder_id)
            bidder_balance = economy_balance(gid, bidder_id)
            snapshots[bidder_id] = (bidder_balance, dict(bidder_inv))
            bidder_inv[item_id] = int(bidder_inv.get(item_id, 0)) + qty
            economy_balances[(gid, seller_id)] = seller_balance + int(rec.get("highest_bid", 0))
            rec["winner_id"] = bidder_id
            rec["status"] = "sold"
        else:
            seller_inv[item_id] = int(seller_inv.get(item_id, 0)) + qty
            rec["status"] = "ended_no_bids"
        rec["closed_at"] = int(_market_time.time())
        if not await _market_persist_or_rollback(gid, snapshots, auctions, old_records):
            return False
        return True
    finally:
        _market_release(locks)

@tasks.loop(minutes=1)
async def _auction_expiry_loop():
    now = int(_market_time.time())
    for guild_key, auctions in list(advanced_features_data.get(_AUCTION_KEY, {}).items()):
        if not str(guild_key).isdigit() or not isinstance(auctions, dict):
            continue
        gid = int(guild_key)
        due = [aid for aid, rec in auctions.items()
               if isinstance(rec, dict) and rec.get("status") == "active"
               and int(rec.get("ends_at", 0)) <= now]
        for auction_id in due:
            async with _market_lock(gid):
                if await _auction_finalize_locked(gid, auction_id):
                    try:
                        await economy_log(gid, title="Auction ended", fields=[
                            ("Auction ID", auction_id),
                            ("Winner ID", str(auctions.get(auction_id, {}).get("winner_id", "No bids"))),
                            ("Item", str(auctions.get(auction_id, {}).get("item_id", "unknown"))),
                        ])
                    except Exception:
                        log.exception("Auction completion log failed")

@bot.listen("on_ready")
async def _auction_start_expiry_loop():
    if not _auction_expiry_loop.is_running():
        _auction_expiry_loop.start()

async def _auction_id_autocomplete(interaction, current):
    if not interaction.guild:
        return []
    root = _market_root(_AUCTION_KEY, interaction.guild.id)
    query, results = str(current or "").lower(), []
    for aid, rec in root.items():
        if rec.get("status") != "active":
            continue
        item = ECONOMY_ITEMS.get(rec.get("item_id"), {})
        label = f"{item.get('name', rec.get('item_id'))} • bid {int(rec.get('highest_bid', 0)):,} • #{aid}"
        if query in label.lower() or query in aid.lower():
            results.append(app_commands.Choice(name=label[:100], value=aid))
    return results[:25]

auction_group = app_commands.Group(name="auction", description="Run Catnip auctions for eligible inventory items")

@auction_group.command(name="create", description="Auction an item from your inventory")
@app_commands.guild_only()
@app_commands.describe(item="Item to auction", quantity="Quantity to escrow",
                       starting_bid="Minimum opening bid in Catnip", duration_hours="Auction length, 1–72 hours")
@app_commands.autocomplete(item=_market_item_autocomplete)
async def auction_create(interaction: discord.Interaction, item: str,
                         quantity: app_commands.Range[int, 1, 99],
                         starting_bid: app_commands.Range[int, 1, 10000000],
                         duration_hours: app_commands.Range[int, 1, 72] = 24):
    gid, uid, item_id = interaction.guild.id, interaction.user.id, str(item).strip().lower()
    if not _market_item_ok(item_id):
        return await cinnamon_send(interaction, "That item cannot be auctioned.", ephemeral=True)
    async with _market_lock(gid):
        locks = _market_member_locks(gid, [uid])
        await _market_acquire(locks)
        try:
            inv = economy_inventory_for(gid, uid)
            owned = int(inv.get(item_id, 0))
            if owned < quantity:
                return await cinnamon_send(interaction, "You don't own enough of that item.", ephemeral=True)
            auctions = _market_root(_AUCTION_KEY, gid)
            old_records = _market_copy.deepcopy(auctions)
            snapshots = {uid: (economy_balance(gid, uid), dict(inv))}
            inv[item_id] = owned - quantity
            if inv[item_id] <= 0: inv.pop(item_id, None)
            auction_id = _market_uuid.uuid4().hex[:8]
            now = int(_market_time.time())
            auctions[auction_id] = {
                "seller_id": uid, "item_id": item_id, "quantity": int(quantity),
                "starting_bid": int(starting_bid), "highest_bid": 0,
                "highest_bidder_id": 0, "status": "active",
                "created_at": now, "ends_at": now + int(duration_hours) * 3600,
            }
            if not await _market_persist_or_rollback(gid, snapshots, auctions, old_records):
                return await cinnamon_send(interaction, "Couldn't save the auction; your item was returned.", ephemeral=True)
        finally:
            _market_release(locks)
    await cinnamon_send(interaction, f"Auction {auction_id} opened for {quantity}× {ECONOMY_ITEMS[item_id]['name']}. Opening bid: {starting_bid:,} Catnip. It ends in {duration_hours} hour(s).", ephemeral=True)

@auction_group.command(name="list", description="View active auctions")
@app_commands.guild_only()
async def auction_list(interaction: discord.Interaction):
    gid = interaction.guild.id
    async with _market_lock(gid):
        auctions = _market_root(_AUCTION_KEY, gid)
        due = [aid for aid, rec in auctions.items()
               if isinstance(rec, dict) and rec.get("status") == "active"
               and int(rec.get("ends_at", 0)) <= int(_market_time.time())]
        for aid in due:
            await _auction_finalize_locked(gid, aid)
        active = [(aid, rec) for aid, rec in auctions.items() if rec.get("status") == "active"]
    lines = []
    for aid, rec in active[:20]:
        item = ECONOMY_ITEMS.get(rec.get("item_id"), {})
        bid = max(int(rec.get("starting_bid", 0)), int(rec.get("highest_bid", 0)) + 1)
        lines.append(f"#{aid} • {item.get('emoji', '📦')} {item.get('name', rec.get('item_id'))} ×{rec.get('quantity', 0)}\nCurrent bid: {int(rec.get('highest_bid', 0)):,} • Next bid: {bid:,} Catnip")
    e = discord.Embed(title="🔨 Cinnamon Auctions",
        description="\n\n".join(lines) or "No active auctions.",
        color=0xE8A05A)
    await interaction.response.send_message(embed=e, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

@auction_group.command(name="bid", description="Place a Catnip bid on an active auction")
@app_commands.guild_only()
@app_commands.describe(auction_id="Choose an active auction", amount="Your total bid in Catnip")
@app_commands.autocomplete(auction_id=_auction_id_autocomplete)
async def auction_bid(interaction: discord.Interaction, auction_id: str,
                      amount: app_commands.Range[int, 1, 10000000]):
    gid, bidder_id = interaction.guild.id, interaction.user.id
    async with _market_lock(gid):
        auctions = _market_root(_AUCTION_KEY, gid)
        rec = auctions.get(str(auction_id))
        if not isinstance(rec, dict) or rec.get("status") != "active":
            return await cinnamon_send(interaction, "That auction isn't active.", ephemeral=True)
        seller_id = int(rec["seller_id"])
        previous_bidder = int(rec.get("highest_bidder_id") or 0)
        if bidder_id == seller_id:
            return await cinnamon_send(interaction, "You cannot bid on your own auction.", ephemeral=True)
        if int(rec.get("ends_at", 0)) <= int(_market_time.time()):
            await _auction_finalize_locked(gid, str(auction_id))
            return await cinnamon_send(interaction, "That auction has ended.", ephemeral=True)
        minimum = max(int(rec.get("starting_bid", 0)), int(rec.get("highest_bid", 0)) + 1)
        if amount < minimum:
            return await cinnamon_send(interaction, f"The next bid must be at least {minimum:,} Catnip.", ephemeral=True)
        users = [bidder_id] + ([previous_bidder] if previous_bidder else [])
        locks = _market_member_locks(gid, users)
        await _market_acquire(locks)
        try:
            rec = auctions.get(str(auction_id))
            if not isinstance(rec, dict) or rec.get("status") != "active":
                return await cinnamon_send(interaction, "That auction has already ended.", ephemeral=True)
            previous_bidder = int(rec.get("highest_bidder_id") or 0)
            old_bid = int(rec.get("highest_bid", 0))
            balance = economy_balance(gid, bidder_id)
            if balance < amount:
                return await cinnamon_send(interaction, f"You need {amount:,} Catnip; your balance is {balance:,}.", ephemeral=True)
            old_records = _market_copy.deepcopy(auctions)
            bidder_inv = economy_inventory_for(gid, bidder_id)
            snapshots = {bidder_id: (balance, dict(bidder_inv))}
            if previous_bidder and previous_bidder != bidder_id:
                prev_inv = economy_inventory_for(gid, previous_bidder)
                prev_balance = economy_balance(gid, previous_bidder)
                snapshots[previous_bidder] = (prev_balance, dict(prev_inv))
                economy_balances[(gid, previous_bidder)] = prev_balance + old_bid
            elif previous_bidder == bidder_id:
                # Re-bidding releases the member's previous escrow only for
                # the new balance calculation. Keep the original snapshot so
                # a failed save restores the exact pre-click balance.
                balance += old_bid
            economy_balances[(gid, bidder_id)] = balance - amount
            rec["highest_bid"], rec["highest_bidder_id"] = int(amount), bidder_id
            rec["last_bid_at"] = int(_market_time.time())
            if not await _market_persist_or_rollback(gid, snapshots, auctions, old_records):
                return await cinnamon_send(interaction, "Couldn't save your bid; all balances were restored.", ephemeral=True)
        finally:
            _market_release(locks)
    await economy_log(gid, title="Auction bid placed", fields=[
        ("Auction ID", auction_id), ("Bidder", f"{interaction.user} ({bidder_id})"),
        ("Bid", f"{amount:,} Catnip")])
    await cinnamon_send(interaction, f"Your bid of {amount:,} Catnip is now leading auction {auction_id}.", ephemeral=True)

@auction_group.command(name="cancel", description="Cancel your auction if nobody has bid")
@app_commands.guild_only()
@app_commands.autocomplete(auction_id=_auction_id_autocomplete)
async def auction_cancel(interaction: discord.Interaction, auction_id: str):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _market_lock(gid):
        auctions = _market_root(_AUCTION_KEY, gid)
        rec = auctions.get(str(auction_id))
        if not isinstance(rec, dict) or rec.get("status") != "active" or int(rec.get("seller_id", 0)) != uid:
            return await cinnamon_send(interaction, "That isn't your active auction.", ephemeral=True)
        if int(rec.get("highest_bid", 0)) > 0:
            return await cinnamon_send(interaction, "An auction with bids cannot be cancelled.", ephemeral=True)
        locks = _market_member_locks(gid, [uid])
        await _market_acquire(locks)
        try:
            old_records = _market_copy.deepcopy(auctions)
            inv = economy_inventory_for(gid, uid)
            snapshots = {uid: (economy_balance(gid, uid), dict(inv))}
            item_id, qty = str(rec["item_id"]), int(rec["quantity"])
            inv[item_id] = int(inv.get(item_id, 0)) + qty
            rec["status"] = "cancelled"
            if not await _market_persist_or_rollback(gid, snapshots, auctions, old_records):
                return await cinnamon_send(interaction, "Couldn't save cancellation; your auction remains active.", ephemeral=True)
        finally:
            _market_release(locks)
    await cinnamon_send(interaction, f"Auction cancelled. Returned {qty}× {ECONOMY_ITEMS[item_id]['name']}.", ephemeral=True)

bot.tree.add_command(auction_group)
