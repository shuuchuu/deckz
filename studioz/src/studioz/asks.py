"""What studioz's dialogs ask the agent: the prompts, and the commit message.

A dialog's "Demander à l'agent" sends the workspace's conversation a prompt
studioz writes from what the dialog shows (a one-sided pair, a refusal, a
conflict), so that the person needn't explain it; the turn then shows in the
agent's panel like any other, and the person still commits or continues
from the dialog. "Proposer un message" is different: a single exchange with
no tool, on the diff of the files ticked, kept out of the conversation.
"""

import subprocess
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from .watches import workspace_environment

TASKS = frozenset({"traduire", "corriger", "conflit"})

_DIFF_LIMIT = 30_000
_DRAFT_MODEL = "haiku"
"""A commit message needs no more: it spares the person's plan."""


def prompt(task: str, values: dict[str, list[str]]) -> str:
    """The prompt a dialog's "Demander à l'agent" sends.

    Args:
        task: `traduire` (`changed`, `other`: a pair's paths), `corriger`
            (`refused`: what the repository said, `path`: the files ticked) or
            `conflit` (`path`: the files in conflict, `upstream`: the branch).
        values: The button's values, each a list.

    Returns:
        The prompt, in French.

    Raises:
        ValueError: For an unknown task, or one missing its values.
    """
    one = {name: (found[0] if found else "") for name, found in values.items()}
    paths = ", ".join(f"`{path}`" for path in values.get("path", []))
    if task == "traduire" and one.get("changed") and one.get("other"):
        return (
            f"`{one['changed']}` a changé sans sa version dans l'autre langue, "
            f"`{one['other']}`. Porte-y la même modification (vois `git diff -- "
            f"{one['changed']}`), en suivant les conventions de traduction du "
            "dépôt, puis dis-moi ce que tu as changé. Je committerai les deux "
            "fichiers ensemble depuis studioz."
        )
    if task == "corriger" and one.get("refused"):
        return (
            f"Le dépôt a refusé mon commit de {paths or 'ces fichiers'}. Voici ce "
            f"qu'il a dit :\n\n```\n{one['refused']}\n```\n\nCorrige les fichiers "
            "pour que ses vérifications passent, sans changer ce que dit le "
            "contenu au-delà de ce qu'il faut, puis dis-moi ce que tu as fait. Je "
            "recommencerai le commit depuis studioz."
        )
    if task == "conflit" and paths:
        upstream = one.get("upstream") or "la branche de référence"
        return (
            f"La mise à jour de l'espace sur {upstream} (un rebase) est arrêtée sur "
            f"un conflit dans {paths}. Dans chaque fichier, garde le bon texte des "
            "deux versions (la nôtre et celle qui arrive, souvent les deux "
            "modifications ensemble), retire les marqueurs `<<<<<<<`, `=======` et "
            "`>>>>>>>`, et enregistre. Ne lance aucune commande git qui avance la "
            "mise à jour : je vérifierai et continuerai depuis studioz. Dis-moi "
            "ce que tu as gardé, fichier par fichier."
        )
    msg = f"Demande inconnue ou incomplète : {task}"
    raise ValueError(msg)


def _git(workspace: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    ).stdout


def draft_prompt(workspace: Path, paths: list[str]) -> str:
    """What "Proposer un message" asks: the diff of `paths`, and the style.

    Returns:
        The prompt, with the last commits' subjects as examples.
    """
    # Untracked files have no diff against HEAD: shown whole, as new.
    diff = _git(workspace, "diff", "HEAD", "--", *paths)
    tracked = set(_git(workspace, "ls-files", "--", *paths).splitlines())
    for path in paths:
        if path not in tracked and (workspace / path).is_file():
            text = (workspace / path).read_text(encoding="utf8", errors="replace")
            diff += f"\n--- nouveau fichier {path}\n{text}"
    if len(diff) > _DIFF_LIMIT:
        diff = diff[:_DIFF_LIMIT] + "\n[… coupé]"
    subjects = _git(workspace, "log", "-15", "--format=%s").strip()
    return (
        "Write the commit message for this change: a subject line in the "
        "imperative, under 72 characters, then, only if it helps, a blank line "
        "and a short body saying why. Same language and style as these recent "
        f"subjects of the repository:\n\n{subjects}\n\nThe change:\n\n{diff}\n\n"
        "Answer with the message alone: no quotes, no code block, no trailer."
    )


Query = Callable[[str, ClaudeAgentOptions], AsyncIterator[Any]]


def _sdk_query(text: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
    return query(prompt=text, options=options)


async def draft_message(
    workspace: Path, paths: list[str], ask: Query = _sdk_query
) -> str:
    """A commit message for `paths`, from one exchange with no tool.

    Returns:
        The message, maybe empty.
    """
    env = workspace_environment(workspace, CLAUDE_CODE_DISABLE_AUTO_MEMORY="1")
    env.pop("ANTHROPIC_API_KEY", None)
    options = ClaudeAgentOptions(
        cwd=workspace,
        tools=[],
        setting_sources=[],
        max_turns=1,
        model=_DRAFT_MODEL,
        env=env,
    )
    texts: list[str] = []
    result = ""
    async for message in ask(draft_prompt(workspace, paths), options):
        if isinstance(message, AssistantMessage):
            texts.extend(b.text for b in message.content if isinstance(b, TextBlock))
        elif isinstance(message, ResultMessage) and message.result:
            result = message.result
    return (result or "".join(texts)).strip().strip("`").strip()
