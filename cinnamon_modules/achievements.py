"""Cinnamon achievement system built from the user's master achievement list."""

ACHIEVEMENTS = {
    # id: name, requirement, metric/target, rewards. Achievement Points are
    # intentionally 0 until the user finalizes their values.
    "cat_yapper": {"name":"Cat Yapper","description":"Ping Cinnamon 100 times.","metric":"pings","target":100,"catnip":1000,"xp":500,"role":"Cat Yapper","points":0},
    "master_cat_yapper": {"name":"Master Cat Yapper","description":"Ping Cinnamon 500 times.","metric":"pings","target":500,"catnip":5000,"xp":1500,"role":"Master Cat Yapper","points":0},
    "cinnamon_whisperer": {"name":"Cinnamon Whisperer","description":"Ping Cinnamon 1,000 times.","metric":"pings","target":1000,"catnip":12000,"xp":3000,"role":"Cinnamon Whisperer","points":0},
    "biggest_problem": {"name":"Cinnamon's Biggest Problem","description":"Ping Cinnamon 5,000 times.","metric":"pings","target":5000,"catnip":30000,"xp":7500,"role":"Cinnamon's Biggest Problem","points":0},
    "little_yapper": {"name":"Little Yapper","description":"Send 100 messages.","metric":"messages","target":100,"catnip":500,"xp":500,"points":0},
    "professional_yapper": {"name":"Professional Yapper","description":"Send 500 messages.","metric":"messages","target":500,"catnip":2500,"xp":2000,"points":0},
    "mega_yapper": {"name":"Mega Yapper","description":"Send 1,000 messages.","metric":"messages","target":1000,"catnip":5000,"xp":5000,"role":"Mega Yapper","points":0},
    "human_podcast": {"name":"Human Podcast","description":"Send 5,000 messages.","metric":"messages","target":5000,"catnip":15000,"xp":10000,"role":"Human Podcast","points":0},
    "never_ending_story": {"name":"The Never-Ending Story","description":"Send 10,000 messages.","metric":"messages","target":10000,"catnip":35000,"xp":20000,"role":"The Never-Ending Story","points":0},
    "why_typing": {"name":"Why Are You Still Typing?","description":"Send 25,000 messages.","metric":"messages","target":25000,"catnip":80000,"xp":30000,"role":"Why Are You Still Typing?","points":0},
    "catnip_beginner": {"name":"Catnip Beginner","description":"Earn 1,000 lifetime Catnip.","metric":"lifetime_catnip","target":1000,"catnip":500,"xp":500,"points":0},
    "catnip_collector": {"name":"Catnip Collector","description":"Earn 5,000 lifetime Catnip.","metric":"lifetime_catnip","target":5000,"catnip":3000,"xp":1500,"points":0},
    "catnip_hoarder": {"name":"Catnip Hoarder","description":"Earn 10,000 lifetime Catnip.","metric":"lifetime_catnip","target":10000,"catnip":6000,"xp":3000,"points":0},
    "catnip_tycoon": {"name":"Catnip Tycoon","description":"Earn 25,000 lifetime Catnip.","metric":"lifetime_catnip","target":25000,"catnip":15000,"xp":7500,"points":0},
    "catnip_apprentice": {"name":"Catnip Millionaire's Apprentice","description":"Earn 50,000 lifetime Catnip.","metric":"lifetime_catnip","target":50000,"catnip":0,"xp":15000,"role":"Catnip Millionaire's Apprentice","points":0},
    "catnip_king": {"name":"Catnip King","description":"Earn 100,000 lifetime Catnip.","metric":"lifetime_catnip","target":100000,"catnip":0,"xp":30000,"role":"Catnip King","points":0},
    "catnip_corporation": {"name":"Catnip Corporation","description":"Earn 250,000 lifetime Catnip.","metric":"lifetime_catnip","target":250000,"catnip":0,"xp":60000,"role":"Catnip Corporation","points":0},
    "window_shopper": {"name":"Window Shopper","description":"Buy your first item.","metric":"purchases","target":1,"catnip":0,"xp":500,"points":0},
    "regular_customer": {"name":"Regular Customer","description":"Buy 25 items.","metric":"purchases","target":25,"catnip":0,"xp":2500,"role":"Regular Customer","points":0},
    "receipt_collector": {"name":"Receipt Collector","description":"Buy 100 items.","metric":"purchases","target":100,"catnip":0,"xp":7500,"role":"Receipt Collector","points":0},
    "money_what_money": {"name":"Money? What Money?","description":"Spend 25,000 Catnip.","metric":"spent","target":25000,"catnip":0,"xp":15000,"role":"Money? What Money?","points":0},
    "take_my_money": {"name":"Take My Money","description":"Spend 100,000 Catnip.","metric":"spent","target":100000,"catnip":0,"xp":35000,"role":"Take My Money","points":0},
    "tuna_enjoyer": {"name":"Tuna Enjoyer","description":"Own 10 Tuna.","metric":"tuna_owned","target":10,"catnip":2000,"xp":2000,"points":0},
    "tuna_addict": {"name":"Tuna Addict","description":"Own 50 Tuna.","metric":"tuna_owned","target":50,"catnip":10000,"xp":5000,"role":"Tuna Addict","points":0},
    "tuna_empire": {"name":"TUNA EMPIRE","description":"Own 100 Tuna.","metric":"tuna_owned","target":100,"catnip":25000,"xp":10000,"role":"TUNA EMPIRE","points":0},
    "pack_rat": {"name":"Pack Rat","description":"Own 100 total items.","metric":"items_owned","target":100,"catnip":10000,"xp":5000,"points":0},
    "stuff_hoarder": {"name":"Why Do You Have So Much Stuff?","description":"Own 500 total items.","metric":"items_owned","target":500,"catnip":35000,"xp":15000,"role":"Stuff Hoarder","points":0},
    "first_day_work": {"name":"First Day At Work","description":"Complete 1 /work session.","metric":"work_sessions","target":1,"catnip":450,"xp":500,"points":0},
    "part_time_cat": {"name":"Part-Time Cat Employee","description":"Complete 25 /work sessions.","metric":"work_sessions","target":25,"catnip":5000,"xp":2000,"points":0},
    "full_time_cat": {"name":"Full-Time Cat Employee","description":"Complete 100 /work sessions.","metric":"work_sessions","target":100,"catnip":15000,"xp":5000,"points":0},
    "corporate_cat": {"name":"Corporate Cat","description":"Complete 500 /work sessions.","metric":"work_sessions","target":500,"catnip":40000,"xp":15000,"role":"Corporate Cat","points":0},
    "best_employee": {"name":"Cinnamon's Best Employee","description":"Complete 1,000 /work sessions.","metric":"work_sessions","target":1000,"catnip":75000,"xp":25000,"role":"Cinnamon's Best Employee","points":0},
    "level_up": {"name":"Level Up!","description":"Reach Level 5.","metric":"level","target":5,"catnip":2500,"xp":0,"points":0},
    "getting_somewhere": {"name":"Getting Somewhere","description":"Reach Level 10.","metric":"level","target":10,"catnip":8000,"xp":0,"points":0},
    "veteran_cat": {"name":"Veteran Cat","description":"Reach Level 25.","metric":"level","target":25,"catnip":25000,"xp":0,"role":"Veteran Cat","points":0},
    "server_legend": {"name":"Server Legend","description":"Reach Level 50.","metric":"level","target":50,"catnip":75000,"xp":0,"role":"Server Legend","points":0},
    "personal_assistant": {"name":"Cinnamon's Personal Assistant","description":"Complete 25 Cinnamon quests.","metric":"quests_completed","target":25,"catnip":15000,"xp":5000,"role":"Cinnamon's Personal Assistant","points":0},
    "cat_servant": {"name":"Cat Servant","description":"Complete 50 Cinnamon quests.","metric":"quests_completed","target":50,"catnip":35000,"xp":12500,"role":"Cat Servant","points":0},
    "tuna_supplier": {"name":"Tuna Supplier","description":"Give Cinnamon 100 Tuna.","metric":"tuna_fed","target":100,"catnip":50000,"xp":10000,"role":"Tuna Supplier","points":0},
    "toe_bean_inspector": {"name":"Toe Bean Inspector","description":"Use 25 Cinnamon interaction commands.","metric":"interactions","target":25,"catnip":5000,"xp":2500,"points":0},
    "no_life": {"name":"I Have No Life","description":"Send 10,000 messages and complete 100 /work sessions.","metric":"compound_no_life","target":1,"catnip":60000,"xp":20000,"role":"I Have No Life","points":0},
    "second_favourite": {"name":"Cinnamon's Second Favourite Human","description":"Complete 50 quests, ping Cinnamon 500 times, and feed 50 Tuna.","metric":"compound_second_favourite","target":1,"catnip":100000,"xp":30000,"role":"Cinnamon's Second Favourite Human","points":0},
    "first_blood": {"name":"First Blood","description":"Score 10 total kills in Hangry Games.","metric":"hangry_kills","target":10,"catnip":3000,"xp":1500,"points":0},
    "apex_predator": {"name":"Apex Predator","description":"Win 5 Hangry Games matches.","metric":"hangry_wins","target":5,"catnip":10000,"xp":5000,"role":"Apex Predator","points":0},
    "nine_lives": {"name":"Nine Lives","description":"Participate in 25 completed Hangry Games.","metric":"hangry_played","target":25,"catnip":7500,"xp":3000,"points":0},
    "democracy": {"name":"Democracy in Action","description":"Cast a vote in 10 different polls.","metric":"poll_votes","target":10,"catnip":2500,"xp":1500,"points":0},
    "feeling_lucky": {"name":"Feeling Lucky","description":"Enter 10 giveaways.","metric":"giveaways_entered","target":10,"catnip":2000,"xp":1000,"points":0},
    "generous_paws": {"name":"Generous Paws","description":"Transfer a cumulative 10,000 Catnip to other members.","metric":"transferred","target":10000,"catnip":0,"xp":4000,"role":"Benefactor","points":0},
    "clocking_in": {"name":"Clocking In","description":"Collect Catnip from an income role 25 times.","metric":"income_collects","target":25,"catnip":5000,"xp":2500,"points":0},
}

