"""Free-entry community raffles and cosmetic accessories for collectible pets."""
import asyncio as _f_asyncio
import copy as _f_copy
import random as _f_random
import time as _f_time

_LOTTERY_KEY = "community_lottery_v1"
_FEATURE_LOCKS = {}
_PET_ACCESSORIES = {
    "red_scarf": {"name": "Red Scarf", "emoji": "🧣", "price": 350},
    "golden_bell": {"name": "Golden Bell", "emoji": "🔔", "price": 600},
    "flower_crown": {"name": "Flower Crown", "emoji": "🌼", "price": 850},
    "tiny_cape": {"name": "Tiny Cape", "emoji": "🦸", "price": 1200},
    "star_glasses": {"name": "Star Glasses", "emoji": "⭐", "price": 1500},
}

def _feature_lock(guild_id):
    return _FEATURE_LOCKS.setdefault(int(guild_id), _f_asyncio.Lock())

def _lottery_guild(guild_id):
    return advanced_features_data.setdefault(_LOTTERY_KEY, {}).setdefault(str(int(guild_id)), {})

async def _lottery_finish(guild_id, cancelled=False):
    async with _feature_lock(guild_id):
        state = _lottery_guild(guild_id)
        raffle = state.get("active")
        if not isinstance(raffle, dict):
            return False
        if not cancelled and int(raffle.get("ends_at", 0)) > int(_f_time.time()):
            return False
        old_state = _f_copy.deepcopy(state)
        sponsor_id = int(raffle.get("sponsor_id", 0))
        prize = int(raffle.get("prize_catnip", 0))
        entries = sorted({int(uid) for uid in raffle.get("entries", [])})
        winner_id = None if cancelled or not entries else _f_random.SystemRandom().choice(entries)
        sponsor_key = (int(guild_id), sponsor_id)
        winner_key = (int(guild_id), winner_id) if winner_id else None
        old_sponsor = economy_balances.get(sponsor_key)
        old_winner = economy_balances.get(winner_key) if winner_key else None
        if winner_id:
            economy_ensure_balance(guild_id, winner_id)
            economy_balances[winner_key] = economy_balance(guild_id, winner_id) + prize
        else:
            economy_ensure_balance(guild_id, sponsor_id)
            economy_balances[sponsor_key] = economy_balance(guild_id, sponsor_id) + prize
        raffle["status"] = "cancelled" if cancelled else "completed"
        raffle["winner_id"] = winner_id
        raffle["completed_at"] = int(_f_time.time())
        state["last"] = _f_copy.deepcopy(raffle)
        state.pop("active", None)
        try:
            saved = await bd_save_data()
        except Exception:
            saved = False
            if "log" in globals():
                log.exception("Community raffle settlement failed for guild %s", guild_id)
        if not saved:
            state.clear()
            state.update(old_state)
            if old_sponsor is None:
                economy_balances.pop(sponsor_key, None)
            else:
                economy_balances[sponsor_key] = old_sponsor
            if winner_key:
                if old_winner is None:
                    economy_balances.pop(winner_key, None)
                else:
                    economy_balances[winner_key] = old_winner
            return False
    await economy_log(guild_id, title="Community raffle settled",
        fields=[("Winner", str(winner_id) if winner_id else "No winner"),
                ("Prize", f"{prize:,} Catnip"), ("Entries", str(len(entries)))])
    return True

@tasks.loop(minutes=1)
async def _community_lottery_loop():
    now = int(_f_time.time())
    for guild_id, state in list(advanced_features_data.get(_LOTTERY_KEY, {}).items()):
        raffle = state.get("active") if isinstance(state, dict) else None
        if isinstance(raffle, dict) and int(raffle.get("ends_at", 0)) <= now:
            await _lottery_finish(int(guild_id))

@_community_lottery_loop.before_loop
async def _community_lottery_before_loop():
    await bot.wait_until_ready()

@bot.listen("on_ready")
async def _community_lottery_start():
    if not _community_lottery_loop.is_running():
        _community_lottery_loop.start()

lottery_group = app_commands.Group(name="lottery", description="Free-entry, Catnip-sponsored community raffles")

