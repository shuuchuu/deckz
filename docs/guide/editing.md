# Editing and building

## The edit loop

```sh
deckz run --watch --workdir my/deck --handout --no-presentation --no-print
```

rebuilds the deck's handout on every change, in about a second: each PDF's compiler
stays alive with its cache. Watching fewer PDFs keeps fewer of these (large) processes
alive.

To look at one file or one section on its own: `deckz run file <file>`, `deckz run
section <section> <flavor>` (they build under `.run/` and open the result).

## A real build

```sh
deckz run --workdir my/deck --lang fr en
```

builds the handouts, presentations and printable handouts, in both languages
(English PDFs under `pdf/en/`). Narrow it with `--handout`/`--no-presentation`/
`--no-print`, `--lang fr`, `--parts <part>`; `--dry-run` shows what would be built.

After a build, deckz removes the PDFs that no build of the deck produces anymore: a
renamed or removed part's, a stray file. A narrower build never removes the rest
(the other language's, presentations after a handout-only build). `--no-sync` keeps
everything.

## When a build fails

The error names the file. Common causes:

- Markdown that doesn't convert: see the repository's Markdown guide;
- a missing English file in an English build: [Translating](translating.md);
- a video never rendered: `deckz videos render`;
- a compilation using more memory than `deckz.yml`'s `typst_memory_max`: build fewer
  PDFs at once, or raise the limit. To keep several builds at once (two checkouts, a
  `--watch` and another build) from adding up their memory, set
  `typst_machine_compilations` (e.g. `2`) in your own `~/.config/deckz/deckz.yml`:
  past it, a compilation waits for another to finish.

## Checking the result

- `deckz check overflow <deck>`: the frames shrunk to fit, worst first (`--tables` for
  the tables whose cells wrap most). A frame shrunk below about 97% is too full.
- `deckz run --html` builds the deck as a web page too; `deckz check parity <deck>`
  compares it with the PDF, slide by slide.
