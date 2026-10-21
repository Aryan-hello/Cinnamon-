# Cinnamon Giveaway Audit Fixes

## Changes in this patch
- Added a per-giveaway `stack_bonus_entries` setting. It defaults to enabled for existing giveaway/dashboard behavior; when enabled, matching role bonuses add together. When disabled, only the largest matching role bonus applies.
- Expanded validated extra-entry values from 1–20 to 1–250 per role.
- Replaced repeated ticket-list expansion with weighted random selection, avoiding large memory allocations from malformed or high-entry configurations.
- Rechecked current eligibility at reroll time when the member is available in the guild cache.
- Rerolls exclude every ID already in `winner_ids`, so the current and previous winners cannot be selected again.
- Made dashboard rerolls use the same eligibility and weighted-selection helpers as slash rerolls.
- Kept an active giveaway in active state until selection and history creation are ready, reducing the risk that an exception early in completion loses the active record.
- Added the stack toggle to the dashboard create/edit forms and passed its value through the existing validator.

## Validation run
- `python -m py_compile` across all `.py` files: passed.
- `node --check static/dashboard-mobile.js`: passed.

## Not verified
- Live Discord interactions, command sync, member cache behavior, Discord permissions, and Render deployment were not tested.
- The current source archive did not contain the previously described `Cinnamon_giveaway_upgrade.zip`; this patch is based on `Cinnamon_main_only.zip` available in the session.
- This patch does not claim to finish every item from the full giveaway specification (for example, the complete preview/edit flow, claim-time rerolls, all requirements, and full schedule/template command set remain separate work).
