"""Cinnamon feature module.

Loaded by main.py into Cinnamon's shared runtime namespace. This is still
one Discord bot and one process; this file is not a separate bot.
Do not run this file directly.
"""

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


def economy_user_snapshot(guild_id: int, user_id: int) -> dict:
    return {
        "balance": economy_balance(guild_id, user_id),
        "inventory": dict(economy_inventory_for(guild_id, user_id)),
        "level_rewards_claimed": list(economy_level_rewards_claimed.get((guild_id, user_id), [])),
    }


async def economy_log(guild_id: int, *, title: str, description: str = "", fields=None):
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
        f"{item['emoji']} **{item['name']}** — `{item_id}` — **{item['price']} Catnip**\n{item['description']}"
        for item_id, item in ECONOMY_ITEMS.items()
    )


async def economy_do_work(guild_id: int, user: discord.abc.User) -> tuple[bool, int, str]:
    user_id = user.id
    remaining = economy_cooldown_remaining(guild_id, user_id, "work")
    if remaining:
        return False, 0, f"🐾 You're on a work cooldown. Try again in **{remaining // 60}m {remaining % 60}s**."
    balance_before = economy_balance(guild_id, user_id)
    amount = random.randint(ECONOMY_WORK_MIN, ECONOMY_WORK_MAX)
    jobs = [
        "sorted Cinnamon's treats", "guarded the tuna cupboard", "cleaned the cat tree",
        "chased a suspicious cardboard box", "organized the yarn drawer",
        "polished Cinnamon's food bowl", "delivered a mysterious package of kibble",
    ]
    job = random.choice(jobs)
    economy_cooldowns[(guild_id, user_id, "work")] = time.time() + ECONOMY_WORK_COOLDOWN
    economy_balances[(guild_id, user_id)] = balance_before + amount
    await achievement_record(guild_id, user_id, "catnip_earned", amount)
    await achievement_record(guild_id, user_id, "balance")
    await quest_event(guild_id, user_id, "work", 1)
    await quest_event(guild_id, user_id, "balance", balance_before + amount)
    try:
        await quest_record_event(guild_id, user_id, "work", 1, member=user)
        await quest_record_event(guild_id, user_id, "earned", amount, member=user)
    except Exception:
        log.exception("Full quest work event failed for guild %s", guild_id)
    await bd_save_data()
    await economy_log(guild_id, title="💼 Economy work", fields=[("User", f"{user} ({user_id})"), ("Job", job), ("Earned", f"+{amount} Catnip"), ("Balance before", f"{balance_before:,}"), ("Balance after", f"{balance_before+amount:,}")])
    return True, amount, f"💼 You **{job}** and earned **{amount} Catnip**! *Cinnamon inspects the work proudly.*"


def economy_level_reward_claimed(guild_id: int, user_id: int, level: int) -> bool:
    return level in economy_level_rewards_claimed.get((guild_id, user_id), [])


def mark_economy_level_reward_claimed(guild_id: int, user_id: int, level: int):
    key = (guild_id, user_id)
    economy_level_rewards_claimed.setdefault(key, [])
    if level not in economy_level_rewards_claimed[key]:
        economy_level_rewards_claimed[key].append(level)


def economy_income_role_lines(guild: discord.Guild) -> str:
    cfg = economy_income_roles.get(guild.id, {})
    if not cfg:
        return "No income roles are configured."
    lines = []
    for role_id, data in cfg.items():
        role = guild.get_role(int(role_id))
        name = role.mention if role else f"Deleted role ({role_id})"
        cooldown = int(data.get("cooldown", 3600))
        amount = int(data.get("amount", 0))
        interval = int(data.get("interval", max(1, cooldown // 3600)))
        unit = str(data.get("unit", "hour"))
        lines.append(f"{name} — **{amount:,} Catnip / {interval} {unit}(s)**")
    return "\n".join(lines)


economy_group = app_commands.Group(name="economy", description="Cinnamon's Catnip economy, items, quests, and backups")

# Discord allows at most 25 direct children under one application-command group.
# Keep the two Catnip admin balance controls under a nested admin group so the
# main /economy group stays within that limit.
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
    embed = discord.Embed(title=f"🐾 {member.display_name}'s wallet", color=discord.Color.gold())
    embed.add_field(name="Catnip", value=f"🌿 **{balance:,}**", inline=True)
    embed.add_field(name="Items", value=f"🎒 **{item_count}**", inline=True)
    await interaction.response.send_message(embed=embed)
    await economy_log(interaction.guild.id, title="👛 Economy balance viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Balance", f"{balance:,} Catnip")])
    await bd_save_data()


@economy_group.command(name="inventory", description="See your Cinnamon items")
@app_commands.guild_only()
async def economy_inventory_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    inv = economy_inventory_for(interaction.guild.id, member.id)
    lines = []
    for item_id, qty in inv.items():
        if qty > 0 and item_id in ECONOMY_ITEMS:
            item = ECONOMY_ITEMS[item_id]
            lines.append(f"{item['emoji']} **{item['name']}** × **{qty}** (`{item_id}`)")
    embed = discord.Embed(title=f"🎒 {member.display_name}'s inventory", color=discord.Color.blurple())
    embed.description = "\n".join(lines) if lines else "Your inventory is empty. Visit `/economy shop`!"
    await interaction.response.send_message(embed=embed)
    inv_summary = "\n".join(f"{ECONOMY_ITEMS[k]['name']}: {int(v)}" for k, v in inv.items() if k in ECONOMY_ITEMS and int(v) > 0) or "Empty"
    await economy_log(interaction.guild.id, title="🎒 Economy inventory viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Inventory", inv_summary[:1000]), ("Total items", str(sum(int(v) for v in inv.values()))), ("Catnip balance", f"{economy_balance(interaction.guild.id, member.id):,}")])


