import json

from conftest import FIXTURES, load_script, run_script

SKILL = "laravel-queues-horizon"
CHECK = "queue_config_check.py"
TRIAGE = "failed_jobs_triage.py"
chk = load_script(SKILL, CHECK)
tri = load_script(SKILL, TRIAGE)
F = FIXTURES / SKILL


def test_parse_queue_connections():
    conns = chk.parse_queue_connections((F / "bad" / "config" / "queue.php").read_text())
    assert conns["redis"] == {"driver": "redis", "retry_after": 90, "after_commit": False}
    assert conns["database"]["retry_after"] is None
    assert conns["sync"]["driver"] == "sync"
    assert chk.default_connection((F / "bad" / "config" / "queue.php").read_text()) == "database"


def test_parse_horizon_skips_outer_arrays():
    sups = chk.parse_horizon((F / "bad" / "config" / "horizon.php").read_text())
    assert [s["name"] for s in sups] == ["supervisor-1"]
    assert sups[0]["timeout"] == 90 and sups[0]["tries"] == 0 and sups[0]["connection"] == "redis"


def test_parse_supervisor():
    progs = chk.parse_supervisor((F / "bad-worker.conf").read_text())
    assert [p["name"] for p in progs] == ["laravel-worker", "horizon"]
    worker, horizon = progs
    assert worker["timeout"] == 120 and worker["connection"] == "redis" and not worker["autorestart"]
    assert worker["user"] is None and worker["max_time"] is None
    assert horizon["horizon"] and horizon["user"] == "deploy"
    good = chk.parse_supervisor((F / "good-worker.conf").read_text())[0]
    assert good["stopwaitsecs"] == 3600 and good["max_time"] == 3600 and good["tries"] == 3


def test_bad_project_findings():
    findings, summary = chk.check(str(F / "bad"), [str(F / "bad-worker.conf")], None)
    got = {(f.check, f.severity) for f in findings}
    for expected in [
        ("timeout-vs-retry-after", "high"),
        ("sync-driver", "medium"),
        ("horizon-gate", "medium"),
        ("stopwaitsecs", "medium"),
        ("autorestart", "medium"),
        ("worker-user", "medium"),
        ("tries", "medium"),
        ("worker-recycle", "low"),
        ("horizon-trim", "low"),
        ("retry-after", "low"),
        ("after-commit", "info"),
        ("job-failed-handler", "info"),
    ]:
        assert expected in got, expected
    timeouts = [f for f in findings if f.check == "timeout-vs-retry-after"]
    assert {f.file for f in timeouts} == {
        "app/Jobs/GenerateReport.php",
        str(F / "bad-worker.conf"),
        "config/horizon.php",
    }
    assert summary["env_connection"] == "sync" and len(summary["jobs"]) == 1  # Helper is not a job


def test_good_project_is_clean():
    findings, _ = chk.check(str(F / "good"), [str(F / "good-worker.conf")], None)
    assert findings == []


def test_env_override(tmp_path):
    env = tmp_path / ".env"
    env.write_text("QUEUE_CONNECTION=redis\n")
    findings, summary = chk.check(str(F / "bad"), [], str(env))
    assert summary["env_connection"] == "redis"
    assert "sync-driver" not in {f.check for f in findings}


def test_triage_json_export():
    rows = tri.parse_rows((F / "failed_jobs.json").read_text())
    groups = tri.triage(rows)
    assert [(g["job"], g["count"], g["cause"]) for g in groups] == [
        ("App\\Jobs\\GenerateReport", 4, "timeout"),
        ("App\\Jobs\\SendInvoice", 3, "missing-model"),
        ("App\\Jobs\\SyncCrm", 1, "external"),
    ]
    assert groups[0]["first_failed_at"] == "2026-11-20 10:00:00"
    assert groups[0]["last_failed_at"] == "2026-11-23 10:00:00"
    assert groups[1]["queues"] == ["redis:emails"] and len(groups[1]["ids"]) == 3
    assert "<n>" in groups[1]["message"]


def test_triage_tsv_matches_json():
    tsv = tri.triage(tri.parse_rows((F / "failed_jobs.tsv").read_text()))
    assert [(g["job"], g["count"]) for g in tsv] == [
        ("App\\Jobs\\GenerateReport", 4),
        ("App\\Jobs\\SendInvoice", 1),
    ]


def test_payload_and_trace_never_printed():
    r = run_script(SKILL, TRIAGE, str(F / "failed_jobs.json"), "--json")
    assert "secret" not in r.stdout
    r = run_script(SKILL, TRIAGE, str(F / "failed_jobs.json"), "--ids")
    assert "secret" not in r.stdout and "queue:retry 0b6c1f6e" in r.stdout


def test_classify_and_exception_head():
    assert tri.classify("PDOException: SQLSTATE[40001]: Deadlock found")[0] == "db-lock"
    assert tri.classify("Error: Allowed memory size of 134217728 bytes exhausted")[0] == "memory"
    assert tri.classify('Error: Class "App\\Jobs\\Old" not found')[0] == "deploy-mismatch"
    assert tri.classify("TypeError: x(): Argument #1 must be of type int")[0] == "bug"
    assert tri.classify("Something odd")[0] == "other"
    cls, msg = tri.exception_head("Foo\\BarException: user 42 'bob' failed in /var/x.php:10\n#0")
    assert cls == "BarException" and msg == "user <n> '<v>' failed"
    assert tri.job_name('{"displayName": "App\\\\Jobs\\\\X"') == "App\\Jobs\\X"
    assert tri.job_name(None) == "unknown"


def test_cli(tmp_path):
    r = run_script(SKILL, CHECK, str(F / "bad"), "--supervisor", str(F / "bad-worker.conf"), "--json")
    assert r.returncode == 1 and json.loads(r.stdout)["summary"]["connections"]["redis"]["retry_after"] == 90
    assert run_script(SKILL, CHECK, str(F / "good"), "--supervisor", str(F / "good-worker.conf")).returncode == 0
    assert run_script(SKILL, CHECK, str(F / "bad"), "--fail-on", "high").returncode == 1
    assert run_script(SKILL, CHECK, str(tmp_path / "nope")).returncode == 2
    assert run_script(SKILL, CHECK, str(F / "good"), "--supervisor", "/nonexistent.conf").returncode == 2
    assert run_script(SKILL, CHECK, "--help").returncode == 0
    empty = tmp_path / "empty.json"
    empty.write_text("[]")
    assert run_script(SKILL, TRIAGE, str(empty)).returncode == 0
    r = run_script(SKILL, TRIAGE, "-", stdin=(F / "failed_jobs.tsv").read_text())
    assert r.returncode == 1 and "5 failed job(s)" in r.stdout
    bad = tmp_path / "bad.json"
    bad.write_text("[{not json")
    assert run_script(SKILL, TRIAGE, str(bad)).returncode == 2
    assert run_script(SKILL, TRIAGE, "--help").returncode == 0
