"""Cinnamon feature module.

Loaded by main.py into Cinnamon's shared runtime namespace. This is still
one Discord bot and one process; this file is not a separate bot.
Do not run this file directly.
"""



# --- Warnings -------------------------------------------------------------

def add_warning(guild_id: int, member_id: int, reason: str, moderator: discord.abc.User) -> int:
    lst = warnings_data[(guild_id, member_id)]
    lst.append({
        "reason": reason, "mod_id": moderator.id, "mod_name": str(moderator),
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    return len(lst)


_WARN_LOG_TITLES = {"⚠️ Member warned", "🚨 Auto-mod action"}
_ID_IN_PARENS_RE = re.compile(r"\((\d+)\)\s*$")


async def recover_warnings_from_log(guild: discord.Guild, limit: int = 2000) -> int:
    """Rebuild this guild's warnings entirely from the mod log channel's message
    history — used when the persisted store comes back empty for a guild that
    has a log channel configured. Only recovers what's still in the channel's
    scanned history (bounded by `limit` messages and Discord's own retention),
    so this is a best-effort recovery, not a guarantee of completeness."""
    channel_id = log_channels.get(guild.id)
    if channel_id is None:
        return 0
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.HTTPException, discord.NotFound, discord.Forbidden) as exc:
            log.warning(f"Cannot access moderation log channel {channel_id} for recovery: {type(exc).__name__}")
            return 0

    found: list[tuple[int, dict]] = []  # (member_id, warning_dict)
    max_case = 0
    try:
        async for message in channel.history(limit=limit):
            for embed in message.embeds:
                case_val = next((f.value for f in embed.fields if f.name == "Case"), "")
                if case_val.lstrip("#").isdigit():
                    max_case = max(max_case, int(case_val.lstrip("#")))
                if embed.title not in _WARN_LOG_TITLES:
                    continue
                fields = {f.name: f.value for f in embed.fields}
                member_field = fields.get("Member", "")
                m = _ID_IN_PARENS_RE.search(member_field)
                if not m:
                    continue
                member_id = int(m.group(1))
                reason = fields.get("Reason", "Unknown (recovered from log)")
                if embed.title == "🚨 Auto-mod action":
                    reason = f"[Auto-mod] {reason}"
                    mod_name = "Auto-mod (recovered)"
                    mod_id = bot.user.id if bot.user else 0
                else:
                    footer_m = re.search(r"Run by (.+?) • #", embed.footer.text or "") if embed.footer else None
                    mod_name = footer_m.group(1) if footer_m else "Unknown (recovered from log)"
                    mod_id = 0
                ts = embed.timestamp.isoformat() if embed.timestamp else datetime.datetime.now(datetime.timezone.utc).isoformat()
                found.append((member_id, {"reason": reason, "mod_id": mod_id, "mod_name": mod_name, "ts": ts}))
    except discord.HTTPException as e:
        log.error(f"Failed to scan log channel for warning recovery in guild {guild.id}: {e}")
        return 0

    if max_case > case_counters.get(guild.id, 0):
        case_counters[guild.id] = max_case  # so new cases continue after the highest one logged
        await bd_save_data()
    if not found:
        return 0
    found.sort(key=lambda pair: pair[1]["ts"])  # oldest first, matching normal append order
    recovered_count = 0
    for member_id, warning in found:
        existing = warnings_data[(guild.id, member_id)]
        signature = (warning.get("ts"), warning.get("reason"), warning.get("mod_name"))
        if any((item.get("ts"), item.get("reason"), item.get("mod_name")) == signature for item in existing):
            continue
        existing.append(warning)
        recovered_count += 1
    if recovered_count or max_case > case_counters.get(guild.id, 0):
        await bd_save_data()
    return recovered_count


@bot.tree.command(name="warn", description="Warn a member and log it")
@app_commands.describe(member="Who to warn", reason="Why")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def warn(interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 300]):
    count = add_warning(interaction.guild.id, member.id, reason, interaction.user)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await cinnamon_send(interaction, 
        f"🐾 *hisses a warning at* {member.mention} — now has **{count}** warning(s). (Case #{case_id})",
        allowed_mentions=discord.AllowedMentions(users=True),
    )
    await send_log(
        interaction.guild.id, title="⚠️ Member warned", color=discord.Color.orange(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Reason", reason), ("Total warnings", str(count))],
    )


@bot.tree.command(name="warnings", description="View a member's warning history")
@app_commands.describe(member="Whose warnings to view")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def warnings_cmd(interaction: discord.Interaction, member: discord.Member):
    lst = warnings_data.get((interaction.guild.id, member.id), [])
    if not lst:
        return await cinnamon_send(interaction, f"{member.display_name} has no warnings. 🐾", ephemeral=True)
    embed = discord.Embed(title=f"⚠️ Warnings for {member.display_name}", color=discord.Color.orange())
    for i, w in enumerate(lst[-10:], 1):
        embed.add_field(name=f"#{i} — {w['ts'][:10]}", value=f"{w['reason']} (by {w['mod_name']})", inline=False)
    embed.set_footer(text=f"{len(lst)} total warning(s)")
    await interaction.response.send_message(embed=cinnamon_polish_embed(embed), ephemeral=True)


@bot.tree.command(name="clearwarnings", description="Clear all warnings for a member")
@app_commands.describe(member="Whose warnings to clear")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    removed = len(warnings_data.pop((interaction.guild.id, member.id), []))
    await bd_save_data()
    await cinnamon_send(interaction, f"🐾 Cleared **{removed}** warning(s) for {member.display_name}.")
    await send_log(
        interaction.guild.id, title="🧹 Warnings cleared", color=discord.Color.green(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})"), ("Cleared", str(removed))],
    )


