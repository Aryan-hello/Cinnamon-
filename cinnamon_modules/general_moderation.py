"""Cinnamon feature module.

Loaded by main.py into Cinnamon's shared runtime namespace. This is still
one Discord bot and one process; this file is not a separate bot.
Do not run this file directly.
"""

@bot.tree.command(name="pet", description="Give Cinnamon some pets")
async def pet(interaction: discord.Interaction):
    await interaction.response.send_message(
        "*melts into a puddle of fluff, purring loudly* Purrrrr... more, please?"
    )


@bot.tree.command(name="treat", description="Offer Cinnamon a treat")
async def treat(interaction: discord.Interaction):
    await interaction.response.send_message(
        "*ears perk up, pupils go huge* Tuna?? Churu?? ANYTHING?? *sits so politely*"
    )


@bot.tree.command(name="nap", description="Let Cinnamon take a nap")
async def nap(interaction: discord.Interaction):
    await interaction.response.send_message(
        "*curls into a tight loaf on the nearest keyboard* Zzz... five more minutes..."
    )


@bot.tree.command(name="zoomies", description="Uh oh, Cinnamon has the zoomies")
async def zoomies(interaction: discord.Interaction):
    await interaction.response.send_message(
        "*tears across the room sideways, tail puffed* WHO TURNED ON THE FLOOR IS LAVA?!"
    )


# ---------------------------------------------------------------------------
# AI channel configuration (mods only)
# ---------------------------------------------------------------------------

@bot.tree.command(name="aichannel", description="Make Cinnamon reply to every message in this channel, no mention needed")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def aichannel(interaction: discord.Interaction):
    ai_channels[interaction.guild.id] = interaction.channel.id
    await bd_save_data()
    await interaction.response.send_message(
        f"*claims {interaction.channel.mention} as her own* I'll chat here without being mentioned now!"
    )
    await send_log(
        interaction.guild.id, title="⚙️ AI channel set", interaction=interaction,
        fields=[("Channel", interaction.channel.mention)],
    )


@bot.tree.command(name="disableaichannel", description="Turn off Cinnamon's always-on AI channel for this server")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def disableaichannel(interaction: discord.Interaction):
    removed = ai_channels.pop(interaction.guild.id, None)
    await bd_save_data()
    if removed:
        await interaction.response.send_message(
            "*stretches and wanders off* Back to needing a mention or reply now."
        )
        await send_log(interaction.guild.id, title="⚙️ AI channel disabled", interaction=interaction)
    else:
        await interaction.response.send_message(
            "*blinks* There wasn't an AI channel set for this server.", ephemeral=True
        )


@bot.tree.command(name="disableai", description="Stop Cinnamon from talking in this channel at all")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def disableai(interaction: discord.Interaction):
    disabled_channels[interaction.guild.id].add(interaction.channel.id)
    await bd_save_data()
    await interaction.response.send_message(
        "*curls up and goes quiet* Won't respond in this channel anymore, even if mentioned."
    )
    await send_log(
        interaction.guild.id, title="⚙️ Channel muted for AI", interaction=interaction,
        fields=[("Channel", interaction.channel.mention)],
    )


@bot.tree.command(name="enableai", description="Let Cinnamon talk in this channel again")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def enableai(interaction: discord.Interaction):
    disabled_channels[interaction.guild.id].discard(interaction.channel.id)
    await bd_save_data()
    await interaction.response.send_message("*perks back up* I can talk here again!")
    await send_log(
        interaction.guild.id, title="⚙️ Channel re-enabled for AI", interaction=interaction,
        fields=[("Channel", interaction.channel.mention)],
    )


@bot.tree.command(name="logchannel", description="Set this channel as Cinnamon's log channel for mod actions and errors")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def logchannel(interaction: discord.Interaction):
    log_channels[interaction.guild.id] = interaction.channel.id
    await secure_log_channel(interaction.channel)
    await bd_save_data()
    status = await storage_status()
    icon = "✅" if status["connected"] else "⚠️"
    await interaction.response.send_message(
        f"*sets up a little logbook in {interaction.channel.mention}* "
        f"I'll post mod actions, config changes, and errors here from now on.\n\n"
        f"{icon} **Storage:** {status['backend']} — {status['detail']}"
    )
    await send_log(
        interaction.guild.id,
        title="📋 Log channel set",
        description=f"This channel is now Cinnamon's log channel.",
        color=discord.Color.blurple(),
        interaction=interaction,
        fields=[("Storage backend", status["backend"]), ("Connected", "Yes" if status["connected"] else "No")],
    )


