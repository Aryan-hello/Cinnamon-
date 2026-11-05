"""Deterministic, non-authoritative intent routing for Cinnamon.

Routes only the current human-authored message. A route selects an existing
handler; its parser, Discord identity, permissions, confirmation and storage
checks remain the authority. Model output/history are never routed to actions.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

MAX_INPUT_CHARS = 1_200


class Intent(str, Enum):
    REMINDER = "reminder"
    MEMORY = "memory"
    HELP = "help"
    ACTION = "action_candidate"
    CHAT = "chat"


@dataclass(frozen=True)
class RouteDecision:
    intent: Intent
    reason: str
    confidence: float
    authorized: bool = False
    matched_signal: str = ""


def normalize_input(value: object) -> str:
    """Bound current input; no interpretation or execution."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:MAX_INPUT_CHARS]


_REMINDER = re.compile(
    r"\b(?:remind\s+me|reminder\s+(?:for|to)|set\s+(?:a\s+)?reminder)\b",
    re.I,
)
_MEMORY = re.compile(
    r"\b(?:remember\s+(?:that\s+)?i\s+(?:like|love|enjoy|prefer)|"
    r"(?:show|view|list)\s+(?:my\s+)?(?:saved\s+)?(?:notes|memories|preferences)|"
    r"(?:forget|delete|remove)\s+(?:my\s+)?(?:note|memory|preference|preferences|notes|memories))\b",
    re.I,
)
_HELP = re.compile(
    r"\b(?:how\s+(?:do|can|to)\s+i|what\s+(?:does|is|are)|"
    r"explain|help\s+me\s+(?:with|use)|show\s+me\s+how)\b",
    re.I,
)
_ACTION = re.compile(
    r"^\s*(?:please\s+)?(?:add|give|grant|remove|take|subtract|"
    r"mute|timeout|unmute|untimeout)\b",
    re.I,
)


def classify_intent(value: object) -> RouteDecision:
    """Classify a current message into one safe route, with no side effects."""
    text = normalize_input(value)
    if not text:
        return RouteDecision(Intent.CHAT, "empty_or_invalid_input", 0.0)
    # Highest priority: explicit personal reminder/memory requests.
    if _REMINDER.search(text):
        return RouteDecision(Intent.REMINDER, "explicit_reminder", 0.98,
                             matched_signal="remind_me")
    if _MEMORY.search(text):
        return RouteDecision(Intent.MEMORY, "explicit_memory_request", 0.98,
                             matched_signal="memory_phrase")
    if _HELP.search(text) and re.search(r"[/!?]?[a-z][\w-]{1,30}", text, re.I):
        return RouteDecision(Intent.HELP, "help_question", 0.85,
                             matched_signal="help_language")
    # Action route is only a candidate. Actual parser and Discord checks decide.
    if _ACTION.match(text):
        return RouteDecision(Intent.ACTION, "explicit_action_candidate", 0.90,
                             matched_signal="action_verb")
    return RouteDecision(Intent.CHAT, "ordinary_conversation", 0.50)
