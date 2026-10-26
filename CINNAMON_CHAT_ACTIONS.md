# Cinnamon Chat Actions & Safe Playtime

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
- `@Cinnamon mute @Member for 1 hour` — requires the requesting human to have **Timeout Members** permission (or Administrator).
- `@Cinnamon time out @Member for 10 seconds` — same permission. Chat-side duration range is 1 second to **24 hours**.
- `@Cinnamon unmute @Member` — same permission.
- `@Cinnamon kick @Member` and `@Cinnamon ban @Member` — **Administrator only**.
- `@Cinnamon mute this member for 1 hour` — only when the requester **replies to the target member's message**, so Cinnamon never guesses the recipient.

**Nothing happens immediately.** Cinnamon posts a public confirmation card specifying exact action, duration, target, and requesting staff member. Only that requester may confirm within 60 seconds. At confirmation, permissions, role hierarchy, guild/target identity and bot permissions are re-verified, and repeated clicks cannot execute twice. The Discord audit reason identifies the requesting human; Cinnamon also writes a moderation log.

Targets excluded from conversational moderation: server owner, bots, administrators, members with Timeout Members permission, requester's own account, someone with an equal/higher role, or someone above Cinnamon's highest role. If the requester loses permissions before clicking Confirm, the action is denied.

The AI has **no generic command execution**. Broad or ambiguous requests (e.g. granting roles, minting virtual Catnip, wiping channels) are referred to the existing *Administrator-protected slash commands* with their typed selectors. This is intentional; otherwise a prompt injection could make Cinnamon execute harmful instructions.

## Administrator-only changes

The latest release tightened high-impact legacy commands that used to accept Manage Guild, Manage Roles, Kick/Ban Members or Manage Channels alone. Such settings, economy catalog/admin balance edits, role assignment, channel configuration, kicks and bans require Administrator. **Timeout and untimeout remain available to users with the Discord Timeout Members permission.** The Hangry hosting budget mechanism for staff remains as previously designed; game hosting is not a server security operation. Dashboard configuration POST requests now verify current Administrator permission server-side. View-only dashboard access still supports Manage Server.

## Testing and pre-deployment

1. Back up Cinnamon's current Upstash data, and check she has the Moderate Members permission with her role above any non-staff test account.
2. In a test Discord server, try to opt someone else into the prank (must not be possible). Check default-disabled server flag; enable as Administrator, then personally opt in from a test member.
3. Say `Cinnamon, hello` many times in a test-only channel or use the static simulation test. Verify 1–10 seconds, maximum once per UTC day and no target staff, no surprise outside a direct invitation. Disable again after test.
4. Test moderator ping + named member + 1-hour duration. The confirmation must appear, but the timeout must **not** happen until the requester clicks Confirm. A different member clicking must fail.
5. Remove the moderator's Timeout Members permission after showing the prompt, before pressing Confirm; the action must be rejected. Attempt actions against staff/owner/bots/higher roles and in other guilds; all must fail.
6. Test kick/ban request by a moderator (denied) and by an Administrator (confirmation required). Use a dedicated test account only.
7. Confirm other server settings, economy adjustments, role changes, merchant access and dashboard writes reject non-Administrator accounts. Check `/cinnamon-events announce` remains separately confirmed and limited.
8. Verify no AI chat message claims it executed moderation, an unauthorized transaction or role change. Test custom Hangry channel, private merchant permissions, story, fishing and recall after restart.
9. **GitHub Actions offline tests are not equivalent to real Discord/Render checks.** Do not claim zero loopholes or that all features are live-tested until you complete a test-guild smoke run.

Discord library reference: https://discordpy.readthedocs.io/en/stable/api.html#discord.Member.timeout