# --- User / server info -----------------------------------------------------

@bot.tree.command(name="userinfo", description="Show info about a member")
@app_commands.describe(member="Who to look up (defaults to you)")
@app_commands.guild_only()
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    warn_count = len(warnings_data.get((interaction.guild.id, member.id), []))
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    embed = discord.Embed(
        title=f"🐾 {member.display_name}",
        color=member.color if member.color.value else 0xFFB02E,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
    embed.add_field(
        name="Joined server",
        value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Unknown", inline=True,
    )
    embed.add_field(name="Warnings", value=str(warn_count), inline=True)
    embed.add_field(name=f"Roles ({len(roles)})", value=", ".join(roles) if roles else "None", inline=False)
    await interaction.response.send_message(embed=cinnamon_polish_embed(embed), allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="serverinfo", description="Show info about this server")
@app_commands.guild_only()
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(title=f"🐾 {g.name}", color=0xFFB02E)
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, "R"), inline=True)
    embed.add_field(name="Members", value=str(g.member_count), inline=True)
    embed.add_field(name="Boost tier", value=str(g.premium_tier), inline=True)
    embed.add_field(name="Text channels", value=str(len(g.text_channels)), inline=True)
    embed.add_field(name="Voice channels", value=str(len(g.voice_channels)), inline=True)
    embed.add_field(name="Roles", value=str(len(g.roles)), inline=True)
    embed.add_field(name="Owner", value=g.owner.mention if g.owner else "Unknown", inline=True)
    await interaction.response.send_message(embed=cinnamon_polish_embed(embed), allowed_mentions=discord.AllowedMentions.none())


# --- AFK ---------------------------------------------------------------------

@bot.tree.command(name="afk", description="Mark yourself AFK; Cinnamon notifies anyone who pings you")
@app_commands.describe(reason="Optional reason")
@app_commands.guild_only()
async def afk_cmd(interaction: discord.Interaction, reason: str = "AFK"):
    afk_users[(interaction.guild.id, interaction.user.id)] = reason[:200]
    await cinnamon_send(interaction, 
        f"🐾 {interaction.user.mention} is now AFK: {reason}",
        allowed_mentions=discord.AllowedMentions(users=True),
    )
    await send_log(interaction.guild.id, title="💤 AFK status set", interaction=interaction, category="general",
                   fields=[("User", f"{interaction.user} ({interaction.user.id})"), ("Reason", reason[:200])])


# --- Welcome / goodbye messages ----------------------------------------------

welcome_group = app_commands.Group(name="welcome", description="Configure member-join messages")


def _validate_template(message: str) -> str | None:
    """Returns an error string if the template has a bad placeholder, else None."""
    try:
        message.format(member="x", server="y")
        return None
    except (KeyError, IndexError, ValueError) as e:
        return (
            f"That message template isn't valid ({e}). Only `{{member}}` and `{{server}}` "
            f"are supported as placeholders — check for typos or stray `{{`/`}}`."
        )


