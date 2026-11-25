#!/usr/bin/env python3
"""Flag risky operations in Laravel migration files before they run in production. Read-only.

Reads database/migrations/*.php as text and reports, per migration and line:
  drop-column / drop-table / truncate   data loss, and old code still reading the column
  rename                                renameColumn / Schema::rename break running code
  change                                ->change() rewrites the column (table copy / lock)
  not-null-no-default                   new NOT NULL column without default on an existing table
  unique-on-existing                    ->unique() on an existing table (fails on duplicates)
  index-on-big-table                    index/foreign key added to a table from --big-tables
  foreign-key                           ->foreign()/->constrained() added to an existing table
  data-migration                        DB::table()->update(), Model::all(), chunk() in a migration
  raw-statement                         DB::statement()/DB::unprepared(): review manually
  missing-down / empty-down             no rollback path

Exit codes: 0 = nothing at or above --fail-on, 1 = findings, 2 = error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass

SEVERITIES = ["info", "low", "medium", "high"]
COLUMN_TYPES = (
    "string|char|text|mediumText|longText|tinyText|integer|tinyInteger|smallInteger|mediumInteger|"
    "bigInteger|unsignedInteger|unsignedBigInteger|unsignedTinyInteger|unsignedSmallInteger|"
    "boolean|date|dateTime|dateTimeTz|time|timestamp|timestampTz|decimal|float|double|json|jsonb|"
    "uuid|ulid|enum|set|binary|year|ipAddress|macAddress|foreignId|foreignUuid|foreignUlid"
)


@dataclass
class Finding:
    severity: str
    check: str
    file: str
    line: int
    table: str
    title: str
    fix: str


def blank_comments_and_strings_keep(text: str) -> str:
    """Remove comments (keep offsets). Strings are kept because table names live in them."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"":
            q = c
            i += 1
            while i < n and text[i] != q:
                i += 2 if text[i] == "\\" else 1
            i += 1
            continue
        if text.startswith("/*", i) or text.startswith("//", i) or (c == "#" and not text.startswith("#[", i)):
            end = text.find("*/", i + 2) + 2 if text.startswith("/*", i) else text.find("\n", i)
            if end < 2 or end == -1:
                end = n
            for k in range(i, end):
                if out[k] != "\n":
                    out[k] = " "
            i = end
            continue
        i += 1
    return "".join(out)


def match_brace(text: str, open_pos: int) -> int:
    """Return the index of the brace closing the one at open_pos (or len(text))."""
    depth, i, n = 0, open_pos, len(text)
    while i < n:
        c = text[i]
        if c in "'\"":
            q = c
            i += 1
            while i < n and text[i] != q:
                i += 2 if text[i] == "\\" else 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def method_body(text: str, name: str) -> tuple[int, int] | None:
    m = re.search(rf"function\s+{name}\s*\([^)]*\)\s*(?::\s*\??\w+)?\s*\{{", text)
    if not m:
        return None
    start = m.end() - 1
    return start, match_brace(text, start)


def schema_blocks(text: str, start: int, end: int):
    """Yield (kind, table, body_start, body_end, call_pos) for Schema::create/table blocks."""
    pat = re.compile(r"Schema::(?:connection\([^)]*\)->)?(create|table)\(\s*['\"]([\w.]+)['\"]")
    for m in pat.finditer(text, start, end):
        brace = text.find("{", m.end(), end)
        if brace == -1:
            continue
        close = match_brace(text, brace)
        yield m.group(1), m.group(2), brace, close, m.start()


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def statements(text: str, start: int, end: int):
    """Split a block into ;-terminated statements: yields (pos, statement)."""
    pos = start + 1
    depth = 0
    i = pos
    while i < end:
        c = text[i]
        if c in "'\"":
            q = c
            i += 1
            while i < end and text[i] != q:
                i += 2 if text[i] == "\\" else 1
        elif c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == ";" and depth <= 0:
            stmt = text[pos:i]
            lead = len(stmt) - len(stmt.lstrip())
            yield pos + lead, stmt.strip()
            pos = i + 1
        i += 1


