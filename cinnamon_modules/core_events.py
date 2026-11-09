"""Cinnamon feature module.

Loaded by main.py into Cinnamon's shared runtime namespace. This is still
one Discord bot and one process; this file is not a separate bot.
Do not run this file directly.
"""

async def _send_admin_error_dm(user, *, command_name: str, error: BaseException, context: str = ""):
    """Privately send useful diagnostics to a server Administrator after a command fails.

    Never includes tokens, secrets, authorization codes, or full tracebacks. The normal
    public error remains unchanged; this DM is only an administrator diagnostic.
    """
    try:
        guild_perms = getattr(user, "guild_permissions", None)
        if not guild_perms or not guild_perms.administrator:
            return

        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
        detail = str(original).strip() or repr(original)
        # Avoid accidentally exposing credentials/codes that might appear in an exception.
        sensitive_words = ("token", "client_secret", "authorization", "access_token", "refresh_token")
        if any(word in detail.lower() for word in sensitive_words):
            detail = f"{type(original).__name__} (sensitive error details hidden)"
        detail = detail[:1200]
        context = (context or "").replace("@", "@\u200b")[:700]

        message = (
            "🔧 **Cinnamon command diagnostic**\n"
            f"**Command:** `{command_name}`\n"
            f"**Error type:** `{type(original).__name__}`\n"
            f"**Reason:** `{detail}`"
        )
        if context:
            message += f"\n**Context:** {context}"
        message += "\n\nOnly you received this diagnostic because you have **Administrator** permission. The public error message was left unchanged."
        await user.send(message)
    except (discord.Forbidden, discord.HTTPException, AttributeError):
        # DMs can be disabled; never turn a failed diagnostic DM into another command error.
        pass


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
        if any(x in lowered for x in ("dashboard", "message studio", "web dashboard", "slash help opened")):
            category = "dashboard"
        elif any(x in lowered for x in ("economy", "catnip", "shop item", "income role", "cinnamon fed", "tuna")):
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
    if root in {"rank", "leaderboard", "levelrole", "level-rewards", "level-settings"}:
        return "levels"
    if root in {"achievement", "achievements"} or "achievement" in name:
        return "achievements"
    if root in {"quest", "quests", "questshop"} or "quest" in name:
        return "quests"
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
    await _send_admin_error_dm(
        ctx.author,
        command_name="?" + (ctx.command.qualified_name if ctx.command else "unknown"),
        error=error,
        context=f"Server: {ctx.guild.name if ctx.guild else 'DM'} | Channel: {getattr(ctx.channel, 'name', 'unknown')}",
    )


_slash_commands_synced = False


@bot.event
async def on_ready():
    global _slash_commands_synced
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
        # Keep the daily/weekly quest rotation clock-driven rather than waiting
        # for a member to invoke /quest.
        if not quest_reset_loop.is_running():
            quest_reset_loop.start()

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

    # Global slash commands are the source of truth. Avoid per-guild clear/sync
    # REST calls on every startup; they add API traffic and can trigger 429s.
    # Mark synced only after the global request succeeds so a later reconnect
    # can retry if Discord temporarily rejects command synchronization.
    if not _slash_commands_synced:
        try:
            synced = await bot.tree.sync()
            log.info("Globally synced %d Cinnamon slash commands", len(synced))
            _slash_commands_synced = True
        except Exception:
            log.exception("Global slash-command sync failed; will retry on next reconnect")

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



# Main prefix commands. Hangry Games and the real quest/achievement systems stay slash-only.
@bot.command(name="help", aliases=["commands"])
async def prefix_help(ctx):
    """Live prefix command directory, including nested commands and aliases."""
    entries = _help_prefix_entries(bot.walk_commands())
    pages = _help_command_pages(entries, max_chars=940)
    total = len(pages)
    embeds = []
    for index, body in enumerate(pages, start=1):
        embed = cinnamon_embed(
            "🐾 Cinnamon · Prefix commands",
            "These commands are registered right now. Use `!command`, "
            "or `/help` for slash commands and more details.",
            color=CINNAMON_ORANGE, user=ctx.author,
            footer=cinnamon_page_footer("Prefix Help", index, total, 
                                         f"{len(entries)} commands"),
        )
        embed.add_field(name="Available commands", value=body, inline=False)
        embeds.append(embed)
    await ctx.reply(
        embed=embeds[0],
        view=HelpPagesView(ctx.author.id, embeds),
        mention_author=False, allowed_mentions=discord.AllowedMentions.none(),
    )
    if ctx.guild:
        try:
            await send_log(
                ctx.guild.id, title="📖 Prefix help opened",
                description=f"{ctx.author} ({ctx.author.id}) opened the live prefix guide.",
                category="dashboard",
            )
        except Exception:
            log.exception("Failed to log prefix help view")

@bot.command(name="ping")
async def prefix_ping(ctx): await ctx.reply(f"🐾 Pong! {round(bot.latency*1000)} ms",mention_author=False)

@bot.command(name="ask",aliases=["ai","chat"])
@commands.guild_only()
async def prefix_ask(ctx,*,prompt:str):
    if ctx.channel.id in disabled_channels[ctx.guild.id]: return
    if await _cinnamon_try_assistance(ctx.message, prompt):
        return
    ai_success=False
    async with ctx.typing():
        try:
            result=await asyncio.to_thread(ask_gemini,ctx.channel.id,ctx.author.display_name,prompt,ctx.guild,ctx.author.id)
            reply=result.get("reply") or "*paws at the screen* Try again?"
            ai_success=bool(result.get("reply"))
        except Exception:
            log.exception("Prefix AI failed"); reply="*paws at the screen, confused* I couldn't answer just now. Try again soon?"
    channel_memories[ctx.channel.id].append((ctx.author.display_name,prompt[:2000])); channel_memories[ctx.channel.id].append(("Cinnamon",reply[:2000]))
    if ai_success:
        await achievement_record(ctx.guild.id,ctx.author.id,"ai_reply",1)
    await ctx.reply(reply[:1900],mention_author=False,allowed_mentions=discord.AllowedMentions.none())


async def _ch_maybe_handle(message, clean_content):
    """Explain real registered commands without executing them or calling Gemini."""
    offset = CINNAMON_TIMEZONE_OFFSET_MINUTES
    sign = "+" if offset >= 0 else "-"
    hours, minutes = divmod(abs(offset), 60)
    answer = answer_help(
        clean_content, build_command_catalog(_all_leaf_commands()),
        timezone_label=f"UTC{sign}{hours:02d}:{minutes:02d}",
    )
    if answer is None:
        return False
    await message.reply(answer[:1900], mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none())
    return True



