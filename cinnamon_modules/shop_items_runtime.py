"""Dashboard-configured item rules and /economy use execution.

Loaded into Cinnamon's shared runtime after economy.py. Item configuration lives
inside ECONOMY_ITEMS so existing economy snapshots persist it with the catalogue.
"""
import datetime as _shop_dt
import random as _shop_random
import time as _shop_time


def _shop_item_expired(item):
    raw = item.get("expires_at")
    if not raw:
        return False
    try:
        value = _shop_dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=_shop_dt.timezone.utc)
        return _shop_dt.datetime.now(_shop_dt.timezone.utc) >= value
    except (TypeError, ValueError):
        # Invalid dates fail closed: an item with a malformed expiry is unavailable.
        return True


def _shop_item_requirement_failure(guild, member, requirement):
    requirement = requirement if isinstance(requirement, dict) else {}
    balance_min = int(requirement.get("balance_min", 0) or 0)
    if balance_min < 0:
        return "This item's balance requirement is misconfigured."
    if economy_balance(guild.id, member.id) < balance_min:
        return f"You need at least **{balance_min:,} Catnip** to do this."

    roles_cfg = requirement.get("roles", {})
    if isinstance(roles_cfg, dict):
        role_ids = [int(x) for x in roles_cfg.get("ids", []) if str(x).isdigit()]
        mode = str(roles_cfg.get("mode", "all")).lower()
        owned_roles = {r.id for r in getattr(member, "roles", [])}
        hits = [rid in owned_roles for rid in role_ids]
        if role_ids and ((mode == "all" and not all(hits)) or
                         (mode == "any" and not any(hits)) or
                         (mode == "none" and any(hits))):
            return "You don't meet this item's role requirements."

    items_cfg = requirement.get("items", {})
    if isinstance(items_cfg, dict):
        entries = items_cfg.get("entries", {})
        if not isinstance(entries, dict):
            return "This item's inventory requirement is misconfigured."
        inventory = economy_inventory_for(guild.id, member.id)
        checks = []
        for key, amount in entries.items():
            if key not in ECONOMY_ITEMS:
                return "An item in this requirement no longer exists. Ask an administrator to edit it."
            try:
                amount = int(amount)
            except (TypeError, ValueError):
                return "This item's inventory requirement is misconfigured."
            if amount < 1:
                return "This item's inventory requirement is misconfigured."
            checks.append(int(inventory.get(key, 0)) >= amount)
        mode = str(items_cfg.get("mode", "all")).lower()
        if checks and ((mode == "all" and not all(checks)) or
                       (mode == "any" and not any(checks)) or
                       (mode == "none" and any(checks))):
            return "You don't have the required items."
    return None


def _shop_item_purchase_failure(guild, member, item_id, quantity=1):
    item = ECONOMY_ITEMS.get(item_id)
    if not isinstance(item, dict) or not item.get("shop_enabled", True):
        return "This item is not available in the shop."
    if _shop_item_expired(item):
        return "This item has expired and can no longer be purchased."
    if not item.get("stock_unlimited", True):
        if int(item.get("stock_quantity", 0)) < quantity:
            return "There isn't enough stock available."
    requirement_error = _shop_item_requirement_failure(
        guild, member, item.get("purchase_requirements", {}))
    if requirement_error:
        return requirement_error
    owned = int(economy_inventory_for(guild.id, member.id).get(item_id, 0))
    limit = int(item.get("max_per_person", 0))
    if limit and owned + quantity > limit:
        return f"This item has a limit of **{limit}** per member."
    return None


