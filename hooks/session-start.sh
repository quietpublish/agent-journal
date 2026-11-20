#!/usr/bin/env bash
# session-start.sh — inject docs/BELIEFS.md plus the newest N journal entries
# (heading + first paragraph) as additionalContext. Silent when the repo has no
# journal, so unjournaled repos pay nothing. Never injects the whole journal:
# context files raise cost without generally raising task success (arXiv 2602.11988), so the
# budget here is small and capped.
set -uo pipefail
root="${CLAUDE_PROJECT_DIR:-$PWD}"
journal="$root/docs/JOURNAL.md"
[ -f "$journal" ] || exit 0

# Session marker for the stop nudge: "did the journal change after this point".
input="$(cat 2>/dev/null || true)"
sid="$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("session_id",""))' 2>/dev/null || true)"
# It also records the working tree as it stood, so a tree that was already dirty
# when the session began is not mistaken for work done in it.
if [ -n "$sid" ]; then
  git -C "$root" status --porcelain 2>/dev/null | grep -v 'docs/JOURNAL' \
    > "${TMPDIR:-/tmp}/journal-nudge-${sid}.session" 2>/dev/null || true
fi

n="${JOURNAL_INJECT_ENTRIES:-3}"
cap="${JOURNAL_INJECT_CHARS:-12000}"
plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

out=""
if [ -f "$root/docs/BELIEFS.md" ]; then
  out+="## Current beliefs (docs/BELIEFS.md)"$'\n'
  out+="$(cat "$root/docs/BELIEFS.md")"$'\n\n'
fi

out+="## Newest journal entries (docs/JOURNAL.md, newest first)"$'\n'
out+="$(awk -v n="$n" '
  /^## [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/ {
    if (c >= n) exit
    c++; print; inpara=1; blank=0; next
  }
  c > 0 && inpara {
    if ($0 ~ /^[[:space:]]*$/) { if (blank) { inpara=0 } else { blank=1; print "" } ; next }
    print; blank=0
  }
' "$journal")"$'\n\n'

stale=""
if [ -x "$plugin_root/scripts/journal-index.sh" ]; then
  if ! bash "$plugin_root/scripts/journal-index.sh" --project "$root" --check >/dev/null 2>&1; then
    stale="Seek table docs/JOURNAL_INDEX.md is stale or missing; regenerate with scripts/journal-index.sh before trusting line ranges."$'\n'
  fi
fi

out+="Journal rules: read more entries with the seek table (docs/JOURNAL_INDEX.md) or the /journal skill's search. Append an entry with /journal when a decision is made, a lesson is learned, or a dogfood surprises you. Entries are never edited; corrections are new entries. ${stale}"

out="${out:0:$cap}"
python3 - "$out" <<'PY'
import json, sys
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": sys.argv[1]}}))
PY
