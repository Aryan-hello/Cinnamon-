"""Community interaction features: polls, server events and anonymous confessions."""
import asyncio as _ci_asyncio
import copy as _ci_copy
import datetime as _ci_dt
import time as _ci_time
import uuid as _ci_uuid

_CI_KEY = "cinnamon_community_interactions_v1"
_CI_LOCKS = {}
_CI_VIEWS_READY = False

def _ci_root(gid):
    root = advanced_features_data.setdefault(_CI_KEY, {})
    if not isinstance(root, dict):
        root = advanced_features_data[_CI_KEY] = {}
    cfg = root.setdefault(str(int(gid)), {})
    for key, default in (
        ("events", {}), ("confessions", {}),
        ("confession_channel_id", 0), ("confession_cooldowns", {}),
    ):
        cfg.setdefault(key, _ci_copy.deepcopy(default))
    return cfg

def _ci_lock(gid, key):
    return _CI_LOCKS.setdefault((int(gid), str(key)), _ci_asyncio.Lock())

def _ci_event_embed(record):
    starts = int(record.get("starts_at", 0))
    rsvps = record.get("rsvps", {})
    counts = {kind: sum(1 for value in rsvps.values() if value == kind)
              for kind in ("going", "maybe", "not_going")}
    e = discord.Embed(
        title="📅 " + str(record.get("title", "Community event"))[:240],
        description=(str(record.get("description", ""))[:1500] + "\n\n" if record.get("description") else "")
                    + f"Starts <t:{starts}:F> (<t:{starts}:R>)",
        color=0x91B5A2,
    )
    e.add_field(name="Going", value=str(counts["going"]), inline=True)
    e.add_field(name="Maybe", value=str(counts["maybe"]), inline=True)
    e.add_field(name="Not going", value=str(counts["not_going"]), inline=True)
    e.add_field(name="Status", value=str(record.get("status", "scheduled")).title(), inline=False)
    e.set_footer(text="Cinnamon Events • Update your RSVP with the buttons")
    return e

class CommunityEventView(discord.ui.View):
    def __init__(self, guild_id, event_id, disabled=False):
        super().__init__(timeout=None)
        self.guild_id, self.event_id = int(guild_id), str(event_id)
        for label, value, style in (
            ("Going", "going", discord.ButtonStyle.success),
            ("Maybe", "maybe", discord.ButtonStyle.primary),
            ("Can't go", "not_going", discord.ButtonStyle.secondary),
        ):
            button = discord.ui.Button(
                label=label, style=style,
                custom_id=f"cinnamon:eventrsvp:{self.guild_id}:{self.event_id}:{value}",
                disabled=disabled,
            )
            button.callback = self._make_callback(value)
            self.add_item(button)

    def _make_callback(self, value):
        async def callback(interaction):
            if not interaction.guild or interaction.guild.id != self.guild_id:
                return await interaction.response.send_message("This event belongs to another server.", ephemeral=True)
            async with _ci_lock(self.guild_id, self.event_id):
                cfg = _ci_root(self.guild_id)
                record = cfg["events"].get(self.event_id)
                if not isinstance(record, dict) or record.get("status") != "scheduled":
                    return await interaction.response.send_message("This event is no longer accepting RSVPs.", ephemeral=True)
                before = _ci_copy.deepcopy(record)
                record.setdefault("rsvps", {})[str(interaction.user.id)] = value
                if not await bd_save_data():
                    cfg["events"][self.event_id] = before
                    return await interaction.response.send_message("Couldn't save your RSVP.", ephemeral=True)
                embed = _ci_event_embed(record)
            await interaction.response.edit_message(embed=embed, view=CommunityEventView(
                self.guild_id, self.event_id, disabled=record.get("status") != "scheduled"))
        return callback

event_group = app_commands.Group(name="event", description="Create and manage server events")
community_group.add_command(event_group)

