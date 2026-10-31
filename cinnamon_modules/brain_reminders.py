"""Pure personal reminder parsing for Cinnamon.

Reminders are self-addressed only. All due times are timezone-aware UTC
instants. The scheduler and persistence live in cinnamon_reminders.py.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re


@dataclass(frozen=True)
class ReminderSpec:
    text: str
    due_at: int  # POSIX UTC seconds
    timezone_label: str


class ReminderRequestError(ValueError):
    """A safe, user-readable clarification; no reminder was created."""


_WAKE = re.compile(
    r"^\s*(?:(?:hey|hi|please)\s+)?cinnamon\b\s*[,!:.]?\s*",
    re.IGNORECASE,
)
_PREFIX = re.compile(r"^\s*(?:please\s+)?remind\s+me\b\s*", re.IGNORECASE)
_RELATIVE = re.compile(
    r"\bin\s+(?P<number>[0-9]{1,4})\s*"
    r"(?P<unit>minutes?|mins?|hours?|hrs?|days?)\b", re.IGNORECASE
)
_DAY_AT = re.compile(
    r"\b(?P<day>today|tomorrow)\s+at\s+"
    r"(?P<hour>[0-9]{1,2})(?::(?P<minute>[0-9]{2}))?\s*"
    r"(?P<ampm>am|pm)\b", re.IGNORECASE
)
_ISO_AT = re.compile(
    r"\bon\s+(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})\s+at\s+"
    r"(?P<hour>[0-9]{1,2})(?::(?P<minute>[0-9]{2}))?\s*"
    r"(?P<ampm>am|pm)\b", re.IGNORECASE
)
_INTENT = re.compile(r"\bremind\s+me\b", re.IGNORECASE)
_MAX_SECONDS = 30 * 86400
_MIN_SECONDS = 60


def _timezone(offset_minutes: int):
    if type(offset_minutes) is not int or not -720 <= offset_minutes <= 840:
        raise ReminderRequestError("That server timezone is not configured correctly.")
    sign = "+" if offset_minutes >= 0 else "-"
    hour, minute = divmod(abs(offset_minutes), 60)
    return timezone(timedelta(minutes=offset_minutes)), f"UTC{sign}{hour:02d}:{minute:02d}"


def _clock(hour: int, minute: int, ampm: str) -> tuple[int, int]:
    if not 1 <= hour <= 12 or not 0 <= minute < 60:
        raise ReminderRequestError("Please choose a valid time, like tomorrow at 6 PM.")
    return (hour % 12 + (12 if ampm.lower() == "pm" else 0), minute)


def parse_reminder_request(message: str, *, now: datetime,
                           offset_minutes: int = 330) -> ReminderSpec | None:
    """Return None if unrelated; otherwise a valid reminder or clarification.

    Accepted: 'remind me to check quests in 30 minutes',
              'remind me in 2 hours to drink water',
              'remind me to play tomorrow at 6 PM',
              'remind me to read on 2026-11-05 at 7:30 PM'.
    Ambiguous times and requests without a subject are rejected.
    """
    text = _WAKE.sub("", str(message or "")[:1000]).strip()
    if not _PREFIX.match(text):
        return None
    remainder = _PREFIX.sub("", text, count=1).strip()
    tz, label = _timezone(offset_minutes)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ReminderRequestError("I need a timezone-aware clock for your reminder.")
    now_local = now.astimezone(tz)
    matches = []
    for kind, pattern in (("relative", _RELATIVE), ("local", _DAY_AT), ("date", _ISO_AT)):
        matches.extend((kind, match) for match in pattern.finditer(remainder))
    if len(matches) != 1:
        raise ReminderRequestError(
            "Tell me what and when, e.g. 'remind me to check quests in 30 minutes' "
            "or 'remind me to read tomorrow at 6 PM'.")
    kind, match = matches[0]
    if kind == "relative":
        number = int(match.group("number"))
        unit = match.group("unit").lower()
        seconds = number * (60 if unit.startswith("min") else
                            3600 if unit.startswith("h") else 86400)
        due_local = now_local + timedelta(seconds=seconds)
    else:
        hour, minute = _clock(int(match.group("hour")),
                              int(match.group("minute") or 0),
                              match.group("ampm"))
        try:
            day = (now_local.date() + timedelta(days=int(
                match.group("day").lower() == "tomorrow"))
                if kind == "local" else
                datetime.strptime(match.group("day"), "%Y-%m-%d").date())
            due_local = datetime(day.year, day.month, day.day,
                                 hour, minute, tzinfo=tz)
        except (ValueError, OverflowError) as exc:
            raise ReminderRequestError("That date is invalid.") from exc
    seconds_until = (due_local - now_local).total_seconds()
    if not _MIN_SECONDS <= seconds_until <= _MAX_SECONDS:
        raise ReminderRequestError("Choose a time between one minute and 30 days from now.")

    task = (remainder[:match.start()] + " " + remainder[match.end():]).strip()
    task = re.sub(r"^(?:to\s+)+", "", task, flags=re.IGNORECASE).strip(" ,.!?\t\n")
    task = re.sub(r"\s+", " ", task)
    if not task:
        raise ReminderRequestError(
            "What should I remind you about? Try 'remind me to check my quests in 1 hour'.")
    if len(task) > 180 or len(task) < 2:
        raise ReminderRequestError("Keep your reminder description between 2 and 180 characters.")
    if re.search(r"<@|@everyone\b|@here\b|[\x00-\x08\x0b-\x1f]", task, re.IGNORECASE):
        raise ReminderRequestError("Reminders cannot include mentions or control characters.")
    return ReminderSpec(task, int(due_local.timestamp()), label)
