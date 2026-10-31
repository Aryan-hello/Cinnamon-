"""Pure request recognition and validation for Cinnamon's trusted actions.

Nothing in this module contacts Discord, Gemini, or storage.  A proposal is
untrusted data, not authorization: the Discord adapter must validate the real
requester, member evidence, permissions, and confirmation before execution.
Only a current human request may be parsed; never pass model replies, channel
history, quoted examples, or external documents back into this parser.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from types import MappingProxyType
from typing import Mapping, Sequence


MAX_CATNIP = 1_000_000
MAX_TIMEOUT_SECONDS = 86_400
CONFIRM_SECONDS = 60
SOURCE_MAX_AGE_SECONDS = 300
RECEIPT_RETENTION_SECONDS = 30 * 24 * 60 * 60


class ActionValidationError(ValueError):
    """A safe explanation of an invalid or unsupported action request."""

    def __init__(self, message: str, *, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ActionProposal:
    action: str
    target_user_id: int
    amount: int = 0
    seconds: int = 0


@dataclass(frozen=True)
class ActionSpec:
    permission: str
    confirmation_required: bool = True


ACTION_REGISTRY: Mapping[str, ActionSpec] = MappingProxyType({
    "economy.add_catnip": ActionSpec("administrator"),
    "economy.remove_catnip": ActionSpec("administrator"),
    "moderation.timeout": ActionSpec("moderate_members"),
    "moderation.remove_timeout": ActionSpec("moderate_members"),
})


@dataclass(frozen=True)
class TrustedRequest:
    """Discord-supplied source metadata, kept separate from proposed arguments."""

    guild_id: int
    channel_id: int
    source_id: int
    requester_id: int
    created_at: float

    @property
    def receipt_id(self) -> str:
        return f"{self.guild_id}:{self.channel_id}:{self.source_id}"


def _positive_id(value: object) -> bool:
    return type(value) is int and value > 0


def validate_request(request: TrustedRequest, *, now: float) -> TrustedRequest:
    """Reject stale/replayed sources before creating a confirmation.

    Authorization is deliberately absent here.  Callers must obtain every
    identifier and timestamp from the Discord event, not proposed arguments.
    """
    if type(request) is not TrustedRequest or not all(
        _positive_id(value) for value in (
            request.guild_id, request.channel_id, request.source_id,
            request.requester_id,
        )
    ):
        raise ActionValidationError("This request has no valid Discord source.",
                                    code="invalid_source")
    if (type(request.created_at) not in (int, float)
            or type(now) not in (int, float)
            or not math.isfinite(request.created_at) or not math.isfinite(now)):
        raise ActionValidationError("This request has no valid timestamp.",
                                    code="invalid_source")
    age = now - request.created_at
    if age < 0 or age > SOURCE_MAX_AGE_SECONDS:
        raise ActionValidationError("That request expired. Please send a new request.",
                                    code="expired_source")
    return request


def validate_proposal(proposal: ActionProposal) -> ActionProposal:
    """Validate the entire closed shape, independently of how it was proposed."""
    if type(proposal) is not ActionProposal:
        raise ActionValidationError("An action must use the supported typed proposal.",
                                    code="invalid_proposal")
    if type(proposal.action) is not str or proposal.action not in ACTION_REGISTRY:
        raise ActionValidationError("That action is not supported in conversation.",
                                    code="unsupported_action")
    if not _positive_id(proposal.target_user_id):
        raise ActionValidationError("Choose a valid member of this server.",
                                    code="invalid_target")
    if type(proposal.amount) is not int or type(proposal.seconds) is not int:
        raise ActionValidationError("Amounts and durations must be whole numbers.",
                                    code="invalid_arguments")
    if proposal.action.startswith("economy."):
        if not 1 <= proposal.amount <= MAX_CATNIP or proposal.seconds != 0:
            raise ActionValidationError(
                "Chat adjustments must be 1–1,000,000 Catnip, with no duration.",
                code="invalid_amount")
    elif proposal.action == "moderation.timeout":
        if not 1 <= proposal.seconds <= MAX_TIMEOUT_SECONDS or proposal.amount != 0:
            raise ActionValidationError(
                "Chat timeouts must be 1 second–24 hours, with no currency amount.",
                code="invalid_duration")
    elif proposal.amount != 0 or proposal.seconds != 0:
        raise ActionValidationError("Removing a timeout takes no amount or duration.",
                                    code="invalid_arguments")
    return proposal


_FLAGS = re.IGNORECASE | re.ASCII
_MENTION = r"<@!?[0-9]{15,22}>"
_RELATIVE = r"(?:this|that)\s+(?:member|user|person)"
_MOD_TARGET = rf"(?:{_MENTION}|{_RELATIVE})"
_QUANTITY = r"[+-]?[0-9][0-9,]*(?:\.[0-9]+)?"
_END = r"\s*[.!?]?\s*"
_UNIT = r"(?:seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)"
_TIMEOUT = re.compile(
    rf"(?:mute|timeout|time\s+out)\s+(?P<target>{_MOD_TARGET})\s+"
    rf"(?:for\s+)?(?P<quantity>{_QUANTITY})\s*(?P<unit>{_UNIT}){_END}", _FLAGS)
_UNTIMEOUT = re.compile(
    rf"(?:unmute|untimeout|remove\s+(?:the\s+)?timeout(?:\s+from)?)\s+"
    rf"(?P<target>{_MOD_TARGET}){_END}", _FLAGS)
_ADD = re.compile(
    rf"(?:add|give)\s+(?P<amount>{_QUANTITY})\s+catnip\s+to\s+"
    rf"(?P<target>{_MENTION}){_END}", _FLAGS)
_GIVE = re.compile(
    rf"give\s+(?P<target>{_MENTION}|me)\s+(?P<amount>{_QUANTITY})\s+catnip{_END}",
    _FLAGS)
_REMOVE = re.compile(
    rf"(?:remove|take)\s+(?P<amount>{_QUANTITY})\s+catnip\s+from\s+"
    rf"(?P<target>{_MENTION}){_END}", _FLAGS)
_ACTION_LIKE = re.compile(
    r"^(?:mute\b|timeout\b|time\s+out\b|unmute\b|untimeout\b|"
    r"remove\s+(?:the\s+)?timeout\b|kick\b|ban\b|purge\b|"
    r"(?:add|give|remove|take)\b[^\n]*\bcatnip\b|"
    r"delete\b[^\n]*\bchannel\b|(?:assign|give)\b[^\n]*\brole\b|"
    r"lock\b[^\n]*\bchannel\b)", _FLAGS)


def _wake_text(text: str) -> str:
    text = text.strip()
    text = re.sub(
        r"^(?:(?:hey|hi|hello|yo|please)[,! ]+)?cinnamon\b\s*[,!:.]?\s*",
        "", text, count=1, flags=_FLAGS)
    return re.sub(r"^please\s+", "", text, count=1, flags=_FLAGS).strip()


def _number(text: str, *, limit: int, label: str) -> int:
    if not (re.fullmatch(r"[0-9]+", text)
            or re.fullmatch(r"[1-9][0-9]{0,2}(?:,[0-9]{3})+", text)):
        raise ActionValidationError(f"Use a positive whole {label}; commas must group thousands.",
                                    code="invalid_number")
    digits = text.replace(",", "")
    if len(digits) > len(str(limit)) or not 1 <= int(digits) <= limit:
        raise ActionValidationError(f"The {label} is outside the supported chat limit.",
                                    code="invalid_number")
    return int(digits)


def _target(text: str, *, requester_id: int, target_ids: Sequence[int],
            reply_target_id: int | None) -> int:
    ids = set(target_ids)
    if any(not _positive_id(value) for value in ids):
        raise ActionValidationError("The target evidence is invalid.", code="invalid_target")
    if text.lower() == "me":
        if ids or not _positive_id(requester_id):
            raise ActionValidationError("Please choose exactly one target member.",
                                        code="ambiguous_target")
        return requester_id
    if re.fullmatch(_MENTION, text, _FLAGS):
        uid = int(re.sub(r"[^0-9]", "", text))
        if len(ids) != 1 or uid not in ids:
            raise ActionValidationError("Please mention exactly one target member.",
                                        code="ambiguous_target")
        return uid
    if ids or not _positive_id(reply_target_id):
        raise ActionValidationError(
            "Reply to that member's message or mention the member explicitly.",
            code="ambiguous_target")
    return reply_target_id


def parse_action(text: str, *, requester_id: int, target_ids: Sequence[int],
                 reply_target_id: int | None = None) -> ActionProposal | None:
    """Recognize one complete direct instruction, or return ``None`` for chat.

    ``target_ids`` must be the actual user mentions excluding Cinnamon's own
    mention. ``reply_target_id`` must come from a resolved Discord message.
    The adapter must additionally reject nonmembers and protected/bot targets.
    """
    if type(text) is not str:
        raise ActionValidationError("The request must be text.", code="invalid_request")
    clean = _wake_text(text)
    if re.match(r"^(?:remind\s+me\b|set\s+(?:a\s+)?reminder\b)", clean, _FLAGS):
        raise ActionValidationError(
            "Personal reminders aren't implemented yet. I haven't scheduled a reminder.",
            code="unsupported_action")
    if re.match(r"^start\s+(?:(?:a|the)\s+)?(?:hangry\s+games|game)\b", clean, _FLAGS):
        raise ActionValidationError(
            "Chat game launching isn't available yet. Use /hangrygames new; its normal hosting permissions apply.",
            code="unsupported_action")
    if re.match(r"^(?:kick|ban)\b", clean, _FLAGS):
        raise ActionValidationError(
            "Chat kick/ban actions are paused pending security review. "
            "Use the existing /kick or /ban slash command with its required permissions.",
            code="unsupported_action")
    # Normalize only the *classification* probe so a split action cannot fall
    # through to chat. The original input remains subject to the single-line
    # rule and is the only input ever used for proposal recognition.
    action_probe = re.sub(r"[\r\n]+", " ", clean)
    if not clean or not _ACTION_LIKE.match(action_probe):
        return None
    if "\n" in clean or "\r" in clean or len(clean) > 2000:
        raise ActionValidationError("Send one short action request on a single line.",
                                    code="invalid_request")

    for expression, action in (
        (_ADD, "economy.add_catnip"), (_GIVE, "economy.add_catnip"),
        (_REMOVE, "economy.remove_catnip"), (_TIMEOUT, "moderation.timeout"),
        (_UNTIMEOUT, "moderation.remove_timeout"),
    ):
        match = expression.fullmatch(clean)
        if not match:
            continue
        target = _target(match["target"], requester_id=requester_id,
                         target_ids=target_ids, reply_target_id=reply_target_id)
        amount, seconds = 0, 0
        if action.startswith("economy."):
            amount = _number(match["amount"], limit=MAX_CATNIP, label="Catnip amount")
        elif action == "moderation.timeout":
            quantity = _number(match["quantity"], limit=MAX_TIMEOUT_SECONDS,
                               label="timeout duration")
            unit = match["unit"].lower()
            multiplier = (1 if unit.startswith("s") else 60 if unit.startswith("m")
                          else 3600 if unit.startswith("h") else 86400)
            seconds = quantity * multiplier
        return validate_proposal(ActionProposal(action, target, amount, seconds))
    raise ActionValidationError(
        "I need one exact supported request: add/remove Catnip for one mentioned member, "
        "or timeout/unmute one member. Use /help for other commands.",
        code="unsupported_request")