async def _ch_private_data_redirect(message, clean_content):
    """Keep a member's private account questions out of public chat and AI history."""
    classifier = globals().get("_me_classify_private_question")
    snapshot_builder = globals().get("_me_private_snapshot")
    answer_builder = globals().get("_me_generate_private_answer")
    if not message.guild or not callable(classifier) or not callable(snapshot_builder) or not callable(answer_builder):
        return False
    scopes = classifier(clean_content)
    if not scopes:
        return False
    snapshot = snapshot_builder(message.guild.id, message.author.id, scopes)
    try:
        answer = await asyncio.to_thread(answer_builder, clean_content, snapshot)
        answer = str(answer or "I couldn't verify those details.")[:1400]
        await message.author.send(answer, allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException):
        # Never put account values in a public fallback.
        try:
            await message.channel.send(
                f"{message.author.mention} I couldn't DM that private answer. "
                "Use /cinnamon-me ask for an ephemeral reply; I won't disclose account values here.",
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException:
            pass
    return True

async def _cinnamon_try_assistance(message, clean_content):
    """Trusted, acknowledged personal requests and help precede Gemini."""
    reminder_handler = globals().get("_cr_maybe_handle")
    memory_handler = globals().get("_cmem_maybe_handle")
    if message.guild and callable(reminder_handler) and await reminder_handler(message, clean_content):
        return True
    if message.guild and callable(memory_handler) and await memory_handler(message, clean_content):
        return True
    if message.guild and await _ch_private_data_redirect(message, clean_content):
        return True
    if await _ch_maybe_handle(message, clean_content):
        return True
    if message.guild and await _ca_maybe_handle(message, clean_content):
        return True
    return False

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
@commands.has_guild_permissions(administrator=True)
async def prefix_warn(ctx,member:discord.Member,*,reason:str):
    count=add_warning(ctx.guild.id,member.id,reason[:300],ctx.author); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"⚠️ {member.mention} warned — {count} warning(s). Case #{case}.",mention_author=False,allowed_mentions=discord.AllowedMentions(users=True)); await send_log(ctx.guild.id,title="⚠️ Member warned",color=discord.Color.orange(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})"),("Reason",reason[:300]),("Total warnings",str(count))])

@bot.command(name="warnings",aliases=["warns"])
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_warnings(ctx,member:discord.Member):
    ws=warnings_data.get((ctx.guild.id,member.id),[])
    if not ws: return await ctx.reply(f"{member.display_name} has no warnings.",mention_author=False)
    e=discord.Embed(title=f"⚠️ Warnings for {member.display_name}",color=discord.Color.orange())
    for i,w in enumerate(ws[-10:],1): e.add_field(name=f"Warning #{i}",value=f"{w.get('reason','No reason')} — {w.get('ts','')[:10]}",inline=False)
    await ctx.reply(embed=e,mention_author=False)

@bot.command(name="clearwarnings",aliases=["clearwarns"])
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_clearwarnings(ctx,member:discord.Member):
    removed=len(warnings_data.pop((ctx.guild.id,member.id),[])); await bd_save_data(); await ctx.reply(f"🧹 Cleared {removed} warning(s) for {member.mention}.",mention_author=False); await send_log(ctx.guild.id,title="🧹 Warnings cleared",fields=[("Member",f"{member} ({member.id})"),("Cleared",str(removed))])

@bot.command(name="kick")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(kick_members=True)
async def prefix_kick(ctx,member:discord.Member,*,reason="No reason given"):
    if member==ctx.author or member==ctx.guild.owner or (member.top_role>=ctx.author.top_role and ctx.author.id!=ctx.guild.owner_id) or member.top_role>=ctx.guild.me.top_role: return await ctx.reply("❌ Role hierarchy prevents this action.",mention_author=False)
    await member.kick(reason=reason[:300]); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"👢 Kicked {member}. Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="👢 Member kicked",color=discord.Color.orange(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})"),("Reason",reason[:300])])

@bot.command(name="ban")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(ban_members=True)
async def prefix_ban(ctx,member:discord.Member,*,reason="No reason given"):
    if member==ctx.author or member==ctx.guild.owner or (member.top_role>=ctx.author.top_role and ctx.author.id!=ctx.guild.owner_id) or member.top_role>=ctx.guild.me.top_role: return await ctx.reply("❌ Role hierarchy prevents this action.",mention_author=False)
    await member.ban(reason=reason[:300],delete_message_seconds=0); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"🔨 Banned {member}. Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="🔨 Member banned",color=discord.Color.red(),fields=[("Case",f"#{case}"),("Member",f"{member} ({member.id})"),("Reason",reason[:300])])

@bot.command(name="unban")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(ban_members=True)
async def prefix_unban(ctx,user_id:int):
    await ctx.guild.unban(discord.Object(id=user_id)); temp_bans.pop((ctx.guild.id,user_id),None); case=next_case(ctx.guild.id); await bd_save_data(); await ctx.reply(f"🔓 Unbanned user `{user_id}`. Case #{case}.",mention_author=False); await send_log(ctx.guild.id,title="🔓 Member unbanned",color=discord.Color.green(),fields=[("Case",f"#{case}"),("User ID",str(user_id)),("Moderator",f"{ctx.author} ({ctx.author.id})")])

@bot.command(name="purge",aliases=["clear"])
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(manage_messages=True)
async def prefix_purge(ctx,amount:int):
    if not 1 <= amount <= 100: return await ctx.reply("❌ Amount must be between 1 and 100.",mention_author=False)
    deleted=await ctx.channel.purge(limit=amount+1); removed=max(0,len(deleted)-1); await ctx.send(f"🧹 Removed {removed} messages.",delete_after=4); await send_log(ctx.guild.id,title="🧹 Messages purged",color=discord.Color.light_grey(),fields=[("Moderator",f"{ctx.author} ({ctx.author.id})"),("Channel",ctx.channel.mention),("Deleted",str(removed))])

@bot.command(name="slowmode")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(manage_channels=True)
async def prefix_slowmode(ctx,seconds:int):
    if not 0 <= seconds <= 21600: return await ctx.reply("❌ Seconds must be between 0 and 21,600.",mention_author=False)
    await ctx.channel.edit(slowmode_delay=seconds); await ctx.reply(f"🐌 Slowmode set to {seconds} second(s).",mention_author=False); await send_log(ctx.guild.id,title="🐌 Slowmode changed",fields=[("Moderator",f"{ctx.author} ({ctx.author.id})"),("Channel",ctx.channel.mention),("Seconds",str(seconds))])

@bot.command(name="balance",aliases=["bal","wallet"])
@commands.guild_only()
async def prefix_balance(ctx,member:discord.Member=None):
    m=member or ctx.author; gid=ctx.guild.id; bal=economy_balance(gid,m.id); inv=economy_inventory_for(gid,m.id); total_items=sum(int(v) for v in inv.values())
    embed=cinnamon_embed("🌿 Catnip Wallet",f"**{m.mention}**\n\nHere is your current Cinnamon economy status.",color=CINNAMON_GOLD,user=m,footer="Cinnamon Economy • Wallet")
    cinnamon_field(embed,"🌿 Catnip",f"**{bal:,}**",True); cinnamon_field(embed,"🎒 Items",f"**{total_items:,}**",True); cinnamon_field(embed,"\u200b","\u200b",True)
    await ctx.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none()); await economy_log(gid,title="👛 Economy balance viewed",fields=[("Viewer",f"{ctx.author} ({ctx.author.id})"),("Member",f"{m} ({m.id})"),("Balance",f"{bal:,} Catnip"),("Total items",total_items)]); await bd_save_data()