ADMIN_ACHIEVEMENT = {"name":"Cinnamon's Favourite Human","description":"Manually awarded by an Administrator.","metric":"manual","target":1,"catnip":100000,"xp":50000,"role":"Cinnamon's Favourite Human","points":0}

SECRET_ACHIEVEMENTS = {
    "s1": {"name":"Cinnamon Summoned Me","description":"First person to use a Cinnamon interaction after the bot comes online.","metric":"first_interaction","target":1,"catnip":1000,"xp":500},
    "s2": {"name":"The Cat Has Spoken","description":"Get a reply from Cinnamon 10 times in AI chat.","metric":"ai_replies","target":10,"catnip":2500,"xp":1000},
    "s3": {"name":"Treat Dealer","description":"Give Cinnamon 25 treats.","metric":"treat_fed","target":25,"catnip":3000,"xp":1500},
    "s4": {"name":"Cinnamon's Therapist","description":"Use /pet 50 times.","metric":"pet_count","target":50,"catnip":5000,"xp":2000},
    "s5": {"name":"Professional Cat Whisperer","description":"Run 10 distinct Cinnamon interaction commands.","metric":"distinct_interactions","target":10,"catnip":8000,"xp":3500,"role":"Professional Cat Whisperer"},
    "s6": {"name":"Oops, All Tuna","description":"Have Tuna and 3 other different food/item types in inventory at the same time.","metric":"oops_all_tuna","target":1,"catnip":5000,"xp":2500},
    "s7": {"name":"The Economy Is Mine","description":"Hold 50,000 Catnip while owning 50+ total items.","metric":"economy_mine","target":1,"catnip":25000,"xp":10000,"role":"The Economy Is Mine"},
    "s8": {"name":"Cinnamon Knows My Name","description":"Use Cinnamon commands on 25 different calendar days.","metric":"interaction_days","target":25,"catnip":20000,"xp":7500,"role":"Cinnamon Knows My Name"},
    "s9": {"name":"Wait… You Actually Did It?","description":"Unlock 5 different achievements in a single day.","metric":"daily_achievement_unlocks","target":5,"catnip":12000,"xp":7500},
    "s10": {"name":"The Dream Has Been Archived","description":"100 Hangry Games + Level 50 + 100k lifetime Catnip + 100 Tuna.","metric":"dream_archived","target":1,"catnip":50000,"xp":30000,"role":"The Dream Has Been Archived"},
    "s11": {"name":"Midnight Snack","description":"Feed Cinnamon an item between 12:00 AM and 3:00 AM server time.","metric":"midnight_snack","target":1,"catnip":3500,"xp":1500},
}