@event_group.command(name="create", description="Create a scheduled event with RSVP buttons")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_events=True)
@app_commands.describe(title="Event name", start_at="ISO date/time with timezone, e.g. 2026-12-01T18:30:00+05:30",
                       description="Optional event details", channel="Where to post the event")
async def community_event_create(interaction: discord.Interaction, title: app_commands.Range[str, 1, 120],
                                 start_at: app_commands.Range[str, 10, 40],
                                 description: str = "", channel: discord.TextChannel | None = None):
    try:
        start = _ci_dt.datetime.fromisoformat(str(start_at).replace("Z", "+00:00"))
    except ValueError:
        return await cinnamon_send(interaction, "Use an ISO date/time including a timezone offset.", ephemeral=True)
    if start.tzinfo is None:
        return await cinnamon_send(interaction, "The event time must include a timezone offset, such as +05:30 or Z.", ephemeral=True)
    starts_at = int(start.astimezone(_ci_dt.timezone.utc).timestamp())
    if starts_at <= int(_ci_time.time()) or starts_at > int(_ci_time.time()) + 366 * 86400:
        return await cinnamon_send(interaction, "Choose a future time within the next 366 days.", ephemeral=True)
    target = channel or interaction.channel
    if not isinstance(target, discord.TextChannel):
        return await cinnamon_send(interaction, "Choose a text channel for the event.", ephemeral=True)
    perms = target.permissions_for(interaction.guild.me)
    if not (perms.view_channel and perms.send_messages and perms.embed_links):
        return await cinnamon_send(interaction, "Cinnamon needs View Channel, Send Messages and Embed Links in that channel.", ephemeral=True)
    event_id = _ci_uuid.uuid4().hex[:8]
    record = {
        "creator_id": int(interaction.user.id), "title": str(title).strip(),
        "description": str(description or "").strip()[:1500], "starts_at": starts_at,
        "channel_id": int(target.id), "rsvps": {}, "status": "scheduled",
        "created_at": int(_ci_time.time()), "reminders_sent": [],
    }
    message = await target.send(
        embed=_ci_event_embed(record),
        view=CommunityEventView(interaction.guild.id, event_id),
        allowed_mentions=discord.AllowedMentions.none(),
    )
    record["message_id"] = int(message.id)
    cfg = _ci_root(interaction.guild.id)
    cfg["events"][event_id] = record
    if not await bd_save_data():
        cfg["events"].pop(event_id, None)
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        return await cinnamon_send(interaction, "Couldn't save the event, so its post was removed.", ephemeral=True)
    await cinnamon_send(interaction, f"Event posted in {target.mention}. Event ID: {event_id}.", ephemeral=True)

@event_group.command(name="list", description="List upcoming server events")
@app_commands.guild_only()
async def community_event_list(interaction: discord.Interaction):
    records = [(eid, r) for eid, r in _ci_root(interaction.guild.id)["events"].items()
               if r.get("status") == "scheduled"]
    records.sort(key=lambda pair: int(pair[1].get("starts_at", 0)))
    lines = [f"**{r.get('title', 'Event')}** — <t:{int(r.get('starts_at', 0))}:F> · ID {eid}"
             for eid, r in records[:15]]
    await cinnamon_send(interaction, "\n".join(lines) or "No upcoming events are scheduled.", ephemeral=True)

@event_group.command(name="cancel", description="Cancel an event you created")
@app_commands.guild_only()
async def community_event_cancel(interaction: discord.Interaction, event_id: str):
    cfg = _ci_root(interaction.guild.id)
    async with _ci_lock(interaction.guild.id, event_id):
        record = cfg["events"].get(str(event_id))
        if not isinstance(record, dict) or record.get("status") != "scheduled":
            return await cinnamon_send(interaction, "That event is not active.", ephemeral=True)
        if int(record.get("creator_id", 0)) != interaction.user.id and not interaction.user.guild_permissions.manage_events:
            return await cinnamon_send(interaction, "Only the event creator or a member with Manage Events can cancel it.", ephemeral=True)
        before = _ci_copy.deepcopy(record)
        record["status"] = "cancelled"
        record["cancelled_at"] = int(_ci_time.time())
        if not await bd_save_data():
            cfg["events"][str(event_id)] = before
            return await cinnamon_send(interaction, "Couldn't save event cancellation.", ephemeral=True)
        channel = interaction.guild.get_channel(int(record.get("channel_id", 0)))
        if channel:
            try:
                message = await channel.fetch_message(int(record.get("message_id", 0)))
                await message.edit(embed=_ci_event_embed(record),
                    view=CommunityEventView(interaction.guild.id, event_id, disabled=True))
            except discord.HTTPException:
                pass
    await cinnamon_send(interaction, "Event cancelled.", ephemeral=True)


