#!/usr/bin/env python3
"""Summarise PHPStan / Larastan results by rule, file and message pattern. Read-only.

Inputs:
  report.json      output of `vendor/bin/phpstan analyse --error-format=json --no-progress`
  --baseline FILE  phpstan-baseline.neon (or .php) to summarise what is ignored
  --compare FILE   a previous JSON report: show new and fixed errors per rule

Errors are grouped by PHPStan identifier (PHPStan 1.11+/2.x, e.g. `method.notFound`); for
older reports without identifiers the message is normalised into a pattern instead.

Exit codes: 0 = no errors (or not more than --max-errors / no new errors with --compare),
1 = errors, 2 = bad input.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

# Fix hints per PHPStan/Larastan error identifier.
HINTS = {
    "missingType": "Add native or @param/@return types; for Laravel collections use generics "
    "(@return Collection<int, User>).",
    "property.notFound": "Usually Eloquent attributes: add @property annotations or use Larastan "
    "(it reads migrations); check for typos.",
    "method.notFound": "Magic methods/macros: use Larastan, add @method annotations or @mixin; check for typos.",
    "staticMethod.notFound": "Facade or model static call: Larastan resolves most; else @method static.",
    "larastan.noEnvCallsOutsideOfConfig": "Move env() into config/*.php and read it with config().",
    "argument.type": "Wrong argument type: cast, narrow with assert()/instanceof, or fix the signature.",
    "return.type": "Return value does not match the declared type: fix the type or the code path.",
    "nullsafe.neverNull": "Remove the ?-> operator; the value cannot be null here.",
    "deadCode.unreachable": "Delete unreachable code.",
    "variable.undefined": "Initialise the variable on every path.",
    "offsetAccess.notFound": "Array shape unknown: add @var array{key: type} or check isset().",
    "class.notFound": "Missing class or autoload: composer dump-autoload, or a dev-only class in prod code.",
    "function.notFound": "Missing function or extension stub: install the extension stub or a polyfill.",
    "identical.alwaysFalse": "Comparison is always false: the types never match; check the logic.",
    "booleanAnd.alwaysFalse": "Condition can never be true; check the logic.",
    "if.alwaysTrue": "Condition is always true; simplify.",
}


def normalise_message(msg: str) -> str:
    s = re.sub(r"\$\w+", "$var", msg)
    s = re.sub(r"(?<![\w\\])(?:\\?[A-Z][\w]*\\)+[A-Z]\w*", "Class", s)
    s = re.sub(r"\b[A-Z][a-zA-Z0-9_]*::\w+\(\)", "Class::method()", s)
    s = re.sub(r"\b(?:Class)::\w+\(\)", "Class::method()", s)
    s = re.sub(r"(?<=method )\w+\(\)", "method()", s)
    s = re.sub(r"(?<=function )\w+\(\)", "function()", s)
    s = re.sub(r"(?<=property )[\w\\]+::\$var", "Class::$var", s)
    s = re.sub(r"'[^']*'|\"[^\"]*\"", "'…'", s)
    s = re.sub(r"\b\d+\b", "N", s)
    return s[:160]


def hint_for(identifier: str) -> str:
    if identifier in HINTS:
        return HINTS[identifier]
    if identifier.startswith("missingType"):
        return HINTS["missingType"]
    return ""


def load_report(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    start = text.find("{")
    if start == -1:
        raise ValueError(f"{path}: no JSON object found (run with --error-format=json)")
    data = json.loads(text[start:])
    if "files" not in data and "totals" not in data:
        raise ValueError(f"{path}: not a PHPStan JSON report")
    return data


TOP_DIRS = {"app", "src", "tests", "routes", "database", "config", "resources", "lib", "modules", "bootstrap"}


def common_prefix(paths: list[str]) -> str:
    """Guess the project root so paths print as app/..., src/..."""
    if not paths:
        return ""
    cp = os.path.commonpath(paths) if len(paths) > 1 else os.path.dirname(paths[0])
    cand = cp
    while True:
        rels = [os.path.relpath(p, cand).split(os.sep)[0] for p in paths]
        if all(r in TOP_DIRS for r in rels):
            return cand.rstrip("/") + "/"
        parent = os.path.dirname(cand)
        if parent == cand:
            break
        cand = parent
    return cp.rstrip("/") + "/" if cp else ""


def flatten(report: dict, prefix: str | None = None) -> list[dict]:
    files = report.get("files") or {}
    if isinstance(files, list):  # empty PHP arrays become [] in JSON
        files = {}
    if prefix is None:
        prefix = common_prefix(list(files))
    out = []
    for path, info in files.items():
        rel = path[len(prefix) :] if prefix and path.startswith(prefix) else path
        for m in info.get("messages", []):
            ident = m.get("identifier") or ""
            out.append(
                {
                    "file": rel,
                    "line": m.get("line"),
                    "message": m.get("message", ""),
                    "identifier": ident,
                    "key": ident or normalise_message(m.get("message", "")),
                    "ignorable": m.get("ignorable", True),
                    "tip": m.get("tip", ""),
                }
            )
    return out


def summarise(report: dict, top: int) -> dict:
    errors = flatten(report)
    by_key = Counter(e["key"] for e in errors)
    by_file = Counter(e["file"] for e in errors)
    files_per_key: dict[str, set] = defaultdict(set)
    sample: dict[str, dict] = {}
    for e in errors:
        files_per_key[e["key"]].add(e["file"])
        sample.setdefault(e["key"], e)
    rules = []
    for key, n in by_key.most_common(top):
        s = sample[key]
        rules.append(
            {
                "rule": key,
                "count": n,
                "files": len(files_per_key[key]),
                "example": f"{s['file']}:{s['line']} {s['message'][:180]}",
                "hint": hint_for(key) if s["identifier"] else "",
            }
        )
    totals = report.get("totals") or {}
    general = report.get("errors") or []
    return {
        "file_errors": len(errors),
        "reported_total": totals.get("file_errors", len(errors)),
        "general_errors": general,
        "files_with_errors": len(by_file),
        "by_rule": rules,
        "by_file": [{"file": f, "count": n} for f, n in by_file.most_common(top)],
        "non_ignorable": sum(1 for e in errors if e["ignorable"] is False),
        "uses_identifiers": any(e["identifier"] for e in errors),
    }


def parse_baseline(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    entries = []
    if path.endswith(".php"):
        for m in re.finditer(r"\$ignoreErrors\[\]\s*=\s*\[(.*?)\];", text, re.S):
            block = m.group(1)

            def get(key, block=block):
                km = re.search(rf"'{key}'\s*=>\s*(?:'((?:\\'|[^'])*)'|(\d+)|__DIR__\s*\.\s*'([^']*)')", block)
                if not km:
                    return None
                return km.group(1) or km.group(2) or km.group(3)

            entries.append(
                {
                    "message": get("message") or get("rawMessage") or "",
                    "identifier": get("identifier") or "",
                    "count": int(get("count") or 1),
                    "path": (get("path") or "").lstrip("/"),
                }
            )
    else:
        current: dict | None = None
        for line in text.splitlines():
            m = re.match(r"^\s*-\s*(?:(\w+):\s*(.*))?$", line)
            if m:
                current = {"message": "", "identifier": "", "count": 1, "path": ""}
                entries.append(current)
                if not m.group(1):
                    continue
                line = f"  {m.group(1)}: {m.group(2)}"
            km = re.match(r"^\s+(message|rawMessage|identifier|count|path):\s*(.*)$", line)
            if km and current is not None:
                key, val = km.group(1), km.group(2).strip().strip("'\"")
                if key == "count":
                    current["count"] = int(val) if val.isdigit() else 1
                elif key == "rawMessage":
                    current["message"] = val
                else:
                    current[key] = val
    by_key: Counter = Counter()
    by_path: Counter = Counter()
    for e in entries:
        key = e["identifier"] or normalise_message(re.sub(r"^#\^?|\$?#$", "", e["message"]).replace("\\", ""))
        by_key[key] += e["count"]
        by_path[e["path"]] += e["count"]
    return {
        "entries": len(entries),
        "ignored_errors": sum(e["count"] for e in entries),
        "by_rule": [{"rule": k, "count": n} for k, n in by_key.most_common()],
        "by_file": [{"file": k, "count": n} for k, n in by_path.most_common()],
    }


def compare(old: dict, new: dict) -> dict:
    def counts(rep):
        return Counter((e["file"], e["key"]) for e in flatten(rep))

    a, b = counts(old), counts(new)
    new_c, fixed_c = Counter(), Counter()
    for k in set(a) | set(b):
        d = b[k] - a[k]
        if d > 0:
            new_c[k] = d
        elif d < 0:
            fixed_c[k] = -d
    return {
        "new": sum(new_c.values()),
        "fixed": sum(fixed_c.values()),
        "new_by_file_rule": [{"file": f, "rule": r, "count": n} for (f, r), n in new_c.most_common()],
        "fixed_by_rule": [{"rule": r, "count": n} for r, n in _by_rule(fixed_c).most_common()],
    }


def _by_rule(c: Counter) -> Counter:
    out: Counter = Counter()
    for (_, r), n in c.items():
        out[r] += n
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Summarise PHPStan/Larastan JSON output by rule and file (read-only).",
        epilog="Example: vendor/bin/phpstan analyse --error-format=json --no-progress > phpstan.json; "
        "phpstan_summary.py phpstan.json --baseline phpstan-baseline.neon",
    )
    ap.add_argument("report", nargs="?", help="PHPStan JSON report (or - for stdin)")
    ap.add_argument("--baseline", help="phpstan-baseline.neon or .php to summarise")
    ap.add_argument("--compare", help="previous JSON report: show new/fixed errors")
    ap.add_argument("--top", type=int, default=15, help="rows per table (default 15)")
    ap.add_argument("--max-errors", type=int, default=0, help="exit 0 while errors <= N (default 0)")
    ap.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args(argv)
    if not args.report and not args.baseline:
        ap.error("give a report and/or --baseline")
    out: dict = {}
    try:
        if args.report:
            if args.report == "-":
                tmp = sys.stdin.read()
                report = json.loads(tmp[tmp.find("{") :])
            else:
                report = load_report(args.report)
            out["summary"] = summarise(report, args.top)
            if args.compare:
                out["compare"] = compare(load_report(args.compare), report)
        if args.baseline:
            out["baseline"] = parse_baseline(args.baseline)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        s = out.get("summary")
        if s:
            print(
                f"PHPStan: {s['file_errors']} error(s) in {s['files_with_errors']} file(s)"
                + (f", {len(s['general_errors'])} general error(s)" if s["general_errors"] else "")
            )
            if not s["uses_identifiers"] and s["file_errors"]:
                print("(no error identifiers in this report; grouped by message pattern. PHPStan 1.11+ adds them)")
            if s["by_rule"]:
                print("\nBy rule:")
                for r in s["by_rule"]:
                    print(f"  {r['count']:>5}  {r['rule']}  ({r['files']} file(s))")
                    print(f"         e.g. {r['example']}")
                    if r["hint"]:
                        print(f"         hint: {r['hint']}")
            if s["by_file"]:
                print("\nBy file:")
                for f in s["by_file"]:
                    print(f"  {f['count']:>5}  {f['file']}")
            for g in s["general_errors"]:
                print(f"\nGENERAL: {g}")
        c = out.get("compare")
        if c:
            print(f"\nCompared with {args.compare}: {c['new']} new, {c['fixed']} fixed")
            for n in c["new_by_file_rule"][: args.top]:
                print(f"  +{n['count']}  {n['file']}  {n['rule']}")
        b = out.get("baseline")
        if b:
            print(f"\nBaseline: {b['ignored_errors']} ignored error(s) in {b['entries']} entr(y/ies)")
            for r in b["by_rule"][: args.top]:
                print(f"  {r['count']:>5}  {r['rule']}")
            print("  Top files:")
            for f in b["by_file"][: min(args.top, 10)]:
                print(f"  {f['count']:>5}  {f['file']}")

    s = out.get("summary")
    if not s:
        return 0
    if "compare" in out:
        return 1 if out["compare"]["new"] or s["general_errors"] else 0
    total = s["file_errors"] + len(s["general_errors"])
    return 1 if total > args.max_errors else 0


if __name__ == "__main__":
    sys.exit(main())
