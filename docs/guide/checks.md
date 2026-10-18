# Checks

`deckz check` runs every check (the pre-commit hook runs it on the staged files);
`deckz check <name>` runs one. Each problem it reports ends with how to fix it.
Checks a repository lists under `deckz.yml`'s `checks.opt_in` only run when named (or
nightly in CI): they're slow, or need the network.

## What blocks a commit

A **blocking** check's problem refuses the commit (and fails CI): the commit is when
its harm happens, a secret kept in the history or a build broken for everyone at
their next `git pull`. A **deferred** check's problem is printed without failing:
it does harm later, when a lab is published or a deck uploaded or taught, so you can
commit and fix it then: `deckz labs publish` refuses while a check reports a problem
in a notebook, `deckz upload` while one does in the deck's files (both take
`--skip-checks`), and `deckz status <deck>` lists a deck's before you teach it.
`deckz status` keeps listing them (studioz too, in its Problems tab), the blocking
ones marked "(blocks a commit)". `deckz check <name>` fails on any problem of the
checks it names, deferred or not.

`deckz.yml`'s `checks.deferred` changes which checks are deferred (see the README);
a repository's own checks block unless it lists them.

| Check | Blocks a commit | What it guards | Usual fix |
|---|---|---|---|
| `lab-secrets` | yes | no token or password in a notebook (they're public) | remove it, revoke it; `labs.not_secrets` for a false positive |
| `jinja-syntax` | yes | every content file's Jinja parses with the repository's environment, its filters and tests known (otherwise only the build fails) | fix the tag or the filter's name; `{% raw %}…{% endraw %}` around braces meant as text |
| `deck-definitions` | yes | every deck parses in French: its `deck.yml`, the sections it includes and their `.yml`, the files they name, its `variables.yml` | fix the YAML, or restore (or stop including) the section or file it names |
| `lab-ids` | no | every notebook has a valid, unique published ID | `deckz labs ids` |
| `lab-pairs` | no | every lab exists in French and English, with the same cells and code | translate the missing one; `deckz labs compare <lab dir>` |
| `lab-outputs` | no | hands-on notebooks store no outputs; demos store a full run's, none of them blank | clear them, or run the demo and `deckz labs outputs` |
| `lab-format` | no | notebooks in deckz's JSON style | `deckz labs fmt <notebook>` |
| `asset-credits` | no | image credit lines in Markdown, not LaTeX | rewrite the line in Markdown |
| `raw-latex` | no | no LaTeX left in the content | rewrite it in Markdown |
| `lab-urls` | no | labs linked through the repository's templating, not a pasted URL | use the repository's lab link |

A repository adds its own checks in `templates/checks.py`; `deckz check --help` lists
them all.
