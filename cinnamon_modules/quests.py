"""Cinnamon rotating daily/weekly quest system from the user's master quest list."""

DAILY_QUESTS = {
"tuna_time":{"name":"Tuna Time","desc":"Feed Cinnamon 3 Tuna.","kind":"feed","item":"tuna","target":3,"qp":220,"xp":600},
"treat_run":{"name":"Treat Run","desc":"Feed Cinnamon 5 Cat Treats.","kind":"feed","item":"treat","target":5,"qp":300,"xp":750},
"royal_snack":{"name":"Royal Snack","desc":"Feed Cinnamon 2 Churus.","kind":"feed","item":"churu","target":2,"qp":180,"xp":500},
"zoomies_fuel":{"name":"Zoomies Fuel","desc":"Feed Cinnamon 2 Catnip Balls.","kind":"feed","item":"catnip_ball","target":2,"qp":200,"xp":600},
"fish_connoisseur":{"name":"Fish Connoisseur","desc":"Feed Cinnamon 1 Fancy Fish.","kind":"feed","item":"fish","target":1,"qp":150,"xp":500},
"tuna_delivery":{"name":"Tuna Delivery","desc":"Feed Cinnamon 1 Tuna.","kind":"feed","item":"tuna","target":1,"qp":120,"xp":400},
"snack_basket":{"name":"Snack Basket","desc":"Feed Cinnamon 1 Treat and 1 Churu on the same day.","kind":"combo","needs":{"treat":1,"churu":1},"qp":160,"xp":500},
"ball_of_yarn":{"name":"Ball of Yarn","desc":"Feed Cinnamon 1 Catnip Ball.","kind":"feed","item":"catnip_ball","target":1,"qp":110,"xp":400},
"clean_bowl":{"name":"Clean Bowl","desc":"Feed Cinnamon any 3 food items of your choice.","kind":"feed_any","target":3,"qp":200,"xp":600},
"head_scritches":{"name":"Head Scritches & Snacks","desc":"Use /pet 3 times and feed Cinnamon 1 item.","kind":"combo2","needs":{"pet":3,"feed":1},"qp":140,"xp":450},
"triple_threat":{"name":"Triple Threat","desc":"Complete 1 /work, send 15 messages, and feed Cinnamon 1 item.","kind":"combo3","needs":{"work":1,"messages":15,"feed":1},"qp":160,"xp":600},
"quick_shift":{"name":"Quick Shift","desc":"Complete 3 /work sessions.","kind":"counter","metric":"work","target":3,"qp":100,"xp":350},
"tidy_up":{"name":"Tidy Up","desc":"Complete 5 /work sessions throughout the day.","kind":"counter","metric":"work","target":5,"qp":150,"xp":500},
"double_shift":{"name":"Double Shift","desc":"Complete 2 /work sessions.","kind":"counter","metric":"work","target":2,"qp":80,"xp":250},
"morning_stretches":{"name":"Morning Stretches","desc":"Send 25 chat messages in the server.","kind":"counter","metric":"messages","target":25,"qp":90,"xp":350},
"server_buzz":{"name":"Server Buzz","desc":"Send 50 chat messages in the server.","kind":"counter","metric":"messages","target":50,"qp":140,"xp":500},
"late_night":{"name":"Late Night Chatter","desc":"Send 15 messages between 9:00 PM and midnight server time.","kind":"time_messages","start":21,"end":24,"target":15,"qp":90,"xp":300},
"night_patrol":{"name":"Night Patrol","desc":"Send 10 messages after 10:00 PM server time.","kind":"time_messages","start":22,"end":24,"target":10,"qp":80,"xp":250},
"daily_purr":{"name":"Daily Purr","desc":"Use 3 Cinnamon cat interactions.","kind":"counter","metric":"interactions","target":3,"qp":80,"xp":250},
"biscuit_maker":{"name":"Biscuit Maker","desc":"Use /pet 5 times.","kind":"counter","metric":"pet","target":5,"qp":90,"xp":300},
"afternoon_nap":{"name":"Afternoon Nap","desc":"Use /nap twice during the day.","kind":"counter","metric":"nap","target":2,"qp":70,"xp":250},
"cardboard_inspector":{"name":"Cardboard Inspector","desc":"Ping Cinnamon in chat 5 times, respecting cooldowns.","kind":"counter","metric":"pings","target":5,"qp":80,"xp":300},
"active_citizen":{"name":"Active Citizen","desc":"Cast a vote on any active server poll.","kind":"counter","metric":"poll_votes","target":1,"qp":75,"xp":250},
"checking_in":{"name":"Checking In","desc":"Run /economy balance and /rank to review your profile.","kind":"combo2","needs":{"balance_cmd":1,"rank_cmd":1},"qp":70,"xp":200},
"generous_tip":{"name":"Generous Tip","desc":"Send at least 1,000 Catnip to another member using /economy give.","kind":"give_single","target":1000,"qp":100,"xp":350},
}
WEEKLY_QUESTS = {
"tuna_wholesale":{"name":"Tuna Wholesale","desc":"Feed 10 Tuna to Cinnamon.","kind":"feed","item":"tuna","target":10,"qp":800,"xp":3500},
"gourmet_supplier":{"name":"Gourmet Supplier","desc":"Feed Cinnamon 20 combined Treats, Churus, or Fish.","kind":"feed_any_selected","items":["treat","churu","fish"],"target":20,"qp":1400,"xp":4500},
"ocean_harvest":{"name":"Ocean Harvest","desc":"Feed a combined total of 15 Tuna and Fancy Fish.","kind":"feed_selected","items":["tuna","fish"],"target":15,"qp":1200,"xp":4000},
"snack_hoarder":{"name":"Snack Hoarder","desc":"Purchase 15 total items from the shop during the week.","kind":"counter","metric":"purchases","target":15,"qp":900,"xp":3500},
"big_spender":{"name":"Big Spender","desc":"Spend at least 25,000 Catnip in /economy shop.","kind":"counter","metric":"spent","target":25000,"qp":1000,"xp":4000},
"full_inventory":{"name":"Full Inventory","desc":"Own at least 25 total items simultaneously.","kind":"live","metric":"items_owned","target":25,"qp":600,"xp":3000},
"employee_week":{"name":"Employee of the Week","desc":"Complete 30 /work sessions.","kind":"counter","metric":"work","target":30,"qp":550,"xp":3000},
"overtime_grind":{"name":"Overtime Grind","desc":"Complete 45 /work sessions.","kind":"counter","metric":"work","target":45,"qp":850,"xp":4500},
"workaholism":{"name":"Workaholism","desc":"Complete 20 /work sessions.","kind":"counter","metric":"work","target":20,"qp":400,"xp":2500},
"payday_routine":{"name":"Payday Routine","desc":"Use /economy collect on your income roles 15 times.","kind":"counter","metric":"collect","target":15,"qp":500,"xp":3000},
"server_socialite":{"name":"Server Socialite","desc":"Send 300 messages across any channel.","kind":"counter","metric":"messages","target":300,"qp":450,"xp":2500},
"chatterbox":{"name":"Chatterbox","desc":"Send 600 messages throughout the week.","kind":"counter","metric":"messages","target":600,"qp":750,"xp":4000},
"dedicated_attendant":{"name":"Dedicated Attendant","desc":"Complete 15 Daily Quests over the week.","kind":"counter","metric":"daily_completed","target":15,"qp":750,"xp":4000},
"daily_mastery":{"name":"Daily Mastery","desc":"Complete 25 Daily Quests over the week.","kind":"counter","metric":"daily_completed","target":25,"qp":1200,"xp":5000},
"best_friend":{"name":"Cinnamon's Best Friend","desc":"Use Cinnamon interaction commands 35 times.","kind":"counter","metric":"interactions","target":35,"qp":450,"xp":3000},
"voice_people":{"name":"Voice of the People","desc":"Vote in 3 different polls throughout the week.","kind":"counter","metric":"poll_votes","target":3,"qp":350,"xp":2000},
"community_supporter":{"name":"Community Supporter","desc":"Transfer Catnip to other members 5 times.","kind":"counter","metric":"give_count","target":5,"qp":400,"xp":2000},
"generous_patron":{"name":"Generous Patron","desc":"Transfer at least 10,000 Catnip total to server members.","kind":"counter","metric":"transferred","target":10000,"qp":500,"xp":3000},
"kibble_tycoon":{"name":"Kibble Tycoon","desc":"Reach or hold an active balance of at least 50,000 Catnip.","kind":"live","metric":"balance","target":50000,"qp":600,"xp":3500},
}

