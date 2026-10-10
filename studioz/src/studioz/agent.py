"""The agent of a workspace: one Claude Code conversation, through the Agent SDK.

Each workspace has one conversation at a time (two agents would edit the
same files), run by the Agent SDK's own, unmodified Claude Code binary,
logged in as the person (`claude auth status`): studioz never handles
credentials, and removes `ANTHROPIC_API_KEY` from its environment at start
(see `studioz.cli`), so that a key left in a shell can't take over billing.

The agent works in the workspace (`cwd`), with the repository's project
settings only (its `CLAUDE.md`, skills and hooks; not the person's own
`~/.claude` setup, nor auto memory), `auto` permissions inside Claude Code's
command sandbox, and the workspace's own deckz and caches (plan, "Finding 2").
It never commits, pushes nor moves the branch: a `PreToolUse` hook refuses
it, the person commits from studioz. A tool call the permission rules would
ask about is refused with a message, never shown to the person. A question
the agent asks (`AskUserQuestion`, as slides' skills do) is shown as a form,
and the turn waits for the answer (`can_use_tool`).

Claude's usage limits are the account's (the person's other uses of Claude
count too): the panel shows the five-hour and seven-day windows as Claude Code
reports them, each turn's estimated usage, and a turn stopped by a limit is a
pause: the conversation resumes by itself once the limit resets.

The conversation outlives a page and studioz itself: its session id and the
transcript shown are kept under the workspace's `.run/studioz/agent/`, and
the next message resumes the session (`resume=`). The Claude Code process
(about 0.5 GB) is stopped once the conversation has been idle a while.
"""

import asyncio
import json
import re
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from time import monotonic, time
from typing import Any, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    RateLimitEvent,
    RateLimitInfo,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from . import checkpoints
from .watches import workspace_environment
from .workspaces import STATE_DIR

AGENT_DIR = STATE_DIR / "agent"
"""The conversation's state, relative to a workspace."""

_SESSION = "session"
_TRANSCRIPT = "transcript.jsonl"
_IDLE_AFTER = 15 * 60.0
_DETAIL = 400

APPEND = """\
Tu travailles dans un espace de travail studioz : une copie du dépôt (un \
worktree git) consacrée à une ligne de travail, que la personne fait évoluer \
avec toi et à la main, en voyant les formations construites en direct.

- La personne connaît le contenu des formations, pas l'outillage : réponds en \
français, simplement, sans jargon git ni détails de commandes, et dis ce que \
tu as changé, fichier par fichier. Écris aussi en français la description \
de chaque commande que tu lances : la personne la voit.
- Ne committe jamais, ne pousse jamais, ne change pas de branche : la personne \
committe elle-même depuis studioz quand elle le décide, en voyant les \
modifications.
- Quand la personne doit choisir (une option, une façon de faire), \
demande-le avec AskUserQuestion : elle voit un formulaire, et ton tour \
attend sa réponse. Pour une question ouverte, pose-la dans ta réponse et \
arrête-toi : elle te répondra dans la conversation.
"""
"""Appended to Claude Code's system prompt."""

# Commands that commit, push, move or rewrite the branch, or discard changes:
# the person does that from studioz. Matched anywhere in a command line,
# after `git` and its options (`git -C x commit`), up to the next `;`, `&`,
# `|` or newline.
_GIT = re.compile(
    r"\bgit(?:\s+-[Cc]\s+\S+|\s+--?[\w-]+(?:=\S+)?)*\s+"
    r"(?P<verb>[\w-]+)(?P<rest>[^;&|\n]*)"
)
_ALWAYS = frozenset(
    {
        "commit",
        "push",
        "pull",
        "rebase",
        "reset",
        "checkout",
        "switch",
        "restore",
        "stash",
        "merge",
        "cherry-pick",
        "revert",
        "am",
        "update-ref",
    }
)
# These only read, unless given one of these options or subcommands.
_CHANGING = {
    "branch": re.compile(r"\s(?:-[dDmMcCf]\b|--(?:delete|move|copy|force)\b|[^-\s])"),
    "tag": re.compile(r"\s(?:-[dfas]\b|--(?:delete|force)\b|[^-\s])"),
    "worktree": re.compile(r"\s(?!list\b)\w"),
}


