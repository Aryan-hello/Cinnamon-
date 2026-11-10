# Brain compound planner (experimental, not yet connected to Discord execution)

This branch adds a **pure parser/planner** for a narrow compound-command subset.
It does not change production command routing or execute anything.

Supported clauses:
- `add 2k catnip to @A and @B` (Discord mentions; expands to one typed action per target)
- `remove 500 catnip from @A`
- `mute @A for 10 minutes` / `timeout @A for 10m`
- `unmute @A`

Combine clauses with `and`, e.g.:
`add 2k catnip to @A and @B and mute @C for 10 minutes`

## Safety contract

- Uses existing `ActionProposal` and `validate_proposal`; no new action types.
- Parses only current explicit text; never model output, quoted text, channel history, or documents.
- No authorization is inferred. Adapter must check all permissions, targets, hierarchy and storage readiness for **every** action before confirmation.
- No partial execution: adapter must show one complete plan and require requester-bound confirmation; if any validation/check fails, execute none.
- Planner itself makes no Discord/API/storage calls.
- Unsupported clauses fail closed; existing single-action parser remains the authority for single requests.
- Expanded batch capped at eight; Catnip per target capped at 1,000,000; timeout at 24 hours.

## Integration still required

Wire `parse_compound_request` into the trusted action message handler before the current single-action parser, then adapt confirmation/execution to process the entire tuple atomically (preflight all actions, requester-only confirmation, idempotency receipt per batch, clear partial-failure reporting). Until that adapter work and live Discord tests land, compound requests are **not active in production**.

Tests: `pytest -q tests/test_brain_compound.py`
