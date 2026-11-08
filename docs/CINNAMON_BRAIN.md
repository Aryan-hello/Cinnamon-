# Cinnamon Brain: trusted actions, help, and bounded independence

> **Historical Phase 1 implementation notes (31 October 2026).** The release
> status and prerequisite PR text below describe the project at the time Phase 1
> was authored. PRs #13–#16 have since been merged into `main`; the Phase 2
> reminder, explicit preference-memory, and optional adviser code is present.
> **No full live Discord/Render/Upstash acceptance test is recorded yet.**
> For the latest implementation, see [Phase 2](CINNAMON_BRAIN_PHASE2.md),
> [current command audit](COMMAND_AUDIT.md), and the running bot's `/help`.


## Release status

This is the first implementation increment of [Project Cinnamon's roadmap](https://app.notion.com/p/40adf5931d2381f4ac00cff68d650eb9).
It builds on [Brain v1, PR #14](https://github.com/Aryan-hello/Cinnamon-/pull/14)
and reuses [the persistence/dashboard fixes in PR #13](https://github.com/Aryan-hello/Cinnamon-/pull/13).
Neither prerequisite is silently merged into `main` by this work.

| Capability | Planned | Implemented | Offline tested | Live tested | Ready for release |
| --- | --- | --- | --- | --- | --- |
| Typed Catnip/timeout actions and confirmations | Yes | Yes | Yes | No | No |
| Registry-backed command and feature assistance | Yes | Yes | Yes | No | No |
| Checked snapshots, action receipts, uncertain-write recovery | Yes | Yes | Yes | No | No |
| Brain v1 scheduler boundary fixes and dashboard switches | Yes | Yes | Yes | No | No |
| Persistent reminders | Next increment | No | No | No | No |
| Persistent private member memory and correction tickets | Later phase | No | No | No | No |
| Semantic serious-discussion/incident assistance | Later phase | No | No | No | No |
| Expanded personality/emoji system and authored stories | Later phase | No | No | No | No |

The private Discord/Render/Upstash acceptance checks below are release gates.
Source compilation, mocked Discord interactions, and temporary-file persistence
do not establish production readiness.

## Audit and architecture

The audit examined `main@c1eb4b6`, Brain v1 `db1b450`, and persistence fixes
`421c536`. Their separate baselines passed 52, 60, and 70 offline tests,
respectively. Existing reusable components include the shared-namespace loader,
Gemini conversation generation and central character prompt, mood helpers,
economy dictionaries/logging, slash registry, confirmed moderation, Hangry Games,
and Flask OAuth/CSRF controls.

The audit found swallowed storage errors, unsafe replacement after failed startup
loads, negative slash currency amounts, confirmation/cancel races, stale help
paths, overly broad dashboard read access, and surprise-lobby checks that did not
repeat after permissions or switches changed. This increment addresses those
boundaries without replacing the bot, games, or authored stories.

The runtime flow is:

1. Existing prefix/mention/reply/name dispatch and channel restrictions.
2. Deterministic help from current command metadata, or deterministic action recognition.
3. A frozen typed proposal from a four-action registry, plus independently obtained Discord identities.
4. Permission, target, argument, settings, source-age, and storage validation.
5. Original-requester confirmation, with fresh authorization before execution.
6. Trusted Python execution, durable receipt, best-effort private Discord log, truthful response.

Pure `brain_actions`, `brain_help`, and `brain_storage` modules import normally;
the existing runtime feature modules still load into one shared namespace. Gemini
remains a display-only conversation provider. No model output, channel history,
or arbitrary code enters the executor. Mood affects phrasing, never authority.

### Supported requests

Enable conversational actions only in the private test guild initially:
`/cinnamon-mind actions enabled:true`. They default to **off** per guild.

| Request | Required authority | Limits |
| --- | --- | --- |
| `Cinnamon, add 20,000 Catnip to @Member` | Owner/Administrator | 1–1,000,000 Catnip |
| `Cinnamon, remove 500 Catnip from @Member` | Owner/Administrator | Same limit; sufficient, unchanged confirmed balance |
| `Cinnamon, mute @Member for 5 minutes` | Timeout Members or Administrator | 1 second–24 hours; hierarchy and protected-target checks |
| `Cinnamon, unmute @Member` | Timeout Members or Administrator | Same target protections |
| `Cinnamon, mute this member for 5 minutes` | Same moderation authority | Must reply to that member's actual message |
| `Cinnamon, how do I fish?` | Member | Current registry-backed guidance |
| `Cinnamon, what does /recall do?` | Member may ask | Explains recovery; does not invoke it |

The `?ask`, `?ai`, and `?chat` aliases share this help/action path. Requests for
deferred reminders or chat game launches receive explicit capability guidance;
they do not fall through to a claim that something was scheduled or started. There is no new
`/ask` command. Unfamiliar action wording receives clarification rather than a
Gemini-chosen action. Compound requests, guessed numeric IDs, multiple ambiguous
targets, and non-positive or incorrectly grouped amounts are refused.

Chat kick/ban execution is suspended pending separate review; existing slash
commands remain available. No autonomous disciplinary timeouts are introduced.
Existing doubly opted-in 1–10-second prank behavior remains a separate legacy
feature; recognized help/actions bypass it.

Confirmations expire after 60 seconds or restart. They identify the target and
requester, permit only the original requester, and keep one pending/executing
request per requester per guild. Confirm/Cancel share a lock. Source messages
older than five minutes are ineligible. Durable receipts are retained for 30 days;
they contain IDs, validated arguments, time, and outcome, not raw chat content.

### Storage and execution safety

The existing `cinnamon_bot_data` snapshot and guild/member economy keys remain in
use. New settings and receipts are additive `advanced_features` records; there is
no destructive migration. Shared advanced-feature dictionary identity is retained.

Startup validates a complete snapshot before applying it. A missing store may
initialize; an unreadable or corrupt store blocks subsequent snapshot writes.
Every writer uses the same lock and captures its snapshot after obtaining it.
Upstash compare-and-set uses a fixed internal Lua script to detect stale writers.
Local replacement flushes the file and directory rather than truncating the last
good snapshot.

Credits remain staged until acknowledgement. Removals reserve spendable funds
before I/O. Balance and receipt commit together. Live publication and definite
refunds use deltas so concurrent legacy purchases/rewards are preserved. Full
economy restoration is blocked during a pending transaction/reconciliation.

Cancellation, lost acknowledgements, and malformed write responses establish a
write barrier. Reconciliation waits for retained in-flight work, then reads the
store. If the old state remains, an atomic fence prevents a delayed original write
from committing after a refund. No new snapshot blindly overwrites an uncertain
transaction. Conflicting writers fail closed and require operator review/restart;
this is not a multi-instance economy.

Moderation records an execution intent before contacting Discord. Lost Discord
responses remain uncertain and are not automatically retried. A successful API
response is distinguished from a successfully persisted final receipt. Discord
logs are best effort; durable receipts remain the execution record.

Existing slash/prefix administrator Catnip command names remain available and use
the checked transaction helper. Their direct invocation does not add a chat
confirmation or conversational amount cap. Other existing economy/game operations
retain their current behavior; this increment does not make every legacy reward,
inventory operation, or independent Hangry statistics file transactional.

### Independence and dashboard

There is still one activity scheduler. Brain v1 retains six recent messages from
two humans, a fresh message within ten minutes, and six-hour backoff after an
unanswered game. The sampler keeps bounded timestamps/member IDs, not message
content, and starts empty after restart. Operational cooldowns and settings persist.

Eligibility now repeats before invitation, follow-up ping, and launch. It covers
independence and feature switches, configured channel, view/send/embed permissions,
notification role, storage readiness, and other games/lobbies in the guild.
Ignored-game feedback is saved independently of message-edit success. One guild's
scheduler exception does not stop checks for the other guilds.

`/cinnamon-mind status` provides private readiness reasons. Independence and
conversational-action switches are available through that command group and the
mobile dashboard. Failed saves are reported; a protective off remains effective
in the current process. Dashboard viewing and editing require owner/Administrator
authorization; Manage Server alone is insufficient. No member portal was added.

The policy does not yet understand serious-discussion semantics. Keep invitations
in an explicitly approved games channel and complete live verification before
enabling wider use. No new autonomous activity types were added.

## Deployment and verification

Use one active bot process. Review prerequisite PRs #13 and #14 before merging
this stacked increment, then retarget/rebase it onto reviewed `main`. Do not run
an old blind-writing worker alongside the new writer during rollout. Take a
private backup before a planned test deployment; never place it in the repository.

Required existing deployment values remain `DISCORD_TOKEN`, `GEMINI_API_KEY`, and
the dashboard OAuth configuration. On Render, configure both
`UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`; the token must allow the
fixed GET/EVAL/SET storage operations. Partial configuration fails closed. Keep
`DASHBOARD_SECRET_KEY` stable; the old `DASHBOARD_SESSION_SECRET` name is accepted
as fallback.

New optional variable: `CINNAMON_ALLOW_LOCAL_ACTIONS=true` explicitly permits
local development or an actually persistent disk. Leave it unset on Render's
ephemeral filesystem. `BOT_DATA_FILE` still chooses the local path. No new
hosting service, scheduler, AI key, or Discord permission is introduced.

Moderation needs the bot's Timeout Members permission and suitable role hierarchy.
Game invitations need view/send/embed permissions and the existing opt-in role
configuration. Render's free service may sleep: a healthy HTTP endpoint does not
prove an active Discord gateway connection.

Run offline checks:

```bash
python -m pip install -r requirements.txt
python -m compileall -q main.py dashboard.py cinnamon_modules tests
python -m unittest discover -s tests -v
git diff --check
```

CI runs Python 3.11 and 3.12. Tests use fake Discord/backend objects and temporary
files; runtime startup is exercised without Discord login or Gemini requests.
Local verification on 31 October 2026:

| Check | Result |
| --- | --- |
| Python 3.11.17 full suite | 180 tests passed, no skips |
| Python 3.12.14 full suite | 180 tests passed, no skips |
| Compilation on both versions | Passed, including `dashboard.py` |
| `git diff --check` | Passed |
| Real dependency/runtime startup | Passed on both versions with sockets blocked |
| Discord, Gemini, Render, live Upstash | Not exercised |

Private-server acceptance checklist:

- [ ] Verify one slash-command copy, successful startup, dashboard OAuth, mobile controls, and storage status.
- [ ] As an ordinary member, ask about quests, fishing, stories, and `/recall`; request a Catnip grant and a timeout and verify no state change.
- [ ] As an Administrator, enable chat actions; request a 20,000-Catnip grant. Check the target ID, confirm once, repeat the click/source, and compare the balance with the durable receipt.
- [ ] Confirm another user cannot approve or cancel the card; test cancellation, expiry, role removal, protected targets, changed balances, and multiple target mentions.
- [ ] Exercise an authorized five-minute timeout and its removal on a test account. Chat kick/ban must only give slash guidance.
- [ ] Restart before confirmation and after committed execution; expired cards must not execute and committed receipts must prevent replay.
- [ ] Verify quiet/one-person servers stay quiet, ignored lobbies back off, another game suppresses a surprise, and disabling independence or permissions mid-lobby prevents ping/launch.
- [ ] Test failure handling with isolated test storage and controlled credentials; never damage production data to simulate a failure. Verify uncertain outcomes are reported and no blind duplicate occurs.
- [ ] Smoke-test existing economy, quests, achievements, fishing, stories, Hangry hosting, log routing, and opt-outs.
- [ ] Mark live-tested and ready-for-release only after recording evidence and reviewing remaining failures.

## Changed-file manifest

This increment's exact paths are listed below; the stacked PR also retains PR
#13's already-authored restart/dashboard fixes and its dashboard-runtime tests.

| Subsystem | Added or modified files |
| --- | --- |
| Pure Brain components | `cinnamon_modules/brain_actions.py`, `cinnamon_modules/brain_help.py`, `cinnamon_modules/brain_storage.py` |
| Trusted runtime actions | `cinnamon_modules/cinnamon_actions.py`, `cinnamon_modules/economy.py`, `cinnamon_modules/core_events.py` |
| Storage/runtime loading | `cinnamon_modules/dashboard_runtime.py`, `main.py` |
| Existing autonomy | `cinnamon_modules/cinnamon_brain.py`, `cinnamon_modules/cinnamon_personality.py` |
| Dashboard and help | `dashboard.py`, `cinnamon_modules/general_moderation.py`, `cinnamon_modules/server_setup.py` |
| New regressions | `tests/test_brain_actions.py`, `tests/test_brain_help.py`, `tests/test_brain_storage.py`, `tests/test_brain_dispatch.py`, `tests/test_brain_dashboard.py`, `tests/test_trusted_actions.py`, `tests/test_runtime_startup.py` |
| Existing/prerequisite regressions | `tests/test_cinnamon_actions.py`, `tests/test_cinnamon_brain.py`, `tests/test_cinnamon_personality.py`, `tests/test_persistence.py`, `tests/test_dashboard_runtime.py` |
| Configuration and documentation | `.env.example`, `.github/workflows/wildlands-checks.yml`, `README.md`, `CINNAMON_CHAT_ACTIONS.md`, `docs/CINNAMON_BRAIN.md` |

## Next increments

Finish live acceptance and resolve failures before broadening the action catalog.
Then implement persistent personal reminders with view/cancel and restart-safe
delivery. Persistent member memory follows separately, including disclosure,
guild/member isolation, opt-out, access/deletion, private correction tickets, and
retention. Semantic incident assistance, richer personality/emoji selection, and
additional authored story content remain later work.
