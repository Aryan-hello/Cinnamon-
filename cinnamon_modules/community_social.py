"""Community social features: quotes, reputation, member teams and challenges."""
import asyncio as _cs_asyncio
import copy as _cs_copy
import re as _cs_re
import time as _cs_time
import uuid as _cs_uuid

_CS_KEY = "cinnamon_community_social_v1"
_CS_LOCKS = {}

def _cs_root(gid):
    root = advanced_features_data.setdefault(_CS_KEY, {})
    if not isinstance(root, dict):
        root = advanced_features_data[_CS_KEY] = {}
    cfg = root.setdefault(str(int(gid)), {})
    for key, default in (
        ("quotes", {}), ("rep_scores", {}), ("rep_given", {}),
        ("teams", {}), ("team_members", {}), ("challenge", None),
    ):
        cfg.setdefault(key, _cs_copy.deepcopy(default))
    return cfg

def _cs_lock(gid, key):
    return _CS_LOCKS.setdefault((int(gid), str(key)), _cs_asyncio.Lock())

def _cs_team_slug(name):
    slug = _cs_re.sub(r"[^a-z0-9-]+", "-", str(name).strip().lower()).strip("-")
    return slug[:24]

quote_group = app_commands.Group(name="quote", description="Save and browse memorable server quotes")

@quote_group.command(name="add", description="Add a quote to the server's collection")
@app_commands.guild_only()
@app_commands.describe(text="Quote text to save")
async def community_quote_add(interaction: discord.Interaction, text: app_commands.Range[str, 1, 400]):
    clean = " ".join(str(text).split()).strip()
    if not clean:
        return await cinnamon_send(interaction, "A quote cannot be empty.", ephemeral=True)
    cfg = _cs_root(interaction.guild.id)
    quote_id = _cs_uuid.uuid4().hex[:8]
    cfg["quotes"][quote_id] = {
        "text": clean, "submitted_by": int(interaction.user.id),
        "created_at": int(_cs_time.time()),
    }
    if not await bd_save_data():
        cfg["quotes"].pop(quote_id, None)
        return await cinnamon_send(interaction, "Couldn't save that quote.", ephemeral=True)
    await cinnamon_send(interaction, f"Quote saved to the collection. ID: {quote_id}.", ephemeral=True)

