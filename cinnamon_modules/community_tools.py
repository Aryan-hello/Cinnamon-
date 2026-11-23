"""Suggestion board and starboard additions for Cinnamon."""
import asyncio
import datetime as _ct

_CT_KEY = "cinnamon_community_tools_v1"
_CT_LOCKS = {}
_CT_VIEWS_READY = False

def _ct_root(guild_id):
    return advanced_features_data.setdefault(_CT_KEY, {}).setdefault(str(int(guild_id)), {
        "suggestion_channel_id": 0, "starboard_channel_id": 0,
        "starboard_threshold": 3, "starboard_emoji": "⭐",
        "suggestions": {}, "starboard_posts": {},
    })

def _ct_lock(guild_id, message_id):
    return _CT_LOCKS.setdefault((int(guild_id), int(message_id)), asyncio.Lock())

def _ct_embed(guild, author, text, status="Pending"):
    colors = {"Pending": 0xE6A04B, "Approved": 0x69A982, "Declined": 0xD97777}
    e = discord.Embed(title="💡 Community suggestion", description=str(text)[:1000],
                      color=colors.get(status, 0xE6A04B),
                      timestamp=_ct.datetime.now(_ct.timezone.utc))
    e.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    e.add_field(name="Status", value="**" + status + "**", inline=True)
    e.set_footer(text="Cinnamon Suggestions • " + guild.name)
    return e

class _CTSuggestionView(discord.ui.View):
    def __init__(self, guild_id, message_id, disabled=False):
        super().__init__(timeout=None)
        self.guild_id, self.message_id = int(guild_id), int(message_id)
        for action, label, style in (
            ("approve", "Approve", discord.ButtonStyle.success),
            ("decline", "Decline", discord.ButtonStyle.danger),
        ):
            button = discord.ui.Button(label=label, style=style,
                custom_id="cinnamon:suggestion:" + action + ":" + str(self.message_id),
                disabled=disabled)
            button.callback = self._callback(action)
            self.add_item(button)

    def _callback(self, action):
        async def run(interaction):
            if (not interaction.guild or interaction.guild.id != self.guild_id
                    or not interaction.user.guild_permissions.manage_messages):
                return await interaction.response.send_message(
                    "Manage Messages permission is required to review suggestions.", ephemeral=True)
            async with _ct_lock(self.guild_id, self.message_id):
                root = _ct_root(self.guild_id)
                record = root["suggestions"].get(str(self.message_id))
                if not isinstance(record, dict):
                    return await interaction.response.send_message("Suggestion record not found.", ephemeral=True)
                if record.get("status") != "Pending":
                    return await interaction.response.send_message("This suggestion has already been reviewed.", ephemeral=True)
                status = "Approved" if action == "approve" else "Declined"
                record["status"] = status
                record["reviewed_by"] = int(interaction.user.id)
                record["reviewed_at"] = int(_ct.datetime.now(_ct.timezone.utc).timestamp())
                if not await bd_save_data():
                    record["status"] = "Pending"
                    record.pop("reviewed_by", None)
                    record.pop("reviewed_at", None)
                    return await interaction.response.send_message("Couldn't save the decision; no change was made.", ephemeral=True)
                author = interaction.guild.get_member(int(record.get("author_id", 0))) or interaction.user
                embed = _ct_embed(interaction.guild, author, record.get("text", ""), status)
                embed.add_field(name="Reviewed by", value=interaction.user.mention, inline=True)
                await interaction.message.edit(embed=embed, view=_CTSuggestionView(
                    self.guild_id, self.message_id, disabled=True))
            await interaction.response.send_message("Suggestion marked " + status.lower() + ".", ephemeral=True)
            try:
                await send_log(self.guild_id, title="Suggestion " + status.lower(),
                    description="Suggestion message ID: " + str(self.message_id),
                    category="community",
                    fields=[("Author ID", str(record.get("author_id", ""))),
                            ("Reviewer", str(interaction.user.id))])
            except Exception:
                log.exception("Suggestion audit logging failed")
        return run

