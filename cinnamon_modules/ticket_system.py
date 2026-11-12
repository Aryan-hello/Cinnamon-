"""Cinnamon Discord-native ticket system and central role permissions."""
import discord
from discord import app_commands
import asyncio, datetime as _dt, html as _html, io as _io, secrets as _secrets, time as _time

_TICKET_KEY = "cinnamon_tickets_v1"
_ROLE_KEY = "cinnamon_role_permissions_v1"
ROLE_CATEGORIES = {
    "giveaway_creator": ("Giveaway Creator", "Create/edit/end/reroll giveaways"),
    "hangry_runner": ("Hangry Games Runner", "Start and manage Hangry Games"),
    "trusted_booster": ("Trusted Booster", "Handle Grow a Garden boosting tickets"),
    "ticket_staff": ("Ticket Staff", "Claim, assign and resolve tickets"),
    "ticket_admin": ("Ticket Administrator", "Manage all ticket settings and tickets"),
    "shop_manager": ("Shop Manager", "Manage shop support and orders"),
    "economy_admin": ("Economy Administrator", "Manage economy tools"),
    "quest_manager": ("Quest Manager", "Manage quests and challenges"),
    "event_manager": ("Event Manager", "Manage server events"),
    "moderator": ("Moderator", "Moderation commands"),
}

def _ticket_root():
    root=advanced_features_data.setdefault(_TICKET_KEY,{})
    if not isinstance(root,dict): root=advanced_features_data[_TICKET_KEY]={}
    return root

def _ticket_guild(gid):
    cfg=_ticket_root().setdefault(str(int(gid)),{})
    cfg.setdefault("panels",{}); cfg.setdefault("tickets",{}); cfg.setdefault("closed",{}); cfg.setdefault("cooldowns",{})
    cfg.setdefault("settings",{"log_channel_id":None,"ticket_category_id":None,"staff_role_ids":[],"trusted_booster_role_ids":[],"max_open_per_user":3,"cooldown_seconds":60,"auto_close_hours":0,"transcript_on_close":True,"rating_enabled":True})
    return cfg

def _role_setup(gid):
    root=advanced_features_data.setdefault(_ROLE_KEY,{})
    if not isinstance(root,dict): root=advanced_features_data[_ROLE_KEY]={}
    cfg=root.setdefault(str(int(gid)),{})
    for key in ROLE_CATEGORIES: cfg.setdefault(key,[])
    return cfg

def cinnamon_role_has(member,category):
    if not member or not getattr(member,"guild",None): return False
    if getattr(member.guild_permissions,"administrator",False): return True
    try: allowed={int(x) for x in _role_setup(member.guild.id).get(str(category),[]) if str(x).isdigit()}
    except Exception: allowed=set()
    return bool(allowed & {r.id for r in member.roles})

async def _ticket_log(guild,action,actor=None,ticket=None,detail=""):
    cfg=_ticket_guild(guild.id); channel_id=cfg.get("settings",{}).get("log_channel_id")
    channel=guild.get_channel(int(channel_id)) if str(channel_id or "").isdigit() else None
    fields=[]
    if ticket: fields += [("Ticket",str(ticket.get("channel_id","unknown"))),("Creator",str(ticket.get("creator_id","unknown"))),("Category",str(ticket.get("category_label","Support")))]
    if actor: fields.append(("Actor",f"{actor} ({actor.id})"))
    if detail: fields.append(("Details",str(detail)[:800]))
    if channel:
        try:
            e=discord.Embed(title="🎫 Ticket log · "+str(action)[:180],description=str(detail)[:900] or "Ticket activity",color=discord.Color.orange(),timestamp=discord.utils.utcnow())
            for k,v in fields[:20]: e.add_field(name=k,value=str(v)[:1024] or "—",inline=True)
            await channel.send(embed=e)
        except Exception: log.exception("Ticket log channel send failed")
    fn=globals().get("send_log")
    if callable(fn):
        try: await fn(guild.id,title="Ticket: "+str(action)[:180],description="Ticket event; private message contents are not logged.",fields=[(k,v) for k,v in fields if k!="Details"],category="tickets")
        except Exception: log.exception("Ticket audit failed")

