# Cinnamon Brain v5 Task & Memory Engine Implementation Plan

> **For agentic workers:** Use Superpowers TDD and verification-before-completion. Steps use checkboxes.

**Goal:** Add durable, safe multi-step tasks and relevance-scoped memory retrieval to Cinnamon's existing Gemini + trusted Python architecture.

**Architecture:** Pure modules define and validate task transitions, plan schemas, retrieval relevance, and execution outcomes. Existing persistence/runtime adapters store tasks; the existing scheduler resumes only safe work. Existing Discord/game/economy handlers remain execution authority.

**Tech Stack:** Python, discord.py, existing Upstash-backed storage, Gemini, unittest, GitHub Actions (Python 3.11/3.12).

**Spec:** `docs/superpowers/specs/2026-11-05-cinnamon-brain-v5-design.md`.

## Global Constraints
- No model output directly executes Discord, moderation, economy, or game mutations.
- Member notes are explicit, scoped, deletable, and treated as untrusted data.
- No new scheduler; use the current scheduler and storage lock/receipts.
- Storage uncertainty blocks mutations; uncertain external outcomes never blind-retry.
- Offline CI is not live guild or deployment acceptance.

## Review Focus
- Malformed/oversized plan and argument payloads are rejected without partial writes.
- Guild/member scope mismatch never returns another user's task or note.
- Permission revocation, feature disable, expiry, cancellation, or serious/quiet policy blocks pending execution.
- Duplicate events and restarts cannot replay an external side effect.
- JSON escaping and hostile memory text remain bounded and inert.

## File map
- Create `cinnamon_modules/brain_tasks.py`: pure schemas, transition policy, dependencies.
- Create `cinnamon_modules/brain_planner.py`: plan proposal parsing/validation against capability registry.
- Create `cinnamon_modules/brain_verification.py`: typed outcomes and retry policy.
- Create `cinnamon_modules/brain_memory_retrieval.py`: scope-first deterministic retrieval/ranking.
- Modify existing storage adapter (after audit) for task persistence/atomic transitions; reuse its lock and durable receipts.
- Modify `core_events.py` only to expose explicit task create/status/cancel routes through trusted adapters.
- Modify existing scheduler only after task store and executor are tested; no second loop.
- Modify `brain_kernel.py` to accept a small retrieval result only after scope and budget tests pass.
- Add focused unittest files and update Brain architecture/status docs.

## Tasks

### Task 1 — Pure task records and transitions
- [ ] Add tests for valid task/step records, caps (8 steps), unique IDs, dependency cycles, missing dependencies, and illegal state transitions.
- [ ] Run tests and confirm expected failures.
- [ ] Implement immutable typed records and `validate_task`, `can_transition`, `transition_task` in `brain_tasks.py`.
- [ ] Test expiry, cancellation, blocked, uncertain and completed terminal states.
- [ ] Run focused and full tests; commit.

### Task 2 — Plan proposal validation
- [ ] Test malformed JSON, unknown capability IDs, extra keys, oversized arguments, more than 8 steps, duplicate IDs, and dependency cycles.
- [ ] Implement `parse_plan_proposal(payload, capability_registry)` in `brain_planner.py`; allow only registered schemas and return a validated proposal, never execute.
- [ ] Run focused and full tests; commit.

### Task 3 — Outcome and retry policy
- [ ] Test success, definite failure, transient safe failure, and uncertain external outcome.
- [ ] Implement `classify_outcome` and `retry_allowed` in `brain_verification.py`; uncertain mutations are never retryable.
- [ ] Run focused and full tests; commit.

### Task 4 — Scoped memory retrieval
- [ ] Test guild/member filtering before scoring, deterministic ranking, empty/opt-out/deleted notes, hostile text, and strict character budget.
- [ ] Implement `retrieve_relevant_memories(query, notes, guild_id, member_id, limit, max_chars)` in `brain_memory_retrieval.py`; no embeddings/dependencies in this phase.
- [ ] Run focused and full tests; commit.

### Task 5 — Durable task store
- [ ] Inspect the actual advanced-feature storage API and its lock/receipt semantics; add tests before changing storage.
- [ ] Implement scoped task read/write and atomic transition using existing persistence primitives; storage errors return explicit unavailable state and never defaults.
- [ ] Test restart persistence, stale writer, duplicate event/idempotency, corrupt store, and uncertain commit.
- [ ] Run focused and full tests; commit.

### Task 6 — Trusted one-step executor and routes
- [ ] Add tests for explicit requester, guild/member scope, permission/feature recheck, confirmation expiry, dependency gating, and one-step-only execution.
- [ ] Implement execution through a closed capability adapter registry; never call Discord APIs from planner/model output.
- [ ] Add task status/cancel/create UX through current event/command patterns; no auto-start from ambiguous chat.
- [ ] Run focused and full tests; commit.

### Task 7 — Scheduler recovery and context integration
- [ ] Test restart resume, task expiry, disabled independence, quiet/serious state, storage outage, and uncertain-step reconciliation.
- [ ] Extend the existing scheduler with bounded task polling; ensure only one scheduler exists.
- [ ] Integrate small scope-filtered memory/task summaries into Brain Kernel context.
- [ ] Run full suite and syntax checks; commit.

### Task 8 — Docs, review, CI, release boundary
- [ ] Update Brain architecture/status and the Notion Brain Vision page with actual implementation and test counts.
- [ ] Run CI on Python 3.11/3.12 and inspect full changed-file diff.
- [ ] Request independent code review; fix critical/important issues.
- [ ] Create/update PR with explicit non-live status and test-guild checklist.
- [ ] Do not merge or deploy until separate user approval and private-guild acceptance.
