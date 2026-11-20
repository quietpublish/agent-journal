#!/usr/bin/env bash
# journal-init.sh — scaffold a journal into a repo. Idempotent: never overwrites
# an existing file. Creates docs/JOURNAL.md, docs/GLOSSARY.md, docs/BELIEFS.md,
# docs/knowledge/, adds .journal-search.db and the append lock to .gitignore, and prints the
# AGENTS.md / CLAUDE.md snippet to paste.
#
# Usage: journal-init.sh [--project DIR] [--name "Project name"]
set -euo pipefail
plugin_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
root=""; name=""
while [ $# -gt 0 ]; do
  case "$1" in
    --project) root="$2"; shift 2 ;;
    --name) name="$2"; shift 2 ;;
    -h|--help) sed -n '2,8p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "journal-init.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$root" ] || root="${CLAUDE_PROJECT_DIR:-}"
[ -n "$root" ] || root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
root="$(cd "$root" && pwd)"
[ -n "$name" ] || name="$(basename "$root")"

mkdir -p "$root/docs/knowledge"
place() { # place TEMPLATE DEST
  if [ -e "$2" ]; then echo "keep   ${2#"$root"/}"; return; fi
  sed "s/{{PROJECT}}/$name/g" "$plugin_root/templates/$1" > "$2"
  echo "create ${2#"$root"/}"
}
place JOURNAL.md "$root/docs/JOURNAL.md"
place GLOSSARY.md "$root/docs/GLOSSARY.md"
place BELIEFS.md "$root/docs/BELIEFS.md"
place CONTRADICTIONS.md "$root/docs/knowledge/CONTRADICTIONS.md"
if ! grep -qs '^\.journal-search\.db$' "$root/.gitignore" 2>/dev/null; then
  printf '\n# journal plugin: local embeddings (rebuildable) and the append lock\n.journal-search.db\ndocs/.JOURNAL.md.append.lock\n' >> "$root/.gitignore"
  echo "append .gitignore"
fi
bash "$plugin_root/scripts/journal-index.sh" --project "$root" >/dev/null && echo "create docs/JOURNAL_INDEX.md"

echo
echo "Paste into AGENTS.md or CLAUDE.md:"
echo "-----"
sed "s/{{PROJECT}}/$name/g" "$plugin_root/templates/AGENTS-snippet.md"
echo "-----"
echo "Optional commit trailers: see $plugin_root/templates/COMMIT_TRAILERS.md"
