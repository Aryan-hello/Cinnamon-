"""Pure choices for Cinnamon's optional, bounded AI activity adviser.

An AI choice is untrusted data. The hard activity eligibility gate runs both
before and immediately after a choice; the adviser has zero execution rights.
"""
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class ActivitySignals:
    messages: int
    members: int
    mood: str
    allowed_prompt: bool


def interpret_activity_choice(raw: str, *, prompt_allowed: bool) -> str:
    """One of wait, game, prompt. Invalid/restricted proposals become wait."""
    try:
        data = json.loads(str(raw or "")[:500])
    except (ValueError, TypeError):
        return "wait"
    if not isinstance(data, dict):
        return "wait"
    choice = data.get("choice")
    if choice == "game":
        return "game"
    if choice == "prompt" and prompt_allowed:
        return "prompt"
    return "wait"


def default_activity(signals: ActivitySignals, opportunity: int) -> str:
    """Conservative fallback without Gemini or any user message content."""
    if (signals.messages < 6 or signals.members < 2):
        return "wait"
    if signals.allowed_prompt and opportunity % 3 == 2:
        return "prompt"
    return "game"
