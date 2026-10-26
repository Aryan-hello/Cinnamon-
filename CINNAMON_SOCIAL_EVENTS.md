# Cinnamon: Surprise Hangry Games & Personality — October 26, 2026

Cinnamon is a chaotic cat with an actual mood, friends, favourite visitors, playful grudges, spontaneous questions and reactions to members' achievements. This is the current **design/implementation guide**, not evidence of a tested live Render deployment.

## Surprise Hangry Games

After an administrator re-runs **/setup**, Cinnamon creates or reuses:
- **#cinnamon-games** — the public channel for the surprise games.
- **Hangry Games** — a role members can opt into for game announcement pings.
- **#cinnamon-stuff-logs** — private personality/mood/favourites/nice-and-naughty logs. Existing #cinnamon-hangry still receives detailed game logs and prize results.

When automatic games are enabled, Cinnamon chooses the next event **randomly 1–2 hours into the future**. After a restart, saved next-event timestamps prevent an immediate duplicate burst. A game already running in the channel causes a scheduled surprise to be skipped, not duplicated.

The automatic lobby:
1. Picks an **integer prize between 1,000 and 2,500 Catnip** from the game economy (not the host's personal wallet).
2. Sends **one Hangry Games role ping at creation** with an in-character announcement and the Join button.
3. Exactly **90 seconds after posting**, sends the **second and final role ping**, warning that only 30 seconds remain.
4. At **120 seconds**, starts if at least two non-bot players joined; otherwise cancels, pays nobody, and Cinnamon theatrically complains about the missing audience. Cancellation mildly reduces her server mood.
5. Pays the winner the prize via the existing Hangry Games winner-payout path. The normal winner mention at the end is for the winner, **not an extra Hangry Games role ping**. Cinnamon congratulates the winner.
6. Surprise games **do not consume any human moderator's weekly Hangry Games prize budget** and cannot award the bot a host-farming bonus.

Cinnamon avoids spam by using **two role mentions only**, and members can unsubscribe. Administrator commands allow disabling automatic games or choosing another public channel.

## Commands

| Command | Who | Purpose |
| --- | --- | --- |
| `/cinnamon-events status` | Everyone | See enabled state, approximate next game and favourite visitors |
| `/cinnamon-events notify enabled:true/false` | Everyone | Add/remove your own Hangry Games notification role |
| `/cinnamon-events questions enabled:true/false` | Everyone | Opt in/out of occasional personal questions |
| `/cinnamon-events auto enabled:true/false` | Manage Server | Enable/disable automatic games |
| `/cinnamon-events channel` | Manage Server | Set the public game channel |
| `/cinnamon-events people` | Manage Server | View favourite visitors, nice counts, current Naughty List and mood |
| `/cinnamon-events test-game` | Manage Server | Immediately open one two-minute test lobby without changing schedule |
| `/setup` | Manage Server | Create/reuse required channels, logs and roles |
| `/recall` | Manage Server | Recover missing absolute Cinnamon personality records from Stuff logs |

**IMPORTANT:** Servers that previously ran /setup must run it again to add the new channel and role. The first setup enables the feature by default. Subsequent setups preserve an admin's previously disabled setting. Roles are mentionable to allow Cinnamon's alerts, so administrators should apply role-mention rules if needed.

## Personal Cinnamon questions

When a member **directly talks to Cinnamon** (mentions Cinnamon or replies to her), there is a **small 8% chance** she'll ask a goofy question about tuna, potatoes, or cat laws.

- At most **one personal mention per member per 24 hours**, and **one question per server per six hours**.
- She does **not** ping the person repeatedly or guilt them for not replying. If they haven't answered after two minutes, her global mood dips only very slightly and this is noted in the private Stuff log.
- If the person later talks to Cinnamon again in the same channel (within 24 hours), she playfully exclaims **YOU ARE LATE!!** or celebrates a timely reply. Answering improves her mood.
- Every member can disable questions with `/cinnamon-events questions enabled:false`.
- Cinnamon does **not** store the content of personal messages in the Stuff logs, only counts, events and a small status record.

## Celebrations and funny reactions

Cinnamon may react to:
- **Expensive purchases (5,000+ Catnip):** playful mockery like “MISTER MONEYBAGS!”
- **Legendary and Mythical fish:** excitement over impressive catches.
- **Hangry Games wins:** congratulates the winner.
- **Giveaway wins:** congratulations for members who win.
- **Nice visitors:** the tone becomes noticeably more excited.
- **Naughty members:** the pre-existing temporary Naughty List and its repair options still work.

Reactions have **15-minute cooldowns per user and event type**; they are ordinary messages without extra mentions. Multiple-winner giveaways limit the number of public Cinnamon celebration lines.

The "Nice" and "Favourite visitors" lists are based on positive **in-game** actions, **not** private chat surveillance. **Aryan remains Cinnamon's favourite human in the Wildlands story**, regardless of visitor rankings.

## Logs, restore and data

Cinnamon logs mood scores and changes, action counts, nice deeds, current Naughty List expiration, favourite visitor standings, question interactions and game events in **#cinnamon-stuff-logs**, which /setup secures to server administrators. Hangry game matches, winners, prizes and cancellations are also recorded in the existing **#cinnamon-hangry** channel.

The shared Upstash/local `advanced_features_data` contains `cinnamon_social_v1`. The Stuff log embeds contain **absolute snapshots** of recorded values rather than a stream of deltas. `/recall` scans this log (including discovering the channel by name if its saved mapping disappeared), **fills missing records only**, and reports how many personality records/mood snapshots were actually reconstructed. It cannot reconstruct chat messages or data that was never logged.

## Testing and limitations

- GitHub Actions checks code compilation, module order, command registration and offline tests. **Discord/Render have not been live tested** by these static tests.
- Use `/cinnamon-events test-game` in a private server to validate role permissions, Join buttons, two role pings, 120-second start, winner award and cancellation.
- Test surprise schedule persistence over Render restarts, /setup idempotency, /recall restores, shop and fish reactions, random question limits and member opt-out.
- This bot's current Upstash/JSON persistence does not provide atomic distributed transactions; running **multiple Cinnamon processes with the same data store** risks lost writes.
- A service restart in the middle of a two-minute game lobby can abandon that temporary lobby; the next scheduled event is not automatically duplicated. Avoid deploying during test games.

**Nothing in this feature resets player Catnip, inventories, fishing catches, Wildlands story progress, existing mood data, staff budgets or previous Hangry Games statistics.**
