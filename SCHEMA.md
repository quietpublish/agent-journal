# Journal schema

This file is the contract. The skills read it, the lint enforces the parts that
can be checked deterministically, and the compile step treats it as the spec for
what it may write. Change the schema here first, then the tools.

## Files in a journaled repo

| Path | Layer | Who writes | Rule |
|---|---|---|---|
| `docs/JOURNAL.md` | raw, immutable | agent drafts, human approves, `journal-append.py` writes | append-only, newest first, entries never edited |
| `docs/JOURNAL_INDEX.md` | derived | `journal-index.sh` | regenerated on every append; carries the journal's sha256 |
| `.journal-search.db` | derived, untracked | `journal-search.py --build` | local Ollama embeddings; refuses a stale index |
| `docs/GLOSSARY.md` | curated | human, with agent proposals | one line per project term; the jargon gate |
| `docs/BELIEFS.md` | rewritten | compile step proposes, human approves | current load-bearing claims, hard line cap, every line cites entry IDs |
| `docs/knowledge/*.md` | rewritten | compile step proposes, human approves | one page per concept; frontmatter below |
| `docs/knowledge/CONTRADICTIONS.md` | append-only | compile step | open and resolved contradictions between entries or pages |
| `docs/knowledge/.compile-state.json` | derived | `journal-compile-state.py` | which entry IDs have been folded into pages |

## Entry format

```
## YYYY-MM-DD (j-<32 hex>) — [type] Title that states the finding in plain words

First sentence is the lesson or decision, readable with zero project context.
Body under 250 words. Say why, not what changed; git has the what.
Keep failures beside wins. Cite evidence by path or commit, not by memory.

Supersedes: j-<id>            (optional, when this entry corrects an earlier one)
Keeper: one-line lesson worth carrying forward   (optional)
```

- The writer assigns the ID. Never hand-number.
- `[type]` is one of `decision`, `lesson`, `status`, `correction`, `sweep`.
  A `correction` must carry `Supersedes:`.
- Entries are never edited. A wrong entry gets a `correction` entry above it.
- The forward-look does not live here. Put "what next" in a living doc the
  repo already has (`NEXT_SESSION.md`, `TODO.md`, an issue tracker).

## Voice standard

Drift is the failure mode: prior LLM entries become the exemplar for the next
one, and each rewrite compounds. The rules below are re-applied on every write.

1. Title states the finding. Not a metaphor, not an aphorism.
2. First sentence is the lesson. A reader who stops there knows the point.
3. Under 250 words. Longer belongs in `docs/research/` with a link.
4. No project term without a glossary entry. A new term is introduced in
   bold on first use and added to `docs/GLOSSARY.md` in the same change.
5. One term per concept. Use the glossary's spelling, not a synonym.
6. Anchor to the exemplars in `templates/EXEMPLARS.md`, not to recent entries.
7. Cold-reader check before append: restate the entry in plain words and list
   undefined terms. If any term is undefined, fix the entry or the glossary.

## Glossary format

```
- **term** — one-sentence definition. First seen: j-<id>. Aliases: other, spellings.
```

Lint flags: a bold term in a journal entry with no glossary line; a glossary
term whose definition text changed since the last compile (drift); two glossary
terms sharing an alias.

## Knowledge page frontmatter

```yaml
---
title: Concept name
aliases: [other names]
tags: [area]
status: current        # current | superseded | contested
supersedes: []         # page slugs or entry IDs this page replaces
superseded_by: null
sources: [j-..., j-...]   # entry IDs, not dates
confirmed: YYYY-MM-DD  # last date a human confirmed the page still holds
---
```

Body: `## Key points` (3–5 bullets, each citing an entry ID), `## Detail`,
`## History` (dated lines: what changed and which entry drove it), `## Related`.

Lint flags: broken `[[link]]`, orphan page, missing required field, bad
`status` value, `superseded_by` that does not resolve, `confirmed` older than
90 days.

## Beliefs page

`docs/BELIEFS.md` is the ten-to-forty-line answer to "what does this project
currently hold true that is not in the code". Hard cap set in the file header
(default 60 lines). Adding a line means removing one and naming the removed
line in the commit message. Every line cites at least one entry ID.

## Compile step

Monthly, or on demand. Deterministic part (`journal-compile-state.py`) lists
entries not yet folded in. Synthesis part (the `journal-compile` skill) runs two
passes: pass one reads the knowledge index and the new entries and names the
pages to load; pass two reads only those pages and writes proposals to
`docs/knowledge/_proposals/<date>/`. Nothing is written to a live page without a
human saying so. A contradiction between a new entry and a live page is never
silently merged: the page gets a `## History` line and the old claim is marked
superseded, or the pair is appended to `CONTRADICTIONS.md` as open.

## Commit trailers

Commit-grain decisions use git trailers so they stay greppable with plain git
and queryable with the optional `lore-protocol` CLI. See
`templates/COMMIT_TRAILERS.md`.
