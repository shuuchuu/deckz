# Command line

The top layer: `deckz.cli` turns a command line into a call to the core, and the core's
results and errors into output.

| | |
|---|---|
| **Responsibility** | Parse arguments, build settings, call the core, render its results |
| **Owns** | The terminal: logging setup, `rich` widgets, exit codes, `--plain`/`--json` output |
| **Depends on** | Any layer below it |
| **Never** | Holds business logic, or is imported by anything outside `deckz.cli` (layers and `studioz-cli` contracts) |
| **Entry points** | [`main`][deckz.cli.main] (the `deckz` script), and `app`, the `cyclopts` app every command registers onto |
| **Fails with** | Exit code 1 on a `DeckzError`, 2 on a usage error, 130 on Ctrl-C |

## Wiring

[`main`][deckz.cli.main] loads the `.env` files (the closest one, then the user's,
`<user config dir>/.env`), then imports every module under `deckz.cli`
(`utils.import_module_and_submodules`). Each command module registers its command onto
the shared `app` with `@app.command()` as a side effect of being imported. A related set
of commands is a sub-app: a package (`run/`, `check/`, `labs/`…) whose `__init__.py`
creates an `App(name=...)` and registers it onto its parent, and whose modules each add
one subcommand. A sub-app may have a default subcommand (`@app.default`): `deckz run` is
`deckz run deck`, and `deckz check` is `deckz check content`.

`--help` lists commands by task, in the groups of `cli/_groups.py`. Shipping a command
means giving it a group, a page in the [guide](../guide/index.md), `--plain`/`--json`
when a script reads its output, and tests.

## A command function

A command function stays thin:

1. parse its arguments (`cyclopts`, from the function's signature and docstring);
2. build a `GlobalSettings` or `DeckSettings` (see [Foundations](foundations.md));
3. call one core function, from `pipelines`, `status`, an `analyzing` module…;
4. render what it returns, through `cli/_presentation.py`.

It holds no rule of its own: a rule that a command needs is a function of the core,
where the other commands, studioz and the hooks can reach it too.

## The error boundary

`main` calls `app.meta`, whose default, `_launch`, takes the global flags (`--quiet`,
`--verbose`, `--debug`), configures logging, and runs the command. It is the only place
that catches errors:

- a [`DeckzError`][deckz.exceptions] becomes a logged message and exit code
  1, without a traceback. A [`DeckParsingError`][deckz.exceptions.DeckParsingError]
  also prints the deck's tree with the unresolved paths marked;
- a usage error exits 2 (printed by `cyclopts`);
- Ctrl-C stops every Typst worker and multiprocessing child (`compiler.stop()`), then
  exits 130.

`--debug`, or `DECKZ_DEBUG=1`, re-raises instead. Anything else that escapes is a bug,
shown with its traceback. So the core raises a `DeckzError` subclass whose message names
the fix, and never calls `sys.exit` or prints.

## Output

- stdout carries results only, `--json` included, so that a script can parse it.
- Logs and progress bars go to stderr (`RichHandler` on a stderr `Console`).
- The core reports progress through a
  [`ProgressReporterProtocol`][deckz.components.protocols.ProgressReporterProtocol].
  The CLI passes `RichProgress`; anything else gets `NullProgress`.
- `cli/_presentation.py` holds the `rich` widgets (trees, tables, progress, plans, status
  reports). A command with a one-off table may draw it itself (`cli/deps.py`).

## Options from the environment

`cli/_options.py` holds the options several commands share. `Langs` (`--lang fr en`)
defaults to `DECKZ_LANG`. The `run` sub-app reads every option of every subcommand from
`DECKZ_RUN_<OPTION>` (`Env("DECKZ_RUN_", command=False)`, the same names for `deckz run`
and `deckz run deck`). A default taken from the environment or a `.env` file is
announced (`environment_defaults`), never silent.

## Commands outside the core's API

- `deckz hooks <event>` (`cli/hooks/`) are the Claude Code hooks' entry points: each one
  reads the event's JSON from stdin and calls [`agent_hooks`](tasks.md#agent-hooks). They
  catch broadly, because a hook that fails must let the action through.
- `deckz generate-agent-notes` prints the notes an agent reads in a managed repository.
- `deckz generate-completion` and `--install-completion` set up shell completion.
