#!/usr/bin/env python3
"""Scan a Laravel project for common security mistakes. Read-only.

Checks PHP, Blade and .env files as text (no PHP needed):
  mass-assignment   $guarded = [], Model::unguard(), $request->all() into create/update/fill
  raw-sql           DB::raw/whereRaw/selectRaw/orderByRaw/DB::select... with interpolated or
                    concatenated variables; orderBy()/groupBy() on request input
  blade-unescaped   {!! !!} output (high when it prints request data)
  csrf              wildcard or broad CSRF exceptions, CSRF middleware removed
  debug             APP_DEBUG=true in .env files, 'debug' => true hard-coded in config/app.php
  authorization     controller store/update/destroy/edit methods with no visible authorization
  dangerous-call    unserialize/eval/exec/shell_exec/system/passthru on request input
  tls               Http::withoutVerifying() / 'verify' => false
  cors              allowed_origins '*' together with supports_credentials true
  debug-helper      dd()/dump()/var_dump() left in app code

Suppress a finding by putting `security-scan: ignore` in a comment on the same line.
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
SKIP_DIRS = {"vendor", "node_modules", "storage", ".git", "public", ".idea", ".vscode"}
IGNORE_MARK = "security-scan: ignore"


@dataclass
class Finding:
    severity: str
    check: str
    file: str
    line: int
    title: str
    fix: str
    snippet: str = ""


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def strip_php_comments(text: str) -> str:
    """Blank out // # and /* */ comments while keeping offsets and newlines.

    Strings are respected so a '#' or '//' inside a string is kept.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"":
            q = c
            i += 1
            while i < n and text[i] != q:
                i += 2 if text[i] == "\\" else 1
            i += 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            for k in range(i, end):
                if out[k] != "\n":
                    out[k] = " "
            i = end
            continue
        if text.startswith("//", i) or (c == "#" and not text.startswith("#[", i)):
            end = text.find("\n", i)
            end = n if end == -1 else end
            if IGNORE_MARK in text[i:end]:
                # keep the marker so per-line suppression still works
                i = end
                continue
            for k in range(i, end):
                out[k] = " "
            i = end
            continue
        i += 1
    return "".join(out)


REQUEST_INPUT = r"(?:\$request->|request\(\)|Request::|\$_(?:GET|POST|REQUEST|COOKIE)|request\(\s*['\"])"
RAW_FUNCS = (
    r"(?:DB::raw|DB::select|DB::statement|DB::insert|DB::update|DB::delete|DB::unprepared|"
    r"->(?:whereRaw|orWhereRaw|selectRaw|orderByRaw|havingRaw|orHavingRaw|groupByRaw|fromRaw|joinRaw))"
)
RAW_CALL_RE = re.compile(RAW_FUNCS + r"\s*\(\s*")
CSRF_FIELD_SAFE = re.compile(
    r"^\s*(?:csrf_field\(\)|method_field\([^)]*\)|\$[\w>-]+->links\([^)]*\)|"
    r"\$[\w>-]+->render\(\)|Vite::|vite\(|\$__env->)"
)
AUTH_TOKENS = re.compile(
    r"(?:->authorize\(|Gate::|->can\(|->cannot\(|->cant\(|\$this->authorize|abort_unless\(|abort_if\(|"
    r"->authorizeResource\(|Policy|->allows\(|->denies\(|->authorizeForUser\(|can:|->inspect\()"
)
ACTION_METHODS = ("store", "update", "destroy", "edit", "delete", "restore", "forceDelete")