@welcome_group.command(name="set", description="Set the welcome channel/message")
@app_commands.describe(channel="Channel to post welcomes in", message="Use {member} and {server} as placeholders")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def welcome_set(interaction: discord.Interaction, channel: discord.TextChannel,
                       message: app_commands.Range[str, 1, 800] = "🐾 Welcome {member} to {server}! Glad you're here."):
    error = _validate_template(message)
    if error:
        return await cinnamon_send(interaction, error, ephemeral=True)
    welcome_config[interaction.guild.id] = {"channel_id": channel.id, "message": message}
    await bd_save_data()
    await cinnamon_send(interaction, f"🐾 Welcome messages will post in {channel.mention}.")
    await send_log(interaction.guild.id, title="👋 Welcome configuration changed", interaction=interaction, category="setup",
                   fields=[("Channel", channel.mention), ("Message", message[:900])])


@welcome_group.command(name="disable", description="Turn off welcome messages")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def welcome_disable(interaction: discord.Interaction):
    welcome_config.pop(interaction.guild.id, None)
    await bd_save_data()
    await cinnamon_send(interaction, "🐾 Welcome messages turned off.")
    await send_log(interaction.guild.id, title="👋 Welcome messages disabled", interaction=interaction, category="setup")


goodbye_group = app_commands.Group(name="goodbye", description="Configure member-leave messages")


@goodbye_group.command(name="set", description="Set the goodbye channel/message")
@app_commands.describe(channel="Channel to post goodbyes in", message="Use {member} and {server} as placeholders")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def goodbye_set(interaction: discord.Interaction, channel: discord.TextChannel,
                       message: app_commands.Range[str, 1, 800] = "🐾 {member} has left {server}. We'll miss you!"):
    error = _validate_template(message)
    if error:
        return await cinnamon_send(interaction, error, ephemeral=True)
    goodbye_config[interaction.guild.id] = {"channel_id": channel.id, "message": message}
    await bd_save_data()
    await cinnamon_send(interaction, f"🐾 Goodbye messages will post in {channel.mention}.")
    await send_log(interaction.guild.id, title="🚪 Goodbye configuration changed", interaction=interaction, category="setup",
                   fields=[("Channel", channel.mention), ("Message", message[:900])])


@goodbye_group.command(name="disable", description="Turn off goodbye messages")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def goodbye_disable(interaction: discord.Interaction):
    goodbye_config.pop(interaction.guild.id, None)
    await bd_save_data()
    await cinnamon_send(interaction, "🐾 Goodbye messages turned off.")
    await send_log(interaction.guild.id, title="🚪 Goodbye messages disabled", interaction=interaction, category="setup")


# --- Reaction roles (self-assignable, via button) ----------------------------

class ReactionRoleView(discord.ui.View):
    """timeout=None + a static custom_id makes this a persistent view: it keeps
    working across restarts as long as bot.add_view() is called again for the
    same role_id on startup (done in on_ready, from reaction_role_ids)."""

    def __init__(self, role_id: int, label: str = "Toggle Role 🐾"):
        super().__init__(timeout=None)
        self.role_id = role_id
        button = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary, custom_id=f"rr:{role_id}")
        button.callback = self.toggle
        self.add_item(button)

    async def toggle(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            return await cinnamon_send(interaction, "That role no longer exists.", ephemeral=True)
        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Reaction role toggle")
                await cinnamon_send(interaction, f"➖ Removed **{role.name}**.", ephemeral=True)
                await send_log(interaction.guild.id, title="🏷️ Self-assign role removed", category="roles",
                               fields=[("Member", f"{member} ({member.id})"), ("Role", f"{role.name} ({role.id})")])
            else:
                await member.add_roles(role, reason="Reaction role toggle")
                await cinnamon_send(interaction, f"➕ Added **{role.name}**!", ephemeral=True)
                await send_log(interaction.guild.id, title="🏷️ Self-assign role added", category="roles",
                               fields=[("Member", f"{member} ({member.id})"), ("Role", f"{role.name} ({role.id})")])
        except discord.Forbidden:
            await cinnamon_send(interaction, 
                "I don't have permission to manage that role — check my role position.", ephemeral=True
            )


reactionrole_group = app_commands.Group(name="reactionrole", description="Self-assignable roles via a button")


@reactionrole_group.command(name="create", description="Post a button members can click to toggle a role")
@app_commands.describe(role="The role to toggle", label="Button text", description="Message shown above the button")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def reactionrole_create(interaction: discord.Interaction, role: discord.Role,
                               label: str = "Toggle Role 🐾", description: str = None):
    if role >= interaction.guild.me.top_role:
        return await cinnamon_send(interaction, 
            "I can't manage a role higher than or equal to my own top role — move my role above it first.",
            ephemeral=True,
        )
    embed = discord.Embed(
        title="🐾 Self-Assignable Role",
        description=description or f"Click below to toggle **{role.name}**.",
        color=0xFFB02E,
    )
    view = ReactionRoleView(role.id, label)
    await interaction.response.send_message(embed=cinnamon_polish_embed(embed), view=view)
    reaction_role_ids.add(role.id)
    await bd_save_data()
    bot.add_view(view)  # re-register for persistence in case this process restarts
    await send_log(interaction.guild.id, title="🏷️ Reaction role created", interaction=interaction, category="roles",
                   fields=[("Role", f"{role.name} ({role.id})"), ("Button label", label[:80])])


@reactionrole_group.command(name="remove", description="Stop a role from being self-assignable")
@app_commands.describe(role="The role to stop tracking")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def reactionrole_remove(interaction: discord.Interaction, role: discord.Role):
    reaction_role_ids.discard(role.id)
    await bd_save_data()
    await cinnamon_send(interaction, 
        f"🐾 **{role.name}** is no longer tracked as self-assignable. (Existing buttons for it stop working "
        f"after the next restart; this doesn't delete the message.)",
        ephemeral=True,
    )
    await send_log(interaction.guild.id, title="🏷️ Reaction role removed", interaction=interaction, category="roles",
                   fields=[("Role", f"{role.name} ({role.id})")])


# --- Auto-moderation -----------------------------------------------------------

DEFAULT_AUTOMOD = {"words": [], "spam": False, "mentions": False, "invites": False, "mention_threshold": 5}
_INVITE_RE = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)\S+", re.IGNORECASE)