achievement_data = {}  # (guild,user) -> persisted state
achievement_config = {}  # guild -> config
friendship_data = {}  # (guild,user) -> {points, level, history}

FRIENDSHIP_LEVELS = [
    (0, "Stranger"),
    (25, "Familiar Face"),
    (75, "Friend"),
    (200, "Trusted Human"),
    (500, "Cinnamon's Best Friend"),
    (1000, "Cinnamon's Chosen Human"),
]

def friendship_level(points):
    current=FRIENDSHIP_LEVELS[0][1]
    for threshold,name in FRIENDSHIP_LEVELS:
        if int(points)>=threshold: current=name
        else: break
    return current

def friendship_state(g,u):
    k=_key(g,u); st=friendship_data.get(k)
    if not isinstance(st,dict): st={}
    st.setdefault("points",0); st.setdefault("history",[]); st["level"]=friendship_level(st["points"])
    friendship_data[k]=st; return st

async def friendship_add(g,u,points,reason):
    if not g or not u or not points: return
    st=friendship_state(g,u); before=st["level"]; st["points"]+=int(points); st["level"]=friendship_level(st["points"])
    st["history"].append({"points":int(points),"reason":str(reason),"at":cinnamon_now().isoformat()}); st["history"]=st["history"][-100:]
    if st["level"]!=before:
        await achievement_log(g,"🐾 Cinnamon Friendship Level Up",[("User",f"<@{u}>"),("Level",st["level"]),("Friendship XP",f"{st['points']:,}")])
        await send_log(g, title="🐾 Cinnamon Friendship Level Up", category="friendship", fields=[("User",f"<@{u}> ({u})"),("Level",str(st["level"])),("Friendship XP",f"{st['points']:,}"),("Reason",reason)])
    if st["level"]!=before:
        await bd_save_data()

RARITY_ORDER = {"Common": 1, "Uncommon": 2, "Rare": 3, "Epic": 4, "Legendary": 5, "Secret": 6}
def achievement_rarity(aid, a):
    if aid in SECRET_ACHIEVEMENTS:
        return "Secret"
    if a.get("rarity"):
        return str(a["rarity"])
    target = int(a.get("target", 1) or 1)
    metric = str(a.get("metric", ""))
    if metric.startswith("compound_") or target >= 25000:
        return "Legendary"
    if target >= 5000:
        return "Epic"
    if target >= 1000:
        return "Rare"
    if target >= 100:
        return "Uncommon"
    return "Common"

_achievement_guard = set()
first_interaction_claimed = False

def _key(g,u): return (int(g),int(u))
def _state(g,u):
    k=_key(g,u); s=achievement_data.get(k)
    if not isinstance(s,dict): s={}
    s.setdefault("stats",{}); s.setdefault("unlocked",[]); s.setdefault("secret_unlocked",[]); s.setdefault("points",0); s.setdefault("showcase",[])
    s["stats"].setdefault("distinct_interactions",[]); s["stats"].setdefault("interaction_days",[]); s["stats"].setdefault("daily_unlock_dates",{}); s["stats"].setdefault("poll_ids",[])
    achievement_data[k]=s; return s

def achievement_stats(g,u):
    s=_state(g,u); return s["stats"]

def _metric(s, metric):
    v=s["stats"].get(metric,0)
    if isinstance(v,list): return len(v)
    return v

def _compound(s, metric):
    st=s["stats"]
    if metric=="compound_no_life": return int(st.get("messages",0)>=10000 and st.get("work_sessions",0)>=100)
    if metric=="compound_second_favourite": return int(st.get("quests_completed",0)>=50 and st.get("pings",0)>=500 and st.get("tuna_fed",0)>=50)
    if metric=="oops_all_tuna": return int(st.get("tuna_owned",0)>0 and st.get("items_owned",0)>=4 and st.get("distinct_item_types",0)>=4)
    if metric=="economy_mine": return int(st.get("balance",0)>=50000 and st.get("items_owned",0)>=50)
    if metric=="dream_archived": return int(st.get("hangry_played",0)>=100 and st.get("level",0)>=50 and st.get("lifetime_catnip",0)>=100000 and st.get("tuna_owned",0)>=100)
    return 0

def _value(g,u, metric):
    s=_state(g,u)
    if metric.startswith("compound_") or metric in {"oops_all_tuna","economy_mine","dream_archived"}: return _compound(s,metric)
    return _metric(s,metric)

async def _add_xp(g,u,amount):
    if not amount: return
    key=(g,u); xp_data[key]=int(xp_data.get(key,0))+int(amount)
    member=bot.get_guild(g).get_member(u) if bot.get_guild(g) else None
    if member:
        try: await sync_level_roles(member, level_from_xp(xp_data[key]))
        except Exception: pass

def _role_candidates(guild, name):
    return [r for r in guild.roles if r.name == name and not r.managed]

async def _assign_role(g,u,aid,default_role_name=None):
    guild=bot.get_guild(g)
    if not guild: return False
    member=guild.get_member(u)
    if not member: return False
    override=achievement_role_overrides.get(g,{}).get(aid)
    role=None
    if override:
        try: role=guild.get_role(int(override))
        except (TypeError,ValueError): role=None
    if role is None and default_role_name:
        roles=_role_candidates(guild,default_role_name)
        role=roles[-1] if roles else None
    if role is None: return False
    try:
        if role not in member.roles:
            await member.add_roles(role, reason="Cinnamon achievement reward")
        return True
    except discord.HTTPException: return False

