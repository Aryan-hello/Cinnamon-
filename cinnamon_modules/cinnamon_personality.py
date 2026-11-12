"""Cinnamon's playful personality, surprise games, and recoverable log snapshots.
Loaded last in main.py, after mood, economy, Hangry Games, and setup.
"""
import json as _cp_json
import random as _cp_random
import time as _cp_time
import re as _cp_re

_CP_LOG = "🐈 Cinnamon personality snapshot"
_CP_LAUNCHING = set()  # prevent duplicate /test-game and scheduler racing before post.send()
_CP_QUESTIONS = (
    "Are cucumbers evil or just misunderstood?",
    "Would you rather live in a castle of tuna or a thousand tiny cardboard boxes?",
    "If I became mayor, what would our very first cat law be?",
    "Is pushing a cup off a table modern art? Explain your answer.",
    "QUICK! A suspicious potato has entered the room. What do we do?",
)

def _cp_server(gid):
    return advanced_features_data.setdefault("cinnamon_social_v1", {}).setdefault(
        str(gid), {"people": {}, "auto_enabled": False})

def _cp_person(gid, uid):
    return _cp_server(gid).setdefault("people", {}).setdefault(
        str(uid), {"good": 0, "wins": 0, "rare_fish": 0})

def _cp_favourites(gid):
    members = _cp_server(gid)["people"]
    return sorted(((int(uid), int(p.get("good", 0))) for uid, p in members.items()
                   if str(uid).isdigit() and int(p.get("good", 0)) >= 3),
                  key=lambda x: (-x[1], x[0]))[:3]

def _cp_nice(gid, uid):
    return int(_cp_person(gid, uid).get("good", 0)) >= 5 and not _cm_naughty(gid, uid)

def _cp_direct_name(content):
    """A direct address, not incidental 'cinnamon rolls' or quoted text."""
    text = str(content or "").strip()[:300].lower()
    return bool(_cp_re.match(r"^(?:(?:hey|hi|hello|yo|psst)[,! ]+)?cinnamon(?:[!?.,: ]|$)", text)
                or _cp_re.search(r"\b(?:what about you|and you|your thoughts)[, ]+cinnamon[?.!]*$", text))


async def _cp_maybe_cameo(message):
    """Extremely rare one-line cameo about another cat. Never begins dialogue."""
    if not message.guild or message.author.bot or not message.content:
        return False
    gid, ch = message.guild.id, message.channel
    s = _cp_server(gid)
    if (not _cb_independence_enabled(gid) or not _cb_storage_available()
            or (callable(globals().get("_cx_serious")) and _cx_serious(gid))
            or not s.get("cameos_enabled", True)):
        return False
    if (ch.id in disabled_channels[gid] or
        ch.id in set(category_log_channels.get(gid, {}).values()) or
        not ch.permissions_for(message.guild.me).send_messages):
        return False
    text = message.content.lower()
    if not _cp_re.search(r"\b(?:another cat|other cat|that cat|cute kitten|adorable kitten)\b", text):
        return False
    now = _cp_time.time()
    key = "cameo_channel_" + str(ch.id)
    if now - float(s.get("last_cameo", 0)) < 21600 or now - float(s.get(key, 0)) < 21600:
        return False
    if _cp_random.random() >= 0.02:
        return False
    s["last_cameo"], s[key] = now, now
    if not await bd_save_data():
        return False
    if not _cb_independence_enabled(gid) or not guild_channel_send_allowed(message.guild, ch):
        return False
    try:
        await ch.send("😾 Oh. We're admiring OTHER cats in this household now. Interesting. *tail flick*",
                      allowed_mentions=discord.AllowedMentions.none())
        await _cp_log(gid, "Single voluntary jealousy cameo (no ping)")
        return True
    except discord.HTTPException:
        return False


