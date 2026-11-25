"""Interactive giveaway setup layered on Cinnamon's existing giveaway engine.

The existing storage schema, entry view, eligibility checks, weighted tickets,
finish loop, history, recurring schedules and templates remain authoritative.
"""
import re as _gw_re
import time as _gw_time

# The interactive wizard is the sole registered /giveaway create command.

_GW_DEFAULTS = {
    "prize":"", "duration_minutes":"60", "winners":"1", "channel_id":"",
    "required_roles":"", "blacklisted_roles":"", "bypass_roles":"",
    "min_account_age_days":"0", "min_server_age_days":"0", "bonus_roles":"",
    "embed_title":"", "embed_description":"", "embed_color":"E89A3C",
    "entry_emoji":"🎉", "winner_role_id":"", "winner_role_minutes":"0",
    "winner_thread_minutes":"0", "claim_minutes":"0", "reaction_entries":"no",
    "entry_message":"", "leave_message":"", "denied_message":"",
}

_GW_SECTIONS = {
    "basic":("Basic setup",[
        ("prize","Prize",discord.TextStyle.short,True,200),
        ("duration_minutes","Duration in minutes",discord.TextStyle.short,True,7),
        ("winners","Number of winners",discord.TextStyle.short,True,3),
        ("channel_id","Channel ID or mention (blank = current)",discord.TextStyle.short,False,100),
    ]),
    "eligibility":("Eligibility rules",[
        ("required_roles","Required role mentions (one per line)",discord.TextStyle.paragraph,False,1000),
        ("blacklisted_roles","Excluded role mentions (one per line)",discord.TextStyle.paragraph,False,1000),
        ("bypass_roles","Bypass role mentions (one per line)",discord.TextStyle.paragraph,False,1000),
        ("min_account_age_days","Minimum account age in days",discord.TextStyle.short,False,5),
        ("min_server_age_days","Minimum server membership in days",discord.TextStyle.short,False,5),
    ]),
    "bonus":("Bonus entries",[
        ("bonus_roles","One @Role:EXTRA_ENTRIES per line",discord.TextStyle.paragraph,False,1000),
    ]),
    "appearance":("Appearance",[
        ("embed_title","Embed title",discord.TextStyle.short,False,256),
        ("embed_description","Embed description",discord.TextStyle.paragraph,False,1800),
        ("embed_color","Embed colour (hex, no #)",discord.TextStyle.short,False,6),
        ("entry_emoji","Entry button emoji",discord.TextStyle.short,False,40),
    ]),
    "advanced":("Advanced options",[
        ("winner_role_id","Winner role mention (blank = none)",discord.TextStyle.short,False,100),
        ("winner_role_minutes","Winner role duration in minutes (0 = permanent)",discord.TextStyle.short,False,7),
        ("winner_thread_minutes","Winner thread duration in minutes (0 = disabled)",discord.TextStyle.short,False,7),
        ("claim_minutes","Prize claim window in minutes (0 = disabled)",discord.TextStyle.short,False,7),
        ("reaction_entries","Enable reaction entries? yes/no",discord.TextStyle.short,False,5),
    ]),
    "messages":("Entry messages",[
        ("entry_message","Message shown after entering",discord.TextStyle.paragraph,False,300),
        ("leave_message","Message shown after leaving",discord.TextStyle.paragraph,False,300),
        ("denied_message","Eligibility denial message",discord.TextStyle.paragraph,False,300),
    ]),
}

def _gw_clean_role_id(value):
    return _gw_re.sub(r"[<@&#>\s]", "", str(value or "")).strip()

def _gw_duration_label(minutes):
    minutes=int(minutes)
    days, rem=divmod(minutes,1440)
    hours, mins=divmod(rem,60)
    return (f"{days}d " if days else "")+(f"{hours}h " if hours else "")+(f"{mins}m" if mins or not (days or hours) else "")

