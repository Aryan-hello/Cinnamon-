"""Cinnamon's presentation primitives.

A single, deliberately small visual language for Discord's native clients.
Keep rich embeds and Components V2 separate: Discord doesn't permit a classic
embed on a V2 message. This module is loaded before feature modules.
"""

CINNAMON_UI = {
    "brand": 0xD97732,
    "gold": 0xE5AC43,
    "info": 0x648DD0,
    "success": 0x3BA77A,
    "warning": 0xE6A23C,
    "danger": 0xD75A56,
    "muted": 0x8592A6,
}


def cinnamon_ui_literal(value, limit=300):
    """Render untrusted names/descriptions as text, not formatting or pings."""
    value = str(value)
    value = "".join(ch for ch in value if ch in "\n\t" or ord(ch) >= 32)
    value = discord.utils.escape_mentions(discord.utils.escape_markdown(value))
    limit = max(2, int(limit))
    return value if len(value) <= limit else value[:limit - 1] + "…"


def cinnamon_ui_card(section, title, description="", *, color=None, user=None,
                     footer=None, timestamp=False):
    """Consistent classic embed; timestamps belong on logs, not static panels."""
    e = discord.Embed(
        title=str(title)[:256],
        description=str(description)[:4096],
        color=color if color is not None else CINNAMON_UI["brand"],
        timestamp=datetime.datetime.now(datetime.timezone.utc) if timestamp else None,
    )
    e.set_author(name=("CINNAMON  /  " + str(section).upper())[:256])
    if user is not None:
        e.set_thumbnail(url=user.display_avatar.url)
    e.set_footer(text=str(footer or "Cinnamon  •  Made with paws")[:2048])
    return e


def cinnamon_ui_progress(current, target, width=8):
    """Text-first progress: always show the fraction, not only a color/bar."""
    target = max(1, int(target))
    current = max(0, min(int(current), target))
    count = round(width * current / target)
    return f'{"▰" * count}{"▱" * (width - count)}  **{current:,}/{target:,}**'


def cinnamon_ui_page(section, page, pages, context=""):
    suffix = f"  ·  {context}" if context else ""
    return f"Cinnamon  /  {section}  ·  {page}/{pages}{suffix}"
