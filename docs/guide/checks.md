# Checks

`deckz check` runs every check (the pre-commit hook runs it on the staged files);
`deckz check <name>` runs one. Each problem it reports ends with how to fix it.
Checks a repository lists under `deckz.yml`'s `checks.opt_in` only run when named (or
nightly in CI): they're slow, or need the network.

| Check | What it guards | Usual fix |
|---|---|---|
| `lab-ids` | every notebook has a valid, unique published ID | `deckz labs ids` |
| `lab-pairs` | every lab exists in French and English, with the same cells and code | translate the missing one; `deckz labs compare <lab dir>` |
| `lab-outputs` | hands-on notebooks store no outputs; demos store a full run's | clear them, or run the demo and `deckz labs outputs` |
| `lab-secrets` | no token or password in a notebook (they're public) | remove it, revoke it; `labs.not_secrets` for a false positive |
| `lab-format` | notebooks in deckz's JSON style | `deckz labs fmt <notebook>` |
| `asset-credits` | image credit lines in Markdown, not LaTeX | rewrite the line in Markdown |
| `raw-latex` | no LaTeX left in the content | rewrite it in Markdown |
| `lab-urls` | labs linked through the repository's templating, not a pasted URL | use the repository's lab link |

A repository adds its own checks in `templates/checks.py`; `deckz check --help` lists
them all.
