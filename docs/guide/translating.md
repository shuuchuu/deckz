# Translating

Every content file and lab notebook exists in French and in English: `content/x/a.md`
and `content/x/en/a.md`, `demo-fr.ipynb` and `demo-en.ipynb`. Titles in `.yml` files
are either one string (the same in both languages) or a `{fr: ..., en: ...}` map.

## Committing in one language

You don't have to translate in the same commit, nor say anything about it. When a
commit changes one side of a pair only, the commit-msg hook adds this line at the end
of its message:

```text
Lang-sync: pending
```

and lists the files, which `deckz i18n stale` shows until the other language is
updated. When there's nothing to port (a typo, the language's own typography), end
the message yourself with `Lang-sync: fr-only (<why>)` or `Lang-sync: en-only
(<why>)`, after a blank line, and the hook keeps it; forgot to, `deckz i18n
mark-synced` (below) settles it later. The hook refuses a commit only when its
`Lang-sync` line isn't read (misspelled, or not in the message's last paragraph),
since your choice would be lost; git keeps your message, so committing again is
quick.

## Catching up

- `deckz i18n stale` lists every file changed since its other-language version, with
  the commits to port and the `git diff` to read (`--plain` or `--json` for a script).
  A file leaves the list when a commit touches its sibling.
- When its changes need nothing in the other language after all (a case fix committed
  without its `Lang-sync: fr-only` line), `deckz i18n mark-synced <file> --reason
  "<why>"` takes it off the list: an empty commit whose message ends with
  `Lang-synced: <file>`, after which the pair counts as in sync. It commits nothing
  else, even what you've staged.
- `deckz i18n missing-en --workdir <deck>` (`--all` for every deck) lists the files
  and titles with no English version; an English build fails on them.
- `deckz status` shows the backlog in one line.