def check_file(path: str, display: str, big_tables: set[str]) -> list[Finding]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    text = blank_comments_and_strings_keep(raw)
    findings: list[Finding] = []

    seen: set[tuple[str, int]] = set()

    def add(sev, check, pos, table, title, fix):
        key = (check, line_of(text, pos))
        if key in seen:
            return
        seen.add(key)
        findings.append(Finding(sev, check, display, key[1], table, title, fix))

    up = method_body(text, "up")
    down = method_body(text, "down")
    if up is None:
        return findings
    if down is None:
        add(
            "medium",
            "missing-down",
            up[0],
            "",
            "migration has no down() method",
            "Add down() that reverses up(), or document that rollback means restoring a backup.",
        )
    else:
        inner = text[down[0] + 1 : down[1]].strip()
        if not inner:
            add(
                "low",
                "empty-down",
                down[0],
                "",
                "down() is empty: rollback does nothing",
                "Reverse up() in down(), or throw an exception to make the one-way nature explicit.",
            )

    ustart, uend = up
    for kind, table, bstart, bend, _call in schema_blocks(text, ustart, uend):
        existing = kind == "table"
        big = table in big_tables
        for pos, st in statements(text, bstart, bend):
            if not st.startswith("$"):
                continue
            if re.search(
                r"->(dropColumn|dropColumns|dropMorphs|dropTimestamps|dropSoftDeletes|"
                r"dropRememberToken)\(",
                st,
            ):
                add(
                    "high",
                    "drop-column",
                    pos,
                    table,
                    f"drops column(s) on {table}",
                    "Deploy code that stops using the column first, back up, then drop in a later release.",
                )
            if re.search(r"->renameColumn\(", st):
                add(
                    "high",
                    "rename",
                    pos,
                    table,
                    f"renames a column on {table}",
                    "Expand/contract: add the new column, dual-write, backfill, switch reads, drop the old one.",
                )
            if re.search(r"->change\(\)", st):
                add(
                    "high" if big else "medium",
                    "change",
                    pos,
                    table,
                    f"->change() alters an existing column on {table}" + (" (big table)" if big else ""),
                    "Laravel 11+ drops modifiers you do not repeat (nullable, default, comment); "
                    "on big tables run online DDL (pt-online-schema-change/gh-ost) in a maintenance window.",
                )
                continue
            if not existing:
                continue
            col = re.match(rf"^\$\w+->({COLUMN_TYPES})\(\s*['\"](\w+)['\"]", st)
            if col and col.group(1) not in ("foreignId", "foreignUuid", "foreignUlid"):
                if not re.search(r"->(nullable|default|useCurrent|storedAs|virtualAs|autoIncrement)\(", st):
                    add(
                        "medium",
                        "not-null-no-default",
                        pos,
                        table,
                        f"adds NOT NULL column '{col.group(2)}' without a default to existing table {table}",
                        "Add ->nullable() or ->default(...), backfill, then tighten in a later migration.",
                    )
            elif col and not re.search(r"->(nullable|default)\(", st):
                add(
                    "medium",
                    "not-null-no-default",
                    pos,
                    table,
                    f"adds NOT NULL foreign key '{col.group(2)}' to existing table {table}",
                    "Add ->nullable() first, backfill, then make it required.",
                )
            if re.search(r"->unique\(", st):
                add(
                    "medium",
                    "unique-on-existing",
                    pos,
                    table,
                    f"adds a unique index to existing table {table}",
                    "Check for duplicates first: SELECT col, COUNT(*) FROM t GROUP BY col HAVING COUNT(*) > 1.",
                )
            if re.search(r"->(index|fullText|spatialIndex|primary)\(", st) and big:
                add(
                    "medium",
                    "index-on-big-table",
                    pos,
                    table,
                    f"adds an index to big table {table}",
                    "MySQL 8: online DDL (ALGORITHM=INPLACE, LOCK=NONE); PostgreSQL: CREATE INDEX CONCURRENTLY "
                    "in a migration with $withinTransaction = false.",
                )
            if re.search(r"->(foreign|constrained)\(", st):
                add(
                    "medium" if big else "low",
                    "foreign-key",
                    pos,
                    table,
                    f"adds a foreign key to existing table {table}",
                    "Validates every row and locks the table; check orphans first and run off-peak.",
                )

    body = text[ustart:uend]
    for m in re.finditer(r"Schema::(?:drop|dropIfExists|dropColumns)\(\s*['\"]([\w.]+)['\"]", body):
        add(
            "high",
            "drop-table",
            ustart + m.start(),
            m.group(1),
            f"drops table {m.group(1)} in up()",
            "Confirm nothing reads the table, take a backup, and keep a rename-to-_old step if unsure.",
        )
    for m in re.finditer(r"Schema::rename\(\s*['\"]([\w.]+)['\"]", body):
        add(
            "high",
            "rename",
            ustart + m.start(),
            m.group(1),
            f"renames table {m.group(1)}",
            "Running code still uses the old name; deploy code that handles both or use a view.",
        )
    for m in re.finditer(r"->truncate\(\)|\bTRUNCATE\b", body):
        add("high", "truncate", ustart + m.start(), "", "truncates a table", "Never truncate in a migration.")
    for m in re.finditer(
        r"DB::table\([^)]*\)[^;]*->(update|delete|insert|upsert)\(|::(all|cursor)\(\)|->(chunk|chunkById|each|lazy)\(",
        body,
    ):
        add(
            "medium",
            "data-migration",
            ustart + m.start(),
            "",
            "moves or rewrites data inside a migration",
            "Large backfills time out and lock tables: use a queued job or command in batches; "
            "avoid Eloquent models in migrations (they change later).",
        )
    for m in re.finditer(r"DB::(statement|unprepared)\(", body):
        add(
            "info",
            "raw-statement",
            ustart + m.start(),
            "",
            f"raw DB::{m.group(1)}() in up(): review the SQL by hand",
            "Check locking behaviour and that down() reverses it.",
        )
    findings.sort(key=lambda f: f.line)
    return findings


