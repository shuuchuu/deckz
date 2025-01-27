from functools import reduce
from typing import Any

from ..utils import dirs_hierarchy, load_all_yamls
from .settings import GlobalSettings


def get_variables(settings: GlobalSettings) -> dict[str, Any]:
    return reduce(
        lambda a, b: {**a, **b},
        load_all_yamls(
            d
            for p in dirs_hierarchy(
                settings.paths.git_dir,
                settings.paths.user_config_dir,
                settings.paths.current_dir,
            )
            if (d := p / "variables.yml").is_file()
        ),
        {},
    )