@quote_group.command(name="list", description="Browse recent server quotes")
@app_commands.guild_only()
async def community_quote_list(interaction: discord.Interaction):
    quotes = list(_cs_root(interaction.guild.id)["quotes"].items())
    quotes.sort(key=lambda pair: int(pair[1].get("created_at", 0)), reverse=True)
    lines = []
    for quote_id, record in quotes[:10]:
        member = interaction.guild.get_member(int(record.get("submitted_by", 0)))
        by = member.display_name if member else "Former member"
        lines.append(f"**#{quote_id}** — “{str(record.get('text', ''))[:400]}”\n<text:>{by}")
    e = discord.Embed(title="💬 Server Quote Collection",
                      description="\n\n".join(lines) or "No quotes have been saved yet.",
                      color=0xB8A7D9)
    await interaction.response.send_message(embed=e, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

@quote_group.command(name="remove", description="Remove a quote you submitted or moderate a quote")
@app_commands.guild_only()
async def community_quote_remove(interaction: discord.Interaction, quote_id: str):
    cfg = _cs_root(interaction.guild.id)
    record = cfg["quotes"].get(str(quote_id))
    if not isinstance(record, dict):
        return await cinnamon_send(interaction, "Quote not found.", ephemeral=True)
    if int(record.get("submitted_by", 0)) != interaction.user.id and not interaction.user.guild_permissions.manage_messages:
        return await cinnamon_send(interaction, "Only the submitter or a moderator with Manage Messages can remove this quote.", ephemeral=True)
    before = _cs_copy.deepcopy(record)
    cfg["quotes"].pop(str(quote_id), None)
    if not await bd_save_data():
        cfg["quotes"][str(quote_id)] = before
        return await cinnamon_send(interaction, "Couldn't save quote removal.", ephemeral=True)
    await cinnamon_send(interaction, "Quote removed.", ephemeral=True)

bot.tree.add_command(quote_group)

rep_group = app_commands.Group(name="rep", description="Give and view community reputation")

@rep_group.command(name="give", description="Give one reputation point to another member")
@app_commands.guild_only()
@app_commands.describe(member="Member who earned your reputation point", reason="Optional reason")
async def community_rep_give(interaction: discord.Interaction, member: discord.Member, reason: str = ""):
    gid, giver_id, target_id = interaction.guild.id, interaction.user.id, member.id
    if member.bot or giver_id == target_id:
        return await cinnamon_send(interaction, "You can give reputation to another human member, not yourself or a bot.", ephemeral=True)
    async with _cs_lock(gid, "rep"):
        cfg = _cs_root(gid)
        last = int(cfg["rep_given"].get(str(giver_id), 0))
        remaining = 86400 - (int(_cs_time.time()) - last)
        if remaining > 0:
            return await cinnamon_send(interaction, f"You can give another reputation point in {remaining // 3600}h {(remaining % 3600) // 60}m.", ephemeral=True)
        before = _cs_copy.deepcopy(cfg)
        scores = cfg["rep_scores"]
        scores[str(target_id)] = int(scores.get(str(target_id), 0)) + 1
        cfg["rep_given"][str(giver_id)] = int(_cs_time.time())
        if not await bd_save_data():
            cfg.clear()
            cfg.update(before)
            return await cinnamon_send(interaction, "Couldn't save the reputation point.", ephemeral=True)
    try:
        await send_log(gid, title="Community reputation given",
            description="A member gave another member a reputation point.",
            category="community",
            fields=[("Giver ID", str(giver_id)), ("Recipient ID", str(target_id)),
                    ("Reason", str(reason or "Not provided")[:300])])
    except Exception:
        log.exception("Reputation audit failed")
    await cinnamon_send(interaction, f"You gave {member.mention} a reputation point. They now have **{scores[str(target_id)]}**.", ephemeral=True)

@rep_group.command(name="leaderboard", description="View the server reputation leaderboard")
@app_commands.guild_only()
async def community_rep_leaderboard(interaction: discord.Interaction):
    cfg = _cs_root(interaction.guild.id)
    scores = sorted(((int(uid), int(score)) for uid, score in cfg["rep_scores"].items()),
                    key=lambda x: x[1], reverse=True)[:10]
    lines = []
    for rank, (uid, score) in enumerate(scores, 1):
        member = interaction.guild.get_member(uid)
        lines.append(f"**{rank}.** {member.display_name if member else 'Former member'} — {score} rep")
    e = discord.Embed(title="🏅 Community Reputation", description="\n".join(lines) or "No reputation points yet.", color=0xE8A05A)
    await interaction.response.send_message(embed=e, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

bot.tree.add_command(rep_group)

team_group = app_commands.Group(name="team", description="Create and manage community teams")

async def _team_autocomplete(interaction, current):
    if not interaction.guild:
        return []
    teams = _cs_root(interaction.guild.id)["teams"]
    query = str(current or "").lower()
    return [app_commands.Choice(name=str(team.get("name", slug))[:100], value=slug)
            for slug, team in teams.items()
            if query in slug.lower() or query in str(team.get("name", "")).lower()][:25]

@team_group.command(name="create", description="Create a community team")
@app_commands.guild_only()
async def community_team_create(interaction: discord.Interaction, name: app_commands.Range[str, 2, 24]):
    gid, uid = interaction.guild.id, interaction.user.id
    slug = _cs_team_slug(name)
    if len(slug) < 2:
        return await cinnamon_send(interaction, "Team names need at least two letters or numbers.", ephemeral=True)
    async with _cs_lock(gid, "teams"):
        cfg = _cs_root(gid)
        if str(uid) in cfg["team_members"]:
            return await cinnamon_send(interaction, "Leave your current team before creating another.", ephemeral=True)
        if slug in cfg["teams"]:
            return await cinnamon_send(interaction, "That team name is already taken.", ephemeral=True)
        before = _cs_copy.deepcopy(cfg)
        cfg["teams"][slug] = {"name": " ".join(str(name).split()), "owner_id": uid,
                              "members": [uid], "created_at": int(_cs_time.time())}
        cfg["team_members"][str(uid)] = slug
        if not await bd_save_data():
            cfg.clear()
            cfg.update(before)
            return await cinnamon_send(interaction, "Couldn't save the new team.", ephemeral=True)
    await cinnamon_send(interaction, f"Created team **{name}**. Share its name so other members can join.", ephemeral=True)

@team_group.command(name="join", description="Join an existing community team")
@app_commands.guild_only()
@app_commands.autocomplete(team_name=_team_autocomplete)
async def community_team_join(interaction: discord.Interaction, team_name: str):
    gid, uid, slug = interaction.guild.id, interaction.user.id, str(team_name).lower()
    async with _cs_lock(gid, "teams"):
        cfg = _cs_root(gid)
        team = cfg["teams"].get(slug)
        if not isinstance(team, dict):
            return await cinnamon_send(interaction, "Team not found. Search using autocomplete.", ephemeral=True)
        if str(uid) in cfg["team_members"]:
            return await cinnamon_send(interaction, "You are already in a team.", ephemeral=True)
        if len(team.get("members", [])) >= 10:
            return await cinnamon_send(interaction, "That team has reached its 10-member limit.", ephemeral=True)
        before = _cs_copy.deepcopy(cfg)
        team["members"].append(uid)
        cfg["team_members"][str(uid)] = slug
        if not await bd_save_data():
            cfg.clear()
            cfg.update(before)
            return await cinnamon_send(interaction, "Couldn't save your team membership.", ephemeral=True)
    await cinnamon_send(interaction, f"You joined **{team['name']}**.", ephemeral=True)

@team_group.command(name="leave", description="Leave your current community team")
@app_commands.guild_only()
async def community_team_leave(interaction: discord.Interaction):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _cs_lock(gid, "teams"):
        cfg = _cs_root(gid)
        slug = cfg["team_members"].get(str(uid))
        team = cfg["teams"].get(slug) if slug else None
        if not isinstance(team, dict):
            return await cinnamon_send(interaction, "You are not in a team.", ephemeral=True)
        before = _cs_copy.deepcopy(cfg)
        team["members"] = [int(x) for x in team.get("members", []) if int(x) != uid]
        cfg["team_members"].pop(str(uid), None)
        if int(team.get("owner_id", 0)) == uid:
            if team["members"]:
                team["owner_id"] = team["members"][0]
            else:
                cfg["teams"].pop(slug, None)
        if not await bd_save_data():
            cfg.clear()
            cfg.update(before)
            return await cinnamon_send(interaction, "Couldn't save your team change.", ephemeral=True)
    await cinnamon_send(interaction, "You left your team.", ephemeral=True)

@team_group.command(name="info", description="View a community team's members")
@app_commands.guild_only()
@app_commands.autocomplete(team_name=_team_autocomplete)
async def community_team_info(interaction: discord.Interaction, team_name: str | None = None):
    cfg = _cs_root(interaction.guild.id)
    slug = str(team_name or cfg["team_members"].get(str(interaction.user.id), "")).lower()
    team = cfg["teams"].get(slug)
    if not isinstance(team, dict):
        return await cinnamon_send(interaction, "Team not found. Join one or choose it from autocomplete.", ephemeral=True)
    members = []
    for uid in team.get("members", []):
        member = interaction.guild.get_member(int(uid))
        members.append(member.mention if member else f"Former member {uid}")
    e = discord.Embed(title="👥 " + str(team.get("name", "Community team")),
        description="\n".join(members) or "No members.", color=0x91B5A2)
    owner = interaction.guild.get_member(int(team.get("owner_id", 0)))
    e.add_field(name="Team owner", value=owner.mention if owner else "Former member", inline=True)
    e.add_field(name="Members", value=f"{len(members)}/10", inline=True)
    await interaction.response.send_message(embed=e, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

@team_group.command(name="leaderboard", description="Rank community teams by combined Catnip balances")
@app_commands.guild_only()
async def community_team_leaderboard(interaction: discord.Interaction):
    cfg = _cs_root(interaction.guild.id)
    ranked = []
    for slug, team in cfg["teams"].items():
        total = sum(economy_balance(interaction.guild.id, int(uid)) for uid in team.get("members", []))
        ranked.append((str(team.get("name", slug)), total, len(team.get("members", []))))
    ranked.sort(key=lambda x: x[1], reverse=True)
    lines = [f"**{i}. {name}** — {total:,} Catnip · {members} member(s)"
             for i, (name, total, members) in enumerate(ranked[:10], 1)]
    e = discord.Embed(title="🏆 Team Leaderboard", description="\n".join(lines) or "No teams yet.", color=0xE8A05A)
    await interaction.response.send_message(embed=e, ephemeral=True)

@team_group.command(name="disband", description="Disband a team you own")
@app_commands.guild_only()
@app_commands.autocomplete(team_name=_team_autocomplete)
async def community_team_disband(interaction: discord.Interaction, team_name: str | None = None):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _cs_lock(gid, "teams"):
        cfg = _cs_root(gid)
        slug = str(team_name or cfg["team_members"].get(str(uid), "")).lower()
        team = cfg["teams"].get(slug)
        if not isinstance(team, dict) or int(team.get("owner_id", 0)) != uid:
            return await cinnamon_send(interaction, "Only the team owner can disband it.", ephemeral=True)
        before = _cs_copy.deepcopy(cfg)
        for member_id in team.get("members", []):
            cfg["team_members"].pop(str(member_id), None)
        cfg["teams"].pop(slug, None)
        if not await bd_save_data():
            cfg.clear()
            cfg.update(before)
            return await cinnamon_send(interaction, "Couldn't save team disbanding.", ephemeral=True)
    await cinnamon_send(interaction, "Team disbanded.", ephemeral=True)

bot.tree.add_command(team_group)

challenge_group = app_commands.Group(name="challenge", description="Join community message challenges and earn Catnip")

@challenge_group.command(name="create", description="Create a server-wide activity challenge")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(name="Challenge name", messages_goal="Messages each participant needs",
                       reward_catnip="Catnip reward per participant", duration_hours="Challenge length in hours")
async def community_challenge_create(interaction: discord.Interaction,
        name: app_commands.Range[str, 2, 80],
        messages_goal: app_commands.Range[int, 1, 500],
        reward_catnip: app_commands.Range[int, 1, 10000],
        duration_hours: app_commands.Range[int, 1, 168] = 48):
    gid = interaction.guild.id
    async with _cs_lock(gid, "challenge"):
        cfg = _cs_root(gid)
        current = cfg.get("challenge")
        if isinstance(current, dict) and current.get("status") == "active":
            return await cinnamon_send(interaction, "A community challenge is already active. End it before creating another.", ephemeral=True)
        before = _cs_copy.deepcopy(current)
        now = int(_cs_time.time())
        cfg["challenge"] = {
            "name": " ".join(str(name).split()), "goal": int(messages_goal),
            "reward": int(reward_catnip), "creator_id": int(interaction.user.id),
            "created_at": now, "ends_at": now + int(duration_hours) * 3600,
            "status": "active", "participants": [], "progress": {},
            "last_message_at": {}, "claimed": [],
        }
        if not await bd_save_data():
            cfg["challenge"] = before
            return await cinnamon_send(interaction, "Couldn't save the challenge.", ephemeral=True)
    await cinnamon_send(interaction, f"Community challenge **{name}** created. Members can join with /challenge join.", ephemeral=True)

@challenge_group.command(name="join", description="Join the active community challenge")
@app_commands.guild_only()
async def community_challenge_join(interaction: discord.Interaction):
    gid, uid = interaction.guild.id, interaction.user.id
    async with _cs_lock(gid, "challenge"):
        cfg = _cs_root(gid)
        challenge = cfg.get("challenge")
        if not isinstance(challenge, dict) or challenge.get("status") != "active" or int(challenge.get("ends_at", 0)) <= int(_cs_time.time()):
            return await cinnamon_send(interaction, "There is no active community challenge.", ephemeral=True)
        if uid in challenge["participants"]:
            return await cinnamon_send(interaction, "You already joined this challenge.", ephemeral=True)
        before = _cs_copy.deepcopy(challenge)
        challenge["participants"].append(uid)
        challenge["progress"][str(uid)] = 0
        if not await bd_save_data():
            cfg["challenge"] = before
            return await cinnamon_send(interaction, "Couldn't save your participation.", ephemeral=True)
    await cinnamon_send(interaction, f"You joined **{challenge['name']}**. Your progress starts now.", ephemeral=True)

@challenge_group.command(name="progress", description="View your community challenge progress")
@app_commands.guild_only()
async def community_challenge_progress(interaction: discord.Interaction):
    challenge = _cs_root(interaction.guild.id).get("challenge")
    if not isinstance(challenge, dict):
        return await cinnamon_send(interaction, "No community challenge has been created yet.", ephemeral=True)
    uid = str(interaction.user.id)
    progress = int(challenge.get("progress", {}).get(uid, 0))
    goal = int(challenge.get("goal", 0))
    joined = interaction.user.id in challenge.get("participants", [])
    claimed = interaction.user.id in challenge.get("claimed", [])
    e = discord.Embed(title="🎯 " + str(challenge.get("name", "Community challenge")),
        description=f"Your progress: **{progress}/{goal}** messages\nReward: **{int(challenge.get('reward', 0)):,} Catnip**",
        color=0x91B5A2)
    e.add_field(name="Participation", value="Joined" if joined else "Not joined", inline=True)
    e.add_field(name="Reward", value="Claimed" if claimed else ("Ready to claim" if joined and progress >= goal else "Not ready"), inline=True)
    e.add_field(name="Ends", value=f"<t:{int(challenge.get('ends_at', 0))}:R>", inline=True)
    await interaction.response.send_message(embed=e, ephemeral=True)

@challenge_group.command(name="claim", description="Claim your reward after reaching the challenge goal")
@app_commands.guild_only()
async def community_challenge_claim(interaction: discord.Interaction):
    gid, uid = interaction.guild.id, interaction.user.id
    lock = _CINNAMON_SHOP_LOCKS.setdefault((gid, uid), _cs_asyncio.Lock())
    async with _cs_lock(gid, "challenge"):
        async with lock:
            cfg = _cs_root(gid)
            challenge = cfg.get("challenge")
            if not isinstance(challenge, dict) or uid not in challenge.get("participants", []):
                return await cinnamon_send(interaction, "Join an active challenge before claiming its reward.", ephemeral=True)
            if uid in challenge.get("claimed", []):
                return await cinnamon_send(interaction, "You already claimed this challenge reward.", ephemeral=True)
            if int(challenge.get("progress", {}).get(str(uid), 0)) < int(challenge.get("goal", 0)):
                return await cinnamon_send(interaction, "You haven't reached the message goal yet.", ephemeral=True)
            before = _cs_copy.deepcopy(challenge)
            balance = economy_balance(gid, uid)
            reward = int(challenge.get("reward", 0))
            economy_balances[(gid, uid)] = balance + reward
            challenge.setdefault("claimed", []).append(uid)
            if not await bd_save_data():
                economy_balances[(gid, uid)] = balance
                cfg["challenge"] = before
                return await cinnamon_send(interaction, "Couldn't save your reward. Your balance was restored.", ephemeral=True)
    await economy_log(gid, title="Community challenge reward claimed", fields=[
        ("Member", f"{interaction.user} ({uid})"), ("Challenge", challenge.get("name", "Challenge")),
        ("Reward", f"{reward:,} Catnip")])
    await cinnamon_send(interaction, f"Challenge complete! You earned **{reward:,} Catnip**.", ephemeral=True)

@challenge_group.command(name="end", description="End the active community challenge")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def community_challenge_end(interaction: discord.Interaction):
    cfg = _cs_root(interaction.guild.id)
    challenge = cfg.get("challenge")
    if not isinstance(challenge, dict) or challenge.get("status") != "active":
        return await cinnamon_send(interaction, "There is no active challenge to end.", ephemeral=True)
    before = _cs_copy.deepcopy(challenge)
    challenge["status"] = "ended"
    challenge["ended_at"] = int(_cs_time.time())
    if not await bd_save_data():
        cfg["challenge"] = before
        return await cinnamon_send(interaction, "Couldn't save challenge closure.", ephemeral=True)
    await cinnamon_send(interaction, "Community challenge ended. Members who reached the goal can still claim their rewards.", ephemeral=True)

bot.tree.add_command(challenge_group)

@bot.listen("on_message")
async def _community_challenge_message(message):
    if not message.guild or message.author.bot or len((message.content or "").strip()) < 5:
        return
    cfg = _cs_root(message.guild.id)
    challenge = cfg.get("challenge")
    if not isinstance(challenge, dict) or challenge.get("status") != "active":
        return
    uid = int(message.author.id)
    if uid not in challenge.get("participants", []):
        return
    now = int(_cs_time.time())
    if now >= int(challenge.get("ends_at", 0)):
        return
    last = int(challenge.get("last_message_at", {}).get(str(uid), 0))
    if now - last < 60:
        return
    async with _cs_lock(message.guild.id, "challenge"):
        challenge = _cs_root(message.guild.id).get("challenge")
        if not isinstance(challenge, dict) or challenge.get("status") != "active":
            return
        last = int(challenge.get("last_message_at", {}).get(str(uid), 0))
        if now - last < 60:
            return
        before_progress = int(challenge.get("progress", {}).get(str(uid), 0))
        challenge.setdefault("progress", {})[str(uid)] = before_progress + 1
        challenge.setdefault("last_message_at", {})[str(uid)] = now
        if not await bd_save_data():
            challenge["progress"][str(uid)] = before_progress
            if last:
                challenge["last_message_at"][str(uid)] = last
            else:
                challenge["last_message_at"].pop(str(uid), None)


