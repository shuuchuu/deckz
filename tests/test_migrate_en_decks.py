import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from pygit2 import init_repository
from pytest import fixture, raises
from ruamel.yaml import YAML

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "migrate_en_decks.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrate_en_decks", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


migrate_en_decks = _load_script()

_yaml = YAML()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf8") as fh:
        return _yaml.load(fh)


def _frame(title: str) -> str:
    return f"\\begin{{frame}}{{{title}}}\n  {title}!\n\\end{{frame}}\n"


@fixture
def repo(tmp_path: Path, monkeypatch: Any) -> Path:
    import appdirs

    init_repository(str(tmp_path))
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_path))
    _write(tmp_path / "deckz.yml", 'build_command: ["true"]\n')

    shared = tmp_path / "shared" / "latex"
    _write(
        shared / "i18n-demo" / "i18n-demo.yml",
        "title: Section de démo\n"
        "flavors:\n"
        "  - name: hello\n"
        "    includes:\n"
        "      - hello\n",
    )
    _write(shared / "i18n-demo" / "hello.tex", _frame("Bonjour"))
    _write(
        shared / "i18n-demo" / "en" / "en.yml",
        "title: Demo section\n"
        "flavors:\n"
        "  - name: hello\n"
        "    includes:\n"
        "      - hello\n",
    )
    _write(shared / "i18n-demo" / "en" / "hello.tex", _frame("Hello"))

    deck_dir = tmp_path / "company" / "xyz"
    _write(
        deck_dir / "deck.yml",
        "name: XYZ\n"
        "parts:\n"
        "  - name: p1\n"
        "    title: Partie 1\n"
        "    sections:\n"
        "      - $i18n-demo@hello\n"
        "      - about: A propos\n",
    )
    _write(
        deck_dir / "en" / "deck.yml",
        "name: XYZ\n"
        "parts:\n"
        "  - name: p1\n"
        "    title: Part 1\n"
        "    sections:\n"
        "      - $i18n-demo/en@hello\n"
        "      - en/about: About\n",
    )
    _write(deck_dir / "latex" / "about.tex", _frame("A propos"))
    _write(deck_dir / "en" / "latex" / "about.tex", _frame("About"))
    _write(deck_dir / "variables.yml", "deck_title: Cas Bilingue\n")
    _write(deck_dir / "en" / "variables.yml", "deck_title: Bilingual Case\n")

    # A deck with no en/ counterpart at all: nothing to merge, and its plain
    # title is a valid permanent state -- left untouched, never wrapped.
    fr_only_dir = tmp_path / "company" / "fronly"
    _write(
        fr_only_dir / "deck.yml",
        "name: FRONLY\nparts:\n  - name: p1\n    title: Solo\n    sections:\n"
        "      - $i18n-demo@hello\n",
    )

    return tmp_path


def test_dry_run_reports_no_fatal_and_does_not_write(repo: Path) -> None:
    report = migrate_en_decks.migrate_decks(repo, None, apply=False, git_mv=False)
    migrate_en_decks.migrate_sections(repo / "shared" / "latex", report, apply=False)

    assert not report.fatal
    assert (repo / "company" / "xyz" / "en" / "deck.yml").is_file()
    assert (repo / "shared" / "latex" / "i18n-demo" / "en" / "en.yml").is_file()
    deck_data = _read_yaml(repo / "company" / "xyz" / "deck.yml")
    assert deck_data["parts"][0]["title"] == "Partie 1"


