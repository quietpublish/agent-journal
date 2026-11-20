#!/usr/bin/env bash
# journal-index.sh — Generate docs/JOURNAL_INDEX.md: a seek table over the
# journal's headings so an agent can find an entry without reading the file.
#
# Usage:
#   journal-index.sh                 Regenerate the index (atomic write)
#   journal-index.sh --check         Read-only: exit 0 fresh, 1 stale, 2 missing
#   journal-index.sh --stdout        Print the index, write nothing
#   journal-index.sh --project DIR   Repo root (default: $CLAUDE_PROJECT_DIR, git toplevel, cwd)
#   journal-index.sh --journal PATH --index PATH   Override either path
#
# WHY THIS EXISTS
# A long journal cannot be read into a context window, and grep only works when
# you already remember the vocabulary. The headings are the journal's own
# extraction layer, made addressable: read the index, pick entries, seek them by
# line range.
#
# STALENESS IS THE FAILURE MODE
# A committed index whose line ranges have drifted is worse than no index: it
# looks healthy and silently seeks the wrong bytes. The index records a sha256
# of the whole journal file and --check recomputes it. Any edit to JOURNAL.md
# invalidates the index; --check is the source of truth about freshness.
#
# Line ranges are inclusive and 1-based, ready for `sed -n 'START,ENDp'`.
# A `##` entry's range spans its `###` subsections; a `###` range stops at the
# next heading of any level.
#
# INPUT/OUTPUT COLLISION IS REFUSED
# --journal and --index resolving to the same file would replace the journal
# with its own index: render() reads the journal, then the temp file is renamed
# over the output path. With both paths equal, that rename destroys 820k tokens
# of irreplaceable prose whose only other copy is the last commit. The paths are
# therefore canonicalized (symlinked parent dirs included) and compared before
# any mode runs, plus a device:inode check when the output already exists, which
# catches a symlink or hard link pointing at the journal that path comparison
# alone would miss.

set -euo pipefail

repo_root=""
journal=""
index=""
mode="write"

while [ $# -gt 0 ]; do
  case "$1" in
    --project) repo_root="$2"; shift 2 ;;
    --check)   mode="check";  shift ;;
    --stdout)  mode="stdout"; shift ;;
    --journal) journal="$2";  shift 2 ;;
    --index)   index="$2";    shift 2 ;;
    -h|--help) sed -n '2,32p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "journal-index.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$repo_root" ]; then
  repo_root="${CLAUDE_PROJECT_DIR:-}"
  [ -n "$repo_root" ] || repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi
repo_root="$(cd "$repo_root" && pwd)"
[ -n "$journal" ] || journal="$repo_root/docs/JOURNAL.md"
[ -n "$index" ] || index="$repo_root/docs/JOURNAL_INDEX.md"

if [ ! -f "$journal" ]; then
  echo "journal-index.sh: no journal at $journal" >&2
  exit 2
fi

# Canonicalize a path whether or not it exists yet: resolve the parent directory
# physically (-P, so a symlinked parent cannot disguise a collision) and re-attach
# the basename. realpath(1) is not portable to a stock macOS shell, and the output
# path legitimately may not exist on a first run, so neither `realpath -e` nor
# `realpath -m` is available to lean on here.
canon() {
  local dir base
  dir="$(cd "$(dirname -- "$1")" 2>/dev/null && pwd -P)" || return 1
  base="$(basename -- "$1")"
  case "$base" in
    .|..) (cd "$1" 2>/dev/null && pwd -P) ;;
    *)    printf '%s/%s\n' "${dir%/}" "$base" ;;
  esac
}

# Refuse before ANY mode runs, --check included: comparing the journal's own sha
# against a fingerprint parsed out of the journal is meaningless, and refusing
# uniformly keeps one rule to remember rather than a per-mode exception.
canon_journal="$(canon "$journal")" || {
  echo "journal-index.sh: cannot resolve journal path: $journal" >&2
  exit 2
}
canon_index="$(canon "$index")" || {
  echo "journal-index.sh: cannot resolve index path: $index (does its directory exist?)" >&2
  exit 2
}

collision=""
[ "$canon_journal" = "$canon_index" ] && collision="same path"
# A symlink or hard link at the output path can name the journal while the two
# path strings differ. Bash's -ef compares device/inode and follows symlinks on
# both macOS and Linux. Do not combine BSD/GNU stat probes with ||: GNU stat -f
# can emit filesystem details before failing, contaminating the fallback value
# with a pathname and making two names for the same file compare unequal.
if [ -z "$collision" ] && [ "$journal" -ef "$index" ]; then
  collision="same file (link or symlink)"
fi

if [ -n "$collision" ]; then
  echo "journal-index.sh: refusing to write the index over the journal — $collision" >&2
  echo "  journal: $journal -> $canon_journal" >&2
  echo "  index:   $index -> $canon_index" >&2
  echo "  The index is derived FROM the journal; writing one onto the other destroys it." >&2
  exit 2
fi

# shasum ships with perl (macOS, most Linux); minimal Linux images carry only
# coreutils sha256sum. Both print the digest first.
if command -v shasum >/dev/null 2>&1; then
  journal_sha="$(shasum -a 256 "$journal" | awk '{print $1}')"
