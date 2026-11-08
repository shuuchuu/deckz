import json

from pytest import MonkeyPatch, raises

from deckz.exceptions import LabRunNeedsError
from deckz.labs.needs import RunNeeds, fill, redact, run_needs


def test_redact_replaces_every_json_form_of_a_value(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("LAB_TOKEN", 'mot "de" passe-é')
    text = " ".join(
        [
            'mot "de" passe-é',
            json.dumps('mot "de" passe-é', ensure_ascii=False),
            json.dumps('mot "de" passe-é'),
        ]
    )

    redacted = redact(text, ["LAB_TOKEN"])

    assert "passe" not in redacted
    assert redacted.count("[deckz: redacted LAB_TOKEN]") == 3


def test_redact_skips_an_unset_variable_unless_strict(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("LAB_TOKEN", raising=False)

    assert redact("text", ["LAB_TOKEN"], strict=False) == "text"
    with raises(LabRunNeedsError, match="set LAB_TOKEN"):
        redact("text", ["LAB_TOKEN"])


def test_fill_leaves_an_unset_need_as_written(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("LAB_USER", "jeanne")
    monkeypatch.delenv("LAB_TOKEN", raising=False)
    cell = {"cell_type": "code", "source": ['user = ""\n', 'token = ""\n']}
    nb = {"cells": [cell], "metadata": {}}
    needs = RunNeeds(variables={"user": "LAB_USER"}, secrets={"token": "LAB_TOKEN"})

    assert fill(nb, needs) is None
    assert cell["source"] == ['user = "jeanne"\n', 'token = ""\n']
    assert needs.unset() == ["LAB_TOKEN"]


def test_run_needs_reads_the_metadata_key() -> None:
    nb = {"metadata": {"shuuchuu": {"run": {"hook": "reset"}}}}

    assert run_needs(nb, "shuuchuu.run") == RunNeeds(hook="reset")
    assert run_needs(nb, "shuuchuu.gpu") == RunNeeds()
