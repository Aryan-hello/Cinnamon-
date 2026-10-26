> **Historical release notes.** The October 23 exploratory Wildlands implementation and older fishing/cooking module described below are no longer loaded. They were removed from source on October 26, 2026. The active story and merchant commands are documented in [WILDLANDS_UPDATE.md](WILDLANDS_UPDATE.md). The notes below are retained for historical context, not current user instructions.

# Cinnamon Main Features Release Notes

## Dashboard
- Added a search field and category filter to the recent activity-log viewer. Filters apply to the latest events retrieved from configured log channels; they do not pretend to search the server's entire Discord history.
- Message Studio validates the combined title, description, and footer length against Discord's 6,000-character embed text limit before sending.
- Added Automation Studio as a central hub for welcome/goodbye rules, always-on Cinnamon, AutoMod/anti-raid status, recurring giveaways, and system links.
- Added sidebar search that filters settings sections live.
- Added per-server JSON configuration backup download and validated restore. Restore rejects cross-server files and only changes supported configuration sections; it preserves economy balances, inventories, user progress, active giveaways, tokens, and secrets.
- Retained the responsive mobile navigation, live gateway readiness, role-income controls, activity logs, analytics, message studio, recovery scan, and existing feature pages.

## Giveaways
- Added persistent finished-giveaway history and rerolls.
- Added reusable templates and recurring giveaway schedules, both persisted across restarts.
- Added role eligibility requirements, bypass roles, blacklisted roles, minimum account age, minimum server membership age, and stacked bonus entries.
- Added custom embed title/description/colour, entry emoji, entry/leave/denied messages, and optional reaction-based entry.
- Added optional timed winner roles and auto-closing winner threads.
- Expanded giveaway limits to 100 unique winners and up to one year.
- Added dashboard controls for the above, plus schedule stop, template save/delete, and history reroll.

## Validation and limitations
- Python syntax checks passed for all shipped Python files.
- `node --check static/dashboard-mobile.js` passed.
- Dashboard page rendering, backup round-trip, wrong-server backup rejection, and static giveaway/persistence checks passed offline.
- No live Discord server, OAuth login, slash-command sync, or role-permission operation was executed in this environment. Verify these after deploying.
- Platform-specific features that depend on Discord account/server-tag data not exposed reliably through the current bot model, and external giveaway-directory promotion/voting features, are not included.

## Honest limitations
- Analytics are live runtime counters, not historical charts; the bot does not yet record a time series for charts.
- Activity log search is limited to the recent embed-based events fetched from configured channels.
- Automation Studio is a hub for the bot's existing welcome/goodbye, AI-channel, AutoMod, anti-raid, and logging settings; it is not an arbitrary user-defined script engine.
- Configuration restore is validated and scoped to the selected server, but this release does not provide a persistent staged-review workflow across dashboard restarts.
- This package has not been tested against a live Discord server or a live Render deployment.

## Fishing & Cooking compatibility update

- Integrated the Fishing & Cooking module into the current Cinnamon main-module load order.
- Fish species and all 20 cooked dishes are registered as non-shop items in the existing economy item catalogue.
- Fishing catches, cooking ingredients, and cooked dishes use the same inventory as `/economy feed`, so caught fish and cooked dishes can be fed to Cinnamon and trigger the existing feeding quests and achievements.
- `/economy feed` now uses searchable name autocomplete based on items the member actually owns, including fishing catches and dishes.
- Selling fish or dishes removes them from the shared inventory before paying Catnip; cooking resale values are capped below ingredient value to prevent Catnip-generation exploits.
- Added one-time migration for existing separate fishing fish/dish inventories into the shared economy inventory.
- Added fishing/cooking quest metrics to the existing daily and weekly quest pools.

## Fishing feature refinement (shop plan removed)

- Removed the experimental fish-shop plan: all 20 fish and all 20 dishes are explicitly marked as not purchasable through the shop.
- Improved `/fish sell` with an upgradeable sale-value bonus, shared-inventory validation, Catnip payout, quest progress, achievements, and economy logging.
- Feeding Rare/Epic/Legendary/Mythical fish now builds Cinnamon Memory by rarity (1/2/3/5), capped at 100. Memory milestones are shown by `/fish bond`.
- Fishing luck is calculated consistently and bounded: Cinnamon Memory contributes up to 20% luck strength, Lucky Rod adds up to 10%, and `/fish odds` shows current rarity chances.
- Added Fishing Point upgrades: Lucky Rod, Quick Cast, Angler's Instinct, Steady Hands, Golden Hook, and Market Sense.
- Fishing stats now display the correct XP award, memory cap, and luck strength. New data continues to use the existing persistent advanced-feature store.


### Fish selling prices
Fish sale values were increased by 200% (3× original base value). Market Sense applies on top; cooked-dish sale values are unchanged.

## Cinnamon: Wildlands playable adventure

- Added `cinnamon_modules/wildlands.py` and loaded it after economy, fishing/cooking, quest, achievement, and Hangry Games modules so it can reuse the existing shared runtime and persistence layer.
- Added `/adventure play`, a personal button-driven hub with Explore, Status, Map, Pack, and Journal views. Encounters replace the hub in place, then provide a button to return to the hub, keeping the game from flooding a channel with many messages.
- Added six explorable regions, area-specific material yields, randomized encounters, three choice types, energy regeneration, personal XP/levels, searchable crafting blueprints, permanent gear, camp upgrades, and discovery journal entries.
- Added unique hidden locations and clues. The server records first discoveries, alongside a personal discoveries leaderboard.
- Integrated Wildlands expeditions/materials/clues/crafting/camp upgrades and starting-area visits with existing achievement and quest tracking. Added six achievements, three daily quest options, and three weekly quest options.
- Connected existing fishing and cooking: Wildlands shows shared fish/dish inventory, and packing a cooked dish consumes it once in exchange for a bonus on the next encounter. No duplicate fish shop or separate fish inventory was created.
- Corrected progression so an expedition counts only after its encounter is resolved. Travelling now stops cleanly when an encounter is pending; existing pending encounters can be resumed without paying energy again.
- Energy now restores at one point every two minutes. The adventure is designed for short interactions and does not delete gathered materials when an encounter fails to yield a rare discovery.

## Wildlands validation and limitations

- `py_compile` passed for `main.py`, `dashboard.py`, and all module files.
- AST parsing passed for all 15 Python files in the package.
- Static checks confirmed that the adventure group includes its expected commands, the runtime module load list includes Wildlands, and the quest/achievement events exist.
- The live import/Discord command-registration smoke test could not be run here: `discord.py` is not installed in the environment, and package installation failed because network DNS was unavailable. This is not a live Discord test. Slash commands, component interactions, permissions, and the deployment's data persistence still need validation in a private test server.
