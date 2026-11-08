"""Pure activation policy for Cinnamon Brain V2.

Only the current message can activate Cinnamon. Quoted and code-formatted
text is ignored as an activation source; a verified reply to Cinnamon is not.
"""
from __future__ import annotations

import re


_MENTION_TEMPLATE = r"<@!?{user_id}>"
_NAME = re.compile(r"(?<![\w])cinnamon(?![\w])", re.IGNORECASE)
_CODE_FENCE = re.compile(r"(?s)```.*?```|~~~.*?~~~")
_INLINE_CODE = re.compile(r"`[^`]*`")
_MENTION = re.compile(r"<@!?\d+>")


def _unquoted_text(content: str) -> str:
    """Remove fenced/inline code and Markdown blockquote lines."""
    if not isinstance(content, str) or not content:
        return ""
    content = _CODE_FENCE.sub(" ", content)
    content = _INLINE_CODE.sub(" ", content)
    lines = []
    for line in content.splitlines():
        if re.match(r"^\s*>", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def is_directly_addressed(
    content: str,
    *,
    bot_user_id: int | None,
    reply_author_id: int | None = None,
    bot_name: str = "Cinnamon",
) -> bool:
    """Return whether the current message directly addresses Cinnamon."""
    if not isinstance(content, str) or not content.strip():
        return False
    if bot_user_id is not None and reply_author_id == bot_user_id:
        return True
    clean = _unquoted_text(content)
    if bot_user_id is not None:
        mention = re.compile(_MENTION_TEMPLATE.format(user_id=re.escape(str(bot_user_id))))
        if mention.search(clean):
            return True
    name_pattern = _NAME if bot_name.casefold() == "cinnamon" else re.compile(
        rf"(?<![\w]){re.escape(bot_name)}(?![\w])", re.IGNORECASE
    )
    return bool(name_pattern.search(clean))


def strip_bot_addressing(
    content: str,
    *,
    bot_user_id: int | None,
    bot_name: str = "Cinnamon",
) -> str:
    """Remove a leading bot name/mention and tidy the remaining request."""
    clean = _unquoted_text(content).strip()
    if bot_user_id is not None:
        clean = re.sub(_MENTION_TEMPLATE.format(user_id=re.escape(str(bot_user_id))), " ", clean)
    clean = re.sub(
        rf"^\s*(?:(?:hey|hi|hello|yo|please)[,! ]+)?{re.escape(bot_name)}\b",
        " ",
        clean,
        count=1,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"^\s*(?:please[,! ]+)", "", clean, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", clean).strip(" ,!:.\t\r\n")