def first_arg(text: str, start: int) -> str:
    """Return the source of the first call argument beginning at `start` (after '(')."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c in "'\"":
            q = c
            i += 1
            while i < n and text[i] != q:
                i += 2 if text[i] == "\\" else 1
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return text[start:i]
            depth -= 1
        elif c == "," and depth == 0:
            return text[start:i]
        i += 1
    return text[start:]


def is_interpolated(arg: str) -> bool:
    arg = arg.strip()
    if re.search(r'"[^"]*(?<!\\)\$[A-Za-z_{][^"]*"', arg):
        return True
    if re.search(r"^<<<\s*\"?\w+", arg) and "$" in arg:
        return True
    # concatenation with a variable or call outside a string
    no_strings = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", "''", arg)
    if "." in no_strings and re.search(r"\$\w|\w\(", no_strings):
        return True
    if re.fullmatch(r"\$\w+(?:->\w+|\[[^\]]*\])*", no_strings.strip()):
        return True
    return False


class Scanner:
    def __init__(self, root: str):
        self.root = root
        self.findings: list[Finding] = []

    def add(self, sev, check, path, text, pos, title, fix):
        line_no = line_of(text, pos)
        lines = text.splitlines()
        src = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
        if IGNORE_MARK in src:
            return
        rel = os.path.relpath(path, self.root) if os.path.isdir(self.root) else os.path.basename(path)
        self.findings.append(Finding(sev, check, rel, line_no, title, fix, src.strip()[:160]))

    # ---- PHP -----------------------------------------------------------------
    def scan_php(self, path: str, raw: str) -> None:
        text = strip_php_comments(raw)
        rel = os.path.relpath(path, self.root).replace(os.sep, "/") if os.path.isdir(self.root) else path
        for m in re.finditer(r"(?:protected|public)\s+\$guarded\s*=\s*(?:\[\s*\]|array\(\s*\))", text):
            self.add(
                "high",
                "mass-assignment",
                path,
                raw,
                m.start(),
                "model has $guarded = [] (every attribute is mass assignable)",
                "List assignable columns in $fillable, or guard sensitive ones (is_admin, role, user_id).",
            )
        for m in re.finditer(r"\b(?:Model|Eloquent)::unguard\(\)", text):
            self.add(
                "medium",
                "mass-assignment",
                path,
                raw,
                m.start(),
                "Model::unguard() disables mass-assignment protection globally",
                "Remove it outside seeders; never call it in a service provider.",
            )
        for m in re.finditer(r"\$fillable\s*=\s*\[([^\]]*)\]", text):
            sensitive = re.findall(r"['\"](is_admin|admin|role|roles|is_superuser|permissions)['\"]", m.group(1))
            if sensitive:
                self.add(
                    "medium",
                    "mass-assignment",
                    path,
                    raw,
                    m.start(),
                    f"privilege column(s) in $fillable: {', '.join(sorted(set(sensitive)))}",
                    "Set privilege columns explicitly after authorization, not via create()/update().",
                )
        for m in re.finditer(
            r"(?:::|->)(?:create|update|fill|forceFill|forceCreate|updateOrCreate|firstOrCreate|insert)"
            r"\(\s*(?:\[[^\]]*\]\s*,\s*)?(?:\$request->all\(\)|request\(\)->all\(\)|Request::all\(\)|"
            r"\$request->input\(\)|\$_POST)",
            text,
        ):
            self.add(
                "high",
                "mass-assignment",
                path,
                raw,
                m.start(),
                "unfiltered request data passed to a model write",
                "Use $request->validated() from a FormRequest, or $request->only([...]).",
            )

        for m in RAW_CALL_RE.finditer(text):
            arg = first_arg(text, m.end())
            if is_interpolated(arg):
                sev = "high"
                self.add(
                    sev,
                    "raw-sql",
                    path,
                    raw,
                    m.start(),
                    f"{m.group(0).strip(' (')} built with interpolated/concatenated values",
                    "Use bindings: ->whereRaw('price > ?', [$price]) or DB::select('... = ?', [$id]).",
                )
        for m in re.finditer(r"->(orderBy|orderByDesc|groupBy|latest|oldest)\(\s*" + REQUEST_INPUT, text):
            self.add(
                "medium",
                "raw-sql",
                path,
                raw,
                m.start(),
                f"{m.group(1)}() column taken from request input (column names are not bound)",
                "Map the input to an allow-list: in_array($col, ['name', 'created_at'], true).",
            )

        for m in re.finditer(
            r"\b(unserialize|eval|exec|shell_exec|system|passthru|popen|proc_open|assert)\s*\(\s*[^;]*?"
            + REQUEST_INPUT,
            text,
        ):
            self.add(
                "high",
                "dangerous-call",
                path,
                raw,
                m.start(),
                f"{m.group(1)}() called with request input",
                "Never pass user input to these functions; use json_decode, Process with an argument "
                "array, or an allow-list.",
            )
        for m in re.finditer(r"(?:->|::)withoutVerifying\(\)|['\"]verify['\"]\s*=>\s*false", text):
            self.add(
                "medium",
                "tls",
                path,
                raw,
                m.start(),
                "TLS certificate verification disabled for outgoing HTTP",
                "Remove withoutVerifying()/verify=false; fix the CA bundle instead.",
            )

        if "/app/" in "/" + rel and not rel.startswith("tests/"):
            for m in re.finditer(r"(?<![\w>$:])(dd|dump|var_dump|ray)\s*\(", text):
                self.add(
                    "low",
                    "debug-helper",
                    path,
                    raw,
                    m.start(),
                    f"{m.group(1)}() left in application code",
                    "Remove it; use Log::debug() if you need the data.",
                )

        self.scan_csrf(path, raw, text)
        self.scan_config(path, raw, text, rel)
        if "Http/Controllers/" in rel and not rel.endswith("/Controller.php"):
            self.scan_controller(path, raw, text)

    def scan_csrf(self, path, raw, text):
        for m in re.finditer(r"\$except\s*=\s*\[([^\]]*)\]", text):
            if "VerifyCsrfToken" not in text and "Csrf" not in os.path.basename(path):
                continue
            self._csrf_entries(path, raw, m.start(1), m.group(1))
        for m in re.finditer(r"validateCsrfTokens\(\s*except:\s*\[([^\]]*)\]", text):
            self._csrf_entries(path, raw, m.start(1), m.group(1))
        for m in re.finditer(r"withoutMiddleware\(\s*\[?[^)]*(?:VerifyCsrfToken|ValidateCsrfToken)::class", text):
            self.add(
                "medium",
                "csrf",
                path,
                raw,
                m.start(),
                "CSRF middleware removed from routes",
                "Keep CSRF on browser routes; move token-authenticated endpoints to routes/api.php.",
            )

    def _csrf_entries(self, path, raw, offset, body):
        for em in re.finditer(r"['\"]([^'\"]+)['\"]", body):
            entry = em.group(1)
            pos = offset + em.start()
            if entry.strip() in ("*", "/*"):
                self.add(
                    "high",
                    "csrf",
                    path,
                    raw,
                    pos,
                    "CSRF protection disabled for every route ('*')",
                    "Remove '*'; list only webhook URIs that verify their own signatures.",
                )
            elif entry.endswith("*") and entry.count("/") <= 1:
                self.add(
                    "medium",
                    "csrf",
                    path,
                    raw,
                    pos,
                    f"broad CSRF exception '{entry}'",
                    "Narrow it to the exact webhook path and verify the provider signature.",
                )

    def scan_config(self, path, raw, text, rel):
        if rel.endswith("config/app.php"):
            for m in re.finditer(r"['\"]debug['\"]\s*=>\s*true\b", text):
                self.add(
                    "high",
                    "debug",
                    path,
                    raw,
                    m.start(),
                    "'debug' => true hard-coded in config/app.php",
                    "Use 'debug' => (bool) env('APP_DEBUG', false).",
                )
        if rel.endswith("config/cors.php"):
            origins = re.search(r"['\"]allowed_origins['\"]\s*=>\s*\[\s*['\"]\*['\"]", text)
            creds = re.search(r"['\"]supports_credentials['\"]\s*=>\s*true", text)
            if origins and creds:
                self.add(
                    "high",
                    "cors",
                    path,
                    raw,
                    origins.start(),
                    "CORS allows any origin with credentials",
                    "List your front-end origins explicitly when supports_credentials is true.",
                )

    def scan_controller(self, path, raw, text):
        class_level = re.search(r"authorizeResource\(|middleware\(\s*['\"]can:|HasMiddleware", text)
        if class_level:
            return
        methods = list(re.finditer(r"public\s+function\s+(\w+)\s*\(([^)]*)\)[^{;]*\{", text))
        for idx, m in enumerate(methods):
            name, params = m.group(1), m.group(2)
            if name not in ACTION_METHODS:
                continue
            end = methods[idx + 1].start() if idx + 1 < len(methods) else len(text)
            body = text[m.end() : end]
            form_request = re.search(r"\b(?!Request\b)\w+Request\s+\$", params)
            if AUTH_TOKENS.search(body) or form_request:
                continue
            self.add(
                "medium",
                "authorization",
                path,
                raw,
                m.start(),
                f"{name}() has no visible authorization",
                "Add $this->authorize()/Gate::authorize(), a FormRequest with authorize(), or a "
                "'can:' route middleware (check routes/ before reporting).",
            )

    # ---- Blade ---------------------------------------------------------------
    def scan_blade(self, path, raw):
        text = re.sub(r"\{\{--.*?--\}\}", lambda m: re.sub(r"[^\n]", " ", m.group(0)), raw, flags=re.S)
        for m in re.finditer(r"\{!!(.*?)!!\}", text, re.S):
            expr = m.group(1)
            if CSRF_FIELD_SAFE.match(expr):
                continue
            user = re.search(REQUEST_INPUT + r"|old\(|\$_GET|\$_POST", expr)
            sev = "high" if user else "medium"
            self.add(
                sev,
                "blade-unescaped",
                path,
                raw,
                m.start(),
                "unescaped Blade output of request data" if user else "unescaped Blade output {!! !!}",
                "Use {{ }}; if HTML is required, sanitize it first (e.g. a purifier) and document why.",
            )

    # ---- .env ----------------------------------------------------------------
    def scan_env(self, path, raw):
        values = {}
        for m in re.finditer(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$", raw, re.M):
            values[m.group(1)] = (m.group(2).strip().strip("\"'"), m.start())
        name = os.path.basename(path)
        app_env = values.get("APP_ENV", ("", 0))[0].lower()
        debug = values.get("APP_DEBUG")
        if debug and debug[0].lower() in ("true", "1", "on", "yes"):
            prod = app_env == "production" or "prod" in name
            self.add(
                "high" if prod else ("medium" if name != ".env" else "low"),
                "debug",
                path,
                raw,
                debug[1],
                f"APP_DEBUG=true in {name}" + (" with APP_ENV=production" if app_env == "production" else ""),
                "Ship APP_DEBUG=false; examples copied to servers should default to false.",
            )
        if app_env == "production":
            sec = values.get("SESSION_SECURE_COOKIE")
            if sec and sec[0].lower() in ("false", "0"):
                self.add(
                    "low",
                    "debug",
                    path,
                    raw,
                    sec[1],
                    "SESSION_SECURE_COOKIE=false in production",
                    "Set SESSION_SECURE_COOKIE=true behind HTTPS.",
                )

    # ---- walk ----------------------------------------------------------------
    def run(self, paths: list[str]) -> list[Finding]:
        for target in paths:
            if os.path.isfile(target):
                self.scan_file(target)
                continue
            for dirpath, dirnames, filenames in os.walk(target):
                dirnames[:] = sorted(
                    d
                    for d in dirnames
                    if d not in SKIP_DIRS and not (d == "cache" and os.path.basename(dirpath) == "bootstrap")
                )
                for fn in sorted(filenames):
                    self.scan_file(os.path.join(dirpath, fn))
        order = {s: i for i, s in enumerate(SEVERITIES)}
        self.findings.sort(key=lambda f: (-order[f.severity], f.file, f.line))
        return self.findings

    def scan_file(self, path: str) -> None:
        name = os.path.basename(path)
        is_env = name == ".env" or name.startswith(".env.")
        if not (is_env or name.endswith(".php")):
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError:
            return
        if is_env:
            self.scan_env(path, raw)
        elif name.endswith(".blade.php"):
            self.scan_blade(path, raw)
        else:
            self.scan_php(path, raw)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Scan a Laravel project for security mistakes (read-only).",
        epilog="Example: laravel_security_scan.py . --fail-on high --json",
    )
    p.add_argument("paths", nargs="*", default=["."], help="project root(s) or files (default: .)")
    p.add_argument("--json", action="store_true", help="print JSON")
    p.add_argument("--fail-on", choices=SEVERITIES, default="medium", help="exit 1 at or above this")
    p.add_argument("--min-severity", choices=SEVERITIES, default="info", help="hide findings below this")
    args = p.parse_args(argv)
    for t in args.paths:
        if not os.path.exists(t):
            print(f"error: {t} does not exist", file=sys.stderr)
            return 2
    root = args.paths[0] if os.path.isdir(args.paths[0]) else os.path.dirname(args.paths[0]) or "."
    findings = Scanner(root).run(args.paths)
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    shown = [f for f in findings if rank[f.severity] >= rank[args.min_severity]]
    counts = {s: sum(1 for f in shown if f.severity == s) for s in reversed(SEVERITIES)}
    if args.json:
        print(json.dumps({"counts": counts, "findings": [asdict(f) for f in shown]}, indent=2))
    else:
        summary = ", ".join(f"{n} {s}" for s, n in counts.items())
        print(f"laravel security scan: {summary}")
        for f in shown:
            print(f"{f.severity.upper():6} {f.file}:{f.line}  [{f.check}] {f.title}")
            if f.snippet:
                print(f"       > {f.snippet}")
            print(f"       fix: {f.fix}")
    failing = any(rank[f.severity] >= rank[args.fail_on] for f in shown)
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
