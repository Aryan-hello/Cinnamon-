# Cinnamon — Achievement / Quest / Shop Update

**Historical feature summary:** use `/help` for the current registered slash commands and `docs/COMMAND_AUDIT.md` for the latest command audit. The notes below describe the achievement/quest milestone, not an up-to-date production certification.

This build uses the user's text master list as the source of truth for the achievement and quest definitions.

## Included
- 49 regular achievements from the master list.
- Admin-only `Cinnamon's Favourite Human`.
- 11 secret achievements, including S11 Midnight Snack.
- `/achievement` command group with member views and admin controls.
- Rotating daily and weekly quest pools; use `/quests daily` and `/quests weekly` for the canonical slash subcommands, or `/quest` for the paginated board. Five daily and five weekly selections persist when the underlying snapshot store is durable and healthy.
- Quest Points (QP) and `/questshop` redemptions from the supplied list.
- Achievement/quest persistence through the existing Cinnamon persistence layer.
- Tracking hooks for messages, Cinnamon pings/interactions, economy purchases/feeding/work/give/collect, polls, giveaways, levels, and Hangry Games.
- Default shop prices raised to 1,000+ Catnip:
  - Tuna: 1,000
  - Cat Treat: 1,000
  - Churu: 1,500
  - Catnip Ball: 2,000
  - Fancy Fish: 2,500
- Existing saved shop items are migrated to a minimum price of 1,000 Catnip.
- Newly added/edited shop items cannot be priced below 1,000 Catnip.

## Important
The Catnip/XP/AP/role reward values are the values in the current master list, but they remain editable because the user has not declared the reward sheet final yet.

The master list did not define Box achievements or Box shop items, so this build does not invent them.
