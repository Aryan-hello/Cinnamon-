# Cinnamon Brain v3 — Personalization, staff signals and diagnostics

Extends Brain v1/v2 without replacing the trusted Python action dispatcher, reminder scheduler or explicit memory system.

## Member controls (private replies)
- `/cinnamon-me style` — choose balanced, playful, calm, concise or detailed.
- `/cinnamon-me teasing enabled:<true|false>` — choose whether friendly teasing is welcome.
- Existing `/cinnamon-me privacy` and `/cinnamon-me today` remain available.

Member presentation settings are explicit, reversible and included only in that member's prompt as fixed guidance. They cannot grant permissions or override serious-conversation boundaries.

## Server voice (Administrator)
- `/cinnamon-mind style` — classic, extra playful, gentle or formal.
- `/cinnamon-mind status` — activity/action readiness.
- `/cinnamon-mind audit` — local subsystem wiring audit.

Server voice uses a closed list of fixed prompt fragments, not arbitrary admin prompt text. Cinnamon's core identity remains intact.

## Optional serious-topic staff signal (Administrator)
- `/cinnamon-incident alerts enabled:<true|false> channel:<private staff channel>`

Disabled by default. Enabling requires a channel hidden from @everyone and writable by Cinnamon. A cautious keyword signal sends at most one content-free alert every 15 minutes. Alerts include no original text, member mention or judgment. False positives are possible. Human moderators may use `/cinnamon-incident review` for a private recap and make all decisions.

## Brain audit
`/cinnamon-mind audit` checks storage readiness, Gemini configuration (not connectivity), module wiring and duplicate top-level slash names. It does not verify live Discord DM delivery, Gemini reachability or Render deployment.

## Safety
- No passive personal chat archive.
- Existing explicit member-scoped memory remains in place.
- Activity adviser receives aggregate engagement only.
- AI output never executes actions or grants permission.
- Serious conversations override playful style; members can disable teasing.
- Staff alerts are opt-in, content-free and rate-limited.

## Release checklist
- [ ] Python 3.11 and 3.12 suites pass.
- [ ] Test member style/teasing in a private guild.
- [ ] Test private staff channel alert and 15-minute cooldown.
- [ ] Verify `/cinnamon-mind audit`.
- [ ] Verify Discord registration and Render deployment separately.