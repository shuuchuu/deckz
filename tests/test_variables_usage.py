from json import loads
from pathlib import Path

import appdirs
from pygit2 import init_repository
from pytest import CaptureFixture, MonkeyPatch, raises

from deckz.analyzing.variables_usage import check_variables
from deckz.cli import main
from deckz.configuring.settings import GlobalSettings


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")


def _repo(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """A repo with three shared sections and one real deck.

    - "greeting"'s "loud" flavor's body reads `variables.theme` (set by the
      root `variables.yml`, fine) and `variables.typo` (set nowhere --
      undefined).
    - "broken"'s only flavor includes a file that doesn't exist -- a parsing
      failure, reported as structural.
    - "badsyntax" has a fragment with invalid Jinja syntax -- unparsable.
    - the real deck "D" includes a local file reading an undefined
      `variables.missing_local`.

    Returns:
        git_dir.
    """
    git_dir = tmp_path
    init_repository(str(git_dir))
    monkeypatch.setattr(
        appdirs, "user_config_dir", lambda *a, **k: str(tmp_path / "userconfig")
    )

    _write(git_dir / "variables.yml", "theme: dark\n")
    _write(
        git_dir / "templates" / "jinja2" / "env.py",
        "from jinja2 import Environment\n\n\n"
        "def environment_for(suffix: str) -> Environment:\n"
        "    return Environment()\n",
    )

    _write(
        git_dir / "content" / "greeting" / "greeting.yml",
        "flavors:\n"
        "  - name: loud\n    includes:\n      - body\n"
        "  - name: quiet\n    includes:\n      - body_quiet\n",
    )
    _write(
        git_dir / "content" / "greeting" / "body.md",
        "{{ variables.theme }} {{ variables.typo }}\n",
    )
    _write(
        git_dir / "content" / "greeting" / "body_quiet.md",
        "{{ variables.theme }}\n",
    )

    _write(
        git_dir / "content" / "broken" / "broken.yml",
        "flavors:\n  - name: incomplete\n    includes:\n      - body\n      - gone\n",
    )
    _write(git_dir / "content" / "broken" / "body.md", "static\n")

    _write(
        git_dir / "content" / "badsyntax" / "badsyntax.yml",
        "flavors:\n  - name: only\n    includes:\n      - body\n",
    )
    _write(git_dir / "content" / "badsyntax" / "body.md", "{% if %}\n")

    _write(
        git_dir / "company" / "deck.yml",
        "name: D\nparts:\n  - name: p1\n    sections:\n      - local\n",
    )
    _write(
        git_dir / "company" / "content" / "local.md",
        "{{ variables.missing_local }}\n",
    )

    return git_dir


def test_check_variables_reports_all_finding_kinds(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    git_dir = _repo(tmp_path, monkeypatch)
    settings = GlobalSettings.from_yaml(git_dir)

    report = check_variables(settings)

    undefined_names = {(path.name, name) for path, name in report.undefined}
    assert ("body.md", "typo") in undefined_names
    assert ("local.md", "missing_local") in undefined_names
    # "theme" is set by the root variables.yml: never flagged as undefined.
    assert not any(name == "theme" for _, name in undefined_names)

    assert any(path.parent.name == "badsyntax" for path, _ in report.unparsable)

    assert any("broken@incomplete" in context for context, _ in report.structural)


def test_check_variables_clean_repo_has_no_findings(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    git_dir = tmp_path
    init_repository(str(git_dir))
    monkeypatch.setattr(
        appdirs, "user_config_dir", lambda *a, **k: str(tmp_path / "userconfig")
    )
    _write(
        git_dir / "templates" / "jinja2" / "env.py",
        "from jinja2 import Environment\n\n\n"
        "def environment_for(suffix: str) -> Environment:\n"
        "    return Environment()\n",
    )
    _write(
        git_dir / "content" / "about" / "about.yml",
        "flavors:\n  - name: standard\n    includes:\n      - body\n",
    )
    _write(git_dir / "content" / "about" / "body.md", "Hello.\n")

    settings = GlobalSettings.from_yaml(git_dir)
    report = check_variables(settings)

    assert report.undefined == []
    assert report.unparsable == []
    assert report.structural == []


def test_check_variables_json_output(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    git_dir = _repo(tmp_path, monkeypatch)

    with raises(SystemExit) as exc_info:
        main(("check", "variables", "--json", "--workdir", str(git_dir)))

    assert exc_info.value.code == 1
    records = loads(capsys.readouterr().out)
    assert {"undefined", "unparsable", "structural"} == {
        record["kind"] for record in records
    }
    assert {
        "kind": "undefined",
        "lang": "fr",
        "fragment": str(git_dir / "content" / "greeting" / "body.md"),
        "name": "typo",
    } in records


def test_check_variables_skips_flavors_including_deck_local_files(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    git_dir = _repo(tmp_path, monkeypatch)
    # "about@deck" includes a file only the deck has: it can't resolve on its
    # own, and the deck covers it. "about@typo" includes a file nothing has.
    _write(
        git_dir / "content" / "about" / "about.yml",
        "flavors:\n"
        "  - name: deck\n    includes:\n      - intro\n      - description\n"
        "  - name: typo\n    includes:\n      - intro\n      - descriptoin\n",
    )
    _write(git_dir / "content" / "about" / "intro.md", "Hello.\n")
    _write(git_dir / "company" / "content" / "about" / "description.md", "D.\n")

    report = check_variables(GlobalSettings.from_yaml(git_dir))

    contexts = {context for context, _ in report.structural}
    assert "shared:about@deck" not in contexts
    assert "shared:about@typo" in contexts
