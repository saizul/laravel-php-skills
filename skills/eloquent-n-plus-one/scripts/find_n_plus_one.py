#!/usr/bin/env python3
"""Find N+1 query patterns in a Laravel query log or Telescope export. Read-only.

Accepted inputs (auto-detected, several files allowed, '-' = stdin):
  * Telescope export: JSON array / JSON lines of telescope_entries rows
    ({"batch_id": ..., "type": "query", "content": {"sql", "time", "file", "line"}}),
    with `content` as an object or a JSON string
  * DB::getQueryLog() dump: [{"query": ..., "bindings": [...], "time": ...}]
  * Laravel log lines written by the DB::listen snippet in SKILL.md:
    [2026-01-01 10:00:00] local.DEBUG: sql {"sql": "...", "time": 0.4, "request": "abc"}
  * Lazy-loading violations: "Attempted to lazy load [comments] on model [App\\Models\\Post] ..."
  * Plain text with one SQL statement per line (one request)

Queries are grouped per request (batch_id / request / log file), normalised (literals ->
?, IN lists collapsed) and a select repeated --threshold times or more in one request is
reported with the eager-loading fix it most likely needs.

Exit codes: 0 = no N+1 found, 1 = N+1 patterns found, 2 = error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict

LAZY_RE = re.compile(r"Attempted to lazy load \[(\w+)\] on model \[([\w\\]+)\]")
LOG_JSON_RE = re.compile(r"^\[[^\]]+\]\s+\w+\.\w+:\s*(?:\S+\s+)?(\{.*\})\s*(?:\[\])?\s*$")
SQL_START_RE = re.compile(r"^\s*(select|insert|update|delete|with)\b", re.I)


def normalize(sql: str) -> str:
    s = sql.strip().rstrip(";")
    s = re.sub(r"'(?:''|\\.|[^'\\])*'", "?", s)
    s = re.sub(r"(?<![\w\"`.])-?\d+(?:\.\d+)?\b", "?", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\bin\s*\(\s*\?(?:\s*,\s*\?)*\s*\)", "in (?)", s, flags=re.I)
    s = re.sub(r"\blimit \? offset \?", "limit ? offset ?", s, flags=re.I)
    return s.lower()


def _ident(x: str) -> str:
    return x.strip('`"[]').split(".")[-1].strip('`"[]')


def analyse_query(norm: str) -> dict:
    """Guess table, filter column and the kind of query from a normalised select."""
    info = {"table": None, "column": None, "kind": "select"}
    m = re.search(r"\bfrom\s+([`\"\[]?[\w.]+[`\"\]]?)", norm)
    if m:
        info["table"] = _ident(m.group(1))
    if re.match(r"select count\(\*\) as aggregate", norm):
        info["kind"] = "count"
    elif re.match(r"select exists\(", norm) or " exists(" in norm[:40]:
        info["kind"] = "exists"
    elif re.match(r"select (?:sum|avg|max|min)\(", norm):
        info["kind"] = "aggregate"
    w = re.search(r"\bwhere\s+([`\"\[]?[\w.`\"\]]+?)\s*(?:=\s*\?|in \(\?\))", norm)
    if w:
        info["column"] = _ident(w.group(1))
    # many-to-many: inner join pivot on ... where pivot.x_id in (?)
    if " inner join " in norm and info["column"] and info["column"].endswith("_id"):
        info["pivot"] = True
    return info


def singular(word: str) -> str:
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def camel(word: str) -> str:
    parts = word.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def suggest(info: dict) -> str:
    table, col, kind = info.get("table"), info.get("column"), info.get("kind")
    if not table or not col:
        return "Find the loop that runs this query and load the data once before it (with()/load())."
    if col == "id" or col.endswith(".id"):
        rel = camel(singular(table))
        return (
            f"belongsTo: each child loads its {rel}. Eager load it: ->with('{rel}') "
            f"(or ->load('{rel}') on an existing collection)."
        )
    if col.endswith("_id") or col.endswith("_type"):
        parent = camel(col[:-3]) if col.endswith("_id") else camel(col[:-5])
        rel = camel(table)
        if kind == "count":
            return f"count per {parent}: use ->withCount('{rel}') and read ${parent}->{rel}_count."
        if kind == "exists":
            return f"exists per {parent}: use ->withExists('{rel}') and read ${parent}->{rel}_exists."
        if kind == "aggregate":
            return f"aggregate per {parent}: use ->withSum('{rel}', 'column') / withAvg / withMax."
        if info.get("pivot"):
            return f"belongsToMany: eager load ->with('{rel}') on the {parent} query."
        return f"hasMany/hasOne: each {parent} loads its {rel}. Eager load it: ->with('{rel}')."
    return f"Repeated lookup on {table}.{col}: fetch all values with whereIn() once and key them by {col}."


class Query:
    __slots__ = ("group", "location", "sql", "time")

    def __init__(self, sql, time=0.0, group="all", location=""):
        self.sql = sql
        self.time = float(time or 0)
        self.group = str(group)
        self.location = location


def _from_obj(obj: dict, default_group: str):
    """Yield Query objects from one JSON object of any supported shape."""
    content = obj.get("content", obj)
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return
    if not isinstance(content, dict):
        return
    if obj.get("type") not in (None, "query"):
        return
    sql = content.get("sql") or content.get("query")
    if not isinstance(sql, str):
        return
    group = obj.get("batch_id") or content.get("request") or obj.get("request") or default_group
    loc = ""
    if content.get("file"):
        loc = str(content["file"]) + (f":{content['line']}" if content.get("line") else "")
    yield Query(sql, content.get("time", 0), group, loc)


def parse_input(text: str, source: str) -> tuple[list[Query], Counter]:
    queries: list[Query] = []
    lazy: Counter = Counter()
    for m in LAZY_RE.finditer(text):
        lazy[(m.group(2).replace("\\\\", "\\"), m.group(1))] += 1
    stripped = text.lstrip()
    if stripped.startswith("[") and not LOG_JSON_RE.match(stripped.splitlines()[0]):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            for obj in data:
                if isinstance(obj, dict):
                    queries.extend(_from_obj(obj, source))
            return queries, lazy
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                rows = data.get("data") or data.get("entries") or data.get("queries")
                if isinstance(rows, list):
                    for obj in rows:
                        if isinstance(obj, dict):
                            queries.extend(_from_obj(obj, source))
                    return queries, lazy
        except json.JSONDecodeError:
            pass
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    queries.extend(_from_obj(obj, source))
                    continue
            except json.JSONDecodeError:
                pass
        m = LOG_JSON_RE.match(line)
        if m:
            try:
                obj = json.loads(m.group(1))
                if isinstance(obj, dict):
                    queries.extend(_from_obj(obj, source))
            except json.JSONDecodeError:
                pass
            continue
        if SQL_START_RE.match(line):
            queries.append(Query(line, 0, source))
    return queries, lazy


def find(queries: list[Query], threshold: int) -> list[dict]:
    by_group: dict[str, list[Query]] = defaultdict(list)
    for q in queries:
        by_group[q.group].append(q)
    patterns: dict[str, dict] = {}
    for group, qs in by_group.items():
        counts: Counter = Counter()
        times: Counter = Counter()
        locs: dict[str, Counter] = defaultdict(Counter)
        for q in qs:
            norm = normalize(q.sql)
            if not norm.startswith(("select", "with")):
                continue
            counts[norm] += 1
            times[norm] += q.time
            if q.location:
                locs[norm][q.location] += 1
        for norm, n in counts.items():
            if n < threshold:
                continue
            p = patterns.setdefault(
                norm,
                {
                    "query": norm,
                    "requests": 0,
                    "max_per_request": 0,
                    "total_queries": 0,
                    "total_time_ms": 0.0,
                    "locations": Counter(),
                    "example_request": group,
                },
            )
            p["requests"] += 1
            p["total_queries"] += n
            p["total_time_ms"] += times[norm]
            if n > p["max_per_request"]:
                p["max_per_request"] = n
                p["example_request"] = group
            p["locations"].update(locs[norm])
    out = []
    for p in patterns.values():
        info = analyse_query(p["query"])
        p.update(info)
        p["fix"] = suggest(info)
        p["total_time_ms"] = round(p["total_time_ms"], 2)
        p["locations"] = [loc for loc, _ in p["locations"].most_common(3)]
        out.append(p)
    out.sort(key=lambda p: (-p["total_queries"], p["query"]))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Find N+1 query patterns in Laravel query logs or Telescope exports.",
        epilog="Example: find_n_plus_one.py storage/logs/queries.log --threshold 5 --json",
    )
    ap.add_argument("inputs", nargs="+", help="log/JSON files, or - for stdin")
    ap.add_argument("--threshold", type=int, default=5, help="repeats per request to report (default 5)")
    ap.add_argument("--top", type=int, default=20, help="show at most N patterns (default 20)")
    ap.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args(argv)
    if args.threshold < 2:
        print("error: --threshold must be at least 2", file=sys.stderr)
        return 2
    queries: list[Query] = []
    lazy: Counter = Counter()
    for path in args.inputs:
        try:
            if path == "-":
                text = sys.stdin.read()
            else:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        q, lz = parse_input(text, path)
        queries.extend(q)
        lazy.update(lz)
    patterns = find(queries, args.threshold)[: args.top]
    groups = len({q.group for q in queries})
    lazy_list = [{"model": m, "relation": r, "count": n} for (m, r), n in lazy.most_common()]
    if args.json:
        print(
            json.dumps(
                {
                    "queries": len(queries),
                    "requests": groups,
                    "threshold": args.threshold,
                    "patterns": patterns,
                    "lazy_loading_violations": lazy_list,
                },
                indent=2,
            )
        )
    else:
        print(f"{len(queries)} queries in {groups} request(s); {len(patterns)} N+1 pattern(s)")
        for i, p in enumerate(patterns, 1):
            print(
                f"\n#{i} x{p['max_per_request']} in one request ({p['requests']} request(s), "
                f"{p['total_queries']} queries, {p['total_time_ms']} ms)"
            )
            print(f"   {p['query'][:200]}")
            for loc in p["locations"]:
                print(f"   at {loc}")
            print(f"   fix: {p['fix']}")
        if lazy_list:
            print("\nLazy loading violations (Model::preventLazyLoading):")
            for item in lazy_list:
                print(f"   {item['model']}::{item['relation']} x{item['count']}  fix: ->with('{item['relation']}')")
    return 1 if patterns or lazy_list else 0


if __name__ == "__main__":
    sys.exit(main())
