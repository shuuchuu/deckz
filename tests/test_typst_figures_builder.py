import os
from pathlib import Path

from pytest import raises

from deckz.components.typst_figures_builder import TypstFiguresAssetsBuilder
from deckz.exceptions import DeckzError


def _make_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    assets_dir = tmp_path / "assets"
    input_dir = tmp_path / "figures" / "typ"
    output_dir = assets_dir / "typ"
    input_dir.mkdir(parents=True)
    (input_dir / "_svg.typ").write_text("#include sys.inputs.figure\n", encoding="utf8")
    (input_dir / "_lib.typ").write_text("#let unused = 1\n", encoding="utf8")
    (input_dir / "fig.typ").write_text("Figure\n", encoding="utf8")
    (input_dir / "fig.yml").write_text("author: Jane\n", encoding="utf8")
    assets_dir.mkdir(parents=True, exist_ok=True)
    return assets_dir, input_dir, output_dir


def _touch_future(path: Path, after_ns: int) -> None:
    future = after_ns + 2_000_000_000
    os.utime(path, ns=(future, future))


def test_build_assets_compiles_one_svg_per_language(tmp_path: Path) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)

    builder.build_assets()

    assert (output_dir / "fig.fr.svg").exists()
    assert (output_dir / "fig.en.svg").exists()
    assert (output_dir / "fig.yml").exists()
    assert (output_dir / "_svg.typ").exists()
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
    before = (output_dir / "fig.fr.svg").stat().st_mtime_ns
    _touch_future(input_dir / "fig.typ", before)

    builder.build_assets()

    assert (output_dir / "fig.fr.svg").stat().st_mtime_ns > before


def test_build_assets_rebuilds_on_extra_watched_file_change(tmp_path: Path) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    theme = tmp_path / "theme.typ"
    theme.write_text("", encoding="utf8")
    builder = TypstFiguresAssetsBuilder(
        input_dir, output_dir, assets_dir, extra_watched_files=(theme,)
    )
    builder.build_assets()
    before = (output_dir / "fig.fr.svg").stat().st_mtime_ns
    _touch_future(theme, before)

    builder.build_assets()

    assert (output_dir / "fig.fr.svg").stat().st_mtime_ns > before


def test_build_assets_removes_stale_output(tmp_path: Path) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)
    builder.build_assets()
    assert (output_dir / "fig.fr.svg").exists()

    (input_dir / "fig.typ").unlink()
    (input_dir / "fig.yml").unlink()
    builder.build_assets()

    assert not (output_dir / "fig.fr.svg").exists()
    assert not (output_dir / "fig.en.svg").exists()
    assert not (output_dir / "fig.yml").exists()


def test_build_assets_raises_on_a_compile_error(tmp_path: Path) -> None:
    assets_dir, input_dir, output_dir = _make_layout(tmp_path)
    (input_dir / "fig.typ").write_text("#nonexistent-function()\n", encoding="utf8")
    builder = TypstFiguresAssetsBuilder(input_dir, output_dir, assets_dir)

    with raises(DeckzError, match=r"fig\.typ"):
        builder.build_assets()