QUEST_SHOP={"250_catnip":{"name":"Starter cash-out","qp":250,"catnip":2500},"1000_catnip":{"name":"Bulk tier","qp":1000,"catnip":11500},"2500_catnip":{"name":"Major milestone tier","qp":2500,"catnip":30000},"golden_tuna":{"name":"Golden Tuna","qp":2000,"item":"golden_tuna","item_qty":1},"quest_master":{"name":"Quest Master Role","qp":7500,"role":"Quest Master"}}
quest_data={} # guild -> {daily_date,daily_ids,weekly_key,weekly_ids,users:{uid:{qp,daily,weekly,week_counters,daily_completed_week}}}
quest_config={}
_QUEST_SHOP_LOCKS = {}  # Prevent concurrent redemptions from spending QP twice.

def _today(): return cinnamon_now().date().isoformat()
def _week():
    iso=cinnamon_now().date().isocalendar(); return iso.year*100+iso.week

def _guild(g):
    d=quest_data.setdefault(int(g),{}); d.setdefault("users",{}); return d

def _user(g,u):
    d=_guild(g); x=d["users"].setdefault(str(u),{"qp":0,"daily":{},"weekly":{},"daily_completed_week":0,"week_counters":{},"poll_ids":[]}); return x

def _ensure_rolls(g):
    d=_guild(g); today=_today(); week=_week()
    if d.get("daily_date")!=today:
        d["daily_date"]=today; d["daily_ids"]=random.sample(list(DAILY_QUESTS),5)
        asyncio.create_task(send_log(g, title="📅 Daily quests rotated", category="quests", fields=[("Date", today), ("Selected quests", ", ".join(DAILY_QUESTS[q]["name"] for q in d["daily_ids"]))]))
        for u in d["users"].values(): u["daily"]={}
    if d.get("weekly_key")!=week:
        d["weekly_key"]=week; d["weekly_ids"]=random.sample(list(WEEKLY_QUESTS),5)
        asyncio.create_task(send_log(g, title="🗓️ Weekly quests rotated", category="quests", fields=[("Week", str(week)), ("Selected quests", ", ".join(WEEKLY_QUESTS[q]["name"] for q in d["weekly_ids"]))]))
        for u in d["users"].values(): u["weekly"]={}; u["week_counters"]={}; u["daily_completed_week"]=0
    return d

