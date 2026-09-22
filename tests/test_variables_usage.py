from pathlib import Path

import appdirs
from pygit2 import init_repository
from pytest import MonkeyPatch

from deckz.analyzing.variables_usage import check_variables
from deckz.configuring.settings import GlobalSettings


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")


def _repo(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """A repo with three shared sections and one real deck.

    - "greeting" declares `variables_to_define: [depth, format]`; its "loud"
      flavor's body reads `variables.depth` (declared, fine) and
      `variables.typo` (never declared/set anywhere -- undefined); "format"
      is declared but no fragment under the section, in any flavor, ever
      reads it -- unused.
    - "broken" declares `variables_to_define: [x]`, but its only flavor
      never sets it -- a parsing failure, reported as structural.
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

    _write(
        git_dir / "deckz.yml",
        "build_command:\n  - echo\n",
    )
    _write(git_dir / "variables.yml", "theme: dark\n")
    _write(
        git_dir / "templates" / "jinja2" / "env.py",
        "from jinja2 import Environment\n\n\n"
        "def environment_for(suffix: str) -> Environment:\n"
        "    return Environment()\n",
    )

    _write(
        git_dir / "latex" / "greeting" / "greeting.yml",
        "variables_to_define:\n  - depth\n  - format\nflavors:\n"
        "  - name: loud\n    variables: { depth: shallow, format: bold }\n"
        "    includes:\n      - body\n"
        "  - name: quiet\n    variables: { depth: deep, format: italic }\n"
        "    includes:\n      - body_quiet\n",
    )
    _write(
        git_dir / "latex" / "greeting" / "body.tex",
        "{{ variables.depth }} {{ variables.typo }}\n",
    )
    _write(
        git_dir / "latex" / "greeting" / "body_quiet.tex",
        "{{ variables.depth }}\n",
    )

    _write(
        git_dir / "latex" / "broken" / "broken.yml",
        "variables_to_define:\n  - x\nflavors:\n"
        "  - name: incomplete\n    includes:\n      - body\n",
    )
    _write(git_dir / "latex" / "broken" / "body.tex", "static\n")

    _write(
        git_dir / "latex" / "badsyntax" / "badsyntax.yml",
        "flavors:\n  - name: only\n    includes:\n      - body\n",
    )
    _write(git_dir / "latex" / "badsyntax" / "body.tex", "{% if %}\n")

    _write(
        git_dir / "company" / "deck.yml",
        "name: D\nparts:\n  - name: p1\n    sections:\n      - local\n",
    )
    _write(
        git_dir / "company" / "latex" / "local.tex",
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
    assert ("body.tex", "typo") in undefined_names
    assert ("local.tex", "missing_local") in undefined_names
    # "depth" is declared and set: never flagged as undefined.
    assert not any(name == "depth" for _, name in undefined_names)

    unused_names = {(path.name, name) for path, name in report.unused}
    assert unused_names == {("greeting.yml", "format")}

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
    _write(git_dir / "deckz.yml", "build_command:\n  - echo\n")
    _write(
        git_dir / "templates" / "jinja2" / "env.py",
        "from jinja2 import Environment\n\n\n"
        "def environment_for(suffix: str) -> Environment:\n"
        "    return Environment()\n",
    )
    _write(
        git_dir / "latex" / "about" / "about.yml",
        "flavors:\n  - name: standard\n    includes:\n      - body\n",
    )
    _write(git_dir / "latex" / "about" / "body.tex", "Hello.\n")

    settings = GlobalSettings.from_yaml(git_dir)
    report = check_variables(settings)

    assert report.undefined == []
    assert report.unused == []
    assert report.unparsable == []
    assert report.structural == []
