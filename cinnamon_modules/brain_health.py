"""Cinnamon Brain diagnostics: safe readiness booleans, no secret values."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class HealthCheck:
    name: str
    ready: bool
    detail: str


def command_name_counts(commands) -> dict[str, int]:
    counts = Counter(str(getattr(command, "name", "")) for command in commands)
    return {name: count for name, count in counts.items() if name and count > 1}


def build_brain_health(*, storage_ready: bool, model_configured: bool,
                       modules: dict[str, bool], duplicate_commands: dict[str, int] | None = None):
    """Return a stable, non-sensitive checklist; never include keys or IDs."""
    checks = [
        HealthCheck("Persistent storage", bool(storage_ready),
                   "ready" if storage_ready else "not ready; state-changing Brain features should fail closed"),
        HealthCheck("Gemini configuration", bool(model_configured),
                   "configured (connectivity not tested)" if model_configured else "not configured"),
    ]
    labels = {
        "actions": "Trusted action dispatcher",
        "help": "Command help catalog",
        "memory": "Preference memory",
        "reminders": "Reminder scheduler",
        "member": "Private member tools",
        "incidents": "Incident assistance",
        "activity": "Activity adviser",
    }
    for key, label in labels.items():
        ready = bool(modules.get(key, False))
        checks.append(HealthCheck(label, ready, "loaded" if ready else "missing"))
    duplicates = duplicate_commands or {}
    duplicate_detail = ("no duplicate top-level names" if not duplicates else
                         "duplicates: " + ", ".join(f"{k}×{v}" for k, v in sorted(duplicates.items())))
    checks.append(HealthCheck("Slash command names", not duplicates, duplicate_detail))
    return tuple(checks)
