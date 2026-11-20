#!/usr/bin/env python3
"""journal-compile-state.py — the deterministic half of the compile step.

Usage:
  journal-compile-state.py pending   [--project DIR] [--since YYYY-MM-DD]
      Print entries not yet folded into docs/knowledge (JSON list, newest first).
  journal-compile-state.py mark      [--project DIR] --ids j-... [j-...] [--pages slug ...]
      Record that these entries were folded in (after the human approved the proposal).
  journal-compile-state.py status    [--project DIR]

State lives in docs/knowledge/.compile-state.json:
  {"compiled": {"<entry-id>": {"sha": "<sha256[:16] of entry text>", "at": "...", "pages": [...]}},
   "last_compile": "YYYY-MM-DD"}

Entries written before the plugin (no j-ID) are keyed as
`legacy-<date>-<sha8 of title>` so a long-lived journal can be compiled too.

An entry is pending when its ID is absent from the state or its text hash
changed (which should never happen in an append-only journal; if it does, the
lint is the place to notice, but the compile must not silently skip it).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from journal_lint import parse_entries, resolve_project  # type: ignore  # noqa: E402


def state_path(root: Path) -> Path:
    return root / "docs" / "knowledge" / ".compile-state.json"


def load(root: Path) -> dict:
    p = state_path(root)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"compiled": {}, "last_compile": None}


def save(root: Path, st: dict) -> None:
    p = state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def entry_key(e: dict) -> str:
    if e.get("id") and e["id"].startswith("j-"):
        return e["id"]
    return "legacy-" + e["date"] + "-" + hashlib.sha256(e["title"].encode("utf-8")).hexdigest()[:8]


def entry_sha(e: dict) -> str:
    return hashlib.sha256((e["title"] + "\n" + e["text"]).encode("utf-8")).hexdigest()[:16]


def cmd_pending(root: Path, since: str | None) -> int:
    journal = root / "docs" / "JOURNAL.md"
    if not journal.exists():
        print("no docs/JOURNAL.md", file=sys.stderr)
        return 2
    st = load(root)
    out = []
    for e in parse_entries(journal.read_text(encoding="utf-8")):
        if since and e["date"] < since:
            continue
        key = entry_key(e)
        rec = st["compiled"].get(key)
        if rec and rec.get("sha") == entry_sha(e):
            continue
        out.append({"id": key, "date": e["date"], "line": e["line"], "title": e["title"],
                    "words": len(e["text"].split()), "changed_since_compile": bool(rec)})
    print(json.dumps(out, indent=2))
    print(f"{len(out)} pending", file=sys.stderr)
    return 0


def cmd_mark(root: Path, ids: list[str], pages: list[str]) -> int:
    journal = root / "docs" / "JOURNAL.md"
    by_id = {entry_key(e): e for e in parse_entries(journal.read_text(encoding="utf-8"))}
    st = load(root)
    today = date.today().isoformat()
    for i in ids:
        if i not in by_id:
            print(f"unknown entry {i}", file=sys.stderr)
            return 2
        st["compiled"][i] = {"sha": entry_sha(by_id[i]), "at": today, "pages": pages}
    st["last_compile"] = today
    save(root, st)
    print(f"marked {len(ids)} entries compiled on {today}")
    return 0


def cmd_status(root: Path) -> int:
    st = load(root)
    print(f"project:      {root}")
    print(f"state:        {state_path(root)} ({'present' if state_path(root).exists() else 'absent'})")
    print(f"compiled:     {len(st['compiled'])} entries")
    print(f"last_compile: {st['last_compile']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["pending", "mark", "status"])
    ap.add_argument("--project", default=None)
    ap.add_argument("--since", default=None)
    ap.add_argument("--ids", nargs="*", default=[])
    ap.add_argument("--pages", nargs="*", default=[])
    a = ap.parse_args()
    root = resolve_project(a.project)
    if a.cmd == "pending":
        return cmd_pending(root, a.since)
    if a.cmd == "mark":
        if not a.ids:
            print("--ids required", file=sys.stderr)
            return 2
        return cmd_mark(root, a.ids, a.pages)
    return cmd_status(root)


if __name__ == "__main__":
    sys.exit(main())
