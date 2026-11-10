# Labs and videos

## Lab notebooks

Notebooks live under `labs/notebooks/<topic>/<lab>/<type>-<lang>.ipynb` and are
published, to a public repository, under an ID stored in their metadata. Slides link
to the published copy, and the IDs are printed in handed-out PDFs: never change one.

- Edit a notebook in Jupyter or Colab, then `deckz labs fmt <notebook>`: deckz keeps
  notebooks in one JSON style so that changes stay readable (`lab-format` checks it).
- `deckz labs list` lists the notebooks, each with its lab, kind and language
  (`--json` for a script); `deckz labs missing`, those lacking the other language.
- `deckz labs dump <notebook>` prints a compact view, cells numbered.
- `deckz labs check <notebook>` runs it the way Colab would (`--python <interpreter>`
  for a virtual environment with the lab's libraries). It skips shell commands other
  than data fetches: `--container` runs everything, for real, in the Codespace the
  published repository opens (`labs/published/.devcontainer/`, needs Docker).
  A failed shell command doesn't stop the cell, as in Colab: look at each
  "shell command exited with code N" line (`nvidia-smi` on a CPU aside). A
  deprecation a cell's own code meets is a problem too (`[i] DeprecationWarning: …`,
  `FutureWarning`), once per place: the library's next release turns it into an
  error. Those a library meets inside itself aren't reported, nor any with
  `--container`. The command
  exits with code 1 when a notebook has a problem, and lists those notebooks last.
- A hands-on notebook stores no outputs (trainees would see the answers); a demo
  stores those of a full run in its own language: run it, then `deckz labs outputs
  <executed copy> <notebook>`. What the repository does to some outputs after that
  (e.g. load a library's JavaScript from a CDN rather than embed it in every
  report) is a `labs.outputs.hooks` command in `deckz.yml`, which `deckz labs
  outputs` runs on each notebook it applies to: nothing to remember.
- A demo whose code changed after its outputs were written shows what the code no
  longer does: `deckz labs stale` lists them (and `deckz status` those you
  changed). Rerun it and write its outputs back; when the change alters no output
  that matters (a comment, a download line), `deckz labs mark-current <notebook>
  --reason "<why>"` takes it off the list instead, in an empty commit. A commit
  making such a change across many demos can carry the `Lab-outputs-current:
  <path>` trailers itself.