def _gw_draft_from_existing(gw):
    draft=dict(_GW_DEFAULTS)
    draft.update({
        "prize":str(gw.get("prize","")),
        "duration_minutes":str(max(1,int((float(gw.get("ends_at",_gw_time.time()+3600))-_gw_time.time())/60))),
        "winners":str(gw.get("winners",1)),
        "channel_id":str(gw.get("channel_id","")),
        "required_roles":"\n".join(f"<@&{x}>" for x in gw.get("required_roles",[])),
        "blacklisted_roles":"\n".join(f"<@&{x}>" for x in gw.get("blacklisted_roles",[])),
        "bypass_roles":"\n".join(f"<@&{x}>" for x in gw.get("bypass_roles",[])),
        "min_account_age_days":str(gw.get("min_account_age_days",0)),
        "min_server_age_days":str(gw.get("min_server_age_days",0)),
        "bonus_roles":"\n".join(f"<@&{k}>:{v}" for k,v in (gw.get("bonus_roles",{}) or {}).items()),
        "embed_title":str(gw.get("embed_title","")),
        "embed_description":str(gw.get("embed_description","")),
        "embed_color":str(gw.get("embed_color","E89A3C")),
        "entry_emoji":str(gw.get("entry_emoji","🎉")),
        "winner_role_id":(f"<@&{gw.get('winner_role_id')}>" if str(gw.get("winner_role_id","")).isdigit() else ""),
        "winner_role_minutes":str(gw.get("winner_role_minutes",0)),
        "winner_thread_minutes":str(gw.get("winner_thread_minutes",0)),
        "claim_minutes":str(gw.get("claim_minutes",0)),
        "reaction_entries":"yes" if gw.get("reaction_entries") else "no",
        "entry_message":str(gw.get("entry_message","")),
        "leave_message":str(gw.get("leave_message","")),
        "denied_message":str(gw.get("denied_message","")),
    })
    return draft

class GiveawayWizardModal(discord.ui.Modal):
    def __init__(self, wizard, section):
        title, definitions=_GW_SECTIONS[section]
        super().__init__(title=f"Giveaway • {title}",timeout=300)
        self.wizard=wizard
        self.section=section
        self.inputs={}
        for key,label,style,required,max_length in definitions:
            value=str(wizard.draft.get(key,""))
            field=discord.ui.TextInput(
                label=label, style=style, required=required,
                default=value if value else None, max_length=max_length,
            )
            self.inputs[key]=field
            self.add_item(field)

    async def on_submit(self, interaction):
        if interaction.user.id!=self.wizard.owner_id:
            return await interaction.response.send_message("Only the person who opened this setup can edit it.",ephemeral=True)
        for key,field in self.inputs.items():
            self.wizard.draft[key]=str(field.value or "").strip()
        embed=self.wizard.render()
        if interaction.message:
            await interaction.response.edit_message(embed=embed,view=self.wizard)
        else:
            await interaction.response.send_message(embed=embed,view=self.wizard,ephemeral=True)

class GiveawayWizardView(discord.ui.View):
    def __init__(self,owner_id,draft=None,edit_message_id=None):
        super().__init__(timeout=900)
        self.owner_id=int(owner_id)
        self.draft=dict(_GW_DEFAULTS)
        if draft: self.draft.update(draft)
        self.edit_message_id=int(edit_message_id) if edit_message_id else None

    def render(self):
        d=self.draft
        embed=discord.Embed(
            title="🎉 Giveaway setup" if not self.edit_message_id else "🛠️ Edit giveaway",
            description="Choose a section to configure it, then preview and publish. Nothing is posted until you press Publish.",
            color=0xE89A3C,
        )
        embed.add_field(name="Prize",value=str(d.get("prize") or "Not set")[:200],inline=False)
        embed.add_field(name="Duration / winners",value=f"{d.get('duration_minutes','60')} minutes · {d.get('winners','1')} winner(s)",inline=True)
        embed.add_field(name="Channel",value=f"<#{d.get('channel_id')}>" if str(d.get("channel_id","")).isdigit() else "Current channel",inline=True)
        role_count=sum(1 for line in str(d.get("bonus_roles","")).splitlines() if line.strip())
        embed.add_field(name="Eligibility / bonus",value=f"{len([x for x in str(d.get('required_roles','')).splitlines() if x.strip()])} required role(s) · {len([x for x in str(d.get('blacklisted_roles','')).splitlines() if x.strip()])} excluded · {role_count} bonus role(s)",inline=False)
        embed.add_field(name="Appearance",value=f"Title: {d.get('embed_title') or 'Default'} · Emoji: {d.get('entry_emoji') or '🎉'} · Colour: {d.get('embed_color') or 'E89A3C'}",inline=False)
        embed.add_field(name="Advanced",value=f"Claim window: {d.get('claim_minutes','0')} min · Winner role: {d.get('winner_role_id') or 'None'} · Reaction entries: {d.get('reaction_entries','no')}",inline=False)
        embed.set_footer(text="Cinnamon Giveaways • Orange & gold setup")
        return embed

    async def _open_section(self,interaction,section):
        if interaction.user.id!=self.owner_id:
            return await interaction.response.send_message("This giveaway setup belongs to another member.",ephemeral=True)
        await interaction.response.send_modal(GiveawayWizardModal(self,section))

    @discord.ui.button(label="Basic",style=discord.ButtonStyle.primary,row=0)
    async def basic(self,interaction,button):
        await self._open_section(interaction,"basic")

    @discord.ui.button(label="Eligibility",style=discord.ButtonStyle.secondary,row=0)
    async def eligibility(self,interaction,button):
        await self._open_section(interaction,"eligibility")

    @discord.ui.button(label="Bonus entries",style=discord.ButtonStyle.secondary,row=0)
    async def bonus(self,interaction,button):
        await self._open_section(interaction,"bonus")

    @discord.ui.button(label="Appearance",style=discord.ButtonStyle.secondary,row=0)
    async def appearance(self,interaction,button):
        await self._open_section(interaction,"appearance")

    @discord.ui.button(label="Advanced",style=discord.ButtonStyle.secondary,row=0)
    async def advanced(self,interaction,button):
        await self._open_section(interaction,"advanced")

    @discord.ui.button(label="Messages",style=discord.ButtonStyle.secondary,row=1)
    async def messages(self,interaction,button):
        await self._open_section(interaction,"messages")

    @discord.ui.button(label="Preview",style=discord.ButtonStyle.secondary,row=1)
    async def preview(self,interaction,button):
        if interaction.user.id!=self.owner_id:
            return await interaction.response.send_message("This giveaway setup belongs to another member.",ephemeral=True)
        d=self.draft
        preview=discord.Embed(
            title=str(d.get("embed_title") or "🎉 Giveaway")[:256],
            description=(str(d.get("embed_description") or "")+"\n\n" if d.get("embed_description") else "")+
                        f"**Prize:** {str(d.get('prize') or 'Not set')[:200]}\n**Winners:** {d.get('winners','1')}\n**Duration:** {d.get('duration_minutes','60')} minutes",
            color=0xE89A3C,
        )
        preview.add_field(name="Entry",value=f"Button emoji: {d.get('entry_emoji') or '🎉'} · Reaction entries: {d.get('reaction_entries','no')}",inline=False)
        await interaction.response.send_message(content="Preview only — this has not been published.",embed=preview,ephemeral=True)

    @discord.ui.button(label="Publish giveaway",style=discord.ButtonStyle.success,row=1)
    async def publish(self,interaction,button):
        if interaction.user.id!=self.owner_id:
            return await interaction.response.send_message("This giveaway setup belongs to another member.",ephemeral=True)
        await _gw_publish(interaction,self)

