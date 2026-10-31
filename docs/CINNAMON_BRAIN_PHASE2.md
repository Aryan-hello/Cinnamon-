# Cinnamon Brain — Phase 2: reminders, preference memory, context, expression

**Branch:** `feature/cinnamon-brain-reminders-memory-context` (stacked on `feature/cinnamon-trusted-actions-v1`, draft PR #15).  
**Status:** Implemented on a development branch. **Not merged, deployed, live Discord-tested, or release-ready.**  
**Vision:** [Cinnamon Notion roadmap](https://app.notion.com/p/40adf5931d2381f4ac00cff68d650eb9).

## Implemented behavior

### 1. Personal reminders

Members can address Cinnamon directly or use:
- `/cinnamon-reminder create text:<task> when:<time>`
- `/cinnamon-reminder list`
- `/cinnamon-reminder cancel reminder_id:<ID>`

Natural-language examples:
- `@Cinnamon remind me to check quests in 30 minutes`
- `Cinnamon, could you please remind me in 2 hours to read`
- `@Cinnamon remind me to play tomorrow at 6 PM`
- `@Cinnamon remind me to read on 2026-11-05 at 7:30 PM`

Times are interpreted using existing `CINNAMON_TIMEZONE_OFFSET_MINUTES`, default UTC+05:30, and stored as UTC Unix timestamps. Ambiguous, past, empty, non-self and out-of-range requests are rejected or clarified. Range: one minute to 30 days. Reminders are delivered by DM to **the requesting member only**, with no ping of someone else.

The existing 15-second Cinnamon social scheduler also processes due reminders. There is **no new competing scheduler**. To avoid duplicate messages after crash, a reminder is durably marked `sending` *before* the DM is attempted. An uncertain or in-flight delivery is never automatically retried; if a bot dies between claim and send, one reminder may be lost rather than duplicated. Discord failures are marked `failed`. A reminder more than 24 hours late is marked `missed`, not delivered days after the fact. Completed records older than 30 days are pruned. Max ten active reminders per member per guild. Replayed Discord source IDs do not schedule again.

**Limitations:** Delivery depends on the bot being online, Discord permitting DMs, and working persistent storage. The default timezone is not individualized per member; requests explicitly display the timezone. Failed/uncertain statuses are visible in the private reminder list. No recurring reminders or arbitrary third-party pings in this release.

### 2. Private, limited preference memory

Only explicit preferences are stored. Cinnamon does **not** automatically archive general message history.

- `/cinnamon-memory status`
- `/cinnamon-memory enable enabled:false` — opt out and clear notes
- `/cinnamon-memory save category:<games|stories|hobbies|reply_style> detail:<preference>`
- `/cinnamon-memory view` — private/ephemeral
- `/cinnamon-memory forget note_id:<ID>`
- `/cinnamon-memory clear`
- `/cinnamon-memory correct note_id:<ID> new_text:<correction>`
- Owner-only `/cinnamon-memory tickets` and `/cinnamon-memory resolve`

Chat example: `Cinnamon, remember I like mystery stories`. Save acknowledgment in a public channel does not repeat the preference text.

Maximum 12 notes per member per guild, each 2–120 characters, with categories limited to ordinary entertainment/hobby/reply preferences. Validation rejects links, mentions, obvious secret/sensitive categories and instruction-like strings. Explicit user input is still not an unlimited privacy guarantee: do not save data you would not want the bot operator or infrastructure to access.

Only the **member's own guild-scoped notes** are supplied as a bounded, data-only context snippet to Gemini when that member invites Cinnamon. Other members' notes and notes from other guilds are never included. Member can inspect, delete, and disable notes at any time. Correction requests go to a private in-bot queue visible only to the guild owner. Erasure also scrubs open correction ticket contents; resolved tickets do not retain old note text.

**Limitations:** This is intentionally **not** a complete automatic long-term social memory or emotional profiling system. Preferences are limited and explicit. A later memory design may add privacy-reviewed summary extraction and better ticket notifications.

### 3. Serious-conversation boundaries and staff assistance

Heuristic, short-lived **content-free signals** detect phrases suggesting a serious discussion and suppress unsolicited games and social asides for fifteen minutes. No raw text is persisted as part of the signal. Model replies in that context are instructed to be gentle, helpful and non-teasing.

Authorized moderators can use `/cinnamon-incident review` to privately see up to twelve short chronological excerpts from the last 30 minutes in a channel they and Cinnamon can access. The review does **not** call Gemini to determine guilt; it explicitly explains the limits and requires human judgment. No automatic punishments, verdicts or stored transcripts are added.

**Limitations:** Keyword heuristics are not true semantic understanding; false positives and misses are possible. This release does not automatically ping staff about every argument or preserve full dispute evidence. Those need a separate privacy and moderation review.

### 4. Optional activity intelligence

Cinnamon now supports an approved activity choice: **wait**, **Hangry Games**, or **non-pinging community question** in the approved games channel.

- `/cinnamon-mind prompts enabled:<bool>` — allow no-ping community questions (default OFF)
- `/cinnamon-mind reasoning enabled:<bool>` — let Gemini recommend an activity from aggregates only (default OFF)
- `/cinnamon-mind status` — admin diagnostics
- `/cinnamon-mind independence enabled:<bool>` — emergency pause (existing)

The advisory Gemini call sees **only message count, distinct member count and Cinnamon mood**; no raw conversation content or private memories. JSON responses are confined to three allowed values. Invalid output or model failure results in **wait**. The Python eligibility gate checks storage health, enabled features, activity, available channel/role/permissions, serious-discussion context, game conflicts, and idle cooldowns both before and after the choice. No model output executes code or grants moderation/economy authority.

Without optional Gemini advice, the deterministic fallback selects approved opportunities conservatively, with a no-ping question at only some eligible opportunities if admins opted in. Questions get a response window and a long backoff after silence. Existing game role notification opt-in remains intact.

**Limitations:** The optional adviser makes bounded content-free decisions; it is not a full general autonomous AI agent. The existing opportunity scheduler is still 1–2 hours with activity gating, not an AI generating new schedules.

### 5. Better expressions and polite language

Gemini sees a shortlist of at most sixteen relevant existing guild custom emoji names, not a huge list of thousands. Returned reactions are checked for validity, and no reaction is added for recognized serious concerns. This is a preparatory emoji registry, **not** an uploaded 2,000 application-emoji collection.

The trusted action parser additionally recognizes polite wrappers such as `could you please add 20000 Catnip...`, without adding privileged tools or weakening the existing permissions/confirmation layer. The reminder and explicit memory parsers accept similar polite phrasing.

**Limitations:** General arbitrary-language-to-any-command execution is deliberately not supported. Only typed allowlisted administrative actions may execute; all other help stays informational.

## File map

| Purpose | Files |
| --- | --- |
| Reminder parsing and runtime | `cinnamon_modules/brain_reminders.py`, `cinnamon_modules/cinnamon_reminders.py` |
| Memory validation and runtime | `cinnamon_modules/brain_memory.py`, `cinnamon_modules/cinnamon_memory.py` |
| Serious conversation/incident assistance | `cinnamon_modules/brain_context.py`, `cinnamon_modules/cinnamon_incidents.py` |
| Activity suggestions | `cinnamon_modules/brain_decision.py`, `cinnamon_modules/cinnamon_brain.py`, `cinnamon_modules/cinnamon_personality.py` |
| Expression | `cinnamon_modules/brain_expression.py`, `main.py` |
| Command wiring | `cinnamon_modules/core_events.py`, `cinnamon_modules/brain_actions.py` |
| Dashboard | `dashboard.py` |
| Regression tests | `tests/test_brain_reminders_memory_context.py`, `tests/test_brain_expression_decision.py` |

## Validation and safety release gates

- [ ] Compile all Python modules, dashboard, tests.
- [ ] Run full existing and new offline suite under Python 3.11 and 3.12.
- [ ] Run real startup/registration test without network.
- [ ] Private test guild: retry the **same Discord source**, create/list/cancel reminder; restart before/after due time; disable DM and ensure status is honest.
- [ ] Test reminder timezones and DST limitations. Verify a sleeping Render instance cannot promise exact delivery.
- [ ] Private test guild: user memory opt-out, erase/correction workflow, privacy scope, Guild A vs Guild B, Gemini context prompts, forbidden sensitive values.
- [ ] Check only owners see correction tickets; admins cannot view other members' private notes.
- [ ] Confirm moderators cannot read channels where they lack history permission; review must be private.
- [ ] Test Hangry vs community prompt vs wait; disable admin switches and change role permissions **during** a launch.
- [ ] Test model output `ban`, invalid JSON, network failure; all yield wait/no action.
- [ ] Test mobile dashboard toggles and Discord slash command name registration for duplicates.
- [ ] Confirm full legacy games/economy/story/quests/achievements work in test guild.
- [ ] Take a **private off-repo backup** before any test deployment to Render/Upstash.
- [ ] Review the stacked PR dependencies (#13, #14, #15); merge in safe order after real-world verification.

**Never claim production-ready or AI-complete before the above release gates pass.**
