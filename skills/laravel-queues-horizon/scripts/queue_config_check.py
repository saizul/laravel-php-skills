#!/usr/bin/env python3
"""Check Laravel queue, Horizon and Supervisor settings for the classic mistakes. Read-only.

Reads (as text, PHP not needed):
  config/queue.php        retry_after per connection, after_commit, failed driver
  config/horizon.php      supervisor timeout / tries / maxProcesses / memory, trim, environments
  app/Jobs/*.php          $timeout / $tries / $backoff / $failOnTimeout per job, failed() handler
  supervisor *.conf       queue:work --timeout/--tries/--max-time, stopwaitsecs, numprocs
  .env                    QUEUE_CONNECTION (only that key is read)

Main rule (Laravel docs): every worker or job timeout must be several seconds shorter than
the connection's retry_after, or jobs run twice.

Exit codes: 0 = nothing at or above --fail-on, 1 = findings, 2 = error.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import asdict, dataclass

SEVERITIES = ["info", "low", "medium", "high"]
NUM = r"(?:\(int\)\s*)?(?:env\(\s*['\"]\w+['\"]\s*,\s*)?(\d+)"


@dataclass
class Finding:
    severity: str
    check: str
    file: str
    title: str
    fix: str


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*(//|#(?!\[)).*$", "", text)


def parse_queue_connections(text: str) -> dict[str, dict]:
    """Return {name: {"driver": ..., "retry_after": int|None, "after_commit": bool|None}}."""
    text = strip_comments(text)
    conns: dict[str, dict] = {}
    starts = list(re.finditer(r"['\"](\w+)['\"]\s*=>\s*\[\s*['\"]driver['\"]\s*=>\s*['\"](\w+)['\"]", text))
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        block = text[m.start() : end]
        ra = re.search(r"['\"]retry_after['\"]\s*=>\s*" + NUM, block)
        ac = re.search(r"['\"]after_commit['\"]\s*=>\s*(true|false)", block)
        conns[m.group(1)] = {
            "driver": m.group(2),
            "retry_after": int(ra.group(1)) if ra else None,
            "after_commit": (ac.group(1) == "true") if ac else None,
        }
    return conns


def default_connection(text: str) -> str | None:
    m = re.search(r"['\"]default['\"]\s*=>\s*env\(\s*['\"]QUEUE_CONNECTION['\"]\s*,\s*['\"](\w+)['\"]", text)
    if m:
        return m.group(1)
    m = re.search(r"['\"]default['\"]\s*=>\s*['\"](\w+)['\"]", text)
    return m.group(1) if m else None


def parse_horizon(text: str) -> list[dict]:
    """Return supervisor settings found in config/horizon.php."""
    text = strip_comments(text)
    sups = []
    for m in re.finditer(r"['\"]([\w-]+)['\"]\s*=>\s*\[", text):
        depth, i = 0, m.end() - 1
        while i < len(text):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        block = text[m.end() : i]
        if "'connection'" not in block and '"connection"' not in block and "'timeout'" not in block:
            continue
        if re.search(r"['\"][\w-]+['\"]\s*=>\s*\[[^\]]*['\"](?:connection|timeout)['\"]", block):
            continue  # an outer array (environments/defaults) that contains supervisors
        sup = {"name": m.group(1)}
        for key in ("timeout", "tries", "maxProcesses", "memory", "maxTime", "maxJobs", "nice"):
            km = re.search(rf"['\"]{key}['\"]\s*=>\s*" + NUM, block)
            sup[key] = int(km.group(1)) if km else None
        cm = re.search(r"['\"]connection['\"]\s*=>\s*['\"](\w+)['\"]", block)
        sup["connection"] = cm.group(1) if cm else None
        sups.append(sup)
    return sups


def parse_supervisor(text: str) -> list[dict]:
    progs = []
    for m in re.finditer(r"^\[program:([^\]]+)\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S):
        body = m.group(2)
        cmd = re.search(r"^command\s*=\s*(.+)$", body, re.M)
        if not cmd or "artisan" not in cmd.group(1):
            continue
        command = cmd.group(1)

        def opt(name, command=command):
            om = re.search(rf"--{name}[= ](\d+)", command)
            return int(om.group(1)) if om else None

        sw = re.search(r"^stopwaitsecs\s*=\s*(\d+)", body, re.M)
        conn = re.search(r"queue:work\s+(?!-)(\w+)", command)
        progs.append(
            {
                "name": m.group(1),
                "horizon": "horizon" in command and "queue:work" not in command,
                "connection": conn.group(1) if conn else None,
                "timeout": opt("timeout"),
                "tries": opt("tries"),
                "max_time": opt("max-time"),
                "max_jobs": opt("max-jobs"),
                "stopwaitsecs": int(sw.group(1)) if sw else None,
                "autorestart": bool(re.search(r"^autorestart\s*=\s*true", body, re.M)),
                "user": (re.search(r"^user\s*=\s*(\S+)", body, re.M) or [None, None])[1],
            }
        )
    return progs


def parse_jobs(paths: list[str]) -> list[dict]:
    jobs = []
    for p in paths:
        text = strip_comments(read(p))
        if "ShouldQueue" not in text:
            continue
        name = os.path.splitext(os.path.basename(p))[0]

        def prop(key, text=text):
            m = re.search(rf"(?:public|protected)\s+(?:int\s+|\?int\s+)?\${key}\s*=\s*(\d+)", text)
            return int(m.group(1)) if m else None

        jobs.append(
            {
                "name": name,
                "file": p,
                "timeout": prop("timeout"),
                "tries": prop("tries"),
                "has_backoff": bool(re.search(r"\$backoff\s*=|function\s+backoff\s*\(", text)),
                "has_failed": bool(re.search(r"function\s+failed\s*\(", text)),
                "retry_until": bool(re.search(r"function\s+retryUntil\s*\(", text)),
                "unique": "ShouldBeUnique" in text,
            }
        )
    return jobs


def check(root: str, supervisor_files: list[str], env_file: str | None) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    qpath = os.path.join(root, "config", "queue.php")
    hpath = os.path.join(root, "config", "horizon.php")
    qtext, htext = read(qpath), read(hpath)
    conns = parse_queue_connections(qtext)
    sups = parse_horizon(htext) if htext else []
    progs = []
    for sf in supervisor_files:
        progs += [dict(p, file=sf) for p in parse_supervisor(read(sf))]
    jobs = parse_jobs(sorted(glob.glob(os.path.join(root, "app", "Jobs", "**", "*.php"), recursive=True)))
    default = default_connection(qtext)
    env_conn = None
    env_path = env_file or os.path.join(root, ".env")
    m = re.search(r"^QUEUE_CONNECTION\s*=\s*['\"]?(\w+)", read(env_path), re.M)
    if m:
        env_conn = m.group(1)
    active = env_conn or default
    summary = {
        "default_connection": default,
        "env_connection": env_conn,
        "connections": conns,
        "horizon_supervisors": sups,
        "supervisor_programs": progs,
        "jobs": [{k: v for k, v in j.items() if k != "file"} for j in jobs],
    }

    def add(sev, chk, file, title, fix):
        if file and file.startswith(os.path.join(root, "")):
            file = os.path.relpath(file, root)
        findings.append(Finding(sev, chk, file or "", title, fix))

    if not qtext:
        add("info", "config", "config/queue.php", "config/queue.php not found", "Run from the project root.")
    if active == "sync":
        add(
            "medium" if env_conn else "low",
            "sync-driver",
            ".env" if env_conn else "config/queue.php",
            "QUEUE_CONNECTION=sync: jobs run inside the web request",
            "Use redis or database in production and run workers (Horizon or queue:work).",
        )
    for name, c in conns.items():
        if c["driver"] in ("sync", "null", "sqs"):
            continue
        if c["retry_after"] is None:
            add(
                "low",
                "retry-after",
                "config/queue.php",
                f"connection '{name}' has no retry_after (default 60s)",
                "Set retry_after explicitly, longer than your longest job timeout.",
            )
    if conns and not any(c.get("after_commit") for c in conns.values()):
        add(
            "info",
            "after-commit",
            "config/queue.php",
            "after_commit is false on every connection",
            "Jobs dispatched inside DB transactions may run before commit; use ->afterCommit() "
            "on those dispatches or set after_commit => true.",
        )

    def retry_after_for(conn_name):
        c = conns.get(conn_name or "")
        if not c or c["driver"] in ("sync", "null", "sqs"):
            return None
        return c["retry_after"] or 60

    # Connection the workers most likely consume: Horizon means redis, else the config default.
    worker_conn = "redis" if htext and "redis" in conns else (default if default != "sync" else env_conn)

    for s in sups:
        ra = retry_after_for(s.get("connection") or "redis")
        if s["timeout"] is not None and ra and s["timeout"] >= ra - 5:
            add(
                "high",
                "timeout-vs-retry-after",
                "config/horizon.php",
                f"Horizon supervisor '{s['name']}' timeout {s['timeout']}s is not below retry_after {ra}s",
                "Keep timeout several seconds below retry_after, e.g. timeout 60 / retry_after 90.",
            )
        if s["tries"] == 0:
            add(
                "medium",
                "tries",
                "config/horizon.php",
                f"Horizon supervisor '{s['name']}' has tries 0 (retries forever)",
                "Set tries (e.g. 3) or define retryUntil() on jobs that need time-based retries.",
            )
    if htext and not re.search(r"['\"]trim['\"]\s*=>", htext):
        add(
            "low",
            "horizon-trim",
            "config/horizon.php",
            "no 'trim' settings: Horizon keeps job history with defaults",
            "Set trim.recent / trim.failed / trim.monitored minutes to bound Redis memory.",
        )
    if htext and "viewHorizon" not in read(os.path.join(root, "app", "Providers", "HorizonServiceProvider.php")):
        add(
            "medium",
            "horizon-gate",
            "app/Providers/HorizonServiceProvider.php",
            "viewHorizon gate not found: dashboard access in non-local environments is unclear",
            "Define Gate::define('viewHorizon', fn ($user) => in_array($user->email, [...])).",
        )

    for p in progs:
        if p["horizon"]:
            if p["stopwaitsecs"] is None or p["stopwaitsecs"] < 60:
                add(
                    "medium",
                    "stopwaitsecs",
                    p["file"],
                    f"[program:{p['name']}] stopwaitsecs is {p['stopwaitsecs'] or 'unset (10)'}",
                    "Set stopwaitsecs longer than your longest job so deploys do not kill running jobs.",
                )
            continue
        ra = retry_after_for(p["connection"] or worker_conn)
        t = p["timeout"] if p["timeout"] is not None else 60
        if ra and t >= ra - 5:
            add(
                "high",
                "timeout-vs-retry-after",
                p["file"],
                f"[program:{p['name']}] --timeout {t}s is not below retry_after {ra}s",
                "Lower --timeout or raise retry_after so a job cannot be picked up twice.",
            )
        if p["stopwaitsecs"] is None or p["stopwaitsecs"] < t:
            add(
                "medium",
                "stopwaitsecs",
                p["file"],
                f"[program:{p['name']}] stopwaitsecs ({p['stopwaitsecs'] or 'unset (10)'}) < job timeout {t}s",
                "Set stopwaitsecs >= --timeout (Laravel docs use 3600 with --max-time=3600).",
            )
        if p["tries"] is None:
            add(
                "low",
                "tries",
                p["file"],
                f"[program:{p['name']}] no --tries (default 1: failures are not retried)",
                "Add --tries=3 or set $tries on jobs.",
            )
        if p["max_time"] is None and p["max_jobs"] is None:
            add(
                "low",
                "worker-recycle",
                p["file"],
                f"[program:{p['name']}] no --max-time/--max-jobs: workers never recycle (memory leaks)",
                "Add --max-time=3600 so Supervisor restarts workers hourly.",
            )
        if not p["autorestart"]:
            add(
                "medium",
                "autorestart",
                p["file"],
                f"[program:{p['name']}] autorestart is not true",
                "Set autorestart=true so workers come back after --max-time, crashes and queue:restart.",
            )
        if p["user"] in (None, "root"):
            add(
                "medium",
                "worker-user",
                p["file"],
                f"[program:{p['name']}] runs as {p['user'] or 'root (no user=)'}",
                "Run workers as the deploy/web user (user=forge or www-data).",
            )

    for j in jobs:
        ra = retry_after_for(worker_conn)
        if j["timeout"] is not None and ra and j["timeout"] >= ra - 5:
            add(
                "high",
                "timeout-vs-retry-after",
                j["file"],
                f"{j['name']} $timeout {j['timeout']}s is not below retry_after {ra}s",
                "Move long jobs to a connection with a larger retry_after, or split the work.",
            )
        if j["tries"] is None and not j["retry_until"] and not j["has_backoff"]:
            add(
                "info",
                "job-retries",
                j["file"],
                f"{j['name']} sets no $tries/$backoff/retryUntil (worker defaults apply)",
                "Set $tries and $backoff = [10, 60, 300] for jobs that call external services.",
            )
        if not j["has_failed"]:
            add(
                "info",
                "job-failed-handler",
                j["file"],
                f"{j['name']} has no failed() method",
                "Add failed(Throwable $e) to notify or clean up when retries are exhausted.",
            )
    return findings, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Check Laravel queue/Horizon/Supervisor configuration (read-only).",
        epilog="Example: queue_config_check.py . --supervisor /etc/supervisor/conf.d/worker.conf",
    )
    ap.add_argument("root", nargs="?", default=".", help="Laravel project root (default .)")
    ap.add_argument("--supervisor", action="append", default=[], help="Supervisor .conf file (repeatable)")
    ap.add_argument("--env", help="env file to read QUEUE_CONNECTION from (default ROOT/.env)")
    ap.add_argument("--fail-on", choices=SEVERITIES, default="medium", help="exit 1 at or above (default medium)")
    ap.add_argument("--json", action="store_true", help="print JSON (findings + parsed settings)")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.root):
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2
    for sf in args.supervisor:
        if not os.path.isfile(sf):
            print(f"error: {sf} not found", file=sys.stderr)
            return 2
    findings, summary = check(args.root, args.supervisor, args.env)
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: (-rank[f.severity], f.file, f.title))
    if args.json:
        print(json.dumps({"summary": summary, "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        conns = ", ".join(
            f"{n}({c['driver']}, retry_after={c['retry_after']})" for n, c in summary["connections"].items()
        )
        print(f"queue connection: {summary['env_connection'] or summary['default_connection']}; {conns}")
        print(
            f"horizon supervisors: {len(summary['horizon_supervisors'])}; supervisor programs: "
            f"{len(summary['supervisor_programs'])}; jobs: {len(summary['jobs'])}"
        )
        for f in findings:
            print(f"{f.severity.upper():6} {f.file}  [{f.check}] {f.title}\n       fix: {f.fix}")
    return 1 if any(rank[f.severity] >= rank[args.fail_on] for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
