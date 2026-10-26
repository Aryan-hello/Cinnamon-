"""Cinnamon's server-local mood: bounded, friendly, and saved with bot state.

Loaded in main.py after the regular feature modules. Keep the modifiers
deterministic within short windows, and never modify the permanent base prices.
"""
import hashlib as _cm_hashlib

_CM_NAUGHTY_ROLE = "Cinnamon's Naughty List"
_CM_NAUGHTY_SECONDS = 30 * 60
_CM_ACTION_COOLDOWN = 90
_CM_FOOD_WINDOW = 10 * 60


def _cm_root():
    return advanced_features_data.setdefault("cinnamon_mood_v1", {})


def _cm_state(guild_id):
    g = _cm_root().setdefault(str(guild_id), {"score": 0, "updated": time.time(), "members": {}})
    now = time.time()
    old = float(g.get("updated", now))
    steps = max(0, int((now - old) // 1800))
    if steps:
        score = int(g.get("score", 0))
        g["score"] = max(0, score - steps * 6) if score > 0 else min(0, score + steps * 6)
        g["updated"] = old + steps * 1800
    g.setdefault("members", {})
    return g


def _cm_member(guild_id, user_id):
    return _cm_state(guild_id)["members"].setdefault(str(user_id), {})


def _cm_tier(guild_id):
    score = int(_cm_state(guild_id).get("score", 0))
    if score >= 35:
        return "delighted"
    if score <= -35:
        return "grumpy"
    return "normal"


def _cm_adjust(guild_id, change):
    g = _cm_state(guild_id)
    g["score"] = max(-60, min(60, int(g.get("score", 0)) + int(change)))
    g["updated"] = time.time()
    return _cm_tier(guild_id)


def _cm_naughty(guild_id, user_id):
    return float(_cm_member(guild_id, user_id).get("naughty_until", 0)) > time.time()


def _cm_price(guild_id, user_id, item_id, base_price):
    """Return final price, including bounded mood sales and temporary naughty fee.

    Delighted: 10% off, sometimes a 25% flash discount (deterministic per item
    and 30-minute interval). Grumpy: +20%. Normal: regular catalogue prices.
    The +1000 temporary naughty fee is only applied to items costing Catnip.
    """
    base = max(0, int(base_price))
    if not base:
        return 0
    mood = _cm_tier(guild_id)
    if mood == "delighted":
        bucket = int(time.time() // 1800)
        digest = _cm_hashlib.sha256(f"{guild_id}:{item_id}:{bucket}".encode()).digest()
        percent = 75 if digest[0] < 64 else 90
        final = max(1, (base * percent + 99) // 100)
    elif mood == "grumpy":
        final = (base * 120 + 99) // 100
    else:
        final = base
    if _cm_naughty(guild_id, user_id):
        final += 1000
    return final


def _cm_fishing_bonus(guild_id):
    """Fishing modifier, interpreted as rarity-luck strength; not a guarantee."""
    return {"delighted": 1.0, "normal": 0.0, "grumpy": -0.8}[_cm_tier(guild_id)]


async def _cm_set_naughty(guild, member):
    state = _cm_member(guild.id, member.id)
    state["naughty_until"] = time.time() + _CM_NAUGHTY_SECONDS
    state["makeup_actions"] = 0
    try:
        role = discord.utils.get(guild.roles, name=_CM_NAUGHTY_ROLE)
        if role is None and guild.me and guild.me.guild_permissions.manage_roles:
            role = await guild.create_role(name=_CM_NAUGHTY_ROLE, reason="Cinnamon playful mood system")
        if role and role not in member.roles and guild.me and role < guild.me.top_role:
            await member.add_roles(role, reason="Temporary Cinnamon naughty-list adventure")
    except discord.HTTPException:
        log.warning("Could not grant Cinnamon's Naughty List role in guild %s", guild.id)
    await bd_save_data()
    await _cp_log(guild.id, "Naughty List assigned", member.id)


async def _cm_clear_naughty(guild, member):
    state = _cm_member(guild.id, member.id)
    state["naughty_until"] = 0
    state["makeup_actions"] = 0
    role = discord.utils.get(guild.roles, name=_CM_NAUGHTY_ROLE)
    if role and role in member.roles and guild.me and role < guild.me.top_role:
        try:
            await member.remove_roles(role, reason="Cinnamon's forgiveness / naughty timer expired")
        except discord.HTTPException:
            log.warning("Could not remove expired Cinnamon Naughty List role")
    await bd_save_data()
    await _cp_log(guild.id, "Naughty List cleared", member.id)


async def _cm_action(guild, member, kind, quantity=1):
    """Action cooldown prevents feeding/petting macros from forcing a mood."""
    g, state = guild.id, _cm_member(guild.id, member.id)
    now = time.time()
    if now - float(state.get("last_action", 0)) < _CM_ACTION_COOLDOWN:
        return "🐈 I appreciate the attention, but give me a moment to enjoy it!"
    state["last_action"] = now
    if kind == "feed":
        if now - float(state.get("food_since", 0)) > _CM_FOOD_WINDOW:
            state["food_since"], state["food_count"] = now, 0
        state["food_count"] = int(state.get("food_count", 0)) + max(1, int(quantity))
        if state["food_count"] >= 5:
            _cm_adjust(g, -45)
            await _cm_set_naughty(guild, member)
            return ("😾 WHY ARE YOU TRYING TO MANIPULATE ME WITH FOOD?! "
                    "I'm a CAT, not a vending machine! You are on my Naughty List for 30 minutes.")
        _cm_adjust(g, 5 + min(3, quantity))
        msg = "🐟 *happy chewing noises* Very good snack choices, human."
    elif kind == "pet":
        _cm_adjust(g, 8)
        msg = "🐾 *purrs loudly* Okay, that was a very acceptable pet."
    elif kind == "toy":
        _cm_adjust(g, 9)
        msg = "🧶 *launches across the room* MY TOY! OUR DIPLOMATIC RELATIONS IMPROVE."
    elif kind == "talk":
        _cm_adjust(g, 6)
        msg = "🐈 You actually listened to my concerns? ...Fine. I am slightly less dramatic."
    else:
        return "That action is not in Cinnamon's very important handbook."

    if _cm_naughty(g, member.id) and kind in ("pet", "toy", "talk"):
        state["makeup_actions"] = min(3, int(state.get("makeup_actions", 0)) + 1)
        msg += f" ({state['makeup_actions']}/2 steps toward making up.)"
    await bd_save_data()
    await _cp_good_event(guild, member, "Cinnamon enjoyed " + kind)
    await _cp_log(g, "Mood changed by " + kind, member.id)
    return msg + f"\n**Cinnamon's mood:** {_cm_tier(g).title()}"


async def _cm_ping(message):
    """Occasional grumpy replies; don't ping users or add a per-message punishment."""
    if not message.guild:
        return None
    if _cm_naughty(message.guild.id, message.author.id):
        return random.choice((
            "😼 Well, WELL. A distinguished member of my Naughty List. Have you considered /mood apologize?",
            "🐈 I see you, troublemaker. My shop accountant also sees you. Bring toys, not chaos.",
            "😾 It's you again! Two good deeds and a sincere apology. I believe in character development!",
        ))
    if _cm_tier(message.guild.id) != "grumpy":
        return None
    state = _cm_member(message.guild.id, message.author.id)
    now = time.time()
    if now - float(state.get("last_ping", 0)) < 35:
        if now - float(state.get("ping_window", 0)) > 300:
            state["ping_window"], state["fast_pings"] = now, 0
        state["fast_pings"] = int(state.get("fast_pings", 0)) + 1
        if state["fast_pings"] >= 5 and not _cm_naughty(message.guild.id, message.author.id):
            await _cm_set_naughty(message.guild, message.author)
            return "😾 FIVE PINGS?! THE NAUGHTY LIST HAS CHOSEN YOU. You may appeal using /mood apologize."
    else:
        state["fast_pings"] = 0
        state["ping_window"] = now
    state["last_ping"] = now
    # A direct ping always gets a cat-astrophically grumpy answer in this mood.
    return random.choice((
        "😾 I WAS HAVING A VERY IMPORTANT NAP. Did the universe end? No? THEN WHY THE PING?!",
        "🐈 *furiously types with one paw* My lawyer will hear about these notifications.",
        "😼 If this is about the missing tuna, I was never here.",
        "😾 I am NOT angry. My tail is simply expressing its constitutional rights.",
    ))


async def _cm_expire_naughty_roles():
    """Best-effort role cleanup across restarts; prices expire immediately anyway."""
    try:
        while not bot.is_closed():
            for guild in bot.guilds:
                g = _cm_root().get(str(guild.id), {})
                for uid, state in list(g.get("members", {}).items()):
                    expires = float(state.get("naughty_until", 0))
                    if not expires or expires > time.time():
                        continue
                    member = guild.get_member(int(uid))
                    if member is not None:
                        await _cm_clear_naughty(guild, member)
                    else:
                        state["naughty_until"] = 0
                        state["makeup_actions"] = 0
                        await bd_save_data()
            await asyncio.sleep(300)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Cinnamon Naughty List cleanup stopped unexpectedly")
    finally:
        bot._cm_role_reaper_running = False


@bot.listen("on_ready")
async def _cm_ready():
    if not getattr(bot, "_cm_role_reaper_running", False):
        bot._cm_role_reaper_running = True
        asyncio.create_task(_cm_expire_naughty_roles())


_mood_group = app_commands.Group(name="mood", description="Check and improve Cinnamon's playful server mood")


@_mood_group.command(name="status", description="See Cinnamon's mood, economy bonuses and naughty-list timer")
@app_commands.guild_only()
async def cinnamon_mood_status(interaction: discord.Interaction):
    gid, uid = interaction.guild.id, interaction.user.id
    tier = _cm_tier(gid)
    desc = {"delighted": "😻 Delightfully happy! 10% shop discounts and occasional 25% flash sales; better rare-fish odds.",
            "normal": "🐈 Normal cat operations. Standard shop prices and fishing odds.",
            "grumpy": "😾 GRUMPY! Shop prices +20%; rare fish are slightly less likely."}[tier]
    until = float(_cm_member(gid, uid).get("naughty_until", 0))
    if until > time.time():
        desc += f"\n🐾 Your Naughty List surcharge: **+1,000 Catnip per item** for another **{int((until-time.time())//60)+1} min**. Pet, play and talk, then apologize!"
    else:
        role = discord.utils.get(interaction.guild.roles, name=_CM_NAUGHTY_ROLE)
        if role and role in interaction.user.roles:
            await _cm_clear_naughty(interaction.guild, interaction.user)
    await interaction.response.send_message(desc + "\nUse /mood talk, /mood play, /pet or /economy feed to change her mood.", ephemeral=True)


@_mood_group.command(name="talk", description="Talk to Cinnamon and help her calm down")
@app_commands.guild_only()
async def cinnamon_mood_talk(interaction: discord.Interaction):
    await interaction.response.send_message(await _cm_action(interaction.guild, interaction.user, "talk"), ephemeral=True)


@_mood_group.command(name="play", description="Play with Cinnamon and her beloved toys")
@app_commands.guild_only()
async def cinnamon_mood_play(interaction: discord.Interaction):
    await interaction.response.send_message(await _cm_action(interaction.guild, interaction.user, "toy"), ephemeral=True)


@_mood_group.command(name="apologize", description="Ask Cinnamon to forgive your Naughty List mischief")
@app_commands.guild_only()
async def cinnamon_mood_apologize(interaction: discord.Interaction):
    if not _cm_naughty(interaction.guild.id, interaction.user.id):
        await _cm_clear_naughty(interaction.guild, interaction.user)
        return await interaction.response.send_message("🐈 You're already off the list. Please don't make me regret it.", ephemeral=True)
    st = _cm_member(interaction.guild.id, interaction.user.id)
    if int(st.get("makeup_actions", 0)) < 2:
        return await interaction.response.send_message("😾 TWO good deeds first! Try /pet, /mood play, or /mood talk. No Catnip payment necessary.", ephemeral=True)
    await _cm_clear_naughty(interaction.guild, interaction.user)
    _cm_adjust(interaction.guild.id, 5)
    await bd_save_data()
    await interaction.response.send_message("😻 Apology accepted! You're off the Naughty List. We are best business associates again.", ephemeral=True)


bot.tree.add_command(_mood_group)
