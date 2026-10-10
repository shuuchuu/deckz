import subprocess
from pathlib import Path
from pathlib import PurePosixPath as P

from pytest import raises

from deckz.analyzing.i18n_stale import OneSidedChange, one_sided, stale_files
from deckz.configuring.settings import GlobalPaths, GlobalSettings, I18nSettings
from deckz.exceptions import InvalidConfigurationError


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(cwd),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _init(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--quiet", "-b", "main", str(tmp_path))
    return tmp_path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _commit(repo: Path, subject: str, *, trailer: str | None = None) -> None:
    _git(repo, "add", "-A")
    args = ["commit", "-m", subject]
    if trailer:
        args += ["-m", trailer]
    _git(repo, *args)


def _settings(git_dir: Path) -> GlobalSettings:
    return GlobalSettings(paths=GlobalPaths(current_dir=git_dir, git_dir=git_dir))


def test_stale_reports_fr_only_commit_with_no_trailer(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "content" / "topic" / "topic.md", "fr v1")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en v1")
    _commit(repo, "Add topic")
    _write(repo / "content" / "topic" / "topic.md", "fr v2")
    _commit(repo, "Update fr")

    findings = stale_files(_settings(repo))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.path == P("content/topic/topic.md")
    assert finding.sibling == P("content/topic/en/topic.md")
    assert [c.subject for c in finding.commits] == ["Update fr"]


def test_fr_only_trailer_exempts_the_commit(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "content" / "topic" / "topic.md", "fr v1")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en v1")
    _commit(repo, "Add topic")
    _write(repo / "content" / "topic" / "topic.md", "fr v2 (typo fix)")
    _commit(repo, "Fix typo", trailer="Lang-sync: fr-only (typo)")

    assert stale_files(_settings(repo)) == []


def test_pending_trailer_still_counts_as_stale(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "content" / "topic" / "topic.md", "fr v1")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en v1")
    _commit(repo, "Add topic")
    _write(repo / "content" / "topic" / "topic.md", "fr v2")
    _commit(repo, "Update fr", trailer="Lang-sync: pending")

    findings = stale_files(_settings(repo))

    assert len(findings) == 1
    assert [c.subject for c in findings[0].commits] == ["Update fr"]


def test_touching_the_sibling_resets_the_baseline(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "content" / "topic" / "topic.md", "fr v1")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en v1")
    _commit(repo, "Add topic")
    _write(repo / "content" / "topic" / "topic.md", "fr v2")
    _commit(repo, "Update fr", trailer="Lang-sync: pending")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en v2")
    _commit(repo, "Update en")

    findings = stale_files(_settings(repo))

    # fr's own pending change is now ported (en was touched after it); the en
    # update itself is a new, not-yet-exempted one-sided change.
    assert len(findings) == 1
    assert findings[0].path == P("content/topic/en/topic.md")
    assert [c.subject for c in findings[0].commits] == ["Update en"]


def test_synced_commit_touching_both_sides_is_never_stale(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "content" / "topic" / "topic.md", "fr v1")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en v1")
    _commit(repo, "Add topic")
    _write(repo / "content" / "topic" / "topic.md", "fr v2")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en v2")
    _commit(repo, "Update both")

    assert stale_files(_settings(repo)) == []


def test_yml_files_are_ignored(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "content" / "topic" / "topic.md", "fr v1")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en v1")
    _commit(repo, "Add topic")
    _write(repo / "content" / "topic" / "topic.yml", "title: {fr: Topic, en: Topic}")
    _commit(repo, "Add title yml")

    assert stale_files(_settings(repo)) == []


def test_notebook_pairs_are_tracked(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "labs" / "notebooks" / "topic" / "demo-fr.ipynb", "{}")
    _write(repo / "labs" / "notebooks" / "topic" / "demo-en.ipynb", "{}")
    _commit(repo, "Add demo notebooks")
    _write(repo / "labs" / "notebooks" / "topic" / "demo-fr.ipynb", '{"x": 1}')
    _commit(repo, "Update fr notebook")

    findings = stale_files(_settings(repo))

    assert len(findings) == 1
    assert findings[0].path == P("labs/notebooks/topic/demo-fr.ipynb")


def test_targets_restrict_the_report(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "content" / "a" / "a.md", "fr v1")
    _write(repo / "content" / "a" / "en" / "a.md", "en v1")
    _write(repo / "content" / "b" / "b.md", "fr v1")
    _write(repo / "content" / "b" / "en" / "b.md", "en v1")
    _commit(repo, "Add a and b")
    _write(repo / "content" / "a" / "a.md", "fr v2")
    _write(repo / "content" / "b" / "b.md", "fr v2")
    _commit(repo, "Update both a and b")

    findings = stale_files(_settings(repo), [repo / "content" / "a"])

    assert len(findings) == 1
    assert findings[0].path == P("content/a/a.md")


def test_no_sibling_ever_touched_reports_since_none(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "content" / "topic" / "topic.md", "fr v1")
    _commit(repo, "Add fr only, no en ever")

    findings = stale_files(_settings(repo))

    assert len(findings) == 1
    assert findings[0].since is None


def _synced_settings(git_dir: Path, synced_at: str) -> GlobalSettings:
    return _settings(git_dir).model_copy(
        update={"i18n": I18nSettings(synced_at=synced_at)}
    )


def test_synced_at_ignores_it_and_its_ancestors(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "content" / "topic" / "topic.md", "fr v1")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en v1")
    _commit(repo, "Add topic")
    _write(repo / "content" / "topic" / "topic.md", "fr v2")
    _commit(repo, "Update fr, settled before trailers")
    synced = _git(repo, "rev-parse", "HEAD").strip()

    assert stale_files(_synced_settings(repo, synced)) == []

    _write(repo / "content" / "topic" / "topic.md", "fr v3")
    _commit(repo, "Update fr again")

    findings = stale_files(_synced_settings(repo, synced))
    assert [c.subject for f in findings for c in f.commits] == ["Update fr again"]
    assert findings[0].since == synced


def test_synced_at_must_name_a_commit(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _write(repo / "content" / "topic" / "topic.md", "fr v1")
    _write(repo / "content" / "topic" / "en" / "topic.md", "en v1")
    _commit(repo, "Add topic")

    with raises(InvalidConfigurationError):
        stale_files(_synced_settings(repo, "no-such-revision"))


def test_one_sided_pairs() -> None:
    pairs = [(P("c/a.md"), P("c/en/a.md")), (P("c/b.md"), P("c/en/b.md"))]

    assert one_sided({"c/a.md", "c/en/a.md", "c/en/b.md", "x.py"}, pairs) == [
        OneSidedChange(P("c/b.md"), P("c/en/b.md"), "en")
    ]
    found = one_sided({"c/a.md"}, pairs)
    assert [(c.changed_path, c.other_path) for c in found] == [
        (P("c/a.md"), P("c/en/a.md"))
    ]