@economy_group.command(name="shop", description="View Cinnamon's shop")
@app_commands.guild_only()
async def economy_shop_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🐟 Cinnamon's Catnip Shop", description=economy_item_lines(), color=discord.Color.gold())
    embed.set_footer(text="Buy with /economy buy item:<item_id> quantity:<number>")
    await interaction.response.send_message(embed=embed)
    await economy_log(interaction.guild.id, title="🛒 Economy shop viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})")])


@economy_group.command(name="buy", description="Buy an item with Catnip")
@app_commands.describe(item="Item ID or item name from /economy shop", quantity="How many to buy")
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
        await interaction.response.send_message("❌ That item isn't in the shop. Use `/economy shop` to see available items.", ephemeral=True)
        return
    current_qty = int(economy_inventory_for(guild_id, user_id).get(item_id, 0))
    max_per_person = int(data.get("max_per_person", 0))
    if max_per_person and current_qty + quantity > max_per_person:
        await interaction.response.send_message(f"❌ This item has a limit of **{max_per_person}** per person. You already have **{current_qty}**.", ephemeral=True)
        return
    cost = data["price"] * quantity
    balance = economy_balance(guild_id, user_id)
    if balance < cost:
        await interaction.response.send_message(f"❌ You need **{cost:,} Catnip**, but you only have **{balance:,}**.", ephemeral=True)
        return
    economy_balances[(guild_id, user_id)] = balance - cost
    inv = economy_inventory_for(guild_id, user_id)
    inv[item_id] = current_qty + quantity
    await achievement_record(guild_id, user_id, "purchase", quantity, spent=cost)
    await achievement_record(guild_id, user_id, "inventory")
    await quest_event(guild_id, user_id, "items_owned", sum(max(0,int(v)) for v in inv.values()))
    await quest_event(guild_id, user_id, "purchase", quantity, spent=cost)
    await quest_event(guild_id, user_id, "spent", cost, spent=cost)
    await achievement_record(guild_id, user_id, "balance")
    await quest_event(guild_id, user_id, "balance", balance - cost)
    await bd_save_data()
    await economy_log(guild_id, title="🛒 Economy purchase", fields=[("User", f"{interaction.user} ({user_id})"), ("Item", f"{data['name']} (`{item_id}`)"), ("Quantity", quantity), ("Unit price", f"{data['price']:,} Catnip"), ("Deducted", f"-{cost:,} Catnip"), ("Balance before", f"{balance:,} Catnip"), ("Balance after", f"{balance-cost:,} Catnip"), ("Item quantity after", str(inv[item_id]))])
    await interaction.response.send_message(f"🛒 Bought **{quantity}× {data['emoji']} {data['name']}** for **{cost:,} Catnip**. Balance: **{economy_balances[(guild_id, user_id)]:,}**")


