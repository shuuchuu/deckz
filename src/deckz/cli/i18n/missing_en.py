from pathlib import Path

from . import app


@app.command()
def missing_en(
    *,
    all: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Report fr content/titles/variables with no en counterpart.

    Resolves the deck at WORKDIR as deckz would without --en, then reports:

    - FILE <fr_path> <expected_en_path>: fr file with no en/ sibling on disk. \
        Blocks `deckz run --en`.
    - TITLE <status> <yml_path> <field>: title that is a plain string \
        ("untranslated" -- informational only, a plain string is always \
        valid, used as-is in every language, but commonly means "not yet \
        localized"), or a `{fr, en}` map missing its "en" key \
        ("missing-en" -- blocks `deckz run --en`)
    - VARIABLE <status> <variables_yml_path> <key>: same "missing-en" case, \
        for a translation map declared in variables.yml (plain scalars are \
        never flagged)

    Running this lets you audit gaps -- both what would block `deckz run \
    --en` and what's merely unlocalized -- without compiling anything.

    With --json, prints one JSON array of objects instead, each with a \
    "kind" (file/title/variable) and the fields above: "fr_path"/"en_path", \
    or "status", "path" and "field"/"key".

    Args:
        all: Check every deck in the repository instead of just WORKDIR
        json: Print the gaps as JSON
        workdir: Path to move into before running the command

    """
    from ...analyzing.i18n_coverage import missing_en_files, title_gaps, variable_gaps
    from ...configuring.settings import DeckSettings, GlobalSettings
    from ...utils import all_deck_settings

    if all:
        settings_list = list(
            all_deck_settings(GlobalSettings.from_yaml(workdir).paths.git_dir)
        )
    else:
        settings_list = [DeckSettings.from_yaml(workdir)]

    records: list[dict[str, object]] = []
    for settings in settings_list:
        records.extend(
            {"kind": "file", "fr_path": fr_path, "en_path": en_path}
            for fr_path, en_path in missing_en_files(settings)
        )
        records.extend(
            {"kind": "title", "status": status, "path": yml_path, "field": field}
            for yml_path, field, status in title_gaps(settings)
        )
        records.extend(
            {"kind": "variable", "status": status, "path": var_path, "key": key}
            for var_path, key, status in variable_gaps(settings)
        )

    if json:
        from .._presentation import print_json

        print_json(records)
        return
    for record in records:
        if record["kind"] == "file":
            print(f"FILE\t{record['fr_path']}\t{record['en_path']}")
        elif record["kind"] == "title":
            print(f"TITLE\t{record['status']}\t{record['path']}\t{record['field']}")
        else:
            print(f"VARIABLE\t{record['status']}\t{record['path']}\t{record['key']}")