async def achievement_log(g,title,fields=None):
    cfg=achievement_config.get(g,{})
    cid=cfg.get("log_channel") or category_log_channels.get(g,{}).get("achievements")
    if not cid: return
    ch=bot.get_channel(int(cid))
    if not ch: return
    try:
        e=discord.Embed(title=title,color=discord.Color.gold(),timestamp=datetime.datetime.now(datetime.timezone.utc))
        for n,v in (fields or []): e.add_field(name=n,value=str(v)[:1024],inline=True)
        await ch.send(embed=e)
    except Exception: pass

async def _unlock(g,u,aid,secret=False,reason=""):
    pool=SECRET_ACHIEVEMENTS if secret else ACHIEVEMENTS
    if aid not in pool: return False
    s=_state(g,u); key="secret_unlocked" if secret else "unlocked"
    if aid in s[key] or aid in s["unlocked"] or aid in s["secret_unlocked"]: return False
    a=pool[aid]
    s[key].append(aid); s["points"]+=int(a.get("points",0) or 0)
    guard_key=(g,u,aid)
    if guard_key in _achievement_guard: return False
    _achievement_guard.add(guard_key)
    try:
        if a.get("catnip"):
            economy_balances[(g,u)]=economy_balance(g,u)+int(a["catnip"])
        await _add_xp(g,u,int(a.get("xp",0)))
        role_ok=await _assign_role(g,u,aid,a["role"]) if a.get("role") else None
        await bd_save_data()
        await achievement_log(g,"🕵️ Secret achievement discovered" if secret else "🏆 Achievement unlocked",[
            ("User",f"<@{u}> ({u})"),("Achievement",a["name"]),("Rewards",f"+{int(a.get('catnip',0)):,} Catnip · +{int(a.get('xp',0)):,} XP · +{int(a.get('points',0))} AP"),
            ("Role",a.get("role") or "None"),("Role applied",str(role_ok) if role_ok is not None else "N/A"),("Reason",reason or a.get("description",""))])
        return True
    finally:
        _achievement_guard.discard(guard_key)

async def achievement_check_all(g,u):
    s=_state(g,u)
    for aid,a in ACHIEVEMENTS.items():
        if a.get("enabled",True) and _value(g,u,a["metric"])>=int(a["target"]): await _unlock(g,u,aid)
    for aid,a in SECRET_ACHIEVEMENTS.items():
        if a.get("enabled",True) and _value(g,u,a["metric"])>=int(a["target"]): await _unlock(g,u,aid,True)

async def achievement_record(g,u,event,value=1,**kw):
    global first_interaction_claimed
    if not g or not u: return
    s=_state(g,u); st=s["stats"]
    if event=="interaction":
        await friendship_add(g,u,5,"Cinnamon interaction")
        name=str(kw.get("name","interaction")); st["interactions"]=int(st.get("interactions",0))+int(value); st.setdefault("distinct_interactions",[])
        if name not in st["distinct_interactions"]: st["distinct_interactions"].append(name)
        today=cinnamon_now().date().isoformat(); st.setdefault("interaction_days",[])
        if today not in st["interaction_days"]: st["interaction_days"].append(today)
        if not first_interaction_claimed:
            first_interaction_claimed = True
            await _unlock(g,u,"s1",True,"First Cinnamon interaction after bot startup")
    elif event=="message":
        await friendship_add(g,u,1,"Message")
        st["messages"]=int(st.get("messages",0))+int(value); st["daily_messages"]=int(st.get("daily_messages",0))+int(value)
    elif event=="ping":
        await friendship_add(g,u,2,"Cinnamon ping")
        st["pings"]=int(st.get("pings",0))+int(value)
    elif event=="work":
        await friendship_add(g,u,2,"Work session")
        st["work_sessions"]=int(st.get("work_sessions",0))+int(value)
    elif event=="purchase": st["purchases"]=int(st.get("purchases",0))+int(value); st["spent"]=int(st.get("spent",0))+int(kw.get("spent",0))
    elif event=="feed":
        await friendship_add(g,u,10,"Fed Cinnamon")
        qty=int(value); item=str(kw.get("item","")); st["tuna_fed"]=int(st.get("tuna_fed",0))+(qty if item=="tuna" else 0); st["treat_fed"]=int(st.get("treat_fed",0))+(qty if item=="treat" else 0)
        st["fed_total"]=int(st.get("fed_total",0))+qty
        now=cinnamon_now().hour
        if 0<=now<3: st["midnight_snack"]=1
    elif event=="catnip_earned": st["lifetime_catnip"]=int(st.get("lifetime_catnip",0))+int(value)
    elif event=="give": st["transferred"]=int(st.get("transferred",0))+int(value); st["give_count"]=int(st.get("give_count",0))+1
    elif event=="collect": st["income_collects"]=int(st.get("income_collects",0))+1
    elif event=="poll_vote":
        st.setdefault("poll_ids",[])
        pid=str(kw.get("poll_id", ""))
        if pid and pid not in st["poll_ids"]: st["poll_ids"].append(pid)
        st["poll_ids"]=st["poll_ids"][-500:]
        st["poll_votes"]=len(st["poll_ids"])
    elif event=="giveaway":
        await friendship_add(g,u,2,"Giveaway entry")
        st["giveaways_entered"]=int(st.get("giveaways_entered",0))+1
    elif event=="ai_reply":
        await friendship_add(g,u,5,"Cinnamon AI reply")
        st["ai_replies"]=int(st.get("ai_replies",0))+1
    elif event=="pet":
        await friendship_add(g,u,8,"Pet Cinnamon")
        st["pet_count"]=int(st.get("pet_count",0))+int(value)
    elif event=="level": st["level"]=max(int(st.get("level",0)),int(value))
    elif event=="hangry":
        for k in ("hangry_kills","hangry_wins","hangry_played"): st.setdefault(k,0)
        st["hangry_kills"]+=int(kw.get("kills",0)); st["hangry_played"]+=1; st["hangry_wins"]+=int(kw.get("win",0))
    elif event=="inventory":
        inv=economy_inventory_for(g,u); st["items_owned"]=sum(max(0,int(v)) for v in inv.values()); st["tuna_owned"]=int(inv.get("tuna",0)); st["distinct_item_types"]=sum(1 for v in inv.values() if int(v)>0)
    elif event=="balance": st["balance"]=economy_balance(g,u)
    elif event=="daily_unlock":
        date=str(kw.get("date")); ds=st.setdefault("daily_unlock_dates",{}); ds[date]=int(ds.get(date,0))+int(value)
        if ds[date]>=5: st["daily_achievement_unlocks"]=1
    await achievement_check_all(g,u)

