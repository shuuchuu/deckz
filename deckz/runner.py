from typing import List

from deckz.builder import Builder
from deckz.config import get_config
from deckz.paths import Paths
from deckz.targets import Targets


def run(
    paths: Paths,
    handout: bool,
    presentation: bool,
    verbose_latexmk: bool,
    debug: bool,
    target_whitelist: List[str],
) -> None:
    config = get_config(paths)
    targets = Targets(
        paths=paths, debug=debug, fail_on_missing=True, whitelist=target_whitelist
    )
    builder = Builder(config, paths)
    builder.build_all(
        targets,
        handout=handout,
        presentation=presentation,
        verbose_latexmk=verbose_latexmk,
    )
