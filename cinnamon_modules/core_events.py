"""Cinnamon feature module.

Loaded by main.py into Cinnamon's shared runtime namespace. This is still
one Discord bot and one process; this file is not a separate bot.
Do not run this file directly.
"""

def owner_mention(guild: "discord.Guild | None") -> str:
    """Best-effort mention for the bot's owner. A numeric OWNER_USER_ID always
    works; without one, we try to match the username in this server's member
    cache (requires the Server Members Intent and Aryan being in the server)."""
    if OWNER_USER_ID:
        return f"<@{OWNER_USER_ID}>"
    if guild:
        member = discord.utils.get(guild.members, name=OWNER_USERNAME)
        if member:
            return member.mention
    return f"@{OWNER_USERNAME}"


# --- Reactions ----------------------------------------------------------------

async def add_reaction_safely(message: discord.Message, reaction: str):
    """React to a message with a unicode or custom guild emoji. Never raises —
    a failed reaction shouldn't break the rest of the flow."""
    if not reaction:
        return
    emoji_to_use = reaction
    if message.guild:
        custom = discord.utils.get(message.guild.emojis, name=reaction.strip(":"))
        if custom:
            emoji_to_use = custom
    try:
        await message.add_reaction(emoji_to_use)
    except discord.HTTPException as e:
        log.warning(f"Couldn't add reaction {reaction!r}: {e}")


async def secure_log_channel(channel: discord.TextChannel):
    """Restrict audit channels from @everyone while allowing Cinnamon to post.

    Server Administrators retain access through Discord's Administrator bypass.
    Other moderator roles can be granted View Channel manually in channel permissions.
    """
    guild = channel.guild
    await channel.set_permissions(guild.default_role, view_channel=False, reason="Protect Cinnamon audit logs")
    if guild.me is not None:
        await channel.set_permissions(
            guild.me, view_channel=True, send_messages=True, embed_links=True,
            read_message_history=True, reason="Allow Cinnamon to write audit logs",
        )


async def send_log(guild_id: int | None, *, title: str, description: str = "",
                    color: discord.Color = discord.Color.blurple(),
                    interaction: discord.Interaction | None = None,
                    fields: list[tuple[str, str]] | None = None,
                    category: str | None = None):
    """Post an embed to the guild's configured log channel, if any. Never raises —
    logging should never be the thing that breaks a command."""
    if guild_id is None:
        return
    # Route events to a category-specific channel, falling back to the legacy
    # main log channel when that category has not been configured.
    if category is None:
        lowered = (title + " " + description).lower()
        if any(x in lowered for x in ("economy", "catnip", "shop item", "income role", "cinnamon fed", "tuna")):
            category = "economy"
        elif any(x in lowered for x in ("ai ", " ai", "gemini", "channel re-enabled for ai", "ai channel")):
            category = "ai"
        elif any(x in lowered for x in ("level", "xp", "rank")):
            category = "levels"
        elif any(x in lowered for x in ("giveaway", "poll")):
            category = "community"
        elif any(x in lowered for x in ("role added", "role removed", "reaction role", "role income")):
            category = "roles"
        elif any(x in lowered for x in ("welcome", "goodbye", "setup", "configuration", "log channel")):
            category = "setup"
        elif any(x in lowered for x in ("userinfo", "serverinfo", "afk", "ping", "status", "help")):
            category = "general"
        else:
            category = "moderation"
    channel_id = category_log_channels.get(guild_id, {}).get(category)
    if channel_id is None:
        channel_id = log_channels.get(guild_id)
    if channel_id is None:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    if interaction is not None:
        embed.set_footer(text=f"Run by {interaction.user} • #{interaction.channel}")
    for name, value in (fields or []):
        embed.add_field(name=name, value=value, inline=True)

    try:
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        log.error(f"Failed to send log message to channel {channel_id}: {e}")


def _command_log_category(command_name: str) -> str:
    name = (command_name or "").lower().replace("/", " ").strip()
    root = name.split()[0] if name else ""
    if root in {"economy", "collect"} or "economy" in name:
        return "economy"
    if root in {"ask", "ai", "chat", "aichannel", "disableaichannel", "disableai", "enableai"}:
        return "ai"
    if root in {"rank", "leaderboard", "levelrole"}:
        return "levels"
    if root in {"giveaway", "poll"}:
        return "community"
    if root in {"role", "reactionrole"}:
        return "roles"
    if root in {"setup", "setupstatus", "welcome", "goodbye", "categorylogs", "logchannel", "disablelogchannel"}:
        return "setup"
    if root in {"help", "ping", "botstatus", "userinfo", "serverinfo", "afk"}:
        return "general"
    if root == "hangrygames":
        return "hangrygames"
    return "moderation"


