# New content

Before writing a new section, look for an existing one: `deckz search-sections
<keywords>` searches the sections' and frames' titles, in both languages.

## A deck

```sh
deckz new deck company/CODE --name CODE --title "Course title"
```

creates the deck's directory from the repository's template (`templates/scaffold/
deck/`). Then list its sections in `deck.yml` (`$section@flavor`; `deckz
section-flavors <section>` lists a section's flavors) and build it.

## A shared section

```sh
deckz new section topic/subject --title "Titre"
```

creates `content/topic/subject/` with its `.yml` (a `full` flavor), a first file and its
English twin. It lists the existing sections sharing a word with it first. Add files
to the folder and to the flavor's `includes`; each `# Title` in a file is a frame.

## A lab

```sh
deckz labs new topic/subject/what-it-does-framework hands-on
```

creates the French and English notebooks of a lab (`hands-on`: trainees write code,
with collapsed "Solution" sections; `demo`: runs start to finish), with their
published IDs, and prints how to link it from a slide. See [Labs and
videos](labs-and-videos.md).
