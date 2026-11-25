import json

from conftest import FIXTURES, load_script, run_script

SKILL = "laravel-performance"
SCRIPT = "perf_audit.py"
mod = load_script(SKILL, SCRIPT)
F = FIXTURES / SKILL


def checks(findings):
    return {(f.check, f.where) for f in findings}


def test_bad_project():
    findings, production = mod.check_project(str(F / "bad"), None, deployed=True)
    assert production
    got = checks(findings)
    for expected in [
        ("env-file", ".env"),
        ("env-outside-config", "app/Http/Controllers/ReportController.php:15"),
        ("env-outside-config", "app/Services/Feature.php:9"),
        ("env-outside-config", "routes/web.php:3"),
        ("env-outside-config", "resources/views/footer.blade.php:1"),
        ("dev-packages", "composer.json"),
        ("autoloader", "composer.json"),
        ("caches", "bootstrap/cache/config.php"),
        ("caches", "bootstrap/cache/routes-v7.php"),
        ("caches", "bootstrap/cache/events.php"),
        ("caches", "storage/framework/views"),
        ("query-patterns", "app/Http/Controllers/ReportController.php:11"),
        ("query-patterns", "app/Http/Controllers/ReportController.php:12"),
        ("query-patterns", "app/Http/Controllers/ReportController.php:13"),
    ]:
        assert expected in got, expected
    # config/ is allowed to call env(); comments are ignored
    assert not any(w.startswith("config/") for _, w in got)
    assert not any(w.endswith(":14") for _, w in got)
    env_titles = [f.title for f in findings if f.check == "env-file"]
    assert len(env_titles) == 5
    assert not any("not-printed" in f.title + f.fix for f in findings)


def test_good_project():
    findings, production = mod.check_project(str(F / "good"), None, deployed=True)
    assert production and findings == []


def test_php_info_parsing_and_checks():
    ini = mod.parse_php_ini((F / "bad" / "php-i.txt").read_text())
    assert ini["opcache.memory_consumption"] == "128" and ini["realpath_cache_size"] == "4096K"
    got = {(f.check, f.severity) for f in mod.check_php(ini, production=True)}
    assert ("xdebug", "high") in got and ("jit", "info") in got
    titles = " ".join(f.title for f in mod.check_php(ini, production=True))
    assert "max_accelerated_files=10000" in titles and "interned_strings_buffer=8" in titles
    assert "validate_timestamps" in titles
    assert "validate_timestamps" not in " ".join(f.title for f in mod.check_php(ini, production=False))


def test_opcache_missing_vs_ini_default():
    phpinfo = mod.parse_php_ini((F / "bad" / "no-opcache-php-i.txt").read_text())
    assert [f.check for f in mod.check_php(phpinfo, False)] == ["opcache"]
    snippet = mod.parse_php_ini((F / "good" / "opcache.ini").read_text())
    assert mod.check_php(snippet, True) == []
    off = mod.parse_php_ini("opcache.enable=0\n")
    assert mod.check_php(off, False)[0].severity == "high"
    assert mod.check_php({}, True) == []


def test_helpers():
    assert mod.to_bytes("8M") == 8 * 1024 * 1024 and mod.to_bytes("4096K") == 4096 * 1024
    assert mod.to_bytes("abc") is None and mod.to_bytes(None) is None
    assert mod.to_bool("On") and mod.to_bool("off") is False and mod.to_bool(None) is None
    assert mod.parse_env("A=1\n# c\nB = 'x y'\n") == {"A": "1", "B": "x y"}


def test_non_production_env_skips_env_checks(tmp_path):
    (tmp_path / ".env").write_text("APP_ENV=local\nAPP_DEBUG=true\nQUEUE_CONNECTION=sync\n")
    findings, production = mod.check_project(str(tmp_path), None, deployed=False)
    assert not production and findings == []


def test_cli(tmp_path):
    r = run_script(SKILL, SCRIPT, str(F / "bad"), "--deployed", "--php-ini", str(F / "bad" / "php-i.txt"), "--json")
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert data["production"] and data["counts"]["high"] == 6
    assert "not-printed" not in r.stdout
    r = run_script(SKILL, SCRIPT, str(F / "good"), "--deployed", "--php-ini", str(F / "good" / "opcache.ini"))
    assert r.returncode == 0
    r = run_script(SKILL, SCRIPT, str(F / "bad"), "--env", str(F / "good" / ".env"), "--fail-on", "high")
    assert r.returncode == 1 and "APP_DEBUG" not in r.stdout
    assert run_script(SKILL, SCRIPT, str(tmp_path / "nope")).returncode == 2
    assert run_script(SKILL, SCRIPT, str(F / "good"), "--php-ini", str(tmp_path / "x.ini")).returncode == 2
    assert run_script(SKILL, SCRIPT, "--help").returncode == 0
