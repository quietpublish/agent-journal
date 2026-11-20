---
name: journal-init
description: Scaffold the journal files into the current repo (docs/JOURNAL.md, GLOSSARY.md, BELIEFS.md, docs/knowledge/) and print the AGENTS.md snippet. Use when the user says "set up a journal", "add a journal to this repo", "journal init".
disable-model-invocation: true
allowed-tools:
  - Bash
  - Read
---

# /journal-init

Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/journal-init.sh"`. It is idempotent and never overwrites.
Show the user what it created and the AGENTS.md / CLAUDE.md snippet it printed. Offer to paste the
snippet into the repo's `AGENTS.md` (or `CLAUDE.md` if there is no AGENTS.md); do not paste without a yes.
Suggest a first entry: the reason this repo exists, as a `[decision]`.
