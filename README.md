# Cinnamon — main features release

Cinnamon is a single `discord.py` bot with modular feature files and a Flask dashboard. This release consolidates the main dashboard work and adds final guardrails for embed publishing and activity-log filtering. This package contains the main application files only. Live Discord/OAuth and Render behaviour still needs to be checked after deployment.

## Included

### Dashboard
- Live bot-ready status and the existing server overview.
- Mobile navigation retained, with an in-sidebar settings search that filters dashboard sections as you type.
- New **Automation Studio** hub for welcome/goodbye rules, always-on Cinnamon, AutoMod, anti-raid, recurring giveaways, and log/recovery links.
- Existing Moderation & Security, Levels & XP, Achievements, Quests, Friendship, Catnip Economy, Giveaways, Hangry Games, Community & AI, Message Studio, Analytics, Activity Logs, and Settings pages retained.
- Message Studio checks the combined title, description, and footer text against Discord’s 6,000-character embed limit before publishing.
- Activity Logs can filter recent retrieved events by category and search text. The view only searches the recent embed-based log sample fetched from configured channels, not all Discord history.
- Configuration backup download and validated JSON restore for the selected server. Restore rejects backups from another server and does not overwrite balances, inventories, user progress, active giveaways, tokens, or secrets.
- Existing role-based Catnip income controls and audit logging retained.

### Giveaways
- Start and end giveaways with up to 100 winners and durations up to one year.
- Button entry and optional reaction entry, using a configurable entry emoji.
- Required roles, bypass roles, blacklisted roles, minimum Discord account age, and minimum time in the server.
- Bonus entries by role (1–20 extra entries per configured role; role bonuses stack, and a person can win only once).
- Custom embed title/description/colour and custom entry, leave, and denied-entry messages.
- Optional timed winner role and optional winner thread with auto-close.
- Reusable templates (`/giveaway template-save`, `/giveaway template-list`, `/giveaway template-start`).
- Recurring schedules (`/giveaway repeat`, `/giveaway repeat-stop`) and dashboard schedule controls.
- Reroll a finished giveaway from saved history (`/giveaway reroll` or the dashboard).
- Persistent history for the most recent 250 finished giveaways; active giveaways, templates, schedules, timed roles, and timed threads are persisted through Cinnamon's existing data store.

## Existing giveaway commands

- `/giveaway start` — start a giveaway in the current channel.
- `/giveaway end` — end an active giveaway by message ID.
- `/giveaway reroll` — choose a different winner from a finished giveaway.
- `/giveaway template-save` — save an active giveaway as a template.
- `/giveaway template-list` — list saved templates.
- `/giveaway template-start` — start a giveaway from a template.
- `/giveaway repeat` — schedule a recurring giveaway.
- `/giveaway repeat-stop` — stop a schedule without cancelling any active giveaway already posted.

The dashboard provides richer entry-rule and embed settings than the compact `/giveaway start` command.

## Deploy on Render/GitHub

1. Download and extract `Cinnamon_main_only.zip`.
2. Replace the matching files in your existing repository with the files from the extracted package. Keep your Render environment variables and secrets unchanged.
3. Commit and push to GitHub, then wait for Render to deploy.
4. Keep `DISCORD_TOKEN`, `GEMINI_API_KEY`, Discord OAuth variables, and any Upstash credentials in Render's environment settings only; never put them in the repository or backup JSON.
5. Test the dashboard OAuth login on Render; this workspace cannot sign in to your Discord account or verify the live OAuth callback from here.
6. Test dashboard actions in a private test server and verify each action’s Discord permissions before relying on it in your main server.

## Storage and backup notes

Upstash is recommended when configured because local JSON storage may not survive a Render redeploy. Configuration backups are per-server and exclude member balances, inventories, XP/progress data, active giveaway message IDs, bot tokens, and API secrets. The existing `/recall` recovery scan remains available for supported information retained in configured log channels.

## Validation performed

- Python syntax compilation for `main.py`, `dashboard.py`, and every module.
- JavaScript syntax check for `static/dashboard-mobile.js`.
- AST-based rendering checks for all live dashboard page functions, including empty and populated giveaway states.
- Configuration backup export/restore round-trip and wrong-server rejection tests.
- Static checks for giveaway persistence, templates, recurring schedules, eligibility controls, rerolls, reaction entry handlers, timed roles/threads, and dashboard action routing.

These are offline/static checks, not a live Discord integration test. Real permissions, slash-command registration, and OAuth still need to be confirmed after deployment.

## Known limitations
- Analytics currently shows live counters, not historical charts. Historical charts require durable time-series collection that is not included here.
- Automation Studio organizes existing configuration; it does not run arbitrary scripts or provide a general-purpose automation rule engine.
- The configuration restore form validates and restores supported settings, but it does not yet provide a persistent staged review page that survives a process restart.
- Message Studio currently sends an embed with title, description, footer, colour and optional HTTPS image; editable fields/buttons and saved template versioning are not included in this release.
- Offline checks cannot prove that Discord OAuth, gateway events, slash-command registration, bot role hierarchy, or Render storage work in your live environment.


