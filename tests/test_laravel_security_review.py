import json

from conftest import FIXTURES, load_script, run_script

SKILL = "laravel-security-review"
SCRIPT = "laravel_security_scan.py"
mod = load_script(SKILL, SCRIPT)
F = FIXTURES / SKILL


def scan(path):
    return mod.Scanner(str(path)).run([str(path)])


def scan_text(tmp_path, rel, text):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return mod.Scanner(str(tmp_path)).run([str(tmp_path)])


def keyed(findings):
    return {(f.check, f.file, f.line) for f in findings}


def test_bad_project_findings():
    found = keyed(scan(F / "bad"))
    expected = {
        ("mass-assignment", "app/Models/Post.php", 10),
        ("mass-assignment", "app/Models/User.php", 9),
        ("mass-assignment", "app/Http/Controllers/PostController.php", 28),
        ("mass-assignment", "app/Http/Controllers/PostController.php", 35),
        ("raw-sql", "app/Http/Controllers/PostController.php", 15),
        ("raw-sql", "app/Http/Controllers/PostController.php", 16),
        ("raw-sql", "app/Http/Controllers/PostController.php", 18),
        ("dangerous-call", "app/Http/Controllers/PostController.php", 49),
        ("debug-helper", "app/Http/Controllers/PostController.php", 21),
        ("authorization", "app/Http/Controllers/PostController.php", 26),
        ("authorization", "app/Http/Controllers/PostController.php", 33),
        ("authorization", "app/Http/Controllers/PostController.php", 40),
        ("csrf", "app/Http/Middleware/VerifyCsrfToken.php", 10),
        ("csrf", "app/Http/Middleware/VerifyCsrfToken.php", 11),
        ("csrf", "bootstrap/app.php", 5),
        ("debug", "config/app.php", 5),
        ("debug", ".env.example", 3),
        ("debug", ".env.production", 2),
        ("debug", ".env.production", 3),
        ("cors", "config/cors.php", 5),
        ("tls", "config/services.php", 6),
        ("blade-unescaped", "resources/views/post.blade.php", 2),
        ("blade-unescaped", "resources/views/post.blade.php", 3),
    }
    missing = expected - found
    assert not missing, missing
    assert len(found) == len(expected), found - expected


def test_safe_patterns_are_not_reported():
    files = {f.file for f in scan(F / "bad")}
    # vendor/ and bootstrap/cache/ are skipped
    assert not any(f.startswith("vendor/") or "bootstrap/cache" in f for f in files)
    bad = scan(F / "bad")
    lines = {(f.file, f.line) for f in bad}
    ctrl = "app/Http/Controllers/PostController.php"
    assert (ctrl, 19) not in lines  # DB::select with bindings
    assert (ctrl, 20) not in lines  # whereRaw with bindings
    assert (ctrl, 50) not in lines  # ignore marker
    assert ("resources/views/post.blade.php", 4) not in lines  # csrf_field
    assert ("resources/views/post.blade.php", 5) not in lines  # Blade comment
    assert ("resources/views/post.blade.php", 6) not in lines  # ->links()
    assert ("app/Models/Post.php", 9) not in lines  # PHP comment


def test_severities():
    by = {(f.check, f.file, f.line): f.severity for f in scan(F / "bad")}
    assert by[("blade-unescaped", "resources/views/post.blade.php", 3)] == "high"
    assert by[("blade-unescaped", "resources/views/post.blade.php", 2)] == "medium"
    assert by[("debug", ".env.production", 2)] == "high"
    assert by[("debug", ".env.example", 3)] == "medium"
    assert by[("csrf", "app/Http/Middleware/VerifyCsrfToken.php", 10)] == "high"


def test_good_project_is_clean():
    assert scan(F / "good") == []


def test_interpolation_detection():
    assert mod.is_interpolated('"select * from t where id = $id"')
    assert mod.is_interpolated("'a = ' . $b")
    assert mod.is_interpolated("$sql")
    assert not mod.is_interpolated("'price > ?'")
    assert not mod.is_interpolated('"price > ?"')
    assert not mod.is_interpolated(r'"cost \$5"')


def test_comment_stripping_keeps_strings():
    src = "<?php $u = 'http://x.test'; // $guarded = [];\n# also\n/* $guarded = [] */ $a = 1;"
    out = mod.strip_php_comments(src)
    assert "http://x.test" in out and "$guarded" not in out and len(out) == len(src)
    assert "#[Attr]" in mod.strip_php_comments("<?php #[Attr]\nclass A {}")


def test_controller_with_class_level_authorization(tmp_path):
    findings = scan_text(
        tmp_path,
        "app/Http/Controllers/A.php",
        "<?php class A { public function __construct() { $this->authorizeResource(Post::class); }\n"
        "public function store(Request $r) { return 1; } }",
    )
    assert findings == []


def test_controller_abort_unless_counts(tmp_path):
    findings = scan_text(
        tmp_path,
        "app/Http/Controllers/B.php",
        "<?php class B { public function destroy(Post $p) { abort_unless($p->user_id === auth()->id(), 403);"
        " $p->delete(); } }",
    )
    assert findings == []


def test_local_env_debug_is_low(tmp_path):
    findings = scan_text(tmp_path, ".env", "APP_ENV=local\nAPP_DEBUG=true\n")
    assert [(f.check, f.severity) for f in findings] == [("debug", "low")]


def test_heredoc_and_dangerous_calls(tmp_path):
    findings = scan_text(
        tmp_path,
        "app/Services/S.php",
        "<?php\n$out = shell_exec('convert ' . $request->input('file'));\n"
        '$rows = DB::select(<<<"SQL"\n select * from t where a = $a\nSQL);\n',
    )
    checks = sorted(f.check for f in findings)
    assert checks == ["dangerous-call", "raw-sql"]


def test_cli():
    r = run_script(SKILL, SCRIPT, str(F / "bad"), "--json")
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert data["counts"]["high"] >= 10 and data["findings"][0]["severity"] == "high"
    assert run_script(SKILL, SCRIPT, str(F / "good")).returncode == 0
    r = run_script(SKILL, SCRIPT, str(F / "bad"), "--fail-on", "high", "--min-severity", "high")
    assert r.returncode == 1 and "MEDIUM" not in r.stdout
    single = run_script(SKILL, SCRIPT, str(F / "bad" / "app" / "Models" / "User.php"), "--fail-on", "high")
    assert single.returncode == 0 and "is_admin" in single.stdout
    assert run_script(SKILL, SCRIPT, "/nonexistent/path").returncode == 2
    assert run_script(SKILL, SCRIPT, "--help").returncode == 0
