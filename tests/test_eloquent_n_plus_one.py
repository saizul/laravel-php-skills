import json

import pytest

from conftest import FIXTURES, load_script, run_script

SKILL = "eloquent-n-plus-one"
SCRIPT = "find_n_plus_one.py"
mod = load_script(SKILL, SCRIPT)
F = FIXTURES / SKILL


def patterns_for(name, threshold=5):
    queries, lazy = mod.parse_input((F / name).read_text(), name)
    return mod.find(queries, threshold), lazy, queries


def test_telescope_export():
    patterns, lazy, queries = patterns_for("telescope.json")
    assert len(queries) == 70  # the request entry is ignored, string content is parsed
    assert len({q.group for q in queries}) == 2
    by_table = {p["table"]: p for p in patterns}
    assert set(by_table) == {"users", "comments", "tags"}
    users = by_table["users"]
    assert users["max_per_request"] == 15 and users["requests"] == 2 and users["total_queries"] == 30
    assert "->with('user')" in users["fix"]
    assert users["locations"] == ["/var/www/app/resources/views/posts/index.blade.php:12"]
    assert "withCount('comments')" in by_table["comments"]["fix"]
    assert by_table["comments"]["locations"] == ["/var/www/app/app/Http/Controllers/PostController.php"]
    assert "belongsToMany" in by_table["tags"]["fix"] and by_table["tags"]["requests"] == 1
    assert not lazy


def test_laravel_log_and_lazy_violations():
    patterns, lazy, queries = patterns_for("laravel.log")
    assert {q.group for q in queries} == {"req-a", "req-b"}
    assert len(patterns) == 1
    p = patterns[0]
    assert p["table"] == "order_items" and p["column"] == "order_id" and p["requests"] == 2
    assert "with('orderItems')" in p["fix"]
    assert lazy[("App\\Models\\Order", "items")] == 2


def test_plain_sql_ignores_writes():
    patterns, _, _ = patterns_for("plain.sql")
    assert [p["table"] for p in patterns] == ["prices"]


def test_clean_query_log():
    patterns, lazy, queries = patterns_for("query-log-clean.json")
    assert len(queries) == 3 and patterns == [] and not lazy


def test_threshold():
    patterns, _, _ = patterns_for("telescope.json", threshold=16)
    assert patterns == []
    patterns, _, _ = patterns_for("telescope.json", threshold=7)
    assert len(patterns) == 3


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("select * from `users` where `id` = 42 limit 1", "select * from `users` where `id` = ? limit ?"),
        ("SELECT *  FROM t WHERE name = 'O''Brien'", "select * from t where name = ?"),
        ("select * from t where id in (1, 2, 3)", "select * from t where id in (?)"),
        ("select * from t where id in (?, ?)", "select * from t where id in (?)"),
        ("select * from t2 where a = -1.5;", "select * from t2 where a = ?"),
    ],
)
def test_normalize(sql, expected):
    assert mod.normalize(sql) == expected


@pytest.mark.parametrize(
    "sql,fix",
    [
        ("select * from categories where categories.id = ?", "->with('category')"),
        ("select * from addresses where addresses.user_id = ?", "->with('addresses')"),
        ("select exists(select * from subscriptions where user_id = ?) as `exists`", "withExists"),
        ("select sum(price) as aggregate from line_items where line_items.order_id = ?", "withSum"),
        ("select * from images where images.imageable_id = ?", "->with('images')"),
        ("select * from settings where key = ?", "whereIn()"),
        ("select 1", "load the data once"),
    ],
)
def test_suggestions(sql, fix):
    assert fix in mod.suggest(mod.analyse_query(mod.normalize(sql)))


def test_singular_and_camel():
    assert mod.singular("categories") == "category"
    assert mod.singular("boxes") == "box"
    assert mod.singular("address") == "address"
    assert mod.camel("order_items") == "orderItems"


def test_json_lines_and_wrapped_object(tmp_path):
    lines = tmp_path / "q.jsonl"
    lines.write_text(
        "\n".join(json.dumps({"sql": f"select * from a where a.b_id = {i}", "request": "r"}) for i in range(5))
    )
    queries, _ = mod.parse_input(lines.read_text(), "q.jsonl")
    assert len(mod.find(queries, 5)) == 1
    wrapped = {"data": [{"query": f"select * from a where a.id = {i}"} for i in range(6)]}
    queries, _ = mod.parse_input(json.dumps(wrapped), "w.json")
    assert len(queries) == 6 and mod.find(queries, 5)[0]["table"] == "a"


def test_cli(tmp_path):
    r = run_script(SKILL, SCRIPT, str(F / "telescope.json"), "--json")
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert data["requests"] == 2 and len(data["patterns"]) == 3
    r = run_script(SKILL, SCRIPT, str(F / "laravel.log"))
    assert r.returncode == 1 and "Lazy loading violations" in r.stdout
    assert run_script(SKILL, SCRIPT, str(F / "query-log-clean.json")).returncode == 0
    r = run_script(SKILL, SCRIPT, "-", stdin=(F / "plain.sql").read_text())
    assert r.returncode == 1 and "prices" in r.stdout
    r = run_script(SKILL, SCRIPT, str(F / "telescope.json"), "--top", "1", "--json")
    assert len(json.loads(r.stdout)["patterns"]) == 1
    assert run_script(SKILL, SCRIPT, str(tmp_path / "missing.log")).returncode == 2
    assert run_script(SKILL, SCRIPT, str(F / "plain.sql"), "--threshold", "1").returncode == 2
    assert run_script(SKILL, SCRIPT, "--help").returncode == 0
