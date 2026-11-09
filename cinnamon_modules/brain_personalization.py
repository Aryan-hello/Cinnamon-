"""Safe per-member Cinnamon Brain conversation preferences.

These are explicit presentation preferences only: they never grant permissions,
change server settings, or override serious-conversation safety.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

STYLES = ("balanced", "playful", "calm", "concise", "detailed")
MAX_LABEL = 24


@dataclass(frozen=True)
class MemberBrainPreferences:
    style: str = "balanced"
    teasing: bool = True


def validate_style(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Choose one of: " + ", ".join(STYLES))
    clean = value.strip().lower()
    if clean not in STYLES:
        raise ValueError("Choose one of: " + ", ".join(STYLES))
    return clean


def validate_teasing(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("Teasing must be enabled or disabled.")
    return value


def prompt_guidance(style: object = "balanced", teasing: object = True) -> str:
    """Small, fixed prompt fragment; never interpolates arbitrary user text."""
    style = validate_style(style)
    teasing = validate_teasing(teasing)
    guide = {
        "balanced": "Use a natural balance of warmth, humor, and useful detail.",
        "playful": "Be more playful and witty, while staying kind and useful.",
        "calm": "Use a calm, reassuring, low-drama tone.",
        "concise": "Prefer short, direct answers; expand only when needed.",
        "detailed": "Explain things clearly with helpful context and examples.",
    }[style]
    tease = ("Light friendly teasing is welcome when context is clearly casual; "
             "never target vulnerabilities or appearance." if teasing else
             "Avoid teasing this member; be warm and respectful.")
    return f"Member's chosen response style: {guide}\n{tease}"