def refused_git(command: str) -> str | None:
    """Why the agent may not run `command`: it commits or moves the branch.

    Returns:
        The git subcommand refused, None if the command may run.
    """
    for found in _GIT.finditer(command):
        verb = found["verb"]
        changing = _CHANGING.get(verb)
        if verb in _ALWAYS or (changing and changing.search(found["rest"])):
            return verb
    return None


@dataclass(frozen=True)
class Entry:
    """A line of the transcript a page shows."""

    kind: str
    """`person`, `text`, `tool`, `error`, `end` or `notice`."""
    text: str
    detail: str = ""
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


ASK = "AskUserQuestion"
OTHER = "__autre__"
"""A radio button's value for a free answer."""


@dataclass(frozen=True)
class Choice:
    label: str
    description: str = ""


@dataclass(frozen=True)
class Asked:
    """One of the questions in an `AskUserQuestion` call."""

    question: str
    header: str
    choices: tuple[Choice, ...]
    multiple: bool

    def answer(self, chosen: list[str], other: str) -> str:
        """The answer Claude Code expects, from a form's fields.

        Args:
            chosen: The labels ticked (or `OTHER`).
            other: The free answer, if any.

        Returns:
            The labels chosen, in the question's order, then the free answer,
            joined by ", " (a single choice: the free answer replaces it); empty
            if nothing was answered.
        """
        labels = [c.label for c in self.choices if c.label in chosen]
        free = other.strip() if OTHER in chosen or self.multiple else ""
        if not self.multiple:
            return free or (labels[0] if labels else "")
        return ", ".join([*labels, *([free] if free else [])])


def asked(data: dict[str, Any]) -> list[Asked]:
    """The questions of an `AskUserQuestion` call's input.

    Returns:
        Them, maybe none if the input isn't what Claude Code sends.
    """
    found = []
    for item in data.get("questions") or []:
        if not isinstance(item, dict) or not item.get("question"):
            continue
        choices = tuple(
            Choice(str(o.get("label", "")), str(o.get("description", "")))
            for o in item.get("options") or []
            if isinstance(o, dict) and o.get("label")
        )
        found.append(
            Asked(
                str(item["question"]),
                str(item.get("header", "")),
                choices,
                bool(item.get("multiSelect")),
            )
        )
    return found


@dataclass
class Question:
    """A question the agent waits on."""

    id: int
    asked: list[Asked]
    answers: "asyncio.Future[dict[str, str] | None]"


def _short(text: str, limit: int = _DETAIL) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _relative(workspace: Path, value: object) -> str:
    return str(value or "").replace(f"{workspace}/", "")


def tool_entry(workspace: Path, block: ToolUseBlock) -> Entry:
    """What a tool use says on one line, in French.

    Returns:
        Its entry, the command or file in `detail`.
    """
    data = block.input
    name = block.name
    if name == "Bash":
        what = data.get("description") or "Commande"
        return Entry("tool", str(what), _relative(workspace, data.get("command")))
    if name in {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}:
        verb = "Lit" if name == "Read" else "Modifie"
        path = data.get("file_path") or data.get("notebook_path")
        return Entry("tool", verb, _relative(workspace, path))
    if name in {"Grep", "Glob"}:
        return Entry("tool", "Cherche", _relative(workspace, data.get("pattern")))
    if name == "Skill":
        return Entry("tool", "Suit la procédure", str(data.get("skill", "")))
    if name in {"Task", "Agent"}:
        return Entry(
            "tool", "Délègue à un sous-agent", str(data.get("description", ""))
        )
    if name == "TodoWrite":
        items = [
            f"{'✓' if todo.get('status') == 'completed' else '·'} {todo.get('content')}"
            for todo in data.get("todos", [])
        ]
        return Entry("tool", "Liste de tâches", "\n".join(items))
    if name in {"WebFetch", "WebSearch"}:
        what = data.get("url") or data.get("query")
        return Entry("tool", "Consulte le web", str(what or ""))
    return Entry("tool", name)


def _result_text(block: ToolResultBlock) -> str:
    content = block.content
    if isinstance(content, list):
        content = "\n".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    return str(content or "")