@bot.listen("on_message")
async def achievement_message_listener(message):
    if not message.guild or message.author.bot: return
    clean=(message.content or "").strip()
    if clean:
        await achievement_record(message.guild.id,message.author.id,"message",1)
        await quest_event(message.guild.id,message.author.id,"message",1)
    if bot.user and bot.user in message.mentions and not message.mention_everyone:
        await achievement_record(message.guild.id,message.author.id,"ping",1)
        await quest_event(message.guild.id,message.author.id,"ping",1)

@bot.listen("on_app_command_completion")
async def achievement_command_listener(interaction, command):
    if not interaction.guild: return
    gid,uid=interaction.guild.id,interaction.user.id
    q=getattr(command,"qualified_name",getattr(command,"name","")); parts=q.split(); root=parts[0]
    ns=getattr(interaction,"namespace",None)
    if root=="economy":
        action=parts[1] if len(parts)>1 else ""
        # Economy state-changing actions already call achievement_record/quest_event
        # directly so quantities and Catnip amounts are exact. This listener only
        # handles read-only commands that a quest explicitly asks the member to use.
        if action=="balance":
            await achievement_record(gid,uid,"balance")
            await quest_event(gid,uid,"balance_cmd",1)
        elif action=="feed":
            # Feed is handled by economy.py; this records the interaction metric only.
            await achievement_record(gid,uid,"interaction",1,name="/economy feed")
    elif root in {"pet","treat","nap"} or root.startswith("cinnamon"):
        await achievement_record(gid,uid,"interaction",1,name=q)
        if root=="pet":
            await achievement_record(gid,uid,"pet")
            await quest_event(gid,uid,"pet",1)
        elif root=="nap":
            await quest_event(gid,uid,"nap",1)
        else:
            await quest_event(gid,uid,"interactions",1)
    elif root=="rank":
        await achievement_record(gid,uid,"interaction",1,name="/rank")
        await quest_event(gid,uid,"rank_cmd",1)
    await achievement_record(gid,uid,"balance")

