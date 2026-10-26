# Repository cleanup audit — 26 October 2026

Scope: complete tracked-file tree, including all Python modules, `dashboard.py`, the start-up loader, existing tests, GitHub workflows, release documentation and the Wildlands feature. Inspected active command decorators and command group registrations as well as source cross-references. This is a **static code audit**, not a live Discord integration test.

## Retired only after verifying the active replacements

| Removed | Why it was redundant | Active replacement / result |
| --- | --- | --- |
| `cinnamon_modules/wildlands.py` | Uploaded Oct 23, **not in `main.py` active module loader**. Defines obsolete `/adventure` gathering / sanctuary story. | Oct 26 `wildlands_story.py` is loaded, with choice-driven Cinnamon treasure narrative; `wildlands_fishing.py` handles separate fishing. |
| `cinnamon_modules/fishing.py` | Uploaded Oct 23, **not loaded**; contains older `/fish` and `/cook` handlers, old points and dishes. | `wildlands_fishing.py` (last updated Oct 26) is active for fishing, rods, bait, merchant access, 36 collectible fish. Old `/fish` and `/cook` commands were already inactive and are **not falsely claimed as preserved**. |
| `FISHING_POINTS_UPDATE.md` | Outdated guide to the inactive `/fish` command implementation. | Current Wildlands guide links active `/fishing` functionality. Historic guide remains in Git history. |

## Duplicate registrations and command UX

- In `core_events.py`, startup **globally synced** slash commands, then `copy_global_to` for every guild and synced those duplicates. The redundant guild copies may show the same command twice. Fixed by syncing globals and using `clear_commands(guild=guild)` followed by `sync(guild=guild)` to remove stale guild copies. There were no explicit guild-specific commands in the loaded modules based on static inspection. Discord client caches may briefly still display old entries.
- In `quests.py`, two top-level aliases `/dailyquests` and `/weeklyquests` duplicated `/quests daily` and `/quests weekly`. Removed the redundant aliases and made the grouped commands reuse the better paginated `QuestPageView`. Kept `/quest` for the existing quest launcher; kept `?quest daily` and `?quest weekly` since they are prefix interfaces, not slash duplicates.
- Python AST tests now detect duplicate direct slash names and duplicate commands within shared `app_commands.Group` definitions, ensure all configured modules exist exactly once, and confirm the obsolete source modules cannot accidentally be loaded.
- The separate `dashboard.py` file is **not** a duplicate Flask server: `dashboard_runtime.py` registers its `dashboard_bp` blueprint into Cinnamon's `flask_app`. Kept both.
- Slash and prefix versions of commands (e.g. `/economy work` versus `?work`) are alternate interfaces, not duplicate registered slash commands. Kept them.
- Quest, achievement and economy modules are distinct systems despite sharing source globals; deleting them as duplicates would remove real features. Kept them.
- Preserved Wildlands art, merchants, fish, rods, bait, roles, all persistent user data and shop channels.

## Documentation / regression protection

- Rewrote `WILDLANDS_UPDATE.md` to document the *Treasure Worth Billions* story, commands, merchant commissions and legacy retirements.
- Added a prominent Wildlands update pointer to `README.md`.
- Marked old narrative entries in `CINNAMON_RELEASE_NOTES.md` as historical.
- Extended GitHub Actions to run syntax compilation and the complete `tests/` suite on main and feature/cleanup pushes and applicable pull requests.

## Validation and limitations

- GitHub Actions runs syntax compilation and the entire offline unittest suite. Check actual run status before merging.
- No live Discord testing was performed for this audit. Verify global slash propagation, existing command functionality, merchant channel permissions and story continuation on Render after deploying.
- Persistent old Wildlands save keys are deliberately untouched. Delete archived member records only via a separate backup-reviewed migration, never as part of source cleanup.
- `Static/wildlands` artwork importer references may expire, but those are **not duplicate Python gameplay modules** and remain untouched until verified.