def _assistant(workspace: Path, message: AssistantMessage) -> list[Entry]:
    found = []
    for block in message.content:
        if isinstance(block, TextBlock) and block.text.strip():
            found.append(Entry("text", block.text.strip()))
        elif isinstance(block, ToolUseBlock) and block.name != ASK:
            # A question shows as its own entry, once asked (`Conversation`).
            found.append(tool_entry(workspace, block))
    return found


# How Claude Code words a hook's refusal (studioz's own, `_refuse_git`).
_HOOK_REFUSAL = re.compile(r"^PreToolUse:\w+ hook error:\s*")


def _failed_tools(workspace: Path, message: UserMessage) -> list[Entry]:
    if not isinstance(message.content, list):
        return []
    found = []
    for block in message.content:
        if isinstance(block, ToolResultBlock) and block.is_error:
            text = _relative(workspace, _result_text(block)).strip()
            reason, refused = _HOOK_REFUSAL.subn("", text)
            what = "Refusé par studioz" if refused else "Refusé ou en échec"
            found.append(Entry("error", what, _short(reason)))
    return found


def _result(message: ResultMessage, stopped: bool, limited: bool) -> list[Entry]:
    seconds = round(message.duration_ms / 1000)
    if limited and message.is_error:
        return [Entry("end", f"Interrompu par la limite au bout de {seconds} s")]
    # An interrupted turn may end on an error result (`ede_diagnostic`).
    if stopped or message.terminal_reason in {"aborted_streaming", "aborted_tools"}:
        return [Entry("end", f"Arrêté au bout de {seconds} s")]
    if message.is_error:
        errors = "\n".join(message.errors or []) or message.result or ""
        return [Entry("error", "Le tour s'est arrêté sur une erreur", _short(errors))]
    cost = message.total_cost_usd
    usage = (
        f"Usage estimé : {cost:.2f} $ au tarif de l'API, décompté de votre "
        "abonnement".replace(".", ",", 1)
        if cost
        else ""
    )
    return [Entry("end", f"Terminé en {seconds} s", usage)]


def when(timestamp: float) -> str:
    """A reset time, in French.

    Returns:
        « 18:30 » today, else « le 13/10 à 08:00 ».
    """
    moment = datetime.fromtimestamp(timestamp)
    if moment.date() == datetime.now().date():
        return moment.strftime("%H:%M")
    return moment.strftime("le %d/%m à %H:%M")


def _rate_limit(message: RateLimitEvent) -> list[Entry]:
    info = message.rate_limit_info
    if info.status != "rejected":
        return []
    reset = f"elle se renouvelle {when(info.resets_at)}" if info.resets_at else ""
    return [Entry("error", "Limite d'utilisation de votre abonnement atteinte", reset)]


@dataclass(frozen=True)
class Window:
    """One of the account's usage windows."""

    name: str
    """`five_hour`, `seven_day`…"""
    used: float
    """The share used, from 0 to 1."""
    resets_at: float | None


_WINDOWS = {"five_hour": ("5 h", "des 5 heures"), "seven_day": ("7 j", "de la semaine")}
_WARN = 0.75


def windows(info: RateLimitInfo) -> tuple[Window, ...]:
    """The usage windows a `RateLimitEvent` reports.

    Returns:
        Them, from `unifiedWindows` (seen with Claude Code 2.1.283), else the one
        the event is about.
    """
    unified = (info.raw or {}).get("unifiedWindows") or {}
    found = tuple(
        Window(name, float(data.get("utilization") or 0), data.get("resetsAt"))
        for name, data in unified.items()
        if isinstance(data, dict)
    )
    if found or info.utilization is None:
        return found
    return (Window(info.rate_limit_type or "?", info.utilization, info.resets_at),)


