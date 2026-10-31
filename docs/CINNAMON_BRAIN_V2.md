# Cinnamon Brain v2 — Useful, Personal, Explainable

**Started:** 31 October 2026  
**Development branch:** `feature/cinnamon-brain-v2-personal-utility`  
**Stacking:** Based on `fix/cinnamon-live-command-audit` (PR #19), which depends on storage diagnostics PR #18. The parallel storage fix PR #17 overlaps and must be reconciled before merging.  
**Status:** First implementation increment complete in source, **not merged or deployed**; offline tests and private-guild acceptance are mandatory.

## Design direction

Brain v1 established deterministic verified action requests, durable-store requirements, limited explicit member preferences, self-reminders, optional independence, tone boundaries, and registry-backed feature help.

Brain v2 should evolve into a **useful cat companion**, not a model with unrestricted server permissions. The priorities are:

1. **Useful before flashy** — save members time with a private, accurate view of their tasks, quest progress, preferences and Catnip.
2. **Personal without spying** — read only existing, guild-scoped, member-owned records; never auto-store raw chat transcripts as personal memory.
3. **Clear control** — users can correct their own benign preferences, set their own reminder timezone, snooze reminders, or disable/delete memory.
4. **Explainable behavior** — real registered command names, reason codes, precise status, safe corrections for ambiguous intents.
5. **Safe autonomous activity** — optional, quiet by default; never treat Gemini's suggestions as permission to alter balances, moderate members or ping everyone.
6. **Shared infrastructure** — one Discord process, one scheduler, current snapshot serializer, no extra free-tier background services.

## Brain v2 Increment A — implemented

### Personal timezone

New `/cinnamon-reminder timezone` command:
- With no argument: privately shows the effective timezone and whether it is a personal setting or the server default.
- With `offset:UTC+05:30`, `offset:UTC-04:00`, or `offset:UTC`: records the member's **explicit fixed UTC offset**, in the reminder system's existing `advanced_features` snapshot.
- With `offset:server`: removes their override and uses the server's configured default.
- Values must be within UTC−12:00 and UTC+14:00. This is **not geolocation**. Fixed UTC offsets **do not follow daylight saving transitions automatically**.
- Changing the setting affects **future reminder parsing only**. Already scheduled UTC due timestamps are unchanged. Each member and guild is isolated.
- On an unacknowledged storage write, the old setting is restored and no success is claimed.

### Reminder snooze

New `/cinnamon-reminder snooze reminder_id:<ID> minutes:<1–1440>`:
- Only changes the caller's own **scheduled** reminder in the current server.
- Adds a delay to the later of the existing due time and the present time.
- Refuses already delivered/claimed, expired or cancelled reminders, unknown IDs, invalid durations, and final times beyond 30 days.
- Takes the existing reminder lock and saves before acknowledging; a failed save restores the previous due time and metadata.
- The original at-most-once DM-claim workflow and existing 15-second scheduler remain unchanged. **No new external timed process** is introduced.

### Self-editable preference memory

New `/cinnamon-memory edit note_id:<ID> new_text:<text>`:
- Members can correct **their own** preference immediately without waiting for the server owner.
- Maintains the original benign category; uses the existing validation that rejects sensitive secrets, links, mentions and instruction-like data.
- Refuses a member-disabled memory, unknown note, or duplicate preference.
- Any old open correction ticket for the edited note is withdrawn and its original/proposed text scrubbed.
- Failed snapshot writes roll back the note and tickets together. Existing owner ticket commands remain compatible, but are no longer required for ordinary self-edits.
- Turning memory off now also scrubs **both** the original and proposed text of open tickets.

### Private “My Day” and privacy guide

New `/cinnamon-me today`:
- Ephemeral, **current-member-only**, current-guild-only.
- Lists up to five scheduled reminders due on that member's current local calendar date.
- Includes a count of all pending reminders and explicitly saved preference notes.
- Displays **read-only** saved Catnip balance, Quest Points and today's completed daily-quest count when a valid snapshot is loaded. It does not roll quests, grant rewards or change balances.
- If stored data is not loaded, shows an honest warning rather than making up a wallet balance.
- Offers shortcuts to actual registered reminder/memory commands and notes that DM delivery needs Cinnamon online and DMs enabled.

New `/cinnamon-me privacy`:
- Private, factual explanation of what Cinnamon stores and how to view/edit/delete personal preferences, reset timezone, cancel reminders, and disable memory.
- Explains that bot operators/storage providers may access stored data; does not falsely promise end-to-end privacy.

Cinnamon's **registry-backed help** now recognizes the new commands for timezone, snooze, member profile, and self-editable memory.

### Architectural constraints kept

- No autonomous balance changes, staff role changes, bans, kicks, timeouts or `@everyone`.
- No user-agent interaction history exported by the activity adviser.
- No changes to Gemini's execution boundary, confirmation cards, permissions or durable receipt protocol.
- Reminder and memory operations stay in the existing shared snapshot and use the existing locks/scheduler.
- Ordinary member data does **not** cross guild boundaries.
- No inference of real-world location or sensitive personal details.
- No new database migrations needed: per-member timezone overrides are optional fields under the existing reminder state.

## Brain v2 Increment B — deterministic intent routing (implementation in progress)

A pure planner in `cinnamon_modules/brain_intent.py` classifies the current request as reminder, memory, help, action-like, or ordinary chat. The shared assistance dispatcher tries the corresponding existing Python handler first, then preserves the existing safe fallback order.

- Classification uses only the current member-authored request; it does not inspect channel history or send additional content to Gemini.
- A route is not permission, consent, or execution authority. Existing reminder/memory validators, action parsing, Discord permission checks, durable receipts and confirmation controls remain responsible for their own operations.
- Uncertain text stays ordinary chat. Action-like requests are routed to the existing action validator instead of being treated as harmless chat.
- Tests cover intent classification and shared dispatcher integration. GitHub Actions is still running for the latest commit; failures from earlier intermediate commits are being corrected and are not release evidence.

## Proposed next increments

### B1 — Private progress view (implemented on the stacked development branch)

- `/cinnamon-me progress` privately combines the member's existing level/XP, XP-to-next-level, quest history and Quest Points, current daily/weekly completion counts, and unlocked achievement totals.
- Reuses the bot's own level-threshold functions; no duplicated XP formula.
- Read-only and ephemeral; it never awards XP, rotates quests, unlocks achievements, changes Catnip, or writes state.
- Missing saved quest data is reported as unavailable rather than guessed.

### B2 — Deterministic intent planner (implemented on the next development branch)

- Routes only the **current member-authored request** into reminder, memory, help, trusted-action, or ordinary-chat handler order.
- Explicit reminder and memory language is recognized before generic help/chat. Personal phrases such as "show my progress" and "my day" reach the existing registered help.
- The planner is a routing hint only: it has no Discord, Gemini, storage, permissions, or execution dependencies.
- Existing trusted Python handlers remain the only place that can save a reminder, change memory, or propose an admin action. Their original requester, guild, permission, confirmation and durable-write checks are unchanged.
- Uncertain text falls back to the normal conversation path. Quoted/history text is never fed back into the planner as an executable request.
- Regression tests cover memory save/view/forget, reminder requests, progress questions, action-like requests and casual chat. A memory-regex escaping bug discovered by CI was corrected before final verification.

### B — Better answers and safe action planning

- Expand explainable read-only help: current quest progress, feature status and known cooldowns, with permission-aware views.
- Show the member exactly what Cinnamon understood before executing any consequential action.
- Expand explainable read-only help: current quest progress, feature status and known cooldowns, with permission-aware views.
- Add “I don’t know” responses rather than hallucinated commands, balances or settings.
- Treat channel conversation excerpts and saved preferences as **untrusted data**, never instructions.

### C — Better opt-in memory

- Support self-selected memory categories, correction and deletion with clear lifetimes and opt-out.
- Expire records that no longer help; retain only intentionally saved non-sensitive preferences.
- Review privacy before adding any optional automatic summaries. Do not build hidden emotional profiles.
- Let members see which of their own notes influenced an answer (without revealing private model prompts).

### D — More reliable time features

- Investigate IANA timezone support and daylight-saving transitions after adding bundled timezone data; do not guess timezones by IP.
- Add **opt-in** gentle recurring reminders and snooze/acknowledgment buttons only after idempotency and restart behavior are tested.
- Design for delayed/offline Render instances: no claim of exact-on-time delivery unless hosting supports that guarantee.

### E — Improved tasteful independence

- Keep the activity adviser metadata-only and bounded.
- Offer additional opt-in server activities without farming Catnip rewards or sending repeat pings.
- Add observable “why I did/didn't speak” reasons for administrators and avoid interfering with conflict, grief, exams or sensitive questions.
- Move toward curated application-owned emojis in a staged, validated registry.

## Acceptance tests to complete before merge

- [ ] Full Python 3.11/3.12 offline suite and compile/startup checks, including duplicate slash command registration.
- [ ] Private Discord server: personal timezone UTC+05:30 and another member's UTC−04:00; verify isolation and no changes to past reminders.
- [ ] Create, snooze, cancel and deliver one reminder; restart during an unsent and already-sending reminder.
- [ ] Reject snoozing a pending reminder belonging to another member or guild.
- [ ] Edit one preference and verify Gemini only sees the caller's own current guild notes; disable memory and verify no note or ticket content remains.
- [ ] Test My Day on both healthy and unavailable snapshots; no false or changed balances, no quest resets.
- [ ] Verify all member views are ephemeral and permission checks stay in place.
- [ ] Validate Android/mobile slash command parameters and help directory pagination.
- [ ] Backup existing economy/snapshot records and reconcile storage PRs #17–#19 before merging.
- [ ] Verify Render deployment and Upstash persistence in a private test environment. GitHub tests are not live acceptance evidence.

**Please do not merge or auto-deploy this incremental branch before these release gates are reviewed.**
