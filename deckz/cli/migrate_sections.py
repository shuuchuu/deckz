from logging import getLogger
from subprocess import CalledProcessError, run
from typing import Any, Dict

from yaml import safe_dump, safe_load

from deckz.cli import command
from deckz.exceptions import DeckzException
from deckz.paths import Paths
from deckz.targets import SECTION_YML_VERSION


@command
def migrate_sections() -> None:
    """Find all `section.yml` files and upgrade to newest format."""
    logger = getLogger(__name__)
    git_dir = Paths(".", check_depth=False).git_dir
    section_ymls = git_dir.glob("**/section.yml")

    for section_yml in section_ymls:
        with section_yml.open(encoding="utf8") as fh:
            config = safe_load(fh)
        version = config.get("version", 1)
        if version == SECTION_YML_VERSION:
            continue
        logger.info(
            "Upgrading %s from version %d to %d",
            section_yml,
            version,
            SECTION_YML_VERSION,
        )
        if version < 2:
            config = _v1_v2(config)

        with section_yml.open(encoding="utf8", mode="w") as fh:
            safe_dump(config, fh, allow_unicode=True)

    logger.info("Running prettier on section.yml files")
    try:
        run(
            ["prettier", "--write", "**/section.yml"], check=True, capture_output=True,
        )
    except CalledProcessError as e:
        raise DeckzException(
            "Prettier errored or was not found.\n"
            "Captured stdout\n"
            "---\n"
            "%s\n"
            "Captured stderr\n"
            "---\n%s" % (e.stdout, e.stderr)
        ) from e


def _v1_v2(v1: Dict[str, Any]) -> Dict[str, Any]:
    title = v1["title"]
    includes = [(i if isinstance(i, dict) else {"path": i}) for i in v1["includes"]]
    default_titles = {i["path"]: i["title"] for i in includes if "title" in i}
    flavors = {"standard": [i["path"] for i in includes]}
    return dict(version=2, title=title, default_titles=default_titles, flavors=flavors)
