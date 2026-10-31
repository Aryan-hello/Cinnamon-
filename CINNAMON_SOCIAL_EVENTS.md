# Cinnamon Social Events — Current Code Reference (31 October 2026)

This document replaces the October 26 description of how Cinnamon's
surprise Hangry Games and optional personality messages operate.
It describes the **current code**, not proof of a successful live
Discord/Render deployment. See
[the Cinnamon Brain design](docs/CINNAMON_BRAIN_PHASE2.md) and
[the active command audit](docs/COMMAND_AUDIT.md) for additional limits.

## Surprise Hangry Games

Running `/setup` creates or repairs the approved game channel, the
**Hangry Games** notification role, and private event logs. The game channel
can subsequently be selected with `/cinnamon-events channel`.
A member must separately opt in with
`/cinnamon-events notify enabled:true` to receive the role's alerts.

With automatic games enabled, Cinnamon schedules an **activity opportunity**
every 1–2 hours. **An opportunity is not a promised game.** The independent
activity policy decides whether to stay quiet, ask an optional no-ping
community question, or begin a game. The choice is constrained by:

- A healthy stored snapshot, an enabled independence switch and the
  administrator-approved game channel.
- Guild and bot permissions, an existing Hangry Games role, and no other
  conflicting game/lobby.
- Genuine recent participation: at least six recent human messages from
  at least two members, with activity in the last ten minutes.
- A quiet period after a previously unanswered game, and temporary quiet
  periods for discussions that may need more care.

The ordinary automatic game lobby has a two-minute join window and
**1,000–2,500 Catnip** from the game economy, not from a member's wallet.
It may mention the opted-in Hangry Games role **once at creation**.
At the 90-second check it sends a second role alert **only if someone
has joined**; if nobody joins, Cinnamon does not repeat the ping.
At 120 seconds, at least two non-bot entrants are required to launch the
game. Otherwise she cancels quietly, logs the result privately, and
backs off for six hours. There is **no public cancellation tantrum or
automatic mood penalty for an unanswered game**.

Normal winner rewards go through the existing Hangry Games payout path.
Automated surprise games do not spend a human host's weekly prize budget.
Do not assume a game will start merely because the next check is due.

## Commands and permissions

| Registered command | Who can use it | What it does |
| --- | --- | --- |
| `/cinnamon-events status` | Members | Game state, activity-check time, notification info |
| `/cinnamon-events notify` | Members | Opt in or out of the Hangry Games notification role |
| `/cinnamon-events questions` | Members | Opt in/out of *personal* random questions |
| `/cinnamon-events auto` | Administrators | Enable/disable scheduled surprise-game opportunities |
| `/cinnamon-events channel` | Administrators | Choose the approved surprise-game channel |
| `/cinnamon-events people` | Administrators | See favourite visitors and nice/naughty summaries |
| `/cinnamon-events test-game` | Administrators | Request a test lobby, still subject to safety/permission checks |
| `/cinnamon-events cameos` | Administrators | Enable/disable very rare non-pinging cameo lines |
| `/cinnamon-events announce` | Administrators | Explicitly confirm a mass announcement, with cooldown |
| `/cinnamon-mind status` | Administrators | Explain why voluntary activity is READY or WAIT |
| `/cinnamon-mind independence` | Administrators | Pause or resume Cinnamon's voluntary activities |
| `/cinnamon-mind prompts` | Administrators | Allow occasional no-ping community questions |
| `/cinnamon-mind reasoning` | Administrators | Opt in to metadata-only Gemini activity advice |
| `/setup` | Administrators | Create or repair configured resources |
| `/datastatus check` | Administrators | Inspect actual saved-data and confirmed-action readiness |

The `/cinnamon-events questions` switch is **not** a reminder switch.
Members may still request personal reminders using
`/cinnamon-reminder create`, `/cinnamon-reminder list`, and
`/cinnamon-reminder cancel`.

## Personal questions, public questions and cameos

A member directly interacting with Cinnamon may receive an optional,
silly **personal question**, with at most an **8% chance** per eligible
invitation. It is limited to one per member per 24 hours and one per
server per six hours. Members may opt out, and Cinnamon respects the
global independence and sensitive-discussion quiet controls.
A question waiting longer than two minutes is marked missed; no
automatic negative mood penalty is applied just because no one answered.
A later answer may trigger a playful response.

Separately, administrators can allow rare **public no-ping community
questions** via `/cinnamon-mind prompts`. These are proposed only at
eligible activity opportunities, use the approved activity channel,
and have backoff behavior if nobody responds. Gemini-assisted activity
advice is opt-in and only receives aggregate activity counts and mood.
Model output cannot execute commands or bypass the Python restrictions.

Cinnamon may also make a rare cat-jealousy one-liner about another cat,
subject to a low random chance, six-hour limits, disabled channels,
storage readiness, and independence/serious-context controls. It
does not start a Gemini conversation or ping members.

## Reactions, records and recovery

In-game achievements, purchases and wins may prompt occasional
in-character celebrations. A big purchase reaction requires at least
5,000 Catnip and reactions have a 15-minute cooldown per member/event.
Nice/favourite lists are based on in-game deeds, not a hidden archive
of members' private conversations.

Cinnamon stores relevant state in her existing snapshot and records
limited administrative personality snapshots in private configured logs.
`/recall` can reconstruct **only records for which appropriate evidence
was actually logged**; it does not restore everything or retrieve private
AI memory. The store uses guarded snapshot commits and Upstash's
compare-and-set mechanism when configured. On Render Free, local
JSON may be lost on redeployment; configure and test durable storage,
and avoid simultaneous writers.

## Before a public release

- Confirm `/help` and `?help` list the registered commands after Discord sync.
- Verify an active, a quiet and a single-member server; no unexpected games.
- Test the opted-in role ping, no second ping when zero players join,
  quiet cancellation and six-hour backoff in a private test guild.
- Verify administrator-only settings and member-only consent controls.
- Recheck permission changes during a lobby, game winner payout, and
  persistence after a restart.
- Never infer a live Discord success from passing offline unit tests.
