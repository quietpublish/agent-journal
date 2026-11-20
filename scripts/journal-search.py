#!/usr/bin/env python3
"""journal-search.py — semantic search over docs/JOURNAL.md entries.

Usage:
  journal-search.py --build            Embed every entry into the local index
  journal-search.py --query TEXT       Rank entries by meaning, print line ranges
  journal-search.py --check            Read-only: 0 fresh, 1 stale, 2 missing
  journal-search.py --status           Backend + index facts, no work

  --top N          How many hits to print (default 8)
  --journal PATH   --index PATH   --db PATH        Override any path
  --model NAME     Embedding model (default nomic-embed-text)
  --host URL       Ollama base URL (default http://localhost:11434)

WHY THIS EXISTS
journal-index.sh made the journal addressable: headlines, greppable. That answers "find the entry about the retry budget" when
you remember the words. It cannot answer "have we hit anything LIKE this",
because a project's vocabulary drifts and a plain-English search for a concept
misses every entry that names it the project's way. This is the half the
seek table cannot do: rank by meaning, then hand back the same inclusive line
ranges so the answer is still `sed -n 'START,ENDp' docs/JOURNAL.md`.

EVERYTHING IS LOCAL
Embeddings come from Ollama on localhost. No journal text leaves the machine —
which is the point, because the journal is the project's evidence record and
much of it exists nowhere else. There is no API-key path and no remote fallback, by
design: a fallback is how local-only quietly becomes not-local-only.

UNAVAILABLE IS NOT "NO MATCHES"
If Ollama is down, or the model is not pulled, or the index has not been built,
this exits non-zero and says which. It never prints an empty result set that
reads like "the journal is silent on that" — the failure mode agents keep
finding in its own instruments. Silence has to mean silence.

CHUNKING IS FREE, BUT NOT UNBOUNDED
Entry boundaries are not re-derived here. docs/JOURNAL_INDEX.md already carries
every entry's inclusive line range, so this reads that table and embeds exactly
those spans. Entries are not uniform, though: p50 is ~3.1k chars but p90 is
~5.4k and the longest is ~22k, and the embedding model refuses an input past
roughly 8-16k chars even with num_ctx raised (probed, not assumed). Truncating
to fit would silently drop the tail of the 29% of entries over 4k chars — and
the tail of an entry is usually where the finding gets qualified. So a
long entry is split into overlapping windows, each window is embedded, and a
query scores every window but reports each entry ONCE at its best window's
score. Recall on long entries is preserved and the unit of the answer stays the
entry, which is what the line range addresses. One consequence worth knowing: a stale seek table produces a
subtly wrong semantic index, since the spans would be cut at the wrong lines.
Both files therefore fingerprint the same journal sha256, and --build refuses
to run against a stale table rather than bake the drift in.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import math
import os
import re
import sqlite3
import struct
import sys
import urllib.error
import urllib.request

DEFAULT_MODEL = "nomic-embed-text"
DEFAULT_HOST = "http://localhost:11434"
def _project_root() -> str:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return os.path.abspath(env)
    try:
        import subprocess
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, check=True).stdout.strip()
        if top:
            return top
    except Exception:  # noqa: BLE001
        pass
    return os.getcwd()


ROOT = _project_root()

RANGE_RE = re.compile(r"^\s*(\d+)-(\d+)\s")
SHA_RE = re.compile(r"^- source-sha256:\s*([0-9a-f]{64})\s*$", re.M)


def die(msg: str, code: int = 2) -> None:
    print(f"journal-search.py: {msg}", file=sys.stderr)
    sys.exit(code)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def index_sha(index_path: str) -> str | None:
    with open(index_path, encoding="utf-8") as fh:
        head = fh.read(4096)
    m = SHA_RE.search(head)
    return m.group(1) if m else None


def parse_index(index_path: str) -> list[dict]:
    """Rows from the seek table: (start, end, date, seq, headline, level)."""
    entries = []
    with open(index_path, encoding="utf-8") as fh:
        for line in fh:
            m = RANGE_RE.match(line)
            if not m:
                continue
            start, end = int(m.group(1)), int(m.group(2))
            rest = line[m.end():].rstrip("\n")
            # A subsection row is indented and carries the ↳ marker; keep it,
            # but remember which it is so a hit can say so.
            level = 3 if "↳" in rest else 2
            rest = rest.replace("↳", " ")
            cols = rest.split()
            date = cols[0] if cols and re.match(r"^\d{4}-\d{2}-\d{2}$|^-$", cols[0]) else "-"
            seq = ""
            headline = rest.strip()
            if date != "-" or (cols and cols[0] == "-"):
                # Strip the two fixed columns off the front, whatever their width.
                headline = re.sub(r"^\s*\S+\s+\S+\s+", "", rest).strip()
                seq = cols[1] if len(cols) > 1 else ""
            entries.append(
                {"start": start, "end": end, "date": date, "seq": seq,
                 "headline": headline, "level": level}
            )
    return entries


def read_span(journal_lines: list[str], start: int, end: int) -> str:
    return "".join(journal_lines[start - 1:end])


# 6k chars sits safely under the probed ceiling: real prose tokenizes worse than
# synthetic filler, so the margin is deliberate. The overlap keeps a finding that
# straddles a window boundary from being split out of both windows.
CHUNK_CHARS = 6000
CHUNK_OVERLAP = 600


def chunk_text(text: str, size: int = CHUNK_CHARS,
               overlap: int = CHUNK_OVERLAP) -> list[str]:
    if len(text) <= size:
        return [text]
    step = size - overlap
    out = [text[i:i + size] for i in range(0, len(text), step)]
    # A trailing sliver adds a near-duplicate vector and no recall; fold it in.
    if len(out) > 1 and len(out[-1]) < overlap:
        out.pop()
    return out


def embed(texts: list[str], host: str, model: str) -> list[list[float]]:
    """One Ollama call per text. Errors are fatal and named, never empty vectors."""
    out = []
    url = f"{host.rstrip('/')}/api/embeddings"
    for text in texts:
        payload = json.dumps({"model": model, "prompt": text}).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            if e.code == 404:
                die(f"model {model!r} is not pulled — run: ollama pull {model}\n"
                    f"  ollama said: {detail}")
            die(f"ollama HTTP {e.code} from {url}: {detail}")
        except urllib.error.URLError as e:
            die(f"cannot reach ollama at {host} ({e.reason}) — is it running? "
                f"start it with: ollama serve")
        vec = body.get("embedding")
        if not vec:
            die(f"ollama returned no embedding for a {len(text)}-char input "
                f"(model {model!r}); refusing to store an empty vector")
        out.append(vec)
    return out


def pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def norm(vec: list[float]) -> list[float]:
    mag = math.sqrt(sum(v * v for v in vec))
    if mag == 0:
        die("refusing a zero-magnitude embedding — the backend returned garbage")
    return [v / mag for v in vec]


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS entries ("
        " start INTEGER, end INTEGER, date TEXT, seq TEXT,"
        " headline TEXT, level INTEGER, chunk INTEGER, vec BLOB)"
    )
    return conn


def meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def cmd_build(args, journal, index, db) -> int:
    jsha = sha256_file(journal)
    isha = index_sha(index)
    if isha is None:
        die(f"{index} carries no source-sha256 — regenerate it with journal-index.sh")
    if isha != jsha:
        die(f"seek table is stale ({isha[:12]} vs journal {jsha[:12]}) — its line "
            f"ranges would cut entries at the wrong lines and bake that into the "
            f"semantic index. Run journal-index.sh first.", 1)

    entries = parse_index(index)
    if not entries:
        die(f"no entries parsed from {index}")
    with open(journal, encoding="utf-8") as fh:
        lines = fh.readlines()

    print(f"embedding {len(entries)} entries via {args.model} at {args.host} ...",
          file=sys.stderr)
    conn = connect(db)
    conn.execute("DELETE FROM entries")
    done = 0
    chunks_written = 0
    for e in entries:
        body = read_span(lines, e["start"], e["end"])
        for ix, piece in enumerate(chunk_text(body)):
            vec = norm(embed([piece], args.host, args.model)[0])
            conn.execute(
                "INSERT INTO entries VALUES (?,?,?,?,?,?,?,?)",
                (e["start"], e["end"], e["date"], e["seq"], e["headline"],
                 e["level"], ix, pack(vec)),
            )
            chunks_written += 1
        done += 1
        if done % 100 == 0:
            print(f"  {done}/{len(entries)} entries, {chunks_written} chunks",
                  file=sys.stderr)
            conn.commit()
    for k, v in (("journal_sha256", jsha), ("model", args.model),
                 ("dim", str(len(unpack(conn.execute(
                     'SELECT vec FROM entries LIMIT 1').fetchone()[0]))))):
        conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, v))
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('entries',?)", (str(done),))
    conn.commit()
    conn.close()
    print(f"built {db}: {done} entries, {chunks_written} chunks, "
          f"model {args.model}", file=sys.stderr)
    return 0


def cmd_check(args, journal, index, db, quiet: bool = False) -> int:
    # quiet is for the --query path: a search's stdout must carry results and
    # nothing else, or piping it anywhere puts a status line in the data. The
    # failure branches stay loud on stderr either way.
    if not os.path.exists(db):
        print(f"missing: no index at {db} (run journal-search.py --build)",
              file=sys.stderr)
        return 2
    conn = connect(db)
    recorded = meta_get(conn, "journal_sha256")
    count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    conn.close()
    if count == 0:
        print(f"missing: {db} has no entries (run --build)", file=sys.stderr)
        return 2
    actual = sha256_file(journal)
    if recorded == actual:
        if not quiet:
            print(f"fresh: {db} matches {journal} ({actual})")
        return 0
    print(f"stale: {db} was built from {recorded or '<none>'}, journal is now "
          f"{actual}", file=sys.stderr)
    print("       rankings and line ranges are both suspect — run --build",
          file=sys.stderr)
    return 1


def cmd_status(args, journal, index, db) -> int:
    print(f"journal:  {journal}")
    print(f"index:    {index}  ({'present' if os.path.exists(index) else 'ABSENT'})")
    print(f"db:       {db}  ({'present' if os.path.exists(db) else 'ABSENT'})")
    print(f"host:     {args.host}")
    print(f"model:    {args.model}")
    if os.path.exists(db):
        conn = connect(db)
        n = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        e = conn.execute("SELECT COUNT(DISTINCT start||'-'||end) FROM entries"
                         ).fetchone()[0]
        print(f"entries:  {e}  ({n} chunks)")
        print(f"built-from: {meta_get(conn, 'journal_sha256')}")
        print(f"dim:      {meta_get(conn, 'dim')}")
        conn.close()
    return 0


def cmd_query(args, journal, index, db) -> int:
    rc = cmd_check(args, journal, index, db, quiet=True)
    if rc == 2:
        return 2
    if rc == 1 and not args.allow_stale:
        die("refusing to search a stale index — run --build, or pass "
            "--allow-stale to accept ranges that may be off", 1)

    conn = connect(db)
    built_model = meta_get(conn, "model")
    if built_model and built_model != args.model:
        die(f"index was built with {built_model!r} but you asked for "
            f"{args.model!r} — vectors from different models are not comparable; "
            f"rebuild or pass --model {built_model}")
    qvec = norm(embed([args.query], args.host, args.model)[0])
    rows = conn.execute(
        "SELECT start,end,date,seq,headline,level,chunk,vec FROM entries"
    ).fetchall()
    conn.close()

    # Score every chunk, but collapse to one row per entry at its best chunk.
    # Without this a long entry would occupy several of the top slots with
    # near-duplicate scores and crowd out other entries.
    best: dict[tuple[int, int], tuple] = {}
    for start, end, date, seq, headline, level, _chunk, blob in rows:
        v = unpack(blob)
        if len(v) != len(qvec):
            die(f"dimension mismatch: index has {len(v)}, query has {len(qvec)} "
                f"— rebuild the index")
        score = sum(a * b for a, b in zip(qvec, v))
        key = (start, end)
        if key not in best or score > best[key][0]:
            best[key] = (score, start, end, date, seq, headline, level)
    scored = sorted(best.values(), reverse=True)

    rel = os.path.relpath(journal, os.getcwd())
    for score, start, end, date, seq, headline, level in scored[:args.top]:
        mark = "  ↳ " if level == 3 else ""
        print(f"{score:.3f}  {start}-{end:<7} {date:<11} {seq:<6} {mark}{headline}")
    print(f"\nseek: sed -n 'START,ENDp' {rel}", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(add_help=True, description=__doc__.split("\n")[0])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--query", metavar="TEXT")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--status", action="store_true")
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--project", default=None, help="repo root (default: $CLAUDE_PROJECT_DIR, git toplevel, cwd)")
    p.add_argument("--journal", default=None)
    p.add_argument("--index", default=None)
    p.add_argument("--db", default=None)
    p.add_argument("--model", default=os.environ.get("JOURNAL_EMBED_MODEL", DEFAULT_MODEL))
    p.add_argument("--host", default=os.environ.get("OLLAMA_HOST", DEFAULT_HOST))
    p.add_argument("--allow-stale", action="store_true")
    args = p.parse_args()

    root = os.path.abspath(args.project) if args.project else ROOT
    journal = args.journal or os.path.join(root, "docs/JOURNAL.md")
    index = args.index or os.path.join(root, "docs/JOURNAL_INDEX.md")
    db = args.db or os.path.join(root, ".journal-search.db")
    if not os.path.isfile(journal):
        die(f"no journal at {journal}")
    if (args.build or args.query) and not os.path.isfile(index):
        die(f"no seek table at {index} — run journal-index.sh first")
    # The db must never be the journal or the seek table: --build truncates it.
    for name, other in (("journal", journal), ("seek table", index)):
        if os.path.exists(db) and os.path.samefile(db, other):
            die(f"refusing to use the {name} as the database — --build would "
                f"destroy it")
        if os.path.abspath(db) == os.path.abspath(other):
            die(f"refusing to use the {name} as the database — --build would "
                f"destroy it")

    if args.build:
        return cmd_build(args, journal, index, db)
    if args.check:
        return cmd_check(args, journal, index, db)
    if args.status:
        return cmd_status(args, journal, index, db)
    return cmd_query(args, journal, index, db)


if __name__ == "__main__":
    sys.exit(main())
