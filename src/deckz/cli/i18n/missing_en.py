from pathlib import Path

from . import app


@app.command()
def missing_en(
    *,
    all: bool = False,  # ruff: ignore[builtin-argument-shadowing]
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
    --en` and what's merely unlocalized -- without needing a LaTeX toolchain.

    Args:
        all: Check every deck in the repository instead of just WORKDIR
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

    for settings in settings_list:
        for fr_path, en_path in missing_en_files(settings):
            print(f"FILE\t{fr_path}\t{en_path}")
        for yml_path, field, status in title_gaps(settings):
            print(f"TITLE\t{status}\t{yml_path}\t{field}")
        for var_path, key, status in variable_gaps(settings):
            print(f"VARIABLE\t{status}\t{var_path}\t{key}")
