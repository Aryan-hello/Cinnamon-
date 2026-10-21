# Cinnamon Consolidated Fixes

This build is based on the uploaded `Cinnamon_giveaway_audit_fixes.zip`. It retains the earlier giveaway stacking/reroll patch and applies the following additional corrections.

## Fixed in this build

- **Duplicate slash commands:** command startup no longer copies the global command tree into every guild. On startup it clears stale guild-scoped copies left by earlier versions, then syncs the global command tree once.
- **Quest slash paths:** added `/quest daily`, `/quest weekly`, `/quest progress`, and `/quest overview`. The prefix command `?quest` remains available. `/quests daily` and the other compatibility commands remain.
- **Help embed overflow:** `/help` now packs command listings into fields below Discord's 1,024-character field-value limit. The previous 3,000-character packing threshold could make the help embed fail.
- **Slash-command diagnostics:** uncaught application-command failures are logged with tracebacks and return a useful ephemeral message rather than silently timing out.
- **Economy recovery:** reading a balance no longer writes a fake default account to storage. This prevents viewing `/economy balance` from blocking `/recall` after a data reset.
- **`/recall` money recovery:** absolute balance values in recent transaction logs can repair accounts left at the legacy default balance. Snapshot merge recovery can repair that same default case while preserving non-default live balances.
- **Name-search autocomplete:** shop item autocomplete now applies to buying, feeding Cinnamon, admin inventory add/remove, item info, and shop-item editing/removal. Achievement info/award/revoke and giveaway template/schedule selection also support readable suggestions.
- **OAuth callback diagnostics:** the dashboard login checks for non-empty OAuth credentials and validates that the configured callback is an HTTPS URL ending in `/oauth/callback`; invalid configuration now produces a clearer setup page.

## Verification performed

- Python source compilation: all 13 Python files passed `compile()`.
- JavaScript syntax: `node --check static/dashboard-mobile.js` passed.
- Static assertions checked the command-sync change, quest subcommands, help field limit, recovery logic, autocomplete registration, and OAuth callback validation.

## Still needs live verification or further implementation

I cannot test Discord's live command registration, a real OAuth exchange, role hierarchy, member-cache behavior, or Render persistence from this workspace. After deploying, test these in a private server first.

This build does **not** claim to finish every item from the original expanded giveaway specification. In particular, the complete 25-option preview/edit/cancel workflow, claim-deadline auto-rerolls, and every advanced eligibility requirement (such as message-count/level/boost/captcha/server-tag checks) are not all implemented. The current giveaway code has the previously patched stacking and reroll protections, role/account/server-age checks, templates/schedules and dashboard controls, but it still needs a separate feature-completion pass for those missing items.
