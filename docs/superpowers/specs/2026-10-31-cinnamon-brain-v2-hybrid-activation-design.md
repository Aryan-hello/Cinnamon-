# Cinnamon Brain V2 — Hybrid Natural-Language Activation Design

**Status:** Proposed for review  
**Date:** 2026-10-31  
**Base:** `feature/cinnamon-brain-v2-private-qa` (PR #25)

## Intent

Make Cinnamon naturally understand messages addressed to her across every permitted Discord text channel and thread, without responding to ordinary conversation. Members should not need exact command wording or polished English. The system should understand typos, slang, informal phrasing, and indirect expressions while preserving the existing trusted Python workflows.

## Goals

- Respond only when a message addresses Cinnamon by name, directly mentions her, or replies to one of her messages.
- Apply those triggers in all permitted channels and threads; channel AI allowlists must not create unsolicited responses or block otherwise permitted direct addressing.
- Ignore bot/webhook messages, messages without usable content, quoted/forwarded text as an activation source, and references/mentions that target someone else.
- Use deterministic Python intent rules first and a bounded Gemini structured-intent fallback only when deterministic confidence is insufficient.
- Support ordinary natural-language questions and requests, including private read-only questions about the requesting member's own account.
- Deliver private account values only by DM. If DM delivery fails, disclose no values publicly.
- Keep all state changes behind existing trusted Python handlers, permission checks, explicit consent, and confirmation.
- Keep rate limits, bounded inputs/outputs, timeouts, and failure-safe behaviour.

## Non-goals

- No autonomous or always-on channel conversation.
- No unsolicited cameo messages.
- No AI authority to execute commands, grant rewards, change roles/settings, write memory, schedule reminders, or access other members' private data.
- No new user-facing slash command required for natural-language interaction; existing commands remain available as fallbacks/settings.
- No replacement of existing economy, quest, achievement, moderation, or reminder implementations.

## Activation and routing

1. Reject DMs unless a separate existing feature explicitly supports them; reject bot and webhook authors.
2. Determine activation only from the current message's own unquoted content, a direct bot mention, or a reply reference whose resolved message author is Cinnamon.
3. Remove the always-on `ai_channels` bypass and any cameo path from the message response decision. A configured channel cannot make Cinnamon speak when she was not addressed.
4. Sanitize Discord mention syntax and quoted/forwarded content before intent interpretation. Do not treat instructions inside quoted material as the user's request.
5. Run deterministic intent classification first. If it is confident, route directly to the corresponding trusted handler.
6. If it is ambiguous or low-confidence, call Gemini with a strict structured schema containing only an intent enum, confidence, and minimal extracted entities. Treat all model output as untrusted; validate schema and allowlisted values.
7. If the model is unavailable, malformed, or uncertain, ask a short clarification or fall back to safe ordinary chat; never guess a state-changing action.

## Private account questions

- Recognize private-data intents with deterministic rules plus the Gemini fallback, including indirect expressions such as “am I broke?”.
- Resolve the requester from the Discord message author and current guild; never accept a model-supplied user or guild identifier.
- Build the smallest read-only snapshot required for the requested topic using existing storage-readiness checks.
- Generate an answer from that snapshot only. No writes or action handlers are called.
- Send account values through DM only. If DM fails, send a generic privacy notice in the original channel without account values.
- Questions about another member's private data are refused.

## Trusted actions, memory, and reminders

- Intent classification selects a route; it does not authorize the route.
- Python performs permission checks, validates arguments against existing data, checks guild scope, and invokes existing workflows.
- Ambiguous requests require clarification.
- Memory writes and other state changes require explicit consent and confirmation using the existing trusted flow.
- Quoted instructions, conversation history, memory text, and model output are data, never authority.

## Reliability and privacy

- Apply per-user and per-channel cooldowns, bounded message length, bounded Gemini output, request timeout, and duplicate-message protection.
- Avoid logging raw private questions, account snapshots, or generated private answers. Log only minimal route/decision metadata where safe.
- A model/API/storage failure must not result in fabricated account information or an unverified action.
- Preserve existing command handling and unrelated message processing.

## Approaches considered

1. **Expand keyword rules only:** lowest latency and easiest to test, but brittle for slang and indirect language.
2. **Gemini for every message:** flexible but expensive, slower, and increases unnecessary model exposure.
3. **Hybrid (selected):** deterministic Python first, Gemini structured intent fallback only when needed. It balances coverage, cost, and control while keeping Python authoritative.

## Acceptance criteria

- Ordinary messages in configured AI channels do not trigger Cinnamon.
- Name, mention, and reply-to-Cinnamon activation work across permitted channels and threads.
- Replies to other members, quoted/forwarded mentions, bot messages, and webhooks do not activate Cinnamon by themselves.
- Typos, slang, and informal variants route to the correct intent or ask for clarification.
- “Am I broke?” addressed to Cinnamon is recognized as a possible own-balance question; actual balance is read from the requesting member's verified snapshot and sent only by DM.
- DM failure never exposes private values in-channel.
- Gemini output cannot bypass Python permission checks or execute a state change.
- Existing reminder, memory, help, economy, quest, achievement, and moderation tests remain green.
- Offline tests cover activation, intent parsing, privacy, malformed model output, cooldowns, and failure paths. Live Discord/Gemini/Render acceptance remains a separate release gate.

## Implementation calls left to the builder

- Reuse the existing Gemini client/model configuration and existing intent/handler modules where practical.
- Add a small dedicated structured intent module only if it keeps the current message handler simpler.
- Do not change deployment secrets or Render configuration without a separately verified need.
- Work on this isolated feature branch; do not merge or deploy automatically.