def _prog(u,scope,qid): return u.setdefault(scope,{}).setdefault(qid,{})

def _completed(q,p):
    kind=q["kind"]
    if kind in {"feed","counter","time_messages","feed_any","feed_selected","feed_any_selected"}: return int(p.get("count",0))>=int(q["target"])
    if kind=="combo": return all(int(p.get(k,0))>=v for k,v in q["needs"].items())
    if kind=="combo2" or kind=="combo3": return all(int(p.get(k,0))>=v for k,v in q["needs"].items())
    if kind in {"live","give_single"}: return int(p.get("value",0))>=int(q["target"])
    return False

def _apply_event(q,p,event,value,kw):
    kind=q["kind"]
    if kind=="feed":
        if event=="feed" and kw.get("item")==q["item"]: p["count"]=int(p.get("count",0))+value
    elif kind=="combo":
        if event=="feed" and kw.get("item") in q.get("needs",{}): p[kw.get("item")]=int(p.get(kw.get("item"),0))+value
    elif kind in {"feed_any","feed_any_selected"}:
        if event=="feed" and (kind=="feed_any" or kw.get("item") in q["items"]): p["count"]=int(p.get("count",0))+value
    elif kind=="feed_selected":
        if event=="feed" and kw.get("item") in q["items"]: p["count"]=int(p.get("count",0))+value
    elif kind=="combo2" or kind=="combo3":
        if event in q.get("needs",{}): p[event]=int(p.get(event,0))+value
        if event=="feed" and "feed" in q.get("needs",{}): p["feed"]=int(p.get("feed",0))+value
    elif kind=="counter":
        if event==q.get("metric"): p["count"]=int(p.get("count",0))+value
    elif kind=="time_messages":
        if event=="message" and q["start"]<=cinnamon_now().hour<q["end"]: p["count"]=int(p.get("count",0))+value
    elif kind=="live":
        if event==q.get("metric"): p["value"]=max(int(p.get("value",0)),int(value))
    elif kind=="give_single":
        if event=="give" and int(value)>=q["target"]: p["value"]=q["target"]

def _quest_metric_event(event, value, kw):
    return event,value,kw

