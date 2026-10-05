"""Cinnamon feature module.

Loaded by main.py into Cinnamon's shared runtime namespace. This is still
one Discord bot and one process; this file is not a separate bot.
Do not run this file directly.
"""

flask_app = Flask(__name__)
flask_app.secret_key = os.environ.get("DASHBOARD_SESSION_SECRET") or os.urandom(32)


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
        "economy_achievements": {f"{g}:{u}": list(ids) for (g, u), ids in economy_achievements.items()},
        "economy_items": ECONOMY_ITEMS,
        "economy_quest_definitions": ECONOMY_QUESTS,
        # Server configuration that should survive a restart/redeploy.
        "ai_channels": {str(k): v for k, v in ai_channels.items()},
        "disabled_channels": {str(k): list(v) for k, v in disabled_channels.items()},
        "log_channels": {str(k): v for k, v in log_channels.items()},
        "category_log_channels": {str(g): {str(c): ch for c, ch in cfg.items()} for g, cfg in category_log_channels.items()},
    }


def _bd_decode(raw: dict):
    global warnings_data, welcome_config, goodbye_config, automod_config
    global xp_data, reaction_role_ids, temp_bans, antiraid_config, case_counters
    global level_roles, active_giveaways, active_polls, ai_channels, disabled_channels, log_channels, category_log_channels
    global economy_balances, economy_inventory, economy_quests, economy_cooldowns, economy_log_channels
    global economy_level_rewards_claimed, economy_income_roles, economy_achievements
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
    economy_achievements = {}
    for k, ids in raw.get("economy_achievements", {}).items():
        parts = k.split(":")
        if len(parts) == 2 and isinstance(ids, list):
            economy_achievements[(int(parts[0]), int(parts[1]))] = [str(x) for x in ids if str(x) in ECONOMY_ACHIEVEMENTS]
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
    saved_quests = raw.get("economy_quest_definitions")
    if isinstance(saved_quests, dict):
        ECONOMY_QUESTS.clear()
        for quest_id, quest in saved_quests.items():
            if isinstance(quest, dict) and str(quest.get("item", "")) in ECONOMY_ITEMS:
                ECONOMY_QUESTS[str(quest_id)] = {
                    "name": str(quest.get("name", quest_id))[:80],
                    "item": str(quest.get("item")),
                    "amount": max(1, int(quest.get("amount", 1))),
                    "reward": max(0, int(quest.get("reward", 0))),
                    "description": str(quest.get("description", ""))[:300],
                }
    ai_channels = {int(k): v for k, v in raw.get("ai_channels", {}).items()}
    disabled_channels = defaultdict(set, {int(k): set(v) for k, v in raw.get("disabled_channels", {}).items()})
    log_channels = {int(k): v for k, v in raw.get("log_channels", {}).items()}
    category_log_channels = {int(g): {str(c): int(ch) for c, ch in cfg.items()} for g, cfg in raw.get("category_log_channels", {}).items() if isinstance(cfg, dict)}


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


def dashboard_state_provider() -> dict:
    """Expose live bot state to the Flask dashboard without copying mutable data."""
    hg = bot.get_cog("HangryGamesCog")
    return {
        "warnings_data": warnings_data, "welcome_config": welcome_config,
        "goodbye_config": goodbye_config, "automod_config": automod_config,
        "xp_data": xp_data, "level_roles": level_roles, "antiraid_config": antiraid_config,
        "active_giveaways": active_giveaways, "economy_balances": economy_balances,
        "economy_inventory": economy_inventory, "economy_quests": economy_quests,
        "economy_log_channels": economy_log_channels, "economy_income_roles": economy_income_roles,
        "ECONOMY_ITEMS": ECONOMY_ITEMS, "ECONOMY_QUESTS": ECONOMY_QUESTS, "ECONOMY_ACHIEVEMENTS": ECONOMY_ACHIEVEMENTS, "economy_achievements": economy_achievements,
        "ECONOMY_DAILY_REWARD": ECONOMY_DAILY_REWARD, "ECONOMY_WORK_MIN": ECONOMY_WORK_MIN,
        "ECONOMY_WORK_MAX": ECONOMY_WORK_MAX, "ECONOMY_WORK_COOLDOWN": ECONOMY_WORK_COOLDOWN,
        "ai_channels": ai_channels, "log_channels": log_channels,
        "category_log_channels": category_log_channels,
        "BD_UPSTASH_URL": BD_UPSTASH_URL, "BD_UPSTASH_TOKEN": BD_UPSTASH_TOKEN,
        "bd_save_data": bd_save_data, "send_log": send_log,
        "recall_guild_data": recall_guild_data,
        "level_from_xp": level_from_xp, "giveaway_embed": _giveaway_embed,
        "giveaway_view": GiveawayView, "finish_giveaway": finish_giveaway,
        "cancel_giveaway": cancel_giveaway,
        "hg_cog": hg,
    }


try:
    import dashboard as cinnamon_dashboard
    cinnamon_dashboard.configure_dashboard(bot, dashboard_state_provider)
    flask_app.register_blueprint(cinnamon_dashboard.dashboard_bp)
except Exception as dashboard_error:
    log.exception("Dashboard could not be initialized (%s)", type(dashboard_error).__name__)


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
