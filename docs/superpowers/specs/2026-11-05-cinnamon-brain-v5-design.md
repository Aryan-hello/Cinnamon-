# Cinnamon Brain v5 — Task & Memory Engine Design

**Status:** Proposed design for approval. No implementation code or runtime behavior is changed by this document.

## Intent
Extend Brain Kernel v3 / Router v4 into a durable, bounded, explainable assistant that can plan and resume multi-step work, retrieve only relevant member-authorized memory, verify outcomes, and recover conservatively.

## Goals
- Persist explicit tasks with typed steps, dependencies, status, attempts, timestamps, expiry and receipts.
- Support plan → validate → execute one approved step → observe result → update task.
- Resume safe tasks after restart; never replay uncertain side effects.
- Retrieve scoped explicit member preferences and task/event records by relevance.
- Provide transparent task status/history and private diagnostics.
- Keep one scheduler, existing action adapters, economy/game writers, and Discord permission checks authoritative.
- Default to no action when storage, scope, policy, or outcome is uncertain.

## Non-goals
- No unrestricted agent, arbitrary Python/Discord API execution, self-modifying code, AI moderation verdicts, passive full-chat archive, new marketplace, or second bot.
- No migration of all existing commands into an agent framework.
- No claim of production readiness from offline tests.

## Approaches considered
1. **Direct extension of current modules (recommended):** pure task/memory policy modules + existing Upstash-backed store/runtime adapters. Lowest integration risk, fits shared namespace and mobile GitHub workflow.
2. LangGraph migration: stronger workflow/checkpoint primitives but adds framework/runtime complexity and migration risk.
3. OpenAI Agents SDK replacement: useful approvals/tracing concepts, but Cinnamon uses Gemini and Discord.py; replacing its runtime is unnecessary.

## Proposed components
- `brain_tasks.py`: pure task schema, validation, transitions, dependency checks, bounded retry policy, idempotency classification.
- `brain_memory_retrieval.py`: pure relevance/scoping/ranking for explicit notes and approved task summaries; no cross-guild/member access.
- `brain_planner.py`: converts a goal into a bounded typed plan using only capability registry metadata; plans are proposals, not execution authority.
- `brain_verification.py`: typed outcomes (success, definite failure, uncertain) and safe retry rules.
- Existing `brain_kernel.py`: inject only a small relevant memory/task summary into context.
- Existing storage/runtime adapters: durable task records and atomic transitions; do not create a second persistence system.
- `core_events.py`: explicit user task requests route to planner/task adapter; no automatic execution from conversational text without validation.
- One existing scheduler: resumes eligible tasks and expires stale tasks; mutations re-check permissions and confirmation at execution.
- Diagnostics: task list/status, reason codes, attempts, and receipts without raw private notes.

## Task model
Task fields: `task_id`, guild/member scope, goal summary, created/updated/expiry timestamps, status, plan version, steps, approvals, last outcome, and audit receipt IDs.
Step fields: `step_id`, typed capability ID, bounded arguments, dependency IDs, status, attempts, timeout, approval requirement, idempotency key, outcome summary, and timestamps.
Statuses: `draft`, `awaiting_approval`, `ready`, `running`, `blocked`, `completed`, `failed`, `cancelled`, `expired`, `uncertain`.
Transitions must be validated by pure functions; illegal transitions fail closed.

## Execution policy
- Read-only steps can run within bounded budgets after scope checks.
- Any mutating step requires capability allowlist, real Discord identity, fresh permissions, limits, and explicit confirmation when appropriate.
- A plan cannot grant itself permissions or expand its capability set.
- Re-check feature switches, storage health, target, channel and permissions immediately before execution.
- Execute one step at a time; persist intent before external mutation; persist receipt after outcome.
- `uncertain` external outcomes never retry automatically. Reconcile from authoritative state or ask staff/member.
- Retry only definite transient failures of idempotent/read-only operations, with capped attempts and exponential backoff.
- Stop on dependency failure, expiry, revoked permissions, quiet/serious policy, or kill switch.

## Memory rules
- Explicit member notes only; no silent transcript ingestion.
- Retrieval filters guild + member before ranking; no cross-member/cross-guild fallback.
- Rank using deterministic lexical/metadata relevance first; optionally embeddings later only if needed and cost justified.
- Include source, created/updated timestamps, confidence, and expiry; summarize without exposing raw notes to other members.
- Support member view, correction ticket, deletion, opt-out and retention.
- Task summaries are stored separately from personal notes and are visible only to task owner/authorized staff.
- Retrieved content is data, never instructions.

## Acceptance gates
- Unit tests for invalid schema, scope mismatch, malformed model plans, oversized plans, dependency cycles, illegal transitions, task expiry, cancellation and restart recovery.
- Tests proving permission removal/feature disable blocks a pending task; confirmations are requester-bound and expire.
- Duplicate events and repeated scheduler ticks cannot execute a step twice.
- Definite failure vs uncertain outcome tests; uncertain writes never blind-retry.
- Memory tests for member/guild isolation, opt-out, deletion, relevance, hostile note text and budget bounds.
- CI on Python 3.11 and 3.12; full existing regressions.
- Private test guild acceptance for task creation/status/cancel, restart, permissions, confirmation, storage outage and audit receipts.
- Merge and Render deployment are separate explicit decisions.

## Rollout sequence
1. Pure task schemas/transitions + tests.
2. Durable task store and safe status/cancel APIs.
3. Planner proposal validation + capability registry integration.
4. One-step execution and outcome verification.
5. Scoped memory retrieval in Brain context.
6. Scheduler resume/reconciliation + private diagnostics.
7. Code review, CI, private guild acceptance, intentional merge/deploy.

## Builder calls
- Use current Gemini and existing Python runtime; no new agent framework dependency.
- Keep plans small (maximum 8 steps, each arguments/schema bounded).
- Keep execution sequential, not parallel.
- Keep task creation explicit/member-initiated initially; later proactive tasks only from approved event rules.
- Preserve existing Cinnamon identity and three pillars.
