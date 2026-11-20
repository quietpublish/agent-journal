---
name: journal-compile
description: Monthly consolidation of docs/JOURNAL.md into docs/BELIEFS.md and docs/knowledge pages, as proposals a human approves. Use when the user says "compile the journal", "consolidate the journal", "update beliefs", or when a month has passed since the last compile.
disable-model-invocation: true
argument-hint: "[--since YYYY-MM-DD] [--apply]"
allowed-tools:
  - Read
  - Write
  - Bash
  - Grep
  - Glob
---

# /journal-compile

Turns raw entries into the rewritten layer. Never touches `docs/JOURNAL.md`. Writes only under
`docs/knowledge/_proposals/<date>/` until the human approves. Contract: `${CLAUDE_PLUGIN_ROOT}/SCHEMA.md`.

Why this shape: memory that an LLM re-consolidates after every interaction can fall below the
no-memory baseline (arXiv 2605.12978), and the best model tested acted correctly on outdated memories
only about half the time (arXiv 2605.06527). So this
runs on a cadence, keeps the raw journal as evidence, and makes every supersession explicit.

## Steps

1. **Pending entries.** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal-compile-state.py" pending [--since ...]`.
   If zero, stop. If more than ~60, propose a `--since` window and ask; do not compile a year at once.
2. **Pass one: select pages.** Read `docs/BELIEFS.md`, `docs/GLOSSARY.md`, and the frontmatter
   (title, aliases, tags, status) of every page in `docs/knowledge/`. Read the pending entries by line
   range from `docs/JOURNAL_INDEX.md`. Output a plan: for each pending entry, which existing pages it
   touches, which new pages it needs, which beliefs it confirms, contradicts, or adds. Prefer updating an
   existing page over minting a near-duplicate; reuse an existing slug when an alias matches.
3. **Pass two: proposals.** Read only the pages named in the plan. Write to
   `docs/knowledge/_proposals/<YYYY-MM-DD>/`:
   - one full replacement body per touched or new page, frontmatter per SCHEMA.md, `sources:` listing
     entry IDs, a dated `## History` line per change, `confirmed:` set to today;
   - `BELIEFS.md` full replacement, within its line cap, every line citing IDs, with a `REMOVED:` block at
     the bottom naming each dropped line and why;
   - `GLOSSARY.additions.md` with new or changed term lines;
   - `CONTRADICTIONS.additions.md` with `- <date> open — [a] vs [b] — why` lines for every conflict you
     could not resolve by marking the older claim superseded. Do not merge conflicting claims silently.
   - `PLAN.md`: the pass-one plan, plus the exact `mark` command for step 5.
4. **Show the human** a diff per file (`diff -u` against the live file) and the contradictions list.
   Stop here unless `--apply` was given and the human confirms in chat.
5. **On approval**, copy proposals over the live files, then record state:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal-compile-state.py" mark --ids <ids> --pages <slugs>`.
   Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/journal-lint.py"` and fix what it reports before finishing.
   Leave the proposals directory in place; it is the audit trail.

## Rules

- Raw entries are evidence, never inputs to rewrite. Quote IDs, never paraphrase an entry as if it were
  a page.
- A page whose claim is contradicted by a newer entry gets `status: superseded` and a `superseded_by:`,
  or the pair goes to CONTRADICTIONS. Nothing is deleted.
- Beliefs page: adding a line means removing one. Name it.
