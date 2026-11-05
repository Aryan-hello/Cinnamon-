# Cinnamon Brain V2 Hybrid Activation Implementation Plan

> **For agentic workers:** Use the native session implementation workflow task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make Cinnamon respond only to direct name/mention/reply activation and route natural-language intents through deterministic Python with a constrained Gemini fallback.

**Architecture:** Keep activation and policy decisions deterministic in a small pure module. Extend the existing intent planner with a structured fallback boundary; the existing trusted Python handlers remain the only executors. Update the current `on_message` pipeline to remove always-on and unsolicited cameo responses while preserving moderation, XP, channel-disable settings, and prefix commands.

**Tech Stack:** Python 3.11+, discord.py, existing Google Gemini client, pytest.

**Spec:** `docs/superpowers/specs/2026-10-31-cinnamon-brain-v2-hybrid-activation-design.md`

## Global Constraints

- Respond only when the current message addresses Cinnamon by name, directly mentions her, or replies to her own message.
- Ordinary conversation never activates Cinnamon, including in configured always-on AI channels.
- Python validates all permissions, guild scope, identity, and action arguments; Gemini only suggests a bounded intent.
- Personal account values are delivered by DM only; failed DMs disclose no private values publicly.
- Memory writes and other state changes require explicit consent and confirmation.
- Preserve existing commands and unrelated features.

## Review Focus

- Bot mention embedded in quoted/forwarded text — must not activate by itself; covered by activation parser tests.
- Message replies to other members — must not activate; covered by reply-target tests.
- Name detection inside a longer unrelated word or code block — must not activate; covered by boundary tests.
- Gemini returns malformed/unknown intent or low confidence — must fall back safely; covered by schema-validation tests.
- Private-data DM fails — channel receives generic notice only; covered by private delivery tests.

---

### Task 1: Deterministic activation policy

**Files:**
- Create: `cinnamon_modules/brain_activation.py`
- Create: `tests/test_brain_activation.py`
- Modify: `cinnamon_modules/core_events.py`

**Interfaces:**
- Produce `is_directly_addressed(content: str, *, bot_user_id: int | None, reply_author_id: int | None, bot_name: str = "Cinnamon") -> bool`.
- Produce `strip_bot_addressing(content: str, *, bot_user_id: int | None, bot_name: str = "Cinnamon") -> str`.
- Activation is true only for a standalone Cinnamon name token, a Discord mention of the bot ID, or a reply whose resolved author ID equals the bot ID.
- Ignore quoted spans and fenced/inline code for name/mention activation; a real reply to Cinnamon remains a valid trigger.

- [ ] **Step 1: Write failing tests** for case-insensitive name matching, punctuation/spacing, word boundaries, mention forms `<@id>` and `<@!id>`, valid/invalid reply author IDs, quoted names/mentions, and code-block mentions.
- [ ] **Step 2: Run** `pytest -q tests/test_brain_activation.py`; confirm failures are due to missing module/functions.
- [ ] **Step 3: Implement** the two pure functions with bounded, dependency-free parsing.
- [ ] **Step 4: Run** `pytest -q tests/test_brain_activation.py`; expect all activation tests to pass.
- [ ] **Step 5: Update** `on_message` to use the helper and remove the `ai_channels` activation bypass and the uninvited `_cp_maybe_cameo` path. Keep `disabled_channels` as an explicit administrator opt-out.
- [ ] **Step 6: Add integration regression tests** proving ordinary messages in AI channels and cameo-eligible messages do not respond, while name/mention/reply do.
- [ ] **Step 7: Run** the activation tests and existing event/Brain tests.

### Task 2: Natural-language intent fallback

**Files:**
- Modify: `cinnamon_modules/brain_intent.py`
- Create: `cinnamon_modules/brain_intent_ai.py`
- Create: `tests/test_brain_intent_ai.py`
- Modify: `main.py` only where the existing Gemini client/model wrapper must be exposed safely.

**Interfaces:**
- Produce `parse_intent_suggestion(raw: str) -> IntentSuggestion | None`, validating an allowlisted intent, confidence range, and bounded entity values.
- Produce `async classify_intent_with_fallback(text: str, *, deterministic_plan, model_call) -> IntentPlan`; call the model only when deterministic intent is `chat` or otherwise explicitly uncertain.
- Gemini prompt requests JSON only with an intent enum (`private_data`, `reminder`, `memory`, `help`, `action`, `chat`, `clarify`), confidence, and short extracted phrase; it cannot return user/guild IDs, permissions, executable commands, or handler names.
- Only sufficiently confident allowlisted suggestions may change the route hint. Low-confidence or malformed output becomes a clarification/chat-safe plan.

- [ ] **Step 1: Write failing tests** for valid JSON, fenced JSON, invalid JSON, unknown intents, confidence bounds, oversized entities, missing fields, and fallback invocation only on uncertain deterministic results.
- [ ] **Step 2: Run** `pytest -q tests/test_brain_intent_ai.py`; confirm the intended failures.
- [ ] **Step 3: Implement** strict parsing and fallback orchestration without importing discord.py.
- [ ] **Step 4: Run** the focused tests and existing `brain_intent` tests.
- [ ] **Step 5: Wire** the existing Gemini client through a timeout-bounded async wrapper using `asyncio.to_thread`; never log raw prompts or private snapshots.
- [ ] **Step 6: Add tests** that model suggestions cannot supply identities, invoke handlers, or override Python permissions/consent.

### Task 3: Private natural-language account answers and end-to-end safeguards

**Files:**
- Modify: `cinnamon_modules/core_events.py`
- Modify: `cinnamon_modules/brain_private_qa.py` (or the exact existing private Q&A module path after confirming its current interface)
- Modify: `main.py` system prompt text
- Create/modify: focused Brain V2 integration tests

**Interfaces:**
- Private account intent is resolved using the message author and current guild only; model output cannot select another member.
- Use existing read-only snapshot construction and readiness checks.
- Deliver private answer via `message.author.send(...)`; on `discord.Forbidden` or `discord.HTTPException`, post only a generic privacy notice in the originating channel.
- Update guidance from `/cinnamon-me ask` to natural DM interaction without removing the slash command.

- [ ] **Step 1: Write failing tests** for DM-only answer, own-member snapshot scoping, refusal for third-party requests, unavailable snapshot, and DM failure with no public values.
- [ ] **Step 2: Run** focused tests and confirm expected failures.
- [ ] **Step 3: Implement** the private natural-language route using the existing read-only snapshot path; do not duplicate account data assembly.
- [ ] **Step 4: Update** the system prompt and public redirect wording to explain that account questions should be asked in DM.
- [ ] **Step 5: Run** the full pytest suite and static compilation checks.
- [ ] **Step 6: Review** the complete diff for unrelated feature changes, secrets, raw private logging, duplicate event handlers, and unsafe AI authority.
- [ ] **Step 7: Commit** the finished feature branch and open a draft PR; do not merge or deploy automatically.

## Release gate

Offline tests cannot prove Discord permissions, real Gemini responses, DM deliverability, or Render/Upstash state. Before deployment, test in a private guild with two human accounts, verify public privacy behavior and Android interactions, then back up persistent economy/snapshot data.