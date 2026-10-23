import os
import subprocess
from pathlib import Path

from pytest import LogCaptureFixture, MonkeyPatch, raises

from deckz import stamps
from deckz.stamps import (
    adoptions,
    digest,
    is_fresh,
    python_sources,
    stamp_path,
    write_stamp,
)
from deckz.utils import copy_file_if_changed, write_atomic


def test_write_atomic_failing_midway_leaves_the_old_file_whole(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    output = _write(tmp_path / "fig.svg", "<svg/>")
    write_stamp(output, "old")

    def failing_replace(*_: object) -> None:
        raise OSError

    monkeypatch.setattr(os, "replace", failing_replace)
    for write in (
        lambda: write_atomic(output, b"<svg>new</svg>"),
        lambda: write_stamp(output, "new"),
        lambda: copy_file_if_changed(_write(tmp_path / "new.svg", "new"), output),
    ):
        with raises(OSError):
            write()

    assert output.read_text(encoding="utf8") == "<svg/>"
    assert stamp_path(output).read_text(encoding="utf8") == "old\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "fig.svg",
        "fig.svg.stamp",
        "new.svg",
    ]


def test_write_atomic_replaces_the_file(tmp_path: Path) -> None:
    output = _write(tmp_path / "fig.svg", "<svg/>")

    write_atomic(output, b"<svg>new</svg>")

    assert output.read_bytes() == b"<svg>new</svg>"
    assert [path.name for path in tmp_path.iterdir()] == ["fig.svg"]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf8")
    return path


def _age(path: Path, seconds: int) -> None:
    then = path.stat().st_mtime_ns - seconds * 1_000_000_000
    os.utime(path, ns=(then, then))


def test_digest_depends_on_contents_not_paths(tmp_path: Path) -> None:
    a = _write(tmp_path / "a" / "fig.typ", "Figure")
    b = _write(tmp_path / "b" / "other.typ", "Figure")

    assert digest([a]) == digest([b])
    assert digest([a]) != digest([a], "en")
    assert digest([a, b]) != digest([a])


def test_digest_tells_apart_how_bytes_split_across_inputs(tmp_path: Path) -> None:
    ab = _write(tmp_path / "ab", "ab")
    a = _write(tmp_path / "a", "a")
    b = _write(tmp_path / "b", "b")

    assert digest([ab]) != digest([a, b])


def test_is_fresh_after_write_stamp(tmp_path: Path) -> None:
    source = _write(tmp_path / "fig.typ", "Figure")
    output = _write(tmp_path / "fig.svg", "<svg/>")
    write_stamp(output, digest([source]))
    # Times don't matter once stamped: a checkout makes sources look newer.
    _age(output, 10)

    assert is_fresh(output, digest([source]), [source])


def test_is_fresh_false_on_a_changed_source(tmp_path: Path) -> None:
    source = _write(tmp_path / "fig.typ", "Figure")
    output = _write(tmp_path / "fig.svg", "<svg/>")
    write_stamp(output, digest([source]))
    source.write_text("Changed", encoding="utf8")
    _age(source, 10)

    assert not is_fresh(output, digest([source]), [source])


def test_is_fresh_false_without_the_output(tmp_path: Path) -> None:
    source = _write(tmp_path / "fig.typ", "Figure")
    output = tmp_path / "fig.svg"

    assert not is_fresh(output, digest([source]), [source])


def test_is_fresh_stamps_an_unstamped_output_newer_than_its_inputs(
    tmp_path: Path,
) -> None:
    source = _write(tmp_path / "fig.typ", "Figure")
    output = _write(tmp_path / "fig.svg", "<svg/>")
    _age(source, 10)

    assert is_fresh(output, digest([source]), [source])
    assert stamp_path(output).read_text(encoding="utf8").strip() == digest([source])


def test_is_fresh_false_on_an_unstamped_output_older_than_its_inputs(
    tmp_path: Path,
) -> None:
    source = _write(tmp_path / "fig.typ", "Figure")
    output = _write(tmp_path / "fig.svg", "<svg/>")
    _age(output, 10)

    assert not is_fresh(output, digest([source]), [source])
    assert not is_fresh(output, digest([source]))
    assert not stamp_path(output).exists()


def test_python_sources_follows_repo_imports(tmp_path: Path) -> None:
    root = tmp_path / "figures"
    module = _write(
        root / "plots" / "mpl" / "bar.py",
        "import numpy as np\n"
        "from plots.utils import helper\n"
        "def plot():\n"
        "    from .style import apply\n",
    )
    init = _write(root / "plots" / "__init__.py", "")
    mpl_init = _write(root / "plots" / "mpl" / "__init__.py", "")
    utils = _write(root / "plots" / "utils.py", "from . import data\n")
    data = _write(root / "plots" / "data" / "__init__.py", "")
    style = _write(root / "plots" / "mpl" / "style.py", "")
    _write(root / "plots" / "unused.py", "")

    assert python_sources(module, [root]) == (
        module,
        *sorted([init, mpl_init, utils, data, style]),
    )


