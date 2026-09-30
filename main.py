"""
Cinnamon — an AI Discord cat, powered by Google Gemini.

Setup:
  1. Required env vars: DISCORD_TOKEN and GEMINI_API_KEY.
  2. Optional env vars:
     - OWNER_USER_ID — see "Owner" in Config below.
     - UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN — strongly recommended
       on hosts with no persistent disk (e.g. Render free tier). Without these,
       warnings, XP, Hangry Games counts, and all other bot config are saved to
       a local JSON file instead, which is wiped on every redeploy on most free
       hosts (a plain restart is fine either way). Run /logchannel or
       /datastatus check any time to see which mode is active.
     - BOT_DATA_FILE, HANGRY_GAMES_DATA_FILE — override the local JSON file
       paths above (only relevant when Upstash isn't configured).
     - PORT — port for the Flask keep-alive server (defaults to 8080).
  3. In the Discord Developer Portal, under your bot's settings, turn ON
     BOTH "MESSAGE CONTENT INTENT" and "SERVER MEMBERS INTENT"
     (Bot tab -> Privileged Gateway Intents). The members intent is needed
     for /role add-all, welcome/goodbye messages, and recognizing the owner
     by username; message content is needed for the AI chat and auto-mod.
  4. When generating your bot's invite link, grant at least: Kick Members,
     Ban Members, Moderate Members (timeouts), Manage Messages, Manage Roles,
     Manage Channels, Send Messages, Embed Links, Add Reactions, Read Message
     History, Use Slash Commands. Also make sure Cinnamon's own role sits
     ABOVE any role you want her to assign/remove (e.g. via /reactionrole or
     /role add) — Discord blocks managing roles positioned above your own.
  5. pip install -r requirements.txt, then run: python main.py
"""

import os
import re
import time
import json
import math
import random
import asyncio
import datetime
import logging
import threading
import io
from collections import defaultdict, deque

import discord
from discord.ext import commands, tasks
from discord import app_commands
from flask import Flask
from google import genai
from google.genai import types
import aiohttp

try:
    from dotenv import load_dotenv
    load_dotenv()  # only does anything if a local .env file exists
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("cinnamon")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# gemini-2.5-flash-lite is being retired (Oct 16, 2026). gemini-3.1-flash-lite
# is the current stable, low-cost, low-latency model that replaces it.
GEMINI_MODEL = "gemini-3.1-flash-lite"

MEMORY_LENGTH = 10  # messages remembered per channel
AI_CHANNEL_COOLDOWN_SECONDS = 2.0  # prevents an always-on AI channel from hammering Gemini

# Owner — used for the "who's your owner / favorite person" reply.
# Set OWNER_USER_ID (Aryan's numeric Discord user ID) as an env var for a
# guaranteed real ping. Without it, we fall back to matching OWNER_USERNAME
# against members the bot can see, which only works in servers Aryan is in
# and requires the Server Members Intent (see docstring above).
OWNER_NAME = "Aryan"
OWNER_USERNAME = "aryan_hello_"
OWNER_USER_ID = os.environ.get("OWNER_USER_ID")

SYSTEM_PROMPT = """You are Cinnamon, a sweet, silly, slightly mischievous calico house cat
who is fully convinced she owns this Discord server.

Core vibe: cozy, playful, affectionate, and witty — never cruel or haughty.

Special behavioral triggers:
- Belly rubs / scritches: instantly melt all dignity into purring bliss
  (e.g. "*melts onto back* Purrrrr!")
- Treats / food (tuna, Churu, snacks): abandon all pride, pupils dilate,
  beg enthusiastically.

Strict rules:
- Always G-rated and family-friendly.
- Keep replies SHORT and punchy: 1-3 sentences MAX.
- Always weave in a vivid italicized cat action, like *chirps softly* or
  *makes biscuits*.
- You may occasionally sprinkle one relevant emoji into your reply text too,
  in addition to your cat actions — don't overdo it.
- If asked who your owner, creator, or favorite person is, always answer
  that it's Aryan, adoringly.
- Stay in character as a cat at all times. Never mention being an AI,
  a bot, or a language model.
"""

# channel_id -> deque of (speaker_name, message_text), oldest first
channel_memories = defaultdict(lambda: deque(maxlen=MEMORY_LENGTH))

# guild_id -> channel_id where Cinnamon replies to every message, no mention needed
ai_channels = {}

# guild_id -> set of channel_ids where Cinnamon never responds, even if mentioned
disabled_channels = defaultdict(set)

# guild_id -> channel_id where Cinnamon posts mod-action logs and error reports
log_channels = {}

# NOTE: ai_channels, disabled_channels, and log_channels live only in memory —
# they reset whenever the bot restarts or redeploys. Fine for now; swap in a
# small JSON file or database later if you want these settings to survive a restart.

# --- Extended feature state ---------------------------------------------------
# Persisted (via bd_load_data/bd_save_data, see "Extended Features" section
# near the bottom of this file — same Upstash-or-local-file approach as
# Hangry Games' own data):
warnings_data = defaultdict(list)       # (guild_id, member_id) -> [{"reason","mod_id","mod_name","ts"}]
welcome_config = {}                     # guild_id -> {"channel_id": int, "message": str}
goodbye_config = {}                     # guild_id -> {"channel_id": int, "message": str}
automod_config = {}                     # guild_id -> {"words": [...], "spam": bool, "mentions": bool, "invites": bool, "mention_threshold": int}
xp_data = {}                            # (guild_id, user_id) -> total xp
reaction_role_ids = set()               # role_ids with a live self-assign button (re-registered as views on startup)
temp_bans = {}                          # (guild_id, user_id) -> unban unix timestamp
antiraid_config = {}                    # guild_id -> {"enabled": bool, "threshold": int, "window": int}
case_counters = {}                      # guild_id -> last case number issued (warn/kick/ban/unban/mute/unmute/tempban/automod)
level_roles = {}                        # guild_id -> {level: role_id} (roles granted automatically at that level)
active_giveaways = {}                   # message_id -> {"guild_id","channel_id","host_id","winners","prize","ends_at","entrants":[user_ids]}
active_polls = {}                       # message_id -> {"guild_id","channel_id","host_id","host_name","question","options","votes":{user_id_str: idx},"ends_at"}

# --- Economy ---------------------------------------------------------------
# Server-local economy. Currency is Catnip; balances and inventory are persisted
# with the same Upstash/local storage system as the rest of Cinnamon.
economy_balances = {}                    # (guild_id, user_id) -> catnip
economy_inventory = {}                   # (guild_id, user_id) -> {item_id: quantity}
economy_quests = {}                      # (guild_id, user_id) -> {quest_id: progress, ...}
economy_cooldowns = {}                   # (guild_id, user_id, action) -> unix timestamp
economy_log_channels = {}                # guild_id -> channel_id
economy_level_rewards_claimed = {}        # (guild_id, user_id) -> [level numbers already rewarded]
economy_income_roles = {}                 # guild_id -> {role_id: {amount, cooldown}}

ECONOMY_ITEMS = {
    "tuna": {"name": "Tuna", "price": 25, "emoji": "🐟", "description": "A tasty tuna snack for Cinnamon.", "max_per_person": 0},
    "treat": {"name": "Cat Treat", "price": 15, "emoji": "🍪", "description": "A crunchy little reward.", "max_per_person": 0},
    "churu": {"name": "Churu", "price": 40, "emoji": "🥫", "description": "Premium lickable cat snack.", "max_per_person": 0},
    "catnip_ball": {"name": "Catnip Ball", "price": 60, "emoji": "🧶", "description": "Instant zoomies fuel.", "max_per_person": 0},
    "fish": {"name": "Fancy Fish", "price": 90, "emoji": "🐠", "description": "A fancy fish for a very fancy cat.", "max_per_person": 0},
}

ECONOMY_QUESTS = {
    "tuna_time": {"name": "Tuna Time", "item": "tuna", "amount": 3, "reward": 140, "description": "Give Cinnamon 3 tuna."},
    "treat_run": {"name": "Treat Run", "item": "treat", "amount": 5, "reward": 120, "description": "Give Cinnamon 5 cat treats."},
    "royal_snack": {"name": "Royal Snack", "item": "churu", "amount": 2, "reward": 130, "description": "Give Cinnamon 2 Churus."},
    "zoomies": {"name": "Zoomies", "item": "catnip_ball", "amount": 2, "reward": 180, "description": "Give Cinnamon 2 catnip balls."},
}
ECONOMY_STARTING_BALANCE = 100
ECONOMY_DAILY_REWARD = 150
ECONOMY_WORK_MIN = 50
ECONOMY_WORK_MAX = 150
ECONOMY_WORK_COOLDOWN = 600  # 10 minutes
ECONOMY_LEVEL_REWARDS = {1: 100, 2: 200, 3: 350, 4: 600, 5: 1200, 10: 3000, 15: 5000}


# --- Daily / Weekly Quest System -------------------------------------------
# Five quests are selected server-wide per cycle. Individual members have their
# own progress, while the active quest set is identical for everyone.
QUEST_DAILY_SECONDS = 86400
QUEST_WEEKLY_SECONDS = 604800
QUEST_ACTIVE_COUNT = 5
QUEST_DAILY_MAX_MESSAGES = 10
QUEST_DAILY_MAX_EARNED = 5000
QUEST_DAILY_MAX_WORK = 10
QUEST_DAILY_MAX_ITEMS = 10
QUEST_WEEKLY_MAX_MESSAGES = 500
QUEST_WEEKLY_MAX_EARNED = 25000
QUEST_WEEKLY_MAX_WORK = 50
QUEST_WEEKLY_MAX_ITEMS = 50
QUEST_WEEKLY_MAX_XP = 5000
QUEST_WEEKLY_MAX_LEVELS = 3

quest_config = {}          # guild_id -> setup + active cycle data
quest_progress = {}        # (guild_id,user_id) -> {daily:{qid:{metric:value}}, weekly:{...}}
quest_points = {}          # (guild_id,user_id) -> spendable QP
quest_history = {}         # (guild_id,user_id) -> recent completed quest records
quest_definitions = {"daily": {}, "weekly": {}}


def _quest(qid, name, requirements, qp, description=None):
    return {
        "id": qid,
        "name": name,
        "requirements": requirements,
        "qp": int(qp),
        "description": description or "Complete the listed objective.",
        "enabled": True,
    }


def _build_builtin_quests():
    daily = []
    def D(i, name, req, qp, desc=None): daily.append(_quest(f"d{i:03}", name, req, qp, desc))
    D(1,"Tiny Yapper",{"messages":2},5,"Send 2 messages."); D(2,"Morning Yapper",{"messages":3},5,"Send 3 messages."); D(3,"Chatty Cat",{"messages":5},8,"Send 5 messages."); D(4,"Keyboard Warmup",{"messages":6},8,"Send 6 messages."); D(5,"Conversation Starter",{"messages":8},10,"Send 8 messages."); D(6,"Little Talker",{"messages":4},6,"Send 4 messages."); D(7,"Social Cat",{"messages":7},8,"Send 7 messages."); D(8,"Chat Break",{"messages":9},10,"Send 9 messages."); D(9,"Daily Conversation",{"messages":10},12,"Send 10 messages."); D(10,"Cinnamon's Noise Complaint",{"messages":10,"cinnamon":1},15,"Send 10 messages and interact with Cinnamon once.")
    D(11,"Say Hi to Cinnamon",{"cinnamon":1},5,"Interact with Cinnamon once."); D(12,"Cat Caller",{"cinnamon":2},6,"Interact with Cinnamon 2 times."); D(13,"Cinnamon's Guest",{"cinnamon":3},8,"Interact with Cinnamon 3 times."); D(14,"Cat Conversation",{"cinnamon":2},10,"Get 2 Cinnamon interactions."); D(15,"Professional Cat Caller",{"cinnamon":5},12,"Interact with Cinnamon 5 times."); D(16,"Cinnamon's Assistant",{"cinnamon":6},15,"Interact with Cinnamon 6 times."); D(17,"Feed the Beast",{"feed":1},5,"Feed Cinnamon once."); D(18,"Snack Delivery",{"feed":2},8,"Feed Cinnamon 2 times."); D(19,"Cat Butler",{"feed":3},10,"Feed Cinnamon 3 times."); D(20,"The Cat Has Been Summoned",{"cinnamon":10},20,"Interact with Cinnamon 10 times.")
    D(21,"First Paycheck",{"earned":100},5,"Earn 100 Catnip."); D(22,"Catnip Collector",{"earned":250},8,"Earn 250 Catnip."); D(23,"Small Fortune",{"earned":500},10,"Earn 500 Catnip."); D(24,"Catnip Hunter",{"earned":750},12,"Earn 750 Catnip."); D(25,"Mini Tycoon",{"earned":1000},15,"Earn 1,000 Catnip."); D(26,"Hard Worker",{"earned":1500},18,"Earn 1,500 Catnip."); D(27,"Catnip Machine",{"earned":2000},22,"Earn 2,000 Catnip."); D(28,"Money Printer",{"earned":2500},25,"Earn 2,500 Catnip."); D(29,"Daily Fortune",{"earned":3500},30,"Earn 3,500 Catnip."); D(30,"Cinnamon's Taxpayer",{"earned":5000},40,"Earn 5,000 Catnip.")
    D(31,"Window Shopper",{"buy":1},5,"Buy 1 item."); D(32,"Snack Buyer",{"buy":2},8,"Buy 2 items."); D(33,"Regular Customer",{"buy":3},10,"Buy 3 items."); D(34,"Shopping Spree",{"buy":5},15,"Buy 5 items."); D(35,"Impulse Buyer",{"spent":100},8,"Spend 100 Catnip."); D(36,"Little Purchase",{"spent":250},10,"Spend 250 Catnip."); D(37,"Retail Therapy",{"spent":500},15,"Spend 500 Catnip."); D(38,"Catnip Goes Brrr",{"spent":750},18,"Spend 750 Catnip."); D(39,"Shopping Day",{"spent":1000},22,"Spend 1,000 Catnip."); D(40,"Cinnamon's Favourite Customer",{"buy":5},20,"Buy 5 items.")
    D(41,"Clock In",{"work":1},5,"Work once."); D(42,"Employee of the Hour",{"work":2},8,"Work 2 times."); D(43,"Part-Time Cat",{"work":3},10,"Work 3 times."); D(44,"Busy Cat",{"work":4},12,"Work 4 times."); D(45,"Overtime",{"work":5},15,"Work 5 times."); D(46,"Corporate Slave",{"work":6},18,"Work 6 times."); D(47,"Workaholic",{"work":7},22,"Work 7 times."); D(48,"Cinnamon's Employee",{"work":3,"earned":250},15,"Work 3 times and earn 250 Catnip."); D(49,"Payday",{"work":5,"earned":500},22,"Work 5 times and earn 500 Catnip."); D(50,"Where Is HR?",{"work":10},30,"Work 10 times.")
    D(51,"Tuna Time",{"items:tuna":2},5,"Obtain 2 Tuna."); D(52,"Tuna Run",{"items:tuna":3},8,"Obtain 3 Tuna."); D(53,"Fish Market",{"items:tuna":5},12,"Obtain 5 Tuna."); D(54,"TUNA TUNA TUNA",{"items:tuna":10},20,"Obtain 10 Tuna."); D(55,"Treat Time",{"items:treat":2},5,"Obtain 2 Cat Treats."); D(56,"Treat Collector",{"items:treat":5},10,"Obtain 5 Cat Treats."); D(57,"Churu Hunter",{"items:churu":2},6,"Obtain 2 Churu."); D(58,"Churu Collector",{"items:churu":5},12,"Obtain 5 Churu."); D(59,"Catnip Ball Fan",{"items:catnip_ball":2},8,"Obtain 2 Catnip Balls."); D(60,"Fancy Fish Finder",{"items:fish":2},10,"Obtain 2 Fancy Fish.")
    D(61,"Busy Day",{"messages":5,"work":2},15,"Send 5 messages and work 2 times."); D(62,"Cat Employee",{"work":3,"earned":500},18,"Work 3 times and earn 500 Catnip."); D(63,"Shopping Employee",{"earned":500,"buy":2},18,"Earn 500 Catnip and buy 2 items."); D(64,"Social Cat",{"messages":5,"cinnamon":1},15,"Send 5 messages and interact with Cinnamon once."); D(65,"Catnip Shopper",{"earned":1000,"spent":250},22,"Earn 1,000 Catnip and spend 250 Catnip."); D(66,"Tuna Supplier",{"items:tuna":5,"messages":3},18,"Obtain 5 Tuna and send 3 messages."); D(67,"Full Schedule",{"work":5,"messages":5},22,"Work 5 times and send 5 messages."); D(68,"Snack Break",{"buy":2,"feed":1},15,"Buy 2 items and feed Cinnamon once."); D(69,"Daily Grind",{"work":5,"earned":1000},25,"Work 5 times and earn 1,000 Catnip."); D(70,"Cat's Busy Day",{"messages":10,"work":3},28,"Send 10 messages and work 3 times.")
    D(71,"Little Spender",{"spent":100},6,"Spend 100 Catnip."); D(72,"Daily Shopper",{"buy":1,"spent":100},8,"Buy 1 item and spend 100 Catnip."); D(73,"Fish Delivery",{"items:tuna":3,"feed":1},12,"Obtain 3 Tuna and feed Cinnamon once."); D(74,"Snack Delivery Service",{"items:treat":3,"feed":1},12,"Obtain 3 Cat Treats and feed Cinnamon once."); D(75,"Churu Delivery",{"items:churu":3,"cinnamon":1},12,"Obtain 3 Churu and interact with Cinnamon once."); D(76,"Hardworking Cat",{"work":5,"earned":750},20,"Work 5 times and earn 750 Catnip."); D(77,"Money & Snacks",{"earned":500,"buy":2},18,"Earn 500 Catnip and buy 2 items."); D(78,"Catnip Worker",{"work":3,"earned":750},18,"Work 3 times and earn 750 Catnip."); D(79,"Social Worker",{"work":3,"messages":5},18,"Work 3 times and send 5 messages."); D(80,"Cat's Shopping Trip",{"buy":3,"cinnamon":1},18,"Buy 3 items and interact with Cinnamon once.")
    D(81,"Daily Hustle",{"earned":1500,"work":5},30,"Earn 1,500 Catnip and work 5 times."); D(82,"Chat & Hustle",{"messages":10,"earned":1000},25,"Send 10 messages and earn 1,000 Catnip."); D(83,"Tuna Hunter",{"items:tuna":10,"messages":5},25,"Obtain 10 Tuna and send 5 messages."); D(84,"Snack Hunter",{"items:treat":5,"items:churu":3},22,"Obtain 5 Cat Treats and 3 Churu."); D(85,"Catnip Shopper Pro",{"earned":2000,"spent":500},32,"Earn 2,000 Catnip and spend 500 Catnip."); D(86,"Cinnamon's Errand",{"cinnamon":5,"work":3},28,"Interact with Cinnamon 5 times and work 3 times."); D(87,"Busy Employee",{"work":7,"earned":1500},35,"Work 7 times and earn 1,500 Catnip."); D(88,"Daily Collector",{"items:tuna":5,"items:treat":5},30,"Obtain 5 Tuna and 5 Cat Treats."); D(89,"The Daily Grind",{"messages":10,"work":7,"earned":1500},40,"Send 10 messages, work 7 times, and earn 1,500 Catnip."); D(90,"Perfect Cat Day",{"messages":10,"work":5,"earned":1000,"cinnamon":3},50,"Send 10 messages, work 5 times, earn 1,000 Catnip, and interact with Cinnamon 3 times.")
    D(91,"Quick Worker",{"work":2},7,"Work 2 times."); D(92,"Quick Shopper",{"buy":2},7,"Buy 2 items."); D(93,"Quick Fisher",{"items:tuna":3},7,"Obtain 3 Tuna."); D(94,"Quick Talker",{"messages":5},7,"Send 5 messages."); D(95,"Quick Earner",{"earned":500},8,"Earn 500 Catnip."); D(96,"Quick Cat Friend",{"cinnamon":3},8,"Interact with Cinnamon 3 times."); D(97,"Snack Mission",{"items:treat":2,"items:churu":2},12,"Obtain 2 Cat Treats and 2 Churu."); D(98,"Small Hustle",{"work":3,"earned":500},15,"Work 3 times and earn 500 Catnip."); D(99,"Catnip Mission",{"earned":2000,"messages":5},25,"Earn 2,000 Catnip and send 5 messages."); D(100,"Daily Champion",{"work":5,"earned":2000,"messages":10},45,"Work 5 times, earn 2,000 Catnip, and send 10 messages.")

    weekly = []
    def W(i, name, req, qp, desc=None): weekly.append(_quest(f"w{i:03}", name, req, qp, desc))
    W(1,"Weekly Yapper",{"messages":50},40,"Send 50 messages."); W(2,"Chat Machine",{"messages":75},50,"Send 75 messages."); W(3,"Professional Yapper",{"messages":100},60,"Send 100 messages."); W(4,"Human Podcast",{"messages":150},75,"Send 150 messages."); W(5,"Never-Ending Story",{"messages":200},90,"Send 200 messages."); W(6,"Server Announcer",{"messages":250},110,"Send 250 messages."); W(7,"Keyboard Destroyer",{"messages":300},125,"Send 300 messages."); W(8,"Cinnamon Needs Earplugs",{"messages":350},140,"Send 350 messages."); W(9,"Discord Resident",{"messages":400},160,"Send 400 messages."); W(10,"You Literally Live Here",{"messages":500},200,"Send 500 messages.")
    W(11,"Cat Regular",{"cinnamon":10},40,"Interact with Cinnamon 10 times."); W(12,"Cinnamon's Visitor",{"cinnamon":15},50,"Interact with Cinnamon 15 times."); W(13,"Cat Conversation Expert",{"cinnamon":20},60,"Interact with Cinnamon 20 times."); W(14,"Cinnamon's Assistant",{"cinnamon":25},75,"Interact with Cinnamon 25 times."); W(15,"Professional Cat Summoner",{"cinnamon":30},90,"Interact with Cinnamon 30 times."); W(16,"Cinnamon's Personal Employee",{"cinnamon":35},105,"Interact with Cinnamon 35 times."); W(17,"Catnip Consultant",{"cinnamon":40},120,"Interact with Cinnamon 40 times."); W(18,"Cinnamon's Therapist",{"cinnamon":45},140,"Interact with Cinnamon 45 times."); W(19,"The Cat Owns You",{"cinnamon":50},160,"Interact with Cinnamon 50 times."); W(20,"Cinnamon's Favourite Problem",{"cinnamon":50,"feed":5},200,"Interact with Cinnamon 50 times and feed her 5 times.")
    W(21,"Weekly Income",{"earned":2500},40,"Earn 2,500 Catnip."); W(22,"Catnip Collector",{"earned":5000},55,"Earn 5,000 Catnip."); W(23,"Mini Tycoon",{"earned":7500},70,"Earn 7,500 Catnip."); W(24,"Catnip Tycoon",{"earned":10000},90,"Earn 10,000 Catnip."); W(25,"Money Printer",{"earned":12500},110,"Earn 12,500 Catnip."); W(26,"Catnip Corporation",{"earned":15000},130,"Earn 15,000 Catnip."); W(27,"Financial Menace",{"earned":17500},150,"Earn 17,500 Catnip."); W(28,"Cinnamon's Bank Account",{"earned":20000},175,"Earn 20,000 Catnip."); W(29,"Catnip Empire",{"earned":22500},200,"Earn 22,500 Catnip."); W(30,"THE CATNIP ECONOMY",{"earned":25000},250,"Earn 25,000 Catnip.")
    W(31,"Weekly Shopper",{"buy":5},40,"Buy 5 items."); W(32,"Regular Customer",{"buy":10},55,"Buy 10 items."); W(33,"Shopping Addiction",{"buy":15},70,"Buy 15 items."); W(34,"Retail Warrior",{"buy":20},90,"Buy 20 items."); W(35,"Shop Employee",{"buy":25},110,"Buy 25 items."); W(36,"Shopping Machine",{"buy":30},130,"Buy 30 items."); W(37,"Money? What Money?",{"spent":2500},75,"Spend 2,500 Catnip."); W(38,"Big Spender",{"spent":5000},110,"Spend 5,000 Catnip."); W(39,"Financial Disaster",{"spent":10000},160,"Spend 10,000 Catnip."); W(40,"Cinnamon's Favourite Customer",{"spent":15000},200,"Spend 15,000 Catnip.")
    W(41,"Weekly Employee",{"work":5},40,"Work 5 times."); W(42,"Reliable Employee",{"work":10},55,"Work 10 times."); W(43,"Part-Time Professional",{"work":15},70,"Work 15 times."); W(44,"Full-Time Cat",{"work":20},90,"Work 20 times."); W(45,"Overtime Cat",{"work":25},110,"Work 25 times."); W(46,"Corporate Cat",{"work":30},130,"Work 30 times."); W(47,"Workaholic",{"work":35},155,"Work 35 times."); W(48,"Cinnamon's Best Employee",{"work":40},180,"Work 40 times."); W(49,"HR Is Concerned",{"work":45},210,"Work 45 times."); W(50,"PLEASE GO HOME",{"work":50},250,"Work 50 times.")
    W(51,"Tuna Supplier",{"items:tuna":5},40,"Obtain 5 Tuna."); W(52,"Fish Merchant",{"items:tuna":10},55,"Obtain 10 Tuna."); W(53,"Tuna Dealer",{"items:tuna":15},70,"Obtain 15 Tuna."); W(54,"Tuna Empire",{"items:tuna":20},90,"Obtain 20 Tuna."); W(55,"Tuna Overlord",{"items:tuna":25},110,"Obtain 25 Tuna."); W(56,"Tuna Distribution",{"items:tuna":30},130,"Obtain 30 Tuna."); W(57,"Tuna Factory",{"items:tuna":40},160,"Obtain 40 Tuna."); W(58,"TUNA TAKEOVER",{"items:tuna":50},200,"Obtain 50 Tuna."); W(59,"Treat Supplier",{"items:treat":25},90,"Obtain 25 Cat Treats."); W(60,"Treat Warehouse",{"items:treat":50},150,"Obtain 50 Cat Treats.")
    W(61,"Churu Supplier",{"items:churu":10},50,"Obtain 10 Churu."); W(62,"Churu Collector",{"items:churu":20},70,"Obtain 20 Churu."); W(63,"Churu Warehouse",{"items:churu":30},100,"Obtain 30 Churu."); W(64,"Churu Empire",{"items:churu":40},130,"Obtain 40 Churu."); W(65,"Churu Takeover",{"items:churu":50},170,"Obtain 50 Churu."); W(66,"Catnip Ball Collector",{"items:catnip_ball":10},55,"Obtain 10 Catnip Balls."); W(67,"Catnip Ball Hoarder",{"items:catnip_ball":20},80,"Obtain 20 Catnip Balls."); W(68,"Catnip Ball Warehouse",{"items:catnip_ball":30},110,"Obtain 30 Catnip Balls."); W(69,"Fancy Fish Collector",{"items:fish":25},100,"Obtain 25 Fancy Fish."); W(70,"Fancy Fish Merchant",{"items:fish":50},175,"Obtain 50 Fancy Fish.")
    W(71,"XP Grinder",{"xp":500},40,"Gain 500 XP."); W(72,"XP Hunter",{"xp":1000},60,"Gain 1,000 XP."); W(73,"XP Climber",{"xp":1500},80,"Gain 1,500 XP."); W(74,"XP Machine",{"xp":2000},100,"Gain 2,000 XP."); W(75,"XP Addict",{"xp":2500},120,"Gain 2,500 XP."); W(76,"XP Monster",{"xp":3000},140,"Gain 3,000 XP."); W(77,"XP Grinder Pro",{"xp":3500},160,"Gain 3,500 XP."); W(78,"XP Veteran",{"xp":4000},180,"Gain 4,000 XP."); W(79,"XP Legend",{"xp":4500},200,"Gain 4,500 XP."); W(80,"THE XP GRIND",{"xp":5000},225,"Gain 5,000 XP.")
    W(81,"Level Up",{"levels":1},60,"Gain 1 level."); W(82,"Level Hunter",{"levels":2},100,"Gain 2 levels."); W(83,"Triple Level-Up",{"levels":3},160,"Gain 3 levels.")
    W(84,"Weekly Hustle",{"messages":100,"work":10},100,"Send 100 messages and work 10 times."); W(85,"Corporate Lifestyle",{"work":20,"earned":5000},110,"Work 20 times and earn 5,000 Catnip."); W(86,"Shopping Employee",{"buy":10,"work":15},120,"Buy 10 items and work 15 times."); W(87,"Social Butterfly",{"messages":100,"cinnamon":10},100,"Send 100 messages and interact with Cinnamon 10 times."); W(88,"Catnip Shopper",{"earned":10000,"spent":2500},150,"Earn 10,000 Catnip and spend 2,500 Catnip."); W(89,"Cat's Busy Week",{"work":25,"messages":150},150,"Work 25 times and send 150 messages."); W(90,"Tuna Logistics",{"items:tuna":25,"earned":5000},140,"Obtain 25 Tuna and earn 5,000 Catnip.")
    W(91,"Full-Time Server Resident",{"messages":250,"work":25},175,"Send 250 messages and work 25 times."); W(92,"Cinnamon's Weekly Challenge",{"cinnamon":25,"earned":5000},150,"Interact with Cinnamon 25 times and earn 5,000 Catnip."); W(93,"Money & Work",{"work":25,"earned":10000},200,"Work 25 times and earn 10,000 Catnip."); W(94,"The Weekly Grind",{"messages":300,"work":30},225,"Send 300 messages and work 30 times."); W(95,"Catnip Worker Pro",{"work":40,"earned":15000},250,"Work 40 times and earn 15,000 Catnip."); W(96,"Shopping Beast",{"buy":25,"spent":10000},250,"Buy 25 items and spend 10,000 Catnip."); W(97,"Tuna Tycoon",{"items:tuna":50,"earned":15000},275,"Obtain 50 Tuna and earn 15,000 Catnip."); W(98,"Cinnamon's Nightmare",{"cinnamon":50,"work":30},275,"Interact with Cinnamon 50 times and work 30 times."); W(99,"The Weekly Beast",{"messages":500,"work":50,"earned":20000},350,"Send 500 messages, work 50 times, and earn 20,000 Catnip."); W(100,"THE DREAM",{"messages":500,"work":50,"earned":25000,"cinnamon":50},500,"Send 500 messages, work 50 times, earn 25,000 Catnip, and interact with Cinnamon 50 times.")
    return {"daily": {q["id"]: q for q in daily}, "weekly": {q["id"]: q for q in weekly}}

quest_definitions = _build_builtin_quests()

QUEST_SHOP = {
    "catnip_500": {"name":"500 Catnip", "cost":50, "type":"catnip", "amount":500, "description":"Redeem 50 QP for 500 Catnip."},
    "catnip_1250": {"name":"1,250 Catnip", "cost":100, "type":"catnip", "amount":1250, "description":"Redeem 100 QP for 1,250 Catnip."},
    "catnip_3500": {"name":"3,500 Catnip", "cost":250, "type":"catnip", "amount":3500, "description":"Redeem 250 QP for 3,500 Catnip."},
    "catnip_8000": {"name":"8,000 Catnip", "cost":500, "type":"catnip", "amount":8000, "description":"Redeem 500 QP for 8,000 Catnip."},
    "xp_500": {"name":"500 XP", "cost":100, "type":"xp", "amount":500, "description":"Redeem 100 QP for 500 XP."},
    "xp_1500": {"name":"1,500 XP", "cost":250, "type":"xp", "amount":1500, "description":"Redeem 250 QP for 1,500 XP."},
    "xp_4000": {"name":"4,000 XP", "cost":500, "type":"xp", "amount":4000, "description":"Redeem 500 QP for 4,000 XP."},
}


def quest_user_progress(guild_id: int, user_id: int) -> dict:
    key = (guild_id, user_id)
    if key not in quest_progress:
        quest_progress[key] = {"daily": {}, "weekly": {}}
    quest_progress[key].setdefault("daily", {})
    quest_progress[key].setdefault("weekly", {})
    return quest_progress[key]


def quest_points_for(guild_id: int, user_id: int) -> int:
    return int(quest_points.get((guild_id, user_id), 0))


def quest_cycle_id(kind: str, started_at: float) -> str:
    return f"{kind}:{int(started_at)}"


def _quest_pick(kind: str) -> list[str]:
    pool = [qid for qid, q in quest_definitions[kind].items() if q.get("enabled", True)]
    return random.sample(pool, min(QUEST_ACTIVE_COUNT, len(pool)))


def _quest_clear_guild_progress(guild_id: int, kind: str):
    for (gid, uid), data in list(quest_progress.items()):
        if gid == guild_id:
            data[kind] = {}


def _quest_cycle_config(guild_id: int, kind: str) -> dict:
    cfg = quest_config.setdefault(guild_id, {"enabled": True, "log_channel_id": None, "daily": {}, "weekly": {}, "history": []})
    cfg.setdefault(kind, {})
    now = time.time()
    duration = QUEST_DAILY_SECONDS if kind == "daily" else QUEST_WEEKLY_SECONDS
    current = cfg[kind]
    if not current.get("started_at") or not current.get("active") or float(current.get("ends_at", 0)) <= now:
        started = now
        current.clear()
        current.update({"started_at": started, "ends_at": started + duration, "cycle_id": quest_cycle_id(kind, started), "active": _quest_pick(kind)})
        _quest_clear_guild_progress(guild_id, kind)
    return current


def quest_setup_ready(guild_id: int) -> bool:
    return bool(quest_config.get(guild_id, {}).get("enabled", False))


def cinnamon_embed(
    *,
    title: str,
    description: str = "",
    color: discord.Color | int = 0xFFB02E,
    guild: discord.Guild | None = None,
    footer: str = "Cinnamon • Powered by paws, snacks & chaos",
    timestamp: bool = True,
) -> discord.Embed:
    """Build a consistent, polished Cinnamon embed.

    Discord supports rich embeds with titles, descriptions, fields, thumbnails,
    timestamps and footers; this helper keeps those elements consistent while
    staying safely inside Discord's documented embed limits.
    """
    embed = discord.Embed(
        title=str(title)[:256],
        description=str(description)[:2048],
        color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc) if timestamp else None,
    )
    if guild and bot.user:
        avatar = bot.user.display_avatar.url
        embed.set_author(name=f"Cinnamon • {guild.name[:220]}", icon_url=avatar)
        embed.set_thumbnail(url=avatar)
    elif bot.user:
        embed.set_author(name="Cinnamon", icon_url=bot.user.display_avatar.url)
    embed.set_footer(text=str(footer)[:2048])
    return embed


