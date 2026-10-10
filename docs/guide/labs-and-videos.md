# Labs and videos

## Lab notebooks

Notebooks live under `labs/notebooks/<topic>/<lab>/<type>-<lang>.ipynb` and are
published, to a public repository, under an ID stored in their metadata. Slides link
to the published copy, and the IDs are printed in handed-out PDFs: never change one.

- Edit a notebook in Jupyter or Colab, then `deckz labs fmt <notebook>`: deckz keeps
  notebooks in one JSON style so that changes stay readable (`lab-format` checks it).
- `deckz labs dump <notebook>` prints a compact view, cells numbered.
- `deckz labs check <notebook>` runs it the way Colab would (`--python <interpreter>`
  for a virtual environment with the lab's libraries).
- A hands-on notebook stores no outputs (trainees would see the answers); a demo
  stores those of a full run in its own language: run it, then `deckz labs outputs
  <executed copy> <notebook>`.
- `deckz labs compare <lab dir>` shows how the French and English versions differ
  beyond the translation.
- Never put a token or password in a notebook: the `lab-secrets` check refuses it,
  and so does publishing. Read secrets from the environment.
- `deckz labs publish` publishes the committed notebooks. Only maintainers do it:
  `deckz status` says when committed notebooks differ from the published ones.

## Videos

Videos are Manim scenes, rendered apart from deck builds (a render takes minutes):

- `deckz videos render` renders those out of date (`--quality l` for quick drafts
  while working on a scene);
- `deckz videos list` shows each one's state;
- `deckz videos publish` publishes the renders (maintainers). A published video's
  address is printed in handouts: never rename or remove its scene.
