"""Shared, explainable Brain decision records with fail-closed policy defaults.

This is a pure policy helper. It never invokes Discord, writes data, calls a
model, or grants permission. Runtime adapters must re-check their own guards.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DecisionKind(str, Enum):
    WAIT = "wait"
    RESPOND = "respond"
    RESPOND_GENTLY = "respond_gently"
    SUGGEST = "suggest"
    CLARIFY = "clarify"
    REFUSE = "refuse"
    EXECUTE_CANDIDATE = "execute_candidate"


@dataclass(frozen=True)
class DecisionInput:
    intent: str
    feature_enabled: bool = True
    serious: bool = False
    quiet: bool = False
    storage_ok: bool = True
    permission: bool = False
    confirmed: bool = False
    enabled: bool = False
    engaged: bool = False


@dataclass(frozen=True)
class DecisionRecord:
    kind: DecisionKind
    reason: str
    intent: str
    requires_runtime_recheck: bool = True


def _record(kind: DecisionKind, reason: str, intent: str) -> DecisionRecord:
    return DecisionRecord(kind=kind, reason=reason, intent=intent)


def decide(value: DecisionInput | None) -> DecisionRecord:
    """Produce an explainable decision; missing/malformed input defaults to wait."""
    if not isinstance(value, DecisionInput) or not isinstance(value.intent, str):
        return _record(DecisionKind.WAIT, "invalid_decision_input", "unknown")
    intent = value.intent.strip().lower()
    if intent == "chat":
        if not value.feature_enabled:
            return _record(DecisionKind.WAIT, "feature_disabled", intent)
        if value.serious:
            return _record(DecisionKind.RESPOND_GENTLY, "serious_context", intent)
        return _record(DecisionKind.RESPOND, "direct_invitation", intent)
    if intent in {"help", "memory", "reminder"}:
        if not value.feature_enabled:
            return _record(DecisionKind.WAIT, "feature_disabled", intent)
        return _record(DecisionKind.RESPOND, "explicit_member_request", intent)
    if intent == "action":
        if not value.permission:
            return _record(DecisionKind.REFUSE, "permission_missing", intent)
        if not value.confirmed:
            return _record(DecisionKind.CLARIFY, "confirmation_required", intent)
        if not value.storage_ok:
            return _record(DecisionKind.WAIT, "storage_unavailable", intent)
        return _record(DecisionKind.EXECUTE_CANDIDATE, "authorized_confirmed_candidate", intent)
    if intent == "activity":
        if not value.enabled:
            return _record(DecisionKind.WAIT, "independence_or_feature_disabled", intent)
        if value.quiet:
            return _record(DecisionKind.WAIT, "quiet_server", intent)
        if value.serious:
            return _record(DecisionKind.WAIT, "serious_context", intent)
        if not value.storage_ok:
            return _record(DecisionKind.WAIT, "storage_unavailable", intent)
        if not value.engaged:
            return _record(DecisionKind.WAIT, "insufficient_engagement", intent)
        return _record(DecisionKind.SUGGEST, "eligible_activity_opportunity", intent)
    return _record(DecisionKind.WAIT, "unsupported_intent", intent)
