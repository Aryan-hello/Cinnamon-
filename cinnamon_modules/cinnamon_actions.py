"""Cinnamon's safe chat-action router.

This is NOT AI tool use. Narrow, anchored phrases are parsed in code, actions
are permission-checked twice, and state-changing moderation needs confirmation.
A playful 1–10 second timeout is opt-in at BOTH server and member level.
"""
import asyncio as _ca_asyncio
import datetime as _ca_datetime
import random as _ca_random
import re as _ca_re

_CA_MENTION = r"<@!?(?P<target_id>\d{15,22})>"
_CA_TARGET = rf"(?:{_CA_MENTION}|(?P<relative>(?:this|that)\s+(?:member|user|person)))"
_CA_TIMEOUT = _ca_re.compile(
    rf"^(?P<verb>mute|timeout|time\s+out)\s+{_CA_TARGET}\s+(?:for\s+)?"
    rf"(?P<quantity>\d{{1,5}})\s*(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)\s*[.!]?\s*$",
    _ca_re.IGNORECASE,
)
_CA_SIMPLE = _ca_re.compile(
    rf"^(?P<verb>unmute|untimeout|remove\s+timeout|kick|ban)\s+{_CA_TARGET}\s*[.!]?\s*$",
    _ca_re.IGNORECASE,
)
_CA_DANGEROUS_INTENT = _ca_re.compile(
    r"^(?:mute|timeout|time\s+out|unmute|untimeout|remove\s+timeout|kick|ban|"
    r"give\s+.*catnip|add\s+.*catnip|remove\s+.*catnip|delete\s+.*channel|"
    r"assign\s+.*role|give\s+.*role|purge\b|lock\s+.*channel)\b", _ca_re.IGNORECASE
)
_CA_LOCKS = {}


def _ca_server(gid):
    return advanced_features_data.setdefault("cinnamon_actions_v1", {}).setdefault(
        str(gid), {"play_enabled": False, "players": {}})


def _ca_user(gid, uid):
    return _ca_server(gid).setdefault("players", {}).setdefault(
        str(uid), {"consent": False})


def _ca_wake_text(text):
    """Remove only leading spoken direct address; mentions are stripped upstream."""
    return _ca_re.sub(
        r"^\s*(?:(?:hey|hi|hello|yo|please)[,! ]+)?cinnamon\s*[,!:.]?\s*",
        "", str(text or ""), count=1, flags=_ca_re.IGNORECASE).strip()


def _ca_seconds(amount, unit):
    q = int(amount)
    unit = unit.lower()
    mult = (1 if unit.startswith("sec") else 60 if unit.startswith("min")
            else 3600 if unit.startswith("h") else 86400)
    seconds = q * mult
    return seconds if 1 <= seconds <= 86400 else None  # 24h cap for chat route


def _ca_permission_reason(guild, actor, target, action):
    """Return a plain-English refusal or None; called before AND after confirm."""
    if not guild or actor.guild.id != guild.id or target.guild.id != guild.id:
        return "This command can only affect a member of this server."
    me = guild.me
    if not me or target.bot or actor.id == target.id or target.id in (guild.owner_id, me.id):
        return "That member is protected from this action."
    actor_p = actor.guild_permissions
    target_p = target.guild_permissions
    admin_only = action in ("kick", "ban")
    if admin_only:
        if not actor_p.administrator:
            return "Only a server Administrator can confirm a kick or ban."
    elif not (actor_p.administrator or actor_p.moderate_members):
        return "You need Timeout Members permission for this request."
    if target_p.administrator or target_p.moderate_members:
        return "Cinnamon won't apply conversational punishments to staff."
    if actor.id != guild.owner_id and target.top_role >= actor.top_role:
        return "You cannot moderate someone with an equal or higher role."
    if target.top_role >= me.top_role:
        return "Move Cinnamon's role above the target before trying this."
    required = ("kick_members" if action == "kick" else
                "ban_members" if action == "ban" else "moderate_members")
    if not getattr(me.guild_permissions, required, False):
        return "Cinnamon needs " + required.replace("_", " ").title() + " permission."
    return None


