#!/usr/bin/env python3
"""Find smells in a Laravel test suite (Pest or PHPUnit). Read-only.

Checks tests/**/*.php as text:
  focused-test        Pest ->only() / test()->only(): CI runs only that test
  debug-output        dd() / dump() / ray() / var_dump() in tests
  sleep               sleep()/usleep(): use $this->travel() / Carbon::setTestNow() / Sleep::fake()
  no-db-reset         uses the database without RefreshDatabase / DatabaseTransactions /
                      LazilyRefreshDatabase / DatabaseMigrations (in the file or tests/Pest.php)
  real-http           Http:: / Guzzle calls without Http::fake() or preventStrayRequests()
  no-assertions       a test body with no assertion or expectation
  without-middleware  withoutMiddleware() hides auth/CSRF behaviour
  hard-coded-id       HTTP test hitting /resource/1 instead of a factory model's id
  skipped             skipped / incomplete tests (info)

Exit codes: 0 = nothing at or above --fail-on, 1 = findings, 2 = error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass

SEVERITIES = ["info", "low", "medium", "high"]
DB_TRAITS = re.compile(
    r"\b(RefreshDatabase|LazilyRefreshDatabase|DatabaseTransactions|DatabaseMigrations|DatabaseTruncation)\b"
)
DB_USE = re.compile(
    r"::factory\(|assertDatabase(?:Has|Missing|Count|Empty)|assertSoftDeleted|assertModel(?:Exists|Missing)|"
    r"\bDB::table\(|->create\(\s*\[|::create\(\s*\[|->seed\("
)
HTTP_USE = re.compile(
    r"\bHttp::(?:get|post|put|patch|delete|send|withHeaders|withToken|acceptJson|baseUrl|asForm)\b|new\s+(?:\\?GuzzleHttp\\)?Client\("
)
HTTP_FAKE = re.compile(r"Http::(?:fake|preventStrayRequests)\(")
ASSERTION = re.compile(
    r"\bassert\w*\(|->assert\w*\(|\bexpect\(|->expect\w*\(|\$this->expect\w*\(|->toBe\w*\(|"
    r"::assert\w*\(|->throws\(|->throwsIf\(|->expectsOutput|->expectsQuestion|->expectsJobs|"
    r"\bfail\(|Mockery::|->shouldReceive\(|->shouldHaveReceived\(|->once\(\)|->twice\(\)|"
    r"\$this->mock\(|\$this->partialMock\(|\$this->spy\(|->assertExitCode\("
)
HTTP_TEST_CALL = re.compile(
    r"->(?:get|post|put|patch|delete|getJson|postJson|putJson|patchJson|deleteJson|json)\(\s*"
    r"(?:['\"][A-Z]+['\"]\s*,\s*)?['\"](/[^'\"]*?/\d+(?:/[^'\"]*)?)['\"]"
)


@dataclass
class Finding:
    severity: str
    check: str
    file: str
    line: int
    title: str
    fix: str


def strip_comments(text: str) -> str:
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))

    text = re.sub(r"/\*.*?\*/", blank, text, flags=re.S)
    return re.sub(r"(?m)(?<![:'\"])//[^\n]*", blank, text)


def match_brace(text: str, pos: int) -> int:
    depth, i, n = 0, pos, len(text)
    while i < n:
        c = text[i]
        if c in "'\"":
            q = c
            i += 1
            while i < n and text[i] != q:
                i += 2 if text[i] == "\\" else 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def iter_tests(text: str, raw: str | None = None):
    """Yield (name, start_pos, body_text) for PHPUnit test methods and Pest tests."""
    for m in re.finditer(r"public\s+function\s+(test\w*)\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{", text):
        end = match_brace(text, m.end() - 1)
        yield m.group(1), m.start(), text[m.end() : end]
    for m in re.finditer(
        r"#\[(?:\\?PHPUnit\\Framework\\Attributes\\)?Test\]\s*public\s+function\s+(\w+)\s*\([^)]*\)\s*(?::\s*\w+)?\s*\{",
        text,
    ):
        if m.group(1).startswith("test"):
            continue
        end = match_brace(text, m.end() - 1)
        yield m.group(1), m.start(), text[m.end() : end]
    for m in re.finditer(r"/\*\*[^/]*@test\b[^/]*\*/\s*public\s+function\s+(\w+)\s*\([^)]*\)[^{]*\{", raw or text):
        if m.group(1).startswith("test"):
            continue
        end = match_brace(text, m.end() - 1)
        yield m.group(1), m.start(), text[m.end() : end]
    for m in re.finditer(
        r"(?m)^\s*(?:test|it)\(\s*(['\"])(.+?)\1\s*,\s*(?:static\s+)?(function\s*\([^)]*\)(?:\s*use\s*\([^)]*\))?\s*(?::\s*\w+)?\s*\{|fn\s*\()",
        text,
    ):
        if m.group(3).startswith("fn"):
            # arrow function: body runs to the paren closing test( (we are inside test( and fn( )
            depth, i = 2, m.end()
            while i < len(text) and depth:
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                i += 1
            yield m.group(2), m.start(), text[m.end() : i]
            continue
        end = match_brace(text, m.end() - 1)
        tail = text[end : end + 400]
        yield m.group(2), m.start(), text[m.end() : end] + tail.split(";", 1)[0]


def scan(root: str, tests_dir: str) -> list[Finding]:
    findings: list[Finding] = []
    pest_path = os.path.join(tests_dir, "Pest.php")
    pest_global = ""
    if os.path.isfile(pest_path):
        with open(pest_path, encoding="utf-8", errors="replace") as fh:
            pest_global = strip_comments(fh.read())
    global_db = bool(DB_TRAITS.search(pest_global))
    base_case = os.path.join(tests_dir, "TestCase.php")
    if os.path.isfile(base_case):
        with open(base_case, encoding="utf-8", errors="replace") as fh:
            global_db = global_db or bool(DB_TRAITS.search(strip_comments(fh.read())))
    global_http_fake = bool(HTTP_FAKE.search(pest_global))

    files = []
    for dirpath, dirnames, filenames in os.walk(tests_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in ("fixtures", "Fixtures", "__snapshots__"))
        for fn in sorted(filenames):
            if fn.endswith(".php") and fn not in ("Pest.php", "TestCase.php", "CreatesApplication.php"):
                files.append(os.path.join(dirpath, fn))

    for path in files:
        with open(path, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        text = strip_comments(raw)
        rel = os.path.relpath(path, root)

        def add(sev, check, pos, title, fix, rel=rel, text=text):
            findings.append(Finding(sev, check, rel, line_of(text, pos), title, fix))

        for m in re.finditer(r"\)\s*->only\(\s*\)", text):
            add(
                "high",
                "focused-test",
                m.start(),
                "focused test with ->only(): CI runs only this test",
                "Remove ->only() before committing.",
            )
        for m in re.finditer(r"(?<![\w>$:])(dd|dump|ray|var_dump|print_r)\s*\(", text):
            add(
                "medium",
                "debug-output",
                m.start(),
                f"{m.group(1)}() in a test",
                "Remove it; use assertions or ->dump() locally only.",
            )
        for m in re.finditer(r"(?<![\w>$:])(sleep|usleep)\s*\(", text):
            add(
                "medium",
                "sleep",
                m.start(),
                f"{m.group(1)}() slows the suite and makes it flaky",
                "Use $this->travel(5)->minutes(), Carbon::setTestNow() or Sleep::fake() (Laravel 10+).",
            )
        uses_db = DB_USE.search(text)
        if uses_db and not global_db and not DB_TRAITS.search(text):
            add(
                "medium",
                "no-db-reset",
                uses_db.start(),
                "uses the database but never resets it",
                "Add use RefreshDatabase (PHPUnit) or pest()->use(RefreshDatabase::class)->in('Feature').",
            )
        http = HTTP_USE.search(text)
        if http and not global_http_fake and not HTTP_FAKE.search(text) and "MockHandler" not in text:
            add(
                "medium",
                "real-http",
                http.start(),
                "outgoing HTTP without Http::fake()",
                "Call Http::fake([...]) and Http::preventStrayRequests() so tests never hit real APIs.",
            )
        for m in re.finditer(r"->withoutMiddleware\(\s*\)", text):
            add(
                "low",
                "without-middleware",
                m.start(),
                "withoutMiddleware() disables auth, CSRF and throttling",
                "Authenticate with actingAs() instead, or disable only one middleware class.",
            )
        for m in HTTP_TEST_CALL.finditer(text):
            add(
                "low",
                "hard-coded-id",
                m.start(),
                f"hard-coded id in URL {m.group(1)}",
                "Create the model with a factory and use route('posts.show', $post) or \"/posts/{$post->id}\".",
            )
        for m in re.finditer(r"->skip\(|markTestSkipped\(|markTestIncomplete\(|->todo\(\)|\btodo\(", text):
            add(
                "info",
                "skipped",
                m.start(),
                "skipped or incomplete test",
                "Fix or delete it; track the reason in an issue.",
            )
        for name, pos, body in iter_tests(text, raw):
            if re.search(r"->(skip|todo)\(", body) or "markTest" in body:
                continue
            if not ASSERTION.search(body):
                add(
                    "low",
                    "no-assertions",
                    pos,
                    f"test '{name}' has no assertion",
                    "Assert the outcome (assertOk(), assertDatabaseHas(), expect()->toBe()).",
                )
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: (-rank[f.severity], f.file, f.line))
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Find smells in a Laravel Pest/PHPUnit test suite (read-only).",
        epilog="Example: find_test_smells.py /path/to/project --fail-on high",
    )
    ap.add_argument("root", nargs="?", default=".", help="project root containing tests/ (default .)")
    ap.add_argument("--tests-dir", default="tests", help="tests directory relative to root (default tests)")
    ap.add_argument("--fail-on", choices=SEVERITIES, default="medium", help="exit 1 at or above (default medium)")
    ap.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args(argv)
    tests_dir = os.path.join(args.root, args.tests_dir)
    if not os.path.isdir(tests_dir):
        print(f"error: {tests_dir} is not a directory", file=sys.stderr)
        return 2
    findings = scan(args.root, tests_dir)
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    counts = {s: sum(1 for f in findings if f.severity == s) for s in reversed(SEVERITIES)}
    if args.json:
        print(json.dumps({"counts": counts, "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        print("test smells: " + ", ".join(f"{n} {s}" for s, n in counts.items()))
        for f in findings:
            print(f"{f.severity.upper():6} {f.file}:{f.line}  [{f.check}] {f.title}\n       fix: {f.fix}")
    return 1 if any(rank[f.severity] >= rank[args.fail_on] for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
