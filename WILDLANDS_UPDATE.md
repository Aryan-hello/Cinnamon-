# Cinnamon: Wildlands — Playable Adventure Update

## Design research applied

The public documentation of established Discord RPGs illustrates two useful patterns: a clear resource-to-crafting-to-progression loop and a compact Discord-native hub that reduces command memorisation and channel spam. Wildlands applies these broad patterns to Cinnamon rather than copying another game's items, characters, text, or exact progression.

## What is included

### Explore

- Six connected areas: Whispering Woods, Quiet Shore, Stoneback Highlands, Moonlit Marsh, Frostfall Pass, and Forgotten Ruins.
- Encounter prompts with three strategic choices: Gather supplies, Investigate, or Follow tracks.
- Each choice can give materials and XP; investigation is more clue-oriented, while tracks have a higher-variance path toward secrets.
- Energy regenerates one point every two minutes. An unfinished encounter can be resumed without paying again.

### Build and progress

- Six resource families across common, coastal, mountain, marsh, cold, and ruin regions.
- Permanent gear blueprints and camp facilities that affect pack capacity, resource gathering, clues, and food bonuses.
- Personal XP and levels, clue journal, secret discovery journal, and unlocked map areas.
- Catnip/material costs for camp upgrades and modest Catnip values for selling excess materials.

### Connect with existing Cinnamon features

- Keeps the existing fish and cooked dishes in Cinnamon's shared economy inventory.
- `/adventure pack` consumes one cooked dish for an expedition bonus instead of making a second copy of food.
- Connects completed exploration, collected materials, clues, secrets, crafted gear, camp upgrades, and area visits to Wildlands achievements and daily/weekly quest options.
- Keeps first-discovery records per server and shows a Wildlands leaderboard.
- Stores Wildlands records inside `advanced_features_data` so the existing persistence mechanism saves it with the rest of Cinnamon.

## First play-through

1. `/adventure start`
2. `/adventure play`
3. Press **Explore** and choose an encounter approach.
4. Check **Pack** and **Journal** from the hub.
5. Use `/adventure recipes` and `/adventure craft` to make gear.
6. Use `/adventure map` then `/adventure travel` to open new resource regions.
7. Cook a dish through Cinnamon's existing `/cook make` and pack it before a future expedition with `/adventure pack`.

## Full command list

`/adventure play`, `/adventure start`, `/adventure help`, `/adventure explore`, `/adventure status`, `/adventure map`, `/adventure travel`, `/adventure inventory`, `/adventure recipes`, `/adventure craft`, `/adventure camp`, `/adventure pack`, `/adventure sell`, `/adventure journal`, `/adventure leaderboard`.

## Deployment / testing note

Run this package in a private Discord test server first. Static Python compilation and AST checks passed, but this environment could not import the full bot because `discord.py` was unavailable and network access to install it was blocked. The live command sync, interaction callbacks, server permissions, and Upstash/Render persistence have not been tested from this workspace.