def test_python_sources_survives_import_cycles(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.py", "import b\n")
    b = _write(tmp_path / "b.py", "import a\n")

    assert python_sources(a, [tmp_path]) == (a, b)


def _checkouts(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Make a repository with two worktrees beside its main checkout.

    Returns:
        The main checkout, then the worktrees.
    """
    main = tmp_path / "repo"
    _write(main / "README.md", "Repo")
    git = ["git", "-C", str(main)]
    for args in (["init", "--quiet"], ["add", "."], ["commit", "--quiet", "-m", "c"]):
        subprocess.run([*git, *args], check=True)
    for name in ("a", "b"):
        path = tmp_path / f"repo--{name}"
        subprocess.run(
            [*git, "worktree", "add", "--quiet", "-b", f"ws/{name}", str(path)],
            check=True,
        )
    return main, tmp_path / "repo--a", tmp_path / "repo--b"


def _built(checkout: Path, stamp: str, text: str = "video") -> Path:
    output = _write(checkout / "assets" / "videos" / "demo.mp4", text)
    _write(output.with_suffix(".png"), f"poster of {text}")
    write_stamp(output, stamp)
    return output


def test_is_fresh_copies_an_output_fresh_in_another_checkout(tmp_path: Path) -> None:
    main, a, b = _checkouts(tmp_path)
    _built(main, "s1", "main's")
    _built(b, "s2", "b's")
    output = a / "assets" / "videos" / "demo.mp4"
    poster = output.with_suffix(".png")

    assert is_fresh(output, "s2", companions=[poster])
    assert output.read_text(encoding="utf8") == "b's"
    assert poster.read_text(encoding="utf8") == "poster of b's"
    assert stamp_path(output).read_text(encoding="utf8") == "s2\n"
    # From a worktree into the main checkout too, over a stale output.
    assert is_fresh(main / "assets" / "videos" / "demo.mp4", "s2")
    assert (main / "assets" / "videos" / "demo.mp4").read_text(encoding="utf8") == "b's"
    assert not is_fresh(output, "s3")


def test_is_fresh_prefers_the_main_checkout(tmp_path: Path) -> None:
    main, a, b = _checkouts(tmp_path)
    _built(main, "s", "main's")
    _built(b, "s", "b's")
    output = a / "assets" / "videos" / "demo.mp4"

    assert is_fresh(output, "s")
    assert output.read_text(encoding="utf8") == "main's"


def test_is_fresh_skips_a_checkout_lacking_a_companion(tmp_path: Path) -> None:
    main, a, _ = _checkouts(tmp_path)
    built = _built(main, "s")
    built.with_suffix(".png").unlink()
    output = a / "assets" / "videos" / "demo.mp4"

    assert not is_fresh(output, "s", companions=[output.with_suffix(".png")])
    assert not output.exists()
    # Without companions asked for, the output alone is enough.
    assert is_fresh(output, "s")


def test_is_fresh_leaves_unstamped_a_copy_rebuilt_while_copied(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    main, a, _ = _checkouts(tmp_path)
    built = _built(main, "s")
    copy = stamps.copy_file_if_changed

    def rebuilt_meanwhile(original: Path, destination: Path) -> bool:
        write_stamp(built, "rebuilt")
        return copy(original, destination)

    monkeypatch.setattr(stamps, "copy_file_if_changed", rebuilt_meanwhile)
    output = a / "assets" / "videos" / "demo.mp4"

    assert not is_fresh(output, "s")
    assert not stamp_path(output).exists()


def test_is_fresh_outside_a_repository_copies_nothing(tmp_path: Path) -> None:
    assert not is_fresh(tmp_path / "fig.svg", "s")


def test_adoptions_sums_up_the_copies_in_one_line(
    tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    main, a, b = _checkouts(tmp_path)
    for name in ("one", "two"):
        write_stamp(_write(main / "assets" / f"{name}.svg", name), name)
    write_stamp(_write(b / "assets" / "three.svg", "three"), "three")
    caplog.set_level("INFO", logger="deckz.stamps")

    with adoptions():
        for name in ("one", "two", "three"):
            assert is_fresh(a / "assets" / f"{name}.svg", name)

    (line,) = [r.getMessage() for r in caplog.records if r.levelname == "INFO"]
    assert line == (
        "Copied 3 build(s) up to date elsewhere rather than build them: "
        f"2 from {main}, 1 from {b}"
    )
    # Outside, each copy gets its own line.
    caplog.clear()
    (a / "assets" / "one.svg").unlink()
    assert is_fresh(a / "assets" / "one.svg", "one")
    assert [r.getMessage() for r in caplog.records] == [
        f"assets/one.svg: copied from {main}, where it's up to date"
    ]
