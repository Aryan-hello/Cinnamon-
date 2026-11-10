"""Safe compound-request parsing for Cinnamon Brain.

This module only expands a narrowly supported compound sentence into the
existing typed ActionProposal format. It performs no authorization, Discord
lookups, persistence, or execution. The adapter must still validate every
proposal and confirm the complete batch before running anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from cinnamon_modules.brain_actions import ActionProposal, ActionValidationError, validate_proposal

MAX_BATCH_ACTIONS = 8
_MENTION = r"<@!?[0-9]{15,22}>"
_AMOUNT = r"(?:[0-9]+(?:,[0-9]{3})*|[0-9]+(?:\.[0-9]+)?[kKmM]?)"
_AMOUNT_RE = re.compile(r"^([0-9]+(?:,[0-9]{3})*|[0-9]+(?:\.[0-9]+)?)([kKmM]?)$")
_DURATION = re.compile(r"^([0-9]+)(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$", re.I)


@dataclass(frozen=True)
class CompoundPlan:
    actions: tuple[ActionProposal, ...]
    summary: str


def _amount(raw: str) -> int:
    match = _AMOUNT_RE.fullmatch(raw.strip())
    if not match:
        raise ActionValidationError("Use a whole Catnip amount (for example 2k or 20,000).")
    try:
        value = Decimal(match.group(1).replace(",", ""))
        suffix = match.group(2).lower()
        value *= Decimal(1000 if suffix == "k" else 1_000_000 if suffix == "m" else 1)
    except InvalidOperation as exc:
        raise ActionValidationError("That Catnip amount is invalid.") from exc
    if value != value.to_integral_value() or not 1 <= value <= 1_000_000:
        raise ActionValidationError("Each Catnip adjustment must be 1–1,000,000.")
    return int(value)


def _duration(raw: str) -> int:
    match = _DURATION.fullmatch(raw.strip())
    if not match:
        raise ActionValidationError("Use a duration like 10m, 30 seconds, or 1h.")
    n, unit = int(match.group(1)), match.group(2).lower()
    seconds = n * (60 if unit.startswith("m") else 3600 if unit.startswith("h") else 86400 if unit.startswith("d") else 1)
    if not 1 <= seconds <= 86_400:
        raise ActionValidationError("Timeouts must be between 1 second and 24 hours.")
    return seconds


def _mentions(text: str) -> tuple[int, ...]:
    ids = tuple(int(x) for x in re.findall(r"<@!?(\d{15,22})>", text))
    if not ids or len(ids) != len(set(ids)):
        raise ActionValidationError("Mention each target exactly once.")
    return ids


def parse_compound_request(text: str) -> CompoundPlan | None:
    """Parse only explicit Catnip adjustments and timeouts separated by 'and'.

    Returns None for ordinary/single-action requests so the existing parser
    remains authoritative. A compound request with unsupported syntax raises
    a safe validation error rather than partially executing.
    """
    clean = re.sub(r"^(?:(?:hey|hi|hello|please)[,! ]+)?cinnamon\s*[,!:.]?\s*", "", str(text or "").strip(), flags=re.I)
    # A compound plan must contain at least two action verbs; don't intercept
    # existing single-action grammar or arbitrary conversational text.
    if len(re.findall(r"\b(?:add|give|remove|take|mute|timeout|unmute|untimeout)\b", clean, re.I)) < 2:
        return None
    clauses = re.split(r"\s+and\s+(?=(?:add|give|remove|take|mute|timeout|time\s+out|unmute|untimeout)\b)", clean, flags=re.I)
    if len(clauses) < 2 or len(clauses) > MAX_BATCH_ACTIONS:
        raise ActionValidationError(f"Compound requests support 2–{MAX_BATCH_ACTIONS} actions.")
    actions: list[ActionProposal] = []
    descriptions: list[str] = []
    for clause in clauses:
        clause = clause.strip().rstrip(".!?")
        add = re.fullmatch(rf"(?:add|give)\s+({_AMOUNT})\s+catnip\s+to\s+(.+)", clause, re.I)
        remove = re.fullmatch(rf"(?:remove|take)\s+({_AMOUNT})\s+catnip\s+from\s+({_MENTION})", clause, re.I)
        timeout = re.fullmatch(rf"(?:mute|timeout|time\s+out)\s+({_MENTION})\s+(?:for\s+)?([0-9]+\\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days))", clause, re.I)
        untimeout = re.fullmatch(rf"(?:unmute|untimeout)\s+({_MENTION})", clause, re.I)
        if add:
            amount, target_text = add.groups()
            ids = _mentions(target_text)
            for uid in ids:
                proposal = validate_proposal(ActionProposal("economy.add_catnip", uid, amount=_amount(amount)))
                actions.append(proposal); descriptions.append(f"add {_amount(amount):,} Catnip to <@{uid}>")
        elif remove:
            amount, target = remove.groups(); uid = _mentions(target)[0]
            proposal = validate_proposal(ActionProposal("economy.remove_catnip", uid, amount=_amount(amount)))
            actions.append(proposal); descriptions.append(f"remove {_amount(amount):,} Catnip from <@{uid}>")
        elif timeout:
            target, duration = timeout.groups(); uid = _mentions(target)[0]; seconds = _duration(duration)
            proposal = validate_proposal(ActionProposal("moderation.timeout", uid, seconds=seconds))
            actions.append(proposal); descriptions.append(f"timeout <@{uid}> for {seconds}s")
        elif untimeout:
            uid = _mentions(untimeout.group(1))[0]
            proposal = validate_proposal(ActionProposal("moderation.remove_timeout", uid))
            actions.append(proposal); descriptions.append(f"remove timeout from <@{uid}>")
        else:
            raise ActionValidationError("I couldn't safely parse every part. Nothing was executed; use separate commands or simplify the request.")
    if len(actions) > MAX_BATCH_ACTIONS:
        raise ActionValidationError(f"That expands to too many targets (maximum {MAX_BATCH_ACTIONS}).")
    return CompoundPlan(tuple(actions), "\n".join(f"• {line}" for line in descriptions))