- A demo that needs a GPU (or Colab's exact libraries) runs on a rented machine:
  `deckz labs gpu pass <notebooks> --dry-run` says what it would cost now (the GPU
  and its price, each notebook's last run time, the estimate and the ceiling);
  `deckz labs gpu pass <notebooks> --write-outputs` then rents the machine, runs
  them, prints each run's report, writes the demos' outputs back, and destroys
  the machine, always: when done, on failure, past `--max-hours` (4 by default),
  on Ctrl-C. A network cut of up to 30 minutes doesn't stop a pass. The machine
  runs Colab's own image, so what runs there runs on Colab. The steps also exist one by one (`up`, `queue`, `run`, `status --watch`,
  `fetch`, `down`: see the README), for a machine kept between passes, which
  bills until `down`; `deckz labs gpu status --offline` lists the machines this
  checkout has rented without asking Vast.ai. In studioz, "Exécuter sur GPU…" (a
  notebook's page, or the notebooks ticked in the TP view) runs the same pass after
  a confirmation giving the GPU, the estimate and the ceiling; studioz's agent
  can't start one.
- Writing a notebook for Colab: its runtime is Python 3.13 (pin a project the
  notebook installs accordingly), and the image sets `UV_CONSTRAINT` and
  `UV_SYSTEM_PYTHON`, so `!uv pip install --system <packages>` (or `!pip install`)
  adds packages without replacing Colab's own. Never `uv sync` an exact environment
  into the system Python: it removes what Colab ships. `deckz labs gpu` restores the
  image's packages before each notebook, as a fresh Colab session would.
- `deckz labs compare <lab dir>` shows how the French and English versions differ
  beyond the translation.
- Never put a token or password in a notebook: the `lab-secrets` check refuses it,
  and so does publishing. Read secrets from the environment.
- A lab whose automated runs need a credential or a setting (to publish a package
  to Test PyPI, to log to a DagsHub account) says so in its metadata,
  `shuuchuu.run` (`labs.run.metadata_key`): `variables` and `secrets` name the
  notebook's variables, each assigned `""` on a line of its own, and the
  environment variables (or `.env` entries, e.g. `~/.config/deckz/.env`) to fill
  them from, and `hook` a command of `labs.run.hooks` run before and after the run
  (to reset a server the notebook writes to). `deckz labs check --container` and
  `deckz labs gpu queue` fill them in the copy they run, never on a command line,
  and redact a secret's value from every line they report and every file they keep;
  `deckz labs outputs` stores no output that showed one. One that isn't set: `labs
  check --container` runs the notebook as written, the `""` line a trainee's run
  has, with a line `<VARIABLE> not set: ran without it` that doesn't fail the
  check; `labs gpu queue` refuses the notebook. `deckz labs check` without
  `--container` skips the shell commands that need them, and fills none. The
  notebook must keep working without them: that is what trainees run.
- `deckz labs publish` publishes the notebooks of the shared branch (`origin/main`,
  fetched first), whichever checkout it runs in, and the files committed there
  under `labs/published/` (with them, or to a repository of their own, such as the
  one a Codespace opens: `labs.published_files_remote`). Push your lab commits
  first: it refuses while they aren't on the shared branch. It refuses while a check
  reports a problem in a notebook, even one that didn't block its commit
  (`lab-pairs`, `lab-format`...): fix it, commit and push, or `--skip-checks`; and
  it refuses to replace a published version the shared branch's history doesn't
  hold (someone published commits never pushed): push them, or
  `--replace-unknown`.
  Only maintainers do it: `deckz status` says when committed files differ from the
  published ones.
- Publishing pushes to git remotes a fresh clone doesn't have: `deckz setup` adds
  those the repository lists in `deckz.yml`'s `setup.remotes`. Pushing needs your
  GitHub account to have write access to the published repositories: a refused push
  fails with git's own message (`git ls-remote <remote>` tests the connection).
- A lab whose project lives in a repository of its own (`labs.repos`: a notebook as
  its Colab version, the repository's README as the same statement for a Codespace
  or a clone): `deckz labs repos` fetches each and reports a branch missing or behind
  the one it stacks on, a README that doesn't link its notebook, and a README last
  changed before its notebook was. Content links such a repository through the
  repository's templating, never by hand (`lab-urls`).


## Labs in CI

A lab breaks without anyone touching it: a library's new release removes what it
calls, after a release or two of deprecation warnings. With `ci.labs` set, the
scheduled job (`deckz hooks install --ci`) runs `deckz labs check` every Sunday on the
notebooks it names, in an environment it creates anew, with the libraries'
latest versions the requirements allow; an error or a deprecation fails the job, and
`ci.report_to` gets the issue, with the command to run again. Unset, the workflow has
no such step: regenerating it changes nothing.

```yaml
ci:
  labs:
    notebooks:                     # files, or directories searched recursively
      - labs/notebooks/python/basics
      - labs/notebooks/ml/regression/linear-regression/hands-on-fr.ipynb
    requirements: labs/requirements.txt              # and/or
    packages: [scikit-learn, pandas]                 # pip install's arguments
    index_urls: [https://download.pytorch.org/whl/cpu]  # PyTorch without CUDA
    python: "3.12"                 # the default
    timeout: 600                   # seconds per notebook, the default
    smoke: true                    # cap Lightning's Trainers, the default
```

It runs as `deckz labs check` without `--container` does: on the runner's CPU, the run
needs' variables and secrets unset, no shell command but the data fetches. So name
only the labs that run that way: not those needing a GPU, credentials or a server,
nor those that `!pip install` a library `packages` doesn't install. A pinned
requirements file (one compiled against Colab's versions) shows what breaks on
Colab today; an unpinned one shows the next releases before Colab takes them. A
directory runs both languages of each lab: name the French notebooks alone to halve
the time.

## Videos

Videos are Manim scenes, rendered apart from deck builds (a render takes minutes):

- `deckz videos render` renders those out of date (`--quality l` for quick drafts
  while working on a scene); `deckz videos fetch` puts the published renders in
  place of those you never rendered instead, with no Manim to install (`deckz
  videos render` renders them again: nothing says which scene version they're
  from);
- `deckz videos list` shows each one's state (never rendered, stale, a draft, or
  fresh), `--json` for a script;
- `deckz videos publish` publishes the renders (maintainers), from a checkout whose
  scenes are the shared branch's (it refuses otherwise: update the checkout, push
  its commits). A published video's address is printed in handouts: never rename
  or remove its scene.
