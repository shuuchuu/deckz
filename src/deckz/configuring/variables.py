from functools import reduce
from typing import Any

from ..models import Lang, is_lang_map, resolve_lang
from ..utils import dirs_hierarchy, load_all_yamls
from .settings import GlobalSettings


def get_variables(settings: GlobalSettings, lang: Lang = "fr") -> dict[str, Any]:
    merged = reduce(
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
    return {
        key: resolve_lang(value, lang) if is_lang_map(value) else value
        for key, value in merged.items()
    }
