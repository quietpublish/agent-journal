#!/usr/bin/env python3
"""journal-lint.py — deterministic checks over a journaled repo. Read-only.

Usage:
  journal-lint.py [--project DIR] [--json] [--strict] [--legacy-before YYYY-MM-DD] [--summary]

--legacy-before (or env JOURNAL_LEGACY_BEFORE): entries dated before this were
written before the plugin's format existed. Their J1/J3/J6 findings become
"info" and G1 is skipped, so a long-lived journal can adopt the plugin without
686 errors it will never fix (entries are immutable). New entries are held to
the full rules. --summary prints counts by code only.

Exit 0 clean, 1 warnings only, 2 errors (or 1 if --strict turns warnings into errors).

Checks (see SCHEMA.md):
  journal   J1 every dated heading carries a (j-<32hex>) ID          error
            J2 IDs are unique                                        error
            J3 heading carries a [type] tag                          warning (legacy entries)
            J4 [correction] entries carry Supersedes:                error
            J5 Supersedes: targets resolve to an existing entry      error
            J6 entry body over 250 words                             warning
  glossary  G1 bold **term** in an entry with no glossary line       warning
            G2 two glossary terms share an alias                     error
  knowledge K1 broken [[link]]                                       error
            K2 orphan page (no inbound [[link]])                     warning
            K3 missing required frontmatter field                    error
            K4 bad status value                                      error
            K5 superseded_by does not resolve                        error
            K6 confirmed older than 90 days                          warning
  beliefs   B1 BELIEFS.md exceeds its declared line cap              error
            B2 a beliefs line cites no entry ID                      warning
  index     I1 JOURNAL_INDEX.md stale or missing                     warning
            I2 session-start injection would exceed budget           warning

The LLM contradiction pass is not here; it lives in the journal-compile skill,
which emits `CONTRADICTION: [a] vs [b] - why` lines for a human to resolve.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2})(?: \((j-[0-9a-f]{32}|latest\+\d+)\))?(?: [0-9:]+ [A-Z]+)? — (.*)$")
TYPE_TAG = re.compile(r"^\[(decision|lesson|status|correction|sweep)\]\s")
ID_RE = re.compile(r"j-[0-9a-f]{32}")
# A citation is a j-ID or, for journals older than the plugin, a legacy `+NNN` label.
CITE_RE = re.compile(r"j-[0-9a-f]{32}|(?<![\w])\+\d{1,5}\b")
BOLD = re.compile(r"\*\*([^*\n]{2,40})\*\*")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
REQUIRED_FM = ("title", "status", "sources", "confirmed")
STATUSES = {"current", "superseded", "contested"}


def resolve_project(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, check=True).stdout.strip()
        if top:
            return Path(top)
    except Exception:  # noqa: BLE001
        pass
    return Path.cwd()


class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, code: str, sev: str, where: str, msg: str) -> None:
        self.items.append({"code": code, "severity": sev, "where": where, "message": msg})

    def errors(self) -> int:
        return sum(1 for i in self.items if i["severity"] == "error")

    def warnings(self) -> int:
        return sum(1 for i in self.items if i["severity"] == "warning")


def parse_entries(text: str) -> list[dict]:
    entries: list[dict] = []
    cur: dict | None = None
    for n, line in enumerate(text.splitlines(), 1):
        m = HEADING.match(line)
        if m:
            if cur:
                entries.append(cur)
            cur = {"line": n, "date": m.group(1), "id": m.group(2), "title": m.group(3), "body": []}
            continue
        if line.startswith("## ") and cur:
            entries.append(cur)
            cur = None
            continue
        if cur is not None:
            cur["body"].append(line)
    if cur:
        entries.append(cur)
    for e in entries:
        e["text"] = "\n".join(e["body"])
    return entries


def lint_journal(root: Path, rep: Report, legacy_before: str | None = None) -> tuple[list[dict], set[str]]:
    journal = root / "docs" / "JOURNAL.md"
    if not journal.exists():
        rep.add("J0", "error", "docs/JOURNAL.md", "no journal; run journal-init.sh")
        return [], set()
    entries = parse_entries(journal.read_text(encoding="utf-8"))
    ids: dict[str, int] = {}
    for e in entries:
        where = f"docs/JOURNAL.md:{e['line']}"
        legacy = bool(legacy_before and e["date"] < legacy_before)
        e["legacy"] = legacy
        soft = "info" if legacy else None
        if not e["id"] or not e["id"].startswith("j-"):
            rep.add("J1", soft or ("error" if not e["id"] else "warning"), where,
                    "heading has no j-ID" if not e["id"] else f"legacy id {e['id']}; leave as is, new entries get j-IDs")
        elif e["id"] in ids:
            rep.add("J2", "error", where, f"duplicate id {e['id']} (first at line {ids[e['id']]})")
        else:
            ids[e["id"]] = e["line"]
        if not TYPE_TAG.match(e["title"]):
            rep.add("J3", soft or "warning", where, "title lacks [type] tag")
        if e["title"].startswith("[correction]") and not re.search(r"^Supersedes:\s*j-", e["text"], re.M):
            rep.add("J4", "error", where, "[correction] without Supersedes:")
        words = len(re.findall(r"\S+", e["text"]))
        if words > 250:
            rep.add("J6", soft or "warning", where, f"entry body is {words} words (limit 250)")
    all_ids = set(ids)
    for e in entries:
        for m in re.finditer(r"^Supersedes:\s*(.+)$", e["text"], re.M):
            for target in ID_RE.findall(m.group(1)):
                if target not in all_ids:
                    rep.add("J5", "error", f"docs/JOURNAL.md:{e['line']}", f"Supersedes target {target} not found")
    return entries, all_ids


def parse_glossary(root: Path) -> dict[str, dict]:
    path = root / "docs" / "GLOSSARY.md"
    terms: dict[str, dict] = {}
    if not path.exists():
        return terms
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        # Two accepted shapes: the plugin's list line, and a markdown table row
        # whose first cell is the bold term (older glossaries use tables).
        m = re.match(r"^- \*\*([^*]+)\*\*\s+—\s+(.*)$", line) or \
            re.match(r"^\|\s*\*\*([^*]+)\*\*\s*\|\s*(.*?)\s*\|?\s*$", line)
        if not m:
            continue
        term = m.group(1).strip()
        rest = m.group(2)
        aliases = []
        am = re.search(r"Aliases:\s*(.+?)\.?$", rest)
        if am:
            aliases = [a.strip().lower() for a in am.group(1).split(",") if a.strip()]
        terms[term.lower()] = {"line": n, "aliases": aliases, "definition": rest}
    return terms


def lint_glossary(root: Path, entries: list[dict], rep: Report) -> None:
    terms = parse_glossary(root)
    known = set(terms)
    for t, meta in terms.items():
        known.update(meta["aliases"])
    seen_alias: dict[str, str] = {}
    for t, meta in terms.items():
        for a in meta["aliases"]:
            if a in seen_alias and seen_alias[a] != t:
                rep.add("G2", "error", f"docs/GLOSSARY.md:{meta['line']}", f"alias '{a}' shared by '{t}' and '{seen_alias[a]}'")
            seen_alias[a] = t
    for e in entries:
        if e.get("legacy"):
            continue
        for b in BOLD.findall(e["text"]):
            term = b.strip().lower()
            if term.endswith(":"):
                continue
            if len(term.split()) > 3:
                continue
            if term not in known:
                rep.add("G1", "warning", f"docs/JOURNAL.md:{e['line']}", f"bold term '{b}' has no glossary entry")


def parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm: dict = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm


def lint_knowledge(root: Path, all_ids: set[str], rep: Report) -> None:
    kdir = root / "docs" / "knowledge"
    if not kdir.exists():
        return
    pages = {p.stem: p for p in kdir.glob("*.md") if not p.name.startswith("_") and p.name != "CONTRADICTIONS.md"}
    inbound: dict[str, int] = {s: 0 for s in pages}
    for slug, p in pages.items():
        text = p.read_text(encoding="utf-8")
        where = f"docs/knowledge/{p.name}"
        fm = parse_frontmatter(text)
        for f in REQUIRED_FM:
            if f not in fm:
                rep.add("K3", "error", where, f"missing frontmatter field '{f}'")
        if fm.get("status") and fm["status"] not in STATUSES:
            rep.add("K4", "error", where, f"status '{fm['status']}' not in {sorted(STATUSES)}")
        sb = fm.get("superseded_by")
        if sb and sb not in ("null", "~", ""):
            if sb not in pages and sb not in all_ids:
                rep.add("K5", "error", where, f"superseded_by '{sb}' does not resolve")
        if fm.get("confirmed"):
            try:
                d = datetime.strptime(fm["confirmed"], "%Y-%m-%d").date()
                if (date.today() - d).days > 90 and fm.get("status", "current") == "current":
                    rep.add("K6", "warning", where, f"confirmed {fm['confirmed']} is over 90 days old")
            except ValueError:
                rep.add("K3", "error", where, f"confirmed '{fm['confirmed']}' is not YYYY-MM-DD")
        # Code spans are not links: bash `[[ ]]` conditionals in prose would otherwise read as [[]].
        scannable = re.sub(r"`[^`\n]*`", "", text)
        for link in WIKILINK.findall(scannable):
            target = link.strip()
            if not target:
                continue
            if target in pages:
                if target != slug:
                    inbound[target] += 1
            elif not ID_RE.fullmatch(target):
                rep.add("K1", "error", where, f"broken link [[{target}]]")
    for slug, n in inbound.items():
        if n == 0 and len(pages) > 1:
            rep.add("K2", "warning", f"docs/knowledge/{slug}.md", "orphan page: no inbound [[link]]")


def lint_beliefs(root: Path, rep: Report) -> None:
    path = root / "docs" / "BELIEFS.md"
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    cap = 60
    for line in lines[:10]:
        m = re.search(r"line-cap:\s*(\d+)", line)
        if m:
            cap = int(m.group(1))
    if len(lines) > cap:
        rep.add("B1", "error", "docs/BELIEFS.md", f"{len(lines)} lines, cap is {cap}")
    for n, line in enumerate(lines, 1):
        if line.startswith("- ") and not CITE_RE.search(line):
            rep.add("B2", "warning", f"docs/BELIEFS.md:{n}", "belief cites no entry ID")


def lint_index(root: Path, rep: Report) -> None:
    journal = root / "docs" / "JOURNAL.md"
    index = root / "docs" / "JOURNAL_INDEX.md"
    if not journal.exists():
        return
    if not index.exists():
        rep.add("I1", "warning", "docs/JOURNAL_INDEX.md", "missing; run journal-index.sh")
    else:
        sha = hashlib.sha256(journal.read_bytes()).hexdigest()
        head = index.read_text(encoding="utf-8")[:4096]
        m = re.search(r"^- source-sha256:\s*([0-9a-f]{64})", head, re.M)
        if not m or m.group(1) != sha:
            rep.add("I1", "warning", "docs/JOURNAL_INDEX.md", "stale; run journal-index.sh")
    beliefs = root / "docs" / "BELIEFS.md"
    budget = int(os.environ.get("JOURNAL_INJECT_CHARS", "12000"))
    size = len(beliefs.read_text(encoding="utf-8")) if beliefs.exists() else 0
    if size > budget * 0.6:
        rep.add("I2", "warning", "docs/BELIEFS.md", f"{size} chars; session-start budget is {budget}, beliefs should leave room for entries")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--legacy-before", default=os.environ.get("JOURNAL_LEGACY_BEFORE"))
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()
    root = resolve_project(args.project)
    rep = Report()
    entries, ids = lint_journal(root, rep, args.legacy_before)
    lint_glossary(root, entries, rep)
    lint_knowledge(root, ids, rep)
    lint_beliefs(root, rep)
    lint_index(root, rep)

    if args.summary:
        counts: dict[str, dict[str, int]] = {}
        for i in rep.items:
            counts.setdefault(i["code"], {}).setdefault(i["severity"], 0)
            counts[i["code"]][i["severity"]] += 1
        for code in sorted(counts):
            print(f"{code}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts[code].items())))
        print(f"\n{len(entries)} entries, {rep.errors()} errors, {rep.warnings()} warnings", file=sys.stderr)
    elif args.json:
        print(json.dumps({"project": str(root), "entries": len(entries), "errors": rep.errors(),
                          "warnings": rep.warnings(), "items": rep.items}, indent=2))
    else:
        for i in rep.items:
            if i["severity"] == "info":
                continue
            print(f"{i['where']}: {i['severity'].upper()} {i['code']}: {i['message']}")
        print(f"\n{len(entries)} entries, {rep.errors()} errors, {rep.warnings()} warnings", file=sys.stderr)
    if rep.errors():
        return 2
    if rep.warnings():
        return 1 if args.strict else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