async def _gw_publish(interaction,wizard):
    if not _giveaway_role_gate(interaction):
        return await cinnamon_send(interaction, "You no longer have permission to publish giveaways in this server.", ephemeral=True)
    d=wizard.draft
    try:
        prize=str(d.get("prize","")).strip()
        duration=int(d.get("duration_minutes","60"))
        winners=int(d.get("winners","1"))
        claim_minutes=int(d.get("claim_minutes","0") or 0)
        if not 1<=len(prize)<=200: raise ValueError("Prize must be 1–200 characters.")
        if not 1<=duration<=525600: raise ValueError("Duration must be between 1 and 525,600 minutes.")
        if not 1<=winners<=100: raise ValueError("Winners must be between 1 and 100.")
        if not 0<=claim_minutes<=10080: raise ValueError("Claim window must be between 0 and 10,080 minutes.")
        channel_raw=str(d.get("channel_id","")).strip()
        channel_id=int(_gw_clean_role_id(channel_raw)) if channel_raw else int(interaction.channel.id)
        channel=interaction.guild.get_channel(channel_id)
        if not isinstance(channel,discord.TextChannel):
            raise ValueError("Choose a text channel in this server. You can paste its channel ID or mention.")
        perms=channel.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.embed_links:
            raise ValueError("Cinnamon needs Send Messages and Embed Links in the selected channel.")
        config=_validate_giveaway_config(
            interaction.guild,
            bonus_roles=str(d.get("bonus_roles","")),
            required_roles=str(d.get("required_roles","")),
            bypass_roles=str(d.get("bypass_roles","")),
            blacklisted_roles=str(d.get("blacklisted_roles","")),
            min_account_age_days=int(d.get("min_account_age_days","0") or 0),
            min_server_age_days=int(d.get("min_server_age_days","0") or 0),
            winner_role_id=_gw_clean_role_id(d.get("winner_role_id","")),
            winner_role_minutes=int(d.get("winner_role_minutes","0") or 0),
            winner_thread_minutes=int(d.get("winner_thread_minutes","0") or 0),
            embed_color=str(d.get("embed_color","E89A3C") or "E89A3C"),
            entry_emoji=str(d.get("entry_emoji","🎉") or "🎉"),
            reaction_entries=str(d.get("reaction_entries","no")).lower() in {"yes","true","on","1"},
        )
        config.update({
            "claim_minutes":claim_minutes,
            "embed_title":str(d.get("embed_title",""))[:256],
            "embed_description":str(d.get("embed_description",""))[:4000],
            "entry_message":str(d.get("entry_message",""))[:300],
            "leave_message":str(d.get("leave_message",""))[:300],
            "denied_message":str(d.get("denied_message",""))[:300],
        })
        if wizard.edit_message_id:
            mid=wizard.edit_message_id
            gw=active_giveaways.get(mid)
            if not gw or int(gw.get("guild_id",0))!=interaction.guild.id:
                raise ValueError("That active giveaway is no longer available to edit.")
            if channel.id!=int(gw.get("channel_id",0)):
                raise ValueError("An existing giveaway cannot be moved to another channel.")
            old=dict(gw)
            gw.update(config)
            gw.update({"prize":prize,"winners":winners,"ends_at":_gw_time.time()+duration*60})
            message=await channel.fetch_message(mid)
            await message.edit(embed=_giveaway_embed(gw),view=GiveawayView(emoji=gw.get("entry_emoji")))
            if gw.get("reaction_entries"):
                try: await message.add_reaction(_giveaway_emoji(gw.get("entry_emoji") or "🎉"))
                except discord.HTTPException: pass
            if not await bd_save_data():
                gw.clear()
                gw.update(old)
                await message.edit(embed=_giveaway_embed(gw),view=GiveawayView(emoji=gw.get("entry_emoji")))
                raise ValueError("The edit could not be saved; the previous giveaway settings were restored.")
            action="updated"
        else:
            mid=await _create_giveaway(
                guild_id=interaction.guild.id,channel_id=channel.id,host_id=interaction.user.id,
                prize=prize,winners=winners,duration_minutes=duration,config=config,
            )
            action="started"
        await send_log(
            interaction.guild.id,title="🎉 Giveaway "+action,interaction=interaction,category="community",
            fields=[("Message",str(mid)),("Prize",prize),("Duration",_gw_duration_label(duration)),
                    ("Winners",str(winners)),("Bonus roles",str(len(config.get("bonus_roles",{})))),
                    ("Required roles",str(len(config.get("required_roles",[]))))],
        )
        wizard.stop()
        await interaction.response.send_message(
            f"🎉 Giveaway {action} successfully in {channel.mention}. Message ID: {mid}.",
            ephemeral=True,allowed_mentions=discord.AllowedMentions.none(),
        )
    except (ValueError,TypeError,discord.HTTPException) as exc:
        await interaction.response.send_message(f"Couldn't publish the giveaway: {exc}",ephemeral=True)

