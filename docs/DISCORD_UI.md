# Cinnamon — Discord interface guidelines

These conventions apply to all member-facing and staff-facing Discord messages. The aim is a deliberate, consistent interface that feels native to Discord, rather than a different visual experiment for every command.

## Visual hierarchy

- **One purpose per panel.** A screen is either a summary, selection, action, result, or error. Put the most important information first.
- **Consistent branding.** Use the semantic colors in `cinnamon_modules/ui_system.py`. Do not create a fresh orange or green in each command.
- **Text first.** Always show numeric progress, a clear status label, and the exact Catnip cost or reward. Colors, emojis, and images are supplements.
- **Concise copy.** Use short, useful button labels such as “Buy”, “Details”, “Continue”, and “Close”. Reserve longer in-character jokes for narrative responses.
- **Mobile first.** Prefer one-column information cards; avoid critical data in fixed three-column field layouts.
- **No artificial urgency.** The only countdowns should reflect real in-game timeouts or reset schedules.

## Message types

| Situation | Implementation |
| --- | --- |
| Success, error, public announcement, audit log | A classic `discord.Embed` using `cinnamon_ui_card`. |
| Personal shop, inventory, achievement collection, quest board | `discord.ui.LayoutView` with a Components V2 container. |
| Story or fishing phase | One owner-bound interactive panel; edit the same response as state changes. |
| A destructive moderator action | Permission-check at the point of use, explicit confirmation, private response when appropriate. |
| Input longer than a select option | An appropriate modal or slash-command autocomplete. |
| More items than fit comfortably on a panel | Paginate; never cram hundreds of entries into one embed. |

**Do not mix classic embeds with Components V2 in one message.** A V2 message cannot be converted back into an embed through a normal edit. Use a separate response if a legacy screen needs to open a V2 panel.

## Design tokens

- `brand`: warm orange — general Cinnamon identity.
- `gold`: achievements and rare milestones.
- `info`: inventories and neutral information.
- `success`: completed operations and confirmation.
- `warning`: recoverable issues and attention.
- `danger`: errors and destructive operations.
- `muted`: secondary details.

Use `cinnamon_ui_literal` for display names and any administrator- or member-provided string inserted into Markdown. Prefer stable bot-controlled HTTPS assets. The application bot uses `AllowedMentions.none()` by default; do not loosen it without a specific, authorized notification use case.

## Interaction contract

1. Validate guild, actor, ownership, permissions and current resource state **on every button press**, not just when the panel is opened.
2. Acknowledge Discord interactions promptly; defer when database, network, or role operations may take time.
3. Avoid double purchases or duplicate rewards by serializing mutations and checking state under a lock.
4. Keep the displayed panel synchronized with server-side state after an action. Update the original message rather than sending many progress messages.
5. Treat a button click on an expired or stale panel as a request to reopen the current state, not as permission to replay an old action.
6. A view timeout is not a persistent session. Persist game progress separately and provide a command to resume where supported.
7. Return a helpful failure message when permissions, stock, funds, or data are missing.

## Review checklist

- [ ] Does the mobile view show the goal, current status, and next action without scrolling through decoration?
- [ ] Are interactive labels meaningful without their emoji or color?
- [ ] Are there no unintended pings, unsafe Markdown, or user-controlled URLs?
- [ ] Do all embed strings fit Discord's limits, including the **6,000-character aggregate**?
- [ ] Do select menus respect their **25-option** limit, with an alternative for larger collections?
- [ ] Does every interaction guard owner, guild, and permissions as appropriate?
- [ ] Can double-clicking, pressing Back, or using an old panel incorrectly mutate state?
- [ ] Are success, error, empty and unavailable states designed and tested?
- [ ] Is there a clean path back from details to the main view?
- [ ] Has the flow been tested on Discord mobile and desktop in a staging guild?

## Technical reference

- Discord message and embed limits: https://docs.discord.com/developers/resources/message
- Components V2: https://docs.discord.com/developers/components/reference
- Interactions and acknowledgements: https://docs.discord.com/developers/interactions/receiving-and-responding
- discord.py interactions/UI: https://discordpy.readthedocs.io/en/stable/interactions/api.html

Keep this document current when changing `ui_system.py` or adding a new reusable panel.
