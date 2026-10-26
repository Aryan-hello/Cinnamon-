# Cinnamon moods & Hangry Games prize budgets — October 26, 2026

**Status:** Proposed gameplay update on the dedicated feature branch. Source has offline syntax/unit checks; no live Discord or Render deployment has been tested yet.

## Cinnamon has moods

Cinnamon has a **per-server mood**: Normal 🐈, Delighted 😻, or Grumpy 😾. It is persisted in the existing `advanced_features_data` snapshot (Upstash when configured). Every 30 minutes of inactivity, its score slowly drifts toward Normal.

| Mood | Main economy shop & fishing merchants | Wildlands rare-fish odds |
| --- | --- | --- |
| Normal | Existing base prices | Existing base odds |
| Delighted | 10% sale, with an approximately 25% chance of a 25% **flash discount per item / 30-minute window** | Moderate rarity improvement (+1 weighted-luck unit) |
| Grumpy | Prices +20% | Rarer fish slightly less likely (-0.8 weighted-luck units) |

This is a **weighted probability change**, never a guaranteed rare catch. Mood-driven price changes apply to the main economy shop, both normal shop buying methods, the prefix `?buy` command, and the Wildlands fishing rod/bait merchant purchases and catalogs. Free items remain free. Black Market listings have their own independently set prices and currently stay independent of mood.

**No actual base prices are rewritten.** Shown prices and charged prices are computed from the current mood, allowing discounts or surcharges to change without touching inventory.

## How to interact with Cinnamon

- `/mood status` — see mood, modifiers and personal Naughty List status.
- `/mood talk` — listen to Cinnamon and gently improve her mood.
- `/mood play` — play with toys, cheer her up and help make amends.
- `/mood apologize` — ask for removal from the temporary Naughty List once two good actions are completed.
- `/pet` and `/treat` — boost mood with an interaction cooldown.
- `/economy feed` — feed real inventory items to improve her mood, but **five or more snacks within ten minutes** (including a large single feed) makes her grumpy and earns a temporary Naughty List role.
- Petting, playing, talking and feeding share a **90-second per-member mood action cooldown** so scripts cannot instantly max out mood or exploit discounts.
- When Grumpy, Cinnamon gives a special theatrical annoyed response to direct pings. Repeated rapid pings can land someone on the Naughty List.

The playful **Cinnamon's Naughty List** role lasts at most 30 minutes, and while active adds **1,000 Catnip per item** to the main shop and fishing merchant prices. It is **not an irreversible punishment**: two positive actions and `/mood apologize` remove it early; a restart-tolerant reaper automatically clears expired role assignments when possible. A role-creation/permission failure does not prevent the saved status and fair timer from working.

## Hangry Games Catnip prizes

Optionally add `catnip_prize` to:
- `/hangrygames new` — lobby; payout is reserved only when the sponsor starts the match.
- `/hangrygames giveaway` — optional Catnip alongside the existing textual prize/winner role.
- `/hangrygames role` — immediately runs with selected members and the optional Catnip prize.
- `/hangrygames budget` — member-only view of weekly allowance, spent, remaining, completed games and runner bonus.

Budget limits are determined **from the funding member's current permissions**:
- **Manage Messages:** 20,000 Catnip per week.
- **Moderate Members / timeout:** 30,000 Catnip per week.
- **Administrator:** no weekly budget ceiling.
- Multiple permissions use the **highest** available tier. Non-staff can join games but cannot sponsor Catnip prizes.

For anti-abuse, a single game may award up to **200,000 Catnip**, including when an administrator creates it. Hosting allowance is *not* deducted from the host's personal wallet; it is a weekly guild-funded prize allocation. Budget usage is recorded in the Hangry Games data store, resets Monday 00:00 UTC, and is logged with sponsor, game and reward details. When a game is cancelled without a prize payout, the reservation is refunded to the same week's allowance.

**Host appreciation:** Every fifth game **completed** by the person who started/sponsored a game has a 30% chance of awarding a bonus of 250–600 Catnip; host bonuses are capped at **1,500 Catnip per week**. This is logged to Hangry Games logs and added to the existing Catnip wallet, not paid in real money.

## Preserved existing features

Wildlands story, permanent merchant channels, finder commissions, 100,000 Catnip story finale, existing quest and achievement commands, regular Hangry Games with no prize, giveaway roles, fishing items, and current Catnip balances are unaffected outside the listed mood modifiers. No data migrations delete old progress.

## Live staging and limitations

- [ ] Confirm `/mood` commands, cooldowns, role hierarchy and role expiry in Discord.
- [ ] Verify every shop surface reflects the actual charge across temporary mood changes.
- [ ] Test rare-fish distribution over many test casts for Delighted/Normal/Grumpy.
- [ ] Confirm Hangry prize sponsor permissions, max budgets, weekly UTC reset and cancelled-game refunds.
- [ ] Verify an actual Hangry winner receives Catnip **once**, and host bonus caps.
- [ ] Validate logging, persistence and restore across Render restarts.
- [ ] Check older messages with stale price buttons and bot command refresh behaviour.

Current Hangry Games budget writes and economy payouts use the existing persistence system, **not database transactions**. A rare crash or concurrent redeploy during an in-flight game can still require manual reconciliation from logs; avoid running multiple Cinnamon instances against one datastore until transactional accounting is implemented.
