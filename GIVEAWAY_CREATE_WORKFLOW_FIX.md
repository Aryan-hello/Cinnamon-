# Giveaway create workflow patch

- Added `/giveaway create` as a preview-first command with an ephemeral 15-minute preview and Start/Edit/Cancel buttons.
- Added an edit modal for prize, duration, and winner count.
- Start publishes the public giveaway only after the user presses Start.
- Added a finishing guard so timer and manual-end calls cannot concurrently select winners and send duplicate announcements.
- Kept `/giveaway start` for backward compatibility.

## Validation and limitations
- Python syntax compilation and dashboard JavaScript syntax checks pass.
- This was not tested against a live Discord application. Discord command registration may require a sync/restart.
- The create command exposes the core settings and some requirement fields, but advanced checks (message counts, level, boosts, server tag, claim deadline) are not all enforced end-to-end yet. Do not treat those options as active enforcement until implemented and tested.