def usage_summary(found: tuple[Window, ...]) -> dict[str, object]:
    """What the panel shows of the account's usage.

    Returns:
        `text` (« 5 h : 11 % · 7 j : 77 % »), `title` (with the reset times),
        `warn` (a window at 75 % or more); empty before Claude Code reported any.
    """
    if not found:
        return {"text": "", "title": "", "warn": False}
    text = " · ".join(
        f"{_WINDOWS.get(w.name, (w.name, ''))[0]} : {round(w.used * 100)} %"
        for w in found
    )
    details = [
        f"{round(w.used * 100)} % de la fenêtre {_WINDOWS.get(w.name, ('', w.name))[1]}"
        + (f", renouvelée {when(w.resets_at)}" if w.resets_at else "")
        for w in found
    ]
    title = (
        "Votre abonnement Claude (tout ce que vous faites avec Claude compte) : "
        + " ; ".join(details)
    )
    return {"text": text, "title": title, "warn": any(w.used >= _WARN for w in found)}


RESUME = (
    "La limite d'utilisation de l'abonnement est passée : reprends là où tu "
    "t'étais arrêté."
)
"""Sent when a conversation paused by a limit resumes by itself."""


class Account:
    """What every conversation shares: the account's usage windows."""

    def __init__(self) -> None:
        self.windows: tuple[Window, ...] = ()


def entries(
    workspace: Path, message: object, stopped: bool = False, limited: bool = False
) -> list[Entry]:
    """What a message adds to the transcript.

    A subagent's own messages aren't shown: the tool use that started it is.

    Args:
        workspace: The workspace, which paths are shown relative to.
        message: The Agent SDK's message.
        stopped: Whether the person stopped the turn it ends.
        limited: Whether a usage limit stopped it.

    Returns:
        Its entries, maybe none.
    """
    if isinstance(message, AssistantMessage) and not message.parent_tool_use_id:
        return _assistant(workspace, message)
    if isinstance(message, UserMessage) and not message.parent_tool_use_id:
        # Once stopped, the tools interrupted fail: "Arrêté" says it.
        return [] if stopped else _failed_tools(workspace, message)
    if isinstance(message, ResultMessage):
        return _result(message, stopped, limited)
    if isinstance(message, RateLimitEvent):
        return _rate_limit(message)
    return []


class Client(Protocol):
    """What studioz uses of `ClaudeSDKClient` (tests replace it)."""

    async def connect(self) -> None: ...

    async def query(self, prompt: str) -> None: ...

    def receive_response(self) -> AsyncIterator[Any]: ...

    async def interrupt(self) -> None: ...

    async def disconnect(self) -> None: ...


def _sdk_client(options: ClaudeAgentOptions) -> Client:
    return ClaudeSDKClient(options)


# The SDK awaits its hooks and `can_use_tool`: they are coroutines with
# nothing to await.
async def _refuse_git(  # ruff: ignore[unused-async]
    hook_input: HookInput, _tool_use_id: str | None, _context: HookContext
) -> HookJSONOutput:
    tool_input = hook_input.get("tool_input") or {}
    verb = refused_git(str(tool_input.get("command", "")))
    if verb is None:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"`git {verb}` est refusé dans studioz : la personne committe, "
                "synchronise et change de branche elle-même. Laisse les "
                "modifications dans l'espace et dis-lui ce que tu as fait."
            ),
        }
    }


async def _no_op(  # ruff: ignore[unused-async]
    _input: HookInput, _tool_use_id: str | None, _context: HookContext
) -> HookJSONOutput:
    # The Python SDK calls `can_use_tool` only with a `PreToolUse` hook set.
    return {}


async def _deny(  # ruff: ignore[unused-async]
    tool: str, _input: dict[str, Any], _context: ToolPermissionContext
) -> PermissionResult:
    return PermissionResultDeny(
        message=(
            f"{tool} n'est pas autorisé ici, et studioz ne montre pas de demande "
            "d'autorisation à la personne : fais autrement, ou explique-lui ce "
            "qu'il faudrait faire."
        )
    )