def add_embed_fields(embed: discord.Embed, fields=None, *, inline: bool = True):
    """Add fields with Discord's limits enforced, so one bad value cannot break a command."""
    for name, value in (fields or []):
        if len(embed.fields) >= 25:
            break
        embed.add_field(name=str(name)[:256] or "Info", value=str(value)[:1024] or "—", inline=inline)
    return embed


def friendly_error_embed(title: str, description: str, *, guild=None) -> discord.Embed:
    return cinnamon_embed(title=f"🐱 {title}", description=description, color=discord.Color.red(), guild=guild, footer="Cinnamon • Something went wrong")


async def quest_log(guild_id: int, *, title: str, description: str = "", fields=None):
    cfg = quest_config.get(guild_id, {})
    channel_id = cfg.get("log_channel_id")
    if not channel_id:
        return
    channel = bot.get_channel(int(channel_id))
    if channel is None:
        return
    guild = bot.get_guild(guild_id)
    embed = cinnamon_embed(title=title, description=description, color=0x8E7CFF, guild=guild, footer="Cinnamon • Quest log")
    add_embed_fields(embed, fields)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        log.error(f"Quest log failed for {guild_id}: {e}")
    except Exception:
        log.exception("Unexpected quest log failure for %s", guild_id)


def quest_requirement_text(q: dict) -> str:
    return q.get("description", "Complete the objective.")


def quest_progress_value(data: dict, metric: str) -> int:
    return int(data.get(metric, 0))


def quest_completed(q: dict, progress: dict) -> bool:
    return all(quest_progress_value(progress, metric) >= int(amount) for metric, amount in q["requirements"].items())


def quest_display(kind: str, qid: str, progress: dict | None = None, completed: bool = False) -> str:
    q = quest_definitions[kind][qid]
    if progress is None:
        progress = {}
    bits=[]
    for metric, amount in q["requirements"].items():
        bits.append(f"{min(int(progress.get(metric,0)), int(amount))}/{int(amount)}")
    status = "✅" if completed else "⬜"
    return f"{status} **{q['name']}** — {q['description']} — **+{q['qp']} QP**\nProgress: `{', '.join(bits)}`"


async def quest_complete(guild_id: int, user_id: int, kind: str, qid: str, member=None):
    q = quest_definitions[kind].get(qid)
    if not q:
        return False
    pdata = quest_user_progress(guild_id, user_id)[kind]
    state = pdata.setdefault(qid, {})
    if state.get("completed") or not quest_completed(q, state):
        return False
    state["completed"] = True
    quest_points[(guild_id, user_id)] = quest_points_for(guild_id, user_id) + int(q["qp"])
    history = quest_history.setdefault((guild_id, user_id), [])
    history.append({"quest_id": qid, "kind": kind, "name": q["name"], "qp": int(q["qp"]), "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    del history[:-50]
    # Every completed daily/weekly quest counts toward the achievement system.
    if member is None:
        guild = bot.get_guild(guild_id)
        member = guild.get_member(user_id) if guild else None
    if member is not None:
        await achievement_record(guild_id, user_id, metric_updates={"quests_completed": 1}, member=member)
        ap = achievement_progress(guild_id, user_id)
        quest_count = int(ap["stats"].get("quests_completed", 0))
        link = f"`/achievement profile` • Quest achievement progress: **{quest_count}**"
    else:
        link = "`/achievement profile` • Quest achievement progress is tracked automatically"
    await quest_log(guild_id, title="🎯 Quest completed", fields=[("Member", f"<@{user_id}> ({user_id})"), ("Quest", q["name"]), ("Type", kind.title()), ("Reward", f"+{q['qp']} QP"), ("Achievement link", link)])
    return True


async def quest_record_event(guild_id: int, user_id: int, metric: str, amount: int = 1, member=None):
    if not guild_id or amount <= 0:
        return []
    if not quest_setup_ready(guild_id):
        return []
    completed = []
    for kind in ("daily", "weekly"):
        cycle = _quest_cycle_config(guild_id, kind)
        pdata = quest_user_progress(guild_id, user_id)[kind]
        for qid in cycle.get("active", []):
            q = quest_definitions[kind].get(qid)
            if not q or qid not in quest_definitions[kind]:
                continue
            state = pdata.setdefault(qid, {})
            if state.get("completed"):
                continue
            if metric in q["requirements"]:
                state[metric] = min(int(q["requirements"][metric]), int(state.get(metric, 0)) + int(amount))
            if quest_completed(q, state):
                if await quest_complete(guild_id, user_id, kind, qid, member=member):
                    completed.append((kind, q))
    return completed


async def quest_setup_guild(guild: discord.Guild) -> dict:
    cfg = quest_config.setdefault(guild.id, {"enabled": True, "log_channel_id": None, "daily": {}, "weekly": {}, "history": []})
    category = discord.utils.get(guild.categories, name="Cinnamon • Logs & Setup")
    if category is None:
        category = await guild.create_category("Cinnamon • Logs & Setup", reason="Cinnamon quest setup")
    channel, _ = await _ensure_setup_channel(guild, category, "cinnamon-quest-logs", "Daily and weekly quest completion, administration, and recovery logs.")
    cfg["enabled"] = True
    cfg["log_channel_id"] = channel.id
    _quest_cycle_config(guild.id, "daily")
    _quest_cycle_config(guild.id, "weekly")
    await bd_save_data()
    await quest_log(guild.id, title="⚙️ Quest system setup", fields=[("Daily pool", 100), ("Weekly pool", 100), ("Daily active", QUEST_ACTIVE_COUNT), ("Weekly active", QUEST_ACTIVE_COUNT), ("Log channel", channel.mention)])
    return cfg

# In-memory only (session state — fine to lose on restart):
afk_users = {}                          # (guild_id, user_id) -> reason
xp_cooldowns = {}                       # (guild_id, user_id) -> monotonic time of last XP award
spam_tracker = defaultdict(lambda: deque(maxlen=6))   # (guild_id, user_id) -> recent message timestamps
join_log = defaultdict(lambda: deque(maxlen=20))      # guild_id -> recent member-join timestamps (anti-raid)

# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

gemini_client = genai.Client(api_key=GEMINI_API_KEY)


def ask_gemini(channel_id: int, speaker: str, trigger_text: str, guild: "discord.Guild | None") -> dict:
    """Blocking call to Gemini. Run this off the event loop with asyncio.to_thread.

    Returns {"reply": str, "reaction": str} where reaction is either a plain
    unicode emoji, the bare name of one of the guild's custom emoji (no colons),
    or "" if nothing fits.
    """
    history = channel_memories[channel_id]
    convo = "\n".join(f"{name}: {text}" for name, text in history)

    custom_emoji_names = [e.name for e in guild.emojis] if guild else []
    emoji_note = (
        f"This server also has these custom emoji you may react with by bare name "
        f"(no colons): {', '.join(custom_emoji_names)}."
        if custom_emoji_names else
        "This server has no custom emoji available, so only use a standard unicode emoji, or none."
    )

    prompt = (
        f"Recent channel conversation:\n{convo}\n\n"
        f"{speaker} just said: \"{trigger_text}\"\n\n"
        f"Reply as Cinnamon, talking to {speaker}. {emoji_note}\n\n"
        "Respond with ONLY a JSON object (no markdown fences, no extra text) shaped exactly like:\n"
        '{"reply": "<your in-character reply, 1-3 sentences>", '
        '"reaction": "<one unicode emoji, OR a bare custom emoji name from the list above, '
        'OR an empty string if none fits>"}'
    )

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=200,
            temperature=0.9,
            response_mime_type="application/json",
        ),
    )

    raw = (response.text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.IGNORECASE).strip()

    reply, reaction = "", ""
    try:
        data = json.loads(raw)
        reply = str(data.get("reply") or "").strip()
        reaction = str(data.get("reaction") or "").strip()
    except (json.JSONDecodeError, AttributeError):
        reply = raw  # fall back to treating the whole thing as plain text

    if not reply:
        reply = "*blinks slowly, unsure what just happened*"
    return {"reply": reply, "reaction": reaction}


# ---------------------------------------------------------------------------
# Discord bot
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # needed for /role add-all and for finding the owner by username

bot = commands.Bot(command_prefix="!", intents=intents)


# --- "Who's your owner / favorite person" ------------------------------------

_OWNER_QUESTION_PATTERNS = [
    re.compile(r"\bwho.{0,20}\bowner\b", re.IGNORECASE),
    re.compile(r"\bowner\b.{0,20}\bwho\b", re.IGNORECASE),
    re.compile(r"\b(favorite|favourite)\s+person\b", re.IGNORECASE),
    re.compile(r"\bwho\s+(made|created|owns|built)\s+you\b", re.IGNORECASE),
]


def is_owner_question(text: str) -> bool:
    return any(p.search(text) for p in _OWNER_QUESTION_PATTERNS)


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


async def send_log(guild_id: int | None, *, title: str, description: str = "",
                    color: discord.Color = discord.Color.blurple(),
                    interaction: discord.Interaction | None = None,
                    fields: list[tuple[str, str]] | None = None):
    """Post an embed to the guild's configured log channel, if any. Never raises —
    logging should never be the thing that breaks a command."""
    if guild_id is None:
        return
    channel_id = log_channels.get(guild_id)
    if channel_id is None:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        return

    guild = bot.get_guild(guild_id)
    footer = f"Cinnamon • Server log • {guild.name}" if guild else "Cinnamon • Server log"
    if interaction is not None:
        footer = f"{footer} • Run by {interaction.user}"
    embed = cinnamon_embed(title=title, description=description, color=color, guild=guild, footer=footer)
    add_embed_fields(embed, fields)

    try:
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        log.error(f"Failed to send log message to channel {channel_id}: {e}")
    except Exception:
        log.exception("Unexpected failure sending log message to channel %s", channel_id)


@bot.event
async def on_ready():
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

    # Sync globally for all servers, then sync the same command tree to every
    # connected guild so newly-added slash commands appear immediately instead
    # of waiting for Discord's global command propagation.
    try:
        global_commands = await bot.tree.sync()
        log.info("Global slash-command sync complete: %d commands", len(global_commands))
    except Exception:
        log.exception("Global slash-command sync failed")

    guild_sync_success = 0
    guild_sync_failed = 0
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            guild_commands = await bot.tree.sync(guild=guild)
            guild_sync_success += 1
            log.info("Guild slash-command sync complete for %s (%s): %d commands", guild.name, guild.id, len(guild_commands))
        except Exception:
            guild_sync_failed += 1
            log.exception("Guild slash-command sync failed for %s (%s)", guild.name, guild.id)

    log.info(
        "Slash-command registration finished: %d guild(s) synced, %d guild(s) failed.",
        guild_sync_success, guild_sync_failed,
    )

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


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Lightweight prefix shortcut requested for economy: ?work (no prefix-command
    # framework is needed, so it keeps the existing message/AI pipeline intact).
    if message.guild and message.content.strip().lower() == "?work":
        try:
            ok, amount, work_message = await economy_do_work(message.guild.id, message.author)
            await message.channel.send(work_message)
        except discord.Forbidden:
            await message.channel.send("🔒 Cinnamon can't send the work result here. Please check my channel permissions.")
        except discord.HTTPException:
            await message.channel.send("🌐 Discord had trouble sending Cinnamon's work result. Please try again.")
        except Exception:
            log.exception("Unhandled ?work error")
            try:
                await message.channel.send("🐱💥 Something went wrong with `?work`. Cinnamon logged the error.")
            except discord.HTTPException:
                pass
        return

    if message.guild:
        # --- AFK: clear the sender's own status, and flag anyone AFK they pinged ---
        afk_key = (message.guild.id, message.author.id)
        if afk_key in afk_users:
            del afk_users[afk_key]
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
        ping_count = 1 if bot.user is not None and bot.user in message.mentions and not message.mention_everyone else 0
        await achievement_record(message.guild.id, message.author.id, metric_updates={"messages": 1, "cinnamon_pings": ping_count}, member=message.author)
        qdone = await quest_record_event(message.guild.id, message.author.id, "messages", 1, member=message.author)
        if ping_count:
            qdone += await quest_record_event(message.guild.id, message.author.id, "cinnamon", ping_count, member=message.author)
        if qdone:
            await bd_save_data()

    if clean_content:
        channel_memories[message.channel.id].append((speaker, clean_content))

    guild_id = message.guild.id if message.guild else None
    channel_id = message.channel.id

    # A disabled channel overrides everything else — Cinnamon stays silent here.
    if guild_id is not None and channel_id in disabled_channels[guild_id]:
        return

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

    is_ai_channel = guild_id is not None and ai_channels.get(guild_id) == channel_id

    if clean_content and (was_mentioned or was_reply_to_bot or is_ai_channel):
        # Keep an always-on AI channel from turning chat bursts into Gemini bursts.
        now = time.monotonic()
        if is_ai_channel and not (was_mentioned or was_reply_to_bot):
            last_ai = ai_cooldowns.get(channel_id, 0.0)
            if now - last_ai < AI_CHANNEL_COOLDOWN_SECONDS:
                return
            ai_cooldowns[channel_id] = now

        if is_owner_question(clean_content):
            # Hard-coded so this is always correct, instead of hoping the model remembers.
            reply = (
                f"*puffs up proudly* {OWNER_NAME} is my human and my favorite person "
                f"in the whole wide world! {owner_mention(message.guild)}"
            )
            reaction = "❤️"
        else:
            async with message.channel.typing():
                try:
                    result = await asyncio.to_thread(
                        ask_gemini, message.channel.id, speaker, clean_content, message.guild
                    )
                except Exception as e:
                    log.error(f"Gemini call failed: {e}")
                    result = {
                        "reply": "*paws at the screen, confused* ...something smells like tuna gone wrong. Try again in a moment?",
                        "reaction": "",
                    }
            reply = result["reply"]
            reaction = result["reaction"]

        channel_memories[message.channel.id].append(("Cinnamon", reply))

        # In the dedicated AI channel, chat naturally instead of quote-replying
        # to every single message — but still use a reply if directly pinged.
        if is_ai_channel and not (was_mentioned or was_reply_to_bot):
            await message.channel.send(reply)
        else:
            await message.reply(
                reply, mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        await add_reaction_safely(message, reaction)
        if message.guild:
            await achievement_record(message.guild.id, message.author.id, metric_updates={"ai_replies": 1}, member=message.author)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="pet", description="Give Cinnamon some pets")
async def pet(interaction: discord.Interaction):
    await achievement_record(interaction.guild.id, interaction.user.id, metric_updates={"pet_uses": 1} if "pet_uses" != "cinnamon_interactions" else {}, interaction_command="pet", date_interaction=True, member=interaction.user)
    if await quest_record_event(interaction.guild.id, interaction.user.id, "cinnamon", 1, member=interaction.user): await bd_save_data()
    await interaction.response.send_message(
        "*melts into a puddle of fluff, purring loudly* Purrrrr... more, please?"
    )


@bot.tree.command(name="treat", description="Offer Cinnamon a treat")
async def treat(interaction: discord.Interaction):
    await achievement_record(interaction.guild.id, interaction.user.id, metric_updates={}, interaction_command="treat", date_interaction=True, member=interaction.user)
    if await quest_record_event(interaction.guild.id, interaction.user.id, "cinnamon", 1, member=interaction.user): await bd_save_data()
    await interaction.response.send_message(
        "*ears perk up, pupils go huge* Tuna?? Churu?? ANYTHING?? *sits so politely*"
    )


@bot.tree.command(name="nap", description="Let Cinnamon take a nap")
async def nap(interaction: discord.Interaction):
    await achievement_record(interaction.guild.id, interaction.user.id, metric_updates={}, interaction_command="nap", date_interaction=True, member=interaction.user)
    if await quest_record_event(interaction.guild.id, interaction.user.id, "cinnamon", 1, member=interaction.user): await bd_save_data()
    await interaction.response.send_message(
        "*curls into a tight loaf on the nearest keyboard* Zzz... five more minutes..."
    )


@bot.tree.command(name="zoomies", description="Uh oh, Cinnamon has the zoomies")
async def zoomies(interaction: discord.Interaction):
    await achievement_record(interaction.guild.id, interaction.user.id, metric_updates={}, interaction_command="zoomies", date_interaction=True, member=interaction.user)
    if await quest_record_event(interaction.guild.id, interaction.user.id, "cinnamon", 1, member=interaction.user): await bd_save_data()
    await interaction.response.send_message(
        "*tears across the room sideways, tail puffed* WHO TURNED ON THE FLOOR IS LAVA?!"
    )


# ---------------------------------------------------------------------------
# AI channel configuration (mods only)
# ---------------------------------------------------------------------------

@bot.tree.command(name="aichannel", description="Make Cinnamon reply to every message in this channel, no mention needed")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def aichannel(interaction: discord.Interaction):
    ai_channels[interaction.guild.id] = interaction.channel.id
    await bd_save_data()
    await interaction.response.send_message(
        f"*claims {interaction.channel.mention} as her own* I'll chat here without being mentioned now!"
    )
    await send_log(
        interaction.guild.id, title="⚙️ AI channel set", interaction=interaction,
        fields=[("Channel", interaction.channel.mention)],
    )


@bot.tree.command(name="disableaichannel", description="Turn off Cinnamon's always-on AI channel for this server")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def disableaichannel(interaction: discord.Interaction):
    removed = ai_channels.pop(interaction.guild.id, None)
    await bd_save_data()
    if removed:
        await interaction.response.send_message(
            "*stretches and wanders off* Back to needing a mention or reply now."
        )
        await send_log(interaction.guild.id, title="⚙️ AI channel disabled", interaction=interaction)
    else:
        await interaction.response.send_message(
            "*blinks* There wasn't an AI channel set for this server.", ephemeral=True
        )


@bot.tree.command(name="disableai", description="Stop Cinnamon from talking in this channel at all")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def disableai(interaction: discord.Interaction):
    disabled_channels[interaction.guild.id].add(interaction.channel.id)
    await bd_save_data()
    await interaction.response.send_message(
        "*curls up and goes quiet* Won't respond in this channel anymore, even if mentioned."
    )
    await send_log(
        interaction.guild.id, title="⚙️ Channel muted for AI", interaction=interaction,
        fields=[("Channel", interaction.channel.mention)],
    )


@bot.tree.command(name="enableai", description="Let Cinnamon talk in this channel again")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def enableai(interaction: discord.Interaction):
    disabled_channels[interaction.guild.id].discard(interaction.channel.id)
    await bd_save_data()
    await interaction.response.send_message("*perks back up* I can talk here again!")
    await send_log(
        interaction.guild.id, title="⚙️ Channel re-enabled for AI", interaction=interaction,
        fields=[("Channel", interaction.channel.mention)],
    )


@bot.tree.command(name="logchannel", description="Set this channel as Cinnamon's log channel for mod actions and errors")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def logchannel(interaction: discord.Interaction):
    log_channels[interaction.guild.id] = interaction.channel.id
    await bd_save_data()
    status = await storage_status()
    icon = "✅" if status["connected"] else "⚠️"
    await interaction.response.send_message(
        f"*sets up a little logbook in {interaction.channel.mention}* "
        f"I'll post mod actions, config changes, and errors here from now on.\n\n"
        f"{icon} **Storage:** {status['backend']} — {status['detail']}"
    )
    await send_log(
        interaction.guild.id,
        title="📋 Log channel set",
        description=f"This channel is now Cinnamon's log channel.",
        color=discord.Color.blurple(),
        interaction=interaction,
        fields=[("Storage backend", status["backend"]), ("Connected", "Yes" if status["connected"] else "No")],
    )


@bot.tree.command(name="disablelogchannel", description="Stop Cinnamon from posting logs anywhere in this server")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def disablelogchannel(interaction: discord.Interaction):
    removed = log_channels.pop(interaction.guild.id, None)
    await bd_save_data()
    if removed:
        await interaction.response.send_message("*closes the logbook* Stopped logging actions for this server.")
    else:
        await interaction.response.send_message(
            "*blinks* There wasn't a log channel set for this server.", ephemeral=True
        )


# ---------------------------------------------------------------------------
# Moderation commands (mods only)
# ---------------------------------------------------------------------------



@bot.tree.command(name="questlogchannel", description="Set the dedicated quest log channel for Cinnamon")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def questlogchannel(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    target = channel or interaction.channel
    cfg = quest_config.setdefault(interaction.guild.id, {"enabled": True, "log_channel_id": None, "daily": {}, "weekly": {}, "history": []})
    cfg["log_channel_id"] = target.id
    await bd_save_data()
    await interaction.response.send_message(f"🎯 Quest logs will now be posted in {target.mention}.", ephemeral=True)
    await quest_log(interaction.guild.id, title="📋 Quest log channel set", fields=[("Admin", str(interaction.user)), ("Channel", target.mention)])


@bot.tree.command(name="disablequestlogchannel", description="Disable Cinnamon's dedicated quest log channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def disablequestlogchannel(interaction: discord.Interaction):
    cfg = quest_config.setdefault(interaction.guild.id, {"enabled": True, "log_channel_id": None, "daily": {}, "weekly": {}, "history": []})
    old = cfg.pop("log_channel_id", None)
    await bd_save_data()
    await interaction.response.send_message("🎯 Quest logging disabled." if old else "ℹ️ Quest logging was not configured.", ephemeral=True)


@bot.tree.command(name="achievementlogchannel", description="Set the dedicated achievement log channel for Cinnamon")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def achievementlogchannel(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    target = channel or interaction.channel
    cfg = achievement_config.setdefault(interaction.guild.id, {"enabled": True, "log_channel_id": None})
    cfg["log_channel_id"] = target.id
    await bd_save_data()
    await interaction.response.send_message(f"🏆 Achievement logs will now be posted in {target.mention}.", ephemeral=True)
    await achievement_log(interaction.guild.id, title="📋 Achievement log channel set", fields=[("Admin", str(interaction.user)), ("Channel", target.mention)])


@bot.tree.command(name="disableachievementlogchannel", description="Disable Cinnamon's dedicated achievement log channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def disableachievementlogchannel(interaction: discord.Interaction):
    cfg = achievement_config.setdefault(interaction.guild.id, {"enabled": True, "log_channel_id": None})
    old = cfg.pop("log_channel_id", None)
    await bd_save_data()
    await interaction.response.send_message("🏆 Achievement logging disabled." if old else "ℹ️ Achievement logging was not configured.", ephemeral=True)


@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Who to kick", reason="Why are they being kicked?")
@app_commands.guild_only()
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.checks.bot_has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member,
               reason: app_commands.Range[str, 1, 300] = "No reason given"):
    await member.kick(reason=reason)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(f"*escorts {member.mention} out with a paw* Kicked. Reason: {reason}")
    await send_log(
        interaction.guild.id, title="👢 Member kicked", color=discord.Color.orange(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Reason", reason)],
    )


@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Who to ban", reason="Why are they being banned?")
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member,
              reason: app_commands.Range[str, 1, 300] = "No reason given"):
    await member.ban(reason=reason, delete_message_seconds=0)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(f"*hisses and swats {member.mention} out the door* Banned. Reason: {reason}")
    await send_log(
        interaction.guild.id, title="🔨 Member banned", color=discord.Color.red(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Reason", reason)],
    )


@bot.tree.command(name="unban", description="Unban a user using their user ID")
@app_commands.describe(user_id="The numeric ID of the user to unban")
@app_commands.guild_only()
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        await interaction.guild.unban(discord.Object(id=int(user_id)))
        temp_bans.pop((interaction.guild.id, int(user_id)), None)  # in case it was also a tempban
        case_id = next_case(interaction.guild.id)
        await bd_save_data()
        await interaction.response.send_message(f"*nudges the door back open* Unbanned <@{user_id}>.")
        await send_log(
            interaction.guild.id, title="🔓 Member unbanned", color=discord.Color.green(), interaction=interaction,
            fields=[("Case", f"#{case_id}"), ("User ID", str(int(user_id)))],
        )
    except (ValueError, discord.NotFound):
        await interaction.response.send_message(
            "*tilts head* Couldn't find that user ID on the ban list.", ephemeral=True
        )


@bot.tree.command(name="mute", description="Timeout a member so they can't send messages for a while")
@app_commands.describe(member="Who to mute", minutes="How many minutes to mute for", reason="Why are they being muted?")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def mute(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320] = 10,
               reason: app_commands.Range[str, 1, 300] = "No reason given"):
    await member.timeout(datetime.timedelta(minutes=minutes), reason=reason)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(
        f"*sits on {member.mention}'s keyboard* Muted for {minutes} minute(s). Reason: {reason}"
    )
    await send_log(
        interaction.guild.id, title="🔇 Member muted", color=discord.Color.orange(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Duration", f"{minutes} min"), ("Reason", reason)],
    )


@bot.tree.command(name="unmute", description="Remove a member's timeout early")
@app_commands.describe(member="Who to unmute")
@app_commands.guild_only()
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(f"*hops off the keyboard* {member.mention} can talk again.")
    await send_log(
        interaction.guild.id, title="🔊 Member unmuted", color=discord.Color.green(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})")],
    )


@bot.tree.command(name="purge", description="Delete a number of recent messages in this channel")
@app_commands.describe(amount="How many messages to delete (1-100)")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"*sweeps up {len(deleted)} messages with her tail* All tidy now!", ephemeral=True)
    await send_log(
        interaction.guild.id, title="🧹 Messages purged", color=discord.Color.light_grey(), interaction=interaction,
        fields=[("Channel", interaction.channel.mention), ("Deleted", str(len(deleted)))],
    )


@bot.tree.command(name="slowmode", description="Set slowmode (message rate limit) for a channel")
@app_commands.describe(
    seconds="Seconds each member must wait between messages (0 turns it off, max 21600 = 6 hours)",
    channel="Channel to apply it to (defaults to this channel)",
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600],
                    channel: discord.TextChannel = None):
    target = channel or interaction.channel
    await target.edit(slowmode_delay=seconds)
    if seconds == 0:
        msg = f"*stops pacing the room* Slowmode's off in {target.mention}."
    else:
        msg = f"*sets a little hourglass* Slowmode set to {seconds}s in {target.mention}."
    await interaction.response.send_message(msg)
    await send_log(
        interaction.guild.id, title="🐌 Slowmode changed", color=discord.Color.blurple(), interaction=interaction,
        fields=[("Channel", target.mention), ("Seconds", str(seconds))],
    )


# ---------------------------------------------------------------------------
# Role commands (mods only) — grouped under /role
# ---------------------------------------------------------------------------

role_group = app_commands.Group(name="role", description="Add roles to members")


@role_group.command(name="add", description="Add a role to one specific member")
@app_commands.describe(member="Who to give the role to", role="Which role to add")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def role_add(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.add_roles(role, reason=f"/role add run by {interaction.user}")
    await interaction.response.send_message(
        f"*drapes **{role.name}** over {member.mention}* Done!",
        allowed_mentions=discord.AllowedMentions(roles=False),
    )
    await send_log(
        interaction.guild.id, title="🏷️ Role added", color=discord.Color.green(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})"), ("Role", role.name)],
    )


@role_group.command(name="add-all", description="Add a role to every member in the server")
@app_commands.describe(
    role="Which role to add to everyone",
    include_bots="Also give the role to bot accounts (default: no)",
)
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_roles=True, manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def role_add_all(interaction: discord.Interaction, role: discord.Role, include_bots: bool = False):
    if role.is_default():
        await interaction.response.send_message("*tilts head* Everyone already has @everyone!", ephemeral=True)
        return
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(
            "*can't quite reach that high* That role sits above (or level with) my own top role — "
            "move my role above it in Server Settings → Roles first.", ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)
    targets = [m for m in interaction.guild.members if role not in m.roles and (include_bots or not m.bot)]

    added, failed = 0, 0
    for member in targets:
        try:
            await member.add_roles(role, reason=f"/role add-all run by {interaction.user}")
            added += 1
        except discord.HTTPException:
            failed += 1

    summary = f"*stamps **{role.name}** onto {added} member(s)* All done!"
    if failed:
        summary += f" ({failed} couldn't be given the role — probably role hierarchy.)"
    await interaction.followup.send(summary, allowed_mentions=discord.AllowedMentions(roles=False))
    await send_log(
        interaction.guild.id, title="🏷️ Role added to all members", color=discord.Color.green(), interaction=interaction,
        fields=[("Role", role.name), ("Added", str(added)), ("Failed", str(failed))],
    )


bot.tree.add_command(role_group)


# ---------------------------------------------------------------------------
# Friendly errors for missing permissions, instead of a raw Discord error
# ---------------------------------------------------------------------------

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Single friendly error boundary for every slash command."""
    original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
    command_name = interaction.command.qualified_name if interaction.command else "unknown"

    if isinstance(error, app_commands.MissingPermissions):
        msg = "🐾 You don't have the required server permissions for this command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "🐾 I don't have the Discord permissions needed for this command. Check my role and channel permissions."
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ Cinnamon needs a tiny cooldown. Try again <t:{int(time.time() + error.retry_after)}:R>."
    elif isinstance(error, app_commands.NoPrivateMessage):
        msg = "🏠 This command only works inside a Discord server."
    elif isinstance(original, discord.Forbidden):
        msg = "🔒 Discord refused the action. Check my role hierarchy and the channel permissions."
    elif isinstance(original, discord.NotFound):
        msg = "🔎 I couldn't find that Discord object. It may have been deleted or changed."
    elif isinstance(error, app_commands.TransformerError):
        msg = "🔎 One of the command values isn't valid. Check the selected member, channel, role, or option and try again."
    elif isinstance(error, app_commands.CheckFailure):
        msg = "🐱 Cinnamon says this command isn't available to you here."
    elif isinstance(original, discord.HTTPException):
        msg = "🌐 Discord returned an error while I was doing that. Please try again in a moment."
    else:
        log.exception("Unhandled slash-command error in /%s", command_name, exc_info=original)
        msg = "🐱💥 Something unexpected went wrong. Cinnamon logged the error so it can be investigated."

    try:
        embed = friendly_error_embed("Command error", msg, guild=interaction.guild)
        embed.add_field(name="Command", value=f"`/{command_name}`", inline=True)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException:
        # Last-resort fallback: never let the error handler itself crash.
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass

    try:
        await send_log(
            interaction.guild.id if interaction.guild else None,
            title="⚠️ Command error",
            description=f"`/{command_name}` failed with `{type(original).__name__}`.",
            color=discord.Color.red(),
            interaction=interaction,
        )
    except Exception:
        log.exception("Failed to write command-error log for /%s", command_name)


@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    """Friendly fallback for prefix commands such as ?work."""
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        msg = "🐾 You don't have the required permissions for that command."
    elif isinstance(error, commands.MissingRequiredArgument):
        msg = f"🔎 Missing `{error.param.name}`. Check the command's usage and try again."
    elif isinstance(error, commands.CommandOnCooldown):
        msg = f"⏳ Try again <t:{int(time.time() + error.retry_after)}:R>."
    else:
        log.exception("Unhandled prefix-command error", exc_info=error)
        msg = "🐱💥 Something unexpected went wrong. Cinnamon logged the error."
    try:
        await ctx.reply(embed=friendly_error_embed("Command error", msg, guild=ctx.guild), mention_author=False)
    except discord.HTTPException:
        pass


# ---------------------------------------------------------------------------
# Keep-alive web server (Koyeb / Render free tiers expect something bound
# to $PORT). Runs in a background thread alongside the bot.
# ---------------------------------------------------------------------------

flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Cinnamon is awake and purring. 🐾"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


# ---------------------------------------------------------------------------
# Extended features: warnings, user/server info, AFK, welcome/goodbye,
# edit/delete logging, reaction roles, auto-mod, temp-bans, leveling,
# giveaways, anti-raid, and channel lock/unlock.
# ---------------------------------------------------------------------------

# --- Persistence (same Upstash-or-local-file approach as Hangry Games' data) ---

BD_DATA_FILE = os.environ.get("BOT_DATA_FILE", "cinnamon_data.json")
BD_UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
BD_UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
BD_REDIS_KEY = "cinnamon_bot_data"


def _bd_encode() -> dict:
    return {
        "warnings": {f"{g}:{m}": v for (g, m), v in warnings_data.items()},
        "welcome_config": {str(k): v for k, v in welcome_config.items()},
        "goodbye_config": {str(k): v for k, v in goodbye_config.items()},
        "automod_config": {str(k): v for k, v in automod_config.items()},
        "xp_data": {f"{g}:{m}": v for (g, m), v in xp_data.items()},
        "reaction_role_ids": list(reaction_role_ids),
        "temp_bans": {f"{g}:{m}": v for (g, m), v in temp_bans.items()},
        "antiraid_config": {str(k): v for k, v in antiraid_config.items()},
        "case_counters": {str(k): v for k, v in case_counters.items()},
        "level_roles": {str(g): {str(l): r for l, r in v.items()} for g, v in level_roles.items()},
        "active_giveaways": {str(k): v for k, v in active_giveaways.items()},
        "active_polls": {str(k): v for k, v in active_polls.items()},
        "economy_balances": {f"{g}:{u}": v for (g, u), v in economy_balances.items()},
        "economy_inventory": {f"{g}:{u}": v for (g, u), v in economy_inventory.items()},
        "economy_quests": {f"{g}:{u}": v for (g, u), v in economy_quests.items()},
        "economy_cooldowns": {f"{g}:{u}:{a}": v for (g, u, a), v in economy_cooldowns.items()},
        "economy_log_channels": {str(k): v for k, v in economy_log_channels.items()},
        "economy_level_rewards_claimed": {f"{g}:{u}": list(levels) for (g, u), levels in economy_level_rewards_claimed.items()},
        "economy_income_roles": {str(g): {str(r): cfg for r, cfg in roles.items()} for g, roles in economy_income_roles.items()},
        "economy_items": ECONOMY_ITEMS,
        # Server configuration that should survive a restart/redeploy.
        "ai_channels": {str(k): v for k, v in ai_channels.items()},
        "disabled_channels": {str(k): list(v) for k, v in disabled_channels.items()},
        "log_channels": {str(k): v for k, v in log_channels.items()},
        "achievement_data": {f"{g}:{u}": v for (g, u), v in achievement_data.items()},
        "achievement_defs": {str(g): v for g, v in achievement_defs.items()},
        "achievement_roles": {str(g): {str(a): r for a, r in v.items()} for g, v in achievement_roles.items()},
        "achievement_config": {str(g): v for g, v in achievement_config.items()},
        "quest_config": {str(g): v for g, v in quest_config.items()},
        "quest_progress": {f"{g}:{u}": v for (g, u), v in quest_progress.items()},
        "quest_points": {f"{g}:{u}": v for (g, u), v in quest_points.items()},
        "quest_history": {f"{g}:{u}": v for (g, u), v in quest_history.items()},
        "quest_definitions": quest_definitions,
        "quest_shop": QUEST_SHOP,
    }


def _bd_decode(raw: dict):
    global warnings_data, welcome_config, goodbye_config, automod_config
    global xp_data, reaction_role_ids, temp_bans, antiraid_config, case_counters
    global level_roles, active_giveaways, active_polls, ai_channels, disabled_channels, log_channels
    global economy_balances, economy_inventory, economy_quests, economy_cooldowns, economy_log_channels
    global economy_level_rewards_claimed, economy_income_roles
    global achievement_data, achievement_defs, achievement_roles, achievement_config
    global quest_config, quest_progress, quest_points, quest_history
    warnings_data = defaultdict(list, {tuple(map(int, k.split(":"))): v for k, v in raw.get("warnings", {}).items()})
    welcome_config = {int(k): v for k, v in raw.get("welcome_config", {}).items()}
    goodbye_config = {int(k): v for k, v in raw.get("goodbye_config", {}).items()}
    automod_config = {int(k): v for k, v in raw.get("automod_config", {}).items()}
    xp_data = {tuple(map(int, k.split(":"))): v for k, v in raw.get("xp_data", {}).items()}
    reaction_role_ids = set(raw.get("reaction_role_ids", []))
    temp_bans = {tuple(map(int, k.split(":"))): v for k, v in raw.get("temp_bans", {}).items()}
    antiraid_config = {int(k): v for k, v in raw.get("antiraid_config", {}).items()}
    case_counters = {int(k): v for k, v in raw.get("case_counters", {}).items()}
    level_roles = {int(g): {int(l): r for l, r in v.items()} for g, v in raw.get("level_roles", {}).items()}
    active_giveaways = {int(k): v for k, v in raw.get("active_giveaways", {}).items()}
    active_polls = {int(k): v for k, v in raw.get("active_polls", {}).items()}
    economy_balances = {tuple(map(int, k.split(":"))): v for k, v in raw.get("economy_balances", {}).items()}
    economy_inventory = {tuple(map(int, k.split(":"))): v for k, v in raw.get("economy_inventory", {}).items()}
    economy_quests = {tuple(map(int, k.split(":"))): v for k, v in raw.get("economy_quests", {}).items()}
    economy_cooldowns = {}
    for k, v in raw.get("economy_cooldowns", {}).items():
        parts = k.split(":")
        if len(parts) == 3:
            economy_cooldowns[(int(parts[0]), int(parts[1]), parts[2])] = v
    economy_log_channels = {int(k): v for k, v in raw.get("economy_log_channels", {}).items()}
    economy_level_rewards_claimed = {}
    for k, levels in raw.get("economy_level_rewards_claimed", {}).items():
        parts = k.split(":")
        if len(parts) == 2:
            economy_level_rewards_claimed[(int(parts[0]), int(parts[1]))] = [int(x) for x in levels]
    economy_income_roles = {int(g): {int(r): cfg for r, cfg in roles.items()} for g, roles in raw.get("economy_income_roles", {}).items()}
    saved_items = raw.get("economy_items")
    if isinstance(saved_items, dict):
        ECONOMY_ITEMS.clear()
        for item_id, item in saved_items.items():
            if isinstance(item, dict):
                ECONOMY_ITEMS[str(item_id)] = {
                    "name": str(item.get("name", item_id))[:80],
                    "price": max(1, int(item.get("price", 1))),
                    "emoji": str(item.get("emoji", "🐾"))[:8],
                    "description": str(item.get("description", ""))[:300],
                    "max_per_person": max(0, int(item.get("max_per_person", 0))),
                }
    ai_channels = {int(k): v for k, v in raw.get("ai_channels", {}).items()}
    disabled_channels = defaultdict(set, {int(k): set(v) for k, v in raw.get("disabled_channels", {}).items()})
    log_channels = {int(k): v for k, v in raw.get("log_channels", {}).items()}
    achievement_data = {tuple(map(int, k.split(":"))): v for k, v in raw.get("achievement_data", {}).items()}
    achievement_defs = {int(g): v for g, v in raw.get("achievement_defs", {}).items()}
    achievement_roles = {int(g): {str(a): int(r) for a, r in v.items()} for g, v in raw.get("achievement_roles", {}).items()}
    achievement_config = {int(g): v for g, v in raw.get("achievement_config", {}).items()}
    quest_config = {int(g): v for g, v in raw.get("quest_config", {}).items()}
    quest_progress = {tuple(map(int, k.split(":"))): v for k, v in raw.get("quest_progress", {}).items()}
    quest_points = {tuple(map(int, k.split(":"))): int(v) for k, v in raw.get("quest_points", {}).items()}
    quest_history = {tuple(map(int, k.split(":"))): v for k, v in raw.get("quest_history", {}).items()}
    saved_qdefs = raw.get("quest_definitions")
    if isinstance(saved_qdefs, dict):
        for kind in ("daily", "weekly"):
            if isinstance(saved_qdefs.get(kind), dict):
                quest_definitions[kind] = saved_qdefs[kind]
    saved_qshop = raw.get("quest_shop")
    if isinstance(saved_qshop, dict):
        QUEST_SHOP.clear(); QUEST_SHOP.update(saved_qshop)


async def bd_load_data():
    """Load persisted settings (warnings, welcome/goodbye, auto-mod config, XP,
    reaction roles, temp-bans, anti-raid config). Uses Upstash Redis if
    configured (survives redeploys), otherwise a local JSON file (restarts
    only). Never raises — a missing/corrupt/unreachable store just means we
    start fresh."""
    if BD_UPSTASH_URL and BD_UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    BD_UPSTASH_URL, json=["GET", BD_REDIS_KEY],
                    headers={"Authorization": f"Bearer {BD_UPSTASH_TOKEN}"},
                ) as resp:
                    result = (await resp.json()).get("result")
            if result:
                _bd_decode(json.loads(result))
            return
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, ValueError) as e:
            log.error(f"Failed to load bot data from Upstash: {e}")
            return
    try:
        with open(BD_DATA_FILE, "r") as f:
            _bd_decode(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass


async def bd_save_data():
    """Persist settings. See bd_load_data for storage choice. Never raises —
    a failed save shouldn't break a command."""
    encoded = _bd_encode()
    if BD_UPSTASH_URL and BD_UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    BD_UPSTASH_URL, json=["SET", BD_REDIS_KEY, json.dumps(encoded)],
                    headers={"Authorization": f"Bearer {BD_UPSTASH_TOKEN}"},
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.error(f"Failed to save bot data to Upstash: {e}")
        return
    try:
        with open(BD_DATA_FILE, "w") as f:
            json.dump(encoded, f)
    except OSError as e:
        log.error(f"Failed to save bot data: {e}")


@tasks.loop(minutes=5)
async def periodic_save():
    """XP changes on every eligible message, so we batch-save it (and anything
    else pending) every few minutes instead of hitting the store on every
    single message — everything admin-triggered (warn, welcome config, etc.)
    still saves immediately when it happens."""
    await bd_save_data()


def next_case(guild_id: int) -> int:
    """Issue the next sequential moderation case number for this guild
    (warn/kick/ban/unban/mute/tempban/automod all share one counter, so mods
    can reference "case #N" unambiguously). Caller is responsible for saving —
    it's always called right before a send_log/bd_save_data anyway."""
    case_counters[guild_id] = case_counters.get(guild_id, 0) + 1
    return case_counters[guild_id]


async def storage_status() -> dict:
    """Live health check of the persistence backend. Does NOT touch real data —
    just confirms the connection actually works right now. Returns
    {"backend": "Upstash Redis" | "local JSON file", "connected": bool, "detail": str}."""
    if BD_UPSTASH_URL and BD_UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    BD_UPSTASH_URL, json=["PING"],
                    headers={"Authorization": f"Bearer {BD_UPSTASH_TOKEN}"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    data = await resp.json()
            ok = data.get("result") == "PONG"
            return {
                "backend": "Upstash Redis", "connected": ok,
                "detail": "Reachable — data survives restarts and redeploys." if ok
                          else f"Configured but not responding as expected: {data}",
            }
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
            return {"backend": "Upstash Redis", "connected": False, "detail": f"Configured but unreachable: {e}"}
    file_writable = True
    try:
        with open(BD_DATA_FILE, "a"):
            pass
    except OSError:
        file_writable = False
    return {
        "backend": "local JSON file", "connected": file_writable,
        "detail": (
            "No UPSTASH_REDIS_REST_URL/TOKEN set. Data survives plain restarts but is "
            "LIKELY WIPED on a Render redeploy (no persistent disk on the free tier)."
        ) if file_writable else "Local file isn't writable — data isn't being saved at all right now.",
    }


# --- Warnings -------------------------------------------------------------

def add_warning(guild_id: int, member_id: int, reason: str, moderator: discord.abc.User) -> int:
    lst = warnings_data[(guild_id, member_id)]
    lst.append({
        "reason": reason, "mod_id": moderator.id, "mod_name": str(moderator),
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    return len(lst)


_WARN_LOG_TITLES = {"⚠️ Member warned", "🚨 Auto-mod action"}
_ID_IN_PARENS_RE = re.compile(r"\((\d+)\)\s*$")


async def recover_warnings_from_log(guild: discord.Guild, limit: int = 2000) -> int:
    """Rebuild this guild's warnings entirely from the mod log channel's message
    history — used when the persisted store comes back empty for a guild that
    has a log channel configured. Only recovers what's still in the channel's
    scanned history (bounded by `limit` messages and Discord's own retention),
    so this is a best-effort recovery, not a guarantee of completeness."""
    channel_id = log_channels.get(guild.id)
    if channel_id is None:
        return 0
    channel = bot.get_channel(channel_id)
    if channel is None:
        return 0

    found: list[tuple[int, dict]] = []  # (member_id, warning_dict)
    max_case = 0
    try:
        async for message in channel.history(limit=limit):
            for embed in message.embeds:
                case_val = next((f.value for f in embed.fields if f.name == "Case"), "")
                if case_val.lstrip("#").isdigit():
                    max_case = max(max_case, int(case_val.lstrip("#")))
                if embed.title not in _WARN_LOG_TITLES:
                    continue
                fields = {f.name: f.value for f in embed.fields}
                member_field = fields.get("Member", "")
                m = _ID_IN_PARENS_RE.search(member_field)
                if not m:
                    continue
                member_id = int(m.group(1))
                reason = fields.get("Reason", "Unknown (recovered from log)")
                if embed.title == "🚨 Auto-mod action":
                    reason = f"[Auto-mod] {reason}"
                    mod_name = "Auto-mod (recovered)"
                    mod_id = bot.user.id if bot.user else 0
                else:
                    footer_m = re.search(r"Run by (.+?) • #", embed.footer.text or "") if embed.footer else None
                    mod_name = footer_m.group(1) if footer_m else "Unknown (recovered from log)"
                    mod_id = 0
                ts = embed.timestamp.isoformat() if embed.timestamp else datetime.datetime.now(datetime.timezone.utc).isoformat()
                found.append((member_id, {"reason": reason, "mod_id": mod_id, "mod_name": mod_name, "ts": ts}))
    except discord.HTTPException as e:
        log.error(f"Failed to scan log channel for warning recovery in guild {guild.id}: {e}")
        return 0

    if max_case > case_counters.get(guild.id, 0):
        case_counters[guild.id] = max_case  # so new cases continue after the highest one logged
        await bd_save_data()
    if not found:
        return 0
    found.sort(key=lambda pair: pair[1]["ts"])  # oldest first, matching normal append order
    for member_id, warning in found:
        warnings_data[(guild.id, member_id)].append(warning)
    await bd_save_data()
    return len(found)


@bot.tree.command(name="warn", description="Warn a member and log it")
@app_commands.describe(member="Who to warn", reason="Why")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.guild_only()
async def warn(interaction: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 300]):
    count = add_warning(interaction.guild.id, member.id, reason, interaction.user)
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 *hisses a warning at* {member.mention} — now has **{count}** warning(s). (Case #{case_id})",
        allowed_mentions=discord.AllowedMentions(users=True),
    )
    await send_log(
        interaction.guild.id, title="⚠️ Member warned", color=discord.Color.orange(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Reason", reason), ("Total warnings", str(count))],
    )


@bot.tree.command(name="warnings", description="View a member's warning history")
@app_commands.describe(member="Whose warnings to view")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.guild_only()
async def warnings_cmd(interaction: discord.Interaction, member: discord.Member):
    lst = warnings_data.get((interaction.guild.id, member.id), [])
    if not lst:
        return await interaction.response.send_message(f"{member.display_name} has no warnings. 🐾", ephemeral=True)
    embed = discord.Embed(title=f"⚠️ Warnings for {member.display_name}", color=discord.Color.orange())
    for i, w in enumerate(lst[-10:], 1):
        embed.add_field(name=f"#{i} — {w['ts'][:10]}", value=f"{w['reason']} (by {w['mod_name']})", inline=False)
    embed.set_footer(text=f"{len(lst)} total warning(s)")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="clearwarnings", description="Clear all warnings for a member")
@app_commands.describe(member="Whose warnings to clear")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    removed = len(warnings_data.pop((interaction.guild.id, member.id), []))
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Cleared **{removed}** warning(s) for {member.display_name}.")
    await send_log(
        interaction.guild.id, title="🧹 Warnings cleared", color=discord.Color.green(), interaction=interaction,
        fields=[("Member", f"{member} ({member.id})"), ("Cleared", str(removed))],
    )


# --- User / server info -----------------------------------------------------

@bot.tree.command(name="userinfo", description="Show info about a member")
@app_commands.describe(member="Who to look up (defaults to you)")
@app_commands.guild_only()
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    warn_count = len(warnings_data.get((interaction.guild.id, member.id), []))
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    embed = discord.Embed(
        title=f"🐾 {member.display_name}",
        color=member.color if member.color.value else 0xFFB02E,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, "R"), inline=True)
    embed.add_field(
        name="Joined server",
        value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Unknown", inline=True,
    )
    embed.add_field(name="Warnings", value=str(warn_count), inline=True)
    embed.add_field(name=f"Roles ({len(roles)})", value=", ".join(roles) if roles else "None", inline=False)
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="serverinfo", description="Show info about this server")
@app_commands.guild_only()
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(title=f"🐾 {g.name}", color=0xFFB02E)
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, "R"), inline=True)
    embed.add_field(name="Members", value=str(g.member_count), inline=True)
    embed.add_field(name="Boost tier", value=str(g.premium_tier), inline=True)
    embed.add_field(name="Text channels", value=str(len(g.text_channels)), inline=True)
    embed.add_field(name="Voice channels", value=str(len(g.voice_channels)), inline=True)
    embed.add_field(name="Roles", value=str(len(g.roles)), inline=True)
    embed.add_field(name="Owner", value=g.owner.mention if g.owner else "Unknown", inline=True)
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


