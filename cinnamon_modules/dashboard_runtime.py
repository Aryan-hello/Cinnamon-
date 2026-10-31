"""Cinnamon feature module.

Loaded by main.py into Cinnamon's shared runtime namespace. This is still
one Discord bot and one process; this file is not a separate bot.
Do not run this file directly.
"""

flask_app = Flask(__name__)
flask_app.secret_key = (os.environ.get("DASHBOARD_SECRET_KEY")
                        or os.environ.get("DASHBOARD_SESSION_SECRET") or os.urandom(32))


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
from cinnamon_modules.brain_storage import (
    SnapshotStore as _BDSnapshotStore, LocalSnapshotBackend as _BDLocalBackend,
    UpstashSnapshotBackend as _BDUpstashBackend, validate_snapshot as _bd_validate_snapshot,
)
bd_store = _BDSnapshotStore(
    _BDUpstashBackend(BD_UPSTASH_URL, BD_UPSTASH_TOKEN, BD_REDIS_KEY)
    if BD_UPSTASH_URL or BD_UPSTASH_TOKEN else _BDLocalBackend(BD_DATA_FILE))
_BD_SAVE_LOCK = bd_store.lock


def _bd_encode() -> dict:
    achievement_data_local = globals().get("achievement_data", {})
    achievement_config_local = globals().get("achievement_config", {})
    quest_data_local = globals().get("quest_data", {})
    quest_config_local = globals().get("quest_config", {})
    return {
        "warnings": {f"{g}:{m}": v for (g, m), v in warnings_data.items()},
        "welcome_config": {str(k): v for k, v in welcome_config.items()},
        "goodbye_config": {str(k): v for k, v in goodbye_config.items()},
        "automod_config": {str(k): v for k, v in automod_config.items()},
        "xp_data": {f"{g}:{m}": v for (g, m), v in xp_data.items()},
        "xp_per_message": {str(g): int(v) for g, v in xp_per_message.items()},
        "xp_channels": {str(g): list(v) for g, v in xp_channels.items()},
        "reaction_role_ids": list(reaction_role_ids),
        "temp_bans": {f"{g}:{m}": v for (g, m), v in temp_bans.items()},
        "antiraid_config": {str(k): v for k, v in antiraid_config.items()},
        "case_counters": {str(k): v for k, v in case_counters.items()},
        "level_roles": {str(g): {str(l): r for l, r in v.items()} for g, v in level_roles.items()},
        "active_giveaways": {str(k): v for k, v in active_giveaways.items()},
        "active_polls": {str(k): v for k, v in active_polls.items()},
        "giveaway_history": globals().get("giveaway_history", {}),
        "giveaway_templates": {str(g): cfg for g, cfg in globals().get("giveaway_templates", {}).items()},
        "giveaway_schedules": globals().get("giveaway_schedules", {}),
        "giveaway_timed_roles": globals().get("giveaway_timed_roles", []),
        "giveaway_timed_threads": globals().get("giveaway_timed_threads", []),
        "economy_balances": {f"{g}:{u}": v for (g, u), v in economy_balances.items()},
        "economy_inventory": {f"{g}:{u}": v for (g, u), v in economy_inventory.items()},
        "economy_cooldowns": {f"{g}:{u}:{a}": v for (g, u, a), v in economy_cooldowns.items()},
        "economy_log_channels": {str(k): v for k, v in economy_log_channels.items()},
        "economy_level_rewards_claimed": {f"{g}:{u}": list(levels) for (g, u), levels in economy_level_rewards_claimed.items()},
        "economy_income_roles": {str(g): {str(r): cfg for r, cfg in roles.items()} for g, roles in economy_income_roles.items()},
        "economy_items": ECONOMY_ITEMS,
        "achievement_data": {f"{g}:{u}": v for (g,u), v in achievement_data_local.items()},
        "achievement_config": {str(g): v for g,v in achievement_config_local.items()},
        "friendship_data": {f"{g}:{u}": v for (g,u),v in friendship_data.items()},
        "quest_data": {str(g): v for g,v in quest_data_local.items()},
        "quest_config": {str(g): v for g,v in quest_config_local.items()},
        "advanced_features": globals().get("advanced_features_data", {}),
        # Server configuration that should survive a restart/redeploy.
        "ai_channels": {str(k): v for k, v in ai_channels.items()},
        "disabled_channels": {str(k): list(v) for k, v in disabled_channels.items()},
        "log_channels": {str(k): v for k, v in log_channels.items()},
        "category_log_channels": {str(g): {str(c): ch for c, ch in cfg.items()} for g, cfg in category_log_channels.items()},
    }


