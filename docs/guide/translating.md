# Translating

Every content file and lab notebook exists in French and in English: `content/x/a.md`
and `content/x/en/a.md`, `demo-fr.ipynb` and `demo-en.ipynb`. Titles in `.yml` files
are either one string (the same in both languages) or a `{fr: ..., en: ...}` map.

## Committing in one language

You don't have to translate in the same commit. When a commit changes one side of a
pair only, git asks you to say why, with a line at the end of the commit message,
after a blank line:

```text
Lang-sync: pending
```

when the other language will be updated later, or `Lang-sync: fr-only (<why>)` /
`Lang-sync: en-only (<why>)` when there's nothing to port (a typo, the language's own
typography). The refusal message lists the files and the lines to paste; git keeps
your message, so committing again is quick.

## Catching up

- `deckz i18n stale` lists every file changed since its other-language version, with
  the commits to port and the `git diff` to read. A file leaves the list when a commit
  touches its sibling.
- `deckz i18n missing-en --workdir <deck>` (`--all` for every deck) lists the files
  and titles with no English version; an English build fails on them.
- `deckz status` shows the backlog in one line.
