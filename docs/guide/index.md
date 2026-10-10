# Running a deckz repository

These pages are for the people who maintain a deckz-managed repository day to day:
writing slides, translating them, preparing labs, building and handing out decks. Each
page is one task. `deckz --help` lists the commands by task too, and `deckz <command>
--help` is the full reference of one.

| I want to... | Page |
|---|---|
| set up a fresh clone | [Setting up](setup.md) |
| edit slides and see the result | [Editing and building](editing.md) |
| start a deck, a section or a lab | [New content](new-content.md) |
| keep French and English in step | [Translating](translating.md) |
| work on lab notebooks or videos | [Labs and videos](labs-and-videos.md) |
| know if my work is ready to commit, teach or publish | [Before committing, teaching, publishing](before-you-commit.md) |
| understand what a check reports | [Checks](checks.md) |

The configuration files (`deckz.yml`, `variables.yml`, `deck.yml`, section `.yml`s)
are described in the [README](https://github.com/shuuchuu/deckz#configuration).

## A typical day

```sh
git pull
deckz setup                          # anything new to install since last time?
deckz run --watch --workdir my/deck  # edit, and see the PDF rebuild in a second
deckz status                         # what's left before committing
git add <the files you changed>
git commit                           # the hooks run the checks
```

Every command that refuses or reports a problem says how to fix it. If a message
doesn't, that's a bug in deckz: report it.
