"""Moderation operations: private notes, appeals, verification, autoroles and onboarding."""
import copy as _mc_copy
import datetime as _mc_dt
import time as _mc_time
import uuid as _mc_uuid

_MC_KEY = "cinnamon_moderation_controls_v1"
_MC_VIEWS_READY = False
_MC_LOCKS = {}
moderation_tools_group = app_commands.Group(name="moderation-tools", description="Verification, onboarding, moderator notes and appeals")

def _mc_root(gid):
    root = advanced_features_data.setdefault(_MC_KEY, {})
    cfg = root.setdefault(str(int(gid)), {})
    for key, default in (
        ("notes", {}), ("appeals", {}), ("appeal_channel_id", 0),
        ("verification_channel_id", 0), ("verification_role_id", 0),
        ("verification_message_id", 0), ("autorole_id", 0),
        ("onboarding", {}),
    ):
        cfg.setdefault(key, _mc_copy.deepcopy(default))
    return cfg

def _mc_is_mod(member):
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_messages or perms.moderate_members))


async def _mc_decide_appeal(guild_id, appeal_id, decision, moderator_id, note=None):
    """Serialize appeal decisions and persist exactly one moderator outcome."""
    lock = _MC_LOCKS.setdefault(int(guild_id), asyncio.Lock())
    async with lock:
        cfg = _mc_root(guild_id)
        record = cfg["appeals"].get(str(appeal_id))
        if not isinstance(record, dict) or record.get("status") != "pending":
            return "not_pending", None
        before = _mc_copy.deepcopy(record)
        record["status"] = str(decision)
        record["reviewed_by"] = int(moderator_id)
        record["reviewed_at"] = int(_mc_time.time())
        if note is not None:
            record["review_note"] = str(note or "")[:500]
        try:
            saved = await bd_save_data()
        except Exception:
            saved = False
        if not saved:
            cfg["appeals"][str(appeal_id)] = before
            return "save_failed", None
        return "ok", _mc_copy.deepcopy(record)

async def _mc_restore_message(guild, channel_id, message_id, embed, view):
    channel = guild.get_channel(int(channel_id))
    if not channel:
        return
    try:
        message = await channel.fetch_message(int(message_id))
        await message.edit(embed=embed, view=view)
    except discord.HTTPException:
        pass

class CinnamonVerificationView(discord.ui.View):
    def __init__(self, guild_id, disabled=False):
        super().__init__(timeout=None)
        self.guild_id = int(guild_id)
        button = discord.ui.Button(label="Verify", emoji="✅", style=discord.ButtonStyle.success,
            custom_id=f"cinnamon:verification:{self.guild_id}", disabled=disabled)
        button.callback = self._verify
        self.add_item(button)

    async def _verify(self, interaction):
        if not interaction.guild or interaction.guild.id != self.guild_id:
            return await interaction.response.send_message("This verification panel belongs to another server.", ephemeral=True)
        cfg = _mc_root(self.guild_id)
        role = interaction.guild.get_role(int(cfg.get("verification_role_id", 0) or 0))
        if not role:
            return await interaction.response.send_message("The verification role is no longer configured. Ask an administrator.", ephemeral=True)
        if role >= interaction.guild.me.top_role or not interaction.guild.me.guild_permissions.manage_roles:
            return await interaction.response.send_message("Cinnamon cannot assign the configured verification role. An administrator must move the bot role higher.", ephemeral=True)
        if role in interaction.user.roles:
            return await interaction.response.send_message("You're already verified.", ephemeral=True)
        try:
            await interaction.user.add_roles(role, reason="Cinnamon verification button")
        except discord.Forbidden:
            return await interaction.response.send_message("Cinnamon doesn't have permission to assign that role.", ephemeral=True)
        await interaction.response.send_message("Verification complete. Welcome!", ephemeral=True)

