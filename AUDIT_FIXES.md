# Cinnamon Audit Fixes

Applied fixes based on the supplied audit:

1. Module filenames remain `core_events.py`, `economy.py`, `quests.py`, `achievements.py`, etc.; `main.py` loads these exact names.
2. Fixed `/economy buy` quest balance update: it now reports the post-purchase balance (`balance - cost`) instead of an undefined `balance_before` expression.
3. Fixed weekly `Dedicated Attendant` / `Daily Mastery` completion handling by updating the weekly daily-completion counter and immediately rechecking dependent weekly quests when a daily quest completes.
4. Declared achievement/quest persistence state before modular loading and made dashboard encoding resilient to missing early globals.
5. Added `ai_cooldowns = {}` and only credits the AI-reply achievement after a successful Gemini response.
6. Unified `?rank` with the canonical `level_from_xp()` formula used by `/rank`/level tracking.
7. Added achievement/quest tracking to prefix `?buy`, `?give`, and `?feed`; `?daily` now records Catnip earnings too.
8. Added a background quest rotation loop that touches every guild every minute so daily/weekly rotations persist and occur predictably without user activity.
9. Added `/questshop` Discord choices to prevent invalid reward strings.
10. Fixed Secret S1 so only the first Cinnamon interaction after bot startup can claim it.
11. Added explicit configurable server-time offset (`CINNAMON_TIMEZONE_OFFSET_MINUTES`, default `330` / UTC+5:30) for time-based quests and Secret S11.
12. Poll achievements/quests now count distinct polls rather than repeated voting in the same poll.
13. Added a 1-hour sender→recipient Catnip-transfer cooldown to stop immediate back-and-forth transfer loops from farming transfer achievements/quests.

The shop minimum-price migration remains 1,000 Catnip per item, with the configured defaults in `main.py`.

## Follow-up Audit Fixes (2026-10-06)
- Started `quest_reset_loop` from `on_ready` so daily/weekly rotations are clock-driven.
- Made achievement role overrides achievement-ID-specific: `_assign_role(guild_id, user_id, achievement_id, default_role_name)` now resolves `achievement_role_overrides[guild_id][achievement_id]` directly.
- Preserved the successful-AI-only `ai_reply` tracking path; the mention listener does not award `ai_reply` before Gemini succeeds. Prefix `?ask` also records only successful replies.
- S1 already contains the required `global first_interaction_claimed` declaration.
- The packaged build uses the exact filenames referenced by `main.py`; deployment should preserve those names and not rename them with `_2`/`_3` suffixes.
- `/economy daily` already initializes `balance_before` before using it.
- `cinnamon_now()` is defined before modular loading in `main.py` and is intentionally shared through the single-namespace module loader. The modules are not standalone-import modules; direct importing them outside the bot loader is not a supported execution mode.