@giveaway_group.command(name="create",description="Open the interactive giveaway setup")
@app_commands.guild_only()
@app_commands.check(_giveaway_role_gate)
async def giveaway_create_wizard(interaction:discord.Interaction):
    draft=dict(_GW_DEFAULTS)
    draft["channel_id"]=str(interaction.channel.id)
    view=GiveawayWizardView(interaction.user.id,draft)
    await interaction.response.send_message(embed=view.render(),view=view,ephemeral=True)

@giveaway_group.command(name="edit",description="Edit an active giveaway using the setup wizard")
@app_commands.describe(message_id="The active giveaway message ID")
@app_commands.guild_only()
@app_commands.check(_giveaway_role_gate)
async def giveaway_edit_wizard(interaction:discord.Interaction,message_id:str):
    if not str(message_id).isdigit():
        return await cinnamon_send(interaction,"Enter the numeric giveaway message ID.",ephemeral=True)
    mid=int(message_id)
    gw=active_giveaways.get(mid)
    if not gw or int(gw.get("guild_id",0))!=interaction.guild.id:
        return await cinnamon_send(interaction,"No active giveaway with that message ID was found in this server.",ephemeral=True)
    view=GiveawayWizardView(interaction.user.id,_gw_draft_from_existing(gw),edit_message_id=mid)
    await interaction.response.send_message(embed=view.render(),view=view,ephemeral=True)

@giveaway_group.command(name="cancel",description="Cancel an active giveaway without choosing winners")
@app_commands.describe(message_id="The active giveaway message ID")
@app_commands.guild_only()
@app_commands.check(_giveaway_role_gate)
async def giveaway_cancel_command(interaction:discord.Interaction,message_id:str):
    if not str(message_id).isdigit():
        return await cinnamon_send(interaction,"Enter the numeric giveaway message ID.",ephemeral=True)
    mid=int(message_id)
    gw=active_giveaways.get(mid)
    if not gw or int(gw.get("guild_id",0))!=interaction.guild.id:
        return await cinnamon_send(interaction,"No active giveaway with that message ID was found in this server.",ephemeral=True)
    if not await cancel_giveaway(mid):
        return await cinnamon_send(interaction,"That giveaway could not be cancelled.",ephemeral=True)
    await cinnamon_send(interaction,f"🚫 Giveaway {mid} was cancelled.")
