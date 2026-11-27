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


DROPS = """public function up(): void {
    Schema::table('orders', function (Blueprint $table) {
        $table->dropIndex(['status', 'created_at']);
        $table->dropUnique('orders_number_unique');
        $table->dropForeign(['customer_id']);
        $table->dropPrimary();
        $table->dropConstrainedForeignId('coupon_id');
        $table->dropForeignIdFor(Store::class);
    });
}
public function down(): void { }"""


def drops(tmp_path, big=()):
    p = tmp_path / "2026_01_01_000000_drops.php"
    p.write_text("<?php\nreturn new class extends Migration {\n" + DROPS + "\n};\n")
    return mod.check_file(str(p), p.name, set(big))


def test_drop_index_findings(tmp_path):
    found = {(f.check, f.line, f.severity) for f in drops(tmp_path) if f.check != "empty-down"}
    assert found == {
        ("drop-index", 5, "low"),
        ("drop-index", 6, "medium"),
        ("drop-index", 7, "low"),
        ("drop-index", 8, "low"),
        ("drop-column", 9, "high"),
        ("drop-column", 10, "high"),
    }
    titles = {f.line: f.title for f in drops(tmp_path)}
    assert "duplicates" in titles[6] and "orphaned" in titles[7] and "full scans" in titles[5]


def test_drop_index_on_big_table_is_medium(tmp_path):
    sev = {f.line: f.severity for f in drops(tmp_path, {"orders"}) if f.check == "drop-index"}
    assert sev == {5: "medium", 6: "medium", 7: "low", 8: "medium"}


def test_drop_index_in_create_block_and_cli(tmp_path):
    found = write(
        tmp_path,
        "public function up(): void { Schema::create('t', function (Blueprint $table) { $table->id(); "
        "$table->dropIndex('t_x_index'); }); }\npublic function down(): void { Schema::dropIfExists('t'); }",
    )
    assert [f.check for f in found] == ["drop-index"]
    res = run_script(SKILL, SCRIPT, str(tmp_path), "--json", "--fail-on", "low")
    assert res.returncode == 1
    assert json.loads(res.stdout)["counts"]["low"] == 1
    assert run_script(SKILL, SCRIPT, str(tmp_path), "--fail-on", "medium").returncode == 0
