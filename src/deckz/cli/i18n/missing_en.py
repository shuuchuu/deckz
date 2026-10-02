from pathlib import Path

from . import app


@app.command()
def missing_en(
    *,
    all: bool = False,  # ruff: ignore[builtin-argument-shadowing]
    untranslated: bool = False,
    json: bool = False,
    workdir: Path = Path(),
) -> None:
    """Report fr content/titles/variables with no en counterpart.

    Resolves the deck at WORKDIR as deckz would without --en, then reports:

    - `FILE <fr_path> <expected_en_path>`: fr file with no en/ sibling on disk.
        Blocks `deckz run --en`.
    - `TITLE <status> <yml_path> <field>`: title that is a `{fr, en}` map
        missing its "en" key ("missing-en" -- blocks `deckz run --en`),
        or, with --untranslated, a plain string ("untranslated" --
        informational only, a plain string is always valid, used as-is in
        every language, but commonly means "not yet localized")
    - `VARIABLE <status> <variables_yml_path> <key>`: same "missing-en" case,
        for a translation map declared in variables.yml (plain scalars are
        never flagged)

    Running this lets you audit gaps -- what would block `deckz run --en`,
    and with --untranslated what's merely unlocalized -- without compiling
    anything. Exits 1 when a blocking gap (FILE, or "missing-en") is
    reported; "untranslated" titles never fail it.

    With --json, prints one JSON array of objects instead, each with a
    "kind" (file/title/variable) and the fields above: "fr_path"/"en_path",
    or "status", "path" and "field"/"key".

    Args:
        all: Check every deck in the repository instead of just WORKDIR
        untranslated: Also report plain-string titles (informational)
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
            if untranslated or status != "untranslated"
        )
        records.extend(
            {"kind": "variable", "status": status, "path": var_path, "key": key}
            for var_path, key, status in variable_gaps(settings)
        )

    if json:
        from .._presentation import print_json

        print_json(records)
    else:
        for record in records:
            if record["kind"] == "file":
                print(f"FILE\t{record['fr_path']}\t{record['en_path']}")
            elif record["kind"] == "title":
                status, path, field = record["status"], record["path"], record["field"]
                print(f"TITLE\t{status}\t{path}\t{field}")
            else:
                status, path, key = record["status"], record["path"], record["key"]
                print(f"VARIABLE\t{status}\t{path}\t{key}")

    if any(record.get("status") != "untranslated" for record in records):
        from sys import exit as sys_exit

        sys_exit(1)