@community_group.command(name="confession-settings", description="Configure or disable anonymous confessions")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(channel="Confession channel; omit to disable")
async def community_confession_settings(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    cfg = _ci_root(interaction.guild.id)
    old = int(cfg.get("confession_channel_id", 0) or 0)
    cfg["confession_channel_id"] = int(channel.id) if channel else 0
    if not await bd_save_data():
        cfg["confession_channel_id"] = old
        return await cinnamon_send(interaction, "Couldn't save confession settings.", ephemeral=True)
    await cinnamon_send(interaction,
        "Anonymous confessions will be posted in " + channel.mention + "." if channel else "Anonymous confessions are disabled.",
        ephemeral=True)

class ConfessionModerationView(discord.ui.View):
    def __init__(self, guild_id, confession_id, disabled=False):
        super().__init__(timeout=None)
        self.guild_id, self.confession_id = int(guild_id), str(confession_id)
        button = discord.ui.Button(label="Remove confession", emoji="🛡️",
            style=discord.ButtonStyle.danger,
            custom_id=f"cinnamon:confessionremove:{self.guild_id}:{self.confession_id}",
            disabled=disabled)
        button.callback = self._remove
        self.add_item(button)

    async def _remove(self, interaction):
        if not interaction.guild or interaction.guild.id != self.guild_id or not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Manage Messages permission is required.", ephemeral=True)
        cfg = _ci_root(self.guild_id)
        async with _ci_lock(self.guild_id, self.confession_id):
            record = cfg["confessions"].get(self.confession_id)
            if not isinstance(record, dict) or record.get("status") != "published":
                return await interaction.response.send_message("That confession is no longer active.", ephemeral=True)
            before = _ci_copy.deepcopy(record)
            record["status"] = "removed"
            record["removed_by"] = int(interaction.user.id)
            record["removed_at"] = int(_ci_time.time())
            if not await bd_save_data():
                cfg["confessions"][self.confession_id] = before
                return await interaction.response.send_message("Couldn't save moderation action.", ephemeral=True)
            embed = discord.Embed(title="Confession removed",
                description="A moderator removed this confession.", color=0xD97777)
            await interaction.message.edit(embed=embed, view=ConfessionModerationView(
                self.guild_id, self.confession_id, disabled=True))
        try:
            await send_log(self.guild_id, title="Anonymous confession removed",
                description="A confession was removed by a moderator.",
                category="community", fields=[("Confession ID", self.confession_id),
                                               ("Moderator ID", str(interaction.user.id))])
        except Exception:
            log.exception("Confession moderation audit failed")
        await interaction.response.send_message("Confession removed.", ephemeral=True)

@community_group.command(name="confess", description="Post an anonymous confession to this server's configured channel")
@app_commands.guild_only()
@app_commands.describe(text="Your confession (do not include private contact details)")
async def community_confess(interaction: discord.Interaction, text: app_commands.Range[str, 1, 1500]):
    cfg = _ci_root(interaction.guild.id)
    channel_id = int(cfg.get("confession_channel_id", 0) or 0)
    channel = interaction.guild.get_channel(channel_id) if channel_id else None
    if not isinstance(channel, discord.TextChannel):
        return await cinnamon_send(interaction, "Anonymous confessions are not configured. Ask an administrator to use /confession-settings.", ephemeral=True)
    now = int(_ci_time.time())
    last = int(cfg["confession_cooldowns"].get(str(interaction.user.id), 0))
    if now - last < 300:
        return await cinnamon_send(interaction, f"Please wait {300 - (now - last)} seconds before posting another confession.", ephemeral=True)
    clean = str(text).strip()
    if not clean:
        return await cinnamon_send(interaction, "A confession cannot be empty.", ephemeral=True)
    confession_id = _ci_uuid.uuid4().hex[:8]
    embed = discord.Embed(title="🤫 Anonymous confession", description=clean[:1500],
                          color=0xB8A7D9, timestamp=_ci_dt.datetime.now(_ci_dt.timezone.utc))
    embed.set_footer(text="Cinnamon Confessions • Anonymous to server members")
    message = await channel.send(embed=embed,
        view=ConfessionModerationView(interaction.guild.id, confession_id),
        allowed_mentions=discord.AllowedMentions.none())
    before_cooldown = cfg["confession_cooldowns"].get(str(interaction.user.id))
    cfg["confession_cooldowns"][str(interaction.user.id)] = now
    cfg["confessions"][confession_id] = {
        "author_id": int(interaction.user.id), "channel_id": int(channel.id),
        "message_id": int(message.id), "text": clean[:1500],
        "status": "published", "created_at": now,
    }
    if not await bd_save_data():
        cfg["confessions"].pop(confession_id, None)
        if before_cooldown is None:
            cfg["confession_cooldowns"].pop(str(interaction.user.id), None)
        else:
            cfg["confession_cooldowns"][str(interaction.user.id)] = before_cooldown
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        return await cinnamon_send(interaction, "Couldn't safely save your confession. The post was removed.", ephemeral=True)
    await cinnamon_send(interaction, f"Your confession was posted anonymously in {channel.mention}.", ephemeral=True)

@tasks.loop(minutes=5)
async def _community_event_reminders():
    now = int(_ci_time.time())
    for guild_key, cfg in list(advanced_features_data.get(_CI_KEY, {}).items()):
        if not str(guild_key).isdigit() or not isinstance(cfg, dict):
            continue
        gid = int(guild_key)
        for event_id, record in list((cfg.get("events", {}) or {}).items()):
            if not isinstance(record, dict) or record.get("status") != "scheduled":
                continue
            remaining = int(record.get("starts_at", 0)) - now
            for threshold, label in ((86400, "24-hour"), (3600, "1-hour")):
                sent = record.setdefault("reminders_sent", [])
                if label in sent or not (0 < remaining <= threshold):
                    continue
                channel = bot.get_channel(int(record.get("channel_id", 0)))
                if channel:
                    try:
                        await channel.send(
                            f"⏰ Reminder: **{record.get('title', 'Server event')}** starts <t:{int(record['starts_at'])}:R>.",
                            allowed_mentions=discord.AllowedMentions.none())
                        sent.append(label)
                        await bd_save_data()
                    except discord.HTTPException:
                        log.exception("Community event reminder delivery failed")

@bot.listen("on_ready")
async def _community_interactions_restore():
    global _CI_VIEWS_READY
    if _CI_VIEWS_READY:
        return
    _CI_VIEWS_READY = True
    if not _community_event_reminders.is_running():
        _community_event_reminders.start()
    try:
        for guild_key, cfg in advanced_features_data.get(_CI_KEY, {}).items():
            if not str(guild_key).isdigit() or not isinstance(cfg, dict):
                continue
            gid = int(guild_key)
            for event_id, record in (cfg.get("events", {}) or {}).items():
                if isinstance(record, dict) and record.get("status") == "scheduled":
                    bot.add_view(CommunityEventView(gid, event_id))
            for confession_id, record in (cfg.get("confessions", {}) or {}).items():
                if isinstance(record, dict) and record.get("status") == "published":
                    bot.add_view(ConfessionModerationView(gid, confession_id))
    except Exception:
        log.exception("Could not restore community interaction views")
