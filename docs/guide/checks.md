# Checks

`deckz check` runs every check (the pre-commit hook runs it on the staged files);
`deckz check <name>` runs one. Each problem it reports ends with how to fix it.
Checks a repository lists under `deckz.yml`'s `checks.opt_in` only run when named (or
nightly in CI): they're slow, or need the network. So does deckz's own
`course-notes-code`, which runs the course notes' code. `--file <path>...` limits the
checks that read files to those: `deckz check course-notes-code --file
course-notes/topic/intro.md` runs one chapter's code.
No check compiles a deck: when `ci.builds` is set, CI builds every Sunday (or every
night) the handouts of the decks the period's commits reach, and fails naming the deck
that doesn't build (`deckz run decks --since <rev>` does the same before you push).
With `ci.report_to`, the failures land in a `deckz-ci` GitHub issue, which GitHub
emails: each with the command that reproduces it and its errors, ready to paste to an
agent.

## What blocks a commit

A **blocking** check's problem refuses the commit (and fails CI): the commit is when
its harm happens, a secret kept in the history or a build broken for everyone at
their next `git pull`. A **deferred** check's problem is printed without failing:
it does harm later, when a lab is published or a deck uploaded or taught, so you can
commit and fix it then: `deckz labs publish` refuses while a check reports a problem
in a notebook, `deckz upload` while one does in the deck's files or in an asset the
deck shows (both take `--skip-checks`), and `deckz status <deck>` lists a deck's before you teach it.
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
| `review-headers` | yes | every review report's `reviewed` front matter is well formed, and the files it records exist (only with `review.dir`, see [Reviews](reviews.md)) | a renamed file: `deckz review mark <report> --forget <old> <new>`; a deleted one: `--forget <old>` |
| `lab-ids` | no | every notebook has a valid, unique published ID | `deckz labs ids` |
| `lab-pairs` | no | every lab exists in French and English, with the same cells and code | translate the missing one; `deckz labs compare <lab dir>` |
| `lab-outputs` | no | hands-on notebooks store no outputs; demos store a full run's, none of them blank | clear them, or run the demo and `deckz labs outputs` |
| `lab-format` | no | notebooks in deckz's JSON style | `deckz labs fmt <notebook>` |
| `asset-credits` | no | image credit lines in Markdown, not LaTeX | rewrite the line in Markdown |
| `raw-latex` | no | no LaTeX left in the content | rewrite it in Markdown |
| `lab-urls` | no | labs linked through the repository's templating, not a pasted URL | use the repository's lab link |
| `course-notes-files` | no | each course notes chapter is named after a content file; `course_notes.same_as` names content files with no chapter of their own | move the chapter after its renamed file; fix `same_as` |
| `course-notes-pairs` | no | each course notes chapter exists in French and English (a directory with no English chapter yet: one line, and none in the post-edit hook) | translate the missing one |
| `course-notes-code` | no, and opt-in | each course notes chapter's Python code runs, and prints what the chapter shows (see below) | show what it prints; mark the block `.output-varies` or `.no-run` |

## A chapter's code

`deckz check course-notes-code` runs each chapter's Python as a reader typing it in
would, in a scratch directory, with the interpreter `course_notes.code.python` names
(the README's "Course notes"): each `pycon` prompt, its output compared with the one
shown under it (`...` stands for any text: an address, a long tail), and each `python`
block, compared with the `text` block right after it, or else expected to print
nothing. A shown error counts by its last line. A block whose first line names a file
(`# greeting.py`) is written to that file, for the blocks after it to import (a file
other than Python source, `# example.txt`, without that first line). The programs run
in English (`LC_ALL=C.UTF-8`), as on Colab. A `console` block runs command by command
(`$ pytest -v`, its output under it, as an 80-column terminal shows it: line-buffered,
`ls` in columns) when `course_notes.code.commands` lists every
program it runs, `uv run <program>` running
the program itself; a command that fails with nothing shown is a problem, unless an
`echo $?` follows it. Classes on the fence opt a block out: `{.python .no-run}` isn't
run (a GUI's main loop, a server, `input()`, a deliberate fragment), `{.pycon
.output-varies}` runs without its output compared (timings, the machine's own state);
neither shows in the PDF. Each problem shows what the code printed, ready to paste
into the chapter.

A chapter needing a package the interpreter lacks gets it from
`course_notes.code.requirements` (where `python`'s `{with}` stands). Its data sets
come from the repository `course_notes.code.datasets` names, through the links the
chapter gives its reader: a file link puts that file in the working directory under
its own name, a directory link (`<url>/tree/main/<dir>`, or the repository's
`ghsparse.sh <dir>`) the directory. The check reports a linked file missing from the
local clone, not committed, or not pushed, and two files downloaded under the same
name (link their directories instead). Big files (over 50 MB) are linked rather than
copied, and a chapter writing over one is reported.

A repository adds its own checks in `templates/checks.py`; `deckz check --help` lists
them all.
