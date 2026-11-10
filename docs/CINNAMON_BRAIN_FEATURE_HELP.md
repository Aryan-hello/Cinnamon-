# Cinnamon Brain Feature Help: coverage and guardrails

## Goal
Cinnamon should answer feature questions in her own playful, warm cat voice while giving accurate, practical guidance grounded in the live command registry.

## Current help coverage added
- Moderation: timeout/mute, unmute, kick, ban, incident review; permission and role-hierarchy caveats.
- Roles/reaction roles: role assignment and Discord hierarchy requirements.
- Leveling: XP/rank/profile/leaderboards; avoid inventing exact thresholds.
- Community games/Hangry Games: commands and voluntary surprise-game boundaries.
- Giveaways: member entry and staff-controlled management.
- Wildlands: explain as exploration/gameplay, explicitly distinguish live registered commands from planned concepts.
- Social events: route to currently registered event commands.
- Dashboard: link request is public; settings remain owner/Admin-only.
- Profiles: public progression and configured stats.
- Existing guides retained: quests, fishing, stories, achievements, economy, reminders, personal memory, personal day, independence, incident reviews, and `/recall`.

## Source-of-truth policy
- Slash command paths, descriptions, and parameter syntax come from the runtime command catalog.
- Explain feature behavior only when supported by implementation/docs. If an exact reward, threshold, cooldown, option, or server setting is unknown, say so instead of guessing.
- Proposed roadmap features (Cat Companion, Living World, etc.) are not live features unless implemented and registered.
- Help answers must never execute commands or grant permissions.
- Sensitive actions require the normal Discord/Cinnamon permission checks; help is not authorization.

## UX direction
- Keep answers concise, useful, and in Cinnamon's voice (light cat mannerisms, not overdone).
- Explain what it is, how to start, key commands, rewards/requirements, limits, and a relevant safety/privacy note.
- Prefer command links/mentions where supported; use exact current paths.
- Ask a short clarification if the feature name is ambiguous.
- Add regression tests whenever a feature guide is introduced or changed.

## Current implementation PR
Expanded deterministic feature routing in `cinnamon_modules/brain_help.py`, plus tests in `tests/test_brain_feature_help.py`.
