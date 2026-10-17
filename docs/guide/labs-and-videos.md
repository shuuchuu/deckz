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
  "shell command exited with code N" line (`nvidia-smi` on a CPU aside).
- A hands-on notebook stores no outputs (trainees would see the answers); a demo
  stores those of a full run in its own language: run it, then `deckz labs outputs
  <executed copy> <notebook>`.
- A demo that needs a GPU (or Colab's exact libraries) runs on a rented machine:
  `deckz labs gpu pass <notebooks> --dry-run` says what it would cost now (the GPU
  and its price, each notebook's last run time, the estimate and the ceiling);
  `deckz labs gpu pass <notebooks> --write-outputs` then rents the machine, runs
  them, prints each run's report, writes the demos' outputs back, and destroys
  the machine, always: when done, on failure, past `--max-hours` (4 by default),
  on Ctrl-C. The machine runs Colab's own image, so what runs there runs on
  Colab. The steps also exist one by one (`up`, `queue`, `run`, `status --watch`,
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
- `deckz labs publish` publishes the committed notebooks, and the files committed
  under `labs/published/` (with them, or to a repository of their own, such as the
  one a Codespace opens: `labs.published_files_remote`).
  Only maintainers do it: `deckz status` says when committed files differ from the
  published ones.

## Videos

Videos are Manim scenes, rendered apart from deck builds (a render takes minutes):

- `deckz videos render` renders those out of date (`--quality l` for quick drafts
  while working on a scene);
- `deckz videos list` shows each one's state (never rendered, stale, a draft, or
  fresh), `--json` for a script;
- `deckz videos publish` publishes the renders (maintainers). A published video's
  address is printed in handouts: never rename or remove its scene.
