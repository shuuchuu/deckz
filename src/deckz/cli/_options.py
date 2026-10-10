"""Options shared by several commands."""

from collections.abc import Iterable, Mapping
from os import environ
from types import MappingProxyType
from typing import Annotated

from cyclopts import Parameter

from ..models import Lang

Langs = Annotated[
    tuple[Lang, ...],
    Parameter(
        name="--lang",
        env_var="DECKZ_LANG",
        consume_multiple=True,
        negative="",
        show_default=lambda langs: " ".join(langs),
    ),
]
"""Languages to process in one pass: `--lang fr en`, or `--lang fr --lang en`.

Defaults to `DECKZ_LANG` (space-separated, e.g. `DECKZ_LANG="fr en"`, which a \
`.env` file can set) when the option isn't given. Commands that show a single \
resolved view take a plain `lang: Lang` instead, which ignores `DECKZ_LANG`.
"""


def unique(langs: Iterable[Lang]) -> tuple[Lang, ...]:
    """`langs` without repeats, in order.

    Returns:
        Each language once.
    """
    return tuple(dict.fromkeys(langs))


class _Invocation:
    """What `main` knows of the command line and `.env`, for `environment_defaults`."""

    tokens: tuple[str, ...] = ()
    """The command-line arguments."""
    from_dotenv: Mapping[str, str] = MappingProxyType({})
    """Environment variables set by a `.env` file, not by the environment: \
    the file each came from, as shown to the user."""


invocation = _Invocation()


def environment_defaults(variables: Iterable[str]) -> list[str]:
    """The `variables` that set an option's value in this invocation.

    A variable counts when it's set and its option isn't given on the \
    command line (`DECKZ_LANG` is `--lang`, `DECKZ_RUN_PART_HANDOUTS` is \
    `--part-handouts`/`--no-part-handouts`).

    Returns:
        One `NAME=value (source)` per such variable, the source being \
        `.env` or `environment`.
    """
    given = {token.split("=", 1)[0] for token in invocation.tokens}
    defaults = []
    for name in variables:
        if name not in environ:
            continue
        option = (
            "lang"
            if name == "DECKZ_LANG"
            else name.removeprefix("DECKZ_RUN_").lower().replace("_", "-")
        )
        if {f"--{option}", f"--no-{option}"} & given:
            continue
        source = invocation.from_dotenv.get(name, "environment")
        defaults.append(f"{name}={environ[name]} ({source})")
    return defaults