def _bd_decode(raw: dict):
    _bd_validate_snapshot(raw)
    global warnings_data, welcome_config, goodbye_config, automod_config
    global xp_data, xp_per_message, xp_channels, reaction_role_ids, temp_bans, antiraid_config, case_counters
    global level_roles, active_giveaways, active_polls, ai_channels, disabled_channels, log_channels, category_log_channels
    global economy_balances, economy_inventory, economy_cooldowns, economy_log_channels
    global economy_level_rewards_claimed, economy_income_roles
    global achievement_data, achievement_config, friendship_data, quest_data, quest_config, advanced_features_data
    warnings_data = defaultdict(list, {tuple(map(int, k.split(":"))): v for k, v in raw.get("warnings", {}).items()})
    welcome_config = {int(k): v for k, v in raw.get("welcome_config", {}).items()}
    goodbye_config = {int(k): v for k, v in raw.get("goodbye_config", {}).items()}
    automod_config = {int(k): v for k, v in raw.get("automod_config", {}).items()}
    ai_channels = {int(k): v for k, v in raw.get("ai_channels", {}).items()}
    disabled_channels = defaultdict(set, {int(g): set(map(int, ids)) for g, ids in raw.get("disabled_channels", {}).items()})
    log_channels = {int(k): v for k, v in raw.get("log_channels", {}).items()}
    category_log_channels = {int(g): dict(cfg) for g, cfg in raw.get("category_log_channels", {}).items()}
    xp_data = {tuple(map(int, k.split(":"))):v for k, v in raw.get("xp_data", {}).items()}
    xp_per_message = {int(g): int(v) for g, v in raw.get("xp_per_message", {}).items()}
    xp_channels = defaultdict(set, {int(g): set(map(int, ids)) for g, ids in raw.get("xp_channels", {}).items()})
    reaction_role_ids = set(raw.get("reaction_role_ids", []))
    temp_bans = {tuple(map(int, k.split(":"))): v for k, v in raw.get("temp_bans", {}).items()}
    antiraid_config = {int(k): v for k, v in raw.get("antiraid_config", {}).items()}
    case_counters = {int(k): v for k, v in raw.get("case_counters", {}).items()}
    level_roles = {int(g): {int(l): r for l, r in v.items()} for g, v in raw.get("level_roles", {}).items()}
    active_giveaways = {int(k): v for k, v in raw.get("active_giveaways", {}).items()}
    active_polls = {int(k): v for k, v in raw.get("active_polls", {}).items()}
    globals()["giveaway_history"] = raw.get("giveaway_history", {}) if isinstance(raw.get("giveaway_history", {}), dict) else {}
    globals()["giveaway_templates"] = {int(g): cfg for g, cfg in raw.get("giveaway_templates", {}).items() if str(g).isdigit()}
    globals()["giveaway_schedules"] = raw.get("giveaway_schedules", {}) if isinstance(raw.get("giveaway_schedules", {}), dict) else {}
    globals()["giveaway_timed_roles"] = raw.get("giveaway_timed_roles", []) if isinstance(raw.get("giveaway_timed_roles", []), list) else []
    globals()["giveaway_timed_threads"] = raw.get("giveaway_timed_threads", []) if isinstance(raw.get("giveaway_timed_threads", []), list) else []
    economy_balances = {tuple(map(int, k.split(":"))): v for k, v in raw.get("economy_balances", {}).items()}
    economy_inventory = {tuple(map(int, k.split(":"))): v for k, v in raw.get("economy_inventory", {}).items()}
    economy_cooldowns = {}
    for k, v in raw.get("economy_cooldowns", {}).items():
        # Actions such as income:<role_id> and give:<member_id> contain colons.
        parts = k.split(":", 2)
        if len(parts) == 3:
            economy_cooldowns[(int(parts[0]), int(parts[1]), parts[2])] = v
    economy_log_channels = {int(k): v for k, v in raw.get("economy_log_channels", {}).items()}
    economy_level_rewards_claimed = {}
    for k, levels in raw.get("economy_level_rewards_claimed", {}).items():
        parts = k.split(":")
        if len(parts) == 2:
            economy_level_rewards_claimed[(int(parts[0]), int(parts[1]))] = [int(x) for x in levels]
    economy_income_roles = {int(g): {int(r): cfg for r, cfg in roles.items()} for g, roles in raw.get("economy_income_roles", {}).items()}
    # A saved catalog is authoritative, including removals and an empty shop.
    # Older snapshots without this field keep the built-in catalog. Update in
    # place so existing views/helpers retain their shared catalog reference.
    saved_items = raw.get("economy_items")
    if isinstance(saved_items, dict):
        ECONOMY_ITEMS.clear()
        ECONOMY_ITEMS.update(saved_items)
    else:
        # Migrate only legacy/default catalogs. Explicitly saved prices are
        # administrator choices and may validly be below these default floors.
        price_floor_defaults = {"tuna":1000,"treat":1000,"churu":1500,"catnip_ball":2000,"fish":2500}
        for item_id, minimum in price_floor_defaults.items():
            if item_id in ECONOMY_ITEMS:
                ECONOMY_ITEMS[item_id]["price"] = max(int(ECONOMY_ITEMS[item_id].get("price",minimum)), minimum)
        for item_id, item in ECONOMY_ITEMS.items():
            if isinstance(item, dict): item["price"] = max(1000, int(item.get("price",1000)))
    achievement_data = {}
    for k,v in raw.get("achievement_data", {}).items():
        parts=k.split(":")
        if len(parts)==2:
            achievement_data[(int(parts[0]),int(parts[1]))]=v
    achievement_config = {int(g):v for g,v in raw.get("achievement_config", {}).items()}
    friendship_data = {}
    for k,v in raw.get("friendship_data", {}).items():
        parts=k.split(":")
        if len(parts)==2: friendship_data[(int(parts[0]),int(parts[1]))]=v
    quest_data = {int(g):v for g,v in raw.get("quest_data", {}).items()}
    quest_config = {int(g):v for g,v in raw.get("quest_config", {}).items()}
    # Update IN PLACE: advanced_economy.py keeps a reference to this same dict,
    # so rebinding the name here would silently detach it and lose box/market data.
    _af_raw = raw.get("advanced_features", {})
    advanced_features_data.clear()
    advanced_features_data.update(_af_raw if isinstance(_af_raw, dict) else {})
    for _af_key_name in ("mystery_boxes", "crafted_counts", "mystery_opened", "black_market_purchases"):
        advanced_features_data.setdefault(_af_key_name, {})