@lottery_group.command(name="start", description="Admin: sponsor a free-entry Catnip raffle")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(prize_catnip="Catnip prize escrowed from your balance", duration_hours="Entry window in hours (1–168)")
async def lottery_start(interaction: discord.Interaction,
                        prize_catnip: app_commands.Range[int, 1, 1000000],
                        duration_hours: app_commands.Range[int, 1, 168] = 24):
    gid, sponsor_id = interaction.guild.id, interaction.user.id
    async with _feature_lock(gid):
        state = _lottery_guild(gid)
        if isinstance(state.get("active"), dict):
            return await cinnamon_send(interaction, "A raffle is already running in this server.", ephemeral=True)
        balance = economy_balance(gid, sponsor_id)
        if balance < prize_catnip:
            return await cinnamon_send(interaction, f"You need {prize_catnip:,} Catnip; your balance is {balance:,}.", ephemeral=True)
        key = (gid, sponsor_id)
        old_balance = economy_balances.get(key)
        economy_ensure_balance(gid, sponsor_id)
        economy_balances[key] = balance - int(prize_catnip)
        state["active"] = {
            "sponsor_id": sponsor_id, "prize_catnip": int(prize_catnip),
            "created_at": int(_f_time.time()),
            "ends_at": int(_f_time.time()) + int(duration_hours) * 3600,
            "entries": [], "status": "active",
        }
        try:
            saved = await bd_save_data()
        except Exception:
            saved = False
        if not saved:
            state.pop("active", None)
            if old_balance is None:
                economy_balances.pop(key, None)
            else:
                economy_balances[key] = old_balance
            return await cinnamon_send(interaction, "I couldn't save the raffle. No Catnip was kept.", ephemeral=True)
    await economy_log(gid, title="Community raffle started",
        fields=[("Sponsor", str(sponsor_id)), ("Prize", f"{int(prize_catnip):,} Catnip"),
                ("Duration", f"{int(duration_hours)} hours"), ("Entry cost", "Free")])
    await cinnamon_send(interaction, f"A free-entry raffle is open! Prize: {int(prize_catnip):,} Catnip. Use /lottery enter. Closes in {int(duration_hours)} hour(s).")

@lottery_group.command(name="enter", description="Enter the current free community raffle")
@app_commands.guild_only()
async def lottery_enter(interaction: discord.Interaction):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _feature_lock(gid):
        raffle = _lottery_guild(gid).get("active")
        if not isinstance(raffle, dict) or int(raffle.get("ends_at", 0)) <= int(_f_time.time()):
            return await cinnamon_send(interaction, "There isn't an open raffle right now.", ephemeral=True)
        entries = raffle.setdefault("entries", [])
        if uid in entries:
            return await cinnamon_send(interaction, "You're already entered. Each member gets one free entry.", ephemeral=True)
        before = list(entries)
        entries.append(uid)
        try:
            saved = await bd_save_data()
        except Exception:
            saved = False
        if not saved:
            raffle["entries"] = before
            return await cinnamon_send(interaction, "I couldn't save your entry. Please try again.", ephemeral=True)
        count = len(entries)
    await cinnamon_send(interaction, f"Your free entry is saved. Total entries: {count}.", ephemeral=True)

