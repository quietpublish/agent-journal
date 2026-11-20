#!/usr/bin/env bash
# stop-nudge.sh — enforce-once nudge. When the working tree's git status changed
# since session start and the journal did not, block the first stop with a reminder. A
# marker file keyed by session id guarantees one nudge per session, and the
# stop_hook_active flag guards against loops. Set JOURNAL_STOP_NUDGE=0 to
# disable. Fail-open on any error: a nudge must never trap a session.
set -uo pipefail
[ "${JOURNAL_STOP_NUDGE:-1}" = "0" ] && exit 0
root="${CLAUDE_PROJECT_DIR:-$PWD}"
journal="$root/docs/JOURNAL.md"
[ -f "$journal" ] || exit 0

input="$(cat 2>/dev/null || true)"
active="$(printf '%s' "$input" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(str(d.get("stop_hook_active", False)).lower())' 2>/dev/null || echo false)"
[ "$active" = "true" ] && exit 0
sid="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("session_id",""))' 2>/dev/null || true)"
[ -n "$sid" ] || exit 0

marker="${TMPDIR:-/tmp}/journal-nudge-${sid}"
[ -f "$marker" ] && exit 0

# Only nudge when there is code change to reflect on.
if ! git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then exit 0; fi
dirty="$(git -C "$root" status --porcelain 2>/dev/null | grep -v 'docs/JOURNAL' || true)"
[ -n "$dirty" ] || exit 0

# If the journal was touched in this session, no nudge. Without a session
# marker (session-start hook did not run) there is no baseline: fail open.
[ -f "$marker.session" ] || exit 0
# The marker holds the tree's status at session start. Same status now means
# this session changed nothing new; a tree that was dirty on arrival stays quiet.
[ "$dirty" = "$(cat "$marker.session" 2>/dev/null)" ] && exit 0
if [ "$journal" -nt "$marker.session" ]; then exit 0; fi

touch "$marker"
python3 - <<'PY'
import json
print(json.dumps({"decision": "block",
  "reason": "Files changed this session but docs/JOURNAL.md did not. If a decision or lesson came out of this work, run /journal to draft an entry. If nothing is worth recording, say so in one line and stop again."}))
PY
