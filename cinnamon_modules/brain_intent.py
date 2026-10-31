"""Deterministic routing for Cinnamon Brain v2.

This planner classifies only the current member-authored request. It does not
read channel history, invoke Gemini, authorize actions, or execute commands.
The selected route is a hint for the existing trusted Python handlers.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from cinnamon_modules.brain_private_qa import classify_private_question


@dataclass(frozen=True)
class IntentPlan:
    intent: str
    reason: str
    route_order: tuple[str, ...]


# Deliberately narrow patterns: uncertain text remains ordinary conversation.
_REMINDER = re.compile(
    r"^(?:remind\s+me\b|set\s+(?:a\s+)?reminder\b|"
    r"(?:my\s+)?reminders?\b|"
    r"(?:list|show|cancel|snooze)\s+(?:my\s+)?reminders?\b|"
    r"what\s+reminders?\s+(?:do\s+i\s+have|are\s+pending)\b)",
    re.IGNORECASE,
)
_MEMORY = re.compile(
    r"^(?:(?:remember|forget|delete|clear|edit|change)\b|"
    r"(?:show|view)\s+(?:my\s+)?(?:preferences|memory|notes)\b|"
    r"(?:what|show|view)\s+(?:do\s+you\s+)?remember\s+about\s+me\b|"
    r"(?:turn|switch)\s+(?:my\s+)?memory\s+(?:on|off)\b)",
    re.IGNORECASE,
)
_HELP = re.compile(
    r"^(?:(?:what|how|why|explain|help|tell\s+me|show\s+(?:me|my))\b|"
    r"my\s+(?:day|progress|privacy|level|xp)\b|"
    r"can\s+you\s+(?:explain|help|tell|show)\b|"
    r"i\s+(?:do\s+not|don['’]t)\s+understand\b)",
    re.IGNORECASE,
)
_ACTION = re.compile(
    r"^(?:add\b.*\bcatnip\b|give\b.*\bcatnip\b|"
    r"remove\b.*\bcatnip\b|take\b.*\bcatnip\b|"
    r"mute\b|timeout\b|time\s+out\b|unmute\b|untimeout\b|"
    r"kick\b|ban\b|purge\b|warn\b|delete\b.*\bchannel\b|"
    r"(?:assign|give)\b.*\brole\b|lock\b.*\bchannel\b)",
    re.IGNORECASE,
)
_WAKE = re.compile(
    r"^(?:(?:hey|hi|hello|yo|please)[,! ]+)?cinnamon\s*[,!:.]?\s*(?:please\s+)?",
    re.IGNORECASE,
)


def plan_intent(text: str) -> IntentPlan:
    """Return a deterministic route for one current user request.

    Every plan retains a final chat fallback. No route is permission or consent.
    """
    if type(text) is not str:
        return IntentPlan("chat", "non_text_input", ("chat",))
    clean = _WAKE.sub("", text.strip(), count=1)
    clean = re.sub(r"^please[,! ]+", "", clean, count=1, flags=re.IGNORECASE)
    if not clean:
        return IntentPlan("chat", "empty_request", ("chat",))
    if _REMINDER.search(clean):
        intent, reason = "reminder", "reminder_language"
    elif _ACTION.search(clean):
        intent, reason = "action", "action_like_language"
    elif _MEMORY.search(clean):
        intent, reason = "memory", "explicit_memory_language"
    elif classify_private_question(clean):
        intent, reason = "private_data", "private_member_data_question"
    elif _HELP.search(clean) or re.search(r"/[a-z][a-z0-9_-]*", clean, re.IGNORECASE):
        intent, reason = "help", "question_or_command_explanation"
    else:
        intent, reason = "chat", "no_confident_specialized_intent"

    # Preserve the existing safe handler order after trying the strongest
    # deterministic match. The fallback is intentionally never an executor.
    preferred = {
        "reminder": ("reminder", "private_data", "memory", "help", "action", "chat"),
        "memory": ("memory", "private_data", "reminder", "help", "action", "chat"),
        "private_data": ("private_data", "reminder", "memory", "help", "action", "chat"),
        "help": ("help", "private_data", "reminder", "memory", "action", "chat"),
        "action": ("action", "private_data", "reminder", "memory", "help", "chat"),
        "chat": ("private_data", "reminder", "memory", "help", "action", "chat"),
    }[intent]
    return IntentPlan(intent, reason, preferred)