@bot.tree.command(name="disablelogchannel", description="Stop Cinnamon from posting logs anywhere in this server")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def disablelogchannel(interaction: discord.Interaction):
    removed = log_channels.pop(interaction.guild.id, None)
    await bd_save_data()
    if removed:
        await interaction.response.send_message("*closes the logbook* Stopped logging actions for this server.")
        await send_log(interaction.guild.id, title="📋 Main log channel disabled", interaction=interaction, category="setup",
                       fields=[("Previous channel ID", str(removed))])
    else:
        await interaction.response.send_message(
            "*blinks* There wasn't a log channel set for this server.", ephemeral=True
        )


# ---------------------------------------------------------------------------
# Moderation commands (mods only)
# ---------------------------------------------------------------------------

@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Who to kick", reason="Why are they being kicked?")
@app_commands.guild_only()
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.checks.bot_has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member,
               reason: app_commands.Range[str, 1, 300] = "No reason given"):
    await member.kick(reason=reason)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(f"*escorts {member.mention} out with a paw* Kicked. Reason: {reason}")
    await send_log(
        interaction.guild.id, title="👢 Member kicked", color=discord.Color.orange(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Reason", reason)],
    )


@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Who to ban", reason="Why are they being banned?")
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member,
              reason: app_commands.Range[str, 1, 300] = "No reason given"):
    await member.ban(reason=reason, delete_message_seconds=0)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(f"*hisses and swats {member.mention} out the door* Banned. Reason: {reason}")
    await send_log(
        interaction.guild.id, title="🔨 Member banned", color=discord.Color.red(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Reason", reason)],
    )


@bot.tree.command(name="unban", description="Unban a user using their user ID")
@app_commands.describe(user_id="The numeric ID of the user to unban")
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        await interaction.guild.unban(discord.Object(id=int(user_id)))
        temp_bans.pop((interaction.guild.id, int(user_id)), None)  # in case it was also a tempban
        case_id = next_case(interaction.guild.id)
        await bd_save_data()
        await interaction.response.send_message(f"*nudges the door back open* Unbanned <@{user_id}>.")
        await send_log(
            interaction.guild.id, title="🔓 Member unbanned", color=discord.Color.green(), interaction=interaction,
            fields=[("Case", f"#{case_id}"), ("User ID", str(int(user_id)))],
        )
    except (ValueError, discord.NotFound):
        await interaction.response.send_message(
            "*tilts head* Couldn't find that user ID on the ban list.", ephemeral=True
        )


@bot.tree.command(name="mute", description="Timeout a member so they can't send messages for a while")
@app_commands.describe(member="Who to mute", minutes="How many minutes to mute for", reason="Why are they being muted?")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, member: discord.Member, minutes: int = 10,
               reason: app_commands.Range[str, 1, 300] = "No reason given"):
    await member.timeout(datetime.timedelta(minutes=minutes), reason=reason)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(
        f"*sits on {member.mention}'s keyboard* Muted for {minutes} minute(s). Reason: {reason}"
    )
    await send_log(
        interaction.guild.id, title="🔇 Member muted", color=discord.Color.orange(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Duration", f"{minutes} min"), ("Reason", reason)],
    )


@bot.tree.command(name="unmute", description="Remove a member's timeout early")
@app_commands.describe(member="Who to unmute")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(f"*hops off the keyboard* {member.mention} can talk again.")
    await send_log(
        interaction.guild.id, title="🔊 Member unmuted", color=discord.Color.green(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})")],
    )


@bot.tree.command(name="purge", description="Delete a number of recent messages in this channel")
@app_commands.describe(amount="How many messages to delete (1-100)")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"*sweeps up {len(deleted)} messages with her tail* All tidy now!", ephemeral=True)
    await send_log(
        interaction.guild.id, title="🧹 Messages purged", color=discord.Color.light_grey(), interaction=interaction,
        fields=[("Channel", interaction.channel.mention), ("Deleted", str(len(deleted)))],
    )


@bot.tree.command(name="slowmode", description="Set slowmode (message rate limit) for a channel")
@app_commands.describe(
    seconds="Seconds each member must wait between messages (0 turns it off, max 21600 = 6 hours)",
    channel="Channel to apply it to (defaults to this channel)",
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: int,
                    channel: discord.TextChannel = None):
    target = channel or interaction.channel
    await target.edit(slowmode_delay=seconds)
    if seconds == 0:
        msg = f"*stops pacing the room* Slowmode's off in {target.mention}."
    else:
        msg = f"*sets a little hourglass* Slowmode set to {seconds}s in {target.mention}."
    await interaction.response.send_message(msg)
    await send_log(
        interaction.guild.id, title="🐌 Slowmode changed", color=discord.Color.blurple(), interaction=interaction,
        fields=[("Channel", target.mention), ("Seconds", str(seconds))],
    )


