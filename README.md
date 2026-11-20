# journal — a Claude Code plugin

A human-approved, append-only journal for any repo, plus the consolidation
layer that keeps it useful past a few hundred entries.

Git records what changed. The journal records why: the decisions, pivots and
lessons an agent would otherwise rediscover every session. The agent drafts an
entry, you approve it, and a script appends it. Nothing is ever edited; a wrong
entry gets a correction entry that names what it supersedes.

## Install

```
/plugin marketplace add quietpublish/agent-journal
/plugin install journal@agent-journal
```

Then, in the repo you want to journal:

```
/journal:journal-init
```

That scaffolds the files below, never overwriting one that exists, and prints a
short snippet to paste into `AGENTS.md` or `CLAUDE.md`.

### Requirements

- macOS or Linux. The writer uses POSIX file locks, so Windows needs WSL.
- `python3` (standard library only), `bash`, `git`.
- For search only: [Ollama](https://ollama.com) running locally, with
  `ollama pull nomic-embed-text`. Everything else works without it.

## What it gives a repo

| File | Role |
|---|---|
| `docs/JOURNAL.md` | raw evidence: dated entries, newest first, never edited, stable `j-` IDs |
| `docs/JOURNAL_INDEX.md` | seek table with line ranges, fingerprinted to the journal |
| `docs/GLOSSARY.md` | one line per project term; the gate against private jargon |
| `docs/BELIEFS.md` | the short current picture, rewritten monthly, hard line cap |
| `docs/knowledge/` | one page per concept, frontmatter with status and supersession |
| `.journal-search.db` | local Ollama embeddings, untracked; search by meaning, nothing leaves the machine |

An entry looks like this:

```
## 2026-03-29 (j-<32 hex>) — [decision] The artifact is the handoff, not the conversation

Carrying investigation transcripts between agent phases causes context bloat
and convergence failures. ...

Keeper: pass files between phases, not transcripts.
```

The full format, the voice rules and what the lint checks are in [SCHEMA.md](SCHEMA.md).

## Skills

Plugin skills are namespaced, so the full names are `journal:<skill>`.

- `/journal:journal`: draft an entry with a cold-reader check, get approval,
  append. Also `/journal:journal search <query>` and `/journal:journal lint`.
  Claude can invoke this one on its own when a decision or lesson comes up.
- `/journal:journal-compile`: monthly. Folds pending entries into the beliefs
  page and knowledge pages as proposals under `docs/knowledge/_proposals/`.
  Nothing live changes without a yes. User-invoked only.
- `/journal:journal-init`: scaffold the files and print the `AGENTS.md`
  snippet. User-invoked only.

## Hooks

All three are silent in a repo that has no `docs/JOURNAL.md`.

- **SessionStart** injects `docs/BELIEFS.md` and the newest three entries
  (heading and first paragraph), capped at 12,000 characters.
- **PreCompact** reminds the agent to journal anything worth keeping before
  context is compacted.
- **Stop** blocks once per session, with a reminder, when the working tree's
  git status changed since the session started and the journal did not. The
  agent can answer "nothing worth recording" and stop again.

| Variable | Default | Effect |
|---|---|---|
| `JOURNAL_STOP_NUDGE` | `1` | `0` disables the Stop reminder |
| `JOURNAL_INJECT_ENTRIES` | `3` | entries injected at session start |
| `JOURNAL_INJECT_CHARS` | `12000` | cap on injected characters |
| `JOURNAL_LEGACY_BEFORE` | unset | date; lint demotes findings on older entries to info |
| `JOURNAL_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model for search |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama base URL |

## Scripts (usable without Claude)

```
scripts/journal-init.sh          [--project DIR] [--name NAME]           scaffold
scripts/journal-append.py        echo '<entry>' | ... [--apply]          canonical writer, assigns IDs
scripts/journal-index.sh         [--check|--stdout]                      seek table, sha-fingerprinted
scripts/journal-search.py        --build | --query TEXT | --check        Ollama embeddings in sqlite
scripts/journal-lint.py          [--json] [--summary] [--legacy-before D] deterministic checks, see SCHEMA.md
scripts/journal-compile-state.py pending | mark | status                 which entries are folded in
```

All resolve the repo from `--project`, then `$CLAUDE_PROJECT_DIR`, then
`git rev-parse --show-toplevel`, then the current directory.
`journal-append.py` is a dry run without `--apply`.

## Adopting it in a repo that already has a journal

`journal-init.sh` keeps an existing `docs/JOURNAL.md`. Entries written before
the plugin have no `j-` IDs or type tags, and they are immutable, so pass
`--legacy-before YYYY-MM-DD` to the lint (or set `JOURNAL_LEGACY_BEFORE`) to
report them as info instead of errors. The compile step keys those entries by
date and title hash, so they can still be folded into beliefs and knowledge
pages.

## Voice standard

Title states the finding. First sentence is the lesson. Under 250 words. No
project term without a glossary line. Anchor to `templates/EXEMPLARS.md`, not
to recent entries, so one session's phrasing cannot become the next session's
style. Full rules in [SCHEMA.md](SCHEMA.md).

## Lineage

This came out of six months and 1,245 entries of one project's journal, then a
survey of what else exists. The pieces are borrowed:

- The rewritten wiki layer over raw sources follows Andrej Karpathy's
  [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
- Commit trailers follow the Lore protocol
  ([arXiv 2603.15566](https://arxiv.org/abs/2603.15566)); see
  `templates/COMMIT_TRAILERS.md`.
- Consolidation runs on a cadence instead of after every interaction because
  continuously re-consolidated memory can fall below a no-memory baseline
  ([arXiv 2605.12978](https://arxiv.org/abs/2605.12978)).
- Supersession is explicit because models act on outdated memories unreliably
  ([arXiv 2605.06527](https://arxiv.org/abs/2605.06527)).
- The session-start injection is small and capped because repository context
  files raise cost without generally raising task success
  ([arXiv 2602.11988](https://arxiv.org/abs/2602.11988)).

## License

MIT. See [LICENSE](LICENSE).
