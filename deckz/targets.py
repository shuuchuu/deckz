from logging import getLogger
from sys import exit
from typing import Any, Dict, List, NamedTuple

from yaml import safe_load as yaml_safe_load

from deckz.paths import Paths


_logger = getLogger(__name__)


class Section(NamedTuple):
    title: str
    includes: List[str]

    @staticmethod
    def from_dict(input_dict: Dict[str, Any]) -> "Section":
        return Section(**input_dict)


class Target(NamedTuple):
    name: str
    title: str
    sections: List[Section]

    @staticmethod
    def from_dict(input_dict: Dict[str, Any]) -> "Target":
        return Target(
            name=input_dict["name"],
            title=input_dict["title"],
            sections=[Section.from_dict(section) for section in input_dict["sections"]],
        )


def get_targets(
    debug: bool, paths: Paths, fail_on_missing: bool, whitelist: List[str],
) -> List[Target]:
    targets = paths.targets_debug if debug else paths.targets
    if not targets.exists():
        if fail_on_missing:
            _logger.critical(f"Could not find {targets}.")
            exit(1)
        else:
            return []
    with targets.open("r", encoding="utf8") as fh:
        return [
            Target.from_dict(target)
            for target in yaml_safe_load(fh)
            if not whitelist or target["name"] in whitelist
        ]
