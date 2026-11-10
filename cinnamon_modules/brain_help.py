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


def _feature_index(catalog: Mapping[str, CommandGuide]) -> str:
    """Compact live feature map generated only from registered commands."""
    groups: dict[str, list[str]] = {}
    for guide in catalog.values():
        root = guide.path.strip("/").split()[0].lower()
        groups.setdefault(root, []).append(guide.path)
    labels = {"economy":"Catnip economy", "quest":"Quests", "quests":"Quest tracking", "achievement":"Achievements", "fishing":"Fishing", "cinnamon":"Cinnamon companion & stories", "cinnamon-mind":"Brain & independent activities", "cinnamon-memory":"Personal memory & privacy", "cinnamon-reminder":"Reminders & personal day", "cinnamon-incident":"Incident review", "hangry":"Hangry Games", "wildlands":"Wildlands", "role":"Roles", "reactionrole":"Reaction roles", "giveaway":"Giveaways", "poll":"Polls", "profile":"Profiles", "rank":"Ranks", "leaderboard":"Leaderboards", "mute":"Moderation", "ban":"Moderation", "kick":"Moderation", "dashboard":"Dashboard", "recall":"Recovery / recall", "setup":"Server setup"}
    rows = []
    for root, paths in sorted(groups.items()):
        label = labels.get(root, root.replace("-", " ").replace("_", " ").title())
        shown = ", ".join("`" + p + "`" for p in paths[:5])
        if len(paths) > 5: shown += f" (+{len(paths)-5} more)"
        rows.append(f"**{label}**: {shown}")
    return "*opens her feature atlas* Here is what is registered right now:\n" + "\n".join(rows[:28]) + "\nAsk about any feature or slash command for details. Planned ideas are not presented as live."

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
    elif topic == "reminders":
        body = ("I can DM you about a task at a future time. Try 'Cinnamon, remind me to check "
                "quests in 30 minutes' or choose a date like 'tomorrow at 6 PM'. "
                "Times use your personal fixed UTC offset when set, or the server default "
                "(" + timezone_label + "). I can't remind another person without their request.")
        paths = ("/cinnamon-reminder create", "/cinnamon-reminder list",
                 "/cinnamon-reminder cancel", "/cinnamon-reminder snooze",
                 "/cinnamon-reminder timezone", "/cinnamon-me today")
    elif topic == "memory":
        body = ("I save only ordinary preferences you intentionally ask me to keep: "
                "games, stories, hobbies, or how you like explanations. "
                "Your private notes belong to you in this server. "
                "You can privately edit, delete or disable notes anytime without waiting for staff.")
        paths = ("/cinnamon-memory status", "/cinnamon-memory save", "/cinnamon-memory view",
                 "/cinnamon-memory edit", "/cinnamon-memory clear",
                 "/cinnamon-memory enable", "/cinnamon-me privacy")
    elif topic == "myday":
        body = ("Your private daily view shows today's pending reminders in your own fixed "
                "timezone and the number of preferences you explicitly saved. "
                "It doesn't read your private messages or schedule anything by itself.")
        paths = ("/cinnamon-me today", "/cinnamon-me privacy",
                 "/cinnamon-reminder create", "/cinnamon-memory view")
    elif topic == "independence":
        body = ("When allowed by an Administrator, I can choose whether to launch eligible "
                "Hangry Games, pose an optional no-ping question, or stay quiet. "
                "Gemini activity advice is optional and never gives me moderator powers.")
        paths = ("/cinnamon-mind status", "/cinnamon-mind independence",
                 "/cinnamon-mind prompts", "/cinnamon-mind reasoning")
    elif topic == "incidents":
        body = ("I don't judge who's right or automatically punish people for arguing. "
                "Moderators with access to a channel can request a private chronological "
                "excerpt review, then make their own decisions.")
        paths = ("/cinnamon-incident review", "/cinnamon-incident policy")
    elif topic == "recall":
        body = ("`/recall` is an Administrator-only recovery scan of configured logs and snapshots. "
                "It reconstructs only data those sources support; it cannot recover deleted "
                "Discord history or retrieve personal AI memories. Asking about it does not run recovery.")
        paths = ("/recall",)
    elif topic == "moderation":
        body = "Moderation tools help staff timeout/mute, unmute, kick, ban, and review incidents. Discord permissions and role hierarchy apply; explaining never performs moderation."
        paths = ("/mute", "/unmute", "/kick", "/ban", "/cinnamon-incident review", "/cinnamon-incident policy")
    elif topic == "roles":
        body = "Role tools assign/remove roles and support reaction roles where configured. Cinnamon must sit above managed roles; Discord permissions and hierarchy are enforced."
        paths = ("/role", "/reactionrole")
    elif topic == "leveling":
        body = "Activity XP and levels reward participation according to server progression. Check rank/profile and leaderboard; exact thresholds are data-driven, so I will not guess."
        paths = ("/level", "/rank", "/leaderboard", "/profile")
    elif topic == "games":
        body = "Cinnamon has community games and Hangry Games. Use registered game commands for modes and lobbies. Surprise games are optional and should stay quiet during inactivity or serious conversations."
        paths = ("/hangry", "/hangrygames", "/cinnamon-mind status")
    elif topic == "giveaways":
        body = "Giveaways host timed prize events with member entry controls. Creation/editing/ending are staff-controlled; check registered commands for exact options."
        paths = ("/giveaway",)
    elif topic == "wildlands":
        body = "Wildlands is Cinnamon exploration/gameplay. Available actions come from live commands and in-game prompts; planned features are not necessarily live."
        paths = tuple(path for path in catalog if "wildland" in path)
    elif topic == "social":
        body = "Social events are optional community activities. Available controls depend on commands registered in this server."
        paths = tuple(path for path in catalog if any(word in path for word in ("event", "social", "birthday")))
    elif topic == "dashboard":
        body = "The dashboard is a web control center. Anyone may request its link, but viewing/changing server settings is restricted to the owner/Administrators. Never share private login/session links."
        paths = ("/dashboard",)
    elif topic == "profile":
        body = "Profile/rank commands show member progression and public server stats. Leaderboards compare configured categories; exact values come from current server data."
        paths = ("/profile", "/rank", "/leaderboard")
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
    if path == "/dashboard":
        result += ("\nAnyone can request the dashboard link. Viewing or changing "
                   "server settings requires server owner or Administrator authorization.")
    elif path.startswith("/economy admin "):
        result += ("\nAdministrator permission and verified durable storage "
                   "are required for Catnip balance changes.")
    elif path in {"/setup", "/setupstatus", "/ban", "/kick",
                  "/datastatus check", "/datastatus recover", "/recall"} or path.startswith("/cinnamon-mind "):
        result += "\nThis command requires Administrator permissions; its own checks still apply."
    elif path in {"/mute", "/unmute", "/cinnamon-incident review"}:
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
    overview_request = bool(re.search(r"\b(?:what\s+(?:can|do)|all\s+(?:the\s+)?features|features\s+list|feature\s+list|everything\s+(?:you|cinnamon)|what\s+features)\b", lower))
    is_question = overview_request or bool(_QUERY.match(query)) or simple_topic in {
        "quests", "quest", "fishing", "stories", "achievements", "economy", "catnip",
        "help", "reminder", "reminders", "memory", "memories", "independence", "brain",
        "incident", "incidents", "today", "my day", "myday", "privacy",
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

    if re.search(r"\b(?:my\s+day|my\s+schedule|today(?:'s)?\s+(?:plan|overview)|personal\s+dashboard|privacy)\b", lower):
        topic = "myday"
    elif re.search(r"\b(?:reminders?|remind\s+me)\b", lower):
        topic = "reminders"
    elif re.search(r"\b(?:memories|memory|remember\s+(?:things|people))\b", lower):
        topic = "memory"
    elif re.search(r"\b(?:independence|autonomy|cinnamon\s+mind)\b", lower):
        topic = "independence"
    elif re.search(r"\b(?:incident|disagreement|arguing)\b", lower):
        topic = "incidents"
    elif re.search(r"\bquests?\b", lower):
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
    elif re.search(r"\b(?:moderation|timeout|mute|ban|kick|automod)\b", lower):
        topic = "moderation"
    elif re.search(r"\b(?:role|reaction.?role)\b", lower):
        topic = "roles"
    elif re.search(r"\b(?:level|xp|rank|leaderboard)\b", lower):
        topic = "leveling"
    elif re.search(r"\b(?:game|games|hangry)\b", lower):
        topic = "games"
    elif re.search(r"\bgiveaways?\b", lower):
        topic = "giveaways"
    elif re.search(r"\bwildlands\b", lower):
        topic = "wildlands"
    elif re.search(r"\bsocial|events?\b", lower):
        topic = "social"
    elif re.search(r"\bdashboard\b", lower):
        topic = "dashboard"
    elif re.search(r"\bprofile\b", lower):
        topic = "profile"
    elif simple_topic == "help" or re.fullmatch(r"(?:what|how).*(?:commands|features).*", lower):
        return "*unrolls her command ledger* Use `/help` for registered commands, or ask about quests, reminders, memory, fishing, Catnip, stories, or my independent activities."
    else:
        return None
    return _feature_answer(topic, catalog, str(timezone_label)[:60])[:1900]