@moderation_tools_group.command(name="verification", description="Post or disable a member verification panel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(channel="Channel for the verification panel", role="Role members receive after verification")
async def moderation_verification(interaction: discord.Interaction,
                                  channel: discord.TextChannel | None = None,
                                  role: discord.Role | None = None):
    cfg = _mc_root(interaction.guild.id)
    if channel is None and role is None:
        old = (cfg.get("verification_channel_id", 0), cfg.get("verification_role_id", 0), cfg.get("verification_message_id", 0))
        cfg["verification_channel_id"] = cfg["verification_role_id"] = cfg["verification_message_id"] = 0
        if not await bd_save_data():
            cfg["verification_channel_id"], cfg["verification_role_id"], cfg["verification_message_id"] = old
            return await cinnamon_send(interaction, "Couldn't disable verification.", ephemeral=True)
        return await cinnamon_send(interaction, "Verification panel disabled. Existing verified roles are unchanged.", ephemeral=True)
    if channel is None or role is None:
        return await cinnamon_send(interaction, "Provide both a channel and a role, or omit both to disable the panel.", ephemeral=True)
    if role >= interaction.guild.me.top_role or not interaction.guild.me.guild_permissions.manage_roles:
        return await cinnamon_send(interaction, "Move Cinnamon's bot role above the verification role and grant Manage Roles.", ephemeral=True)
    perms = channel.permissions_for(interaction.guild.me)
    if not (perms.view_channel and perms.send_messages and perms.embed_links):
        return await cinnamon_send(interaction, "Cinnamon needs View Channel, Send Messages and Embed Links in that channel.", ephemeral=True)
    embed = discord.Embed(title="🔐 Server Verification",
        description=f"Press **Verify** below to receive {role.mention} and finish server verification.",
        color=0x91B5A2)
    message = await channel.send(embed=embed, view=CinnamonVerificationView(interaction.guild.id),
                                 allowed_mentions=discord.AllowedMentions.none())
    before = (cfg.get("verification_channel_id", 0), cfg.get("verification_role_id", 0), cfg.get("verification_message_id", 0))
    cfg["verification_channel_id"], cfg["verification_role_id"], cfg["verification_message_id"] = channel.id, role.id, message.id
    if not await bd_save_data():
        cfg["verification_channel_id"], cfg["verification_role_id"], cfg["verification_message_id"] = before
        try: await message.delete()
        except discord.HTTPException: pass
        return await cinnamon_send(interaction, "Couldn't save verification settings; the panel was removed.", ephemeral=True)
    await cinnamon_send(interaction, f"Verification panel posted in {channel.mention}.", ephemeral=True)

autorole_group = app_commands.Group(name="autorole", description="Configure automatic roles for new members")
moderation_tools_group.add_command(autorole_group)

@autorole_group.command(name="set", description="Set the role automatically assigned to new members")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_roles=True)
async def moderation_autorole_set(interaction: discord.Interaction, role: discord.Role):
    if role >= interaction.guild.me.top_role or not interaction.guild.me.guild_permissions.manage_roles:
        return await cinnamon_send(interaction, "Cinnamon's bot role must be above the autorole and have Manage Roles.", ephemeral=True)
    cfg = _mc_root(interaction.guild.id)
    old = int(cfg.get("autorole_id", 0) or 0)
    cfg["autorole_id"] = int(role.id)
    if not await bd_save_data():
        cfg["autorole_id"] = old
        return await cinnamon_send(interaction, "Couldn't save autorole settings.", ephemeral=True)
    await cinnamon_send(interaction, f"New members will receive {role.mention}.", ephemeral=True)

@autorole_group.command(name="disable", description="Disable automatic role assignment")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_roles=True)
async def moderation_autorole_disable(interaction: discord.Interaction):
    cfg = _mc_root(interaction.guild.id)
    old = int(cfg.get("autorole_id", 0) or 0)
    cfg["autorole_id"] = 0
    if not await bd_save_data():
        cfg["autorole_id"] = old
        return await cinnamon_send(interaction, "Couldn't disable autorole.", ephemeral=True)
    await cinnamon_send(interaction, "Automatic role assignment disabled.", ephemeral=True)


onboarding_group = app_commands.Group(name="onboarding", description="Configure new-member welcome and rules information")
moderation_tools_group.add_command(onboarding_group)

@onboarding_group.command(name="configure", description="Configure welcome channel and rules link")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(welcome_channel="Channel for new-member welcome messages",
                       rules_channel="Channel containing server rules")
async def moderation_onboarding_configure(interaction: discord.Interaction,
        welcome_channel: discord.TextChannel | None = None,
        rules_channel: discord.TextChannel | None = None):
    if welcome_channel is None and rules_channel is None:
        return await cinnamon_send(interaction, "Provide at least one channel to configure.", ephemeral=True)
    cfg = _mc_root(interaction.guild.id)
    before = _mc_copy.deepcopy(cfg.get("onboarding", {}))
    settings = cfg.setdefault("onboarding", {})
    if welcome_channel is not None: settings["welcome_channel_id"] = int(welcome_channel.id)
    if rules_channel is not None: settings["rules_channel_id"] = int(rules_channel.id)
    if not await bd_save_data():
        cfg["onboarding"] = before
        return await cinnamon_send(interaction, "Couldn't save onboarding settings.", ephemeral=True)
    parts = []
    if welcome_channel: parts.append("welcome messages in " + welcome_channel.mention)
    if rules_channel: parts.append("rules in " + rules_channel.mention)
    await cinnamon_send(interaction, "Configured " + " and ".join(parts) + ".", ephemeral=True)

