"""Pure, privacy-limited user preference validation for Cinnamon's memory.

Only explicit, intentionally shared non-sensitive preferences are eligible.
The runtime adapter owns persistence, permissions, visibility and correction.
"""
from dataclasses import dataclass
import re

ALLOWED_CATEGORIES = ("games", "stories", "hobbies", "reply_style")
MAX_NOTES = 12
MAX_TEXT = 120


class MemoryValidationError(ValueError):
    pass


_REMEMBER = re.compile(
    r"^(?:(?:hey|hi|please)\s+)?cinnamon\s*[,!:.]?\s*"
    r"remember\s+(?:that\s+)?i\s+(?:like|love|enjoy|prefer)\s+(.+?)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_DIRECT = re.compile(
    r"^(?:please\s+)?remember\s+(?:that\s+)?i\s+"
    r"(?:like|love|enjoy|prefer)\s+(.+?)\s*[.!]?\s*$", re.IGNORECASE
)
_BLOCKED = re.compile(
    r"\b(?:password|passcode|api.?key|secret|token|auth|credential|"
    r"address|where i live|phone|email|dob|birthday|date of birth|"
    r"health|illness|diagnos|medicine|medication|therapy|medical|"
    r"religion|politic|party affiliation|race|ethnic|sexual|"
    r"nude|porn|self.harm|suicid|credit card|bank|account number|"
    r"my school|my teacher|identity|private message|doxx|location)\b",
    re.IGNORECASE,
)
_INJECTION = re.compile(
    r"\b(?:ignore (?:all |previous )?instructions|system prompt|"
    r"developer message|execute|run code|send to|delete data|"
    r"bot token|override|jailbreak|reveal secrets)\b",
    re.IGNORECASE,
)
_TAGS = re.compile(r"(?:<@|<#|<@&|@everyone\b|@here\b|https?://|[\x00-\x1f])",
                   re.IGNORECASE)
_CATEGORY_HINTS = {
    "games": ("game", "gaming", "roblox", "minecraft", "rpg", "puzzle game",
              "hangry games", "fishing game", "chess"),
    "stories": ("story", "stories", "mystery", "fantasy", "novel", "books",
                "comedy", "adventure", "horror", "fiction", "sci-fi"),
    "hobbies": ("reading", "writing", "drawing", "painting", "coding", "music",
                "chess", "cooking", "gardening", "puzzles", "origami"),
    "reply_style": ("short replies", "short answers", "detailed explanations",
                    "simple explanations", "examples", "step by step",
                    "bullet points", "brief answers"),
}


@dataclass(frozen=True)
class Preference:
    category: str
    detail: str


def validate_preference(category: str, detail: str) -> Preference:
    category = str(category or "").strip().lower()
    detail = re.sub(r"\s+", " ", str(detail or "").strip()).strip(" .!?")
    if category not in ALLOWED_CATEGORIES:
        raise MemoryValidationError(
            "Choose one category: games, stories, hobbies, or reply_style.")
    if not 2 <= len(detail) <= MAX_TEXT:
        raise MemoryValidationError("Keep this preference between 2 and 120 characters.")
    if _TAGS.search(detail) or _BLOCKED.search(detail) or _INJECTION.search(detail):
        raise MemoryValidationError(
            "I only save ordinary game, story, hobby, and reply preferences, "
            "not private, sensitive or command-like details.")
    if len(detail.split()) > 24 or detail.count("`") > 2:
        raise MemoryValidationError("Please use a short, simple preference.")
    return Preference(category, detail)


def parse_explicit_preference(message: str) -> Preference | None:
    """Parse explicit 'remember I like ...', never passive chat."""
    text = str(message or "")[:600].strip()
    text = re.sub(
        r"^(?:(?:hey|hi)\s+)?cinnamon\s*[,!:.]?\s*",
        "", text, count=1, flags=re.IGNORECASE)
    text = re.sub(
        r"^(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|please\s+)",
        "", text, count=1, flags=re.IGNORECASE)
    m = _REMEMBER.fullmatch(text) or _DIRECT.fullmatch(text)
    if not m:
        return None
    detail = m.group(1).strip()
    low = detail.lower()
    for category in ("reply_style", "games", "stories", "hobbies"):
        if any(hint in low for hint in _CATEGORY_HINTS[category]):
            return validate_preference(category, detail)
    raise MemoryValidationError(
        "Tell me whether that's about games, stories, hobbies, or reply style. "
        "You can use /cinnamon-memory save for an explicit category.")


def safe_context(notes) -> str:
    """Small data-only excerpt for Gemini; never treat preferences as orders."""
    clean = []
    for note in list(notes or [])[:MAX_NOTES]:
        if not isinstance(note, dict):
            continue
        try:
            p = validate_preference(note.get("category"), note.get("detail"))
        except MemoryValidationError:
            continue
        clean.append(f"- {p.category}: {p.detail}")
    if not clean:
        return ""
    return "\n".join(clean)[:1000]
