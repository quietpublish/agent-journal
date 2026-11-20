---
name: journal
description: Draft, approve, and append a journal entry to docs/JOURNAL.md; or search the journal by meaning. Use when a decision is made, a lesson is learned, a dogfood surprises you, or the user says "journal this", "add a journal entry", "what did we decide about", "search the journal". Not for routine progress notes.
argument-hint: "[search <query> | init | lint | draft text]"
allowed-tools:
  - Read
  - Bash
  - Grep
  - Glob
---

# /journal

Plugin root: `${CLAUDE_PLUGIN_ROOT}`. Project root: `${CLAUDE_PROJECT_DIR}` or the git toplevel.
The contract is `${CLAUDE_PLUGIN_ROOT}/SCHEMA.md`. Read it once per session before drafting.

## Subcommands

- `/journal search <query>` → run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal-search.py" --query "<query>"`.
  If it exits non-zero, report the exact reason (Ollama down, model not pulled, index stale) and offer
  `--build`. Never say "the journal has nothing on that" when the tool failed. Then `sed -n 'START,ENDp' docs/JOURNAL.md`
  for the top hits and answer from the entries, citing IDs.
- `/journal init` → run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/journal-init.sh"` and show the AGENTS.md snippet it prints.
- `/journal lint` → run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal-lint.py"` and summarize by code.
- Anything else, or no argument → draft an entry (below).

## Drafting an entry

1. **Decide whether it deserves an entry.** Yes: a decision with a why, a lesson that changes how we
   work, a correction of an earlier entry, a surprising dogfood result. No: routine progress, a list of
   files changed, anything git already says. If no, say so in one line and stop.
2. **Read the anchors.** `${CLAUDE_PLUGIN_ROOT}/templates/EXEMPLARS.md` (voice), `docs/GLOSSARY.md`
   (terms), and the top two entries of `docs/JOURNAL.md` (so you don't duplicate). Anchor voice to the
   exemplars, not to the recent entries.
3. **Draft** in this exact shape:

   ```
   ## YYYY-MM-DD — [type] Title that states the finding in plain words

   First sentence is the lesson or decision, readable with zero project context.
   Why, not what. Under 250 words. Evidence by path or commit.

   Supersedes: j-<id>        (only for [correction])
   Keeper: one-line lesson   (optional)
   ```
   `type` ∈ decision | lesson | status | correction | sweep. Today's date from `date +%F`. No ID; the writer assigns it.
4. **Cold-reader check.** Restate the entry in two plain sentences as if to someone who has never seen
   this repo. List every project-specific term used. Each must be in `docs/GLOSSARY.md` or be introduced
   in bold in this entry with a proposed glossary line. Fix the draft until the list is empty.
5. **Dry-run the writer** to validate format:
   `printf '%s\n' "<entry>" | python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal-append.py"`
   Fix any error it reports.
6. **Show the human** the entry, the plain restatement, and any proposed glossary lines. Ask for approval.
   Do not append without it.
7. **On approval**, append with `--apply` (same command). Add proposed glossary lines to `docs/GLOSSARY.md`.
   Report the entry ID from the JSON output. The seek table regenerates automatically.
8. If `docs/BELIEFS.md` exists and this entry changes a listed belief, say which line, and propose the
   edit. Do not edit BELIEFS.md silently; it has a line cap and every change names what it removes.

## Rules that do not bend

- Entries are never edited. Corrections are new entries with `Supersedes:`.
- One entry per invocation.
- The forward-look does not go in the journal.
