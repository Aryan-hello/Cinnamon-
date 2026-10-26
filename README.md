# Cinnamon — main features release

> **Security & UX release (October 26, 2026):** Fixes negative-Catnip transfer exploit; Cinnamon now answers only when pinged, replied to or directly called, with safe rare no-ping cameos. Admin-confirmed @everyone is the only mass-ping path. /setup has an optional Hangry channel picker, private rod/bait merchant shops, and Mood logs. Fishing gets bait selection and interactive reeling; story and dashboard received major UI improvements. Before public rollout, follow [CINNAMON_FINAL_DEPLOYMENT.md](CINNAMON_FINAL_DEPLOYMENT.md) and back up your persistent state.

> **Cinnamon social events (October 26, 2026):** Surprise Hangry Games now have random 1–2-hour scheduling, a two-minute Join window, exactly two Hangry Games role pings, and a 1,000–2,500 Catnip winner reward. Cinnamon also asks occasional optional questions, celebrates big moments, and logs mood/favourite/nice/naughty records in #cinnamon-stuff-logs. Re-run `/setup` after deploying and use `/cinnamon-events notify` to opt in. See [CINNAMON_SOCIAL_EVENTS.md](CINNAMON_SOCIAL_EVENTS.md).

> **Cinnamon mood & Hangry Games update (October 26, 2026):** `/mood status`, `/mood talk`, `/mood play`, and `/mood apologize` manage Cinnamon's playful server mood and temporary Naughty List. Mood modifies main-shop and merchant prices and fishing rarity odds. Hangry Games staff can add an optional Catnip winner prize under a weekly hosting budget; see [CINNAMON_MOOD_HANGRY_UPDATE.md](CINNAMON_MOOD_HANGRY_UPDATE.md) for rules and safety limits.

> **Wildlands update (October 26, 2026):** The active mystery is **The Treasure Worth Billions** with Cinnamon, Baron Clawdius, and a final **100,000 Catnip** (one-time) reward. Start with `/wildlands story`; use `/fishing start` for the separate fishing system. Fishing merchants open for two hours when discovered and permanently for story finishers. See [WILDLANDS_UPDATE.md](WILDLANDS_UPDATE.md) for current commands. The old `/adventure` and old `/fish`/`/cook` implementations are retired and are not loaded.


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

## Cinnamon Wildlands — existing Runway artwork import (Oct 24, 2026)

This update includes **50 references to artwork that was already generated in Runway**. It does not create new artwork or spend Runway credits:

- 46 transparent background-removed cutouts, kept as `cutout_01` through `cutout_46` because Runway's recent asset list did **not** identify which particular fish, rod, or bait each image portrays. They are *not* arbitrarily assigned item names.
- Four named fishing places: Woodland Fishing Pier, Moonlit Fishing Pool, Frostfall Fishing Spot, and Ruins Fishing Pool.

**Important: these are links, not image bytes.** The source URLs expire, with the earliest on **25 October 2026 at 14:12 IST**. For permanent images in the GitHub repository, include `tools/runway_art_urls.txt`, `tools/import_runway_art.py`, and `.github/workflows/import-runway-art.yml` in your GitHub commit **before that expiry**. The GitHub Action called **Save Cinnamon Runway artwork** automatically downloads, converts to optimized WebP, and commits up to 50 files under `static/wildlands/` on that push. Use GitHub → Actions → **Save Cinnamon Runway artwork** → **Run workflow** as a manual alternative, while the links are valid. The repository must allow GitHub Actions to write contents. Once saved in GitHub, the artwork is permanent across Render free-tier redeploys and no longer needs Runway URL authentication.

Runway image bytes could not be transferred directly into the ZIP in this environment. Import success must be verified in your repository's GitHub Actions log or using `/wildlands art-status` after deployment. This release does not claim that the image files are already bundled.

**New commands:** `/wildlands places` shows a polished gallery for the four locations; `/wildlands art-vault` is a staff-only numbered browser for the 46 unlabelled cutouts; `/wildlands art-status` reports installed files. Both galleries use responsive image-left/text-right cards generated by Pillow and Prev/Next buttons. The bot replies with a friendly message when artwork has not yet been saved instead of breaking. The artwork registry and `wildlands_local_asset(key)` helper can be connected to future Wildlands fishing, rod, and bait item screens after the exact cutouts have been matched by name.

This ZIP contains the previously supplied main bot/dashboard, with Wildlands art support added; **it does not yet contain the entire Wildlands gameplay system**, because that was not present in the supplied Cinnamon source archive. The remaining 24 older Runway images (environment, merchant, resource, lore, and encounter art) did not appear in the connected Runway recent-assets listing, so they are not included in this initial importer.

## Wildlands image files when you cannot reopen the Runway chat

This package works without displaying any image preview in ChatGPT. It contains
**links to 50 existing Runway generations**, not the underlying image bytes.
After uploading the whole project to GitHub, the included **Save Cinnamon Runway artwork**
GitHub Action runs on push and writes actual WebP images into your repository.
The bot also has an optional, background-only deployment fallback that attempts
to download any still-missing images on Render without blocking bot startup.
This fallback is enabled by default and can be disabled with
`CINNAMON_WILDLANDS_AUTO_FETCH=0`. Because Render free disks can reset, run
the GitHub Action to make the downloaded assets permanent.

**The uploaded ZIP is not an image ZIP.** No actual image files can be embedded
from that archive alone. The original 24 older images for environments, merchants,
resources, lore, and encounters remain missing from the Runway recent-assets list.
The 46 cutouts are intentionally unassigned until their specific identities can
be confirmed. To connect the images to named fish/rod/bait cards, the complete
Wildlands fishing gameplay source and an asset-to-item mapping are still needed.
