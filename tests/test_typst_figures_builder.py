import logging
import os
from pathlib import Path
from typing import Any

from pytest import LogCaptureFixture, MonkeyPatch, raises

from deckz.components.typst_figures_builder import TypstFiguresAssetsBuilder
from deckz.exceptions import DeckzError
from deckz.stamps import digest
from deckz.utils import copy_file_if_changed

_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>\n'


def _make_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    assets_dir = tmp_path / "assets"
    input_dir = tmp_path / "figures" / "typ"
    output_dir = assets_dir / "typ"
    input_dir.mkdir(parents=True)
    (input_dir / "_svg.typ").write_text("#include sys.inputs.figure\n", encoding="utf8")
    (input_dir / "_lib.typ").write_text("#let unused = 1\n", encoding="utf8")
    (input_dir / "fig.typ").write_text(
        '#import "_lib.typ": unused\nFigure\n', encoding="utf8"
    )
    (input_dir / "fig.yml").write_text("author: Jane\n", encoding="utf8")
    assets_dir.mkdir(parents=True, exist_ok=True)
    return assets_dir, input_dir, output_dir


def _touch_future(path: Path, after_ns: int) -> None:
    future = after_ns + 2_000_000_000
    os.utime(path, ns=(future, future))


def _touch_past(path: Path, than: Path) -> None:
    # Older than `than`: only a content check can see `path` changed.
    past = than.stat().st_mtime_ns - 2_000_000_000
    os.utime(path, ns=(past, past))


def test_build_assets_compiles_one_svg_per_language(tmp_path: Path) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)

    builder.build_assets()

    assert (output_dir / "fig.fr.svg").exists()
    assert (output_dir / "fig.en.svg").exists()
    assert (output_dir / "fig.yml").exists()
    assert (output_dir / "_svg.typ").exists()
    assert (output_dir / "fig.fr.svg.stamp").exists()
    assert not (output_dir / "_lib.fr.svg").exists()


def test_watched_dirs_is_the_input_dir(tmp_path: Path) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)

    assert tuple(builder.watched_dirs()) == (input_dir,)


def test_build_assets_skips_up_to_date_figures(tmp_path: Path) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)
    builder.build_assets()
    before = (output_dir / "fig.fr.svg").stat().st_mtime_ns

    builder.build_assets()

    assert (output_dir / "fig.fr.svg").stat().st_mtime_ns == before


def test_build_assets_rebuilds_on_figure_change(tmp_path: Path) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)
    builder.build_assets()
    before = (output_dir / "fig.fr.svg").read_bytes()
    (input_dir / "fig.typ").write_text("Changed\n", encoding="utf8")
    _touch_past(input_dir / "fig.typ", output_dir / "fig.fr.svg")

    builder.build_assets()

    assert (output_dir / "fig.fr.svg").read_bytes() != before


def test_build_assets_skips_a_figure_only_touched(tmp_path: Path) -> None:
    # A checkout or a copy changes file times, not contents.
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)
    builder.build_assets()
    before = (output_dir / "fig.fr.svg").stat().st_mtime_ns
    _touch_future(input_dir / "fig.typ", before)
    _touch_future(input_dir / "_lib.typ", before)

    builder.build_assets()

    assert (output_dir / "fig.fr.svg").stat().st_mtime_ns == before


def test_build_assets_stamps_an_unstamped_up_to_date_figure(tmp_path: Path) -> None:
    # An SVG built before stamps existed isn't rebuilt if it's newer.
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)
    builder.build_assets()
    stamp = output_dir / "fig.fr.svg.stamp"
    stamp.unlink()
    before = (output_dir / "fig.fr.svg").stat().st_mtime_ns

    builder.build_assets()

    assert (output_dir / "fig.fr.svg").stat().st_mtime_ns == before
    assert stamp.is_file()


def test_build_assets_rebuilds_on_library_change(tmp_path: Path) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)
    builder.build_assets()
    before = (output_dir / "fig.fr.svg").stat().st_mtime_ns
    (input_dir / "_lib.typ").write_text("#let unused = 2\n", encoding="utf8")
    _touch_past(input_dir / "_lib.typ", output_dir / "fig.fr.svg")

    builder.build_assets()

    assert (output_dir / "fig.fr.svg").stat().st_mtime_ns != before


def test_build_assets_skips_a_change_of_a_library_it_does_not_use(
    tmp_path: Path,
) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    (input_dir / "_other.typ").write_text("#let other = 1\n", encoding="utf8")
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)
    builder.build_assets()
    before = (output_dir / "fig.fr.svg").stat().st_mtime_ns
    (input_dir / "_other.typ").write_text("#let other = 2\n", encoding="utf8")

    builder.build_assets()

    assert (output_dir / "fig.fr.svg").stat().st_mtime_ns == before


