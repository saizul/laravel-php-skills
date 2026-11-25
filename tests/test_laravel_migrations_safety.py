import json

from conftest import FIXTURES, load_script, run_script

SKILL = "laravel-migrations-safety"
SCRIPT = "migration_safety.py"
mod = load_script(SKILL, SCRIPT)
F = FIXTURES / SKILL / "project"
MIG = F / "database" / "migrations"


def check(name, big=frozenset()):
    return mod.check_file(str(MIG / name), name, set(big))


def write(tmp_path, body):
    p = tmp_path / "2026_01_01_000000_x.php"
    p.write_text("<?php\nreturn new class extends Migration {\n" + body + "\n};\n")
    return mod.check_file(str(p), p.name, set())


def test_alter_users_findings():
    found = {(f.check, f.line) for f in check("2026_11_02_000000_alter_users_table.php", {"users"})}
    assert found == {
        ("missing-down", 10),
        ("drop-column", 13),
        ("rename", 14),
        ("change", 15),
        ("not-null-no-default", 16),
        ("not-null-no-default", 19),
        ("unique-on-existing", 19),
        ("index-on-big-table", 20),
        ("not-null-no-default", 21),
        ("foreign-key", 21),
    }


def test_big_table_raises_severity():
    small = {f.check: f.severity for f in check("2026_11_02_000000_alter_users_table.php")}
    big = {f.check: f.severity for f in check("2026_11_02_000000_alter_users_table.php", {"users"})}
    assert small["change"] == "medium" and big["change"] == "high"
    assert small["foreign-key"] == "low" and big["foreign-key"] == "medium"
    assert "index-on-big-table" not in small


def test_backfill_findings():
    found = sorted((f.check, f.line) for f in check("2026_11_03_000000_backfill_orders.php"))
    assert found == [
        ("data-migration", 12),
        ("data-migration", 13),
        ("drop-table", 15),
        ("empty-down", 20),
        ("raw-statement", 14),
        ("rename", 16),
    ]


def test_safe_migrations_are_clean():
    assert check("2024_01_01_000000_create_orders_table.php") == []
    assert check("2026_11_04_000000_add_note_to_orders.php", {"users"}) == []


def test_change_inside_create_and_down_drops_are_fine(tmp_path):
    findings = write(
        tmp_path,
        "public function up(): void { Schema::create('a', function (Blueprint $t) { $t->id(); }); }\n"
        "public function down(): void { Schema::dropIfExists('a'); Schema::table('b', function ($t) "
        "{ $t->dropColumn('x'); }); }",
    )
    assert findings == []


def test_truncate_and_connection(tmp_path):
    findings = write(
        tmp_path,
        "public function up() { DB::table('logs')->truncate();\n"
        "Schema::connection('pgsql')->table('events', function ($t) { $t->renameColumn('a', 'b'); }); }\n"
        "public function down() { throw new RuntimeException('one-way'); }",
    )
    assert sorted(f.check for f in findings) == ["rename", "truncate"]


def test_not_a_migration(tmp_path):
    p = tmp_path / "helper.php"
    p.write_text("<?php function x() { return 1; }")
    assert mod.check_file(str(p), "helper.php", set()) == []


def test_match_brace_ignores_braces_in_strings():
    text = "{ $a = '}'; { } }"
    assert mod.match_brace(text, 0) == len(text) - 1


def test_cli(tmp_path):
    r = run_script(SKILL, SCRIPT, str(F), "--big-tables", "users", "--json")
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert data["files"] == 4 and data["counts"]["high"] == 5
    r = run_script(SKILL, SCRIPT, str(F), "--since", "2026_11_04")
    assert r.returncode == 0 and "1 migration(s)" in r.stdout
    one = MIG / "2026_11_03_000000_backfill_orders.php"
    assert run_script(SKILL, SCRIPT, str(one), "--fail-on", "high").returncode == 1
    r = run_script(SKILL, SCRIPT, str(MIG / "2024_01_01_000000_create_orders_table.php"), "--fail-on", "info")
    assert r.returncode == 0
    assert run_script(SKILL, SCRIPT, str(tmp_path / "nope")).returncode == 2
    assert run_script(SKILL, SCRIPT, "--help").returncode == 0
