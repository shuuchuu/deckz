from typing import Any

from deckz.labs.secrets import find_secrets

# Built at run time: no token-shaped literal in the repository.
_GITHUB = "ghp_" + "A1b2" * 9
_OPENAI = "sk-proj-" + "x9Y8" * 6


def _notebook(*cells: dict[str, Any]) -> dict[str, Any]:
    return {"cells": list(cells), "metadata": {}, "nbformat": 4}


def _code(source: str, outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"cell_type": "code", "source": source, "outputs": outputs or []}


def test_finds_a_token_in_a_source_without_showing_it() -> None:
    findings = find_secrets(_notebook(_code(f'client = Github("{_GITHUB}")')))

    assert [(f.cell, f.where, f.kind) for f in findings] == [
        (0, "source", "GitHub token")
    ]
    assert _GITHUB not in str(findings[0])


def test_finds_a_token_printed_in_an_output() -> None:
    output = {"output_type": "stream", "name": "stdout", "text": [f"{_OPENAI}\n"]}

    findings = find_secrets(_notebook(_code("print(key)", [output])))

    assert [(f.where, f.kind) for f in findings] == [
        ("outputs", "OpenAI or Anthropic key")
    ]


def test_finds_a_credential_assignment() -> None:
    findings = find_secrets(_notebook(_code('API_KEY = "a1b2c3d4e5f6g7h8i9"')))

    assert [f.kind for f in findings] == ["credential assignment"]


def test_ignores_placeholders_and_scikit_learn_reprs() -> None:
    notebook = _notebook(
        _code('API_KEY = "YOUR_API_KEY_HERE"'),
        _code(
            "model",
            [
                {
                    "output_type": "display_data",
                    "data": {
                        "text/html": [
                            '<div class="sk-toggleable__control sk-top-container">'
                        ]
                    },
                }
            ],
        ),
        _code('token = os.environ["HF_TOKEN"]'),
    )

    assert find_secrets(notebook) == []


def test_not_secrets_are_ignored() -> None:
    notebook = _notebook(_code(f'client = Github("{_GITHUB}")'))

    assert find_secrets(notebook, not_secrets=[_GITHUB]) == []