@economy_group.command(name="daily", description="Claim your daily Catnip")
@app_commands.guild_only()
async def economy_daily_cmd(interaction: discord.Interaction):
    guild_id, user_id = interaction.guild.id, interaction.user.id
    remaining = economy_cooldown_remaining(guild_id, user_id, "daily")
    if remaining:
        await interaction.response.send_message(f"🐾 Cinnamon already gave you your daily Catnip. Come back in **{remaining // 3600}h {(remaining % 3600) // 60}m**.", ephemeral=True)
        return
    economy_cooldowns[(guild_id, user_id, "daily")] = time.time() + 86400
    balance_before = economy_balance(guild_id, user_id)
    economy_balances[(guild_id, user_id)] = balance_before + ECONOMY_DAILY_REWARD
    await achievement_record(guild_id, user_id, "catnip_earned", ECONOMY_DAILY_REWARD)
    await achievement_record(guild_id, user_id, "balance")
    await bd_save_data()
    await economy_log(guild_id, title="🌿 Daily Catnip", fields=[("User", f"{interaction.user} ({user_id})"), ("Amount", f"+{ECONOMY_DAILY_REWARD} Catnip"), ("Balance before", f"{balance_before:,}"), ("Balance after", f"{balance_before+ECONOMY_DAILY_REWARD:,}")])
    await interaction.response.send_message(f"🌿 **+{ECONOMY_DAILY_REWARD} Catnip!** Cinnamon has approved your daily snack budget.")