@bot.command(name="inventory",aliases=["inv","bag"])
@commands.guild_only()
async def prefix_inventory(ctx,member:discord.Member=None):
    m=member or ctx.author; gid=ctx.guild.id; inv=economy_inventory_for(gid,m.id); lines=[f"{ECONOMY_ITEMS[k]['emoji']} **{ECONOMY_ITEMS[k]['name']}** × **{v}**" for k,v in inv.items() if k in ECONOMY_ITEMS and int(v)>0]; summary="\n".join(f"{ECONOMY_ITEMS[k]['name']}: {int(v)}" for k,v in inv.items() if k in ECONOMY_ITEMS and int(v)>0) or "Empty"
    embed=cinnamon_embed("🎒 Inventory",f"**{m.mention}**\n\n"+("\n".join(lines) if lines else "Your inventory is empty. Use `?shop` to start collecting."),color=CINNAMON_BLUE,user=m,footer="Cinnamon Economy • Inventory")
    cinnamon_field(embed,"🌿 Catnip",f"**{economy_balance(gid,m.id):,}**",True); cinnamon_field(embed,"📦 Total items",f"**{sum(int(v) for v in inv.values()):,}**",True)
    await ctx.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none()); await economy_log(gid,title="🎒 Economy inventory viewed",fields=[("Viewer",f"{ctx.author} ({ctx.author.id})"),("Member",f"{m} ({m.id})"),("Inventory",summary[:1000]),("Total items",sum(int(v) for v in inv.values())),("Catnip balance",economy_balance(gid,m.id))])

@bot.command(name="shop")
@commands.guild_only()
async def prefix_shop(ctx):
    # Keep ?shop identical to /economy shop. The old embed-only shop was
    # accidentally left behind, so prefix users were still seeing the legacy UI.
    view = CinnamonShopView(ctx.guild.id, ctx.author.id, 0)
    await ctx.reply(view=view, mention_author=False, allowed_mentions=discord.AllowedMentions.none())
    await economy_log(
        ctx.guild.id,
        title="🛒 Economy shop viewed",
        fields=[
            ("Viewer", f"{ctx.author} ({ctx.author.id})"),
            ("Items shown", str(len(ECONOMY_ITEMS))),
            ("Entry", "?shop"),
        ],
    )

@bot.command(name="daily")
@commands.guild_only()
async def prefix_daily(ctx):
    gid,uid=ctx.guild.id,ctx.author.id; rem=economy_cooldown_remaining(gid,uid,"daily")
    if rem:
        embed=cinnamon_embed("⏳ Daily Catnip Cooldown",f"Cinnamon has already given you today's reward.\n\nCome back in **{rem//3600}h {(rem%3600)//60}m**.",color=CINNAMON_MUTED,user=ctx.author,footer="Cinnamon Economy • Daily")
        return await ctx.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none())
    economy_cooldowns[(gid,uid,"daily")]=time.time()+86400; economy_balances[(gid,uid)]=economy_balance(gid,uid)+ECONOMY_DAILY_REWARD; await achievement_record(gid,uid,"catnip_earned",ECONOMY_DAILY_REWARD); await achievement_record(gid,uid,"balance"); await quest_event(gid,uid,"balance",economy_balance(gid,uid)); box_awarded = await advanced_maybe_award_box(gid,ctx.author,"daily",chance=0.12) if "advanced_maybe_award_box" in globals() else False; await bd_save_data(); await economy_log(gid,title="🌿 Daily Catnip",fields=[("User",str(ctx.author)),("Amount",f"+{ECONOMY_DAILY_REWARD}"),("Mystery Box","Yes" if box_awarded else "No")]); embed=cinnamon_embed("🌿 Daily Catnip Claimed","Cinnamon has approved your daily snack budget.\n\n**Come back tomorrow for another reward!**",color=CINNAMON_GREEN,user=ctx.author,footer="Cinnamon Economy • Daily Reward")
    cinnamon_field(embed,"Reward",f"**+{ECONOMY_DAILY_REWARD:,} Catnip**",True); cinnamon_field(embed,"New balance",f"**{economy_balance(gid,uid):,} Catnip**",True);
    if box_awarded: cinnamon_field(embed,"🎁 Bonus", "**1 Mystery Box**", True)
    await ctx.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none())

@bot.command(name="work")
@commands.guild_only()
async def prefix_work(ctx):
    ok,amount,msg=await economy_do_work(ctx.guild.id,ctx.author)
    if not ok:
        embed=cinnamon_embed("⏳ Work Cooldown",msg,color=CINNAMON_MUTED,user=ctx.author,footer="Cinnamon Economy • Work")
        return await ctx.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none())
    balance=economy_balance(ctx.guild.id,ctx.author.id); job=msg.replace("💼 You **","").split("** and earned",1)[0] if "** and earned" in msg else "worked for Cinnamon"
    embed=cinnamon_embed("💼 Shift Complete","Cinnamon inspected your work and approved the payment. 🐾",color=CINNAMON_GREEN,user=ctx.author,footer="Cinnamon Economy • Work • 10 minute cooldown")
    cinnamon_field(embed,"💼 Job",job); cinnamon_field(embed,"🌿 Earned",f"**+{amount:,} Catnip**",True); cinnamon_field(embed,"💰 New balance",f"**{balance:,} Catnip**",True)
    await ctx.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none())

@bot.command(name="buy")
@commands.guild_only()
async def prefix_buy(ctx,item:str,quantity:int=1):
    if not 1 <= quantity <= 99: return await ctx.reply("❌ Quantity must be between 1 and 99.",mention_author=False)
    gid,uid=ctx.guild.id,ctx.author.id; item=item.lower().strip(); item=next((k for k,v in ECONOMY_ITEMS.items() if k==item or v["name"].lower()==item),item); data=ECONOMY_ITEMS.get(item)
    if not data: return await ctx.reply("❌ Item not found. Use `?shop`.",mention_author=False)
    bal=economy_balance(gid,uid); unit_price=_cm_price(gid,uid,item,data["price"]); cost=unit_price*quantity
    if bal<cost: return await ctx.reply(f"❌ Need {cost:,} Catnip; you have {bal:,}.",mention_author=False)
    inv=economy_inventory_for(gid,uid); inv[item]=int(inv.get(item,0))+quantity; economy_balances[(gid,uid)]=bal-cost; await achievement_record(gid,uid,"purchase",quantity,spent=cost); await achievement_record(gid,uid,"inventory"); await quest_event(gid,uid,"items_owned",sum(max(0,int(v)) for v in inv.values())); await quest_event(gid,uid,"purchase",quantity,spent=cost); await quest_event(gid,uid,"spent",cost,spent=cost); await achievement_record(gid,uid,"balance"); await quest_event(gid,uid,"balance",bal-cost); await bd_save_data(); await economy_log(gid,title="🛒 Economy purchase",fields=[("User",f"{ctx.author} ({uid})"),("Item",f"{data['name']} (`{item}`)"),("Quantity",quantity),("Unit price",unit_price),("Deducted",f"-{cost:,} Catnip"),("Balance before",bal),("Balance after",bal-cost),("Item quantity after",inv[item])]); await ctx.reply(f"🛒 Bought {quantity}× {data['name']} for {cost:,} Catnip. Balance: {bal-cost:,}.",mention_author=False); await _cp_react(ctx.guild,ctx.author,ctx.channel,"big_purchase",value=cost)