class TicketQuestionModal(discord.ui.Modal):
    def __init__(self,gid,panel_id,category_id,user_id,questions):
        super().__init__(title="Open support ticket",timeout=300)
        self.gid=int(gid); self.panel_id=str(panel_id); self.category_id=str(category_id); self.user_id=int(user_id); self.questions=list(questions or [])[:5]
        for i,q in enumerate(self.questions):
            self.add_item(discord.ui.TextInput(label=str(q.get("label","Question "+str(i+1)))[:45],placeholder=str(q.get("placeholder","Your answer"))[:100],required=bool(q.get("required",True)),max_length=min(1000,max(1,int(q.get("max_length",400)))),style=discord.TextStyle.paragraph if q.get("paragraph",True) else discord.TextStyle.short,custom_id="q"+str(i)))
    async def on_submit(self,interaction):
        if interaction.user.id!=self.user_id: return await interaction.response.send_message("This ticket form belongs to another member.",ephemeral=True)
        answers=[(str(q.get("label","Question"))[:45],str(self.children[i].value).strip()) for i,q in enumerate(self.questions)]
        await interaction.response.defer(ephemeral=True,thinking=True)
        cfg=_ticket_guild(self.gid); panel=cfg.get("panels",{}).get(self.panel_id)
        if not panel or not panel.get("published",True): return await interaction.followup.send("That panel is unavailable.",ephemeral=True)
        category=next((x for x in panel.get("categories",[]) if str(x.get("id"))==self.category_id),None)
        if not category: return await interaction.followup.send("That ticket category is unavailable.",ephemeral=True)
        await _ticket_create_channel(interaction,panel,category,answers)

class TicketPanelView(discord.ui.View):
    def __init__(self,gid,panel_id,panel):
        super().__init__(timeout=None); self.gid=int(gid); self.panel_id=str(panel_id)
        for cat in list(panel.get("categories",[]))[:25]:
            b=discord.ui.Button(label=str(cat.get("button_label") or cat.get("label") or "Open ticket")[:80],emoji=cat.get("emoji") or None,style=getattr(discord.ButtonStyle,str(cat.get("button_style","primary")).lower(),discord.ButtonStyle.primary),custom_id=f"ticket:open:{self.gid}:{self.panel_id}:{cat.get('id')}")
            b.callback=self._open; self.add_item(b)
    async def _open(self,interaction):
        cid=interaction.data.get("custom_id","").rsplit(":",1)[-1]; panel=_ticket_guild(self.gid).get("panels",{}).get(self.panel_id,{})
        cat=next((x for x in panel.get("categories",[]) if str(x.get("id"))==cid),None)
        if not cat: return await interaction.response.send_message("Ticket category unavailable.",ephemeral=True)
        if cat.get("questions"): return await interaction.response.send_modal(TicketQuestionModal(self.gid,self.panel_id,cid,interaction.user.id,cat["questions"]))
        await interaction.response.defer(ephemeral=True,thinking=True); await _ticket_create_channel(interaction,panel,cat,[])

class TicketControls(discord.ui.View):
    def __init__(self,ticket_id):
        super().__init__(timeout=None); self.ticket_id=str(ticket_id)
        for label,emoji,style,action in [("Claim","🙋",discord.ButtonStyle.success,"claim"),("Unclaim","↩️",discord.ButtonStyle.secondary,"unclaim"),("Close","🔒",discord.ButtonStyle.danger,"close"),("Reopen","🔓",discord.ButtonStyle.primary,"reopen")]:
            b=discord.ui.Button(label=label,emoji=emoji,style=style,custom_id=f"ticket:control:{self.ticket_id}:{action}"); b.callback=self._control; self.add_item(b)
    async def _control(self,interaction):
        action=interaction.data.get("custom_id","").rsplit(":",1)[-1]
        ticket=next((t for g in _ticket_root().values() for t in (g.get("tickets",{}) or {}).values() if str(t.get("ticket_id"))==self.ticket_id),None)
        if not ticket: return await interaction.response.send_message("Ticket record not found.",ephemeral=True)
        guild=interaction.guild; cfg=_ticket_guild(guild.id); staff=set(map(int,cfg.get("settings",{}).get("staff_role_ids",[])))
        is_staff=interaction.user.guild_permissions.administrator or any(r.id in staff for r in interaction.user.roles) or cinnamon_role_has(interaction.user,"ticket_staff") or cinnamon_role_has(interaction.user,"ticket_admin")
        if action in ("claim","unclaim"):
            if not is_staff: return await interaction.response.send_message("Only ticket staff can claim tickets.",ephemeral=True)
            if action=="claim" and ticket.get("claimed_by") not in (None,interaction.user.id): return await interaction.response.send_message("Already claimed by another staff member.",ephemeral=True)
            ticket["claimed_by"]=interaction.user.id if action=="claim" else None; await bd_save_data(); await _ticket_log(guild,action,interaction.user,ticket)
            return await interaction.response.send_message("Ticket "+("claimed." if action=="claim" else "unclaimed."),ephemeral=True)
        if action=="close":
            if not is_staff and interaction.user.id!=int(ticket.get("creator_id",0)): return await interaction.response.send_message("Only creator or staff can close.",ephemeral=True)
            return await interaction.response.send_modal(TicketCloseModal(self.ticket_id,interaction.user.id))
        if action=="reopen":
            if not is_staff: return await interaction.response.send_message("Only staff can reopen tickets.",ephemeral=True)
            channel=interaction.channel; creator=guild.get_member(int(ticket.get("creator_id",0)))
            await channel.set_permissions(guild.default_role,view_channel=False)
            if creator: await channel.set_permissions(creator,view_channel=True,send_messages=True,read_message_history=True)
            ticket["status"]="open"; ticket["closed_at"]=None; _ticket_guild(guild.id).get("closed",{}).pop(str(channel.id),None)
            await bd_save_data(); await _ticket_log(guild,"reopened",interaction.user,ticket)
            return await interaction.response.send_message("Ticket reopened.",ephemeral=True)

