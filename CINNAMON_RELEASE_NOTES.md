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