async def quest_event(g,u,event,value=1,**kw):
    if not g or not u: return
    d=_ensure_rolls(g); usr=_user(g,u); completed_total=0
    # A poll vote counts once per distinct poll, matching the master quest/achievement wording.
    if event=="poll_vote":
        poll_id=str(kw.get("poll_id", ""))
        if poll_id and poll_id in usr.setdefault("poll_ids", []):
            return 0
        if poll_id:
            usr.setdefault("poll_ids", []).append(poll_id)
            usr["poll_ids"] = usr["poll_ids"][-500:]
    # Update weekly daily-completion counters BEFORE evaluating weekly quests.
    if event=="daily_quest_completed":
        usr["daily_completed_week"]=int(usr.get("daily_completed_week",0))+int(value)
        for qid in d.get("weekly_ids",[]):
            q=WEEKLY_QUESTS[qid]; p=_prog(usr,"weekly",qid)
            if q.get("metric")=="daily_completed": p["count"]=int(usr["daily_completed_week"])
    for scope,defs,ids in (("daily",DAILY_QUESTS,d.get("daily_ids",[])),("weekly",WEEKLY_QUESTS,d.get("weekly_ids",[]))):
        for qid in ids:
            q=defs[qid]; p=_prog(usr,scope,qid)
            if _completed(q,p): continue
            before=_completed(q,p); _apply_event(q,p,event,int(value),kw)
            if event=="balance" and q["kind"]=="live": p["value"]=max(int(p.get("value",0)),int(value))
            if _completed(q,p) and not before:
                usr["qp"]+=int(q["qp"]); completed_total+=1
                usr.setdefault("completed_history",[]).append({"scope":scope,"id":qid,"at":datetime.datetime.now(datetime.timezone.utc).isoformat()})
                xp_data[(g,u)]=int(xp_data.get((g,u),0))+int(q["xp"])
                await achievement_record(g,u,"level",level_from_xp(xp_data[(g,u)]))
                await achievement_record(g,u,"balance")
                if achievement_stats(g,u) is not None:
                    achievement_stats(g,u)["quests_completed"]=int(achievement_stats(g,u).get("quests_completed",0))+1
                await friendship_add(g,u,15,"Quest completed")
                await achievement_check_all(g,u)
                await send_log(g, title="📜 Quest completed", category="quests", fields=[
                    ("User", f"<@{u}> ({u})"),
                    ("Quest", str(q.get("name", qid))),
                    ("Schedule", scope.title()),
                    ("Quest Points", f"+{int(q.get('qp',0)):,}"),
                    ("XP", f"+{int(q.get('xp',0)):,}"),
                    ("Total QP", f"{int(usr.get('qp',0)):,}"),
                ])
                if scope=="daily":
                    # Feed the weekly daily-completion counter through the same tracker.
                    usr["daily_completed_week"]=int(usr.get("daily_completed_week",0))+1
                    for wqid in d.get("weekly_ids",[]):
                        wq=WEEKLY_QUESTS[wqid]; wp=_prog(usr,"weekly",wqid)
                        if wq.get("metric")=="daily_completed": wp["count"]=int(usr["daily_completed_week"])
                    # Re-check the two dependent weekly quests immediately.
                    for wqid in d.get("weekly_ids",[]):
                        wq=WEEKLY_QUESTS[wqid]; wp=_prog(usr,"weekly",wqid)
                        if wq.get("metric")=="daily_completed" and _completed(wq,wp) and wqid not in [x.get("id") for x in usr.get("completed_history",[]) if x.get("scope")=="weekly"]:
                            usr["qp"]+=int(wq["qp"]); completed_total+=1; wp["count"]=int(usr["daily_completed_week"])
                            usr.setdefault("completed_history",[]).append({"scope":"weekly","id":wqid,"at":datetime.datetime.now(datetime.timezone.utc).isoformat()})
                            xp_data[(g,u)]=int(xp_data.get((g,u),0))+int(wq["xp"])
                            await achievement_record(g,u,"level",level_from_xp(xp_data[(g,u)])); await achievement_record(g,u,"balance")
                            achievement_stats(g,u)["quests_completed"]=int(achievement_stats(g,u).get("quests_completed",0))+1
                            await achievement_check_all(g,u)
    if completed_total:
        await bd_save_data()
    return completed_total

@tasks.loop(minutes=1)
async def quest_reset_loop():
    # Touch every guild once a minute so rotations happen predictably at local midnight/week rollover.
    changed=False
    for guild in bot.guilds:
        before=(quest_data.get(guild.id,{}).get("daily_date"), quest_data.get(guild.id,{}).get("weekly_key"))
        _ensure_rolls(guild.id)
        after=(quest_data.get(guild.id,{}).get("daily_date"), quest_data.get(guild.id,{}).get("weekly_key"))
        if before!=after: changed=True
    if changed: await bd_save_data()

@quest_reset_loop.before_loop
async def _quest_reset_before_loop():
    await bot.wait_until_ready()

