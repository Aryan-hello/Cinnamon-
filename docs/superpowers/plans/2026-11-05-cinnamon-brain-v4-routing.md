# Cinnamon Brain v4 — Intent Router and Unified Decision Records

## Objective
Implement the next missing brain layer from Notion: one explicit, explainable route/decision record around the existing trusted features, with deterministic fallback and zero new authority. Preserve all current feature handlers and one scheduler.

## Existing source evidence
- \`main.py\` owns Gemini conversation adapter and loads modules into a shared namespace.
- \`core_events.py\` processes \`on_message\`, then calls reminder, memory, help, trusted actions in sequence.
- Existing pure modules: \`brain_kernel.py\`, \`brain_context.py\`, \`brain_help.py\`, \`brain_actions.py\`, \`brain_memory.py\`, \`brain_reminders.py\`, \`brain_decision.py\`.
- Runtime adapters: \`cinnamon_memory.py\`, \`cinnamon_reminders.py\`, \`cinnamon_actions.py\`, \`cinnamon_brain.py\`.
- Existing autonomous game eligibility and activity policy already handles cooldowns, quiet/serious context, enabled features, storage and permission checks. Do not replace or duplicate it.

## Design
1. Add a pure \`brain_router.py\`: bounded input normalization, route enum, deterministic classifier, and immutable route decision (intent, confidence, reason code, matched signal). It only recognizes current human input; never classify model replies/history into action requests.
2. Routes: explicit self-reminder, explicit preference-memory management, command help, trusted action candidate, conversational response. Classification is advisory: adapters still run exact parsers and authorization.
3. Integrate in \`core_events.py\` assistance dispatcher. Invoke only the matching handler first; preserve safe fallback order for ambiguous input. Handler result (handled/not handled) is authoritative; route never creates a reminder, saves memory, or performs an action.
4. Add pure \`brain_decision.py\` (distinct from current \`brain_decision.py\` naming conflict? Current is already activity decisions; use \`brain_route_decision.py\` instead): a common typed DecisionRecord for chat/activities/action/help: wait/respond/suggest/execute/clarify, reason codes, and policy guards. Existing activity gate remains authoritative; action proposals never execute.
5. Tests first: route precedence, false-positive boundaries, message caps, invalid types, prompt-injection text treated as plain chat, route does not authorize; policy gates default to wait and fail closed; serious/quiet/disabled/storage/unconfirmed states block.
6. Documentation: update Brain architecture and plan, clearly mark merged/offline/live status.

## Files
- Create \`cinnamon_modules/brain_router.py\`
- Create \`cinnamon_modules/brain_route_decision.py\`
- Create \`tests/test_brain_router.py\`
- Create \`tests/test_brain_route_decision.py\`
- Modify \`cinnamon_modules/core_events.py\` for explicit route dispatch
- Modify \`docs/CINNAMON_BRAIN_ARCHITECTURE.md\`, \`docs/CINNAMON_BRAIN.md\`
- Keep \`main.py\` module loader unchanged for pure imports; test modules import directly.

## Acceptance
- Existing handler parsers and permissions remain the final authority.
- Current reminder/memory/help/actions behavior does not regress.
- Route and decision records are deterministic, bounded and inspectable.
- Invalid/malformed inputs and any missing policy data fail closed.
- GitHub Actions green on Python 3.11/3.12; no live claims until test-guild verification.