@bot.command(name="give",aliases=["pay","transfer"])
@commands.guild_only()
async def prefix_give(ctx,member:discord.Member,amount:int):
    if not 1 <= amount <= 1000000: return await ctx.reply("❌ Amount must be between 1 and 1,000,000.",mention_author=False)
    if member.bot or member.id==ctx.author.id: return await ctx.reply("❌ Choose another human member.",mention_author=False)
    gid=ctx.guild.id
    pair_remaining=economy_cooldown_remaining(gid,ctx.author.id,f"give:{member.id}")
    if pair_remaining: return await ctx.reply(f"🐾 You recently sent Catnip to that member. Try again in **{pair_remaining // 60}m**.",mention_author=False)
    bal=economy_balance(gid,ctx.author.id)
    if bal<amount: return await ctx.reply("❌ You don't have enough Catnip.",mention_author=False)
    recipient_before=economy_balance(gid,member.id); economy_balances[(gid,ctx.author.id)]=bal-amount; economy_balances[(gid,member.id)]=recipient_before+amount; economy_cooldowns[(gid,ctx.author.id,f"give:{member.id}")]=time.time()+3600; await achievement_record(gid,ctx.author.id,"give",amount); await achievement_record(gid,ctx.author.id,"balance"); await quest_event(gid,ctx.author.id,"balance",bal-amount); await quest_event(gid,ctx.author.id,"give",amount); await quest_event(gid,ctx.author.id,"give_count",1); await bd_save_data(); await economy_log(gid,title="💸 Catnip transfer",fields=[("From",f"{ctx.author} ({ctx.author.id})"),("To",f"{member} ({member.id})"),("Amount",f"{amount:,} Catnip"),("Sender before",bal),("Sender after",bal-amount),("Recipient before",recipient_before),("Recipient after",recipient_before+amount)]); await ctx.reply(f"💸 Sent {amount:,} Catnip to {member.mention}.",mention_author=False)

@bot.command(name="econlb",aliases=["economylb"])
@commands.guild_only()
async def prefix_econlb(ctx):
    rows=sorted(((uid,b) for (gid,uid),b in economy_balances.items() if gid==ctx.guild.id),key=lambda x:x[1],reverse=True)[:10]; lines=[f"**{i}.** {ctx.guild.get_member(uid) or f'User {uid}'} — 🌿 **{bal:,}**" for i,(uid,bal) in enumerate(rows,1)]
    embed=cinnamon_embed("🏆 Catnip Leaderboard","The richest humans in this server, according to Cinnamon. 🐱\n",color=CINNAMON_GOLD,user=ctx.author,footer="Cinnamon Economy • Top 10")
    embed.description += "\n".join(lines) if lines else "No economy balances yet. Start with `?daily` or `?work`."
    await ctx.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none())

@bot.command(name="rank")
@commands.guild_only()
async def prefix_rank(ctx,member:discord.Member=None):
    m=member or ctx.author; xp=int(xp_data.get((ctx.guild.id,m.id),0)); level=level_from_xp(xp); embed=cinnamon_embed("🏅 Rank & XP",f"**{m.mention}**\n\nYour current level progress is below.",color=CINNAMON_ORANGE,user=m,footer="Cinnamon Levels • Use /rank for your level card")
    cinnamon_field(embed,"🏅 Level",f"**{level}**",True); cinnamon_field(embed,"✨ Total XP",f"**{xp:,} XP**",True)
    await ctx.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none())

@bot.command(name="leaderboard",aliases=["lb"])
@commands.guild_only()
async def prefix_leaderboard(ctx):
    rows=sorted(((uid,xp) for (gid,uid),xp in xp_data.items() if gid==ctx.guild.id),key=lambda x:x[1],reverse=True)[:10]; lines=[f"**{i}.** {ctx.guild.get_member(uid) or f'User {uid}'} — **Level {level_from_xp(xp)}** · {xp:,} XP" for i,(uid,xp) in enumerate(rows,1)]
    embed=cinnamon_embed("🏆 XP Leaderboard","Top members by XP and level.\n",color=CINNAMON_ORANGE,user=ctx.author,footer="Cinnamon Levels • Top 10")
    embed.description += "\n".join(lines) if lines else "No XP data yet. Start chatting to earn XP."
    await ctx.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none())

