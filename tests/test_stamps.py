import os
from pathlib import Path

from deckz.stamps import digest, is_fresh, python_sources, stamp_path, write_stamp


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
