# Cinnamon Brain — Architecture Blueprint (v3+)

> Status: design grounded in the 30 confirmed Notion decisions (31 Oct 2026), the merged Brain v1/Phase 2 source, and the Brain Kernel v3 branch. This document is a build target—not a claim that every layer exists.

## North star

Cinnamon is one character and one trusted Discord bot with three equally important capabilities:
1. **Companion:** context-aware conversation, teaching/help, stable character, respectful relationships and member-controlled memory.
2. **Server assistant:** natural-language help and authorized actions, with real permission checks and honest outcomes.
3. **Connected game universe:** activities, Hangry Games, quests, achievements, Catnip, Wildlands and story state share context without duplicating schedulers or reward logic.

A language model is the language/reasoning component—not the authority, database, scheduler, or Discord executor.

## Target architecture

```
Discord events / slash commands / scheduled opportunities
                     |
             Event + identity adapter
                     |
        Context assembler (Brain Kernel)
    guild + channel + member + recent turns
   explicit notes + mood + serious/activity signals
                     |
              Intent / route layer
 help | chat | reminder | memory | trusted action
 game | story | incident | wait | clarification
                     |
        Policy + autonomy controller (Python)
 permissions | switches | cooldowns | budgets
 safety | channel rules | engagement | storage health
                     |
         ┌───────────┴───────────┐
         |                      |
  Gemini conversation     Typed trusted tools
  / bounded adviser       (allowlist only)
         |                      |
   validated reply        fresh authorization
   + persona guard        + confirmation/idempotency
         |                      |
         └───────────┬──────────┘
                     |
         Discord response / game / result
                     |
          audit + health + metrics
```

## Components and responsibilities

### 1. Event and identity adapter
- Receives Discord events and slash interactions.
- Uses Discord's real member, guild, channel, role and permission objects; never trusts model-supplied IDs as identity proof.
- Filters bots, ignored channels, disabled features, duplicate source events and stale requests.
- Keeps normal Discord command callbacks authoritative.

### 2. Context kernel (current PR #32)
- Produces one deterministic, bounded object for a conversation turn.
- Includes guild/channel/member scope, current input, recent turns, the current member's explicit preferences, mood, tone and serious-context flag.
- Treats history and notes as untrusted data; never as system instructions.
- Limits input before the model call and can be unit-tested without Discord/Gemini.

### 3. Intent and route layer (next)
Use deterministic routing first for explicit capabilities already supported:
- registry-backed command help
- self-reminders
- explicit preference save/view/forget
- current typed admin actions
- existing game/story commands

Use Gemini only for **language understanding and conversational answers**, or for proposing a constrained, schema-validated intent when deterministic parsing cannot understand wording. Model intent proposals remain untrusted. Ambiguous target, amount, channel, or action → clarification, not a guess. Compound or unsupported action → explain/refuse.

### 4. Decision record + policy engine (next)
Every autonomous opportunity should produce a compact decision record:
- event/opportunity and timestamp
- aggregate engagement (counts/freshness, not message transcript)
- allowed candidates and why each was excluded
- proposed choice: wait / speak / ask / start enabled activity
- final Python policy result and reason
- feature switch, cooldown, quiet/serious state, storage health

Policy checks run before and after any model advice. Model advice can rank approved candidates; it cannot enable a feature, choose a target, ping a role, grant a reward or bypass cooldowns. Default and malformed output = **wait**.

### 5. Personality and relationship layer
- Immutable Cinnamon identity: dramatic, teasing, clever, sometimes grumpy, kind underneath.
- Per-guild admin settings can adjust mood/style/independence, but cannot force a message cadence or erase the core character.
- Serious context overrides jokes, reactions and cameos.
- Member familiarity comes only from approved memory/state, not inferred sensitive traits.
- No guilt, pressure, insults, manipulative attachment, or punishment through character mood.

### 6. Memory tiers
| Tier | Purpose | Rules |
|---|---|---|
| Turn context | Short conversation continuity | Ephemeral, bounded, channel scoped |
| Personal preferences | Hobbies, games, stories, reply style | Explicit save; guild/member scoped; view/delete/opt out |
| Game/story state | Inventory, skills, branches, achievements | Existing authoritative game/economy stores |
| Activity signals | Engagement, serious/quiet periods | Aggregate/content-free where possible; short TTL |
| Operational audit | Actions, errors, receipts | IDs/outcomes only where possible; redact message content |

