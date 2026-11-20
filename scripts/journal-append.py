#!/usr/bin/env python3
"""journal-append.py — append an entry to docs/JOURNAL.md (append-only, newest first).

The journal is the project's institutional memory: append-only, written at the moment of
realization, and an existing entry is NEVER edited (CLAUDE.md operator rule). This
inserts a NEW entry at the top of the entries — right before the current newest
dated entry, after the meta "How to use" section — then atomic-writes. It never
touches an existing entry.

The agent DRAFTS an entry; the human reviews, edits, and commits it through THIS
canonical writer. The agent never appends without approval — single writer.

Usage:
  echo '<entry markdown>' | journal-append.py [--project <repo>] [--journal <path>] [--apply]

--project defaults to $CLAUDE_PROJECT_DIR, then the git toplevel, then cwd.
The entry must begin with "## YYYY-MM-DD — [type] Title". The writer inserts a
stable UUID-based j-ID into that heading. Do not supply a sequence number.
Dry-run by default (its ID is provisional); --apply writes. Output is one JSON
status line including entry_id. After a successful --apply the seek table
docs/JOURNAL_INDEX.md is regenerated (journal-index.sh beside this script),
best-effort, so the index is never one entry behind the writer.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import date
from pathlib import Path

DATED_HEADING = re.compile(r"^## \d{4}-\d{2}-\d{2}")


def identify_entry(entry: str) -> tuple[str, str]:
    """Assign a worktree-independent identity; never renumber existing prose."""
    heading, separator, body = entry.partition("\n")
    match = re.fullmatch(r"## (\d{4}-\d{2}-\d{2})\s+—\s+(.+)", heading)
    if not match:
        raise ValueError("use '## YYYY-MM-DD — [type] Title'; the writer assigns the entry ID (do not hand-number)")
    if not re.match(r"\[(decision|lesson|status|correction|sweep)\]\s+\S", match[2]):
        raise ValueError("title must start with a type tag: [decision] [lesson] [status] [correction] [sweep]")
    if match[2].startswith("[correction]") and not re.search(r"^Supersedes:\s*j-[0-9a-f]{32}", body, re.M):
        raise ValueError("a [correction] entry must carry a 'Supersedes: j-<id>' line")
    date.fromisoformat(match[1])
    if any(DATED_HEADING.match(line) for line in body.splitlines()):
        raise ValueError("append one dated journal entry per invocation")
    entry_id = "j-" + uuid.uuid4().hex
    return f"## {match[1]} ({entry_id}) — {match[2]}" + separator + body, entry_id


def resolve_project(explicit: str | None) -> str:
    if explicit:
        return os.path.abspath(explicit)
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return os.path.abspath(env)
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, check=True).stdout.strip()
        if top:
            return top
    except Exception:  # noqa: BLE001
        pass
    return os.getcwd()


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")



def _regenerate_index(project: Path, journal: Path) -> None:
    """Refresh docs/JOURNAL_INDEX.md after an append — best-effort.

    The index is keyed on the journal's sha256, so the append that just landed
    made it stale. Never changes this writer's exit status: a failed regen
    leaves a stale index, which `journal-index.sh --check` reports.
    """
    script = Path(__file__).resolve().parent / "journal-index.sh"
    if not script.exists():
        return
    try:
        subprocess.run(
            ["bash", str(script), "--journal", str(journal),
             "--index", str(journal.with_name("JOURNAL_INDEX.md"))],
            cwd=str(project), check=False, timeout=60,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001 — best-effort by design
        pass

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None, help="repo root (default: $CLAUDE_PROJECT_DIR, git toplevel, cwd)")
    ap.add_argument("--journal", default=None, help="journal path (default: <project>/docs/JOURNAL.md)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    project = Path(resolve_project(args.project))

    entry = sys.stdin.read().strip()
    if not entry:
        emit({"status": "error", "error": "empty entry"})
        return 1
    try:
        entry, entry_id = identify_entry(entry)
    except ValueError as exc:
        emit({"status": "error", "error": str(exc)})
        return 1

    journal = (Path(args.journal) if args.journal else project / "docs" / "JOURNAL.md").resolve()
    if not journal.exists():
        emit({"status": "error", "error": f"JOURNAL.md not found at {journal}"})
        return 1

    # Lock identity is the target journal, not its replaceable inode. Keep the
    # lock file: unlinking after release could leave concurrent waiters holding
    # different inodes. OS advisory locks are released on process death.
    # Beside the canonical target, so different per-session TMPDIR settings
    # cannot split one journal's writers across independent locks.
    lock_path = journal.with_name(f".{journal.name}.append.lock")
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _append_entry(journal, entry, entry_id=entry_id, apply=args.apply, project=project)


def _append_entry(journal: Path, entry: str, *, entry_id: str, apply: bool, project: Path) -> int:
    """Called under the target journal lock, including derived-index refresh."""
    text = journal.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Insert before the first DATED entry heading — the newest entry. (The meta
    # section's "## How to use this file" is not dated, so it's never matched.)
    insert_at = next(
        (i for i, line in enumerate(lines) if DATED_HEADING.match(line)),
        len(lines),  # no dated entry yet → append at end
    )

    block = entry.rstrip() + "\n\n"
    new_text = "".join(lines[:insert_at] + [block] + lines[insert_at:])

    if not apply:
        emit({"status": "would_append", "insert_line": insert_at + 1,
              "entry_chars": len(entry), "entry_id": entry_id})
        return 0

    fd, tmp = tempfile.mkstemp(dir=str(journal.parent), prefix=".journal.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp, journal)
    except Exception as e:  # noqa: BLE001
        try:
            os.unlink(tmp)
        except OSError:
            pass
        emit({"status": "error", "error": str(e)})
        return 1

    _regenerate_index(project, journal)
    emit({"status": "appended", "insert_line": insert_at + 1, "entry_id": entry_id})
    return 0


if __name__ == "__main__":
    sys.exit(main())
