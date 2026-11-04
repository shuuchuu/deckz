"""What a fragment's rendering read: the module, and through a real render."""

from concurrent.futures import ThreadPoolExecutor
from json import dumps
from os import utime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pytest import MonkeyPatch, mark

from deckz import render_inputs
from deckz.components.assets_metadata_retriever import AssetsMetadataRetriever
from deckz.components.deck_builder import CopiedDependency, render_dependencies
from deckz.components.renderer import Renderer
from deckz.render_inputs import (
    Input,
    depends_on,
    depends_on_json,
    depends_on_presence,
    file_digest,
    inputs_changed,
    recording,
    write_record,
)

if TYPE_CHECKING:
    from deckz.components.protocols import (
        GlobalFactoryProtocol,
        MarkdownConverterProtocol,
    )


def _recorded(record: Path, *paths: Path) -> None:
    with recording() as inputs:
        depends_on(*paths)
    write_record(record, inputs)


def test_depends_on_does_nothing_outside_a_render(tmp_path: Path) -> None:
    depends_on(tmp_path / "anything")

    with recording() as inputs:
        pass

    assert inputs == {}


def test_recording_keeps_the_first_digest_of_a_file(tmp_path: Path) -> None:
    # What the render read is the first version it declared.
    path = tmp_path / "input"
    path.write_text("before", encoding="utf8")
    before = file_digest(path)

    with recording() as inputs:
        depends_on(path)
        path.write_text("edited", encoding="utf8")
        depends_on(path)

    assert inputs == {path: before}


