# Cinnamon Wildlands — The Treasure Worth Billions (active)

**Current code:** `cinnamon_modules/wildlands_story.py`, `cinnamon_modules/wildlands_fishing.py`, and `cinnamon_modules/wildlands_art.py`.

The former *Wildlands playable adventure* (generic encounters, explorer clues, the forgotten sanctuary, `/adventure ...` commands) has been retired. Its **unloaded** code file `cinnamon_modules/wildlands.py` was removed on October 26, 2026. Another **unloaded** older fishing implementation `cinnamon_modules/fishing.py` (with `/fish ...` and `/cook ...`) was removed. Neither was included in `main.py`'s active module list before cleanup. Their Git history remains available.

## Story

Cinnamon takes the player on a ridiculous six-region treasure hunt for an object she claims is worth **one billion Catnip**. Villain cat Baron Clawdius von Scratch and his assistant Beans stand in the way. The finale reveals that Cinnamon's priceless treasure is an ordinary chew toy Aryan gave her. The actual completion reward is **100,000 Catnip, once per player per server**. The one billion Catnip is a joke, not a payout.

- `/wildlands story` — start/resume interactive chapters with decision buttons.
- `/wildlands story-journal` — review progress and clues.
- `/wildlands story-help` — learn the rules.
- Cinnamon sometimes asks players whether they're having fun. If they're bored, she dramatically reminds them about the alleged billion-Catnip treasure.
- New scene progress is stored separately in `advanced_features_data["wildlands_story_v2"]`, preserving older saved data without executing old code.

## Preserved fishing and merchants

- `/fishing start`, `/fishing cast`, `/fishing locations`, `/fishing travel`, `/fishing journal`, `/fishing inventory`, `/fishing merchants`, `/fishing buy-rod`, `/fishing buy-bait`, `/fishing equip`, `/fishing sell`, and `/fishing setup-roles` remain provided by `wildlands_fishing.py`.
- `/wildlands gather` and the catalog/gallery commands are also retained.
- Finding a merchant may open a two-hour server-wide shop in `#fishing-rod-merchant` or `#fishing-bait-merchant`. The discoverer earns 10% Catnip on **other players' purchases in that shop channel during its live window**.
- Completing the story unlocks permanent access to both merchant channels through the `Wildlands • Treasure Hunter` role.
- Existing fish, bait, rods, roles, and inventory data are **not deleted by this code cleanup**.

## Command deduplication

Cinnamon's slash commands are defined **globally once**. Previous startup code additionally copied every global command into every guild, a plausible cause of duplicate command suggestions. On startup the bot now clears those obsolete *guild-specific copies* and syncs global commands. Two redundant top-level aliases, `/dailyquests` and `/weeklyquests`, were retired; use `/quests daily` and `/quests weekly`. The `/quest` launch command and prefix quest commands remain.

## Migration / testing

- Run automatic unit/integrity checks on GitHub Actions.
- Test slash-command visibility (including stale Discord client caches), interactive buttons and story rewards, Catnip persistence, role permissions, and the two-hour shop lifecycle on a real Discord guild after deployment.
- The older `/adventure`, `/fish`, and `/cook` code was **already inactive**, so those commands were not preserved as playable features. If intentionally reintroduced, rebuild them in active modules instead of restoring conflicting old registrations.
- The old files and documentation remain retrievable through Git history if needed.

**Note:** This document describes source configuration. Passing syntax/static checks does not prove live Discord and Render functionality.
