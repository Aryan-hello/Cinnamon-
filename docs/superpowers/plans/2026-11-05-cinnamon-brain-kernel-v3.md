# Cinnamon Brain Kernel v3 — Implementation Plan

> **For agentic workers:** Use Superpowers TDD and verification-before-completion. Steps are checkboxes.

**Goal:** Unify Cinnamon's existing chat context into a small, explicit, testable brain context kernel without granting model output execution authority.

**Architecture:** A pure Python module normalizes and bounds recent turns, current message, member-scoped preferences, mood, tone, and safety framing. The existing Gemini adapter consumes that structured context; all action parsing, authorization, confirmation, and execution stay in trusted runtime modules.

**Tech Stack:** Python, dataclasses, unittest, existing discord.py + google-genai runtime.

**Spec:** Notion Cinnamon Vision & Brain roadmap (31 Oct 2026), Brain v1 + Phase 2; docs/CINNAMON_BRAIN.md.

## Global Constraints
- User/member content and memory remain untrusted data, not instructions.
- No model-generated text directly invokes Discord APIs, economy, or moderation.
- Keep member preference retrieval scoped to the current member and guild.
- No new scheduler or second bot.
- No public-channel pings from model output; existing AllowedMentions.none remains.
- Offline tests do not count as live Discord verification.

## Review Focus
- Prompt-injection strings remain inert data.
- Context cannot exceed bounded message, turn, or preference limits.
- Missing/invalid identifiers do not broaden memory scope.
- Empty/invalid turns are skipped safely.
- Existing channel conversation and Gemini reply behavior remain compatible.

## File map
- `cinnamon_modules/brain_kernel.py`: pure bounded context model/serializer.
- `tests/test_brain_kernel.py`: regression tests for normalization, scope, limits and untrusted framing.
- `main.py`: use kernel to assemble Gemini context, preserving existing system prompt and reply output contract.
- `docs/CINNAMON_BRAIN.md`: update architecture/status and current implementation truth.

## Tasks
- [ ] Add the kernel tests and confirm they fail because module is missing.
- [ ] Implement pure context normalization and deterministic serialization.
- [ ] Integrate context kernel into `ask_gemini` without changing action authority.
- [ ] Update docs with accurate merged status and boundaries.
- [ ] Run GitHub Actions syntax/tests; inspect full diff and CI before merge.
- [ ] Keep PR unmerged until review; deployment/live-guild test remains separate.

