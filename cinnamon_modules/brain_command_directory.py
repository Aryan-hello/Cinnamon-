"""Live-registry help pages for Cinnamon's slash and prefix commands.

Avoid duplicated, hand-maintained command lists. Discord embed fields allow
at most 1024 characters, so we cap content below that limit on every page.
The helpers are pure and can be tested without Discord or network access.
"""
from dataclasses import dataclass
from typing import Iterable


MAX_FIELD_CHARS = 950
MAX_LINE_CHARS = 225


@dataclass(frozen=True)
class DirectoryEntry:
    path: str
    description: str = ""


def _clean(value: object, *, length: int) -> str:
    return " ".join(str(value or "").split())[:length].replace("`", "'")


def slash_entries(commands: Iterable[object]) -> list[DirectoryEntry]:
    """Build from *registered* slash leaf command metadata only."""
    from cinnamon_modules.brain_help import build_command_catalog

    catalog = build_command_catalog(commands)
    return [
        DirectoryEntry(item.path, _clean(item.description, length=155))
        for item in catalog.values()
    ]


def prefix_entries(commands: Iterable[object]) -> list[DirectoryEntry]:
    """Build from bot.walk_commands(): includes real registered subcommands."""
    entries = {}
    for command in commands:
        if getattr(command, "hidden", False):
            continue
        name = _clean(getattr(command, "qualified_name", ""), length=80)
        if not name:
            continue
        path = "?" + name
        # Python prefix commands expose real argument syntax and aliases.
        # Use Discord's registered signature instead of guessing parameters.
        signature = _clean(getattr(command, "signature", ""), length=95)
        description = _clean(
            getattr(command, "brief", "") or getattr(command, "help", ""),
            length=100,
        )
        if signature:
            description = ("Args: " + signature +
                           ("; " + description if description else ""))
        aliases = tuple(str(x).strip() for x in getattr(command, "aliases", ()) or ()
                        if str(x).strip())
        if aliases:
            # Subcommand aliases must keep their parent path. An alias
            # 'todays' for 'quest daily' is '?quest todays', not '?todays'.
            parents, _, _ = name.rpartition(" ")
            extras = ", ".join(
                "?" + (parents + " " if parents else "") + alias
                for alias in aliases[:3]
            )
            description = (description + "; " if description else "") + "also " + extras
        entries[path.lower()] = DirectoryEntry(path, description)
    return sorted(entries.values(), key=lambda x: x.path.casefold())


def command_pages(entries: Iterable[DirectoryEntry], *, max_chars: int = MAX_FIELD_CHARS,
                  group_roots: bool = False) -> list[str]:
    """Produce complete, nonempty pages under a Discord embed field limit.

    Never start a page with a stranded group heading or silently lose entries.
    """
    if not 300 <= max_chars <= 1024:
        raise ValueError("Embed-field page limit must be between 300 and 1024.")
    result = []
    lines = []
    used = 0
    previous_root = None
    for entry in entries:
        path = _clean(entry.path, length=100)
        description = _clean(entry.description, length=MAX_LINE_CHARS)
        if not path:
            continue
        item = "**" + path + "**" + (" — " + description if description else "")
        item = item[:MAX_LINE_CHARS]
        root = path.lstrip("/?").split()[0].lower()
        heading = ("**" + root.replace("-", " ").replace("_", " ").title() + "**"
                   if group_roots and root != previous_root else "")
        part = "\n".join(v for v in (heading, item) if v)
        cost = len(part) + (1 if lines else 0)
        if lines and used + cost > max_chars:
            result.append("\n".join(lines))
            lines, used = [], 0
            # Repeat the heading if a command group continues on a new page.
            heading = ("**" + root.replace("-", " ").replace("_", " ").title() + "**"
                       if group_roots else "")
            part = "\n".join(v for v in (heading, item) if v)
            cost = len(part)
        if cost > max_chars:
            raise ValueError("A single command entry exceeds the page limit.")
        lines.append(part)
        used += cost
        previous_root = root
    if lines:
        result.append("\n".join(lines))
    return result or ["Cinnamon has no registered commands in this category yet."]


def registered_paths(entries: Iterable[DirectoryEntry]) -> set[str]:
    return {str(entry.path).lower() for entry in entries}


def available_shortcuts(catalog: set[str], paths: Iterable[str]) -> str:
    """Only print command links that are currently registered."""
    return " · ".join("`" + p + "`" for p in paths if p.lower() in catalog)
