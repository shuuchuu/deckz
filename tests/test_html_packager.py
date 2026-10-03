"""HtmlPackager: the page plus every local file it references, nothing else."""

from pathlib import Path

from deckz.components.html_packager import HtmlPackager


def _build_dir(tmp_path: Path, page: str) -> Path:
    # A build dir with its assets linked in, like the deck builder's.
    assets = tmp_path / "assets"
    for name, content in {
        "img/logo.png": "png",
        "img/unused.png": "png",
        "videos/intro.mp4": "mp4",
        "videos/intro.png": "poster",
        "web/theme.css": "@import 'extra.css'; body { background: url(bg.png) }",
        "web/extra.css": "@font-face { src: url('../fonts/Fira Sans.ttf') }",
        "web/bg.png": "png",
        "web/vendor/plugin.js": "js",
        "fonts/Fira Sans.ttf": "ttf",
    }.items():
        path = assets / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf8")
    build_dir = tmp_path / "build" / "deck-html"
    build_dir.mkdir(parents=True)
    for directory in assets.iterdir():
        (build_dir / directory.name).symlink_to(directory)
    (build_dir / "deck-html.html").write_text(page, encoding="utf8")
    return build_dir


def _site(build_dir: Path) -> set[str]:
    site = build_dir / "deck-html.site"
    return {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}


def test_copies_the_page_and_what_it_references(tmp_path: Path) -> None:
    build_dir = _build_dir(
        tmp_path,
        '<link rel="stylesheet" href="web/theme.css">'
        '<img src="img/logo.png">'
        '<video data-src="videos/intro.mp4" poster="videos/intro.png"></video>'
        '<a href="https://example.com">x</a><a href="#/2">y</a>'
        '<img src="data:image/png;base64,AAAA">',
    )

    result = HtmlPackager().compile(build_dir / "deck-html.html")

    assert result.ok, result.diagnostics
    assert _site(build_dir) == {
        "index.html",
        "img/logo.png",
        "videos/intro.mp4",
        "videos/intro.png",
        "web/theme.css",
        "web/extra.css",
        "web/bg.png",
        "fonts/Fira Sans.ttf",
    }


def test_static_dirs_are_copied_whole(tmp_path: Path) -> None:
    build_dir = _build_dir(tmp_path, '<script src="web/vendor/plugin.js"></script>')

    result = HtmlPackager(static_dirs=("web",)).compile(build_dir / "deck-html.html")

    assert result.ok, result.diagnostics
    # And the stylesheets it holds are still scanned for their own references.
    assert _site(build_dir) == {
        "index.html",
        "web/theme.css",
        "web/extra.css",
        "web/bg.png",
        "web/vendor/plugin.js",
        "fonts/Fira Sans.ttf",
    }


def test_style_attributes_and_blocks_are_scanned(tmp_path: Path) -> None:
    build_dir = _build_dir(
        tmp_path,
        "<style>.a { background: url(img/logo.png) }</style>"
        '<section data-background-image="videos/intro.png"></section>',
    )

    result = HtmlPackager().compile(build_dir / "deck-html.html")

    assert result.ok, result.diagnostics
    assert _site(build_dir) == {"index.html", "img/logo.png", "videos/intro.png"}


def test_unresolvable_references_fail_without_packaging(tmp_path: Path) -> None:
    build_dir = _build_dir(
        tmp_path,
        '<img src="img/missing.png"><img src="/img/logo.png">'
        '<img src="../outside.png">',
    )

    result = HtmlPackager(static_dirs=("nope",)).compile(build_dir / "deck-html.html")

    assert not result.ok
    assert "'img/missing.png' not found" in result.diagnostics
    assert "root-absolute" in result.diagnostics
    assert "outside the build directory" in result.diagnostics
    assert "static directory 'nope'" in result.diagnostics
    assert not (build_dir / "deck-html.site").exists()