@bot.tree.command(name="suggest", description="Send an idea to this server's suggestion board")
@app_commands.guild_only()
@app_commands.describe(suggestion="Describe one clear idea for the server")
async def _ct_suggest(interaction: discord.Interaction, suggestion: app_commands.Range[str, 1, 1000]):
    root = _ct_root(interaction.guild.id)
    channel = interaction.guild.get_channel(int(root.get("suggestion_channel_id", 0) or 0))
    if not isinstance(channel, discord.TextChannel):
        return await cinnamon_send(interaction, "The suggestion board is not configured. Ask an administrator to use /suggestion-settings.", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        message = await channel.send(embed=_ct_embed(interaction.guild, interaction.user, suggestion),
            allowed_mentions=discord.AllowedMentions.none())
        record = {"channel_id": int(channel.id), "author_id": int(interaction.user.id),
                  "text": str(suggestion)[:1000], "status": "Pending",
                  "created_at": int(_ct.datetime.now(_ct.timezone.utc).timestamp())}
        root["suggestions"][str(message.id)] = record
        if not await bd_save_data():
            root["suggestions"].pop(str(message.id), None)
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return await interaction.followup.send("Couldn't save the suggestion, so the post was removed.", ephemeral=True)
        await message.edit(view=_CTSuggestionView(interaction.guild.id, message.id))
        await interaction.followup.send("Your suggestion was posted in " + channel.mention + ".", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("Cinnamon needs permission to send messages in the suggestion channel.", ephemeral=True)
    except discord.HTTPException:
        log.exception("Suggestion publish failed")
        await interaction.followup.send("Discord couldn't publish the suggestion. Try again later.", ephemeral=True)

@bot.tree.command(name="suggestion-settings", description="Set or disable the suggestion board")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(channel="Suggestion channel; omit to disable")
async def _ct_suggestion_settings(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    root = _ct_root(interaction.guild.id)
    old = root.get("suggestion_channel_id", 0)
    root["suggestion_channel_id"] = int(channel.id) if channel else 0
    if not await bd_save_data():
        root["suggestion_channel_id"] = old
        return await cinnamon_send(interaction, "Couldn't save the suggestion setting.", ephemeral=True)
    await cinnamon_send(interaction,
        "Suggestion board set to " + channel.mention + "." if channel else "Suggestion board disabled.",
        ephemeral=True)

@bot.tree.command(name="starboard-settings", description="Set or disable the server starboard")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(channel="Starboard channel; omit to disable", threshold="Required reactions, 2–20", emoji="Reaction to count")
async def _ct_starboard_settings(interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        threshold: app_commands.Range[int, 2, 20] = 3,
        emoji: app_commands.Range[str, 1, 20] = "⭐"):
    root = _ct_root(interaction.guild.id)
    old = (root.get("starboard_channel_id", 0), root.get("starboard_threshold", 3), root.get("starboard_emoji", "⭐"))
    root["starboard_channel_id"] = int(channel.id) if channel else 0
    root["starboard_threshold"], root["starboard_emoji"] = int(threshold), str(emoji)
    if not await bd_save_data():
        root["starboard_channel_id"], root["starboard_threshold"], root["starboard_emoji"] = old
        return await cinnamon_send(interaction, "Couldn't save starboard settings.", ephemeral=True)
    await cinnamon_send(interaction,
        "Starboard enabled in " + channel.mention + " (" + str(threshold) + "× " + str(emoji) + ")."
        if channel else "Starboard disabled.", ephemeral=True)

@bot.listen("on_raw_reaction_add")
async def _ct_starboard_reaction(payload):
    if not payload.guild_id or not bot.user or payload.user_id == bot.user.id:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    root = _ct_root(guild.id)
    starboard_id = int(root.get("starboard_channel_id", 0) or 0)
    emoji = str(root.get("starboard_emoji", "⭐"))
    if not starboard_id or int(payload.channel_id) == starboard_id or str(payload.emoji) != emoji:
        return
    source = guild.get_channel(int(payload.channel_id))
    target = guild.get_channel(starboard_id)
    if not isinstance(source, discord.TextChannel) or not isinstance(target, discord.TextChannel):
        return
    async with _ct_lock(guild.id, payload.message_id):
        key = str(payload.message_id)
        if key in root["starboard_posts"]:
            return
        try:
            message = await source.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        if message.author.bot:
            return
        count = next((int(r.count) for r in message.reactions if str(r.emoji) == emoji), 0)
        if count < int(root.get("starboard_threshold", 3)):
            return
        embed = discord.Embed(description=message.content[:3500] or "*No text content*",
            color=0xE6B84A, timestamp=message.created_at)
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.add_field(name="Source", value="[Jump to message](" + message.jump_url + ")", inline=True)
        embed.add_field(name="Stars", value=emoji + " **" + str(count) + "**", inline=True)
        if message.attachments:
            image_url = next((a.url for a in message.attachments
                if a.content_type and a.content_type.startswith("image/")), None)
            if image_url:
                embed.set_image(url=image_url)
        try:
            posted = await target.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            return
        root["starboard_posts"][key] = {"channel_id": int(target.id), "message_id": int(posted.id)}
        if not await bd_save_data():
            root["starboard_posts"].pop(key, None)
            try:
                await posted.delete()
            except discord.HTTPException:
                pass

@bot.listen("on_ready")
async def _ct_restore_views():
    global _CT_VIEWS_READY
    if _CT_VIEWS_READY:
        return
    _CT_VIEWS_READY = True
    try:
        registered = 0
        for guild_id, data in advanced_features_data.get(_CT_KEY, {}).items():
            if not str(guild_id).isdigit() or not isinstance(data, dict):
                continue
            records = list(data.get("suggestions", {}).items())[-1000:]
            for message_id, record in records:
                if isinstance(record, dict) and record.get("status") == "Pending":
                    bot.add_view(_CTSuggestionView(int(guild_id), int(message_id)))
                    registered += 1
        log.info("Restored %s suggestion review views", registered)
    except Exception:
        log.exception("Suggestion view restoration failed")
