#!/usr/bin/env bash
# pre-compact.sh — before the context window is compacted, remind the agent to
# journal anything worth keeping from this session. Compaction is where
# unrecorded realizations die.
set -uo pipefail
root="${CLAUDE_PROJECT_DIR:-$PWD}"
[ -f "$root/docs/JOURNAL.md" ] || exit 0
python3 - <<'PY'
import json
msg = ("Context is about to be compacted. If this session produced a decision, a lesson, "
       "or a surprising result that is not yet in docs/JOURNAL.md, draft it now with the "
       "/journal skill so it survives compaction. Do not journal routine progress.")
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreCompact", "additionalContext": msg}}))
PY