## Fishing & Cooking integration

Fishing is loaded as a module inside the existing Cinnamon bot. Fish catches and cooked dishes are stored in the normal economy inventory, not in a separate spendable item bag. Therefore `/economy feed` can feed a caught fish or cooked dish to Cinnamon, and the existing feeding quest/achievement hooks run normally. Fishing species and recipes are registered as non-shop items; players obtain them by fishing/cooking rather than buying duplicates from the shop. `/fish sell` and `/cook sell` remove items from that same inventory before paying Catnip. Older fishing data with separate fish/dish bags is migrated once into the shared inventory. Cooked dishes sell below the base value of their ingredients to prevent cooking from creating Catnip from nothing.

## Fishing and Cinnamon Memory

- `/fish catch`, `/fish inventory`, `/fish journal`, `/fish sell`, `/fish stats`, `/fish odds`, `/fish points`, `/fish upgrades`, `/fish upgrade`, and `/fish bond`.
- `/economy feed` supports the fish in the shared inventory. Feeding higher-rarity fish builds Cinnamon Memory and improves fishing luck.
- Fishing Points can be spent on Lucky Rod, Quick Cast, Angler's Instinct, Steady Hands, Golden Hook, and Market Sense upgrades.
- Fish and dishes are not shop stock in this version. Fish can be caught, fed to Cinnamon, or sold for Catnip.
- `/cookbook`, `/cook make`, `/cook inventory`, and `/cook sell` retain the 20-recipe cooking system.


Fish selling: each fish now sells for 3× its original base value (a 200% increase). Market Sense bonuses apply afterward; cooked-dish prices remain unchanged.

## Cinnamon: Wildlands — new exploration and crafting game

Wildlands is a persistent, server-specific adventure module built into Cinnamon. Its design uses general patterns found in established Discord RPGs: a compact button-led hub, quick encounters, area-based gathering, permanent crafting progression, achievements, and community discovery records. This release keeps Cinnamon's friendly cat theme and connects adventure play to the existing fishing, cooking, Catnip economy, daily/weekly quests, and achievements.

### Start playing

1. Use `/adventure start` once to create your explorer and receive starter supplies.
2. Use `/adventure play` to open your personal button-driven hub. **Explore** starts or resumes an encounter; **Status**, **Map**, **Pack**, and **Journal** open compact views without adding extra public messages.
3. Choose **Gather supplies**, **Investigate**, or **Follow tracks** for each encounter. The routes have different trade-offs: gathering is steadier, investigation leans toward clues, and tracks lean toward secrets.
4. Use `/adventure recipes`, `/adventure craft`, and `/adventure camp` to turn materials and Catnip into permanent gear and camp improvements.
5. Use `/adventure map` and `/adventure travel` to move through six areas as new gear and discoveries unlock them.
6. Use `/fish catch` and `/cook make` as usual. `/adventure pack` consumes one cooked dish from the same shared inventory for a bonus on your next expedition. Fish and meals are not duplicated into a separate Wildlands inventory.

### Wildlands commands

- `/adventure play`, `/adventure start`, `/adventure help` — the hub, account setup, and quick guide.
- `/adventure explore`, `/adventure status`, `/adventure map`, `/adventure travel` — encounters, progress, and area routes.
- `/adventure inventory`, `/adventure journal`, `/adventure leaderboard` — gathered materials, shared fishing/cooking items, personal discoveries, and server-first records.
- `/adventure recipes`, `/adventure craft`, `/adventure camp` — blueprints, permanent equipment, and camp upgrades.
- `/adventure pack`, `/adventure sell` — use cooked food for an expedition bonus or trade spare gathered materials for modest Catnip.

### Progress and fairness

- Wildlands progress is stored under Cinnamon's existing `advanced_features_data` persistence. It follows the same storage durability rules as the rest of the bot: configure Upstash for durable state on a Render service whose local disk can reset during a redeploy.
- Players have their own supplies and discoveries. The server records the first person to discover each unique secret, so exploration can create friendly competition without taking away another player's progress.
- Energy restores one point every two minutes. An unfinished encounter can be resumed with `/adventure explore` or the hub's Explore button without charging energy again. Encounters do not destroy already-collected materials.
- Wildlands awards XP, achievement progress, and selected daily/weekly quest progress. Milestone interactions are only recorded once per newly found clue, secret, or crafted blueprint to avoid turning repeated button clicks into free interaction farming.

### Validation status

All shipped Python files passed `py_compile` and AST parsing, and static checks confirmed that the Wildlands module is in the runtime load list with quest/achievement hooks. A live Discord integration test was **not** possible in this environment because the `discord.py` package was not installed and network access to install it was unavailable. After adding the ZIP to your repository, confirm slash-command sync and interaction behaviour in a private test server before relying on it in your main server.
