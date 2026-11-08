# Cinnamon Final Safety & UX Release — October 26, 2026

**Historical release notes (26 October 2026):** these describe an earlier Cinnamon revision and are **not the current deployment guide**. The current source has subsequently added a trusted allowlisted natural-language action system, memory, reminders, contextual independence and newer storage safeguards. Use [the current README](README.md), [Cinnamon Brain](docs/CINNAMON_BRAIN_PHASE2.md), and [Command Audit](docs/COMMAND_AUDIT.md) for current behavior. GitHub tests alone do not verify live Discord, Render, Upstash, OAuth or the dashboard.

## Critical fix

The previous /economy give accepted negative amounts, allowing an inverted transfer that could create Catnip for a sender and reduce the recipient's wallet. It now uses a native Discord member selector, amount 1–10,000,000, and redundant server-side positive validation. Similar negative quantities were closed in administrator inventory actions, and edited/new item prices are bounded. Old wallet records are not silently rewritten.

## Cinnamon's safe mind

The Gemini AI may generate character dialogue only, never autonomous Catnip rewards, moderation, staff role grants, channel visibility changes or @everyone announcements. All normal bot output is default-denied Discord mentions.

Cinnamon answers direct user ping, reply, or clear invocation by name ("Cinnamon?" or "hey Cinnamon"). She ignores incidental "cinnamon rolls" and normal person-to-person chat, including in the dedicated AI channel. Exception: a two-percent chance of one non-pinging jealous cat line if someone discusses another cat; at most once every six hours per server, with a server-manager toggle. The cameo never starts an AI dialogue.

Explicit mass announcements use /cinnamon-events announce with selected channel and text, Administrator permission, 60-second in-chat Confirm/Cancel buttons, and 15-minute rate limit. That confirmation callback is the only function permitted to set everyone=True in AllowedMentions.

## Setup, merchant channels and logs

/setup accepts an optional native TextChannel selector for the Hangry game channel. Setup creates/reuses Cinnamon Mood and Cinnamon Stuff private logs, a public default games channel, both fishing rod and fishing bait merchant channels (private unless currently discovered/open) and matching roles. Rerunning setup preserves active merchant discovery windows, staff settings and any previously selected Hangry channel.

Staff with Manage Channels or Moderate Members can use /fishing merchant-access to make the rod or bait merchant private, public for 2 hours, or public until staff closes. A staff opening has no finder commission; optional merchant role announcement is OFF unless selected. Discoverers still get their usual 10% Catnip bonus on eligible other-customer purchases inside their shop. Treasure Hunters still have permanent access.

## Polished user experience

Wildlands story scenes now have consistent titles, region, clue counts and numeric progress bars. Fishing cast now shows owned bait options, defaults to cheapest bait, and offers Reel gently / Keep steady / YANK! choices. Only the actual reel spends bait and grants the fish; the 30s cooldown and per-user lock protect double-clicks. Rarity remains determined by rod, bait and Cinnamon mood, not reaction speed. Expired fishing views waste nothing.

Hangry Games, Mood, Fishing and Cinnamon Events embeds were improved for readability and warmth. Economy item names in buy/feed/item-add/item-remove/edit/remove now use dynamic autocomplete. /economy give uses a native named member selector.

The Flask dashboard received Cinnamon Mind and Wildlands/Fishing pages for guild-scoped mood, autonomy switches, Hangry game destination, visitor standings, merchant private/public states, story/fishing statistics, gear catalog, Catnip gifts, and controlled staff actions. Form choices use names rather than asking users to remember IDs; large existing dropdowns now receive a progressive local name filter. Responsive CSS, visible focus styles and mobile sizing follow feedback from the existing Lovable Cinnamon prototype.

## Deploy only after these smoke checks

1. Back up Upstash/JSON data, note old main commit SHA, and run one bot process only.
2. In test guild, run /setup twice: check no duplicates, both merchant channels hidden, custom Hangry channel kept, private mood/stuff logs.
3. Try /economy give with negative, zero, positive and huge numbers and confirm no money is created. Check negative admin item quantities also fail.
4. Try normal person-to-person chat in AI channel and incidental cinnamon-roll text (no reply), then direct mention/reply/name (reply). Check no AI @everyone and admin confirmed announce only.
5. Test Hangry game announcement in custom channel and only two role pings, no reward without 2 entrants, positive game winner Catnip.
6. Test discovery opening/closing shops and staff merchant-access manual toggles, finder commission only when discovered, Treasure Hunter permanent access.
7. Test fishing owner-only selectors, double click, view timeout, bait counts, rare-fish roles and journals; test story scene completion only pays once.
8. Test dashboard Discord OAuth guild checks, CSRF protection, role/channel/member selection, personality controls, live merchant status, nonnegative wallet transfer, and mobile layout.
9. Restart Render, verify persistence via Upstash, and exercise /recall. If any serious fault appears, roll back code, preserve snapshot backup and reconcile balances from logs.

Research sources: https://discord.com/developers/docs/resources/message | https://discord.com/developers/docs/interactions/application-commands | https://discord.com/developers/docs/components/reference | https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
Lovable prototype: https://lovable.dev/projects/792aa59b-628e-4021-9e97-895933597f0f
Notion notes: https://app.notion.com/p/405df5931d23817f885ad91927c74e0b