No passive full-chat archive, sensitive profile, cross-guild memory leakage, or private-note exposure. Retention and deletion must be explicit and tested.

### 7. Trusted tools and actions
- Closed registry of typed tools with schemas, documented permission requirements and bounded arguments.
- The Python adapter independently resolves targets and checks guild scope, roles, hierarchy, feature settings, limits and storage.
- Confirmation is tied to requester/source, expires, and re-checks authorization at execution.
- Idempotency receipts prevent double currency/reward or duplicate execution.
- Separate read-only tools from mutations.
- Model-generated prose never reaches an executor. No eval, arbitrary code, arbitrary slash command execution or general-purpose Discord API tool.
- Autonomous discipline stays prohibited; arguments for staff actions remain human initiated/authorized.

### 8. Reliability and observability
- One existing scheduler; no competing timer loops.
- Storage unavailable/uncertain → disable mutations and unsolicited events; do not overwrite a good snapshot with defaults.
- Retry only operations known not to have happened; uncertain writes require read/reconciliation.
- Per-guild feature kill switch and global emergency autonomy-off.
- Private admin diagnostics show decisions, policy reasons, model/tool errors and health without exposing raw member notes.
- Model timeout/rate limit/invalid output → deterministic fallback, then silence/clarification.
- Track model latency, failures, token/cost estimates, activity engagement and action outcomes; avoid logging full chat by default.

## Build sequence and release gates

### A — Context kernel
- Structured, bounded context integrated into the Gemini adapter.
- Unit tests for scope, caps, invalid data, prompt-injection-as-data, serialization.
- Gate: CI passes and no memory cross-scope regression.

### B — Intent routing and response contract
- One route enum + decision result; deterministic capability routing.
- Strict response schema and safe text/reaction validation.
- Clarification path for ambiguity; no claims of actions without receipts.
- Gate: all supported routes and unsupported requests tested; no tool authority in chat model.

### C — Unified decision engine
- Aggregate signals → eligible candidates → deterministic policy → optional Gemini ranking → revalidation.
- Explainable reason codes and cooldowns; default wait.
- Gate: quiet server, no-response, serious context, disabled channel, storage failure, bot permissions, duplicate scheduler all block activity.

### D — Memory and relationship quality
- Improve explicit note management and owner correction tickets.
- Member-visible transparency, opt-out/erase, TTL/retention, data minimization.
- Gate: deletion scrubs notes/tickets/context; guild/member isolation tests.

### E — Capability/tool quality
- Tool registry metadata feeds help and action parser.
- Read-only information first; mutating tools require authority/confirmation.
- Gate: permission matrix, role hierarchy, stale confirmation, idempotency, restart recovery.

### F — Game/story integration
- Cinnamon can explain and suggest enabled features using real registries/state.
- Activity starts through existing Hangry Games/story entry points only.
- Gate: rewards/inventory are written by existing game/economy code exactly once; failure does not touch permanent Catnip.

### G — Operations and launch
- Dashboard controls, private health panel, backup/recovery and test-guild acceptance.
- Gate: restore drill, OAuth/mobile dashboard checks, all offline tests, and actual Discord smoke tests before public launch.

## Non-goals
- Training a foundation model from scratch.
- A second gameplay bot or duplicated economy writer.
- An unrestricted autonomous agent.
- AI-generated moderation verdicts or automatic punishment.
- Passive member chat archiving, sensitive profiling, public member portal or independent marketplace.
- Claiming production readiness from CI alone.

## Evidence sources
- Notion: Cinnamon Vision, AI Brain & Launch Roadmap (30 decisions, architecture and release targets).
- GitHub: merged Brain v1 (#14), trusted actions (#15), Brain Phase 2 (#16); current main source and tests.
- Google Gemini API: function calling is a proposal/result loop, with application-side execution; keep tools narrowly declared and validate before execution.
- OWASP LLM Prompt Injection guidance: enforce least privilege at tool boundaries and treat model output/retrieved text as untrusted. Prompt text alone is not a security boundary.