# --- AFK ---------------------------------------------------------------------

@bot.tree.command(name="afk", description="Mark yourself AFK; Cinnamon notifies anyone who pings you")
@app_commands.describe(reason="Optional reason")
@app_commands.guild_only()
async def afk_cmd(interaction: discord.Interaction, reason: str = "AFK"):
    afk_users[(interaction.guild.id, interaction.user.id)] = reason
    await interaction.response.send_message(
        f"🐾 {interaction.user.mention} is now AFK: {reason}",
        allowed_mentions=discord.AllowedMentions(users=True),
    )


# --- Welcome / goodbye messages ----------------------------------------------

welcome_group = app_commands.Group(name="welcome", description="Configure member-join messages")


def _validate_template(message: str) -> str | None:
    """Returns an error string if the template has a bad placeholder, else None."""
    try:
        message.format(member="x", server="y")
        return None
    except (KeyError, IndexError, ValueError) as e:
        return (
            f"That message template isn't valid ({e}). Only `{{member}}` and `{{server}}` "
            f"are supported as placeholders — check for typos or stray `{{`/`}}`."
        )


@welcome_group.command(name="set", description="Set the welcome channel/message")
@app_commands.describe(channel="Channel to post welcomes in", message="Use {member} and {server} as placeholders")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcome_set(interaction: discord.Interaction, channel: discord.TextChannel,
                       message: app_commands.Range[str, 1, 800] = "🐾 Welcome {member} to {server}! Glad you're here."):
    error = _validate_template(message)
    if error:
        return await interaction.response.send_message(error, ephemeral=True)
    welcome_config[interaction.guild.id] = {"channel_id": channel.id, "message": message}
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Welcome messages will post in {channel.mention}.")


@welcome_group.command(name="disable", description="Turn off welcome messages")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcome_disable(interaction: discord.Interaction):
    welcome_config.pop(interaction.guild.id, None)
    await bd_save_data()
    await interaction.response.send_message("🐾 Welcome messages turned off.")


goodbye_group = app_commands.Group(name="goodbye", description="Configure member-leave messages")


@goodbye_group.command(name="set", description="Set the goodbye channel/message")
@app_commands.describe(channel="Channel to post goodbyes in", message="Use {member} and {server} as placeholders")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def goodbye_set(interaction: discord.Interaction, channel: discord.TextChannel,
                       message: app_commands.Range[str, 1, 800] = "🐾 {member} has left {server}. We'll miss you!"):
    error = _validate_template(message)
    if error:
        return await interaction.response.send_message(error, ephemeral=True)
    goodbye_config[interaction.guild.id] = {"channel_id": channel.id, "message": message}
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Goodbye messages will post in {channel.mention}.")


@goodbye_group.command(name="disable", description="Turn off goodbye messages")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def goodbye_disable(interaction: discord.Interaction):
    goodbye_config.pop(interaction.guild.id, None)
    await bd_save_data()
    await interaction.response.send_message("🐾 Goodbye messages turned off.")


# --- Reaction roles (self-assignable, via button) ----------------------------

class ReactionRoleView(discord.ui.View):
    """timeout=None + a static custom_id makes this a persistent view: it keeps
    working across restarts as long as bot.add_view() is called again for the
    same role_id on startup (done in on_ready, from reaction_role_ids)."""

    def __init__(self, role_id: int, label: str = "Toggle Role 🐾"):
        super().__init__(timeout=None)
        self.role_id = role_id
        button = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.primary, custom_id=f"rr:{role_id}")
        button.callback = self.toggle
        self.add_item(button)

    async def toggle(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            return await interaction.response.send_message("That role no longer exists.", ephemeral=True)
        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Reaction role toggle")
                await interaction.response.send_message(f"➖ Removed **{role.name}**.", ephemeral=True)
            else:
                await member.add_roles(role, reason="Reaction role toggle")
                await interaction.response.send_message(f"➕ Added **{role.name}**!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to manage that role — check my role position.", ephemeral=True
            )


reactionrole_group = app_commands.Group(name="reactionrole", description="Self-assignable roles via a button")


@reactionrole_group.command(name="create", description="Post a button members can click to toggle a role")
@app_commands.describe(role="The role to toggle", label="Button text", description="Message shown above the button")
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def reactionrole_create(interaction: discord.Interaction, role: discord.Role,
                               label: str = "Toggle Role 🐾", description: str = None):
    if role >= interaction.guild.me.top_role:
        return await interaction.response.send_message(
            "I can't manage a role higher than or equal to my own top role — move my role above it first.",
            ephemeral=True,
        )
    embed = discord.Embed(
        title="🐾 Self-Assignable Role",
        description=description or f"Click below to toggle **{role.name}**.",
        color=0xFFB02E,
    )
    view = ReactionRoleView(role.id, label)
    await interaction.response.send_message(embed=embed, view=view)
    reaction_role_ids.add(role.id)
    await bd_save_data()
    bot.add_view(view)  # re-register for persistence in case this process restarts


@reactionrole_group.command(name="remove", description="Stop a role from being self-assignable")
@app_commands.describe(role="The role to stop tracking")
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guild_only()
async def reactionrole_remove(interaction: discord.Interaction, role: discord.Role):
    reaction_role_ids.discard(role.id)
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 **{role.name}** is no longer tracked as self-assignable. (Existing buttons for it stop working "
        f"after the next restart; this doesn't delete the message.)",
        ephemeral=True,
    )


# --- Auto-moderation -----------------------------------------------------------

DEFAULT_AUTOMOD = {"words": [], "spam": False, "mentions": False, "invites": False, "mention_threshold": 5}
_INVITE_RE = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)\S+", re.IGNORECASE)


def get_automod(guild_id: int) -> dict:
    return automod_config.setdefault(guild_id, dict(DEFAULT_AUTOMOD))


async def _automod_strike(message: discord.Message, reason: str):
    try:
        await message.delete()
    except discord.HTTPException:
        pass
    count = add_warning(
        message.guild.id, message.author.id, f"[Auto-mod] {reason}",
        bot.user if bot.user else message.author,
    )
    case_id = next_case(message.guild.id)
    await bd_save_data()
    try:
        note = await message.channel.send(
            f"🐾 {message.author.mention}, that got removed for {reason}. Warning #{count} logged.",
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        await asyncio.sleep(6)
        await note.delete()
    except discord.HTTPException:
        pass
    await send_log(
        message.guild.id, title="🚨 Auto-mod action", color=discord.Color.red(),
        fields=[("Case", f"#{case_id}"), ("Member", f"{message.author} ({message.author.id})"), ("Reason", reason),
                ("Channel", message.channel.mention)],
    )


async def run_automod(message: discord.Message) -> bool:
    """Returns True if the message was removed (caller should stop processing it)."""
    if message.author.guild_permissions.manage_messages:
        return False  # mods bypass auto-mod
    cfg = automod_config.get(message.guild.id)
    if not cfg:
        return False

    if cfg.get("invites") and _INVITE_RE.search(message.content):
        await _automod_strike(message, "posting a Discord invite link")
        return True

    content_lower = message.content.lower()
    for w in cfg.get("words", []):
        if w and w.lower() in content_lower:
            await _automod_strike(message, "using a banned word")
            return True

    if cfg.get("mentions") and (len(message.mentions) + len(message.role_mentions)) >= cfg.get("mention_threshold", 5):
        await _automod_strike(message, "mass-mentioning members/roles")
        return True

    if cfg.get("spam"):
        key = (message.guild.id, message.author.id)
        dq = spam_tracker[key]
        dq.append(time.monotonic())
        if len(dq) == dq.maxlen and (dq[-1] - dq[0]) < 5:  # 6 msgs within 5s
            await _automod_strike(message, "spamming messages")
            return True

    return False


automod_group = app_commands.Group(name="automod", description="Configure auto-moderation")
automod_word_group = app_commands.Group(name="word", description="Manage banned words", parent=automod_group)


@automod_word_group.command(name="add", description="Add a banned word/phrase")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_word_add(interaction: discord.Interaction, word: app_commands.Range[str, 1, 100]):
    cfg = get_automod(interaction.guild.id)
    if word.lower() not in (w.lower() for w in cfg["words"]):
        cfg["words"].append(word)
        await bd_save_data()
    await interaction.response.send_message(f"🐾 Added `{word}` to the banned word list.", ephemeral=True)


@automod_word_group.command(name="remove", description="Remove a banned word/phrase")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_word_remove(interaction: discord.Interaction, word: app_commands.Range[str, 1, 100]):
    cfg = get_automod(interaction.guild.id)
    cfg["words"] = [w for w in cfg["words"] if w.lower() != word.lower()]
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Removed `{word}` from the banned word list.", ephemeral=True)


@automod_word_group.command(name="list", description="List banned words")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_word_list(interaction: discord.Interaction):
    words = get_automod(interaction.guild.id)["words"]
    await interaction.response.send_message(
        "Banned words: " + (", ".join(f"`{w}`" for w in words) if words else "*(none set)*"), ephemeral=True
    )


@automod_group.command(name="spam", description="Toggle spam detection (rapid repeated messages)")
@app_commands.describe(enabled="On/off")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_spam(interaction: discord.Interaction, enabled: bool):
    get_automod(interaction.guild.id)["spam"] = enabled
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Spam detection turned **{'on' if enabled else 'off'}**.")


@automod_group.command(name="mentions", description="Toggle mass-mention detection")
@app_commands.describe(enabled="On/off", threshold="Mentions in one message that triggers it (default 5)")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_mentions(interaction: discord.Interaction, enabled: bool, threshold: int = 5):
    cfg = get_automod(interaction.guild.id)
    cfg["mentions"] = enabled
    cfg["mention_threshold"] = threshold
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 Mass-mention detection turned **{'on' if enabled else 'off'}** (threshold {threshold})."
    )


@automod_group.command(name="invites", description="Toggle auto-deleting Discord invite links")
@app_commands.describe(enabled="On/off")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def automod_invites(interaction: discord.Interaction, enabled: bool):
    get_automod(interaction.guild.id)["invites"] = enabled
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Invite-link filter turned **{'on' if enabled else 'off'}**.")


# --- Temp-ban ------------------------------------------------------------------

@bot.tree.command(name="tempban", description="Temporarily ban a member; auto-unbanned after the duration")
@app_commands.describe(member="Who to ban", duration_hours="Hours until auto-unban", reason="Why")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
@app_commands.guild_only()
async def tempban(interaction: discord.Interaction, member: discord.Member, duration_hours: float,
                   reason: app_commands.Range[str, 1, 300] = "No reason given"):
    unban_at = time.time() + duration_hours * 3600
    await member.ban(reason=f"Tempban by {interaction.user}: {reason}")
    temp_bans[(interaction.guild.id, member.id)] = unban_at
    case_id = next_case(interaction.guild.id)
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 {member.mention} temp-banned for **{duration_hours}h**. Reason: {reason}",
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await send_log(
        interaction.guild.id, title="⏳ Member temp-banned", color=discord.Color.red(), interaction=interaction,
        fields=[("Case", f"#{case_id}"), ("Member", f"{member} ({member.id})"), ("Duration", f"{duration_hours}h"), ("Reason", reason)],
    )


@tasks.loop(minutes=5)
async def check_tempbans():
    now = time.time()
    due = [key for key, unban_at in temp_bans.items() if unban_at <= now]
    for guild_id, user_id in due:
        guild = bot.get_guild(guild_id)
        if guild:
            try:
                await guild.unban(discord.Object(id=user_id), reason="Temp-ban expired")
                await send_log(
                    guild_id, title="⏳ Temp-ban expired — member unbanned", color=discord.Color.green(),
                    fields=[("User ID", str(user_id))],
                )
            except discord.HTTPException:
                pass
        temp_bans.pop((guild_id, user_id), None)
    if due:
        await bd_save_data()


# --- Leveling / XP --------------------------------------------------------------

def level_from_xp(xp: int) -> int:
    # Inverse of total_xp_for_level's quadratic (25*n^2 + 75*n <= xp).
    n = (-75 + math.sqrt(5625 + 100 * xp)) / 50
    return max(0, int(n))


def total_xp_for_level(level: int) -> int:
    return 25 * level * level + 75 * level


async def sync_level_roles(member: discord.Member, level: int) -> list[str]:
    """Give `member` every level role they've earned but don't have yet. Runs on
    each XP award (not just level-ups), so roles added later still reach people
    who are already past that level. Returns the names of roles newly given."""
    cfg = level_roles.get(member.guild.id)
    if not cfg:
        return []
    have = {r.id for r in member.roles}
    top = member.guild.me.top_role
    to_add = []
    for lvl, rid in cfg.items():
        if lvl <= level and rid not in have:
            role = member.guild.get_role(rid)
            if role and not role.managed and role < top:
                to_add.append(role)
    if not to_add:
        return []
    try:
        await member.add_roles(*to_add, reason=f"Reached level {level}")
    except discord.HTTPException:
        return []
    return [r.name for r in to_add]


async def award_xp(message: discord.Message):
    key = (message.guild.id, message.author.id)
    now = time.monotonic()
    if now - xp_cooldowns.get(key, 0) < 60:
        return
    xp_cooldowns[key] = now
    old_xp = xp_data.get(key, 0)
    old_level = level_from_xp(old_xp)
    new_xp = old_xp + random.randint(15, 25)
    xp_data[key] = new_xp
    qdone = await quest_record_event(message.guild.id, message.author.id, "xp", new_xp - old_xp, member=message.author)
    new_level = level_from_xp(new_xp)
    if new_level > old_level:
        qdone += await quest_record_event(message.guild.id, message.author.id, "levels", new_level - old_level, member=message.author)
    if qdone:
        await bd_save_data()
    current_achievement_level = achievement_progress(message.guild.id, message.author.id)["stats"].get("levels", 0)
    if new_level > current_achievement_level:
        await achievement_record(message.guild.id, message.author.id, metric_updates={"levels": new_level - current_achievement_level}, member=message.author)
    gained = await sync_level_roles(message.author, new_level)
    if new_level > old_level:
        text = f"🐾 {message.author.mention} just leveled up to **Level {new_level}**!"
        if gained:
            text += f" New role{'s' if len(gained) > 1 else ''}: **{', '.join(gained)}**"
        reward_levels = [lvl for lvl, amount in ECONOMY_LEVEL_REWARDS.items() if old_level < lvl <= new_level and not economy_level_reward_claimed(message.guild.id, message.author.id, lvl)]
        reward_total = sum(ECONOMY_LEVEL_REWARDS[lvl] for lvl in reward_levels)
        if reward_total:
            economy_balances[(message.guild.id, message.author.id)] = economy_balance(message.guild.id, message.author.id) + reward_total
            await achievement_record(message.guild.id, message.author.id, metric_updates={"lifetime_earned": reward_total}, member=message.author)
            for lvl in reward_levels:
                mark_economy_level_reward_claimed(message.guild.id, message.author.id, lvl)
            await economy_log(message.guild.id, title="🏆 Level Catnip reward", fields=[("User", f"{message.author} ({message.author.id})"), ("Levels", ", ".join(map(str, reward_levels))), ("Reward", f"+{reward_total:,} Catnip")])
            text += f"\n🌿 Level reward: **+{reward_total:,} Catnip**!"
            await bd_save_data()
        try:
            await message.channel.send(
                text,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False),
            )
        except discord.HTTPException:
            pass


@bot.tree.command(name="rank", description="Show your (or someone's) level and XP")
@app_commands.describe(member="Who to check (defaults to you)")
@app_commands.guild_only()
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    xp = xp_data.get((interaction.guild.id, member.id), 0)
    level = level_from_xp(xp)
    this_level_xp = total_xp_for_level(level)
    next_level_xp = total_xp_for_level(level + 1)
    embed = discord.Embed(title=f"🐾 {member.display_name}'s Rank", color=0xFFB02E)
    embed.add_field(name="Level", value=str(level), inline=True)
    embed.add_field(name="Total XP", value=str(xp), inline=True)
    embed.add_field(name="Progress", value=f"{xp - this_level_xp}/{next_level_xp - this_level_xp} XP to next level", inline=True)
    reward = ECONOMY_LEVEL_REWARDS.get(level)
    if reward:
        embed.add_field(name="🌿 Level reward", value=f"+{reward:,} Catnip at this level", inline=True)
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="leaderboard", description="Show the top 10 members by XP in this server")
@app_commands.guild_only()
async def leaderboard(interaction: discord.Interaction):
    entries = sorted(
        ((uid, xp) for (gid, uid), xp in xp_data.items() if gid == interaction.guild.id),
        key=lambda e: e[1], reverse=True,
    )[:10]
    if not entries:
        return await interaction.response.send_message("No one has earned XP yet. 🐾", ephemeral=True)
    lines = []
    for i, (uid, xp) in enumerate(entries, 1):
        member = interaction.guild.get_member(uid)
        name = member.display_name if member else f"User {uid}"
        lines.append(f"**#{i}** {name} — Level {level_from_xp(xp)} ({xp} XP)")
    embed = discord.Embed(title="🏆 XP Leaderboard", description="\n".join(lines), color=0xFEE75C)
    await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


# --- Level roles ----------------------------------------------------------------

levelrole_group = app_commands.Group(name="levelrole", description="Give roles automatically at certain levels")


@levelrole_group.command(name="add", description="Give a role automatically when members reach a level")
@app_commands.describe(level="Level that unlocks the role", role="Role to give")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def levelrole_add(interaction: discord.Interaction, level: app_commands.Range[int, 1, 100], role: discord.Role):
    if role.is_default() or role.managed:
        return await interaction.response.send_message("That role can't be assigned by a bot.", ephemeral=True)
    if role >= interaction.guild.me.top_role:
        return await interaction.response.send_message(
            "That role is above my highest role, so I can't hand it out. Move my role higher in Server Settings → Roles.",
            ephemeral=True,
        )
    level_roles.setdefault(interaction.guild.id, {})[level] = role.id
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 Members will get **{role.name}** at **Level {level}**. "
        f"Anyone already past that level gets it the next time they earn XP.",
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await send_log(
        interaction.guild.id, title="🎖️ Level role added", color=discord.Color.green(), interaction=interaction,
        fields=[("Level", str(level)), ("Role", role.name)],
    )


@levelrole_group.command(name="remove", description="Stop giving a role at a level (members keep roles they already have)")
@app_commands.describe(level="The level to remove the reward from")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelrole_remove(interaction: discord.Interaction, level: app_commands.Range[int, 1, 100]):
    cfg = level_roles.get(interaction.guild.id, {})
    if cfg.pop(level, None) is None:
        return await interaction.response.send_message(f"No level role is set for level {level}.", ephemeral=True)
    await bd_save_data()
    await interaction.response.send_message(f"🐾 Removed the Level {level} reward. Members keep roles they already earned.")
    await send_log(
        interaction.guild.id, title="🎖️ Level role removed", color=discord.Color.orange(), interaction=interaction,
        fields=[("Level", str(level))],
    )