def test_apply_merges_titles_and_cleans_up(repo: Path) -> None:
    report = migrate_en_decks.migrate_decks(repo, None, apply=True, git_mv=False)
    migrate_en_decks.migrate_sections(repo / "shared" / "latex", report, apply=True)

    assert not report.fatal

    deck_path = repo / "company" / "xyz" / "deck.yml"
    deck_data = _read_yaml(deck_path)
    assert deck_data["parts"][0]["title"] == {"fr": "Partie 1", "en": "Part 1"}
    sections = deck_data["parts"][0]["sections"]
    assert sections[0] == "$i18n-demo@hello"
    assert sections[1] == {"about": {"fr": "A propos", "en": "About"}}

    section_path = repo / "shared" / "latex" / "i18n-demo" / "i18n-demo.yml"
    section_data = _read_yaml(section_path)
    assert section_data["title"] == {"fr": "Section de démo", "en": "Demo section"}

    variables_data = _read_yaml(repo / "company" / "xyz" / "variables.yml")
    assert variables_data["deck_title"] == {
        "fr": "Cas Bilingue",
        "en": "Bilingual Case",
    }

    # Cleanup: the old bilingual-tree conventions are all gone.
    assert not (repo / "company" / "xyz" / "en").exists()
    assert not (repo / "shared" / "latex" / "i18n-demo" / "en" / "en.yml").exists()
    # Already-correct shared-section translated body files are untouched.
    assert (repo / "shared" / "latex" / "i18n-demo" / "en" / "hello.tex").is_file()

    # Deck-local file relocated from the old en/latex tree to the new
    # sibling-file convention.
    assert (repo / "company" / "xyz" / "latex" / "en" / "about.tex").is_file()
    assert not (repo / "company" / "xyz" / "en" / "latex").exists()


def test_apply_leaves_untranslated_plain_titles_alone(repo: Path) -> None:
    """No en/ counterpart to merge with -- a plain title stays a plain title."""
    original = (repo / "company" / "fronly" / "deck.yml").read_text(encoding="utf8")

    report = migrate_en_decks.migrate_decks(repo, None, apply=True, git_mv=False)
    migrate_en_decks.migrate_sections(repo / "shared" / "latex", report, apply=True)

    fronly_path = repo / "company" / "fronly" / "deck.yml"
    assert fronly_path not in report.migrated_decks
    assert fronly_path.read_text(encoding="utf8") == original


def test_apply_is_idempotent(repo: Path) -> None:
    report1 = migrate_en_decks.migrate_decks(repo, None, apply=True, git_mv=False)
    migrate_en_decks.migrate_sections(repo / "shared" / "latex", report1, apply=True)
    assert not report1.fatal

    report2 = migrate_en_decks.migrate_decks(repo, None, apply=True, git_mv=False)
    migrate_en_decks.migrate_sections(repo / "shared" / "latex", report2, apply=True)

    assert not report2.fatal
    assert not report2.migrated_decks
    assert not report2.migrated_sections
    assert not report2.moved_files


def test_structural_mismatch_is_fatal_and_untouched(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import appdirs

    init_repository(str(tmp_path))
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_path))
    _write(tmp_path / "deckz.yml", 'build_command: ["true"]\n')
    _write(tmp_path / "shared" / "latex" / ".keep", "")

    deck_dir = tmp_path / "company" / "mismatch"
    _write(
        deck_dir / "deck.yml",
        "name: M\nparts:\n  - name: p1\n    sections:\n      - about\n      - other\n",
    )
    _write(
        deck_dir / "en" / "deck.yml",
        "name: M\nparts:\n  - name: p1\n    sections:\n      - en/about\n",
    )
    original = (deck_dir / "deck.yml").read_text(encoding="utf8")

    report = migrate_en_decks.migrate_decks(tmp_path, None, apply=True, git_mv=False)

    assert len(report.fatal) == 1
    assert (deck_dir / "deck.yml").read_text(encoding="utf8") == original
    assert (deck_dir / "en" / "deck.yml").is_file()


def test_main_exits_nonzero_on_fatal(tmp_path: Path, monkeypatch: Any) -> None:
    import appdirs

    init_repository(str(tmp_path))
    monkeypatch.setattr(appdirs, "user_config_dir", lambda _: str(tmp_path))
    _write(tmp_path / "deckz.yml", 'build_command: ["true"]\n')
    _write(tmp_path / "shared" / "latex" / ".keep", "")

    deck_dir = tmp_path / "company" / "mismatch"
    _write(
        deck_dir / "deck.yml",
        "name: M\nparts:\n  - name: p1\n    sections:\n      - about\n      - other\n",
    )
    _write(
        deck_dir / "en" / "deck.yml",
        "name: M\nparts:\n  - name: p1\n    sections:\n      - en/about\n",
    )

    monkeypatch.setattr(sys, "argv", ["migrate_en_decks.py", str(tmp_path)])
    with raises(SystemExit) as exc_info:
        migrate_en_decks.main()
    assert exc_info.value.code == 1