class QuestPageView(discord.ui.View):
    def __init__(self, guild_id:int, user_id:int, scope:str="daily", page:int=0):
        super().__init__(timeout=300); self.guild_id=guild_id; self.user_id=user_id; self.scope=scope; self.page=page; self._refresh()
    def _refresh(self):
        defs=DAILY_QUESTS if self.scope=="daily" else WEEKLY_QUESTS; per=2; pages=max(1,(len(_guild(self.guild_id).get(self.scope+"_ids",[]))+per-1)//per); self.page=max(0,min(self.page,pages-1)); self.clear_items()
        p=discord.ui.Button(label="Back",emoji="◀️",style=discord.ButtonStyle.secondary,disabled=self.page==0,row=0); n=discord.ui.Button(label="Next",emoji="▶️",style=discord.ButtonStyle.primary,disabled=self.page>=pages-1,row=0); p.callback=self._prev; n.callback=self._next; self.add_item(p); self.add_item(n)
        daily=discord.ui.Button(label="Daily",emoji="☀️",style=discord.ButtonStyle.success if self.scope=="daily" else discord.ButtonStyle.secondary,row=1)
        weekly=discord.ui.Button(label="Weekly",emoji="📅",style=discord.ButtonStyle.success if self.scope=="weekly" else discord.ButtonStyle.secondary,row=1)
        progress=discord.ui.Button(label="Progress",emoji="📊",style=discord.ButtonStyle.secondary,row=1)
        daily.callback=self._daily; weekly.callback=self._weekly; progress.callback=self._progress
        self.add_item(daily); self.add_item(weekly); self.add_item(progress)
    async def _guard(self,i):
        if i.user.id!=self.user_id: await i.response.send_message("🐾 This quest page belongs to the person who opened it.",ephemeral=True); return False
        return True
    async def _prev(self,i):
        if not await self._guard(i): return
        self.page-=1; self._refresh(); await i.response.edit_message(embed=quest_scope_embed(self.guild_id,self.user_id,self.scope,self.page),view=self)
    async def _next(self,i):
        if not await self._guard(i): return
        self.page+=1; self._refresh(); await i.response.edit_message(embed=quest_scope_embed(self.guild_id,self.user_id,self.scope,self.page),view=self)

    async def _daily(self,i):
        if not await self._guard(i): return
        self.scope="daily"; self.page=0; self._refresh(); await i.response.edit_message(embed=quest_scope_embed(self.guild_id,self.user_id,"daily",0),view=self)
    async def _progress(self,i):
        if not await self._guard(i): return
        u=_user(self.guild_id,self.user_id); d=_guild(self.guild_id); completed=len(u.get("completed_history",[]))
        e=cinnamon_embed("📊 Quest Progress","Your current Cinnamon quest summary.",color=CINNAMON_BLUE,user=bot.get_guild(self.guild_id).get_member(self.user_id) if bot.get_guild(self.guild_id) else None,footer="Cinnamon • Quest Progress")
        e.add_field(name="⭐ Quest Points",value=f"**{u.get('qp',0):,}**",inline=True)
        e.add_field(name="☀️ Daily",value=f"**{len(d.get('daily_ids',[]))}/5** active",inline=True)
        e.add_field(name="📅 Weekly",value=f"**{len(d.get('weekly_ids',[]))}/5** active",inline=True)
        e.add_field(name="✅ Completed",value=f"**{completed:,}** quests",inline=False)
        await i.response.edit_message(embed=cinnamon_polish_embed(e),view=self)

    async def _weekly(self,i):
        if not await self._guard(i): return
        self.scope="weekly"; self.page=0; self._refresh(); await i.response.edit_message(embed=quest_scope_embed(self.guild_id,self.user_id,"weekly",0),view=self)

def quest_scope_embed(guild_id,user_id,scope="daily",page=0):
    d=_ensure_rolls(guild_id); u=_user(guild_id,user_id); defs=DAILY_QUESTS if scope=="daily" else WEEKLY_QUESTS; ids=d.get(scope+"_ids",[]); per=2; pages=max(1,(len(ids)+per-1)//per); page=max(0,min(page,pages-1)); chunk=ids[page*per:(page+1)*per]
    title="☀️ Daily Quests" if scope=="daily" else "📅 Weekly Quests"; color=CINNAMON_ORANGE if scope=="daily" else 0x8E7CFF
    e=cinnamon_embed(title,"Complete quests to earn Quest Points and XP.",color=color,user=bot.get_guild(guild_id).get_member(user_id) if bot.get_guild(guild_id) else None,footer=cinnamon_page_footer("Quests",page+1,pages,f"{u.get('qp',0):,} QP"))
    for qid in chunk:
        q=defs[qid]; p=_prog(u,scope,qid); target=int(q.get('target',p.get('value',0) or 1)); cur=int(p.get('count',p.get('value',0))); shown=min(cur,target); done=_completed(q,p)
        e.add_field(name=f"{'✅' if done else '⬜'} {q['name']}",value=f"{cinnamon_progress_bar(shown,target,8)} **{shown}/{target}**\n{q['desc']}\n⭐ **{q['qp']:,} QP**  ·  ✨ **{q['xp']:,} XP**",inline=False)
    return cinnamon_polish_embed(e)


def _quest_ui_values(record, progress):
    """Progress for both counter quests and multi-requirement quests."""
    needs = record.get("needs")
    if needs:
        goal = sum(max(0, int(v)) for v in needs.values())
        amount = sum(min(max(0, int(progress.get(k, 0))), int(v)) for k, v in needs.items())
        return amount, max(1, goal)
    goal = max(1, int(record.get("target", 1)))
    amount = int(progress.get("count", progress.get("value", 0)))
    return min(max(0, amount), goal), goal


def _quest_next_reset(scope):
    now = cinnamon_now()
    days = 1 if scope == "daily" else 7 - now.weekday()
    next_day = (now + datetime.timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return f"<t:{int(next_day.timestamp())}:R>"


class CinnamonQuestBoard(discord.ui.LayoutView):
    """Private quest board. Text-first progress, context and instant navigation."""

    def __init__(self, guild_id, user_id, scope="daily", page=0):
        super().__init__(timeout=300)
        self.guild_id, self.user_id, self.scope, self.page = guild_id, user_id, scope, page
        self._build()

    def _build(self):
        self.clear_items()
        d = _ensure_rolls(self.guild_id)
        u = _user(self.guild_id, self.user_id)
        defs = DAILY_QUESTS if self.scope == "daily" else WEEKLY_QUESTS
        ids = d.get(self.scope + "_ids", [])
        pages = max(1, (len(ids) + 2) // 3)
        self.page = max(0, min(self.page, pages - 1))
        completed = sum(_completed(defs[qid], _prog(u, self.scope, qid))
                        for qid in ids if qid in defs)
        color = CINNAMON_UI["brand"] if self.scope == "daily" else 0x8674C2
        panel = discord.ui.Container(accent_color=color)
        panel.add_item(discord.ui.TextDisplay(
            f"# {'☀️ Daily' if self.scope == 'daily' else '📅 Weekly'} quests\n"
            f"**{completed}/{len(ids)} completed**  ·  "
            f"**{int(u.get('qp', 0)):,} QP**  ·  Resets {_quest_next_reset(self.scope)}\n"
            f"Page **{self.page + 1}/{pages}**"
        ))
        panel.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))

        visible = ids[self.page * 3:(self.page + 1) * 3]
        if not visible:
            panel.add_item(discord.ui.TextDisplay("No quests are available yet."))
        for qid in visible:
            record = defs.get(qid)
            if not record:
                continue
            current = _prog(u, self.scope, qid)
            amount, goal = _quest_ui_values(record, current)
            done = _completed(record, current)
            detail_button = discord.ui.Button(label="Details", style=discord.ButtonStyle.secondary)
            detail_button.callback = self._detail_callback(qid)
            panel.add_item(discord.ui.Section(
                f"### {'✅' if done else '◻️'} {cinnamon_ui_literal(record['name'], 85)}",
                f"{cinnamon_ui_progress(amount, goal)}\n"
                f"**{int(record['qp']):,} QP**  ·  **{int(record['xp']):,} XP**",
                accessory=detail_button,
            ))
            panel.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))

        nav = discord.ui.ActionRow()
        prev = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
        nxt = discord.ui.Button(label="Next", style=discord.ButtonStyle.primary, disabled=self.page >= pages - 1)
        daily = discord.ui.Button(label="Daily", style=discord.ButtonStyle.success if self.scope == "daily" else discord.ButtonStyle.secondary)
        weekly = discord.ui.Button(label="Weekly", style=discord.ButtonStyle.success if self.scope == "weekly" else discord.ButtonStyle.secondary)
        prev.callback = self._prev
        nxt.callback = self._next
        daily.callback = self._daily
        weekly.callback = self._weekly
        for item in (prev, nxt, daily, weekly):
            nav.add_item(item)
        panel.add_item(nav)
        self.add_item(panel)

    async def _guard(self, interaction):
        if (interaction.user.id != self.user_id or not interaction.guild or
                interaction.guild.id != self.guild_id):
            await interaction.response.send_message(
                "This quest board belongs to a different player.", ephemeral=True)
            return False
        return True

    def _detail_callback(self, qid):
        async def show(interaction):
            if not await self._guard(interaction):
                return
            d = _ensure_rolls(self.guild_id)
            defs = DAILY_QUESTS if self.scope == "daily" else WEEKLY_QUESTS
            if qid not in d.get(self.scope + "_ids", []) or qid not in defs:
                return await interaction.response.send_message(
                    "Quests have rotated. Open /quest to see your new ones.", ephemeral=True)
            record = defs[qid]
            progress = _prog(_user(self.guild_id, self.user_id), self.scope, qid)
            amount, goal = _quest_ui_values(record, progress)
            card = cinnamon_ui_card(
                "Quests", cinnamon_ui_literal(record["name"], 160),
                cinnamon_ui_literal(record["desc"], 900),
                color=CINNAMON_UI["brand"] if self.scope == "daily" else 0x8674C2,
                footer="Resets " + ("daily" if self.scope == "daily" else "weekly"),
            )
            card.add_field(name="Progress", value=cinnamon_ui_progress(amount, goal), inline=False)
            card.add_field(name="Reward", value=f"{int(record['qp']):,} QP  ·  {int(record['xp']):,} XP", inline=False)
            card.add_field(name="Status", value="Complete" if _completed(record, progress) else "In progress", inline=False)
            await interaction.response.send_message(
                embed=card, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        return show

    async def _show(self, interaction, scope=None, page=None):
        if await self._guard(interaction):
            await interaction.response.edit_message(
                view=CinnamonQuestBoard(self.guild_id, self.user_id,
                                        scope or self.scope,
                                        self.page if page is None else page))

    async def _prev(self, interaction):
        await self._show(interaction, page=self.page - 1)

    async def _next(self, interaction):
        await self._show(interaction, page=self.page + 1)

    async def _daily(self, interaction):
        await self._show(interaction, scope="daily", page=0)

    async def _weekly(self, interaction):
        await self._show(interaction, scope="weekly", page=0)


@bot.tree.command(name="quest",description="Open paginated daily and weekly Cinnamon quests")
@app_commands.guild_only()
async def quest_cmd(interaction):
    await interaction.response.send_message(
        view=CinnamonQuestBoard(interaction.guild.id, interaction.user.id),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

# Canonical daily/weekly quest commands are /quests daily and /quests weekly.
# /quest remains a convenient paginated entrypoint.

@bot.group(name="quest", aliases=["quests"], invoke_without_command=True)
@commands.guild_only()
async def prefix_quest(ctx):
    d=_ensure_rolls(ctx.guild.id); u=_user(ctx.guild.id,ctx.author.id)
    def render(scope, defs, ids):
        lines=[]
        for qid in ids:
            q=defs[qid]; p=_prog(u,scope,qid); done="✅" if _completed(q,p) else "⬜"; cur=p.get("count",p.get("value",0)); target=q.get("target","—")
            lines.append(f"{done} **{q['name']}** — {cur}/{target} · {q['qp']} QP + {q['xp']} XP")
        return "\n".join(lines) or "None"
    embed=discord.Embed(title="📜 Cinnamon Quests",color=0xFFB02E)
    embed.add_field(name="☀️ Daily",value=render("daily",DAILY_QUESTS,d.get("daily_ids",[]))[:1024],inline=False)
    embed.add_field(name="📅 Weekly",value=render("weekly",WEEKLY_QUESTS,d.get("weekly_ids",[]))[:1024],inline=False)
    embed.set_footer(text=f"Quest Points: {u['qp']:,} • Use ?quest daily, ?quest weekly, or ?quest progress")
    await ctx.reply(embed=embed,mention_author=False)

@prefix_quest.command(name="daily")
@commands.guild_only()
async def prefix_quest_daily(ctx):
    d=_ensure_rolls(ctx.guild.id); u=_user(ctx.guild.id,ctx.author.id)
    lines=[]
    for qid in d.get("daily_ids",[]):
        q=DAILY_QUESTS[qid]; p=_prog(u,"daily",qid); done="✅" if _completed(q,p) else "⬜"; cur=p.get("count",p.get("value",0))
        lines.append(f"{done} **{q['name']}** — {cur}/{q.get('target','—')} · **{q['qp']} QP + {q['xp']} XP**\n{q['desc']}")
    await ctx.reply("**☀️ Daily Cinnamon Quests**\n\n"+"\n\n".join(lines),mention_author=False)

@prefix_quest.command(name="weekly")
@commands.guild_only()
async def prefix_quest_weekly(ctx):
    d=_ensure_rolls(ctx.guild.id); u=_user(ctx.guild.id,ctx.author.id)
    lines=[]
    for qid in d.get("weekly_ids",[]):
        q=WEEKLY_QUESTS[qid]; p=_prog(u,"weekly",qid); done="✅" if _completed(q,p) else "⬜"; cur=p.get("count",p.get("value",0))
        lines.append(f"{done} **{q['name']}** — {cur}/{q.get('target','—')} · **{q['qp']} QP + {q['xp']} XP**\n{q['desc']}")
    await ctx.reply("**📅 Weekly Cinnamon Quests**\n\n"+"\n\n".join(lines),mention_author=False)

@prefix_quest.command(name="progress")
@commands.guild_only()
async def prefix_quest_progress(ctx):
    d=_ensure_rolls(ctx.guild.id); u=_user(ctx.guild.id,ctx.author.id)
    completed=len(u.get("completed_history",[]))
    await ctx.reply(f"📜 **Quest Progress**\n• Quest Points: **{u['qp']:,}**\n• Completed quests: **{completed}**\n• Active daily: **{len(d.get('daily_ids',[]))}/5**\n• Active weekly: **{len(d.get('weekly_ids',[]))}/5**",mention_author=False)


# Canonical grouped commands; the old redundant /dailyquests and
# /weeklyquests top-level aliases were retired to avoid command clutter.
quests_view_group = app_commands.Group(name="quests", description="View Cinnamon's daily and weekly quests")

@quests_view_group.command(name="daily", description="View your 5 active daily Cinnamon quests")
@app_commands.guild_only()
async def quests_daily_view_cmd(interaction):
    await interaction.response.send_message(
        view=CinnamonQuestBoard(interaction.guild.id, interaction.user.id, "daily"),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@quests_view_group.command(name="weekly", description="View your 5 active weekly Cinnamon quests")
@app_commands.guild_only()
async def quests_weekly_view_cmd(interaction):
    await interaction.response.send_message(
        view=CinnamonQuestBoard(interaction.guild.id, interaction.user.id, "weekly"),
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@quests_view_group.command(name="progress", description="View your Cinnamon quest progress and Quest Points")
@app_commands.guild_only()
async def quests_progress_view_cmd(interaction):
    d = _ensure_rolls(interaction.guild.id)
    u = _user(interaction.guild.id, interaction.user.id)
    completed = len(u.get("completed_history", []))
    e = discord.Embed(title="📜 Cinnamon Quest Progress", color=0xFFB02E)
    e.add_field(name="Quest Points", value=f"✨ **{u['qp']:,} QP**", inline=True)
    e.add_field(name="Completed", value=f"🏆 **{completed}**", inline=True)
    e.add_field(name="Active", value=f"☀️ {len(d.get('daily_ids', []))}/5 daily\n📅 {len(d.get('weekly_ids', []))}/5 weekly", inline=True)
    await interaction.response.send_message(embed=cinnamon_polish_embed(e), ephemeral=True)

bot.tree.add_command(quests_view_group)

@bot.tree.command(name="questshop",description="Redeem Quest Points for Catnip, Golden Tuna, or the Quest Master role")
@app_commands.guild_only()
@app_commands.choices(reward=[app_commands.Choice(name=v["name"], value=k) for k,v in QUEST_SHOP.items()])
async def questshop_cmd(interaction, reward:app_commands.Choice[str]):
    reward = reward.value
    guild_id, user_id = interaction.guild.id, interaction.user.id
    key = str(reward).lower().strip()
    match = next((k for k, v in QUEST_SHOP.items()
                  if k == key or v["name"].lower() == key), None)
    if not match:
        return await cinnamon_send(interaction, "❌ Unknown reward. Please select a reward from the Quest Shop.", ephemeral=True)
    r = QUEST_SHOP[match]
    lock = _QUEST_SHOP_LOCKS.setdefault((guild_id, user_id), asyncio.Lock())
    async with lock:
        u = _user(guild_id, user_id)
        if int(u.get("qp", 0)) < int(r["qp"]):
            return await cinnamon_send(interaction, f"❌ You need **{r['qp']:,} QP** but have **{u['qp']:,} QP**.", ephemeral=True)
        # Never charge QP for a role that does not exist or cannot be granted.
        if r.get("role") and not await _assign_quest_role(guild_id, user_id, r["role"]):
            return await cinnamon_send(interaction, f"❌ The **{r['role']}** role is missing or Cinnamon cannot assign it. Your QP was not spent.", ephemeral=True)
        u["qp"] -= int(r["qp"])
        if r.get("catnip"):
            economy_balances[(guild_id, user_id)] = economy_balance(guild_id, user_id) + int(r["catnip"])
            await achievement_record(guild_id, user_id, "catnip_earned", int(r["catnip"]))
        if r.get("item"):
            inv = economy_inventory_for(guild_id, user_id)
            inv[r["item"]] = int(inv.get(r["item"], 0)) + int(r.get("item_qty", 1))
            await achievement_record(guild_id, user_id, "inventory")
        result = await bd_save_data()
        if getattr(result, "status", "committed") not in {"committed", None}:
            return await cinnamon_send(interaction, "⚠️ The reward changed locally, but storage did not confirm the save. Please check /datastatus check before retrying.", ephemeral=True)
        await send_log(guild_id, title="🎁 Quest Shop redemption", category="quests",
                       interaction=interaction,
                       fields=[("Member", f"{interaction.user} ({user_id})"),
                               ("Reward", r["name"]), ("QP spent", str(r["qp"])),
                               ("QP remaining", str(u["qp"]))])
        await cinnamon_send(interaction, f"✅ Redeemed **{r['name']}** for **{r['qp']:,} QP**. Remaining: **{u['qp']:,} QP**.")

async def _assign_quest_role(g,u,name):
    guild=bot.get_guild(g); member=guild.get_member(u) if guild else None
    if not member: return False
    roles=[r for r in guild.roles if r.name==name and not r.managed]
    if not roles: return False
    try: await member.add_roles(roles[-1],reason="Quest Shop reward"); return True
    except discord.HTTPException: return False

# Quest configuration/definition management is dashboard-only.

ECONOMY_QUESTS=DAILY_QUESTS

def economy_quests_for(g,u): return _user(g,u)
def sanitize_economy_quests(g,u): return _user(g,u)
def quest_is_complete(g,u,qid):
    d=_ensure_rolls(g); usr=_user(g,u)
    for scope,defs in (("daily",DAILY_QUESTS),("weekly",WEEKLY_QUESTS)):
        if qid in defs: return _completed(defs[qid],_prog(usr,scope,qid))
    return False
def all_quests_complete(g,u): return False
async def apply_quest_progress(g,u,item_id,quantity): return [],0
