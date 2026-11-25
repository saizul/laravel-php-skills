#!/usr/bin/env python3
"""Audit a Laravel project and its PHP settings for production performance. Read-only.

Project checks (text, no PHP needed):
  env-outside-config   env() outside config/ returns null once `php artisan config:cache` runs
  env-file             APP_DEBUG / APP_ENV / LOG_LEVEL / CACHE_STORE / SESSION_DRIVER /
                       QUEUE_CONNECTION in .env (only these keys are read, values never printed
                       except these non-secret ones)
  dev-packages         debugbar / telescope / clockwork / ray in "require" instead of "require-dev"
  autoloader           composer.json without optimize-autoloader
  caches               --deployed: bootstrap/cache config.php, routes-v7.php, events.php missing
  query-patterns       Model::all() and ->get()->count() / ->get()->isEmpty() in app/
PHP checks (--php-ini FILE: a php.ini, a conf.d snippet, or `php -i` output):
  opcache              enable, memory_consumption, interned_strings_buffer, max_accelerated_files,
                       validate_timestamps, realpath_cache_size, JIT

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
DEV_PACKAGES = (
    "barryvdh/laravel-debugbar",
    "laravel/telescope",
    "itsgoingd/clockwork",
    "spatie/laravel-ray",
    "laravel/pail",
)
SKIP = {"vendor", "node_modules", "storage", ".git", "public", "config", "tests", "database"}


@dataclass
class Finding:
    severity: str
    check: str
    where: str
    title: str
    fix: str


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return re.sub(r"(?m)(?<![:'\"])//[^\n]*", "", text)


def parse_env(text: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", text, re.M):
        out[m.group(1)] = m.group(2).strip("\"'")
    return out


def parse_php_ini(text: str) -> dict[str, str]:
    """Accept php.ini syntax (key = value) and `php -i` output (key => local => master)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith((";", "#", "[")):
            continue
        m = re.match(r"^([\w.]+)\s*=>\s*(.*?)\s*=>\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
            out["__phpinfo__"] = "1"
            continue
        m = re.match(r"^([\w.]+)\s*=\s*(.*?)\s*(?:;.*)?$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip("\"'")
    return out


def to_bool(v: str | None) -> bool | None:
    if v is None:
        return None
    return v.strip().lower() in ("1", "on", "true", "yes")


def to_bytes(v: str | None) -> int | None:
    if not v:
        return None
    m = re.match(r"^(\d+)\s*([KMG])?", v.strip(), re.I)
    if not m:
        return None
    n = int(m.group(1))
    mult = {"k": 1024, "m": 1024**2, "g": 1024**3}.get((m.group(2) or "").lower(), 1)
    return n * mult


def check_php(ini: dict[str, str], production: bool) -> list[Finding]:
    f: list[Finding] = []
    src = "php.ini"
    if not ini:
        return f
    # In `php -i` output a missing opcache.enable means the extension is not loaded;
    # in an ini file it means the default (1).
    missing = "opcache.enable" not in ini and "__phpinfo__" in ini
    if to_bool(ini.get("opcache.enable", "1")) is False or missing:
        f.append(
            Finding(
                "high",
                "opcache",
                src,
                "OPcache is disabled or not loaded",
                "Install/enable OPcache: opcache.enable=1 (php8.x-opcache package on Debian/Ubuntu).",
            )
        )
        return f
    mem = ini.get("opcache.memory_consumption")
    if mem and mem.isdigit() and int(mem) < 128:
        f.append(
            Finding(
                "medium",
                "opcache",
                src,
                f"opcache.memory_consumption={mem} MB is small",
                "Use 256 for a typical Laravel app; check opcache_get_status() for free memory.",
            )
        )
    isb = ini.get("opcache.interned_strings_buffer")
    if isb and isb.isdigit() and int(isb) < 16:
        f.append(
            Finding(
                "low",
                "opcache",
                src,
                f"opcache.interned_strings_buffer={isb} MB",
                "Use 16-32 for frameworks with many classes.",
            )
        )
    maf = ini.get("opcache.max_accelerated_files")
    if maf and maf.isdigit() and int(maf) < 20000:
        f.append(
            Finding(
                "medium",
                "opcache",
                src,
                f"opcache.max_accelerated_files={maf} is below the file count of most Laravel apps",
                "Use 20000 or more (vendor/ alone often has 10k+ files).",
            )
        )
    vt = to_bool(ini.get("opcache.validate_timestamps"))
    if production and vt is not False:
        f.append(
            Finding(
                "low",
                "opcache",
                src,
                "opcache.validate_timestamps is on in production",
                "Set 0 and reload PHP-FPM on every deploy (the deploy script must do this).",
            )
        )
    rcs = to_bytes(ini.get("realpath_cache_size"))
    if rcs is not None and rcs < 4096 * 1024:
        f.append(
            Finding(
                "low",
                "realpath",
                src,
                f"realpath_cache_size={ini.get('realpath_cache_size')}",
                "Use 4096K or more; Laravel touches many files per request.",
            )
        )
    jit = ini.get("opcache.jit")
    jit_buf = to_bytes(ini.get("opcache.jit_buffer_size"))
    if jit and jit not in ("0", "off", "disable", "disabled") and not jit_buf:
        f.append(
            Finding(
                "info",
                "jit",
                src,
                "opcache.jit set but jit_buffer_size is 0: JIT is inactive",
                "JIT rarely helps typical web requests; leave it off unless you benchmarked it.",
            )
        )
    if ini.get("xdebug.mode", "off").lower() not in ("off", "", "no value"):
        f.append(
            Finding(
                "high",
                "xdebug",
                src,
                f"Xdebug enabled (xdebug.mode={ini.get('xdebug.mode')})",
                "Never load Xdebug in production; it slows every request several times.",
            )
        )
    return f


def check_project(root: str, env_path: str | None, deployed: bool) -> tuple[list[Finding], bool]:
    f: list[Finding] = []
    env = parse_env(read(env_path or os.path.join(root, ".env")))
    production = env.get("APP_ENV", "").lower() == "production"

    if env:
        if production and to_bool(env.get("APP_DEBUG")):
            f.append(
                Finding(
                    "high",
                    "env-file",
                    ".env",
                    "APP_DEBUG=true in production",
                    "Set APP_DEBUG=false (debug mode also collects data on every request).",
                )
            )
        if production and env.get("LOG_LEVEL", "debug").lower() == "debug":
            f.append(
                Finding(
                    "low",
                    "env-file",
                    ".env",
                    "LOG_LEVEL is debug in production (default when unset)",
                    "Use LOG_LEVEL=warning or error to cut disk I/O.",
                )
            )
        if production and env.get("QUEUE_CONNECTION", "") == "sync":
            f.append(
                Finding(
                    "medium",
                    "env-file",
                    ".env",
                    "QUEUE_CONNECTION=sync runs jobs inside requests",
                    "Use redis or database with workers.",
                )
            )
        cache = env.get("CACHE_STORE") or env.get("CACHE_DRIVER")
        if production and cache in ("file", "array", "database", None):
            f.append(
                Finding(
                    "low",
                    "env-file",
                    ".env",
                    f"cache store is {cache or 'default (database in Laravel 11+)'}",
                    "Use redis (or memcached) for cache in production; it also enables atomic locks.",
                )
            )
        sess = env.get("SESSION_DRIVER")
        if production and sess in ("file", "database", None):
            f.append(
                Finding(
                    "info",
                    "env-file",
                    ".env",
                    f"session driver is {sess or 'default'}",
                    "redis is faster and works across several web servers.",
                )
            )

    composer = read(os.path.join(root, "composer.json"))
    if composer:
        try:
            cj = json.loads(composer)
        except json.JSONDecodeError:
            cj = {}
        req = cj.get("require", {}) or {}
        for pkg in DEV_PACKAGES:
            if pkg in req:
                f.append(
                    Finding(
                        "medium",
                        "dev-packages",
                        "composer.json",
                        f"{pkg} is in require (installed in production)",
                        f"composer remove {pkg} && composer require --dev {pkg}",
                    )
                )
        cfg = cj.get("config", {}) or {}
        if not cfg.get("optimize-autoloader") and not cfg.get("classmap-authoritative"):
            f.append(
                Finding(
                    "low",
                    "autoloader",
                    "composer.json",
                    "optimize-autoloader is not set",
                    "Set config.optimize-autoloader=true, or deploy with "
                    "composer install --no-dev --optimize-autoloader.",
                )
            )

    if deployed:
        cache_dir = os.path.join(root, "bootstrap", "cache")
        cached = set(os.listdir(cache_dir)) if os.path.isdir(cache_dir) else set()
        hint = "Run php artisan optimize on deploy (Laravel 11+: config, events, routes, views; older: config, routes)."
        if "config.php" not in cached:
            f.append(
                Finding(
                    "medium",
                    "caches",
                    "bootstrap/cache/config.php",
                    "config cache missing: config:cache has not run",
                    hint,
                )
            )
        if not any(n.startswith("routes") and n.endswith(".php") for n in cached):
            f.append(
                Finding(
                    "medium",
                    "caches",
                    "bootstrap/cache/routes-v7.php",
                    "route cache missing: route:cache has not run",
                    hint,
                )
            )
        if "events.php" not in cached:
            f.append(
                Finding(
                    "low",
                    "caches",
                    "bootstrap/cache/events.php",
                    "event cache missing: event:cache has not run",
                    hint,
                )
            )
        views = os.path.join(root, "storage", "framework", "views")
        if os.path.isdir(views) and not any(n.endswith(".php") for n in os.listdir(views)):
            f.append(
                Finding(
                    "low",
                    "caches",
                    "storage/framework/views",
                    "no compiled views: view:cache has not run",
                    "Run php artisan view:cache on deploy.",
                )
            )

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP)
        else:
            dirnames[:] = sorted(d for d in dirnames if d not in ("vendor", "node_modules"))
        for fn in sorted(filenames):
            if not fn.endswith(".php"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root)
            text = strip_comments(read(path))
            for m in re.finditer(r"(?<![\w>:$])env\(\s*['\"](\w+)['\"]", text):
                line = text.count("\n", 0, m.start()) + 1
                f.append(
                    Finding(
                        "high",
                        "env-outside-config",
                        f"{rel}:{line}",
                        f"env('{m.group(1)}') outside config/: returns null after config:cache",
                        f"Add it to a config file ('x' => env('{m.group(1)}')) and read config('file.x').",
                    )
                )
            if not rel.startswith("app" + os.sep):
                continue
            for m in re.finditer(r"\b[A-Z]\w*::all\(\)", text):
                line = text.count("\n", 0, m.start()) + 1
                f.append(
                    Finding(
                        "low",
                        "query-patterns",
                        f"{rel}:{line}",
                        f"{m.group(0)} loads the whole table",
                        "Paginate, select columns, filter with where(), or chunkById() for batch work.",
                    )
                )
            for m in re.finditer(r"->get\(\)\s*->\s*(count|isEmpty|isNotEmpty|first)\(\)", text):
                line = text.count("\n", 0, m.start()) + 1
                better = {
                    "count": "->count()",
                    "isEmpty": "->doesntExist()",
                    "isNotEmpty": "->exists()",
                    "first": "->first()",
                }
                f.append(
                    Finding(
                        "low",
                        "query-patterns",
                        f"{rel}:{line}",
                        f"->get()->{m.group(1)}() fetches every row first",
                        f"Use {better[m.group(1)]} on the query builder.",
                    )
                )
    return f, production


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit a Laravel project and PHP/OPcache settings for production performance (read-only).",
        epilog="Example: perf_audit.py /var/www/app/current --deployed --php-ini <(php -i)",
    )
    ap.add_argument("root", nargs="?", default=".", help="Laravel project root (default .)")
    ap.add_argument("--env", help="env file to read (default ROOT/.env)")
    ap.add_argument("--php-ini", help="php.ini, conf.d snippet or saved `php -i` output")
    ap.add_argument("--production", action="store_true", help="treat as production even without APP_ENV")
    ap.add_argument("--deployed", action="store_true", help="ROOT is a deployed release: check artisan caches")
    ap.add_argument("--fail-on", choices=SEVERITIES, default="medium", help="exit 1 at or above (default medium)")
    ap.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args(argv)
    if not os.path.isdir(args.root):
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2
    if args.php_ini and not os.path.exists(args.php_ini):
        print(f"error: {args.php_ini} not found", file=sys.stderr)
        return 2
    findings, production = check_project(args.root, args.env, args.deployed)
    production = production or args.production
    if args.php_ini:
        findings += check_php(parse_php_ini(read(args.php_ini)), production)
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda x: (-rank[x.severity], x.check, x.where))
    counts = {s: sum(1 for x in findings if x.severity == s) for s in reversed(SEVERITIES)}
    if args.json:
        print(
            json.dumps(
                {"production": production, "counts": counts, "findings": [asdict(x) for x in findings]},
                indent=2,
            )
        )
    else:
        print(
            f"performance audit ({'production' if production else 'non-production'}): "
            + ", ".join(f"{n} {s}" for s, n in counts.items())
        )
        for x in findings:
            print(f"{x.severity.upper():6} {x.where}  [{x.check}] {x.title}\n       fix: {x.fix}")
    return 1 if any(rank[x.severity] >= rank[args.fail_on] for x in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