@lottery_group.command(name="status", description="Check the current raffle and your entry")
@app_commands.guild_only()
async def lottery_status(interaction: discord.Interaction):
    state = _lottery_guild(interaction.guild.id)
    raffle = state.get("active")
    if not isinstance(raffle, dict):
        last = state.get("last")
        if isinstance(last, dict):
            winner = f"<@{int(last['winner_id'])}>" if last.get("winner_id") else "No winner"
            return await cinnamon_send(interaction, f"No raffle is open. Last result: {winner} · {int(last.get('prize_catnip', 0)):,} Catnip.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        return await cinnamon_send(interaction, "No raffle has been started in this server yet.", ephemeral=True)
    remaining = max(0, int(raffle.get("ends_at", 0)) - int(_f_time.time()))
    hours, minutes = divmod(remaining // 60, 60)
    entered = interaction.user.id in {int(uid) for uid in raffle.get("entries", [])}
    await cinnamon_send(interaction,
        f"Free-entry raffle · Prize: {int(raffle.get('prize_catnip', 0)):,} Catnip · "
        f"Entries: {len(raffle.get('entries', []))} · Time left: {hours}h {minutes}m · "
        f"Your entry: {'Entered' if entered else 'Not entered'}",
        ephemeral=True)

@lottery_group.command(name="cancel", description="Admin: cancel the raffle and refund its sponsor")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def lottery_cancel(interaction: discord.Interaction):
    if not isinstance(_lottery_guild(interaction.guild.id).get("active"), dict):
        return await cinnamon_send(interaction, "There isn't an active raffle to cancel.", ephemeral=True)
    if not await _lottery_finish(interaction.guild.id, cancelled=True):
        return await cinnamon_send(interaction, "I couldn't save the cancellation; the raffle remains active.", ephemeral=True)
    await cinnamon_send(interaction, "Raffle cancelled. The Catnip prize was returned to its sponsor.", ephemeral=True)

bot.tree.add_command(lottery_group)

pet_style_group = app_commands.Group(name="pet-style", description="Collect and equip cosmetic accessories for your active pet")

@pet_style_group.command(name="shop", description="Browse cosmetic pet accessories")
@app_commands.guild_only()
async def pet_style_shop(interaction: discord.Interaction):
    lines = [f"{v['emoji']} {v['name']} — {v['price']:,} Catnip · {k}" for k, v in _PET_ACCESSORIES.items()]
    await cinnamon_send(interaction, "\n".join(lines) + "\nBuy with /pet-style buy, then equip with /pet-style equip.", ephemeral=True)

@pet_style_group.command(name="buy", description="Buy a cosmetic accessory")
@app_commands.guild_only()
@app_commands.choices(accessory=[app_commands.Choice(name=f"{v['emoji']} {v['name']} · {v['price']:,} Catnip", value=k) for k, v in _PET_ACCESSORIES.items()])
async def pet_style_buy(interaction: discord.Interaction, accessory: app_commands.Choice[str]):
    gid, uid, item_id = interaction.guild.id, interaction.user.id, accessory.value
    data = _collectible_pet_user(gid, uid)
    owned = data.setdefault("accessories", [])
    if item_id in owned:
        return await cinnamon_send(interaction, "You already own that accessory.", ephemeral=True)
    item = _PET_ACCESSORIES[item_id]
    key = (gid, uid)
    balance = economy_balance(gid, uid)
    if balance < item["price"]:
        return await cinnamon_send(interaction, f"You need {item['price']:,} Catnip; your balance is {balance:,}.", ephemeral=True)
    old_balance, old_owned = economy_balances.get(key), list(owned)
    economy_ensure_balance(gid, uid)
    economy_balances[key] = balance - item["price"]
    owned.append(item_id)
    try:
        saved = await bd_save_data()
    except Exception:
        saved = False
    if not saved:
        owned[:] = old_owned
        if old_balance is None:
            economy_balances.pop(key, None)
        else:
            economy_balances[key] = old_balance
        return await cinnamon_send(interaction, "I couldn't save the purchase. No Catnip was kept.", ephemeral=True)
    await economy_log(gid, title="Pet accessory purchased",
        fields=[("Member", str(uid)), ("Accessory", item["name"]), ("Price", f"{item['price']:,} Catnip")])
    await cinnamon_send(interaction, f"Purchased {item['emoji']} {item['name']}. Equip it with /pet-style equip.", ephemeral=True)

@pet_style_group.command(name="equip", description="Equip an accessory on your active pet")
@app_commands.guild_only()
@app_commands.choices(accessory=[app_commands.Choice(name=f"{v['emoji']} {v['name']}", value=k) for k, v in _PET_ACCESSORIES.items()])
async def pet_style_equip(interaction: discord.Interaction, accessory: app_commands.Choice[str]):
    data = _collectible_pet_user(interaction.guild.id, interaction.user.id)
    pet = _collectible_pet_active(data)
    if not pet:
        return await cinnamon_send(interaction, "Discover and equip a pet first with ?work and ?pets equip.", ephemeral=True)
    if accessory.value not in data.get("accessories", []):
        return await cinnamon_send(interaction, "You don't own that accessory yet. Browse /pet-style shop.", ephemeral=True)
    old = pet.get("accessory_id")
    pet["accessory_id"] = accessory.value
    if not await bd_save_data():
        if old is None:
            pet.pop("accessory_id", None)
        else:
            pet["accessory_id"] = old
        return await cinnamon_send(interaction, "I couldn't save that equipment change.", ephemeral=True)
    item = _PET_ACCESSORIES[accessory.value]
    await cinnamon_send(interaction, f"Equipped {item['emoji']} {item['name']} on {pet.get('nickname') or pet.get('species', 'your pet')}.", ephemeral=True)

@pet_style_group.command(name="remove", description="Remove the accessory from your active pet")
@app_commands.guild_only()
async def pet_style_remove(interaction: discord.Interaction):
    data = _collectible_pet_user(interaction.guild.id, interaction.user.id)
    pet = _collectible_pet_active(data)
    if not pet:
        return await cinnamon_send(interaction, "You don't have an active pet.", ephemeral=True)
    old = pet.pop("accessory_id", None)
    if not old:
        return await cinnamon_send(interaction, "Your active pet isn't wearing an accessory.", ephemeral=True)
    if not await bd_save_data():
        pet["accessory_id"] = old
        return await cinnamon_send(interaction, "I couldn't save that equipment change.", ephemeral=True)
    await cinnamon_send(interaction, "Accessory removed and kept in your collection.", ephemeral=True)

bot.tree.add_command(pet_style_group)
