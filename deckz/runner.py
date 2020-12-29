from typing import List, Optional

from deckz.builder import Builder
from deckz.config import get_config
from deckz.paths import Paths
from deckz.settings import Settings
from deckz.targets import Targets


def run(
    paths: Paths,
    build_handout: bool,
    build_presentation: bool,
    build_print: bool,
    target_whitelist: Optional[List[str]] = None,
) -> None:
    config = get_config(paths)
    targets = Targets.from_file(paths=paths, whitelist=target_whitelist)
    settings = Settings(paths)
    Builder(
        config,
        settings,
        paths,
        targets,
        build_handout=build_handout,
        build_presentation=build_presentation,
        build_print=build_print,
    )