@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    """Audit successful slash command use without storing arguments or AI text."""
    if interaction.guild is None:
        return
    category = _command_log_category(getattr(command, "qualified_name", getattr(command, "name", "")))
    if category == "hangrygames":
        return  # Hangry Games has its own detailed logger/channel.
    await send_log(
        interaction.guild.id, title="📌 Slash command used", interaction=interaction,
        fields=[("Command", "/" + getattr(command, "qualified_name", getattr(command, "name", "unknown"))),
                ("User", f"{interaction.user} ({interaction.user.id})"),
                ("Channel", getattr(interaction.channel, "mention", "Unknown"))],
        category=category,
    )


@bot.event
async def on_command_completion(ctx: commands.Context):
    """Audit successful prefix command use without storing arguments or AI text."""
    if ctx.guild is None:
        return
    category = _command_log_category(getattr(ctx.command, "qualified_name", ""))
    if category == "hangrygames":
        return
    await send_log(
        ctx.guild.id, title="📌 Prefix command used", fields=[("Command", "?" + getattr(ctx.command, "qualified_name", "unknown")),
            ("User", f"{ctx.author} ({ctx.author.id})"), ("Channel", getattr(ctx.channel, "mention", "Unknown"))],
        category=category,
    )


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Log failed prefix invocations without capturing command arguments."""
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.CommandOnCooldown):
        message = f"⏳ Try again in {error.retry_after:.1f} seconds."
    elif isinstance(error, commands.MissingPermissions):
        message = "❌ You don't have permission to use that command."
    elif isinstance(error, commands.BotMissingPermissions):
        message = "❌ Cinnamon is missing a required permission."
    elif isinstance(error, commands.UserInputError):
        message = f"❌ Invalid or missing command argument. Use `?help` for command names and syntax."
    else:
        log.exception("Prefix command failed", exc_info=error)
        message = "❌ That command failed. The issue has been recorded for the bot owner."
    if ctx.guild:
        await send_log(ctx.guild.id, title="⚠️ Prefix command failed", fields=[
            ("Command", "?" + (ctx.command.qualified_name if ctx.command else "unknown")),
            ("User", f"{ctx.author} ({ctx.author.id})"),
            ("Channel", getattr(ctx.channel, "mention", "Unknown")),
            ("Error type", type(error).__name__),
        ], category=_command_log_category(ctx.command.qualified_name if ctx.command else ""))
    try:
        await ctx.reply(message, mention_author=False)
    except discord.HTTPException:
        pass


@bot.event
async def on_ready():
    if bot.get_cog("HangryGamesCog") is None:
        hg_cog = HangryGamesCog(bot)
        await hg_cog.async_init()
        await bot.add_cog(hg_cog)

        # First-run-only setup for the extended features below.
        await bd_load_data()
        for role_id in reaction_role_ids:
            bot.add_view(ReactionRoleView(role_id))
        bot.add_view(GiveawayView())  # persistent: matched by custom_id, state looked up by message ID
        bot.add_view(PollView())
        if not check_timers.is_running():
            check_timers.start()
        if not check_tempbans.is_running():
            check_tempbans.start()
        if not periodic_save.is_running():
            periodic_save.start()

        # --- Data-loss recovery: for any guild with a log channel configured
        # but no matching data loaded (persisted store came back empty), try to
        # rebuild from that channel's own message history before it's needed. ---
        for guild in bot.guilds:
            if guild.id in log_channels and not any(g == guild.id for g, _ in warnings_data.keys()):
                try:
                    recovered = await recover_warnings_from_log(guild)
                    if recovered:
                        log.info(f"Recovered {recovered} warning(s) for guild {guild.id} from its log channel.")
                        await send_log(
                            guild.id, title="🩹 Warnings recovered from log channel", color=discord.Color.gold(),
                            fields=[("Recovered", str(recovered)),
                                    ("Note", "Persisted storage came back empty on startup — rebuilt from this channel's history.")],
                        )
                except Exception as e:
                    log.error(f"Warning recovery failed for guild {guild.id}: {e}")

            if guild.id in hg_cog.hg_log_channels and not hg_cog.game_counts.get(guild.id):
                try:
                    game_num, wins = await hg_cog.recover_from_log(guild)
                    if game_num or wins:
                        log.info(f"Recovered Hangry Games data for guild {guild.id}: game #{game_num}, {wins} win(s).")
                        await hg_cog._log(
                            guild.id, title="🩹 Hangry Games data recovered from log channel", color=discord.Color.gold(),
                            fields=[("Game number restored to", str(game_num)), ("Wins reconstructed", str(wins))],
                        )
                except Exception as e:
                    log.error(f"Hangry Games recovery failed for guild {guild.id}: {e}")

    await bot.tree.sync()
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="for treats 🐟"))
    log.info(f"Cinnamon is online as {bot.user}")


@bot.event
async def on_member_join(member: discord.Member):
    cfg = welcome_config.get(member.guild.id)
    if cfg:
        channel = bot.get_channel(cfg["channel_id"])
        if channel:
            text = cfg["message"].format(member=member.mention, server=member.guild.name)
            try:
                await channel.send(text, allowed_mentions=discord.AllowedMentions(users=True))
            except discord.HTTPException:
                pass
    await check_antiraid(member)
    await send_log(member.guild.id, title="👋 Member joined", fields=[("Member", f"{member} ({member.id})"), ("Account created", discord.utils.format_dt(member.created_at, style="R"))], category="setup")


@bot.event
async def on_member_remove(member: discord.Member):
    cfg = goodbye_config.get(member.guild.id)
    if cfg:
        channel = bot.get_channel(cfg["channel_id"])
        if channel:
            text = cfg["message"].format(member=member.display_name, server=member.guild.name)
            try:
                await channel.send(text)
            except discord.HTTPException:
                pass
    await send_log(member.guild.id, title="🚪 Member left", fields=[("Member", f"{member} ({member.id})")], category="setup")


@bot.event
async def on_message_delete(message: discord.Message):
    if message.guild is None or message.author.bot:
        return
    content = message.content or "*(no text content — embed/attachment only)*"
    await send_log(
        message.guild.id, title="🗑️ Message deleted", color=discord.Color.red(),
        fields=[("Author", f"{message.author} ({message.author.id})"), ("Channel", message.channel.mention),
                ("Content", content[:1000])],
    )


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.guild is None or before.author.bot or before.content == after.content:
        return
    await send_log(
        before.guild.id, title="✏️ Message edited", color=discord.Color.orange(),
        fields=[("Author", f"{before.author} ({before.author.id})"), ("Channel", before.channel.mention),
                ("Before", (before.content or "*(empty)*")[:500]), ("After", (after.content or "*(empty)*")[:500])],
    )



# Main prefix commands. Hangry Games, quests, and achievements stay slash-only.
@bot.command(name="help", aliases=["commands"])
async def prefix_help(ctx):
    e=discord.Embed(title="🐾 Cinnamon — Help",description="Use ? before a command. Mention or ID works for member arguments.",color=discord.Color.blurple())
    e.add_field(name="Moderation",value="`?kick`, `?ban`, `?unban`, `?mute`, `?unmute`, `?warn`, `?warnings`, `?clearwarnings`, `?purge`, `?slowmode`",inline=False)
    e.add_field(name="AI",value="`?ask <message>` (`?ai`, `?chat`)",inline=False)
    e.add_field(name="Normal",value="`?ping`, `?botstatus`, `?userinfo [member]`, `?serverinfo`, `?afk [reason]`, `?rank [member]`, `?leaderboard`",inline=False)
    e.add_field(name="Economy",value="`?balance` (`?bal`, `?wallet`), `?inventory` (`?inv`), `?shop`, `?buy <item> [qty]`, `?daily`, `?work`, `?give <member> <amount>` (`?pay`), `?econlb`",inline=False)
    await ctx.reply(embed=e,mention_author=False)

@bot.command(name="ping")
async def prefix_ping(ctx): await ctx.reply(f"🐾 Pong! {round(bot.latency*1000)} ms",mention_author=False)

@bot.command(name="ask",aliases=["ai","chat"])
@commands.guild_only()
async def prefix_ask(ctx,*,prompt:str):
    if ctx.channel.id in disabled_channels[ctx.guild.id]: return
    async with ctx.typing():
        try: result=await asyncio.to_thread(ask_gemini,ctx.channel.id,ctx.author.display_name,prompt,ctx.guild); reply=result.get("reply") or "*paws at the screen* Try again?"
        except Exception: log.exception("Prefix AI failed"); reply="*paws at the screen, confused* I couldn't answer just now. Try again soon?"
    channel_memories[ctx.channel.id].append((ctx.author.display_name,prompt)); channel_memories[ctx.channel.id].append(("Cinnamon",reply))
    await ctx.reply(reply[:1900],mention_author=False,allowed_mentions=discord.AllowedMentions.none())

@bot.command(name="userinfo",aliases=["whois"])
@commands.guild_only()
async def prefix_userinfo(ctx,member:discord.Member=None):
    m=member or ctx.author; e=discord.Embed(title=f"👤 {m}",color=discord.Color.blurple()); e.add_field(name="ID",value=m.id); e.add_field(name="Joined",value=discord.utils.format_dt(m.joined_at,style="R") if m.joined_at else "Unknown"); e.add_field(name="Created",value=discord.utils.format_dt(m.created_at,style="R")); e.add_field(name="Top role",value=m.top_role.mention); await ctx.reply(embed=e,mention_author=False)

@bot.command(name="serverinfo")
@commands.guild_only()
async def prefix_serverinfo(ctx):
    g=ctx.guild; e=discord.Embed(title=f"🏡 {g.name}",color=discord.Color.blurple()); e.add_field(name="Members",value=str(g.member_count or "Unknown")); e.add_field(name="Created",value=discord.utils.format_dt(g.created_at,style="D")); e.add_field(name="Owner",value=str(g.owner or "Unknown")); e.add_field(name="Channels",value=str(len(g.channels))); await ctx.reply(embed=e,mention_author=False)

@bot.command(name="afk")
@commands.guild_only()
async def prefix_afk(ctx,*,reason="AFK"):
    afk_users[(ctx.guild.id,ctx.author.id)]=reason[:200]
    await ctx.reply(f"🐾 Marked AFK: {reason[:200]}",mention_author=False)
    await send_log(ctx.guild.id,title="💤 AFK status set",fields=[("User",f"{ctx.author} ({ctx.author.id})"),("Reason",reason[:200])],category="general")

@bot.command(name="mute",aliases=["timeout"])
@commands.guild_only()
@commands.has_guild_permissions(moderate_members=True)
@commands.bot_has_guild_permissions(moderate_members=True)
async def prefix_mute(ctx,member:discord.Member,minutes:int=10,*,reason="No reason given"):
    if not 1 <= minutes <= 40320: return await ctx.reply("❌ Minutes must be between 1 and 40,320.",mention_author=False)
    if member==ctx.author or member==ctx.guild.owner or (member.top_role>=ctx.author.top_role and ctx.author.id!=ctx.guild.owner_id) or member.top_role>=ctx.guild.me.top_role: return await ctx.reply("❌ Role hierarchy prevents this action.",mention_author=False)
    await member.timeout(datetime.timedelta(minutes=minutes),reason=reason[:300]); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"🔇 {member.mention} timed out for {minutes} minute(s). Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="🔇 Member muted",color=discord.Color.orange(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})"),("Duration",f"{minutes} min"),("Reason",reason[:300])])

@bot.command(name="unmute",aliases=["untimeout"])
@commands.guild_only()
@commands.has_guild_permissions(moderate_members=True)
@commands.bot_has_guild_permissions(moderate_members=True)
async def prefix_unmute(ctx,member:discord.Member):
    if member.top_role>=ctx.guild.me.top_role: return await ctx.reply("❌ Cinnamon's role must be above the target's role.",mention_author=False)
    await member.timeout(None,reason=f"Unmuted by {ctx.author}"); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"🔊 {member.mention} can talk again. Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="🔊 Member unmuted",color=discord.Color.green(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})")])

@bot.command(name="warn")
@commands.guild_only()
@commands.has_guild_permissions(kick_members=True)
async def prefix_warn(ctx,member:discord.Member,*,reason:str):
    count=add_warning(ctx.guild.id,member.id,reason[:300],ctx.author); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"⚠️ {member.mention} warned — {count} warning(s). Case #{case}.",mention_author=False,allowed_mentions=discord.AllowedMentions(users=True)); await send_log(ctx.guild.id,title="⚠️ Member warned",color=discord.Color.orange(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})"),("Reason",reason[:300]),("Total warnings",str(count))])

@bot.command(name="warnings",aliases=["warns"])
@commands.guild_only()
@commands.has_guild_permissions(kick_members=True)
async def prefix_warnings(ctx,member:discord.Member):
    ws=warnings_data.get((ctx.guild.id,member.id),[])
    if not ws: return await ctx.reply(f"{member.display_name} has no warnings.",mention_author=False)
    e=discord.Embed(title=f"⚠️ Warnings for {member.display_name}",color=discord.Color.orange())
    for i,w in enumerate(ws[-10:],1): e.add_field(name=f"Warning #{i}",value=f"{w.get('reason','No reason')} — {w.get('ts','')[:10]}",inline=False)
    await ctx.reply(embed=e,mention_author=False)

@bot.command(name="clearwarnings",aliases=["clearwarns"])
@commands.guild_only()
@commands.has_guild_permissions(kick_members=True)
async def prefix_clearwarnings(ctx,member:discord.Member):
    removed=len(warnings_data.pop((ctx.guild.id,member.id),[])); await bd_save_data(); await ctx.reply(f"🧹 Cleared {removed} warning(s) for {member.mention}.",mention_author=False); await send_log(ctx.guild.id,title="🧹 Warnings cleared",fields=[("Member",f"{member} ({member.id})"),("Cleared",str(removed))])

@bot.command(name="kick")
@commands.guild_only()
@commands.has_guild_permissions(kick_members=True)
@commands.bot_has_guild_permissions(kick_members=True)
async def prefix_kick(ctx,member:discord.Member,*,reason="No reason given"):
    if member==ctx.author or member==ctx.guild.owner or (member.top_role>=ctx.author.top_role and ctx.author.id!=ctx.guild.owner_id) or member.top_role>=ctx.guild.me.top_role: return await ctx.reply("❌ Role hierarchy prevents this action.",mention_author=False)
    await member.kick(reason=reason[:300]); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"👢 Kicked {member}. Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="👢 Member kicked",color=discord.Color.orange(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})"),("Reason",reason[:300])])

@bot.command(name="ban")
@commands.guild_only()
@commands.has_guild_permissions(ban_members=True)
@commands.bot_has_guild_permissions(ban_members=True)
async def prefix_ban(ctx,member:discord.Member,*,reason="No reason given"):
    if member==ctx.author or member==ctx.guild.owner or (member.top_role>=ctx.author.top_role and ctx.author.id!=ctx.guild.owner_id) or member.top_role>=ctx.guild.me.top_role: return await ctx.reply("❌ Role hierarchy prevents this action.",mention_author=False)
    await member.ban(reason=reason[:300],delete_message_seconds=0); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"🔨 Banned {member}. Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="🔨 Member banned",color=discord.Color.red(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})"),("Reason",reason[:300])])

@bot.command(name="unban")
@commands.guild_only()
@commands.has_guild_permissions(ban_members=True)
@commands.bot_has_guild_permissions(ban_members=True)
async def prefix_unban(ctx,user_id:int):
    await ctx.guild.unban(discord.Object(id=user_id)); temp_bans.pop((ctx.guild.id,user_id),None); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"🔓 Unbanned user `{user_id}`. Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="🔓 Member unbanned",color=discord.Color.green(),fields=[("Case",f"#{case}"),("User ID",str(user_id)),("Moderator",f"{ctx.author} ({ctx.author.id})")])

@bot.command(name="purge",aliases=["clear"])
@commands.guild_only()
@commands.has_guild_permissions(manage_messages=True)
@commands.bot_has_guild_permissions(manage_messages=True)
async def prefix_purge(ctx,amount:int):
    if not 1 <= amount <= 100: return await ctx.reply("❌ Amount must be between 1 and 100.",mention_author=False)
    deleted=await ctx.channel.purge(limit=amount+1); removed=max(0,len(deleted)-1); await ctx.send(f"🧹 Removed {removed} messages.",delete_after=4); await send_log(ctx.guild.id,title="🧹 Messages purged",color=discord.Color.light_grey(),fields=[("Moderator",f"{ctx.author} ({ctx.author.id})"),("Channel",ctx.channel.mention),("Deleted",str(removed))])

@bot.command(name="slowmode")
@commands.guild_only()
@commands.has_guild_permissions(manage_channels=True)
@commands.bot_has_guild_permissions(manage_channels=True)
async def prefix_slowmode(ctx,seconds:int):
    if not 0 <= seconds <= 21600: return await ctx.reply("❌ Seconds must be between 0 and 21,600.",mention_author=False)
    await ctx.channel.edit(slowmode_delay=seconds); await ctx.reply(f"🐌 Slowmode set to {seconds} second(s).",mention_author=False); await send_log(ctx.guild.id,title="🐌 Slowmode changed",fields=[("Moderator",f"{ctx.author} ({ctx.author.id})"),("Channel",ctx.channel.mention),("Seconds",str(seconds))])

@bot.command(name="balance",aliases=["bal","wallet"])
@commands.guild_only()
async def prefix_balance(ctx,member:discord.Member=None):
    m=member or ctx.author; gid=ctx.guild.id; bal=economy_balance(gid,m.id); inv=economy_inventory_for(gid,m.id); total_items=sum(int(v) for v in inv.values()); await ctx.reply(f"👛 **{m.display_name}'s wallet**\n🌿 Catnip: **{bal:,}**\n🎒 Items: **{total_items}**",mention_author=False); await economy_log(gid,title="👛 Economy balance viewed",fields=[("Viewer",f"{ctx.author} ({ctx.author.id})"),("Member",f"{m} ({m.id})"),("Balance",f"{bal:,} Catnip"),("Total items",total_items)]); await bd_save_data()

@bot.command(name="inventory",aliases=["inv","bag"])
@commands.guild_only()
async def prefix_inventory(ctx,member:discord.Member=None):
    m=member or ctx.author; gid=ctx.guild.id; inv=economy_inventory_for(gid,m.id); lines=[f"{ECONOMY_ITEMS[k]['emoji']} **{ECONOMY_ITEMS[k]['name']}** × {v}" for k,v in inv.items() if k in ECONOMY_ITEMS and int(v)>0]; summary="\n".join(f"{ECONOMY_ITEMS[k]['name']}: {int(v)}" for k,v in inv.items() if k in ECONOMY_ITEMS and int(v)>0) or "Empty"; await ctx.reply("\n".join(lines) if lines else "🎒 Inventory is empty. Use `?shop`.",mention_author=False); await economy_log(gid,title="🎒 Economy inventory viewed",fields=[("Viewer",f"{ctx.author} ({ctx.author.id})"),("Member",f"{m} ({m.id})"),("Inventory",summary[:1000]),("Total items",sum(int(v) for v in inv.values())),("Catnip balance",economy_balance(gid,m.id))])

@bot.command(name="shop")
@commands.guild_only()
async def prefix_shop(ctx): await ctx.reply(embed=discord.Embed(title="🐟 Cinnamon's Catnip Shop",description=economy_item_lines(),color=discord.Color.gold()))

@bot.command(name="daily")
@commands.guild_only()
async def prefix_daily(ctx):
    gid,uid=ctx.guild.id,ctx.author.id; rem=economy_cooldown_remaining(gid,uid,"daily")
    if rem: return await ctx.reply(f"🐾 Daily ready in {rem//3600}h {(rem%3600)//60}m.",mention_author=False)
    economy_cooldowns[(gid,uid,"daily")]=time.time()+86400; economy_balances[(gid,uid)]=economy_balance(gid,uid)+ECONOMY_DAILY_REWARD; await bd_save_data(); await economy_log(gid,title="🌿 Daily Catnip",fields=[("User",str(ctx.author)),("Amount",f"+{ECONOMY_DAILY_REWARD}")]); await ctx.reply(f"🌿 +{ECONOMY_DAILY_REWARD} Catnip!",mention_author=False)

@bot.command(name="work")
@commands.guild_only()
async def prefix_work(ctx):
    _,_,msg=await economy_do_work(ctx.guild.id,ctx.author); await ctx.reply(msg,mention_author=False)

@bot.command(name="buy")
@commands.guild_only()
async def prefix_buy(ctx,item:str,quantity:int=1):
    if not 1 <= quantity <= 99: return await ctx.reply("❌ Quantity must be between 1 and 99.",mention_author=False)
    gid,uid=ctx.guild.id,ctx.author.id; item=item.lower().strip(); item=next((k for k,v in ECONOMY_ITEMS.items() if k==item or v["name"].lower()==item),item); data=ECONOMY_ITEMS.get(item)
    if not data: return await ctx.reply("❌ Item not found. Use `?shop`.",mention_author=False)
    bal=economy_balance(gid,uid); cost=data["price"]*quantity
    if bal<cost: return await ctx.reply(f"❌ Need {cost:,} Catnip; you have {bal:,}.",mention_author=False)
    inv=economy_inventory_for(gid,uid); inv[item]=int(inv.get(item,0))+quantity; economy_balances[(gid,uid)]=bal-cost; await bd_save_data(); await economy_log(gid,title="🛒 Economy purchase",fields=[("User",f"{ctx.author} ({uid})"),("Item",f"{data['name']} (`{item}`)"),("Quantity",quantity),("Unit price",data["price"]),("Deducted",f"-{cost:,} Catnip"),("Balance before",bal),("Balance after",bal-cost),("Item quantity after",inv[item])]); await ctx.reply(f"🛒 Bought {quantity}× {data['name']} for {cost:,} Catnip. Balance: {bal-cost:,}.",mention_author=False)

@bot.command(name="give",aliases=["pay","transfer"])
@commands.guild_only()
async def prefix_give(ctx,member:discord.Member,amount:int):
    if not 1 <= amount <= 1000000: return await ctx.reply("❌ Amount must be between 1 and 1,000,000.",mention_author=False)
    if member.bot or member.id==ctx.author.id: return await ctx.reply("❌ Choose another human member.",mention_author=False)
    gid=ctx.guild.id; bal=economy_balance(gid,ctx.author.id)
    if bal<amount: return await ctx.reply("❌ You don't have enough Catnip.",mention_author=False)
    recipient_before=economy_balance(gid,member.id); economy_balances[(gid,ctx.author.id)]=bal-amount; economy_balances[(gid,member.id)]=recipient_before+amount; await bd_save_data(); await economy_log(gid,title="💸 Catnip transfer",fields=[("From",f"{ctx.author} ({ctx.author.id})"),("To",f"{member} ({member.id})"),("Amount",f"{amount:,} Catnip"),("Sender before",bal),("Sender after",bal-amount),("Recipient before",recipient_before),("Recipient after",recipient_before+amount)]); await ctx.reply(f"💸 Sent {amount:,} Catnip to {member.mention}.",mention_author=False)

@bot.command(name="econlb",aliases=["economylb"])
@commands.guild_only()
async def prefix_econlb(ctx):
    rows=sorted(((uid,b) for (gid,uid),b in economy_balances.items() if gid==ctx.guild.id),key=lambda x:x[1],reverse=True)[:10]; lines=[f"**{i}.** {ctx.guild.get_member(uid) or f'User {uid}'} — {bal:,} Catnip" for i,(uid,bal) in enumerate(rows,1)]; await ctx.reply("\n".join(lines) if lines else "No economy balances yet.",mention_author=False)

@bot.command(name="rank")
@commands.guild_only()
async def prefix_rank(ctx,member:discord.Member=None):
    m=member or ctx.author; xp=int(xp_data.get((ctx.guild.id,m.id),0)); level=max(0,int(math.sqrt(max(0,xp)//100))); await ctx.reply(f"🏅 **{m.display_name}** — Level **{level}**, **{xp:,} XP**",mention_author=False)

@bot.command(name="leaderboard",aliases=["lb"])
@commands.guild_only()
async def prefix_leaderboard(ctx):
    rows=sorted(((uid,xp) for (gid,uid),xp in xp_data.items() if gid==ctx.guild.id),key=lambda x:x[1],reverse=True)[:10]; lines=[f"**{i}.** {ctx.guild.get_member(uid) or f'User {uid}'} — {xp:,} XP" for i,(uid,xp) in enumerate(rows,1)]; await ctx.reply("\n".join(lines) if lines else "No XP data yet.",mention_author=False)

@bot.command(name="botstatus",aliases=["status"])
async def prefix_botstatus(ctx): await ctx.reply(f"🐾 Cinnamon is online. Latency: {round(bot.latency*1000)} ms.",mention_author=False)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    # Dispatch ? commands before the regular AI/XP chat pipeline.
    ctx = await bot.get_context(message)
    if ctx.valid:
        await bot.invoke(ctx)
        return

    if message.guild:
        # --- AFK: clear the sender's own status, and flag anyone AFK they pinged ---
        afk_key = (message.guild.id, message.author.id)
        if afk_key in afk_users:
            old_reason = afk_users.pop(afk_key)
            await send_log(message.guild.id, title="💤 AFK status cleared", category="general",
                           fields=[("User", f"{message.author} ({message.author.id})"), ("Previous reason", str(old_reason)[:300])])
            try:
                await message.channel.send(
                    f"🐾 Welcome back, {message.author.mention}! I've cleared your AFK status.",
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            except discord.HTTPException:
                pass
        afk_notes = [
            f"🐾 **{u.display_name}** is AFK: {afk_users[(message.guild.id, u.id)]}"
            for u in message.mentions if (message.guild.id, u.id) in afk_users
        ]
        if afk_notes:
            try:
                await message.channel.send("\n".join(afk_notes), allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

        # --- Auto-moderation: acts first; a removed message skips everything else below ---
        if await run_automod(message):
            return

    speaker = message.author.display_name
    content = message.content.strip()

    # Strip the bot's own mention text out of the message before we store/send it.
    clean_content = content
    if bot.user:
        clean_content = clean_content.replace(f"<@{bot.user.id}>", "").strip()
        clean_content = clean_content.replace(f"<@!{bot.user.id}>", "").strip()

    # --- XP: award for genuine chat messages, at most once per user per 60s ---
    if message.guild and clean_content:
        await award_xp(message)

    if clean_content:
        channel_memories[message.channel.id].append((speaker, clean_content))

    guild_id = message.guild.id if message.guild else None
    channel_id = message.channel.id

    # A disabled channel overrides everything else — Cinnamon stays silent here.
    if guild_id is not None and channel_id in disabled_channels[guild_id]:
        return

    was_mentioned = bot.user is not None and bot.user in message.mentions and not message.mention_everyone

    # Check if this message is a reply to one of Cinnamon's own messages.
    was_reply_to_bot = False
    if message.reference and bot.user:
        ref = message.reference.resolved
        if ref is None:
            try:
                ref = await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.HTTPException):
                ref = None
        if isinstance(ref, discord.Message) and ref.author.id == bot.user.id:
            was_reply_to_bot = True

    is_ai_channel = guild_id is not None and ai_channels.get(guild_id) == channel_id

    if clean_content and (was_mentioned or was_reply_to_bot or is_ai_channel):
        # Keep an always-on AI channel from turning chat bursts into Gemini bursts.
        now = time.monotonic()
        if is_ai_channel and not (was_mentioned or was_reply_to_bot):
            last_ai = ai_cooldowns.get(channel_id, 0.0)
            if now - last_ai < AI_CHANNEL_COOLDOWN_SECONDS:
                return
            ai_cooldowns[channel_id] = now

        if is_owner_question(clean_content):
            # Hard-coded so this is always correct, instead of hoping the model remembers.
            reply = (
                f"*puffs up proudly* {OWNER_NAME} is my human and my favorite person "
                f"in the whole wide world! {owner_mention(message.guild)}"
            )
            reaction = "❤️"
        else:
            async with message.channel.typing():
                try:
                    result = await asyncio.to_thread(
                        ask_gemini, message.channel.id, speaker, clean_content, message.guild
                    )
                except Exception as e:
                    log.error(f"Gemini call failed: {e}")
                    result = {
                        "reply": "*paws at the screen, confused* ...something smells like tuna gone wrong. Try again in a moment?",
                        "reaction": "",
                    }
            reply = result["reply"]
            reaction = result["reaction"]

        channel_memories[message.channel.id].append(("Cinnamon", reply))

        # In the dedicated AI channel, chat naturally instead of quote-replying
        # to every single message — but still use a reply if directly pinged.
        if is_ai_channel and not (was_mentioned or was_reply_to_bot):
            await message.channel.send(reply)
        else:
            await message.reply(
                reply, mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        await add_reaction_safely(message, reaction)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