def test_build_assets_follows_absolute_references(tmp_path: Path) -> None:
    # `/typ/...` is the library's mirror under the Typst root: its source is
    # what counts; `/img/...` is any other asset.
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    (assets_dir / "img").mkdir()
    picture = assets_dir / "img" / "pic.svg"
    picture.write_text(_SVG, encoding="utf8")
    (input_dir / "fig.typ").write_text(
        '#import "/typ/_lib.typ": unused\n#image("/img/pic.svg")\n', encoding="utf8"
    )
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)
    builder.build_assets()

    for changed, text in (
        (input_dir / "_lib.typ", "#let unused = 2\n"),
        (picture, _SVG.replace("1", "2")),
    ):
        before = (output_dir / "fig.fr.svg").stat().st_mtime_ns
        changed.write_text(text, encoding="utf8")
        _touch_past(changed, output_dir / "fig.fr.svg")
        builder.build_assets()
        assert (output_dir / "fig.fr.svg").stat().st_mtime_ns != before, changed


def test_build_assets_rebuilds_on_extra_watched_file_change(tmp_path: Path) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    theme = tmp_path / "theme.typ"
    theme.write_text("", encoding="utf8")
    builder = TypstFiguresAssetsBuilder(
        input_dir, output_dir, assets_dir, extra_watched_files=(theme,)
    )
    builder.build_assets()
    before = (output_dir / "fig.fr.svg").stat().st_mtime_ns
    theme.write_text("// changed\n", encoding="utf8")
    _touch_past(theme, output_dir / "fig.fr.svg")

    builder.build_assets()

    assert (output_dir / "fig.fr.svg").stat().st_mtime_ns != before


def test_build_assets_removes_stale_output(tmp_path: Path) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)
    builder.build_assets()
    assert (output_dir / "fig.fr.svg").exists()

    (input_dir / "fig.typ").unlink()
    (input_dir / "fig.yml").unlink()
    builder.build_assets()

    assert not (output_dir / "fig.fr.svg").exists()
    assert not (output_dir / "fig.fr.svg.stamp").exists()
    assert not (output_dir / "fig.en.svg").exists()
    assert not (output_dir / "fig.yml").exists()


def test_build_assets_raises_on_a_compile_error(tmp_path: Path) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    (input_dir / "fig.typ").write_text("#nonexistent-function()\n", encoding="utf8")
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)

    with raises(DeckzError, match=r"fig\.typ"):
        builder.build_assets()


def _count_compilations(monkeypatch: MonkeyPatch) -> list[str]:
    import typst

    compiled: list[str] = []
    compile_ = typst.compile

    def counting(*args: Any, **kwargs: Any) -> Any:
        compiled.append(kwargs["sys_inputs"]["figure"])
        return compile_(*args, **kwargs)

    monkeypatch.setattr(typst, "compile", counting)
    return compiled


def test_build_assets_leaves_unchanged_figures_and_their_stamps(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)
    builder.build_assets()
    stamp = output_dir / "fig.fr.svg.stamp"
    before = stamp.read_bytes()
    compiled = _count_compilations(monkeypatch)

    builder.build_assets()

    assert compiled == []
    assert stamp.read_bytes() == before
    # The mirrors' bytes in their sources' order: the stamps of SVGs built
    # when stamps digested the sources still match.
    sources = sorted(input_dir / name for name in ("fig.typ", "_lib.typ", "_svg.typ"))
    assert before.decode().strip() == digest(sources, "fr")


def test_a_figure_edited_after_it_was_mirrored_is_compiled_again(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # The edit lands after the mirror was written, before the stamp is
    # computed: the SVG shows the mirror, so must its stamp.
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    figure = input_dir / "fig.typ"
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)

    def copy_then_edit(original: Path, copy: Path) -> bool:
        copied = copy_file_if_changed(original, copy)
        if original == figure:
            figure.write_text("Edited\n", encoding="utf8")
        return copied

    monkeypatch.setattr(
        "deckz.components.typst_figures_builder.copy_file_if_changed", copy_then_edit
    )
    builder.build_assets()
    monkeypatch.undo()
    drawn = (output_dir / "fig.fr.svg").read_bytes()
    compiled = _count_compilations(monkeypatch)

    builder.build_assets()

    assert sorted(compiled) == ["/typ/fig.typ", "/typ/fig.typ"]
    assert (output_dir / "fig.fr.svg").read_bytes() != drawn


def test_a_figure_whose_inputs_change_while_it_compiles_is_compiled_again(
    tmp_path: Path, monkeypatch: MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    import typst

    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    theme = tmp_path / "theme.typ"
    theme.write_text("", encoding="utf8")
    builder = TypstFiguresAssetsBuilder(
        input_dir, output_dir, assets_dir, languages=["fr"], extra_watched_files=[theme]
    )
    compile_ = typst.compile

    def edit_while_compiling(*args: Any, **kwargs: Any) -> Any:
        theme.write_text("// edited\n", encoding="utf8")
        return compile_(*args, **kwargs)

    monkeypatch.setattr(typst, "compile", edit_while_compiling)
    with caplog.at_level(logging.INFO):
        builder.build_assets()
    monkeypatch.undo()

    stamp = output_dir / "fig.fr.svg.stamp"
    assert (output_dir / "fig.fr.svg").is_file()
    assert stamp.read_text(encoding="utf8") == "changed while compiled\n"
    assert "changed while it was compiled" in caplog.text
    compiled = _count_compilations(monkeypatch)
    builder.build_assets()
    assert compiled == ["/typ/fig.typ"]
    assert stamp.read_text(encoding="utf8") != "changed while compiled\n"
