#!/usr/bin/env python3
"""Group Laravel failed jobs by job class and root cause, and suggest what to do. Read-only.

Input: an export of the failed_jobs table, any of
  * JSON array or JSON lines of rows (uuid, connection, queue, payload, exception, failed_at)
  * tab-separated output with a header row, e.g. `mysql --batch -e "select ... from failed_jobs"`
    or `psql --no-align --field-separator=$'\\t' -c "..."`

Only the job class (payload.displayName), exception class and the first line of the
message are shown. Payload data and stack traces are never printed (they can contain
personal data).

Exit codes: 0 = no failed jobs, 1 = failed jobs found, 2 = error.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys

CAUSES = [
    (
        r"MaxAttemptsExceededException|has been attempted too many times",
        "timeout",
        "Job ran longer than retry_after or kept being released. Check that the worker --timeout is "
        "below retry_after, raise $timeout for this job, or make it faster / chunked.",
    ),
    (
        r"TimeoutExceededException|has timed out",
        "timeout",
        "Job exceeded its timeout. Raise $timeout (keep it below retry_after) or split the work.",
    ),
    (
        r"ModelNotFoundException|No query results for model",
        "missing-model",
        "The model was deleted before the job ran. Set public $deleteWhenMissingModels = true "
        "if that is expected; do not retry.",
    ),
    (
        r"Deadlock found|deadlock detected|Lock wait timeout|SQLSTATE\[40001\]",
        "db-lock",
        "Database deadlock/lock timeout. Retry is usually safe; add $backoff and keep transactions short.",
    ),
    (
        r"QueryException|SQLSTATE",
        "database",
        "SQL error. Often a schema/code mismatch after a deploy: check migrations ran, then retry.",
    ),
    (
        r"ConnectionException|cURL error 28|cURL error 7|Connection refused|Could not resolve host|"
        r"RequestException|429 Too Many Requests|50[234] ",
        "external",
        "External service failed or rate limited. Use $backoff = [10, 60, 300], the "
        "RateLimited/ThrottlesExceptions middleware, then retry once the service is healthy.",
    ),
    (
        r"Allowed memory size|Out of memory",
        "memory",
        "Worker ran out of memory. Process in chunks, unset large variables, or raise "
        "the worker --memory / Horizon 'memory' and PHP memory_limit.",
    ),
    (
        r"Class \"[^\"]+\" not found|Call to undefined method|Unable to find|__PHP_Incomplete_Class|"
        r"unserialize\(\)",
        "deploy-mismatch",
        "Payload refers to code that changed or was removed. Restart workers after every deploy "
        "(php artisan queue:restart / horizon:terminate); retrying old payloads may fail again.",
    ),
    (
        r"ValidationException|InvalidArgumentException|TypeError|ErrorException|Undefined (?:array key|index)",
        "bug",
        "Application bug for this input. Fix the code first, then retry the affected jobs.",
    ),
]


def parse_rows(text: str) -> list[dict]:
    s = text.strip()
    if not s:
        return []
    if s.startswith("["):
        data = json.loads(s)
        return [r for r in data if isinstance(r, dict)]
    if s.startswith("{"):
        rows = []
        for line in s.splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        if len(rows) == 1 and isinstance(rows[0].get("data"), list):
            return rows[0]["data"]
        return rows
    reader = csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
    rows = []
    for r in reader:
        rows.append({k: _unescape_batch(v) for k, v in r.items() if k})
    return rows


def _unescape_batch(v: str | None) -> str:
    if v is None:
        return ""
    return v.replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")


def job_name(payload) -> str:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            m = re.search(r'"displayName"\s*:\s*"([^"]+)"', payload)
            return m.group(1).replace("\\\\", "\\") if m else "unknown"
    if isinstance(payload, dict):
        return str(payload.get("displayName") or payload.get("job") or "unknown")
    return "unknown"


def exception_head(exc: str) -> tuple[str, str]:
    """Return (exception class, normalised first message line)."""
    first = (exc or "").strip().splitlines()[0] if exc and exc.strip() else ""
    m = re.match(r"^([\w\\]+(?:Exception|Error|Exceeded\w*|Throwable)?)\s*:\s*(.*)$", first)
    cls, msg = (m.group(1), m.group(2)) if m else ("", first)
    msg = re.sub(r" in /\S+:\d+$", "", msg)
    msg = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<uuid>", msg)
    msg = re.sub(r"\[\d+(?:, ?\d+)*\]", "[<ids>]", msg)
    msg = re.sub(r"\b\d+\b", "<n>", msg)
    msg = re.sub(r"'[^']{1,200}'", "'<v>'", msg)
    return cls.split("\\")[-1] if cls else "", msg[:200]


def classify(exc: str) -> tuple[str, str]:
    head = "\n".join((exc or "").splitlines()[:3])
    for pattern, cause, advice in CAUSES:
        if re.search(pattern, head):
            return cause, advice
    return "other", "Read one full stack trace (php artisan queue:failed shows ids) and fix the cause."


def triage(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, dict] = {}
    for r in rows:
        name = job_name(r.get("payload", ""))
        exc = str(r.get("exception", ""))
        cls, msg = exception_head(exc)
        cause, advice = classify(exc)
        key = (name, cls, msg)
        g = groups.setdefault(
            key,
            {
                "job": name,
                "exception": cls,
                "message": msg,
                "cause": cause,
                "advice": advice,
                "count": 0,
                "queues": set(),
                "first_failed_at": None,
                "last_failed_at": None,
                "ids": [],
            },
        )
        g["count"] += 1
        q = r.get("queue")
        if q:
            g["queues"].add(f"{r.get('connection', '')}:{q}".lstrip(":"))
        ts = str(r.get("failed_at") or "")
        if ts:
            g["first_failed_at"] = min(filter(None, [g["first_failed_at"], ts]))
            g["last_failed_at"] = max(filter(None, [g["last_failed_at"], ts]))
        ident = r.get("uuid") or r.get("id")
        if ident:
            g["ids"].append(str(ident))
    out = sorted(groups.values(), key=lambda g: (-g["count"], g["job"]))
    for g in out:
        g["queues"] = sorted(g["queues"])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Group Laravel failed jobs by job and cause (read-only).",
        epilog="Example: failed_jobs_triage.py failed_jobs.tsv --ids",
    )
    ap.add_argument("input", help="failed_jobs export (JSON, JSON lines or TSV with header), or -")
    ap.add_argument("--ids", action="store_true", help="print queue:retry / queue:forget commands per group")
    ap.add_argument("--top", type=int, default=20, help="show at most N groups (default 20)")
    ap.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args(argv)
    try:
        if args.input == "-":
            text = sys.stdin.read()
        else:
            with open(args.input, encoding="utf-8") as fh:
                text = fh.read()
        rows = parse_rows(text)
    except (OSError, json.JSONDecodeError, csv.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    groups = triage(rows)[: args.top]
    if args.json:
        print(json.dumps({"failed_jobs": len(rows), "groups": groups}, indent=2))
    else:
        print(f"{len(rows)} failed job(s) in {len(triage(rows))} group(s)")
        for i, g in enumerate(groups, 1):
            print(f"\n#{i} {g['count']}x {g['job']}  [{g['cause']}]")
            print(f"   {g['exception']}: {g['message']}" if g["exception"] else f"   {g['message']}")
            if g["queues"]:
                print(f"   queues: {', '.join(g['queues'])}")
            if g["first_failed_at"]:
                print(f"   between {g['first_failed_at']} and {g['last_failed_at']}")
            print(f"   advice: {g['advice']}")
            if args.ids and g["ids"]:
                ids = " ".join(g["ids"][:50])
                print(f"   retry:  php artisan queue:retry {ids}")
                print(f"   forget: php artisan queue:forget {g['ids'][0]}   (one id per call)")
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
