# Cinnamon

A Discord bot built around a Catnip economy, interactive games, community tools, and a companion web dashboard.

**Stack:** Python 3.11+ · discord.py 2.7+ · Flask · optional Upstash Redis · Google Gemini for Cinnamon's conversation features.

## Features

| Area | What members can do |
| --- | --- |
| Catnip economy | Earn, transfer, spend, and track Catnip; browse items and inventory. |
| Quests and achievements | Complete daily/weekly objectives, track milestones, and unlock rewards. |
| Wildlands | Play a choice-driven treasure mystery, explore locations, and collect fishing gear. |
| Fishing | Choose bait, wait for a bite, hook, and fight fish using interactive controls. There is no post-cast 30-second cooldown. |
| Hangry Games | Join hosted games and compete for server rewards. |
| Community | Levels, role income, giveaways, moderation, and server setup. |
| Dashboard | Discord OAuth login for authorized server-management features. |

Cinnamon uses both traditional Discord embeds and **Components V2**. The shop, inventory, quest board, and achievement collection use structured interactive panels. See [Discord UI guidelines](docs/DISCORD_UI.md) for the component conventions and release checklist.

## Run locally

1. Create an application and bot in the Discord Developer Portal. Enable the **Message Content** and **Server Members** privileged gateway intents required by the existing features.
2. Copy `.env.example` to `.env`. Set `DISCORD_TOKEN` and `GEMINI_API_KEY`. For the dashboard, also set the Discord OAuth client ID/secret, `DASHBOARD_SESSION_SECRET`, and the exact `DASHBOARD_REDIRECT_URI` registered in Discord.
3. Install requirements and start the combined bot/dashboard process:

   ```bash
   python -m pip install -r requirements.txt
   python main.py
   ```

4. Invite the bot using only the permissions it needs. Place its role above roles it must manage. Run `/setup` in a private test server before public use.

Never commit `.env`, tokens, session secrets, or exported member data.

## Deployment and data

The included `render.yaml` describes one Render **web** service running `python main.py`. Free web instances can sleep; **the deployment configuration does not guarantee an always-online Discord connection**.

For ephemeral hosting, configure `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` so balances, story progress, and settings survive redeploys. Without remote storage, the bot uses local JSON files, which can be lost when an ephemeral filesystem resets.

Render's HTTP endpoint and the Discord gateway connection are separate concerns. A healthy web endpoint **does not prove the bot successfully logged in**. Check deployment logs and Discord connectivity after every release.

The existing `DISCORD_RETRY_SECONDS` controls the interval following a failed Discord login; it does not bypass Discord rate limits.

## Repository structure

```text
main.py                   Discord bot entry point and modular loader
cinnamon_modules/         Commands, game systems, shared UI, and moderation
dashboard.py              Flask dashboard
Static/ and static/       Dashboard assets and Wildlands art registry
tests/                    Offline regressions and UI contract checks
.github/workflows/        CI and repository automation
docs/                     Current development guidance
```

The feature modules execute inside a **shared namespace** loaded by `main.py`; they are not standalone Python programs. The loading order is intentional. When changing the UI, preserve compatibility between legacy `discord.ui.View` embeds and Components V2 `discord.ui.LayoutView` messages.

## Checks before merging

```bash
python -m compileall -q main.py dashboard.py cinnamon_modules tests
python -m unittest discover -s tests -v
```

Automated tests cover formatting, selected game logic, and code contracts. They **do not** replace a live test-guild pass. Check interactions on Discord mobile and desktop, button ownership, timeout behavior, currency integrity, dashboard OAuth permissions, and persistence after a process restart.

## Documentation

- [Discord UI & interaction guidelines](docs/DISCORD_UI.md)
- [Deployment and safety checks](CINNAMON_FINAL_DEPLOYMENT.md) — historical release notes may describe older mechanics; use current code as the source of truth.
- [Chat actions and consent rules](CINNAMON_CHAT_ACTIONS.md)
- [Quest and achievement notes](README_CINNAMON_ACHIEVEMENTS_QUESTS.md)
- [Release history](CINNAMON_RELEASE_NOTES.md)

## Project status

Features on `main` are implemented and have offline regression coverage. Live behavior depends on the configured Discord application, permissions, network connectivity, and persistent storage. New changes should be developed in a short-lived branch, checked in CI, merged through a pull request, and cleaned up after merging.

