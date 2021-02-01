from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

from yaml import dump

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


def run_all(
    directory: Path, build_handout: bool, build_presentation: bool, build_print: bool,
) -> None:
    with TemporaryDirectory(prefix="deckz-run-all-") as tempdir:
        tempdir_path = Path(tempdir)
        paths = Paths.from_tempdir(directory, tempdir_path)
        targets_content = [
            dict(
                name="all",
                title="Compilation de tous les modules partagés",
                sections=[
                    dict(
                        path=str(p.relative_to(paths.shared_latex_dir).with_suffix("")),
                        title=str(p.relative_to(p.parent.parent).with_suffix("")),
                    )
                    for p in paths.shared_latex_dir.glob("**/*.tex")
                ],
            )
        ]
        with paths.targets.open(mode="w", encoding="utf8") as fh:
            dump(targets_content, fh)
        targets = Targets.from_file(paths=paths, whitelist=None)
        config = get_config(paths)
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
