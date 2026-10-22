# New content

Before writing a new section, look for an existing one: `deckz search-sections
<keywords>` searches the sections' and frames' titles, in both languages.

## A deck

```sh
deckz new deck company/CODE --name CODE --title "Course title"
```

creates the deck's directory from the repository's template (`templates/scaffold/
deck/`, whose `deck.yml.jinja` becomes `deck.yml`). Then list its sections in `deck.yml` (`$section@flavor`; `deckz
section-flavors <section>` lists a section's flavors) and build it.

## A shared section

```sh
deckz new section topic/subject --title "Titre"
```

creates `content/topic/subject/` with its `.yml` (a `full` flavor), a first file and its
English twin. It lists the existing sections sharing a word with it first. Add files
to the folder and to the flavor's `includes`; each `# Title` in a file is a frame.

## Course notes

A deck's course notes are written chapter by chapter, one per content file, under
`course-notes/` at the content file's path (`course-notes/topic/subject/intro.md`
for `content/topic/subject/intro.md`, its English version in `en/`). `deckz show
course-notes` lists the deck's files with their chapters, and

```sh
deckz run course-notes --watch
```

recompiles the course notes PDF (`pdf/course-notes/`) on each change (`deckz run
--watch --course-notes` rebuilds the slides along with it). A chapter serves every
deck that includes its file. A chapter no deck includes yet builds on its own:
`deckz run file course-notes/topic/subject/intro.md` (`--watch` to keep it
building). See the README's "Course notes".

## A lab

```sh
deckz labs new topic/subject/what-it-does-framework hands-on
```

creates the French and English notebooks of a lab (`hands-on`: trainees write code,
with collapsed "Solution" sections; `demo`: runs start to finish), with their
published IDs, and prints how to link it from a slide. See [Labs and
videos](labs-and-videos.md).