def collect(paths: list[str]) -> list[tuple[str, str]]:
    files = []
    for target in paths:
        if os.path.isfile(target):
            files.append((target, os.path.basename(target)))
        elif os.path.isdir(target):
            mig = os.path.join(target, "database", "migrations")
            base = mig if os.path.isdir(mig) else target
            for dirpath, _, filenames in os.walk(base):
                for fn in sorted(filenames):
                    if fn.endswith(".php"):
                        full = os.path.join(dirpath, fn)
                        files.append((full, os.path.relpath(full, base)))
    return sorted(files, key=lambda f: f[1])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Flag risky operations in Laravel migrations (read-only).",
        epilog="Example: migration_safety.py . --big-tables users,orders --since 2026_11_01",
    )
    ap.add_argument("paths", nargs="*", default=["."], help="project root, migrations dir or files")
    ap.add_argument("--big-tables", default="", help="comma-separated tables with many rows")
    ap.add_argument("--since", default="", help="only files whose name sorts at or after this prefix")
    ap.add_argument("--fail-on", choices=SEVERITIES, default="high", help="exit 1 at or above (default high)")
    ap.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args(argv)
    for t in args.paths:
        if not os.path.exists(t):
            print(f"error: {t} does not exist", file=sys.stderr)
            return 2
    big = {t.strip() for t in args.big_tables.split(",") if t.strip()}
    files = [f for f in collect(args.paths) if os.path.basename(f[0]) >= args.since]
    findings: list[Finding] = []
    for full, display in files:
        findings.extend(check_file(full, display, big))
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    counts = {s: sum(1 for f in findings if f.severity == s) for s in reversed(SEVERITIES)}
    if args.json:
        print(json.dumps({"files": len(files), "counts": counts, "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        print(f"{len(files)} migration(s): " + ", ".join(f"{n} {s}" for s, n in counts.items()))
        current = None
        for f in findings:
            if f.file != current:
                current = f.file
                print(f"\n{f.file}")
            print(f"  {f.severity.upper():6} line {f.line:<4} [{f.check}] {f.title}")
            print(f"         fix: {f.fix}")
    return 1 if any(rank[f.severity] >= rank[args.fail_on] for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