@levelrole_group.command(name="list", description="Show this server's level roles")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def levelrole_list(interaction: discord.Interaction):
    cfg = level_roles.get(interaction.guild.id, {})
    if not cfg:
        return await interaction.response.send_message("No level roles set. Add one with `/levelrole add`.", ephemeral=True)
    lines = []
    for lvl in sorted(cfg):
        role = interaction.guild.get_role(cfg[lvl])
        lines.append(f"**Level {lvl}** → {role.name if role else '(deleted role)'}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


# --- Standalone giveaways (persistent — survive restarts) --------------------------
# State lives in active_giveaways (saved with everything else); the Enter button
# is a persistent view matched by custom_id and looked up by message ID, so it
# keeps working after a restart, and check_timers ends giveaways on schedule.

def _giveaway_embed(gw: dict, winner_ids: list[int] | None = None) -> discord.Embed:
    if winner_ids is None:
        embed = discord.Embed(
            title="🎉 Giveaway!", color=0xFEE75C,
            description=f"**Prize:** {gw['prize']}\n**Winners:** {gw['winners']}\n"
                        f"Ends <t:{int(gw['ends_at'])}:R>\nHosted by <@{gw['host_id']}>",
        )
    else:
        won = " ".join(f"<@{u}>" for u in winner_ids) if winner_ids else "No one entered 🐾"
        embed = discord.Embed(
            title="🎉 Giveaway ended", color=0x99AAB5,
            description=f"**Prize:** {gw['prize']}\n**Winner{'s' if len(winner_ids) > 1 else ''}:** {won}\n"
                        f"Hosted by <@{gw['host_id']}>",
        )
    return embed


class GiveawayView(discord.ui.View):
    def __init__(self, disabled: bool = False):
        super().__init__(timeout=None)  # persistent: registered on startup via bot.add_view
        btn = discord.ui.Button(label="🎉 Enter", style=discord.ButtonStyle.success,
                                custom_id="giveaway:enter", disabled=disabled)
        btn.callback = self._enter
        self.add_item(btn)

    async def _enter(self, interaction: discord.Interaction):
        gw = active_giveaways.get(interaction.message.id)
        if gw is None:
            return await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
        uid = interaction.user.id
        if uid in gw["entrants"]:
            gw["entrants"].remove(uid)
            text = "You left the giveaway."
        else:
            gw["entrants"].append(uid)
            text = "🎉 You're entered! Click again to leave."
        await interaction.response.send_message(text, ephemeral=True)
        await bd_save_data()  # after responding: Discord only gives us 3s to answer


async def finish_giveaway(mid: int):
    gw = active_giveaways.pop(mid, None)
    if gw is None:
        return
    await bd_save_data()
    channel = bot.get_channel(gw["channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(mid)
    except discord.HTTPException:
        return  # message was deleted — nothing to update
    entrants = gw["entrants"]
    winner_ids = random.sample(entrants, min(gw["winners"], len(entrants))) if entrants else []
    try:
        await message.edit(embed=_giveaway_embed(gw, winner_ids), view=GiveawayView(disabled=True))
    except discord.HTTPException:
        pass
    if winner_ids:
        text = f"🎉 Congrats {' '.join(f'<@{u}>' for u in winner_ids)}! You won **{gw['prize']}**!"
    else:
        text = "🐾 No one entered the giveaway — no winners this time."
    try:
        await message.reply(text, allowed_mentions=discord.AllowedMentions(users=True))
    except discord.HTTPException:
        pass


giveaway_group = app_commands.Group(name="giveaway", description="Run a simple prize giveaway")


@giveaway_group.command(name="start", description="Start a giveaway")
@app_commands.describe(duration_minutes="How long the giveaway runs", winners="Number of winners", prize="What's being given away")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def giveaway_start(interaction: discord.Interaction, duration_minutes: app_commands.Range[int, 1, 43200],
                          winners: app_commands.Range[int, 1, 20], prize: app_commands.Range[str, 1, 200]):
    gw = {
        "guild_id": interaction.guild.id, "channel_id": interaction.channel.id, "host_id": interaction.user.id,
        "winners": winners, "prize": prize, "ends_at": time.time() + duration_minutes * 60, "entrants": [],
    }
    await interaction.response.send_message(embed=_giveaway_embed(gw), view=GiveawayView())
    msg = await interaction.original_response()
    active_giveaways[msg.id] = gw
    await bd_save_data()


@giveaway_group.command(name="end", description="End a giveaway early and pick winners now")
@app_commands.describe(message_id="The ID of the giveaway message")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def giveaway_end(interaction: discord.Interaction, message_id: str):
    try:
        mid = int(message_id)
    except ValueError:
        return await interaction.response.send_message("That doesn't look like a valid message ID.", ephemeral=True)
    gw = active_giveaways.get(mid)
    if not gw or gw["guild_id"] != interaction.guild.id:
        return await interaction.response.send_message("No active giveaway with that message ID.", ephemeral=True)
    await interaction.response.send_message("Ending the giveaway now...", ephemeral=True)
    await finish_giveaway(mid)


# --- Polls (persistent — survive restarts) ---------------------------------------

def _poll_embed(poll: dict, ended: bool = False) -> discord.Embed:
    options, votes = poll["options"], poll["votes"]
    counts = [0] * len(options)
    for idx in votes.values():
        if 0 <= idx < len(options):
            counts[idx] += 1
    total = sum(counts)
    lines = []
    for i, (opt, c) in enumerate(zip(options, counts), 1):
        pct = c / total if total else 0
        filled = round(pct * 10)
        lines.append(f"**{i}. {opt}**\n{'█' * filled}{'░' * (10 - filled)} {c} vote(s) ({pct:.0%})")
    status = "Poll ended" if ended else f"Ends <t:{int(poll['ends_at'])}:R> · tap the same option again to remove your vote"
    embed = discord.Embed(
        title=f"📊 {poll['question']}", description="\n\n".join(lines) + f"\n\n{status}",
        color=0x99AAB5 if ended else 0xFFB02E,
    )
    embed.set_footer(text=f"{total} vote(s) · Started by {poll['host_name']}")
    return embed


class PollView(discord.ui.View):
    def __init__(self, options: list[str] | None = None, disabled: bool = False):
        super().__init__(timeout=None)  # persistent: registered on startup via bot.add_view
        for i in range(len(options) if options else 4):
            label = f"{i + 1}. {options[i]}"[:80] if options else f"Option {i + 1}"
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary,
                                    custom_id=f"poll:{i}", disabled=disabled)
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    @staticmethod
    def _make_callback(idx: int):
        async def callback(interaction: discord.Interaction):
            poll = active_polls.get(interaction.message.id)
            if poll is None:
                return await interaction.response.send_message("This poll has ended.", ephemeral=True)
            if idx >= len(poll["options"]):
                return await interaction.response.send_message("That option doesn't exist.", ephemeral=True)
            uid = str(interaction.user.id)
            if poll["votes"].get(uid) == idx:
                del poll["votes"][uid]  # tapping your current choice again removes your vote
            else:
                poll["votes"][uid] = idx
            await interaction.response.edit_message(embed=_poll_embed(poll))
            await bd_save_data()  # after responding: Discord only gives us 3s to answer
        return callback


async def finish_poll(mid: int):
    poll = active_polls.pop(mid, None)
    if poll is None:
        return
    await bd_save_data()
    channel = bot.get_channel(poll["channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(mid)
    except discord.HTTPException:
        return
    try:
        await message.edit(embed=_poll_embed(poll, ended=True), view=PollView(poll["options"], disabled=True))
    except discord.HTTPException:
        pass
    counts = [0] * len(poll["options"])
    for idx in poll["votes"].values():
        if 0 <= idx < len(counts):
            counts[idx] += 1
    if not any(counts):
        text = "📊 The poll ended with no votes."
    else:
        top = max(counts)
        winners = [poll["options"][i] for i, c in enumerate(counts) if c == top]
        text = (f"📊 Poll ended — **{winners[0]}** wins with {top} vote(s)!" if len(winners) == 1
                else f"📊 Poll ended in a tie between **{' & '.join(winners)}** ({top} vote(s) each).")
    try:
        await message.reply(text, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass


@bot.tree.command(name="poll", description="Start a poll with 2-4 options")
@app_commands.describe(
    question="What are you asking?", option1="First option", option2="Second option",
    option3="Third option (optional)", option4="Fourth option (optional)",
    duration_minutes="How long the poll stays open (default 24 hours, max 7 days)",
)
@app_commands.guild_only()
async def poll(interaction: discord.Interaction, question: app_commands.Range[str, 1, 200],
               option1: app_commands.Range[str, 1, 60], option2: app_commands.Range[str, 1, 60],
               option3: app_commands.Range[str, 1, 60] = None, option4: app_commands.Range[str, 1, 60] = None,
               duration_minutes: app_commands.Range[int, 1, 10080] = 1440):
    options = [o for o in (option1, option2, option3, option4) if o]
    p = {
        "guild_id": interaction.guild.id, "channel_id": interaction.channel.id,
        "host_id": interaction.user.id, "host_name": interaction.user.display_name,
        "question": question, "options": options, "votes": {},
        "ends_at": time.time() + duration_minutes * 60,
    }
    await interaction.response.send_message(embed=_poll_embed(p), view=PollView(options),
                                            allowed_mentions=discord.AllowedMentions.none())
    msg = await interaction.original_response()
    active_polls[msg.id] = p
    await bd_save_data()


@tasks.loop(seconds=30)
async def check_timers():
    """Ends any giveaway/poll whose time is up. Runs off saved timestamps, so
    anything that came due while the bot was offline is handled on startup."""
    now = time.time()
    for mid, gw in list(active_giveaways.items()):
        if gw["ends_at"] <= now:
            try:
                await finish_giveaway(mid)
            except Exception as e:
                log.error(f"Failed to finish giveaway {mid}: {e}")
    for mid, p in list(active_polls.items()):
        if p["ends_at"] <= now:
            try:
                await finish_poll(mid)
            except Exception as e:
                log.error(f"Failed to finish poll {mid}: {e}")


# --- Anti-raid (join-rate spike alerts) -----------------------------------------

DEFAULT_ANTIRAID = {"enabled": False, "threshold": 5, "window": 10}


def get_antiraid(guild_id: int) -> dict:
    return antiraid_config.setdefault(guild_id, dict(DEFAULT_ANTIRAID))


async def check_antiraid(member: discord.Member):
    cfg = antiraid_config.get(member.guild.id)
    if not cfg or not cfg.get("enabled"):
        return
    dq = join_log[member.guild.id]
    now = time.monotonic()
    dq.append(now)
    recent = sum(1 for t in dq if now - t <= cfg.get("window", 10))
    if recent >= cfg.get("threshold", 5):
        await send_log(
            member.guild.id, title="🚨 Possible raid detected", color=discord.Color.red(),
            fields=[("Joins", f"{recent} in {cfg.get('window', 10)}s"), ("Latest member", f"{member} ({member.id})")],
        )


antiraid_group = app_commands.Group(name="antiraid", description="Configure join-spike (raid) alerts")


@antiraid_group.command(name="enable", description="Turn on raid-join alerts to the log channel")
@app_commands.describe(threshold="Alert if this many joins happen...", window_seconds="...within this many seconds")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def antiraid_enable(interaction: discord.Interaction, threshold: int = 5, window_seconds: int = 10):
    cfg = get_antiraid(interaction.guild.id)
    cfg.update({"enabled": True, "threshold": threshold, "window": window_seconds})
    await bd_save_data()
    await interaction.response.send_message(
        f"🐾 Anti-raid alerts on: {threshold} joins within {window_seconds}s triggers a log-channel alert. "
        f"(This only alerts — it doesn't auto-kick or lock the server.)"
    )


@antiraid_group.command(name="disable", description="Turn off raid-join alerts")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def antiraid_disable(interaction: discord.Interaction):
    get_antiraid(interaction.guild.id)["enabled"] = False
    await bd_save_data()
    await interaction.response.send_message("🐾 Anti-raid alerts off.")


# --- Channel lock / unlock -------------------------------------------------------

@bot.tree.command(name="lock", description="Prevent @everyone from sending messages in a channel")
@app_commands.describe(channel="Channel to lock (defaults to this one)")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
@app_commands.guild_only()
async def lock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"Locked by {interaction.user}")
    await interaction.response.send_message(f"🔒 {channel.mention} locked.")
    await send_log(
        interaction.guild.id, title="🔒 Channel locked", color=discord.Color.red(), interaction=interaction,
        fields=[("Channel", channel.mention)],
    )


@bot.tree.command(name="unlock", description="Allow @everyone to send messages in a channel again")
@app_commands.describe(channel="Channel to unlock (defaults to this one)")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
@app_commands.guild_only()
async def unlock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None  # inherit
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"Unlocked by {interaction.user}")
    await interaction.response.send_message(f"🔓 {channel.mention} unlocked.")
    await send_log(
        interaction.guild.id, title="🔓 Channel unlocked", color=discord.Color.green(), interaction=interaction,
        fields=[("Channel", channel.mention)],
    )


# --- Mod information (reads the log channel live) --------------------------

_MODINFO_TITLES = {
    "⚠️ Member warned", "🚨 Auto-mod action", "👢 Member kicked", "🔨 Member banned",
    "🔓 Member unbanned", "🔇 Member muted", "🔊 Member unmuted", "⏳ Member temp-banned",
    "⏳ Temp-ban expired — member unbanned",
}


@bot.tree.command(name="modinfo", description="Mods only: a person's full moderation history, read from the log channel")
@app_commands.describe(user="Who to look up (works even if they've left or are banned)")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def modinfo(interaction: discord.Interaction, user: discord.User):
    channel = bot.get_channel(log_channels.get(interaction.guild.id, 0))
    if channel is None:
        return await interaction.response.send_message(
            "Set a log channel first with `/logchannel` — this command reads its history.", ephemeral=True
        )
    await interaction.response.defer(ephemeral=True)

    entries = []  # newest first (channel.history order)
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
                entries.append({
                    "ts": embed.timestamp or message.created_at,
                    "case": fields.get("Case", "—"),
                    "title": embed.title,
                    "reason": (fields.get("Reason", "") + extra).strip(),
                    "by": footer_m.group(1) if footer_m else "system",
                })
    except discord.HTTPException as e:
        return await interaction.followup.send(f"Couldn't read the log channel: {e}", ephemeral=True)

    member = interaction.guild.get_member(user.id)
    stored_warns = len(warnings_data.get((interaction.guild.id, user.id), []))
    info = [f"**Account created:** {discord.utils.format_dt(user.created_at, 'D')}"]
    if member and member.joined_at:
        info.append(f"**Joined server:** {discord.utils.format_dt(member.joined_at, 'D')}")
    else:
        info.append("**In server:** No (left, kicked, or banned)")
    info.append(f"**Active warnings on file:** {stored_warns}")
    info.append(f"**Logged actions found:** {len(entries)}")

    lines, used = [], 0
    for e in entries:
        line = f"{discord.utils.format_dt(e['ts'], 'd')} **{e['case']}** {e['title']}"
        if e["reason"]:
            line += f" — {e['reason'][:120]}"
        line += f" · _{e['by']}_"
        if used + len(line) > 3000:
            lines.append(f"…and {len(entries) - len(lines)} older action(s) not shown.")
            break
        lines.append(line)
        used += len(line) + 1

    body = "\n".join(lines) if lines else "No logged moderation actions found for this person."
    embed = discord.Embed(
        title=f"🛡️ Mod information — {user}", description="\n".join(info) + "\n\n" + body,
        color=discord.Color.blurple(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Read live from the log channel (last 2000 messages). Actions logged before case IDs existed show —.")
    await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


# --- Health / status ---------------------------------------------------------

@bot.tree.command(name="ping", description="Check Cinnamon's Discord latency")
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(
        f"🏓 **Pong!** Discord latency: **{latency_ms} ms**",
        ephemeral=True,
    )


@bot.tree.command(name="botstatus", description="Show Cinnamon's current health and enabled systems")
@app_commands.guild_only()
async def botstatus(interaction: discord.Interaction):
    guild = interaction.guild
    hg_cog = bot.get_cog("HangryGamesCog")
    storage = await storage_status()
    embed = discord.Embed(title="🐾 Cinnamon status", color=discord.Color.blurple())
    embed.add_field(name="Discord latency", value=f"{round(bot.latency * 1000)} ms", inline=True)
    embed.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="Members here", value=str(guild.member_count or 0), inline=True)
    embed.add_field(name="AI channel", value="Enabled" if ai_channels.get(guild.id) else "Off", inline=True)
    embed.add_field(name="Auto-mod", value="Configured" if guild.id in automod_config else "Off", inline=True)
    embed.add_field(name="Anti-raid", value="Enabled" if antiraid_config.get(guild.id, {}).get("enabled") else "Off", inline=True)
    embed.add_field(name="XP / leveling", value="Active", inline=True)
    embed.add_field(name="Hangry Games", value="Ready" if hg_cog else "Starting", inline=True)
    embed.add_field(name="Storage", value=storage["backend"], inline=True)
    embed.set_footer(text="Use /help for commands. 🐾")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- Help + guided setup ------------------------------------------------------

async def _ensure_setup_channel(guild: discord.Guild, category: discord.CategoryChannel, name: str, topic: str):
    """Find or create one of Cinnamon's managed setup channels.

    The setup is deliberately idempotent: running /setup again reuses channels
    instead of creating duplicates.
    """
    existing = discord.utils.get(category.text_channels, name=name)
    if existing:
        return existing, False
    channel = await guild.create_text_channel(name=name, category=category, topic=topic, reason="Cinnamon guided server setup")
    return channel, True


def _command_path(command) -> str:
    parts = []
    current = command
    while current is not None:
        name = getattr(current, "name", None)
        if name:
            parts.append(name)
        current = getattr(current, "parent", None)
    return "/" + " ".join(reversed(parts))


def _all_leaf_commands() -> list:
    """Return every registered slash command, including commands inside groups."""
    leaves = []

    def walk(command):
        children = getattr(command, "commands", None) or []
        if children:
            for child in children:
                walk(child)
        else:
            leaves.append(command)

    for command in bot.tree.get_commands():
        walk(command)
    # Hangry Games is a GroupCog and should already be attached to the tree by
    # the time /help is used, but sorting here makes the output deterministic.
    return sorted(leaves, key=lambda c: _command_path(c).lower())


@bot.tree.command(name="setup", description="Guided first-time setup: create Cinnamon's channels and configure logging")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_channels=True, send_messages=True, embed_links=True)
async def setup_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    await interaction.response.defer(ephemeral=True)

    category = discord.utils.get(guild.categories, name="Cinnamon • Logs & Setup")
    created_category = False
    if category is None:
        category = await guild.create_category("Cinnamon • Logs & Setup", reason="Cinnamon guided server setup")
        created_category = True

    specs = [
        ("cinnamon-logs", "Cinnamon moderation, AutoMod, errors, warnings, and general logs."),
        ("cinnamon-economy", "Catnip economy transactions and pre-reset economy snapshots."),
        ("cinnamon-hangry", "Hangry Games starts, winners, cancellations, and recovery logs."),
        ("cinnamon-welcome", "Cinnamon's member welcome messages."),
        ("cinnamon-goodbye", "Cinnamon's member goodbye messages."),
        ("cinnamon-ai", "Cinnamon's always-on AI chat channel."),
        ("cinnamon-quest-logs", "Daily and weekly quest completion, administration, and recovery logs."),
        ("cinnamon-achievement-logs", "Cinnamon achievement unlocks, administration, role setup, and recovery logs."),
    ]
    channels = {}
    created = []
    for name, topic in specs:
        channel, was_created = await _ensure_setup_channel(guild, category, name, topic)
        channels[name] = channel
        if was_created:
            created.append(channel.mention)

    # Configure the systems that have dedicated channel settings.
    log_channels[guild.id] = channels["cinnamon-logs"].id
    economy_log_channels[guild.id] = channels["cinnamon-economy"].id
    ai_channels[guild.id] = channels["cinnamon-ai"].id

    # Wire the quest and achievement log channels into the main setup too.
    # This keeps /setup as the one-command server bootstrap while the dedicated
    # /questlogchannel and /achievementlogchannel commands remain available for
    # changing either channel later.
    qcfg = quest_config.setdefault(guild.id, {"enabled": True, "log_channel_id": None, "daily": {}, "weekly": {}, "history": []})
    qcfg["enabled"] = True
    qcfg["log_channel_id"] = channels["cinnamon-quest-logs"].id
    acfg = achievement_config.setdefault(guild.id, {"enabled": True, "log_channel_id": None})
    acfg["enabled"] = True
    acfg["log_channel_id"] = channels["cinnamon-achievement-logs"].id
    # Initialize active quest cycles without requiring a second setup command.
    _quest_cycle_config(guild.id, "daily")
    _quest_cycle_config(guild.id, "weekly")

    welcome_config[guild.id] = {
        "channel_id": channels["cinnamon-welcome"].id,
        "message": "🐾 Welcome {member} to **{server}**! Cinnamon hopes you brought snacks.",
    }
    goodbye_config[guild.id] = {
        "channel_id": channels["cinnamon-goodbye"].id,
        "message": "🐾 {member} left **{server}**. Cinnamon will miss the head pats!",
    }

    hg_cog = bot.get_cog("HangryGamesCog")
    if hg_cog:
        hg_cog.hg_log_channels[guild.id] = channels["cinnamon-hangry"].id
        hg_cog.log_enabled[guild.id] = True
        await hg_cog._save()

    await bd_save_data()

    # Keep the setup message useful even if someone runs it again later.
    created_text = ", ".join(created) if created else "No channels needed to be created; the setup was already present."
    embed = cinnamon_embed(
        title="🐾 Cinnamon setup complete",
        description=(
            "I checked the server and configured Cinnamon's core systems. "
            "Running `/setup` again is safe — existing channels are reused.\n\n"
            f"**Created:** {created_text}"
        ),
        color=discord.Color.green(),
        guild=guild,
        footer="Cinnamon • Setup complete",
    )
    embed.add_field(name="🛡️ Main logs", value=channels["cinnamon-logs"].mention, inline=True)
    embed.add_field(name="🌿 Economy", value=channels["cinnamon-economy"].mention, inline=True)
    embed.add_field(name="🍔 Hangry Games", value=channels["cinnamon-hangry"].mention, inline=True)
    embed.add_field(name="👋 Welcome", value=channels["cinnamon-welcome"].mention, inline=True)
    embed.add_field(name="🚪 Goodbye", value=channels["cinnamon-goodbye"].mention, inline=True)
    embed.add_field(name="🐱 AI chat", value=channels["cinnamon-ai"].mention, inline=True)
    embed.add_field(name="🎯 Quest logs", value=channels["cinnamon-quest-logs"].mention, inline=True)
    embed.add_field(name="🏆 Achievement logs", value=channels["cinnamon-achievement-logs"].mention, inline=True)
    embed.add_field(
        name="Next steps",
        value=(
            "Use `/help` to see every command and what it does. "
            "Use `/economy snapshot` before a reset. "
            "Use `/economy recover` after a reset if needed."
        ),
        inline=False,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="setupstatus", description="Check Cinnamon's configured channels and systems")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
async def setupstatus_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    hg_cog = bot.get_cog("HangryGamesCog")
    rows = [
        ("🛡️ Main logs", log_channels.get(guild.id)),
        ("🌿 Economy logs", economy_log_channels.get(guild.id)),
        ("🍔 Hangry logs", hg_cog.hg_log_channels.get(guild.id) if hg_cog else None),
        ("👋 Welcome", welcome_config.get(guild.id, {}).get("channel_id")),
        ("🚪 Goodbye", goodbye_config.get(guild.id, {}).get("channel_id")),
        ("🐱 AI channel", ai_channels.get(guild.id)),
        ("🎯 Quest logs", quest_config.get(guild.id, {}).get("log_channel_id")),
        ("🏆 Achievement logs", achievement_config.get(guild.id, {}).get("log_channel_id")),
    ]
    lines = []
    for label, channel_id in rows:
        channel = guild.get_channel(channel_id) if channel_id else None
        lines.append(f"{label}: {channel.mention if channel else '❌ Not configured'}")
    embed = discord.Embed(title="🐾 Cinnamon setup status", description="\n".join(lines), color=discord.Color.blurple())
    embed.add_field(name="AutoMod", value="Configured" if guild.id in automod_config else "Not configured", inline=True)
    embed.add_field(name="Anti-raid", value="Enabled" if antiraid_config.get(guild.id, {}).get("enabled") else "Off", inline=True)
    embed.add_field(name="Persistent storage", value=(await storage_status())["backend"], inline=True)
    embed.set_footer(text="Run /setup to create/configure the standard Cinnamon channels.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- Help ---------------------------------------------------------------------

_HELP_EVERYONE = (
    "`/pet` `/treat` `/nap` `/zoomies` — cat antics\n"
    "`/afk` — set an AFK note (auto-replies when you're pinged)\n"
    "`/rank` · `/leaderboard` — your level, and the top 10\n"
    "`/userinfo` · `/serverinfo` — info about a member or the server\n"
    "`/poll` — start a poll with 2–4 options\n"
    "`/ping` · `/botstatus` — check Cinnamon's health\n"
    "`/help` — this menu\n"
    "Chat with me any time by mentioning me or replying to me. 🐾"
)
_HELP_ECONOMY = (
    "`/economy balance` · `/economy inventory` — your Catnip and items\n"
    "`/economy daily` · `/economy work` · `?work` — earn Catnip\n"
    "`/economy shop` · `/economy buy` · `/economy iteminfo` — view, buy, and inspect items\n"
    "`/economy quest` · `/economy feed` — see quests and give Cinnamon items\n"
    "`/economy give` — give Catnip to another member\n"
    "`/collect` — collect income from your income roles\n"
    "`/economy leaderboard` — richest members\n"
)

_HELP_HANGRY = (
    "`/hangrygames new` — open a lobby (Start needs Manage Messages)\n"
    "`/hangrygames giveaway` — lobby with a prize and optional winner role\n"
    "`/hangrygames role` — start straight away with everyone in a role\n"
    "`/hangrygames stats` · `leaderboard` — wins, kills, and top winners\n"
    "`/hangrygames cancel` — stop the game or lobby in this channel"
)
_HELP_MODS = (
    "`/warn` · `/warnings` — warn someone / see their warnings\n"
    "`/kick` `/ban` `/tempban` `/unban`\n"
    "`/mute` · `/unmute` — timeouts\n"
    "`/modinfo` — someone's full mod history, read from the log channel\n"
    "`/purge` `/slowmode` `/lock` `/unlock` — channel tools\n"
    "`/role add` · `/reactionrole create` `remove` — roles\n"
    "`/aichannel` `/disableaichannel` `/disableai` `/enableai` — where I chat"
)
_HELP_ADMINS = (
    "`/logchannel` · `/disablelogchannel` — mod log\n"
    "`/datastatus check` `recover` — storage health and data recovery\n"
    "`/welcome` · `/goodbye` — `set` or `disable` join/leave messages\n"
    "`/automod` — `word add/remove/list`, `spam`, `mentions`, `invites`\n"
    "`/antiraid enable` `disable` — join-spike alerts\n"
    "`/levelrole add` `remove` `list` — roles at certain levels\n"
    "`/giveaway start` `end` — prize giveaways\n"
    "`/clearwarnings` · `/role add-all`\n"
    "`/hangrygames logchannel` `disablelogchannel` `log` — its own log channel\n"
    "`/economy logs` — choose the economy transaction log channel\n"
    "`/economy snapshot` — create a complete pre-reset backup\n"
    "`/economy recover` — restore the latest backup from economy logs\n"
    "`/economy addcatnip` · `removecatnip` — admin balance controls\n"
    "`/economy income` — admin income-role management\n"
    "`/economy item-add` · `/economy item-remove` — admin inventory controls\n`/economy add-item-shop` · `/economy edit-shop-item` · `/economy remove-item-shop` — admin shop controls\n`/economy add-role-income` · `/economy remove-role-income` — admin role income controls\n`/economy iteminfo` — detailed item information"
)


@bot.tree.command(name="help", description="See every Cinnamon command and what it does")
@app_commands.guild_only()
async def help_cmd(interaction: discord.Interaction):
    commands_list = _all_leaf_commands()
    pages = []
    current_lines = []
    current_len = 0
    last_root = None

    for command in commands_list:
        path = _command_path(command)
        root = path.split()[0].lstrip("/")
        description = getattr(command, "description", None) or "No description provided."
        line = f"**{path}** — {description}"
        if len(line) > 900:
            line = line[:897] + "..."
        heading = "" if root == last_root else f"\n**{root.replace('-', ' ').replace('_', ' ').title()}**"
        extra = len(heading) + len(line) + 1
        # Pack multiple command groups into each page so the help command can
        # show the entire bot, not just the first few groups.
        if current_lines and current_len + extra > 3500:
            pages.append("\n".join(current_lines))
            current_lines = []
            current_len = 0
            heading = f"**{root.replace('-', ' ').replace('_', ' ').title()}**"
            extra = len(heading) + len(line) + 1
        current_lines.append(heading)
        current_lines.append(line)
        current_len += extra
        last_root = root
    if current_lines:
        pages.append("\n".join(current_lines))

    embeds = []
    total = len(commands_list)
    for index, body in enumerate(pages, start=1):
        embed = discord.Embed(title=f"🐾 Cinnamon command directory ({index}/{len(pages)})", description=body, color=0xFFB02E)
        embed.set_footer(text=f"/help • {total} commands • Use /setup for guided server setup")
        embeds.append(embed)

    # Add a compact guide as the final page if there is room.
    guide = discord.Embed(
        title="📖 How to use Cinnamon",
        description=(
            "**New server?** Run `/setup` first. It creates and configures the standard log/welcome/AI channels.\n\n"
            "**Looking for something?** Discord's slash-command search also filters these commands as you type.\n\n"
            "**Admin tools:** Most moderation, setup, logging, recovery, and configuration commands require the appropriate Discord permission.\n\n"
            "**Reset protection:** Run `/economy snapshot` before a reset, then `/economy recover` afterward.\n\n"
            "**AI:** Mention Cinnamon or reply to her, or use the configured AI channel."
        ),
        color=discord.Color.blurple(),
    )
    if len(embeds) < 10:
        embeds.append(guide)
    await interaction.response.send_message(embeds=embeds, ephemeral=True)


# --- Data status / recovery -------------------------------------------------

datastatus_group = app_commands.Group(name="datastatus", description="Check or recover Cinnamon's persisted data")


@datastatus_group.command(name="check", description="Check whether persistent storage is actually connected right now")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def datastatus_check(interaction: discord.Interaction):
    status = await storage_status()
    icon = "✅" if status["connected"] else "⚠️"
    guild_warnings = sum(1 for g, _ in warnings_data.keys() if g == interaction.guild.id)
    hg_cog = bot.get_cog("HangryGamesCog")
    hg_game_num = hg_cog.game_counts.get(interaction.guild.id, 0) if hg_cog else 0
    embed = discord.Embed(title=f"{icon} Storage status", color=discord.Color.green() if status["connected"] else discord.Color.orange())
    embed.add_field(name="Backend", value=status["backend"], inline=True)
    embed.add_field(name="Connected", value="Yes" if status["connected"] else "No", inline=True)
    embed.add_field(name="Detail", value=status["detail"], inline=False)
    embed.add_field(name="This server's warnings tracked", value=str(guild_warnings), inline=True)
    embed.add_field(name="This server's Hangry Games count", value=str(hg_game_num), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@datastatus_group.command(name="recover", description="Force a rebuild of this server's warnings/Hangry Games data from the log channels' history")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def datastatus_recover(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    warn_recovered = await recover_warnings_from_log(interaction.guild)
    hg_cog = bot.get_cog("HangryGamesCog")
    game_num, wins = (await hg_cog.recover_from_log(interaction.guild)) if hg_cog else (0, 0)
    await interaction.followup.send(
        f"🩹 Recovery scan complete.\n"
        f"• Warnings reconstructed: **{warn_recovered}**\n"
        f"• Hangry Games: game count restored to **#{game_num}**, **{wins}** win(s) reconstructed\n\n"
        f"This only rebuilds from what's still visible in the log channels' message history — "
        f"it can't recover anything older than that or anything never logged (like XP).",
        ephemeral=True,
    )


bot.tree.add_command(welcome_group)
bot.tree.add_command(goodbye_group)
bot.tree.add_command(reactionrole_group)
bot.tree.add_command(automod_group)
bot.tree.add_command(giveaway_group)
bot.tree.add_command(levelrole_group)
bot.tree.add_command(antiraid_group)
bot.tree.add_command(datastatus_group)




# ---------------------------------------------------------------------------
# Achievements — persistent, automatic, Cinnamon-themed progression
# ---------------------------------------------------------------------------

achievement_data = {}          # (guild_id, user_id) -> persistent progress dict
achievement_defs = {}          # guild_id -> {achievement_id: definition}
achievement_roles = {}         # guild_id -> {achievement_id: role_id}
achievement_config = {}        # guild_id -> {"enabled": bool, "log_channel_id": int|None}
achievement_session_first = {} # guild_id -> user_id for the first Cinnamon interaction after startup

ACHIEVEMENT_METRICS = {
    "messages", "cinnamon_pings", "lifetime_earned", "purchases", "lifetime_spent",
    "tuna", "total_items", "work_sessions", "quests_completed", "cinnamon_interactions",
    "levels", "hangry_games", "interaction_days", "achievement_points", "daily_unlocks",
}

ACHIEVEMENT_POINT_MILESTONES = {
    "ap_100": (100, "Achievement Profile", "A first milestone in Cinnamon's achievement book."),
    "ap_250": (250, "Achievement Hunter", "250 Achievement Points."),
    "ap_500": (500, "Achievement Master", "500 Achievement Points."),
    "ap_1000": (1000, "Achievement Master", "1,000 Achievement Points."),
    "ap_2500": (2500, "Achievement Legend", "2,500 Achievement Points."),
    "ap_5000": (5000, "Cinnamon's Certified Achievement Maniac", "5,000 Achievement Points."),
}


def _achievement_key(guild_id: int, user_id: int) -> tuple[int, int]:
    return guild_id, user_id


def achievement_progress(guild_id: int, user_id: int) -> dict:
    key = _achievement_key(guild_id, user_id)
    if key not in achievement_data:
        achievement_data[key] = {
            "stats": {m: 0 for m in ACHIEVEMENT_METRICS},
            "unlocked": [],
            "points": 0,
            "interaction_commands": [],
            "interaction_days": [],
            "unlock_dates": {},
            "hangry_games": 0,
            "manual": [],
        }
    d = achievement_data[key]
    d.setdefault("stats", {})
    for m in ACHIEVEMENT_METRICS:
        d["stats"].setdefault(m, 0)
    d.setdefault("unlocked", [])
    d.setdefault("points", 0)
    d.setdefault("interaction_commands", [])
    d.setdefault("interaction_days", [])
    d.setdefault("unlock_dates", {})
    d.setdefault("hangry_games", 0)
    d.setdefault("manual", [])
    return d


def _achievement_defs_for(guild_id: int) -> dict:
    if guild_id not in achievement_defs:
        achievement_defs[guild_id] = default_achievement_definitions()
    return achievement_defs[guild_id]


def default_achievement_definitions() -> dict:
    # Requirements are intentionally data-driven so admins can create/edit/disable
    # achievements without changing the bot code.
    defs = {}
    def add(aid, name, description, metric, threshold, catnip=0, xp=0, points=10,
            role=None, secret=False, role_group=None, special=None):
        defs[aid] = {
            "name": name, "description": description, "metric": metric,
            "threshold": threshold, "catnip": catnip, "xp": xp,
            "points": points, "role": role, "secret": secret, "enabled": True,
            "role_group": role_group, "special": special,
        }

    # Yapping / messages
    add("ping_100", "Cat Yapper", "Ping Cinnamon 100 times.", "cinnamon_pings", 100, 2000, 500, 25, "Cat Yapper", role_group="ping")
    add("ping_500", "Master Cat Yapper", "Ping Cinnamon 500 times.", "cinnamon_pings", 500, 5000, 1500, 50, "Master Cat Yapper", role_group="ping")
    add("ping_1000", "Professional Yapper", "Ping Cinnamon 1,000 times.", "cinnamon_pings", 1000, 10000, 3000, 100, "Professional Yapper", role_group="ping")
    add("ping_5000", "Cinnamon's Biggest Problem", "Ping Cinnamon 5,000 times.", "cinnamon_pings", 5000, 25000, 7500, 250, "Cinnamon's Biggest Problem", role_group="ping")
    add("msg_100", "Little Yapper", "Send 100 messages.", "messages", 100, 500, 100, 10)
    add("msg_500", "Professional Yapper", "Send 500 messages.", "messages", 500, 2000, 500, 25)
    add("msg_1000", "Mega Yapper", "Send 1,000 messages.", "messages", 1000, 5000, 1000, 50, "Mega Yapper")
    add("msg_5000", "Human Podcast", "Send 5,000 messages.", "messages", 5000, 15000, 3000, 100, "Human Podcast")
    add("msg_10000", "The Never-Ending Story", "Send 10,000 messages.", "messages", 10000, 30000, 7500, 200, "Never-Ending Story")
    add("msg_25000", "Why Are You Still Typing?", "Send 25,000 messages.", "messages", 25000, 75000, 15000, 500, "Why Are You Still Typing?")

    # Catnip lifetime earned
    add("earned_1000", "Catnip Beginner", "Earn 1,000 lifetime Catnip.", "lifetime_earned", 1000, 500, 100, 10)
    add("earned_5000", "Catnip Collector", "Earn 5,000 lifetime Catnip.", "lifetime_earned", 5000, 2000, 300, 25)
    add("earned_10000", "Catnip Hoarder", "Earn 10,000 lifetime Catnip.", "lifetime_earned", 10000, 4000, 750, 50)
    add("earned_25000", "Catnip Tycoon", "Earn 25,000 lifetime Catnip.", "lifetime_earned", 25000, 10000, 1500, 100)
    add("earned_50000", "Catnip Millionaire's Apprentice", "Earn 50,000 lifetime Catnip.", "lifetime_earned", 50000, 0, 0, 250, "Catnip Tycoon", role_group="earned", special="no_catnip")
    add("earned_100000", "Catnip King", "Earn 100,000 lifetime Catnip.", "lifetime_earned", 100000, 0, 0, 500, "Catnip King", role_group="earned", special="no_catnip")
    add("earned_250000", "Catnip Corporation", "Earn 250,000 lifetime Catnip.", "lifetime_earned", 250000, 0, 0, 1000, "Catnip Corporation", role_group="earned", special="no_catnip")

    # Shopping
    add("buy_1", "Window Shopper", "Make your first shop purchase.", "purchases", 1, 0, 100, 10)
    add("buy_25", "Regular Customer", "Make 25 purchases.", "purchases", 25, 0, 750, 25, "Regular Customer", role_group="shopping")
    add("buy_100", "Receipt Collector", "Make 100 purchases.", "purchases", 100, 0, 2000, 75, "Receipt Collector", role_group="shopping")
    add("spend_25000", "Money? What Money?", "Spend 25,000 Catnip in the shop.", "lifetime_spent", 25000, 0, 3000, 100, "Big Spender", role_group="spending")
    add("spend_100000", "Take My Money", "Spend 100,000 Catnip in the shop.", "lifetime_spent", 100000, 0, 7500, 250, "Big Spender", role_group="spending")

    # Items
    add("tuna_10", "Tuna Enjoyer", "Own 10 Tuna at once.", "tuna", 10, 2000, 500, 25)
    add("tuna_50", "Tuna Addict", "Own 50 Tuna at once.", "tuna", 50, 7500, 1500, 100, "Tuna Addict", role_group="tuna")
    add("tuna_100", "TUNA EMPIRE", "Own 100 Tuna at once.", "tuna", 100, 20000, 5000, 250, "Tuna Empire", role_group="tuna")
    add("items_100", "Pack Rat", "Own 100 total items at once.", "total_items", 100, 5000, 1000, 75)
    add("items_500", "Why Do You Have So Much Stuff?", "Own 500 total items at once.", "total_items", 500, 25000, 5000, 250, "Professional Hoarder", role_group="items")

    # Work
    add("work_1", "First Day At Work", "Complete 1 work session.", "work_sessions", 1, 500, 100, 10)
    add("work_25", "Part-Time Cat Employee", "Complete 25 work sessions.", "work_sessions", 25, 2500, 500, 25)
    add("work_100", "Full-Time Cat Employee", "Complete 100 work sessions.", "work_sessions", 100, 7500, 1500, 75)
    add("work_500", "Corporate Cat", "Complete 500 work sessions.", "work_sessions", 500, 25000, 5000, 250, "Corporate Cat")
    add("work_1000", "Cinnamon's Best Employee", "Complete 1,000 work sessions.", "work_sessions", 1000, 50000, 10000, 500, "Cinnamon's Best Employee")

    # Levels — Catnip only, never XP
    add("level_5", "Level Up!", "Reach Level 5.", "levels", 5, 1500, 0, 25)
    add("level_10", "Getting Somewhere", "Reach Level 10.", "levels", 10, 4000, 0, 50)
    add("level_25", "Veteran Cat", "Reach Level 25.", "levels", 25, 10000, 0, 150, "Veteran Cat", role_group="level")
    add("level_50", "Server Legend", "Reach Level 50.", "levels", 50, 25000, 0, 500, "Server Legend", role_group="level")

    # Cinnamon / quests
    add("quests_25", "Cinnamon's Personal Assistant", "Complete 25 quests.", "quests_completed", 25, 15000, 3000, 150, "Cinnamon's Assistant", special="linked_quest_achievement")
    add("quests_50", "Cat Servant", "Complete 50 quests.", "quests_completed", 50, 30000, 7500, 300, "Cinnamon's Servant", special="linked_quest_achievement")
    add("tuna_given_100", "Tuna Supplier", "Give Cinnamon 100 Tuna.", "tuna_given", 100, 25000, 5000, 250, "Official Tuna Supplier")
    add("interactions_25", "Toe Bean Inspector", "Use Cinnamon interaction commands 25 times.", "cinnamon_interactions", 25, 5000, 1000, 75)
    add("no_life", "I Have No Life", "Send 10,000 messages and complete 100 work sessions.", "messages", 10000, 50000, 10000, 500, "I Have No Life", special="combo_no_life")
    add("second_favourite", "Cinnamon's Second Favourite Human", "Complete 50 quests, ping Cinnamon 500 times, and own 50 Tuna.", "quests_completed", 50, 75000, 15000, 750, "Second Favourite Human", special="combo_second_favourite")
    add("favourite_admin", "Cinnamon's Favourite Human", "A special achievement that can only be awarded by an administrator.", "manual", 1, 0, 0, 1000, "Cinnamon's Favourite Human", secret=False, special="manual_only")

    # Ten secrets
    add("secret_01", "Cinnamon Summoned Me", "Be the first person to use a Cinnamon interaction after the bot comes online.", "session_first", 1, 1000, 250, 25, "Cinnamon Summoned Me", secret=True)
    add("secret_02", "The Cat Has Spoken", "Get a reply from Cinnamon 10 times in AI chat.", "ai_replies", 10, 2500, 500, 50, "The Cat Has Spoken", secret=True)
    add("secret_03", "Treat Dealer", "Give Cinnamon 25 treats.", "treats_given", 25, 3000, 750, 75, "Treat Dealer", secret=True)
    add("secret_04", "Cinnamon's Therapist", "Use /pet 50 times.", "pet_uses", 50, 5000, 1000, 100, "Cinnamon's Therapist", secret=True)
    add("secret_05", "Professional Cat Whisperer", "Successfully use all four classic Cinnamon interaction commands.", "unique_interactions", 4, 7500, 1500, 150, "Professional Cat Whisperer", secret=True)
    add("secret_06", "Oops, All Tuna", "Own Tuna plus at least three other different item types at once.", "tuna_plus_types", 1, 5000, 1000, 100, "Oops, All Tuna", secret=True)
    add("secret_07", "The Economy Is Mine", "Have 10,000 Catnip while owning at least 50 total items.", "economy_combo", 1, 10000, 2000, 200, "The Economy Is Mine", secret=True)
    add("secret_08", "Cinnamon Knows My Name", "Use Cinnamon-related interactions on 25 different days.", "interaction_days", 25, 15000, 3000, 300, "Cinnamon Knows My Name", secret=True)
    add("secret_09", "Wait… You Actually Did It?", "Unlock 5 different achievements in the same day.", "daily_unlocks", 5, 10000, 2500, 250, "Wait… You Actually Did It?", secret=True)
    add("secret_10", "The Dream Has Been Archived", "Participate in 100 Hangry Games, reach Level 50, earn 100,000 lifetime Catnip, and own at least 100 Tuna.", "hangry_games", 100, 25000, 5000, 1000, "The Dream Has Been Archived", secret=True, special="dream_archived")
    return defs


def achievement_get_stat(progress: dict, metric: str) -> int:
    if metric == "manual":
        return 0
    if metric == "session_first":
        return 1 if progress.get("stats", {}).get("session_first") else 0
    if metric == "tuna_given":
        return int(progress.get("stats", {}).get("tuna_given", 0))
    if metric == "ai_replies":
        return int(progress.get("stats", {}).get("ai_replies", 0))
    if metric == "treats_given":
        return int(progress.get("stats", {}).get("treats_given", 0))
    if metric == "pet_uses":
        return int(progress.get("stats", {}).get("pet_uses", 0))
    if metric == "unique_interactions":
        return len(progress.get("interaction_commands", []))
    if metric == "interaction_days":
        return len(progress.get("interaction_days", []))
    if metric == "daily_unlocks":
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        return len(progress.get("unlock_dates", {}).get(today, []))
    return int(progress.get("stats", {}).get(metric, 0))


def achievement_condition_met(guild_id: int, user_id: int, aid: str, d: dict, p: dict) -> bool:
    special = d.get("special")
    if special == "manual_only":
        return False
    if special == "combo_no_life":
        return p["stats"].get("messages", 0) >= 10000 and p["stats"].get("work_sessions", 0) >= 100
    if special == "combo_second_favourite":
        inv = economy_inventory_for(guild_id, user_id)
        return p["stats"].get("quests_completed", 0) >= 50 and p["stats"].get("cinnamon_pings", 0) >= 500 and int(inv.get("tuna", 0)) >= 50
    if special == "dream_archived":
        inv = economy_inventory_for(guild_id, user_id)
        return p["stats"].get("hangry_games", 0) >= 100 and level_from_xp(xp_data.get((guild_id, user_id), 0)) >= 50 and p["stats"].get("lifetime_earned", 0) >= 100000 and int(inv.get("tuna", 0)) >= 100
    if d.get("metric") == "tuna_plus_types":
        inv = economy_inventory_for(guild_id, user_id)
        return int(inv.get("tuna", 0)) >= 1 and sum(1 for q in inv.values() if int(q) > 0) >= 4
    if d.get("metric") == "economy_combo":
        return economy_balance(guild_id, user_id) >= 10000 and sum(int(q) for q in economy_inventory_for(guild_id, user_id).values()) >= 50
    if d.get("metric") == "session_first":
        return achievement_session_first.get(guild_id) == user_id
    return achievement_get_stat(p, d.get("metric", "")) >= int(d.get("threshold", 0))


async def achievement_log(guild_id: int, *, title: str, fields=None):
    cfg = achievement_config.get(guild_id, {})
    channel_id = cfg.get("log_channel_id")
    channel = bot.get_channel(channel_id) if channel_id else None
    if not channel:
        return
    guild = bot.get_guild(guild_id)
    embed = cinnamon_embed(title=title, color=0xA970FF, guild=guild, footer="Cinnamon • Achievement log")
    add_embed_fields(embed, fields)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        log.error(f"Achievement log failed for {guild_id}: {e}")
    except Exception:
        log.exception("Unexpected achievement log failure for %s", guild_id)


async def achievement_assign_role(member: discord.Member, aid: str, d: dict):
    role_id = achievement_roles.get(member.guild.id, {}).get(aid)
    if not role_id:
        return
    role = member.guild.get_role(role_id)
    if not role:
        return
    group = d.get("role_group")
    if group:
        for other_id, other_d in _achievement_defs_for(member.guild.id).items():
            if other_id == aid or other_d.get("role_group") != group:
                continue
            old_rid = achievement_roles.get(member.guild.id, {}).get(other_id)
            old_role = member.guild.get_role(old_rid) if old_rid else None
            if old_role and old_role in member.roles:
                try:
                    await member.remove_roles(old_role, reason="Achievement progression upgrade")
                except discord.HTTPException:
                    pass
    if role in member.roles:
        return
    try:
        await member.add_roles(role, reason=f"Achievement unlocked: {d.get('name')}")
    except discord.HTTPException as e:
        await achievement_log(member.guild.id, title="⚠️ Achievement role assignment failed", fields=[("User", f"{member} ({member.id})"), ("Achievement", d.get("name")), ("Error", str(e)[:500])])


async def achievement_grant(member: discord.Member, aid: str, *, manual=False) -> bool:
    guild_id, user_id = member.guild.id, member.id
    defs = _achievement_defs_for(guild_id)
    d = defs.get(aid)
    if not d or (not d.get("enabled", True) and not manual):
        return False
    p = achievement_progress(guild_id, user_id)
    if aid in p["unlocked"] and not manual:
        return False
    if not manual and not achievement_condition_met(guild_id, user_id, aid, d, p):
        return False
    if aid not in p["unlocked"]:
        p["unlocked"].append(aid)
    points = int(d.get("points", 0))
    p["points"] = int(p.get("points", 0)) + points
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    p.setdefault("unlock_dates", {}).setdefault(today, []).append(aid)
    # Achievement rewards are not counted as lifetime-earned Catnip, preventing
    # achievement reward chains from inflating Catnip earning milestones.
    catnip = int(d.get("catnip", 0))
    if catnip:
        economy_balances[(guild_id, user_id)] = economy_balance(guild_id, user_id) + catnip
    xp_reward = int(d.get("xp", 0))
    if xp_reward:
        xp_data[(guild_id, user_id)] = xp_data.get((guild_id, user_id), 0) + xp_reward
        await sync_level_roles(member, level_from_xp(xp_data[(guild_id, user_id)]))
    await achievement_assign_role(member, aid, d)
    log_fields=[("User", f"{member} ({user_id})"), ("Achievement", d.get("name")), ("Achievement Points", f"+{points}"), ("Catnip", f"+{catnip:,}"), ("XP", f"+{xp_reward:,}"), ("Manual", manual)]
    if d.get("special") == "linked_quest_achievement":
        log_fields.append(("Quest link", "`/quests progress` • quest completions update this achievement"))
    await achievement_log(guild_id, title="🏆 Achievement unlocked", fields=log_fields)
    await achievement_check_point_roles(member)
    await bd_save_data()
    return True


async def achievement_check_point_roles(member: discord.Member):
    p = achievement_progress(member.guild.id, member.id)
    cfg = achievement_roles.get(member.guild.id, {})
    top = member.guild.me.top_role if member.guild.me else None
    milestones = sorted(ACHIEVEMENT_POINT_MILESTONES.items(), key=lambda x: x[1][0])
    eligible = [(aid, data) for aid, data in milestones if p.get("points", 0) >= data[0]]
    highest = eligible[-1][0] if eligible else None
    for aid, _ in milestones:
        rid = cfg.get(aid)
        role = member.guild.get_role(rid) if rid else None
        if not role:
            continue
        if aid == highest:
            if role not in member.roles and (not top or role < top):
                try:
                    await member.add_roles(role, reason=f"Reached {ACHIEVEMENT_POINT_MILESTONES[aid][0]} Achievement Points")
                except discord.HTTPException:
                    pass
        elif role in member.roles:
            try:
                await member.remove_roles(role, reason="Achievement Points milestone upgrade")
            except discord.HTTPException:
                pass


async def achievement_record(guild_id: int, user_id: int, *, metric_updates=None, interaction_command=None, date_interaction=False, member=None):
    p = achievement_progress(guild_id, user_id)
    stats = p["stats"]
    for metric, amount in (metric_updates or {}).items():
        stats[metric] = int(stats.get(metric, 0)) + int(amount)
    if interaction_command:
        if guild_id not in achievement_session_first:
            achievement_session_first[guild_id] = user_id
            p["stats"]["session_first"] = True
        cmds = p.setdefault("interaction_commands", [])
        if interaction_command not in cmds:
            cmds.append(interaction_command)
        stats["cinnamon_interactions"] = int(stats.get("cinnamon_interactions", 0)) + 1
    if date_interaction:
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        days = p.setdefault("interaction_days", [])
        if today not in days:
            days.append(today)
    defs = _achievement_defs_for(guild_id)
    if member is None:
        member = bot.get_guild(guild_id).get_member(user_id) if bot.get_guild(guild_id) else None
    if member:
        for aid, d in defs.items():
            if aid not in p["unlocked"] and d.get("enabled", True) and achievement_condition_met(guild_id, user_id, aid, d, p):
                await achievement_grant(member, aid)
    await bd_save_data()


def achievement_display(d: dict, *, hidden=False) -> str:
    if hidden:
        return "🔒 **Secret Achievement**\nRequirement: *Hidden until unlocked.*"
    reward = []
    if d.get("catnip"): reward.append(f"🌿 {d['catnip']:,} Catnip")
    if d.get("xp"): reward.append(f"⭐ {d['xp']:,} XP")
    if d.get("points"): reward.append(f"🏆 {d['points']:,} AP")
    link = "\n🔗 **Linked:** `/quests progress` — quest completions update this achievement." if d.get("special") == "linked_quest_achievement" else ""
    return f"**{d.get('name')}**\n{d.get('description')}\n**Rewards:** {', '.join(reward) or 'Special role/status'}{link}"


async def achievement_setup_guild(guild: discord.Guild) -> dict:
    cfg = achievement_config.setdefault(guild.id, {})
    category = discord.utils.get(guild.categories, name="Cinnamon • Logs & Setup")
    if category is None:
        category = await guild.create_category("Cinnamon • Logs & Setup", reason="Cinnamon achievement setup")
    channel, created = await _ensure_setup_channel(guild, category, "cinnamon-achievement-logs", "Cinnamon achievement unlocks, administration, role setup, and recovery logs.")
    cfg["enabled"] = True
    cfg["log_channel_id"] = channel.id
    defs = _achievement_defs_for(guild.id)
    roles = achievement_roles.setdefault(guild.id, {})
    created_roles = 0
    # Create only roles explicitly used by achievements/point milestones.
    names = {}
    for aid, d in defs.items():
        if d.get("role"):
            names[aid] = d["role"]
    for aid, (_, role_name, _) in ACHIEVEMENT_POINT_MILESTONES.items():
        names[aid] = role_name
    for aid, role_name in names.items():
        existing = discord.utils.get(guild.roles, name=role_name)
        if existing is None:
            existing = await guild.create_role(name=role_name, reason="Cinnamon achievement setup")
            created_roles += 1
        roles[aid] = existing.id
    await bd_save_data()
    await achievement_log(guild.id, title="⚙️ Achievement system setup", fields=[("Admin", "Automatic /achievement setup"), ("Achievements", len(defs)), ("Secret achievements", sum(1 for d in defs.values() if d.get("secret"))), ("Roles created", created_roles), ("Log channel", channel.mention)])
    return {"channel": channel, "roles_created": created_roles, "achievements": len(defs)}


achievement_group = app_commands.Group(name="achievement", description="Cinnamon's achievement collection and administration")


@achievement_group.command(name="setup", description="Create and configure Cinnamon's complete achievement system")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_channels=True, manage_roles=True, send_messages=True, embed_links=True)
async def achievement_setup_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    result = await achievement_setup_guild(interaction.guild)
    await interaction.followup.send(f"🏆 **Achievement system ready!**\n• Achievements configured: **{result['achievements']}**\n• Secret achievements: **10**\n• Achievement roles created/reused: **{result['roles_created']}**\n• Log channel: {result['channel'].mention}\n\nEverything is persisted automatically. No achievement unlock announcements are posted publicly.", ephemeral=True)


@achievement_group.command(name="setup-status", description="Check Cinnamon's achievement setup")
@app_commands.guild_only()
async def achievement_setup_status_cmd(interaction: discord.Interaction):
    cfg = achievement_config.get(interaction.guild.id, {})
    defs = _achievement_defs_for(interaction.guild.id)
    configured = bool(cfg.get("enabled") and cfg.get("log_channel_id"))
    role_count = len(achievement_roles.get(interaction.guild.id, {}))
    await interaction.response.send_message(f"🏆 Achievement system: **{'Enabled' if configured else 'Not set up'}**\n• Achievements: **{len(defs)}**\n• Secret achievements: **{sum(1 for d in defs.values() if d.get('secret'))}**\n• Achievement roles mapped: **{role_count}**\n• Log channel: <#{cfg.get('log_channel_id')}>" if cfg.get('log_channel_id') else "• Log channel: Not configured", ephemeral=True)


@achievement_group.command(name="list", description="Browse Cinnamon's achievements")
@app_commands.guild_only()
async def achievement_list_cmd(interaction: discord.Interaction, show_secrets: bool = False):
    defs = _achievement_defs_for(interaction.guild.id)
    visible = [d for d in defs.values() if d.get("enabled", True) and (show_secrets or not d.get("secret"))]
    lines = []
    for d in visible:
        lines.append(achievement_display(d, hidden=d.get("secret", False)))
    pages = [lines[i:i+8] for i in range(0, len(lines), 8)] or [["No achievements configured."]]
    embeds=[]
    for i, page in enumerate(pages):
        e=cinnamon_embed(title="🏆 Cinnamon Achievements", description="\n\n".join(page), color=0xA970FF, guild=interaction.guild, footer=f"Cinnamon • Achievements • Page {i+1}/{len(pages)}")
        e.set_footer(text=f"Page {i+1}/{len(pages)} • Secret achievements stay hidden until unlocked.")
        embeds.append(e)
    await interaction.response.send_message(embeds=embeds[:10], ephemeral=True)


@achievement_group.command(name="profile", description="View your or another member's achievement profile")
@app_commands.guild_only()
async def achievement_profile_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    p = achievement_progress(interaction.guild.id, member.id)
    defs = _achievement_defs_for(interaction.guild.id)
    unlocked = [defs[a]["name"] for a in p["unlocked"] if a in defs]
    secret_unlocked = sum(1 for a in p["unlocked"] if defs.get(a, {}).get("secret"))
    e=cinnamon_embed(title=f"🏆 {member.display_name}'s Achievement Profile", color=0xA970FF, guild=interaction.guild, footer="Cinnamon • Achievement profile")
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="Achievement Points", value=f"✨ {p.get('points',0):,}", inline=True)
    e.add_field(name="Achievements", value=f"{len(unlocked)}/{len(defs)}", inline=True)
    e.add_field(name="Secret discoveries", value=str(secret_unlocked), inline=True)
    e.add_field(name="Recent unlocks", value="\n".join(f"• {x}" for x in unlocked[-10:]) or "None yet.", inline=False)
    await interaction.response.send_message(embed=e, allowed_mentions=discord.AllowedMentions.none())


@achievement_group.command(name="leaderboard", description="Show the Achievement Points leaderboard")
@app_commands.guild_only()
async def achievement_leaderboard_cmd(interaction: discord.Interaction):
    rows=[]
    for (gid, uid), p in achievement_data.items():
        if gid == interaction.guild.id:
            rows.append((uid, int(p.get("points",0))))
    rows.sort(key=lambda x:x[1], reverse=True)
    lines=[]
    for i,(uid,pts) in enumerate(rows[:10],1):
        m=interaction.guild.get_member(uid)
        lines.append(f"**#{i}** {m.display_name if m else uid} — ✨ **{pts:,} AP**")
    e=cinnamon_embed(title="🏆 Achievement Points Leaderboard", description="\n".join(lines) or "No achievement data yet.", color=0xA970FF, guild=interaction.guild, footer="Cinnamon • Achievement Points")
    await interaction.response.send_message(embed=e)


@achievement_group.command(name="info", description="Inspect an achievement")
@app_commands.guild_only()
async def achievement_info_cmd(interaction: discord.Interaction, achievement_id: str):
    d=_achievement_defs_for(interaction.guild.id).get(achievement_id.lower())
    if not d:
        await interaction.response.send_message("❌ Achievement ID not found.", ephemeral=True); return
    if d.get("secret"):
        await interaction.response.send_message("🔒 That's a secret achievement. Its requirement stays hidden until someone unlocks it.", ephemeral=True); return
    e=cinnamon_embed(title=f"🏆 {d['name']}", description=achievement_display(d), color=0xA970FF, guild=interaction.guild, footer="Cinnamon • Achievement details")
    await interaction.response.send_message(embed=e, ephemeral=True)


@achievement_group.command(name="secret", description="See how many secret achievements you have discovered")
@app_commands.guild_only()
async def achievement_secret_cmd(interaction: discord.Interaction):
    defs=_achievement_defs_for(interaction.guild.id); p=achievement_progress(interaction.guild.id, interaction.user.id)
    total=sum(1 for d in defs.values() if d.get("secret")); found=[a for a in p["unlocked"] if defs.get(a,{}).get("secret")]
    names="\n".join(f"🔓 {defs[a]['name']}" for a in found) or "None yet. The other secrets remain hidden."
    e=cinnamon_embed(title="🔒 Secret Achievements", description=f"Discovered: **{len(found)}/{total}**\n\n{names}", color=0x5B2C83, guild=interaction.guild, footer="Cinnamon • Secret achievements")
    await interaction.response.send_message(embed=e, ephemeral=True)


# --- Administrator achievement management ----------------------------------

@achievement_group.command(name="award", description="Admin: manually award an achievement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_award_cmd(interaction: discord.Interaction, member: discord.Member, achievement_id: str):
    aid=achievement_id.lower().strip(); d=_achievement_defs_for(interaction.guild.id).get(aid)
    if not d:
        await interaction.response.send_message("❌ Achievement ID not found.", ephemeral=True); return
    ok=await achievement_grant(member, aid, manual=True)
    await interaction.response.send_message(f"{'🏆 Awarded' if ok else 'ℹ️ Already unlocked'} **{d['name']}** for {member.mention}.", ephemeral=True)


@achievement_group.command(name="revoke", description="Admin: revoke an achievement and its points")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_revoke_cmd(interaction: discord.Interaction, member: discord.Member, achievement_id: str):
    aid=achievement_id.lower().strip(); d=_achievement_defs_for(interaction.guild.id).get(aid); p=achievement_progress(interaction.guild.id, member.id)
    if not d or aid not in p["unlocked"]:
        await interaction.response.send_message("❌ That achievement isn't unlocked for this member.", ephemeral=True); return
    p["unlocked"].remove(aid); p["points"]=max(0,int(p.get("points",0))-int(d.get("points",0)))
    role_id=achievement_roles.get(interaction.guild.id,{}).get(aid); role=interaction.guild.get_role(role_id) if role_id else None
    if role and role in member.roles:
        try: await member.remove_roles(role, reason="Achievement revoked")
        except discord.HTTPException: pass
    await bd_save_data(); await achievement_log(interaction.guild.id,title="🗑️ Achievement revoked",fields=[("Admin",f"{interaction.user} ({interaction.user.id})"),("User",f"{member} ({member.id})"),("Achievement",d['name'])])
    await interaction.response.send_message(f"🗑️ Revoked **{d['name']}** from {member.mention}.", ephemeral=True)


@achievement_group.command(name="user", description="Admin: inspect a member's raw achievement progress")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_user_cmd(interaction: discord.Interaction, member: discord.Member):
    p=achievement_progress(interaction.guild.id,member.id)
    stats=p.get("stats",{}); top=sorted(stats.items(), key=lambda x:x[1], reverse=True)[:12]
    text="\n".join(f"• `{k}`: **{v}**" for k,v in top)
    await interaction.response.send_message(f"🏆 **{member.display_name}** — {p.get('points',0):,} AP\nUnlocked: **{len(p.get('unlocked',[]))}**\n\n{text}",ephemeral=True)


@achievement_group.command(name="stats", description="Admin: show achievement system statistics")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_stats_cmd(interaction: discord.Interaction):
    defs=_achievement_defs_for(interaction.guild.id); users=[p for (g,_),p in achievement_data.items() if g==interaction.guild.id]
    total_unlocks=sum(len(p.get("unlocked",[])) for p in users)
    await interaction.response.send_message(f"🏆 **Achievement stats**\n• Definitions: **{len(defs)}**\n• Secrets: **{sum(1 for d in defs.values() if d.get('secret'))}**\n• Users tracked: **{len(users)}**\n• Total unlocks: **{total_unlocks}**\n• Total Achievement Points awarded: **{sum(int(p.get('points',0)) for p in users):,}**",ephemeral=True)


@achievement_group.command(name="roles", description="Admin: show achievement role mappings")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_roles_cmd(interaction: discord.Interaction):
    defs=_achievement_defs_for(interaction.guild.id); roles=achievement_roles.get(interaction.guild.id,{})
    lines=[]
    for aid,d in defs.items():
        if d.get("role"):
            role=interaction.guild.get_role(roles.get(aid,0)); lines.append(f"`{aid}` → {role.mention if role else 'missing'}")
    await interaction.response.send_message("🏆 **Achievement roles**\n"+"\n".join(lines),ephemeral=True)


@achievement_group.command(name="role-set", description="Admin: map an achievement to an existing role")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_role_set_cmd(interaction: discord.Interaction, achievement_id: str, role: discord.Role):
    aid=achievement_id.lower().strip(); d=_achievement_defs_for(interaction.guild.id).get(aid)
    if not d: await interaction.response.send_message("❌ Achievement ID not found.",ephemeral=True); return
    achievement_roles.setdefault(interaction.guild.id,{})[aid]=role.id; await bd_save_data()
    await interaction.response.send_message(f"✅ `{aid}` now uses {role.mention}.",ephemeral=True)


@achievement_group.command(name="role-remove", description="Admin: remove an achievement's role mapping")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_role_remove_cmd(interaction: discord.Interaction, achievement_id: str):
    aid=achievement_id.lower().strip(); removed=achievement_roles.setdefault(interaction.guild.id,{}).pop(aid,None); await bd_save_data()
    await interaction.response.send_message("🗑️ Role mapping removed." if removed else "ℹ️ No role mapping existed.",ephemeral=True)


@achievement_group.command(name="enable", description="Admin: enable an achievement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_enable_cmd(interaction: discord.Interaction, achievement_id: str):
    d=_achievement_defs_for(interaction.guild.id).get(achievement_id.lower().strip())
    if not d: await interaction.response.send_message("❌ Achievement ID not found.",ephemeral=True); return
    d["enabled"]=True; await bd_save_data(); await interaction.response.send_message(f"✅ Enabled **{d['name']}**.",ephemeral=True)


@achievement_group.command(name="disable", description="Admin: disable an achievement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_disable_cmd(interaction: discord.Interaction, achievement_id: str):
    d=_achievement_defs_for(interaction.guild.id).get(achievement_id.lower().strip())
    if not d: await interaction.response.send_message("❌ Achievement ID not found.",ephemeral=True); return
    d["enabled"]=False; await bd_save_data(); await interaction.response.send_message(f"⏸️ Disabled **{d['name']}**.",ephemeral=True)


@achievement_group.command(name="create", description="Admin: create a custom achievement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_create_cmd(interaction: discord.Interaction, achievement_id: str, name: str, metric: str, threshold: app_commands.Range[int,1,100000000], catnip: int=0, xp: int=0, points: app_commands.Range[int,0,10000]=10, secret: bool=False):
    aid=achievement_id.lower().strip(); defs=_achievement_defs_for(interaction.guild.id)
    if aid in defs: await interaction.response.send_message("❌ That achievement ID already exists.",ephemeral=True); return
    if metric not in ACHIEVEMENT_METRICS: await interaction.response.send_message(f"❌ Metric must be one of: {', '.join(sorted(ACHIEVEMENT_METRICS))}",ephemeral=True); return
    defs[aid]={"name":name[:100],"description":f"Reach {threshold} {metric}.","metric":metric,"threshold":int(threshold),"catnip":max(0,int(catnip)),"xp":max(0,int(xp)),"points":int(points),"role":None,"secret":secret,"enabled":True,"role_group":None,"special":None}
    await bd_save_data(); await achievement_log(interaction.guild.id,title="🛠️ Achievement created",fields=[("Admin",f"{interaction.user} ({interaction.user.id})"),("ID",aid),("Name",name)])
    await interaction.response.send_message(f"✅ Created `{aid}` — **{name}**.",ephemeral=True)


@achievement_group.command(name="edit", description="Admin: edit a custom achievement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_edit_cmd(interaction: discord.Interaction, achievement_id: str, name: str|None=None, threshold: int|None=None, catnip: int|None=None, xp: int|None=None, points: int|None=None, description: str|None=None):
    d=_achievement_defs_for(interaction.guild.id).get(achievement_id.lower().strip())
    if not d: await interaction.response.send_message("❌ Achievement ID not found.",ephemeral=True); return
    for k,v in (("name",name),("threshold",threshold),("catnip",catnip),("xp",xp),("points",points),("description",description)):
        if v is not None: d[k]=v
    await bd_save_data(); await interaction.response.send_message(f"✅ Updated **{d['name']}**.",ephemeral=True)


@achievement_group.command(name="delete", description="Admin: delete a custom achievement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_delete_cmd(interaction: discord.Interaction, achievement_id: str):
    aid=achievement_id.lower().strip(); d=_achievement_defs_for(interaction.guild.id).pop(aid,None)
    if not d: await interaction.response.send_message("❌ Achievement ID not found.",ephemeral=True); return
    achievement_roles.setdefault(interaction.guild.id,{}).pop(aid,None); await bd_save_data()
    await interaction.response.send_message(f"🗑️ Deleted `{aid}`.",ephemeral=True)


@achievement_group.command(name="secret-create", description="Admin: create a hidden secret achievement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_secret_create_cmd(interaction: discord.Interaction, achievement_id: str, name: str, metric: str, threshold: app_commands.Range[int,1,100000000], catnip: int=0, xp: int=0, points: app_commands.Range[int,0,10000]=10):
    aid=achievement_id.lower().strip(); defs=_achievement_defs_for(interaction.guild.id)
    if aid in defs: await interaction.response.send_message("❌ That achievement ID already exists.",ephemeral=True); return
    if metric not in ACHIEVEMENT_METRICS: await interaction.response.send_message(f"❌ Metric must be one of: {', '.join(sorted(ACHIEVEMENT_METRICS))}",ephemeral=True); return
    defs[aid]={"name":name[:100],"description":"A secret achievement. Requirement hidden until unlocked.","metric":metric,"threshold":int(threshold),"catnip":max(0,int(catnip)),"xp":max(0,int(xp)),"points":int(points),"role":None,"secret":True,"enabled":True,"role_group":None,"special":None}
    await bd_save_data(); await interaction.response.send_message(f"🔒 Created hidden secret achievement `{aid}` — **{name}**.",ephemeral=True)

@achievement_group.command(name="secret-edit", description="Admin: edit a hidden secret achievement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_secret_edit_cmd(interaction: discord.Interaction, achievement_id: str, name: str|None=None, threshold: int|None=None, catnip: int|None=None, xp: int|None=None, points: int|None=None):
    d=_achievement_defs_for(interaction.guild.id).get(achievement_id.lower().strip())
    if not d or not d.get("secret"): await interaction.response.send_message("❌ Hidden secret achievement not found.",ephemeral=True); return
    for k,v in (("name",name),("threshold",threshold),("catnip",catnip),("xp",xp),("points",points)):
        if v is not None: d[k]=v
    await bd_save_data(); await interaction.response.send_message(f"✅ Updated hidden secret **{d['name']}**.",ephemeral=True)

@achievement_group.command(name="secret-delete", description="Admin: delete a hidden secret achievement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_secret_delete_cmd(interaction: discord.Interaction, achievement_id: str):
    aid=achievement_id.lower().strip(); d=_achievement_defs_for(interaction.guild.id).get(aid)
    if not d or not d.get("secret"): await interaction.response.send_message("❌ Hidden secret achievement not found.",ephemeral=True); return
    _achievement_defs_for(interaction.guild.id).pop(aid,None); achievement_roles.setdefault(interaction.guild.id,{}).pop(aid,None); await bd_save_data(); await interaction.response.send_message(f"🗑️ Deleted secret achievement `{aid}`.",ephemeral=True)

@achievement_group.command(name="secret-enable", description="Admin: enable a secret achievement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_secret_enable_cmd(interaction: discord.Interaction, achievement_id: str):
    d=_achievement_defs_for(interaction.guild.id).get(achievement_id.lower().strip())
    if not d or not d.get("secret"): await interaction.response.send_message("❌ Hidden secret achievement not found.",ephemeral=True); return
    d["enabled"]=True; await bd_save_data(); await interaction.response.send_message(f"🔓 Secret achievement **{d['name']}** enabled.",ephemeral=True)

@achievement_group.command(name="secret-disable", description="Admin: disable a secret achievement")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_secret_disable_cmd(interaction: discord.Interaction, achievement_id: str):
    d=_achievement_defs_for(interaction.guild.id).get(achievement_id.lower().strip())
    if not d or not d.get("secret"): await interaction.response.send_message("❌ Hidden secret achievement not found.",ephemeral=True); return
    d["enabled"]=False; await bd_save_data(); await interaction.response.send_message(f"⏸️ Secret achievement **{d['name']}** disabled.",ephemeral=True)

@achievement_group.command(name="backup", description="Admin: create an achievement backup in the achievement log")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_backup_cmd(interaction: discord.Interaction):
    payload={"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"definitions":_achievement_defs_for(interaction.guild.id),"roles":achievement_roles.get(interaction.guild.id,{}),"config":achievement_config.get(interaction.guild.id,{}),"users":{str(uid):p for (gid,uid),p in achievement_data.items() if gid==interaction.guild.id}}
    await achievement_log(interaction.guild.id,title="💾 Achievement backup",fields=[("Admin",f"{interaction.user} ({interaction.user.id})"),("Users",len(payload["users"])),("Definitions",len(payload["definitions"]))])
    await interaction.response.send_message("💾 Achievement backup created and logged. Use the log channel history for recovery.",ephemeral=True)


@achievement_group.command(name="recover", description="Admin: recover achievement data from the latest bot storage state")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def achievement_recover_cmd(interaction: discord.Interaction):
    await bd_load_data(); await interaction.response.send_message("🩹 Achievement data reloaded from persistent storage.",ephemeral=True)


bot.tree.add_command(achievement_group)

# ---------------------------------------------------------------------------
# Economy — Catnip, items, quests, transaction logs, and reset-safe snapshots
# ---------------------------------------------------------------------------


def economy_key(guild_id: int, user_id: int) -> tuple[int, int]:
    return guild_id, user_id


def economy_balance(guild_id: int, user_id: int) -> int:
    key = economy_key(guild_id, user_id)
    if key not in economy_balances:
        economy_balances[key] = ECONOMY_STARTING_BALANCE
    return int(economy_balances[key])


def economy_inventory_for(guild_id: int, user_id: int) -> dict:
    key = economy_key(guild_id, user_id)
    if key not in economy_inventory:
        economy_inventory[key] = {}
    return economy_inventory[key]


def economy_quests_for(guild_id: int, user_id: int) -> dict:
    key = economy_key(guild_id, user_id)
    if key not in economy_quests:
        economy_quests[key] = {qid: 0 for qid in ECONOMY_QUESTS}
    else:
        for qid in ECONOMY_QUESTS:
            economy_quests[key].setdefault(qid, 0)
    return economy_quests[key]


def economy_user_snapshot(guild_id: int, user_id: int) -> dict:
    return {
        "balance": economy_balance(guild_id, user_id),
        "inventory": dict(economy_inventory_for(guild_id, user_id)),
        "quests": dict(economy_quests_for(guild_id, user_id)),
        "level_rewards_claimed": list(economy_level_rewards_claimed.get((guild_id, user_id), [])),
    }


async def economy_log(guild_id: int, *, title: str, description: str = "", fields=None):
    channel_id = economy_log_channels.get(guild_id)
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        return
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.gold(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    for name, value in (fields or []):
        embed.add_field(name=name, value=str(value), inline=True)
    embed.set_footer(text=f"Cinnamon economy log • Guild {guild_id}")
    try:
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        log.error(f"Failed to send economy log in guild {guild_id}: {e}")


def economy_cooldown_remaining(guild_id: int, user_id: int, action: str) -> int:
    until = float(economy_cooldowns.get((guild_id, user_id, action), 0))
    return max(0, math.ceil(until - time.time()))


def economy_item_lines() -> str:
    return "\n".join(
        f"{item['emoji']} **{item['name']}** — `{item_id}` — **{item['price']} Catnip**\n{item['description']}"
        for item_id, item in ECONOMY_ITEMS.items()
    )


async def economy_do_work(guild_id: int, user: discord.abc.User) -> tuple[bool, int, str]:
    user_id = user.id
    remaining = economy_cooldown_remaining(guild_id, user_id, "work")
    if remaining:
        return False, 0, f"🐱💤 Cinnamon has put you on a tiny work break! Try again in **{remaining // 60}m {remaining % 60}s**. Even cats need nap time."
    amount = random.randint(ECONOMY_WORK_MIN, ECONOMY_WORK_MAX)
    jobs = [
        "sorted Cinnamon's treats", "guarded the tuna cupboard", "cleaned the cat tree",
        "chased a suspicious cardboard box", "organized the yarn drawer",
        "polished Cinnamon's food bowl", "delivered a mysterious package of kibble",
        'patrolled the windowsill for imaginary birds',
        "counted Cinnamon's toe beans",
        'rearranged the sunbeams',
        'inspected every cardboard box',
        'folded tiny cat blankets',
        'guarded the forbidden snack drawer',
        'organized the fish stickers',
        'polished the royal scratching post',
        'chased a laser dot',
        'supervised nap time',
        'refilled the water fountain',
        'checked the tuna delivery',
        'sorted yarn by squishiness',
        'tested three cardboard boxes',
        'removed one suspicious dust bunny',
        'counted the cat toys',
        'delivered a tiny parcel',
        'cleaned the treat shelf',
        'watched the garden for pigeons',
        "organized Cinnamon's plushies",
        'tested the comfiest cushion',
        'escorted a fly out of the room',
        'inspected the food bowls',
        'untangled the yarn',
        'guarded the cozy blanket',
        'polished the bell collar',
        'checked the emergency tuna supply',
        "filed Cinnamon's imaginary paperwork",
        'stamped pretend invoices',
        'answered the meow hotline',
        'inspected the cat castle',
        'repaired a wobbly toy',
        'sorted fish-shaped biscuits',
        'counted the scratching posts',
        'checked every hiding spot',
        'protected the nap corner',
        'reorganized the toy basket',
        'carried a sock to headquarters',
        'investigated a mysterious noise',
        'supervised the vacuum from a safe distance',
        'checked the curtains for intruders',
        'delivered premium catnip',
        'organized the biscuit budget',
        'guarded the treat jar',
        'tested a new cardboard fort',
        'polished the tiny bell',
        'inspected the balcony',
        'counted the blankets',
        'sorted the sleepy pillows',
        'chased a paper ball',
        'delivered a catnip ball',
        'checked the royal throne',
        'organized snack receipts',
        'patrolled the hallway',
        'investigated a suspicious shadow',
        'tested the softest towel',
        'restocked the tuna shelf',
        'cleaned the royal nap station',
        'checked the food timer',
        'organized the meow schedule',
        'protected the yarn kingdom',
        'inspected the scratching mat',
        'counted the fish cans',
        'delivered a surprise treat',
        'checked the windows for birds',
        'repaired the cat tree ladder',
        'organized the whisker department',
        'guarded the cardboard fort',
        'tested the zoomies track',
        'sorted the catnip stash',
        'checked the emergency snack box',
        "inspected Cinnamon's favorite chair",
        'delivered a bowl of fresh water',
        'polished the food scoop',
        'organized the nap timetable',
        'patrolled the snack cabinet',
        'investigated a rogue shoelace',
        'checked the toy batteries',
        'sorted the plush mice',
        'guarded the sunny spot',
        'delivered a fancy fish',
        'organized the treat inventory',
        'inspected the litter-free hallway',
        'checked the royal cushions',
        'repaired a toy mouse',
        'patrolled the bookcase',
        'counted the suspicious boxes',
        'organized the cat café menu',
        'tested the crunchy treats',
        'checked the secret tunnel',
        'delivered a blanket',
        'guarded the fish tank',
        'inspected the meow mailbox',
        'sorted the cat-themed paperwork',
        'checked the snack alarm',
        'organized the royal schedule',
        'chased an imaginary butterfly',
        'secured the premium tuna',
        'supervised the human staff',
        "completed Cinnamon's mysterious assignment",
    ]
    job = random.choice(jobs)
    economy_cooldowns[(guild_id, user_id, "work")] = time.time() + ECONOMY_WORK_COOLDOWN
    economy_balances[(guild_id, user_id)] = economy_balance(guild_id, user_id) + amount
    await achievement_record(guild_id, user_id, metric_updates={"work_sessions": 1, "lifetime_earned": amount}, member=user)
    qdone = await quest_record_event(guild_id, user_id, "work", 1, member=user)
    qdone += await quest_record_event(guild_id, user_id, "earned", amount, member=user)
    await bd_save_data()
    await economy_log(guild_id, title="💼 Economy work", fields=[("User", f"{user} ({user_id})"), ("Job", job), ("Earned", f"+{amount} Catnip")])
    return True, amount, f"💼 You **{job}** and earned **{amount} Catnip**! *Cinnamon inspects the work proudly.*"


def economy_level_reward_claimed(guild_id: int, user_id: int, level: int) -> bool:
    return level in economy_level_rewards_claimed.get((guild_id, user_id), [])


def mark_economy_level_reward_claimed(guild_id: int, user_id: int, level: int):
    key = (guild_id, user_id)
    economy_level_rewards_claimed.setdefault(key, [])
    if level not in economy_level_rewards_claimed[key]:
        economy_level_rewards_claimed[key].append(level)


def economy_income_role_lines(guild: discord.Guild) -> str:
    cfg = economy_income_roles.get(guild.id, {})
    if not cfg:
        return "No income roles are configured."
    lines = []
    for role_id, data in cfg.items():
        role = guild.get_role(int(role_id))
        name = role.mention if role else f"Deleted role ({role_id})"
        cooldown = int(data.get("cooldown", 3600))
        amount = int(data.get("amount", 0))
        interval = int(data.get("interval", max(1, cooldown // 3600)))
        unit = str(data.get("unit", "hour"))
        lines.append(f"{name} — **{amount:,} Catnip / {interval} {unit}(s)**")
    return "\n".join(lines)


economy_group = app_commands.Group(name="economy", description="Cinnamon's Catnip economy, items, quests, and backups")


@economy_group.command(name="balance", description="Check your Catnip balance")
@app_commands.guild_only()
async def economy_balance_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    balance = economy_balance(interaction.guild.id, member.id)
    inv = economy_inventory_for(interaction.guild.id, member.id)
    item_count = sum(int(v) for v in inv.values())
    embed = discord.Embed(title=f"🐾 {member.display_name}'s wallet", color=discord.Color.gold())
    embed.add_field(name="Catnip", value=f"🌿 **{balance:,}**", inline=True)
    embed.add_field(name="Items", value=f"🎒 **{item_count}**", inline=True)
    await interaction.response.send_message(embed=embed)
    await economy_log(interaction.guild.id, title="👛 Economy balance viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Balance", f"{balance:,} Catnip")])
    await bd_save_data()


@economy_group.command(name="inventory", description="See your Cinnamon items")
@app_commands.guild_only()
async def economy_inventory_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    inv = economy_inventory_for(interaction.guild.id, member.id)
    lines = []
    for item_id, qty in inv.items():
        if qty > 0 and item_id in ECONOMY_ITEMS:
            item = ECONOMY_ITEMS[item_id]
            lines.append(f"{item['emoji']} **{item['name']}** × **{qty}** (`{item_id}`)")
    embed = discord.Embed(title=f"🎒 {member.display_name}'s inventory", color=discord.Color.blurple())
    embed.description = "\n".join(lines) if lines else "Your inventory is empty. Visit `/economy shop`!"
    await interaction.response.send_message(embed=embed)
    await economy_log(interaction.guild.id, title="🎒 Economy inventory viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})")])


@economy_group.command(name="shop", description="View Cinnamon's shop")
@app_commands.guild_only()
async def economy_shop_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🐟 Cinnamon's Catnip Shop", description=economy_item_lines(), color=discord.Color.gold())
    embed.set_footer(text="Buy with /economy buy item:<item_id> quantity:<number>")
    await interaction.response.send_message(embed=embed)
    await economy_log(interaction.guild.id, title="🛒 Economy shop viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})")])


@economy_group.command(name="buy", description="Buy an item with Catnip")
@app_commands.describe(item="Item ID or item name from /economy shop", quantity="How many to buy")
@app_commands.guild_only()
async def economy_buy_cmd(interaction: discord.Interaction, item: str, quantity: app_commands.Range[int, 1, 99] = 1):
    guild_id, user_id = interaction.guild.id, interaction.user.id
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await interaction.response.send_message("❌ That item isn't in the shop. Use `/economy shop` to see available items.", ephemeral=True)
        return
    current_qty = int(economy_inventory_for(guild_id, user_id).get(item_id, 0))
    max_per_person = int(data.get("max_per_person", 0))
    if max_per_person and current_qty + quantity > max_per_person:
        await interaction.response.send_message(f"❌ This item has a limit of **{max_per_person}** per person. You already have **{current_qty}**.", ephemeral=True)
        return
    cost = data["price"] * quantity
    balance = economy_balance(guild_id, user_id)
    if balance < cost:
        await interaction.response.send_message(f"❌ You need **{cost:,} Catnip**, but you only have **{balance:,}**.", ephemeral=True)
        return
    economy_balances[(guild_id, user_id)] = balance - cost
    await achievement_record(guild_id, user_id, metric_updates={"purchases": 1, "lifetime_spent": cost}, member=interaction.user)
    qdone = await quest_record_event(guild_id, user_id, "buy", quantity, member=interaction.user)
    qdone += await quest_record_event(guild_id, user_id, "spent", cost, member=interaction.user)
    qdone += await quest_record_event(guild_id, user_id, f"items:{item_id}", quantity, member=interaction.user)
    inv = economy_inventory_for(guild_id, user_id)
    inv[item_id] = current_qty + quantity
    await bd_save_data()
    await economy_log(guild_id, title="🛒 Economy purchase", fields=[("User", f"{interaction.user} ({user_id})"), ("Item", data["name"]), ("Quantity", quantity), ("Cost", f"{cost:,} Catnip")])
    await interaction.response.send_message(f"🛒 Bought **{quantity}× {data['emoji']} {data['name']}** for **{cost:,} Catnip**. Balance: **{economy_balances[(guild_id, user_id)]:,}**")


@economy_group.command(name="daily", description="Claim your daily Catnip")
@app_commands.guild_only()
async def economy_daily_cmd(interaction: discord.Interaction):
    guild_id, user_id = interaction.guild.id, interaction.user.id
    remaining = economy_cooldown_remaining(guild_id, user_id, "daily")
    if remaining:
        await interaction.response.send_message(f"🐾 Cinnamon already gave you your daily Catnip. Come back in **{remaining // 3600}h {(remaining % 3600) // 60}m**.", ephemeral=True)
        return
    economy_cooldowns[(guild_id, user_id, "daily")] = time.time() + 86400
    economy_balances[(guild_id, user_id)] = economy_balance(guild_id, user_id) + ECONOMY_DAILY_REWARD
    await achievement_record(guild_id, user_id, metric_updates={"lifetime_earned": ECONOMY_DAILY_REWARD}, member=interaction.user)
    await quest_record_event(guild_id, user_id, "earned", ECONOMY_DAILY_REWARD, member=interaction.user)
    await bd_save_data()
    await economy_log(guild_id, title="🌿 Daily Catnip", fields=[("User", f"{interaction.user} ({user_id})"), ("Amount", f"+{ECONOMY_DAILY_REWARD} Catnip")])
    await interaction.response.send_message(f"🌿 **+{ECONOMY_DAILY_REWARD} Catnip!** Cinnamon has approved your daily snack budget.")


@economy_group.command(name="work", description="Work for Cinnamon and earn 50-150 Catnip every 10 minutes")
@app_commands.guild_only()
async def economy_work_cmd(interaction: discord.Interaction):
    ok, amount, message = await economy_do_work(interaction.guild.id, interaction.user)
    await interaction.response.send_message(message, ephemeral=not ok)


@economy_group.command(name="give", description="Give Catnip to another member")
@app_commands.guild_only()
async def economy_give_cmd(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1000000]):
    guild_id = interaction.guild.id
    if member.bot:
        await interaction.response.send_message("❌ Bot accounts can't receive Catnip.", ephemeral=True)
        return
    if member.id == interaction.user.id:
        await interaction.response.send_message("🐾 You can't give Catnip to yourself.", ephemeral=True)
        return
    sender_balance = economy_balance(guild_id, interaction.user.id)
    if sender_balance < amount:
        await interaction.response.send_message(f"❌ You only have **{sender_balance:,} Catnip**.", ephemeral=True)
        return
    economy_balances[(guild_id, interaction.user.id)] = sender_balance - amount
    economy_balances[(guild_id, member.id)] = economy_balance(guild_id, member.id) + amount
    await bd_save_data()
    await economy_log(guild_id, title="🎁 Catnip transfer", fields=[("From", f"{interaction.user} ({interaction.user.id})"), ("To", f"{member} ({member.id})"), ("Amount", f"{amount:,} Catnip")])
    await interaction.response.send_message(f"🎁 Gave **{amount:,} Catnip** to {member.mention}.")


@economy_group.command(name="leaderboard", description="Show the richest members")
@app_commands.guild_only()
async def economy_leaderboard_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    rows = [(uid, bal) for (gid, uid), bal in economy_balances.items() if gid == guild_id]
    rows.sort(key=lambda x: x[1], reverse=True)
    lines = []
    for i, (uid, bal) in enumerate(rows[:10], 1):
        member = interaction.guild.get_member(uid)
        name = member.display_name if member else f"User {uid}"
        lines.append(f"**{i}.** {name} — 🌿 **{bal:,}**")
    embed = discord.Embed(title="🏆 Catnip leaderboard", description="\n".join(lines) if lines else "No economy users yet.", color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)


@economy_group.command(name="quest", description="View Cinnamon quests and your progress")
@app_commands.guild_only()
async def economy_quest_cmd(interaction: discord.Interaction):
    progress = economy_quests_for(interaction.guild.id, interaction.user.id)
    lines = []
    for qid, q in ECONOMY_QUESTS.items():
        done = min(progress.get(qid, 0), q["amount"])
        lines.append(f"**{q['name']}** — {done}/{q['amount']} {ECONOMY_ITEMS[q['item']]['emoji']} {ECONOMY_ITEMS[q['item']]['name']} → **{q['reward']} Catnip**\n{q['description']}")
    embed = discord.Embed(title="📜 Cinnamon's quests", description="\n\n".join(lines), color=discord.Color.blurple())
    embed.set_footer(text="Use /economy feed to give Cinnamon the required item.")
    await interaction.response.send_message(embed=embed)


@economy_group.command(name="feed", description="Give Cinnamon an item and progress matching quests")
@app_commands.describe(item="Item to give Cinnamon", quantity="How many to give")
@app_commands.choices(item=[app_commands.Choice(name=v["name"], value=k) for k, v in ECONOMY_ITEMS.items()])
@app_commands.guild_only()
async def economy_feed_cmd(interaction: discord.Interaction, item: app_commands.Choice[str], quantity: app_commands.Range[int, 1, 99] = 1):
    guild_id, user_id = interaction.guild.id, interaction.user.id
    item_id = item.value
    inv = economy_inventory_for(guild_id, user_id)
    have = int(inv.get(item_id, 0))
    if have < quantity:
        await interaction.response.send_message(f"❌ You only have **{have}× {ECONOMY_ITEMS[item_id]['name']}**.", ephemeral=True)
        return
    inv[item_id] = have - quantity
    completed = []
    feed_updates = {"tuna_given": quantity} if item_id == "tuna" else {}
    if item_id == "treat": feed_updates["treats_given"] = quantity
    if feed_updates:
        await achievement_record(guild_id, user_id, metric_updates=feed_updates, member=interaction.user)
    progress = economy_quests_for(guild_id, user_id)
    for qid, q in ECONOMY_QUESTS.items():
        if q["item"] != item_id:
            continue
        before = min(progress.get(qid, 0), q["amount"])
        progress[qid] = before + quantity
        if before < q["amount"] <= progress[qid]:
            economy_balances[(guild_id, user_id)] = economy_balance(guild_id, user_id) + q["reward"]
            await achievement_record(guild_id, user_id, metric_updates={"lifetime_earned": q["reward"], "quests_completed": 1}, member=interaction.user)
            await quest_record_event(guild_id, user_id, "earned", q["reward"], member=interaction.user)
            completed.append(f"**{q['name']}** (+{q['reward']} Catnip)")
    await bd_save_data()
    await economy_log(guild_id, title="🐟 Cinnamon fed", fields=[("User", f"{interaction.user} ({user_id})"), ("Item", ECONOMY_ITEMS[item_id]["name"]), ("Quantity", quantity), ("Quest rewards", ", ".join(completed) if completed else "None")])
    text = f"🐾 Cinnamon happily accepted **{quantity}× {ECONOMY_ITEMS[item_id]['name']}**!"
    if completed:
        text += "\n🎉 Quest complete: " + ", ".join(completed)
    await interaction.response.send_message(text)


@economy_group.command(name="logs", description="Set or disable the economy transaction log channel")
@app_commands.describe(channel="Channel where economy transactions and backups will be logged; omit to disable")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def economy_logs_cmd(interaction: discord.Interaction, channel: discord.TextChannel | None = None):
    guild_id = interaction.guild.id
    if channel is None:
        removed = economy_log_channels.pop(guild_id, None)
        await bd_save_data()
        await interaction.response.send_message("🧾 Economy logs disabled." if removed else "🧾 Economy logs are already disabled.", ephemeral=True)
        return
    economy_log_channels[guild_id] = channel.id
    await bd_save_data()
    await economy_log(guild_id, title="🧾 Economy logging enabled", description=f"Economy transactions and backup snapshots will be posted here: {channel.mention}")
    await interaction.response.send_message(f"✅ Economy logs will now go to {channel.mention}.", ephemeral=True)


async def economy_snapshot_payload(guild_id: int) -> dict:
    users = {}
    user_ids = set()
    for (gid, uid) in economy_balances:
        if gid == guild_id: user_ids.add(uid)
    for (gid, uid) in economy_inventory:
        if gid == guild_id: user_ids.add(uid)
    for (gid, uid) in economy_quests:
        if gid == guild_id: user_ids.add(uid)
    for uid in user_ids:
        users[str(uid)] = economy_user_snapshot(guild_id, uid)
    return {
        "schema": 1,
        "type": "cinnamon_economy_snapshot",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "guild_id": guild_id,
        "currency": "Catnip",
        "users": users,
        "items": ECONOMY_ITEMS,
        "quests": ECONOMY_QUESTS,
        "level_rewards": ECONOMY_LEVEL_REWARDS,
        "income_roles": economy_income_roles.get(guild_id, {}),
        "achievement_definitions": _achievement_defs_for(guild_id),
        "achievement_roles": achievement_roles.get(guild_id, {}),
        "achievement_config": achievement_config.get(guild_id, {}),
        "achievement_users": {str(uid): p for (gid, uid), p in achievement_data.items() if gid == guild_id},
    }


@economy_group.command(name="snapshot", description="Create one complete economy backup before resetting the bot")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def economy_snapshot_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    channel_id = economy_log_channels.get(guild_id)
    channel = bot.get_channel(channel_id) if channel_id else None
    if channel is None:
        await interaction.response.send_message("❌ Set an economy log channel first with `/economy logs #channel`.", ephemeral=True)
        return
    payload = await economy_snapshot_payload(guild_id)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    file = discord.File(io.BytesIO(raw), filename=f"cinnamon_economy_snapshot_{guild_id}.json")
    user_count = len(payload["users"])
    embed = discord.Embed(title="💾 Cinnamon economy snapshot", description="Complete Catnip balances, inventories, quest progress, item definitions, quest definitions, and achievement progress/configuration for this server. Keep this message/file before a reset.", color=discord.Color.green(), timestamp=datetime.datetime.now(datetime.timezone.utc))
    embed.add_field(name="Users backed up", value=str(user_count), inline=True)
    embed.add_field(name="Currency", value="Catnip", inline=True)
    embed.add_field(name="Items", value=str(len(ECONOMY_ITEMS)), inline=True)
    rows = []
    for uid_text, user in sorted(payload["users"].items(), key=lambda pair: int(pair[1].get("balance", 0)), reverse=True)[:10]:
        member = guild_id and bot.get_guild(guild_id).get_member(int(uid_text))
        name = member.display_name if member else f"User {uid_text}"
        rows.append(f"{len(rows)+1}. {name} — {int(user.get('balance', 0)):,} Catnip")
    embed.add_field(name="🏆 Leaderboard at backup time", value="\n".join(rows) if rows else "No users yet.", inline=False)
    item_text = "\n".join(f"{v['emoji']} {v['name']} (`{k}`) — {v['price']} Catnip" for k, v in ECONOMY_ITEMS.items())
    embed.add_field(name="🛒 Item information", value=item_text, inline=False)
    quest_text = "\n".join(f"{q['name']} — {q['amount']}× {ECONOMY_ITEMS[q['item']]['name']} → {q['reward']} Catnip" for q in ECONOMY_QUESTS.values())
    embed.add_field(name="📜 Quest information", value=quest_text, inline=False)
    embed.add_field(name="How to restore", value="After the reset, run `/economy recover` in this server. The bot will scan this log channel for the newest snapshot.", inline=False)
    await interaction.response.defer(ephemeral=True)
    await channel.send(embed=embed, file=file)
    await bd_save_data()
    await interaction.followup.send(f"✅ Snapshot saved to {channel.mention}. **{user_count}** users are included. You can reset the bot and later run `/economy recover`.", ephemeral=True)


async def economy_restore_from_snapshot(guild: discord.Guild, limit: int = 5000) -> tuple[int, str]:
    channel_id = economy_log_channels.get(guild.id)
    if not channel_id:
        return 0, "No economy log channel is configured."
    channel = bot.get_channel(channel_id)
    if channel is None:
        return 0, "The configured economy log channel could not be found."
    latest = None
    try:
        async for message in channel.history(limit=limit):
            for attachment in message.attachments:
                if attachment.filename.startswith("cinnamon_economy_snapshot_") and attachment.filename.endswith(".json"):
                    try:
                        data = json.loads((await attachment.read()).decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError, discord.HTTPException):
                        continue
                    if data.get("type") == "cinnamon_economy_snapshot" and int(data.get("guild_id", 0)) == guild.id:
                        latest = data
                        break
            if latest:
                break
    except discord.HTTPException as e:
        return 0, f"Could not read the economy log channel: {e}"
    if latest is None:
        return 0, "No economy snapshot was found in the log channel."

    restored = 0
    for uid_text, user in latest.get("users", {}).items():
        try:
            uid = int(uid_text)
            economy_balances[(guild.id, uid)] = int(user.get("balance", ECONOMY_STARTING_BALANCE))
            economy_inventory[(guild.id, uid)] = {str(k): int(v) for k, v in user.get("inventory", {}).items() if int(v) > 0}
            economy_quests[(guild.id, uid)] = {str(k): int(v) for k, v in user.get("quests", {}).items()}
            economy_level_rewards_claimed[(guild.id, uid)] = [int(x) for x in user.get("level_rewards_claimed", [])]
            restored += 1
        except (ValueError, TypeError):
            continue
    snapshot_income = latest.get("income_roles")
    if isinstance(snapshot_income, dict):
        economy_income_roles[guild.id] = {int(r): cfg for r, cfg in snapshot_income.items()}
    snapshot_ach = latest.get("achievement_users")
    if isinstance(snapshot_ach, dict):
        for uid_text, progress in snapshot_ach.items():
            try:
                achievement_data[(guild.id, int(uid_text))] = progress
            except (ValueError, TypeError):
                continue
    snapshot_ach_defs = latest.get("achievement_definitions")
    if isinstance(snapshot_ach_defs, dict):
        achievement_defs[guild.id] = snapshot_ach_defs
    snapshot_ach_roles = latest.get("achievement_roles")
    if isinstance(snapshot_ach_roles, dict):
        achievement_roles[guild.id] = {str(a): int(r) for a, r in snapshot_ach_roles.items()}
    snapshot_ach_cfg = latest.get("achievement_config")
    if isinstance(snapshot_ach_cfg, dict):
        achievement_config[guild.id] = snapshot_ach_cfg
    snapshot_items = latest.get("items")
    if isinstance(snapshot_items, dict):
        ECONOMY_ITEMS.clear()
        for item_id, item in snapshot_items.items():
            if isinstance(item, dict):
                ECONOMY_ITEMS[str(item_id)] = {
                    "name": str(item.get("name", item_id))[:80],
                    "price": max(1, int(item.get("price", 1))),
                    "emoji": str(item.get("emoji", "🐾"))[:8],
                    "description": str(item.get("description", ""))[:300],
                    "max_per_person": max(0, int(item.get("max_per_person", 0))),
                }
    await bd_save_data()
    created = latest.get("created_at", "unknown time")
    return restored, created


@economy_group.command(name="addcatnip", description="Admin: add Catnip to a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def economy_addcatnip_cmd(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 10000000]):
    guild_id = interaction.guild.id
    economy_balances[(guild_id, member.id)] = economy_balance(guild_id, member.id) + amount
    await achievement_record(guild_id, member.id, metric_updates={"lifetime_earned": amount}, member=member)
    await quest_record_event(guild_id, member.id, "earned", amount, member=member)
    await bd_save_data()
    await economy_log(guild_id, title="🛠️ Admin Catnip added", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Amount", f"+{amount:,} Catnip")])
    await interaction.response.send_message(f"✅ Added **{amount:,} Catnip** to {member.mention}. New balance: **{economy_balance(guild_id, member.id):,}**.", ephemeral=True)


@economy_group.command(name="removecatnip", description="Admin: remove Catnip from a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def economy_removecatnip_cmd(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 10000000]):
    guild_id = interaction.guild.id
    current = economy_balance(guild_id, member.id)
    removed = min(current, amount)
    economy_balances[(guild_id, member.id)] = current - removed
    await bd_save_data()
    await economy_log(guild_id, title="🛠️ Admin Catnip removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Amount", f"-{removed:,} Catnip")])
    await interaction.response.send_message(f"✅ Removed **{removed:,} Catnip** from {member.mention}. New balance: **{economy_balance(guild_id, member.id):,}**.", ephemeral=True)


@economy_group.command(name="income", description="Admin: manage Catnip income roles")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(action="add, remove, or list", role="Role that earns Catnip", amount="Catnip paid each collection", minutes="Cooldown in minutes")
@app_commands.choices(action=[app_commands.Choice(name="add", value="add"), app_commands.Choice(name="remove", value="remove"), app_commands.Choice(name="list", value="list")])
async def economy_income_cmd(interaction: discord.Interaction, action: app_commands.Choice[str], role: discord.Role | None = None, amount: app_commands.Range[int, 1, 10000000] | None = None, minutes: app_commands.Range[int, 1, 10080] | None = None):
    guild_id = interaction.guild.id
    cfg = economy_income_roles.setdefault(guild_id, {})
    if action.value == "list":
        embed = discord.Embed(title="💰 Catnip income roles", description=economy_income_role_lines(interaction.guild), color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if role is None:
        await interaction.response.send_message("❌ Choose a role.", ephemeral=True)
        return
    if action.value == "remove":
        removed = cfg.pop(role.id, None)
        await bd_save_data()
        await interaction.response.send_message(f"🗑️ Removed {role.mention} from Catnip income roles." if removed else f"ℹ️ {role.mention} was not an income role.", ephemeral=True)
        return
    if amount is None or minutes is None:
        await interaction.response.send_message("❌ For `add`, provide both `amount` and `minutes`.", ephemeral=True)
        return
    cfg[role.id] = {"amount": int(amount), "cooldown": int(minutes) * 60}
    await bd_save_data()
    await economy_log(guild_id, title="💰 Income role configured", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Role", role.name), ("Income", f"{amount:,} Catnip / {minutes} min")])
    await interaction.response.send_message(f"✅ {role.mention} now earns **{amount:,} Catnip every {minutes} minutes** when members use `/collect`.", ephemeral=True)


async def economy_collect(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    configs = economy_income_roles.get(guild_id, {})
    if not configs:
        await interaction.response.send_message("ℹ️ This server has no income roles configured yet.", ephemeral=True)
        return
    total = 0
    collected = []
    now = time.time()
    for role in interaction.user.roles:
        data = configs.get(role.id)
        if not data:
            continue
        action = f"income:{role.id}"
        remaining = economy_cooldown_remaining(guild_id, interaction.user.id, action)
        if remaining:
            continue
        amount = int(data.get("amount", 0))
        cooldown = int(data.get("cooldown", 3600))
        if amount <= 0:
            continue
        economy_cooldowns[(guild_id, interaction.user.id, action)] = now + cooldown
        total += amount
        collected.append(f"{role.name}: +{amount:,}")
    if not collected:
        await interaction.response.send_message("⏳ None of your income roles are ready to collect yet.", ephemeral=True)
        return
    economy_balances[(guild_id, interaction.user.id)] = economy_balance(guild_id, interaction.user.id) + total
    await achievement_record(guild_id, interaction.user.id, metric_updates={"lifetime_earned": total}, member=interaction.user)
    await quest_record_event(guild_id, interaction.user.id, "earned", total, member=interaction.user)
    await bd_save_data()
    await economy_log(guild_id, title="💰 Income collected", fields=[("User", f"{interaction.user} ({interaction.user.id})"), ("Total", f"+{total:,} Catnip"), ("Sources", "\n".join(collected))])
    await interaction.response.send_message(f"💰 You collected **{total:,} Catnip**!\n" + "\n".join(f"• {x}" for x in collected))


@economy_group.command(name="collect", description="Collect Catnip from all income roles you have")
@app_commands.guild_only()
async def economy_collect_cmd(interaction: discord.Interaction):
    await economy_collect(interaction)


@bot.tree.command(name="collect", description="Collect Catnip from all income roles you have")
@app_commands.guild_only()
async def collect_cmd(interaction: discord.Interaction):
    await economy_collect(interaction)


@economy_group.command(name="item-add", description="Admin: add an item directly to a member's inventory")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(member="Member receiving the item", item="Item ID or item name", quantity="Number of items to add")
async def economy_item_add_cmd(interaction: discord.Interaction, member: discord.Member, item: str, quantity: app_commands.Range[int, 1, 999] = 1):
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await interaction.response.send_message("❌ That item doesn't exist. Use `/economy shop` first.", ephemeral=True)
        return
    inv = economy_inventory_for(interaction.guild.id, member.id)
    max_per_person = int(data.get("max_per_person", 0))
    current = int(inv.get(item_id, 0))
    if max_per_person and current + quantity > max_per_person:
        await interaction.response.send_message(f"❌ {member.mention} cannot hold more than **{max_per_person}** of this item.", ephemeral=True)
        return
    inv[item_id] = current + quantity
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🛠️ Admin item added", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Item", data["name"]), ("Quantity", f"+{quantity}")])
    await interaction.response.send_message(f"✅ Added **{quantity}× {data['emoji']} {data['name']}** to {member.mention}.", ephemeral=True)


@economy_group.command(name="item-remove", description="Admin: remove an item from a member's inventory")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(member="Member losing the item", item="Item ID or item name", quantity="Number of items to remove")
async def economy_item_remove_cmd(interaction: discord.Interaction, member: discord.Member, item: str, quantity: app_commands.Range[int, 1, 999] = 1):
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await interaction.response.send_message("❌ That item doesn't exist.", ephemeral=True)
        return
    inv = economy_inventory_for(interaction.guild.id, member.id)
    current = int(inv.get(item_id, 0))
    removed = min(current, quantity)
    if removed <= 0:
        await interaction.response.send_message(f"❌ {member.mention} doesn't have that item.", ephemeral=True)
        return
    inv[item_id] = current - removed
    if inv[item_id] <= 0:
        inv.pop(item_id, None)
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🛠️ Admin item removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Member", f"{member} ({member.id})"), ("Item", data["name"]), ("Quantity", f"-{removed}")])
    await interaction.response.send_message(f"✅ Removed **{removed}× {data['emoji']} {data['name']}** from {member.mention}.", ephemeral=True)


@economy_group.command(name="add-item-shop", description="Admin: add an item to the Catnip shop")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(item_id="Unique shop ID", name="Item name", price="Price in Catnip", description="Optional item description", per_person_limit="Optional maximum quantity one member can own", emoji="Optional emoji")
async def economy_add_item_shop_cmd(interaction: discord.Interaction, item_id: str, name: str, price: app_commands.Range[int, 1, 10000000], description: str | None = None, per_person_limit: app_commands.Range[int, 0, 999999] | None = None, emoji: str = "🐾"):
    item_id = re.sub(r"[^a-z0-9_-]", "", item_id.lower())[:32]
    if not item_id or item_id in ECONOMY_ITEMS:
        await interaction.response.send_message("❌ That item ID is invalid or already exists.", ephemeral=True)
        return
    ECONOMY_ITEMS[item_id] = {"name": name[:80], "price": int(price), "emoji": emoji[:8], "description": (description or "No description provided.")[:300], "max_per_person": int(per_person_limit or 0)}
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🛒 Shop item added", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Item", f"{emoji} {name}"), ("ID", item_id), ("Price", f"{price:,} Catnip"), ("Per-person limit", per_person_limit or "Unlimited")])
    await interaction.response.send_message(f"✅ Added **{emoji} {name}** (`{item_id}`) to the shop.", ephemeral=True)


@economy_group.command(name="edit-shop-item", description="Admin: edit a Catnip shop item")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(item_id="Item ID to edit", name="New name", price="New price", description="New description", per_person_limit="New per-person limit; 0 means unlimited", emoji="New emoji")
async def economy_edit_shop_item_cmd(interaction: discord.Interaction, item_id: str, name: str | None = None, price: app_commands.Range[int, 1, 10000000] | None = None, description: str | None = None, per_person_limit: app_commands.Range[int, 0, 999999] | None = None, emoji: str | None = None):
    item_id = item_id.lower().strip()
    item = ECONOMY_ITEMS.get(item_id)
    if item is None:
        await interaction.response.send_message("❌ That shop item doesn't exist.", ephemeral=True)
        return
    if all(x is None for x in (name, price, description, per_person_limit, emoji)):
        await interaction.response.send_message("❌ Choose at least one property to edit.", ephemeral=True)
        return
    if name is not None: item["name"] = name[:80]
    if price is not None: item["price"] = int(price)
    if description is not None: item["description"] = description[:300]
    if per_person_limit is not None: item["max_per_person"] = int(per_person_limit)
    if emoji is not None: item["emoji"] = emoji[:8]
    await bd_save_data()
    await economy_log(interaction.guild.id, title="✏️ Shop item edited", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Item ID", item_id), ("New name", item["name"]), ("New price", f"{item['price']:,} Catnip"), ("Per-person limit", item.get("max_per_person", 0) or "Unlimited")])
    await interaction.response.send_message(f"✅ Updated **{item['emoji']} {item['name']}** (`{item_id}`).", ephemeral=True)


@economy_group.command(name="remove-item-shop", description="Admin: remove an item from the Catnip shop")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(item_id="Item ID to remove", remove_from_inventories="Whether all copies should also be removed from member inventories")
async def economy_remove_item_shop_cmd(interaction: discord.Interaction, item_id: str, remove_from_inventories: bool = False):
    guild_id = interaction.guild.id
    item_id = item_id.lower().strip()
    item = ECONOMY_ITEMS.get(item_id)
    if item is None:
        await interaction.response.send_message("❌ That shop item doesn't exist.", ephemeral=True)
        return
    removed_inventory = 0
    if remove_from_inventories:
        for (gid, uid), inv in economy_inventory.items():
            if gid == guild_id and item_id in inv:
                removed_inventory += int(inv.pop(item_id, 0))
    ECONOMY_ITEMS.pop(item_id, None)
    await bd_save_data()
    await economy_log(guild_id, title="🗑️ Shop item removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Item", f"{item['emoji']} {item['name']}"), ("ID", item_id), ("Inventory copies removed", removed_inventory), ("Removed from inventories", remove_from_inventories)])
    await interaction.response.send_message(f"🗑️ Removed **{item['name']}** from the shop. " + (f"Also removed **{removed_inventory}** copies from inventories." if remove_from_inventories else "Existing inventory copies were kept."), ephemeral=True)


@economy_group.command(name="add-role-income", description="Admin: give a role a recurring Catnip income")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(role="Role receiving the income", amount="Catnip earned each collection", interval="How many time units between collections", unit="Time unit")
@app_commands.choices(unit=[app_commands.Choice(name="Minutes", value="minute"), app_commands.Choice(name="Hours", value="hour"), app_commands.Choice(name="Days", value="day"), app_commands.Choice(name="Weeks", value="week")])
async def economy_add_role_income_cmd(interaction: discord.Interaction, role: discord.Role, amount: app_commands.Range[int, 1, 10000000], interval: app_commands.Range[int, 1, 10080], unit: app_commands.Choice[str]):
    multipliers = {"minute": 60, "hour": 3600, "day": 86400, "week": 604800}
    cooldown = int(interval) * multipliers[unit.value]
    economy_income_roles.setdefault(interaction.guild.id, {})[role.id] = {"amount": int(amount), "cooldown": cooldown, "interval": int(interval), "unit": unit.value}
    await bd_save_data()
    await economy_log(interaction.guild.id, title="💰 Role income added/updated", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Role", f"{role} ({role.id})"), ("Income", f"{amount:,} Catnip / {interval} {unit.name.lower()}")])
    await interaction.response.send_message(f"✅ {role.mention} now provides **{amount:,} Catnip every {interval} {unit.name.lower()}** via `/collect`.", ephemeral=True)


@economy_group.command(name="remove-role-income", description="Admin: remove a role's recurring Catnip income")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(role="Role whose income should be removed")
async def economy_remove_role_income_cmd(interaction: discord.Interaction, role: discord.Role):
    cfg = economy_income_roles.setdefault(interaction.guild.id, {})
    removed = cfg.pop(role.id, None)
    await bd_save_data()
    await economy_log(interaction.guild.id, title="🗑️ Role income removed", fields=[("Admin", f"{interaction.user} ({interaction.user.id})"), ("Role", f"{role} ({role.id})"), ("Was configured", bool(removed))])
    await interaction.response.send_message(f"🗑️ Removed {role.mention} from recurring Catnip income." if removed else f"ℹ️ {role.mention} wasn't configured for income.", ephemeral=True)


@economy_group.command(name="iteminfo", description="Show complete information about a Catnip item")
@app_commands.guild_only()
@app_commands.describe(item="Item ID or item name")
async def economy_iteminfo_cmd(interaction: discord.Interaction, item: str):
    item_id = item.lower().strip()
    if item_id not in ECONOMY_ITEMS:
        matches = [k for k, v in ECONOMY_ITEMS.items() if v["name"].lower() == item_id]
        if len(matches) == 1:
            item_id = matches[0]
    data = ECONOMY_ITEMS.get(item_id)
    if data is None:
        await interaction.response.send_message("❌ That item doesn't exist. Use `/economy shop` to see the item IDs.", ephemeral=True)
        return
    limit = int(data.get("max_per_person", 0))
    embed = discord.Embed(title=f"{data['emoji']} {data['name']}", description=data["description"], color=discord.Color.gold())
    embed.add_field(name="Item ID", value=f"`{item_id}`", inline=True)
    embed.add_field(name="Price", value=f"{data['price']:,} Catnip", inline=True)
    embed.add_field(name="Per-person limit", value=str(limit) if limit else "Unlimited", inline=True)
    await interaction.response.send_message(embed=embed)
    await economy_log(interaction.guild.id, title="🔎 Economy item info viewed", fields=[("Viewer", f"{interaction.user} ({interaction.user.id})"), ("Item", f"{data['name']} (`{item_id}`)")])


@economy_group.command(name="recover", description="Restore the latest complete economy snapshot from the economy log channel")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def economy_recover_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    restored, detail = await economy_restore_from_snapshot(interaction.guild)
    if restored <= 0:
        await interaction.followup.send(f"⚠️ Economy recovery did not restore any users. {detail}", ephemeral=True)
        return
    await economy_log(interaction.guild.id, title="🩹 Economy restored", description=f"Restored {restored} user account(s) from the latest snapshot.", fields=[("Snapshot", detail), ("Restored users", restored)])
    await interaction.followup.send(f"🩹 Economy recovery complete. Restored **{restored}** user account(s) from the latest snapshot (**{detail}**).", ephemeral=True)


bot.tree.add_command(economy_group)


# ---------------------------------------------------------------------------
# Daily / Weekly Quests — server-wide active pools + individual progress
# ---------------------------------------------------------------------------

quests_group = app_commands.Group(name="quests", description="Cinnamon's daily, weekly, and Quest Point system")


async def _quest_require_setup(interaction: discord.Interaction) -> bool:
    if not quest_setup_ready(interaction.guild.id):
        await interaction.response.send_message(
            "🐾 Cinnamon's quest board isn't set up yet. An administrator needs to run **/quests setup** first.",
            ephemeral=True,
        )
        return False
    return True


@quests_group.command(name="setup", description="Admin: set up the complete daily and weekly quest system")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.bot_has_permissions(manage_channels=True, send_messages=True, embed_links=True)
async def quests_setup_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        cfg = await quest_setup_guild(interaction.guild)
        daily = _quest_cycle_config(interaction.guild.id, "daily")
        weekly = _quest_cycle_config(interaction.guild.id, "weekly")
        await interaction.followup.send(
            "🎯 **Cinnamon's Quest System is ready!**\n"
            f"• Daily pool: **{len(quest_definitions['daily'])}** quests\n"
            f"• Weekly pool: **{len(quest_definitions['weekly'])}** quests\n"
            f"• Active daily quests: **{len(daily['active'])}/5**\n"
            f"• Active weekly quests: **{len(weekly['active'])}/5**\n"
            f"• Quest Points: **enabled**\n"
            f"• Quest log: {cfg['log_channel_id'] and f'<#{cfg["log_channel_id"]}>'}\n\n"
            "The same 5 daily and 5 weekly quests are shown to everyone in this server. Each member has separate progress.",
            ephemeral=True,
        )
    except discord.Forbidden:
        await interaction.followup.send("🐱🚫 I couldn't create the quest setup channel. Give Cinnamon **Manage Channels** and **Send Messages** permissions.", ephemeral=True)
    except discord.HTTPException:
        await interaction.followup.send("🐱💥 Cinnamon tripped over the quest board while setting it up. Please try `/quests setup` again.", ephemeral=True)


@quests_group.command(name="setup-status", description="Check the quest system setup and current cycles")
@app_commands.guild_only()
async def quests_setup_status_cmd(interaction: discord.Interaction):
    cfg = quest_config.get(interaction.guild.id, {})
    if not cfg.get("enabled"):
        await interaction.response.send_message("🎯 Quest system: **Not set up**\nRun `/quests setup` as an administrator.", ephemeral=True)
        return
    daily = _quest_cycle_config(interaction.guild.id, "daily")
    weekly = _quest_cycle_config(interaction.guild.id, "weekly")
    await interaction.response.send_message(
        f"🎯 **Quest System Status**\n• Daily: **{len(daily.get('active', []))}/5 active** — resets <t:{int(daily['ends_at'])}:R>\n"
        f"• Weekly: **{len(weekly.get('active', []))}/5 active** — resets <t:{int(weekly['ends_at'])}:R>\n"
        f"• Daily pool: **{len(quest_definitions['daily'])}**\n• Weekly pool: **{len(quest_definitions['weekly'])}**\n"
        f"• Quest log: <#{cfg.get('log_channel_id')}>" if cfg.get('log_channel_id') else "• Quest log: not configured",
        ephemeral=True,
    )


@quests_group.command(name="daily", description="View the 5 active daily quests")
@app_commands.guild_only()
async def quests_daily_cmd(interaction: discord.Interaction):
    if not await _quest_require_setup(interaction): return
    cycle = _quest_cycle_config(interaction.guild.id, "daily")
    pdata = quest_user_progress(interaction.guild.id, interaction.user.id)["daily"]
    lines=[]
    for qid in cycle["active"]:
        state=pdata.get(qid,{})
        lines.append(quest_display("daily", qid, state, bool(state.get("completed"))))
    e=cinnamon_embed(title="🌅 Cinnamon's Daily Quests", description="\n\n".join(lines), color=0x57F287, guild=interaction.guild, footer="Cinnamon • Daily quests")
    e.set_footer(text=f"Resets in {max(0,int(cycle['ends_at']-time.time()))//3600}h • The 5 quests are server-wide")
    await interaction.response.send_message(embed=e)


@quests_group.command(name="weekly", description="View the 5 active weekly quests")
@app_commands.guild_only()
async def quests_weekly_cmd(interaction: discord.Interaction):
    if not await _quest_require_setup(interaction): return
    cycle = _quest_cycle_config(interaction.guild.id, "weekly")
    pdata = quest_user_progress(interaction.guild.id, interaction.user.id)["weekly"]
    lines=[]
    for qid in cycle["active"]:
        state=pdata.get(qid,{})
        lines.append(quest_display("weekly", qid, state, bool(state.get("completed"))))
    e=cinnamon_embed(title="📅 Cinnamon's Weekly Quests", description="\n\n".join(lines), color=0xF0A44B, guild=interaction.guild, footer="Cinnamon • Weekly quests")
    e.set_footer(text=f"Resets in {max(0,int(cycle['ends_at']-time.time()))//86400}d • The 5 quests are server-wide")
    await interaction.response.send_message(embed=e)


@quests_group.command(name="progress", description="View your daily and weekly quest progress")
@app_commands.guild_only()
async def quests_progress_cmd(interaction: discord.Interaction):
    if not await _quest_require_setup(interaction): return
    daily = _quest_cycle_config(interaction.guild.id, "daily"); weekly = _quest_cycle_config(interaction.guild.id, "weekly")
    pdata = quest_user_progress(interaction.guild.id, interaction.user.id)
    def block(kind, cycle):
        lines=[]
        for qid in cycle["active"]:
            state=pdata[kind].get(qid,{})
            lines.append(quest_display(kind,qid,state,bool(state.get("completed"))))
        return "\n\n".join(lines) or "None."
    e=cinnamon_embed(title=f"🎯 {interaction.user.display_name}'s Quest Progress", color=0x8E7CFF, guild=interaction.guild, footer="Cinnamon • Quest progress")
    e.add_field(name="🌅 Daily", value=block("daily",daily)[:1024], inline=False)
    e.add_field(name="📅 Weekly", value=block("weekly",weekly)[:1024], inline=False)
    e.add_field(name="✨ Quest Points", value=f"**{quest_points_for(interaction.guild.id, interaction.user.id):,} QP**", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)


@quests_group.command(name="points", description="View your Quest Points")
@app_commands.guild_only()
async def quests_points_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    member = member or interaction.user
    await interaction.response.send_message(f"✨ {member.mention} has **{quest_points_for(interaction.guild.id, member.id):,} Quest Points**.", allowed_mentions=discord.AllowedMentions(users=True))


@quests_group.command(name="shop", description="View the Quest Point redemption shop")
@app_commands.guild_only()
async def quests_shop_cmd(interaction: discord.Interaction):
    lines=[f"**{k}** — {v['description']} — **{v['cost']} QP**" for k,v in QUEST_SHOP.items()]
    e=cinnamon_embed(title="✨ Quest Point Shop", description="\n".join(lines), color=0xFEE75C, guild=interaction.guild, footer="Cinnamon • Quest Points")
    e.set_footer(text="QP are spendable. Achievement Points are separate and cannot be spent here.")
    await interaction.response.send_message(embed=e)


@quests_group.command(name="redeem", description="Redeem Quest Points for Catnip or XP")
@app_commands.describe(reward="Quest Point shop reward ID shown by /quests shop")
@app_commands.guild_only()
async def quests_redeem_cmd(interaction: discord.Interaction, reward: str):
    reward = reward.lower().strip()
    item = QUEST_SHOP.get(reward)
    if not item:
        await interaction.response.send_message("🐱🔎 Cinnamon can't find that reward. Use **/quests shop** and copy the reward ID exactly.", ephemeral=True)
        return
    guild_id,user_id=interaction.guild.id,interaction.user.id
    points=quest_points_for(guild_id,user_id)
    if points < item["cost"]:
        await interaction.response.send_message(f"❌ You need **{item['cost']:,} QP**, but you only have **{points:,} QP**.", ephemeral=True)
        return
    quest_points[(guild_id,user_id)] = points-item["cost"]
    if item["type"] == "catnip":
        economy_balances[(guild_id,user_id)] = economy_balance(guild_id,user_id)+item["amount"]
        await achievement_record(guild_id,user_id,metric_updates={"lifetime_earned":item["amount"]},member=interaction.user)
        result=f"🌿 **+{item['amount']:,} Catnip**"
    else:
        old_xp = int(xp_data.get((guild_id,user_id),0))
        old_level = level_from_xp(old_xp)
        xp_data[(guild_id,user_id)] = old_xp + item["amount"]
        new_level = level_from_xp(xp_data[(guild_id,user_id)])
        if new_level > old_level:
            await achievement_record(guild_id,user_id,metric_updates={"levels":new_level-old_level},member=interaction.user)
            await quest_record_event(guild_id,user_id,"levels",new_level-old_level,member=interaction.user)
        await quest_record_event(guild_id,user_id,"xp",item["amount"],member=interaction.user)
        await sync_level_roles(interaction.user,new_level)
        result=f"⭐ **+{item['amount']:,} XP**"
    await bd_save_data()
    await quest_log(guild_id,title="🛍️ Quest Point redemption",fields=[("Member",f"{interaction.user} ({user_id})"),("Reward",item["name"]),("Spent",f"{item['cost']} QP")])
    await interaction.response.send_message(f"✨ Redeemed **{item['cost']} QP** for {result}! You now have **{quest_points_for(guild_id,user_id):,} QP**.")


@quests_group.command(name="history", description="View your recently completed quests")
@app_commands.guild_only()
async def quests_history_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    member=member or interaction.user
    rows=quest_history.get((interaction.guild.id,member.id),[])[-15:]
    if not rows:
        await interaction.response.send_message(f"📜 {member.display_name} has no recorded quest completions yet.",ephemeral=True); return
    lines=[f"• **{r['name']}** ({r['kind']}) — +{r['qp']} QP — <t:{int(datetime.datetime.fromisoformat(r['completed_at']).timestamp())}:R>" for r in reversed(rows)]
    e=cinnamon_embed(title=f"📜 {member.display_name}'s Quest History", description="\n".join(lines), color=0x5865F2, guild=interaction.guild, footer="Cinnamon • Quest history")
    await interaction.response.send_message(embed=e, ephemeral=True)


@quests_group.command(name="reroll", description="Admin: randomly select a new set of 5 quests")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_reroll_cmd(interaction: discord.Interaction, pool: app_commands.Choice[str]):
    if pool.value not in ("daily","weekly"):
        await interaction.response.send_message("❌ Choose daily or weekly.",ephemeral=True); return
    if not quest_setup_ready(interaction.guild.id): await quest_setup_guild(interaction.guild)
    kind=pool.value; now=time.time(); duration=QUEST_DAILY_SECONDS if kind=="daily" else QUEST_WEEKLY_SECONDS
    cfg=quest_config[interaction.guild.id][kind]; cfg.clear(); cfg.update({"started_at":now,"ends_at":now+duration,"cycle_id":quest_cycle_id(kind,now),"active":_quest_pick(kind)})
    _quest_clear_guild_progress(interaction.guild.id,kind)
    await bd_save_data(); await quest_log(interaction.guild.id,title="🎲 Quest pool rerolled",fields=[("Admin",str(interaction.user)),("Pool",kind),("Active",len(cfg['active']))])
    await interaction.response.send_message(f"🎲 **{kind.title()}** quest pool rerolled. Everyone now has the same new 5 quests.",ephemeral=True)


@quests_group.command(name="user", description="Admin: inspect a member's Quest Points and active progress")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_user_cmd(interaction: discord.Interaction, member: discord.Member):
    if not await _quest_require_setup(interaction): return
    pdata=quest_user_progress(interaction.guild.id,member.id)
    await interaction.response.send_message(f"🎯 **{member.display_name}**\n• QP: **{quest_points_for(interaction.guild.id,member.id):,}**\n• Daily tracked quests: **{len(pdata['daily'])}**\n• Weekly tracked quests: **{len(pdata['weekly'])}**\n• Completed history: **{len(quest_history.get((interaction.guild.id,member.id),[]))}**",ephemeral=True)


@quests_group.command(name="award", description="Admin: award Quest Points to a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_award_cmd(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int,1,1000000]):
    key=(interaction.guild.id,member.id); quest_points[key]=quest_points_for(*key)+int(amount); await bd_save_data(); await quest_log(interaction.guild.id,title="🛠️ Quest Points awarded",fields=[("Admin",str(interaction.user)),("Member",str(member)),("Amount",f"+{amount} QP")]); await interaction.response.send_message(f"✨ Awarded **{amount:,} QP** to {member.mention}.",ephemeral=True)


@quests_group.command(name="revoke", description="Admin: remove Quest Points from a member")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_revoke_cmd(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int,1,1000000]):
    key=(interaction.guild.id,member.id); removed=min(quest_points_for(*key),int(amount)); quest_points[key]=quest_points_for(*key)-removed; await bd_save_data(); await quest_log(interaction.guild.id,title="🛠️ Quest Points revoked",fields=[("Admin",str(interaction.user)),("Member",str(member)),("Amount",f"-{removed} QP")]); await interaction.response.send_message(f"🗑️ Removed **{removed:,} QP** from {member.mention}.",ephemeral=True)


@quests_group.command(name="stats", description="Admin: view quest system statistics")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_stats_cmd(interaction: discord.Interaction):
    gid=interaction.guild.id; users=len({uid for g,uid in quest_points if g==gid}); total=sum(v for (g,_),v in quest_points.items() if g==gid); completed=sum(len(v) for (g,_),v in quest_history.items() if g==gid); cfg=quest_config.get(gid,{})
    await interaction.response.send_message(f"📊 **Quest Stats**\n• Daily definitions: **{len(quest_definitions['daily'])}**\n• Weekly definitions: **{len(quest_definitions['weekly'])}**\n• Members with QP: **{users}**\n• Unspent QP: **{total:,}**\n• Recorded completions: **{completed}**\n• Enabled: **{bool(cfg.get('enabled'))}**",ephemeral=True)


@quests_group.command(name="create", description="Admin: create a custom quest in the daily or weekly pool")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_create_cmd(interaction: discord.Interaction, pool: app_commands.Choice[str], name: str, description: str, qp: app_commands.Range[int,1,10000], metric: str, amount: app_commands.Range[int,1,100000]):
    kind=pool.value; metric=metric.lower().strip()
    allowed={"messages","cinnamon","feed","earned","buy","spent","work","xp","levels","items:tuna","items:treat","items:churu","items:catnip_ball","items:fish"}
    if metric not in allowed:
        await interaction.response.send_message("❌ Unsupported metric. Use messages, cinnamon, feed, earned, buy, spent, work, xp, levels, or an items:<item_id> metric.",ephemeral=True); return
    prefix='d' if kind=='daily' else 'w'; ids=quest_definitions[kind]; n=1
    while f"{prefix}custom{n}" in ids: n+=1
    qid=f"{prefix}custom{n}"; ids[qid]=_quest(qid,name,{metric:int(amount)},int(qp),description)
    await bd_save_data(); await quest_log(interaction.guild.id,title="🛠️ Custom quest created",fields=[("Admin",str(interaction.user)),("Pool",kind),("Quest",f"{name} (`{qid}`)"),("Objective",f"{metric} × {amount}")]); await interaction.response.send_message(f"✅ Created **{name}** as `{qid}` in the {kind} pool.",ephemeral=True)



@quests_group.command(name="edit", description="Admin: edit a quest name, description, or QP reward")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_edit_cmd(interaction: discord.Interaction, pool: app_commands.Choice[str], quest_id: str, name: str | None = None, description: str | None = None, qp: app_commands.Range[int,1,10000] | None = None):
    q=quest_definitions[pool.value].get(quest_id.lower().strip())
    if not q:
        await interaction.response.send_message("❌ Quest ID not found.",ephemeral=True); return
    if name is not None: q["name"]=name[:100]
    if description is not None: q["description"]=description[:500]
    if qp is not None: q["qp"]=int(qp)
    await bd_save_data(); await quest_log(interaction.guild.id,title="✏️ Quest edited",fields=[("Admin",str(interaction.user)),("Pool",pool.value),("Quest",f"{q['name']} (`{q['id']}`)")])
    await interaction.response.send_message(f"✏️ Updated **{q['name']}** (`{q['id']}`).",ephemeral=True)


@quests_group.command(name="disable-system", description="Admin: disable the quest system")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_disable_system_cmd(interaction: discord.Interaction):
    if interaction.guild.id not in quest_config:
        await interaction.response.send_message("ℹ️ The quest system is already disabled/not set up.",ephemeral=True); return
    quest_config[interaction.guild.id]["enabled"]=False; await bd_save_data(); await interaction.response.send_message("⏸️ Cinnamon's quest system is disabled. Existing QP is preserved.",ephemeral=True)


@quests_group.command(name="delete", description="Admin: delete a quest definition")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_delete_cmd(interaction: discord.Interaction, pool: app_commands.Choice[str], quest_id: str):
    q=quest_definitions[pool.value].pop(quest_id.lower().strip(),None)
    if not q: await interaction.response.send_message("❌ Quest ID not found.",ephemeral=True); return
    for cfg in quest_config.values():
        for kind in ('daily','weekly'):
            if quest_id in cfg.get(kind,{}).get('active',[]): cfg[kind]['active'].remove(quest_id)
    await bd_save_data(); await interaction.response.send_message(f"🗑️ Deleted **{q['name']}** (`{quest_id}`).",ephemeral=True)


@quests_group.command(name="enable", description="Admin: enable a quest definition")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_enable_cmd(interaction: discord.Interaction, pool: app_commands.Choice[str], quest_id: str):
    q=quest_definitions[pool.value].get(quest_id.lower().strip())
    if not q: await interaction.response.send_message("❌ Quest ID not found.",ephemeral=True); return
    q['enabled']=True; await bd_save_data(); await interaction.response.send_message(f"✅ Enabled **{q['name']}**.",ephemeral=True)


@quests_group.command(name="disable", description="Admin: disable a quest definition")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_disable_cmd(interaction: discord.Interaction, pool: app_commands.Choice[str], quest_id: str):
    q=quest_definitions[pool.value].get(quest_id.lower().strip())
    if not q: await interaction.response.send_message("❌ Quest ID not found.",ephemeral=True); return
    q['enabled']=False
    for cfg in quest_config.values():
        if quest_id in cfg.get(pool.value,{}).get('active',[]): cfg[pool.value]['active'].remove(quest_id)
    await bd_save_data(); await interaction.response.send_message(f"⏸️ Disabled **{q['name']}**.",ephemeral=True)


@quests_group.command(name="backup", description="Admin: create a complete quest backup")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_backup_cmd(interaction: discord.Interaction):
    payload={"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"definitions":quest_definitions,"config":quest_config,"points":{f"{g}:{u}":v for (g,u),v in quest_points.items() if g==interaction.guild.id},"progress":{f"{g}:{u}":v for (g,u),v in quest_progress.items() if g==interaction.guild.id},"history":{f"{g}:{u}":v for (g,u),v in quest_history.items() if g==interaction.guild.id},"shop":QUEST_SHOP}
    raw=json.dumps(payload,ensure_ascii=False,indent=2).encode('utf-8'); file=discord.File(io.BytesIO(raw),filename=f"cinnamon_quests_{interaction.guild.id}.json")
    await quest_log(interaction.guild.id,title="💾 Quest backup",fields=[("Admin",str(interaction.user)),("Daily definitions",len(quest_definitions['daily'])),("Weekly definitions",len(quest_definitions['weekly']))])
    await interaction.response.send_message("💾 Quest backup created.",file=file,ephemeral=True)


@quests_group.command(name="recover", description="Admin: reload quest data from persistent storage")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_recover_cmd(interaction: discord.Interaction):
    await bd_load_data(); await interaction.response.send_message("🩹 Quest data reloaded from persistent storage.",ephemeral=True)


@quests_group.command(name="shop-add", description="Admin: add a custom QP shop reward")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_shop_add_cmd(interaction: discord.Interaction, reward_id: str, name: str, cost: app_commands.Range[int,1,1000000], reward_type: app_commands.Choice[str], amount: app_commands.Range[int,1,100000000]):
    rid=reward_id.lower().strip()
    rtype=reward_type.value.lower().strip()
    if rtype not in ("catnip","xp"):
        await interaction.response.send_message("❌ Reward type must be `catnip` or `xp`.",ephemeral=True); return
    if rid in QUEST_SHOP: await interaction.response.send_message("❌ That reward ID already exists.",ephemeral=True); return
    QUEST_SHOP[rid]={"name":name,"cost":int(cost),"type":rtype,"amount":int(amount),"description":f"Redeem {cost} QP for {amount:,} {rtype}."}
    await bd_save_data(); await interaction.response.send_message(f"✅ Added **{name}** to the QP shop as `{rid}`.",ephemeral=True)



@quests_group.command(name="shop-edit", description="Admin: edit a QP shop reward")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_shop_edit_cmd(interaction: discord.Interaction, reward_id: str, name: str | None = None, cost: app_commands.Range[int,1,1000000] | None = None, amount: app_commands.Range[int,1,100000000] | None = None):
    item=QUEST_SHOP.get(reward_id.lower().strip())
    if not item:
        await interaction.response.send_message("❌ Reward ID not found.",ephemeral=True); return
    if name is not None: item["name"]=name[:100]
    if cost is not None: item["cost"]=int(cost)
    if amount is not None: item["amount"]=int(amount)
    item["description"]=f"Redeem {item['cost']} QP for {item['amount']:,} {item['type']}."
    await bd_save_data(); await interaction.response.send_message(f"✏️ Updated QP shop reward **{item['name']}** (`{reward_id}`).",ephemeral=True)


@quests_group.command(name="shop-remove", description="Admin: remove a QP shop reward")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def quests_shop_remove_cmd(interaction: discord.Interaction, reward_id: str):
    if reward_id not in QUEST_SHOP: await interaction.response.send_message("❌ Reward ID not found.",ephemeral=True); return
    item=QUEST_SHOP.pop(reward_id); await bd_save_data(); await interaction.response.send_message(f"🗑️ Removed **{item['name']}** from the QP shop.",ephemeral=True)


# Choices are assigned after definitions so the same strings are reused everywhere.
for _cmd in (quests_reroll_cmd, quests_create_cmd, quests_delete_cmd, quests_enable_cmd, quests_disable_cmd, quests_list_cmd):
    pass
# Re-declare choices through the command decorators' expected parameters using
# static choices on the function annotations is not possible after registration;
# Discord accepts these as strings below via the explicit choices added here.
# The commands use app_commands.Choice[str] so Discord supplies the choices.

bot.tree.add_command(quests_group)


# ---------------------------------------------------------------------------
# Hangry Games — isolated Cog, bolted on at the bottom. Self-contained;
# does not touch any of Cinnamon's state above.
# ---------------------------------------------------------------------------

HG_SOLO_DEATHS = [
    "{p1} got stuck in a cardboard box and was shipped to Abu Dhabi.",
    "{p1} misjudged a jump to the fridge and fell into the abyss.",
    "{p1} got the 3 AM zoomies and ran straight into a closed glass door.",
    "{p1} was hypnotized by a laser pointer and wandered off a cliff.",
    "{p1} forgot how to land on their feet.",
    "{p1} was startled by a cucumber and had a fatal heart attack.",
    "{p1} got stuck climbing the curtains and never came down.",
    "{p1} tried to catch a spicy fly (wasp) and lost.",
    "{p1} fell asleep on a warm laptop and melted into a puddle.",
    "{p1} inhaled too much catnip and ascended to another plane of existence.",
    "{p1} fell into a bathtub full of water.",
    "{p1} sneezed too hard and exploded.",
    "{p1} refused to use the new litter box and imploded from spite.",
    "{p1} jumped after a bird through a closed window.",
    "{p1} choked on a furball the size of a tennis ball.",
    "{p1} got their claw stuck in the carpet and starved to death.",
    "{p1} fell into the trash can and was taken out with the garbage.",
    "{p1} chased a fly right into a wall.",
    "{p1} tried to jump on the TV and pulled it down on themselves.",
    "{p1} got trapped inside a pillowcase.",
    "{p1} licked a spicy pepper that fell on the kitchen floor.",
    "{p1} got tangled in the window blinds.",
    "{p1} tried to sleep in a frying pan and cooked.",
    "{p1} smelled a sock and passed out forever.",
    "{p1} saw their own shadow and died of fright.",
    "{p1} tried to eat a fake plastic plant.",
    "{p1} jumped into a box of packing peanuts and disappeared.",
    "{p1} got their head stuck in a tissue box.",
    "{p1} slipped on a wet countertop and went flying.",
    "{p1} heard a loud noise and phased out of reality.",
    "{p1} tried to catch a snowflake and froze.",
    "{p1} got lost underneath the bed forever.",
    "{p1} fell asleep on the radiator.",
    "{p1} watched the washing machine spin until they got dizzy and perished.",
    "{p1} tried to drink from the fish tank and fell in."
]

HG_DUO_DEATHS = [
    "{p2} ate all the tuna, leaving {p1} to starve.",
    "{p1} ate all the tuna, so {p2} pushed them out a window.",
    "{p1} was swatted off the kitchen counter by {p2}.",
    "{p2} stole {p1}'s Churu, leading to a fatal heartbreak.",
    "{p2} pushed {p1} down the stairs while maintaining direct eye contact.",
    "{p2} ambushed {p1} from under the sofa with lethal force.",
    "{p2} challenged {p1} to a staring contest; {p1} spontaneously combusted.",
    "{p2} accidentally locked {p1} in the closet for a month.",
    "{p2} forced {p1} to take a bath, causing a total system failure.",
    "{p2} stole {p1}'s warm sunbeam, freezing them to death.",
    "{p2} betrayed {p1} for a single piece of premium kibble.",
    "{p2} convinced {p1} that the vacuum cleaner was friendly.",
    "{p2} framed {p1} for scratching the good sofa, leading to permanent exile.",
    "{p2} convinced {p1} that the neighborhood dog wanted to play.",
    "{p2} dropped a heavy potted plant directly onto {p1}.",
    "{p2} refused to share the heating pad, and {p1} froze.",
    "{p1} tried to steal {p2}'s toy mouse and caught these paws.",
    "{p2} lured {p1} into a cardboard box and mailed them to Antarctica.",
    "{p2} closed the door right as {p1} was walking through it.",
    "{p2} sneaked up and popped a paper bag behind {p1}, giving them a heart attack.",
    "{p2} stared at {p1} until {p1} forgot how to breathe.",
    "{p1} fell asleep, and {p2} piled heavy laundry on them.",
    "{p2} swatted {p1} right into the spinning ceiling fan.",
    "{p1} looked away for one second, and {p2} struck.",
    "{p2} told {p1} the laser pointer was real; {p1} ran into traffic.",
    "{p2} pushed {p1} right into the dreaded Roomba's path.",
    "{p2} weaponized a cucumber against {p1}.",
    "{p2} sat on {p1}'s face while they were sleeping.",
    "{p1} tried to groom {p2} but got their throat bitten instead.",
    "{p2} trapped {p1} under a laundry basket forever.",
    "{p2} claimed the highest cat tree perch and Sparta-kicked {p1} off of it.",
    "{p1} complained about the food, so {p2} made them the food.",
    "{p1} let their guard down, and {p2} pounced from the shadows.",
    "{p2} aggressively made biscuits on {p1}'s vital organs.",
    "{p2} convinced {p1} to jump into the empty bathtub, then turned on the faucet.",
    "{p2} 'accidentally' knocked a heavy vase directly onto {p1}.",
    "{p1} tripped over {p2} during the 3 AM zoomies and flew out the window.",
    "{p1} tried to steal a bite of {p2}'s wet food and was instantly vaporized.",
    "{p2} told {p1} the vet clinic was a spa. {p1} never returned.",
    "{p2} hissed at {p1} so aggressively that {p1}'s soul left their body.",
    "{p1} was sleeping peacefully until {p2} used their face as a trampoline.",
    "{p2} knocked a flat-screen TV onto {p1} just to see what would happen.",
    "{p2} pushed {p1} into a room full of toddlers and locked the door.",
    "{p1} playfully bit {p2}'s tail and was swiftly eradicated.",
    "{p2} dragged {p1} into the dreaded cat carrier of doom.",
    "{p2} refused to let {p1} use the clean litter box, resulting in a fatal implosion.",
    "{p1} sniffed {p2}'s unwashed paws and passed out forever.",
    "{p2} used {p1} as a scratching post.",
    "{p1} thought {p2} wanted to cuddle, but it was a bunny-kick death trap.",
    "{p2} dropped a live spider on {p1}'s nose, causing a fatal panic attack.",
    "{p2} tricked {p1} into eating the spicy dog kibble.",
    "{p2} sat directly on {p1} and refused to get up until it was too late.",
    "{p2} challenged {p1} to a race down the stairs and tripped them on step two.",
    "{p2} hypnotized {p1} with a swinging pocket watch and ordered them to walk into the fridge.",
    "{p2} told {p1} the red dot was real, sending them straight into a wall.",
    "{p2} pushed {p1} off the bed for taking up too much space.",
    "{p2} tricked {p1} into jumping onto a ceiling fan.",
    "{p1} tried to sneak up on {p2}, but received a swift ninja kick to the face.",
    "{p2} meowed aggressively until {p1}'s ears exploded.",
    "{p1} stole {p2}'s favorite feather toy and paid the ultimate price.",
    "{p2} locked {p1} outside in the rain.",
    "{p2} dropped a half-eaten mouse on {p1}'s face.",
    "{p1} refused to groom {p2} and was promptly banished to the shadow realm.",
    "{p2} body-slammed {p1} from the top of the fridge.",
    "{p1} sneezed, and {p2} took it as a declaration of war.",
    "{p2} swiped {p1}'s nose, causing a fatal system reboot.",
    "{p1} tried to share {p2}'s hammock and was violently evicted.",
    "{p2} convinced {p1} to jump into the toilet bowl.",
    "{p1} interrupted {p2}'s bath time and was destroyed.",
    "{p2} bit {p1}'s ear a little too hard during playtime.",
    "{p2} led {p1} into a room with a closed door, trapping them forever.",
    "{p1} got caught sniffing {p2}'s food bowl.",
    "{p2} swatted {p1} into the dreaded dog's territory.",
    "{p2} tricked {p1} into sniffing a lemon.",
    "{p1} stared at {p2} for too long and spontaneously combusted.",
    "{p2} pushed {p1} into a full bathtub while they were sleeping.",
    "{p1} tried to groom {p2}'s belly, a fatal mistake.",
    "{p2} performed a perfect wrestling takedown on {p1}.",
    "{p2} shoved {p1} off the windowsill.",
    "{p1} thought {p2} was asleep, but {p2} was just waiting to strike.",
    "{p2} trapped {p1} in the laundry basket and sat on the lid.",
    "{p1} took a bite of {p2}'s cat grass and was obliterated.",
    "{p2} convinced {p1} that the vet was just giving out free treats.",
    "{p1} tried to steal {p2}'s collar.",
    "{p2} lured {p1} into a pile of catnip and watched them transcend reality.",
    "{p2} told {p1} the vacuum cleaner was a friend.",
    "{p1} got jump-scared by {p2} and had a heart attack.",
    "{p2} sat on {p1}'s favorite toy until {p1} died of a broken heart.",
    "{p2} tackled {p1} down the hallway.",
    "{p1} tried to walk past {p2} in a narrow hallway.",
    "{p2} pushed {p1} into the empty pool.",
    "{p1} looked at {p2} funny.",
    "{p2} convinced {p1} to chase a laser pointer out the front door.",
    "{p1} sneaked up on {p2} and was roundhouse kicked.",
    "{p2} threw a toy mouse so hard it knocked {p1} out cold.",
    "{p1} refused to wake up, so {p2} used the heavy paws.",
    "{p2} trapped {p1} in a corner and booped them to death.",
    "{p2} lured {p1} into a trap made of cardboard boxes.",
    "{p1} tried to play with {p2}'s tail and was incinerated.",
    "{p2} forced {p1} to listen to the neighbor's dog barking.",
    "{p1} was buried under a mountain of pillows by {p2}.",
    "{p2} showed {p1} a mirror, causing a fatal existential crisis.",
    "{p1} drank from {p2}'s water bowl.",
    "{p2} pushed {p1} into a pile of wet laundry."
]

HG_SURVIVALS = [
    "{p1} took a nice long nap in a sunbeam.",
    "{p1} successfully begged for extra tuna.",
    "{p1} knocked a glass off the table and felt great about it.",
    "{p1} hid under the sofa all day and survived.",
    "{p1} made biscuits on a soft blanket.",
    "{p1} purred loudly to assert dominance.",
    "{p1} found a secret stash of treats and feasted.",
    "{p1} successfully ignored all humans for 24 hours.",
    "{p1} slept inside a warm laundry basket.",
    "{p1} caught the red dot!",
    "{p1} stared out the window at birds all day.",
    "{p1} received excellent chin scritches.",
    "{p1} successfully woke their owner up at 4 AM for food.",
    "{p1} found the perfect empty cardboard box.",
    "{p1} knocked a pen off the desk and survived to tell the tale.",
    "{p1} bathed perfectly in a square of sunlight.",
    "{p1} got a fresh bowl of cold water.",
    "{p1} performed a perfect loaf on the couch.",
    "{p1} successfully camouflaged themselves on a rug.",
    "{p1} found a discarded bottle cap and played with it for hours.",
    "{p1} stretched really, really far.",
    "{p1} watched a spider crawl across the ceiling peacefully.",
    "{p1} got brushed and purred like a motor.",
    "{p1} claimed the highest spot on the cat tree.",
    "{p1} sniffed the air and decided everything was fine.",
    "{p1} successfully avoided the vacuum cleaner."
]


HG_DATA_FILE = os.environ.get("HANGRY_GAMES_DATA_FILE", "hangry_games_data.json")
HG_UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
HG_UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
HG_REDIS_KEY = "hangry_games_data"


def _hg_decode(raw: dict) -> dict:
    pair = lambda d: {tuple(map(int, k.split(":"))): v for k, v in d.items()}
    return {
        "game_counts": {int(k): v for k, v in raw.get("game_counts", {}).items()},
        "win_counts": pair(raw.get("win_counts", {})),
        "kill_counts": pair(raw.get("kill_counts", {})),
        "played_counts": pair(raw.get("played_counts", {})),
        "log_channels": {int(k): v for k, v in raw.get("log_channels", {}).items()},
        "log_enabled": {int(k): v for k, v in raw.get("log_enabled", {}).items()},
    }


def _hg_encode(state: dict) -> dict:
    pair = lambda d: {f"{g}:{m}": v for (g, m), v in d.items()}
    return {
        "game_counts": {str(k): v for k, v in state["game_counts"].items()},
        "win_counts": pair(state["win_counts"]),
        "kill_counts": pair(state["kill_counts"]),
        "played_counts": pair(state["played_counts"]),
        "log_channels": {str(k): v for k, v in state["log_channels"].items()},
        "log_enabled": {str(k): v for k, v in state["log_enabled"].items()},
    }


async def hg_load_data() -> dict:
    """Load persisted game/win counts and the dedicated Hangry Games log channel.
    Uses Upstash Redis (survives redeploys on hosts with no persistent disk, e.g.
    Render free tier) when UPSTASH_REDIS_REST_URL/UPSTASH_REDIS_REST_TOKEN are
    set; otherwise falls back to a local JSON file (only survives plain
    restarts, not redeploys, on most free hosts). Never raises — a missing/
    corrupt/unreachable store just means we start fresh."""
    empty = _hg_decode({})
    if HG_UPSTASH_URL and HG_UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    HG_UPSTASH_URL, json=["GET", HG_REDIS_KEY],
                    headers={"Authorization": f"Bearer {HG_UPSTASH_TOKEN}"},
                ) as resp:
                    result = (await resp.json()).get("result")
            return _hg_decode(json.loads(result)) if result else empty
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, ValueError) as e:
            log.error(f"Failed to load Hangry Games data from Upstash: {e}")
            return empty
    try:
        with open(HG_DATA_FILE, "r") as f:
            return _hg_decode(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return empty


async def hg_save_data(state: dict):
    """Persist Hangry Games state (counts, stats, log settings). See hg_load_data
    for storage choice. Never raises — a failed save shouldn't crash a game."""
    encoded = _hg_encode(state)
    if HG_UPSTASH_URL and HG_UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    HG_UPSTASH_URL, json=["SET", HG_REDIS_KEY, json.dumps(encoded)],
                    headers={"Authorization": f"Bearer {HG_UPSTASH_TOKEN}"},
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.error(f"Failed to save Hangry Games data to Upstash: {e}")
        return
    try:
        with open(HG_DATA_FILE, "w") as f:
            json.dump(encoded, f)
    except OSError as e:
        log.error(f"Failed to save Hangry Games data: {e}")


class HGLobbyView(discord.ui.View):
    def __init__(self, cog: "HangryGamesCog", host: discord.Member, prize: str | None = None,
                 winner_role: discord.Role | None = None):
        super().__init__(timeout=600)
        self.cog = cog
        self.host = host
        self.prize = prize
        self.winner_role = winner_role
        self.players: dict[int, discord.Member] = {}
        self.started = False
        self.message: discord.Message | None = None

    def embed(self) -> discord.Embed:
        title = "🐾 Hangry Games — Giveaway" if self.prize else "🐾 Hangry Games"
        names = "\n".join(m.display_name for m in self.players.values()) or "*(none yet)*"
        desc = f"Host: {self.host.mention}\nTap **Join 🐾** to enter — no backing out!\n\n**Players:**\n{names}"
        if self.prize:
            desc += f"\n\n**Prize:** {self.prize}"
        return discord.Embed(title=title, description=desc, color=0xFFB02E)

    @discord.ui.button(label="Join 🐾", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button):
        if self.started:
            return await interaction.response.send_message("Already started!", ephemeral=True)
        if interaction.user.id in self.players:
            return await interaction.response.send_message("You're already in — no backing out!", ephemeral=True)
        self.players[interaction.user.id] = interaction.user
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Start 🔴", style=discord.ButtonStyle.danger)
    async def start(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Need Manage Messages to start.", ephemeral=True)
        if len(self.players) < 2:
            return await interaction.response.send_message("Need at least 2 players.", ephemeral=True)
        self.started = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(embed=self.embed(), view=self)
        self.stop()
        self.cog.lobbies.pop(interaction.channel.id, None)
        await self.cog.launch(interaction.channel, self.players, self.host, self.prize, self.winner_role)

    async def on_timeout(self):
        if self.started or not self.message:
            return
        for c in self.children:
            c.disabled = True
        self.cog.lobbies.pop(self.message.channel.id, None)
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass
        await self.cog._log(
            self.host.guild.id, title="⏰ Hangry Games lobby timed out", color=discord.Color.orange(),
            fields=[("Channel", self.message.channel.mention), ("Host", f"{self.host} ({self.host.id})"),
                    ("Players signed up", str(len(self.players)))],
        )


class HGRematchView(discord.ui.View):
    """Button under the winner embed: the host (or a mod) restarts with the same cats."""

    def __init__(self, cog: "HangryGamesCog", players: dict[int, discord.Member], host: discord.Member):
        super().__init__(timeout=300)
        self.cog, self.players, self.host = cog, players, host
        self.message: discord.Message | None = None

    @discord.ui.button(label="Rematch 🔁", style=discord.ButtonStyle.primary)
    async def rematch(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.host.id and not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Only the host or a mod can start a rematch.", ephemeral=True)
        if self.cog._busy(interaction.channel.id):
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        for c in self.children:
            c.disabled = True
        self.stop()
        await interaction.response.edit_message(view=self)
        await self.cog.launch(interaction.channel, dict(self.players), self.host, None, None)

    async def on_timeout(self):
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class HangryGamesCog(commands.GroupCog, group_name="hangrygames"):
    """Play a cat-themed elimination minigame"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active: dict[int, asyncio.Task] = {}
        self.lobbies: dict[int, "HGLobbyView"] = {}  # channel_id -> lobby not yet started
        self.game_counts: dict[int, int] = {}  # guild_id -> total games run
        self.win_counts: dict[tuple[int, int], int] = {}  # (guild_id, member_id) -> total wins
        self.kill_counts: dict[tuple[int, int], int] = {}  # (guild_id, member_id) -> total kills (completed games)
        self.played_counts: dict[tuple[int, int], int] = {}  # (guild_id, member_id) -> completed games played
        self.hg_log_channels: dict[int, int] = {}  # guild_id -> dedicated Hangry Games log channel_id
        self.log_enabled: dict[int, bool] = {}  # guild_id -> whether HG activity is logged (default: on once a channel is set)

    async def async_init(self):
        """Load persisted counts. Call once, before add_cog, since __init__ can't await."""
        data = await hg_load_data()
        self.game_counts = data["game_counts"]
        self.win_counts = data["win_counts"]
        self.kill_counts = data["kill_counts"]
        self.played_counts = data["played_counts"]
        self.hg_log_channels = data["log_channels"]
        self.log_enabled = data["log_enabled"]

    async def _save(self):
        await hg_save_data({
            "game_counts": self.game_counts, "win_counts": self.win_counts,
            "kill_counts": self.kill_counts, "played_counts": self.played_counts,
            "log_channels": self.hg_log_channels, "log_enabled": self.log_enabled,
        })

    async def _log(self, guild_id: int, *, title: str, color: discord.Color = discord.Color.blurple(),
                    fields: list[tuple[str, str]] | None = None):
        """Post a Hangry Games event to this guild's dedicated log channel
        (set via /hangrygames logchannel), unless logging's been turned off."""
        if not self.log_enabled.get(guild_id, True):
            return
        channel_id = self.hg_log_channels.get(guild_id)
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return
        embed = discord.Embed(title=title, color=color, timestamp=datetime.datetime.now(datetime.timezone.utc))
        for name, value in (fields or []):
            embed.add_field(name=name, value=value, inline=True)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            log.warning(f"Failed to post Hangry Games log: {e}")

    async def recover_from_log(self, guild: discord.Guild, limit: int = 2000) -> tuple[int, int]:
        """Rebuild this guild's game count and win totals from its Hangry Games
        log channel's message history — used when the persisted store comes back
        empty for a guild that has a log channel configured. Best-effort, bounded
        by `limit` messages and Discord's own retention. Returns
        (reconstructed_game_count, wins_reconstructed)."""
        channel_id = self.hg_log_channels.get(guild.id)
        if channel_id is None:
            return (0, 0)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return (0, 0)

        max_game_num = 0
        wins: list[int] = []  # winner_id per win found
        game_num_re = re.compile(r"Hangry Games #(\d+)")
        id_re = re.compile(r"\((\d+)\)\s*$")
        try:
            async for message in channel.history(limit=limit):
                for embed in message.embeds:
                    if not embed.title:
                        continue
                    m = game_num_re.search(embed.title)
                    if not m:
                        continue
                    max_game_num = max(max_game_num, int(m.group(1)))
                    if embed.title.startswith("🏆 Hangry Games"):
                        fields = {f.name: f.value for f in embed.fields}
                        wm = id_re.search(fields.get("Winner", ""))
                        if wm:
                            wins.append(int(wm.group(1)))
        except discord.HTTPException as e:
            log.error(f"Failed to scan Hangry Games log channel for recovery in guild {guild.id}: {e}")
            return (0, 0)

        if max_game_num:
            self.game_counts[guild.id] = max_game_num
        for winner_id in wins:
            key = (guild.id, winner_id)
            self.win_counts[key] = self.win_counts.get(key, 0) + 1
        if max_game_num or wins:
            await self._save()
        return (max_game_num, len(wins))

    async def launch(self, channel: discord.abc.Messageable, players: dict[int, discord.Member],
                      host: discord.Member, prize: str | None, winner_role: discord.Role | None = None):
        self.game_counts[channel.guild.id] = self.game_counts.get(channel.guild.id, 0) + 1
        game_num = self.game_counts[channel.guild.id]
        await self._save()
        task = asyncio.create_task(self.run_game(channel, players, host, prize, game_num, winner_role))
        self.active[channel.id] = task

        fields = [
            ("Channel", channel.mention), ("Host", f"{host} ({host.id})"),
            ("Players", str(len(players))),
        ]
        if prize:
            fields.append(("Prize", prize))
        if winner_role:
            fields.append(("Winner role", winner_role.name))
        await self._log(
            channel.guild.id, title=f"🐾 Hangry Games #{game_num} started", color=discord.Color.gold(),
            fields=fields,
        )

    async def run_game(self, channel: discord.abc.Messageable, players: dict[int, discord.Member],
                        host: discord.Member, prize: str | None, game_num: int,
                        winner_role: discord.Role | None = None):
        alive = dict(players)
        kills: dict[int, int] = {pid: 0 for pid in alive}
        start = time.monotonic()
        rnd = 0
        await channel.send(f"🐾 **Hangry Games #{game_num}** begins with **{len(alive)}** cats in the arena, hosted by {host.mention}!")
        try:
            while len(alive) > 1:
                rnd += 1
                await asyncio.sleep(5)
                ids = list(alive.keys())
                embed = discord.Embed(color=0xFFB02E)
                embed.set_footer(text=f"Game #{game_num} · Round {rnd}")
                roll = random.random()

                if roll < 0.85:
                    p1_id, p2_id = random.sample(ids, 2)
                    p1, p2 = alive[p1_id], alive[p2_id]
                    content = f"{p1.mention} {p2.mention}"
                    embed.description = f"⚔️ {random.choice(HG_DUO_DEATHS).format(p1=p1.display_name, p2=p2.display_name)}"
                    embed.set_thumbnail(url=p1.display_avatar.url)
                    embed.set_image(url=p2.display_avatar.url)
                    kills[p2_id] = kills.get(p2_id, 0) + 1
                    del alive[p1_id]
                elif roll < 0.925:
                    p1_id = random.choice(ids)
                    p1 = alive[p1_id]
                    content = p1.mention
                    embed.title = "🐾 A cat-astrophe occurred! 🙀"
                    embed.description = f"👉 {random.choice(HG_SOLO_DEATHS).format(p1=p1.display_name)}"
                    embed.set_image(url=p1.display_avatar.url)
                    del alive[p1_id]
                else:
                    p1_id = random.choice(ids)
                    p1 = alive[p1_id]
                    content = p1.mention
                    embed.title = "🐾 A cat-astrophe occurred! 🙀"
                    embed.description = f"👉 {random.choice(HG_SURVIVALS).format(p1=p1.display_name)}"
                    embed.set_image(url=p1.display_avatar.url)

                if rnd % 5 == 0:
                    survivors = "\n".join(m.display_name for m in alive.values()) or "None"
                    embed.add_field(name="Survivors", value=survivors, inline=False)

                await channel.send(content=content, embed=embed)

            winner_id, winner = next(iter(alive.items())) if alive else (None, None)
            winner_kills = kills.get(winner_id, 0)
            elapsed = int(time.monotonic() - start)
            mm, ss = divmod(elapsed, 60)

            win_key = (channel.guild.id, winner_id)
            self.win_counts[win_key] = self.win_counts.get(win_key, 0) + 1
            total_wins = self.win_counts[win_key]
            for pid, k in kills.items():
                pkey = (channel.guild.id, pid)
                self.played_counts[pkey] = self.played_counts.get(pkey, 0) + 1
                if k:
                    self.kill_counts[pkey] = self.kill_counts.get(pkey, 0) + k
                member = channel.guild.get_member(pid)
                if member:
                    await achievement_record(channel.guild.id, pid, metric_updates={"hangry_games": 1}, member=member)
            await self._save()

            desc = f"🎉 **{winner.display_name}** won **{host.display_name}**'s Hangry Games"
            if prize:
                desc += f" and **{prize}**"
            desc += "!\n"
            desc += f"💀 **Total kills:** {winner_kills}\n"
            desc += f"⏱️ **Time survived:** {mm}m {ss}s\n"
            desc += f"🏆 **Total wins in server:** {total_wins}"

            if winner_role:
                try:
                    await winner.add_roles(winner_role, reason=f"Won Hangry Games #{game_num}")
                    desc += f"\n🎗️ **{winner.display_name}** was crowned with the **{winner_role.name}** role!"
                except discord.HTTPException:
                    pass

            winner_embed = discord.Embed(title="🏆 Winner!", color=0xFEE75C, description=desc)
            winner_embed.set_image(url=winner.display_avatar.url)
            winner_embed.set_footer(text=f"Game #{game_num}")
            rematch = HGRematchView(self, players, host)
            rematch.message = await channel.send(
                content=winner.mention, embed=winner_embed, view=rematch,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False),
            )

            log_fields = [
                ("Channel", channel.mention), ("Host", f"{host} ({host.id})"),
                ("Winner", f"{winner} ({winner.id})"), ("Kills", str(winner_kills)),
                ("Time survived", f"{mm}m {ss}s"), ("Total wins (server)", str(total_wins)),
            ]
            if prize:
                log_fields.append(("Prize", prize))
            if winner_role:
                log_fields.append(("Winner role", winner_role.name))
            await self._log(
                channel.guild.id, title=f"🏆 Hangry Games #{game_num} ended", color=discord.Color.gold(),
                fields=log_fields,
            )
        except asyncio.CancelledError:
            await channel.send(
                f"🙀 *the arena collapses mid-brawl!* Hangry Games #{game_num} was cancelled — "
                f"no winner this time, you scaredy-cats."
            )
            await self._log(
                channel.guild.id, title=f"🚫 Hangry Games #{game_num} cancelled mid-game",
                color=discord.Color.red(),
                fields=[("Channel", channel.mention), ("Host", f"{host} ({host.id})"),
                        ("Players remaining", str(len(alive)))],
            )
        finally:
            self.active.pop(channel.id, None)

    def _busy(self, channel_id: int) -> bool:
        return channel_id in self.active or channel_id in self.lobbies

    @app_commands.command(name="new", description="Start a Hangry Games lobby")
    @app_commands.describe(host="Who's hosting (defaults to you)")
    @app_commands.guild_only()
    async def new(self, interaction: discord.Interaction, host: discord.Member = None):
        if self._busy(interaction.channel.id):
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        view = HGLobbyView(self, host or interaction.user)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()
        self.lobbies[interaction.channel.id] = view

    @app_commands.command(name="giveaway", description="Run a Hangry Games giveaway")
    @app_commands.describe(prize="What the winner takes home (optional)", host="Who's hosting (defaults to you)",
                            winner_role="Role to give the winner (optional)")
    @app_commands.guild_only()
    async def giveaway(self, interaction: discord.Interaction, prize: str = None, host: discord.Member = None,
                        winner_role: discord.Role = None):
        if self._busy(interaction.channel.id):
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        view = HGLobbyView(self, host or interaction.user, prize=prize, winner_role=winner_role)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()
        self.lobbies[interaction.channel.id] = view

    @app_commands.command(name="role", description="Auto-start a game with everyone who has a role")
    @app_commands.describe(role="The role to pull players from", prize="What the winner takes home (optional)",
                            host="Who's hosting (defaults to you)", winner_role="Role to give the winner (optional)")
    @app_commands.guild_only()
    async def role_cmd(self, interaction: discord.Interaction, role: discord.Role, prize: str = None,
                        host: discord.Member = None, winner_role: discord.Role = None):
        if self._busy(interaction.channel.id):
            return await interaction.response.send_message("A game's already running here!", ephemeral=True)
        players = {m.id: m for m in role.members if not m.bot}
        if len(players) < 2:
            return await interaction.response.send_message(
                "Need at least 2 non-bot members with that role.", ephemeral=True
            )
        host = host or interaction.user
        await interaction.response.send_message(
            f"🐾 **{len(players)}** cats from **{role.name}** enter the arena, hosted by {host.mention}!",
            allowed_mentions=discord.AllowedMentions(roles=False),
        )
        await self.launch(interaction.channel, players, host, prize, winner_role)

    @app_commands.command(name="leaderboard", description="Top Hangry Games winners in this server")
    @app_commands.guild_only()
    async def hg_leaderboard(self, interaction: discord.Interaction):
        gid = interaction.guild.id
        top = sorted(((m, w) for (g, m), w in self.win_counts.items() if g == gid), key=lambda e: e[1], reverse=True)[:10]
        if not top:
            return await interaction.response.send_message("No Hangry Games winners yet. 🐾", ephemeral=True)
        lines = []
        for i, (uid, wins) in enumerate(top, 1):
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"
            kills = self.kill_counts.get((gid, uid), 0)
            lines.append(f"**#{i}** {name} — {wins} win(s), {kills} kill(s)")
        embed = discord.Embed(title="🏆 Hangry Games Leaderboard", description="\n".join(lines), color=0xFEE75C)
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="stats", description="A member's Hangry Games stats")
    @app_commands.describe(member="Who to check (defaults to you)")
    @app_commands.guild_only()
    async def hg_stats(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        gid, key = interaction.guild.id, (interaction.guild.id, member.id)
        wins, kills = self.win_counts.get(key, 0), self.kill_counts.get(key, 0)
        played = self.played_counts.get(key, 0)
        ranked = sorted({m: w for (g, m), w in self.win_counts.items() if g == gid}.items(), key=lambda e: e[1], reverse=True)
        place = next((i for i, (m, _) in enumerate(ranked, 1) if m == member.id), None)
        embed = discord.Embed(title=f"🐾 {member.display_name}'s Hangry Games stats", color=0xFFB02E)
        embed.add_field(name="Wins", value=str(wins), inline=True)
        embed.add_field(name="Kills", value=str(kills), inline=True)
        embed.add_field(name="Games played", value=str(played) if played else "—", inline=True)
        embed.add_field(name="Win rate", value=f"{wins / played:.0%}" if played else "—", inline=True)
        embed.add_field(name="Server rank", value=f"#{place}" if place else "Unranked", inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Kills and games played count from completed games since stats tracking began.")
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="cancel", description="Cancel the Hangry Games running in this channel")
    @app_commands.guild_only()
    async def cancel(self, interaction: discord.Interaction):
        task = self.active.pop(interaction.channel.id, None)
        if task:
            task.cancel()
            return await interaction.response.send_message(
                "🐾 *pulls the emergency lever* Calling off the Hangry Games mid-fight!"
            )

        lobby = self.lobbies.pop(interaction.channel.id, None)
        if lobby:
            lobby.started = True  # blocks a stray Join/Start click racing the cancel
            for c in lobby.children:
                c.disabled = True
            lobby.stop()
            if lobby.message:
                try:
                    await lobby.message.edit(view=lobby)
                except discord.HTTPException:
                    pass
            await self._log(
                interaction.guild.id, title="🚫 Hangry Games lobby cancelled", color=discord.Color.red(),
                fields=[("Channel", interaction.channel.mention), ("Host", f"{lobby.host} ({lobby.host.id})"),
                        ("Cancelled by", f"{interaction.user} ({interaction.user.id})"),
                        ("Players signed up", str(len(lobby.players)))],
            )
            return await interaction.response.send_message(
                "🐾 *knocks the lobby sign-up sheet off the table* The Hangry Games were cancelled before they even began!"
            )

        await interaction.response.send_message("No game running here.", ephemeral=True)

    @app_commands.command(name="logchannel", description="Set (or reset) this channel as Hangry Games' dedicated log channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def hg_logchannel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        target = channel or interaction.channel
        guild_id = interaction.guild.id

        self.hg_log_channels[guild_id] = target.id
        self.log_enabled[guild_id] = True

        # Fresh start: reset this server's game number back to 1 and wipe its win totals.
        self.game_counts.pop(guild_id, None)
        self.win_counts = {k: v for k, v in self.win_counts.items() if k[0] != guild_id}
        await self._save()

        await interaction.response.send_message(
            f"🐾 Hangry Games will now log to {target.mention}. Game numbers and win totals for this "
            f"server have been reset — the next game will be **Game #1**.",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self._log(
            guild_id, title="🐾 Hangry Games log channel set", color=discord.Color.gold(),
            fields=[("Channel", target.mention), ("Set by", f"{interaction.user} ({interaction.user.id})")],
        )

    @app_commands.command(name="disablelogchannel", description="Stop Hangry Games from posting logs anywhere in this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def hg_disablelogchannel(self, interaction: discord.Interaction):
        removed = self.hg_log_channels.pop(interaction.guild.id, None)
        self.log_enabled.pop(interaction.guild.id, None)
        await self._save()
        if removed is None:
            return await interaction.response.send_message("No Hangry Games log channel was set.", ephemeral=True)
        await interaction.response.send_message("🐾 Hangry Games log channel disabled. Game numbers and win totals are unaffected.")

    @app_commands.command(name="log", description="Turn Hangry Games activity logging on/off without changing the channel")
    @app_commands.describe(enabled="On: log game starts, winners, and cancellations to the log channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def log_toggle(self, interaction: discord.Interaction, enabled: bool):
        if interaction.guild.id not in self.hg_log_channels:
            return await interaction.response.send_message(
                "Set a Hangry Games log channel first with `/hangrygames logchannel`, then toggle this.",
                ephemeral=True,
            )
        self.log_enabled[interaction.guild.id] = enabled
        await self._save()
        state = "on" if enabled else "off"
        await interaction.response.send_message(f"🐾 Hangry Games logging turned **{state}**.", ephemeral=True)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(DISCORD_TOKEN)
