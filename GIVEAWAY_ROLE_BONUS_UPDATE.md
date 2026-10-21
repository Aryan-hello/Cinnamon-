# Giveaway role bonus update

- Removed the standalone `/giveaway start` subcommand. Use `/giveaway create`, then the preview's Start button.
- `extra_entries` now accepts role mentions followed by a bonus count, comma-separated. Example: `@Level 1 3, @VIP 5` means Level 1 adds 3 extra entries and VIP adds 5.
- `required_roles`, `bypass_roles`, and `blacklisted_roles` accept comma-separated role mentions.
- Role bonuses are stored by role ID and only apply to members who have those roles. The global extra-entry bonus is set to zero so it cannot accidentally grant everyone bonus entries.
- Each bonus is validated from 1 to 250. If multiple bonus roles match, their counts stack.

Validation performed: Python syntax compilation. Live Discord command registration/interactions still require deployment testing.
