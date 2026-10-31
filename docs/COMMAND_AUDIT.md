# Cinnamon Command Audit — 31 October 2026

**Source of truth:** `bot.tree.get_commands()` and `bot.walk_commands()` at runtime, not hardcoded lists in Markdown or chat prompts. The audit is implemented on [draft PR #19](https://github.com/Aryan-hello/Cinnamon-/pull/19), stacked on the storage diagnostics in [PR #18](https://github.com/Aryan-hello/Cinnamon-/pull/18). This document is a development record, not a production certification.

## Findings corrected

| Previously outdated or broken | Updated behavior |
| --- | --- |
| Slash `/help` grouped up to **3,000 characters in one embed field**, above Discord's 1,024 maximum | Pages derive from the live registered command tree and cap each field at 940 characters; page navigation stays interactive |
| Prefix `?help` used an old static command list without memory/reminders/Brain or current subcommands | Reads the live prefix command registry, including nested command names, signatures and aliases; all pages bounded |
| `/ping`, `/botstatus` appeared in help but had no real slash-command registration | Both now register as real slash commands |
| `?botstatus` claimed everything was healthy without storage checks | Shows gateway latency, backend, snapshot health and confirmed Catnip readiness truthfully |
| Slash `/botstatus` and `/setupstatus` exposed backend names without action readiness | Now show current snapshot and action readiness; defer interactions before potentially slow status checks |
| Legacy `/datastatus check` said local JSON was "connected" although it was not verified durable storage | Parent [PR #18](https://github.com/Aryan-hello/Cinnamon-/pull/18) replaces it with actual selected backend, partial-credentials detection, snapshot state, and Catnip action readiness |
| Catnip add conversation returned only "durable storage isn't ready" | This branch also integrates the reason-specific safe refusal from parallel [PR #17](https://github.com/Aryan-hello/Cinnamon-/pull/17), without changing the existing security gate |
| Prefix `?rank` advertised nonexistent `?level` | Refers to the real `/rank` |
| Income-role setup messages and a quest suggested nonexistent `/collect` | Refers to the real `/economy collect` |
| `/cinnamon-events questions` said Cinnamon would never send reminders | Clarifies that optional questions are separate from member-requested reminders |
| `/cinnamon-events notify` promised exactly two alerts | Says **up to two**, consistent with no repeat ping after an unanswered lobby |
| `/cinnamon-mind status` described only game timing and reported generic storage status | Describes AI/administrative status and distinguishes confirmed Catnip actions being ready or blocked |
| Old `_HELP_EVERYONE` and other `_HELP_*` references were stale | Removed unused static lists; live command registry is canonical |
| README and startup doc listed legacy dashboard session variable and suggested `/logchannel` as storage check | Documents `DASHBOARD_SECRET_KEY`, `/datastatus check`, and the actual durable-storage requirement |

## User-facing command directory

- `/help` — registered **slash** commands, grouped and paginated safely. Includes economy, quest, achievement, fishing, story, levels, games, Brain and administrator commands when loaded.
- `?help` and `?commands` — registered **prefix** commands with aliases and argument syntax. No manually synchronized static list.
- `/ping`, `/botstatus`, `?botstatus` — gateway/health commands with accurate storage caveat.
- `/setupstatus` — channel/configuration overview plus storage-action readiness.
- `/datastatus check` — administrator-only detailed storage/snapshot/action diagnostic.
- `/cinnamon-mind status` — administrator-only AI and independent activity status.
- For member-facing new features, use `/cinnamon-reminder`, `/cinnamon-memory`, `/quests`, `/achievement`, and `/economy` subcommands shown in the live directory.

**Do not confuse** `/quest` (quest board) with `/quests daily` and `/quests weekly` (specific lists). The real command paths are shown by `/help`. `/economy admin addcatnip` still requires real Administrator authority and a ready durable snapshot, even if the slash command appears in the directory.

## What was checked

- Static review of registrations and user-facing command references across economy, quests, achievements, moderation, games, stories, fishing, personality, AI, and setup modules.
- Automated verification of registered slash and prefix tree, alias/argument lists, no duplicate slash paths on startup, and help pages below 1,024 characters.
- Command and diagnostic tests for outdated references and local/remote storage readiness.
- Python 3.11 and 3.12 CI checks must pass before review/merge.

**Not a blanket claim:** This audit updates the registered-command directory, stale references and misleading status diagnostics. It does **not** constitute an end-to-end live Discord test of every game, slash callback, moderation action, or data migration.

## Deployment prerequisites

1. Review overlapping PRs **#17** and **#18**; this audit incorporates #18 and equivalent safe error messaging from #17. Do not merge overlapping patches twice without comparing them.
2. Preserve a private backup of any existing local Catnip/economy data before changing Render storage. Never place tokens or data dumps in GitHub.
3. Configure both Upstash REST credentials on the **actual bot service**; local JSON on Render Free is not proven durable. Do not use `CINNAMON_ALLOW_LOCAL_ACTIONS=true` on ephemeral storage.
4. Deploy only after review. Run real slash-command sync; check `/help`, `?help`, `/ping`, `/botstatus`, `?botstatus`, `/setupstatus`, `/datastatus check` and important feature commands in a private Discord test server.
5. Test navigation on mobile, Discord role permissions, command availability in the server, and actual snapshot health after restart.
6. Do not declare live or production readiness from green unit tests alone.

## Follow-up audit: remaining stale references found and corrected

A second sweep of the command implementation and older setup notes found:

- `/levelrewards add` was still linked from the empty level-rewards screen. The registered command is `/level-rewards add`; corrected and regression-tested.
- `/cinnamon-events test-game` promised exactly two role alerts. Current code posts **at most two**, with no second role alert when nobody joins; corrected.
- Personal reminder and memory save confirmations named only bare command groups that Discord cannot directly execute. They now link explicit `/cinnamon-reminder list`, `/cinnamon-reminder cancel`, `/cinnamon-memory view`, and `/cinnamon-memory forget` subcommands.
- The live prefix help directory was showing a nested alias like `?todays` for a `?quest daily` alias, dropping the parent path. Nested aliases now retain their full invocation path and are covered by tests.
- The old `CINNAMON_SOCIAL_EVENTS.md` described pre-Brain scheduling, exactly two pings, a public cancellation tantrum, a mood penalty and Manage Server permissions. It has been rewritten to reflect the **current** engagement-gated/permission-gated behavior.
- Historic achievement/quest and deployment guides were relabeled or updated so their commands and release status do not masquerade as current authoritative instructions. `CINNAMON_CHAT_ACTIONS.md` no longer claims its already-merged implementation exists only on an unmerged feature branch.

**Remaining limitations:** Most historical release-note files are intentionally preserved for change history, not current deployment guidance. Static scanning and offline tests cannot guarantee that every command callback works in live Discord. Before deploying, check current slash-command synchronization, mobile help pagination, permission behavior, rewards, and the actual configured Upstash snapshot. PR #19 remains stacked on PR #18; PR #17 overlaps these storage changes and should not be independently merged without reconciliation.
