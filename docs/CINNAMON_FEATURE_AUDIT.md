# Cinnamon Feature Audit & Upgrade Plan
Updated: 2026-11-10

This document distinguishes repository-backed findings from proposed work. It is not a claim that every item is implemented or live-tested.

## Current architecture
- `main.py` loads feature modules into a shared namespace; keep this architecture unless a migration is deliberately staged.
- Discord bot: discord.py, global slash command sync, prefix `!`.
- Flask dashboard and Discord OAuth; deployment on Render.
- Snapshot persistence through Upstash Redis REST when configured, otherwise local JSON (local Render filesystem may be ephemeral).
- Catnip economy and inventories are guild-scoped; keys are `(guild_id, user_id)`.
- Adventure/story/fishing records are stored in `advanced_features_data` under legacy internal keys; keep these keys stable to preserve saves.

## Verified code paths / work in this upgrade branch
- Story entry point: `/cinnamon stories` → explicit dropdown → Start selected story.
- Fishing: timed bite/hook/fight phases, three move choices, tension/progress, missed-turn loss, line snap/escape thresholds.
- Rod repair: `/craft repair_rod` consumes one `fishing_string`; shop item costs 250 Catnip; broken rods cannot cast.
- Economy: `/economy balance` and prefix `!balance`/`!bal` use the same `economy_balance(guild_id,user_id)` accessor.
- Read-only `/economy diagnose` (Administrator) reports the exact guild/member entry and snapshot readiness without creating a missing balance.
- Prefix docs and retired-prefix response are aligned to `!`.
- Adventure/fishing module files were renamed to `cinnamon_adventure_*` / `cinnamon_fishing_game.py`; persisted `wildlands_*` keys remain unchanged for save compatibility.
- Private Brain Q&A is now routed to DM for public chat, and `/cinnamon-me ask` returns an ephemeral read-only answer. Memory on/off/clear/view/edit natural-language controls are explicit and member-scoped.
- `/ping` and `/botstatus` are registered slash commands; status reports snapshot and economy transaction readiness.
- Snapshot loading merges persisted custom shop items over current code defaults, so old snapshots cannot remove newly shipped built-in shop items.
- New offline regression tests cover story selection, repair, prefix consistency, and line snap.

## Main risks / bugs to keep addressing
1. **Economy account mismatch:** A wallet once displayed 63,620 while prefix balance showed 100. Same accessor means investigate guild/member identity, loaded snapshot, or duplicate runtime—not just the shop UI. Diagnose first; never overwrite a balance by guessing.
2. **Storage durability:** Local-file backend is not durable across Render replacement unless a persistent disk is configured. Upstash readiness, schema validation, and CAS conflicts must be visible.
3. **Interaction lifetime:** Buttons must use their own interaction response/followup; scheduled tasks must never reuse an expired slash-command webhook.
4. **Command drift:** Keep one canonical command prefix, one slash registration path, human-readable autocomplete, and no duplicate tree names. CI should inspect the actual command tree.
5. **Economy consistency:** Balance display, affordability, purchase debit, reward credit, and audit log should use the same guild/user key and transaction boundary. Add replay/idempotency protections to all money mutations.
6. **Batch Brain actions:** Keep the exact closed parser; mention evidence, permission/role hierarchy, protected targets, requester-only confirmation, expiration, storage receipt, and partial execution reporting are mandatory. Never let Gemini output authorize an action.
7. **Fishing:** Ensure each action changes outcomes; missed turns lose the fish; repeated hard reels snap line; steady/give/reel have distinct risk/reward; repair consumes exactly one string; concurrent sessions are locked.
8. **Story:** Selection, restart confirmation, resume state, branch validation, rewards once only, and ephemeral ownership checks should be tested.
9. **Dashboard:** Validate OAuth state and exact redirect URI; server-side permission checks on every mutation; mobile layout; explicit health status for Discord, storage, and snapshots; no secrets in HTML/logs.
10. **Privacy/memory:** Only explicit member-owned memory; private summaries/DMs must never leak another user's state or silently use guessed values.
11. **Quest/achievement balance:** daily/weekly rotation, reward caps, idempotent claims, reset timezone, and completion logs should have deterministic tests.
12. **Observability:** structured errors with command/guild/interaction IDs (no tokens or private message content), useful admin diagnostics, storage status, and a bounded error log.

## Suggested implementation sequence
- **P0 — data safety:** diagnose/fix live Catnip divergence, verify snapshot load and Upstash key, backup before migration.
- **P0 — interaction correctness:** story selection and all component views, expired interaction handling, fishing session recovery.
- **P1 — economy integrity:** transaction helper for Catnip/inventory changes, immutable receipts, replay-safe claims, shop purchase tests.
- **P1 — command integrity:** command tree audit, prefix migration, autocomplete, command help generated from actual registrations.
- **P1 — gameplay completeness:** fishing repair/crafting, adventure selector and save/resume, quest/achievement caps and resets.
- **P2 — dashboard:** health/diagnostics, economy analytics, quest/story/fishing views, settings validation and mobile navigation.
- **P2 — content:** rotating shop, trading/auction, titles/prestige, seasonal quests, additional story chapters, collectible catalog.
- **P3 — performance:** reduce REST calls, cache safe reads, bound tasks/queues, inspect Gemini latency/cost and rate-limit backoff.

## Manual release checklist (phone-friendly)
1. Review PR diff and CI, especially Python 3.11/3.12.
2. Merge one cohesive PR at a time; keep the previous main commit as rollback.
3. Confirm Render deploy SHA and storage readiness logs.
4. In a private test channel, check `/ping`, `/help`, `!ping`, `!bal`, `/economy balance`, `/economy diagnose`, `/shop`, `/cinnamon stories`, `/fishing`, and `/craft repair_rod`.
5. Verify two different guilds do not share economy keys; verify a purchase logs before/after balances and persists after restart.
6. Never test timeout/ban or batch Catnip against real members without verifying the complete confirmation card and using consenting test accounts.
7. If storage is uncertain/conflicted, stop economy writes and reconcile—do not restart repeatedly or reset balances.

## Branding compatibility
The visible name is **Cinnamon Adventures**. Legacy module filenames and persisted `wildlands_*` keys remain internal compatibility identifiers until a tested migration can preserve existing story/fishing data. Do not expose those names in command descriptions, embeds, or dashboard labels.