def _ca_action_label(action, seconds):
    if action == "timeout":
        return "Time out for " + str(seconds // 60) + " minutes" if seconds % 60 == 0 else "Time out for " + str(seconds) + " seconds"
    return {"untimeout": "Remove timeout", "kick": "Kick", "ban": "Ban"}[action]


class _CAConfirm(discord.ui.View):
    def __init__(self, gid, requester_id, target_id, action, seconds):
        super().__init__(timeout=60)
        self.gid, self.requester_id, self.target_id = gid, requester_id, target_id
        self.action, self.seconds = action, seconds
        self.used = False
        self.lock = _ca_asyncio.Lock()

    async def interaction_check(self, interaction):
        if (not interaction.guild or interaction.guild.id != self.gid
                or interaction.user.id != self.requester_id):
            await interaction.response.send_message(
                "🐈 Only the original requesting staff member can confirm.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm action", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        async with self.lock:
            if self.used:
                return await interaction.response.send_message(
                    "This action was already handled.", ephemeral=True)
            guild = interaction.guild
            actor = guild.get_member(self.requester_id)
            target = guild.get_member(self.target_id)
            if not actor or not target:
                return await interaction.response.send_message(
                    "Member not in cache. Please use the slash moderation command.", ephemeral=True)
            problem = _ca_permission_reason(guild, actor, target, self.action)
            if problem:
                return await interaction.response.send_message("⛔ " + problem, ephemeral=True)
            if not 1 <= self.seconds <= 86400 and self.action == "timeout":
                return await interaction.response.send_message("Invalid duration.", ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            try:
                reason = f"Cinnamon delegated moderation: {actor} ({actor.id}); {self.action}; chat confirmation"
                if self.action == "timeout":
                    await target.timeout(_ca_datetime.timedelta(seconds=self.seconds), reason=reason)
                elif self.action == "untimeout":
                    await target.timeout(None, reason=reason)
                elif self.action == "kick":
                    await target.kick(reason=reason)
                elif self.action == "ban":
                    await target.ban(reason=reason, delete_message_seconds=0)
                else:
                    raise ValueError("Disallowed action")
            except (discord.Forbidden, discord.HTTPException) as exc:
                return await interaction.followup.send(
                    "❌ Discord refused the action. Check role hierarchy and bot permissions.", ephemeral=True)
            self.used = True
            self.stop()
            label = _ca_action_label(self.action, self.seconds)
            try:
                await interaction.message.edit(content=(
                    f"✅ Cinnamon completed **{label}** on <@{target.id}> "
                    f"**on behalf of {actor.display_name}**. Recorded in moderation logs."
                ), embed=None, view=None, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass
            await send_log(guild.id, title="🛡️ Cinnamon delegated moderation",
                category="moderation", fields=[
                    ("Staff member", f"{actor} ({actor.id})"),
                    ("Target", f"{target} ({target.id})"),
                    ("Confirmed action", label),
                    ("Source", "Directly invited Cinnamon in server chat"),
                    ("Status", "Discord API accepted")])
            await interaction.followup.send("✅ Executed and logged under your staff name.", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled. No action taken.",embed=None,view=None)


async def _ca_maybe_handle(message, clean_content):
    """Only handle an exact recognized moderator instruction; never invoke Gemini tools."""
    if not message.guild or not isinstance(message.author, discord.Member):
        return False
    text = _ca_wake_text(clean_content)
    result = _CA_TIMEOUT.fullmatch(text) or _CA_SIMPLE.fullmatch(text)
    if not result:
        if _CA_DANGEROUS_INTENT.match(text):
            await message.reply(
                "🛡️ For safety, I only accept exact timeout/unmute instructions in chat. "
                "Kick/ban need an Administrator, a named member, and confirmation. "
                "For other powerful changes, use the existing slash command with its proper permissions.",
                mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            return True
        return False
    action = result.group("verb").lower().replace(" ", "")
    action = ("timeout" if action in ("mute", "timeout") else
              "untimeout" if action in ("unmute", "untimeout", "removetimeout") else action)
    ids = [m.id for m in message.mentions if m.id != bot.user.id] if bot.user else [m.id for m in message.mentions]
    raw = result.group("target_id")
    if raw:
        target_id = int(raw)
        if len(set(ids)) != 1 or target_id not in ids:
            await message.reply("Please mention exactly one target member.",
                                mention_author=False,allowed_mentions=discord.AllowedMentions.none())
            return True
    else:
        # "this member" must be a reply to that member's message, NOT a guess.
        ref = message.reference.resolved if message.reference else None
        if ref is None and message.reference and message.reference.message_id:
            try:
                ref = await message.channel.fetch_message(message.reference.message_id)
            except discord.HTTPException:
                ref = None
        if not isinstance(ref, discord.Message) or ref.author.bot:
            await message.reply("Reply to that person's message and ping Cinnamon, "
                                "or mention the target explicitly.",mention_author=False,
                                allowed_mentions=discord.AllowedMentions.none())
            return True
        target_id = ref.author.id
    target = message.guild.get_member(target_id)
    if not target:
        await message.reply("I can't find that member in this server.", mention_author=False,
                            allowed_mentions=discord.AllowedMentions.none())
        return True
    seconds = 0
    if action == "timeout":
        seconds = _ca_seconds(result.group("quantity"), result.group("unit"))
        if seconds is None:
            await message.reply("Chat timeout duration must be 1 second–24 hours. "
                                "Use /mute for longer authorized timeouts.",
                mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            return True
    problem = _ca_permission_reason(message.guild, message.author, target, action)
    if problem:
        await message.reply("⛔ " + problem, mention_author=False,
                            allowed_mentions=discord.AllowedMentions.none())
        return True
    label = _ca_action_label(action, seconds)
    card = discord.Embed(title="🛡️ Cinnamon · Staff confirmation",
                         description="**Action:** " + label + "\n"
                          "**Target:** " + target.display_name + " (" + str(target.id) + ")\n"
                          "**Requested by:** " + message.author.display_name + "\n\n"
                          "**No action happens until YOU click Confirm.**",
                         color=0xD97732)
    card.set_footer(text="This confirmation expires after 60 seconds • Recheck permissions on click")
    await message.reply(embed=card,view=_CAConfirm(message.guild.id,message.author.id,
        target.id,action,seconds),mention_author=False,
        allowed_mentions=discord.AllowedMentions.none())
    return True


async def _ca_maybe_prank(message):
    """Opt-in tiny timeout: <=1 per member per UTC day, at most 10 seconds."""
    if not message.guild or not isinstance(message.author, discord.Member):
        return False
    gid, member = message.guild.id, message.author
    server = _ca_server(gid)
    rec = _ca_user(gid, member.id)
    if not server.get("play_enabled", False) or not rec.get("consent", False):
        return False
    if _ca_random.random() >= 0.015:
        return False
    key = (gid, member.id)
    lock = _CA_LOCKS.setdefault(key, _ca_asyncio.Lock())
    async with lock:
        utcnow = _ca_datetime.datetime.now(_ca_datetime.timezone.utc)
        if rec.get("last_play_day") == utcnow.date().isoformat():
            return False
        me = message.guild.me
        if (not me or not me.guild_permissions.moderate_members
                or member.id == message.guild.owner_id
                or member.guild_permissions.administrator
                or member.guild_permissions.moderate_members
                or member.top_role >= me.top_role):
            return False
        if member.timed_out_until and member.timed_out_until > utcnow:
            return False
        seconds = _ca_random.randint(1, 10)
        try:
            await member.timeout(_ca_datetime.timedelta(seconds=seconds),
                reason="Cinnamon consensual mini-prank; member opted in; once per UTC day")
        except (discord.Forbidden, discord.HTTPException):
            return False
        rec["last_play_day"] = utcnow.date().isoformat()
        await bd_save_data()
        await send_log(gid,title="🐈 Consensual Cinnamon prank timeout",category="mood",
            fields=[("Member",f"{member} ({member.id})"),
                    ("Seconds",str(seconds)),("Consent","Member opted in; staff opted in server"),
                    ("Daily count","1 / UTC day")])
    await message.reply(
        f"😼 COURT OF CAT LAW! A tiny **{seconds}-second** nap sentence! "
        "You opted into my jokes, so this counts as today's one little prank. 🐾",
        mention_author=False,allowed_mentions=discord.AllowedMentions.none())
    return True


_ca_group = app_commands.Group(name="cinnamon-prank",description="Manage Cinnamon's opt-in tiny timeouts")


@_ca_group.command(name="consent",description="Allow or refuse Cinnamon's once-a-day 1–10 second joke")
@app_commands.guild_only()
async def cinnamon_prank_consent(interaction: discord.Interaction, enabled: bool):
    rec = _ca_user(interaction.guild.id, interaction.user.id)
    rec["consent"] = bool(enabled)
    await bd_save_data()
    await interaction.response.send_message(
        ("🐈 You opted in. Cinnamon might play ONE 1–10 second timeout joke per UTC day when you call her."
         if enabled else "🔒 Opted out. Cinnamon won't play timeout jokes on you."),
        ephemeral=True)


@_ca_group.command(name="enable",description="Admin: enable or disable consent-based timeout jokes for this server")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def cinnamon_prank_enable(interaction: discord.Interaction, enabled: bool):
    _ca_server(interaction.guild.id)["play_enabled"] = bool(enabled)
    await bd_save_data()
    await send_log(interaction.guild.id,title="🐈 Cinnamon prank config",category="mood",
        fields=[("Administrator",f"{interaction.user} ({interaction.user.id})"),
                ("Enabled",str(bool(enabled)))])
    await interaction.response.send_message(
        "🐈 Playful 1–10 second timeouts " + ("enabled" if enabled else "disabled") +
        ". Members must personally opt in; staff, owners and already-timed-out people are protected.",
        ephemeral=True)


@_ca_group.command(name="status",description="See whether Cinnamon's tiny timeouts are available to you")
@app_commands.guild_only()
async def cinnamon_prank_status(interaction: discord.Interaction):
    server = _ca_server(interaction.guild.id)
    member = _ca_user(interaction.guild.id,interaction.user.id)
    today = _ca_datetime.datetime.now(_ca_datetime.timezone.utc).date().isoformat()
    await interaction.response.send_message(
        f"🐈 Server enabled: **{bool(server.get('play_enabled',False))}**\n"
        f"Your consent: **{bool(member.get('consent',False))}**\n"
        f"Prank already used today: **{member.get('last_play_day')==today}**\n"
        "One per UTC day, 1–10 seconds, only when you invite Cinnamon.",
        ephemeral=True)


bot.tree.add_command(_ca_group)