def options(
    workspace: Path,
    resume: str | None,
    can_use_tool: Callable[
        [str, dict[str, Any], ToolPermissionContext], Awaitable[PermissionResult]
    ] = _deny,
) -> ClaudeAgentOptions:
    """The agent's options in a workspace (see the module docstring).

    Args:
        workspace: The workspace.
        resume: The session to resume.
        can_use_tool: What decides the tool calls the permission rules would
            ask about, and answers the agent's questions; all denied by default.

    Returns:
        The options, resuming `resume` if given.
    """
    cache = workspace / ".run" / "cache"
    env = workspace_environment(
        workspace,
        VIRTUAL_ENV=str(workspace / ".venv"),
        CLAUDE_CODE_DISABLE_AUTO_MEMORY="1",
        # Under the sandbox, `~/.cache` is read-only (plan, "Finding 2").
        UV_CACHE_DIR=str(cache / "uv"),
        XDG_CACHE_HOME=str(cache),
        MPLCONFIGDIR=str(cache / "matplotlib"),
        CLAUDE_AGENT_SDK_CLIENT_APP="studioz",
    )
    env.pop("ANTHROPIC_API_KEY", None)
    return ClaudeAgentOptions(
        cwd=workspace,
        resume=resume,
        setting_sources=["project"],
        system_prompt={"type": "preset", "preset": "claude_code", "append": APPEND},
        permission_mode="auto",
        sandbox={"enabled": True, "autoAllowBashIfSandboxed": True},
        env=env,
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="Bash", hooks=[_refuse_git]),
                HookMatcher(matcher=None, hooks=[_no_op]),
            ]
        },
        can_use_tool=can_use_tool,
    )