@bot.command(name="botstatus",aliases=["status"])
async def prefix_botstatus(ctx):
    storage = await storage_status()
    ready = storage["transactions_ready"]
    embed = cinnamon_embed(
        "🐾 Cinnamon Status",
        "My Discord connection is working, but that doesn't mean every "
        "database feature is healthy.",
        color=CINNAMON_GREEN if ready else CINNAMON_MUTED,
        user=ctx.author, footer="Cinnamon • Live System Status",
    )
    cinnamon_field(embed,"📡 Discord latency",f"**{round(bot.latency*1000)} ms**",True)
    cinnamon_field(embed,"💾 Storage backend",storage["backend"],True)
    cinnamon_field(embed,"🗃️ Snapshot","Loaded" if storage["snapshot_ready"] else "Unavailable",True)
    cinnamon_field(embed,"🌿 Confirmed Catnip actions",
                   "Ready" if ready else "Blocked for data safety",True)
    if not ready:
        cinnamon_field(embed,"🛡️ Admin diagnosis",
                       "Run `/datastatus check` for the reason.",False)
    await ctx.reply(embed=embed,mention_author=False,allowed_mentions=discord.AllowedMentions.none())

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    # Prefix commands are intentionally !-only. The former ? prefix is retired.
    if message.content.startswith("?") and len(message.content) > 1:
        candidate = message.content[1:].lstrip().split(maxsplit=1)[0].lower()
        if candidate and candidate.replace("-", "").isalnum():
            try:
                await message.reply(
                    "🐾 Cinnamon's prefix is now **!**. Try `!" + candidate + "`.",
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass
            return
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

    guild_id = message.guild.id if message.guild else None
    channel_id = message.channel.id

    # A disabled channel overrides everything else — Cinnamon stays silent here.
    if guild_id is not None and channel_id in disabled_channels[guild_id]:
        return

    if clean_content:
        channel_memories[message.channel.id].append((speaker, clean_content[:2000]))

    # Cinnamon Brain sees only chat that survived moderation and disabled-
    # channel checks. Store aggregate activity timestamps, never message text.
    if (guild_id is not None and len(clean_content) >= 3
            and not clean_content.startswith(("?", "/"))
            and channel_id not in set(category_log_channels.get(guild_id, {}).values())):
        _cb_observe(guild_id, message.author.id)
        # Store only a short-lived boolean quiet signal for serious topics.
        context_observer = globals().get("_cx_observe")
        if callable(context_observer):
            context_observer(guild_id, clean_content)

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

    # The AI channel is a place to FIND Cinnamon, not an invitation to
    # interrupt everyone. Respond only to explicit ping, reply, or direct name.
    is_ai_channel = guild_id is not None and ai_channels.get(guild_id) == channel_id
    called_by_name = _cp_direct_name(clean_content)
    invited = bool(was_mentioned or was_reply_to_bot or called_by_name)
    if not invited:
        if message.guild:
            try:
                await _cp_maybe_cameo(message)  # One-line aside, not a conversation.
            except Exception:
                log.exception("Cinnamon's voluntary aside was suppressed")
        return

    if (clean_content or was_mentioned or was_reply_to_bot) and invited:
        # Keep an always-on AI channel from turning chat bursts into Gemini bursts.
        now = time.monotonic()
        if called_by_name and not (was_mentioned or was_reply_to_bot):
            last_ai = ai_cooldowns.get(channel_id, 0.0)
            if now - last_ai < AI_CHANNEL_COOLDOWN_SECONDS:
                return
            ai_cooldowns[channel_id] = now

        if await _cinnamon_try_assistance(message, clean_content):
            return
        if guild_id is not None:
            if await _ca_maybe_prank(message):
                return
        late_note = await _cp_answer(message) if guild_id is not None and clean_content else ""
        ai_reply_success = False
        if is_owner_question(clean_content):
            # Hard-coded so this is always correct, instead of hoping the model remembers.
            reply = (
                f"*puffs up proudly* {OWNER_NAME} is my human and my favorite person "
                f"in the whole wide world! {owner_mention(message.guild)}"
            )
            reaction = "❤️"
        else:
            mood_reply = await _cm_ping(message) if was_mentioned else None
            if mood_reply:
                reply, reaction = mood_reply, "😾"
            else:
                async with message.channel.typing():
                    try:
                        result = await asyncio.to_thread(
                            ask_gemini, message.channel.id, speaker, clean_content, message.guild, message.author.id
                        )
                        ai_reply_success = bool(result.get("reply"))
                    except Exception as e:
                        log.error(f"Gemini call failed: {e}")
                        result = {
                            "reply": "*paws at the screen, confused* ...something smells like tuna gone wrong. Try again in a moment?",
                            "reaction": "",
                        }
                reply = result["reply"]
                reaction = result["reaction"]

        if late_note:
            reply = late_note + reply
        channel_memories[message.channel.id].append(("Cinnamon", reply[:2000]))

        # In the dedicated AI channel, chat naturally instead of quote-replying
        # to every single message — but still use a reply if directly pinged.
        # Even in the AI channel, reply only when invited. Never ping the author.
        await message.reply(
            reply, mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        if guild_id is not None and ai_reply_success:
            await achievement_record(guild_id, message.author.id, "ai_reply", 1)
        await add_reaction_safely(message, reaction)
        if guild_id is not None and invited:
            try:
                await _cp_maybe_question(message)
            except Exception:
                log.exception("Cinnamon could not ask her optional question")


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Expanded prefix commands
# These mirror the important slash commands requested for prefix use.
# Admin/configuration commands are intentionally kept separate from normal
# ---------------------------------------------------------------------------

# ---- Economy admin: Catnip -------------------------------------------------
@bot.command(name="addcatnip", aliases=["add-catnip"])
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_addcatnip(ctx, member: discord.Member, amount: int):
    await _change_catnip_prefix(ctx, member, amount, True)


@bot.command(name="removecatnip", aliases=["remove-catnip"])
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_removecatnip(ctx, member: discord.Member, amount: int):
    await _change_catnip_prefix(ctx, member, amount, False)


async def _change_catnip_prefix(ctx, member, amount, add):
    """Keep legacy admin commands on the same durable currency boundary."""
    try:
        actor = await ctx.guild.fetch_member(ctx.author.id)
    except discord.HTTPException:
        return await ctx.reply("I couldn't verify your current permissions. Try again shortly.",
                               mention_author=False, allowed_mentions=discord.AllowedMentions.none())
    if actor.id != ctx.guild.owner_id and not actor.guild_permissions.administrator:
        return await ctx.reply("⛔ This needs the server owner or an Administrator.",
                               mention_author=False, allowed_mentions=discord.AllowedMentions.none())
    result = await _ca_adjust_catnip(ctx.guild.id, actor.id, member.id, amount, add,
                                    f"prefix:{ctx.message.id}")
    if result["status"] != "committed":
        return await ctx.reply("🐾 " + result.get("reason", "I couldn't confirm that adjustment."),
                               mention_author=False, allowed_mentions=discord.AllowedMentions.none())
    verb = "Added" if add else "Removed"
    await economy_log(ctx.guild.id, title=f"🌿 Catnip {verb.lower()}", fields=[
        ("Administrator", f"{actor} ({actor.id})"), ("Member", str(member.id)),
        ("Amount", str(result["actual"])), ("Balance before", str(result["before"])),
        ("Balance after", str(result["after"])), ("Receipt", result["receipt_id"]),
    ])
    await ctx.reply(f"🌿 {verb} **{result['actual']:,} Catnip** "
                    f"{'to' if add else 'from'} {member.mention}. "
                    f"Balance: **{result['after']:,}**.", mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none())


# ---- XP admin ---------------------------------------------------------------
async def _change_xp_prefix(ctx, member: discord.Member, amount: int, add: bool):
    if amount <= 0:
        return await ctx.reply("❌ XP amount must be greater than 0.", mention_author=False)
    key = (ctx.guild.id, member.id)
    before = int(xp_data.get(key, 0))
    after = before + amount if add else max(0, before - amount)
    xp_data[key] = after
    old_level = level_from_xp(before)
    new_level = level_from_xp(after)
    gained_roles = await sync_level_roles(member, new_level)
    await bd_save_data()
    await send_log(ctx.guild.id, title="📈 XP manually changed", category="levels", fields=[
        ("Moderator", f"{ctx.author} ({ctx.author.id})"),
        ("Member", f"{member} ({member.id})"),
        ("Change", f"{'+' if add else '-'}{amount:,} XP"),
        ("XP before", f"{before:,}"),
        ("XP after", f"{after:,}"),
        ("Level", f"{old_level} → {new_level}"),
    ])
    text = f"📈 {'Added' if add else 'Removed'} **{amount:,} XP** {'to' if add else 'from'} {member.mention}.\n"
    text += f"XP: **{after:,}** • Level: **{new_level}**"
    if gained_roles:
        text += f"\n🎖️ New level role{'s' if len(gained_roles) != 1 else ''}: **{', '.join(gained_roles)}**"
    await ctx.reply(text, mention_author=False)


@bot.command(name="addxp", aliases=["add-xp"])
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(manage_roles=True)
async def prefix_addxp(ctx, member: discord.Member, amount: int):
    await _change_xp_prefix(ctx, member, amount, True)


@bot.command(name="removexp", aliases=["remove-xp"])
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(manage_roles=True)
async def prefix_removexp(ctx, member: discord.Member, amount: int):
    await _change_xp_prefix(ctx, member, amount, False)


# Slash equivalents: /add xp and /remove xp.
add_group = app_commands.Group(name="add", description="Add rewards or XP")
remove_group = app_commands.Group(name="remove", description="Remove rewards or XP")


@add_group.command(name="xp", description="Admin: add XP to a member")
@app_commands.describe(member="Member to receive XP", amount="XP to add")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def add_xp_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        return await cinnamon_send(interaction, "❌ XP amount must be greater than 0.", ephemeral=True)
    key = (interaction.guild.id, member.id)
    before = int(xp_data.get(key, 0))
    xp_data[key] = before + amount
    level = level_from_xp(xp_data[key])
    gained = await sync_level_roles(member, level)
    await bd_save_data()
    await send_log(interaction.guild.id, title="📈 XP manually added", category="levels", interaction=interaction,
                   fields=[("Member", f"{member} ({member.id})"), ("Amount", f"+{amount:,} XP"), ("XP after", f"{before + amount:,}"), ("Level", str(level))])
    await cinnamon_send(interaction, f"📈 Added **{amount:,} XP** to {member.mention}. They now have **{before + amount:,} XP** (Level **{level}**)." + (f"\n🎖️ New role: **{', '.join(gained)}**" if gained else ""), allowed_mentions=discord.AllowedMentions.none())


@remove_group.command(name="xp", description="Admin: remove XP from a member")
@app_commands.describe(member="Member to remove XP from", amount="XP to remove")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def remove_xp_cmd(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        return await cinnamon_send(interaction, "❌ XP amount must be greater than 0.", ephemeral=True)
    key = (interaction.guild.id, member.id)
    before = int(xp_data.get(key, 0))
    after = max(0, before - amount)
    xp_data[key] = after
    level = level_from_xp(after)
    await bd_save_data()
    await send_log(interaction.guild.id, title="📉 XP manually removed", category="levels", interaction=interaction,
                   fields=[("Member", f"{member} ({member.id})"), ("Amount", f"-{min(amount, before):,} XP"), ("XP after", f"{after:,}"), ("Level", str(level))])
    await cinnamon_send(interaction, f"📉 Removed **{min(amount, before):,} XP** from {member.mention}. They now have **{after:,} XP** (Level **{level}**).", allowed_mentions=discord.AllowedMentions.none())


try:
    bot.tree.add_command(add_group)
    bot.tree.add_command(remove_group)
except Exception:
    # main.py may register/reload modules in a way that already attached them.
    pass


@bot.command(name="feed")
@commands.guild_only()
async def prefix_feed(ctx, item: str, quantity: int = 1):
    if not 1 <= quantity <= 99:
        return await ctx.reply("❌ Quantity must be between 1 and 99.", mention_author=False)
    gid, uid = ctx.guild.id, ctx.author.id
    item_id = item.lower().strip()
    item_id = next((k for k, v in ECONOMY_ITEMS.items() if k == item_id or v["name"].lower() == item_id), item_id)
    data = ECONOMY_ITEMS.get(item_id)
    if not data:
        return await ctx.reply("❌ That item doesn't exist. Use `?shop` to see the available items.", mention_author=False)
    inv = economy_inventory_for(gid, uid)
    have = max(0, int(inv.get(item_id, 0)))
    if have < quantity:
        return await ctx.reply(f"❌ You only have **{have}× {data['name']}**.", mention_author=False)
    inv[item_id] = have - quantity
    await achievement_record(gid, uid, "feed", quantity, item=item_id)
    await achievement_record(gid, uid, "inventory")
    await quest_event(gid, uid, "items_owned", sum(max(0, int(v)) for v in inv.values()))
    await quest_event(gid, uid, "feed", quantity, item=item_id)
    await bd_save_data()
    await economy_log(gid, title="🐟 Cinnamon fed", fields=[
        ("User", f"{ctx.author} ({uid})"), ("Item", f"{data['name']} (`{item_id}`)"),
        ("Quantity fed", quantity), ("Quantity remaining", inv.get(item_id, 0)),
    ])
    await ctx.reply(f"🐾 Cinnamon happily accepted **{quantity}× {data['name']}**!", mention_author=False)


# ---- Moderation: remaining slash-only commands as prefix -------------------
@bot.command(name="tempban")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(ban_members=True)
async def prefix_tempban(ctx, member: discord.Member, duration_hours: float, *, reason="No reason given"):
    if duration_hours <= 0:
        return await ctx.reply("❌ Duration must be greater than 0 hours.", mention_author=False)
    unban_at = time.time() + duration_hours * 3600
    await member.ban(reason=f"Tempban by {ctx.author}: {reason}")
    temp_bans[(ctx.guild.id, member.id)] = unban_at
    case_id = next_case(ctx.guild.id)
    await bd_save_data()
    await ctx.reply(f"🐾 {member.mention} temp-banned for **{duration_hours:g}h**. Case #{case_id}. Reason: {reason}", mention_author=False)
    await send_log(ctx.guild.id, title="⏳ Member temp-banned", color=discord.Color.red(), fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Duration", f"{duration_hours:g}h"), ("Reason", reason[:300]), ("Moderator", f"{ctx.author} ({ctx.author.id})")])


@bot.command(name="lock")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(manage_channels=True)
async def prefix_lock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    overwrite = channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False
    await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Locked by {ctx.author}")
    await ctx.reply(f"🔒 {channel.mention} locked.", mention_author=False)
    await send_log(ctx.guild.id, title="🔒 Channel locked", color=discord.Color.red(), fields=[("Channel", channel.mention), ("Moderator", f"{ctx.author} ({ctx.author.id})")])


@bot.command(name="unlock")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(manage_channels=True)
async def prefix_unlock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    overwrite = channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = None
    await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Unlocked by {ctx.author}")
    await ctx.reply(f"🔓 {channel.mention} unlocked.", mention_author=False)
    await send_log(ctx.guild.id, title="🔓 Channel unlocked", color=discord.Color.green(), fields=[("Channel", channel.mention), ("Moderator", f"{ctx.author} ({ctx.author.id})")])


@bot.command(name="modinfo")
@commands.guild_only()
@commands.has_guild_permissions(moderate_members=True)
async def prefix_modinfo(ctx, user: discord.User):
    channel = bot.get_channel(log_channels.get(ctx.guild.id, 0))
    if channel is None:
        return await ctx.reply("❌ Set a log channel first with `?logchannel` or `/logchannel`.", mention_author=False)
    entries = []
    try:
        async for message in channel.history(limit=2000):
            for embed in message.embeds:
                if embed.title not in _MODINFO_TITLES:
                    continue
                fields = {f.name: f.value for f in embed.fields}
                m = _ID_IN_PARENS_RE.search(fields.get("Member", ""))
                target = int(m.group(1)) if m else (int(fields["User ID"]) if fields.get("User ID", "").isdigit() else None)
                if target != user.id:
                    continue
                footer_m = re.search(r"Run by (.+?) • #", embed.footer.text or "") if embed.footer else None
                extra = f" ({fields['Duration']})" if "Duration" in fields else ""
                entries.append((embed.timestamp or message.created_at, fields.get("Case", "—"), embed.title, (fields.get("Reason", "") + extra).strip(), footer_m.group(1) if footer_m else "system"))
    except discord.HTTPException as exc:
        return await ctx.reply(f"❌ Couldn't read the log channel: {exc}", mention_author=False)
    stored_warns = len(warnings_data.get((ctx.guild.id, user.id), []))
    lines = [f"**Account created:** {discord.utils.format_dt(user.created_at, 'D')}", f"**In server:** {'Yes' if ctx.guild.get_member(user.id) else 'No'}", f"**Active warnings:** {stored_warns}", f"**Logged actions:** {len(entries)}"]
    for ts, case, title, reason, by in entries[:15]:
        lines.append(f"{case} • **{title}** • {reason or 'No reason'} • by {by}")
    embed = discord.Embed(title=f"🛡️ Moderation history — {user}", description="\n".join(lines)[:4000], color=discord.Color.orange())
    await ctx.reply(embed=embed, mention_author=False)


# ---- Roles ------------------------------------------------------------------
@bot.group(name="role", invoke_without_command=True)
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_role(ctx):
    await ctx.reply("🏷️ Use `?role add @member @role` or `?role add-all @role [true/false]`.", mention_author=False)


@prefix_role.command(name="add")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(manage_roles=True)
async def prefix_role_add(ctx, member: discord.Member, role: discord.Role):
    if role.is_default() or role.managed or role >= ctx.guild.me.top_role:
        return await ctx.reply("❌ I can't assign that role because of role hierarchy or because it is managed.", mention_author=False)
    await member.add_roles(role, reason=f"?role add run by {ctx.author}")
    await ctx.reply(f"🏷️ Added **{role.name}** to {member.mention}.", mention_author=False)
    await send_log(ctx.guild.id, title="🏷️ Role added", color=discord.Color.green(), fields=[("Member", f"{member} ({member.id})"), ("Role", role.name), ("Moderator", f"{ctx.author} ({ctx.author.id})")])


@prefix_role.command(name="add-all")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(manage_roles=True)
async def prefix_role_add_all(ctx, role: discord.Role, include_bots: str = "false"):
    if role.is_default() or role.managed or role >= ctx.guild.me.top_role:
        return await ctx.reply("❌ I can't assign that role because of role hierarchy or because it is managed.", mention_author=False)
    bots = include_bots.lower() in {"true", "yes", "1", "on"}
    targets = [m for m in ctx.guild.members if role not in m.roles and (bots or not m.bot)]
    added = failed = 0
    for member in targets:
        try:
            await member.add_roles(role, reason=f"?role add-all run by {ctx.author}")
            added += 1
        except discord.HTTPException:
            failed += 1
    await ctx.reply(f"🏷️ Added **{role.name}** to **{added}** member(s)." + (f" {failed} failed." if failed else ""), mention_author=False)
    await send_log(ctx.guild.id, title="🏷️ Role added to all members", color=discord.Color.green(), fields=[("Role", role.name), ("Added", str(added)), ("Failed", str(failed)), ("Moderator", f"{ctx.author} ({ctx.author.id})")])


# ---- AutoMod prefix group ---------------------------------------------------
@bot.group(name="automod", invoke_without_command=True)
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_automod(ctx):
    await ctx.reply("🛡️ Use `?automod word add/remove/list`, `?automod spam on/off`, `?automod mentions on/off [threshold]`, or `?automod invites on/off`.", mention_author=False)


@prefix_automod.group(name="word", invoke_without_command=True)
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_automod_word(ctx):
    await ctx.reply("🛡️ Use `?automod word add <word>`, `remove <word>`, or `list`.", mention_author=False)


@prefix_automod_word.command(name="add")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_automod_word_add(ctx, *, word: str):
    cfg = get_automod(ctx.guild.id)
    changed = word.lower() not in (w.lower() for w in cfg["words"])
    if changed:
        cfg["words"].append(word)
        await bd_save_data()
    await ctx.reply(f"🛡️ {'Added' if changed else 'Already had'} `{word}` in the banned-word list.", mention_author=False)


@prefix_automod_word.command(name="remove")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_automod_word_remove(ctx, *, word: str):
    cfg = get_automod(ctx.guild.id)
    before = len(cfg["words"])
    cfg["words"] = [w for w in cfg["words"] if w.lower() != word.lower()]
    await bd_save_data()
    await ctx.reply(f"🛡️ Removed **{before - len(cfg['words'])}** matching banned word(s).", mention_author=False)


@prefix_automod_word.command(name="list")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_automod_word_list(ctx):
    words = get_automod(ctx.guild.id)["words"]
    await ctx.reply("Banned words: " + (", ".join(f"`{w}`" for w in words) if words else "*(none set)*"), mention_author=False)


def _prefix_bool(value: str):
    value = value.lower()
    if value in {"on", "true", "yes", "enable", "enabled", "1"}: return True
    if value in {"off", "false", "no", "disable", "disabled", "0"}: return False
    return None


@prefix_automod.command(name="spam")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_automod_spam(ctx, enabled: str):
    value = _prefix_bool(enabled)
    if value is None: return await ctx.reply("❌ Use `on` or `off`.", mention_author=False)
    get_automod(ctx.guild.id)["spam"] = value
    await bd_save_data()
    await ctx.reply(f"🛡️ Spam detection **{'on' if value else 'off'}**.", mention_author=False)


@prefix_automod.command(name="mentions")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_automod_mentions(ctx, enabled: str, threshold: int = 5):
    value = _prefix_bool(enabled)
    if value is None: return await ctx.reply("❌ Use `on` or `off`.", mention_author=False)
    cfg = get_automod(ctx.guild.id)
    cfg["mentions"] = value
    cfg["mention_threshold"] = max(1, threshold)
    await bd_save_data()
    await ctx.reply(f"🛡️ Mass-mention detection **{'on' if value else 'off'}** at threshold **{max(1, threshold)}**.", mention_author=False)


@prefix_automod.command(name="invites")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_automod_invites(ctx, enabled: str):
    value = _prefix_bool(enabled)
    if value is None: return await ctx.reply("❌ Use `on` or `off`.", mention_author=False)
    get_automod(ctx.guild.id)["invites"] = value
    await bd_save_data()
    await ctx.reply(f"🛡️ Invite filter **{'on' if value else 'off'}**.", mention_author=False)


# ---- Anti-raid --------------------------------------------------------------
@bot.group(name="antiraid", invoke_without_command=True)
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_antiraid(ctx):
    cfg = get_antiraid(ctx.guild.id)
    await ctx.reply(f"🚨 Anti-raid is **{'on' if cfg.get('enabled') else 'off'}**. Use `?antiraid enable [threshold] [window]` or `?antiraid disable`.", mention_author=False)


@prefix_antiraid.command(name="enable")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_antiraid_enable(ctx, threshold: int = 5, window_seconds: int = 10):
    cfg = get_antiraid(ctx.guild.id)
    cfg.update({"enabled": True, "threshold": max(2, threshold), "window": max(1, window_seconds)})
    await bd_save_data()
    await ctx.reply(f"🚨 Anti-raid alerts on: **{cfg['threshold']} joins / {cfg['window']}s**.", mention_author=False)


@prefix_antiraid.command(name="disable")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_antiraid_disable(ctx):
    get_antiraid(ctx.guild.id)["enabled"] = False
    await bd_save_data()
    await ctx.reply("🚨 Anti-raid alerts off.", mention_author=False)

# ---- Self-assignable roles --------------------------------------------------
@bot.group(name="reactionrole", invoke_without_command=True)
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_reactionrole(ctx):
    await ctx.reply("🏷️ Use `?reactionrole create @role [button text] [description]` or `?reactionrole remove @role`.", mention_author=False)


@prefix_reactionrole.command(name="create")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
@commands.bot_has_guild_permissions(manage_roles=True)
async def prefix_reactionrole_create(ctx, role: discord.Role, label: str = "Toggle Role 🐾", *, description: str = None):
    if role.is_default() or role.managed or role >= ctx.guild.me.top_role:
        return await ctx.reply("❌ I can't manage that role because of role hierarchy or because it is managed.", mention_author=False)
    embed = discord.Embed(title="🐾 Self-Assignable Role", description=description or f"Click below to toggle **{role.name}**.", color=0xFFB02E)
    view = ReactionRoleView(role.id, label)
    await ctx.reply(embed=embed, view=view, mention_author=False)
    reaction_role_ids.add(role.id)
    await bd_save_data()
    bot.add_view(view)
    await send_log(ctx.guild.id, title="🏷️ Reaction role created", category="roles", fields=[("Role", f"{role.name} ({role.id})"), ("Button label", label[:80]), ("Moderator", f"{ctx.author} ({ctx.author.id})")])


@prefix_reactionrole.command(name="remove")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_reactionrole_remove(ctx, role: discord.Role):
    reaction_role_ids.discard(role.id)
    await bd_save_data()
    await ctx.reply(f"🐾 **{role.name}** is no longer tracked as self-assignable.", mention_author=False)
    await send_log(ctx.guild.id, title="🏷️ Reaction role removed", category="roles", fields=[("Role", f"{role.name} ({role.id})"), ("Moderator", f"{ctx.author} ({ctx.author.id})")])


# ---- Welcome / goodbye ------------------------------------------------------
@bot.group(name="welcome", invoke_without_command=True)
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_welcome(ctx):
    await ctx.reply("👋 Use `!welcome set #channel [message]` or `!welcome disable`. Placeholders: `{member}`, `{server}`.", mention_author=False)


@prefix_welcome.command(name="set")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_welcome_set(ctx, channel: discord.TextChannel, *, message: str = "🐾 Welcome {member} to {server}! Glad you're here."):
    error = _validate_template(message)
    if error:
        return await ctx.reply(error, mention_author=False)
    welcome_config[ctx.guild.id] = {"channel_id": channel.id, "message": message}
    await bd_save_data()
    await ctx.reply(f"👋 Welcome messages will post in {channel.mention}.", mention_author=False)
    await send_log(ctx.guild.id, title="👋 Welcome configuration changed", category="setup", fields=[("Channel", channel.mention), ("Message", message[:900]), ("Moderator", f"{ctx.author} ({ctx.author.id})")])


@prefix_welcome.command(name="disable")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_welcome_disable(ctx):
    welcome_config.pop(ctx.guild.id, None)
    await bd_save_data()
    await ctx.reply("👋 Welcome messages turned off.", mention_author=False)


@bot.group(name="goodbye", invoke_without_command=True)
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_goodbye(ctx):
    await ctx.reply("🚪 Use `!goodbye set #channel [message]` or `!goodbye disable`. Placeholders: `{member}`, `{server}`.", mention_author=False)


@prefix_goodbye.command(name="set")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_goodbye_set(ctx, channel: discord.TextChannel, *, message: str = "🐾 {member} has left {server}. We'll miss you!"):
    error = _validate_template(message)
    if error:
        return await ctx.reply(error, mention_author=False)
    goodbye_config[ctx.guild.id] = {"channel_id": channel.id, "message": message}
    await bd_save_data()
    await ctx.reply(f"🚪 Goodbye messages will post in {channel.mention}.", mention_author=False)
    await send_log(ctx.guild.id, title="🚪 Goodbye configuration changed", category="setup", fields=[("Channel", channel.mention), ("Message", message[:900]), ("Moderator", f"{ctx.author} ({ctx.author.id})")])


@prefix_goodbye.command(name="disable")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_goodbye_disable(ctx):
    goodbye_config.pop(ctx.guild.id, None)
    await bd_save_data()
    await ctx.reply("🚪 Goodbye messages turned off.", mention_author=False)

# ---- AI/log moderation controls --------------------------------------------
@bot.command(name="aichannel")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_aichannel(ctx):
    ai_channels[ctx.guild.id] = ctx.channel.id
    await bd_save_data()
    await ctx.reply(f"🤖 {ctx.channel.mention} is now Cinnamon's always-on AI channel.", mention_author=False)
    await send_log(ctx.guild.id, title="⚙️ AI channel set", category="setup", fields=[("Channel", ctx.channel.mention), ("Moderator", f"{ctx.author} ({ctx.author.id})")])


@bot.command(name="disableaichannel")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_disableaichannel(ctx):
    removed = ai_channels.pop(ctx.guild.id, None)
    await bd_save_data()
    await ctx.reply("🤖 Always-on AI channel disabled." if removed else "❌ No always-on AI channel was set.", mention_author=False)


@bot.command(name="disableai")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_disableai(ctx):
    disabled_channels[ctx.guild.id].add(ctx.channel.id)
    await bd_save_data()
    await ctx.reply("🤫 Cinnamon will stay quiet in this channel, even when mentioned.", mention_author=False)


@bot.command(name="enableai")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_enableai(ctx):
    disabled_channels[ctx.guild.id].discard(ctx.channel.id)
    await bd_save_data()
    await ctx.reply("🤖 Cinnamon can talk in this channel again.", mention_author=False)


@bot.command(name="logchannel")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_logchannel(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    log_channels[ctx.guild.id] = channel.id
    await bd_save_data()
    await ctx.reply(f"📋 Main log channel set to {channel.mention}.", mention_author=False)
    await send_log(ctx.guild.id, title="📋 Main log channel changed", category="setup", fields=[("Channel", channel.mention), ("Moderator", f"{ctx.author} ({ctx.author.id})")])


@bot.command(name="disablelogchannel")
@commands.guild_only()
@commands.has_guild_permissions(administrator=True)
async def prefix_disablelogchannel(ctx):
    removed = log_channels.pop(ctx.guild.id, None)
    await bd_save_data()
    await ctx.reply("📋 Main logging disabled." if removed else "❌ No main log channel was set.", mention_author=False)
