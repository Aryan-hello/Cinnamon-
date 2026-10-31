# Cinnamon Chat Actions & Safe Playtime

This branch implements the first trusted Brain action increment. It is not a
production release. See [the implementation and verification record](docs/CINNAMON_BRAIN.md).

## The rule: personality is not an admin key

Cinnamon's AI can write jokes but cannot trigger arbitrary commands or punish users. Exact message patterns are parsed in a separate deterministic, audited handler. Every moderation action needs permission checks both when the request is posted and again when the original requester confirms it.

## Playful micro-timeouts (strictly opt-in)

- Server Administrator first uses `/cinnamon-prank enable enabled:true` or toggles **Cinnamon Mind → Consent-only cat jokes** in the dashboard. **Disabled by default**.
- Each person who wants these jokes uses `/cinnamon-prank consent enabled:true`. Nobody else can opt them in. `enabled:false` withdraws consent.
- A participating member occasionally gets a **1–10-second timeout** when they voluntarily address Cinnamon; it is rare (1.5% chance per eligible direct invitation) and limited to **once per member per server per UTC calendar day**. The daily limit persists in Upstash/advanced-features state.
- No surprise timeout for server owner, staff with Administrator or Timeout Members, bots, people above Cinnamon's role, or people already timed out.
- A rejected or failed API request does not consume a daily use. Events are recorded in the private Cinnamon Mood Logs, not chat transcripts.
- Members can check `/cinnamon-prank status`. The cat cannot simply decide to use stronger or longer punishments because of mood.

## Staff natural-language commands (closed allowlist)

Cinnamon responds to an actual @mention, a reply to Cinnamon, or a clear direct call by name.

After invoking her, a staff member can write:

- `@Cinnamon add 20,000 Catnip to @Member` — owner/Administrator, maximum 1,000,000 per conversational adjustment.
- `@Cinnamon remove 500 Catnip from @Member` — owner/Administrator, requires the displayed balance to remain unchanged until execution.
- `@Cinnamon mute @Member for 1 hour` — requires the requesting human to have **Timeout Members** permission (or Administrator).
- `@Cinnamon time out @Member for 10 seconds` — same permission. Chat-side duration range is 1 second to **24 hours**.
- `@Cinnamon unmute @Member` — same permission.
- Chat kick/ban requests are directed to existing slash commands, pending a separate security review.
- `@Cinnamon mute this member for 1 hour` — only when the requester **replies to the target member's message**, so Cinnamon never guesses the recipient.

Conversational actions are **disabled by default**. An Administrator enables
them with `/cinnamon-mind actions enabled:true` or Cinnamon Mind in the dashboard.
Acknowledged Upstash storage is required on Render. Local development requires
`CINNAMON_ALLOW_LOCAL_ACTIONS=true`; an ephemeral local file is not redeploy-safe.

**Nothing happens immediately.** Cinnamon posts a public confirmation card specifying exact action, duration, target ID, and requesting staff member. Only that requester may confirm within 60 seconds, before a restart. At confirmation, current permissions, role hierarchy, guild/target identity and bot permissions are re-verified. Confirm and Cancel share a lock. Source receipts prevent duplicate execution; uncertain outcomes cannot be blindly retried. The Discord audit reason identifies the requesting human, and a durable execution receipt accompanies the best-effort Discord log.

Targets excluded from conversational moderation: server owner, bots, administrators, members with Timeout Members permission, requester's own account, someone with an equal/higher role, or someone above Cinnamon's highest role. If the requester loses permissions before clicking Confirm, the action is denied.

The AI has **no generic command execution**. Python recognizes a small set of
anchored phrases and validates a typed, allowlisted proposal. Broad, ambiguous,
or compound requests are refused or clarified. Gemini's output, quoted text,
and channel history are never sent back through the executor.

`?ask`, `?ai`, and `?chat` use the same help/action dispatcher. Questions about
quests, fishing, stories, achievements, economy, and registered commands can be
answered without Gemini. `/recall` means Administrator-only log recovery; it is
not personal-memory retrieval.

## Administrator-only changes

High-impact settings, economy catalog/admin balance edits, role assignment,
channel configuration, kicks and bans require Administrator. **Conversational
timeout and untimeout remain available to users with Timeout Members permission.**
The Hangry hosting budget remains separate. Dashboard viewing and editing now
require the server owner or a current Administrator; Manage Server alone is
insufficient. Existing slash/prefix Catnip admin commands share the checked
transaction helper and reject non-positive amounts.

## Testing and pre-deployment

1. Back up Cinnamon's current Upstash data, and check she has the Moderate Members permission with her role above any non-staff test account.
2. In a test Discord server, try to opt someone else into the prank (must not be possible). Check default-disabled server flag; enable as Administrator, then personally opt in from a test member.
3. Say `Cinnamon, hello` many times in a test-only channel or use the static simulation test. Verify 1–10 seconds, maximum once per UTC day and no target staff, no surprise outside a direct invitation. Disable again after test.
4. Test moderator ping + named member + 1-hour duration. The confirmation must appear, but the timeout must **not** happen until the requester clicks Confirm. A different member clicking must fail.
5. Remove the moderator's Timeout Members permission after showing the prompt, before pressing Confirm; the action must be rejected. Attempt actions against staff/owner/bots/higher roles and in other guilds; all must fail.
6. Test chat kick/ban requests from both a moderator and an Administrator; both must receive slash-command guidance and no confirmation or execution.
7. Confirm other server settings, economy adjustments, role changes, merchant access and dashboard writes reject non-Administrator accounts. Check `/cinnamon-events announce` remains separately confirmed and limited.
8. Verify no AI chat message claims it executed moderation, an unauthorized transaction or role change. Test custom Hangry channel, private merchant permissions, story, fishing and recall after restart.
9. **GitHub Actions offline tests are not equivalent to real Discord/Render checks.** Do not claim zero loopholes or that all features are live-tested until you complete a test-guild smoke run.

Discord library reference: https://discordpy.readthedocs.io/en/stable/api.html#discord.Member.timeout
