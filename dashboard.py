"""Cinnamon's server management dashboard.

Uses Discord OAuth for identity, re-checks guild access on each request, and
runs Discord operations on the bot's event loop. The bot's data persistence
functions are injected by main.py through configure_dashboard().
"""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import html
import json
import logging
import os
import re
import secrets
import hashlib
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from flask import Blueprint, abort, make_response, redirect, render_template_string, request, send_from_directory, session, url_for

log = logging.getLogger("cinnamon.dashboard")
dashboard_bp = Blueprint("cinnamon_dashboard", __name__)
_bot = None
_state_provider = None
_tokens: dict[str, dict[str, Any]] = {}
BASE_URL = "https://discord.com/api/v10"
DEFAULT_REDIRECT = (os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/") or "https://cinnamon-c328.onrender.com") + "/oauth/callback"


def configure_dashboard(bot, state_provider=None):
    """Attach the live bot and a callable returning main.py's current globals."""
    global _bot, _state_provider
    _bot = bot
    _state_provider = state_provider


def _state():
    return _state_provider() if callable(_state_provider) else {}


def _esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def _request_json(url, method="GET", data=None, headers=None):
    request_headers = {
        "User-Agent": "CinnamonDashboard/1.0 (https://cinnamon-c328.onrender.com)",
        "Accept": "application/json",
        **(headers or {}),
    }
    body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _oauth_redirect_uri():
    # Keep the authorization request and token exchange byte-for-byte consistent.
    # Discord requires the redirect_uri used during the code exchange to match
    # the one used to obtain the authorization code.
    return os.getenv("DASHBOARD_REDIRECT_URI", DEFAULT_REDIRECT).strip()


def _token_exchange(data):
    client_id = os.environ["DISCORD_CLIENT_ID"].strip()
    client_secret = os.environ["DISCORD_CLIENT_SECRET"].strip()
    payload = {"client_id": client_id, "client_secret": client_secret, **data}
    return _request_json(
        f"{BASE_URL}/oauth2/token",
        method="POST",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def _access_token(sid):
    record = _tokens.get(sid)
    if not record:
        abort(401)
    if record.get("expires_at", 0) < time.time() + 60:
        refresh = record.get("refresh_token")
        if not refresh:
            _tokens.pop(sid, None)
            abort(401)
        updated = _token_exchange({"grant_type": "refresh_token", "refresh_token": refresh})
        record["access_token"] = updated["access_token"]
        record["refresh_token"] = updated.get("refresh_token", refresh)
        record["expires_at"] = time.time() + int(updated.get("expires_in", 3600))
    return record["access_token"]


def _discord_get(sid, path):
    return _request_json(f"{BASE_URL}{path}", headers={"Authorization": "Bearer " + _access_token(sid)})


def _run_bot(coro, timeout=20):
    if not _bot or not _bot.is_ready():
        coro.close()
        raise RuntimeError("Cinnamon is not ready yet")
    loop = getattr(_bot, "loop", None)
    if not loop or not loop.is_running():
        coro.close()
        raise RuntimeError("Cinnamon event loop is unavailable")
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        # Stop pending work when the request gives up so a retry does not leave
        # a second moderation action or message running in the background.
        future.cancel()
        raise


def _save():
    save_fn = _state().get("bd_save_data")
    if not callable(save_fn):
        raise RuntimeError("Dashboard storage callback is not configured")
    if not _run_bot(save_fn()):
        raise ValueError("The durable save could not be verified. Check storage before trying again.")


def _audit(guild_id, actor, title, detail):
    send_log = _state().get("send_log")
    if callable(send_log):
        try:
            text = f"{title} {detail}".lower()
            if any(x in text for x in ("achievement", "achievement role", "secret achievement")):
                category = "achievements"
            elif any(x in text for x in ("friendship", "cinnamon friendship")):
                category = "friendship"
            elif any(x in text for x in ("quest", "quest shop", "daily quest", "weekly quest")):
                category = "quests"
            elif any(x in text for x in ("economy", "shop item", "catnip")):
                category = "economy"
            elif any(x in text for x in ("giveaway", "poll")):
                category = "community"
            elif any(x in text for x in ("hangry", "hangry games")):
                category = "hangrygames"
            elif any(x in text for x in ("level reward", "level role", "xp")):
                category = "levels"
            elif any(x in text for x in ("role", "reaction")):
                category = "roles"
            elif any(x in text for x in ("welcome", "goodbye", "channel setting", "log channel", "recovery", "setup")):
                category = "setup"
            elif any(x in text for x in ("ai", "gemini")):
                category = "ai"
            elif any(x in text for x in ("moderation", "moderate", "automod", "anti-raid")):
                category = "moderation"
            else:
                category = "general"
            if category == "hangrygames":
                hg = _state().get("hg_cog")
                if hg is not None:
                    _run_bot(hg._log(guild_id, title=title, fields=[("Dashboard actor", str(actor)[:100]), ("Detail", detail[:800])]))
                else:
                    _run_bot(send_log(guild_id, title=title, description=detail[:900], fields=[("Dashboard actor", str(actor)[:100])], category="moderation"))
            else:
                _run_bot(send_log(
                    guild_id, title=title,
                    description=detail[:900],
                    fields=[("Dashboard actor", str(actor)[:100])],
                    category=category,
                ))
            # Every dashboard mutation also gets a copy in the dedicated dashboard audit channel.
            # This is separate from feature-specific logs so admins have one complete audit trail.
            if category != "dashboard":
                _run_bot(send_log(
                    guild_id, title="🧭 Dashboard audit • " + title[:180],
                    description=detail[:900],
                    fields=[("Dashboard actor", str(actor)[:100]), ("Feature log category", category)],
                    category="dashboard",
                ))
        except Exception:
            log.exception("Dashboard audit log failed for guild %s", guild_id)



def _shop_workshop_commit(state, guild_id, actor, actor_id, action, details, rollback):
    """Commit a shop-workshop mutation and its bounded audit event in one snapshot."""
    if not (state.get("BD_UPSTASH_URL") and state.get("BD_UPSTASH_TOKEN")):
        rollback()
        raise ValueError("Shop & Items changes require UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN. Configure both on Render first.")
    advanced = state.get("advanced_features_data")
    if not isinstance(advanced, dict):
        rollback()
        raise RuntimeError("Advanced economy storage is unavailable.")
    root = advanced.setdefault("shop_item_audit_v1", {})
    key = str(int(guild_id))
    previous = copy.deepcopy(root.get(key, []))
    rows = root.setdefault(key, [])
    event = {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "actor": str(actor)[:100],
        "actor_id": int(actor_id),
        "action": str(action)[:80],
        "details": str(details)[:1200],
    }
    rows.append(event)
    del rows[:-500]
    try:
        _save()
    except Exception:
        rollback()
        if previous:
            root[key] = previous
        else:
            root.pop(key, None)
        raise
    send_log = state.get("send_log")
    if callable(send_log):
        try:
            _run_bot(send_log(
                guild_id, title="🧰 Shop & Items • " + str(action)[:180],
                description=str(details)[:900],
                fields=[("Admin", f"{actor} ({actor_id})"), ("Audit storage", "Upstash snapshot committed")],
                category="shop_items",
            ))
        except Exception:
            log.exception("Shop & Items Discord log failed for guild %s", guild_id)


def _shop_items(guild, state):
    """No-code catalogue, crafting and mystery-box reward workshop."""
    gid = guild.id
    shop = state.get("ECONOMY_ITEMS", {})
    recipes = state.get("CRAFTING_RECIPES", {})
    advanced = state.get("advanced_features_data", {})
    custom_recipes = advanced.get("custom_crafting_recipes_v1", {}) if isinstance(advanced, dict) else {}
    disabled_recipes = set(advanced.get("disabled_crafting_recipes_v1", [])) if isinstance(advanced, dict) else set()
    box_root = advanced.get("custom_box_rewards", {}) if isinstance(advanced, dict) else {}
    tiers = state.get("BOX_TIERS", {})
    storage_ok = bool(state.get("BD_UPSTASH_URL") and state.get("BD_UPSTASH_TOKEN"))
    storage = "<span class='pill good'>Upstash configured</span>" if storage_ok else "<span class='pill warn'>Upstash not configured</span>"
    channel_id = state.get("category_log_channels", {}).get(gid, {}).get("shop_items")
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    channel_form = _form(gid, "shop_items_log_channel",
        "<div class='field'><label>Dedicated Shop & Items log channel</label>" +
        _channel_select(guild, "channel_id", channel_id) +
        "<small>Admin changes are sent here. Audit records are also committed to the Upstash snapshot.</small></div>",
        "Save log channel")
    item_rows = []
    item_dialogs = []
    shop_builder_items = [
        {"id": str(item_id), "name": str(item.get("name", item_id)), "emoji": str(item.get("emoji", "🐾"))}
        for item_id, item in shop.items() if isinstance(item, dict)
    ]
    shop_builder_roles = [
        {"id": str(role.id), "name": str(role.name)}
        for role in getattr(guild, "roles", [])
        if not role.is_default() and not role.managed
    ]
    shop_builder_items_json = _esc(json.dumps(shop_builder_items, ensure_ascii=False))
    shop_builder_roles_json = _esc(json.dumps(shop_builder_roles, ensure_ascii=False))
    for item_id, item in sorted(shop.items(), key=lambda pair: str((pair[1] if isinstance(pair[1], dict) else {}).get("name", pair[0])).casefold()):
        item = item if isinstance(item, dict) else {}
        sell_value = item.get("sell_price")
        fields = (
            f"<input type='hidden' name='item_id' value='{_esc(item_id)}'>"
            f"<div class='shop-editor-section'><h3>Item details</h3>"

            f"<div class='field'><label>Name</label><input name='name' maxlength='80' value='{_esc(item.get('name', item_id))}' required></div>"
            f"<div class='field'><label>Buy price (Catnip)</label><input name='price' type='number' min='1' max='10000000' value='{max(1,int(item.get('price',1)))}' required></div>"
            f"<div class='field'><label>Sell-back price (Catnip)</label><input name='sell_price' type='number' min='0' max='10000000' value='{'' if sell_value is None else max(0,int(sell_value))}' placeholder='Default: 50% of buy price'></div>"
            f"<div class='field'><label>Category</label><input name='category' maxlength='40' value='{_esc(item.get('category','General'))}' placeholder='General, GAG Services, Materials…'></div>"
            f"<div class='field'><label>Description</label><textarea name='description' maxlength='300' rows='3'>{_esc(item.get('description',''))}</textarea></div>"
            f"<div class='field'><label>Icon / emoji</label><input name='emoji' maxlength='8' value='{_esc(item.get('emoji','🐾'))}'></div></div>"
            f"<div class='shop-editor-section'><h3>Availability & inventory</h3>"
            f"<label class='toggle'><input type='checkbox' name='shop_enabled'{' checked' if item.get('shop_enabled', True) else ''}><span><b>Listed in shop</b><small>Members can see and purchase this item.</small></span></label>"
            f"<label class='toggle'><input type='checkbox' name='craftable'{' checked' if item.get('craftable', False) else ''}><span><b>Craftable output</b><small>This item can be the output of a crafting recipe.</small></span></label>"
            f"<label class='toggle'><input type='checkbox' name='sellable'{' checked' if item.get('sellable', True) else ''}><span><b>Sell-back enabled</b><small>Members may sell eligible items using /economy sell.</small></span></label>"
            f"<div class='field'><label>Maximum quantity per member</label><input name='max_per_person' type='number' min='0' max='999999' value='{max(0,int(item.get('max_per_person',0)))}'><small>0 means unlimited.</small></div>"
            f"<label class='toggle'><input type='checkbox' name='stock_unlimited'{' checked' if item.get('stock_unlimited', True) else ''}><span><b>Unlimited stock</b><small>Turn off to enforce a fixed stock quantity.</small></span></label>"
            f"<div class='field'><label>Stock quantity</label><input name='stock_quantity' type='number' min='0' max='100000000' value='{max(0,int(item.get('stock_quantity',0)))}'></div>"
            f"<div class='field'><label>Expiry date/time (ISO 8601)</label><input name='expires_at' value='{_esc(item.get('expires_at',''))}' placeholder='2026-12-31T23:59:00+00:00'></div>"
            f"<label class='toggle'><input type='checkbox' name='usable'{' checked' if item.get('usable', False) else ''}><span><b>Usable item</b><small>Members can use it with /economy use.</small></span></label>"
            f"<label class='toggle'><input type='checkbox' name='reusable'{' checked' if item.get('reusable', False) else ''}><span><b>Reusable</b><small>Using it does not consume one unit.</small></span></label>"
            f"<div class='field'><label>Use cooldown (seconds)</label><input name='use_cooldown_seconds' type='number' min='0' max='31536000' value='{max(0,int(item.get('use_cooldown_seconds',0)))}'></div></div>"
            f"<div class='shop-editor-section'><h3>Purchase requirements</h3><p class='muted'>Set who can buy this item. These rules are separate from use requirements.</p>"
            f"<textarea hidden name='purchase_requirements'>{_esc(json.dumps(item.get('purchase_requirements',{}),ensure_ascii=False))}</textarea>"
            f"<div class='shop-requirement-builder' data-config-builder='purchase_requirements' data-items='{shop_builder_items_json}' data-roles='{shop_builder_roles_json}'></div></div>"
            f"<div class='shop-editor-section'><h3>Use requirements</h3><p class='muted'>Set who can use this item. These rules are checked separately.</p>"
            f"<textarea hidden name='use_requirements'>{_esc(json.dumps(item.get('use_requirements',{}),ensure_ascii=False))}</textarea>"
            f"<div class='shop-requirement-builder' data-config-builder='use_requirements' data-items='{shop_builder_items_json}' data-roles='{shop_builder_roles_json}'></div></div>"
            f"<div class='shop-editor-section'><h3>Actions</h3><p class='muted'>Choose when each effect runs: after purchase, after use, or either event.</p>"
            f"<textarea hidden name='item_actions'>{_esc(json.dumps(item.get('actions',[]),ensure_ascii=False))}</textarea>"
            f"<div class='shop-action-builder' data-config-builder='item_actions' data-items='{shop_builder_items_json}'></div></div>"
            f"<div class='shop-editor-section'><h3>Random outcomes</h3><p class='muted'>Add as many outcomes as you need. Configure separate outcome chances for buying and using; weights for each trigger must total 100%.</p>"
            f"<textarea hidden name='random_outcomes'>{_esc(json.dumps(item.get('random_outcomes',[]),ensure_ascii=False))}</textarea>"
            f"<div class='shop-outcome-builder' data-config-builder='random_outcomes' data-items='{shop_builder_items_json}'></div></div>"
        )
        editor = _form(gid, "shop_item_save", fields, "Save changes")
        remove_form = _form(gid, "shop_item_disable", f"<input type='hidden' name='item_id' value='{_esc(item_id)}'>", "Remove from shop", danger=True)
        item_dialogs.append(
            f"<dialog class='shop-item-dialog' id='shop-edit-{_esc(item_id)}'><div class='shop-dialog-head'><div><span class='eyebrow'>ITEM EDITOR</span><h2>{_esc(item.get('name',item_id))}</h2></div><button type='button' class='shop-dialog-close' data-shop-close aria-label='Close editor'>×</button></div>"
            f"<div class='shop-dialog-body'>{editor}<div class='shop-dialog-danger'>{remove_form}</div></div></dialog>"
        )
        item_rows.append(
            f"<button type='button' class='shop-product-tile' data-shop-open='shop-edit-{_esc(item_id)}'>"
            f"<span class='shop-product-icon'>{_esc(item.get('emoji','🐾'))}</span><span class='shop-product-name'>{_esc(item.get('name',item_id))}</span>"
            f"<span class='shop-product-price'>{max(0,int(item.get('price',0))):,} <small>Catnip</small></span><span class='shop-product-edit'>Edit item</span></button>"
        )
    item_grid = "".join(item_rows) or "<p class='muted'>No items yet. Create your first item.</p>"
    create_fields = (
        "<div class='shop-editor-section'><h3>Item details</h3>"
        "<div class='field'><label>Item key (optional)</label><input name='item_id' maxlength='40' pattern='[a-zA-Z0-9_-]+' placeholder='Generated from the item name if blank'><small>Leave blank and Cinnamon will generate it automatically.</small></div>"
        "<div class='field'><label>Name</label><input name='name' maxlength='80' required placeholder='Give this item a name'></div>"
        "<div class='field'><label>Buy price (Catnip)</label><input name='price' type='number' min='1' max='10000000' value='1000' required></div>"
        "<div class='field'><label>Sell-back price (Catnip)</label><input name='sell_price' type='number' min='0' max='10000000' placeholder='Default: 50% of buy price'></div>"
        "<div class='field'><label>Category</label><input name='category' maxlength='40' value='General'></div>"
        "<div class='field'><label>Description</label><textarea name='description' maxlength='300' rows='3'></textarea></div>"
        "<div class='field'><label>Icon / emoji</label><input name='emoji' maxlength='8' value='🐾'></div></div>"
        "<div class='shop-editor-section'><h3>Availability & inventory</h3>"
        "<label class='toggle'><input type='checkbox' name='shop_enabled' checked><span><b>Listed in shop</b><small>Members can see and purchase this item.</small></span></label>"
        "<label class='toggle'><input type='checkbox' name='craftable'><span><b>Craftable output</b><small>This item can be the output of a crafting recipe.</small></span></label>"
        "<label class='toggle'><input type='checkbox' name='sellable' checked><span><b>Sell-back enabled</b><small>Members may sell eligible items using /economy sell.</small></span></label>"
        "<div class='field'><label>Maximum quantity per member</label><input name='max_per_person' type='number' min='0' max='999999' value='0'><small>0 means unlimited.</small></div>"
        "<label class='toggle'><input type='checkbox' name='stock_unlimited' checked><span><b>Unlimited stock</b><small>Turn off to enforce fixed stock.</small></span></label>"
        "<div class='field'><label>Stock quantity</label><input name='stock_quantity' type='number' min='0' max='100000000' value='0'></div>"
        "<div class='field'><label>Expiry date/time (ISO 8601)</label><input name='expires_at' placeholder='2026-12-31T23:59:00+00:00'></div>"
        "<label class='toggle'><input type='checkbox' name='usable'><span><b>Usable item</b><small>Members can use it with /economy use.</small></span></label>"
        "<label class='toggle'><input type='checkbox' name='reusable'><span><b>Reusable</b><small>Using it does not consume one unit.</small></span></label>"
        "<div class='field'><label>Use cooldown (seconds)</label><input name='use_cooldown_seconds' type='number' min='0' max='31536000' value='0'></div></div>"
        "<div class='shop-editor-section'><h3>Purchase requirements</h3><p class='muted'>Set who can buy this item.</p><textarea hidden name='purchase_requirements'>{}</textarea><div class='shop-requirement-builder' data-config-builder='purchase_requirements' data-items='" + shop_builder_items_json + "' data-roles='" + shop_builder_roles_json + "'></div></div>"
        "<div class='shop-editor-section'><h3>Use requirements</h3><p class='muted'>Set who can use this item.</p><textarea hidden name='use_requirements'>{}</textarea><div class='shop-requirement-builder' data-config-builder='use_requirements' data-items='" + shop_builder_items_json + "' data-roles='" + shop_builder_roles_json + "'></div></div>"
        "<div class='shop-editor-section'><h3>Actions</h3><p class='muted'>Choose whether each effect runs when bought, used or both.</p><textarea hidden name='item_actions'>[]</textarea><div class='shop-action-builder' data-config-builder='item_actions' data-items='" + shop_builder_items_json + "'></div></div>"
        "<div class='shop-editor-section'><h3>Random outcomes</h3><p class='muted'>Add as many outcomes as you need. Weights for each trigger must total 100%.</p><textarea hidden name='random_outcomes'>[]</textarea><div class='shop-outcome-builder' data-config-builder='random_outcomes' data-items='" + shop_builder_items_json + "'></div></div>"
    )
    create_editor = _form(gid, "shop_item_add", create_fields, "Create item")
    create_dialog = (
        "<dialog class='shop-item-dialog' id='shop-create-dialog'><div class='shop-dialog-head'><div><span class='eyebrow'>NEW CATALOGUE ITEM</span><h2>Create item</h2></div><button type='button' class='shop-dialog-close' data-shop-close aria-label='Close editor'>×</button></div>"
        "<div class='shop-dialog-body'>" + create_editor + "</div></dialog>"
    )
    shop_editor_ui = (
        "<style>"
        ".shop-catalog-toolbar{display:flex;grid-column:1/-1;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin:18px 0 14px;min-width:0}"
        ".shop-product-grid{display:grid;grid-column:1/-1;grid-template-columns:repeat(auto-fit,minmax(min(100%,190px),1fr));gap:14px;width:100%;min-width:0;box-sizing:border-box}"
        ".shop-product-tile{appearance:none;width:100%;min-width:0;box-sizing:border-box;border:1px solid var(--line);background:var(--surface-2);color:var(--text);border-radius:16px;min-height:174px;padding:18px 12px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;text-align:center;cursor:pointer;transition:transform .16s,border-color .16s,box-shadow .16s}"
        ".shop-product-tile:hover{transform:translateY(-2px);border-color:var(--accent);box-shadow:0 8px 24px #0002}"
        ".shop-create-tile{border:2px dashed var(--accent);background:color-mix(in srgb,var(--accent) 7%,var(--surface-2))}"
        ".shop-product-icon{font-size:42px;line-height:1.2;min-height:52px;display:grid;place-items:center}.shop-product-name{font-weight:750;line-height:1.25;overflow-wrap:anywhere}"
        ".shop-product-price{font-size:18px;font-weight:800;color:var(--accent)}.shop-product-price small{font-size:11px;font-weight:600;color:var(--muted)}.shop-product-edit{font-size:12px;color:var(--muted)}"
        ".shop-recipe-grid{display:grid;grid-column:1/-1;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:14px;width:100%;min-width:0;box-sizing:border-box}.shop-recipe-card{min-width:0;width:100%;box-sizing:border-box;overflow-wrap:anywhere}.shop-recipe-card form{min-width:0}.shop-recipe-card input,.shop-recipe-card select,.shop-recipe-card textarea{max-width:100%;box-sizing:border-box}.shop-item-dialog{border:1px solid var(--line);border-radius:18px;padding:0;width:min(680px,calc(100vw - 24px));max-height:min(88dvh,900px);background:var(--surface);color:var(--text);box-shadow:0 24px 80px #0008}"
        ".shop-item-dialog[open]{display:block}.shop-item-dialog::backdrop{background:#09070bd9;backdrop-filter:blur(4px)}.shop-dialog-head{position:sticky;top:0;z-index:2;display:flex;align-items:center;justify-content:space-between;padding:18px 22px;background:var(--surface);border-bottom:1px solid var(--line)}"
        ".shop-dialog-head h2{margin:4px 0 0}.shop-dialog-close{border:0;background:var(--surface-2);color:var(--text);width:40px;height:40px;border-radius:12px;font-size:26px;cursor:pointer}"
        ".shop-dialog-body{padding:18px 22px 24px;overflow:auto;max-height:calc(88dvh - 82px)}.shop-editor-section{border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:14px}.shop-editor-section h3{margin:0 0 12px}"
        ".shop-editor-section textarea{width:100%;resize:vertical}.shop-builder-field{display:flex;flex-direction:column;gap:6px;margin:10px 0;font-size:13px;font-weight:650}.shop-builder-field input,.shop-builder-field select,.shop-builder-field textarea,.shop-builder-inline select,.shop-builder-inline input{width:100%;min-height:40px;border:1px solid var(--line-strong);border-radius:9px;background:var(--surface-2);padding:8px 10px;color:var(--ink)}.shop-builder-field select[multiple]{min-height:96px}.shop-builder-list{display:grid;gap:10px;margin:10px 0}.shop-builder-row,.shop-builder-outcome{border:1px solid var(--line);background:var(--surface-2);border-radius:12px;padding:12px;margin:8px 0}.shop-builder-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.shop-builder-inline{display:grid;grid-template-columns:minmax(0,1fr) 100px 42px;gap:8px;margin:8px 0}.shop-builder-button,.shop-builder-remove{border:1px solid var(--line-strong);border-radius:9px;padding:9px 12px;background:var(--surface-3);font-weight:650;cursor:pointer}.shop-builder-remove{color:var(--red)}.shop-builder-outcome h4{margin:8px 0}.shop-dialog-danger{border-top:1px solid var(--line);margin-top:18px;padding-top:14px}.shop-dialog-body .actions{position:sticky;bottom:-24px;background:var(--surface);padding:12px 0 2px}"
        "@media(max-width:520px){.shop-product-grid{grid-template-columns:repeat(auto-fit,minmax(min(100%,140px),1fr));gap:10px}.shop-recipe-grid{grid-template-columns:minmax(0,1fr);gap:10px}.shop-product-tile{min-height:150px;padding:14px 8px}.shop-product-icon{font-size:36px}.shop-dialog-head{padding:14px 16px}.shop-dialog-body{padding:14px 16px 20px}}"
        "</style><div class='shop-catalog-toolbar'><div><h2>Shop catalogue</h2><p class='muted'>Tap an item card to edit it.</p></div><span class='pill'>" + str(len(shop)) + " items</span></div>"
        "<div class='shop-product-grid'><button type='button' class='shop-product-tile shop-create-tile' data-shop-open='shop-create-dialog'><span class='shop-product-icon'>＋</span><span class='shop-product-name'>CREATE ITEM</span><span class='shop-product-edit'>Add to catalogue</span></button>"
        + item_grid + "</div>" + "".join(item_dialogs) + create_dialog
        + "<script>(function(){if(window.__cinnamonShopEditorReady)return;window.__cinnamonShopEditorReady=true;"
        + "function node(tag,cls,txt){var n=document.createElement(tag);if(cls)n.className=cls;if(txt!==undefined)n.textContent=txt;return n;}"
        + "function field(label,control){var w=node('label','shop-builder-field');w.appendChild(node('span','',label));w.appendChild(control);return w;}"
        + "function select(options,value){var s=node('select');options.forEach(function(o){var x=node('option','',o[1]);x.value=o[0];if(String(value)===String(o[0]))x.selected=true;s.appendChild(x);});return s;}"
        + "function input(type,value,placeholder){var x=node('input');x.type=type;x.value=value==null?'':value;if(placeholder)x.placeholder=placeholder;return x;}"
        + "function button(label,cls,fn){var b=node('button',cls||'shop-builder-button',label);b.type='button';b.addEventListener('click',fn);return b;}"
        + "function itemOptions(items){return [['','Choose an item']].concat(items.map(function(x){return [x.id,(x.emoji||'')+' '+x.name+' ('+x.id+')'];}));}"
        + "function effectRow(items,cfg,nested){cfg=cfg||{};var row=node('div','shop-builder-row');var type=select([['give_catnip','Give Catnip'],['give_item','Give an item'],['send_message','Send a message'],['reply','Reply to the member']],cfg.type||'give_catnip');var trigger=nested?null:select([['bought','When bought'],['used','When used'],['both','When bought or used']],cfg.trigger||'both');var amount=input('number',cfg.amount||'','Amount');var item=select(itemOptions(items),cfg.item_id||'');var message=node('textarea');message.rows=2;message.placeholder='Message to send';message.value=cfg.message||'';var remove=button('Remove','shop-builder-remove',function(){row.remove();});if(trigger)row.appendChild(field('Trigger',trigger));row.appendChild(field('Effect',type));row.appendChild(field('Catnip amount',amount));row.appendChild(field('Reward item',item));row.appendChild(field('Message',message));row.appendChild(remove);function sync(){var k=type.value;amount.parentElement.hidden=k!=='give_catnip';item.parentElement.hidden=k!=='give_item';message.parentElement.hidden=k!=='send_message'&&k!=='reply';}type.addEventListener('change',sync);sync();row.readConfig=function(){var o={type:type.value};if(trigger)o.trigger=trigger.value;if(type.value==='give_catnip')o.amount=Number(amount.value);if(type.value==='give_item'){o.item_id=item.value;o.amount=Number(amount.value||1);}if(type.value==='send_message'||type.value==='reply')o.message=message.value;return o;};return row;}"
        + "function effectList(host,items,configs,nested){(configs||[]).forEach(function(c){host.appendChild(effectRow(items,c,nested));});host.appendChild(button('＋ Add effect','shop-builder-button',function(){host.insertBefore(effectRow(items,{type:'give_catnip',amount:100,trigger:'both'},nested),host.lastChild);}));}"
        + "function buildRequirement(root,hidden){var items=JSON.parse(root.dataset.items||'[]'),roles=JSON.parse(root.dataset.roles||'[]'),cfg={};try{cfg=JSON.parse(hidden.value||'{}');}catch(e){}var bal=input('number',cfg.balance_min||0,'Minimum Catnip');root.appendChild(field('Minimum balance (Catnip)',bal));var rcfg=cfg.roles||{},rmode=select([['all','Has all selected roles'],['any','Has any selected role'],['none','Has none of these roles']],rcfg.mode||'all');root.appendChild(field('Role condition',rmode));var rselect=node('select');rselect.multiple=true;rselect.size=Math.min(5,Math.max(2,roles.length));roles.forEach(function(r){var o=node('option','',r.name);o.value=r.id;o.selected=(rcfg.ids||[]).map(String).includes(String(r.id));rselect.appendChild(o);});root.appendChild(field('Required roles (select multiple)',rselect));var icfg=cfg.items||{},imode=select([['all','Has all required items'],['any','Has any required item'],['none','Has none of these items']],icfg.mode||'all');root.appendChild(field('Inventory condition',imode));var list=node('div','shop-builder-list');var entries=icfg.entries||{};Object.keys(entries).forEach(function(id){addReq(id,entries[id]);});function addReq(id,qty){var row=node('div','shop-builder-inline');var sel=select(itemOptions(items),id);var q=input('number',qty||1,'Quantity');var rm=button('×','shop-builder-remove',function(){row.remove();});row.appendChild(sel);row.appendChild(q);row.appendChild(rm);list.appendChild(row);}root.appendChild(list);root.appendChild(button('＋ Add required item','shop-builder-button',function(){addReq('',1);}));root.readConfig=function(){var ent={};list.querySelectorAll('.shop-builder-inline').forEach(function(row){var id=row.querySelector('select').value,qty=Number(row.querySelector('input').value);if(id&&qty>0)ent[id]=qty;});var ids=Array.from(rselect.selectedOptions).map(function(o){return o.value;});var out={balance_min:Number(bal.value||0)};if(ids.length)out.roles={mode:rmode.value,ids:ids};if(Object.keys(ent).length)out.items={mode:imode.value,entries:ent};return out;};}"
        + "function buildActions(root,hidden,items){var cfg=[];try{cfg=JSON.parse(hidden.value||'[]');}catch(e){}var list=node('div','shop-builder-list');(cfg||[]).forEach(function(c){list.appendChild(effectRow(items,c,false));});root.appendChild(list);root.appendChild(button('＋ Add action','shop-builder-button',function(){list.appendChild(effectRow(items,{type:'give_catnip',amount:100,trigger:'both'},false));}));root.readConfig=function(){return Array.from(list.children).filter(function(x){return x.readConfig;}).map(function(x){return x.readConfig();});};}"
        + "function buildOutcomes(root,hidden,items){var cfg=[];try{cfg=JSON.parse(hidden.value||'[]');}catch(e){}var list=node('div','shop-builder-list');function addOutcome(c){c=c||{trigger:'both',weight:100,actions:[]};var card=node('div','shop-builder-outcome');var trig=select([['bought','When bought'],['used','When used'],['both','When bought or used']],c.trigger||'both');var weight=input('number',c.weight||100,'Weight %');var effects=node('div','shop-builder-list');effectList(effects,items,c.actions||[],true);card.appendChild(field('Trigger',trig));card.appendChild(field('Chance weight (%)',weight));card.appendChild(node('h4','','Outcome effects'));card.appendChild(effects);card.appendChild(button('Remove outcome','shop-builder-remove',function(){card.remove();}));card.readConfig=function(){return {trigger:trig.value,weight:Number(weight.value),actions:Array.from(effects.children).filter(function(x){return x.readConfig;}).map(function(x){return x.readConfig();})};};list.appendChild(card);} (cfg||[]).forEach(addOutcome);root.appendChild(list);root.appendChild(button('＋ Add random outcome','shop-builder-button',function(){addOutcome({trigger:'both',weight:100,actions:[]});}));root.readConfig=function(){return Array.from(list.children).filter(function(x){return x.readConfig;}).map(function(x){return x.readConfig();});};}"
        + "function initDialog(d){if(d.dataset.shopBuildersReady)return;d.dataset.shopBuildersReady='1';d.querySelectorAll('[data-config-builder]').forEach(function(root){var hidden=d.querySelector('[name="'+root.dataset.configBuilder+'"]');if(!hidden)return;var items=JSON.parse(root.dataset.items||'[]');if(root.classList.contains('shop-requirement-builder'))buildRequirement(root,hidden);else if(root.classList.contains('shop-action-builder'))buildActions(root,hidden,items);else if(root.classList.contains('shop-outcome-builder'))buildOutcomes(root,hidden,items);});var form=d.querySelector('form');if(form)form.addEventListener('submit',function(){d.querySelectorAll('[data-config-builder]').forEach(function(root){var hidden=d.querySelector('[name="'+root.dataset.configBuilder+'"]');if(hidden&&root.readConfig)hidden.value=JSON.stringify(root.readConfig());});});}"
        + "document.addEventListener('click',function(e){var node=e.target;while(node&&node.nodeType!==1)node=node.parentElement;var open=null,close=null;for(var el=node;el&&el!==document;el=el.parentElement){if(!open&&el.matches&&el.matches('[data-shop-open]'))open=el;if(!close&&el.matches&&el.matches('[data-shop-close]'))close=el;}if(open){e.preventDefault();e.stopPropagation();var id=open.getAttribute('data-shop-open');var d=id?document.getElementById(id):null;if(d){try{initDialog(d);}catch(err){console.error('Cinnamon shop editor initialization failed',err);}try{if(d.showModal&&!d.open)d.showModal();else d.setAttribute('open','');}catch(err){d.setAttribute('open','');}}}if(close){e.preventDefault();e.stopPropagation();var dialog=close.closest('dialog');if(dialog&&dialog.close)dialog.close();else if(dialog)dialog.removeAttribute('open');}if(node&&node.matches&&node.matches('dialog.shop-item-dialog')){if(node.close)node.close();else node.removeAttribute('open');}},true);})();</script>"
    )
    item_options = "".join(
        f"<option value='{_esc(k)}'>{_esc(v.get('emoji','🐾'))} {_esc(v.get('name',k))}</option>"
        for k, v in sorted(shop.items()) if isinstance(v, dict)
    )
    def ingredient_picker(selected=None):
        selected={str(k):max(1,int(v)) for k,v in (selected or {}).items() if str(k) in shop}
        rows=[]
        for item_id,item in sorted(shop.items(),key=lambda pair:str((pair[1] or {}).get("name",pair[0])).casefold()):
            if not isinstance(item,dict): continue
            rid=str(item_id); checked=" checked" if rid in selected else ""
            quantity=selected.get(rid,1)
            rows.append(f"<label class='choice-option' data-choice-label='{_esc(str(item.get('name',rid)).lower())}'><input type='checkbox' name='ingredient_item_ids' value='{_esc(rid)}'{checked}><span>{_esc(str(item.get('emoji','🐾'))+' '+str(item.get('name',rid)))}</span><input aria-label='Quantity for {_esc(str(item.get('name',rid)))}' type='number' name='ingredient_quantity_{_esc(rid)}' min='1' max='999' value='{quantity}' style='width:84px;margin-left:auto'></label>")
        return "<div class='choice-picker' data-choice-picker><div class='choice-toolbar'><input class='choice-search' type='search' placeholder='Search catalogue items…' aria-label='Search recipe ingredients' autocomplete='off'><span class='choice-count' aria-live='polite'></span></div><div class='choice-options'>"+("".join(rows) or "<p class='muted'>No catalogue items available.</p>")+"</div><small class='choice-help'>Select ingredients by their names and set the quantity for each.</small></div>"
    recipe_rows = []
    recipe_dialogs = []
    for recipe_id, recipe in sorted(recipes.items()):
        ingredients_text = "\\n".join(f"{shop.get(k,{}).get('name',k)}:{v}" for k, v in recipe.get("ingredients", {}).items())
        output_options = "".join(
            "<option value='" + _esc(k) + "'" +
            (" selected" if k == recipe.get("output") else "") + ">" +
            _esc(v.get("name", k)) + "</option>"
            for k, v in sorted(shop.items()) if isinstance(v, dict)
        )
        recipe_fields = (
            f"<input type='hidden' name='recipe_id' value='{_esc(recipe_id)}'>"
            f"<div class='field'><label>Recipe name</label><input name='name' maxlength='80' value='{_esc(recipe.get('name',recipe_id))}' required></div>"
            f"<div class='field'><label>Emoji</label><input name='emoji' maxlength='8' value='{_esc(recipe.get('emoji','🧪'))}'></div>"
            f"<div class='field'><label>Output item</label><select name='output' required>{output_options}</select></div>"
            f"<div class='field' style='grid-column:1/-1'><label>Ingredients</label>{ingredient_picker(recipe.get('ingredients',{}))}</div>"
            f"<div class='field' style='grid-column:1/-1'><label>Description</label><input name='description' maxlength='300' value='{_esc(recipe.get('description',''))}'></div>"
        )
        recipe_dialog_id="shop-recipe-edit-"+str(recipe_id)
        recipe_editor=_form(gid,"shop_recipe_save",recipe_fields,"Save recipe")
        recipe_remove=_form(gid,"shop_recipe_remove",f"<input type='hidden' name='recipe_id' value='{_esc(recipe_id)}'>","Disable recipe",danger=True)
        recipe_dialogs.append(f"<dialog class='shop-item-dialog' id='{_esc(recipe_dialog_id)}'><div class='shop-dialog-head'><div><span class='eyebrow'>RECIPE EDITOR</span><h2>{_esc(recipe.get('name',recipe_id))}</h2></div><button type='button' class='shop-dialog-close' data-shop-close aria-label='Close editor'>×</button></div><div class='shop-dialog-body'>{recipe_editor}<div class='shop-dialog-danger'>{recipe_remove}</div></div></dialog>")
        recipe_rows.append("<button type='button' class='shop-product-tile shop-recipe-card' data-shop-open='"+_esc(recipe_dialog_id)+"'><span class='shop-product-icon'>"+_esc(recipe.get("emoji","🧪"))+"</span><span class='shop-product-name'>"+_esc(recipe.get("name",recipe_id))+"</span><span class='shop-product-edit'>Edit recipe</span></button>")
    recipe_add = (
        "<div class='formgrid'><div class='field'><label>Recipe ID (optional; generated from the name)</label><input name='recipe_id' maxlength='40' pattern='[a-zA-Z0-9_-]+' placeholder='Auto-generated if blank'></div>"
        "<div class='field'><label>Recipe name</label><input name='name' maxlength='80' required></div>"
        "<div class='field'><label>Emoji</label><input name='emoji' maxlength='8' value='🧪'></div>"
        f"<div class='field'><label>Output item</label><select name='output' required>{item_options}</select></div>"
        "<div class='field' style='grid-column:1/-1'><label>Ingredients</label>"+ingredient_picker()+"</div>"
        "<div class='field' style='grid-column:1/-1'><label>Description</label><input name='description' maxlength='300'></div></div>"
    )
    recipe_card = "<article class='card full'><h2>Create or edit a crafting recipe</h2><p class='muted'>Every ingredient must already exist in the item catalogue. Recipe output items are automatically marked craftable.</p>" + _form(gid, "shop_recipe_save", recipe_add, "Save recipe") + "</article>"
    recipe_grid = "<div class='shop-recipe-grid'>" + ("".join(recipe_rows) or "<article class='card shop-recipe-card'><p class='muted'>No active recipes.</p></article>") + "</div>"

    box_cards = []
    for tier, cfg in tiers.items():
        custom = box_root.get(f"{gid}:{tier}", {}) if isinstance(box_root, dict) else {}
        disabled_items = set(str(x) for x in custom.get("disabled_items", []))
        disabled_materials = set(str(x) for x in custom.get("disabled_materials", []))
        weights = custom.get("weights", {}) if isinstance(custom.get("weights", {}), dict) else {}
        if tier == "common":
            distribution_defaults = {"catnip_small":29,"item_common":28,"xp":14,"material":12,"catnip_big":9,"item_rare":6,"rare_crown":2}
            distribution_key = "category_weights"
            distribution_label = "Common box outcome weights"
        else:
            distribution_defaults = {"catnip":55,"items":35,"materials":10}
            distribution_key = "outcome_weights"
            distribution_label = "Reward type weights"
        distribution = custom.get(distribution_key, {}) if isinstance(custom.get(distribution_key, {}), dict) else {}
        distribution_fields = [f"<input type='hidden' name='tier' value='{_esc(tier)}'>"]
        for outcome_name, default_weight in distribution_defaults.items():
            try:
                outcome_weight = max(0, min(1000000, int(distribution.get(outcome_name, default_weight))))
            except (TypeError, ValueError):
                outcome_weight = default_weight
            distribution_fields.append(
                f"<div class='field'><label>{_esc(outcome_name.replace('_',' ').title())} weight</label>"
                f"<input name='weight_{_esc(outcome_name)}' type='number' min='0' max='1000000' value='{outcome_weight}' required></div>"
            )
        distribution_form = _form(gid, "shop_box_distribution", "".join(distribution_fields),
                                  "Save outcome weights")
        pool_forms = []
        pool_definitions = [("items", "Items", cfg.get("items", [])),
                            ("materials", "Materials", cfg.get("materials", []))]
        if tier == "common":
            pool_definitions.append(("rare_items", "Rare items", state.get("BOX_RARE_ITEM_POOL", [])))
        for kind, label, base_ids in pool_definitions:
            disabled_key = f"disabled_{kind}"
            disabled_pool = set(str(x) for x in custom.get(disabled_key, []))
            active = [str(x) for x in base_ids if str(x) not in disabled_pool]
            active += [str(x) for x in custom.get(kind, []) if str(x) not in disabled_pool]
            active = list(dict.fromkeys(x for x in active if x in shop))
            rows = []
            for item_id in active:
                item = shop.get(item_id, {})
                try:
                    weight = max(1, min(1000000, int(weights.get(item_id, 1))))
                except (TypeError, ValueError):
                    weight = 1
                fields = f"<input type='hidden' name='tier' value='{_esc(tier)}'><input type='hidden' name='pool_kind' value='{kind}'><input type='hidden' name='item_id' value='{_esc(item_id)}'><div class='field'><label>Weight for {_esc(item.get('name',item_id))}</label><input name='weight' type='number' min='1' max='1000000' value='{weight}' required></div>"
                rows.append("<div class='toggle'><span><b>" + _esc(item.get("emoji","🐾")) + " " + _esc(item.get("name",item_id)) + "</b><small>" + _esc(item_id) + "</small></span><div class='actions'>" +
                    _form(gid, "shop_box_weight", fields, "Update weight") +
                    _form(gid, "shop_box_reward_remove", f"<input type='hidden' name='tier' value='{_esc(tier)}'><input type='hidden' name='pool_kind' value='{kind}'><input type='hidden' name='item_id' value='{_esc(item_id)}'>", "Remove", danger=True) +
                    "</div></div>")
            add_fields = f"<input type='hidden' name='tier' value='{_esc(tier)}'><input type='hidden' name='pool_kind' value='{kind}'><div class='field'><label>Add existing item to {label.lower()}</label><select name='item_id' required>{item_options}</select></div><div class='field'><label>Reward weight</label><input name='weight' type='number' min='1' max='1000000' value='1' required></div>"
            pool_forms.append("<div class='card half'><h3>" + label + "</h3>" + ("".join(rows) or "<p class='muted'>No active rewards in this pool.</p>") + _form(gid, "shop_box_reward_add", add_fields, "Add reward") + "</div>")
        box_cards.append("<article class='card full'><h2>" + _esc(cfg.get("emoji","📦")) + " " + _esc(cfg.get("label",tier.title())) + " Mystery Box</h2><p class='muted'>" + _esc(distribution_label) + ": set any weight to zero to disable that outcome. At least one outcome weight must remain above zero. Item weights are relative within their reward pool.</p>" + distribution_form + "<div class='grid'>" + "".join(pool_forms) + "</div></article>")

    audit_rows = advanced.get("shop_item_audit_v1", {}).get(str(gid), []) if isinstance(advanced, dict) else []
    audit_html = "".join(
        "<div class='rowitem'><div class='rowmain'><b>" + _esc(entry.get("action","Change")) + "</b><small>" +
        _esc(entry.get("at","")) + " · " + _esc(entry.get("actor","admin")) + " · " + _esc(entry.get("details","")) +
        "</small></div></div>" for entry in reversed(audit_rows[-30:])
    ) or "<p class='muted'>No Shop & Items changes recorded yet.</p>"
    restore_form = _form(
        gid, "shop_catalog_restore", "",
        "Restore missing built-in items",
    )
    restore_card = (
        "<article class='card full'><h2>Catalogue recovery</h2>"
        "<p class='muted'>Restore missing built-in items from Cinnamon's bundled catalogue. Existing custom items and edited settings are preserved.</p>"
        + restore_form + "</article>"
    )
    return (
        "<h1>Shop & Items Workshop</h1><p class='muted'>Create and manage shop items, crafting recipes, Mystery Box reward pools and their relative weights without editing code.</p>"
        f"<div class='statusline' style='margin-bottom:16px'>{storage}<span class='pill'>{len(shop)} catalogue items</span><span class='pill'>{len(recipes)} active recipes</span></div>"
        "<div class='grid'><article class='card full'><h2>Dedicated change log</h2><p class='muted'>Current destination: " +
        _esc(channel.mention if channel else "Not configured") + "</p>" + channel_form + "</article>"
        + restore_card + shop_editor_ui + recipe_card + "<article class='card full'><h2>Active crafting recipes</h2></article>" + recipe_grid + "".join(recipe_dialogs)
        + "".join(box_cards) + "<article class='card full'><h2>Recent Shop & Items audit history</h2><p class='muted'>Last 30 events shown; up to 500 per server are retained in the Upstash-backed snapshot.</p>" + audit_html + "</article></div>"
    )


def _csrf():
    token = session.get("dashboard_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["dashboard_csrf"] = token
    return token


def _csrf_input():
    return f"<input type='hidden' name='csrf_token' value='{_esc(_csrf())}'>"


def _check_csrf():
    supplied = request.form.get("csrf_token", "")
    expected = session.get("dashboard_csrf", "")
    if not supplied or not expected or not secrets.compare_digest(supplied, expected):
        abort(400, "The form expired. Reload the page and try again.")


def _page(body, title="Cinnamon Dashboard", status=200):
    return render_template_string(
        """<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'>
<meta name='color-scheme' content='light'><meta name='theme-color' content='#F7F3EC'><title>{{title}}</title><style>"""
        + STYLE + """</style><script src='/assets/dashboard-search.js' defer></script></head><body>{{body|safe}}</body></html>""",
        title=title, body=body,
    ), status


_ASSET_DIRS = (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "Static"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"),
)


@dashboard_bp.get("/assets/<path:filename>")
def dashboard_asset(filename):
    """Serve the dashboard's stylesheet scripts and mascot from the repo asset folders."""
    for folder in _ASSET_DIRS:
        if os.path.isfile(os.path.join(folder, filename)):
            return send_from_directory(folder, filename)
    abort(404)


STYLE = r"""
/* Cinnamon Dashboard — warm cream surfaces, burnt-orange action colour, dark-brown ink.
   One consistent system: tokens, layout, navigation, cards, forms, tables, dialogs, mobile. */
:root{
  --bg:#F7F3EC; --surface:#FFFDFA; --surface-2:#FBF7F0; --surface-3:#F4EEE4;
  --ink:#2B211B; --ink-2:#57483D; --muted:#7C6E62;
  --line:#E9DFD2; --line-strong:#D9CBB8;
  --brand:#B4551B; --brand-strong:#94430F; --brand-soft:#FBEDDD;
  --accent:#D98A45;
  --green:#2E6A46; --green-soft:#E8F2EB;
  --amber:#7E5410; --amber-soft:#FBF0D9;
  --red:#A0372B; --red-soft:#FAE9E6;
  --focus:#1F4F8F;
  --radius:12px; --radius-sm:9px;
  --shadow:0 1px 2px rgba(43,33,27,.05),0 10px 26px rgba(43,33,27,.035);
  --font:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%;scroll-padding-top:96px}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);font-size:14.5px;line-height:1.55;-webkit-font-smoothing:antialiased;overflow-x:hidden}
a{color:inherit;text-decoration:none}
button,input,select,textarea{font:inherit;color:inherit}
img{max-width:100%}
h1,h2,h3,p{margin-top:0}
h1{font-size:clamp(23px,2.2vw,28px);font-weight:700;letter-spacing:-.022em;line-height:1.22;margin-bottom:8px}
h2{font-size:16.5px;font-weight:680;letter-spacing:-.012em;line-height:1.3;margin-bottom:12px}
h3{font-size:14.5px;font-weight:680;margin-bottom:8px}
p{margin-bottom:12px}
small{font-size:12.5px;line-height:1.45}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9em;background:var(--surface-3);border:1px solid var(--line);border-radius:5px;padding:1px 5px}
.muted{color:var(--muted)}
p.muted{font-size:13.5px;max-width:78ch}
.skip-link{position:absolute;left:-9999px;top:8px;z-index:400;background:var(--surface);border:1px solid var(--line-strong);border-radius:8px;padding:10px 14px;font-weight:650}
.skip-link:focus{left:12px}

/* ---------- Layout ---------- */
.layout{min-height:100vh;display:grid;grid-template-columns:266px minmax(0,1fr);background:var(--bg)}
.side{position:sticky;top:0;align-self:start;height:100vh;height:100dvh;overflow-y:auto;overscroll-behavior:contain;background:var(--surface);border-right:1px solid var(--line);padding:18px 14px 16px;display:flex;flex-direction:column;gap:16px;scrollbar-width:thin}
.main{min-width:0;width:100%;max-width:1320px;margin:0 auto;padding:0 clamp(18px,3vw,40px) 40px}
.footer{margin-top:36px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}

/* ---------- Brand + server switch ---------- */
.brand{display:flex;align-items:center;gap:11px;padding:2px 6px 8px}
.mascot{width:42px;height:42px;border-radius:11px;border:1px solid var(--line);background:var(--surface-2);object-fit:cover;flex:0 0 auto}
.brandtext{display:grid;min-width:0}
.brandtext b{font-size:16.5px;font-weight:750;letter-spacing:-.02em;line-height:1.2}
.brandtext span{font-size:10.5px;font-weight:700;letter-spacing:.11em;text-transform:uppercase;color:var(--muted)}
.serverbox{padding:12px;background:var(--surface-2);border:1px solid var(--line);border-radius:var(--radius-sm);display:grid;gap:8px}
.serverbox label{display:block;font-size:10.5px;color:var(--muted);font-weight:750;text-transform:uppercase;letter-spacing:.09em}
.serverbox select{width:100%;min-height:40px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);padding:8px 9px;color:var(--ink);font-size:13.5px}
.serverbox .btn{width:100%;justify-content:center}
.sidefoot{margin-top:auto;font-size:11.5px;line-height:1.5;color:var(--muted);padding:10px 8px 2px;border-top:1px solid var(--line)}
.sidefoot b{display:block;color:var(--ink-2);font-size:12px;font-weight:650;margin-bottom:2px}

/* ---------- Navigation ---------- */
.nav-search{display:block;margin:0;padding:0 2px}
.nav-search input{width:100%;min-height:38px;padding:8px 11px;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface-2);font-size:13px}
.nav-search input::placeholder{color:#9A8B7E}
.navgroup{display:grid;gap:2px;margin-top:4px}
.navlabel{font-size:10px;color:var(--muted);font-weight:750;letter-spacing:.11em;text-transform:uppercase;padding:8px 10px 4px}
.nav{display:grid;gap:2px}
.nav a{position:relative;display:flex;align-items:center;gap:10px;min-height:38px;padding:7px 10px;border-radius:8px;color:var(--ink-2);font-size:13.5px;font-weight:550;transition:background .14s ease,color .14s ease}
.nav a .navicon{width:18px;text-align:center;font-size:14px;line-height:1;opacity:.85;flex:0 0 18px}
.nav a .navtext{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nav a:hover{background:var(--surface-2);color:var(--ink)}
.nav a.active{background:var(--brand-soft);color:var(--brand-strong);font-weight:650}
.nav a.active .navicon{opacity:1}
.nav a.active::before{content:"";position:absolute;left:0;top:8px;bottom:8px;width:3px;border-radius:0 3px 3px 0;background:var(--brand)}
.nav a:focus-visible,.serverbox select:focus-visible,.nav-search input:focus-visible{outline:2px solid var(--focus);outline-offset:2px}

/* ---------- Top bar ---------- */
.top{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:12px;padding:14px 0 13px;margin-bottom:24px;background:var(--bg);border-bottom:1px solid var(--line)}
.crumb{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--muted);min-width:0}
.crumb b{color:var(--ink-2);font-weight:600}
.crumb .sep{opacity:.5}
.profile{display:flex;align-items:center;gap:9px;margin-left:auto;min-width:0}
.profile .avatar{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;background:var(--brand-soft);color:var(--brand-strong);font-size:12.5px;font-weight:750;flex:0 0 30px;border:1px solid #F0DCC4}
.profile .profilename{font-size:13px;font-weight:600;max-width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* ---------- Page header + hero ---------- */
.pagehead{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;flex-wrap:wrap;margin:2px 0 20px}
.pagehead h1{margin-bottom:5px}
.pagehead p{margin-bottom:0}
.eyebrow{font-size:11px;font-weight:750;letter-spacing:.1em;text-transform:uppercase;color:var(--brand);margin-bottom:7px}
.statusline{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.hero{display:flex;align-items:center;gap:20px;justify-content:space-between;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:20px 22px;margin-bottom:18px;box-shadow:var(--shadow)}
.hero h1{margin-bottom:6px}
.hero p{margin-bottom:14px;color:var(--muted);font-size:13.5px;max-width:70ch}
.hero .actions{margin-top:0}
.heroimg{width:72px;height:72px;border-radius:16px;border:1px solid var(--line);background:var(--surface-2);flex:0 0 auto}

/* ---------- Grid + cards ---------- */
.grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:16px;margin:0 0 22px}
.card{grid-column:span 12;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:19px 20px;box-shadow:var(--shadow);min-width:0}
.card.third{grid-column:span 4}
.card.half{grid-column:span 6}
.card.full{grid-column:span 12}
.card>h2:first-child,.card>h3:first-child{margin-top:0}
.card>p:last-child,.card>p.muted:last-child{margin-bottom:0}
.card:hover{border-color:var(--line-strong)}
.card .grid{margin-bottom:0}
.card .grid>.card{box-shadow:none;background:var(--surface-2)}
.rule{height:1px;background:var(--line);margin:16px 0}
.grow{flex:1 1 auto}

/* ---------- KPI / stats ---------- */
.statgrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:0 0 18px}
.statgrid>.card{grid-column:span 1}
.statgrid .card,.card.kpi{padding:16px 17px;display:grid;gap:2px}
.kpihead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px}
.statlabel{font-size:10.5px;font-weight:750;letter-spacing:.085em;text-transform:uppercase;color:var(--muted)}
.stat{font-size:27px;font-weight:720;letter-spacing:-.03em;line-height:1.15;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.kpitrend{font-size:12px;color:var(--muted);margin:4px 0 0}
.iconbox{width:34px;height:34px;border-radius:9px;display:grid;place-items:center;background:var(--brand-soft);border:1px solid #F0DCC4;font-size:16px;flex:0 0 34px}

/* ---------- Rows / key-value lists ---------- */
.rowlist{display:grid;gap:0}
.rowitem{display:flex;align-items:center;gap:12px;padding:10px 0;border-top:1px solid #F2EBE1;min-width:0}
.rowitem:first-child{border-top:0;padding-top:2px}
.rowmain{display:grid;min-width:0;flex:1 1 auto}
.rowmain b{font-weight:600;font-size:13.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rowmain small{color:var(--muted)}
.rowmeta{flex:0 0 auto;font-weight:650;font-size:13px;font-variant-numeric:tabular-nums;text-align:right}
.statusgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 26px}

/* ---------- Notices ---------- */
.notice{display:flex;gap:10px;align-items:flex-start;background:var(--green-soft);border:1px solid #C7E0CF;color:#245C3B;border-radius:10px;padding:12px 14px;margin:0 0 18px;font-size:13.5px;font-weight:500}
.notice::before{content:"✓";font-weight:800;line-height:1.5}
.notice.error{background:var(--red-soft);border-color:#EBC7C1;color:#7E2A20}
.notice.error::before{content:"!";display:grid;place-items:center;width:16px;height:16px;border-radius:50%;background:#A0372B;color:#fff;font-size:11px;line-height:1;margin-top:3px}

/* ---------- Buttons ---------- */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:38px;padding:8px 14px;border-radius:8px;border:1px solid transparent;background:var(--brand);color:#FFF9F3;font-size:13.5px;font-weight:600;line-height:1.2;cursor:pointer;white-space:nowrap;transition:background .14s ease,border-color .14s ease,color .14s ease}
.btn:hover{background:var(--brand-strong)}
.btn:active{transform:translateY(1px)}
.btn[disabled]{opacity:.62;cursor:progress}
.btn.secondary{background:var(--surface);border-color:var(--line-strong);color:var(--ink-2)}
.btn.secondary:hover{background:var(--surface-2);color:var(--ink);border-color:#CBBBA6}
.btn.danger{background:var(--red);color:#fff}
.btn.danger:hover{background:#882D23}
.btn.small{min-height:32px;padding:5px 10px;font-size:12.5px;border-radius:7px}
.btn:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:14px}
.card>.actions:first-child{margin-top:0}
form>.actions{margin-top:16px}
.actions .btn{margin:0}

/* ---------- Forms ---------- */
.formgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}
.formgrid>.field.full,.formgrid .field[style*="grid-column"]{grid-column:1/-1}
.field{display:grid;gap:6px;margin:12px 0;min-width:0}
.field>label,.field>span.label{font-size:12px;font-weight:650;color:var(--ink-2);letter-spacing:.005em}
.field small{color:var(--muted)}
.field input,.field select,.field textarea,.searchable-select input,.choice-search{width:100%;min-height:40px;padding:8px 10px;background:var(--surface);border:1px solid var(--line-strong);border-radius:8px;color:var(--ink);font-size:13.5px;transition:border-color .14s ease,box-shadow .14s ease}
.field textarea{min-height:96px;resize:vertical;line-height:1.5}
.field select{appearance:none;background-image:url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath fill='%237C6E62' d='M6 8 0 0h12z'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 11px center;padding-right:32px}
.field input[type=checkbox],.toggle input[type=checkbox]{width:18px;height:18px;min-height:0;accent-color:var(--brand);flex:0 0 18px;margin:1px 0 0}
.field input[type=file]{padding:7px 9px;min-height:42px;background:var(--surface-2)}
.field input[type=color]{padding:3px;height:40px;cursor:pointer}
.field input:focus,.field select:focus,.field textarea:focus,.searchable-select input:focus,.choice-search:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(180,85,27,.14)}
.field input::placeholder,.field textarea::placeholder{color:#A2948A}
.searchable-select{display:grid;gap:5px;margin-bottom:7px}
.searchable-select input{background:var(--surface-2);font-size:12.5px;min-height:36px}
.toggle{display:flex;align-items:flex-start;gap:11px;min-height:44px;padding:10px 0;border-top:1px solid #F2EBE1;font-size:13.5px;cursor:default}
.toggle:first-of-type{border-top:0}
label.toggle{cursor:pointer}
.toggle>span{display:grid;gap:2px;min-width:0;flex:1 1 auto}
.toggle b{font-size:13.5px;font-weight:600;line-height:1.4}
.toggle small{color:var(--muted);font-weight:400}
.toggle>.pill{margin-left:auto;flex:0 0 auto}
.toggle>b+span:not(.pill):not(.iconbox){margin-left:auto;text-align:right;color:var(--ink-2);font-size:13px;overflow-wrap:anywhere}
.toggle>b{flex:0 1 auto}
label.toggle:focus-within{outline:2px solid var(--focus);outline-offset:3px;border-radius:6px}

/* ---------- Catalog / repeated editable blocks ---------- */
.itemlist{display:grid;gap:12px;margin-top:4px}
.catalogitem{border:1px solid var(--line);border-radius:10px;padding:14px 15px;background:var(--surface-2);min-width:0}
.catalogitem form{margin:0}
.cataloghead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.catalogname{font-weight:650;font-size:14px;color:var(--ink)}
.cataloghead code{font-size:11.5px;color:var(--muted);background:var(--surface);border-color:var(--line)}
.catalogitem .formgrid{margin-top:2px}

/* ---------- Pills ---------- */
.pill{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:999px;background:var(--surface-3);border:1px solid var(--line);color:var(--ink-2);font-size:11.5px;font-weight:650;line-height:1.5;white-space:nowrap}
.pill.good{background:var(--green-soft);border-color:#C7E0CF;color:var(--green)}
.pill.warn{background:var(--amber-soft);border-color:#EBD9B4;color:var(--amber)}
.pill.danger{background:var(--red-soft);border-color:#EBC7C1;color:var(--red)}

/* ---------- Tables ---------- */
.tablewrap{width:100%;overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--surface);margin:12px 0 4px;overscroll-behavior-x:contain;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;min-width:440px}
th,td{padding:10px 12px;text-align:left;vertical-align:top;border-bottom:1px solid #F2EBE1;font-size:13px}
th{background:var(--surface-2);color:var(--muted);font-size:10.5px;font-weight:750;letter-spacing:.07em;text-transform:uppercase;white-space:nowrap;position:sticky;top:0}
td{color:var(--ink-2)}
td b{color:var(--ink);font-weight:600}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:#FDFAF4}
td form{margin:0}
td .actions{margin-top:0;flex-wrap:nowrap}
td .actions select{min-height:32px;font-size:12.5px;min-width:130px}
td .btn{margin:2px 2px 2px 0}
.tablewrap+ .muted,.tablewrap+p{margin-top:10px}

/* ---------- Searchable multi-select pickers ---------- */
.choice-picker{display:grid;gap:9px;padding:12px;border:1px solid var(--line-strong);border-radius:10px;background:var(--surface-2)}
.choice-toolbar{display:flex;align-items:center;gap:9px;min-width:0}
.choice-search{background:var(--surface);min-height:38px;font-size:13px}
.choice-count{flex:0 0 auto;color:var(--muted);font-size:11.5px;font-weight:650;white-space:nowrap}
.choice-selected{display:flex;gap:5px;flex-wrap:wrap;min-height:22px;color:var(--muted);font-size:12.5px}
.choice-chip{border:1px solid #EAD3BA;background:var(--brand-soft);color:#7C3E12;border-radius:999px;padding:4px 9px;font-size:11.5px;font-weight:600;cursor:pointer}
.choice-chip:hover{background:#F7E0C8}
.choice-options{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:6px;max-height:250px;overflow:auto;padding:2px;overscroll-behavior:contain}
.choice-option{display:flex;align-items:center;gap:9px;min-width:0;min-height:38px;padding:7px 9px;border:1px solid var(--line);border-radius:7px;background:var(--surface);cursor:pointer;transition:border-color .12s,background .12s}
.choice-option:hover{border-color:var(--line-strong);background:#FFFCF6}
.choice-option:has(input:checked){border-color:#E3C6A6;background:var(--brand-soft)}
.choice-option[hidden]{display:none!important}
.choice-option input{width:17px;height:17px;flex:0 0 17px;accent-color:var(--brand)}
.choice-option span{overflow-wrap:anywhere;font-size:12.5px}
.choice-help{color:var(--muted);font-size:11.5px;line-height:1.45}

/* ---------- Empty states ---------- */
.empty{display:grid;gap:4px;justify-items:center;text-align:center;padding:26px 16px;border:1px dashed var(--line-strong);border-radius:9px;background:var(--surface-2);color:var(--muted);font-size:13px;margin:12px 0}
p.empty{margin:10px 0}
td.empty,td[colspan]{color:var(--muted);font-size:12.5px;text-align:center;padding:16px 12px}
.dangerzone{border-color:#EBC7C1;background:var(--red-soft)}
.sectionhead{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:10px}

/* ---------- Mobile navigation ---------- */
.mobile-nav-toggle{display:none;align-items:center;justify-content:center;border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);border-radius:8px;min-height:38px;min-width:40px;padding:0 10px;font-size:17px;line-height:1;cursor:pointer}
.mobile-nav-close{display:none}
.nav-backdrop{display:none}

/* ---------- Responsive ---------- */
@media(max-width:1180px){
  .statgrid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .card.third{grid-column:span 6}
}
@media(max-width:1024px){
  .layout{grid-template-columns:236px minmax(0,1fr)}
  .card.half{grid-column:span 12}
  .side{padding:16px 12px}
}
@media(max-width:760px){
  .layout{grid-template-columns:minmax(0,1fr)}
  body.nav-open{overflow:hidden}
  .side{position:fixed!important;inset:0 auto 0 0;width:min(87vw,318px);height:100vh;height:100dvh;max-height:100dvh;z-index:120;transform:translateX(-104%);transition:transform .2s ease;box-shadow:14px 0 40px rgba(43,33,27,.20);padding:calc(14px + env(safe-area-inset-top)) 13px calc(18px + env(safe-area-inset-bottom))}
  .side.mobile-open{transform:translateX(0)}
  .side .nav a{min-height:44px;font-size:13.5px}
  .side .nav{display:grid!important;overflow:visible!important}
  .side .navlabel{display:block}
  .mobile-nav-toggle{display:inline-flex}
  .mobile-nav-close{display:inline-flex;align-items:center;justify-content:center;align-self:flex-end;border:1px solid var(--line-strong);border-radius:8px;background:var(--surface);min-height:38px;min-width:40px;font-size:19px;margin-bottom:-4px}
  .nav-backdrop{display:block;position:fixed;inset:0;background:rgba(38,28,21,.42);z-index:110;opacity:0;visibility:hidden;transition:opacity .18s,visibility .18s;border:0;padding:0}
  .nav-backdrop.visible{opacity:1;visibility:visible}
  .main{padding:0 13px calc(30px + env(safe-area-inset-bottom))}
  .top{padding:10px 0 10px;margin-bottom:18px;gap:9px;flex-wrap:wrap;background:var(--bg)}
  .top .crumb{flex:1 1 auto;font-size:12px;min-width:0}
  .profile{font-size:12.5px;margin-left:auto}
  .profile .profilename{max-width:110px}
  h1{font-size:23px}
  h2{font-size:16px}
  p.muted{font-size:13px}
  .pagehead{gap:10px;margin-bottom:15px;align-items:flex-start}
  .statusline{width:100%}
  .hero{flex-direction:column;align-items:flex-start;gap:14px;padding:17px}
  .heroimg{align-self:flex-end;width:56px;height:56px;border-radius:13px;margin-top:-46px}
  .grid{gap:12px;margin-bottom:16px}
  .card{padding:15px;border-radius:11px}
  .statgrid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:14px}
  .statgrid .card,.card.kpi{padding:13px}
  .stat{font-size:23px}
  .statusgrid{grid-template-columns:minmax(0,1fr)}
  .formgrid{grid-template-columns:minmax(0,1fr);gap:0}
  .field{margin:10px 0}
  .field input,.field select,.field textarea,.searchable-select input,.choice-search{font-size:16px;min-height:46px}
  .field textarea{min-height:108px}
  .field select{padding-right:34px}
  .btn{min-height:44px;padding:9px 14px}
  .btn.small{min-height:36px;padding:6px 10px}
  .actions{gap:8px}
  .actions .btn{flex:1 1 140px}
  .toggle{min-height:50px;padding:11px 0}
  .toggle input[type=checkbox]{width:20px;height:20px;flex-basis:20px}
  .choice-picker{padding:10px}
  .choice-options{grid-template-columns:minmax(0,1fr);max-height:230px}
  .choice-option{min-height:44px}
  .choice-toolbar{flex-wrap:wrap;align-items:stretch}
  .tablewrap{border-radius:9px;margin:10px 0 2px}
  table{min-width:520px}
  th,td{padding:9px 10px}
  td .actions{flex-wrap:wrap}
  .footer{font-size:11px;margin-top:24px}
}
@media(max-width:400px){
  .statgrid{grid-template-columns:minmax(0,1fr)}
  .brandtext b{font-size:16px}
  .profile .profilename{display:none}
  .actions .btn{flex:1 1 100%}
}
@media(prefers-reduced-motion:reduce){
  *,*::before,*::after{transition-duration:.01ms!important;animation-duration:.01ms!important;scroll-behavior:auto!important}
}
"""


def _header():
    name = str(session.get("display_name", "Discord user") or "Discord user")
    initial = _esc((name.strip()[:1] or "C").upper())
    return (
        "<header class='top'>"
        "<button class='mobile-nav-toggle' id='liveMenuBtn' type='button' aria-label='Open dashboard navigation' aria-controls='liveSidebar' aria-expanded='false'>☰</button>"
        "<div class='crumb'><b>Cinnamon</b><span class='sep'>/</span><span>Server dashboard</span></div>"
        "<div class='profile'><span class='avatar' aria-hidden='true'>" + initial + "</span>"
        "<span class='profilename'>" + _esc(name) + "</span>"
        "<a class='btn secondary small' href='/logout'>Log out</a></div>"
        "</header>"
    )


def _nav(guild_id, tab):
    groups = [
        ("Workspace", [
            ("overview", "⌂", "Overview"),
            ("mind", "🐈", "Cinnamon Mind"),
            ("automation", "⚡", "Automation Studio"),
            ("message_studio", "✉", "Message Studio"),
        ]),
        ("Community", [
            ("engagement", "✦", "Levels & XP"),
            ("achievements", "🏆", "Achievements"),
            ("quests", "📜", "Quests"),
            ("friendship", "🐾", "Friendship"),
            ("companions", "🐱", "Companions"),
        ]),
        ("Economy & games", [
            ("economy", "🌿", "Catnip Economy"),
            ("shop_items", "🧰", "Shop & Items Workshop"),
            ("adventure", "🎣", "Adventures & Fishing"),
            ("hangry", "🎮", "Hangry Games"),
            ("giveaways", "🎉", "Giveaways"),
            ("tickets", "🎫", "Tickets"),
        ]),
        ("Insights", [
            ("analytics", "▥", "Analytics"),
            ("activity_logs", "≋", "Activity Logs"),
        ]),
        ("Configuration", [
            ("community", "☻", "Community & AI"),
            ("moderation", "🛡", "Moderation & Security"),
            ("roles_setup", "♙", "Roles Setup"),
            ("system", "⚙", "Settings & Logs"),
        ]),
    ]
    groups_html = []
    for label, items in groups:
        links = "".join(
            "<a class='" + ("active" if tab == key else "") + "' href='/dashboard?guild_id=" + str(guild_id) + "&tab=" + key + "'"
            + (" aria-current='page'" if tab == key else "")
            + "><span class='navicon' aria-hidden='true'>" + ico + "</span><span class='navtext'>" + _esc(text) + "</span></a>"
            for key, ico, text in items
        )
        groups_html.append("<div class='navgroup'><div class='navlabel'>" + label + "</div><nav class='nav'>" + links + "</nav></div>")
    return (
        "<label class='field nav-search'><span class='label' style='position:absolute;left:-9999px'>Search dashboard</span>"
        "<input id='dashboardNavSearch' type='search' placeholder='Search dashboard…' aria-label='Search dashboard sections' autocomplete='off'></label>"
        "<div id='dashboardNav'>" + "".join(groups_html) + "</div>"
    )


def _shell(guild, guilds, tab, body, notice=None, notice_level="success"):
    gid = guild.id
    options = []
    for item in guilds:
        if str(item.get("id")) in {str(g.id) for g in (_bot.guilds if _bot else [])} and (item.get("owner") or (int(item.get("permissions", "0")) & 0x8)):
            selected = " selected" if str(item.get("id")) == str(gid) else ""
            options.append(f"<option value='{_esc(item['id'])}'{selected}>{_esc(item.get('name','Server'))}</option>")
    select = (
        "<form action='/dashboard' method='get'><input type='hidden' name='tab' value='overview'>"
        "<div class='serverbox'><label for='dashboardGuildSelect'>Selected server</label>"
        "<select id='dashboardGuildSelect' name='guild_id'>" + "".join(options) + "</select>"
        "<button class='btn secondary small' type='submit'>Switch server</button></div></form>"
    )
    brand = (
        "<div class='brand'><img class='mascot' src='/assets/cinnamon_mascot.svg' alt=''>"
        "<span class='brandtext'><b>Cinnamon</b><span>Control panel</span></span></div>"
    )
    side = (
        "<aside class='side' id='liveSidebar' aria-label='Dashboard navigation'>"
        "<button class='mobile-nav-close' id='liveMenuClose' type='button' aria-label='Close navigation'>×</button>"
        + brand + select + _nav(gid, tab)
        + "<div class='sidefoot'><b>Permission-checked controls</b>Every change is verified against your Discord permissions and written to the audit log where configured.</div>"
        "</aside><button class='nav-backdrop' id='liveNavBackdrop' type='button' aria-label='Close navigation' tabindex='-1'></button>"
    )
    level = " error" if str(notice_level) == "error" else ""
    role = "alert" if level else "status"
    notice_html = f"<div class='notice{level}' role='{role}'>{_esc(notice)}</div>" if notice else ""
    title = f"{guild.name} • Cinnamon Dashboard"
    nav_script = "<script src='/assets/dashboard-mobile.js' defer></script>"
    return _page(
        "<a class='skip-link' href='#mainContent'>Skip to content</a>"
        "<div class='layout'>" + side + "<main class='main' id='mainContent'>" + _header() + notice_html + body
        + "<div class='footer'>Cinnamon · Server controls are permission-checked. Keep your Discord account secure.</div></main></div>"
        + nav_script,
        title,
    )


def _channel_select(guild, name, selected=None, allow_none=True, multiple=False, size=7):
    """Render a channel picker; multi-select is used for settings like XP."""
    channels = [c for c in guild.text_channels if c.permissions_for(guild.me).view_channel] if guild.me else guild.text_channels
    if multiple:
        if selected is None:
            selected_ids = set()
        elif isinstance(selected, (set, list, tuple)):
            selected_ids = {int(x) for x in selected}
        else:
            selected_ids = {int(selected)}
        boxes=[]
        for ch in channels:
            checked = " checked" if ch.id in selected_ids else ""
            boxes.append(
                f"<label class='choice-option' data-choice-label='{_esc(ch.name.lower())}'>"
                f"<input type='checkbox' name='{_esc(name)}' value='{ch.id}'{checked}>"
                f"<span>#{_esc(ch.name)}</span></label>"
            )
        selected_names = ", ".join("#" + ch.name for ch in channels if ch.id in selected_ids)
        return (
            "<div class='choice-picker' data-choice-picker>"
            f"<div class='choice-toolbar'><input class='choice-search' type='search' "
            f"placeholder='Search channels…' aria-label='Search channels for { _esc(name) }' "
            "autocomplete='off'><span class='choice-count' aria-live='polite'></span></div>"
            f"<div class='choice-selected' aria-live='polite'>{_esc(selected_names) if selected_names else 'No channels selected yet'}</div>"
            "<div class='choice-options'>" + "".join(boxes) + "</div>"
            "<small class='choice-help'>Search by channel name, then tick the channels you want. Your existing selections stay selected while you search.</small>"
            "</div>"
        )
    opts = ["<option value=''>— Not set —</option>"] if allow_none else []
    for ch in channels:
        try:
            sel = " selected" if selected is not None and int(selected) == ch.id else ""
        except (TypeError, ValueError):
            sel = ""
        opts.append(f"<option value='{ch.id}'{sel}>#{_esc(ch.name)}</option>")
    return f"<select name='{_esc(name)}'>" + "".join(opts) + "</select>"


def _member_select(guild, name="member_id", selected=None, allow_none=False, size=7):
    """Display member names in the dashboard while submitting their IDs internally."""
    members = sorted((m for m in guild.members if not m.bot), key=lambda m: (m.display_name or m.name or "").lower())
    selected_id = str(selected) if selected is not None else ""
    opts = ["<option value=''>— Select a member —</option>"] if allow_none else []
    for member in members:
        label = member.display_name or member.name
        tag = member.name if member.name != label else ""
        suffix = f" · @{tag}" if tag else ""
        sel = " selected" if str(member.id) == selected_id else ""
        opts.append(f"<option value='{member.id}'{sel}>{_esc(label + suffix)}</option>")
    return f"<select name='{_esc(name)}'>" + "".join(opts) + "</select>"

def _role_select(guild, name, selected=None, allow_none=True):
    roles = sorted([r for r in guild.roles if not r.is_default() and not r.managed], key=lambda r: r.position, reverse=True)
    opts = ["<option value=''>— Not set —</option>"] if allow_none else []
    for role in roles:
        try: sel = " selected" if selected is not None and str(selected).isdigit() and int(selected) == role.id else ""
        except (TypeError, ValueError): sel = ""
        opts.append(f"<option value='{role.id}'{sel}>@{_esc(role.name)}</option>")
    return f"<select name='{_esc(name)}'>" + "".join(opts) + "</select>"


def _role_multi_select(guild, name, selected=None):
    """Accessible checkbox picker that submits role IDs, not names typed by hand."""
    try: selected_ids={int(x) for x in (selected or [])}
    except (TypeError,ValueError): selected_ids=set()
    roles=sorted([r for r in guild.roles if not r.is_default() and not r.managed],key=lambda r:r.position,reverse=True)
    if not roles: return "<p class='muted'>No assignable roles found.</p>"
    boxes=[]
    for role in roles:
        checked=" checked" if role.id in selected_ids else ""
        boxes.append(
            f"<label class='choice-option' data-choice-label='{_esc(role.name.lower())}'>"
            f"<input type='checkbox' name='{_esc(name)}' value='{role.id}'{checked}>"
            f"<span>@{_esc(role.name)}</span></label>"
        )
    selected_names = ", ".join("@" + role.name for role in roles if role.id in selected_ids)
    return (
        "<div class='choice-picker' data-choice-picker>"
        f"<div class='choice-toolbar'><input class='choice-search' type='search' "
        f"placeholder='Search roles…' aria-label='Search roles for {_esc(name)}' autocomplete='off'>"
        "<span class='choice-count' aria-live='polite'></span></div>"
        f"<div class='choice-selected' aria-live='polite'>{_esc(selected_names) if selected_names else 'No roles selected yet'}</div>"
        "<div class='choice-options'>" + "".join(boxes) + "</div>"
        "<small class='choice-help'>Search by role name and select one or more. Existing selections are kept while filtering.</small>"
        "</div>"
    )


def _role_bonus_picker(guild, name="bonus_role_ids", selected=None):
    """Searchable role picker with a per-role extra-entry count; IDs remain internal."""
    selected={str(k):max(1,min(20,int(v))) for k,v in (selected or {}).items() if str(k).isdigit()}
    roles=sorted([r for r in guild.roles if not r.is_default() and not r.managed],key=lambda r:r.position,reverse=True)
    rows=[]
    for role in roles:
        rid=str(role.id); checked=" checked" if rid in selected else ""
        count=selected.get(rid,1)
        rows.append(f"<label class='choice-option' data-choice-label='{_esc(role.name.lower())}'><input type='checkbox' name='{_esc(name)}' value='{rid}'{checked}><span>@{_esc(role.name)}</span><input aria-label='Extra entries for @{_esc(role.name)}' type='number' name='bonus_role_count_{rid}' min='1' max='20' value='{count}' style='width:76px;margin-left:auto'></label>")
    return ("<div class='choice-picker' data-choice-picker><div class='choice-toolbar'><input class='choice-search' type='search' placeholder='Search roles…' aria-label='Search bonus-entry roles' autocomplete='off'><span class='choice-count' aria-live='polite'></span></div><div class='choice-options'>"+("".join(rows) or "<p class='muted'>No assignable roles found.</p>")+"</div><small class='choice-help'>Select each role and set its extra entries (1–20). Only the highest matching role bonus applies.</small></div>")


def _form(guild_id, action, content, button="Save changes", danger=False):
    style = " danger" if danger else ""
    return f"<form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{guild_id}'><input type='hidden' name='action' value='{_esc(action)}'>{content}<div class='actions'><button class='btn{style}' type='submit'>{_esc(button)}</button></div></form>"


async def _dashboard_is_admin(guild, uid):
    """Recheck membership and role permissions without trusting an OAuth/cache claim."""
    if uid == guild.owner_id:
        return True
    try:
        member = await guild.fetch_member(uid)
        roles = await guild.fetch_roles()
        member_role_ids = {role.id for role in member.roles}
        return any(role.permissions.administrator for role in roles
                   if role.id == guild.id or role.id in member_role_ids)
    except Exception:
        return False


def _get_access(sid, guilds, guild_id):
    guild_item = next((g for g in guilds if str(g.get("id")) == str(guild_id)), None)
    guild = _bot.get_guild(int(guild_id)) if _bot and str(guild_id).isdigit() else None
    if not guild_item or not guild or str(guild.id) not in {str(g.get("id")) for g in guilds}:
        abort(404)
    perms = int(guild_item.get("permissions", "0"))
    oauth_allowed = bool(guild_item.get("owner") or (perms & 0x8))
    if not oauth_allowed:
        abort(403)
    uid = int(_tokens[sid]["user"]["id"])
    if not _run_bot(_dashboard_is_admin(guild, uid)):
        abort(403)
    return guild, guild_item


def _dashboard_context():
    sid = session.get("dash_sid")
    if not sid or sid not in _tokens:
        return None
    guilds = _discord_get(sid, "/users/@me/guilds")
    bot_ids = {str(g.id) for g in (_bot.guilds if _bot else [])}
    eligible = [g for g in guilds if str(g.get("id")) in bot_ids and (g.get("owner") or (int(g.get("permissions", "0")) & 0x8))]
    return sid, guilds, eligible


def _count(mapping, gid):
    return sum(1 for key in mapping if isinstance(key, tuple) and key[0] == gid)


async def _apply_brain_settings(state, gid, *, independence_enabled, chat_actions_enabled,
                                prompts_enabled=None, ai_judgment_enabled=None):
    """A failed save can never turn a protective pause back on in this process."""
    advanced = state["advanced_features_data"]
    brain = advanced.setdefault("cinnamon_brain_v1", {}).setdefault(
        str(gid), {"independence_enabled": True})
    actions = advanced.setdefault("cinnamon_actions_v2", {}).setdefault(
        str(gid), {"enabled": False})
    previous_brain = bool(brain.get("independence_enabled", True))
    previous_actions = bool(actions.get("enabled", False))
    previous_prompts = bool(brain.get("prompts_enabled", False))
    previous_reasoning = bool(brain.get("ai_judgment_enabled", False))
    brain["independence_enabled"] = bool(independence_enabled)
    actions["enabled"] = bool(chat_actions_enabled)
    if prompts_enabled is not None:
        brain["prompts_enabled"] = bool(prompts_enabled)
    if ai_judgment_enabled is not None:
        brain["ai_judgment_enabled"] = bool(ai_judgment_enabled)
    saved = False
    try:
        saved = await state["bd_save_data"]()
    except Exception:
        pass
    finally:
        if not saved:
            # Also runs when a timed-out web request cancels this coroutine.
            if not independence_enabled:
                brain["independence_enabled"] = False
            elif brain.get("independence_enabled"):
                brain["independence_enabled"] = previous_brain
            if not chat_actions_enabled:
                actions["enabled"] = False
            elif actions.get("enabled"):
                actions["enabled"] = previous_actions
            if prompts_enabled is not None:
                brain["prompts_enabled"] = previous_prompts if prompts_enabled else False
            if ai_judgment_enabled is not None:
                brain["ai_judgment_enabled"] = previous_reasoning if ai_judgment_enabled else False
    if not saved:
        raise ValueError("The durable save could not be verified. Disabled switches remain off in this session; an unacknowledged write may still persist. Verify storage before restarting.")


def _mind(guild, state):
    """Server-local personality controls, with clearly locked safety boundaries."""
    gid = guild.id
    cfg = state.get("cinnamon_social", {}).get(str(gid), {}) or {}
    play = state.get("cinnamon_actions", {}).get(str(gid), {}) or {}
    advanced = state.get("advanced_features_data", {})
    brain = state.get("cinnamon_brain", advanced.get("cinnamon_brain_v1", {})).get(str(gid), {}) or {}
    actions = state.get("cinnamon_trusted_actions", advanced.get("cinnamon_actions_v2", {})).get(str(gid), {}) or {}
    storage = state.get("brain_storage", {})
    mood = state.get("cinnamon_moods", {}).get(str(gid), {}) or {}
    score = int(mood.get("score", 0))
    tier = "Delighted 😻" if score >= 35 else "Grumpy 😾" if score <= -35 else "Normal 🐈"
    channel = guild.get_channel(int(cfg.get("auto_channel", 0) or 0))
    next_at = int(cfg.get("next_at", 0) or 0)
    next_text = dt.datetime.fromtimestamp(next_at, dt.timezone.utc).strftime("%d %b · %H:%M UTC") if next_at > 0 else "Not scheduled"
    logs = state.get("category_log_channels", {}).get(gid, {})
    people = cfg.get("people", {}) or {}
    top = sorted(((str(uid), int(x.get("good", 0))) for uid, x in people.items()),
                 key=lambda v: -v[1])[:8]
    ranked = "".join("<div class='toggle'><span><b>" + _esc((guild.get_member(int(uid)).display_name if guild.get_member(int(uid)) else "Member "+uid)) +
                     "</b><small>" + str(points) + " nice points</small></span></div>" for uid, points in top) or "<p class='muted'>No visitor milestones recorded yet.</p>"
    name = _channel_select(guild, "channel_id", cfg.get("auto_channel"), allow_none=False)
    toggles = "".join(
        "<label class='toggle'><input type='checkbox' name='" + key + "'" + (" checked" if cfg.get(key, default) else "") +
        "><span><b>" + label + "</b><small>" + desc + "</small></span></label>"
        for key,default,label,desc in [
            ("auto_enabled", False, "Automatic Hangry Games", "Requires recent engagement and available permissions; often stays quiet. Two opt-in role pings maximum."),
            ("cameos_enabled", True, "Rare jealous one-liners", "Maximum one six-hour cameo per server; never tags anyone."),
            ("questions_enabled", True, "Funny questions after being called", "One per person per day; members can individually opt out."),
        ])
    form = ("<div class='field'><label>Surprise game destination</label>" + name +
            "<small>Choose an existing public channel by name. Cinnamon must be able to send there.</small></div>" + toggles +
            "<label class='toggle'><input type='checkbox' name='play_enabled'" +
            (" checked" if play.get("play_enabled", False) else "") +
            "><span><b>Consent-only cat jokes</b><small>Off by default. Each member must opt in, with a strict once-per-day limit.</small></span></label>")
    log_text = "".join("<div class='toggle'><b>" + _esc(label) + "</b><span>" +
                       _esc(guild.get_channel(logs.get(cat)).mention if logs.get(cat) and guild.get_channel(logs.get(cat)) else "Run /setup") +
                       "</span></div>" for cat,label in [("stuff","Personality"),("mood","Mood & Naughty List")])
    boundary_controls = (
        "<label class='toggle'><input type='checkbox' name='independence_enabled'" +
        (" checked" if brain.get("independence_enabled", True) else "") +
        "><span><b>Independent activities</b><small>Pause spontaneous games, questions and cameos. Direct requests remain available.</small></span></label>" +
        "<label class='toggle'><input type='checkbox' name='chat_actions_enabled'" +
        (" checked" if actions.get("enabled", False) else "") +
        "><span><b>Conversational actions</b><small>Off by default. Authorized Catnip adjustments and timeouts require confirmation and reliable storage.</small></span></label>" +
        "<label class='toggle'><input type='checkbox' name='prompts_enabled'" +
        (" checked" if brain.get("prompts_enabled", False) else "") +
        "><span><b>Community questions</b><small>Optional no-ping questions, only in Cinnamon's approved activity channel.</small></span></label>" +
        "<label class='toggle'><input type='checkbox' name='ai_judgment_enabled'" +
        (" checked" if brain.get("ai_judgment_enabled", False) else "") +
        "><span><b>AI activity advice</b><small>Optional Gemini decision from counts and mood only, never raw member conversations. Cinnamon may decide to stay quiet.</small></span></label>")
    health_text = "Ready" if storage.get("ready") else "Unavailable"
    if storage.get("pending"):
        health_text = "Waiting for transaction reconciliation"
    last_reason = str(cfg.get("last_brain_reason", "No activity decision yet")).replace("_", " ")
    return (f"<h1>🐈 Cinnamon Mind</h1><p class='muted'>Cinnamon's playful character, with hard limits on what she may do."
            f" AI writes dialogue; it cannot independently transfer Catnip, punish users or broadcast @everyone.</p>"
            f"<div class='grid'><article class='card third'><div class='statlabel'>Current mood</div><div class='stat'>{_esc(tier)}</div><p class='muted'>Score {score:+d}</p></article>"
            f"<article class='card third'><div class='statlabel'>Next activity check</div><div class='stat' style='font-size:18px'>{_esc(next_text)}</div></article>"
            f"<article class='card third'><div class='statlabel'>Favourite visitors</div><div class='stat'>{len(top)}</div></article>"
            f"<article class='card half'><h2>Activity and action boundaries</h2>{_form(gid,'brain_settings',boundary_controls,'Save boundaries')}"
            f"<p class='muted'>Storage: {_esc(health_text)} · {'Durable' if storage.get('durable') else 'Local or unavailable'} · {_esc(storage.get('status', 'unknown'))}</p>"
            f"<p class='muted'>Last activity decision: {_esc(last_reason)}</p></article>"
            f"<article class='card half'><h2>Autonomy & gameplay</h2>{_form(gid,'mind_settings',form,'Save Cinnamon settings')}</article>"
            f"<article class='card half'><h2>Safety lock</h2><p class='pill good'>🔒 AI @everyone: disabled</p>"
            f"<p class='muted'>Mass announcements require Discord Administrator + an explicit 60-second confirmation in Discord. "
            f"Conversation participation requires a direct ping, reply or Cinnamon's name; voluntary jealousy is only a rare one-line aside.</p>"
            f"<p class='muted'>No autonomous punishments or currency changes. Staff-requested conversational actions are separately checked and confirmed.</p></article>"
            f"<article class='card half'><h2>Favourite people</h2>{ranked}</article>"
            f"<article class='card half'><h2>Cinnamon's private logs</h2>{log_text}"
            f"<p class='muted'>Use /recall to fill missing mood/visitor snapshots without overwriting live state.</p></article></div>")


def _adventure(guild, state):
    gid = guild.id
    fish = state.get("cinnamon_wildlands_fishing", {}).get(str(gid), {}) or {}
    story = state.get("cinnamon_wildlands_story", {}).get(str(gid), {}) or {}
    windows = fish.get("merchant_windows", {}) or {}
    now = time.time()
    cards = []
    for kind,label,name in (("rod","Fishing Rod Merchant","fishing-rod-merchant"),
                            ("bait","Fishing Bait Merchant","fishing-bait-merchant")):
        rec = windows.get(kind, {}) or {}
        ch = guild.get_channel(int(rec.get("channel_id", 0) or 0))
        if ch is None:
            ch = next((c for c in guild.text_channels if c.name == name), None)
        ends = float(rec.get("ends_at", 0) or 0)
        is_public = bool(rec.get("manual_public", False) or ends > now)
        status = "Public" if is_public else "Private"
        ends_text = ("Until staff closes" if rec.get("manual_public") else
                     dt.datetime.fromtimestamp(ends,dt.timezone.utc).strftime("%H:%M UTC") if ends > now else "—")
        finder = rec.get("finder_id")
        finder_name = guild.get_member(int(finder)).display_name if str(finder).isdigit() and guild.get_member(int(finder)) else "No discoverer"
        opts = "".join("<option value='" + k + "'>" + text + "</option>" for k,text in [
            ("private","Hide from visitors"),("two_hours","Open for two hours"),("public","Keep public")])
        content = ("<input type='hidden' name='merchant_kind' value='" + kind + "'>"
                   "<div class='field'><label>Merchant visibility</label><select name='access'>" + opts +
                   "</select></div><label class='toggle'><input type='checkbox' name='announce'><span>"
                   "<b>Announce to merchant role</b><small>Off by default. Opening a channel never automatically pings a role.</small></span></label>")
        cards.append("<article class='card half'><h2>🏪 " + _esc(label) + "</h2><p class='pill " +
                     ("good" if is_public else "warn") + "'>" + status + "</p><div class='toggle'>"
                     "<b>Channel</b><span>" + _esc(ch.mention if ch else "Run /setup") +
                     "</span></div><div class='toggle'><b>Closes</b><span>" + _esc(ends_text) +
                     "</span></div><div class='toggle'><b>Finder</b><span>" + _esc(finder_name) +
                     "</span></div>" + _form(gid,"merchant_access",content,"Apply merchant access") + "</article>")
    catch_count = sum(sum(int(v) for v in p.get("fish", {}).values()) for p in fish.get("members", {}).values())
    finished = sum(bool(p.get("complete", False)) for p in story.values())
    rod_rows = "".join("<tr><td>" + _esc(x.get("name")) + "</td><td>" + str(x.get("price",0)) +
                       "</td><td>" + str(x.get("bonus",0)) + "</td></tr>" for x in state.get("wlf_rods", []))
    return (f"<h1>🎣 Adventures & Fishing</h1><p class='muted'>The Billion-Catnip Mystery, fishing, equipment and "
            f"the two private merchant channels. Shop visibility is managed separately from finder commissions.</p>"
            f"<div class='grid'><article class='card third'><div class='statlabel'>Story explorers</div><div class='stat'>{len(story)}</div></article>"
            f"<article class='card third'><div class='statlabel'>Story completions</div><div class='stat'>{finished}</div></article>"
            f"<article class='card third'><div class='statlabel'>Fish caught</div><div class='stat'>{catch_count}</div></article>"
            + "".join(cards) +
            f"<article class='card full'><h2>🎣 Fishing gear</h2><p class='muted'>Use /fishing cast to choose your bait and reel technique."
            f" Mood influences rarity, but technique does not change the underlying fish roll.</p>"
            f"<div class='tablewrap'><table><thead><tr><th>Rod</th><th>Base Catnip</th><th>Luck bonus</th></tr></thead>"
            f"<tbody>{rod_rows}</tbody></table></div></article>"
            f"<article class='card full'><h2>📖 Cinnamon story</h2><p class='muted'>26 choice-driven scenes across six regions."
            f" Story progress is tracked per member and the 100,000 Catnip finale remains a one-time reward."
            f" Members continue their personal story with /adventure story.</p></article></div>")


def _overview(guild, state):
    """Live overview built only from Cinnamon's current runtime data."""
    gid = guild.id

    def as_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def as_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def member_name(uid):
        member = guild.get_member(int(uid)) if str(uid).isdigit() else None
        return (member.display_name or member.name) if member else "Member " + str(uid)

    balances = state.get("economy_balances", {}) or {}
    guild_balances = [(key[1], as_int(value)) for key, value in balances.items()
                      if isinstance(key, tuple) and len(key) >= 2 and key[0] == gid]
    catnip_total = sum(amount for _, amount in guild_balances)
    top_balances = sorted(guild_balances, key=lambda pair: pair[1], reverse=True)[:5]
    balance_rows = "".join(
        "<div class='rowitem'><span class='rowmain'><b>" + _esc(member_name(uid)) + "</b><small>Member</small></span>"
        "<span class='rowmeta'>" + f"{amount:,} 🌿" + "</span></div>"
        for uid, amount in top_balances
    ) or "<p class='empty'>No Catnip balances recorded yet.</p>"

    ticket_root = ((state.get("advanced_features_data", {}) or {}).get("cinnamon_tickets_v1", {}) or {}).get(str(gid), {}) or {}
    tickets = ticket_root.get("tickets", {}) or {}
    open_tickets = [t for t in tickets.values() if isinstance(t, dict) and t.get("status") == "open"]
    closed_tickets = ticket_root.get("closed", {}) or {}
    panels = ticket_root.get("panels", {}) or {}

    giveaways = [gw for gw in (state.get("active_giveaways", {}) or {}).values()
                 if isinstance(gw, dict) and as_int(gw.get("guild_id")) == gid]
    giveaways.sort(key=lambda gw: as_float(gw.get("ends_at")))
    giveaway_rows = "".join(
        "<div class='rowitem'><span class='rowmain'><b>" + _esc(gw.get("prize", "Giveaway")) + "</b>"
        "<small>" + f"{len(set(gw.get('entrants', []) or [])):,} entries" + " · ends " +
        dt.datetime.fromtimestamp(as_float(gw.get("ends_at")), dt.timezone.utc).strftime("%d %b %H:%M UTC") + "</small></span>"
        "<span class='rowmeta'>" + f"{as_int(gw.get('winners', 1)):,} winner(s)" + "</span></div>"
        for gw in giveaways[:4] if as_float(gw.get("ends_at")) > 0
    ) or "<p class='empty'>No active giveaways right now.</p>"

    quest_data = state.get("quest_data", {}).get(gid, {}) or {}
    daily_ids = quest_data.get("daily_ids", []) if isinstance(quest_data, dict) else []
    weekly_ids = quest_data.get("weekly_ids", []) if isinstance(quest_data, dict) else []
    daily_defs = state.get("DAILY_QUESTS", {}) or {}
    weekly_defs = state.get("WEEKLY_QUESTS", {}) or {}
    active_quests = len(daily_ids or []) + len(weekly_ids or [])
    quest_rows = "".join(
        "<div class='rowitem'><span class='rowmain'><b>" + _esc(pool.get(qid, {}).get("name", qid)) + "</b>"
        "<small>" + ("Daily" if kind == "Daily" else "Weekly") + " rotation</small></span>"
        "<span class='rowmeta'>" + f"{as_int(pool.get(qid, {}).get('qp')):,} QP</span></div>"
        for ids, pool, kind in ((daily_ids, daily_defs, "Daily"), (weekly_ids, weekly_defs, "Weekly"))
        for qid in (ids or [])[:3]
    ) or "<p class='empty'>No quest rotation has been generated yet.</p>"

    achievement_data = state.get("achievement_data", {}) or {}
    achievement_users = [value for key, value in achievement_data.items()
                         if isinstance(key, tuple) and len(key) >= 2 and key[0] == gid and isinstance(value, dict)]
    unlocked = sum(len(value.get("unlocked", []) or []) for value in achievement_users)
    achievement_defs = len(state.get("ACHIEVEMENTS", {}) or {}) + len(state.get("SECRET_ACHIEVEMENTS", {}) or {})

    hangry = state.get("hg_cog")
    hangry_games = as_int(getattr(hangry, "game_counts", {}).get(gid)) if hangry else 0
    if hangry:
        wins = sorted(((uid, count) for (guild_id, uid), count in hangry.win_counts.items() if guild_id == gid),
                      key=lambda pair: pair[1], reverse=True)[:3]
    else:
        wins = []
    hangry_rows = "".join(
        "<div class='rowitem'><span class='rowmain'><b>" + _esc(member_name(uid)) + "</b><small>Hangry Games winner</small></span>"
        "<span class='rowmeta'>" + f"{as_int(count):,} wins" + "</span></div>"
        for uid, count in wins
    ) or "<p class='empty'>No completed Hangry Games recorded yet.</p>"

    member_count = guild.member_count or len(guild.members)
    ready = bool(_bot and _bot.is_ready())
    latency = f"{round(_bot.latency * 1000)} ms" if ready else "Unavailable"
    commands = len(_bot.tree.get_commands()) if _bot else 0
    durable = bool(state.get("BD_UPSTASH_URL") and state.get("BD_UPSTASH_TOKEN"))
    storage = "Upstash Redis" if durable else "Local JSON file"

    flags = [
        ("Welcome messages", bool((state.get("welcome_config", {}) or {}).get(gid) or (state.get("welcome_config", {}) or {}).get(str(gid)))),
        ("Goodbye messages", bool((state.get("goodbye_config", {}) or {}).get(gid) or (state.get("goodbye_config", {}) or {}).get(str(gid)))),
        ("AutoMod", bool((state.get("automod_config", {}) or {}).get(gid) or (state.get("automod_config", {}) or {}).get(str(gid)))),
        ("Anti-raid alerts", bool(((state.get("antiraid_config", {}) or {}).get(gid) or (state.get("antiraid_config", {}) or {}).get(str(gid), {})).get("enabled"))),
        ("Cinnamon AI channel", bool((state.get("ai_channels", {}) or {}).get(gid) or (state.get("ai_channels", {}) or {}).get(str(gid)))),
        ("Hangry Games", bool(hangry)),
        ("Ticket panels", bool(panels)),
        ("Role permissions", bool(((state.get("advanced_features_data", {}) or {}).get("cinnamon_role_permissions_v1", {}) or {}).get(str(gid)))),
    ]
    status_rows = "".join(
        "<div class='toggle'><span><b>" + _esc(name) + "</b><small>" + ("Configured" if enabled else "Not configured") + "</small></span>"
        "<span class='pill " + ("good" if enabled else "warn") + "'>" + ("ON" if enabled else "OFF") + "</span></div>"
        for name, enabled in flags
    )

    latest = []
    for ticket in open_tickets:
        created = as_float(ticket.get("created_at"))
        if created > 0:
            latest.append((created, "Ticket opened", "#" + str(ticket.get("category_label", "Support"))))
    for gw in giveaways:
        created = as_float(gw.get("created_at")) or as_float(gw.get("ends_at"))
        if created > 0:
            latest.append((created, "Giveaway active", str(gw.get("prize", "Giveaway"))))
    latest.sort(key=lambda item: item[0], reverse=True)
    latest_rows = "".join(
        "<div class='rowitem'><span class='rowmain'><b>" + _esc(label) + "</b><small>" + _esc(detail) + "</small></span>"
        "<span class='rowmeta'>" + dt.datetime.fromtimestamp(when, dt.timezone.utc).strftime("%d %b · %H:%M UTC") + "</span></div>"
        for when, label, detail in latest[:5]
    ) or "<p class='empty'>No timestamped tickets or giveaways yet. Discord-side activity appears in Activity Logs.</p>"

    kpis = [
        ("Members", f"{member_count:,}", "👥", "Server size"),
        ("Catnip in circulation", f"{catnip_total:,} 🌿", "🌿", f"Across {len(guild_balances):,} tracked accounts"),
        ("Open tickets", f"{len(open_tickets):,}", "🎫", f"{len(closed_tickets):,} closed records"),
        ("Active giveaways", f"{len(giveaways):,}", "🎉", f"{len(panels):,} ticket panel(s) configured"),
    ]
    kpi_html = "".join(
        "<article class='card kpi'><div class='kpihead'><span class='statlabel'>" + _esc(label) + "</span>"
        "<span class='iconbox' aria-hidden='true'>" + icon + "</span></div>"
        "<div class='stat'>" + value + "</div><p class='kpitrend'>" + _esc(note) + "</p></article>"
        for label, value, icon, note in kpis
    )

    def link(label, tab_key, secondary=True):
        return "<a class='btn " + ("secondary" if secondary else "") + "' href='/dashboard?guild_id=" + str(gid) + "&tab=" + tab_key + "'>" + label + "</a>"

    return (
        "<div class='pagehead'><div><p class='eyebrow'>Server overview</p><h1>" + _esc(guild.name) + "</h1>"
        "<p class='muted'>Live information from Cinnamon's current runtime. Counters reflect saved state, not sample data.</p></div>"
        "<div class='statusline'><span class='pill " + ("good" if ready else "warn") + "'>" + ("Cinnamon online" if ready else "Cinnamon not ready") + "</span>"
        "<span class='pill'>" + _esc(storage) + "</span></div></div>"
        "<div class='statgrid'>" + kpi_html + "</div>"
        "<div class='grid'>"
        "<article class='card half'><div class='sectionhead'><h2>Catnip economy</h2><span class='pill'>" + f"{catnip_total:,} 🌿" + "</span></div>"
        "<div class='rowlist'>" + balance_rows + "</div>"
        "<p class='muted'>Balances are read live. Shop items, role income and transfers stay on the economy page.</p>"
        "<div class='actions'>" + link("Manage economy", "economy") + "</div></article>"
        "<article class='card half'><div class='sectionhead'><h2>Quests & achievements</h2><span class='pill'>" + f"{active_quests:,} active quests" + "</span></div>"
        "<div class='rowlist'>" + quest_rows + "</div><div class='rule'></div>"
        "<div class='rowitem'><span class='rowmain'><b>" + f"{unlocked:,} achievement unlocks" + "</b><small>Across " + f"{len(achievement_users):,} tracked members" + "</small></span>"
        "<span class='rowmeta'>" + f"{achievement_defs:,} definitions" + "</span></div>"
        "<div class='actions'>" + link("Open quests", "quests") + link("Achievements", "achievements") + "</div></article>"
        "<article class='card half'><div class='sectionhead'><h2>Giveaways</h2><span class='pill'>" + f"{len(giveaways):,} active" + "</span></div>"
        "<div class='rowlist'>" + giveaway_rows + "</div>"
        "<div class='actions'>" + link("Manage giveaways", "giveaways") + "</div></article>"
        "<article class='card half'><div class='sectionhead'><h2>Tickets</h2><span class='pill " + ("good" if open_tickets else "") + "'>" + f"{len(open_tickets):,} open" + "</span></div>"
        "<div class='rowlist'>"
        "<div class='rowitem'><span class='rowmain'><b>Active tickets</b><small>Priority-ordered in the ticket workspace</small></span><span class='rowmeta'>" + f"{len(open_tickets):,}" + "</span></div>"
        "<div class='rowitem'><span class='rowmain'><b>Recently closed</b><small>Up to 50 records retained</small></span><span class='rowmeta'>" + f"{len(closed_tickets):,}" + "</span></div>"
        "<div class='rowitem'><span class='rowmain'><b>Panels</b><small>Publish separately after saving</small></span><span class='rowmeta'>" + f"{len(panels):,}" + "</span></div>"
        "</div><div class='actions'>" + link("Open tickets", "tickets") + "</div></article>"
        "<article class='card half'><h2>Cinnamon health</h2>"
        "<div class='rowlist'>"
        "<div class='rowitem'><span class='rowmain'><b>Gateway</b><small>Discord connection</small></span><span class='pill " + ("good" if ready else "warn") + "'>" + ("Online" if ready else "Not ready") + "</span></div>"
        "<div class='rowitem'><span class='rowmain'><b>Latency</b><small>Current heartbeat</small></span><span class='rowmeta'>" + _esc(latency) + "</span></div>"
        "<div class='rowitem'><span class='rowmain'><b>Storage</b><small>Durable persistence</small></span><span class='pill " + ("good" if durable else "warn") + "'>" + _esc(storage) + "</span></div>"
        "<div class='rowitem'><span class='rowmain'><b>Slash commands</b><small>Registered in this process</small></span><span class='rowmeta'>" + f"{commands:,}" + "</span></div>"
        "</div><p class='muted'>Run <b>/diagnostics</b> in Discord for the complete permission and runtime check.</p>"
        "<div class='actions'>" + link("Settings & logs", "system") + "</div></article>"
        "<article class='card half'><div class='sectionhead'><h2>Hangry Games</h2><span class='pill'>" + f"{hangry_games:,} games run" + "</span></div>"
        "<div class='rowlist'>" + hangry_rows + "</div>"
        "<div class='actions'>" + link("Game statistics", "hangry") + "</div></article>"
        "<article class='card full'><h2>Feature status</h2><p class='muted'>Configuration read from this server's saved Cinnamon settings.</p>"
        "<div class='statusgrid'>" + status_rows + "</div></article>"
        "<article class='card full'><h2>Latest recorded activity</h2>"
        "<div class='rowlist'>" + latest_rows + "</div>"
        "<div class='actions'>" + link("View activity logs", "activity_logs") + link("Server analytics", "analytics") + "</div></article>"
        "</div>"
    )


def _moderation(guild, state):
    gid = guild.id
    automod = state.get("automod_config", {}).get(gid, {}) or state.get("automod_config", {}).get(str(gid), {})
    antiraid = state.get("antiraid_config", {}).get(gid, {}) or state.get("antiraid_config", {}).get(str(gid), {})
    warns = state.get("warnings_data", {})
    warning_count = sum(len(v) for k, v in warns.items() if isinstance(k, tuple) and k[0] == gid)
    advanced = state.get("advanced_features_data", {}) or {}
    security = (advanced.get("cinnamon_security_guard_v1", {}) or {}).get(str(gid), {}) or {}
    controls = (advanced.get("cinnamon_moderation_controls_v1", {}) or {}).get(str(gid), {}) or {}
    onboarding = controls.get("onboarding", {}) or {}
    verify_channel = guild.get_channel(int(controls.get("verification_channel_id", 0) or 0))
    verify_role = guild.get_role(int(controls.get("verification_role_id", 0) or 0))
    autorole = guild.get_role(int(controls.get("autorole_id", 0) or 0))
    alert_channel = guild.get_channel(int(security.get("alert_channel_id", 0) or 0))
    welcome_channel = guild.get_channel(int(onboarding.get("welcome_channel_id", 0) or 0))
    rules_channel = guild.get_channel(int(onboarding.get("rules_channel_id", 0) or 0))
    appeal_channel = guild.get_channel(int(controls.get("appeal_channel_id", 0) or 0))
    appeals = controls.get("appeals", {}) or {}
    notes = controls.get("notes", {}) or {}

    modform = "<div class='formgrid'><div class='field'><label>Member</label>" + _member_select(guild, "member_id", allow_none=False) + "<small>Select the Discord name; Cinnamon keeps the user ID internally.</small></div><div class='field'><label>Action</label><select name='mod_action'><option value='timeout'>Timeout</option><option value='kick'>Kick</option><option value='ban'>Ban</option></select></div><div class='field'><label>Timeout duration (minutes)</label><input name='duration' type='number' min='1' max='40320' value='60'></div><div class='field'><label>Reason</label><input name='reason' maxlength='400' placeholder='Reason for moderation action'></div></div><p class='muted'>Actions require the matching Discord permission and bot role hierarchy. Bans and kicks cannot be undone from this page.</p>"
    modcard = "<article class='card half'><h2>Member moderation</h2><p class='muted'>Apply a Discord moderation action by selecting the member name.</p>" + _form(gid, "moderate", modform, "Apply action", True) + "</article>"

    words = "\n".join(str(w) for w in automod.get("words", []))
    automodform = "<div class='field'><label>Banned words or phrases</label><textarea name='words' maxlength='3000' placeholder='One per line'>" + _esc(words) + "</textarea><small>One phrase per line; maximum 50 entries, each up to 100 characters.</small></div>"
    for key, label, desc in [("spam", "Spam detection", "Remove rapid repeated messages."), ("mentions", "Mass mention protection", "Flag messages over the mention threshold."), ("invites", "Discord invite protection", "Remove Discord invite links.")]:
        automodform += f"<label class='toggle'><input type='checkbox' name='{key}' {'checked' if automod.get(key) else ''}><span><b>{label}</b><small>{desc}</small></span></label>"
    automodform += "<div class='field'><label>Mention threshold</label><input name='mention_threshold' type='number' min='2' max='20' value='" + _esc(automod.get("mention_threshold", 5)) + "'></div>"
    automodcard = "<article class='card half'><h2>AutoMod</h2><p class='muted'>These options map to Cinnamon's existing AutoMod settings.</p>" + _form(gid, "automod", automodform) + "</article>"

    raidform = "<label class='toggle'><input type='checkbox' name='enabled' " + ("checked" if antiraid.get("enabled") else "") + "><span><b>Enable join-spike alerts</b><small>Alerts only; does not automatically kick or lock the server.</small></span></label><div class='formgrid'><div class='field'><label>Join threshold</label><input type='number' name='threshold' min='2' max='100' value='" + _esc(antiraid.get("threshold", 5)) + "'></div><div class='field'><label>Time window (seconds)</label><input type='number' name='window' min='2' max='120' value='" + _esc(antiraid.get("window", 10)) + "'></div></div>"
    raidcard = "<article class='card full'><h2>Anti-raid alerts</h2>" + _form(gid, "antiraid", raidform) + "</article>"

    securityform = (
        "<label class='toggle'><input type='checkbox' name='antispam_enabled' " + ("checked" if security.get("antispam_enabled") else "") + "><span><b>Enable anti-spam timeouts</b><small>Timeouts members who exceed the configured message rate. Disabled by default.</small></span></label>"
        "<label class='toggle'><input type='checkbox' name='antinuke_enabled' " + ("checked" if security.get("antinuke_enabled") else "") + "><span><b>Enable anti-nuke audit alerts</b><small>Detect bursts of destructive admin actions and alert moderators; no automatic admin punishment.</small></span></label>"
        "<div class='formgrid'><div class='field'><label>Spam message threshold</label><input name='antispam_threshold' type='number' min='4' max='15' value='" + str(max(4, min(15, int(security.get("antispam_threshold", 6))))) + "'></div>"
        "<div class='field'><label>Spam time window (seconds)</label><input name='antispam_window' type='number' min='3' max='30' value='" + str(max(3, min(30, int(security.get("antispam_window", 8))))) + "'></div>"
        "<div class='field'><label>Timeout duration (seconds)</label><input name='antispam_timeout' type='number' min='30' max='3600' value='" + str(max(30, min(3600, int(security.get("antispam_timeout", 60))))) + "'></div>"
        "<div class='field'><label>Anti-nuke action threshold</label><input name='antinuke_threshold' type='number' min='2' max='8' value='" + str(max(2, min(8, int(security.get("antinuke_threshold", 3))))) + "'></div>"
        "<div class='field'><label>Private security alert channel</label>" + _channel_select(guild, "alert_channel_id", security.get("alert_channel_id")) + "</div></div>"
    )
    securitycard = "<article class='card full'><h2>Anti-spam & anti-nuke</h2><p class='muted'>Anti-spam is opt-in. Anti-nuke monitors the Discord audit log and alerts on rapid destructive actions. Cinnamon does not automatically remove administrator roles or punish server owners.</p><p class='muted'>Current alert channel: " + _esc(alert_channel.mention if alert_channel else "Use the main moderation log") + "</p>" + _form(gid, "security_settings", securityform, "Save security settings") + "</article>"

    onboardingform = (
        "<div class='formgrid'><div class='field'><label>Automatic role for new members</label>" + _role_select(guild, "autorole_id", controls.get("autorole_id")) + "</div>"
        "<div class='field'><label>Verification panel channel</label>" + _channel_select(guild, "verification_channel_id", controls.get("verification_channel_id")) + "</div>"
        "<div class='field'><label>Verified role</label>" + _role_select(guild, "verification_role_id", controls.get("verification_role_id")) + "</div>"
        "<div class='field'><label>Welcome channel</label>" + _channel_select(guild, "welcome_channel_id", onboarding.get("welcome_channel_id")) + "</div>"
        "<div class='field'><label>Rules channel</label>" + _channel_select(guild, "rules_channel_id", onboarding.get("rules_channel_id")) + "</div></div>"
        "<p class='muted'>Verification channel and role must either both be selected or both be blank. The verified role must be below Cinnamon's bot role.</p>"
    )
    verify_button = "<form method='post' action='/dashboard/action'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='verification_publish'><button class='btn secondary' type='submit'>Publish verification panel</button></form>"
    onboardingcard = "<article class='card full'><h2>Verification & member onboarding</h2><div class='toggle'><span>Verification panel</span><b>" + _esc(verify_channel.mention if verify_channel else "Not configured") + "</b></div><div class='toggle'><span>Verified role</span><b>" + _esc(verify_role.mention if verify_role else "Not configured") + "</b></div><div class='toggle'><span>Autorole</span><b>" + _esc(autorole.mention if autorole else "Disabled") + "</b></div><div class='toggle'><span>Welcome / rules</span><b>" + _esc((welcome_channel.mention if welcome_channel else "No welcome") + " · " + (rules_channel.mention if rules_channel else "No rules")) + "</b></div>" + _form(gid, "moderation_controls_settings", onboardingform, "Save onboarding settings") + verify_button + "</article>"

    appeal_rows = []
    for appeal_id, appeal in list(appeals.items())[-15:][::-1]:
        decision = str(appeal.get("status", "pending"))
        action_forms = ""
        if decision == "pending":
            action_forms = "<div class='actions'>"
            for label, value in (("Approve", "approved"), ("Decline", "declined")):
                action_forms += "<form method='post' action='/dashboard/action'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='dashboard_appeal_review'><input type='hidden' name='appeal_id' value='" + _esc(str(appeal_id)) + "'><input type='hidden' name='decision' value='" + value + "'><button class='btn " + ("secondary" if value == "approved" else "danger") + " small'>" + label + "</button></form>"
            action_forms += "</div>"
        appeal_member=guild.get_member(int(appeal.get("user_id",0) or 0)) if str(appeal.get("user_id","")).isdigit() else None
        appeal_member_name=getattr(appeal_member,"display_name","Unknown member")
        appeal_rows.append("<tr><td>" + _esc(str(appeal_id)) + "</td><td>" + _esc(appeal_member_name) + "</td><td>" + _esc(str(appeal.get("details", ""))[:180]) + "</td><td>" + _esc(decision.title()) + "</td><td>" + action_forms + "</td></tr>")
    appeal_rows_html = "".join(appeal_rows) or "<tr><td colspan='5'>No appeals have been submitted.</td></tr>"
    portal_token = str(controls.get("appeal_portal_token", "") or "")
    portal_base = (os.getenv("RENDER_EXTERNAL_URL", "https://cinnamon-c328.onrender.com").rstrip("/"))
    portal_url = portal_base + url_for("cinnamon_dashboard.appeal_portal", guild_id=gid, token=portal_token) if portal_token else ""
    public_appeal_channel = guild.get_channel(int(controls.get("appeal_public_channel_id", 0) or 0))
    appeal_form = (
        "<div class='formgrid'><div class='field'><label>Private moderator review channel</label>" +
        _channel_select(guild, "appeal_channel_id", controls.get("appeal_channel_id")) +
        "<small>Only moderators should be able to view this channel.</small></div><div class='field'><label>Public appeal link channel</label>" +
        _channel_select(guild, "appeal_public_channel_id", controls.get("appeal_public_channel_id")) +
        "<small>Members can see the portal button here. Appeal details are never posted here.</small></div></div>"
    )
    portal_controls = ""
    if portal_url:
        portal_controls += "<div class='field'><label>Member appeal portal link</label><input readonly value='" + _esc(portal_url) + "' onclick='this.select()'><small>Share this link with members. Discord sign-in and server membership are required.</small></div>"
    portal_controls += (
        "<div class='actions'><form method='post' action='/dashboard/action'>" + _csrf_input() +
        "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='appeal_portal_publish'>" +
        "<button class='btn secondary' type='submit'>Publish link in Discord channel</button></form>" +
        "<form method='post' action='/dashboard/action'>" + _csrf_input() +
        "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='appeal_portal_rotate'>" +
        "<button class='btn danger small' type='submit'>Regenerate / revoke old link</button></form></div>"
    )
    appeal_card = (
        "<article class='card full'><h2>Moderation appeals</h2><p class='muted'>Private review channel: " +
        _esc(appeal_channel.mention if appeal_channel else "Not configured") + " · Public link channel: " +
        _esc(public_appeal_channel.mention if public_appeal_channel else "Not configured") + " · Pending: " +
        str(sum(1 for a in appeals.values() if a.get("status") == "pending")) +
        "</p>" + _form(gid, "appeal_settings", appeal_form, "Save appeal channels") +
        portal_controls + "<div class='tablewrap'><table><thead><tr><th>Appeal ID</th><th>Member</th><th>Details preview</th><th>Status</th><th>Review</th></tr></thead><tbody>" +
        appeal_rows_html + "</tbody></table></div></article>"
    )
    note_rows = []
    for member_id, member_notes in notes.items():
        for note_id, note in list((member_notes or {}).items())[-10:]:
            noted_member=guild.get_member(int(member_id)) if str(member_id).isdigit() else None
            author_id=note.get("created_by","")
            note_author=guild.get_member(int(author_id)) if str(author_id).isdigit() else None
            note_rows.append("<tr><td>" + _esc(getattr(noted_member,"display_name","Unknown member")) + "</td><td>" + _esc(str(note_id)) + "</td><td>" + _esc(str(note.get("text", ""))[:180]) + "</td><td>" + _esc(getattr(note_author,"display_name","Unknown moderator")) + "</td></tr>")
    note_rows_html = "".join(note_rows[-30:]) or "<tr><td colspan='4'>No private moderator notes.</td></tr>"
    notes_card = "<article class='card full'><h2>Private moderator notes</h2><p class='muted'>Only administrators and moderators with the appropriate permissions can view or edit these notes.</p><div class='tablewrap'><table><thead><tr><th>Member</th><th>Note ID</th><th>Note preview</th><th>Added by</th></tr></thead><tbody>" + note_rows_html + "</tbody></table></div></article>"
    body = f"<h1>Moderation & safety</h1><p class='muted'>Manage member actions, message filters, join-spike alerts, anti-spam, anti-nuke, private moderator notes, appeals, verification and onboarding.</p><div class='grid'><article class='card third'><div class='statlabel'>Recorded warnings</div><div class='stat'>{warning_count:,}</div></article><article class='card third'><div class='statlabel'>AutoMod</div><div class='stat'><span class='pill {'good' if automod else 'warn'}'>{'Configured' if automod else 'Off'}</span></div></article><article class='card third'><div class='statlabel'>Anti-raid</div><div class='stat'><span class='pill {'good' if antiraid.get('enabled') else 'warn'}'>{'Enabled' if antiraid.get('enabled') else 'Disabled'}</span></div></article>{modcard}{automodcard}{raidcard}{securitycard}{onboardingcard}{appeal_card}{notes_card}</div>"
    return body


def _engagement(guild,state):
    gid=guild.id; xp=state.get("xp_data",{}); levels=state.get("level_roles",{}).get(gid,{})
    channels=state.get("xp_channels",{}).get(gid,set()); per=state.get("xp_per_message",{}).get(gid,20)
    top=sorted(((uid,val) for (g,uid),val in xp.items() if g==gid),key=lambda x:x[1],reverse=True)[:10]
    level_fn=state.get("level_from_xp",lambda n:0)
    rows="".join(f"<tr><td>{i}</td><td>{_esc((guild.get_member(uid).display_name if guild.get_member(uid) else 'Member '+str(uid)))}</td><td>{int(val):,}</td><td>{int(level_fn(val))}</td></tr>" for i,(uid,val) in enumerate(top,1)) or "<tr><td colspan='4'>No XP data yet.</td></tr>"
    role_rows="".join(f"<tr><td>{level}</td><td>{_esc((guild.get_role(rid).name if guild.get_role(rid) else 'Missing role'))}</td><td><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='levelrole_remove'><input type='hidden' name='level' value='{level}'><button class='btn secondary small' type='submit'>Remove</button></form></td></tr>" for level,rid in sorted(levels.items()) if str(level).isdigit()) or "<tr><td colspan='3'>No level roles configured.</td></tr>"
    channel_list="".join(f"<span class='pill good'>#{_esc(guild.get_channel(cid).name if guild.get_channel(cid) else str(cid))}</span> " for cid in sorted(channels)) or "<span class='pill warn'>No channels selected — XP is disabled</span>"
    add_channels=_channel_select(guild,"channel_id",selected=channels,allow_none=False,multiple=True,size=8)
    formcontent="<div class='formgrid'><div class='field'><label>Level (1–200)</label><input name='level' type='number' min='1' max='200' required></div><div class='field'><label>Reward role</label>"+_role_select(guild,"role_id",allow_none=False)+"</div></div>"
    xpcontent=f"<div class='formgrid'><div class='field'><label>XP per eligible message</label><input name='xp_per_message' type='number' min='1' max='1000' value='{int(per)}' required></div><div class='field'><label>XP channels</label>{add_channels}<small>Hold Ctrl/Cmd to select multiple channels. Saving replaces the current XP channel set.</small></div></div><p class='muted'>Cinnamon awards XP only in selected channels, with its built-in 30-second per-member cooldown. Remove channels below when needed.</p>"
    channel_rows="".join(f"<tr><td>#{_esc(guild.get_channel(cid).name if guild.get_channel(cid) else str(cid))}</td><td><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='xp_channel_remove'><input type='hidden' name='channel_id' value='{cid}'><button class='btn secondary small' type='submit'>Remove</button></form></td></tr>" for cid in sorted(channels)) or "<tr><td colspan='2'>No XP channels configured.</td></tr>"
    body=f"<h1>Levels & XP</h1><p class='muted'>Control Cinnamon's message XP, eligible channels and level-role rewards. Level roles are intentionally not created by setup.</p><div class='grid'><article class='card third'><div class='statlabel'>Members with XP</div><div class='stat'>{_count(xp,gid):,}</div></article><article class='card third'><div class='statlabel'>XP per message</div><div class='stat'>{int(per):,}</div></article><article class='card third'><div class='statlabel'>XP channels</div><div class='stat'>{len(channels):,}</div></article><article class='card half'><h2>XP settings</h2>{_form(gid,'xp_settings',xpcontent,'Save XP settings')}<div class='rule'></div><div>{channel_list}</div><div class='tablewrap'><table><thead><tr><th>Eligible channel</th><th></th></tr></thead><tbody>{channel_rows}</tbody></table></div></article><article class='card half'><h2>Level rewards</h2><div class='tablewrap'><table><thead><tr><th>Level</th><th>Role</th><th></th></tr></thead><tbody>{role_rows}</tbody></table></div><div class='rule'></div>{_form(gid,'levelrole_add',formcontent,'Add level reward')}</article><article class='card full'><h2>XP leaderboard</h2><div class='tablewrap'><table><thead><tr><th>#</th><th>Member</th><th>XP</th><th>Level</th></tr></thead><tbody>{rows}</tbody></table></div></article></div>"
    return body


def _achievements(guild,state):
    gid=guild.id; data=state.get("achievement_data",{}); cfg=state.get("achievement_config",{}).get(gid,{})
    normal=state.get("ACHIEVEMENTS",{}); secret=state.get("SECRET_ACHIEVEMENTS",{}); admin=state.get("ADMIN_ACHIEVEMENT",{}) or {}
    users=[(uid,v) for (g,uid),v in data.items() if g==gid and isinstance(v,dict)]
    unlocked=sum(len(v.get("unlocked",[])) for _,v in users); unique_users=len(users)
    log_id=cfg.get("log_channel") or state.get("category_log_channels",{}).get(gid,{}).get("achievements")
    logch=guild.get_channel(log_id) if log_id else None
    role_names=sorted({str(a.get("role")).strip() for a in list(normal.values())+list(secret.values())+[admin] if a.get("role")})
    missing=[n for n in role_names if not any(r.name==n for r in guild.roles)]
    rows="".join(f"<tr><td><b>{_esc(aid)}</b><div class='muted'>{_esc(a.get('name','Unnamed'))}</div></td><td>{_esc(a.get('description',''))}</td><td>{'Secret' if aid in secret else 'Normal'}</td><td>{'Enabled' if a.get('enabled',True) else 'Disabled'}</td></tr>" for aid,a in list(normal.items())[:100]) or "<tr><td colspan='4'>No achievement definitions exposed.</td></tr>"
    secrets_count=len(secret); enabled=cfg.get("enabled",True)
    achievement_form="<div class='formgrid'><div class='field'><label>Achievement log channel</label>"+_channel_select(guild,"channel_id",log_id)+"</div></div><label class='toggle'><input type='checkbox' name='enabled' "+("checked" if enabled else "")+"><span><b>Enable achievement tracking</b><small>Disabling pauses achievement processing; existing unlock data is retained.</small></span></label>"
    role_readiness_rows = ''.join(f"<tr><td>@{_esc(n)}</td><td><span class='pill {'good' if n not in missing else 'warn'}'>{'Ready' if n not in missing else 'Missing'}</span></td></tr>" for n in role_names)
    return f"<h1>Achievements</h1><p class='muted'>Monitor achievements and manage the server-level configuration without exposing every achievement command in the web panel.</p><div class='grid'><article class='card third'><div class='statlabel'>Normal achievements</div><div class='stat'>{len(normal):,}</div></article><article class='card third'><div class='statlabel'>Secret achievements</div><div class='stat'>{secrets_count:,}</div></article><article class='card third'><div class='statlabel'>Members tracked</div><div class='stat'>{unique_users:,}</div></article><article class='card half'><h2>Achievement system</h2><div class='toggle'><b>Status</b><span class='pill {'good' if enabled else 'warn'}'>{'Enabled' if enabled else 'Disabled'}</span></div><div class='toggle'><b>Total unlock records</b><span>{unlocked:,}</span></div><div class='toggle'><b>Achievement logs</b><span>{_esc(logch.mention if logch else 'Not configured')}</span></div><div class='toggle'><b>Reward roles missing</b><span>{len(missing):,}</span></div><p class='muted'>Use Discord's achievement commands for individual awards, revokes and definition editing. The dashboard focuses on server configuration and visibility.</p>{_form(gid,'achievement_settings',achievement_form,'Save achievement settings')}</article><article class='card half'><h2>Reward-role readiness</h2><div class='tablewrap'><table><thead><tr><th>Role</th><th>Status</th></tr></thead><tbody>{role_readiness_rows}</tbody></table></div></article><article class='card full'><h2>Achievement catalog</h2><div class='tablewrap'><table><thead><tr><th>ID / Name</th><th>Description</th><th>Type</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div></article></div>"


def _quests(guild,state):
    gid=guild.id; qdata=state.get("quest_data",{}).get(gid,{}) or {}; qcfg=state.get("quest_config",{}).get(gid,{}) or {}
    daily_defs=state.get("DAILY_QUESTS",{}); weekly_defs=state.get("WEEKLY_QUESTS",{})
    daily_ids=qdata.get("daily_ids",[]) if isinstance(qdata,dict) else []; weekly_ids=qdata.get("weekly_ids",[]) if isinstance(qdata,dict) else []
    log_id=state.get("category_log_channels",{}).get(gid,{}).get("quests"); logch=guild.get_channel(log_id) if log_id else None
    def rows(ids,pool):
        out=[]
        for qid in ids if isinstance(ids,list) else []:
            q=pool.get(qid,{})
            out.append(f"<tr><td><b>{_esc(q.get('name',qid))}</b></td><td>{_esc(q.get('desc',q.get('description','')))}</td><td>{int(q.get('qp',0)):,} QP + {int(q.get('xp',0)):,} XP</td></tr>")
        return ''.join(out) or "<tr><td colspan='3'>No rotation has been generated yet.</td></tr>"
    role=qcfg.get("quest_master_role"); role_obj=guild.get_role(int(role)) if str(role).isdigit() else None
    role_form="<div class='field'><label>Quest Master role</label>"+_role_select(guild,"role_id",role)+"</div>"
    return f"<h1>Quests</h1><p class='muted'>Daily and weekly quest visibility, Quest Master configuration and logging. Quest completion remains in Discord.</p><div class='grid'><article class='card third'><div class='statlabel'>Daily active</div><div class='stat'>{len(daily_ids):,}</div></article><article class='card third'><div class='statlabel'>Weekly active</div><div class='stat'>{len(weekly_ids):,}</div></article><article class='card third'><div class='statlabel'>Quest log</div><div class='stat'>{_esc(logch.name if logch else 'Off')}</div></article><article class='card half'><h2>Daily rotation</h2><div class='tablewrap'><table><thead><tr><th>Quest</th><th>Description</th><th>Reward</th></tr></thead><tbody>{rows(daily_ids,daily_defs)}</tbody></table></div></article><article class='card half'><h2>Weekly rotation</h2><div class='tablewrap'><table><thead><tr><th>Quest</th><th>Description</th><th>Reward</th></tr></thead><tbody>{rows(weekly_ids,weekly_defs)}</tbody></table></div></article><article class='card full'><h2>Quest settings</h2><div class='toggle'><b>Quest Master role</b><span>{_esc(role_obj.mention if role_obj else 'Not configured')}</span></div>{_form(gid,'quest_settings',role_form,'Save Quest Master role')}<p class='muted'>The full quest-definition editor stays in Discord so the dashboard does not become a duplicate of every Cinnamon command.</p></article></div>"


def _friendship(guild,state):
    gid=guild.id; fd=state.get("friendship_data",{}); entries=[]
    thresholds=[(0,'Stranger'),(25,'Familiar Face'),(75,'Friend'),(200,'Trusted Human'),(500,"Cinnamon's Best Friend"),(1000,"Cinnamon's Chosen Human")]
    for (g,u),v in fd.items():
        if g==gid and isinstance(v,dict): entries.append((u,int(v.get('points',0)),int(v.get('level',0))))
    entries.sort(key=lambda x:x[1],reverse=True); rows=''.join(f"<tr><td>{i}</td><td>{_esc(guild.get_member(u).display_name if guild.get_member(u) else 'Member '+str(u))}</td><td>{pts:,}</td><td>{lvl}</td></tr>" for i,(u,pts,lvl) in enumerate(entries[:25],1)) or "<tr><td colspan='4'>No friendship data yet.</td></tr>"
    log_id=state.get("category_log_channels",{}).get(gid,{}).get("friendship"); ch=guild.get_channel(log_id) if log_id else None
    levels=''.join(f"<div class='toggle'><b>{name}</b><span>{points:,} points</span></div>" for points,name in thresholds)
    return f"<h1>Cinnamon Friendship</h1><p class='muted'>See friendship progress and server-level logging. Individual friendship interactions stay in Discord.</p><div class='grid'><article class='card third'><div class='statlabel'>Tracked humans</div><div class='stat'>{len(entries):,}</div></article><article class='card third'><div class='statlabel'>Friendship log</div><div class='stat'>{_esc(ch.name if ch else 'Off')}</div></article><article class='card third'><div class='statlabel'>Highest points</div><div class='stat'>{entries[0][1] if entries else 0:,}</div></article><article class='card half'><h2>Friendship levels</h2>{levels}</article><article class='card half'><h2>Leaderboard</h2><div class='tablewrap'><table><thead><tr><th>#</th><th>Member</th><th>Points</th><th>Level</th></tr></thead><tbody>{rows}</tbody></table></div></article></div>"


def _economy(guild,state):
    gid=guild.id; balances=state.get("economy_balances",{}); inventory=state.get("economy_inventory",{})
    entries=sorted(((uid,val) for (g,uid),val in balances.items() if g==gid),key=lambda x:x[1],reverse=True)[:10]
    rows="".join(f"<tr><td>{i}</td><td>{_esc(guild.get_member(uid).display_name if guild.get_member(uid) else 'Member '+str(uid))}</td><td>{int(val):,} 🌿</td><td>{sum(int(q) for q in inventory.get((gid,uid),{}).values())}</td></tr>" for i,(uid,val) in enumerate(entries,1)) or "<tr><td colspan='4'>No economy balances yet.</td></tr>"
    total=sum(int(v) for (g,_),v in balances.items() if g==gid); users=_count(balances,gid)
    shop=state.get("ECONOMY_ITEMS",{}); items=[]
    for key,item in shop.items():
        form=f"<form method='post' action='/dashboard/action' class='formgrid'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='shop_item_save'><input type='hidden' name='item_id' value='{_esc(key)}'><div class='field'><label>Name</label><input name='name' maxlength='80' value='{_esc(item.get('name',key))}' required></div><div class='field'><label>Price (Catnip)</label><input name='price' type='number' min='1' max='10000000' value='{int(item.get('price',1))}' required></div><div class='field'><label>Emoji</label><input name='emoji' maxlength='8' value='{_esc(item.get('emoji','🐾'))}'></div><div class='field'><label>Per-member limit (0 = unlimited)</label><input name='max_per_person' type='number' min='0' max='999999' value='{int(item.get('max_per_person',0))}'></div><div class='field' style='grid-column:1/-1'><label>Description</label><input name='description' maxlength='300' value='{_esc(item.get('description',''))}'></div><label class='toggle'><input type='checkbox' name='shop_enabled'{' checked' if item.get('shop_enabled', False) else ''}><span><b>Show in shop</b></span></label><label class='toggle'><input type='checkbox' name='craftable'{' checked' if item.get('craftable', False) else ''}><span><b>Craftable output</b></span></label><div class='actions' style='grid-column:1/-1'><button class='btn small' type='submit'>Save item</button></div></form><form method='post' action='/dashboard/action' data-confirm='Remove this shop item? Existing inventory will be kept but the item can no longer be purchased or used.'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='shop_item_disable'><input type='hidden' name='item_id' value='{_esc(key)}'><button class='btn danger small' type='submit'>Remove item</button></form>"
        items.append(
            "<div class='catalogitem'><div class='cataloghead'><span class='catalogname'>"
            + _esc(item.get('emoji','🐾')) + " " + _esc(item.get('name',key))
            + "</span><code>" + _esc(key) + "</code></div>" + form + "</div>"
        )
    item_rows="".join(items) or "<p class='empty'>No shop items available.</p>"
    add_form="<div class='formgrid'><div class='field'><label>Item ID (unique)</label><input name='item_id' maxlength='40' pattern='[a-zA-Z0-9_-]+' required></div><div class='field'><label>Name</label><input name='name' maxlength='80' required></div><div class='field'><label>Price</label><input name='price' type='number' min='1' max='10000000' required></div><div class='field'><label>Emoji</label><input name='emoji' maxlength='8' value='🐾'></div><div class='field'><label>Per-member limit (0 = unlimited)</label><input name='max_per_person' type='number' min='0' max='999999' value='0'></div><div class='field'><label>Description</label><input name='description' maxlength='300'></div></div>"
    add_card="<article class='card full'><h2>Add shop item</h2>"+_form(gid,"shop_item_add",add_form + "<label class='toggle'><input type='checkbox' name='shop_enabled' checked><span><b>Show in shop</b></span></label><label class='toggle'><input type='checkbox' name='craftable'><span><b>Can be crafted</b></span></label>","Create item")+"</article>"
    income_cfg=state.get("economy_income_roles",{}).get(gid,{}) or state.get("economy_income_roles",{}).get(str(gid),{})
    income_rows=[]
    for role_id,cfg in income_cfg.items():
        role=guild.get_role(int(role_id)) if str(role_id).isdigit() else None
        if not role: role_name=f"Missing role ({role_id})"
        else: role_name=role.mention
        amount=max(0,int(cfg.get("amount",0))); cooldown=max(60,int(cfg.get("cooldown",3600)))
        interval=int(cfg.get("interval",max(1,cooldown//60))); unit=str(cfg.get("unit","minute"))
        income_rows.append(f"<div class='toggle'><span><b>{_esc(role_name)}</b><small>{amount:,} Catnip every {interval} {_esc(unit)}(s)</small></span><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='economy_income_remove'><input type='hidden' name='role_id' value='{_esc(role_id)}'><button class='btn danger small' type='submit'>Remove</button></form></div>")
    income_add="<div class='formgrid'><div class='field'><label>Income role</label>"+_role_select(guild,"role_id",allow_none=False)+"</div><div class='field'><label>Catnip per collection</label><input name='amount' type='number' min='1' max='1000000' value='100' required></div><div class='field'><label>Interval</label><input name='interval' type='number' min='1' max='1000' value='1' required></div><div class='field'><label>Time unit</label><select name='unit'><option value='minute'>Minutes</option><option value='hour'>Hours</option><option value='day'>Days</option><option value='week'>Weeks</option></select></div></div>"
    income_card="<article class='card full'><h2>Role-based Catnip income</h2><p class='muted'>Members with a configured role can collect its recurring income using Cinnamon's existing collect command. Role income changes are audited and saved to the bot's data store.</p>"+(''.join(income_rows) or "<p class='muted'>No role income rules configured.</p>")+_form(gid,"economy_income_add",income_add,"Save role income")+"</article>"
    body=f"<h1>Catnip economy</h1><p class='muted'>Manage the shared shop catalog, role income rules, and live economy statistics. Member balances and inventories are preserved.</p><div class='grid'><article class='card third'><div class='statlabel'>Economy members</div><div class='stat'>{users:,}</div></article><article class='card third'><div class='statlabel'>Total Catnip in circulation</div><div class='stat'>{total:,} 🌿</div></article><article class='card third'><div class='statlabel'>Shop items</div><div class='stat'>{len(shop)}</div></article><article class='card half'><h2>Top balances</h2><div class='tablewrap'><table><thead><tr><th>#</th><th>Member</th><th>Balance</th><th>Items</th></tr></thead><tbody>{rows}</tbody></table></div></article><article class='card half'><h2>Economy configuration</h2><p class='muted'>Daily reward: <b>{int(state.get('ECONOMY_DAILY_REWARD',150)):,} Catnip</b></p><p class='muted'>Work range: <b>{int(state.get('ECONOMY_WORK_MIN',50)):,}–{int(state.get('ECONOMY_WORK_MAX',150)):,}</b></p><p class='muted'>Work cooldown: <b>{int(state.get('ECONOMY_WORK_COOLDOWN',600))//60} minutes</b></p><p class='muted'>Economy logs: {_esc(guild.get_channel(state.get('economy_log_channels',{}).get(gid)).mention if guild.get_channel(state.get('economy_log_channels',{}).get(gid)) else 'Not configured')}</p></article><article class='card full'><h2>Catnip shop catalog</h2><p class='muted'>Each item below is editable in place. Saving updates the shared catalog without touching member inventories.</p><div class='itemlist'>{item_rows}</div></article>{add_card}{income_card}</div>"
    gift_form=(
        "<div class='field'><label>Choose a member by name</label>" +
        _member_select(guild,"member_id",allow_none=True,size=7) +
        "<small>Names are displayed, Discord IDs are submitted internally. This transfers Catnip from your OWN wallet.</small></div>"
        "<div class='field'><label>Catnip amount</label><input type='number' name='amount' min='1' max='10000000' required></div>"
        "<input type='hidden' name='transfer_nonce' value='" + _esc(secrets.token_urlsafe(24)) + "'>"
        "<p class='muted'>A positive-only transfer; saved with an idempotency key and recorded in Economy Logs.</p>")
    body=body.replace("</div>", "</div>", 1)  # keep old layout unchanged.
    body=body[:-6] + "<article class='card full'><h2>🌿 Give Catnip to a member</h2>" + _form(gid,"economy_transfer",gift_form,"Transfer Catnip") + "</article></div>"
    return body


def _automation(guild,state):
    gid=guild.id
    welcome=state.get("welcome_config",{}).get(gid,{}) or state.get("welcome_config",{}).get(str(gid),{})
    goodbye=state.get("goodbye_config",{}).get(gid,{}) or state.get("goodbye_config",{}).get(str(gid),{})
    ai=state.get("ai_channels",{}).get(gid) or state.get("ai_channels",{}).get(str(gid))
    automod=state.get("automod_config",{}).get(gid,{}) or state.get("automod_config",{}).get(str(gid),{})
    antiraid=state.get("antiraid_config",{}).get(gid,{}) or state.get("antiraid_config",{}).get(str(gid),{})
    schedules=[cfg for cfg in (state.get("giveaway_schedules",{}) or {}).values() if int(cfg.get("guild_id",0))==gid and cfg.get("enabled",True)]
    def pill(on): return "<span class='pill good'>Active</span>" if on else "<span class='pill warn'>Not configured</span>"
    cards=(f"<article class='card third'><div class='statlabel'>Welcome messages</div><div class='stat'>{'On' if welcome else 'Off'}</div>{pill(bool(welcome))}</article>"
           f"<article class='card third'><div class='statlabel'>Goodbye messages</div><div class='stat'>{'On' if goodbye else 'Off'}</div>{pill(bool(goodbye))}</article>"
           f"<article class='card third'><div class='statlabel'>Cinnamon conversations</div><div class='stat'>{'On' if ai else 'Off'}</div>{pill(bool(ai))}</article>"
           f"<article class='card third'><div class='statlabel'>AutoMod rules</div><div class='stat'>{'On' if automod else 'Off'}</div>{pill(bool(automod))}</article>"
           f"<article class='card third'><div class='statlabel'>Anti-raid</div><div class='stat'>{'On' if antiraid.get('enabled') else 'Off'}</div>{pill(bool(antiraid.get('enabled')))}</article>"
           f"<article class='card third'><div class='statlabel'>Recurring giveaways</div><div class='stat'>{len(schedules)}</div>{pill(bool(schedules))}</article>")
    welcome_content="<div class='formgrid'><div class='field'><label>Welcome channel</label>"+_channel_select(guild,"channel_id",welcome.get("channel_id"))+"</div><div class='field'><label>Message template</label><input name='message' maxlength='800' required value='"+_esc(welcome.get("message","Welcome {member} to {server}! 🐾"))+"'></div></div><p class='muted'>Supported placeholders: {member} and {server}.</p>"
    goodbye_content="<div class='formgrid'><div class='field'><label>Goodbye channel</label>"+_channel_select(guild,"channel_id",goodbye.get("channel_id"))+"</div><div class='field'><label>Message template</label><input name='message' maxlength='800' required value='"+_esc(goodbye.get("message","Goodbye {member}. Thanks for visiting {server}! 🐾"))+"'></div></div><p class='muted'>Supported placeholders: {member} and {server}.</p>"
    ai_content="<div class='field'><label>Cinnamon conversation channel (invitation-only)</label>"+_channel_select(guild,"channel_id",ai)+"</div><p class='muted'>Cinnamon only responds when someone pings, replies to her, or calls her by name. Use the Community & AI page to configure related options.</p>"
    quick="<div class='actions'><a class='btn secondary' href='/dashboard?guild_id="+str(gid)+"&tab=moderation'>Configure AutoMod & anti-raid</a><a class='btn secondary' href='/dashboard?guild_id="+str(gid)+"&tab=giveaways'>Manage giveaway schedules</a><a class='btn secondary' href='/dashboard?guild_id="+str(gid)+"&tab=system'>Manage logs & recovery</a></div>"
    return ("<h1>Automation Studio</h1><p class='muted'>A single place to monitor Cinnamon's event-driven automations and jump into their detailed settings. Changes are permission-checked and saved through the existing bot data store.</p><div class='grid'>"+cards+"</div><div class='grid'><article class='card half'><h2>Welcome automation</h2>"+_form(gid,"welcome",welcome_content,"Save welcome rule")+"</article><article class='card half'><h2>Goodbye automation</h2>"+_form(gid,"goodbye",goodbye_content,"Save goodbye rule")+"</article><article class='card full'><h2>Cinnamon conversations</h2>"+_form(gid,"ai_channel",ai_content,"Save AI channel")+"</article><article class='card full'><h2>Rule management</h2><p class='muted'>AutoMod, anti-raid, XP filters, scheduled giveaways, and log routing are managed by their dedicated pages. This hub shows their current state without pretending disabled rules are running.</p>"+quick+"</article></div>")



def _tickets(guild,state):
    gid=guild.id
    root=(state.get("advanced_features_data",{}) or {}).get("cinnamon_tickets_v1",{}) or {}
    cfg=root.get(str(gid),{}) or {}
    root[str(gid)]=cfg
    settings=cfg.get("settings",{}) or {}
    panels=cfg.get("panels",{}) or {}
    default_panels={
        "default-shop":{"id":"default-shop","name":"Shop Ticket","title":"Shop Tickets","description":"Select the shop item you purchased to open a private service ticket.","color":"#D99048","published":False,"categories":[{"id":"shop","label":"Shop Ticket","button_label":"Shop Ticket","emoji":"🛍️","routing":"shop","welcome_message":"Thanks for opening a shop ticket. A staff member will claim it shortly.","questions":[{"label":"What do you need help with?","required":True,"paragraph":True,"max_length":400}],"inventory_item_ids":[]}]},
        "default-support":{"id":"default-support","name":"Support Ticket","title":"Support Center","description":"Open a private ticket for general help.","color":"#D99048","published":False,"categories":[{"id":"support","label":"Support Ticket","button_label":"Support Ticket","emoji":"🎫","routing":"support","welcome_message":"Thanks for contacting Cinnamon support.","questions":[{"label":"Why did you open this ticket?","required":True,"paragraph":True,"max_length":800}]}]}
    }
    for default_id,default_panel in default_panels.items():
        panels.setdefault(default_id,default_panel)
    cfg["panels"]=panels
    tickets=cfg.get("tickets",{}) or {}
    open_count=sum(1 for t in tickets.values() if t.get("status")=="open")
    closed_count=len(cfg.get("closed",{}) or {})
    log_form="<div class='formgrid'><div class='field'><label>Ticket log channel</label>"+_channel_select(guild,"log_channel_id",settings.get("log_channel_id"))+"</div><div class='field'><label>Ticket parent category</label>"+_category_select(guild,"ticket_category_id",settings.get("ticket_category_id"))+"</div><div class='field'><label>Maximum open tickets per member</label><input name='max_open_per_user' type='number' min='1' max='10' value='"+str(max(1,min(10,int(settings.get("max_open_per_user",3)))))+"'></div><div class='field'><label>Opening cooldown (seconds)</label><input name='cooldown_seconds' type='number' min='0' max='86400' value='"+str(max(0,min(86400,int(settings.get("cooldown_seconds",60)))))+"'></div><div class='field'><label>Auto-close after inactivity (hours; 0 disables)</label><input name='auto_close_hours' type='number' min='0' max='720' value='"+str(max(0,min(720,int(settings.get("auto_close_hours",0)))))+"'></div></div><div class='toggle'><input type='checkbox' name='transcript_on_close'"+(" checked" if settings.get("transcript_on_close",True) else "")+"><span><b>Attach HTML transcript to logs on close</b><small>Transcript is sent to the configured log channel.</small></span></div><div class='toggle'><input type='checkbox' name='rating_enabled'"+(" checked" if settings.get("rating_enabled",True) else "")+"><span><b>Ask ticket creators to rate closed tickets</b><small>Members receive a private 1–5 rating prompt.</small></span></div>"
    log_form+= "<div class='field'><label>General ticket staff roles</label>"+_role_multi_select(guild,"staff_role_ids",settings.get("staff_role_ids",[]))+"</div><div class='field'><label>Moderator roles for ordinary shop tickets</label>"+_role_multi_select(guild,"moderator_role_ids",settings.get("moderator_role_ids",[]))+"</div><div class='field'><label>Trusted Booster roles for GAG services</label>"+_role_multi_select(guild,"trusted_booster_role_ids",settings.get("trusted_booster_role_ids",[]))+"</div>"
    settings_card="<article class='card full'><h2>Ticket settings</h2><p class='muted'>Changes are validated and saved together. Ticket settings and metadata live inside Cinnamon's Upstash-backed snapshot.</p>"+_form(gid,"ticket_settings_save",log_form,"Save ticket settings")+"</article>"
    gag_items = state.get("ECONOMY_ITEMS", {}) or {}
    gag_options = "".join("<option value='" + _esc(item_id) + "'>" + _esc(item.get("name", item_id)) + "</option>" for item_id, item in gag_items.items() if item.get("category") == "grow_a_garden")
    service_select = "<div class='field full' data-panel-feature='gag'><label>Linked Grow a Garden service items</label><select name='service_item_ids' multiple size='6'>" + gag_options + "</select><small>Select multiple registered GAG services. Members can still choose their own eligible inventory items when opening a ticket.</small></div>"
    inventory_options = "".join("<option value='"+_esc(item_id)+"'>"+_esc(str(item.get("emoji","🐾"))+" "+str(item.get("name",item_id)))+"</option>" for item_id,item in sorted(gag_items.items(),key=lambda pair:str((pair[1] or {}).get("name",pair[0])).casefold()) if isinstance(item,dict))
    inventory_select = "<div class='field full' data-panel-feature='items'><label>Eligible inventory items</label><select name='inventory_item_ids' multiple size='6'>"+inventory_options+"</select><small>For Shop routing, select which owned items members may choose. Leave empty to allow every item they own.</small></div>"
    category_roles = "<div class='field full'><label>Additional ticket ping roles</label>"+_role_multi_select(guild,"category_staff_role_ids",[])+ "<small>Use this for custom routing; the default Moderator / Trusted Booster roles are configured above.</small></div>"
    create="<div class='formgrid'><div class='field'><label>Panel name (dashboard label)</label><input name='panel_name' maxlength='60' required placeholder='Support Center'></div><div class='field'><label>Publish channel</label>"+_channel_select(guild,"channel_id",allow_none=False)+"</div><div class='field'><label>Panel title</label><input name='panel_title' maxlength='256' required value='Cinnamon Support Center'></div><div class='field'><label>Embed color (hex)</label><input name='panel_color' maxlength='7' value='#D99048'></div><div class='field full'><label>Panel description</label><textarea name='panel_description' maxlength='3500'>Choose a category below to open a private support ticket.</textarea></div><div class='field'><label>First category name</label><input name='category_label' maxlength='60' required value='General Support'></div><div class='field'><label>Button label</label><input name='button_label' maxlength='80' required value='Open Support Ticket'></div><div class='field'><label>Button emoji (optional)</label><input name='button_emoji' maxlength='100' placeholder='🎫'></div><div class='field'><label>Routing</label><select name='routing'><option value='support'>General support</option><option value='shop'>Shop support</option><option value='grow_a_garden'>Grow a Garden / boosting</option></select></div><div class='field full'><label class='toggle'><input type='checkbox' name='gag_features_enabled' value='1' checked><span><b>Enable Grow a Garden features</b><small>Turn off to remove GAG routing and linked GAG service options from this panel.</small></span></label></div><div class='field full'><label class='toggle'><input type='checkbox' name='item_features_enabled' value='1' checked><span><b>Enable item features</b><small>Turn off to remove shop inventory selection and item-related ticket options from this panel.</small></span></label></div>"+service_select+"<div class='field full'><label>Welcome message / Cinnamon's first reply</label><textarea name='welcome_message' maxlength='1500'>Thanks for opening a ticket. Staff will help you here.</textarea></div>"+inventory_select+category_roles+"<div class='field'><label>Persistent button label (optional)</label><input name='persistent_button_label' maxlength='80' placeholder='View service instructions'></div><div class='field full'><label>Persistent button reply</label><textarea name='persistent_button_reply' maxlength='1800' placeholder='Cinnamon sends this reply when the button is clicked.'></textarea></div><div class='field'><label>Question 1</label><input name='question1' maxlength='45' placeholder='What do you need help with?'></div><div class='field'><label>Question 2</label><input name='question2' maxlength='45' placeholder='What did you purchase?'></div><div class='field'><label>Question 3</label><input name='question3' maxlength='45' placeholder='Order ID'></div><div class='field'><label>Question 4</label><input name='question4' maxlength='45' placeholder='Describe the issue'></div><div class='field'><label>Question 5</label><input name='question5' maxlength='45' placeholder='Anything else?'></div><div class='field full'><label>Optional multi-category JSON (overrides the single category above)</label><textarea name='categories_json' maxlength='12000' placeholder='Paste a JSON category list here'></textarea><small>Each category can have its own modal questions, routing (support/shop/grow_a_garden), button emoji/style, welcome text and ticket naming format.</small></div></div>"
    create_card="<article class='card full'><h2>Create ticket panel</h2><p class='muted'>Create a panel configuration first, then publish it separately. Modal questions are asked before the private channel is created.</p>"+_form(gid,"ticket_panel_save",create,"Save panel draft")+"</article><script>(function(){function sync(f){var g=f.querySelector('[name=gag_features_enabled]'),it=f.querySelector('[name=item_features_enabled]');f.querySelectorAll('[data-panel-feature]').forEach(function(w){var on=w.dataset.panelFeature==='gag'?!g||g.checked:!it||it.checked;w.hidden=!on;w.querySelectorAll('input,select,textarea').forEach(function(x){x.disabled=!on;});});var route=f.querySelector('[name=routing]');if(route){Array.from(route.options).forEach(function(o){if(o.value==='grow_a_garden')o.disabled=!!g&&!g.checked;if(o.value==='shop')o.disabled=!!it&&!it.checked;});if(route.selectedOptions.length&&route.selectedOptions[0].disabled)route.value='support';}}document.addEventListener('change',function(e){if(e.target&&['gag_features_enabled','item_features_enabled'].includes(e.target.name)){var f=e.target.closest('form');if(f)sync(f);}});document.querySelectorAll('form').forEach(function(f){if(f.querySelector('[name=gag_features_enabled]')||f.querySelector('[name=item_features_enabled]'))sync(f);});})();</script>"
    panel_rows=[]
    for pid,p in sorted(panels.items()):
        state_label="Published" if p.get("published") else "Draft"
        ch=guild.get_channel(int(p.get("channel_id",0) or 0))
        cats=p.get("categories",[]) or []
        first_cat=cats[0] if cats else {}
        selected_ids={str(x) for x in first_cat.get("inventory_item_ids",[])}
        panel_inventory_options="".join("<option value='"+_esc(item_id)+"'"+(" selected" if str(item_id) in selected_ids else "")+">"+_esc(str(item.get("emoji","🐾"))+" "+str(item.get("name",item_id)))+"</option>" for item_id,item in sorted(gag_items.items(),key=lambda pair:str((pair[1] or {}).get("name",pair[0])).casefold()) if isinstance(item,dict))
        panel_questions=first_cat.get("questions",[]) or []
        question_fields="".join("<div class='field'><label>Question "+str(i+1)+"</label><input name='question"+str(i+1)+"' maxlength='45' value='"+_esc((panel_questions[i] if i<len(panel_questions) else {}).get("label",""))+"'></div>" for i in range(5))
        panel_routing=str(first_cat.get("routing","support"))
        routing_options="".join("<option value='"+value+"'"+(" selected" if panel_routing==value else "")+">"+label+"</option>" for value,label in (("support","General support"),("shop","Shop support"),("grow_a_garden","Grow a Garden / boosting")))
        panel_selected_service_ids={str(x) for x in (first_cat.get("service_item_ids") or ([first_cat.get("service_item_id")] if first_cat.get("service_item_id") else []))}
        panel_service_options="".join("<option value='"+_esc(item_id)+"'"+(" selected" if str(item_id) in panel_selected_service_ids else "")+">"+_esc(item.get("name",item_id))+"</option>" for item_id,item in gag_items.items() if isinstance(item,dict) and item.get("category")=="grow_a_garden")
        panel_category_editor="<div class='formgrid'><div class='field'><label>Category name</label><input name='category_label' maxlength='60' required value='"+_esc(first_cat.get("label","Support"))+"'></div><div class='field'><label>Ticket button label</label><input name='button_label' maxlength='80' required value='"+_esc(first_cat.get("button_label",first_cat.get("label","Open ticket")))+"'></div><div class='field'><label>Button emoji</label><input name='button_emoji' maxlength='100' value='"+_esc(first_cat.get("emoji",""))+"'></div><div class='field'><label>Routing</label><select name='routing'>"+routing_options+"</select></div><div class='field full' data-panel-feature='gag'><label>Linked GAG service items</label><select name='service_item_ids' multiple size='6'>"+panel_service_options+"</select><small>Select multiple services if this category handles more than one.</small></div><div class='field full'><label>Welcome message / Cinnamon's first reply</label><textarea name='welcome_message' maxlength='1500'>"+_esc(first_cat.get("welcome_message",""))+"</textarea></div><div class='field full' data-panel-feature='items'><label>Eligible inventory items</label><select name='inventory_item_ids' multiple size='6'>"+panel_inventory_options+"</select><small>For Shop routing, leave empty to allow all items members own.</small></div><div class='field full'><label>Additional ticket ping roles</label>"+_role_multi_select(guild,"category_staff_role_ids",first_cat.get("staff_role_ids",[]))+"</div>"+question_fields+"<div class='field'><label>Persistent button label</label><input name='persistent_button_label' maxlength='80' value='"+_esc(first_cat.get("persistent_button_label",""))+"'></div><div class='field full'><label>Persistent button reply</label><textarea name='persistent_button_reply' maxlength='1800'>"+_esc(first_cat.get("persistent_button_reply",""))+"</textarea></div></div>"
        panel_rows.append("<article class='card full'><h3>"+_esc(p.get("name","Ticket panel"))+" <span class='pill'>"+state_label+"</span></h3><p class='muted'>"+_esc("#"+ch.name if ch else "No channel")+" · "+str(len(cats))+" categories</p>"+_form(gid,"ticket_panel_update","<input type='hidden' name='panel_id' value='"+_esc(pid)+"'><div class='formgrid'><div class='field'><label>Panel name</label><input name='panel_name' maxlength='60' required value='"+_esc(p.get("name",""))+"'></div><div class='field'><label>Channel</label>"+_channel_select(guild,"channel_id",p.get("channel_id"),allow_none=False)+"</div><div class='field'><label>Title</label><input name='panel_title' maxlength='256' required value='"+_esc(p.get("title","Support Center"))+"'></div><div class='field'><label>Color</label><input name='panel_color' maxlength='7' value='"+_esc(p.get("color","#D99048"))+"'></div><div class='field full'><label>Description</label><textarea name='panel_description' maxlength='3500'>"+_esc(p.get("description",""))+"</textarea></div>"+"<div class='field full'><label class='toggle'><input type='checkbox' name='gag_features_enabled' value='1'"+(" checked" if p.get("gag_features_enabled",True) else "")+"><span><b>Enable Grow a Garden features</b><small>Allow GAG ticket routing and linked services on this panel.</small></span></label></div><div class='field full'><label class='toggle'><input type='checkbox' name='item_features_enabled' value='1'"+(" checked" if p.get("item_features_enabled",True) else "")+"><span><b>Enable item features</b><small>Allow shop inventory and item selection on this panel.</small></span></label></div>"+panel_category_editor+"<div class='field full'><details><summary>Advanced multi-category editor (JSON)</summary><textarea name='categories_json' maxlength='12000' placeholder='Paste a JSON category list only to replace the categories above'></textarea><small>Optional advanced override. Leave blank to save the no-code editor above.</small></details></div></div>","Save panel settings")+
        "<div class='actions'><form method='post' action='/dashboard/action' class='actions'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='ticket_panel_publish'><input type='hidden' name='panel_id' value='"+_esc(pid)+"'><label class='field'><span>Send panel to channel</span>"+_channel_select(guild,'publish_channel_id',p.get('channel_id'),allow_none=False)+"</label><button class='btn'>"+("Update published panel" if p.get("published") else "Publish panel")+"</button></form><form method='post' action='/dashboard/action' data-confirm='Delete this panel configuration?'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='ticket_panel_delete'><input type='hidden' name='panel_id' value='"+_esc(pid)+"'><button class='btn danger small'>Delete</button></form></div></article>")
    panel_card="<article class='card full'><h2>Ticket panels</h2>"+("".join(panel_rows) or "<p class='empty'>No panels yet.</p>")+"</article>"
    ticket_query = request.args.get("ticket_q", "").strip().casefold()[:100]
    active_parts = []
    priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    active_tickets = [t for t in tickets.values() if t.get("status") == "open"]
    active_tickets.sort(key=lambda t: (priority_order.get(str(t.get("priority", "normal")).lower(), 2), float(t.get("created_at", 0) or 0)))
    member_options = "".join("<option value='" + str(m.id) + "'>" + _esc(m.display_name) + "</option>" for m in sorted(guild.members, key=lambda m: m.display_name.casefold())[:500] if not m.bot)
    for t in active_tickets:
        ch = guild.get_channel(int(t.get("channel_id", 0) or 0))
        channel_name = ("#" + ch.name) if ch else ("Unknown channel " + str(t.get("channel_id", "")))
        creator_member = guild.get_member(int(t.get("creator_id",0) or 0))
        creator_name = getattr(creator_member,"display_name","Unknown member")
        claimed_member = guild.get_member(int(t.get("claimed_by", 0) or 0)) if t.get("claimed_by") else None
        assigned_member = guild.get_member(int(t.get("assigned_to", 0) or 0)) if t.get("assigned_to") else None
        searchable = " ".join([channel_name, str(t.get("category_label", "")), creator_name, str(t.get("priority", "")), str(getattr(claimed_member, "display_name", "")), str(getattr(assigned_member, "display_name", ""))]).casefold()
        if ticket_query and ticket_query not in searchable:
            continue
        channel_id = str(t.get("channel_id"))
        if str(t.get("routing","")).lower() in {"shop","grow_a_garden","gag","boosting"}:
            claim_form = "<span class='muted'>Claim in Discord to apply the inventory transaction</span>"
        else:
            claim_form = "<form method='post' action='/dashboard/action'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='ticket_dashboard_claim'><input type='hidden' name='channel_id' value='" + channel_id + "'><button class='btn secondary small'>Claim as me</button></form>"
        if str(t.get("routing","")).lower() in {"shop","grow_a_garden","gag","boosting"} and t.get("service_consumed"):
            unclaim_form = "<span class='muted'>Item consumed; cannot unclaim</span>"
        else:
            unclaim_form = "<form method='post' action='/dashboard/action'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='ticket_dashboard_unclaim'><input type='hidden' name='channel_id' value='" + channel_id + "'><button class='btn secondary small'>Unclaim</button></form>"
        close_form = "<form method='post' action='/dashboard/action' data-confirm='Close this ticket?'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='ticket_dashboard_close'><input type='hidden' name='channel_id' value='" + channel_id + "'><button class='btn danger small'>Close</button></form>"
        assign_form = "<form method='post' action='/dashboard/action' class='actions'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='ticket_dashboard_assign'><input type='hidden' name='channel_id' value='" + channel_id + "'><select name='member_id' aria-label='Assign ticket to member'><option value=''>Assign to member…</option>" + member_options + "</select><button class='btn secondary small'>Assign</button></form>"
        priority_form = "<form method='post' action='/dashboard/action' class='actions'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='ticket_dashboard_priority'><input type='hidden' name='channel_id' value='" + channel_id + "'><select name='priority' aria-label='Ticket priority'>" + "".join("<option value='" + p + "'" + (" selected" if str(t.get("priority", "normal")) == p else "") + ">" + p.title() + "</option>" for p in ("low", "normal", "high", "urgent")) + "</select><button class='btn secondary small'>Set priority</button></form>"
        assigned = _esc(getattr(assigned_member, "display_name", "Unassigned"))
        claimed = _esc(getattr(claimed_member, "display_name", "Unclaimed"))
        actions = "<div class='actions'>" + claim_form + unclaim_form + close_form + "</div>" + assign_form + priority_form
        active_parts.append("<tr><td>" + _esc(channel_name) + "</td><td>" + _esc(t.get("category_label", "Support")) + "</td><td>" + _esc(creator_name) + "</td><td><span class='pill'>" + _esc(str(t.get("priority", "normal")).title()) + "</span></td><td>" + claimed + "</td><td>" + assigned + "</td><td>" + actions + "</td></tr>")
    active_rows="".join(active_parts) or "<tr><td colspan='7'>No active tickets.</td></tr>"
    closed_parts=[]
    for channel_id,t in list((cfg.get("closed",{}) or {}).items())[-50:]:
        ch=guild.get_channel(int(channel_id)) if str(channel_id).isdigit() else None
        cname="#"+ch.name if ch else "Ticket "+str(channel_id)
        reopen="<form method='post' action='/dashboard/action'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='ticket_dashboard_reopen'><input type='hidden' name='channel_id' value='"+_esc(channel_id)+"'><button class='btn secondary small'>Reopen</button></form>"
        closed_creator=guild.get_member(int(t.get("creator_id",0) or 0))
        closed_creator_name=getattr(closed_creator,"display_name","Unknown member")
        closed_parts.append("<tr><td>"+_esc(cname)+"</td><td>"+_esc(t.get("category_label","Support"))+"</td><td>"+_esc(closed_creator_name)+"</td><td>"+_esc(t.get("close_reason",""))+"</td><td>"+reopen+"</td></tr>")
    closed_rows="".join(closed_parts) or "<tr><td colspan='5'>No closed tickets.</td></tr>"
    closed_card="<article class='card full'><h2>Recently closed tickets (up to 50)</h2><div class='tablewrap'><table><thead><tr><th>Channel</th><th>Category</th><th>Creator</th><th>Close reason</th><th>Action</th></tr></thead><tbody>"+closed_rows+"</tbody></table></div></article>"
    search_form = "<form method='get' action='/dashboard' class='formgrid'><input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='tab' value='tickets'><div class='field'><label>Search active tickets</label><input name='ticket_q' maxlength='100' value='" + _esc(ticket_query) + "' placeholder='Channel, category, creator name, priority or staff name'></div><div class='field'><label>&nbsp;</label><div class='actions'><button class='btn' type='submit'>Search</button><a class='btn secondary' href='/dashboard?guild_id=" + str(gid) + "&tab=tickets'>Clear</a></div></div></form>"
    active="<article class='card full'><h2>Active tickets ("+str(open_count)+")</h2>"+search_form+"<div class='tablewrap'><table><thead><tr><th>Channel</th><th>Category</th><th>Creator</th><th>Priority</th><th>Claimed by</th><th>Assigned to</th><th>Actions</th></tr></thead><tbody>"+active_rows+"</tbody></table></div><p class='muted'>Active tickets are ordered by priority. Assigning and changing priority is saved to the same ticket record used by Discord commands. Ticket conversations and staff replies stay inside Discord.</p></article>"
    body="<h1>Tickets</h1><p class='muted'>Discord-native private tickets, modal intake, automatic staff routing, transcripts, and durable records.</p><div class='grid'><article class='card third'><div class='statlabel'>Panels</div><div class='stat'>"+str(len(panels))+"</div></article><article class='card third'><div class='statlabel'>Open tickets</div><div class='stat'>"+str(open_count)+"</div></article><article class='card third'><div class='statlabel'>Closed records</div><div class='stat'>"+str(closed_count)+"</div></article>"+settings_card+create_card+panel_card+active+closed_card+"</div>"
    return body


def _roles_setup(guild,state):
    gid=guild.id; root=(state.get("advanced_features_data",{}) or {}).get("cinnamon_role_permissions_v1",{}) or {}; config=root.get(str(gid),{}) or {}
    categories=[("giveaway_creator","Giveaway Creator","Create, edit, end and reroll giveaways."),("hangry_runner","Hangry Games Runner","Start and manage Hangry Games."),("trusted_booster","Trusted Booster","Handle Grow a Garden boosting tickets."),("ticket_staff","Ticket Staff","Claim, assign and resolve support tickets."),("ticket_admin","Ticket Administrator","Manage all ticket settings and tickets."),("shop_manager","Shop Manager","Manage shop support and orders."),("economy_admin","Economy Administrator","Manage economy tools."),("quest_manager","Quest Manager","Manage quests and challenges."),("event_manager","Event Manager","Manage server events."),("moderator","Moderator","Moderation commands.")]
    cards=[]
    for key,label,desc in categories:
        cards.append("<article class='card half'><h3>"+_esc(label)+"</h3><p class='muted'>"+_esc(desc)+"</p>"+_role_multi_select(guild,"role_"+key,config.get(key,[]))+"</article>")
    content="<p class='muted'>Select one or more roles per permission category. A member with any selected role receives that category's permission. Discord Administrators retain the universal override.</p>"+"".join(cards)
    return "<h1>Roles Setup</h1><p class='muted'>Central server-side permission mapping for Cinnamon features. Saved role IDs persist in the Upstash snapshot and are logged.</p>"+_form(gid,"roles_setup_save",content,"Save all role permissions")


def _category_select(guild,name,selected=None):
    cats=[c for c in guild.categories]
    opts=["<option value=''>— Not set —</option>"]
    for c in cats:
        sel=" selected" if selected is not None and str(selected)==str(c.id) else ""
        opts.append(f"<option value='{c.id}'{sel}>📁 {_esc(c.name)}</option>")
    return "<select name='"+_esc(name)+"'>"+"".join(opts)+"</select>"


def _giveaways(guild,state):
    gid=guild.id; active=state.get("active_giveaways",{}) or {}; history=state.get("giveaway_history",{}) or {}
    cards=[]
    for mid,gw in active.items():
        if int(gw.get("guild_id",0))!=gid: continue
        remain=max(0,int((float(gw.get('ends_at',0))-time.time())//60))
        entry_message = _esc(gw.get("entry_message", "🎉 You're entered! Tap again to leave."))
        denied_message = _esc(gw.get("denied_message", "You do not meet this giveaway's entry requirements."))
        content=(f"<p class='muted'>Entries: {len(set(gw.get('entrants',[])))} · Ends in approx. {remain} min</p>"
        f"<div class='formgrid'><div class='field'><label>Prize</label><input name='prize' maxlength='200' value='{_esc(gw.get('prize',''))}' required></div>"
        f"<div class='field'><label>Winners</label><input name='winners' type='number' min='1' max='100' value='{int(gw.get('winners',1))}' required></div>"
        f"<div class='field'><label>Reset duration (minutes from save)</label><input name='duration_minutes' type='number' min='1' max='525600' value='{max(1,remain)}' required></div>"
        f"<div class='field'><label>Entry button / reaction emoji</label><input name='entry_emoji' maxlength='40' value='{_esc(gw.get('entry_emoji','🎉'))}'></div>"
        f"<div class='field'><label><input type='checkbox' name='reaction_entries' value='1'{(' checked' if gw.get('reaction_entries') else '')}> Also allow reaction entry</label><small>Bot must have Add Reactions and Manage Messages to remove ineligible entries.</small></div>"
        f"<div class='field full'><label>Bonus entries by role</label>{_role_bonus_picker(guild,selected=gw.get('bonus_roles',{}))}<small>Choose roles by name and set extra entries. Only the highest matching role bonus applies.</small></div>"
        f"<div class='field'><label>Minimum Discord account age (days, 0 = none)</label><input name='min_account_age_days' type='number' min='0' max='3650' value='{int(gw.get('min_account_age_days',0) or 0)}'></div>"
        f"<div class='field'><label>Minimum server membership (days, 0 = none)</label><input name='min_server_age_days' type='number' min='0' max='3650' value='{int(gw.get('min_server_age_days',0) or 0)}'></div>"
        f"<div class='field full'><label>Required roles (member needs at least one)</label>{_role_multi_select(guild,'required_roles',gw.get('required_roles',[]))}</div>"
        f"<div class='field full'><label>Requirement-bypass roles (skip required roles and age checks)</label>{_role_multi_select(guild,'bypass_roles',gw.get('bypass_roles',[]))}</div>"
        f"<div class='field full'><label>Blacklisted roles (always blocked, even if bypass role is present)</label>{_role_multi_select(guild,'blacklisted_roles',gw.get('blacklisted_roles',[]))}</div>"
        f"<div class='field'><label>Winner role (optional)</label>{_role_select(guild,'winner_role_id',gw.get('winner_role_id'),True)}</div>"
        f"<div class='field'><label>Remove winner role after (minutes, 0 = keep)</label><input name='winner_role_minutes' type='number' min='0' max='525600' value='{int(gw.get('winner_role_minutes',0) or 0)}'></div>"
        f"<div class='field'><label>Winner thread auto-close (minutes, 0 = off)</label><input name='winner_thread_minutes' type='number' min='0' max='10080' value='{int(gw.get('winner_thread_minutes',0) or 0)}'></div>"
        f"<div class='field'><label>Claim deadline (minutes, 0 = off)</label><input name='claim_minutes' type='number' min='0' max='10080' value='{int(gw.get('claim_minutes',0) or 0)}'></div>"
        f"<div class='field'><label>Embed colour (hex)</label><input name='embed_color' maxlength='7' value='{_esc(str(gw.get('embed_color','FEE75C')).lstrip('#'))}'></div>"
        f"<div class='field'><label>Embed title (optional)</label><input name='embed_title' maxlength='256' value='{_esc(gw.get('embed_title',''))}'></div>"
        f"<div class='field full'><label>Embed description (optional)</label><textarea name='embed_description' maxlength='3500'>{_esc(gw.get('embed_description',''))}</textarea></div>"
        f"<div class='field'><label>Entry confirmation</label><input name='entry_message' maxlength='300' value='{entry_message}'></div>"
        f"<div class='field'><label>Leave confirmation</label><input name='leave_message' maxlength='300' value='{_esc(gw.get('leave_message','You left the giveaway.'))}'></div>"
        f"<div class='field full'><label>Eligibility-denied message</label><input name='denied_message' maxlength='300' value='{denied_message}'></div></div>")
        edit=_form(gid,"giveaway_edit",f"<input type='hidden' name='message_id' value='{int(mid)}'>{content}","Save giveaway")
        template_form=_form(gid,"giveaway_template_save",f"<input type='hidden' name='message_id' value='{int(mid)}'><div class='field'><label>Template name</label><input name='template_name' maxlength='40' required placeholder='e.g. Monthly Tuna'></div>","Save as template")
        bonus_template_form=_form(gid,"giveaway_bonus_template_save",f"<input type='hidden' name='message_id' value='{int(mid)}'><div class='field'><label>Extra-entry template name</label><input name='template_name' maxlength='40' required placeholder='e.g. VIP + Booster'></div>","Save role template")
        end=(f"<form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='giveaway_end'><input type='hidden' name='message_id' value='{int(mid)}'><button class='btn secondary small'>End & pick winners</button></form>"
             f"<form method='post' action='/dashboard/action' data-confirm='Cancel this giveaway without winners?'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='giveaway_cancel'><input type='hidden' name='message_id' value='{int(mid)}'><button class='btn danger small'>Cancel giveaway</button></form>")
        cards.append(f"<article class='card full'><h3>🎉 {_esc(gw.get('prize','Giveaway'))}</h3>{edit}<div class='grid'><article class='card half'><h3>Reusable giveaway template</h3>{template_form}</article><article class='card half'><h3>Reusable extra-entry template</h3>{bonus_template_form}</article><article class='card half'><h3>Finish or cancel</h3><div class='actions'>{end}</div></article></div></article>")
    bonus_role_templates=(state.get("giveaway_bonus_role_templates",{}) or {}).get(gid,(state.get("giveaway_bonus_role_templates",{}) or {}).get(str(gid),{})) or {}
    bonus_template_options="<option value=''>Use manually selected roles</option>"+"".join("<option value='"+_esc(name)+"'>"+_esc(name)+"</option>" for name in sorted(bonus_role_templates))
    bonus_template_select="<div class='field full'><label>Reusable extra-entry template</label><select name='bonus_role_template'>"+bonus_template_options+"</select><small>Choose a saved role/count template, or configure roles below.</small></div>"
    channels=_channel_select(guild,"channel_id",allow_none=False)
    create=("<div class='formgrid'><div class='field'><label>Post in</label>"+channels+"</div><div class='field'><label>Prize</label><input name='prize' maxlength='200' required></div>"
    "<div class='field'><label>Winners</label><input name='winners' type='number' min='1' max='100' value='1' required></div><div class='field'><label>Duration (minutes; max 1 year)</label><input name='duration_minutes' type='number' min='1' max='525600' value='60' required></div>"
    "<div class='field'><label>Entry button / reaction emoji</label><input name='entry_emoji' maxlength='40' value='🎉'></div><div class='field'><label>Embed colour (hex)</label><input name='embed_color' maxlength='7' value='FEE75C'></div>"
    "<div class='field'><label><input type='checkbox' name='reaction_entries' value='1'> Also allow reaction entry</label><small>Bot needs Add Reactions and Manage Messages to remove ineligible entries.</small></div>"
    "<div class='field'><label>Minimum account age (days)</label><input name='min_account_age_days' type='number' min='0' max='3650' value='0'></div><div class='field'><label>Minimum server membership (days)</label><input name='min_server_age_days' type='number' min='0' max='3650' value='0'></div>"
    +bonus_template_select+
    "<div class='field full'><label>Bonus entries by role</label>"+_role_bonus_picker(guild)+"<small>Choose roles by name and set extra entries. No ID copying needed.</small></div>"
    "<div class='field full'><label>Required roles (member needs at least one)</label>"+_role_multi_select(guild,"required_roles")+"</div>"
    "<div class='field full'><label>Requirement-bypass roles</label>"+_role_multi_select(guild,"bypass_roles")+"</div>"
    "<div class='field full'><label>Blacklisted roles (always blocked)</label>"+_role_multi_select(guild,"blacklisted_roles")+"</div>"
    "<div class='field'><label>Winner role (optional)</label>"+_role_select(guild,"winner_role_id",None,True)+"</div><div class='field'><label>Remove winner role after (minutes; 0 = keep)</label><input name='winner_role_minutes' type='number' min='0' max='525600' value='0'></div>"
    "<div class='field'><label>Winner thread auto-close (minutes; 0 = off)</label><input name='winner_thread_minutes' type='number' min='0' max='10080' value='0'></div><div class='field'><label>Embed title (optional)</label><input name='embed_title' maxlength='256'></div>"
    "<div class='field full'><label>Embed description (optional)</label><textarea name='embed_description' maxlength='3500' placeholder='Additional details for your giveaway'></textarea></div>"
    "<div class='field'><label>Entry confirmation</label><input name='entry_message' maxlength='300' value='🎉 You are entered! Tap again to leave.'></div><div class='field'><label>Leave confirmation</label><input name='leave_message' maxlength='300' value='You left the giveaway.'></div>"
    "<div class='field full'><label>Eligibility-denied message</label><input name='denied_message' maxlength='300' value='You do not meet this giveaway\'s entry requirements.'></div></div>")
    def _giveaway_form_fields(prize,winners,duration,config):
        c=config or {}
        bonus="\\n".join(f"{rid}:{count}" for rid,count in (c.get("bonus_roles",{}) or {}).items())
        roles=lambda key:"\\n".join(str(x) for x in (c.get(key,[]) or []))
        return ("<div class='formgrid'><div class='field'><label>Prize</label><input name='prize' maxlength='200' required value='"+_esc(prize)+"'></div>"
        "<div class='field'><label>Winners</label><input name='winners' type='number' min='1' max='100' value='"+str(int(winners))+"'></div>"
        "<div class='field'><label>Duration (minutes)</label><input name='duration_minutes' type='number' min='1' max='525600' value='"+str(int(duration))+"'></div>"
        "<div class='field full'><label>Role bonuses</label>"+_role_bonus_picker(guild,selected=c.get('bonus_roles',{}))+"</div>"
        "<div class='field full'><label>Required roles (member needs at least one)</label>"+_role_multi_select(guild,"required_roles",c.get("required_roles",[]))+"</div>"
        "<div class='field full'><label>Requirement-bypass roles</label>"+_role_multi_select(guild,"bypass_roles",c.get("bypass_roles",[]))+"</div>"
        "<div class='field full'><label>Blacklisted roles</label>"+_role_multi_select(guild,"blacklisted_roles",c.get("blacklisted_roles",[]))+"</div>"
        "<div class='field'><label>Minimum account age (days)</label><input name='min_account_age_days' type='number' min='0' max='3650' value='"+str(int(c.get('min_account_age_days',0) or 0))+"'></div>"
        "<div class='field'><label>Minimum server age (days)</label><input name='min_server_age_days' type='number' min='0' max='3650' value='"+str(int(c.get('min_server_age_days',0) or 0))+"'></div>"
        "<div class='field'><label>Winner role</label>"+_role_select(guild,"winner_role_id",c.get("winner_role_id"),True)+"</div>"
        "<div class='field'><label>Winner role duration (minutes)</label><input name='winner_role_minutes' type='number' min='0' max='525600' value='"+str(int(c.get('winner_role_minutes',0) or 0))+"'></div>"
        "<div class='field'><label>Winner thread duration (minutes)</label><input name='winner_thread_minutes' type='number' min='0' max='10080' value='"+str(int(c.get('winner_thread_minutes',0) or 0))+"'></div>"
        "<div class='field'><label>Claim deadline (minutes; 0 = off)</label><input name='claim_minutes' type='number' min='0' max='10080' value='"+str(int(c.get('claim_minutes',0) or 0))+"'></div>"
        "<div class='field'><label>Embed color (hex)</label><input name='embed_color' value='"+_esc(c.get('embed_color','FEE75C'))+"'></div>"
        "<div class='field'><label>Entry emoji</label><input name='entry_emoji' value='"+_esc(c.get('entry_emoji','🎉'))+"'></div>"
        "<div class='field'><label>Entry message</label><input name='entry_message' maxlength='300' value='"+_esc(c.get('entry_message','🎉 You are entered! Tap again to leave.'))+"'></div>"
        "<div class='field'><label>Leave message</label><input name='leave_message' maxlength='300' value='"+_esc(c.get('leave_message','You left the giveaway.'))+"'></div>"
        "<div class='field full'><label>Denied message</label><input name='denied_message' maxlength='300' value='"+_esc(c.get('denied_message','You do not meet this giveaway requirements.'))+"'></div>"
        "<div class='field'><label>Embed title</label><input name='embed_title' maxlength='256' value='"+_esc(c.get('embed_title',''))+"'></div>"
        "<div class='field full'><label>Embed description</label><textarea name='embed_description' maxlength='3500'>"+_esc(c.get('embed_description',''))+"</textarea></div>"
        "<div class='field'><label><input type='checkbox' name='reaction_entries' "+("checked" if c.get('reaction_entries') else "")+"> Enable reaction entries</label></div></div>")
    create_card="<article class='card full'><h2>Build giveaway (save draft first)</h2>"+_form(gid,"giveaway_draft_save",create,"Save draft")+"<p class='muted'>Features include eligibility rules, bypass/blacklisted roles, bonus entries, custom embeds and messages, timed winner roles, winner threads, reusable templates, recurring schedules, and rerolls.</p></article>"
    schedules=state.get("giveaway_schedules",{}) or {}; schedule_rows=[]
    for sid,cfg in schedules.items():
        if int(cfg.get("guild_id",0))!=gid: continue
        ch=guild.get_channel(int(cfg.get("channel_id",0))); next_at=int(cfg.get("next_at",0))
        schedule_rows.append(f"<div class='toggle'><span><b>{_esc(cfg.get('prize','Giveaway'))}</b><small>{_esc('#'+ch.name if ch else 'Missing channel')} · every {int(cfg.get('repeat_every_days',7))} day(s) · next <t:{next_at}:R></small></span><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='giveaway_repeat_stop'><input type='hidden' name='schedule_id' value='{_esc(sid)}'><button class='btn danger small'>Stop</button></form></div>")
    repeat_form=("<div class='formgrid'><div class='field'><label>Post in</label>"+_channel_select(guild,"channel_id",allow_none=False)+"</div><div class='field'><label>Prize</label><input name='prize' maxlength='200' required></div><div class='field'><label>Winners</label><input name='winners' type='number' min='1' max='100' value='1' required></div><div class='field'><label>Giveaway duration (minutes)</label><input name='duration_minutes' type='number' min='1' max='525600' value='1440' required></div><div class='field'><label>Repeat every (days)</label><input name='repeat_every_days' type='number' min='1' max='365' value='7' required></div></div>")
    repeat_card="<article class='card half'><h2>Recurring giveaways</h2><p class='muted'>Schedules are saved with bot data and continue after restarts.</p>"+(''.join(schedule_rows) or "<p class='muted'>No recurring giveaways configured.</p>")+_form(gid,"giveaway_repeat_create",repeat_form,"Save recurring schedule")+"</article>"
    templates=state.get("giveaway_templates",{}) or {}; templates=templates.get(gid,templates.get(str(gid),{})) or {}; template_rows=[]
    for name,cfg in sorted(templates.items()):
        template_rows.append(f"<div class='toggle'><span><b>{_esc(name)}</b><small>{_esc(cfg.get('prize','Giveaway'))} · {int(cfg.get('winners',1))} winner(s)</small></span><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='giveaway_template_delete'><input type='hidden' name='template_name' value='{_esc(name)}'><button class='btn danger small'>Delete</button></form></div>")
    template_card="<article class='card half'><h2>Saved templates</h2>"+(''.join(template_rows) or "<p class='muted'>Save any active giveaway as a reusable template.</p>")+"</article>"
    finished=[(mid,gw) for mid,gw in history.items() if int(gw.get('guild_id',0))==gid]
    finished.sort(key=lambda x:float(x[1].get('finished_at',0)),reverse=True)
    hist_rows=''.join(f"<tr><td>{_esc(gw.get('prize','Giveaway'))}</td><td>{len(set(gw.get('eligible_entrants',gw.get('entrants',[]))))}</td><td>{', '.join((guild.get_member(int(x)).display_name if str(x).isdigit() and guild.get_member(int(x)) else 'Unknown member') for x in gw.get('winner_ids',[])) or 'No winner'}</td><td><form method='post' action='/dashboard/action'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='giveaway_reroll'><input type='hidden' name='message_id' value='{_esc(mid)}'><button class='btn secondary small'>Reroll</button></form></td></tr>" for mid,gw in finished[:20]) or "<tr><td colspan='4'>No finished giveaways in history yet.</td></tr>"
    history_card="<article class='card full'><h2>Recent finished giveaways</h2><div class='tablewrap'><table><thead><tr><th>Prize</th><th>Eligible entries</th><th>Winners</th><th>Action</th></tr></thead><tbody>"+hist_rows+"</tbody></table></div><p class='muted'>Reroll selects a different eligible entrant from the saved history. History keeps the latest 250 finished giveaways.</p></article>"
    drafts=(state.get("giveaway_drafts",{}) or {}).get(gid,(state.get("giveaway_drafts",{}) or {}).get(str(gid),{})) or {}
    draft_rows=[]
    for did,d in drafts.items():
        draft_form="<input type='hidden' name='draft_id' value='"+_esc(did)+"'><input type='hidden' name='channel_id' value='"+str(int(d.get('channel_id',0)))+"'>"+_giveaway_form_fields(d.get('prize','Giveaway'),d.get('winners',1),d.get('duration_minutes',60),d.get('config',{}))
        draft_rows.append("<article class='card full'><h3>Draft editor & preview: "+_esc(d.get('prize','Giveaway'))+"</h3><p class='muted'>Edit settings, then save changes to this draft. Publishing is a separate action.</p>"+_form(gid,"giveaway_draft_update",draft_form,"Save draft changes")+"<div class='actions'><form method='post' action='/dashboard/action'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='giveaway_draft_publish'><input type='hidden' name='draft_id' value='"+_esc(did)+"'><button class='btn'>Publish giveaway</button></form><form method='post' action='/dashboard/action'>"+_csrf_input()+"<input type='hidden' name='guild_id' value='"+str(gid)+"'><input type='hidden' name='action' value='giveaway_draft_delete'><input type='hidden' name='draft_id' value='"+_esc(did)+"'><button class='btn danger small'>Discard</button></form></div></article>")
    draft_card="<article class='card full'><h2>Drafts · preview before publishing</h2><div class='grid'>"+(''.join(draft_rows) or "<p class='muted'>No saved drafts.</p>")+"</div></article>"
    body="<h1>Giveaways</h1><p class='muted'>Configure, save a draft, preview it, then publish. Active giveaway changes take effect only after Save giveaway.</p><div class='grid'>"+(''.join(cards) or "<article class='card full'><div class='empty'>No active giveaways in this server.</div></article>")+create_card+draft_card+repeat_card+template_card+history_card+"</div>"
    return body


def _hangry(guild,state):
    gid=guild.id; cog=state.get("hg_cog")
    if not cog: return "<h1>Hangry Games</h1><p class='muted'>Hangry Games statistics are not loaded yet. Reload after Cinnamon is ready.</p>"
    wins=sorted(((uid,n) for (g,uid),n in cog.win_counts.items() if g==gid),key=lambda x:x[1],reverse=True)[:10]
    rows=''.join(f"<tr><td>{i}</td><td>{_esc(guild.get_member(uid).display_name if guild.get_member(uid) else 'Member '+str(uid))}</td><td>{n}</td><td>{cog.played_counts.get((gid,uid),0)}</td><td>{cog.kill_counts.get((gid,uid),0)}</td></tr>" for i,(uid,n) in enumerate(wins,1)) or "<tr><td colspan='5'>No completed games recorded.</td></tr>"
    ch=cog.hg_log_channels.get(gid); enabled=cog.log_enabled.get(gid,True)
    channel_form="<div class='field'><label>Hangry Games log channel</label>"+_channel_select(guild,"channel_id",ch)+"</div><label class='toggle'><input type='checkbox' name='enabled' "+("checked" if enabled else "")+"><span><b>Enable activity logs</b><small>Applies when a log channel is selected.</small></span></label>"
    body=f"<h1>Hangry Games</h1><p class='muted'>Game statistics and log routing from the live Hangry Games module.</p><div class='grid'><article class='card third'><div class='statlabel'>Games run</div><div class='stat'>{int(cog.game_counts.get(gid,0)):,}</div></article><article class='card third'><div class='statlabel'>Members with wins</div><div class='stat'>{sum(1 for g,u in cog.win_counts if g==gid):,}</div></article><article class='card third'><div class='statlabel'>Logging</div><div class='stat'>{'On' if enabled and ch else 'Off'}</div></article><article class='card half'><h2>Win leaderboard</h2><div class='tablewrap'><table><thead><tr><th>#</th><th>Member</th><th>Wins</th><th>Played</th><th>KOs</th></tr></thead><tbody>{rows}</tbody></table></div></article><article class='card half'><h2>Game log settings</h2>{_form(gid,'hangry_logs',channel_form,'Save settings')}</article></div>"
    return body



def _companions(guild, state):
    gid = str(guild.id)
    advanced = state.get("advanced_features_data", {}) or {}
    profiles = (advanced.get("companion_profiles_v1", {}) or {}).get(gid, {}) or {}
    records = []
    total_friendship = total_feeds = total_plays = total_grooms = 0
    for user_id, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        stats = profile.get("stats", {}) or {}
        friendship = int(profile.get("friendship", 0))
        feeds, plays, grooms = int(stats.get("feeds", 0)), int(stats.get("plays", 0)), int(stats.get("grooms", 0))
        total_friendship += friendship
        total_feeds += feeds
        total_plays += plays
        total_grooms += grooms
        member = guild.get_member(int(user_id)) if str(user_id).isdigit() else None
        records.append((str(profile.get("name", "Mochi")), member.display_name if member else "Member " + str(user_id),
                        int(profile.get("level", 1)), str(profile.get("mood", "Content")), friendship,
                        feeds, plays, grooms, len(profile.get("equipped", {}) or {}), len(profile.get("room", []) or [])))
    records.sort(key=lambda x: (x[2], x[4]), reverse=True)
    rows = "".join(
        "<tr><td>" + _esc(member) + "</td><td>" + _esc(name) + "</td><td>" + str(level) +
        "</td><td>" + _esc(mood) + "</td><td>" + f"{friendship:,}" +
        "</td><td>" + str(feeds) + " / " + str(plays) + " / " + str(grooms) +
        "</td><td>" + str(accessories) + "</td><td>" + str(decor) + "</td></tr>"
        for name, member, level, mood, friendship, feeds, plays, grooms, accessories, decor in records[:100]
    ) or "<tr><td colspan='8'>No personal companion profiles yet.</td></tr>"
    return (
        "<h1>Companions</h1><p class='muted'>Member-owned cats, friendship progression, care activity, accessories and room decorations. Personal memory text is private and is not displayed here.</p>"
        "<div class='grid'>"
        "<article class='card third'><div class='statlabel'>Companion profiles</div><div class='stat'>" + f"{len(records):,}" + "</div></article>"
        "<article class='card third'><div class='statlabel'>Friendship points</div><div class='stat'>" + f"{total_friendship:,}" + "</div></article>"
        "<article class='card third'><div class='statlabel'>Care actions</div><div class='stat'>" + f"{total_feeds + total_plays + total_grooms:,}" + "</div></article>"
        "<article class='card full'><h2>Member companion roster</h2><div class='tablewrap'><table><thead><tr><th>Member</th><th>Cat</th><th>Level</th><th>Mood</th><th>Friendship</th><th>Feed / Play / Groom</th><th>Accessories</th><th>Room decor</th></tr></thead><tbody>"
        + rows + "</tbody></table></div><p class='muted'>Members manage their own cat with /pet, /feed, /play, /groom, /dressup and /room. Shared accessories and furniture are managed through the Catnip economy.</p></article>"
        "<article class='card half'><h2>Companion care totals</h2><p>Feeds: <b>" + f"{total_feeds:,}" + "</b></p><p>Play sessions: <b>" + f"{total_plays:,}" + "</b></p><p>Grooming sessions: <b>" + f"{total_grooms:,}" + "</b></p></article>"
        "<article class='card half'><h2>Companion item catalogue</h2><p class='muted'>Accessories and room furniture use the same member inventory as the rest of the economy. Items remain in inventory when equipped; furniture moves between inventory and the room.</p><div class='actions'><a class='btn secondary' href='/dashboard?guild_id=" + str(guild.id) + "&tab=economy'>Open Catnip Economy</a></div></article>"
        "</div>"
    )


def _community(guild,state):
    gid = guild.id
    welcome = state.get("welcome_config", {}).get(gid, {}) or state.get("welcome_config", {}).get(str(gid), {})
    goodbye = state.get("goodbye_config", {}).get(gid, {}) or state.get("goodbye_config", {}).get(str(gid), {})
    ai = state.get("ai_channels", {}).get(gid) or state.get("ai_channels", {}).get(str(gid))
    logs = state.get("log_channels", {}).get(gid) or state.get("log_channels", {}).get(str(gid))
    advanced = state.get("advanced_features_data", {}) or {}
    board = (advanced.get("cinnamon_community_tools_v1", {}) or {}).get(str(gid), {}) or {}
    social = (advanced.get("cinnamon_community_interactions_v1", {}) or {}).get(str(gid), {}) or {}
    active_polls = [(str(mid), p) for mid, p in (state.get("active_polls", {}) or {}).items() if isinstance(p, dict) and int(p.get("guild_id", 0) or 0) == gid]
    events = social.get("events", {}) or {}
    confessions = social.get("confessions", {}) or {}
    activity_root = (advanced.get("cinnamon_community_activity_v1", {}) or {}).get(str(gid), {}) or {}
    activity_days = activity_root.get("days", {}) or {}
    recent_activity_keys = [time.strftime("%Y-%m-%d", time.gmtime(time.time() - day * 86400)) for day in range(7)]
    recent_activity = [activity_days.get(day_key, {}) for day_key in recent_activity_keys]
    activity_messages = sum(int(day.get("messages", 0)) for day in recent_activity)
    activity_members = set()
    for day in recent_activity:
        activity_members.update((day.get("members", {}) or {}).keys())

    def message_form(kind, cfg, action):
        ch = _channel_select(guild, "channel_id", cfg.get("channel_id"))
        msg = _esc(cfg.get("message", ""))
        fields = f"<div class='field'><label>Post in</label>{ch}</div><div class='field'><label>Message template</label><textarea name='message' maxlength='800' placeholder='Use {{member}} and {{server}}'>{msg}</textarea><small>Supported placeholders: {{member}} and {{server}}.</small></div>"
        current = guild.get_channel(cfg.get("channel_id")) if cfg.get("channel_id") else None
        disable = ("<form method='post' action='/dashboard/action'>" + _csrf_input() +
            f"<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='{action}_disable'><button class='btn secondary small' type='submit'>Disable</button></form>") if cfg else ""
        return f"<article class='card half'><h2>{kind}</h2><p class='muted'>Current: {_esc(current.mention if current else 'Disabled')}</p>" + _form(gid, action, fields) + disable + "</article>"

    ai_channel = guild.get_channel(ai) if ai else None
    log_channel = guild.get_channel(logs) if logs else None
    ai_form = "<div class='field'><label>Cinnamon conversation channel (responds when called)</label>" + _channel_select(guild, "channel_id", ai) + "</div>"
    log_form = "<div class='field'><label>Main moderation and error log channel</label>" + _channel_select(guild, "channel_id", logs) + "</div>"
    ai_card = "<article class='card half'><h2>AI channel</h2><p class='muted'>Current: " + _esc(ai_channel.mention if ai_channel else "Not set") + "</p>" + _form(gid, "ai_channel", ai_form) + "</article>"
    log_card = "<article class='card half'><h2>Main logging</h2><p class='muted'>Current: " + _esc(log_channel.mention if log_channel else "Not set") + "</p>" + _form(gid, "log_channel", log_form) + "</article>"

    suggestion_channel = guild.get_channel(int(board.get("suggestion_channel_id", 0) or 0))
    starboard_channel = guild.get_channel(int(board.get("starboard_channel_id", 0) or 0))
    confession_channel = guild.get_channel(int(social.get("confession_channel_id", 0) or 0))
    event_rows = []
    for event_id, event in sorted(events.items(), key=lambda pair: int(pair[1].get("starts_at", 0))):
        if event.get("status") != "scheduled":
            continue
        event_rows.append("<tr><td>" + _esc(event.get("title", "Event")) + "</td><td>" + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(event.get("starts_at", 0)))) + "</td><td>" + _esc(str(event_id)) + "</td><td><form method='post' action='/dashboard/action'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='community_event_cancel'><input type='hidden' name='event_id' value='" + _esc(str(event_id)) + "'><button class='btn danger small'>Cancel</button></form></td></tr>")
    event_rows_html = "".join(event_rows) or "<tr><td colspan='4'>No scheduled events.</td></tr>"
    event_form = "<div class='formgrid'><div class='field'><label>Event title</label><input name='title' maxlength='120' required></div><div class='field'><label>Start time (ISO 8601 with timezone)</label><input name='start_at' placeholder='2026-12-01T18:30:00+05:30' required></div><div class='field full'><label>Description</label><textarea name='description' maxlength='1500'></textarea></div><div class='field'><label>Event channel</label>" + _channel_select(guild, "channel_id", None) + "</div></div><p class='muted'>Use an explicit timezone offset, for example +05:30 or Z. Members RSVP on the event post and receive 24-hour and 1-hour reminders.</p>"
    event_card = "<article class='card full'><h2>Server events</h2><div class='tablewrap'><table><thead><tr><th>Event</th><th>Unix start time</th><th>Event ID</th><th>Action</th></tr></thead><tbody>" + event_rows_html + "</tbody></table></div>" + _form(gid, "community_event_create", event_form, "Create event") + "</article>"
    poll_rows = []
    for message_id, poll in active_polls[:20]:
        poll_rows.append("<tr><td>" + _esc(poll.get("question", "Poll")) + "</td><td>" + _esc(str(len(poll.get("votes", {}) or {}))) + "</td><td><a href='https://discord.com/channels/" + str(gid) + "/" + str(poll.get("channel_id", 0)) + "/" + _esc(str(message_id)) + "' target='_blank' rel='noopener'>Open poll</a></td><td><form method='post' action='/dashboard/action'>" + _csrf_input() + "<input type='hidden' name='guild_id' value='" + str(gid) + "'><input type='hidden' name='action' value='community_poll_close'><input type='hidden' name='message_id' value='" + _esc(str(message_id)) + "'><button class='btn danger small'>Close</button></form></td></tr>")
    poll_rows_html = "".join(poll_rows) or "<tr><td colspan='4'>No active polls.</td></tr>"
    poll_form = "<div class='formgrid'><div class='field full'><label>Poll question</label><input name='question' maxlength='200' required></div><div class='field'><label>Option 1</label><input name='option1' maxlength='60' required></div><div class='field'><label>Option 2</label><input name='option2' maxlength='60' required></div><div class='field'><label>Option 3 (optional)</label><input name='option3' maxlength='60'></div><div class='field'><label>Option 4 (optional)</label><input name='option4' maxlength='60'></div><div class='field'><label>Duration (minutes)</label><input name='duration_minutes' type='number' min='1' max='10080' value='1440' required></div><div class='field'><label>Post in</label>" + _channel_select(guild, "channel_id", None) + "</div></div><p class='muted'>Members can change or remove their vote until the poll closes. Results are shown on the poll post.</p>"
    poll_card = "<article class='card full'><h2>Polls</h2><div class='tablewrap'><table><thead><tr><th>Question</th><th>Votes</th><th>Post</th><th>Action</th></tr></thead><tbody>" + poll_rows_html + "</tbody></table></div>" + _form(gid, "community_poll_create", poll_form, "Create poll") + "</article>"
    features = (
        "<div class='formgrid'>"
        "<div class='field'><label>Suggestion board channel</label>" + _channel_select(guild, "suggestion_channel_id", board.get("suggestion_channel_id")) + "</div>"
        "<div class='field'><label>Starboard channel</label>" + _channel_select(guild, "starboard_channel_id", board.get("starboard_channel_id")) + "</div>"
        "<div class='field'><label>Starboard reaction threshold</label><input name='starboard_threshold' type='number' min='2' max='20' value='" + str(max(2, min(20, int(board.get("starboard_threshold", 3)))) ) + "'></div>"
        "<div class='field'><label>Starboard emoji</label><input name='starboard_emoji' maxlength='20' value='" + _esc(str(board.get("starboard_emoji", "⭐"))) + "'></div>"
        "<div class='field'><label>Anonymous confession channel</label>" + _channel_select(guild, "confession_channel_id", social.get("confession_channel_id")) + "</div>"
        "</div><p class='muted'>Members use /suggest, /poll, /event, /confess and /quote. Confession channels should be moderated; confession submitters are not identified in public posts.</p>"
    )
    feature_card = "<article class='card full'><h2>Community boards and activities</h2><div class='toggle'><span>Suggestions</span><b>" + _esc(suggestion_channel.mention if suggestion_channel else "Disabled") + "</b></div><div class='toggle'><span>Starboard</span><b>" + _esc(starboard_channel.mention if starboard_channel else "Disabled") + "</b></div><div class='toggle'><span>Confessions</span><b>" + _esc(confession_channel.mention if confession_channel else "Disabled") + "</b></div><div class='grid'><article class='card third'><div class='statlabel'>Saved polls</div><div class='stat'>" + str(len(active_polls)) + "</div></article><article class='card third'><div class='statlabel'>Scheduled events</div><div class='stat'>" + str(sum(1 for e in events.values() if e.get("status") == "scheduled")) + "</div></article><article class='card third'><div class='statlabel'>Published confessions</div><div class='stat'>" + str(sum(1 for e in confessions.values() if e.get("status") == "published")) + "</div></article></div>" + _form(gid, "community_features_settings", features, "Save community settings") + "</article>"
    activity_card = "<article class='card full'><h2>Seven-day activity</h2><div class='grid'><article class='card half'><div class='statlabel'>Messages recorded</div><div class='stat'>" + f"{activity_messages:,}" + "</div></article><article class='card half'><div class='statlabel'>Active members</div><div class='stat'>" + f"{len(activity_members):,}" + "</div></article></div><p class='muted'>Use /community recap to share the same rolling seven-day summary. Activity tracking starts with this version; older messages are not backfilled.</p></article>"
    return "<h1>Community</h1><p class='muted'>Welcome and goodbye messages, Cinnamon's AI channel, suggestions, polls, starboard, events, anonymous confessions and server logging.</p><div class='grid'>" + message_form("Welcome messages", welcome, "welcome") + message_form("Goodbye messages", goodbye, "goodbye") + ai_card + log_card + feature_card + activity_card + poll_card + event_card + "</div>"


def _system(guild,state):
    gid=guild.id; hg=state.get("hg_cog"); category_channels=state.get("category_log_channels",{}).get(gid,{})
    categories=[("moderation","Main moderation"),("economy","Economy"),("shop_items","Shop & Items"),("ai","AI"),("levels","Levels & XP"),("achievements","Achievements"),("quests","Quests"),("friendship","Cinnamon Friendship"),("community","Giveaways & polls"),("roles","Role management"),("setup","Server setup"),("general","General utilities"),("dashboard","Dashboard audit trail")]
    configured=[]
    for key,label in categories:
        cid=state.get("log_channels",{}).get(gid) if key=="moderation" else (state.get("economy_log_channels",{}).get(gid) if key=="economy" else category_channels.get(key))
        configured.append((key,label,cid))
    if hg: configured.append(("hangry","Hangry Games",hg.hg_log_channels.get(gid)))
    options=[]
    for key,label,cid in configured:
        options.append(f"<option value='{_esc(key)}'>{_esc(label)} — {_esc((guild.get_channel(cid).name if cid and guild.get_channel(cid) else 'not configured'))}</option>")
    editor=f"<div class='formgrid'><div class='field'><label>Log category</label><select name='log_category'>{''.join(options)}</select></div><div class='field'><label>Channel</label>{_channel_select(guild,'channel_id')}</div></div><p class='muted'>Selecting a channel replaces that category's dedicated log route. Use Disable to remove it.</p>"
    disable="<form method='post' action='/dashboard/action'>"+_csrf_input()+f"<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='category_log_disable'><button class='btn secondary' type='submit'>Disable selected category</button></form>"
    items=''.join(f"<div class='toggle'><b>{_esc(label)}</b><span>{_esc(guild.get_channel(cid).mention if cid and guild.get_channel(cid) else 'Not configured')}</span></div>" for _,label,cid in configured)
    status=bool(_bot and _bot.is_ready()); storage='Upstash Redis' if state.get('BD_UPSTASH_URL') and state.get('BD_UPSTASH_TOKEN') else 'Local JSON file (may not survive redeploys)'
    setup_content="<p class='muted'>This is safe to run again; existing managed channels and roles are reused.</p>"
    setup="<article class='card full'><h2>Guided Cinnamon setup</h2><p class='muted'>Run the same idempotent setup flow as <b>/setup</b>. It creates/reuses Cinnamon's managed log channels and achievement/quest reward roles, but never creates level roles.</p>"+_form(gid,'run_setup',setup_content,'Run /setup from dashboard')+"</article>"
    recall_content="<p class='muted'>Best-effort recovery. Deleted Discord history cannot be recovered.</p>"
    recall="<p class='muted'>Scan configured log channels and merge recoverable warnings, XP, economy state, achievements, quests and Hangry data without intentionally overwriting existing account balances.</p>"+_form(gid,'recall',recall_content,'Run recovery scan')
    backup_form=(f"<form method='post' action='/dashboard/action' enctype='multipart/form-data'>{_csrf_input()}<input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='action' value='config_backup_restore'><div class='field'><label>Choose a Cinnamon configuration backup (.json)</label><input type='file' name='backup_file' accept='.json,application/json' required></div><p class='muted'>Only settings for this server are restored. Balances, inventories, user data, active giveaways, tokens, and secrets are never overwritten by a configuration import.</p><div class='actions'><button class='btn secondary' type='submit'>Validate & restore configuration</button></div></form>")
    backup=(f"<article class='card full'><h2>Configuration backup</h2><p class='muted'>Export this server's dashboard settings to a JSON file before making major changes. Import accepts only validated configuration keys for this same server.</p><div class='actions'><a class='btn' href='/dashboard/backup?guild_id={gid}'>Download configuration backup</a></div><div class='rule'></div>{backup_form}</article>")
    gateway_pill="<span class='pill good'>Connected</span>" if status else "<span class='pill warn'>Not ready</span>"
    return f"<h1>Settings & system</h1><p class='muted'>Cinnamon's server control center: logging, setup, persistence and recovery.</p><div class='grid'><article class='card half'><h2>Log routing</h2>{_form(gid,'category_log_set',editor,'Save log route')}{disable}</article><article class='card half'><h2>System health</h2><div class='toggle'><b>Bot Gateway</b>{gateway_pill}</div><div class='toggle'><b>Storage</b><span>{storage}</span></div><div class='toggle'><b>Guild ID</b><span>{gid}</span></div><p class='muted'>Use <b>/diagnostics</b> in Discord for the complete permission/runtime diagnostic.</p></article><article class='card full'><h2>Configured log channels</h2>{items}</article>{setup}<article class='card full'><h2>Recovery</h2>{recall}</article>{backup}</div>"


async def _dashboard_setup(guild,state):
    """Idempotent dashboard equivalent of /setup. Keeps level roles out."""
    discord=__import__("discord")
    category=discord.utils.get(guild.categories,name="Cinnamon • Logs & Setup")
    if category is None: category=await guild.create_category("Cinnamon • Logs & Setup",reason="Cinnamon dashboard setup")
    specs=[
        ("cinnamon-logs","Cinnamon moderation, AutoMod, errors, warnings, and general logs."),
        ("cinnamon-economy","Catnip economy transactions, balances, inventory and shop."),
        ("cinnamon-hangry","Hangry Games starts, winners, cancellations and recovery."),
        ("cinnamon-ai-logs","Cinnamon AI usage/settings logs; not private conversation contents."),
        ("cinnamon-level-logs","XP awards, level-ups and level-role changes."),
        ("cinnamon-achievement-logs","Achievement unlocks, rewards, roles and recovery."),
        ("cinnamon-quest-logs","Daily/weekly quest rotations, completions and rewards."),
        ("cinnamon-friendship-logs","Cinnamon Friendship level changes and related events."),
        ("cinnamon-stuff-logs","Cinnamon personality and favourites."),
        ("cinnamon-mood-logs","Private Cinnamon mood and Naughty List logs."),
        ("cinnamon-community-logs","Giveaway and poll events."),
        ("cinnamon-role-logs","Role management events."),
        ("cinnamon-setup-logs","Setup and configuration changes."),
        ("cinnamon-general-logs","General utility command usage."),
        ("cinnamon-dashboard-logs","Dashboard changes, Message Studio sends and audit events."),
        ("cinnamon-welcome","Cinnamon member welcome messages."),
        ("cinnamon-goodbye","Cinnamon member goodbye messages."),
        ("cinnamon-ai","Cinnamon's chat channel (responds only when invited)."),
        ("cinnamon-games","Public Hangry Games lobby and Catnip prizes."),
    ]
    channels={}
    for name,topic in specs:
        ch=discord.utils.get(category.text_channels,name=name)
        if ch is None:
            ch=await guild.create_text_channel(name=name,category=category,topic=topic,reason="Cinnamon dashboard setup")
        if name.endswith("-logs") or name in {"cinnamon-logs","cinnamon-economy","cinnamon-hangry"}:
            try:
                await ch.set_permissions(guild.default_role,view_channel=False)
                if guild.me: await ch.set_permissions(guild.me,view_channel=True,send_messages=True,embed_links=True,read_message_history=True)
            except Exception: pass
        if name=="cinnamon-games":
            await ch.set_permissions(guild.default_role,view_channel=True,send_messages=False,read_message_history=True)
            if guild.me:
                await ch.set_permissions(guild.me,view_channel=True,send_messages=True,embed_links=True,read_message_history=True)
        channels[name]=ch
    normal=state.get("ACHIEVEMENTS",{}); secret=state.get("SECRET_ACHIEVEMENTS",{}); admin=state.get("ADMIN_ACHIEVEMENT",{}) or {}
    role_names=sorted({str(a.get("role")).strip() for a in list(normal.values())+list(secret.values())+[admin] if a.get("role")})+ ["Quest Master","Hangry Games","Fishing Rod Merchant","Fishing Bait Merchant","Adventure • Treasure Hunter","Cinnamon's Naughty List"]
    existing={r.name:r for r in guild.roles if not r.managed}
    for name in dict.fromkeys(role_names):
        if name not in existing:
            try: await guild.create_role(name=name,reason="Cinnamon achievement/quest setup",mentionable=(name=="Hangry Games"))
            except Exception: pass
    gid=guild.id; state.setdefault("log_channels",{})[gid]=channels["cinnamon-logs"].id; state.setdefault("economy_log_channels",{})[gid]=channels["cinnamon-economy"].id
    state.setdefault("category_log_channels",{})[gid]={"moderation":channels["cinnamon-logs"].id,"economy":channels["cinnamon-economy"].id,"ai":channels["cinnamon-ai-logs"].id,"levels":channels["cinnamon-level-logs"].id,"achievements":channels["cinnamon-achievement-logs"].id,"quests":channels["cinnamon-quest-logs"].id,"friendship":channels["cinnamon-friendship-logs"].id,"stuff":channels["cinnamon-stuff-logs"].id,"mood":channels["cinnamon-mood-logs"].id,"community":channels["cinnamon-community-logs"].id,"roles":channels["cinnamon-role-logs"].id,"setup":channels["cinnamon-setup-logs"].id,"general":channels["cinnamon-general-logs"].id,"dashboard":channels["cinnamon-dashboard-logs"].id}
    state.setdefault("ai_channels",{})[gid]=channels["cinnamon-ai"].id
    social=state.setdefault("cinnamon_social",{}).setdefault(str(gid),{"people":{}})
    previous=guild.get_channel(int(social.get("auto_channel",0) or 0))
    if previous is None:
        social["auto_channel"]=channels["cinnamon-games"].id
    if not social.get("setup_configured",False):
        social["auto_enabled"]=True
        social["setup_configured"]=True
    social.setdefault("next_at",time.time()+__import__("random").randint(3600,7200))
    refresh=state.get("wlf_refresh_channel")
    if refresh:
        for kind in ("rod","bait"):
            await refresh(guild,kind)
    state.setdefault("welcome_config",{})[gid]={"channel_id":channels["cinnamon-welcome"].id,"message":"🐾 Welcome {member} to **{server}**! Cinnamon hopes you brought snacks."}
    state.setdefault("goodbye_config",{})[gid]={"channel_id":channels["cinnamon-goodbye"].id,"message":"🐾 {member} left **{server}**. Cinnamon will miss the head pats!"}
    hg=state.get("hg_cog")
    if hg:
        hg.hg_log_channels[gid]=channels["cinnamon-hangry"].id; hg.log_enabled[gid]=True
        try: await hg._save()
        except Exception: pass
    await state["bd_save_data"]()
    return "Cinnamon setup complete: mood/personality logs, public games and private fishing merchants are ready."


def _moderate(guild, actor_id, form):
    action=form.get("mod_action","").lower(); raw_id=form.get("member_id","").strip(); reason=form.get("reason","No reason provided")[:400]
    if not raw_id.isdigit() or not 15 <= len(raw_id) <= 22: raise ValueError("Enter a valid Discord member ID.")
    if action not in {"kick","ban","timeout"}: raise ValueError("Choose a supported moderation action.")
    uid=int(raw_id); actor_id=int(actor_id)
    if uid in {actor_id, guild.owner_id, _bot.user.id if _bot.user else -1}: raise ValueError("This member cannot be moderated from the dashboard.")
    async def perform():
        actor=guild.get_member(actor_id) or await guild.fetch_member(actor_id)
        target=guild.get_member(uid) or await guild.fetch_member(uid)
        me=guild.me
        if actor_id != guild.owner_id and not actor.guild_permissions.administrator:
            raise PermissionError("Your current server permissions do not allow dashboard moderation.")
        if target.top_role >= actor.top_role and actor.id != guild.owner_id:
            raise PermissionError("You cannot moderate a member with an equal or higher role.")
        if target.top_role >= me.top_role: raise PermissionError("Cinnamon's highest role must be above the target member's role.")
        if action=="kick":
            if not actor.guild_permissions.kick_members or not me.guild_permissions.kick_members: raise PermissionError("Both you and Cinnamon need Kick Members permission.")
            await target.kick(reason=f"Dashboard by {actor} ({actor.id}): {reason}")
        elif action=="ban":
            if not actor.guild_permissions.ban_members or not me.guild_permissions.ban_members: raise PermissionError("Both you and Cinnamon need Ban Members permission.")
            await target.ban(reason=f"Dashboard by {actor} ({actor.id}): {reason}", delete_message_seconds=0)
        else:
            if not actor.guild_permissions.moderate_members or not me.guild_permissions.moderate_members: raise PermissionError("Both you and Cinnamon need Moderate Members permission.")
            try: minutes=int(form.get("duration","60"))
            except ValueError: raise ValueError("Timeout duration must be a number of minutes.")
            if not 1 <= minutes <= 40320: raise ValueError("Timeout duration must be between 1 and 40,320 minutes (28 days).")
            await target.timeout(dt.timedelta(minutes=minutes), reason=f"Dashboard by {actor} ({actor.id}): {reason}")
        return str(target), action
    return _run_bot(perform())


@dashboard_bp.get("/login")
def login():
    if not os.getenv("DISCORD_CLIENT_ID") or not os.getenv("DISCORD_CLIENT_SECRET"):
        return _page("<main class='main'><article class='card'><h1>Almost ready</h1><p>Add the Discord OAuth client settings to Render's environment variables.</p></article></main>","Cinnamon Login")
    state=secrets.token_urlsafe(32); session["oauth_state"]=state
    params={"client_id":os.environ["DISCORD_CLIENT_ID"].strip(),"response_type":"code","redirect_uri":_oauth_redirect_uri(),"scope":"identify guilds","state":state}
    return redirect("https://discord.com/oauth2/authorize?"+urllib.parse.urlencode(params))


@dashboard_bp.get("/oauth/callback")
def oauth_callback():
    if request.args.get("error"):
        return _page("<main class='main'><article class='card'><h1>Login cancelled</h1><a class='btn' href='/login'>Try again</a></article></main>")
    state=request.args.get("state",""); saved=session.pop("oauth_state","")
    if not state or not saved or not secrets.compare_digest(state,saved):
        return _page("<main class='main'><article class='card'><h1>Login could not be verified</h1><a class='btn' href='/login'>Restart login</a></article></main>",status=400)
    code=request.args.get("code")
    if not code: return _page("<main class='main'><article class='card'><h1>Missing authorization code</h1><a class='btn' href='/login'>Try again</a></article></main>",status=400)
    try:
        redirect_uri=_oauth_redirect_uri()
        client_id_present=bool(os.getenv("DISCORD_CLIENT_ID", "").strip())
        client_secret_present=bool(os.getenv("DISCORD_CLIENT_SECRET", "").strip())
        log.info(
            "Discord OAuth exchange starting status=%s redirect_uri=%s redirect_sha256=%s client_id_present=%s client_secret_present=%s code_length=%s",
            "authorization_code",
            redirect_uri,
            hashlib.sha256(redirect_uri.encode("utf-8")).hexdigest()[:12],
            client_id_present,
            client_secret_present,
            len(code),
        )
        token=_token_exchange({"grant_type":"authorization_code","code":code,"redirect_uri":redirect_uri})
        user=_request_json(f"{BASE_URL}/users/@me",headers={"Authorization":"Bearer "+token["access_token"]})
        portal_flow=session.pop("appeal_oauth",None)
        sid=secrets.token_urlsafe(32)
        _tokens[sid]={"access_token":token["access_token"],"refresh_token":token.get("refresh_token"),"expires_at":time.time()+int(token.get("expires_in",3600)),"user":user}
        session.clear()
        if isinstance(portal_flow,dict):
            portal_gid=int(portal_flow.get("guild_id",0) or 0)
            portal_token=str(portal_flow.get("token","") or "")
            if not _appeal_portal_config(portal_gid,portal_token):
                return _page("<main class='main'><article class='card'><h1>Appeal link expired</h1><p>This server's appeal link was regenerated or disabled. Ask a moderator for the current link.</p></article></main>","Appeal portal",status=410)
            session["appeal_sid"]=sid
            session["appeal_guild_id"]=portal_gid
            session["appeal_portal_token"]=portal_token
            session["appeal_csrf"]=secrets.token_urlsafe(32)
            return redirect(url_for("cinnamon_dashboard.appeal_portal_form",guild_id=portal_gid,token=portal_token))
        session["dash_sid"]=sid
        session["display_name"]=user.get("global_name") or user.get("username") or "Discord user"
        _csrf()
        return redirect(url_for("cinnamon_dashboard.dashboard_home"))
    except urllib.error.HTTPError as exc:
        try: payload=json.loads(exc.read().decode("utf-8"))
        except Exception: payload={}
        oauth_error=str(payload.get("error", "unknown"))[:120]
        oauth_description=str(payload.get("error_description", "unavailable"))[:240]
        log.error(
            "Discord OAuth HTTP error status=%s error=%s description=%s redirect_sha256=%s",
            exc.code, oauth_error, oauth_description,
            hashlib.sha256(_oauth_redirect_uri().encode("utf-8")).hexdigest()[:12],
        )
        safe_error=html.escape(oauth_error, quote=True)
        return _page(f"<main class='main'><article class='card'><h1>Discord login failed</h1><p class='muted'>Discord rejected the OAuth exchange.</p><p class='muted'><strong>Error:</strong> {safe_error}</p><p class='muted'>The sanitized Discord error is also in the Render logs.</p><a class='btn' href='/login'>Try again</a></article></main>",status=502)
    except Exception as exc:
        log.exception("Discord OAuth callback failed (%s)",type(exc).__name__)
        return _page("<main class='main'><article class='card'><h1>Discord login failed</h1><p class='muted'>An unexpected login error occurred. Check Render logs.</p><a class='btn' href='/login'>Try again</a></article></main>",status=502)


def _appeal_portal_config(guild_id, token):
    """Return live appeal configuration only when the persisted public token matches."""
    if not token:
        return None
    advanced = _state().get("advanced_features_data", {})
    root = advanced.get("cinnamon_moderation_controls_v1", {}) if isinstance(advanced, dict) else {}
    cfg = root.get(str(int(guild_id)), {}) if isinstance(root, dict) else {}
    saved = str(cfg.get("appeal_portal_token", "") or "") if isinstance(cfg, dict) else ""
    if not saved or not secrets.compare_digest(saved, str(token)):
        return None
    return cfg


def _appeal_csrf_input():
    return "<input type='hidden' name='csrf_token' value='" + _esc(session.get("appeal_csrf", "")) + "'>"


def _check_appeal_csrf():
    supplied = request.form.get("csrf_token", "")
    expected = session.get("appeal_csrf", "")
    if not supplied or not expected or not secrets.compare_digest(supplied, expected):
        abort(400, "The appeal form expired. Reload it and try again.")


@dashboard_bp.get("/appeal/<int:guild_id>/<token>")
def appeal_portal(guild_id, token):
    cfg = _appeal_portal_config(guild_id, token)
    if not cfg:
        abort(404)
    guild = _bot.get_guild(int(guild_id)) if _bot else None
    if guild is None:
        return _page("<main class='main'><article class='card'><h1>Appeals temporarily unavailable</h1><p>Cinnamon is not connected to this server right now. Please try again later.</p></article></main>", "Appeal portal", status=503)
    if session.get("appeal_guild_id") == int(guild_id) and session.get("appeal_portal_token") == token and session.get("appeal_sid") in _tokens:
        return redirect(url_for("cinnamon_dashboard.appeal_portal_form", guild_id=guild_id, token=token))
    body = (
        "<main class='main'><article class='card'><h1>Appeal a moderation action</h1>"
        "<p>Submit an appeal to <b>" + _esc(guild.name) + "</b>. Sign in with Discord so Cinnamon can verify that you are a member of this server.</p>"
        "<p class='muted'>Your appeal details are delivered privately to the moderation team. This link does not let anyone view other appeals.</p>"
        "<a class='btn' href='" + _esc(url_for("cinnamon_dashboard.appeal_portal_login", guild_id=guild_id, token=token)) + "'>Continue with Discord</a></article></main>"
    )
    return _page(body, "Appeal portal")


@dashboard_bp.get("/appeal/<int:guild_id>/<token>/login")
def appeal_portal_login(guild_id, token):
    if not _appeal_portal_config(guild_id, token):
        abort(404)
    if not os.getenv("DISCORD_CLIENT_ID") or not os.getenv("DISCORD_CLIENT_SECRET"):
        return _page("<main class='main'><article class='card'><h1>Appeals temporarily unavailable</h1><p>Discord sign-in is not configured. Please contact a server moderator.</p></article></main>", "Appeal portal", status=503)
    state_token = secrets.token_urlsafe(32)
    session["oauth_state"] = state_token
    session["appeal_oauth"] = {"guild_id": int(guild_id), "token": str(token)}
    params = {
        "client_id": os.environ["DISCORD_CLIENT_ID"].strip(),
        "response_type": "code",
        "redirect_uri": _oauth_redirect_uri(),
        "scope": "identify",
        "state": state_token,
    }
    return redirect("https://discord.com/oauth2/authorize?" + urllib.parse.urlencode(params))


@dashboard_bp.route("/appeal/<int:guild_id>/<token>/form", methods=["GET", "POST"])
def appeal_portal_form(guild_id, token):
    cfg = _appeal_portal_config(guild_id, token)
    if not cfg:
        abort(404)
    sid = session.get("appeal_sid")
    if (session.get("appeal_guild_id") != int(guild_id)
            or session.get("appeal_portal_token") != token
            or sid not in _tokens):
        return redirect(url_for("cinnamon_dashboard.appeal_portal", guild_id=guild_id, token=token))
    guild = _bot.get_guild(int(guild_id)) if _bot else None
    if guild is None:
        return _page("<main class='main'><article class='card'><h1>Appeals temporarily unavailable</h1><p>Cinnamon is not connected to this server right now. Please try again later.</p></article></main>", "Appeal portal", status=503)
    user_id = str(_tokens[sid].get("user", {}).get("id", ""))
    if not user_id.isdigit():
        session.pop("appeal_sid", None)
        return redirect(url_for("cinnamon_dashboard.appeal_portal", guild_id=guild_id, token=token))
    try:
        member = _run_bot(guild.fetch_member(int(user_id)))
    except Exception:
        return _page("<main class='main'><article class='card'><h1>Server membership required</h1><p>You must be a current member of this Discord server to submit an appeal. If you recently joined, try again in a moment.</p></article></main>", "Appeal portal", status=403)
    if request.method == "POST":
        _check_appeal_csrf()
        details = request.form.get("details", "").strip()
        if not 20 <= len(details) <= 1500:
            return _page("<main class='main'><article class='card'><h1>Check your appeal</h1><p>Explain your appeal in 20–1,500 characters.</p><a class='btn' href='" + _esc(url_for("cinnamon_dashboard.appeal_portal_form", guild_id=guild_id, token=token)) + "'>Return to form</a></article></main>", "Appeal portal", status=400)
        submit = _state().get("submit_moderation_appeal")
        if not callable(submit):
            return _page("<main class='main'><article class='card'><h1>Appeals temporarily unavailable</h1><p>The appeal service is not ready. Please try again later.</p></article></main>", "Appeal portal", status=503)
        try:
            status, appeal_id = _run_bot(submit(guild, member, details), timeout=35)
        except Exception:
            log.exception("Web appeal submission failed for guild %s", guild_id)
            return _page("<main class='main'><article class='card'><h1>Appeal could not be submitted</h1><p>Storage or Discord was unavailable. Please try again later.</p></article></main>", "Appeal portal", status=503)
        messages = {
            "not_configured": "The server has not configured its private moderator review channel.",
            "pending_exists": "You already have a pending appeal for this server.",
            "rate_limited": "You can submit up to two appeals per server every 24 hours.",
            "save_failed": "Your appeal could not be saved safely. No submission was kept.",
        }
        if status != "ok":
            return _page("<main class='main'><article class='card'><h1>Appeal not submitted</h1><p>" + _esc(messages.get(status, "Please try again later.")) + "</p><a class='btn' href='" + _esc(url_for("cinnamon_dashboard.appeal_portal_form", guild_id=guild_id, token=token)) + "'>Return to form</a></article></main>", "Appeal portal", status=400)
        session["appeal_submitted_id"] = str(appeal_id)
        return redirect(url_for("cinnamon_dashboard.appeal_portal_form", guild_id=guild_id, token=token))
    submitted_id = session.pop("appeal_submitted_id", None)
    if submitted_id:
        return _page("<main class='main'><article class='card'><h1>Appeal submitted</h1><p>Your appeal was delivered privately to the moderation team.</p><p class='muted'>Reference: " + _esc(submitted_id) + "</p></article></main>", "Appeal submitted")
    form = (
        "<main class='main'><article class='card'><h1>Submit a moderation appeal</h1>"
        "<p>Signed in as <b>" + _esc(_tokens[sid].get("user", {}).get("global_name") or _tokens[sid].get("user", {}).get("username") or "Discord member") + "</b>."
        " Your membership in " + _esc(guild.name) + " has been verified.</p>"
        "<form method='post'>" + _appeal_csrf_input() +
        "<div class='field'><label for='appealDetails'>Explain your appeal</label><textarea id='appealDetails' name='details' minlength='20' maxlength='1500' rows='8' required placeholder='Explain which moderation action you are appealing and why...'></textarea><small>20–1,500 characters. Do not include passwords or private account credentials.</small></div>"
        "<button class='btn' type='submit'>Submit appeal</button></form></article></main>"
    )
    return _page(form, "Submit appeal")


def _analytics(guild, state):
    """Live, read-only analytics based on the running bot's current state."""
    gid = guild.id
    xp = state.get("xp_data", {})
    xp_users = [(key, value) for key, value in xp.items() if isinstance(key, tuple) and len(key) >= 2 and key[0] == gid]
    total_xp = sum(max(0, int(value or 0)) for _, value in xp_users)
    warns = state.get("warnings_data", {})
    warning_count = sum(len(value) for key, value in warns.items() if isinstance(key, tuple) and key[0] == gid and isinstance(value, list))
    ach = state.get("achievement_data", {})
    ach_users = [(key, value) for key, value in ach.items() if isinstance(key, tuple) and len(key) >= 2 and key[0] == gid and isinstance(value, dict)]
    unlocked = sum(len(value.get("unlocked", [])) for _, value in ach_users)
    qdata = state.get("quest_data", {})
    quest_users = [(key, value) for key, value in qdata.items() if isinstance(key, tuple) and len(key) >= 2 and key[0] == gid]
    balances = state.get("economy_balances", {})
    guild_balances = [(key, value) for key, value in balances.items() if isinstance(key, tuple) and len(key) >= 2 and key[0] == gid]
    total_catnip = sum(max(0, int(value or 0)) for _, value in guild_balances)
    giveaways = state.get("active_giveaways", {})
    active_giveaways = sum(1 for value in giveaways.values() if isinstance(value, dict) and int(value.get("guild_id", 0) or 0) == gid)
    polls = state.get("active_polls", {})
    active_polls = sum(1 for value in polls.values() if isinstance(value, dict) and int(value.get("guild_id", 0) or 0) == gid)
    cards = [
        ("Members", guild.member_count or len(guild.members), "Server size"),
        ("Members with XP", len(xp_users), f"{total_xp:,} total XP tracked"),
        ("Warnings", warning_count, "Tracked moderation warnings"),
        ("Achievements", unlocked, f"Across {len(ach_users)} tracked member records"),
        ("Quest profiles", len(quest_users), "Members with quest state"),
        ("Catnip in circulation", total_catnip, f"Across {len(guild_balances)} tracked accounts"),
        ("Active giveaways", active_giveaways, "Currently tracked giveaways"),
        ("Active polls", active_polls, "Currently tracked polls"),
    ]
    card_html = "".join(f"<article class='card third'><div class='statlabel'>{_esc(label)}</div><div class='stat'>{int(value):,}</div><p class='muted'>{_esc(note)}</p></article>" for label, value, note in cards)
    body = ("<h1>Server analytics</h1><p class='muted'>Live counters read from Cinnamon's current runtime. These are not historical charts; counters may reset if the bot's non-persistent state is lost.</p>"
            f"<div class='grid'>{card_html}<article class='card full'><h2>Explore a feature</h2><p class='muted'>Jump into the live controls behind each metric.</p><div class='actions'><a class='btn' href='/dashboard?guild_id={gid}&tab=engagement'>Levels & XP</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=achievements'>Achievements</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=quests'>Quests</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=economy'>Catnip economy</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=activity_logs'>Activity logs</a></div></article></div>")
    return body


def _message_studio(guild, state):
    gid = guild.id
    channel_select = _channel_select(guild, "channel_id", allow_none=False)
    form = ("<div class='formgrid'><div class='field'><label>Destination channel</label>" + channel_select + "<small>Choose a text channel Cinnamon can send messages to.</small></div>"
            "<div class='field'><label>Embed accent colour</label><input name='embed_color' type='color' value='#D97732' required></div>"
            "<div class='field'><label>Embed title</label><input name='embed_title' maxlength='256' placeholder='A message from Cinnamon' required></div>"
            "<div class='field'><label>Footer</label><input name='embed_footer' maxlength='200' value='Cinnamon • Made with paws 🐾'></div>"
            "<div class='field' style='grid-column:1/-1'><label>Message text</label><textarea name='embed_description' maxlength='4000' rows='5' placeholder='Write the message content here…' required></textarea><small>Discord embed descriptions support up to 4,000 characters. Mentions are disabled for safety.</small></div>"
            "<div class='field' style='grid-column:1/-1'><label>Optional image URL (HTTPS)</label><input name='embed_image' type='url' maxlength='500' placeholder='https://…'><small>Optional. Only HTTPS image URLs are accepted.</small></div></div>"
            "<label class='toggle'><input type='checkbox' name='send_confirmation' value='yes' required><span><b>I checked the destination and message</b><small>Sending is immediate and cannot be undone.</small></span></label>")
    guide = ("<article class='card half'><h2>Embed checklist</h2><div class='toggle'><span><b>Readable title</b><small>Short, specific and easy to scan.</small></span></div>"
             "<div class='toggle'><span><b>Clear body text</b><small>Use line breaks and avoid walls of text.</small></span></div>"
             "<div class='toggle'><span><b>Consistent Cinnamon look</b><small>Warm orange accent, friendly footer, no surprise mentions.</small></span></div>"
             "<div class='rule'></div><p class='muted'>The studio sends a real Discord embed. The dashboard action and destination are recorded in the dedicated dashboard audit log.</p></article>")
    return ("<h1>Message Studio</h1><p class='muted'>Compose and publish a polished Cinnamon embed to a channel in this server.</p><div class='grid'>"
            "<article class='card half'><h2>Compose an embed</h2>" + _form(gid, "message_send", form, "Send embed") + "</article>" + guide + "</div>")


def _activity_logs(guild, state):
    gid = guild.id
    reader = state.get("audit_recent")
    status_reader = state.get("audit_storage_status")
    entries = []
    source_note = "External Upstash activity history"
    storage_status = {}
    if callable(reader):
        try:
            events = _run_bot(reader(gid, limit=100), timeout=20)
            if callable(status_reader):
                storage_status = _run_bot(status_reader(), timeout=12) or {}
            for event in events:
                try:
                    when = dt.datetime.fromisoformat(str(event.get("timestamp", "")).replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    when = None
                metadata = event.get("metadata") or {}
                detail_parts = []
                if event.get("actor_id"):
                    detail_parts.append("Actor ID: " + str(event["actor_id"]))
                if event.get("target_id"):
                    detail_parts.append("Target ID: " + str(event["target_id"]))
                if event.get("channel_id"):
                    detail_parts.append("Channel ID: " + str(event["channel_id"]))
                detail_parts.extend(str(k) + ": " + str(v) for k, v in list(metadata.items())[:5])
                entries.append((when, str(event.get("category", "general")), "Upstash",
                                str(event.get("action", "Activity")), " · ".join(detail_parts), ""))
        except Exception:
            log.exception("External activity log read failed for guild %s", gid)
            source_note = "External history unavailable — showing recent Discord log messages instead"
    if not entries:
        routes = state.get("category_log_channels", {}).get(gid, {}) or state.get("category_log_channels", {}).get(str(gid), {})
        configured = []
        for category, channel_id in routes.items():
            channel = guild.get_channel(int(channel_id)) if str(channel_id).isdigit() else None
            if channel and hasattr(channel, "history"):
                configured.append((str(category), channel))
        for category, channel_id in [("moderation", state.get("log_channels", {}).get(gid)),
                                      ("economy", state.get("economy_log_channels", {}).get(gid))]:
            channel = guild.get_channel(int(channel_id)) if channel_id and str(channel_id).isdigit() else None
            if channel and hasattr(channel, "history") and all(ch.id != channel.id for _, ch in configured):
                configured.append((category, channel))
        hg = state.get("hg_cog")
        if hg:
            channel = guild.get_channel(hg.hg_log_channels.get(gid, 0))
            if channel and hasattr(channel, "history") and all(ch.id != channel.id for _, ch in configured):
                configured.append(("hangry", channel))
        async def read_recent():
            rows = []
            for category, channel in configured[:15]:
                try:
                    async for message in channel.history(limit=8, oldest_first=False):
                        if not message.embeds:
                            continue
                        embed = message.embeds[0]
                        rows.append((message.created_at, category, channel.name,
                                     embed.title or "Cinnamon log event", embed.description or "",
                                     str(message.jump_url)))
                except Exception as exc:
                    rows.append((None, category, channel.name, "Could not read this log channel",
                                 type(exc).__name__, ""))
            rows.sort(key=lambda item: item[0] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
            return rows[:40]
        try:
            entries = _run_bot(read_recent(), timeout=25)
        except Exception:
            log.exception("Discord activity log fallback failed")
            entries = []
        source_note = "Discord log-channel fallback (limited history)"
    query = request.args.get("q", "").strip()[:100].casefold()
    category_filter = request.args.get("category", "all").strip().casefold()
    categories = sorted({row[1].casefold() for row in entries})
    if category_filter not in categories and category_filter != "all":
        category_filter = "all"
    if category_filter != "all":
        entries = [row for row in entries if row[1].casefold() == category_filter]
    if query:
        entries = [row for row in entries if query in " ".join(map(str, row[1:5])).casefold()]
    category_options = "<option value='all'>All categories</option>" + "".join(
        f"<option value='{_esc(category)}'{' selected' if category == category_filter else ''}>{_esc(category.title())}</option>"
        for category in categories
    )
    filters_html = (f"<form method='get' action='/dashboard' class='formgrid'><input type='hidden' name='guild_id' value='{gid}'><input type='hidden' name='tab' value='activity_logs'>"
                    f"<div class='field'><label>Search recent events</label><input name='q' maxlength='100' value='{_esc(query)}' placeholder='Search event, actor ID, details…'></div>"
                    f"<div class='field'><label>Category</label><select name='category'>{category_options}</select></div><div class='field'><label>&nbsp;</label><button class='btn' type='submit'>Filter events</button> <a class='btn secondary' href='/dashboard?guild_id={gid}&tab=activity_logs'>Clear</a></div></form>")
    if not entries:
        rows_html = "<tr><td colspan='4'>No external records found yet. New events will appear after external audit storage is connected.</td></tr>"
    else:
        rows = []
        for when, category, channel_name, title, description, jump_url in entries[:100]:
            timestamp = when.strftime("%Y-%m-%d %H:%M UTC") if when else "Unavailable"
            link = f"<a class='btn secondary small' href='{_esc(jump_url)}' target='_blank' rel='noopener noreferrer'>Open in Discord</a>" if jump_url.startswith("https://discord.com/") else "External record"
            rows.append(f"<tr><td>{_esc(timestamp)}</td><td>{_esc(category.title())}<br><small>{_esc(channel_name)}</small></td><td><b>{_esc(title[:180])}</b><br><small>{_esc(description[:260])}</small></td><td>{link}</td></tr>")
        rows_html = "".join(rows)
    health = ("Connected" if storage_status.get("connected") else
              "Not verified" if not storage_status else "Unavailable")
    return ("<h1>Activity logs</h1><p class='muted'>Searchable external audit records stored separately from Cinnamon's bot snapshot. Private message text and AI prompts/replies are not stored by the shared logger.</p>"
            f"<article class='card full'><h2>External storage</h2><div class='toggle'><b>Upstash audit connection</b><span class='pill {'good' if storage_status.get('connected') else 'warn'}'>{_esc(health)}</span></div>"
            f"<p class='muted'>{_esc(source_note)} · {len(entries)} record(s) currently loaded · Retention: {_esc(storage_status.get('retention_days', 'unknown'))} days · Per-server cap: {_esc(storage_status.get('max_events', 'unknown'))}</p></article>"
            f"<article class='card full'><h2>Find an event</h2>{filters_html}</article>"
            f"<article class='card full'><h2>Recent events</h2><div class='tablewrap'><table><thead><tr><th>Time</th><th>Category / source</th><th>Event</th><th>Location</th></tr></thead><tbody>{rows_html}</tbody></table></div></article>"
            f"<div class='actions'><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=system'>Manage log routing</a><a class='btn secondary' href='/dashboard?guild_id={gid}&tab=analytics'>View analytics</a></div>")


def _backup_guild_value(state, key, gid):
    mapping=state.get(key,{}) or {}
    return mapping.get(gid, mapping.get(str(gid)))


def _backup_json_safe(value):
    if isinstance(value,dict): return {str(k):_backup_json_safe(v) for k,v in value.items()}
    if isinstance(value,(set,tuple,list)): return [_backup_json_safe(v) for v in value]
    if value is None or isinstance(value,(str,int,float,bool)): return value
    return str(value)


def _guild_config_payload(guild, state):
    gid=int(guild.id)
    keys=("welcome_config","goodbye_config","automod_config","antiraid_config","xp_per_message","xp_channels",
          "level_roles","achievement_config","quest_config","ai_channels","disabled_channels","log_channels",
          "category_log_channels","economy_log_channels","economy_income_roles")
    config={}
    for key in keys:
        value=_backup_guild_value(state,key,gid)
        if value is not None:
            config[key]=_backup_json_safe(value)
    templates=state.get("giveaway_templates",{}) or {}
    config["giveaway_templates"]=_backup_json_safe(templates.get(gid,templates.get(str(gid),{})) or {})
    schedules=state.get("giveaway_schedules",{}) or {}
    config["giveaway_schedules"]=_backup_json_safe({str(k):v for k,v in schedules.items() if int(v.get("guild_id",0))==gid})
    return {"format":"cinnamon-config-backup","schema_version":1,"guild_id":gid,
            "guild_name":str(guild.name),"created_at":dt.datetime.now(dt.timezone.utc).isoformat(),
            "notes":"Configuration only. Balances, inventories, user progress, active giveaways, tokens and secrets are excluded.",
            "config":config}


@dashboard_bp.get("/dashboard/backup")
def dashboard_backup_download():
    sid=session.get("dash_sid")
    if not sid or sid not in _tokens: return redirect(url_for("cinnamon_dashboard.login"))
    context=_dashboard_context()
    if not context: return redirect(url_for("cinnamon_dashboard.login"))
    sid,guilds,eligible=context
    if not eligible: abort(403)
    guild_id=request.args.get("guild_id") or eligible[0]["id"]
    guild,_=_get_access(sid,guilds,guild_id)
    payload=_guild_config_payload(guild,_state())
    response=make_response(json.dumps(payload,ensure_ascii=False,indent=2))
    response.headers["Content-Type"]="application/json; charset=utf-8"
    response.headers["Content-Disposition"]=f'attachment; filename="cinnamon-config-{guild.id}.json"'
    return response


def _restore_guild_config_impl(guild, state, payload):
    if not isinstance(payload,dict) or payload.get("format")!="cinnamon-config-backup" or payload.get("schema_version")!=1:
        raise ValueError("This file is not a supported Cinnamon configuration backup.")
    if str(payload.get("guild_id"))!=str(guild.id):
        raise ValueError("This backup belongs to a different Discord server. Nothing was changed.")
    config=payload.get("config")
    if not isinstance(config,dict): raise ValueError("The backup's config section is missing or invalid.")
    allowed={"welcome_config","goodbye_config","automod_config","antiraid_config","xp_per_message","xp_channels",
             "level_roles","achievement_config","quest_config","ai_channels","disabled_channels","log_channels",
             "category_log_channels","economy_log_channels","economy_income_roles"}
    changed=[]
    for key in allowed:
        if key not in config: continue
        value=config[key]
        target=state.setdefault(key,{})
        if key in {"welcome_config","goodbye_config"}:
            if value is not None:
                if not isinstance(value,dict) or not str(value.get("message","")) or len(str(value.get("message","")))>800:
                    raise ValueError(f"Backup section {key} has an invalid message template.")
                channel_id=value.get("channel_id")
                if not str(channel_id).isdigit() or not guild.get_channel(int(channel_id)):
                    raise ValueError(f"Backup section {key} refers to a channel that is not in this server.")
                value={"channel_id":int(channel_id),"message":str(value["message"])}
        elif key in {"ai_channels","log_channels","economy_log_channels"}:
            if value is not None:
                if not str(value).isdigit() or not guild.get_channel(int(value)):
                    raise ValueError(f"Backup section {key} refers to a channel that is not in this server.")
                value=int(value)
        elif key in {"xp_per_message"}:
            if not isinstance(value,int) or isinstance(value,bool) or not 0<=value<=100:
                raise ValueError("XP per message must be a whole number between 0 and 100.")
        elif key in {"xp_channels","disabled_channels"}:
            if not isinstance(value,list): raise ValueError(f"Backup section {key} must be a list of channel IDs.")
            clean=[]
            for item in value:
                if str(item).isdigit() and guild.get_channel(int(item)):
                    clean.append(int(item))
            value=set(dict.fromkeys(clean))
        elif key=="level_roles":
            if not isinstance(value,dict): raise ValueError("Level roles must be a mapping of level to role ID.")
            clean={}
            for level,role_id in value.items():
                if not str(level).isdigit() or not 1<=int(level)<=200 or not str(role_id).isdigit(): continue
                role=guild.get_role(int(role_id))
                if role and not role.is_default() and not role.managed and guild.me and role < guild.me.top_role:
                    clean[int(level)]=role.id
            value=clean
        elif key=="category_log_channels":
            if not isinstance(value,dict): raise ValueError("Category log routing must be an object.")
            value={str(category):int(channel_id) for category,channel_id in value.items()
                   if str(channel_id).isdigit() and guild.get_channel(int(channel_id))}
        elif key=="economy_income_roles":
            if not isinstance(value,dict): raise ValueError("Role income settings must be an object.")
            clean={}
            for role_id,cfg in value.items():
                role=guild.get_role(int(role_id)) if str(role_id).isdigit() else None
                if not role or role.is_default() or role.managed or not isinstance(cfg,dict): continue
                try: amount=int(cfg.get("amount",0)); cooldown=int(cfg.get("cooldown",3600))
                except (TypeError,ValueError): continue
                if 1<=amount<=1_000_000 and 60<=cooldown<=31_536_000:
                    clean[role.id]={"amount":amount,"cooldown":cooldown,
                                    "interval":max(1,int(cfg.get("interval",max(1,cooldown//60)))),
                                    "unit":str(cfg.get("unit","minute"))[:10]}
            value=clean
        elif key in {"automod_config","antiraid_config","achievement_config","quest_config"}:
            if not isinstance(value,dict): raise ValueError(f"Backup section {key} must be an object.")
            if key=="automod_config":
                words=value.get("words",[])
                if not isinstance(words,list): words=[]
                value={"words":[str(w)[:100] for w in words[:50] if str(w).strip()],
                       "spam":bool(value.get("spam")),"mentions":bool(value.get("mentions")),
                       "invites":bool(value.get("invites")),"mention_threshold":max(2,min(20,int(value.get("mention_threshold",5))))}
            elif key=="antiraid_config":
                value={"enabled":bool(value.get("enabled")),"threshold":max(2,min(100,int(value.get("threshold",5)))),
                       "window":max(2,min(300,int(value.get("window",10))))}
        if value is None:
            target.pop(guild.id,None); target.pop(str(guild.id),None)
        else:
            target[guild.id]=value
        changed.append(key)
    if "giveaway_templates" in config:
        templates=config["giveaway_templates"]
        if not isinstance(templates,dict) or len(templates)>100: raise ValueError("Giveaway templates must be an object with at most 100 entries.")
        clean={}
        for name,cfg in templates.items():
            if not isinstance(cfg,dict): continue
            name=str(name).strip().lower()[:40]
            prize=str(cfg.get("prize","Giveaway"))[:200]
            try: winners=max(1,min(100,int(cfg.get("winners",1))))
            except (TypeError,ValueError): winners=1
            clean[name]=dict(cfg,prize=prize,winners=winners)
        state.setdefault("giveaway_templates",{})[guild.id]=clean
        changed.append("giveaway_templates")
    if "giveaway_schedules" in config:
        schedules=config["giveaway_schedules"]
        if not isinstance(schedules,dict) or len(schedules)>50: raise ValueError("Recurring giveaway schedules must be an object with at most 50 entries.")
        target=state.setdefault("giveaway_schedules",{})
        for sid,item in list(target.items()):
            if int(item.get("guild_id",0))==guild.id: target.pop(sid,None)
        for sid,item in schedules.items():
            if not isinstance(item,dict) or int(item.get("guild_id",0))!=guild.id: continue
            try:
                channel_id=int(item.get("channel_id",0)); winners=max(1,min(100,int(item.get("winners",1))))
                duration=max(1,min(525600,int(item.get("duration_minutes",1440))))
                repeat_days=max(1,min(365,int(item.get("repeat_every_days",7))))
                next_at=max(time.time()+60,float(item.get("next_at",time.time()+86400)))
            except (TypeError,ValueError): continue
            channel=guild.get_channel(channel_id); prize=str(item.get("prize",""))[:200]
            if not channel or not prize: continue
            target[str(sid)]=dict(item,channel_id=channel_id,prize=prize,guild_id=guild.id,winners=winners,
                duration_minutes=duration,repeat_every_days=repeat_days,next_at=next_at,enabled=bool(item.get("enabled",True)))
        changed.append("giveaway_schedules")
    return sorted(set(changed))


def _restore_guild_config(guild, state, payload):
    """Restore config atomically: invalid files must not leave partial changes in memory."""
    keys=("welcome_config","goodbye_config","automod_config","antiraid_config","xp_per_message","xp_channels",
          "level_roles","achievement_config","quest_config","ai_channels","disabled_channels","log_channels",
          "category_log_channels","economy_log_channels","economy_income_roles","giveaway_templates","giveaway_schedules")
    present={key for key in keys if key in state}
    snapshots={key:copy.deepcopy(state[key]) for key in present if isinstance(state[key],dict)}
    try:
        return _restore_guild_config_impl(guild,state,payload)
    except Exception:
        for key in keys:
            if key not in present:
                state.pop(key,None)
                continue
            snapshot=snapshots.get(key)
            current=state.get(key)
            if snapshot is not None and isinstance(current,dict):
                current.clear(); current.update(snapshot)
            elif snapshot is not None:
                state[key]=snapshot
        raise


@dashboard_bp.get("/dashboard")
def dashboard_home():
    sid=session.get("dash_sid")
    if not sid or sid not in _tokens: return redirect(url_for("cinnamon_dashboard.login"))
    try:
        context=_dashboard_context()
    except Exception as exc:
        log.exception("Dashboard identity/guild lookup failed (%s)",type(exc).__name__)
        session.pop("dash_sid",None); return redirect(url_for("cinnamon_dashboard.login"))
    if not context: return redirect(url_for("cinnamon_dashboard.login"))
    sid,guilds,eligible=context
    if not eligible:
        body="<section class='hero'><div><h1>No manageable server found</h1><p>Add Cinnamon to a server where you are the owner or have Administrator permission, then reload.</p></div><img class='heroimg' src='/assets/cinnamon_mascot.svg' alt='Cinnamon'></section>"
        return _page("<main class='main'>"+_header()+body+"</main>")
    guild_id=request.args.get("guild_id") or eligible[0]["id"]
    guild,guild_item=_get_access(sid,guilds,guild_id)
    tab=request.args.get("tab","overview"); allowed={"overview","mind","adventure","automation","moderation","engagement","achievements","quests","friendship","companions","economy","shop_items","giveaways","tickets","roles_setup","hangry","community","message_studio","analytics","activity_logs","system"}
    if tab not in allowed: tab="overview"
    state=_state(); notice=session.pop("dashboard_notice",None)
    notice_level=session.pop("dashboard_notice_level","success")
    pages={"overview":_overview,"mind":_mind,"adventure":_adventure,"automation":_automation,"moderation":_moderation,"engagement":_engagement,"achievements":_achievements,"quests":_quests,"friendship":_friendship,"companions":_companions,"economy":_economy,"shop_items":_shop_items,"giveaways":_giveaways,"tickets":_tickets,"roles_setup":_roles_setup,"hangry":_hangry,"community":_community,"message_studio":_message_studio,"analytics":_analytics,"activity_logs":_activity_logs,"system":_system}
    return _shell(guild,eligible,tab,pages[tab](guild,state),notice,notice_level)



@dashboard_bp.post("/dashboard/action")
def dashboard_action():
    _check_csrf()
    sid=session.get("dash_sid")
    if not sid or sid not in _tokens: return redirect(url_for("cinnamon_dashboard.login"))
    try:
        context=_dashboard_context()
        if not context: abort(401)
        sid,guilds,eligible=context
        guild_id=request.form.get("guild_id","")
        guild,_=_get_access(sid,guilds,guild_id)
        gid=guild.id; state=_state(); action=request.form.get("action","")
        actor=_tokens[sid]["user"].get("username","dashboard user")
        async def authorize_dashboard_edit():
            uid=int(_tokens[sid]["user"]["id"])
            return await _dashboard_is_admin(guild, uid)
        if not _run_bot(authorize_dashboard_edit()):
            raise PermissionError("Dashboard changes require Administrator permission.")
        if action in {"welcome","goodbye","ai_channel","log_channel","special_logs","automod","antiraid","levelrole_add","levelrole_remove","economy_item_add","economy_item_save","economy_item_remove","shop_items_log_channel","shop_catalog_restore","shop_item_add","shop_item_save","shop_item_disable","shop_recipe_save","shop_recipe_remove","shop_box_reward_add","shop_box_reward_remove","shop_box_weight","shop_box_distribution","economy_income_add","economy_income_remove","giveaway_create","giveaway_edit","giveaway_draft_save","giveaway_draft_update","giveaway_draft_publish","giveaway_draft_delete","giveaway_end","giveaway_cancel","giveaway_template_save","giveaway_template_delete","giveaway_repeat_create","giveaway_repeat_stop","giveaway_reroll","config_backup_restore","hangry_logs","recall","message_send","community_features_settings","community_event_create","community_event_cancel","community_poll_create","community_poll_close","security_settings","moderation_controls_settings","verification_publish","appeal_settings","appeal_portal_publish","appeal_portal_rotate","dashboard_appeal_review","ticket_dashboard_claim","ticket_dashboard_unclaim"}:
            if not _tokens[sid]["user"].get("id"): abort(401)
        if action=="brain_settings":
            _run_bot(_apply_brain_settings(
                state, gid, independence_enabled="independence_enabled" in request.form,
                chat_actions_enabled="chat_actions_enabled" in request.form,
                prompts_enabled="prompts_enabled" in request.form,
                ai_judgment_enabled="ai_judgment_enabled" in request.form))
            _audit(gid,actor,"Dashboard: Cinnamon boundaries updated",
                   f"Independence={bool('independence_enabled' in request.form)}; conversational actions={bool('chat_actions_enabled' in request.form)}.")
            session["dashboard_notice"]="Cinnamon's activity and action boundaries saved."
        elif action=="mind_settings":
            raw=request.form.get("channel_id","").strip()
            if not raw.isdigit(): raise ValueError("Choose a valid Hangry Games channel.")
            channel=guild.get_channel(int(raw))
            if not isinstance(channel,__import__("discord").TextChannel):
                raise ValueError("Choose a text channel in this server.")
            if not channel.permissions_for(guild.default_role).view_channel:
                raise ValueError("Surprise games must run in a public channel. Members need to see the join button.")
            perms = channel.permissions_for(guild.me) if guild.me else None
            if not perms or not (perms.view_channel and perms.send_messages and perms.embed_links):
                raise ValueError("Cinnamon needs View Channel, Send Messages and Embed Links in the selected game channel.")
            flags={k:k in request.form for k in ("auto_enabled","cameos_enabled","questions_enabled")}
            play_on="play_enabled" in request.form
            async def apply_mind():
                social=state["cinnamon_social"].setdefault(str(gid),{"people":{}})
                old=social.get("auto_channel")
                social.update(flags)
                state["cinnamon_actions"].setdefault(str(gid), {"players": {}})["play_enabled"]=play_on
                social["auto_channel"]=channel.id
                if old!=channel.id or (flags["auto_enabled"] and not social.get("next_at")):
                    social["next_at"]=time.time()+__import__("random").randint(3600,7200)
                if not await state["bd_save_data"]():
                    raise ValueError("The durable settings save could not be verified. Check storage before trying again.")
            _run_bot(apply_mind())
            _audit(gid,actor,"Dashboard: Cinnamon Mind settings updated",
                   f"Hangry channel #{channel.name}; flags={flags}.")
            session["dashboard_notice"]="Cinnamon Mind controls saved."
        elif action=="merchant_access":
            kind=request.form.get("merchant_kind","")
            mode=request.form.get("access","")
            if kind not in ("rod","bait") or mode not in ("private","two_hours","public"):
                raise ValueError("Choose a known fishing merchant and visibility option.")
            announce="announce" in request.form
            async def apply_merchant():
                import discord
                import time as _time
                root=state["cinnamon_wildlands_fishing"].setdefault(str(gid),{})
                window=root.setdefault("merchant_windows",{}).setdefault(kind,{})
                old=dict(window)
                window.update({"finder_id":None,"manual_public":mode=="public",
                               "ends_at":_time.time()+7200 if mode=="two_hours" else 0,
                               "closed_notice":mode=="private"})
                try:
                    channel=await state["wlf_refresh_channel"](guild,kind)
                    await state["bd_save_data"]()
                except Exception:
                    window.clear();window.update(old)
                    raise
                if mode!="private":
                    role=discord.utils.get(guild.roles,name=state["wlf_merchant_names"][kind])
                    line="🐈 The "+state["wlf_merchant_names"][kind]+" is open in "+channel.mention+"!"
                    if mode=="two_hours": line+=" Two-hour limited opening."
                    if announce and role: line=role.mention+" "+line
                    await channel.send(line,allowed_mentions=discord.AllowedMentions(
                        everyone=False,users=False,roles=[role] if announce and role else []))
                return channel.name
            name=_run_bot(apply_merchant(),timeout=40)
            _audit(gid,actor,"Dashboard: fishing merchant access",
                   f"Merchant={kind}; action={mode}; channel=#{name}; role announcement={announce}.")
            session["dashboard_notice"]="Merchant access updated for #"+name+"."
        elif action=="economy_transfer":
            target_raw=request.form.get("member_id","").strip()
            nonce=request.form.get("transfer_nonce","").strip()
            try: amount=int(request.form.get("amount",""))
            except ValueError: raise ValueError("Catnip amount must be a positive whole number.")
            if not 1<=amount<=10000000 or not target_raw.isdigit() or len(nonce)<16 or len(nonce)>100:
                raise ValueError("Choose a member and 1–10,000,000 Catnip.")
            recipient=guild.get_member(int(target_raw))
            actor_id=int(_tokens[sid]["user"]["id"])
            if not recipient or recipient.bot or recipient.id==actor_id:
                raise ValueError("Choose a different non-bot member by name.")
            async def transfer():
                lock=getattr(_bot,"_dashboard_catnip_lock",None)
                if lock is None:
                    lock=asyncio.Lock()
                    _bot._dashboard_catnip_lock=lock
                async with lock:
                    root=state["advanced_features_data"].setdefault("dashboard_transfer_ids_v1",{})
                    used=root.setdefault(str(gid),[])
                    if nonce in used: raise ValueError("This transfer was already submitted.")
                    balances=state["economy_balances"]
                    before=int(balances.get((gid,actor_id),0))
                    if before<amount: raise ValueError("Your own Catnip balance is too low for that gift.")
                    recv_before=int(balances.get((gid,recipient.id),0))
                    balances[(gid,actor_id)]=before-amount
                    balances[(gid,recipient.id)]=recv_before+amount
                    used.append(nonce)
                    del used[:-100]
                    await state["bd_save_data"]()
                    return before,recv_before
            before,recv_before=_run_bot(transfer())
            send_log=state["send_log"]
            _run_bot(send_log(gid,title="🎁 Catnip transfer",category="economy",fields=[
                ("From",f"{actor} ({actor_id})"),("To",f"{recipient} ({recipient.id})"),
                ("Amount",f"{amount:,} Catnip"),("Sender after",str(before-amount)),
                ("Recipient after",str(recv_before+amount))]))
            _audit(gid,actor,"Dashboard: Catnip gift",
                   f"Sent {amount:,} Catnip to {recipient} ({recipient.id}) from actor's wallet.")
            session["dashboard_notice"]=f"Sent {amount:,} Catnip to {recipient.display_name}."
        elif action=="appeal_settings":
            raw=request.form.get("appeal_channel_id","").strip()
            public_raw=request.form.get("appeal_public_channel_id","").strip()
            channel=guild.get_channel(int(raw)) if raw.isdigit() else None
            public_channel=guild.get_channel(int(public_raw)) if public_raw.isdigit() else None
            discord_module=__import__("discord")
            if raw and not isinstance(channel,discord_module.TextChannel):
                raise ValueError("Choose a valid private appeal review channel.")
            if channel and channel.permissions_for(guild.default_role).view_channel:
                raise ValueError("The moderator review channel must be private.")
            if public_raw and not isinstance(public_channel,discord_module.TextChannel):
                raise ValueError("Choose a valid public appeal link channel.")
            if public_channel and not public_channel.permissions_for(guild.default_role).view_channel:
                raise ValueError("The appeal link channel must be visible to server members.")
            async def save_appeal_channels():
                root=state["advanced_features_data"].setdefault("cinnamon_moderation_controls_v1",{})
                cfg=root.setdefault(str(gid),{})
                before=copy.deepcopy(cfg)
                cfg["appeal_channel_id"]=int(channel.id) if channel else 0
                cfg["appeal_public_channel_id"]=int(public_channel.id) if public_channel else 0
                if not cfg.get("appeal_portal_token"):
                    cfg["appeal_portal_token"]=secrets.token_urlsafe(32)
                try:
                    saved=await state["bd_save_data"]()
                except Exception:
                    saved=False
                    log.exception("Could not persist appeal portal settings")
                if not saved:
                    cfg.clear();cfg.update(before)
                    raise ValueError("Couldn't durably save the appeal settings.")
            _run_bot(save_appeal_channels())
            _audit(gid,actor,"Dashboard: appeal portal settings updated",
                   f"Private review channel={channel.id if channel else 0}; public link channel={public_channel.id if public_channel else 0}.")
            session["dashboard_notice"]="Appeal channels saved. The portal link is ready below."
        elif action=="appeal_portal_rotate":
            async def rotate_appeal_portal():
                root=state["advanced_features_data"].setdefault("cinnamon_moderation_controls_v1",{})
                cfg=root.setdefault(str(gid),{})
                previous=cfg.get("appeal_portal_token")
                cfg["appeal_portal_token"]=secrets.token_urlsafe(32)
                try:
                    saved=await state["bd_save_data"]()
                except Exception:
                    saved=False
                if not saved:
                    if previous is None: cfg.pop("appeal_portal_token",None)
                    else: cfg["appeal_portal_token"]=previous
                    raise ValueError("Could not save the new portal link. The old link remains active.")
            _run_bot(rotate_appeal_portal())
            _audit(gid,actor,"Dashboard: appeal portal link rotated","The previous public link has been revoked.")
            session["dashboard_notice"]="New appeal link generated. The old link no longer works."
        elif action=="appeal_portal_publish":
            discord_module=__import__("discord")
            async def publish_appeal_portal():
                root=state["advanced_features_data"].setdefault("cinnamon_moderation_controls_v1",{})
                cfg=root.setdefault(str(gid),{})
                token=str(cfg.get("appeal_portal_token","") or "")
                channel=guild.get_channel(int(cfg.get("appeal_public_channel_id",0) or 0))
                if not token:
                    raise ValueError("Save appeal settings first to generate the portal link.")
                if not isinstance(channel,discord_module.TextChannel):
                    raise ValueError("Choose a public appeal link channel first.")
                portal=(os.getenv("RENDER_EXTERNAL_URL", "https://cinnamon-c328.onrender.com").rstrip("/") +
                    url_for("cinnamon_dashboard.appeal_portal",guild_id=gid,token=token))
                view_class=state.get("ModerationAppealPortalView")
                if not callable(view_class):
                    raise ValueError("The appeal portal panel is unavailable. Restart Cinnamon after updating.")
                embed=discord_module.Embed(
                    title="📨 Need to appeal a moderation action?",
                    description="Use the secure appeal portal below. Sign in with Discord and verify your server membership. Your appeal is sent privately to the moderation team.",
                    color=0xE8A05A,
                )
                await channel.send(embed=embed,view=view_class(portal),
                    allowed_mentions=discord_module.AllowedMentions.none())
                return channel.mention
            channel_mention=_run_bot(publish_appeal_portal())
            _audit(gid,actor,"Dashboard: appeal portal published",f"Published the member appeal link in {channel_mention}.")
            session["dashboard_notice"]="Appeal portal link published in "+channel_mention+"."
        elif action=="dashboard_appeal_review":
            appeal_id=request.form.get("appeal_id","").strip()
            decision=request.form.get("decision","").strip()
            if decision not in {"approved","declined"}: raise ValueError("Choose an appeal decision.")
            async def review_dashboard_appeal():
                root=state["advanced_features_data"].setdefault("cinnamon_moderation_controls_v1",{})
                cfg=root.setdefault(str(gid),{})
                record=cfg.setdefault("appeals",{}).get(appeal_id)
                if not isinstance(record,dict) or record.get("status")!="pending":
                    raise ValueError("That appeal is no longer pending.")
                before=__import__("copy").deepcopy(record)
                reviewer_id=int(_tokens[sid]["user"]["id"])
                record["status"],record["reviewed_by"]=decision,reviewer_id
                record["review_note"]="Reviewed from the dashboard."
                record["reviewed_at"]=int(time.time())
                if not await state["bd_save_data"]():
                    record.clear();record.update(before)
                    raise ValueError("Could not durably save the appeal decision.")
                try:
                    user=await state["bot"].fetch_user(int(record.get("user_id",0)))
                    await user.send(f"Your moderation appeal for {guild.name} was {decision}.")
                except Exception:
                    pass
                channel=guild.get_channel(int(record.get("channel_id",0) or 0))
                view_class=state.get("ModerationAppealView")
                if channel and callable(view_class):
                    try:
                        message=await channel.fetch_message(int(record.get("message_id",0)))
                        embed=__import__("discord").Embed(title="Moderation appeal "+decision.title(),
                            description="The appeal has been reviewed by server moderation.",color=0x69A982 if decision=="approved" else 0xD97777)
                        await message.edit(embed=embed,view=view_class(gid,appeal_id,disabled=True))
                    except __import__("discord").HTTPException:
                        pass
            _run_bot(review_dashboard_appeal())
            _audit(gid,actor,"Dashboard: moderation appeal reviewed",f"Appeal {appeal_id} marked {decision}.")
            session["dashboard_notice"]="Appeal "+appeal_id+" marked "+decision+"."
        elif action=="security_settings":
            def optional_security_channel():
                raw=request.form.get("alert_channel_id","").strip()
                if not raw: return 0
                if not raw.isdigit(): raise ValueError("Choose a valid private security alert channel.")
                channel=guild.get_channel(int(raw))
                if not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Choose a text channel in this server.")
                if channel.permissions_for(guild.default_role).view_channel:
                    raise ValueError("Security alert channels should be private to moderators.")
                return int(channel.id)
            try:
                spam_threshold=int(request.form.get("antispam_threshold","6"))
                spam_window=int(request.form.get("antispam_window","8"))
                spam_timeout=int(request.form.get("antispam_timeout","60"))
                nuke_threshold=int(request.form.get("antinuke_threshold","3"))
            except ValueError:
                raise ValueError("Security thresholds and durations must be whole numbers.")
            if not 4<=spam_threshold<=15 or not 3<=spam_window<=30 or not 30<=spam_timeout<=3600 or not 2<=nuke_threshold<=8:
                raise ValueError("Check anti-spam and anti-nuke ranges.")
            alert_channel_id=optional_security_channel()
            async def apply_security_settings():
                root=state["advanced_features_data"].setdefault("cinnamon_security_guard_v1",{})
                cfg=root.setdefault(str(gid),{})
                before=__import__("copy").deepcopy(cfg)
                cfg.update({"antispam_enabled":"antispam_enabled" in request.form,
                            "antispam_threshold":spam_threshold,"antispam_window":spam_window,
                            "antispam_timeout":spam_timeout,"antinuke_enabled":"antinuke_enabled" in request.form,
                            "antinuke_threshold":nuke_threshold,"alert_channel_id":alert_channel_id})
                if not await state["bd_save_data"]():
                    cfg.clear();cfg.update(before)
                    raise ValueError("The durable security settings save could not be verified. No changes were kept.")
            _run_bot(apply_security_settings())
            _audit(gid,actor,"Dashboard: security safeguards updated",
                   f"Anti-spam={'enabled' if 'antispam_enabled' in request.form else 'disabled'}; anti-nuke={'enabled' if 'antinuke_enabled' in request.form else 'disabled'}; alert channel={alert_channel_id}.")
            session["dashboard_notice"]="Anti-spam and anti-nuke settings saved."
        elif action=="moderation_controls_settings":
            def optional_role(field):
                raw=request.form.get(field,"").strip()
                if not raw: return 0
                if not raw.isdigit(): raise ValueError("Choose a valid role.")
                role=guild.get_role(int(raw))
                if not role or role.is_default() or role.managed: raise ValueError("Choose a valid assignable role.")
                if role>=guild.me.top_role: raise ValueError("Cinnamon's bot role must be above each role it assigns.")
                return int(role.id)
            def optional_channel(field):
                raw=request.form.get(field,"").strip()
                if not raw: return 0
                if not raw.isdigit(): raise ValueError("Choose a valid channel.")
                channel=guild.get_channel(int(raw))
                if not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Choose a text channel from this server.")
                return int(channel.id)
            autorole_id=optional_role("autorole_id")
            verification_role_id=optional_role("verification_role_id")
            verification_channel_id=optional_channel("verification_channel_id")
            welcome_channel_id=optional_channel("welcome_channel_id")
            rules_channel_id=optional_channel("rules_channel_id")
            if bool(verification_role_id)!=bool(verification_channel_id):
                raise ValueError("Choose both a verification channel and role, or leave both blank.")
            if verification_channel_id:
                channel=guild.get_channel(verification_channel_id)
                perms=channel.permissions_for(guild.me)
                if not (perms.view_channel and perms.send_messages and perms.embed_links):
                    raise ValueError("Cinnamon needs View Channel, Send Messages and Embed Links in the verification channel.")
            async def apply_moderation_controls():
                root=state["advanced_features_data"].setdefault("cinnamon_moderation_controls_v1",{})
                cfg=root.setdefault(str(gid),{})
                before=__import__("copy").deepcopy(cfg)
                cfg.update({"autorole_id":autorole_id,"verification_role_id":verification_role_id,
                            "verification_channel_id":verification_channel_id})
                cfg["onboarding"]={"welcome_channel_id":welcome_channel_id,"rules_channel_id":rules_channel_id}
                if not await state["bd_save_data"]():
                    cfg.clear();cfg.update(before)
                    raise ValueError("The durable onboarding settings save could not be verified. No changes were kept.")
            _run_bot(apply_moderation_controls())
            _audit(gid,actor,"Dashboard: verification and onboarding settings updated",
                   f"Autorole={autorole_id}; verification role={verification_role_id}; verification channel={verification_channel_id}; welcome={welcome_channel_id}; rules={rules_channel_id}.")
            session["dashboard_notice"]="Verification, autorole and onboarding settings saved."
        elif action=="verification_publish":
            async def publish_verification():
                root=state["advanced_features_data"].setdefault("cinnamon_moderation_controls_v1",{})
                cfg=root.setdefault(str(gid),{})
                channel=guild.get_channel(int(cfg.get("verification_channel_id",0) or 0))
                role=guild.get_role(int(cfg.get("verification_role_id",0) or 0))
                view_class=state.get("CinnamonVerificationView")
                if not isinstance(channel,__import__("discord").TextChannel) or not role or not callable(view_class):
                    raise ValueError("Configure a verification channel and role before publishing the panel.")
                if role>=guild.me.top_role or not guild.me.guild_permissions.manage_roles:
                    raise ValueError("Cinnamon's bot role must be above the verification role and have Manage Roles.")
                embed=__import__("discord").Embed(title="🔐 Server Verification",
                    description=f"Press Verify below to receive {role.mention} and finish server verification.",
                    color=0x91B5A2)
                old_channel_id=int(cfg.get("verification_channel_id",0) or 0)
                old_message_id=int(cfg.get("verification_message_id",0) or 0)
                message=await channel.send(embed=embed,view=view_class(gid),
                    allowed_mentions=__import__("discord").AllowedMentions.none())
                before=old_message_id
                cfg["verification_message_id"]=int(message.id)
                if not await state["bd_save_data"]():
                    cfg["verification_message_id"]=before
                    try: await message.delete()
                    except __import__("discord").HTTPException: pass
                    raise ValueError("Could not save the published verification panel. The new post was removed.")
                if old_message_id:
                    old_channel=guild.get_channel(old_channel_id)
                    if old_channel:
                        try:
                            old_message=await old_channel.fetch_message(old_message_id)
                            await old_message.edit(view=view_class(gid,disabled=True))
                        except __import__("discord").HTTPException:
                            pass
                return channel.mention
            channel_mention=_run_bot(publish_verification())
            _audit(gid,actor,"Dashboard: verification panel published",f"Posted in {channel_mention}.")
            session["dashboard_notice"]="Verification panel published in "+channel_mention+"."
        elif action=="community_poll_create":
            question=request.form.get("question","").strip()[:200]
            options=[request.form.get("option"+str(i),"").strip()[:60] for i in range(1,5)]
            options=[value for value in options if value]
            raw_channel=request.form.get("channel_id","").strip()
            try: duration=int(request.form.get("duration_minutes","1440"))
            except ValueError: raise ValueError("Poll duration must be a whole number of minutes.")
            if not question or len(options)<2 or len(options)>4 or not 1<=duration<=10080 or not raw_channel.isdigit():
                raise ValueError("Provide a question, two to four options, a valid channel and a duration from 1 to 10080 minutes.")
            if len({value.casefold() for value in options})!=len(options):
                raise ValueError("Poll options must be unique.")
            channel=guild.get_channel(int(raw_channel))
            if not isinstance(channel,__import__("discord").TextChannel):
                raise ValueError("Choose a text channel in this server.")
            perms=channel.permissions_for(guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                raise ValueError("Cinnamon needs View Channel, Send Messages and Embed Links in the poll channel.")
            async def create_dashboard_poll():
                view_class=state.get("PollView")
                embed_fn=state.get("_poll_embed")
                polls=state.setdefault("active_polls",{})
                if not callable(view_class) or not callable(embed_fn):
                    raise ValueError("Poll voting controls are unavailable.")
                record={"guild_id":int(gid),"channel_id":int(channel.id),"host_id":int(_tokens[sid]["user"]["id"]),"host_name":str(_tokens[sid]["user"].get("global_name") or _tokens[sid]["user"].get("username") or "Server staff"),"question":question,"options":options,"votes":{},"ends_at":time.time()+duration*60}
                message=await channel.send(embed=embed_fn(record),view=view_class(options),allowed_mentions=__import__("discord").AllowedMentions.none())
                polls[int(message.id)]=record
                if not await state["bd_save_data"]():
                    polls.pop(int(message.id),None)
                    try: await message.edit(content="This poll was cancelled because durable storage could not confirm it.",embed=None,view=view_class(options,disabled=True))
                    except __import__("discord").HTTPException: pass
                    raise ValueError("Could not durably save the poll; the post was disabled.")
                return message.id
            message_id=_run_bot(create_dashboard_poll())
            _audit(gid,actor,"Dashboard: community poll created",f"Poll message {message_id}; channel {channel.id}.")
            session["dashboard_notice"]="Poll created and published."
        elif action=="community_poll_close":
            raw_mid=request.form.get("message_id","").strip()
            if not raw_mid.isdigit(): raise ValueError("Choose a valid poll.")
            async def close_dashboard_poll():
                polls=state.setdefault("active_polls",{})
                mid=int(raw_mid)
                record=polls.get(mid)
                if not isinstance(record,dict) or int(record.get("guild_id",0))!=int(gid):
                    raise ValueError("That poll is no longer active in this server.")
                if not callable(state.get("finish_poll")):
                    raise ValueError("Poll closing controls are unavailable.")
                await state["finish_poll"](mid)
                if mid in polls:
                    raise ValueError("The poll could not be closed. Please retry.")
            _run_bot(close_dashboard_poll())
            _audit(gid,actor,"Dashboard: community poll closed",f"Poll message {raw_mid}.")
            session["dashboard_notice"]="Poll closed."
        elif action=="community_event_create":
            title=request.form.get("title","").strip()
            start_raw=request.form.get("start_at","").strip()
            description=request.form.get("description","").strip()[:1500]
            raw_channel=request.form.get("channel_id","").strip()
            if not title or len(title)>120 or not raw_channel.isdigit():
                raise ValueError("Provide an event title and a valid text channel.")
            try:
                start=__import__("datetime").datetime.fromisoformat(start_raw.replace("Z","+00:00"))
            except ValueError:
                raise ValueError("Use an ISO date/time including a timezone offset.")
            if start.tzinfo is None:
                raise ValueError("Event start time must include a timezone offset such as +05:30 or Z.")
            starts_at=int(start.astimezone(__import__("datetime").timezone.utc).timestamp())
            if starts_at<=int(time.time()) or starts_at>int(time.time())+366*86400:
                raise ValueError("Choose a future time within the next 366 days.")
            channel=guild.get_channel(int(raw_channel))
            if not isinstance(channel,__import__("discord").TextChannel):
                raise ValueError("Choose a text channel in this server.")
            perms=channel.permissions_for(guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                raise ValueError("Cinnamon needs View Channel, Send Messages and Embed Links in the event channel.")
            async def create_dashboard_event():
                advanced=state["advanced_features_data"]
                root=advanced.setdefault("cinnamon_community_interactions_v1",{})
                cfg=root.setdefault(str(gid),{})
                events=cfg.setdefault("events",{})
                view_class=state.get("CommunityEventView")
                if not callable(view_class): raise ValueError("Community event RSVP controls are unavailable.")
                event_id=__import__("uuid").uuid4().hex[:8]
                record={"creator_id":int(_tokens[sid]["user"]["id"]),"title":title,
                        "description":description,"starts_at":starts_at,"channel_id":int(channel.id),
                        "rsvps":{},"status":"scheduled","created_at":int(time.time()),
                        "reminders_sent":[]}
                embed=__import__("discord").Embed(title="📅 "+title,
                    description=(description+"\\n\\n" if description else "")+f"Starts <t:{starts_at}:F> (<t:{starts_at}:R>)",
                    color=0x91B5A2)
                message=await channel.send(embed=embed,view=view_class(gid,event_id),
                    allowed_mentions=__import__("discord").AllowedMentions.none())
                record["message_id"]=int(message.id)
                events[event_id]=record
                if not await state["bd_save_data"]():
                    events.pop(event_id,None)
                    try: await message.delete()
                    except __import__("discord").HTTPException: pass
                    raise ValueError("Could not durably save the event. Its post was removed.")
                return event_id
            event_id=_run_bot(create_dashboard_event())
            _audit(gid,actor,"Dashboard: community event created",f"Event {event_id}; channel {channel.id}; starts {starts_at}.")
            session["dashboard_notice"]="Event created and published. ID: "+event_id
        elif action=="community_event_cancel":
            event_id=request.form.get("event_id","").strip()
            if not event_id: raise ValueError("Choose an event to cancel.")
            async def cancel_dashboard_event():
                advanced=state["advanced_features_data"]
                cfg=(advanced.get("cinnamon_community_interactions_v1",{}) or {}).get(str(gid),{})
                record=(cfg.get("events",{}) or {}).get(event_id)
                if not isinstance(record,dict) or record.get("status")!="scheduled":
                    raise ValueError("That event is no longer scheduled.")
                before=__import__("copy").deepcopy(record)
                record["status"]="cancelled"
                record["cancelled_at"]=int(time.time())
                if not await state["bd_save_data"]():
                    record.clear();record.update(before)
                    raise ValueError("Could not save event cancellation.")
                channel=guild.get_channel(int(record.get("channel_id",0) or 0))
                view_class=state.get("CommunityEventView")
                if channel and callable(view_class):
                    try:
                        message=await channel.fetch_message(int(record.get("message_id",0)))
                        embed=__import__("discord").Embed(title="📅 "+str(record.get("title","Event")),
                            description="This event has been cancelled.",color=0xD97777)
                        await message.edit(embed=embed,view=view_class(gid,event_id,disabled=True))
                    except __import__("discord").HTTPException:
                        pass
            _run_bot(cancel_dashboard_event())
            _audit(gid,actor,"Dashboard: community event cancelled",f"Event {event_id}.")
            session["dashboard_notice"]="Event cancelled."
        elif action=="community_features_settings":
            def optional_text_channel(field):
                raw=request.form.get(field,"").strip()
                if not raw: return 0
                if not raw.isdigit(): raise ValueError("Choose a valid channel.")
                channel=guild.get_channel(int(raw))
                if not isinstance(channel,__import__("discord").TextChannel):
                    raise ValueError("Choose a text channel from this server.")
                return int(channel.id)
            suggestion_id=optional_text_channel("suggestion_channel_id")
            starboard_id=optional_text_channel("starboard_channel_id")
            confession_id=optional_text_channel("confession_channel_id")
            try:
                threshold=int(request.form.get("starboard_threshold","3"))
            except ValueError:
                raise ValueError("Starboard threshold must be a whole number.")
            emoji=request.form.get("starboard_emoji","⭐").strip()
            if not 2<=threshold<=20 or not 1<=len(emoji)<=20:
                raise ValueError("Use a starboard threshold from 2–20 and an emoji value of 1–20 characters.")
            async def apply_community_features():
                advanced=state["advanced_features_data"]
                board_root=advanced.setdefault("cinnamon_community_tools_v1",{})
                social_root=advanced.setdefault("cinnamon_community_interactions_v1",{})
                board=board_root.setdefault(str(gid),{})
                social=social_root.setdefault(str(gid),{})
                before_board=__import__("copy").deepcopy(board)
                before_social=__import__("copy").deepcopy(social)
                board.update({"suggestion_channel_id":suggestion_id,
                              "starboard_channel_id":starboard_id,
                              "starboard_threshold":threshold,
                              "starboard_emoji":emoji})
                social["confession_channel_id"]=confession_id
                if not await state["bd_save_data"]():
                    board.clear();board.update(before_board)
                    social.clear();social.update(before_social)
                    raise ValueError("The durable community settings save could not be verified. No changes were kept.")
            _run_bot(apply_community_features())
            _audit(gid,actor,"Dashboard: community features updated",
                   f"Suggestions={suggestion_id}; starboard={starboard_id}; threshold={threshold}; confessions={confession_id}.")
            session["dashboard_notice"]="Community boards and confession settings saved."
        elif action in {"welcome","goodbye"}:
            channel_id=request.form.get("channel_id","").strip(); message=request.form.get("message","")
            config_key="welcome_config" if action=="welcome" else "goodbye_config"
            if not channel_id: raise ValueError("Choose a channel or use Disable.")
            if not channel_id.isdigit() or not guild.get_channel(int(channel_id)): raise ValueError("Choose a valid text channel from this server.")
            if not message or len(message)>800: raise ValueError("Message must be between 1 and 800 characters.")
            try: message.format(member="member",server="server")
            except (KeyError,ValueError,IndexError): raise ValueError("Only {member} and {server} placeholders are supported; check the braces.")
            state[config_key][gid]={"channel_id":int(channel_id),"message":message}
            _save(); _audit(gid,actor,f"Dashboard: {action} message updated",f"Channel ID {channel_id}; message template changed.")
            session["dashboard_notice"]=f"{action.title()} message saved."
        elif action in {"welcome_disable","goodbye_disable"}:
            key="welcome_config" if action.startswith("welcome") else "goodbye_config"
            state[key].pop(gid,None); _save(); _audit(gid,actor,"Dashboard: messages disabled",action)
            session["dashboard_notice"]="Message setting disabled."
        elif action in {"ai_channel","log_channel"}:
            channel_id=request.form.get("channel_id","").strip(); key="ai_channels" if action=="ai_channel" else "log_channels"
            if channel_id and (not channel_id.isdigit() or not guild.get_channel(int(channel_id))): raise ValueError("Choose a valid channel from this server.")
            if channel_id: state[key][gid]=int(channel_id)
            else: state[key].pop(gid,None)
            _save(); _audit(gid,actor,"Dashboard: channel setting updated",f"{action}: {channel_id or 'disabled'}")
            session["dashboard_notice"]="Channel setting saved."
        elif action=="special_logs":
            value=request.form.get("economy_log","").strip()
            if value and (not value.isdigit() or not isinstance(guild.get_channel(int(value)),__import__("discord").TextChannel)): raise ValueError("Choose a valid text channel from this server.")
            if value: state["economy_log_channels"][gid]=int(value)
            else: state["economy_log_channels"].pop(gid,None)
            _save(); _audit(gid,actor,"Dashboard: economy log channel updated",value or "disabled")
            session["dashboard_notice"]="Economy log channel saved."
        elif action=="automod":
            raw=request.form.get("words",""); words=[]
            for line in raw.splitlines():
                word=line.strip()
                if word and word not in words: words.append(word[:100])
            if len(words)>50: raise ValueError("Use no more than 50 unique words or phrases.")
            threshold=int(request.form.get("mention_threshold","5"))
            if not 2<=threshold<=20: raise ValueError("Mention threshold must be between 2 and 20.")
            cfg=state["automod_config"].setdefault(gid,{"words":[],"spam":False,"mentions":False,"invites":False,"mention_threshold":5})
            cfg.update({"words":words,"spam":"spam" in request.form,"mentions":"mentions" in request.form,"invites":"invites" in request.form,"mention_threshold":threshold})
            if not (words or cfg["spam"] or cfg["mentions"] or cfg["invites"]): state["automod_config"].pop(gid,None)
            _save(); _audit(gid,actor,"Dashboard: AutoMod updated",f"{len(words)} word/phrase filters; spam={cfg['spam']}; mentions={cfg['mentions']}; invites={cfg['invites']}.")
            session["dashboard_notice"]="AutoMod settings saved."
        elif action=="antiraid":
            threshold=int(request.form.get("threshold","5")); window=int(request.form.get("window","10"))
            if not 2<=threshold<=100 or not 2<=window<=120: raise ValueError("Threshold must be 2–100 and time window 2–120 seconds.")
            cfg=state["antiraid_config"].setdefault(gid,{"enabled":False,"threshold":5,"window":10})
            cfg.update({"enabled":"enabled" in request.form,"threshold":threshold,"window":window})
            _save(); _audit(gid,actor,"Dashboard: anti-raid updated",f"Enabled={cfg['enabled']}, threshold={threshold}, window={window}s. Alert-only.")
            session["dashboard_notice"]="Anti-raid settings saved."
        elif action=="achievement_settings":
            enabled="enabled" in request.form; channel_id=request.form.get("channel_id","").strip()
            if channel_id and (not channel_id.isdigit() or not isinstance(guild.get_channel(int(channel_id)),__import__("discord").TextChannel)): raise ValueError("Choose a valid achievement log channel.")
            cfg=state.setdefault("achievement_config",{}).setdefault(gid,{})
            cfg["enabled"]=enabled
            if channel_id:
                cfg["log_channel"]=int(channel_id); state.setdefault("category_log_channels",{}).setdefault(gid,{})["achievements"]=int(channel_id)
            else: cfg.pop("log_channel",None)
            _save(); _audit(gid,actor,"Dashboard: achievement settings updated",f"enabled={enabled}; channel={channel_id or 'disabled'}"); session["dashboard_notice"]="Achievement settings saved."
        elif action=="quest_settings":
            role_id=request.form.get("role_id","").strip()
            role=guild.get_role(int(role_id)) if role_id.isdigit() else None
            if not role or role.is_default() or role.managed: raise ValueError("Choose a valid assignable Quest Master role.")
            state.setdefault("quest_config",{}).setdefault(gid,{})["quest_master_role"]=role.id
            _save(); _audit(gid,actor,"Dashboard: Quest Master role updated",role.name); session["dashboard_notice"]="Quest Master role saved."
        elif action=="xp_settings":
            per=int(request.form.get("xp_per_message","20")); channel_ids=request.form.getlist("channel_id")
            if not 1<=per<=1000: raise ValueError("XP per message must be between 1 and 1,000.")
            chosen=set()
            for raw in channel_ids:
                raw=raw.strip()
                if not raw.isdigit(): raise ValueError("Choose valid text channels for XP.")
                ch=guild.get_channel(int(raw))
                if not isinstance(ch,__import__("discord").TextChannel): raise ValueError("Choose valid text channels for XP.")
                chosen.add(ch.id)
            state.setdefault("xp_per_message",{})[gid]=per
            state.setdefault("xp_channels",{})[gid]=chosen
            _save(); _audit(gid,actor,"Dashboard: XP settings updated",f"XP/message={per}; channels={','.join(str(x) for x in sorted(chosen)) or 'none'}")
            session["dashboard_notice"]="XP settings saved with the selected channels."
        elif action=="xp_channel_remove":
            channel_id=request.form.get("channel_id","").strip()
            if not channel_id.isdigit(): raise ValueError("Invalid XP channel.")
            state.setdefault("xp_channels",{}).setdefault(gid,set()).discard(int(channel_id)); _save(); _audit(gid,actor,"Dashboard: XP channel removed",channel_id)
            session["dashboard_notice"]="XP channel removed."
        elif action=="category_log_set":
            category=request.form.get("log_category","").strip(); channel_id=request.form.get("channel_id","").strip()
            allowed={"moderation","economy","shop_items","ai","levels","achievements","quests","friendship","community","roles","setup","general","dashboard"}
            if category not in allowed: raise ValueError("Unknown log category.")
            if not channel_id.isdigit() or not isinstance(guild.get_channel(int(channel_id)),__import__("discord").TextChannel): raise ValueError("Choose a valid text channel.")
            cid=int(channel_id); state.setdefault("category_log_channels",{}).setdefault(gid,{})[category]=cid
            if category=="moderation": state.setdefault("log_channels",{})[gid]=cid
            if category=="economy": state.setdefault("economy_log_channels",{})[gid]=cid
            _save(); _audit(gid,actor,"Dashboard: log route updated",f"{category} -> {cid}"); session["dashboard_notice"]=f"{category.title()} log channel saved."
        elif action=="category_log_disable":
            category=request.form.get("log_category","").strip(); allowed={"moderation","economy","shop_items","ai","levels","achievements","quests","friendship","community","roles","setup","general","dashboard"}
            if category not in allowed: raise ValueError("Unknown log category.")
            state.setdefault("category_log_channels",{}).setdefault(gid,{}).pop(category,None)
            if category=="moderation": state.setdefault("log_channels",{}).pop(gid,None)
            if category=="economy": state.setdefault("economy_log_channels",{}).pop(gid,None)
            _save(); _audit(gid,actor,"Dashboard: log route disabled",category); session["dashboard_notice"]=f"{category.title()} log route disabled."
        elif action=="run_setup":
            result=_run_bot(_dashboard_setup(guild,state),timeout=120); _audit(gid,actor,"Dashboard: Cinnamon setup applied",str(result)); session["dashboard_notice"]=result
        elif action=="levelrole_add":
            level=int(request.form.get("level","0")); role_id=request.form.get("role_id","")
            role=guild.get_role(int(role_id)) if role_id.isdigit() else None
            if not 1<=level<=200 or not role or role.is_default() or role.managed: raise ValueError("Choose a valid level (1–100) and assignable role.")
            if not guild.me or role>=guild.me.top_role: raise ValueError("Move Cinnamon's highest role above the reward role first.")
            state["level_roles"].setdefault(gid,{})[level]=role.id
            _save(); _audit(gid,actor,"Dashboard: level reward added",f"Level {level}: {role.name}")
            send_log=state.get("send_log")
            if callable(send_log): _run_bot(send_log(gid,title="🎖️ Level role added",category="levels",fields=[("Action","Added"),("Level",str(level)),("Role",role.name),("Role ID",str(role.id)),("Dashboard actor",str(actor))]))
            session["dashboard_notice"]="Level reward saved."
        elif action=="levelrole_remove":
            level=int(request.form.get("level","0")); mapping=state["level_roles"].get(gid,{})
            role_id=mapping.pop(level,None)
            if role_id is None: raise ValueError("No reward is configured for that level.")
            role=guild.get_role(int(role_id))
            _save(); _audit(gid,actor,"Dashboard: level reward removed",f"Level {level}")
            send_log=state.get("send_log")
            if callable(send_log): _run_bot(send_log(gid,title="🎖️ Level role removed",category="levels",fields=[("Action","Removed"),("Level",str(level)),("Role",role.name if role else "Deleted role"),("Role ID",str(role_id)),("Dashboard actor",str(actor))]))
            session["dashboard_notice"]="Level reward removed. Members keep roles already earned."

        elif action == "shop_items_log_channel":
            raw = request.form.get("channel_id", "").strip()
            channel = guild.get_channel(int(raw)) if raw.isdigit() else None
            if raw and not isinstance(channel, __import__("discord").TextChannel):
                raise ValueError("Choose a valid text channel from this server.")
            if channel:
                perms = channel.permissions_for(guild.me) if guild.me else None
                if not perms or not (perms.view_channel and perms.send_messages and perms.embed_links):
                    raise ValueError("Cinnamon needs View Channel, Send Messages and Embed Links in that channel.")
            routes = state.setdefault("category_log_channels", {}).setdefault(gid, {})
            before = copy.deepcopy(routes)
            if channel:
                routes["shop_items"] = channel.id
            else:
                routes.pop("shop_items", None)
            def rollback_shop_log():
                routes.clear(); routes.update(before)
            _shop_workshop_commit(state, gid, actor, int(_tokens[sid]["user"]["id"]),
                                  "Log channel updated", f"Dedicated Shop & Items log channel: {channel.mention if channel else 'disabled'}.",
                                  rollback_shop_log)
            session["dashboard_notice"] = "Shop & Items log channel saved."

        elif action == "shop_catalog_restore":
            items = state["ECONOMY_ITEMS"]
            defaults = state.get("ECONOMY_BUILTIN_DEFAULTS", {})
            if not isinstance(defaults, dict) or not defaults:
                raise RuntimeError("The built-in catalogue source is unavailable.")
            before = copy.deepcopy(items)
            added = []
            for default_id, default_item in defaults.items():
                if default_id not in items and isinstance(default_item, dict):
                    items[default_id] = copy.deepcopy(default_item)
                    added.append(default_id)
            if not added:
                raise ValueError("No built-in items are missing from the catalogue.")
            def rollback_catalog_restore():
                items.clear(); items.update(before)
            _shop_workshop_commit(state, gid, actor, int(_tokens[sid]["user"]["id"]),
                "Built-in catalogue restored", f"Added {len(added)} missing built-in items: {', '.join(added[:80])}.",
                rollback_catalog_restore)
            session["dashboard_notice"] = f"Restored {len(added)} missing built-in items. Existing custom settings were preserved."

        elif action in {"shop_item_add", "shop_item_save"}:
            name = request.form.get("name", "").strip()
            item_id = request.form.get("item_id", "").strip().lower()
            items = state["ECONOMY_ITEMS"]
            if action=="shop_item_add" and not item_id:
                base=re.sub(r"[^a-z0-9_-]+","_",name.lower()).strip("_-")[:32] or "item"
                item_id=base; suffix=2
                while item_id in items:
                    item_id=f"{base[:35]}_{suffix}"; suffix+=1
            if not item_id or len(item_id)>40 or not all(c.isalnum() or c in "_-" for c in item_id):
                raise ValueError("Item name is required so Cinnamon can generate a unique item key.")
            if action=="shop_item_add" and item_id in items: raise ValueError("That item key already exists; choose another name.")
            if action=="shop_item_save" and item_id not in items: raise ValueError("That item no longer exists.")
            try:
                price = int(request.form.get("price", "0"))
                limit = int(request.form.get("max_per_person", "0"))
                sell_raw = request.form.get("sell_price", "").strip()
                sell_price = int(sell_raw) if sell_raw else None
                stock_quantity = int(request.form.get("stock_quantity", "0"))
                use_cooldown_seconds = int(request.form.get("use_cooldown_seconds", "0"))
                purchase_requirements = json.loads(request.form.get("purchase_requirements", "{}") or "{}")
                use_requirements = json.loads(request.form.get("use_requirements", "{}") or "{}")
                item_actions = json.loads(request.form.get("item_actions", "[]") or "[]")
                random_outcomes = json.loads(request.form.get("random_outcomes", "[]") or "[]")
            except (ValueError, TypeError):
                raise ValueError("Check numeric values and make sure the requirements/actions/outcomes fields contain valid JSON.")
            if (not name or len(name) > 80 or not 1 <= price <= 10000000
                    or not 0 <= limit <= 999999
                    or (sell_price is not None and not 0 <= sell_price <= 10000000)
                    or not 0 <= stock_quantity <= 100000000
                    or not 0 <= use_cooldown_seconds <= 31536000):
                raise ValueError("Check the name, prices, per-member limit, stock (0–100,000,000) and cooldown (0–31,536,000 seconds).")
            if not isinstance(purchase_requirements, dict) or not isinstance(use_requirements, dict):
                raise ValueError("Purchase and use requirements must each be a JSON object.")
            if not isinstance(item_actions, list) or not isinstance(random_outcomes, list):
                raise ValueError("Actions and random outcomes must each be JSON arrays.")
            allowed_triggers = {"bought", "used", "both", "bought_or_used"}
            allowed_action_types = {"give_catnip", "give_item", "send_message", "reply"}
            for requirement in (purchase_requirements, use_requirements):
                try:
                    balance_min = int(requirement.get("balance_min", 0) or 0)
                except (TypeError, ValueError):
                    raise ValueError("Requirement balance_min must be a whole Catnip amount.")
                if not 0 <= balance_min <= 1000000000:
                    raise ValueError("Requirement balance_min must be between 0 and 1,000,000,000.")
                roles_cfg = requirement.get("roles", {})
                if roles_cfg:
                    if not isinstance(roles_cfg, dict) or roles_cfg.get("mode", "all") not in {"all", "any", "none"}:
                        raise ValueError("Role requirements need mode all, any or none.")
                    role_ids = roles_cfg.get("ids", [])
                    if not isinstance(role_ids, list) or len(role_ids) > 20:
                        raise ValueError("Role requirements support up to 20 role IDs.")
                    for role_id in role_ids:
                        role = guild.get_role(int(role_id)) if str(role_id).isdigit() else None
                        if not role or role.is_default() or role.managed:
                            raise ValueError("A requirement role is invalid or no longer belongs to this server.")
                items_cfg = requirement.get("items", {})
                if items_cfg:
                    if not isinstance(items_cfg, dict) or items_cfg.get("mode", "all") not in {"all", "any", "none"}:
                        raise ValueError("Item requirements need mode all, any or none.")
                    entries = items_cfg.get("entries", {})
                    if not isinstance(entries, dict) or len(entries) > 20:
                        raise ValueError("Item requirements support up to 20 item entries.")
                    for required_id, required_qty in entries.items():
                        try:
                            required_qty = int(required_qty)
                        except (TypeError, ValueError):
                            raise ValueError("Required item quantities must be whole numbers.")
                        if required_id not in items or not 1 <= required_qty <= 999:
                            raise ValueError(f"Requirement item {required_id} must exist and use quantity 1–999.")
            def validate_action(action_config, require_trigger=True):
                if (not isinstance(action_config, dict)
                        or (require_trigger and str(action_config.get("trigger", "both")).lower() not in allowed_triggers)
                        or str(action_config.get("type", "")).lower() not in allowed_action_types):
                    raise ValueError("Each action needs a supported type and trigger (bought, used or both).")
                kind = str(action_config.get("type", "")).lower()
                if kind == "give_catnip":
                    try: amount = int(action_config.get("amount", 0))
                    except (TypeError, ValueError): raise ValueError("Give Catnip actions need a whole-number amount.")
                    if not 1 <= amount <= 10000000: raise ValueError("Give Catnip amount must be 1–10,000,000.")
                elif kind == "give_item":
                    reward_id = str(action_config.get("item_id", ""))
                    try: amount = int(action_config.get("amount", 1))
                    except (TypeError, ValueError): raise ValueError("Give item actions need a whole-number amount.")
                    if reward_id not in items or not 1 <= amount <= 999:
                        raise ValueError("Give item actions need an existing item and quantity 1–999.")
                elif kind in {"send_message", "reply"}:
                    message = str(action_config.get("message", "")).strip()
                    if not message or len(message) > 1800:
                        raise ValueError("Message actions need text between 1 and 1,800 characters.")
            for action_config in item_actions:
                validate_action(action_config)
            trigger_totals = {"bought": 0.0, "used": 0.0}
            for outcome in random_outcomes:
                if (not isinstance(outcome, dict)
                        or str(outcome.get("trigger", "both")).lower() not in allowed_triggers
                        or not isinstance(outcome.get("actions", []), list)):
                    raise ValueError("Each random outcome needs a supported trigger and an actions array.")
                try:
                    weight = float(outcome.get("weight", 0))
                except (TypeError, ValueError):
                    raise ValueError("Random outcome weights must be numeric.")
                if not 0 < weight <= 100:
                    raise ValueError("Each random outcome weight must be above 0 and at most 100.")
                trigger = str(outcome.get("trigger", "both")).lower()
                if trigger in {"bought", "both", "bought_or_used"}:
                    trigger_totals["bought"] += weight
                if trigger in {"used", "both", "bought_or_used"}:
                    trigger_totals["used"] += weight
                for action_config in outcome.get("actions", []):
                    validate_action(action_config, require_trigger=False)
            for trigger, total in trigger_totals.items():
                if total and abs(total - 100.0) > 0.001:
                    raise ValueError(f"Random outcome weights for {trigger} must total 100%.")
            expires_at = request.form.get("expires_at", "").strip()
            if expires_at:
                try:
                    parsed_expiry = dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if parsed_expiry.tzinfo is None:
                        parsed_expiry = parsed_expiry.replace(tzinfo=dt.timezone.utc)
                    expires_at = parsed_expiry.astimezone(dt.timezone.utc).isoformat()
                except ValueError:
                    raise ValueError("Expiry must be a valid ISO date/time, for example 2026-12-31T23:59:00+00:00.")
            before = copy.deepcopy(items)
            updated = dict(items.get(item_id, {}))
            updated.update({
                "name": name, "price": price,
                "category": request.form.get("category", "General").strip()[:40] or "General",
                "sell_price": sell_price,
                "sellable": "sellable" in request.form,
                "emoji": request.form.get("emoji", "🐾")[:8] or "🐾",
                "description": request.form.get("description", "")[:300],
                "max_per_person": limit,
                "shop_enabled": "shop_enabled" in request.form,
                "craftable": "craftable" in request.form,
                "stock_unlimited": "stock_unlimited" in request.form,
                "stock_quantity": stock_quantity,
                "expires_at": expires_at,
                "usable": "usable" in request.form,
                "reusable": "reusable" in request.form,
                "use_cooldown_seconds": use_cooldown_seconds,
                "purchase_requirements": purchase_requirements,
                "use_requirements": use_requirements,
                "actions": item_actions,
                "random_outcomes": random_outcomes,
            })
            items[item_id] = updated
            def rollback_shop_item():
                items.clear(); items.update(before)
            _shop_workshop_commit(state, gid, actor, int(_tokens[sid]["user"]["id"]),
                "Item created" if action == "shop_item_add" else "Item edited",
                f"{item_id}: {name}; price={price} Catnip; shop_enabled={updated['shop_enabled']}; craftable={updated['craftable']}; "
                f"stock={'unlimited' if updated['stock_unlimited'] else updated['stock_quantity']}; expires_at={updated['expires_at'] or 'never'}; "
                f"usable={updated['usable']}; reusable={updated['reusable']}; use_cooldown_seconds={updated['use_cooldown_seconds']}; "
                f"purchase_requirements={len(updated['purchase_requirements'])} sections; use_requirements={len(updated['use_requirements'])} sections; "
                f"actions={len(updated['actions'])}; random_outcomes={len(updated['random_outcomes'])}.",
                rollback_shop_item)
            session["dashboard_notice"] = "Shop item saved."
        elif action == "shop_item_disable":
            item_id = request.form.get("item_id", "").strip()
            items = state["ECONOMY_ITEMS"]
            if item_id not in items:
                raise ValueError("That item no longer exists.")
            before = copy.deepcopy(items[item_id])
            items[item_id]["shop_enabled"] = False
            def rollback_shop_item_disable():
                items[item_id] = before
            _shop_workshop_commit(state, gid, actor, int(_tokens[sid]["user"]["id"]),
                "Item removed from shop", f"{item_id} is hidden from purchases; inventory, recipe and Mystery Box references remain intact.",
                rollback_shop_item_disable)
            session["dashboard_notice"] = "Item hidden from the shop. Existing inventory and recipes were preserved."
        elif action == "shop_recipe_save":
            recipe_id = request.form.get("recipe_id", "").strip().lower()
            name = request.form.get("name", "").strip()
            if not recipe_id:
                base=re.sub(r"[^a-z0-9_-]+","_",name.lower()).strip("_-")[:32] or "recipe"
                recipe_id=base; suffix=2
                custom_recipe_ids=(state.get("advanced_features_data",{}).get("custom_crafting_recipes_v1",{}) or {})
                while recipe_id in (state.get("CRAFTING_RECIPES",{}) or {}) or recipe_id in custom_recipe_ids:
                    recipe_id=f"{base[:35]}_{suffix}"; suffix+=1
            if len(recipe_id)>40 or not all(c.isalnum() or c in "_-" for c in recipe_id) or recipe_id=="repair_rod":
                raise ValueError("Recipe ID must use letters, numbers, _ or - (max 40); that ID is reserved.")
            output = request.form.get("output", "").strip()
            emoji = request.form.get("emoji", "🧪")[:8] or "🧪"
            description = request.form.get("description", "")[:300]
            items = state["ECONOMY_ITEMS"]
            recipes = state.get("CRAFTING_RECIPES", {})
            if not name or len(name) > 80 or output not in items:
                raise ValueError("Choose a valid recipe name and output item.")
            ingredients = {}
            selected_ingredient_ids=request.form.getlist("ingredient_item_ids")
            if selected_ingredient_ids:
                for ingredient_id in dict.fromkeys(selected_ingredient_ids):
                    if ingredient_id not in items or not isinstance(items.get(ingredient_id),dict):
                        raise ValueError("One of the selected recipe ingredients no longer exists.")
                    try: quantity=int(request.form.get("ingredient_quantity_"+ingredient_id,"1") or 1)
                    except ValueError: raise ValueError(f"Invalid quantity for {items[ingredient_id].get('name',ingredient_id)}.")
                    if ingredient_id==output or not 1<=quantity<=999: raise ValueError("Choose ingredients different from the output and use quantities 1–999.")
                    ingredients[ingredient_id]=quantity
            else:
                # Backward compatibility for older clients posting name:quantity lines.
                for line in request.form.get("ingredients", "").splitlines():
                    line=line.strip()
                    if not line: continue
                    parts=line.split(":",1)
                    if len(parts)!=2: raise ValueError("Choose ingredients from the item list.")
                    ingredient_ref=parts[0].strip().lower()
                    try: quantity=int(parts[1].strip())
                    except ValueError: raise ValueError(f"Invalid quantity for ingredient {ingredient_ref}.")
                    ingredient_id=ingredient_ref if ingredient_ref in items else ""
                    if not ingredient_id:
                        matches=[str(k) for k,v in items.items() if isinstance(v,dict) and str(v.get("name","")).strip().casefold()==ingredient_ref.casefold()]
                        if len(matches)==1: ingredient_id=matches[0]
                    if not ingredient_id or ingredient_id==output or not 1<=quantity<=999: raise ValueError(f"Choose a valid ingredient and quantity for {parts[0].strip()}.")
                    ingredients[ingredient_id]=quantity
            if not ingredients or len(ingredients) > 20:
                raise ValueError("A recipe needs 1–20 unique ingredients.")
            recipe = {"name": name, "emoji": emoji, "output": output, "ingredients": ingredients, "description": description}
            advanced = state["advanced_features_data"]
            custom_before = copy.deepcopy(advanced.get("custom_crafting_recipes_v1", {}))
            disabled_before = copy.deepcopy(advanced.get("disabled_crafting_recipes_v1", []))
            recipes_before = copy.deepcopy(recipes)
            before_output_flag = bool(items[output].get("craftable", False))
            advanced.setdefault("custom_crafting_recipes_v1", {})[recipe_id] = recipe
            disabled = advanced.setdefault("disabled_crafting_recipes_v1", [])
            advanced["disabled_crafting_recipes_v1"] = [x for x in disabled if str(x) != recipe_id]
            recipes[recipe_id] = recipe
            items[output]["craftable"] = True
            def rollback_recipe_save():
                recipes.clear(); recipes.update(recipes_before)
                advanced["custom_crafting_recipes_v1"] = custom_before
                advanced["disabled_crafting_recipes_v1"] = disabled_before
                if output in items:
                    items[output]["craftable"] = before_output_flag
            _shop_workshop_commit(state, gid, actor, int(_tokens[sid]["user"]["id"]),
                "Crafting recipe saved", f"{recipe_id}: {name}; output={output}; ingredients={ingredients}.",
                rollback_recipe_save)
            session["dashboard_notice"] = "Crafting recipe saved. The output item is now marked craftable."
        elif action == "shop_recipe_remove":
            recipe_id = request.form.get("recipe_id", "").strip().lower()
            recipes = state.get("CRAFTING_RECIPES", {})
            if recipe_id not in recipes:
                raise ValueError("That active recipe no longer exists.")
            advanced = state["advanced_features_data"]
            recipes_before = copy.deepcopy(recipes)
            custom_before = copy.deepcopy(advanced.get("custom_crafting_recipes_v1", {}))
            disabled_before = copy.deepcopy(advanced.get("disabled_crafting_recipes_v1", []))
            removed = recipes.pop(recipe_id)
            advanced.setdefault("custom_crafting_recipes_v1", {}).pop(recipe_id, None)
            disabled = advanced.setdefault("disabled_crafting_recipes_v1", [])
            if recipe_id not in disabled:
                disabled.append(recipe_id)
            def rollback_recipe_remove():
                recipes.clear(); recipes.update(recipes_before)
                advanced["custom_crafting_recipes_v1"] = custom_before
                advanced["disabled_crafting_recipes_v1"] = disabled_before
            _shop_workshop_commit(state, gid, actor, int(_tokens[sid]["user"]["id"]),
                "Crafting recipe disabled", f"{recipe_id}: {removed.get('name', recipe_id)}.",
                rollback_recipe_remove)
            session["dashboard_notice"] = "Crafting recipe disabled. Existing items and inventories were preserved."

        elif action == "shop_box_distribution":
            tier = request.form.get("tier", "").strip().lower()
            tiers = state.get("BOX_TIERS", {})
            if tier not in tiers:
                raise ValueError("Choose a valid Mystery Box tier.")
            if tier == "common":
                distribution_key = "category_weights"
                defaults = {"catnip_small":29,"item_common":28,"xp":14,"material":12,"catnip_big":9,"item_rare":6,"rare_crown":2}
            else:
                distribution_key = "outcome_weights"
                defaults = {"catnip":55,"items":35,"materials":10}
            configured = {}
            for outcome_name in defaults:
                try:
                    weight = int(request.form.get("weight_" + outcome_name, str(defaults[outcome_name])))
                except ValueError:
                    raise ValueError("Every outcome weight must be a whole number.")
                if not 0 <= weight <= 1000000:
                    raise ValueError("Outcome weights must be between 0 and 1,000,000.")
                configured[outcome_name] = weight
            if not any(configured.values()):
                raise ValueError("At least one outcome weight must be above zero.")
            advanced = state["advanced_features_data"]
            box_root = advanced.setdefault("custom_box_rewards", {})
            before = copy.deepcopy(box_root)
            cfg = box_root.setdefault(f"{gid}:{tier}", {})
            cfg[distribution_key] = configured
            def rollback_box_distribution():
                box_root.clear(); box_root.update(before)
            _shop_workshop_commit(state, gid, actor, int(_tokens[sid]["user"]["id"]),
                "Mystery Box outcome weights updated", f"{tier.title()} outcome weights: {configured}.",
                rollback_box_distribution)
            session["dashboard_notice"] = f"{tier.title()} Mystery Box outcome weights saved."

        elif action in {"shop_box_reward_add", "shop_box_reward_remove", "shop_box_weight"}:
            tier = request.form.get("tier", "").strip().lower()
            pool_kind = request.form.get("pool_kind", "").strip().lower()
            item_id = request.form.get("item_id", "").strip().lower()
            tiers = state.get("BOX_TIERS", {})
            items = state.get("ECONOMY_ITEMS", {})
            if (tier not in tiers or pool_kind not in {"items", "materials", "rare_items"}
                    or (pool_kind == "rare_items" and tier != "common") or item_id not in items):
                raise ValueError("Choose a valid Mystery Box tier, reward pool and existing catalogue item.")
            advanced = state["advanced_features_data"]
            box_root = advanced.setdefault("custom_box_rewards", {})
            key = f"{gid}:{tier}"
            before = copy.deepcopy(box_root)
            cfg = box_root.setdefault(key, {"items": [], "materials": [], "weights": {}, "disabled_items": [], "disabled_materials": [], "disabled_rare_items": []})
            cfg.setdefault("items", []); cfg.setdefault("materials", []); cfg.setdefault("weights", {})
            cfg.setdefault("disabled_items", []); cfg.setdefault("disabled_materials", []); cfg.setdefault("disabled_rare_items", [])
            base_source = state.get("BOX_RARE_ITEM_POOL", []) if pool_kind == "rare_items" else tiers[tier].get(pool_kind, [])
            base_ids = [str(x) for x in base_source]
            custom_ids = cfg[pool_kind]
            disabled_key = f"disabled_{pool_kind}"
            if action == "shop_box_reward_add":
                try:
                    weight = int(request.form.get("weight", "1"))
                except ValueError:
                    raise ValueError("Reward weight must be a whole number.")
                if not 1 <= weight <= 1000000:
                    raise ValueError("Reward weight must be between 1 and 1,000,000.")
                cfg[disabled_key] = [x for x in cfg[disabled_key] if str(x) != item_id]
                if item_id not in base_ids and item_id not in custom_ids:
                    custom_ids.append(item_id)
                cfg["weights"][item_id] = weight
                label = "Reward added"
                details = f"{tier.title()} {pool_kind}: added {item_id} with relative weight {weight}."
            elif action == "shop_box_weight":
                try:
                    weight = int(request.form.get("weight", "0"))
                except ValueError:
                    raise ValueError("Reward weight must be a whole number.")
                active = item_id in base_ids or item_id in custom_ids
                if not active or not 1 <= weight <= 1000000:
                    raise ValueError("That reward must be active and its weight must be 1–1,000,000.")
                cfg["weights"][item_id] = weight
                label = "Reward weight updated"
                details = f"{tier.title()} {pool_kind}: {item_id} weight set to {weight}."
            else:
                if item_id not in base_ids and item_id not in custom_ids:
                    raise ValueError("That reward is not in this box pool.")
                if item_id in base_ids and item_id not in cfg[disabled_key]:
                    cfg[disabled_key].append(item_id)
                cfg[pool_kind] = [x for x in custom_ids if str(x) != item_id]
                cfg["weights"].pop(item_id, None)
                label = "Reward removed"
                details = f"{tier.title()} {pool_kind}: removed {item_id} from the active pool."
            def rollback_box_pool():
                box_root.clear(); box_root.update(before)
            _shop_workshop_commit(state, gid, actor, int(_tokens[sid]["user"]["id"]),
                label, details, rollback_box_pool)
            session["dashboard_notice"] = details

        elif action in {"economy_item_add","economy_item_save"}:
            item_id=request.form.get("item_id","").strip().lower(); items=state["ECONOMY_ITEMS"]
            if not item_id or len(item_id)>40 or not all(c.isalnum() or c in "_-" for c in item_id): raise ValueError("Item ID must use letters, numbers, _ or - (max 40).")
            if action=="economy_item_add" and item_id in items: raise ValueError("That item ID already exists.")
            if action=="economy_item_save" and item_id not in items: raise ValueError("That shop item no longer exists.")
            name=request.form.get("name","").strip(); price=int(request.form.get("price","0")); limit=int(request.form.get("max_per_person","0"))
            if not name or len(name)>80 or not 1<=price<=10000000 or not 0<=limit<=999999: raise ValueError("Check item name, price (1–10,000,000) and limit (0–999,999).")
            items[item_id]={"name":name,"price":price,"emoji":request.form.get("emoji","🐾")[:8] or "🐾","description":request.form.get("description","")[:300],"max_per_person":limit,"shop_enabled":True}
            _save(); _audit(gid,actor,"Dashboard: shop item saved",f"{item_id}: {name}, {price} Catnip")
            send_log=state.get("send_log")
            if callable(send_log): _run_bot(send_log(gid,title="🛒 Shop item added" if action=="economy_item_add" else "✏️ Shop item edited",category="economy",fields=[("Action","Added" if action=="economy_item_add" else "Edited"),("Admin",str(actor)),("Item ID",item_id),("Name",name),("Price",str(price)),("Emoji",items[item_id]["emoji"]),("Description",items[item_id]["description"]),("Per-person limit",str(limit)),("Shop enabled","true"),("Catalog scope","Global shared shop")]))
            session["dashboard_notice"]="Shop item saved."
        elif action=="economy_item_remove":
            item_id=request.form.get("item_id","").strip()
            if item_id not in state["ECONOMY_ITEMS"]: raise ValueError("That shop item no longer exists.")
            removed_item=state["ECONOMY_ITEMS"].pop(item_id)
            _save(); _audit(gid,actor,"Dashboard: shop item removed",f"Removed catalog item {item_id}; existing member inventories were preserved.")
            send_log=state.get("send_log")
            if callable(send_log): _run_bot(send_log(gid,title="🗑️ Shop item removed",category="economy",fields=[("Action","Removed"),("Admin",str(actor)),("Item ID",item_id),("Name",removed_item.get("name",item_id)),("Price",str(removed_item.get("price",1))),("Emoji",removed_item.get("emoji","🐾")),("Description",removed_item.get("description","")[:300]),("Per-person limit",str(removed_item.get("max_per_person",0))),("Catalog scope","Global shared shop")]))
            session["dashboard_notice"]="Shop item removed. Existing inventories were preserved."
        elif action=="economy_income_add":
            role_id=request.form.get("role_id","").strip(); role=guild.get_role(int(role_id)) if role_id.isdigit() else None
            try: amount=int(request.form.get("amount","0")); interval=int(request.form.get("interval","0"))
            except ValueError: raise ValueError("Income amount and interval must be whole numbers.")
            unit=request.form.get("unit","minute"); multipliers={"minute":60,"hour":3600,"day":86400,"week":604800}
            if not role or role.is_default() or role.managed: raise ValueError("Choose a valid, assignable server role.")
            if not 1<=amount<=1000000 or not 1<=interval<=1000 or unit not in multipliers: raise ValueError("Use 1–1,000,000 Catnip and an interval from 1–1,000 minutes/hours/days/weeks.")
            income_cfg={"amount":amount,"cooldown":interval*multipliers[unit],"interval":interval,"unit":unit}
            state.setdefault("economy_income_roles",{}).setdefault(gid,{})[role.id]=income_cfg
            _save(); _audit(gid,actor,"Dashboard: role income saved",f"Role {role.name} ({role.id}); {amount} Catnip every {interval} {unit}(s).")
            send_log=state.get("send_log")
            if callable(send_log): _run_bot(send_log(gid,title="💰 Role income added/updated",category="economy",fields=[("Action","Added/Updated"),("Admin",str(actor)),("Role",role.name),("Role ID",str(role.id)),("Amount",str(amount)),("Interval",str(interval)),("Unit",unit),("Cooldown seconds",str(income_cfg["cooldown"]))]))
            session["dashboard_notice"]=f"Role income saved for {role.name}."
        elif action=="economy_income_remove":
            role_id=request.form.get("role_id","").strip(); cfg=state.setdefault("economy_income_roles",{}).setdefault(gid,{})
            removed_income=cfg.pop(int(role_id),None) if role_id.isdigit() else None
            if removed_income is None: raise ValueError("That role income rule no longer exists.")
            role=guild.get_role(int(role_id))
            _save(); _audit(gid,actor,"Dashboard: role income removed",f"Role ID {role_id}.")
            if not role_id.isdigit() or cfg.pop(int(role_id),None) is None: raise ValueError("That role income rule no longer exists.")
            _save(); _audit(gid,actor,"Dashboard: role income removed",f"Role ID {role_id}.")
            session["dashboard_notice"]="Role income rule removed."
        elif action in {"giveaway_create","giveaway_edit","giveaway_draft_save","giveaway_draft_update"}:
            prize=request.form.get("prize","").strip()
            try: winners=int(request.form.get("winners","1")); duration=int(request.form.get("duration_minutes","60"))
            except ValueError: raise ValueError("Winner count and duration must be whole numbers.")
            if not prize or len(prize)>200 or not 1<=winners<=100 or not 1<=duration<=525600:
                raise ValueError("Check prize (1–200 chars), winners (1–100), and duration (1–525,600 minutes).")
            validate=state.get("validate_giveaway_config")
            if not callable(validate): raise RuntimeError("Giveaway settings validation is not available.")
            role_text=lambda field: "\n".join(request.form.getlist(field))
            bonus_ids=request.form.getlist("bonus_role_ids")
            bonus_template_name=request.form.get("bonus_role_template","").strip()
            saved_bonus_templates=(state.get("giveaway_bonus_role_templates",{}) or {}).get(gid,(state.get("giveaway_bonus_role_templates",{}) or {}).get(str(gid),{})) or {}
            bonus_pairs={}
            if bonus_template_name:
                saved_bonus=saved_bonus_templates.get(bonus_template_name)
                if not isinstance(saved_bonus,dict): raise ValueError("That extra-entry template no longer exists.")
                bonus_pairs.update(saved_bonus.get("bonus_roles",{}) or {})
            for rid in dict.fromkeys(bonus_ids):
                if str(rid).isdigit(): bonus_pairs[str(rid)]=request.form.get("bonus_role_count_"+str(rid),"1")
            bonus_text="\n".join(f"<@&{rid}>:{count}" for rid,count in bonus_pairs.items())
            config=validate(guild, bonus_roles=bonus_text,
                required_roles=role_text("required_roles"), bypass_roles=role_text("bypass_roles"),
                blacklisted_roles=role_text("blacklisted_roles"),
                min_account_age_days=request.form.get("min_account_age_days","0"),
                min_server_age_days=request.form.get("min_server_age_days","0"),
                winner_role_id=request.form.get("winner_role_id",""),
                winner_role_minutes=request.form.get("winner_role_minutes","0"),
                winner_thread_minutes=request.form.get("winner_thread_minutes","0"),
                embed_color=request.form.get("embed_color","FEE75C"), entry_emoji=request.form.get("entry_emoji","🎉"),
                reaction_entries="reaction_entries" in request.form)
            config.update({"claim_minutes":int(request.form.get("claim_minutes","0") or 0),"entry_message":request.form.get("entry_message","")[:300],
                "leave_message":request.form.get("leave_message","")[:300],
                "denied_message":request.form.get("denied_message","")[:300],
                "embed_title":request.form.get("embed_title","")[:256],
                "embed_description":request.form.get("embed_description","")[:3500]})
            if action=="giveaway_draft_update":
                draft_id=request.form.get("draft_id",""); drafts=state.setdefault("giveaway_drafts",{}).setdefault(gid,{})
                draft=drafts.get(draft_id)
                if not draft or int(draft.get("guild_id",0))!=gid: raise ValueError("That giveaway draft was not found.")
                draft.update({"prize":prize,"winners":winners,"duration_minutes":duration,"config":config,"updated_at":time.time()})
                _save(); _audit(gid,actor,"Dashboard: giveaway draft edited",f"Draft {draft_id}; prize {prize}; {winners} winner(s).")
                session["dashboard_notice"]="Draft updated. Discord has not been changed."
            elif action=="giveaway_draft_save":
                channel_id=request.form.get("channel_id","").strip(); channel=guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
                if not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Choose a valid text channel in this server.")
                drafts=state.setdefault("giveaway_drafts",{}).setdefault(gid,{})
                draft_id=secrets.token_urlsafe(8)
                drafts[draft_id]={"guild_id":gid,"channel_id":channel.id,"host_id":int(_tokens[sid]["user"]["id"]),"prize":prize,"winners":winners,"duration_minutes":duration,"config":config,"created_at":time.time()}
                _save(); _audit(gid,actor,"Dashboard: giveaway draft saved",f"Draft {draft_id}; prize {prize}; {winners} winner(s); {duration} minutes.")
                session["dashboard_notice"]="Draft saved; it has not been posted to Discord."
            elif action=="giveaway_create":
                raise ValueError("Use Save draft and publish from the saved draft preview.")
            else:
                raw_mid=request.form.get("message_id","0")
                if not raw_mid.isdigit(): raise ValueError("Invalid giveaway message ID.")
                mid=int(raw_mid); gw=state["active_giveaways"].get(mid)
                if not gw or int(gw.get("guild_id",0))!=gid: raise ValueError("Active giveaway not found in this server.")
                channel=_bot.get_channel(int(gw.get("channel_id",0)))
                if channel is None: raise ValueError("Giveaway channel is unavailable.")
                async def update_giveaway():
                    msg=await channel.fetch_message(mid)
                    gw.update(config); gw.update({"prize":prize,"winners":winners,"ends_at":time.time()+duration*60})
                    await msg.edit(embed=state["giveaway_embed"](gw),view=state["giveaway_view"](emoji=gw.get("entry_emoji")))
                    await state["bd_save_data"]()
                _run_bot(update_giveaway())
                _audit(gid,actor,"Dashboard: giveaway edited",f"Message {mid}; prize, duration, entry rules and embed settings updated.")
                session["dashboard_notice"]="Giveaway updated. Existing entrants were retained; entry rules apply to future entries and final eligibility."
        elif action=="giveaway_draft_publish":
            draft_id=request.form.get("draft_id",""); drafts=state.setdefault("giveaway_drafts",{}).setdefault(gid,{})
            draft=drafts.get(draft_id)
            if not draft or int(draft.get("guild_id",0))!=gid: raise ValueError("That giveaway draft was not found.")
            channel=guild.get_channel(int(draft.get("channel_id",0)))
            if not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Draft channel is unavailable.")
            mid=_run_bot(state["create_giveaway"](guild_id=gid,channel_id=channel.id,host_id=int(draft.get("host_id",_tokens[sid]["user"]["id"])),prize=draft["prize"],winners=int(draft["winners"]),duration_minutes=int(draft["duration_minutes"]),config=draft.get("config",{})))
            drafts.pop(draft_id,None); _save(); _audit(gid,actor,"Dashboard: giveaway draft published",f"Draft {draft_id}; message {mid}")
            session["dashboard_notice"]="Draft published; giveaway is live in Discord."
        elif action=="giveaway_draft_delete":
            draft_id=request.form.get("draft_id",""); drafts=state.setdefault("giveaway_drafts",{}).setdefault(gid,{})
            draft=drafts.get(draft_id)
            if not draft or int(draft.get("guild_id",0))!=gid: raise ValueError("That giveaway draft was not found.")
            drafts.pop(draft_id,None); _save(); _audit(gid,actor,"Dashboard: giveaway draft discarded",draft_id)
            session["dashboard_notice"]="Draft discarded."
        elif action=="giveaway_template_save":
            raw_mid=request.form.get("message_id","0"); name=request.form.get("template_name","").strip()
            if not raw_mid.isdigit() or not name or len(name)>40: raise ValueError("Choose an active giveaway and a template name (1–40 characters).")
            gw=state.get("active_giveaways",{}).get(int(raw_mid))
            if not gw or int(gw.get("guild_id",0))!=gid: raise ValueError("Active giveaway not found in this server.")
            templates=state.setdefault("giveaway_templates",{}).setdefault(gid,{})
            template_key=name.lower()
            templates[template_key]={k:v for k,v in gw.items() if k not in {"guild_id","channel_id","host_id","ends_at","entrants","winner_ids","finished_at","eligible_entrants"}}
            _save(); _audit(gid,actor,"Dashboard: giveaway template saved",f"Template {name}; prize {gw.get('prize','Giveaway')}")
            session["dashboard_notice"]=f"Saved giveaway template '{name}'."
        elif action=="giveaway_bonus_template_save":
            raw_mid=request.form.get("message_id","0"); name=request.form.get("template_name","").strip()
            if not raw_mid.isdigit() or not name or len(name)>40: raise ValueError("Choose an active giveaway and a template name (1–40 characters).")
            gw=state.get("active_giveaways",{}).get(int(raw_mid))
            if not gw or int(gw.get("guild_id",0))!=gid: raise ValueError("Active giveaway not found in this server.")
            bonus=dict(gw.get("bonus_roles",{}) or {})
            if not bonus: raise ValueError("This giveaway has no extra-entry role rules to save.")
            templates=state.setdefault("giveaway_bonus_role_templates",{}).setdefault(gid,{})
            templates[name]= {"bonus_roles":{str(k):max(1,min(20,int(v))) for k,v in bonus.items() if str(k).isdigit()}}
            _save(); _audit(gid,actor,"Dashboard: extra-entry template saved",f"Template {name}; {len(bonus)} role rules.")
            session["dashboard_notice"]=f"Saved extra-entry template '{name}'. It can now be selected for new giveaways."
        elif action=="giveaway_template_delete":
            name=request.form.get("template_name","").strip().lower(); templates=state.setdefault("giveaway_templates",{}).setdefault(gid,{})
            if not name or templates.pop(name,None) is None: raise ValueError("That giveaway template no longer exists.")
            _save(); _audit(gid,actor,"Dashboard: giveaway template deleted",name)
            session["dashboard_notice"]="Giveaway template deleted."
        elif action=="giveaway_repeat_create":
            channel_id=request.form.get("channel_id","").strip(); channel=guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
            prize=request.form.get("prize","").strip()
            try: winners=int(request.form.get("winners","1")); duration=int(request.form.get("duration_minutes","1440")); repeat_days=int(request.form.get("repeat_every_days","7"))
            except ValueError: raise ValueError("Recurring giveaway values must be whole numbers.")
            if not isinstance(channel,__import__("discord").TextChannel) or not prize or len(prize)>200 or not 1<=winners<=100 or not 1<=duration<=525600 or not 1<=repeat_days<=365:
                raise ValueError("Choose a valid channel and prize, 1–100 winners, duration up to 1 year, and repeat interval 1–365 days.")
            schedules=state.setdefault("giveaway_schedules",{}); schedule_id=f"{gid}-{int(time.time())}-{secrets.token_hex(2)}"
            schedules[schedule_id]={"guild_id":gid,"channel_id":channel.id,"host_id":int(_tokens[sid]["user"]["id"]),"prize":prize,
                "winners":winners,"duration_minutes":duration,"repeat_every_days":repeat_days,"next_at":time.time()+repeat_days*86400,"enabled":True}
            _save(); _audit(gid,actor,"Dashboard: recurring giveaway scheduled",f"{prize}; every {repeat_days} day(s); schedule {schedule_id}")
            session["dashboard_notice"]="Recurring giveaway schedule saved."
        elif action=="giveaway_repeat_stop":
            schedule_id=request.form.get("schedule_id",""); schedules=state.setdefault("giveaway_schedules",{}); cfg=schedules.get(schedule_id)
            if not cfg or int(cfg.get("guild_id",0))!=gid: raise ValueError("That recurring giveaway schedule was not found.")
            schedules.pop(schedule_id,None); _save(); _audit(gid,actor,"Dashboard: recurring giveaway stopped",schedule_id)
            session["dashboard_notice"]="Recurring giveaway schedule stopped. Existing active giveaways are unchanged."
        elif action=="giveaway_reroll":
            raw_mid=request.form.get("message_id","")
            if not raw_mid.isdigit(): raise ValueError("Invalid giveaway message ID.")
            mid=int(raw_mid); history=state.setdefault("giveaway_history",{}); gw=history.get(str(mid)) or history.get(mid)
            if not gw or int(gw.get("guild_id",0))!=gid: raise ValueError("Finished giveaway not found in this server.")
            old=set(int(x) for x in gw.get("winner_ids",[])); candidates=[int(x) for x in gw.get("eligible_entrants",gw.get("entrants",[])) if int(x) not in old]
            if not candidates: raise ValueError("No eligible non-winning entrants remain to reroll.")
            import random as _random
            winner=_random.choice(candidates); gw.setdefault("winner_ids",[]).append(winner); gw["last_reroll_at"]=time.time()
            channel=_bot.get_channel(int(gw.get("channel_id",0)))
            async def post_reroll():
                if channel:
                    try:
                        msg=await channel.fetch_message(mid)
                        await msg.reply(f"🎉 Reroll winner: <@{winner}>! You won **{gw.get('prize','the giveaway prize')}**.",allowed_mentions=__import__("discord").AllowedMentions(users=True))
                    except __import__("discord").HTTPException: pass
                await state["bd_save_data"]()
            _run_bot(post_reroll()); _audit(gid,actor,"Dashboard: giveaway rerolled",f"Message {mid}; new winner {winner}")
            session["dashboard_notice"]=f"Rerolled giveaway. New winner ID: {winner}."
        elif action=="giveaway_end":
            mid=int(request.form.get("message_id","0")); gw=state["active_giveaways"].get(mid)
            if not gw or int(gw.get("guild_id",0))!=gid: raise ValueError("Active giveaway not found in this server.")
            _run_bot(state["finish_giveaway"](mid)); _audit(gid,actor,"Dashboard: giveaway ended",f"Message {mid}")
            session["dashboard_notice"]="Giveaway ended and winners were selected."
        elif action=="giveaway_cancel":
            mid=int(request.form.get("message_id","0")); gw=state["active_giveaways"].get(mid)
            if not gw or int(gw.get("guild_id",0))!=gid: raise ValueError("Active giveaway not found in this server.")
            _run_bot(state["cancel_giveaway"](mid)); _audit(gid,actor,"Dashboard: giveaway cancelled",f"Message {mid}")
            session["dashboard_notice"]="Giveaway cancelled without selecting winners."
        elif action=="config_backup_restore":
            upload=request.files.get("backup_file")
            if not upload or not upload.filename or not upload.filename.lower().endswith(".json"):
                raise ValueError("Choose a .json Cinnamon configuration backup file.")
            raw=upload.stream.read(1_000_001)
            if len(raw)>1_000_000: raise ValueError("Backup file is too large (maximum 1 MB).")
            try: payload=json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError,json.JSONDecodeError): raise ValueError("Backup file is not valid UTF-8 JSON.")
            changed=_restore_guild_config(guild,state,payload)
            _save(); _audit(gid,actor,"Dashboard: configuration backup restored",f"Sections restored: {', '.join(changed) or 'none'}")
            session["dashboard_notice"]="Configuration restored for this server. Member balances, inventories, progress, active giveaways and secrets were preserved."
        elif action=="hangry_logs":
            cog=state.get("hg_cog"); value=request.form.get("channel_id","").strip()
            if not cog: raise ValueError("Hangry Games is not ready.")
            if value and (not value.isdigit() or not isinstance(guild.get_channel(int(value)),__import__("discord").TextChannel)): raise ValueError("Choose a valid text channel in this server.")
            enabled_now="enabled" in request.form
            async def save_hangry():
                if value: cog.hg_log_channels[gid]=int(value)
                else: cog.hg_log_channels.pop(gid,None); cog.log_enabled.pop(gid,None)
                if value: cog.log_enabled[gid]=enabled_now
                await cog._save()
            _run_bot(save_hangry()); _audit(gid,actor,"Dashboard: Hangry Games logging updated",f"Channel {value or 'disabled'}; enabled={enabled_now}")
            session["dashboard_notice"]="Hangry Games log settings saved."
        elif action=="recall":
            recall_fn=state.get("recall_guild_data")
            if not callable(recall_fn): raise RuntimeError("Recovery service is not connected to the dashboard.")
            result=_run_bot(recall_fn(guild),timeout=120)
            _audit(gid,actor,"Dashboard: log recovery scan completed",
                   f"Channels scanned={result.get('channels_scanned',0)}/{result.get('channels_configured',0)}; "
                   f"embeds={result.get('embeds_scanned',0)}; warnings={result.get('warnings',0)}; "
                   f"XP users={result.get('xp_users_restored',0)}; economy accounts={result.get('economy_accounts',0)}; "
                   f"achievements={result.get('achievements_restored',0)}; quests={result.get('quests_restored',0)}; "
                   f"Hangry games=#{result.get('hangry_game_count',0)}; wins={result.get('hangry_wins_seen',0)}")
            session["dashboard_notice"]=(f"Recovery scanned {result.get('embeds_scanned',0)} log embeds across "
                f"{result.get('channels_scanned',0)} channel(s). Restored/updated: {result.get('warnings',0)} warnings, "
                f"{result.get('xp_users_restored',0)} XP users, {result.get('economy_accounts',0)} economy account(s), "
                f"{result.get('achievements_restored',0)} achievement(s), {result.get('quests_restored',0)} completed quest(s); "
                f"Hangry Games #{result.get('hangry_game_count',0)} with {result.get('hangry_wins_seen',0)} win(s) found. "
                "Only retained logs/snapshots can be recovered.")
        elif action=="message_send":
            if not request.form.get("send_confirmation"):
                raise ValueError("Confirm the destination and message before sending.")
            channel_id=request.form.get("channel_id","").strip()
            channel=guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
            discord=__import__("discord")
            if not isinstance(channel, discord.TextChannel): raise ValueError("Choose a valid text channel in this server.")
            title=request.form.get("embed_title","").strip()
            description=request.form.get("embed_description","").strip()
            footer=request.form.get("embed_footer","Cinnamon • Made with paws 🐾").strip()
            color_text=request.form.get("embed_color","#D97732").strip()
            image_url=request.form.get("embed_image","").strip()
            if not title or len(title)>256: raise ValueError("Embed title must be 1–256 characters.")
            if not description or len(description)>4000: raise ValueError("Message text must be 1–4,000 characters.")
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", color_text): raise ValueError("Choose a valid six-digit hex accent colour.")
            if len(footer)>200: raise ValueError("Footer must be no longer than 200 characters.")
            # Discord limits the combined text across embed title, description, footer,
            # author and fields to 6,000 characters. This studio currently creates no
            # author/fields, so validate the complete text we actually send.
            total_embed_text = len(title) + len(description) + len(footer)
            if total_embed_text > 6000:
                raise ValueError(f"Embed text totals {total_embed_text:,} characters; Discord allows 6,000 across the embed.")
            if image_url and (not image_url.startswith("https://") or len(image_url)>500): raise ValueError("Optional image must be an HTTPS URL under 500 characters.")
            bot_member=guild.me
            perms=channel.permissions_for(bot_member) if bot_member else None
            if not perms or not perms.send_messages or not perms.embed_links:
                raise PermissionError("Cinnamon needs Send Messages and Embed Links in the selected channel.")
            embed=discord.Embed(title=title,description=description,color=int(color_text[1:],16))
            if footer: embed.set_footer(text=footer)
            if image_url: embed.set_image(url=image_url)
            embed.timestamp=dt.datetime.now(dt.timezone.utc)
            async def send_studio_embed():
                return await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            message=_run_bot(send_studio_embed(),timeout=25)
            _audit(gid,actor,"Dashboard: Message Studio embed sent",f"Destination #{channel.name} ({channel.id}); title: {title[:150]}; message ID {message.id}.")
            session["dashboard_notice"]=f"Embed sent to #{channel.name}."


        elif action in {"ticket_dashboard_claim","ticket_dashboard_unclaim"}:
            raw_channel=request.form.get("channel_id","").strip()
            if not raw_channel.isdigit(): raise ValueError("Invalid ticket channel.")
            root=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_tickets_v1",{})
            cfg=root.get(str(gid),{})
            ticket=cfg.get("tickets",{}).get(raw_channel)
            channel=guild.get_channel(int(raw_channel))
            if not ticket or not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Ticket record/channel not found.")
            if ticket.get("status")!="open": raise ValueError("Only open tickets can be assigned.")
            actor_id=int(_tokens[sid]["user"]["id"])
            before=__import__("copy").deepcopy(ticket)
            if action=="ticket_dashboard_claim":
                if str(ticket.get("routing","")).lower() in {"shop","grow_a_garden","gag","boosting"}:
                    raise ValueError("Claim this shop ticket in Discord so Cinnamon can verify and consume the selected inventory item safely.")
                if ticket.get("claimed_by") not in (None,actor_id): raise ValueError("This ticket is already claimed by another staff member.")
                ticket["claimed_by"]=actor_id
            else:
                if str(ticket.get("routing","")).lower() in {"shop","grow_a_garden","gag","boosting"} and ticket.get("service_consumed"):
                    raise ValueError("An inventory-backed ticket cannot be unclaimed after its item has been consumed.")
                ticket["claimed_by"]=None
            async def save_ticket_assignment():
                if not await state["bd_save_data"]():
                    ticket.clear();ticket.update(before)
                    raise ValueError("Ticket assignment could not be durably saved.")
            _run_bot(save_ticket_assignment())
            await_message = "claimed by dashboard staff." if action=="ticket_dashboard_claim" else "unassigned by dashboard staff."
            async def notify_ticket_assignment():
                await channel.send("Ticket "+await_message)
            _run_bot(notify_ticket_assignment())
            _audit(gid,actor,"Dashboard ticket "+("claimed" if action=="ticket_dashboard_claim" else "unassigned"),f"Channel {channel.id}; assigned staff ID {ticket.get('claimed_by')}.")
            session["dashboard_notice"]="Ticket "+("claimed" if action=="ticket_dashboard_claim" else "unassigned")+"."
        elif action in {"ticket_dashboard_close","ticket_dashboard_reopen","ticket_dashboard_claim","ticket_dashboard_unclaim"}:
            raw_channel=request.form.get("channel_id","").strip()
            if not raw_channel.isdigit(): raise ValueError("Invalid ticket channel.")
            root=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_tickets_v1",{}); cfg=root.get(str(gid),{})
            ticket=cfg.get("tickets",{}).get(raw_channel)
            channel=guild.get_channel(int(raw_channel))
            if not ticket or not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Ticket record/channel not found.")
            creator=guild.get_member(int(ticket.get("creator_id",0)))
            async def dashboard_ticket_change():
                before_ticket = __import__("copy").deepcopy(ticket)
                closed_records = cfg.setdefault("closed", {})
                before_closed = __import__("copy").deepcopy(closed_records.get(raw_channel))
                closing = action == "ticket_dashboard_close"
                if closing:
                    if ticket.get("status") != "open":
                        raise ValueError("Ticket is already closed.")
                    ticket.update({"status": "closed", "closed_at": time.time(),
                                   "close_reason": "Closed by dashboard administrator"})
                    closed_records[raw_channel] = dict(ticket)
                    if creator:
                        await channel.set_permissions(creator, view_channel=True, send_messages=False,
                                                       read_message_history=True)
                else:
                    if ticket.get("status") != "closed":
                        raise ValueError("Ticket is not closed.")
                    ticket.update({"status": "open", "closed_at": None})
                    closed_records.pop(raw_channel, None)
                    if creator:
                        await channel.set_permissions(creator, view_channel=True, send_messages=True,
                                                       read_message_history=True, attach_files=True,
                                                       embed_links=True)
                if not await state["bd_save_data"]():
                    ticket.clear()
                    ticket.update(before_ticket)
                    if before_closed is None:
                        closed_records.pop(raw_channel, None)
                    else:
                        closed_records[raw_channel] = before_closed
                    if creator:
                        await channel.set_permissions(
                            creator, view_channel=True,
                            send_messages=before_ticket.get("status") == "open",
                            read_message_history=True, attach_files=True, embed_links=True)
                    raise ValueError("Ticket change could not be durably saved. The previous status was restored.")
                if closing:
                    close_view=None if str(ticket.get("routing","")).lower()=="support" else state["ticket_control_view"](ticket.get("ticket_id"))
                    await channel.send("Ticket closed by a dashboard administrator.",view=close_view)
                    transcript = await state["ticket_transcript"](channel)
                    logch = guild.get_channel(int(cfg.get("settings", {}).get("log_channel_id") or 0))
                    if transcript and cfg.get("settings", {}).get("transcript_on_close", True) and logch:
                        await logch.send(content=f"Dashboard close transcript for {channel.mention}",
                                         file=__import__("discord").File(transcript, filename=f"ticket-{channel.id}.html"))
                else:
                    reopen_view=None if str(ticket.get("routing","")).lower()=="support" else state["ticket_control_view"](ticket.get("ticket_id"))
                    await channel.send("Ticket reopened by a dashboard administrator.",view=reopen_view)
            _run_bot(dashboard_ticket_change(),timeout=40)
            _audit(gid,actor,"Dashboard ticket "+("closed" if action=="ticket_dashboard_close" else "reopened"),f"Channel {channel.id}; creator {ticket.get('creator_id')}.")
            session["dashboard_notice"]="Ticket "+("closed" if action=="ticket_dashboard_close" else "reopened")+" in Discord."

        elif action in {"ticket_dashboard_assign", "ticket_dashboard_priority"}:
            raw_channel = request.form.get("channel_id", "").strip()
            if not raw_channel.isdigit():
                raise ValueError("Invalid ticket channel.")
            cfg = (state.get("advanced_features_data", {}).get("cinnamon_tickets_v1", {}) or {}).get(str(gid), {})
            ticket = (cfg.get("tickets", {}) or {}).get(raw_channel)
            if not isinstance(ticket, dict) or ticket.get("status") != "open":
                raise ValueError("Only an active ticket can be updated.")
            before = __import__("copy").deepcopy(ticket)
            if action == "ticket_dashboard_assign":
                raw_member = request.form.get("member_id", "").strip()
                member = guild.get_member(int(raw_member)) if raw_member.isdigit() else None
                if not member or member.bot:
                    raise ValueError("Choose a valid server member.")
                ticket_cfg = cfg.get("settings", {}) or {}
                allowed_staff = set(map(int, ticket_cfg.get("staff_role_ids", [])))
                role_cfg = (state.get("advanced_features_data", {}).get("cinnamon_role_permissions_v1", {}) or {}).get(str(gid), {})
                allowed_staff.update(map(int, role_cfg.get("ticket_staff", [])))
                allowed_staff.update(map(int, role_cfg.get("ticket_admin", [])))
                if str(ticket.get("routing", "")).lower() in {"grow_a_garden", "gag", "boosting"}:
                    allowed_staff.update(map(int, ticket_cfg.get("trusted_booster_role_ids", [])))
                    allowed_staff.update(map(int, role_cfg.get("trusted_booster", [])))
                is_ticket_staff = member.guild_permissions.administrator or any(role.id in allowed_staff for role in member.roles)
                if not is_ticket_staff:
                    raise ValueError("Assign tickets only to configured ticket staff or administrators.")
                ticket["assigned_to"] = member.id
                audit_detail = f"Channel {raw_channel}; assigned to {member.display_name} ({member.id})."
                notice = f"Ticket assigned to {member.display_name}."
            else:
                priority = request.form.get("priority", "").strip().lower()
                if priority not in {"low", "normal", "high", "urgent"}:
                    raise ValueError("Choose a valid ticket priority.")
                ticket["priority"] = priority
                audit_detail = f"Channel {raw_channel}; priority set to {priority}."
                notice = f"Ticket priority set to {priority.title()}."
            async def save_dashboard_ticket_metadata():
                if not await state["bd_save_data"]():
                    ticket.clear()
                    ticket.update(before)
                    raise ValueError("Ticket update could not be durably saved. The previous values were restored.")
            _run_bot(save_dashboard_ticket_metadata())
            _audit(gid, actor, "Dashboard ticket updated", audit_detail)
            session["dashboard_notice"] = notice
        elif action=="ticket_settings_save":
            raw_log=request.form.get("log_channel_id","").strip(); raw_parent=request.form.get("ticket_category_id","").strip()
            log_channel=guild.get_channel(int(raw_log)) if raw_log.isdigit() else None
            parent=guild.get_channel(int(raw_parent)) if raw_parent.isdigit() else None
            if raw_log and not isinstance(log_channel,__import__("discord").TextChannel): raise ValueError("Choose a valid ticket log text channel.")
            if raw_parent and not isinstance(parent,__import__("discord").CategoryChannel): raise ValueError("Choose a valid ticket category.")
            try: maximum=int(request.form.get("max_open_per_user","3")); cooldown=int(request.form.get("cooldown_seconds","60")); auto_close=int(request.form.get("auto_close_hours","0"))
            except ValueError: raise ValueError("Ticket limits must be whole numbers.")
            if not 1<=maximum<=10 or not 0<=cooldown<=86400 or not 0<=auto_close<=720: raise ValueError("Ticket limits are outside allowed ranges.")
            staff=[]; trusted=[]; moderators=[]
            for field,target in (("staff_role_ids",staff),("moderator_role_ids",moderators),("trusted_booster_role_ids",trusted)):
                for raw in request.form.getlist(field):
                    if not raw.isdigit(): raise ValueError("Invalid role selection.")
                    role=guild.get_role(int(raw))
                    if not role or role.is_default() or role.managed: raise ValueError("A selected ticket role is unavailable or managed.")
                    target.append(role.id)
            cfg=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_tickets_v1",{}).setdefault(str(gid),{})
            cfg.setdefault("panels",{}); cfg.setdefault("tickets",{}); cfg.setdefault("closed",{}); cfg.setdefault("cooldowns",{})
            cfg["settings"]={"log_channel_id":log_channel.id if log_channel else None,"ticket_category_id":parent.id if parent else None,"staff_role_ids":staff,"moderator_role_ids":moderators,"trusted_booster_role_ids":trusted,"max_open_per_user":maximum,"cooldown_seconds":cooldown,"auto_close_hours":auto_close,"transcript_on_close":"transcript_on_close" in request.form,"rating_enabled":"rating_enabled" in request.form}
            _save(); _audit(gid,actor,"Ticket settings updated",f"Log channel {raw_log or 'disabled'}; parent {raw_parent or 'not set'}; staff roles {len(staff)}; trusted booster roles {len(trusted)}.")
            session["dashboard_notice"]="Ticket settings saved to durable storage."
        elif action in {"ticket_panel_save","ticket_panel_update"}:
            panel_id=request.form.get("panel_id","").strip()
            cfg=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_tickets_v1",{}).setdefault(str(gid),{})
            panels=cfg.setdefault("panels",{})
            if action=="ticket_panel_update":
                panel=panels.get(panel_id)
                if not panel: raise ValueError("Ticket panel not found.")
            else:
                panel_id=secrets.token_hex(6); panel={"id":panel_id,"published":False,"categories":[]}
            name=request.form.get("panel_name","").strip(); title=request.form.get("panel_title","").strip(); description=request.form.get("panel_description","").strip(); color=request.form.get("panel_color","#D99048").strip()
            raw_channel=request.form.get("channel_id","").strip(); channel=guild.get_channel(int(raw_channel)) if raw_channel.isdigit() else None
            if not name or len(name)>60 or not title or len(title)>256 or len(description)>3500 or not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Panel name, title, description or channel is invalid.")
            if not re.fullmatch(r"#[0-9a-fA-F]{6}",color): raise ValueError("Panel color must be a six-digit hex color.")
            raw_categories=request.form.get("categories_json","").strip()
            if raw_categories:
                try: categories=json.loads(raw_categories)
                except json.JSONDecodeError: raise ValueError("Categories must be valid JSON.")
                if not isinstance(categories,list) or not 1<=len(categories)<=25: raise ValueError("Provide 1–25 ticket categories.")
                clean_categories=[]
                for item in categories:
                    if not isinstance(item,dict): raise ValueError("Each category must be a JSON object.")
                    label=str(item.get("label","")).strip(); button=str(item.get("button_label",label)).strip(); routing=str(item.get("routing","support")).lower()
                    if not label or len(label)>60 or not button or len(button)>80 or routing not in {"support","shop","grow_a_garden","gag","boosting","faq"}: raise ValueError("Category label, button or routing is invalid.")
                    gag_enabled=request.form.get("gag_features_enabled")=="1"; items_enabled=request.form.get("item_features_enabled")=="1"
                    if routing in {"grow_a_garden","gag","boosting"} and not gag_enabled: raise ValueError("Enable Grow a Garden features before adding a GAG category.")
                    if routing=="shop" and not items_enabled: raise ValueError("Enable item features before adding a Shop category.")
                    questions=item.get("questions",[])
                    if not isinstance(questions,list) or len(questions)>5: raise ValueError("Each category supports up to five modal questions.")
                    clean_questions=[]
                    for q in questions:
                        if not isinstance(q,dict) or not str(q.get("label","")).strip() or len(str(q.get("label","")))>45: raise ValueError("Question labels must be 1–45 characters.")
                        clean_questions.append({"label":str(q["label"]).strip(),"required":bool(q.get("required",True)),"paragraph":bool(q.get("paragraph",True)),"max_length":max(1,min(1000,int(q.get("max_length",400)))),"placeholder":str(q.get("placeholder","Your answer"))[:100]})
                    raw_staff=item.get("staff_role_ids",[])
                    if not isinstance(raw_staff,list) or len(raw_staff)>20: raise ValueError("Category staff_role_ids must be a list of at most 20 roles.")
                    category_staff=[]
                    for rid in raw_staff:
                        if not str(rid).isdigit() or not guild.get_role(int(rid)) or guild.get_role(int(rid)).managed: raise ValueError("A category staff role is invalid.")
                        category_staff.append(int(rid))
                    service_item_ids=item.get("service_item_ids", [])
                    if not isinstance(service_item_ids,list): service_item_ids=[service_item_ids] if service_item_ids else []
                    if not service_item_ids and item.get("service_item_id"): service_item_ids=[item.get("service_item_id")]
                    service_item_ids=list(dict.fromkeys(str(x).strip() for x in service_item_ids if str(x).strip()))
                    if len(service_item_ids)>25: raise ValueError("A category can link at most 25 GAG service items.")
                    for service_id in service_item_ids:
                        linked_item=(state.get("ECONOMY_ITEMS",{}) or {}).get(service_id)
                        if routing not in {"grow_a_garden","gag","boosting"} or not isinstance(linked_item,dict) or linked_item.get("category")!="grow_a_garden":
                            raise ValueError("Every linked service must be a registered Grow a Garden item on a Grow a Garden category.")
                    inventory_ids=item.get("inventory_item_ids",[])
                    if inventory_ids and not items_enabled: raise ValueError("Enable item features before linking inventory items to a category.")
                    if not isinstance(inventory_ids,list) or len(inventory_ids)>100 or any(str(x) not in (state.get("ECONOMY_ITEMS",{}) or {}) for x in inventory_ids): raise ValueError("Eligible inventory items must be existing shop item IDs.")
                    persistent_label=str(item.get("persistent_button_label","")).strip()[:80]
                    persistent_reply=str(item.get("persistent_button_reply","")).strip()[:1800]
                    if bool(persistent_label)!=bool(persistent_reply): raise ValueError("A persistent button needs both a label and a reply.")
                    clean_categories.append({"id":str(item.get("id") or secrets.token_hex(4))[:40],"label":label,"button_label":button,"emoji":str(item.get("emoji",""))[:100],"button_style":str(item.get("button_style","primary")).lower(),"routing":routing,"trusted_booster_routing":bool(item.get("trusted_booster_routing",routing in {"grow_a_garden","gag","boosting"})),"staff_role_ids":category_staff,"inventory_item_ids":[str(x) for x in inventory_ids],"persistent_button_label":persistent_label,"persistent_button_reply":persistent_reply,"faq_answer":str(item.get("faq_answer",""))[:2000],"welcome_title":str(item.get("welcome_title",""))[:256],"welcome_message":str(item.get("welcome_message",""))[:1500],"channel_category_id":int(item.get("channel_category_id",0) or 0),"channel_name_format":str(item.get("channel_name_format","ticket-{username}"))[:80],"service_item_id":service_item_ids[0] if service_item_ids else "","service_item_ids":service_item_ids,"questions":clean_questions})
                panel["categories"]=clean_categories
            elif action in {"ticket_panel_save","ticket_panel_update"}:
                label=request.form.get("category_label","").strip(); button=request.form.get("button_label","").strip(); routing=request.form.get("routing","support").strip()
                if not label or len(label)>60 or not button or len(button)>80 or routing not in {"support","shop","grow_a_garden"}: raise ValueError("Ticket category/button/routing is invalid.")
                gag_enabled=request.form.get("gag_features_enabled")=="1"
                items_enabled=request.form.get("item_features_enabled")=="1"
                if routing=="grow_a_garden" and not gag_enabled: raise ValueError("Enable Grow a Garden features to use GAG routing on this panel.")
                if routing=="shop" and not items_enabled: raise ValueError("Enable item features to use Shop routing on this panel.")
                custom_questions=[]
                for i in range(1,6):
                    q=request.form.get("question"+str(i),"").strip()
                    if q: custom_questions.append({"label":q,"required":True,"paragraph":True,"max_length":400})
                questions=custom_questions
                if not questions and routing in {"shop","grow_a_garden"}:
                    defaults=(["What item or service did you purchase?","Order ID or purchase proof (if available)","What issue are you experiencing?"] if routing=="shop" else ["What Grow a Garden service did you purchase?","Order ID or purchase proof (if available)","What do you need help with?"])
                    questions=[{"label":label,"required":True,"paragraph":True,"max_length":400} for label in defaults]
                old_category=(panel.get("categories",[]) or [{}])[0] if action=="ticket_panel_update" else {}
                legacy_services=old_category.get("service_item_ids") or ([old_category.get("service_item_id")] if old_category.get("service_item_id") else [])
                service_item_ids=(list(dict.fromkeys(str(x).strip() for x in request.form.getlist("service_item_ids") if str(x).strip())) if gag_enabled else [str(x) for x in legacy_services if str(x)])
                if gag_enabled:
                    if len(service_item_ids)>25: raise ValueError("A category can link at most 25 GAG service items.")
                    for service_id in service_item_ids:
                        linked_item=(state.get("ECONOMY_ITEMS",{}) or {}).get(service_id)
                        if routing!="grow_a_garden" or not isinstance(linked_item,dict) or linked_item.get("category")!="grow_a_garden":
                            raise ValueError("Choose registered Grow a Garden items for a Grow a Garden ticket category.")
                if items_enabled:
                    selected_inventory=[]
                    for raw in request.form.getlist("inventory_item_ids"):
                        if raw not in (state.get("ECONOMY_ITEMS",{}) or {}): raise ValueError("An eligible inventory item no longer exists.")
                        selected_inventory.append(str(raw))
                else:
                    selected_inventory=list(old_category.get("inventory_item_ids",[]) or [])
                category_roles=[]
                for raw in request.form.getlist("category_staff_role_ids"):
                    if not raw.isdigit() or not guild.get_role(int(raw)) or guild.get_role(int(raw)).managed: raise ValueError("A custom ticket ping role is invalid.")
                    category_roles.append(int(raw))
                persistent_label=request.form.get("persistent_button_label","").strip()[:80]
                persistent_reply=request.form.get("persistent_button_reply","").strip()[:1800]
                if bool(persistent_label)!=bool(persistent_reply): raise ValueError("A persistent button needs both a label and a reply.")
                category={"id":str(old_category.get("id") or secrets.token_hex(4)),"label":label,"button_label":button,"emoji":request.form.get("button_emoji","").strip()[:100],"button_style":"primary","routing":routing,"trusted_booster_routing":routing=="grow_a_garden","service_item_id":service_item_ids[0] if service_item_ids else "","service_item_ids":service_item_ids,"welcome_message":request.form.get("welcome_message","").strip()[:1500],"questions":questions,"inventory_item_ids":selected_inventory,"staff_role_ids":category_roles,"persistent_button_label":persistent_label,"persistent_button_reply":persistent_reply}
                if action=="ticket_panel_update":
                    panel["categories"]=[category]+(panel.get("categories",[]) or [])[1:]
                else:
                    panel["categories"]=[category]
            panel.update({"id":panel_id,"name":name,"channel_id":channel.id,"title":title,"description":description,"color":color,"gag_features_enabled":request.form.get("gag_features_enabled")=="1","item_features_enabled":request.form.get("item_features_enabled")=="1","updated_at":int(time.time())})
            panels[panel_id]=panel
            _save(); _audit(gid,actor,"Ticket panel configuration saved",f"Panel {name} ({panel_id}); published={bool(panel.get('published'))}.")
            session["dashboard_notice"]="Panel configuration saved. Publish separately to update Discord."
        elif action=="ticket_panel_publish":
            panel_id=request.form.get("panel_id","").strip(); cfg=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_tickets_v1",{}).setdefault(str(gid),{}); panel=cfg.setdefault("panels",{}).get(panel_id)
            if not panel or not panel.get("categories"): raise ValueError("Save a panel with at least one category before publishing.")
            publish_channel_id=request.form.get("publish_channel_id") or panel.get("channel_id")
            channel=guild.get_channel(int(publish_channel_id or 0))
            if not isinstance(channel,__import__("discord").TextChannel): raise ValueError("Panel channel is unavailable.")
            embed=__import__("discord").Embed(title=panel.get("title","Support Center"),description=panel.get("description","Choose a category below."),color=int(panel.get("color","#D99048")[1:],16))
            embed.set_footer(text="Cinnamon Tickets")
            async def publish_panel():
                view=state["ticket_panel_view"](gid,panel_id,panel)
                message=None
                old_channel_id=int(panel.get("channel_id",0) or 0)
                old_message_id=int(panel.get("message_id",0) or 0)
                if old_message_id and old_channel_id==channel.id:
                    try: message=await channel.fetch_message(old_message_id)
                    except Exception: message=None
                elif old_message_id and old_channel_id!=channel.id:
                    old_channel=guild.get_channel(old_channel_id)
                    if old_channel:
                        try:
                            old_message=await old_channel.fetch_message(old_message_id)
                            await old_message.edit(view=None)
                        except Exception: pass
                if message: await message.edit(embed=embed,view=view)
                else: message=await channel.send(embed=embed,view=view)
                panel["channel_id"]=channel.id; panel["message_id"]=message.id; panel["published"]=True; panel["published_at"]=int(time.time())
                if not await state["bd_save_data"](): raise ValueError("Could not verify durable panel publish.")
                return message.id
            mid=_run_bot(publish_panel(),timeout=40); _audit(gid,actor,"Ticket panel published",f"{panel.get('name')} in #{channel.name}; message {mid}.")
            session["dashboard_notice"]="Ticket panel published/updated in Discord."
        elif action=="ticket_panel_delete":
            panel_id=request.form.get("panel_id","").strip(); cfg=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_tickets_v1",{}).setdefault(str(gid),{}); panel=cfg.setdefault("panels",{}).pop(panel_id,None)
            if not panel: raise ValueError("Ticket panel not found.")
            async def remove_panel_message():
                channel=guild.get_channel(int(panel.get("channel_id",0)))
                if channel and panel.get("message_id"):
                    try: msg=await channel.fetch_message(int(panel["message_id"])); await msg.edit(view=None)
                    except Exception: pass
                await state["bd_save_data"]()
            _run_bot(remove_panel_message()); _audit(gid,actor,"Ticket panel deleted",str(panel.get("name",panel_id)))
            session["dashboard_notice"]="Panel configuration deleted; old panel message has been disabled."
        elif action=="roles_setup_save":
            root=state.setdefault("advanced_features_data",{}).setdefault("cinnamon_role_permissions_v1",{}); cfg={}
            role_keys=("giveaway_creator","hangry_runner","trusted_booster","ticket_staff","ticket_admin","shop_manager","economy_admin","quest_manager","event_manager","moderator")
            for key in role_keys:
                ids=[]
                for raw in request.form.getlist("role_"+key):
                    if not raw.isdigit(): raise ValueError("Invalid role selection.")
                    role=guild.get_role(int(raw))
                    if not role or role.is_default() or role.managed: raise ValueError("A selected permission role is unavailable or managed.")
                    ids.append(role.id)
                cfg[key]=sorted(set(ids))
            root[str(gid)]=cfg; _save(); _audit(gid,actor,"Roles Setup permissions saved",", ".join(f"{k}: {len(v)} role(s)" for k,v in cfg.items()))
            session["dashboard_notice"]="All role permissions saved to durable storage and logged."

        elif action=="moderate":
            target,mod_action=_moderate(guild,_tokens[sid]["user"]["id"],request.form)
            _audit(gid,actor,f"Dashboard moderation: {mod_action}",f"Target {target}; reason: {request.form.get('reason','No reason provided')[:350]}")
            session["dashboard_notice"]=f"{mod_action.title()} action completed for {target}."
        else:
            raise ValueError("Unknown dashboard action.")
        tab={"brain_settings":"mind","mind_settings":"mind","economy_item_add":"economy","economy_item_save":"economy","economy_item_remove":"economy","economy_income_add":"economy","economy_income_remove":"economy","giveaway_create":"giveaways","giveaway_edit":"giveaways","giveaway_draft_save":"giveaways","giveaway_draft_update":"giveaways","giveaway_draft_publish":"giveaways","giveaway_draft_delete":"giveaways","giveaway_end":"giveaways","giveaway_cancel":"giveaways","giveaway_template_save":"giveaways","giveaway_template_delete":"giveaways","giveaway_repeat_create":"giveaways","giveaway_repeat_stop":"giveaways","giveaway_reroll":"giveaways","config_backup_restore":"system","hangry_logs":"hangry","welcome":"community","goodbye":"community","community_features_settings":"community","community_event_create":"community","community_event_cancel":"community","security_settings":"moderation","moderation_controls_settings":"moderation","verification_publish":"moderation","appeal_settings":"moderation","appeal_portal_publish":"moderation","appeal_portal_rotate":"moderation","dashboard_appeal_review":"moderation","ticket_dashboard_claim":"tickets","ticket_dashboard_unclaim":"tickets","welcome_disable":"community","goodbye_disable":"community","ai_channel":"community","log_channel":"community","special_logs":"system","automod":"moderation","antiraid":"moderation","moderate":"moderation","levelrole_add":"engagement","levelrole_remove":"engagement","achievement_settings":"achievements","quest_settings":"quests","xp_settings":"engagement","xp_channel_remove":"engagement","category_log_set":"system","category_log_disable":"system","run_setup":"system","recall":"system","message_send":"message_studio"}.get(action,"overview")
        return redirect(url_for("cinnamon_dashboard.dashboard_home",guild_id=gid,tab=tab))
    except (ValueError,PermissionError) as exc:
        session["dashboard_notice_level"]="error"
        session["dashboard_notice"]=str(exc)[:300]
        return redirect(url_for("cinnamon_dashboard.dashboard_home",guild_id=request.form.get("guild_id",""),tab={"brain_settings":"mind","mind_settings":"mind","economy_item_add":"economy","economy_item_save":"economy","economy_item_remove":"economy","economy_income_add":"economy","economy_income_remove":"economy","giveaway_create":"giveaways","giveaway_edit":"giveaways","giveaway_end":"giveaways","giveaway_cancel":"giveaways","giveaway_template_save":"giveaways","giveaway_template_delete":"giveaways","giveaway_repeat_create":"giveaways","giveaway_repeat_stop":"giveaways","giveaway_reroll":"giveaways","ticket_settings_save":"tickets","ticket_panel_save":"tickets","ticket_panel_update":"tickets","ticket_panel_publish":"tickets","ticket_panel_delete":"tickets","ticket_dashboard_claim":"tickets","ticket_dashboard_unclaim":"tickets","roles_setup_save":"roles_setup","config_backup_restore":"system","hangry_logs":"hangry","moderate":"moderation","automod":"moderation","antiraid":"moderation","achievement_settings":"achievements","quest_settings":"quests","xp_settings":"engagement","xp_channel_remove":"engagement","category_log_set":"system","category_log_disable":"system","run_setup":"system","message_send":"message_studio"}.get(request.form.get("action"),"community")))
    except Exception as exc:
        log.exception("Dashboard action failed (%s)",type(exc).__name__)
        session["dashboard_notice_level"]="error"
        session["dashboard_notice"]="The change could not be completed. Check Cinnamon's Render logs and bot permissions."
        return redirect(url_for("cinnamon_dashboard.dashboard_home",guild_id=request.form.get("guild_id",""),tab="overview"))


@dashboard_bp.get("/logout")
def logout():
    sid=session.pop("dash_sid",None)
    if sid: _tokens.pop(sid,None)
    session.pop("oauth_state",None); session.pop("dashboard_csrf",None); session.pop("display_name",None)
    return redirect(url_for("cinnamon_dashboard.login"))


@dashboard_bp.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
    response.headers["Cache-Control"]="no-store"
    response.headers["Content-Security-Policy"]="default-src 'self' https://cdn.discordapp.com; img-src 'self' https://cdn.discordapp.com data:; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    return response
