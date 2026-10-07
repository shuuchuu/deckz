import json
from pathlib import Path

from pytest import MonkeyPatch, raises

import deckz.labs.ids as ids_module
from deckz.exceptions import LabIdConflictError
from deckz.labs.ids import assign_ids, lab_section


def _write_notebook(path: Path, **metadata: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cells": [],
                "metadata": metadata,
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        )
    )


def test_lab_section_finds_longest_matching_section_dir(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    section_dir = content_dir / "nn" / "cnn" / "unet"
    section_dir.mkdir(parents=True)
    (section_dir / "unet.yml").touch()

    assert lab_section(Path("nn/cnn/unet"), content_dir) == "nn/cnn/unet"


def test_lab_section_falls_back_to_whole_path_without_a_yml(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()

    assert lab_section(Path("nn/cnn/unet"), content_dir) == "nn/cnn/unet"


def test_assign_ids_single_lab_in_its_section(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    section_dir = content_dir / "nn" / "cnn" / "image-segmentation-keras"
    section_dir.mkdir(parents=True)
    (section_dir / "image-segmentation-keras.yml").touch()

    notebooks_dir = tmp_path / "labs" / "notebooks"
    lab_dir = notebooks_dir / "nn" / "cnn" / "image-segmentation-keras"
    _write_notebook(lab_dir / "demo-fr.ipynb")
    _write_notebook(lab_dir / "demo-en.ipynb")

    assigned = {
        path.name: lab_id for lab_id, path in assign_ids(notebooks_dir, content_dir)
    }

    assert assigned == {
        "demo-fr.ipynb": "image-segmentation-keras-demo-fr",
        "demo-en.ipynb": "image-segmentation-keras-demo-en",
    }
    written = json.loads((lab_dir / "demo-fr.ipynb").read_text())
    assert written["metadata"]["shuuchuu"]["id"] == "image-segmentation-keras-demo-fr"


def test_assign_ids_several_labs_in_one_section(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    section_dir = content_dir / "nn" / "cnn"
    section_dir.mkdir(parents=True)
    (section_dir / "cnn.yml").touch()

    notebooks_dir = tmp_path / "labs" / "notebooks"
    _write_notebook(notebooks_dir / "nn" / "cnn" / "unet" / "demo-fr.ipynb")
    _write_notebook(notebooks_dir / "nn" / "cnn" / "resnet" / "demo-fr.ipynb")

    assigned = {path: lab_id for lab_id, path in assign_ids(notebooks_dir, content_dir)}

    ids = {path.parent.name: lab_id for path, lab_id in assigned.items()}
    assert ids == {"unet": "cnn-unet-demo-fr", "resnet": "cnn-resnet-demo-fr"}


def test_assign_ids_dry_run_does_not_write(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    notebooks_dir = tmp_path / "labs" / "notebooks"
    path = notebooks_dir / "topic" / "demo-fr.ipynb"
    _write_notebook(path)

    assigned = assign_ids(notebooks_dir, content_dir, dry_run=True)

    assert len(assigned) == 1
    assert "shuuchuu" not in json.loads(path.read_text())["metadata"]


def test_assign_ids_skips_notebooks_with_existing_ids(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    notebooks_dir = tmp_path / "labs" / "notebooks"
    path = notebooks_dir / "topic" / "demo-fr.ipynb"
    _write_notebook(path, shuuchuu={"id": "topic-demo-fr"})

    assert assign_ids(notebooks_dir, content_dir) == []


def test_assign_ids_raises_on_duplicate_existing_id(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    notebooks_dir = tmp_path / "labs" / "notebooks"
    _write_notebook(notebooks_dir / "a" / "demo-fr.ipynb", shuuchuu={"id": "dup"})
    _write_notebook(notebooks_dir / "b" / "demo-fr.ipynb", shuuchuu={"id": "dup"})

    with raises(LabIdConflictError):
        assign_ids(notebooks_dir, content_dir)


def test_assign_ids_raises_on_invalid_existing_id(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    notebooks_dir = tmp_path / "labs" / "notebooks"
    _write_notebook(
        notebooks_dir / "a" / "demo-fr.ipynb", shuuchuu={"id": "Not Valid!"}
    )

    with raises(LabIdConflictError):
        assign_ids(notebooks_dir, content_dir)


def test_assign_ids_raises_when_computed_id_already_taken(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    notebooks_dir = tmp_path / "labs" / "notebooks"
    _write_notebook(
        notebooks_dir / "topic" / "demo-fr.ipynb",
        shuuchuu={"id": "topic-demo-fr"},
    )
    _write_notebook(notebooks_dir / "topic2" / "demo-fr.ipynb")
    # Force a collision: the second notebook computes the same id as the first.
    monkeypatch.setattr(ids_module, "lab_id", lambda *_args, **_kwargs: "topic-demo-fr")

    with raises(LabIdConflictError):
        assign_ids(notebooks_dir, content_dir)