def logged_in(cli: str | None = None) -> tuple[bool, str]:
    """Whether Claude Code is logged in on this machine, as the person.

    Args:
        cli: The `claude` executable; the Agent SDK's own by default.

    Returns:
        Whether it is, and the account (or why not), to show.
    """
    command = cli or claude_cli()
    try:
        result = subprocess.run(
            [command, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        status = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False, "Claude Code ne répond pas"
    if not status.get("loggedIn"):
        return False, "Claude Code n'est connecté à aucun compte"
    if status.get("authMethod") not in {"claude.ai", None}:
        return (
            False,
            f"Claude Code est connecté par {status.get('authMethod')}, "
            "pas par un compte Claude",
        )
    return True, str(status.get("email") or "")


def claude_cli() -> str:
    """The Claude Code the agent runs: the Agent SDK's own, else the `PATH`'s.

    Returns:
        Its path, or `claude`.
    """
    import claude_agent_sdk

    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    return str(bundled) if bundled.is_file() else "claude"


class Conversation:
    """A workspace's conversation with its agent."""

    def __init__(
        self,
        workspace: Path,
        client_factory: Callable[[ClaudeAgentOptions], Client] = _sdk_client,
        account: Account | None = None,
    ) -> None:
        self.workspace = workspace
        self.account = account or Account()
        self.paused_until: float | None = None
        """When a limit stopped the agent: it resumes by itself then."""
        self._limited_until: float | None = None
        self._factory = client_factory
        self._directory = workspace / AGENT_DIR
        self.entries: list[Entry] = self._load()
        self.running = False
        self._stopped = False
        self.version = 0
        """Grows at each change, which the pages follow."""
        self.question: Question | None = None
        """The question the agent waits on, if any."""
        self.undoable: checkpoints.Turn | None = checkpoints.last(self._directory)
        """The last turn, if it changed files: "Annuler ce tour" puts them back."""
        self._note: str | None = None
        """What the agent is told with the next message (an undone turn)."""
        self._questions = count(1)
        self._client: Client | None = None
        self._task: asyncio.Task[None] | None = None
        self._changed = asyncio.Condition()
        self.last_activity = monotonic()

    @property
    def session(self) -> str | None:
        path = self._directory / _SESSION
        return (
            path.read_text(encoding="utf8").strip() or None if path.is_file() else None
        )

    def _load(self) -> list[Entry]:
        path = self._directory / _TRANSCRIPT
        if not path.is_file():
            return []
        found = []
        for line in path.read_text(encoding="utf8").splitlines():
            try:
                found.append(Entry(**json.loads(line)))
            except (ValueError, TypeError):
                continue
        return found

    async def _add(self, *new: Entry) -> None:
        if not new:
            return
        self._directory.mkdir(parents=True, exist_ok=True)
        with (self._directory / _TRANSCRIPT).open("a", encoding="utf8") as file:
            for entry in new:
                file.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        self.entries.extend(new)
        await self._notify()

    async def _notify(self) -> None:
        self.last_activity = monotonic()
        async with self._changed:
            self.version += 1
            self._changed.notify_all()

    async def wait(self, version: int, timeout: float) -> None:
        """Return once the conversation changed since `version`, or after `timeout`."""
        async with self._changed:
            if self.version != version:
                return
            with suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), timeout)

    async def send(self, prompt: str) -> bool:
        """Give the agent a message, starting its turn.

        Returns:
            Whether it was sent: not while the agent is still at work.
        """
        if self.running or not prompt.strip():
            return False
        # The person takes over from a pause.
        self.paused_until = None
        await self._add(Entry("person", prompt.strip()))
        self._start(prompt.strip())
        return True

    def _start(self, prompt: str) -> None:
        self.running = True
        self._stopped = False
        self._limited_until = None
        note, self._note = self._note, None
        told = f"{note}\n\n{prompt}" if note else prompt
        self._task = asyncio.create_task(self._turn(told))

    async def resume_if_due(self) -> None:
        """Resume a conversation a limit paused, once the limit reset."""
        if self.paused_until is None or self.running or time() < self.paused_until:
            return
        self.paused_until = None
        await self._add(Entry("notice", "Reprise après la limite d'utilisation"))
        self._start(RESUME)

    async def _turn(self, prompt: str) -> None:
        index = self._directory / "index"
        before = await asyncio.to_thread(checkpoints.snapshot, self.workspace, index)
        checked = False
        try:
            if self._client is None:
                client = self._factory(
                    options(self.workspace, self.session, self._can_use_tool)
                )
                await client.connect()
                self._client = client
            await self._client.query(prompt)
            async for message in self._client.receive_response():
                if isinstance(message, RateLimitEvent):
                    self._limited(message.rate_limit_info)
                if isinstance(message, ResultMessage) and message.session_id:
                    self._directory.mkdir(parents=True, exist_ok=True)
                    (self._directory / _SESSION).write_text(
                        message.session_id, encoding="utf8"
                    )
                if isinstance(message, ResultMessage) and not checked:
                    # Before "Terminé": the files changed belong to the turn.
                    checked = True
                    await self._checkpoint(index, before)
                await self._add(
                    *entries(
                        self.workspace,
                        message,
                        self._stopped,
                        self._limited_until is not None,
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # The SDK's errors (no CLI, a crashed process) end the turn, shown.
            await self._add(Entry("error", "L'agent s'est arrêté", _short(str(error))))
            await self._disconnect()
        finally:
            # Even a failed turn may have changed files.
            if not checked:
                await self._checkpoint(index, before)
            self.running = False
            if self._limited_until is not None and not self._stopped:
                self.paused_until = self._limited_until
                await self._add(
                    Entry(
                        "notice",
                        f"En pause : l'agent reprendra seul {when(self.paused_until)}",
                        "« Arrêter » annule la reprise ; un message de votre part "
                        "la remplace.",
                    )
                )
            await self._notify()

    def _limited(self, info: RateLimitInfo) -> None:
        self.account.windows = windows(info) or self.account.windows
        if info.status == "rejected":
            # Unknown reset: try again in an hour.
            self._limited_until = info.resets_at or time() + 3600

    async def _checkpoint(self, index: Path, before: str | None) -> None:
        after = await asyncio.to_thread(checkpoints.snapshot, self.workspace, index)
        if before is None or after is None:
            return
        turn = await asyncio.to_thread(
            checkpoints.record, self.workspace, self._directory, before, after
        )
        if turn is None:
            return
        self.undoable = turn
        count = len(turn.files)
        await self._add(
            Entry(
                "changes",
                f"{count} fichier{'s' if count > 1 else ''} modifié"
                f"{'s' if count > 1 else ''} par ce tour",
                "\n".join(turn.files),
            )
        )

    async def undo(self) -> str | None:
        """Put back the files the last turn changed (see `checkpoints.undo`).

        Returns:
            None once done, else why it wasn't, in French.
        """
        turn = self.undoable
        if self.running or turn is None:
            return "Aucun tour à annuler"
        index = self._directory / "index"
        try:
            undone = await asyncio.to_thread(
                checkpoints.undo, self.workspace, index, turn
            )
        except checkpoints.UndoRefusedError as error:
            return str(error)
        self.undoable = None
        await asyncio.to_thread(checkpoints.forget, self.workspace, self._directory)
        detail = "\n".join(undone.restored)
        if undone.kept:
            detail += "\nLaissés tels quels (modifiés depuis) :\n" + "\n".join(
                undone.kept
            )
        await self._add(
            Entry(
                "notice",
                f"Tour annulé : {len(undone.restored)} fichier(s) remis",
                detail,
            )
        )
        self._note = (
            "(La personne a annulé ton dernier tour depuis studioz : ces fichiers "
            f"sont revenus à leur état d'avant : {', '.join(undone.restored) or '—'}"
            + (
                f" ; ceux-ci, modifiés depuis par la personne, n'ont pas été touchés : "
                f"{', '.join(undone.kept)}"
                if undone.kept
                else ""
            )
            + ".)"
        )
        return None

    async def _can_use_tool(
        self, tool: str, data: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResult:
        found = asked(data) if tool == ASK else []
        if not found:
            return await _deny(tool, data, context)
        answers: asyncio.Future[dict[str, str] | None] = (
            asyncio.get_running_loop().create_future()
        )
        self.question = Question(next(self._questions), found, answers)
        await self._add(Entry("question", "\n".join(a.question for a in found)))
        try:
            given = await answers
        finally:
            self.question = None
            await self._notify()
        if given is None:
            return PermissionResultDeny(message="La personne a arrêté sans répondre.")
        await self._add(Entry("person", "\n".join(f"{q} → {given[q]}" for q in given)))
        return PermissionResultAllow(updated_input={**data, "answers": given})

    def answer(self, question_id: int, answers: dict[str, str]) -> bool:
        """Answer the question the agent waits on.

        Args:
            question_id: The question answered, which must still be waiting.
            answers: Each question's answer (`Asked.answer`), by its text.

        Returns:
            Whether the agent got the answers.
        """
        question = self.question
        if (
            question is None
            or question.id != question_id
            or question.answers.done()
            or set(answers) != {a.question for a in question.asked}
        ):
            return False
        question.answers.set_result(answers)
        return True

    def _drop_question(self) -> None:
        if self.question is not None and not self.question.answers.done():
            self.question.answers.set_result(None)

    async def interrupt(self) -> None:
        """Stop the agent's turn, or cancel a pause; what it changed stays."""
        if self.paused_until is not None and not self.running:
            self.paused_until = None
            await self._add(Entry("notice", "Reprise annulée"))
            return
        if self.running and self._client is not None:
            self._stopped = True
            self._drop_question()
            await self._client.interrupt()

    async def reset(self) -> None:
        """Start afresh: a new conversation, the old one's transcript dropped."""
        await self.interrupt()
        if self._task is not None:
            await asyncio.wait({self._task}, timeout=10)
        await self._disconnect()
        for name in (_SESSION, _TRANSCRIPT):
            (self._directory / name).unlink(missing_ok=True)
        self.entries = []
        self._note = None
        await self._notify()

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                # Already gone: nothing to stop.
                return

    async def close(self) -> None:
        self._drop_question()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.wait({self._task}, timeout=10)
        await self._disconnect()

    async def stop_if_idle(self) -> None:
        if (
            self._client is not None
            and not self.running
            and monotonic() - self.last_activity > _IDLE_AFTER
        ):
            await self._disconnect()


class Agents:
    """Each workspace's conversation."""

    def __init__(
        self, client_factory: Callable[[ClaudeAgentOptions], Client] = _sdk_client
    ) -> None:
        self._factory = client_factory
        self._conversations: dict[Path, Conversation] = {}
        self.account = Account()

    def conversation(self, workspace: Path) -> Conversation:
        if workspace not in self._conversations:
            self._conversations[workspace] = Conversation(
                workspace, self._factory, self.account
            )
        return self._conversations[workspace]

    async def stop_idle(self) -> None:
        """Stop the idle agents' processes, and resume the paused ones due."""
        for conversation in list(self._conversations.values()):
            await conversation.stop_if_idle()
            await conversation.resume_if_due()

    async def close_all(self) -> None:
        for conversation in list(self._conversations.values()):
            await conversation.close()