@onboarding_group.command(name="status", description="View current onboarding settings")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def moderation_onboarding_status(interaction: discord.Interaction):
    cfg = _mc_root(interaction.guild.id)
    settings = cfg.get("onboarding", {})
    welcome = interaction.guild.get_channel(int(settings.get("welcome_channel_id", 0) or 0))
    rules = interaction.guild.get_channel(int(settings.get("rules_channel_id", 0) or 0))
    autorole = interaction.guild.get_role(int(cfg.get("autorole_id", 0) or 0))
    verify = interaction.guild.get_role(int(cfg.get("verification_role_id", 0) or 0))
    e = discord.Embed(title="👋 Member Onboarding Settings", color=0x91B5A2)
    e.add_field(name="Welcome channel", value=welcome.mention if welcome else "Not configured", inline=True)
    e.add_field(name="Rules channel", value=rules.mention if rules else "Not configured", inline=True)
    e.add_field(name="Autorole", value=autorole.mention if autorole else "Disabled", inline=True)
    e.add_field(name="Verification role", value=verify.mention if verify else "Not configured", inline=True)
    await interaction.response.send_message(embed=e, ephemeral=True)


modnote_group = app_commands.Group(name="modnote", description="Private moderator notes about server members")
moderation_tools_group.add_command(modnote_group)

