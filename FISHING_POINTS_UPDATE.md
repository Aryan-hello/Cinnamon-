# Cinnamon Fishing: Selling, Memory, and Fishing Points Update

## Shop decision
- Fish are **not shop stock**. Fish are obtained by fishing, and the module forcibly sets their `shop_enabled` flag to false to disable leftover settings from the previous experimental version.
- All fish remain in Cinnamon's shared inventory, so `/economy feed`, `/fish sell`, inventory, and cooking use the same item counts.

## Improved selling
- `/fish sell` removes only fish the player actually owns and awards Catnip using the fish's sale value.
- `/fish sell` updates fish-sold quest progress, economy logs, inventory achievements, and Catnip-earned achievements.
- The Fishing Points upgrade **Market Sense** adds +5% fish sale value per level, up to +25%. It cannot create a buy/sell arbitrage because fishing fish are not sold in the shop.

## Cinnamon Memory
- Feeding Rare, Epic, Legendary, or Mythical fish with `/economy feed` increases persistent Cinnamon Memory.
- Memory gain per fish: Rare +1, Epic +2, Legendary +3, Mythical +5. Memory is capped at 100.
- Memory contributes up to +20% luck strength. The Lucky Rod upgrade adds up to another +10%, with combined luck strength capped at 30%. This adjusts weighted odds but does not guarantee rare catches.
- `/fish bond` shows memory, rare fish fed, the memory contribution, and the next bond milestone. `/fish stats` shows overall fishing stats.

## Fishing Points and upgrades
- Fishing Points are awarded for successful catches: Common 1, Uncommon 2, Rare 3, Epic 5, Legendary 8, Mythical 12.
- `/fish points`, `/fish upgrades`, and `/fish upgrade` show and spend points.
- Lucky Rod: shifts catch odds toward rarer fish.
- Quick Cast: reduces cooldown by 5 seconds per level (minimum 20 seconds).
- Angler's Instinct: +1 FP per level per successful catch.
- Steady Hands: reduces missed-bite chance by 1 percentage point per level (minimum 2%).
- Golden Hook: +10% fishing XP per level.
- Market Sense: +5% fish sale value per level.
- `/fish odds` displays the player's current rarity probabilities. Base rarity odds remain Common 65%, Uncommon 22%, Rare 9%, Epic 3%, Legendary 0.8%, Mythical 0.2% when no luck bonuses apply. A missed bite is a separate 7% roll; Steady Hands reduces that chance.

## Validation
- Python syntax compilation passed for `main.py`, `dashboard.py`, and all `cinnamon_modules/*.py`.
- Static and probability checks are run on the packaged module.
- Live Discord command registration and end-to-end server testing were not performed in this environment.


## Fish sale price increase
- Fish now sell for 3× their original base sale value (a 200% increase).
- Market Sense bonuses are applied on top of the increased sale value.
- Cooked-dish prices and ingredient valuation remain unchanged.