# Member commands
achievement_group=app_commands.Group(name="achievement",description="Cinnamon's achievement system")
class AchievementListView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int, page: int = 0):
        super().__init__(timeout=300)
        self.guild_id, self.user_id, self.page = guild_id, user_id, page
        self._refresh()

    def _refresh(self):
        ids=list(ACHIEVEMENTS.items()); per=6; pages=max(1,(len(ids)+per-1)//per)
        self.page=max(0,min(self.page,pages-1)); self.clear_items()
        prev=discord.ui.Button(label="Previous Page",emoji="◀️",style=discord.ButtonStyle.secondary,disabled=self.page==0,row=0)
        nxt=discord.ui.Button(label="Next Page",emoji="▶️",style=discord.ButtonStyle.primary,disabled=self.page>=pages-1,row=0)
        prev.callback=self._prev; nxt.callback=self._next; self.add_item(prev); self.add_item(nxt)

    async def _guard(self,interaction):
        if interaction.user.id!=self.user_id:
            await interaction.response.send_message("🐾 This achievement page belongs to the person who opened it.",ephemeral=True); return False
        return True
    async def _prev(self,interaction):
        if not await self._guard(interaction): return
        self.page-=1; self._refresh(); await interaction.response.edit_message(embed=achievement_list_embed(self.guild_id,self.user_id,self.page),view=self)
    async def _next(self,interaction):
        if not await self._guard(interaction): return
        self.page+=1; self._refresh(); await interaction.response.edit_message(embed=achievement_list_embed(self.guild_id,self.user_id,self.page),view=self)


def achievement_list_embed(guild_id,user_id,page=0):
    state=_state(guild_id,user_id); unlocked=set(state["unlocked"]); ids=list(ACHIEVEMENTS.items()); per=6; pages=max(1,(len(ids)+per-1)//per); page=max(0,min(page,pages-1)); chunk=ids[page*per:(page+1)*per]
    e=cinnamon_embed("🏆 Achievements","Track your milestones. Secret achievements stay hidden until discovered.",color=CINNAMON_GOLD,user=bot.get_guild(guild_id).get_member(user_id) if bot.get_guild(guild_id) else None,footer=cinnamon_page_footer("Achievements",page+1,pages,f"{len(unlocked)}/{len(ACHIEVEMENTS)} unlocked"))
    for aid,a in chunk:
        val=_value(guild_id,user_id,a["metric"]); target=int(a["target"]); shown=min(val,target); status="✅" if aid in unlocked else "▫️"
        bar=cinnamon_progress_bar(shown,target,8)
        e.add_field(name=f"{status} {a['name']}",value=f"{bar} **{shown:,}/{target:,}**\n{a['description']}  ·  *{achievement_rarity(aid,a)}*",inline=False)
    return cinnamon_polish_embed(e)

@achievement_group.command(name="list",description="View normal achievements and progress")
@app_commands.guild_only()
async def achievement_list_cmd(interaction):
    view=AchievementListView(interaction.guild.id,interaction.user.id,0)
    await interaction.response.send_message(embed=achievement_list_embed(interaction.guild.id,interaction.user.id,0),view=view)

@achievement_group.command(name="profile",description="View your complete achievement profile")
@app_commands.guild_only()
async def achievement_profile_cmd(interaction):
    s=_state(interaction.guild.id,interaction.user.id); st=s["stats"]
    e=cinnamon_embed(f"🏆 {interaction.user.display_name}","Achievement profile and lifetime progress.",color=CINNAMON_GOLD,user=interaction.user,footer="Cinnamon • Achievement Profile")
    e.add_field(name="🏆 Achievements",value=f"**{len(s['unlocked'])}/{len(ACHIEVEMENTS)}** unlocked\n**{s['points']:,}** AP",inline=True)
    e.add_field(name="🕵️ Secrets",value=f"**{len(s['secret_unlocked'])}** discovered",inline=True)
    e.add_field(name="🐾 Friendship",value=f"**{friendship_state(interaction.guild.id,interaction.user.id)['level']}**\n{friendship_state(interaction.guild.id,interaction.user.id)['points']:,} XP",inline=True)
    e.add_field(name="📊 Activity",value=f"Messages **{int(st.get('messages',0)):,}**\nWork **{int(st.get('work_sessions',0)):,}**\nInteractions **{int(st.get('interactions',0)):,}**",inline=True)
    e.add_field(name="🎯 Progress",value=f"Quests completed **{int(st.get('quests_completed',0)):,}**\nLifetime Catnip **{int(st.get('lifetime_catnip',0)):,}",inline=True)
    shown=[]
    for aid in s.get("showcase",[]):
        a=ACHIEVEMENTS.get(aid) or SECRET_ACHIEVEMENTS.get(aid)
        if a: shown.append(f"{a['name']} · {achievement_rarity(aid,a)}")
    e.add_field(name="Showcase",value="\n".join(shown) if shown else "Not set — use `/achievement showcase-set`",inline=False)
    await interaction.response.send_message(embed=cinnamon_polish_embed(e))

@achievement_group.command(name="friendship",description="View your Cinnamon friendship level")
@app_commands.guild_only()
async def achievement_friendship_cmd(interaction):
    fs=friendship_state(interaction.guild.id,interaction.user.id)
    nxt=next(((t,n) for t,n in FRIENDSHIP_LEVELS if t>fs["points"]),None)
    progress=f"{fs['points']:,} Friendship XP"
    if nxt: progress += f"\nNext: **{nxt[1]}** at **{nxt[0]:,}** XP"
    e=discord.Embed(title=f"🐾 {interaction.user.display_name}'s Cinnamon Friendship",description=f"**{fs['level']}**\n{progress}",color=discord.Color.orange())
    e.add_field(name="How to gain Friendship XP",value="Pet Cinnamon, feed Cinnamon, use Cinnamon interactions, ping Cinnamon, work, participate in community activities, and get successful Cinnamon AI replies.",inline=False)
    await interaction.response.send_message(embed=cinnamon_polish_embed(e))

@achievement_group.command(name="showcase",description="View your five featured achievements")
@app_commands.guild_only()
async def achievement_showcase_cmd(interaction):
    s=_state(interaction.guild.id,interaction.user.id); ids=s.get("showcase",[])
    if not ids:
        return await cinnamon_send(interaction, "🏆 Your showcase is empty. Use `/achievement showcase-set` to feature up to 5 achievements.",ephemeral=True)
    lines=[]
    for i,aid in enumerate(ids,1):
        a=ACHIEVEMENTS.get(aid) or SECRET_ACHIEVEMENTS.get(aid)
        if a: lines.append(f"**{i}.** {a['name']} · **{achievement_rarity(aid,a)}**")
    e=discord.Embed(title=f"🏆 {interaction.user.display_name}'s Achievement Showcase",description="\n".join(lines),color=discord.Color.gold())
    await interaction.response.send_message(embed=cinnamon_polish_embed(e))

@achievement_group.command(name="showcase-set",description="Set up to five achievements for your profile showcase")
@app_commands.guild_only()
@app_commands.describe(slot1="First featured achievement",slot2="Second featured achievement",slot3="Third featured achievement",slot4="Fourth featured achievement",slot5="Fifth featured achievement")
async def achievement_showcase_set_cmd(interaction, slot1:str=None, slot2:str=None, slot3:str=None, slot4:str=None, slot5:str=None):
    s=_state(interaction.guild.id,interaction.user.id); unlocked=set(s.get("unlocked",[]))|set(s.get("secret_unlocked",[]))
    slots=[x.strip().lower() for x in (slot1,slot2,slot3,slot4,slot5) if x and x.strip()]
    if len(slots)>5: slots=slots[:5]
    chosen=[]; errors=[]
    pool={**ACHIEVEMENTS,**SECRET_ACHIEVEMENTS}
    for term in slots:
        found=next((aid for aid,a in pool.items() if aid.lower()==term or a["name"].lower()==term),None)
        if not found: errors.append(term); continue
        if found not in unlocked: errors.append(f"{term} (locked)"); continue
        if found not in chosen: chosen.append(found)
    if errors:
        return await cinnamon_send(interaction, "❌ I couldn't use: " + ", ".join(errors) + ". Only achievements you have unlocked can be showcased.",ephemeral=True)
    s["showcase"]=chosen
    await bd_save_data()
    await cinnamon_send(interaction, f"🏆 Showcase updated with **{len(chosen)}** achievement(s).",ephemeral=True)

@achievement_group.command(name="showcase-clear",description="Clear your achievement showcase")
@app_commands.guild_only()
async def achievement_showcase_clear_cmd(interaction):
    _state(interaction.guild.id,interaction.user.id)["showcase"]=[]
    await bd_save_data()
    await cinnamon_send(interaction, "🧹 Your achievement showcase is now empty.",ephemeral=True)

@achievement_group.command(name="secret",description="View secret achievements you have discovered")
@app_commands.guild_only()
async def achievement_secret_cmd(interaction):
    s=_state(interaction.guild.id,interaction.user.id); ids=s["secret_unlocked"]
    text="\n".join(f"🕵️ **{SECRET_ACHIEVEMENTS[i]['name']}** — {SECRET_ACHIEVEMENTS[i]['description']}" for i in ids if i in SECRET_ACHIEVEMENTS) or "No secret achievements discovered yet."
    await interaction.response.send_message(embed=discord.Embed(title="🕵️ Discovered Secrets",description=text[:4000],color=discord.Color.purple()))

@achievement_group.command(name="info",description="View an achievement's details")
@app_commands.guild_only()
async def achievement_info_cmd(interaction, achievement:str):
    term=achievement.lower().strip(); pool={**ACHIEVEMENTS,**SECRET_ACHIEVEMENTS}; found=None
    for aid,a in pool.items():
        if aid.lower()==term or a["name"].lower()==term: found=(aid,a); break
    if not found: return await cinnamon_send(interaction, "❌ Achievement not found.",ephemeral=True)
    aid,a=found; secret=aid in SECRET_ACHIEVEMENTS; s=_state(interaction.guild.id,interaction.user.id)
    if secret and aid not in s["secret_unlocked"]: return await cinnamon_send(interaction, "🕵️ **Secret Achievement** — this achievement's details are hidden until you discover it.",ephemeral=True)
    val=_value(interaction.guild.id,interaction.user.id,a["metric"])
    e=discord.Embed(title=f"🏆 {a['name']}",description=a["description"],color=discord.Color.purple() if secret else discord.Color.gold())
    e.add_field(name="Rarity",value=achievement_rarity(aid,a)); e.add_field(name="Progress",value=f"{min(val,int(a['target'])):,}/{int(a['target']):,}")
    e.add_field(name="Reward",value=f"{int(a.get('catnip',0)):,} Catnip + {int(a.get('xp',0)):,} XP + {int(a.get('points',0))} AP" + (f" + {a['role']} role" if a.get('role') else ""))
    await interaction.response.send_message(embed=cinnamon_polish_embed(e))

@achievement_group.command(name="leaderboard",description="Achievement Points leaderboard")
@app_commands.guild_only()
@app_commands.describe(page="Leaderboard page")
async def achievement_leaderboard_cmd(interaction, page:int=1):
    rows=[]
    for (g,u),s in achievement_data.items():
        if g==interaction.guild.id: rows.append((int(s.get("points",0)),u))
    rows.sort(reverse=True); page=max(1,int(page)); start=(page-1)*10; chunk=rows[start:start+10]; lines=[]
    for i,(p,u) in enumerate(chunk,start+1): lines.append(f"**{i}.** <@{u}> — **{p:,} AP**")
    e=discord.Embed(title="🏆 Achievement Leaderboard",description="\n".join(lines) or "No achievement points yet.",color=discord.Color.gold()); e.set_footer(text=f"Page {page} • Total members: {len(rows)}")
    await interaction.response.send_message(embed=cinnamon_polish_embed(e))

@achievement_group.command(name="setup",description="Admin: configure achievement logging and tracking")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_setup_cmd(interaction, channel:discord.TextChannel|None=None):
    cfg=achievement_config.setdefault(interaction.guild.id,{})
    if channel: cfg["log_channel"]=channel.id; category_log_channels.setdefault(interaction.guild.id,{})["achievements"]=channel.id
    cfg["enabled"]=True; await bd_save_data()
    await cinnamon_send(interaction, f"✅ Achievement system enabled. Logs: {channel.mention if channel else ('<#'+str(cfg.get('log_channel'))+'>' if cfg.get('log_channel') else 'not configured')}.",ephemeral=True)

@achievement_group.command(name="setup-status",description="Admin: show achievement system status")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_setup_status_cmd(interaction):
    cfg=achievement_config.get(interaction.guild.id,{})
    await cinnamon_send(interaction, f"🏆 Enabled: **{cfg.get('enabled',True)}**\n🧾 Log channel: {('<#'+str(cfg['log_channel'])+'>') if cfg.get('log_channel') else 'Not configured'}\n🏆 Definitions: **{len(ACHIEVEMENTS)}** + **{len(SECRET_ACHIEVEMENTS)}** secrets",ephemeral=True)

@achievement_group.command(name="award",description="Admin: manually award an achievement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_award_cmd(interaction, member:discord.Member, achievement:str):
    pool={**ACHIEVEMENTS,"admin":ADMIN_ACHIEVEMENT,**SECRET_ACHIEVEMENTS}; aid=None
    for k,a in pool.items():
        if k.lower()==achievement.lower() or a["name"].lower()==achievement.lower(): aid=k; break
    if not aid: return await cinnamon_send(interaction, "❌ Achievement not found.",ephemeral=True)
    secret=aid in SECRET_ACHIEVEMENTS; ok=await _unlock(interaction.guild.id,member.id,aid,secret,"Manual administrator award") if aid!="admin" else await _unlock_custom_admin(interaction.guild.id,member.id)
    await cinnamon_send(interaction, "✅ Achievement awarded." if ok else "⚠️ That achievement is already unlocked.",ephemeral=True)

async def _unlock_custom_admin(g,u):
    s=_state(g,u)
    if "admin_favourite" in s["unlocked"]: return False
    a=ADMIN_ACHIEVEMENT; s["unlocked"].append("admin_favourite")
    economy_balances[(g,u)]=economy_balance(g,u)+a["catnip"]; await _add_xp(g,u,a["xp"]); await _assign_role(g,u,"admin_favourite",a["role"]); await bd_save_data(); await achievement_log(g,"👑 Admin achievement awarded",[("User",f"<@{u}>"),("Achievement",a["name"])])
    return True

@achievement_group.command(name="revoke",description="Admin: revoke an achievement (rewards are not clawed back)")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_revoke_cmd(interaction, member:discord.Member, achievement:str):
    s=_state(interaction.guild.id,member.id); aid=next((k for k,a in {**ACHIEVEMENTS,**SECRET_ACHIEVEMENTS}.items() if k.lower()==achievement.lower() or a["name"].lower()==achievement.lower()),None)
    if not aid: return await cinnamon_send(interaction, "❌ Achievement not found.",ephemeral=True)
    if aid in s["unlocked"]: s["unlocked"].remove(aid)
    if aid in s["secret_unlocked"]: s["secret_unlocked"].remove(aid)
    await bd_save_data(); await cinnamon_send(interaction, "✅ Achievement revoked. Previously paid Catnip/XP was not removed.",ephemeral=True)

@achievement_group.command(name="roles",description="Admin: list configured achievement role names")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_roles_cmd(interaction):
    names=sorted({a["role"] for a in list(ACHIEVEMENTS.values())+list(SECRET_ACHIEVEMENTS.values())+[ADMIN_ACHIEVEMENT] if a.get("role")})
    await cinnamon_send(interaction, "🎖️ Achievement role names:\n"+"\n".join(f"• {n}" for n in names),ephemeral=True)

@achievement_group.command(name="stats",description="Admin: achievement statistics")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_stats_cmd(interaction):
    total=sum(len(s.get("unlocked",[])) for (g,_),s in achievement_data.items() if g==interaction.guild.id); secrets=sum(len(s.get("secret_unlocked",[])) for (g,_),s in achievement_data.items() if g==interaction.guild.id)
    await cinnamon_send(interaction, f"🏆 Unlocks: **{total}**\n🕵️ Secret discoveries: **{secrets}**\n👥 Tracked users: **{sum(1 for g,_ in achievement_data if g==interaction.guild.id)}**",ephemeral=True)

@achievement_group.command(name="user",description="Admin: view a member's achievement profile")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_user_cmd(interaction, member:discord.Member):
    s=_state(interaction.guild.id,member.id); await cinnamon_send(interaction, f"🏆 {member.mention}: **{len(s['unlocked'])}** achievements, **{len(s['secret_unlocked'])}** secrets, **{s['points']:,} AP**",ephemeral=True)

@achievement_group.command(name="backup",description="Admin: export achievement data")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_backup_cmd(interaction):
    payload={"type":"cinnamon_achievement_snapshot","guild_id":interaction.guild.id,"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"data":{f"{g}:{u}":s for (g,u),s in achievement_data.items() if g==interaction.guild.id},"config":achievement_config.get(interaction.guild.id,{}),"friendship":{str(u):v for (g,u),v in friendship_data.items() if g==interaction.guild.id}}
    raw=json.dumps(payload,ensure_ascii=False,indent=2).encode(); await interaction.response.send_message(file=discord.File(io.BytesIO(raw),filename=f"cinnamon_achievements_{interaction.guild.id}.json"),ephemeral=True); await achievement_log(interaction.guild.id,"💾 Achievement backup created",[("Created by",str(interaction.user))])

@achievement_group.command(name="recover",description="Admin: recover achievement data from an uploaded JSON snapshot")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(snapshot="The JSON file produced by /achievement backup")
async def achievement_recover_cmd(interaction: discord.Interaction, snapshot: discord.Attachment):
    if snapshot.size and snapshot.size > 2_000_000:
        return await cinnamon_send(interaction, "❌ Snapshot is too large. Please upload a JSON snapshot under 2 MB.",ephemeral=True)
    if not snapshot.filename.lower().endswith(".json"):
        return await cinnamon_send(interaction, "❌ Please upload the JSON file produced by `/achievement backup`.",ephemeral=True)
    try:
        raw = await snapshot.read()
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, discord.HTTPException, OSError):
        return await cinnamon_send(interaction, "❌ I couldn't read that snapshot as valid UTF-8 JSON.",ephemeral=True)
    if not isinstance(payload, dict) or payload.get("type") != "cinnamon_achievement_snapshot":
        return await cinnamon_send(interaction, "❌ That file is not a Cinnamon achievement snapshot.",ephemeral=True)
    try:
        source_guild = int(payload.get("guild_id"))
    except (TypeError, ValueError):
        return await cinnamon_send(interaction, "❌ The snapshot has no valid guild ID.",ephemeral=True)
    if source_guild != interaction.guild.id:
        return await cinnamon_send(interaction, "❌ That snapshot belongs to a different server.",ephemeral=True)
    data = payload.get("data")
    if not isinstance(data, dict):
        return await cinnamon_send(interaction, "❌ The snapshot has no valid achievement data.",ephemeral=True)

    restored = 0
    for key, state in data.items():
        try:
            gid, uid = (int(x) for x in str(key).split(":", 1))
        except (TypeError, ValueError):
            continue
        if gid != interaction.guild.id or not isinstance(state, dict):
            continue
        achievement_data[(gid, uid)] = state
        restored += 1
    cfg = payload.get("config")
    if isinstance(cfg, dict):
        achievement_config[interaction.guild.id] = cfg
    for uid,state in (payload.get("friendship") or {}).items():
        try: friendship_data[(interaction.guild.id,int(uid))]=state
        except (TypeError,ValueError): pass
    await bd_save_data()
    await achievement_log(interaction.guild.id,"♻️ Achievement data recovered",[("Recovered users",str(restored)),("File",snapshot.filename),("Recovered by",str(interaction.user))])
    await cinnamon_send(interaction, f"♻️ Recovered achievement data for **{restored}** tracked user(s).",ephemeral=True)

try: bot.tree.add_command(achievement_group)
except Exception: pass

# Backwards compatibility helpers used by old modules, but no old economy quest system is registered.
ECONOMY_ACHIEVEMENTS=ACHIEVEMENTS
economy_achievements=achievement_data
async def unlock_economy_achievement(guild_id,user_id,achievement_id,reason=""): return await _unlock(guild_id,user_id,achievement_id,False,reason)
async def check_economy_achievements(guild_id,user_id,**kwargs): await achievement_check_all(guild_id,user_id); return []

# Achievement definitions and role overrides are managed from the Cinnamon dashboard.
# Discord does not register the old admin create/edit/delete/enable/disable surface.
# Persist custom definitions and role overrides by extending the normal state serializer.
_original_bd_encode = _bd_encode
# We cannot replace the global persistence function wholesale here; dashboard_runtime
# reads these globals, and the existing serializer is extended below through a small
# wrapper installed before the next save.
try:
    _original_encode_func = _bd_encode
    def _bd_encode_with_achievements():
        data=_original_encode_func()
        data["achievement_definitions"]={"normal":ACHIEVEMENTS,"secret":SECRET_ACHIEVEMENTS}
        data["achievement_role_overrides"]={str(g):v for g,v in achievement_role_overrides.items()}
        return data
    _bd_encode=_bd_encode_with_achievements
except Exception: pass


try:
    _original_bd_decode = _bd_decode
    def _bd_decode_with_achievements(raw):
        _original_bd_decode(raw)
        defs=raw.get("achievement_definitions",{}) if isinstance(raw,dict) else {}
        if isinstance(defs,dict):
            for aid,a in defs.get("normal",{}).items():
                if aid not in ACHIEVEMENTS: ACHIEVEMENTS[aid]=a
            for aid,a in defs.get("secret",{}).items():
                if aid not in SECRET_ACHIEVEMENTS: SECRET_ACHIEVEMENTS[aid]=a
        achievement_role_overrides.clear()
        for g,v in (raw.get("achievement_role_overrides",{}) if isinstance(raw,dict) else {}).items():
            try: achievement_role_overrides[int(g)]={str(a):int(r) for a,r in v.items()}
            except Exception: pass
    _bd_decode=_bd_decode_with_achievements
except Exception: pass