@economy_group.command(name="work", description="Work for Cinnamon and earn 50-150 Catnip every 10 minutes")
@app_commands.guild_only()
async def economy_work_cmd(interaction: discord.Interaction):
    ok, amount, message = await economy_do_work(interaction.guild.id, interaction.user)
    if not ok:
        embed = discord.Embed(
            title="🐾 Cinnamon's Work Desk",
            description=message,
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Cinnamon economy • Work cooldown")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    balance = economy_balance(interaction.guild.id, interaction.user.id)
    embed = discord.Embed(
        title="💼 Shift Complete!",
        description=message,
        color=discord.Color.gold(),
    )
    embed.add_field(name="💰 Earned", value=f"**+{amount:,} Catnip**", inline=True)
    embed.add_field(name="🌿 New Balance", value=f"**{balance:,} Catnip**", inline=True)
    embed.set_footer(text="Cinnamon economy • Next shift available in 10 minutes")
    await interaction.response.send_message(embed=embed)


@economy_group.command(name="give", description="Give Catnip to another member")
@app_commands.guild_only()
async def economy_give_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    guild_id = interaction.guild.id
    if member.bot:
        await interaction.response.send_message("❌ Bot accounts can't receive Catnip.", ephemeral=True)
        return
    if member.id == interaction.user.id:
        await interaction.response.send_message("🐾 You can't give Catnip to yourself.", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
        return
    pair_key = (guild_id, interaction.user.id, f"give:{member.id}")
    pair_remaining = economy_cooldown_remaining(guild_id, interaction.user.id, f"give:{member.id}")
    if pair_remaining:
        await interaction.response.send_message(f"🐾 You recently sent Catnip to that member. Try again in **{pair_remaining // 60}m**.", ephemeral=True)
        return
    sender_balance = economy_balance(guild_id, interaction.user.id)
    if sender_balance < amount:
        await interaction.response.send_message(f"❌ You only have **{sender_balance:,} Catnip**.", ephemeral=True)
        return
    recipient_before = economy_balance(guild_id, member.id)
    economy_balances[(guild_id, interaction.user.id)] = sender_balance - amount
    economy_balances[(guild_id, member.id)] = recipient_before + amount
    economy_cooldowns[pair_key] = time.time() + 3600
    await achievement_record(guild_id, interaction.user.id, "give", amount)
    await achievement_record(guild_id, interaction.user.id, "balance")
    await quest_event(guild_id, interaction.user.id, "balance", sender_balance-amount)
    await quest_event(guild_id, interaction.user.id, "give", amount)
    await quest_event(guild_id, interaction.user.id, "give_count", 1)
    await bd_save_data()
    await economy_log(guild_id, title="🎁 Catnip transfer", fields=[("From", f"{interaction.user} ({interaction.user.id})"), ("To", f"{member} ({member.id})"), ("Amount", f"{amount:,} Catnip"), ("Sender before", f"{sender_balance:,}"), ("Sender after", f"{sender_balance-amount:,}"), ("Recipient before", f"{recipient_before:,}"), ("Recipient after", f"{recipient_before+amount:,}")])
    await interaction.response.send_message(f"🎁 Gave **{amount:,} Catnip** to {member.mention}.")


@economy_group.command(name="leaderboard", description="Show the richest members")
@app_commands.guild_only()
async def economy_leaderboard_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    rows = [(uid, bal) for (gid, uid), bal in economy_balances.items() if gid == guild_id]
    rows.sort(key=lambda x: x[1], reverse=True)
    lines = []
    for i, (uid, bal) in enumerate(rows[:10], 1):
        member = interaction.guild.get_member(uid)
        name = member.display_name if member else f"User {uid}"
        lines.append(f"**{i}.** {name} — 🌿 **{bal:,}**")
    embed = discord.Embed(title="🏆 Catnip leaderboard", description="\n".join(lines) if lines else "No economy users yet.", color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)


@economy_group.command(name="feed", description="Give Cinnamon an item")
@app_commands.describe(item="Item to give Cinnamon", quantity="How many to give")
@app_commands.choices(item=[app_commands.Choice(name=v["name"], value=k) for k, v in ECONOMY_ITEMS.items()])
@app_commands.guild_only()
async def economy_feed_cmd(interaction: discord.Interaction, item: app_commands.Choice[str], quantity: app_commands.Range[int, 1, 99] = 1):
    try:
        guild_id, user_id = interaction.guild.id, interaction.user.id
        item_id = str(item.value)
        data = ECONOMY_ITEMS.get(item_id)
        if not data:
            await interaction.response.send_message("❌ That item no longer exists. Refresh the command choices and try again.", ephemeral=True)
            return
        inv = economy_inventory_for(guild_id, user_id)
        have = max(0, int(inv.get(item_id, 0)))
        if have < quantity:
            await interaction.response.send_message(f"❌ You only have **{have}× {data['name']}**.", ephemeral=True)
            return
        inv[item_id] = have - quantity
        await achievement_record(guild_id, user_id, "feed", quantity, item=item_id)
        await achievement_record(guild_id, user_id, "inventory")
        await quest_event(guild_id, user_id, "items_owned", sum(max(0,int(v)) for v in inv.values()))
        await quest_event(guild_id, user_id, "feed", quantity, item=item_id)
        await bd_save_data()
        await economy_log(guild_id, title="🐟 Cinnamon fed", fields=[
            ("User", f"{interaction.user} ({user_id})"),
            ("Item", f"{data['name']} (`{item_id}`)"),
            ("Quantity fed", str(quantity)),
            ("Inventory before", str(have)),
            ("Inventory after", str(inv.get(item_id, 0))),
            ("Inventory change", f"-{quantity} {data['name']}"),
        ])
        await interaction.response.send_message(
            f"🐾 Cinnamon happily accepted **{quantity}× {data['name']}**!",
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except Exception:
        log.exception("Economy feed command failed for guild %s", interaction.guild.id if interaction.guild else 0)
        msg = "❌ I couldn't process that feed action. Please try again."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


@economy_group.command(name="logs", description="Set or disable the economy transaction log channel")
@app_commands.describe(channel="Channel where economy transactions and backups will be logged; omit to disable")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def economy_logs_cmd(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    guild_id = interaction.guild.id
    if channel is None:
        removed = economy_log_channels.pop(guild_id, None)
        category_log_channels.get(guild_id, {}).pop("economy", None)
        await bd_save_data()
        await interaction.response.send_message("🧾 Economy logs disabled." if removed else "🧾 Economy logs are already disabled.", ephemeral=True)
        if removed:
            # The economy destination has just been removed, so this is intentionally routed through the remaining setup/main logger.
            await send_log(guild_id, title="🧾 Economy logging disabled", interaction=interaction, category="setup", fields=[("Previous channel ID", str(removed))])
        return
    economy_log_channels[guild_id] = channel.id
    category_log_channels.setdefault(guild_id, {})["economy"] = channel.id
    await secure_log_channel(channel)
    await bd_save_data()
    await economy_log(guild_id, title="🧾 Economy logging enabled", description=f"Economy transactions and backup snapshots will be posted here: {channel.mention}")
    await interaction.response.send_message(f"✅ Economy logs will now go to {channel.mention}.", ephemeral=True)


async def economy_snapshot_payload(guild_id: int) -> dict:
    users = {}
    user_ids = set()
    for (gid, uid) in economy_balances:
        if gid == guild_id: user_ids.add(uid)
    for (gid, uid) in economy_inventory:
        if gid == guild_id: user_ids.add(uid)
    for uid in user_ids:
        users[str(uid)] = economy_user_snapshot(guild_id, uid)
    achievement_data_all = globals().get("achievement_data", {})
    achievement_config_all = globals().get("achievement_config", {})
    achievement_role_overrides_all = globals().get("achievement_role_overrides", {})
    quest_data_all = globals().get("quest_data", {})
    quest_config_all = globals().get("quest_config", {})
    return {
        "schema": 2,
        "type": "cinnamon_economy_snapshot",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "guild_id": guild_id,
        "currency": "Catnip",
        "users": users,
        "items": ECONOMY_ITEMS,
        "level_rewards": ECONOMY_LEVEL_REWARDS,
        "income_roles": economy_income_roles.get(guild_id, {}),
        "achievements": {
            f"{g}:{u}": v
            for (g, u), v in achievement_data_all.items()
            if g == guild_id
        },
        "achievement_config": achievement_config_all.get(guild_id, {}),
        "achievement_role_overrides": achievement_role_overrides_all.get(guild_id, {}),
        "quests": quest_data_all.get(guild_id, {}),
        "quest_config": quest_config_all.get(guild_id, {}),
    }


@economy_group.command(name="snapshot", description="Create one complete economy backup before resetting the bot")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def economy_snapshot_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    channel_id = economy_log_channels.get(guild_id)
    channel = bot.get_channel(channel_id) if channel_id else None
    if channel is None:
        await interaction.response.send_message("❌ Set an economy log channel first with `/economy logs #channel`.", ephemeral=True)
        return
    payload = await economy_snapshot_payload(guild_id)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    file = discord.File(io.BytesIO(raw), filename=f"cinnamon_economy_snapshot_{guild_id}.json")
    user_count = len(payload["users"])
    embed = discord.Embed(title="💾 Cinnamon economy snapshot", description="Complete Catnip balances, inventories, item definitions, and economy settings for this server. Keep this message/file before a reset.", color=discord.Color.green(), timestamp=datetime.datetime.now(datetime.timezone.utc))
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
    embed.add_field(name="How to restore", value="After the reset, run `/economy restore-snapshot` in this server. The bot will scan this log channel for the newest snapshot.", inline=False)
    await interaction.response.defer(ephemeral=True)
    await channel.send(embed=embed, file=file)
    await bd_save_data()
    await economy_log(guild_id, title="💾 Economy snapshot created", fields=[("Created by", f"{interaction.user} ({interaction.user.id})"), ("Users backed up", str(user_count)), ("Items", str(len(ECONOMY_ITEMS))), ("Channel", channel.mention)])
    await interaction.followup.send(f"✅ Snapshot saved to {channel.mention}. **{user_count}** users are included. You can reset the bot and later run `/economy restore-snapshot`.", ephemeral=True)


async def economy_restore_from_snapshot(guild: discord.Guild, limit: int = 5000, *, merge_only: bool = False) -> tuple[int, str]:
    """Restore a snapshot. merge_only fills missing state without overwriting live accounts."""
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
            snap_levels = [int(x) for x in user.get("level_rewards_claimed", [])]
            if merge_only:
                economy_level_rewards_claimed[key] = sorted(set(economy_level_rewards_claimed.get(key, [])) | set(snap_levels))
            else:
                economy_level_rewards_claimed[key] = snap_levels
            if not had_balance:
                restored += 1
        except (ValueError, TypeError):
            continue
    snapshot_income = latest.get("income_roles")
    if isinstance(snapshot_income, dict):
        economy_income_roles[guild.id] = {int(r): cfg for r, cfg in snapshot_income.items()}
    # Restore achievement/quest state from the same admin snapshot so a full
    # economy recovery does not silently lose unlocked achievements, roles,
    # Quest Points, active rotations, or their per-guild configuration.
    snapshot_achievements = latest.get("achievements")
    if isinstance(snapshot_achievements, dict) and "achievement_data" in globals():
        target = globals()["achievement_data"]
        for key_text, state in snapshot_achievements.items():
            try:
                g_text, u_text = str(key_text).split(":", 1)
                if int(g_text) != guild.id or not isinstance(state, dict):
                    continue
                key = (guild.id, int(u_text))
                if merge_only and key in target:
                    continue
                target[key] = state
            except (ValueError, TypeError):
                continue

    snapshot_achievement_config = latest.get("achievement_config")
    if isinstance(snapshot_achievement_config, dict) and "achievement_config" in globals() and not merge_only:
        globals()["achievement_config"][guild.id] = snapshot_achievement_config

    snapshot_role_overrides = latest.get("achievement_role_overrides")
    if isinstance(snapshot_role_overrides, dict) and "achievement_role_overrides" in globals() and not merge_only:
        try:
            globals()["achievement_role_overrides"][guild.id] = {str(a): int(r) for a, r in snapshot_role_overrides.items()}
        except (ValueError, TypeError):
            pass

    snapshot_quests = latest.get("quests")
    if isinstance(snapshot_quests, dict) and "quest_data" in globals() and not merge_only:
        globals()["quest_data"][guild.id] = snapshot_quests

    snapshot_quest_config = latest.get("quest_config")
    if isinstance(snapshot_quest_config, dict) and "quest_config" in globals() and not merge_only:
        globals()["quest_config"][guild.id] = snapshot_quest_config

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
    await bd_save_data()
    created = latest.get("created_at", "unknown time")
    return restored, created


@economy_admin_group.command(name="addcatnip", description="Admin: add Catnip to a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def economy_addcatnip_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    guild_id = interaction.guild.id
    before = economy_balance(guild_id, member.id)
    economy_balances[(guild_id, member.id)] = before + amount
    await bd_save_data()
    await economy_log(guild_id, title="🛠️ Admin Catnip added", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Amount", f"+{amount:,} Catnip"), ("Balance before", f"{before:,}"), ("Balance after", f"{before+amount:,}")])
    await interaction.response.send_message(f"✅ Added **{amount:,} Catnip** to {member.mention}. New balance: **{economy_balance(guild_id, member.id):,}**.", ephemeral=True)


@economy_admin_group.command(name="removecatnip", description="Admin: remove Catnip from a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def economy_removecatnip_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    guild_id = interaction.guild.id
    current = economy_balance(guild_id, member.id)
    removed = min(current, amount)
    economy_balances[(guild_id, member.id)] = current - removed
    await bd_save_data()
    await economy_log(guild_id, title="🛠️ Admin Catnip removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Amount", f"-{removed:,} Catnip"), ("Balance before", f"{current:,}"), ("Balance after", f"{current-removed:,}")])
    await interaction.response.send_message(f"✅ Removed **{removed:,} Catnip** from {member.mention}. New balance: **{economy_balance(guild_id, member.id):,}**.", ephemeral=True)


@economy_group.command(name="income", description="Admin: manage Catnip income roles")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(action="add, remove, or list", role="Role that earns Catnip", amount="Catnip paid each collection", minutes="Cooldown in minutes")
@app_commands.choices(action=[app_commands.Choice(name="add", value="add"), app_commands.Choice(name="remove", value="remove"), app_commands.Choice(name="list", value="list")])
async def economy_income_cmd(interaction: discord.Interaction, action: app_commands.Choice[str], role: discord.Role | None = None, amount: int | None = None, minutes: int | None = None):
    guild_id = interaction.guild.id
    cfg = economy_income_roles.setdefault(guild_id, {})
    if action.value == "list":
        embed = discord.Embed(title="💰 Catnip income roles", description=economy_income_role_lines(interaction.guild), color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if role is None:
        await interaction.response.send_message("❌ Choose a role.", ephemeral=True)
        return
    if action.value == "remove":
        removed = cfg.pop(role.id, None)
        await bd_save_data()
        await interaction.response.send_message(f"🗑️ Removed {role.mention} from Catnip income roles." if removed else f"ℹ️ {role.mention} was not an income role.", ephemeral=True)
        return
    if amount is None or minutes is None:
        await interaction.response.send_message("❌ For `add`, provide both `amount` and `minutes`.", ephemeral=True)
        return
    cfg[role.id] = {"amount": int(amount), "cooldown": int(minutes) * 60}
    await bd_save_data()
    await economy_log(guild_id, title="💰 Income role configured", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Role", role.name), ("Income", f"{amount:,} Catnip / {minutes} min")])
    await interaction.response.send_message(f"✅ {role.mention} now earns **{amount:,} Catnip every {minutes} minutes** when members use `/collect`.", ephemeral=True)


async def economy_collect(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    configs = economy_income_roles.get(guild_id, {})
    if not configs:
        await interaction.response.send_message("ℹ️ This server has no income roles configured yet.", ephemeral=True)
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
        await interaction.response.send_message("⏳ None of your income roles are ready to collect yet.", ephemeral=True)
        return
    balance_before = economy_balance(guild_id, interaction.user.id)
    economy_balances[(guild_id, interaction.user.id)] = balance_before + total
    await bd_save_data()
    await economy_log(guild_id, title="💰 Income collected", fields=[("User", f"{interaction.user} ({interaction.user.id})"), ("Total", f"+{total:,} Catnip"), ("Balance before", f"{balance_before:,}"), ("Balance after", f"{balance_before+total:,}"), ("Sources", "\n".join(collected))])
    await interaction.response.send_message(f"💰 You collected **{total:,} Catnip**!\n" + "\n".join(f"• {x}" for x in collected))


@economy_group.command(name="collect", description="Collect Catnip from all income roles you have")
@app_commands.guild_only()
async def economy_collect_cmd(interaction: discord.Interaction):
    await economy_collect(interaction)


@app_commands.guild_only()
async def collect_cmd(interaction: discord.Interaction):
    await economy_collect(interaction)


@economy_group.command(name="item-add", description="Admin: add an item directly to a member's inventory")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(member="Member receiving the item", item="Item ID or item name", quantity="Number of items to add")
async def economy_item_add_cmd(interaction: discord.Interaction, member: discord.Member, item: str, quantity: int = 1):
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await interaction.response.send_message("❌ That item doesn't exist. Use `/economy shop` first.", ephemeral=True)
        return
    inv = economy_inventory_for(interaction.guild.id, member.id)
    max_per_person = int(data.get("max_per_person", 0))
    current = int(inv.get(item_id, 0))
    if max_per_person and current + quantity > max_per_person:
        await interaction.response.send_message(f"❌ {member.mention} cannot hold more than **{max_per_person}** of this item.", ephemeral=True)
        return
    inv[item_id] = current + quantity
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🛠️ Admin item added", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Item", f"{data['name']} (`{item_id}`)"), ("Quantity added", f"+{quantity}"), ("Quantity before", current), ("Quantity after", inv[item_id]), ("Catnip balance", economy_balance(interaction.guild.id, member.id))])
    await interaction.response.send_message(f"✅ Added **{quantity}× {data['emoji']} {data['name']}** to {member.mention}.", ephemeral=True)


@economy_group.command(name="item-remove", description="Admin: remove an item from a member's inventory")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(member="Member losing the item", item="Item ID or item name", quantity="Number of items to remove")
async def economy_item_remove_cmd(interaction: discord.Interaction, member: discord.Member, item: str, quantity: int = 1):
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await interaction.response.send_message("❌ That item doesn't exist.", ephemeral=True)
        return
    inv = economy_inventory_for(interaction.guild.id, member.id)
    current = int(inv.get(item_id, 0))
    removed = min(current, quantity)
    if removed <= 0:
        await interaction.response.send_message(f"❌ {member.mention} doesn't have that item.", ephemeral=True)
        return
    inv[item_id] = current - removed
    if inv[item_id] <= 0:
        inv.pop(item_id, None)
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🛠️ Admin item removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Item", f"{data['name']} (`{item_id}`)"), ("Quantity removed", f"-{removed}"), ("Quantity before", current), ("Quantity after", inv.get(item_id, 0)), ("Catnip balance", economy_balance(interaction.guild.id, member.id))])
    await interaction.response.send_message(f"✅ Removed **{removed}× {data['emoji']} {data['name']}** from {member.mention}.", ephemeral=True)


@economy_group.command(name="add-item-shop", description="Admin: add an item to the Catnip shop")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(item_id="Unique shop ID", name="Item name", price="Price in Catnip", description="Optional item description", per_person_limit="Optional maximum quantity one member can own", emoji="Optional emoji")
async def economy_add_item_shop_cmd(interaction: discord.Interaction, item_id: str, name: str, price: int, description: str | None = None, per_person_limit: int | None = None, emoji: str = "🐾"):
    item_id = re.sub(r"[^a-z0-9_-]", "", item_id.lower())[:32]
    if not item_id or item_id in ECONOMY_ITEMS:
        await interaction.response.send_message("❌ That item ID is invalid or already exists.", ephemeral=True)
        return
    if int(price) < 1000:
        return await interaction.response.send_message("❌ Default shop items must cost at least **1,000 Catnip**.", ephemeral=True)
    ECONOMY_ITEMS[item_id] = {"name": name[:80], "price": int(price), "emoji": emoji[:8], "description": (description or "No description provided.")[:300], "max_per_person": int(per_person_limit or 0)}
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🛒 Shop item added", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Item", f"{emoji} {name}"), ("ID", item_id), ("Price", f"{price:,} Catnip"), ("Per-person limit", per_person_limit or "Unlimited")])
    await interaction.response.send_message(f"✅ Added **{emoji} {name}** (`{item_id}`) to the shop.", ephemeral=True)


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
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(item_id="Item ID to edit", name="New name", price="New price", description="New description", per_person_limit="New per-person limit; 0 means unlimited", emoji="New emoji")
async def economy_edit_shop_item_cmd(interaction: discord.Interaction, item_id: str, name: str | None = None, price: int | None = None, description: str | None = None, per_person_limit: int | None = None, emoji: str | None = None):
    item_id = item_id.lower().strip()
    item = ECONOMY_ITEMS.get(item_id)
    if item is None:
        await interaction.response.send_message("❌ That shop item doesn't exist.", ephemeral=True)
        return
    if all(x is None for x in (name, price, description, per_person_limit, emoji)):
        await interaction.response.send_message("❌ Choose at least one property to edit.", ephemeral=True)
        return
    if name is not None: item["name"] = name[:80]
    if price is not None:
        if int(price) < 1000:
            return await interaction.response.send_message("❌ Shop item prices must be at least **1,000 Catnip**.", ephemeral=True)
        item["price"] = int(price)
    if description is not None: item["description"] = description[:300]
    if per_person_limit is not None: item["max_per_person"] = int(per_person_limit)
    if emoji is not None: item["emoji"] = emoji[:8]
    await bd_save_data()
    await economy_log(interaction.guild.id, title="✏️ Shop item edited", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Item ID", item_id), ("New name", item["name"]), ("New price", f"{item['price']:,} Catnip"), ("Per-person limit", item.get("max_per_person", 0) or "Unlimited")])
    await interaction.response.send_message(f"✅ Updated **{item['emoji']} {item['name']}** (`{item_id}`).", ephemeral=True)


@economy_group.command(name="remove-item-shop", description="Admin: remove an item from the Catnip shop")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(item_id="Item ID to remove", remove_from_inventories="Whether all copies should also be removed from member inventories")
async def economy_remove_item_shop_cmd(interaction: discord.Interaction, item_id: str, remove_from_inventories: bool = False):
    guild_id = interaction.guild.id
    item_id = item_id.lower().strip()
    item = ECONOMY_ITEMS.get(item_id)
    if item is None:
        await interaction.response.send_message("❌ That shop item doesn't exist.", ephemeral=True)
        return
    removed_inventory = 0
    if remove_from_inventories:
        for (gid, uid), inv in economy_inventory.items():
            if gid == guild_id and item_id in inv:
                removed_inventory += int(inv.pop(item_id, 0))
    ECONOMY_ITEMS.pop(item_id, None)
    await bd_save_data()
    await economy_log(guild_id, title="🗑️ Shop item removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Item", f"{item['emoji']} {item['name']}"), ("ID", item_id), ("Inventory copies removed", removed_inventory), ("Removed from inventories", remove_from_inventories)])
    await interaction.response.send_message(f"🗑️ Removed **{item['name']}** from the shop. " + (f"Also removed **{removed_inventory}** copies from inventories." if remove_from_inventories else "Existing inventory copies were kept."), ephemeral=True)


@economy_group.command(name="add-role-income", description="Admin: give a role a recurring Catnip income")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(role="Role receiving the income", amount="Catnip earned each collection", interval="How many time units between collections", unit="Time unit")
@app_commands.choices(unit=[app_commands.Choice(name="Minutes", value="minute"), app_commands.Choice(name="Hours", value="hour"), app_commands.Choice(name="Days", value="day"), app_commands.Choice(name="Weeks", value="week")])
async def economy_add_role_income_cmd(interaction: discord.Interaction, role: discord.Role, amount: int, interval: int, unit: app_commands.Choice[str]):
    multipliers = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800}
    cooldown = int(interval) * multipliers[unit.value]
    economy_income_roles.setdefault(interaction.guild.id, {})[role.id] = {"amount": int(amount), "cooldown": cooldown, "interval": int(interval), "unit": unit.value}
    await bd_save_data()
    await economy_log(interaction.guild.id, title="💰 Role income added/updated", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Role", f"{role} ({role.id})"), ("Income", f"{amount:,} Catnip / {interval} {unit.name.lower()}")])
    await interaction.response.send_message(f"✅ {role.mention} now provides **{amount:,} Catnip every {interval} {unit.name.lower()}** via `/collect`.", ephemeral=True)


@economy_group.command(name="remove-role-income", description="Admin: remove a role's recurring Catnip income")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(role="Role whose income should be removed")
async def economy_remove_role_income_cmd(interaction: discord.Interaction, role: discord.Role):
    cfg = economy_income_roles.setdefault(interaction.guild.id, {})
    removed = cfg.pop(role.id, None)
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🗑️ Role income removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Role", f"{role} ({role.id})"), ("Was configured", bool(removed))])
    await interaction.response.send_message(f"🗑️ Removed {role.mention} from recurring Catnip income." if removed else f"ℹ️ {role.mention} wasn't configured for income.", ephemeral=True)


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
        await interaction.response.send_message("❌ That item doesn't exist. Use `/economy shop` to see the item IDs.", ephemeral=True)
        return
    limit = int(data.get("max_per_person", 0))
    embed = discord.Embed(title=f"{data['emoji']} {data['name']}", description=data["description"], color=discord.Color.gold())
    embed.add_field(name="Item ID", value=f"`{item_id}`", inline=True)
    embed.add_field(name="Price", value=f"{data['price']:,} Catnip", inline=True)
    embed.add_field(name="Per-person limit", value=str(limit) if limit else "Unlimited", inline=True)
    await interaction.response.send_message(embed=embed)
    await economy_log(interaction.guild.id, title="🔎 Economy item info viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})"), ("Item", f"{item['name']} (`{item_id}`)")])


@economy_group.command(name="restore-snapshot", description="Restore the latest complete economy snapshot from the economy log channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
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


