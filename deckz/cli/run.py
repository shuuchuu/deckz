from typing import List

from deckz.cli import (
    command,
    compile_type_options,
    deck_path_option,
    target_whitelist_argument,
)
from deckz.paths import Paths
from deckz.runner import run as runner_run


@command
@target_whitelist_argument
@deck_path_option
@compile_type_options(
    default_handout=True, default_presentation=True, default_print=True
)
def run(
    deck_path: str,
    target_whitelist: List[str],
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
) -> None:
    """Compile main targets."""
    paths = Paths(deck_path)
    runner_run(
        paths=paths,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
        target_whitelist=target_whitelist,
    )
