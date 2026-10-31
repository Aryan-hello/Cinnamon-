"""Deterministic, registry-backed help for Cinnamon's conversation adapter.

This module has no Discord, Gemini, storage, or execution dependencies. The
catalog contains public command metadata only; explaining a command never calls
its callback or establishes permission to use it.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping


@dataclass(frozen=True)
class CommandGuide:
    path: str
    description: str
    syntax: str


def _command_path(command: object) -> str:
    parts: list[str] = []
    seen: set[int] = set()
    current = command
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = getattr(current, "name", "")
        if name:
            parts.append(str(name))
        current = getattr(current, "parent", None)
    return "/" + " ".join(reversed(parts))


def build_command_catalog(commands: Iterable[object]) -> dict[str, CommandGuide]:
    """Read real slash command/group metadata without inspecting callbacks.

    Accept either ``bot.tree.get_commands()`` or the existing
    ``_all_leaf_commands()`` result. Required parameters use ``<name>`` and
    optional parameters use ``[name]``; names come from the live registry.
    """
    catalog: dict[str, CommandGuide] = {}
    seen: set[int] = set()

    def visit(command: object) -> None:
        if id(command) in seen:
            return
        seen.add(id(command))
        children = getattr(command, "commands", None)
        if children:
            for child in children:
                visit(child)
            return
        path = _command_path(command)
        if path == "/":
            return
        arguments = []
        for parameter in getattr(command, "parameters", ()) or ():
            name = str(getattr(parameter, "display_name", None)
                       or getattr(parameter, "name", "argument"))
            arguments.append("<" + name + ">" if getattr(parameter, "required", True)
                             else "[" + name + "]")
        syntax = path + (" " + " ".join(arguments) if arguments else "")
        catalog[path.lower()] = CommandGuide(
            path=path,
            description=str(getattr(command, "description", "") or "No description provided.")[:500],
            syntax=syntax[:700],
        )

    for command in commands:
        visit(command)
    return dict(sorted(catalog.items()))


_ADDRESS = re.compile(
    r"^\s*(?:(?:hey|hi|hello|yo|please)[,! ]+)?cinnamon\s*[,!:.]?\s*",
    re.IGNORECASE,
)
_QUERY = re.compile(
    r"^(?:what\b|how\b|why\b|explain\b|help\b|tell\s+me\b|show\s+me\b|"
    r"can\s+you\s+(?:explain|help|tell|show)\b|"
    r"i\s+(?:do\s+not|don['’]t)\s+understand\b)",
    re.IGNORECASE,
)
_SLASH = re.compile(r"/([a-z][a-z0-9_-]*(?:\s+[a-z][a-z0-9_-]*){0,5})", re.IGNORECASE)


def _links(catalog: Mapping[str, CommandGuide], paths: tuple[str, ...]) -> str:
    return " · ".join("`" + catalog[path].path + "`" for path in paths if path in catalog)


def _feature_answer(topic: str, catalog: Mapping[str, CommandGuide], timezone_label: str) -> str:
    if topic == "quests":
        body = ("Five daily and five weekly quests track your progress. Completing them earns "
                "Quest Points and XP; redeem Quest Points in the quest shop. Daily quests "
                "rotate at midnight and weekly quests at Monday midnight (" + timezone_label + ").")
        paths = ("/quests daily", "/quests weekly", "/quests progress", "/questshop")
    elif topic == "fishing":
        body = ("Start fishing to receive your starter rod and 10 bait, then cast to play the "
                "interactive fishing sequence. Your journal tracks catches; you can sell fish "
                "and explore other areas.")
        paths = ("/fishing start", "/fishing cast", "/fishing journal", "/fishing sell", "/fishing travel")
    elif topic == "stories":
        body = ("You choose the route through Cinnamon's authored interactive adventure. "
                "Open the story menu to start or continue; chat replies don't decide story outcomes.")
        paths = ("/cinnamon stories",)
    elif topic == "achievements":
        body = ("Achievements record milestones from Cinnamon's features. Open the achievement "
                "list to see the normal achievements and your progress.")
        paths = ("/achievement list",)
    elif topic == "recall":
        body = ("`/recall` is an Administrator-only recovery scan of configured logs and snapshots. "
                "It reconstructs only data those sources support; it cannot recover deleted "
                "Discord history or retrieve personal AI memories. Asking about it does not run recovery.")
        paths = ("/recall",)
    else:
        body = ("Catnip is this server's economy currency. Check your wallet, earn Catnip with "
                "daily/work rewards, and use the shop for items. Administrative adjustments "
                "require real server authority.")
        paths = ("/economy balance", "/economy daily", "/economy work", "/economy shop", "/economy inventory")
    commands = _links(catalog, paths)
    if not commands:
        return "*checks her command ledger* That feature has no registered commands available right now. Try `/help` after setup finishes."
    return "*unrolls an unnecessarily important scroll* " + body + "\n" + commands


def _describe_command(guide: CommandGuide, catalog: Mapping[str, CommandGuide], timezone_label: str) -> str:
    if guide.path.lower() == "/recall":
        return _feature_answer("recall", catalog, timezone_label)
    result = "*checks her command ledger* **" + guide.path + "** — " + guide.description
    result += "\nUsage: `" + guide.syntax + "`"
    path = guide.path.lower()
    if path.startswith("/economy admin ") or path in {"/dashboard", "/setup", "/ban", "/kick"}:
        result += "\nThis command requires server owner or Administrator authority; its own checks still apply."
    elif path in {"/mute", "/unmute"}:
        result += "\nModeration permissions and Discord role hierarchy still apply."
    return result


def answer_help(text: str, catalog: Mapping[str, CommandGuide], *, timezone_label: str = "UTC+05:30") -> str | None:
    """Return public command guidance for a recognizable help request, or None.

    Unknown questions are left to conversation. Unknown slash commands receive
    an explicit answer instead of an invented command. This function neither
    executes commands nor checks a particular user's authorization.
    """
    if not isinstance(text, str):
        return None
    query = _ADDRESS.sub("", text, count=1).strip()
    lower = query.lower()
    simple_topic = lower.rstrip(" ?.! ")
    is_question = bool(_QUERY.match(query)) or simple_topic in {
        "quests", "quest", "fishing", "stories", "achievements", "economy", "catnip", "help"
    }
    if not is_question:
        return None

    slash = _SLASH.search(query)
    if slash:
        words = slash.group(1).lower().split()
        # Following prose ("do?", "work?") cannot change which registry entry
        # is explained. Prefer the longest exact registered command path.
        for end in range(len(words), 0, -1):
            guide = catalog.get("/" + " ".join(words[:end]))
            if guide:
                return _describe_command(guide, catalog, str(timezone_label)[:60])[:1900]
        root = "/" + words[0]
        children = [guide.path for key, guide in catalog.items() if key.startswith(root + " ")]
        if children:
            return ("*checks her command ledger* Choose a registered subcommand: "
                    + " · ".join("`" + path + "`" for path in children[:8]))[:1900]
        return "*checks her command ledger* `" + root[:80] + "` is not registered. Use `/help` for Cinnamon's current commands."

    if re.search(r"\bquests?\b", lower):
        topic = "quests"
    elif re.search(r"\b(?:fish|fishing)\b", lower):
        topic = "fishing"
    elif re.search(r"\b(?:stories|story|adventures?)\b", lower):
        topic = "stories"
    elif re.search(r"\bachievements?\b", lower):
        topic = "achievements"
    elif re.search(r"\brecall\b", lower):
        topic = "recall"
    elif re.search(r"\b(?:catnip|economy|wallet|shop)\b", lower):
        topic = "economy"
    elif simple_topic == "help" or re.fullmatch(r"(?:what|how).*(?:commands|features).*", lower):
        return "*unrolls her command ledger* Use `/help` for the registered command directory, or ask me how quests, fishing, achievements, Catnip, or stories work."
    else:
        return None
    return _feature_answer(topic, catalog, str(timezone_label)[:60])[:1900]
