import json

import pytest

from conftest import FIXTURES, load_script, run_script

SKILL = "php-static-analysis"
SCRIPT = "phpstan_summary.py"
mod = load_script(SKILL, SCRIPT)
F = FIXTURES / SKILL


def test_summary_by_rule_and_file():
    s = mod.summarise(mod.load_report(str(F / "phpstan.json")), 15)
    assert s["file_errors"] == 9 and s["files_with_errors"] == 3 and s["uses_identifiers"]
    rules = {r["rule"]: r for r in s["by_rule"]}
    assert rules["missingType.return"]["count"] == 2 and rules["missingType.return"]["files"] == 2
    assert s["by_rule"][0]["rule"] == "missingType.return"
    assert "Larastan" in rules["property.notFound"]["hint"]
    assert "config()" in rules["larastan.noEnvCallsOutsideOfConfig"]["hint"]
    assert s["by_file"][0] == {"file": "app/Http/Controllers/OrderController.php", "count": 4}


def test_legacy_report_without_identifiers():
    s = mod.summarise(mod.load_report(str(F / "phpstan-legacy.json")), 15)
    assert not s["uses_identifiers"]
    assert s["by_rule"][0]["rule"] == "Call to an undefined method Class::method()."
    assert s["by_rule"][0]["count"] == 2
    assert s["by_file"][0]["file"] == "src/Foo.php"
    assert len(s["general_errors"]) == 1 and s["non_ignorable"] == 1


def test_clean_report_with_empty_files_list():
    s = mod.summarise(mod.load_report(str(F / "phpstan-clean.json")), 15)
    assert s["file_errors"] == 0 and s["by_rule"] == []


def test_compare():
    c = mod.compare(mod.load_report(str(F / "phpstan-previous.json")), mod.load_report(str(F / "phpstan.json")))
    assert c["new"] == 1 and c["fixed"] == 2
    assert c["new_by_file_rule"] == [
        {"file": "app/Http/Controllers/OrderController.php", "rule": "property.notFound", "count": 1}
    ]
    assert c["fixed_by_rule"] == [{"rule": "variable.undefined", "count": 2}]


@pytest.mark.parametrize("name", ["phpstan-baseline.neon", "phpstan-baseline.php"])
def test_baselines(name):
    b = mod.parse_baseline(str(F / name))
    assert b["by_rule"][0] == {"rule": "property.notFound", "count": 12}
    assert b["by_file"][0] == {"file": "app/Http/Controllers/ProfileController.php", "count": 12}
    if name.endswith(".neon"):
        assert b["entries"] == 3 and b["ignored_errors"] == 16
        assert any(r["rule"].startswith("Called '…' outside of the config directory") for r in b["by_rule"])
    else:
        assert b["entries"] == 2 and b["ignored_errors"] == 14


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("Call to an undefined method App\\Foo::bar().", "Call to an undefined method Class::method()."),
        (
            "Parameter #1 $id of function foo() expects int, string given.",
            "Parameter #N $var of function function() expects int, string given.",
        ),
        (
            "Access to an undefined property App\\Models\\User::$nme.",
            "Access to an undefined property Class::$var.",
        ),
    ],
)
def test_normalise_message(msg, expected):
    assert mod.normalise_message(msg) == expected


def test_common_prefix():
    assert mod.common_prefix(["/w/p/app/A.php", "/w/p/config/b.php"]) == "/w/p/"
    assert mod.common_prefix(["/w/p/app/Http/A.php", "/w/p/app/Http/B.php"]) == "/w/p/"
    assert mod.common_prefix(["/srv/x/src/A.php"]) == "/srv/x/"
    assert mod.common_prefix(["/a/b/c.php", "/a/d/e.php"]) == "/a/"


def test_cli(tmp_path):
    r = run_script(SKILL, SCRIPT, str(F / "phpstan.json"), "--json")
    assert r.returncode == 1 and json.loads(r.stdout)["summary"]["file_errors"] == 9
    assert run_script(SKILL, SCRIPT, str(F / "phpstan.json"), "--max-errors", "9").returncode == 0
    assert run_script(SKILL, SCRIPT, str(F / "phpstan-clean.json")).returncode == 0
    r = run_script(SKILL, SCRIPT, str(F / "phpstan.json"), "--compare", str(F / "phpstan-previous.json"))
    assert r.returncode == 1 and "1 new, 2 fixed" in r.stdout
    same = run_script(SKILL, SCRIPT, str(F / "phpstan.json"), "--compare", str(F / "phpstan.json"))
    assert same.returncode == 0
    r = run_script(SKILL, SCRIPT, "--baseline", str(F / "phpstan-baseline.neon"))
    assert r.returncode == 0 and "16 ignored error(s)" in r.stdout
    r = run_script(SKILL, SCRIPT, "-", stdin=(F / "phpstan-legacy.json").read_text())
    assert r.returncode == 1 and "GENERAL" in r.stdout
    bad = tmp_path / "bad.json"
    bad.write_text('{"hello": 1}')
    assert run_script(SKILL, SCRIPT, str(bad)).returncode == 2
    (tmp_path / "text.txt").write_text("no json here")
    assert run_script(SKILL, SCRIPT, str(tmp_path / "text.txt")).returncode == 2
    assert run_script(SKILL, SCRIPT).returncode == 2
    assert run_script(SKILL, SCRIPT, "--help").returncode == 0
