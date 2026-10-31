"""Cinnamon Brain v2: pure, bounded personal-assistant helpers.

Only explicit member settings are remembered. No location inference, private
message scraping, broad AI tool access or automated member profiling.
"""
from datetime import datetime, timedelta, timezone
import re


class PersonalSettingError(ValueError):
    """Safe feedback for a rejected member setting."""


_OFFSET = re.compile(
    r"^UTC(?:(?P<sign>[+-])(?P<hour>\d{1,2})(?::?(?P<minute>\d{2}))?)?$",
    re.IGNORECASE,
)


def parse_timezone_setting(text: str) -> int | None:
    """Return a fixed UTC offset in minutes; 'server' clears the override.

    IANA/DST behavior is deliberately not inferred. UTC offsets are static:
    remind members to change them if their locality observes clock changes.
    """
    value = str(text or "").strip()
    if value.lower() in {"server", "default", "reset"}:
        return None
    match = _OFFSET.fullmatch(value)
    if not match:
        raise PersonalSettingError(
            "Use a fixed offset like UTC+05:30, UTC-04:00, or UTC. "
            "Use 'server' to restore this server's default.")
    if not match.group("sign"):
        return 0
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or "0")
    signed = (hour * 60 + minute) * (-1 if match.group("sign") == "-" else 1)
    if minute >= 60 or not -720 <= signed <= 840:
        raise PersonalSettingError(
            "Choose an offset from UTC-12:00 through UTC+14:00.")
    return signed


def format_timezone_offset(minutes: int) -> str:
    if type(minutes) is not int or not -720 <= minutes <= 840:
        raise PersonalSettingError("The timezone offset is invalid.")
    sign = "+" if minutes >= 0 else "-"
    hours, minutes_only = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes_only:02d}"


def due_today(reminders, *, now: datetime, offset_minutes: int, limit: int = 5):
    """Only safe current-member scheduled reminders; never another guild."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone aware")
    tz = timezone(timedelta(minutes=offset_minutes))
    today = now.astimezone(tz).date()
    selected = []
    for item in list(reminders or []):
        if not isinstance(item, dict) or item.get("status") != "scheduled":
            continue
        try:
            due_at = int(item.get("due_at"))
            due_day = datetime.fromtimestamp(due_at, tz=tz).date()
        except (ValueError, OverflowError, TypeError, OSError):
            continue
        if due_day == today:
            selected.append((due_at, item))
    return [item for _, item in sorted(selected, key=lambda row: row[0])[:max(0, min(limit, 10))]]
