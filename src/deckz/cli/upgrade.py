from pathlib import Path

from . import app


# ruff: noqa: C901
@app.command()
def upgrade(*, workdir: Path = Path()) -> None:
    """Transform a deckz repo to match the new conventions.

    Args:
        workdir: Path to move into before running the command.

    Raises:
        ValueError: When the format to handle in modified files is non-conform to \
            expectations.

    """
    from itertools import chain
    from shutil import move, rmtree
    from sys import stderr
    from typing import cast

    from rich.console import Console
    from yaml import safe_dump

    from ..configuring.settings import DeckSettings, GlobalSettings
    from ..utils import load_yaml

    console = Console(file=stderr)
    old_settings = Path("settings.yml")
    if old_settings.exists():
        move(old_settings, "deckz.yml")

    settings = GlobalSettings.from_yaml(workdir)

    console.print("Deleting templates")
    yml_templates_dir = settings.paths.templates_dir / "yml"
    if yml_templates_dir.is_dir():
        rmtree(yml_templates_dir)
        console.print(
            "  :white_check_mark: Removed "
            f"{yml_templates_dir.relative_to(settings.paths.git_dir)} "
        )

    console.print("Renaming files (config -> variables, targets -> deck)")

    decks_settings = [
        DeckSettings.from_yaml(path.parent)
        for path in settings.paths.git_dir.rglob("targets.yml")
    ]
    for deck_settings in decks_settings:
        for path, old_name in (
            (deck_settings.paths.deck_definition, "targets.yml"),
            (deck_settings.paths.global_variables, "global-config.yml"),
            (deck_settings.paths.user_variables, "user-config.yml"),
            (deck_settings.paths.company_variables, "company-config.yml"),
            (deck_settings.paths.deck_variables, "deck-config.yml"),
            (deck_settings.paths.session_variables, "session-config.yml"),
        ):
            old_path = path.parent / old_name
            if old_path.exists():
                move(old_path, path)
                console.print(
                    "  :white_check_mark:"
                    f"{old_path}\n"
                    f"  → [link=file://{path}]{path}[/link]"
                )

    console.print("Changing decks format and transfer deck name inside deck definition")

    UNSET = cast(str, object())  # noqa: N806

    def normalize_part_content(
        v: str | dict[str, str],
    ) -> tuple[str, str | None, str | None]:
        title = UNSET
        flavor = None
        if isinstance(v, str):
            path = v
        elif isinstance(v, dict) and "path" not in v:
            assert len(v) == 1
            path, flavor = next(iter(v.items()))
        else:
            path, flavor, title = v["path"], v.get("flavor"), v.get("title", UNSET)
        return path, title, flavor

    decks_settings = [
        DeckSettings.from_yaml(path.parent)
        for path in settings.paths.git_dir.rglob("deck.yml")
    ]
    for deck_settings in decks_settings:
        variables = load_yaml(deck_settings.paths.deck_variables)
        try:
            deck_name = variables["deck_acronym"]
        except KeyError as e:
            msg = f"{deck_settings.paths.deck_variables} does not contain deck_acronym"
            raise ValueError(msg) from e
        del variables["deck_acronym"]
        with deck_settings.paths.deck_variables.open("w", encoding="utf8") as fh:
            safe_dump(
                variables, fh, encoding="utf8", allow_unicode=True, sort_keys=False
            )
        deck_definition = deck_settings.paths.deck_definition
        content = load_yaml(deck_definition)
        for part in content:
            new_sections: list[dict[str, str | None] | str] = []
            for item in part["sections"]:
                path_str, title, flavor = normalize_part_content(item)
                if flavor is None:
                    if title is UNSET:
                        new_sections.append(path_str)
                    else:
                        new_sections.append({path_str: title})
                else:
                    key = f"${path_str}@{flavor}"
                    if title is UNSET:
                        new_sections.append(key)
                    else:
                        new_sections.append({key: title})
            part["sections"] = new_sections
        with deck_definition.open("w", encoding="utf8") as fh:
            new_content = {"name": deck_name, "parts": content}
            safe_dump(
                new_content,
                fh,
                allow_unicode=True,
                encoding="utf8",
                sort_keys=False,
            )
        console.print(
            f"  :white_check_mark: [link=file://{deck_definition}]"
            f"{deck_definition.relative_to(settings.paths.git_dir)}"
            "[/link]"
        )

    console.print("Changing sections format to allow title definition in each flavor")

    def normalize_section_content(
        v: str | dict[str, str],
    ) -> tuple[str, str | None, str | None]:
        title = UNSET
        flavor = None
        if isinstance(v, str):
            path = v
        else:
            assert len(v) == 1
            left, right = next(iter(v.items()))
            if left.startswith("$"):
                path = left[1:]
                flavor = right
            else:
                path = left
                title = right
        return path, title, flavor

    for section_file in chain(
        settings.paths.shared_latex_dir.rglob("*.yml"),
        (
            p
            for deck_settings in decks_settings
            for p in deck_settings.paths.local_latex_dir.rglob("*.yml")
        ),
    ):
        content = load_yaml(section_file)
        if (
            not isinstance(content, dict)
            or "flavors" not in content
            or "title" not in content
        ):
            continue
        if "version" in content:
            del content["version"]
        new_flavors = []
        for flavor_name, includes in content["flavors"].items():
            new_includes = []
            for include in includes:
                path_str, title, flavor = normalize_section_content(include)
                left = path_str if flavor is None else f"${path_str}@{flavor}"
                new_includes.append(left if title is UNSET else {left: title})
            new_flavors.append({"name": flavor_name, "includes": new_includes})
        content["flavors"] = new_flavors
        if "default_titles" in content and not content["default_titles"]:
            del content["default_titles"]
        with section_file.open("w", encoding="utf8") as fh:
            safe_dump(content, fh, allow_unicode=True, encoding="utf8", sort_keys=False)
        console.print(
            f"  :white_check_mark: [link=file://{section_file}]"
            f"{section_file.relative_to(settings.paths.git_dir)}"
            "[/link]"
        )