def get_automod(guild_id: int) -> dict:
    return automod_config.setdefault(guild_id, dict(DEFAULT_AUTOMOD))


async def _automod_strike(message: discord.Message, reason: str):
    try:
        await message.delete()
    except discord.HTTPException:
        pass
    count = add_warning(
        message.guild.id, message.author.id, f"[Auto-mod] {reason}",
        bot.user if bot.user else message.author,
    )
    case_id = next_case(message.guild.id)
    await bd_save_data()
    try:
        note = await message.channel.send(
            f"🐾 {message.author.mention}, that got removed for {reason}. Warning #{count} logged.",
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        await asyncio.sleep(6)
        await note.delete()
    except discord.HTTPException:
        pass
    await send_log(
        message.guild.id, title="🚨 Auto-mod action", color=discord.Color.red(),
        fields=[("Case", f"#{case_id}"), ("Member", f"{message.author} ({message.author.id})"), ("Reason", reason),
                ("Channel", message.channel.mention)],
    )


async def run_automod(message: discord.Message) -> bool:
    """Returns True if the message was removed (caller should stop processing it)."""
    if message.author.guild_permissions.manage_messages:
        return False  # mods bypass auto-mod
    cfg = automod_config.get(message.guild.id)
    if not cfg:
        return False

    if cfg.get("invites") and _INVITE_RE.search(message.content):
        await _automod_strike(message, "posting a Discord invite link")
        return True

    content_lower = message.content.lower()
    for w in cfg.get("words", []):
        if w and w.lower() in content_lower:
            await _automod_strike(message, "using a banned word")
            return True

    if cfg.get("mentions") and (len(message.mentions) + len(message.role_mentions)) >= cfg.get("mention_threshold", 5):
        await _automod_strike(message, "mass-mentioning members/roles")
        return True

    if cfg.get("spam"):
        key = (message.guild.id, message.author.id)
        dq = spam_tracker[key]
        dq.append(time.monotonic())
        if len(dq) == dq.maxlen and (dq[-1] - dq[0]) < 5:  # 6 msgs within 5s
            await _automod_strike(message, "spamming messages")
            return True

    return False


automod_group = app_commands.Group(name="automod", description="Configure auto-moderation")
automod_word_group = app_commands.Group(name="word", description="Manage banned words", parent=automod_group)


@automod_word_group.command(name="add", description="Add a banned word/phrase")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def automod_word_add(interaction: discord.Interaction, word: app_commands.Range[str, 1, 100]):
    cfg = get_automod(interaction.guild.id)
    changed = word.lower() not in (w.lower() for w in cfg["words"])
    if changed:
        cfg["words"].append(word)
        await bd_save_data()
    await cinnamon_send(interaction, f"🐾 Added `{word}` to the banned word list.", ephemeral=True)
    await send_log(interaction.guild.id, title="🛡️ AutoMod banned word added", interaction=interaction, category="moderation",
                   fields=[("Word/phrase", word[:300]), ("Changed", str(changed))])


@automod_word_group.command(name="remove", description="Remove a banned word/phrase")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def automod_word_remove(interaction: discord.Interaction, word: app_commands.Range[str, 1, 100]):
    cfg = get_automod(interaction.guild.id)
    before = len(cfg["words"])
    cfg["words"] = [w for w in cfg["words"] if w.lower() != word.lower()]
    removed = before - len(cfg["words"])
    await bd_save_data()
    await cinnamon_send(interaction, f"🐾 Removed `{word}` from the banned word list.", ephemeral=True)
    await send_log(interaction.guild.id, title="🛡️ AutoMod banned word removed", interaction=interaction, category="moderation",
                   fields=[("Word/phrase", word[:300]), ("Removed", str(removed))])


@automod_word_group.command(name="list", description="List banned words")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def automod_word_list(interaction: discord.Interaction):
    words = get_automod(interaction.guild.id)["words"]
    await cinnamon_send(interaction, 
        "Banned words: " + (", ".join(f"`{w}`" for w in words) if words else "*(none set)*"), ephemeral=True
    )


@automod_group.command(name="spam", description="Toggle spam detection (rapid repeated messages)")
@app_commands.describe(enabled="On/off")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def automod_spam(interaction: discord.Interaction, enabled: bool):
    get_automod(interaction.guild.id)["spam"] = enabled
    await bd_save_data()
    await cinnamon_send(interaction, f"🐾 Spam detection turned **{'on' if enabled else 'off'}**.")
    await send_log(interaction.guild.id, title="🛡️ AutoMod spam setting changed", interaction=interaction, category="moderation", fields=[("Enabled", str(enabled))])


@automod_group.command(name="mentions", description="Toggle mass-mention detection")
@app_commands.describe(enabled="On/off", threshold="Mentions in one message that triggers it (default 5)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def automod_mentions(interaction: discord.Interaction, enabled: bool, threshold: int = 5):
    cfg = get_automod(interaction.guild.id)
    cfg["mentions"] = enabled
    cfg["mention_threshold"] = threshold
    await bd_save_data()
    await cinnamon_send(interaction, 
        f"🐾 Mass-mention detection turned **{'on' if enabled else 'off'}** (threshold {threshold})."
    )
    await send_log(interaction.guild.id, title="🛡️ AutoMod mention setting changed", interaction=interaction, category="moderation",
                   fields=[("Enabled", str(enabled)), ("Threshold", str(threshold))])


@automod_group.command(name="invites", description="Toggle auto-deleting Discord invite links")
@app_commands.describe(enabled="On/off")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def automod_invites(interaction: discord.Interaction, enabled: bool):
    get_automod(interaction.guild.id)["invites"] = enabled
    await bd_save_data()
    await cinnamon_send(interaction, f"🐾 Invite-link filter turned **{'on' if enabled else 'off'}**.")
    await send_log(interaction.guild.id, title="🛡️ AutoMod invite filter changed", interaction=interaction, category="moderation", fields=[("Enabled", str(enabled))])


# --- Temp-ban ------------------------------------------------------------------

@bot.tree.command(name="tempban", description="Temporarily ban a member; auto-unbanned after the duration")
@app_commands.describe(member="Who to ban", duration_hours="Hours until auto-unban", reason="Why")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
@app_commands.guild_only()
async def tempban(interaction: discord.Interaction, member: discord.Member, duration_hours: float,
                   reason: app_commands.Range[str, 1, 300] = "No reason given"):
    unban_at = time.time() + duration_hours * 3600
    await member.ban(reason=f"Tempban by {interaction.user}: {reason}")
    temp_bans[(interaction.guild.id, member.id)] = unban_at
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await cinnamon_send(interaction, 
        f"🐾 {member.mention} temp-banned for **{duration_hours}h**. Reason: {reason}",
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await send_log(
        interaction.guild.id, title="⏳ Member temp-banned", color=discord.Color.red(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Duration", f"{duration_hours}h"), ("Reason", reason)],
    )


@tasks.loop(minutes=5)
async def check_tempbans():
    now = time.time()
    due = [key for key, unban_at in temp_bans.items() if unban_at <= now]
    for guild_id, user_id in due:
        guild = bot.get_guild(guild_id)
        if guild:
            try:
                await guild.unban(discord.Object(id=user_id), reason="Temp-ban expired")
                await send_log(
                    guild_id, title="⏳ Temp-ban expired — member unbanned", color=discord.Color.green(),
                    fields=[("User ID", str(user_id))],
                )
            except discord.HTTPException:
                pass
        temp_bans.pop((guild_id, user_id), None)
    if due:
        await bd_save_data()


# --- Leveling / XP --------------------------------------------------------------