async def bd_load_data():
    """Load only a validated snapshot; an unavailable store never means fresh data."""
    result = await bd_store.load()
    if not result:
        log.error("Bot snapshot load unavailable; persistence writes disabled")
        return result
    try:
        _bd_decode(result.snapshot)
    except (ValueError, TypeError, KeyError, AttributeError):
        bd_store.disable("Snapshot application failed")
        log.error("Bot snapshot validation failed; persistence writes disabled")
        from cinnamon_modules.brain_storage import CommitResult
        return CommitResult("unavailable", "Snapshot application failed")
    return result


async def bd_save_data():
    """Persist an ordered snapshot and return a truthful, non-raising result.

    Legacy callers may ignore the result. Trusted actions must inspect it. No
    writes occur after a failed startup load, conflicting writer, or unresolved
    business transaction. Reconciliation publishes live deltas before encoding.
    """
    async with bd_store.lock:
        available = await bd_store.ensure_ready_locked()
        if not available:
            log.error("Bot snapshot save blocked (%s)", available.status)
            return available
        try:
            prune_receipts = globals().get("_ca_prune_all_receipts")
            if callable(prune_receipts):
                prune_receipts()
            result = await bd_store.commit_locked(_bd_encode())
        except (ValueError, TypeError, KeyError, AttributeError):
            from cinnamon_modules.brain_storage import CommitResult
            result = CommitResult("failed", "Snapshot encoding failed")
        if not result:
            log.error("Bot snapshot save failed (%s)", result.status)
        return result