@modnote_group.command(name="add", description="Add a private moderator note about a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(member="Member the note concerns", note="Private note text")
async def moderation_note_add(interaction: discord.Interaction, member: discord.Member,
                              note: app_commands.Range[str, 3, 700]):
    gid = interaction.guild.id
    cfg = _mc_root(gid)
    note_id = _mc_uuid.uuid4().hex[:8]
    cfg["notes"].setdefault(str(member.id), {})[note_id] = {
        "text": str(note).strip(), "created_by": int(interaction.user.id),
        "created_at": int(_mc_time.time()),
    }
    if not await bd_save_data():
        cfg["notes"].get(str(member.id), {}).pop(note_id, None)
        return await cinnamon_send(interaction, "Couldn't save the moderator note.", ephemeral=True)
    await cinnamon_send(interaction, f"Private note saved for {member.mention}. Note ID: {note_id}.", ephemeral=True)

@modnote_group.command(name="list", description="View private moderator notes for a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
async def moderation_note_list(interaction: discord.Interaction, member: discord.Member):
    records = _mc_root(interaction.guild.id)["notes"].get(str(member.id), {})
    lines = []
    for note_id, record in list(records.items())[-10:]:
        lines.append(f"**{note_id}** — {record.get('text', '')[:700]}\nAdded by ID {record.get('created_by', 'unknown')}")
    await cinnamon_send(interaction, "\n\n".join(lines) or "No private moderator notes for this member.", ephemeral=True)

@modnote_group.command(name="remove", description="Remove a private moderator note")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
async def moderation_note_remove(interaction: discord.Interaction, member: discord.Member, note_id: str):
    cfg = _mc_root(interaction.guild.id)
    notes = cfg["notes"].get(str(member.id), {})
    record = notes.pop(str(note_id), None)
    if not isinstance(record, dict):
        return await cinnamon_send(interaction, "Moderator note not found.", ephemeral=True)
    if not await bd_save_data():
        notes[str(note_id)] = record
        return await cinnamon_send(interaction, "Couldn't save note removal.", ephemeral=True)
    await cinnamon_send(interaction, "Moderator note removed.", ephemeral=True)


appeal_group = app_commands.Group(name="appeal", description="Submit and review moderation appeals")
moderation_tools_group.add_command(appeal_group)

@appeal_group.command(name="settings", description="Set the private channel for moderation appeals")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def moderation_appeal_settings(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    cfg = _mc_root(interaction.guild.id)
    if channel and channel.permissions_for(interaction.guild.default_role).view_channel:
        return await cinnamon_send(interaction, "Appeal channels must be private so member details are not exposed.", ephemeral=True)
    old = int(cfg.get("appeal_channel_id", 0) or 0)
    cfg["appeal_channel_id"] = int(channel.id) if channel else 0
    if not await bd_save_data():
        cfg["appeal_channel_id"] = old
        return await cinnamon_send(interaction, "Couldn't save appeal settings.", ephemeral=True)
    await cinnamon_send(interaction, "Appeals will be sent to " + channel.mention + "." if channel else "Appeals are disabled.", ephemeral=True)

class ModerationAppealView(discord.ui.View):
    def __init__(self, guild_id, appeal_id, disabled=False):
        super().__init__(timeout=None)
        self.guild_id, self.appeal_id = int(guild_id), str(appeal_id)
        for label, value, style in (
            ("Approve", "approved", discord.ButtonStyle.success),
            ("Decline", "declined", discord.ButtonStyle.danger),
        ):
            button = discord.ui.Button(label=label, style=style,
                custom_id=f"cinnamon:appeal:{self.guild_id}:{self.appeal_id}:{value}",
                disabled=disabled)
            button.callback = self._make_callback(value)
            self.add_item(button)

    def _make_callback(self, decision):
        async def callback(interaction):
            if not interaction.guild or interaction.guild.id != self.guild_id or not _mc_is_mod(interaction.user):
                return await interaction.response.send_message("Only moderators can review appeals.", ephemeral=True)
            result, record = await _mc_decide_appeal(
                self.guild_id, self.appeal_id, decision, interaction.user.id
            )
            if result == "not_pending":
                return await interaction.response.send_message("This appeal has already been reviewed.", ephemeral=True)
            if result != "ok":
                return await interaction.response.send_message("Couldn't save the appeal decision.", ephemeral=True)
            embed = discord.Embed(title="Moderation appeal " + decision.title(),
                description="The appeal has been reviewed by server moderation.",
                color=0x69A982 if decision == "approved" else 0xD97777)
            await interaction.message.edit(embed=embed, view=ModerationAppealView(
                self.guild_id, self.appeal_id, disabled=True))
            try:
                user = await bot.fetch_user(int(record.get("user_id", 0)))
                await user.send(f"Your moderation appeal for **{interaction.guild.name}** was {decision}.")
            except discord.HTTPException:
                pass
            await interaction.response.send_message("Appeal marked " + decision + ".", ephemeral=True)
            try:
                await send_log(self.guild_id, title="Moderation appeal decision", category="moderation", fields=[
                    ("Appeal ID", self.appeal_id),
                    ("Member ID", str(record.get("user_id", "unknown"))),
                    ("Decision", decision),
                    ("Moderator", f"{interaction.user} ({interaction.user.id})"),
                ])
            except Exception:
                log.exception("Could not write appeal decision audit log")
        return callback

@appeal_group.command(name="submit", description="Submit an appeal to a server from a DM with Cinnamon")
@app_commands.describe(guild_id="Server ID for the moderation action", details="Explain your appeal")
async def moderation_appeal_submit(interaction: discord.Interaction, guild_id: str,
                                   details: app_commands.Range[str, 20, 1500]):
    if interaction.guild is not None:
        return await cinnamon_send(interaction, "For privacy, submit appeals by messaging Cinnamon directly.", ephemeral=True)
    if not str(guild_id).isdigit():
        return await cinnamon_send(interaction, "That server ID is not valid.", ephemeral=True)
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return await cinnamon_send(interaction, "Cinnamon isn't in that server.", ephemeral=True)
    cfg = _mc_root(guild.id)
    channel = guild.get_channel(int(cfg.get("appeal_channel_id", 0) or 0))
    if not isinstance(channel, discord.TextChannel):
        return await cinnamon_send(interaction, "That server hasn't configured a private appeal channel.", ephemeral=True)
    now = int(_mc_time.time())
    user_appeals = [
        record for record in cfg["appeals"].values()
        if isinstance(record, dict) and int(record.get("user_id", 0)) == int(interaction.user.id)
    ]
    if any(record.get("status") == "pending" for record in user_appeals):
        return await cinnamon_send(interaction, "You already have a pending appeal for this server. Wait for the moderators to review it.", ephemeral=True)
    recent_submissions = sum(
        1 for record in user_appeals
        if now - int(record.get("submitted_at", 0)) < 86400
    )
    if recent_submissions >= 2:
        return await cinnamon_send(interaction, "For fairness, each member can submit up to two appeals per server every 24 hours.", ephemeral=True)
    appeal_id = _mc_uuid.uuid4().hex[:8]
    record = {"user_id": int(interaction.user.id), "details": str(details).strip()[:1500],
              "status": "pending", "submitted_at": now}
    embed = discord.Embed(title="📨 Moderation Appeal",
        description=str(details).strip()[:1500], color=0xE8A05A)
    embed.add_field(name="Appeal ID", value=appeal_id, inline=True)
    embed.add_field(name="Member ID", value=str(interaction.user.id), inline=True)
    embed.set_footer(text="Private moderation channel • Review buttons are moderator-only")
    message = await channel.send(embed=embed, view=ModerationAppealView(guild.id, appeal_id),
                                 allowed_mentions=discord.AllowedMentions.none())
    record["message_id"], record["channel_id"] = int(message.id), int(channel.id)
    cfg["appeals"][appeal_id] = record
    if not await bd_save_data():
        cfg["appeals"].pop(appeal_id, None)
        try: await message.delete()
        except discord.HTTPException: pass
        return await cinnamon_send(interaction, "Couldn't safely save your appeal. The post was removed.", ephemeral=True)
    await cinnamon_send(interaction, f"Your appeal was sent privately to {guild.name}. Reference: {appeal_id}.", ephemeral=True)
    try:
        await send_log(guild.id, title="Moderation appeal submitted", category="moderation", fields=[
            ("Appeal ID", appeal_id),
            ("Member ID", str(interaction.user.id)),
            ("Submitted at", str(record["submitted_at"])),
        ])
    except Exception:
        log.exception("Could not write appeal submission audit log")

@appeal_group.command(name="review", description="Review an appeal by ID")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.choices(decision=[app_commands.Choice(name="Approved", value="approved"),
                                app_commands.Choice(name="Declined", value="declined")])
async def moderation_appeal_review(interaction: discord.Interaction, appeal_id: str,
                                   decision: app_commands.Choice[str], note: str = ""):
    result, record = await _mc_decide_appeal(
        interaction.guild.id, str(appeal_id), decision.value, interaction.user.id, note
    )
    if result == "not_pending":
        return await cinnamon_send(interaction, "Pending appeal not found or already reviewed.", ephemeral=True)
    if result != "ok":
        return await cinnamon_send(interaction, "Couldn't save the appeal decision.", ephemeral=True)
    try:
        user = await bot.fetch_user(int(record.get("user_id", 0)))
        await user.send(f"Your moderation appeal for **{interaction.guild.name}** was {decision.value}. Moderator note: {record['review_note'] or 'No note provided.'}")
    except discord.HTTPException:
        pass
    await cinnamon_send(interaction, f"Appeal {appeal_id} marked {decision.value}.", ephemeral=True)
    try:
        await send_log(interaction.guild.id, title="Moderation appeal decision", category="moderation", fields=[
            ("Appeal ID", str(appeal_id)),
            ("Member ID", str(record.get("user_id", "unknown"))),
            ("Decision", decision.value),
            ("Moderator", f"{interaction.user} ({interaction.user.id})"),
            ("Review note", str(record.get("review_note", ""))[:500] or "None"),
        ])
    except Exception:
        log.exception("Could not write appeal decision audit log")


@bot.listen("on_member_join")
async def moderation_onboarding_member_join(member):
    cfg = _mc_root(member.guild.id)
    role = member.guild.get_role(int(cfg.get("autorole_id", 0) or 0))
    if role and role < member.guild.me.top_role and member.guild.me.guild_permissions.manage_roles:
        try:
            await member.add_roles(role, reason="Cinnamon autorole")
        except discord.HTTPException:
            log.exception("Cinnamon autorole assignment failed for %s", member.id)
    settings = cfg.get("onboarding", {})
    welcome = member.guild.get_channel(int(settings.get("welcome_channel_id", 0) or 0))
    rules = member.guild.get_channel(int(settings.get("rules_channel_id", 0) or 0))
    if isinstance(welcome, discord.TextChannel):
        message = f"Welcome to **{member.guild.name}**, {member.mention}!"
        if rules:
            message += f" Please read {rules.mention} before chatting."
        try:
            await welcome.send(message, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        except discord.HTTPException:
            log.exception("Cinnamon onboarding welcome failed")

@bot.listen("on_ready")
async def moderation_controls_restore_views():
    global _MC_VIEWS_READY
    if _MC_VIEWS_READY:
        return
    _MC_VIEWS_READY = True
    try:
        for guild_key, cfg in advanced_features_data.get(_MC_KEY, {}).items():
            if not str(guild_key).isdigit() or not isinstance(cfg, dict):
                continue
            gid = int(guild_key)
            if int(cfg.get("verification_message_id", 0) or 0):
                bot.add_view(CinnamonVerificationView(gid))
            for appeal_id, record in (cfg.get("appeals", {}) or {}).items():
                if isinstance(record, dict) and record.get("status") == "pending":
                    bot.add_view(ModerationAppealView(gid, appeal_id))
    except Exception:
        log.exception("Could not restore moderation verification and appeal views")


bot.tree.add_command(moderation_tools_group)
