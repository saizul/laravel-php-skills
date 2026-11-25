import json

from conftest import FIXTURES, load_script, run_script

SKILL = "laravel-testing"
SCRIPT = "find_test_smells.py"
mod = load_script(SKILL, SCRIPT)
F = FIXTURES / SKILL


def scan(name):
    root = F / name
    return mod.scan(str(root), str(root / "tests"))


def write_suite(tmp_path, files):
    for rel, body in files.items():
        p = tmp_path / "tests" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return mod.scan(str(tmp_path), str(tmp_path / "tests"))


def test_bad_suite():
    found = {(f.check, f.file, f.line) for f in scan("bad")}
    post = "tests/Feature/PostTest.php"
    inv = "tests/Feature/InvoiceTest.php"
    assert found == {
        ("focused-test", post, 11),
        ("no-db-reset", post, 8),
        ("no-db-reset", inv, 12),
        ("real-http", post, 14),
        ("sleep", post, 15),
        ("debug-output", post, 16),
        ("no-assertions", post, 12),
        ("no-assertions", post, 18),
        ("no-assertions", inv, 10),
        ("without-middleware", post, 21),
        ("hard-coded-id", post, 10),
        ("hard-coded-id", inv, 13),
        ("skipped", post, 24),
        ("skipped", inv, 24),
    }


def test_good_suite_is_clean():
    assert scan("good") == []


def test_iter_tests_shapes():
    text = (
        "<?php\n"
        "it('a', function () { expect(1)->toBe(1); });\n"
        "test('b', fn () => true);\n"
        "it('c', function () use ($x): void { foo(); })->throws(E::class);\n"
        "class T { public function test_d(): void { $this->assertTrue(true); }\n"
        "#[Test]\npublic function e(): void { }\n}\n"
    )
    names = [n for n, _, _ in mod.iter_tests(text, text)]
    assert names == ["test_d", "e", "a", "b", "c"]
    bodies = {n: b for n, _, b in mod.iter_tests(text, text)}
    assert "throws" in bodies["c"] and "true" in bodies["b"]


def test_docblock_test_without_assertion(tmp_path):
    findings = write_suite(
        tmp_path,
        {"Unit/ATest.php": "<?php class ATest { /** @test */\n public function does_it(): void { $x = 1; } }"},
    )
    assert [(f.check, f.title) for f in findings] == [("no-assertions", "test 'does_it' has no assertion")]


def test_trait_in_base_test_case_counts(tmp_path):
    findings = write_suite(
        tmp_path,
        {
            "TestCase.php": "<?php abstract class TestCase { use RefreshDatabase; }",
            "Feature/XTest.php": "<?php it('x', function () { User::factory()->create(); $this->assertTrue(true); });",
        },
    )
    assert findings == []


def test_mockery_counts_as_assertion(tmp_path):
    findings = write_suite(
        tmp_path,
        {
            "Unit/MTest.php": "<?php it('m', function () { $m = Mockery::mock(A::class); $m->shouldReceive('x')->once(); });"
        },
    )
    assert findings == []


def test_comments_are_ignored(tmp_path):
    findings = write_suite(
        tmp_path,
        {"Unit/CTest.php": "<?php\n// sleep(1); dd($x);\n/* ->only() */\nit('c', fn () => expect(1)->toBe(1));"},
    )
    assert findings == []


def test_cli(tmp_path):
    r = run_script(SKILL, SCRIPT, str(F / "bad"), "--json")
    assert r.returncode == 1 and json.loads(r.stdout)["counts"]["high"] == 1
    assert run_script(SKILL, SCRIPT, str(F / "good")).returncode == 0
    r = run_script(SKILL, SCRIPT, str(F / "bad"), "--fail-on", "high")
    assert r.returncode == 1 and "focused-test" in r.stdout
    assert run_script(SKILL, SCRIPT, str(tmp_path)).returncode == 2
    assert run_script(SKILL, SCRIPT, str(F / "bad"), "--tests-dir", "tests/Unit").returncode == 0
    assert run_script(SKILL, SCRIPT, "--help").returncode == 0
