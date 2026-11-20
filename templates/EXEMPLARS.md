# Voice exemplars

Human-written. Every draft is anchored to these, never to recent entries, so
one session's phrasing cannot become the next session's style. Keep two to
four. Replace only by hand.

## 2026-03-30 — [lesson] Headless mode works, so the product story simplifies

The isolation matrix on 03-29 showed all four CLI variants stalling in
non-interactive mode. We spent the session building a separate headless engine.
Then we re-tested `claude -p` with the current version and the plugin loaded.

It worked. 45 seconds, 3 files edited, tests added.

The lesson: test assumptions against current reality, not against last week's
failure. The matrix was correct when it ran. The platform moved.

Keeper: re-run the failing experiment before building around the failure.

## 2026-03-29 — [decision] The artifact is the handoff, not the conversation

Carrying investigation transcripts between agent phases causes context bloat
and convergence failures. The planner's forty reads pollute the generator's
context. The generator's reasoning pollutes the evaluator's judgment.

The fix: file-based handoffs with fresh context per phase. The planner writes
`contract.json`. The generator reads it fresh. The evaluator reads it plus the
diff, fresh. The conversation is disposable; the artifact is the handoff.

Keeper: pass files between phases, not transcripts.