async def _shop_item_run_actions(interaction, item_id, trigger):
    item = ECONOMY_ITEMS.get(item_id, {})
    member = interaction.user
    guild = interaction.guild
    if guild is None:
        return
    trigger = "bought" if trigger == "bought" else "used"
    actions = item.get("actions", [])
    if not isinstance(actions, list):
        actions = []

    def matches(configured):
        return configured in (trigger, "both", "bought_or_used")

    selected = [a for a in actions if isinstance(a, dict) and matches(str(a.get("trigger", "both")).lower())]
    outcomes = item.get("random_outcomes", [])
    if isinstance(outcomes, list):
        eligible = [o for o in outcomes if isinstance(o, dict) and matches(str(o.get("trigger", "both")).lower())]
        if eligible:
            weights = []
            for outcome in eligible:
                try:
                    weights.append(max(0, float(outcome.get("weight", 0))))
                except (TypeError, ValueError):
                    weights.append(0)
            if sum(weights) > 0:
                chosen = _shop_random.choices(eligible, weights=weights, k=1)[0]
                outcome_actions = chosen.get("actions", [])
                if isinstance(outcome_actions, list):
                    selected.extend(a for a in outcome_actions if isinstance(a, dict))

    for action in selected:
        kind = str(action.get("type", "")).lower()
        try:
            if kind == "give_catnip":
                amount = int(action.get("amount", 0))
                if amount > 0:
                    economy_balances[(guild.id, member.id)] = economy_balance(guild.id, member.id) + amount
            elif kind == "give_item":
                reward_id = str(action.get("item_id", ""))
                amount = int(action.get("amount", 1))
                if reward_id in ECONOMY_ITEMS and 1 <= amount <= 999:
                    inv = economy_inventory_for(guild.id, member.id)
                    inv[reward_id] = int(inv.get(reward_id, 0)) + amount
            elif kind == "send_message":
                message = str(action.get("message", ""))[:1800]
                if message and interaction.channel:
                    await interaction.channel.send(message, allowed_mentions=discord.AllowedMentions.none())
            elif kind == "reply":
                message = str(action.get("message", ""))[:1800]
                if message:
                    await interaction.followup.send(message, ephemeral=True,
                        allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            log.exception("Shop item action failed: item=%s type=%s", item_id, kind)
    try:
        await bd_save_data()
    except Exception:
        log.exception("Could not persist shop item action rewards")


@economy_group.command(name="use", description="Use an item from your Cinnamon inventory")
@app_commands.describe(item="Choose an item from your inventory")
@app_commands.autocomplete(item=cinnamon_item_autocomplete)
@app_commands.guild_only()
async def economy_use_cmd(interaction: discord.Interaction, item: str):
    guild = interaction.guild
    user = interaction.user
    item_id = str(item).strip().lower()
    if item_id not in ECONOMY_ITEMS:
        matches = [key for key, value in ECONOMY_ITEMS.items()
                   if str(value.get("name", "")).lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if not isinstance(data, dict) or not data.get("usable", False):
        return await cinnamon_send(interaction, "That item cannot be used.", ephemeral=True)
    lock = _CINNAMON_SHOP_LOCKS.setdefault((guild.id, user.id), asyncio.Lock())
    async with lock:
        inv = economy_inventory_for(guild.id, user.id)
        owned = int(inv.get(item_id, 0))
        if owned < 1:
            return await cinnamon_send(interaction, "You don't have that item.", ephemeral=True)
        if _shop_item_expired(data):
            return await cinnamon_send(interaction, "This item has expired and can no longer be used.", ephemeral=True)
        failure = _shop_item_requirement_failure(guild, user, data.get("use_requirements", {}))
        if failure:
            return await cinnamon_send(interaction, failure, ephemeral=True)
        cooldown = max(0, int(data.get("use_cooldown_seconds", 0) or 0))
        cooldown_key = f"shop_item_use:{item_id}"
        remaining = economy_cooldown_remaining(guild.id, user.id, cooldown_key)
        if remaining:
            return await cinnamon_send(interaction, f"You can use this item again in **{remaining} seconds**.", ephemeral=True)
        old_inventory = dict(inv)
        old_cooldowns = dict(economy_cooldowns)
        old_balance = economy_balances.get((guild.id, user.id))
        if not data.get("reusable", False):
            inv[item_id] = owned - 1
            if inv[item_id] <= 0:
                inv.pop(item_id, None)
        if cooldown:
            economy_cooldowns[(guild.id, user.id, cooldown_key)] = _shop_time.time() + cooldown
        try:
            saved = await bd_save_data()
            if saved is False:
                raise RuntimeError("Economy storage did not confirm the save.")
        except Exception:
            inv.clear()
            inv.update(old_inventory)
            economy_cooldowns.clear()
            economy_cooldowns.update(old_cooldowns)
            if old_balance is None:
                economy_balances.pop((guild.id, user.id), None)
            else:
                economy_balances[(guild.id, user.id)] = old_balance
            return await cinnamon_send(interaction, "The item could not be saved. Nothing was consumed; please try again.", ephemeral=True)
    await interaction.response.send_message(
        f"Used **{data.get('emoji', '🐾')} {data.get('name', item_id)}**.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    await _shop_item_run_actions(interaction, item_id, "used")
    await economy_log(guild.id, title="🧰 Shop item used",
        fields=[("Member", f"{user} ({user.id})"), ("Item", f"{data.get('name', item_id)} ({item_id})"),
                ("Reusable", str(bool(data.get("reusable", False))))])
