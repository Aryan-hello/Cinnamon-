# Cinnamon Wildlands artwork — what is integrated

- Reuses 50 prior Runway generated assets; no images regenerated.
- Permanent artwork import is scheduled through the GitHub Actions workflow on push; background auto-cache on Render is included as a fallback. External Runway CDN access is unavailable in this sandbox, so no image bytes are included in this ZIP.
- When the importer runs successfully, all available images are saved as compressed WebP into `static/wildlands/`, with transparency retained on the 46 cutouts.
- `static/wildlands/manifest.json` identifies all 50 asset filenames and original Runway task IDs. The actual images are NOT in this ZIP; the workflow or bot background importer must first download them.
- Four named fishing area images are wired directly into `/wildlands places`.
- The 46 anonymous transparent cutouts are visible to server staff via `/wildlands art-vault` (Prev/Next), with no guesses as to item identity.
- All views are built as image-left/text-right cards for convenient Discord mobile and desktop viewing; no user images are displayed in this document or the ChatGPT response.
- No edits to existing economy, achievement, quest, or dashboard commands.

## How to deploy on GitHub and Render

1. Extract the provided ZIP and upload all folders to the same GitHub repository as Cinnamon, including the hidden `.github` folder.
2. In GitHub, open the **Actions** tab. Confirm the **Save Cinnamon Runway artwork** workflow ran from your new commit. If not, start it manually. This must happen while the temporary Runway links are valid (the earliest expires on 25 Oct 2026, 14:12 IST).
3. The workflow commits the resulting `static/wildlands/...webp` files to your GitHub repository. Render will redeploy after GitHub receives that commit (if Render auto-deploy is enabled).
4. In Discord use `/wildlands art-status` to check saved images; `/wildlands places` for areas; `/wildlands art-vault` for staff-only inspection. No need to open the old image-heavy ChatGPT chat.

If the GitHub workflow cannot download some or all files, it will report the missing keys and commit any files it successfully copied. A missing asset displays a text fallback; it does not crash the bot.

## Future mapping and gameplay

The source package given for this update predates the actual Wildlands game code. It is not possible to infer the names and rarities of 36 fish plus which cutout shows each rod or bait from 46 anonymous generated-image filenames. Rather than risk mismatched fish art, the complete set is saved by number for inspection in Discord; a later update can connect IDs to item names, rarities, Buy buttons, fish filters, inventories, and game mechanics.