def dashboard_state_provider() -> dict:
    """Expose live bot state to the Flask dashboard without copying mutable data."""
    hg = bot.get_cog("HangryGamesCog")
    return {
        "warnings_data": warnings_data, "welcome_config": welcome_config,
        "goodbye_config": goodbye_config, "automod_config": automod_config,
        "xp_data": xp_data, "xp_per_message": xp_per_message, "xp_channels": xp_channels, "level_roles": level_roles, "antiraid_config": antiraid_config,
        "active_giveaways": active_giveaways, "active_polls": active_polls, "economy_balances": economy_balances,
        "giveaway_history": globals().get("giveaway_history", {}),
        "giveaway_templates": globals().get("giveaway_templates", {}),
        "giveaway_schedules": globals().get("giveaway_schedules", {}),
        "giveaway_timed_roles": globals().get("giveaway_timed_roles", []),
        "giveaway_timed_threads": globals().get("giveaway_timed_threads", []),
        "economy_inventory": economy_inventory,
        "economy_log_channels": economy_log_channels, "economy_income_roles": economy_income_roles,
        "ECONOMY_ITEMS": ECONOMY_ITEMS, "achievement_data": achievement_data, "friendship_data": friendship_data, "quest_data": quest_data,
        "ECONOMY_DAILY_REWARD": ECONOMY_DAILY_REWARD, "ECONOMY_WORK_MIN": ECONOMY_WORK_MIN,
        "ECONOMY_WORK_MAX": ECONOMY_WORK_MAX, "ECONOMY_WORK_COOLDOWN": ECONOMY_WORK_COOLDOWN,
        # Read-only definitions/status exposed to the dashboard. Commands remain Discord-only.
        "ACHIEVEMENTS": globals().get("ACHIEVEMENTS", {}),
        "SECRET_ACHIEVEMENTS": globals().get("SECRET_ACHIEVEMENTS", {}),
        "ADMIN_ACHIEVEMENT": globals().get("ADMIN_ACHIEVEMENT", {}),
        "DAILY_QUESTS": globals().get("DAILY_QUESTS", {}),
        "WEEKLY_QUESTS": globals().get("WEEKLY_QUESTS", {}),
        "QUEST_SHOP": globals().get("QUEST_SHOP", {}),
        "ai_channels": ai_channels, "log_channels": log_channels,
        "category_log_channels": category_log_channels,
        "BD_UPSTASH_URL": BD_UPSTASH_URL, "BD_UPSTASH_TOKEN": BD_UPSTASH_TOKEN,
        "bd_save_data": bd_save_data, "send_log": send_log,
        "audit_recent": globals().get("audit_recent"), "audit_storage_status": globals().get("audit_storage_status"),
        "recall_guild_data": recall_guild_data,
        "level_from_xp": level_from_xp, "giveaway_embed": _giveaway_embed,
        "giveaway_view": GiveawayView, "finish_giveaway": finish_giveaway,
        "cancel_giveaway": cancel_giveaway, "create_giveaway": _create_giveaway,
        "validate_giveaway_config": _validate_giveaway_config,
        "hg_cog": hg,
        # Guild-scoped Cinnamon Mind, Wildlands, Hangry and merchant state.
        "advanced_features_data": advanced_features_data,
        "brain_storage": {"ready": bd_store.ready, "durable": bd_store.durable,
                          "status": bd_store.status, "pending": bool(bd_store.pending_receipt)},
        "cinnamon_brain": advanced_features_data.setdefault("cinnamon_brain_v1", {}),
        "cinnamon_trusted_actions": advanced_features_data.setdefault("cinnamon_actions_v2", {}),
        "cinnamon_social": advanced_features_data.setdefault("cinnamon_social_v1", {}),
        "cinnamon_actions": advanced_features_data.setdefault("cinnamon_actions_v1", {}),
        "cinnamon_moods": advanced_features_data.setdefault("cinnamon_mood_v1", {}),
        "cinnamon_wildlands_fishing": advanced_features_data.setdefault("wildlands_fishing_v1", {}),
        "cinnamon_wildlands_story": advanced_features_data.setdefault("wildlands_story_v2", {}),
        "wlf_refresh_channel": _wlf_refresh_channel,
        "wlf_active": _wlf_active,
        "wlf_server": _wlf_server,
        "wlf_merchant_names": _WLF_MERCHANTS,
        "wlf_shop_names": _WLF_SHOP_NAMES,
        "wlf_rods": _WLF_RODS,
        "wlf_bait": _WLF_BAIT,
        "wlf_fish": _WLF_FISH,
        "cm_tier": _cm_tier,
        "cp_favourites": _cp_favourites,
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