else
  journal_sha="$(sha256sum "$journal" | awk '{print $1}')"
fi

# --check: compare the recorded fingerprint against the journal as it is now.
if [ "$mode" = "check" ]; then
  if [ ! -f "$index" ]; then
    echo "stale: no index at $index (run journal-index.sh)" >&2
    exit 2
  fi
  recorded="$(awk -F': ' '/^- source-sha256: /{print $2; exit}' "$index")"
  if [ "$recorded" = "$journal_sha" ]; then
    echo "fresh: $index matches $journal ($journal_sha)"
    exit 0
  fi
  echo "stale: $index was built from ${recorded:-<none>}, journal is now $journal_sha" >&2
  echo "       line ranges may point at the wrong bytes — run journal-index.sh" >&2
  exit 1
fi

render() {
  local rel_journal="${journal#"$repo_root"/}"
  awk -v src="$rel_journal" -v sha="$journal_sha" -v gen="$(date -u +%Y-%m-%dT%H:%M:%SZ)" '
    # "### " must be tested before "## " never matches it: "^## " requires a
    # space in the third column, so "### x" does not match it. Order is safe.
    /^## / || /^### / {
      n++
      hline[n] = NR
      hlev[n]  = ($0 ~ /^### /) ? 3 : 2
      htext[n] = $0
    }
    END {
      total = NR

      printf "# journal — index\n\n"
      printf "Seek table over `%s`. Generated by the journal plugin (`journal-index.sh`); do not hand-edit.\n\n", src
      printf "Pull an entry with its line range, e.g. `sed -n '\''9,24p'\'' %s`.\n", src
      printf "Ranges are inclusive. A `##` range includes its `###` subsections.\n\n"
      printf "**Verify freshness before trusting a range:** `journal-index.sh --check`.\n"
      printf "Any edit to the journal body shifts every later range while leaving the headings\n"
      printf "identical, so a stale index reads as healthy. The fingerprint below is the check.\n\n"
      printf "- source: `%s`\n", src
      printf "- source-sha256: %s\n", sha
      printf "- source-lines: %d\n", total
      printf "- generated: %s\n\n", gen

      # Count entries and subsections for the summary line.
      for (i = 1; i <= n; i++) { if (hlev[i] == 2) entries++; else subs++ }
      printf "- entries (`##`): %d\n", entries
      printf "- subsections (`###`): %d\n\n", subs
      printf "---\n\n"
      printf "```\n"
      printf "%-14s %-11s %-36s %s\n", "LINES", "DATE", "ID", "HEADLINE"
      printf "```\n\n"

      for (i = 1; i <= n; i++) {
        # A level-2 entry runs to the next level-2 heading, so it carries its
        # own subsections. A level-3 stops at the next heading of any level.
        end = total
        for (j = i + 1; j <= n; j++) {
          if (hlev[i] == 2 && hlev[j] != 2) continue
          end = hline[j] - 1
          break
        }

        text = htext[i]
        date = ""
        seq  = ""

        if (hlev[i] == 2) {
          sub(/^## /, "", text)
          # Explicit digit classes rather than {4} — BSD awk on macOS is not
          # reliable about ERE interval expressions.
          if (match(text, /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/)) {
            date = substr(text, RSTART, RLENGTH)
            text = substr(text, RSTART + RLENGTH)
            sub(/^ /, "", text)
          }
          if (match(text, /^\(latest\+[0-9]+\)/)) {
            seq  = substr(text, RSTART + 8, RLENGTH - 9)
            text = substr(text, RSTART + RLENGTH)
            sub(/^ /, "", text)
          }
          if (match(text, /^\(j-[0-9a-f]+\)/)) {
            seq  = substr(text, RSTART + 1, RLENGTH - 2)
            text = substr(text, RSTART + RLENGTH)
            sub(/^ /, "", text)
          }
          sub(/^(— |- |-- )/, "", text)
          printf "%-14s %-11s %-36s %s\n", hline[i] "-" end, (date == "" ? "-" : date), (seq == "" ? "-" : (seq ~ /^j-/ ? seq : "+" seq)), text
        } else {
          sub(/^### /, "", text)
          printf "  %-12s %-11s %-36s  ↳ %s\n", hline[i] "-" end, "", "", text
        }
      }
    }
  ' "$journal"
}

if [ "$mode" = "stdout" ]; then
  render
  exit 0
fi

# Temp file + rename in the same directory: the rename is atomic on POSIX, so a
# reader never sees a half-written index. Not routed through atomic-write.sh —
# that wrapper is JSON-oriented and runs artifact schema validation on its
# target, which has nothing to say about a markdown seek table.
tmp="$index.tmp.$$"
trap 'rm -f "$tmp"' EXIT
render > "$tmp"
mv "$tmp" "$index"
trap - EXIT

printf 'wrote %s (%s lines) from %s\n' \
  "${index#"$repo_root"/}" "$(wc -l < "$index" | tr -d ' ')" "${journal#"$repo_root"/}"
