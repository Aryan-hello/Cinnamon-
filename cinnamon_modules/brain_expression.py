"""Personality-aware reaction emoji shortlist for Cinnamon's Gemini replies.

This is a preparation layer for a future application-owned emoji library.
It only suggests already available guild custom emoji names, never uploads
assets or assumes application emojis can be used before they are fetched.
"""
import re

_NAME = re.compile(r"^[A-Za-z0-9_]{2,32}$")
_STYLES = {
    "delighted": ("happy", "yay", "love", "excited", "celebrate", "party", "purr"),
    "grumpy": ("angry", "grumpy", "sideeye", "sus", "unamused", "hiss", "mad"),
    "normal": ("cat", "cinnamon", "tuna", "fish", "mischief", "purr", "wink"),
}
_GENERAL = ("cat", "cinnamon", "meow", "fish", "tuna", "huh", "laugh", "wow")


def curated_emoji_names(emoji_names, *, mood="normal", limit=16):
    """At most a small set, no full 2,000-emoji prompt dump or duplicate names."""
    if not isinstance(limit, int) or not 1 <= limit <= 24:
        limit = 16
    seen, valid = set(), []
    for value in emoji_names:
        name = str(value or "")
        if not _NAME.fullmatch(name) or name.lower() in seen:
            continue
        seen.add(name.lower())
        valid.append(name)
    priorities = _STYLES.get(mood, _STYLES["normal"]) + _GENERAL
    scored = sorted(
        valid,
        key=lambda name: (
            -max((len(priorities) - i for i, key in enumerate(priorities)
                  if key in name.lower()), default=0),
            name.lower(),
        ),
    )
    return scored[:limit]


def safe_reaction(raw, names, *, serious=False):
    """Use only available custom names or a small Unicode expression.

    Never turn a textual model response into an arbitrary Discord mention,
    custom emoji ID, or role ping.
    """
    if serious:
        return ""
    emoji = str(raw or "").strip()
    if not emoji:
        return ""
    if emoji in set(names):
        return emoji
    if len(emoji) > 16 or emoji.isascii() or any(ch in emoji for ch in "<@>/"):
        return ""
    return emoji
