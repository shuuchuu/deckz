# Drive links plan: slides that carry their own link, and their course notes'

## Why

A handed-out PDF (a handout, a print, a presentation) has no way back to its online,
up-to-date version, nor to the deck's course notes. `deckz upload` knows each file's
Google Drive link, but only after compiling: a new file's link exists once it's
uploaded, and the PDF can't contain it any more.

## Decisions

- **Reserve, then build, then upload.** `deckz upload --reserve` creates, in the deck's
  Drive folder, an empty file for every PDF a full build of the deck produces (every
  kind, every part handout, the course notes in the languages they have chapters in)
  that has none yet, and records its ID. Builds then show the links, and `deckz upload`
  fills those files: Drive keeps a file's ID across updates, so a link never changes.
  An empty file rather than `files.generateIds`: its ID exists for good, whatever
  delay until the first upload.
- **A per-deck registry, the user's**: `<user config dir>/drive-links/<deck
  path>.yml` (`paths.drive_links`), each PDF's path relative to the deck directory
  mapped to its Drive file ID. The files are in the user's Drive, so the registry is
  theirs, where they may track it (first committed in the deck's directory, moved
  there at the user's request the same day); every checkout shares it. A build reads
  it and never calls Drive. A link is shown when the registry has it: no registry
  (another user, CI), no links, as before. One file per deck: two sessions reserving
  for two decks never conflict.
- **In each main template's context, `links`**: `self` (this PDF's own link),
  `handout` (the whole deck's handout, in this language) and `course_notes` (the
  course notes' PDF, in this language), each only when the registry has it. The
  course notes link is there when the deck has course notes, since only then does
  `--reserve` reserve one: it doesn't depend on which PDFs happen to be on disk.
- **A link change makes a PDF outdated.** A compilation records its links next to
  its build (`<build>/<name>/.links`), and `plan` reports `links_changed`, which
  `outdated_pdfs` (so `deckz upload`'s refusal and `deckz status`) counts.
- **`deckz upload`** writes each PDF to its reserved file, uploads the course notes
  too (`pdf/course-notes/` beside the slides, `pdf/course-notes/en/` in `en/`),
  refuses, with the deck having a registry, a PDF it has no link for (it would go out
  without its own: `--reserve`, rebuild), and never deletes a remote file the
  registry names (its link is printed in PDFs already handed out).

## Steps

1. `deckz/drive_links.py`: load and save the registry, the link of an ID. Settings
   path `paths.drive_links`. Tests.
2. `DeckBuilder`: `links` in the main template's context, `.links` record, `plan`'s
   `links_changed`; factory reads the registry; `outdated_pdfs` counts it, course
   notes targets included. Tests.
3. `extras/uploading.py` + `cli/upload.py`: `--reserve`, reserved files, course
   notes, protected deletions, the refusal; `--dry-run` says which PDFs have no link.
   Tests with a fake Drive service.
4. README (upload, course notes, main template context), CLAUDE.md.
5. slides: show the links (`deck-links` in its theme, on the title slide and the
   course notes' title page).
6. Merge, after telling the running slides sessions (upload's behavior changes).

## Status (2026-10-23)

Done: steps 1-6, tried on slides' orsys/pya with a hand-written registry of fake
IDs (handout, print and course notes: the links on screen, the QR codes in print,
`upload --dry-run` with nothing outdated). Never run against Google Drive: the first
real `deckz upload --reserve` (the user's, with their credentials) is the test of
`Uploader.reserve` and of uploading to a reserved file.