async def _cp_log(gid, event, uid=None):
    """Admin-only absolute snapshots, without members' private message content."""
    if not category_log_channels.get(gid, {}).get("stuff"):
        return
    mood = _cm_state(gid)
    person = _cp_person(gid, uid) if uid else {}
    snapshot = {k: int(person.get(k, 0)) for k in ("good", "wins", "rare_fish")}
    await send_log(gid, title=_CP_LOG, category="stuff", fields=[
        ("Event", str(event)[:140]),
        ("User ID", str(uid or 0)),
        ("Member state", _cp_json.dumps(snapshot, separators=(",", ":"))),
        ("Mood score", str(int(mood.get("score", 0)))),
        ("Mood updated", str(int(mood.get("updated", _cp_time.time())))),
        ("Mood", _cm_tier(gid)),
        ("Naughty until", str(int(_cm_member(gid, uid).get("naughty_until", 0))) if uid else "0"),
        ("Favourite visitors", ", ".join(f"{u}:{v}" for u, v in _cp_favourites(gid)) or "None"),
        ("Nice list count", str(sum(1 for v in _cp_server(gid)["people"].values()
                                   if int(v.get("good", 0)) >= 5))),
    ])
    # Dedicated mood-only channel as well as the master Stuff audit channel.
    if any(word in str(event).lower() for word in ("mood", "naughty", "sad", "jealous", "apolog")):
        await send_log(gid, title="😺 Cinnamon mood & personality change", category="mood",
                       fields=[("Event", str(event)[:140]), ("User ID", str(uid or 0)),
                               ("Mood", _cm_tier(gid)), ("Score", str(int(mood.get("score", 0))))])

async def _cp_good_event(guild, member, reason, points=1):
    if not guild or not member or member.bot:
        return
    p = _cp_person(guild.id, member.id)
    p["good"] = min(10000, int(p.get("good", 0)) + points)
    await bd_save_data()
    if p["good"] <= 5 or p["good"] % 10 == 0:
        await _cp_log(guild.id, reason, member.id)

async def _cp_react(guild, member, channel, kind, *, value=0, detail=""):
    """An occasional in-channel quip; never an additional member ping."""
    if not guild or not member or member.bot or not channel:
        return
    if kind == "big_purchase" and value < 5000:
        return
    p = _cp_person(guild.id, member.id)
    now = _cp_time.time()
    if now - float(p.get("react_" + kind, 0)) < 900:
        return
    p["react_" + kind] = now
    nice = _cp_nice(guild.id, member.id)
    if kind == "big_purchase":
        line = _cp_random.choice((
            "😼 OH, LOOK! MISTER MONEYBAGS JUST SPENT {value:,} CATNIP!",
            "🐈 {value:,} CATNIP?! I suddenly remembered we are VERY good friends.",
            "👑 The royal wallet has arrived. My accountant is purring.",
        )).format(value=value)
    elif kind == "rare_fish":
        p["rare_fish"] = int(p.get("rare_fish", 0)) + 1
        name = str(detail)[:70]
        line = (f"😻 MY FAVOURITE FISHING GENIUS CAUGHT {name}! AAAAA!" if nice else
                f"🐈 YOU CAUGHT {name}?! I DEMAND AN AUTOGRAPH FROM THAT FISH.")
    elif kind == "hangry_win":
        p["wins"] = int(p.get("wins", 0)) + 1
        line = ("😻 MY CHAMPION! I'M SO PROUD I'M KNOCKING OVER THE TROPHY!" if nice else
                "🏆 WINNER WINNER TUNA DINNER! Collect your trophy before I eat it.")
    elif kind == "giveaway_win":
        line = ("😻 MY FAVOURITE LUCKY CHARM! YOU WON! AAAAA!" if nice else
                "🎉 YOU WON?! I am claiming full credit for your excellent luck.")
    else:
        return
    await bd_save_data()
    try:
        await channel.send(line, allowed_mentions=discord.AllowedMentions.none())
    except (discord.HTTPException, AttributeError):
        pass
    await _cp_log(guild.id, kind, member.id)