def test_each_thread_records_its_own_render(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"

    def render(path: Path) -> set[Input]:
        with recording() as inputs:
            depends_on(path)
        return set(inputs)

    with recording() as outer, ThreadPoolExecutor(2) as pool:
        assert list(pool.map(render, [first, second])) == [{first}, {second}]

    assert outer == {}


def test_inputs_changed_with_the_bytes_of_a_file(tmp_path: Path) -> None:
    record, path = tmp_path / "record", tmp_path / "input"
    path.write_text("before", encoding="utf8")
    _recorded(record, path)
    assert not inputs_changed(record)

    path.write_text("edited", encoding="utf8")

    assert inputs_changed(record)


def test_a_new_time_on_the_same_bytes_changes_nothing(tmp_path: Path) -> None:
    # A git checkout or a copy into a worktree changes times, not contents.
    record, path = tmp_path / "record", tmp_path / "input"
    path.write_text("same", encoding="utf8")
    _recorded(record, path)

    utime(path, (1, 1))

    assert not inputs_changed(record)


def test_a_directory_counts_as_no_file(tmp_path: Path) -> None:
    assert file_digest(tmp_path) is None


def test_a_file_appearing_or_going_away_is_a_change(tmp_path: Path) -> None:
    record, path = tmp_path / "record", tmp_path / "input"
    _recorded(record, path)
    assert not inputs_changed(record)

    path.write_text("now there", encoding="utf8")
    assert inputs_changed(record)

    _recorded(record, path)
    path.unlink()
    assert inputs_changed(record)


@mark.parametrize("content", [None, b"{trunc", b"[]", b"\xff"])
def test_a_record_unusable_tells_nothing(tmp_path: Path, content: bytes | None) -> None:
    record = tmp_path / "record"
    if content is not None:
        record.write_bytes(content)

    assert inputs_changed(record)


def test_a_record_with_no_input_is_up_to_date(tmp_path: Path) -> None:
    record = tmp_path / "record"
    write_record(record, {})

    assert not inputs_changed(record)


def test_a_record_follows_its_checkout(tmp_path: Path) -> None:
    # `deckz.render_inputs` keeps paths relative to the record, for a build
    # directory copied or moved along with its checkout.
    checkout = tmp_path / "checkout"
    build = checkout / ".build" / "deck"
    build.mkdir(parents=True)
    path = checkout / "input"
    path.write_text("before", encoding="utf8")
    _recorded(build / "record", path)

    moved = tmp_path / "moved"
    checkout.rename(moved)

    assert not inputs_changed(moved / ".build" / "deck" / "record")
    (moved / "input").write_text("edited", encoding="utf8")
    assert inputs_changed(moved / ".build" / "deck" / "record")


def test_an_unchanged_file_is_read_once_per_process(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # What keeps a `--watch` rebuild at a `stat` per input.
    record, path = tmp_path / "record", tmp_path / "input"
    path.write_text("a large notebook", encoding="utf8")
    utime(path, (1, 1))
    _recorded(record, path)
    digested: list[Path] = []
    digest = render_inputs.digest

    def counted(paths: list[Path]) -> str:
        digested.extend(paths)
        return digest(paths)

    monkeypatch.setattr(render_inputs, "digest", counted)

    assert not inputs_changed(record)
    assert not inputs_changed(record)
    assert digested == []

    path.write_text("a larger notebook", encoding="utf8")
    utime(path, (2, 2))
    assert inputs_changed(record)
    assert inputs_changed(record)
    assert digested == [path]


def test_a_record_is_read_once_per_process_until_it_changes(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # A `stat` stands for reading and parsing it, on a `--watch` rebuild.
    record, path = tmp_path / "record", tmp_path / "input"
    path.write_text("before", encoding="utf8")
    _recorded(record, path)
    utime(record, (1, 1))
    read: list[str] = []
    read_record = render_inputs._read_record

    def counted(name: str) -> list[tuple[str, str | None]]:
        read.append(name)
        return read_record(name)

    monkeypatch.setattr(render_inputs, "_read_record", counted)

    assert not inputs_changed(record)
    assert not inputs_changed(record)
    assert read == [str(record)]

    path.write_text("edited", encoding="utf8")
    assert inputs_changed(record)
    _recorded(record, path)
    assert not inputs_changed(record)


def test_a_record_just_rewritten_is_read_every_time(tmp_path: Path) -> None:
    # A new digest has the size of the old one: a rewrite in the same tick of
    # the clock leaves time and size as they were, so only the content tells.
    record, path = tmp_path / "record", tmp_path / "input"
    path.write_text("before", encoding="utf8")
    _recorded(record, path)
    status = record.stat()
    assert not inputs_changed(record)

    path.write_text("edited", encoding="utf8")
    _recorded(record, path)
    utime(record, ns=(status.st_atime_ns, status.st_mtime_ns))

    assert not inputs_changed(record)


def test_a_file_just_written_is_digested_every_time(tmp_path: Path) -> None:
    # Two edits of one size in the same tick of the clock: time and size are
    # the same, so only the bytes tell.
    path = tmp_path / "input"
    path.write_text("before", encoding="utf8")
    status = path.stat()
    before = file_digest(path)

    path.write_text("edited", encoding="utf8")
    utime(path, ns=(status.st_atime_ns, status.st_mtime_ns))

    assert file_digest(path) != before


def _notebook(path: Path, metadata: object, outputs: object) -> None:
    content = {"metadata": metadata, "cells": [{"outputs": outputs}]}
    path.write_text(dumps(content), encoding="utf8")


def _recorded_metadata(record: Path, path: Path) -> None:
    with recording() as inputs:
        depends_on_json(path, "metadata")
    write_record(record, inputs)


def test_a_json_value_ignores_the_rest_of_the_file(tmp_path: Path) -> None:
    # A notebook's outputs written back, for what only reads its metadata.
    record, path = tmp_path / "record", tmp_path / "notebook"
    _notebook(path, {"id": "a"}, [])
    _recorded_metadata(record, path)

    _notebook(path, {"id": "a"}, ["a long output"])

    assert not inputs_changed(record)


def test_a_json_value_changing_is_a_change(tmp_path: Path) -> None:
    record, path = tmp_path / "record", tmp_path / "notebook"
    _notebook(path, {"gpu": True}, [])
    _recorded_metadata(record, path)

    _notebook(path, {"gpu": False}, [])

    assert inputs_changed(record)


def test_a_json_value_doesnt_count_its_keys_order(tmp_path: Path) -> None:
    record, path = tmp_path / "record", tmp_path / "notebook"
    _notebook(path, {"a": 1, "b": 2}, [])
    _recorded_metadata(record, path)

    _notebook(path, {"b": 2, "a": 1}, [])

    assert not inputs_changed(record)


def test_a_nested_json_value_and_a_missing_key(tmp_path: Path) -> None:
    record, path = tmp_path / "record", tmp_path / "notebook"
    _notebook(path, {"colab": {}}, [])
    with recording() as inputs:
        depends_on_json(path, "metadata", "colab", "gpuType")
    write_record(record, inputs)

    _notebook(path, {"colab": {"name": "other"}}, [])
    assert not inputs_changed(record)

    _notebook(path, {"colab": {"gpuType": "T4"}}, [])
    assert inputs_changed(record)


def test_a_json_file_appearing_or_going_away_is_a_change(tmp_path: Path) -> None:
    record, path = tmp_path / "record", tmp_path / "notebook"
    _recorded_metadata(record, path)
    assert not inputs_changed(record)

    _notebook(path, {}, [])
    assert inputs_changed(record)

    _recorded_metadata(record, path)
    path.unlink()
    assert inputs_changed(record)


@mark.parametrize("content", [b"{trunc", b"\xff"])
def test_a_file_that_isnt_json_counts_by_its_bytes(
    tmp_path: Path, content: bytes
) -> None:
    record, path = tmp_path / "record", tmp_path / "notebook"
    path.write_bytes(content)
    _recorded_metadata(record, path)
    assert not inputs_changed(record)

    path.write_bytes(content + b"edited")

    assert inputs_changed(record)


def test_presence_ignores_the_content(tmp_path: Path) -> None:
    record, path = tmp_path / "record", tmp_path / "notebook"
    path.write_text("before", encoding="utf8")
    with recording() as inputs:
        depends_on_presence(path)
    write_record(record, inputs)

    path.write_text("edited", encoding="utf8")
    assert not inputs_changed(record)

    path.unlink()
    assert inputs_changed(record)


def test_presence_sees_a_file_appearing(tmp_path: Path) -> None:
    record, path = tmp_path / "record", tmp_path / "notebook"
    with recording() as inputs:
        depends_on_presence(path)
    write_record(record, inputs)
    assert not inputs_changed(record)

    path.write_text("now there", encoding="utf8")

    assert inputs_changed(record)


def test_a_file_and_a_part_of_it_are_two_inputs(tmp_path: Path) -> None:
    record, path = tmp_path / "record", tmp_path / "notebook"
    _notebook(path, {}, [])
    with recording() as inputs:
        depends_on_json(path, "metadata")
        depends_on(path)
    write_record(record, inputs)

    _notebook(path, {}, ["an output"])

    assert inputs_changed(record)


def test_a_part_follows_its_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    build = checkout / ".build" / "deck"
    build.mkdir(parents=True)
    _notebook(checkout / "notebook", {"id": "a"}, [])
    _recorded_metadata(build / "record", checkout / "notebook")

    moved = tmp_path / "moved"
    checkout.rename(moved)

    assert not inputs_changed(moved / ".build" / "deck" / "record")
    _notebook(moved / "notebook", {"id": "b"}, [])
    assert inputs_changed(moved / ".build" / "deck" / "record")


def test_a_json_value_is_read_once_per_process(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    # A `--watch` rebuild stays at a `stat` per input.
    record, path = tmp_path / "record", tmp_path / "notebook"
    _notebook(path, {"id": "a"}, [])
    utime(path, (1, 1))
    _recorded_metadata(record, path)
    read: list[str] = []
    read_json_digest = render_inputs._read_json_digest

    def counted(name: str, part: str) -> str:
        read.append(name)
        return read_json_digest(name, part)

    monkeypatch.setattr(render_inputs, "_read_json_digest", counted)

    assert not inputs_changed(record)
    assert not inputs_changed(record)
    assert read == []


class _Converter:
    def convert(self, source: Path, destination: Path) -> None:
        destination.write_text(source.read_text(encoding="utf8"), encoding="utf8")

    def fingerprint(self) -> str:
        return ""


class _Factory:
    def __init__(self, assets_dir: Path) -> None:
        self._assets_dir = assets_dir

    def assets_metadata_retriever(self) -> AssetsMetadataRetriever:
        return AssetsMetadataRetriever(self._assets_dir)


_ENVIRONMENT = """
from pathlib import Path

from deckz.render_inputs import depends_on
from jinja2 import Environment, pass_context


def _marking(path):
    depends_on(Path(path))
    return Path(path).read_text(encoding="utf8").strip()


@pass_context
def _credit(context, value):
    return (context["assets_metadata_retriever"](value) or {}).get("author", "nobody")


def environment_for(suffix):
    env = Environment(autoescape=False)
    env.filters["marking"] = _marking
    env.filters["credit"] = _credit
    return env
"""


def _render(tmp_path: Path, name: str, text: str) -> tuple[Path, str]:
    # A fragment through the real renderer: what a filter reads is recorded.
    module = tmp_path / "env.py"
    module.write_text(_ENVIRONMENT, encoding="utf8")
    renderer = Renderer(
        module, cast("GlobalFactoryProtocol", _Factory(tmp_path / "assets"))
    )
    build_copy = tmp_path / f"{name}.md.j2"
    build_copy.write_text(text, encoding="utf8")
    render_dependencies(
        renderer,
        cast("MarkdownConverterProtocol", _Converter()),
        [CopiedDependency(build_copy, tmp_path / f"{name}.md")],
        ".typ",
        {},
    )
    rendered = (tmp_path / f"{name}.typ").read_text(encoding="utf8").strip()
    return tmp_path / f"{name}.md.inputs", rendered


def test_a_filter_declares_what_it_reads_in_a_real_render(tmp_path: Path) -> None:
    marking = tmp_path / "notebook"
    marking.write_text("GPU", encoding="utf8")

    record, rendered = _render(tmp_path, "lab", f'{{{{ "{marking}" | marking }}}}')

    assert rendered == "GPU"
    assert not inputs_changed(record)
    marking.write_text("CPU", encoding="utf8")
    assert inputs_changed(record)


def test_an_asset_credit_is_an_input_without_the_environment_declaring_it(
    tmp_path: Path,
) -> None:
    # Through `assets_metadata_retriever`, a credit file appearing included.
    assets = tmp_path / "assets"
    (assets / "img").mkdir(parents=True)

    record, rendered = _render(tmp_path, "image", '{{ "img/cat" | credit }}')

    assert rendered == "nobody"
    assert not inputs_changed(record)
    (assets / "img" / "cat.yml").write_text("author: someone\n", encoding="utf8")
    assert inputs_changed(record)


def test_a_fragment_reading_nothing_has_an_empty_record(tmp_path: Path) -> None:
    record, _ = _render(tmp_path, "plain", "Just text")

    assert record.read_text(encoding="utf8") == "{}"
    assert not inputs_changed(record)


def test_the_renderer_fingerprint_follows_the_environment_module(
    tmp_path: Path,
) -> None:
    module = tmp_path / "env.py"
    module.write_text("before = 1\n", encoding="utf8")
    renderer = Renderer(module, cast("GlobalFactoryProtocol", None))
    before = renderer.fingerprint()

    module.write_text("after = 12\n", encoding="utf8")

    assert renderer.fingerprint() != before