class TicketCloseModal(discord.ui.Modal):
    def __init__(self,ticket_id,actor_id):
        super().__init__(title="Close ticket",timeout=300); self.ticket_id=str(ticket_id); self.actor_id=int(actor_id)
        self.reason=discord.ui.TextInput(label="Closing reason",placeholder="Resolved, duplicate, etc.",required=False,max_length=500,style=discord.TextStyle.paragraph); self.add_item(self.reason)
    async def on_submit(self,interaction):
        if interaction.user.id!=self.actor_id: return await interaction.response.send_message("This close form belongs to another member.",ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        ticket=next((t for g in _ticket_root().values() for t in (g.get("tickets",{}) or {}).values() if str(t.get("ticket_id"))==self.ticket_id),None)
        if not ticket: return await interaction.followup.send("Ticket not found.",ephemeral=True)
        channel=interaction.channel; guild=interaction.guild; cfg=_ticket_guild(guild.id); reason=str(self.reason.value).strip() or "No reason provided"
        ticket.update({"status":"closed","closed_at":_time.time(),"close_reason":reason}); creator=guild.get_member(int(ticket.get("creator_id",0)))
        if creator: await channel.set_permissions(creator,view_channel=True,send_messages=False,read_message_history=True)
        await channel.send(embed=discord.Embed(title="Ticket closed",description=f"Closed by {interaction.user.mention}.\\nReason: {reason}",color=discord.Color.orange()),view=TicketControls(self.ticket_id))
        transcript=await _ticket_transcript(channel)
        if transcript and cfg.get("settings",{}).get("transcript_on_close",True):
            logch=guild.get_channel(int(cfg.get("settings",{}).get("log_channel_id") or 0))
            if logch: await logch.send(content=f"Transcript for {channel.mention} · {ticket.get('category_label','Ticket')}",file=discord.File(transcript,filename=f"ticket-{channel.id}.html"))
        cfg.setdefault("closed",{})[str(channel.id)]=dict(ticket); await bd_save_data(); await _ticket_log(guild,"closed",interaction.user,ticket,reason)
        await interaction.followup.send("Ticket closed and transcript logged.",ephemeral=True)

async def _ticket_transcript(channel):
    rows=[]
    try:
        async for msg in channel.history(limit=1000,oldest_first=True):
            body=_html.escape(msg.content or ""); attach=" ".join(f'<a href="{_html.escape(a.url,quote=True)}">{_html.escape(a.filename)}</a>' for a in msg.attachments); embeds=" ".join(_html.escape(e.title or e.description or "[embed]") for e in msg.embeds)
            rows.append(f"<article><time>{msg.created_at.isoformat()}</time> <b>{_html.escape(str(msg.author))}</b><p>{body}</p><p>{attach} {embeds}</p></article>")
    except Exception: log.exception("Transcript fetch failed")
    page="<!doctype html><meta charset='utf-8'><title>Ticket transcript</title><style>body{font:15px sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;background:#f8f3ea;color:#38281e}article{background:white;padding:1rem;margin:.7rem 0;border-radius:10px;overflow-wrap:anywhere}time{color:#88796c;font-size:12px}</style><h1>"+_html.escape(channel.name)+"</h1>"+"".join(rows)
    return _io.BytesIO(page.encode("utf-8"))

async def _ticket_create_channel(interaction,panel,category,answers):
    guild=interaction.guild; member=interaction.user; cfg=_ticket_guild(guild.id); settings=cfg.get("settings",{})
    opened=sum(1 for t in cfg.get("tickets",{}).values() if int(t.get("creator_id",0))==member.id and t.get("status")=="open")
    if opened>=max(1,min(10,int(settings.get("max_open_per_user",3)))): return await interaction.followup.send("You reached the open-ticket limit.",ephemeral=True)
    cooldown=max(0,min(86400,int(settings.get("cooldown_seconds",60)))); last=int(cfg["cooldowns"].get(str(member.id),0))
    if _time.time()-last<cooldown: return await interaction.followup.send(f"Wait {int(cooldown-(_time.time()-last))} seconds before opening another ticket.",ephemeral=True)
    staff=set(map(int,settings.get("staff_role_ids",[]))); route=str(category.get("routing","shop")).lower()
    answers_text=" ".join(str(a) for _,a in (answers or [])).lower()
    gag_purchase=any(x in answers_text for x in ("grow a garden","grow-a-garden","gag","garden boosting","garden boost","mutation","pet mutation"))
    if route in {"grow_a_garden","gag","boosting"} or category.get("trusted_booster_routing") or (route=="shop" and gag_purchase):
        staff.update(map(int,settings.get("trusted_booster_role_ids",[]))); staff.update(map(int,_role_setup(guild.id).get("trusted_booster",[])))
    overwrites={guild.default_role:discord.PermissionOverwrite(view_channel=False),member:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True,embed_links=True)}
    for rid in staff:
        role=guild.get_role(rid)
        if role: overwrites[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,manage_messages=True)
    parent=guild.get_channel(int(category.get("channel_category_id") or settings.get("ticket_category_id") or 0))
    if not isinstance(parent,discord.CategoryChannel): parent=None
    base=str(category.get("channel_name_format","ticket-{username}"))[:80].replace("{username}",member.name.lower().replace(" ","-")[:20]).replace("{user_id}",str(member.id)); name="".join(c for c in base.lower() if c.isalnum() or c in "-_")[:90] or "ticket"
    channel=await guild.create_text_channel(name,category=parent,overwrites=overwrites,reason=f"Cinnamon ticket opened by {member}")
    tid=_secrets.token_hex(8); ticket={"ticket_id":tid,"channel_id":channel.id,"creator_id":member.id,"panel_id":str(panel.get("id")),"panel_name":str(panel.get("name","Ticket panel")),"category_id":str(category.get("id")),"category_label":str(category.get("label","Support")),"created_at":_time.time(),"status":"open","claimed_by":None,"assigned_to":None,"priority":"normal","answers":answers,"close_reason":None}
    cfg["tickets"][str(channel.id)]=ticket; cfg["cooldowns"][str(member.id)]=int(_time.time())
    pings=" ".join(f"<@&{rid}>" for rid in staff if guild.get_role(rid)); e=discord.Embed(title=str(category.get("welcome_title") or f"{category.get('label','Support')} ticket"),description=str(category.get("welcome_message") or "Thanks for opening a ticket. Staff will assist you here."),color=discord.Color.orange())
    e.add_field(name="Ticket creator",value=member.mention,inline=True); e.add_field(name="Category",value=str(category.get("label","Support")),inline=True)
    for q,a in answers[:5]: e.add_field(name=str(q)[:256],value=str(a)[:1024] or "—",inline=False)
    e.add_field(name="Priority",value="Normal",inline=True)
    await channel.send(content=(member.mention+" "+pings).strip(),embed=e,view=TicketControls(tid),allowed_mentions=discord.AllowedMentions(users=[member],roles=[guild.get_role(x) for x in staff if guild.get_role(x)]))
    await bd_save_data(); await _ticket_log(guild,"opened",member,ticket,"Panel "+str(panel.get("name","")))
    await interaction.followup.send(f"Your ticket is ready: {channel.mention}",ephemeral=True)

async def cinnamon_ticket_restore_views():
    for gid,cfg in _ticket_root().items():
        for pid,panel in (cfg.get("panels",{}) or {}).items():
            if panel.get("published") and panel.get("message_id"): bot.add_view(TicketPanelView(int(gid),pid,panel),message_id=int(panel["message_id"]))
        for ticket in (cfg.get("tickets",{}) or {}).values():
            if ticket.get("status") in ("open","closed"): bot.add_view(TicketControls(ticket.get("ticket_id")))