async def _cp_answer(message):
    p = _cp_person(message.guild.id, message.author.id)
    q = p.get("pending")
    if not isinstance(q, dict) or q.get("status") not in ("waiting", "missed"):
        return ""
    age = _cp_time.time() - float(q.get("asked_at", 0))
    if age > 86400:
        p.pop("pending", None)
        return ""
    if message.channel.id != int(q.get("channel_id", 0)):
        return ""
    q["status"] = "answered"
    late = age > 120
    _cm_adjust(message.guild.id, 4 if late else 6)
    await bd_save_data()
    await _cp_log(message.guild.id, "Late answer" if late else "Question answered", message.author.id)
    return ("😹 YOU ARE LATE!! I waited nine hundred cat-years. But I am glad you answered!\n"
            if late else "😻 YOU ANSWERED! My very important cat question has been respected!\n")

async def _cp_maybe_question(message):
    """Only a member talking to Cinnamon can get an optional personal ping."""
    if not message.guild or message.author.bot:
        return
    gid, uid = message.guild.id, message.author.id
    s, p = _cp_server(gid), _cp_person(gid, uid)
    now = _cp_time.time()
    if (not _cb_independence_enabled(gid) or not _cb_storage_available() or
        (callable(globals().get("_cx_serious")) and _cx_serious(gid)) or
        not s.get("questions_enabled", True) or p.get("questions_optout") or
        now - float(p.get("last_question", 0)) < 86400 or
        now - float(s.get("last_question", 0)) < 21600 or
        _cp_random.random() >= .08):
        return
    p["last_question"], s["last_question"] = now, now
    if not await bd_save_data():
        return
    if (not _cb_independence_enabled(gid)
            or not guild_channel_send_allowed(message.guild, message.channel)):
        return
    try:
        msg = await message.channel.send(
            f"{message.author.mention} 🐈 CINNAMON HAS A QUESTION! {_cp_random.choice(_CP_QUESTIONS)}\n"
            "No rush. You can opt out via /cinnamon-events questions.",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        p["pending"] = {"asked_at": now, "channel_id": message.channel.id,
                        "message_id": msg.id, "status": "waiting"}
        await bd_save_data()
        await _cp_log(gid, "Random question sent", uid)
    except (discord.HTTPException, AttributeError):
        pass

async def _cp_recover(guild, limit=1200):
    """Restore only MISSING absolute mood/member state from administrator logs."""
    cid = category_log_channels.get(guild.id, {}).get("stuff")
    channel = guild.get_channel(cid) if cid else None
    if channel is None:
        channel = discord.utils.get(guild.text_channels, name="cinnamon-stuff-logs")
        if channel:
            category_log_channels.setdefault(guild.id, {})["stuff"] = channel.id
    if channel is None:
        return {"members": 0, "mood": 0, "scanned": 0}
    s = _cp_server(guild.id)
    mood_root = advanced_features_data.setdefault("cinnamon_mood_v1", {})
    missing_mood = str(guild.id) not in mood_root
    seen = set()
    n = restored = mood = naughty_restored = 0
    try:
        async for msg in channel.history(limit=limit, oldest_first=False):
            for embed in msg.embeds:
                if embed.title != _CP_LOG:
                    continue
                n += 1
                f = {a.name: a.value for a in embed.fields}
                if missing_mood:
                    try:
                        mood_root[str(guild.id)] = {
                            "score": max(-60, min(60, int(f["Mood score"]))),
                            "updated": float(f["Mood updated"]), "members": {}}
                        missing_mood, mood = False, 1
                    except (ValueError, TypeError, KeyError):
                        pass
                try:
                    uid = int(f.get("User ID", "0"))
                    if not uid or uid in seen:
                        continue
                    seen.add(uid)
                    payload = _cp_json.loads(f.get("Member state", "{}"))
                    if str(uid) not in s["people"] and isinstance(payload, dict):
                        s["people"][str(uid)] = {k: max(0, min(10000, int(payload.get(k, 0))))
                                                 for k in ("good", "wins", "rare_fish")}
                        restored += 1
                    until = float(f.get("Naughty until", "0"))
                    if until > _cp_time.time() and not _cm_member(guild.id, uid).get("naughty_until"):
                        _cm_member(guild.id, uid)["naughty_until"] = until
                        naughty_restored += 1
                except (TypeError, ValueError, KeyError, _cp_json.JSONDecodeError):
                    continue
    except (discord.HTTPException, discord.Forbidden):
        log.warning("Cinnamon could not scan stuff logs for guild %s", guild.id)
    if restored or mood or naughty_restored:
        await bd_save_data()
    return {"members": restored, "mood": mood, "scanned": n}

async def _cp_auto_start(guild, channel, cog, *, explicit=False):
    """Open one bounded lobby; recheck its boundaries before every outward step."""
    eligible, reason = _cb_game_eligibility(
        guild, channel, cog, check_activity=not explicit)
    if not eligible:
        _cp_server(guild.id)["last_brain_reason"] = reason
        return
    _CP_LAUNCHING.add(channel.id)
    role = discord.utils.get(guild.roles, name="Hangry Games")
    prize = _cp_random.randint(1000, 2500)
    view = HGLobbyView(cog, guild.me, catnip_prize=prize, sponsor=guild.me)
    view.auto_managed = True
    for button in view.children:
        if button.label == "Start 🔴":
            button.disabled = True
    post = None
    unanswered_recorded = False
    try:
        _cp_server(guild.id)["last_initiated_at"] = _cp_time.time()
        # A persisted reservation precedes even an explicitly requested test
        # lobby. If storage is unavailable, no invitation is sent.
        if not await bd_save_data():
            _cp_server(guild.id)["last_brain_reason"] = "storage_unavailable"
            return
        eligible, reason = _cb_game_eligibility(
            guild, channel, cog, own_lobby=view, check_activity=not explicit)
        if not eligible:
            _cp_server(guild.id)["last_brain_reason"] = reason
            return
        post = await channel.send(
            f"{role.mention} 🐈 CINNAMON DECLARES HANGRY GAMES!\n"
            f"{prize:,} Catnip to the champion! You have TWO MINUTES to join, "
            "you suspicious potatoes. I WILL BE WATCHING. 👀",
            embed=view.embed(), view=view,
            allowed_mentions=discord.AllowedMentions(users=False, roles=[role], everyone=False))
        started_at = _cp_time.monotonic()
        view.message = post
        cog.lobbies[channel.id] = view
        await cog._log(guild.id, title="🐈 Cinnamon surprise Hangry Games announced",
                       fields=[("Channel", channel.mention), ("Prize", str(prize)),
                               ("Join window", "120 seconds"), ("Role", str(role.id))])
        await _cp_log(guild.id, "Surprise game started")
        await asyncio.sleep(max(0, 90 - (_cp_time.monotonic() - started_at)))
        if view.started or cog.lobbies.get(channel.id) is not view:
            return
        eligible, reason = _cb_game_eligibility(
            guild, channel, cog, own_lobby=view, check_activity=not explicit)
        if not eligible:
            _cp_server(guild.id)["last_brain_reason"] = reason
            return
        if view.players:
            await channel.send(
                f"{role.mention} 😼 30 SECONDS LEFT! JOIN NOW! I DID NOT POLISH A TROPHY FOR NOTHING!",
                allowed_mentions=discord.AllowedMentions(users=False, roles=[role], everyone=False))
        await asyncio.sleep(max(0, 120 - (_cp_time.monotonic() - started_at)))
        if view.started or cog.lobbies.get(channel.id) is not view:
            return
        eligible, reason = _cb_game_eligibility(
            guild, channel, cog, own_lobby=view, check_activity=not explicit)
        if not eligible:
            _cp_server(guild.id)["last_brain_reason"] = reason
            return
        if len(view.players) < 2:
            # Record feedback before any Discord edit: revoked permissions
            # cannot accidentally erase the six-hour quiet period.
            _cp_server(guild.id)["last_unanswered_game_at"] = _cp_time.time()
            unanswered_recorded = True
            await bd_save_data()
            await cog._log(guild.id, title="🐈 Cinnamon surprise game quietly cancelled",
                           fields=[("Reason", "Fewer than 2 players"),
                                   ("Joined", str(len(view.players))), ("Prize unpaid", str(prize))])
            return
        # Remove our lobby before launch so the existing game implementation
        # sees a free channel. A failure here never creates a second launch.
        cog.lobbies.pop(channel.id, None)
        view.started = True
        view.stop()
        await cog.launch(channel, dict(view.players), guild.me, None, None,
                         catnip_prize=prize, sponsor=guild.me)
    except (discord.HTTPException, discord.Forbidden) as exc:
        log.warning("Surprise game failed in guild %s (%s)", guild.id, type(exc).__name__)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Surprise game suppressed in guild %s", guild.id)
    finally:
        if cog.lobbies.get(channel.id) is view:
            cog.lobbies.pop(channel.id, None)
        view.started = True
        view.stop()
        for button in view.children:
            button.disabled = True
        if post is not None and len(view.players) < 2 and not unanswered_recorded:
            _cp_server(guild.id)["last_unanswered_game_at"] = _cp_time.time()
            try:
                await bd_save_data()
            except Exception:
                log.exception("Cinnamon could not save unanswered-game feedback for guild %s", guild.id)
        if post is not None:
            try:
                await post.edit(embed=view.embed(), view=view)
            except (discord.HTTPException, discord.Forbidden):
                pass
        _CP_LAUNCHING.discard(channel.id)


async def _cp_auto_prompt(guild, channel, cog):
    """One optional community question, with no mentions or competing scheduler."""
    if not _cb_prompt_allowed(guild.id):
        return False
    ready, _ = _cb_game_eligibility(guild, channel, cog)
    if not ready:
        return False
    social = _cp_server(guild.id)
    now = _cp_time.time()
    social["last_public_prompt_at"] = now
    social["prompt_pending_until"] = now + 15 * 60
    # Durable claim before the first public message prevents restart spam.
    if not await bd_save_data():
        return False
    # Stop if someone disabled the feature, independence, or channel permission.
    ready, _ = _cb_game_eligibility(guild, channel, cog)
    if not ready or not _cb_settings(guild.id).get("prompts_enabled", False):
        return False
    try:
        await channel.send(
            "🐈 **CINNAMON HAS A QUESTION FOR THE ENTIRE KINGDOM!**\\n" +
            _cp_random.choice(_CP_QUESTIONS) +
            "\\nNo pressure to reply. I am just collecting scientific evidence. 😼",
            allowed_mentions=discord.AllowedMentions.none())
        await _cp_log(guild.id, "Optional no-ping community question posted")
        return True
    except (discord.Forbidden, discord.HTTPException):
        social["prompt_pending_until"] = 0
        await bd_save_data()
        return False


async def _cp_tick_guild(guild, cog, now):
    """Process one guild independently so a broken guild cannot stop the clock."""
    s = _cp_server(guild.id)
    # A recent human response counts as engagement; no response triggers a
    # long prompt backoff without blaming or pinging members.
    pending_until = float(s.get("prompt_pending_until", 0) or 0)
    if pending_until:
        sent_at = float(s.get("last_public_prompt_at", 0) or 0)
        activity = globals().get("_CB_ACTIVITY", {}).get(guild.id, ())
        answered = any(ts > sent_at for ts, _ in activity)
        if answered or now > pending_until:
            s["prompt_pending_until"] = 0
            if not answered:
                s["last_ignored_prompt_at"] = now
            await bd_save_data()
    if s.get("auto_enabled") and s.get("auto_channel"):
        due = float(s.get("next_at", 0))
        if not due:
            s["next_at"] = now + _cp_random.randint(3600, 7200)
            await bd_save_data()
        elif due <= now and cog:
            channel = guild.get_channel(int(s["auto_channel"]))
            ready, reason = _cb_game_eligibility(guild, channel, cog, now=now)
            # The clock creates an opportunity, not an obligation to speak.
            s["next_at"] = now + _cp_random.randint(3600, 7200)
            s["last_brain_reason"] = reason
            s["brain_opportunities"] = int(s.get("brain_opportunities", 0)) + 1
            saved = await bd_save_data()
            if ready and saved:
                chooser = globals().get("_cb_choose_activity")
                choice = (await chooser(guild.id, now=now)
                          if callable(chooser) else "game")
                s["last_brain_choice"] = choice
                if choice == "game":
                    asyncio.create_task(_cp_auto_start(guild, channel, cog))
                elif choice == "prompt" and callable(globals().get("_cp_auto_prompt")):
                    asyncio.create_task(_cp_auto_prompt(guild, channel, cog))
            elif not saved:
                s["last_brain_reason"] = "storage_unavailable"
    for uid, p in list(s.get("people", {}).items()):
        q = p.get("pending")
        if q and q.get("status") == "waiting" and now - float(q.get("asked_at", 0)) > 120:
            q["status"] = "missed"
            await bd_save_data()


async def _cp_tick():
    """One scheduler; each guild and iteration recovers independently."""
    try:
        await bot.wait_until_ready()
        while not bot.is_closed():
            now = _cp_time.time()
            cog = bot.get_cog("HangryGamesCog")
            for guild in bot.guilds:
                try:
                    await _cp_tick_guild(guild, cog, now)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _cp_server(guild.id)["last_brain_reason"] = "scheduler_error"
                    log.exception("Cinnamon activity check failed in guild %s", guild.id)
            # Reuse this one scheduler for member-requested reminders too.
            try:
                await _cr_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Cinnamon reminder scheduler pass failed")
            await asyncio.sleep(15)
    except asyncio.CancelledError:
        raise
    finally:
        bot._cp_scheduler_running = False

@bot.listen("on_ready")
async def _cp_ready():
    if not getattr(bot, "_cp_scheduler_running", False):
        bot._cp_scheduler_running = True
        asyncio.create_task(_cp_tick())

_cp_group = app_commands.Group(name="cinnamon-events", description="Surprise Hangry Games and Cinnamon's personality")

@_cp_group.command(name="status", description="See Cinnamon's activity checks and favourite visitors")
@app_commands.guild_only()
async def cinnamon_events_status(interaction: discord.Interaction):
    data = _cp_server(interaction.guild.id)
    ch = interaction.guild.get_channel(int(data.get("auto_channel", 0) or 0))
    due = int(data.get("next_at", 0))
    desc = f"🎮 Surprise games: {'ON' if data.get('auto_enabled') else 'OFF'}\n"
    desc += f"📢 Game channel: {ch.mention if ch else 'Run /setup'}\n"
    if due and data.get("auto_enabled"):
        desc += f"⏳ Next activity check: <t:{due}:R>\n"
    fav = _cp_favourites(interaction.guild.id)
    desc += ("😻 Favourite visitors: " + ", ".join(f"<@{uid}>" for uid, _ in fav)
             if fav else "😺 No favourite visitors ranked yet!")
    card = discord.Embed(title="🎮 Cinnamon's Surprise Games",
                         description=desc, color=0xD89138)
    card.add_field(name="🌿 Winner prize",value="1,000–2,500 Catnip",inline=True)
    card.add_field(name="⏳ Join window",value="2 minutes · up to 2 opt-in role pings",inline=True)
    card.add_field(name="🛡️ Safety",value="Autonomous @everyone is disabled. Personal questions are optional.",inline=False)
    card.set_footer(text="Cinnamon Mind • /cinnamon-events notify to receive game alerts")
    await interaction.response.send_message(embed=card, ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())

@_cp_group.command(name="auto", description="Admin: enable activity checks for surprise games and optional questions")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_events_auto(interaction: discord.Interaction, enabled: bool):
    s = _cp_server(interaction.guild.id)
    if enabled and not s.get("auto_channel"):
        return await interaction.response.send_message("🐈 Run /setup to create the public game channel first.", ephemeral=True)
    s["auto_enabled"] = bool(enabled)
    if enabled:
        s["next_at"] = _cp_time.time() + _cp_random.randint(3600, 7200)
    await bd_save_data()
    await _cp_log(interaction.guild.id, "Surprise games " + ("enabled" if enabled else "disabled"))
    await interaction.response.send_message(
        "🐈 Surprise Hangry Games " + ("enabled" if enabled else "disabled") +
        ". When enabled, Cinnamon checks for real member activity; quiet servers are skipped.", ephemeral=True)

@_cp_group.command(name="channel", description="Admin: choose Cinnamon's surprise Hangry Games channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_events_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    s = _cp_server(interaction.guild.id)
    s["auto_channel"] = channel.id
    s["next_at"] = _cp_time.time() + _cp_random.randint(3600, 7200)
    await bd_save_data()
    await _cp_log(interaction.guild.id, "Surprise games channel changed")
    await interaction.response.send_message(f"🎮 Surprise games will appear in {channel.mention}.", ephemeral=True)

@_cp_group.command(name="questions", description="Opt in or out of Cinnamon's occasional personal questions")
@app_commands.guild_only()
async def cinnamon_events_questions(interaction: discord.Interaction, enabled: bool):
    p = _cp_person(interaction.guild.id, interaction.user.id)
    p["questions_optout"] = not enabled
    if not enabled:
        p.pop("pending", None)
    await bd_save_data()
    await interaction.response.send_message(
        "🐈 Random questions " + ("enabled" if enabled else "disabled") +
        " for you. This setting does not affect reminders you explicitly request.", ephemeral=True)

@_cp_group.command(name="notify", description="Opt in or out of up to two Hangry Games role alerts")
@app_commands.guild_only()
async def cinnamon_events_notify(interaction: discord.Interaction, enabled: bool):
    role = discord.utils.get(interaction.guild.roles, name="Hangry Games")
    if role is None:
        return await interaction.response.send_message(
            "🐈 Ask a server administrator to run /setup first. I need my Hangry Games role!", ephemeral=True)
    me = interaction.guild.me
    if not me or not me.guild_permissions.manage_roles or role >= me.top_role:
        return await interaction.response.send_message(
            "⚠️ Cinnamon needs Manage Roles, with her role above Hangry Games.", ephemeral=True)
    if enabled and role not in interaction.user.roles:
        await interaction.user.add_roles(role, reason="Opted in to surprise Hangry Games announcements")
    elif not enabled and role in interaction.user.roles:
        await interaction.user.remove_roles(role, reason="Opted out of surprise Hangry Games announcements")
    await interaction.response.send_message(
        "🎮 You will " + ("receive" if enabled else "no longer receive") +
        " up to two opt-in role alerts for surprise games.", ephemeral=True)

@_cp_group.command(name="people", description="Admin: view Cinnamon's favourite visitors and nice/naughty records")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_events_people(interaction: discord.Interaction):
    gid = interaction.guild.id
    members = _cp_server(gid).get("people", {})
    good = sorted(((uid, int(v.get("good", 0))) for uid, v in members.items()),
                  key=lambda x: (-x[1], x[0]))[:8]
    naughty = [uid for uid, v in _cm_state(gid).get("members", {}).items()
               if float(v.get("naughty_until", 0)) > _cp_time.time()][:8]
    lines = ["😻 Favourite visitors: " + (", ".join(f"<@{uid}>" for uid, _ in _cp_favourites(gid)) or "None"),
             "😺 Nice deeds: " + (", ".join(f"<@{uid}> ({v})" for uid, v in good) or "None"),
             "😾 Naughty right now: " + (", ".join(f"<@{uid}>" for uid in naughty) or "None"),
             "🐈 Mood: " + _cm_tier(gid)]
    await interaction.response.send_message("\n".join(lines), ephemeral=True,
                                            allowed_mentions=discord.AllowedMentions.none())


@_cp_group.command(name="test-game", description="Admin: test a surprise lobby immediately without changing the schedule")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_events_test_game(interaction: discord.Interaction):
    s = _cp_server(interaction.guild.id)
    channel = interaction.guild.get_channel(int(s.get("auto_channel", 0) or 0))
    cog = bot.get_cog("HangryGamesCog")
    if not channel or not cog:
        return await interaction.response.send_message(
            "🐈 Run /setup and make sure the Hangry Games cog is online first.", ephemeral=True)
    if cog._busy(channel.id):
        return await interaction.response.send_message("🐈 A game is already running in that channel!", ephemeral=True)
    if not discord.utils.get(interaction.guild.roles, name="Hangry Games"):
        return await interaction.response.send_message("🐈 Run /setup to create the Hangry Games role.", ephemeral=True)
    eligible, reason = _cb_game_eligibility(
        interaction.guild, channel, cog, check_activity=False)
    if not eligible:
        return await interaction.response.send_message(
            "🐈 Test lobby stayed quiet: " + reason.replace("_", " ") + ".", ephemeral=True)
    asyncio.create_task(_cp_auto_start(interaction.guild, channel, cog, explicit=True))
    await interaction.response.send_message("🎮 Test lobby starting now! Two minutes to join, with up to two opt-in role alerts.", ephemeral=True)


@_cp_group.command(name="cameos", description="Admin: allow rare non-pinging Cinnamon jealousy jokes")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_events_cameos(interaction: discord.Interaction, enabled: bool):
    s = _cp_server(interaction.guild.id)
    s["cameos_enabled"] = bool(enabled)
    await bd_save_data()
    await _cp_log(interaction.guild.id, "Jealous cameo " + ("enabled" if enabled else "disabled"))
    await interaction.response.send_message(
        "🐈 Cinnamon's optional one-line cameos are " + ("ON" if enabled else "OFF") +
        ". Max one per server per six hours, no member pings.", ephemeral=True)


class _CPAdminAnnouncementConfirm(discord.ui.View):
    def __init__(self, owner_id, channel, content):
        super().__init__(timeout=60)
        self.owner_id, self.channel, self.content = owner_id, channel, content
        self.sent = False

    @discord.ui.button(label="Confirm @everyone announcement", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id or not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Only the requesting administrator can confirm.", ephemeral=True)
        if self.sent:
            return await interaction.response.send_message("Already sent.", ephemeral=True)
        s = _cp_server(interaction.guild.id)
        if _cp_time.time() - float(s.get("last_mass_ping", 0)) < 900:
            return await interaction.response.send_message("Safety cooldown: @everyone limited to once per 15 minutes per server.", ephemeral=True)
        if self.channel.guild.id != interaction.guild.id:
            return await interaction.response.send_message("Channel mismatch.", ephemeral=True)
        self.sent = True
        button.disabled = True
        try:
            # ONLY this admin-confirmed path can opt in to @everyone.
            await self.channel.send("@everyone " + self.content,
                 allowed_mentions=discord.AllowedMentions(everyone=True, users=False, roles=False, replied_user=False))
            s["last_mass_ping"] = _cp_time.time()
            await bd_save_data()
            await _cp_log(interaction.guild.id, "Administrator confirmed @everyone announcement", interaction.user.id)
            await interaction.response.edit_message(content="✅ Announcement sent. Audited in Cinnamon Stuff Logs.", view=self)
        except discord.HTTPException:
            self.sent = False
            button.disabled = False
            await interaction.response.send_message("Discord could not deliver the announcement; verify channel permissions.", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("This confirmation is not yours.", ephemeral=True)
        await interaction.response.edit_message(content="Announcement cancelled.", view=None)
        self.stop()


@_cp_group.command(name="announce", description="Admin only: send a confirmed mass announcement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_events_announce(interaction: discord.Interaction, channel: discord.TextChannel,
                                  text: app_commands.Range[str, 1, 1700]):
    if channel.guild.id != interaction.guild.id or not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("Administrator required in this server.", ephemeral=True)
    if not channel.permissions_for(interaction.guild.me).send_messages:
        return await interaction.response.send_message("Cinnamon cannot send in that channel.", ephemeral=True)
    # Remove any spoofed mention tokens from the requested text before prefixing.
    clean = _cp_re.sub(r"@(?:everyone|here)", "everyone", text, flags=_cp_re.IGNORECASE)
    view = _CPAdminAnnouncementConfirm(interaction.user.id, channel, clean)
    await interaction.response.send_message(
        f"⚠️ **This WILL ping @everyone in {channel.mention}.**\n"
        f"Preview: {clean[:800]}\nConfirm within 60 seconds or cancel.",
        view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


bot.tree.add_command(_cp_group)
