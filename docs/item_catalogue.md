# Cinnamon Item Catalogue

Central item identity reference for Cinnamon. Keep existing item IDs and inventories stable when integrating.

## Materials
- `moon_fish_scale` — Moonfish Scale (Rare): advanced crafting ingredient; Cosmic Churu, Moonlight accessories.
- `golden_thread` — Golden Thread (Uncommon): accessory material; Catnip Crown, collars, decorations.
- `star_dust` — Star Dust (Rare): magical material; Cosmic Churu, Starry Elixir, high-tier recipes.
- `moonstone` — Moonstone (Epic): high-level material; Starlight Hat, Dream Wings.
- `crystal_fishbone` — Crystal Fishbone (Uncommon): food/decor ingredient; Tuna Stew and fish collectibles.
- `golden_paw_charm` — Golden Paw Charm (Rare): accessory material; Golden Bell Collar.
- `dream_petals` — Dream Petals (Legendary): legendary material; Dream Wings, Moon Jelly.

## Food
- `fish_biscuits` — Fish Biscuits (Uncommon): basic feeding item; feeding quests.
- `cosmic_churu` — Cosmic Churu (Epic): premium treat; special feeding achievements/quests.
- `tuna_stew` — Tuna Stew (Uncommon): crafted food; feeding quests and collection.
- `pawberry_cake` — Pawberry Cake (Rare): special food; event quests/achievements.
- `honey_fish_treat` — Honey Fish Treat (Uncommon): crafted snack; daily feeding quests.
- `moon_jelly` — Moon Jelly (Legendary): rare food; special feeding achievements/events.
- `royal_tuna` — Royal Tuna (Rare): premium food and crafting ingredient; feeding and Royal Tuna recipes.

## Collectibles
- `golden_fish` — Golden Fish (Epic): collection collectible and crafting ingredient.
- `paw_treasure` — Paw Treasure (Rare): collectible chest; collection achievements/display.
- `cinnamon_snow_globe` — Cinnamon Snow Globe (Legendary): seasonal collectible/display.
- `captured_star` — Captured Star (Mythical): ultra-rare collectible; special title/achievement.

## Accessories
- `catnip_crown` — Catnip Crown (Legendary): prestige profile accessory.
- `golden_bell_collar` — Golden Bell Collar (Rare): wearable/profile accessory.
- `starlight_hat` — Starlight Hat (Epic): magical profile accessory.
- `dream_wings` — Dream Wings (Mythical): exclusive profile accessory.

## Consumables
- `purr_potion` — Purr Potion (Rare): proposed +25% eligible XP for 30 minutes; no stacking.
- `lucky_paw_clock` — Lucky Paw Clock (Epic): proposed +25% to one eligible work/daily reward; one use per claim.
- `treasure_map` — Treasure Map (Legendary): starts one treasure hunt; one active hunt at a time.
- `starry_elixir` — Starry Elixir (Mythical): fixed XP bonus within configured level/XP limits.

## Mystery boxes
- `mystery_box` — Mystery Box (Uncommon): Catnip/common materials/food and occasional uncommon rewards.
- `rare_mystery_box` — Rare Mystery Box (Epic): rare materials, accessories, premium food, collectibles.
- `mythical_mystery_box` — Mythical Mystery Box (Mythical): highest-tier rewards; mythical collectibles/accessories and substantial Catnip.
- Reward odds should be displayed before opening.

## Proposed recipes (not yet implemented)
- Fish Biscuits: basic fish ingredients.
- Honey Fish Treat: Fish Biscuits + Golden Thread.
- Tuna Stew: Royal Tuna + Crystal Fishbone.
- Cosmic Churu: Moonfish Scale + Star Dust.
- Pawberry Cake: Dream Petals + Honey Fish Treat.
- Catnip Crown: Golden Thread + Star Dust.
- Golden Bell Collar: Golden Paw Charm + Golden Thread.
- Starlight Hat: Moonstone + Star Dust.
- Dream Wings: Moonstone + Dream Petals.
- Moon Jelly: Moonfish Scale + Dream Petals.

## Item behavior
- Materials/food stack; consume only when crafting/feeding succeeds.
- Collectibles are collection entries and are not consumed.
- Accessories: one owned copy unless duplicates are deliberately enabled.
- Consumables and boxes stack and are consumed on successful use/open.
- Keep descriptions, rarity, icon, obtain method, and use behavior in one central catalogue so shop, inventory, crafting, rewards, and dashboard share it.

**Status:** design catalogue only. Proposed effects/recipes are not live until wired into bot logic.
