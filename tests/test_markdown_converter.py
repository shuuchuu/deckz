from pathlib import Path

from deckz.components.markdown_converter import PandocConverter


def test_convert_writes_to_a_destination_in_another_directory(tmp_path: Path) -> None:
    source_dir = tmp_path / "content"
    source_dir.mkdir()
    source = source_dir / "topic.md"
    source.write_text("# Topic\n\nHello.\n", encoding="utf8")
    destination = tmp_path / "elsewhere" / "topic.md"
    destination.parent.mkdir()

    PandocConverter(("pandoc", "-t", "typst")).convert(source, destination)

    # The source isn't overwritten by an output of the same name, and
    # nothing else lands next to it.
    assert source.read_text(encoding="utf8") == "# Topic\n\nHello.\n"
    assert sorted(p.name for p in source_dir.iterdir()) == ["topic.md"]
    assert "Hello." in destination.read_text(encoding="utf8")


def test_convert_reads_relative_resources_from_the_source_directory(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "content"
    source_dir.mkdir()
    (source_dir / "part.md").write_text("Included.\n", encoding="utf8")
    source = source_dir / "topic.md"
    source.write_text("Main.\n", encoding="utf8")
    destination = tmp_path / "out.typ"

    # `part.md` is relative: pandoc finds it because it runs from the
    # source's directory, while the output still goes to `destination`.
    PandocConverter(("pandoc", "part.md", "-t", "typst")).convert(source, destination)

    text = destination.read_text(encoding="utf8")
    assert "Included." in text
    assert "Main." in text