# ---------------------------------------------------------------------------
# Role commands (mods only) — grouped under /role
# ---------------------------------------------------------------------------

role_group = app_commands.Group(name="role", description="Add roles to members")


@role_group.command(name="add", description="Add a role to one specific member")
@app_commands.describe(member="Who to give the role to", role="Which role to add")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def role_add(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.add_roles(role, reason=f"/role add run by {interaction.user}")
    await interaction.response.send_message(
        f"*drapes **{role.name}** over {member.mention}* Done!",
        allowed_mentions=discord.AllowedMentions(roles=False),
    )
    await send_log(
        interaction.guild.id, title="🏷️ Role added", color=discord.Color.green(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})"), ("Role", role.name)],
    )


@role_group.command(name="add-all", description="Add a role to every member in the server")
@app_commands.describe(
    role="Which role to add to everyone",
    include_bots="Also give the role to bot accounts (default: no)",
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_roles=True, manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def role_add_all(interaction: discord.Interaction, role: discord.Role, include_bots: bool = False):
    if role.is_default():
        await interaction.response.send_message("*tilts head* Everyone already has @everyone!", ephemeral=True)
        return
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            "*can't quite reach that high* That role sits above (or level with) my own top role — "
            "move my role above it in Server Settings → Roles first.", ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)
    targets = [m for m in interaction.guild.members if role not in m.roles and (include_bots or not m.bot)]

    added, failed = 0, 0
    for member in targets:
        try:
            await member.add_roles(role, reason=f"/role add-all run by {interaction.user}")
            added += 1
        except discord.HTTPException:
            failed += 1

    summary = f"*stamps **{role.name}** onto {added} member(s)* All done!"
    if failed:
        summary += f" ({failed} couldn't be given the role — probably role hierarchy.)"
    await interaction.followup.send(summary, allowed_mentions=discord.AllowedMentions(roles=False))
    await send_log(
        interaction.guild.id, title="🏷️ Role added to all members", color=discord.Color.green(), interaction=interaction,
        fields=[("Role", role.name), ("Added", str(added)), ("Failed", str(failed))],
    )


bot.tree.add_command(role_group)


# ---------------------------------------------------------------------------
# Friendly errors for missing permissions, instead of a raw Discord error
# ---------------------------------------------------------------------------

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Command exceptions arrive wrapped in CommandInvokeError — unwrap to get
    # at the real Discord exception so we can tell what actually went wrong.
    original = error.original if isinstance(error, app_commands.CommandInvokeError) else error

    if isinstance(error, app_commands.MissingPermissions):
        msg = "*narrows eyes* You don't have the paws for that command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "*paws helplessly* I don't have permission to do that — check my role's permissions in Server Settings."
    elif isinstance(original, discord.Forbidden):
        # The classic cause: Discord blocks the action even with the right permission
        # if the bot's role isn't positioned above the target's highest role (or if
        # the target has Administrator, for timeouts specifically).
        msg = (
            "*paws helplessly* Discord won't let me do that to them. This usually means "
            "my role needs to be moved *above* their role in Server Settings → Roles "
            "(drag my role near the top). Members with Administrator also can't be muted, "
            "by Discord's own rules."
        )
    elif isinstance(original, discord.NotFound):
        msg = "*tilts head* Couldn't find that — they may have already left, or it no longer exists."
    else:
        log.error(f"Command error in /{interaction.command.name if interaction.command else '?'}: {original!r}")
        msg = "*knocks something off a shelf* Something went wrong running that."

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)

    await send_log(
        interaction.guild.id if interaction.guild else None,
        title="⚠️ Command error",
        description=(
            f"`/{interaction.command.name if interaction.command else 'unknown'}` "
            f"failed with: `{original!r}`"
        ),
        color=discord.Color.red(),
        interaction=interaction,
        category=_command_log_category(interaction.command.qualified_name if interaction.command else ""),
    )


# ---------------------------------------------------------------------------
# Keep-alive web server (Koyeb / Render free tiers expect something bound
# to $PORT). Runs in a background thread alongside the bot.
# ---------------------------------------------------------------------------

