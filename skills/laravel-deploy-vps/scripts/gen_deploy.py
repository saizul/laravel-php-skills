#!/usr/bin/env python3
"""Generate zero-downtime deploy files for a Laravel app on a single VPS. Writes local files only.

Generates (into --out, or prints to stdout with --print):
  deploy.sh              releases/ + shared/ + atomic `current` symlink deploy
  rollback.sh            point `current` back to the previous release
  nginx-<app>.conf       Nginx server block (uses $realpath_root for symlinked releases)
  supervisor-<app>.conf  queue:work workers or Horizon (omitted with --queue none)
  cron-<app>             /etc/cron.d entry for the scheduler
  sudoers-<app>          lets the deploy user reload PHP-FPM / Supervisor without a password
  INSTALL.md             where each file goes and the one-time server commands

Nothing is installed or executed: review the files, then copy them to the server.
Exit codes: 0 = written, 2 = invalid arguments or refusing to overwrite.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
REPO_RE = re.compile(r"^(?:git@[\w.-]+:[\w./-]+|https://[\w.-]+/[\w./-]+|ssh://[\w@.:/-]+)$")
BRANCH_RE = re.compile(r"^[\w][\w./-]{0,99}$")
PATH_RE = re.compile(r"^/[\w./-]+$")
PHP_RE = re.compile(r"^\d\.\d$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def deploy_sh(c: dict) -> str:
    queue_restart = {
        "worker": "php artisan queue:restart",
        "horizon": "php artisan horizon:terminate",
        "none": "true  # no queue workers configured",
    }[c["queue"]]
    assets = (
        "if [ -f package-lock.json ]; then\n  npm ci --no-audit --no-fund\n  npm run build\n  rm -rf node_modules\nfi\n"
        if c["assets"]
        else "# front-end build disabled (--no-assets)\n"
    )
    migrate = (
        "php artisan migrate --force\n" if c["migrate"] else "# migrations disabled (--no-migrate): run them yourself\n"
    )
    return f"""#!/usr/bin/env bash
# Zero-downtime deploy for {c["app"]} ({c["domain"]}).
# Layout: {c["base"]}/releases/<timestamp>, {c["base"]}/shared/{{.env,storage}}, {c["base"]}/current -> release
# Run as {c["user"]} on the server: bash deploy.sh [git-ref]
set -euo pipefail

BASE="{c["base"]}"
REPO="{c["repo"]}"
REF="${{1:-{c["branch"]}}}"
KEEP={c["keep"]}
PHP_FPM="php{c["php"]}-fpm"
HEALTH_URL="${{HEALTH_URL:-https://{c["domain"]}/up}}"

RELEASE="$(date -u +%Y%m%d%H%M%S)"
RELEASE_DIR="$BASE/releases/$RELEASE"

log() {{ printf '\\n==> %s\\n' "$*"; }}

[ -f "$BASE/shared/.env" ] || {{ echo "missing $BASE/shared/.env (see INSTALL.md)" >&2; exit 1; }}
mkdir -p "$BASE/releases" "$BASE/shared/storage"

log "Cloning $REF into $RELEASE_DIR"
git clone --depth 1 --branch "$REF" "$REPO" "$RELEASE_DIR"
cd "$RELEASE_DIR"

log "Linking shared .env and storage"
rm -rf storage
ln -s "$BASE/shared/storage" storage
ln -s "$BASE/shared/.env" .env
mkdir -p storage/app/public storage/framework/{{cache/data,sessions,views}} storage/logs bootstrap/cache

log "Installing PHP dependencies"
composer install --no-dev --optimize-autoloader --no-interaction --prefer-dist --no-progress

log "Building front-end assets"
{assets}
log "Running migrations"
{migrate}
log "Caching config, routes, events and views"
php artisan optimize
php artisan view:cache
php artisan storage:link --force >/dev/null 2>&1 || true

log "Switching current -> $RELEASE (atomic)"
ln -sfn "$RELEASE_DIR" "$BASE/current.tmp"
mv -Tf "$BASE/current.tmp" "$BASE/current"

log "Reloading PHP-FPM (clears OPcache) and restarting queue workers"
sudo /usr/bin/systemctl reload "$PHP_FPM"
cd "$BASE/current"
{queue_restart}

log "Health check $HEALTH_URL"
if ! curl -fsS --max-time 10 -o /dev/null "$HEALTH_URL"; then
  echo "health check failed: run rollback.sh to return to the previous release" >&2
  exit 1
fi

log "Removing old releases (keeping $KEEP)"
find "$BASE/releases" -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' | sort | head -n -"$KEEP" | while read -r old; do
  [ "$old" = "$RELEASE" ] || rm -rf -- "$BASE/releases/$old"
done

log "Deployed $REF as $RELEASE"
"""


def rollback_sh(c: dict) -> str:
    queue_restart = {
        "worker": "php artisan queue:restart",
        "horizon": "php artisan horizon:terminate",
        "none": "true",
    }[c["queue"]]
    return f"""#!/usr/bin/env bash
# Point {c["base"]}/current at the previous release. Database migrations are NOT rolled back.
set -euo pipefail

BASE="{c["base"]}"
CURRENT="$(basename "$(readlink -f "$BASE/current")")"
PREVIOUS="$(find "$BASE/releases" -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' \\
  | sort | grep -B1 -x "$CURRENT" | head -n 1)"

if [ -z "$PREVIOUS" ] || [ "$PREVIOUS" = "$CURRENT" ]; then
  echo "no previous release before $CURRENT" >&2
  exit 1
fi

echo "Rolling back $CURRENT -> $PREVIOUS"
ln -sfn "$BASE/releases/$PREVIOUS" "$BASE/current.tmp"
mv -Tf "$BASE/current.tmp" "$BASE/current"
sudo /usr/bin/systemctl reload "php{c["php"]}-fpm"
cd "$BASE/current"
php artisan optimize
{queue_restart}
echo "Now serving $PREVIOUS"
"""


def nginx_conf(c: dict) -> str:
    return f"""# /etc/nginx/sites-available/{c["app"]}.conf
# HTTPS is added by certbot (--nginx) or by your own ssl_certificate lines.
server {{
    listen 80;
    listen [::]:80;
    server_name {c["domain"]};
    root {c["base"]}/current/public;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    index index.php;
    charset utf-8;
    client_max_body_size 20m;
    server_tokens off;

    location / {{
        try_files $uri $uri/ /index.php?$query_string;
    }}

    location = /favicon.ico {{ access_log off; log_not_found off; }}
    location = /robots.txt  {{ access_log off; log_not_found off; }}

    # Vite builds hashed file names: cache them for a year
    location /build/ {{
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
        try_files $uri =404;
    }}

    error_page 404 /index.php;

    location ~ ^/index\\.php(/|$) {{
        fastcgi_pass unix:/run/php/php{c["php"]}-fpm.sock;
        fastcgi_split_path_info ^(.+\\.php)(/.*)$;
        include fastcgi_params;
        # $realpath_root resolves the `current` symlink so OPcache sees the new release
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
        fastcgi_param DOCUMENT_ROOT $realpath_root;
        fastcgi_hide_header X-Powered-By;
        fastcgi_read_timeout 60s;
    }}

    # Only index.php is executable; deny dotfiles except .well-known (ACME)
    location ~ \\.php$ {{ return 404; }}
    location ~ /\\.(?!well-known).* {{ deny all; }}
}}
"""


def supervisor_conf(c: dict) -> str:
    log = f"{c['base']}/shared/storage/logs"
    if c["queue"] == "horizon":
        return f"""; /etc/supervisor/conf.d/{c["app"]}-horizon.conf
[program:{c["app"]}-horizon]
process_name=%(program_name)s
command=php {c["base"]}/current/artisan horizon
directory={c["base"]}/current
user={c["user"]}
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
redirect_stderr=true
stdout_logfile={log}/horizon.log
stopwaitsecs=3600
"""
    return f"""; /etc/supervisor/conf.d/{c["app"]}-worker.conf
; --timeout must stay below retry_after in config/queue.php (default 90)
[program:{c["app"]}-worker]
process_name=%(program_name)s_%(process_num)02d
command=php {c["base"]}/current/artisan queue:work --sleep=3 --tries=3 --timeout=60 --max-time=3600
directory={c["base"]}/current
user={c["user"]}
numprocs={c["workers"]}
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
redirect_stderr=true
stdout_logfile={log}/worker.log
stopwaitsecs=3600
"""


def cron(c: dict) -> str:
    return f"""# /etc/cron.d/{c["app"]} - Laravel scheduler, runs every minute.
# Tasks are defined in routes/console.php (Laravel 11+) or app/Console/Kernel.php (older).
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
* * * * * {c["user"]} cd {c["base"]}/current && php artisan schedule:run >> /dev/null 2>&1
"""


def sudoers(c: dict) -> str:
    lines = [
        f"# /etc/sudoers.d/{c['app']}",
        f"# install: sudo visudo -cf <file> && sudo install -m 0440 <file> /etc/sudoers.d/{c['app']}",
        f"{c['user']} ALL=(root) NOPASSWD: /usr/bin/systemctl reload php{c['php']}-fpm",
    ]
    if c["queue"] != "none":
        lines.append(f"{c['user']} ALL=(root) NOPASSWD: /usr/bin/supervisorctl status")
    return "\n".join(lines) + "\n"


def install_md(c: dict, files: list[str]) -> str:
    sup = (
        f"""
## Queue workers ({c["queue"]})

```bash
sudo cp supervisor-{c["app"]}.conf /etc/supervisor/conf.d/
sudo supervisorctl reread && sudo supervisorctl update
sudo supervisorctl status
```
"""
        if c["queue"] != "none"
        else ""
    )
    return f"""# Install {c["app"]} on the server

Generated files: {", ".join(files)}. Review every file before copying it.

## One-time setup (as root or with sudo)

```bash
sudo apt install nginx php{c["php"]}-fpm php{c["php"]}-{{cli,mbstring,xml,curl,zip,bcmath,intl,mysql,redis}} \\
     composer git unzip supervisor
sudo adduser --disabled-password --gecos "" {c["user"]}
sudo usermod -aG {c["web_group"]} {c["user"]}
sudo mkdir -p {c["base"]}/{{releases,shared/storage}}
sudo chown -R {c["user"]}:{c["web_group"]} {c["base"]}
sudo chmod -R 2775 {c["base"]}/shared/storage
```

Create `{c["base"]}/shared/.env` (copy `.env.example`, set `APP_ENV=production`, `APP_DEBUG=false`,
database and cache settings), then as {c["user"]}: `php artisan key:generate` inside the first
release, or set `APP_KEY` yourself. Keep it `chmod 640`.

The deploy user needs read access to the repository (deploy key):
`ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""` and add the public key to the repository.

## Nginx

```bash
sudo cp nginx-{c["app"]}.conf /etc/nginx/sites-available/{c["app"]}.conf
sudo ln -s /etc/nginx/sites-available/{c["app"]}.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d {c["domain"]}
```
{sup}
## Scheduler

```bash
sudo install -m 0644 cron-{c["app"]} /etc/cron.d/{c["app"]}
```

## Passwordless reloads for the deploy user

```bash
sudo visudo -cf sudoers-{c["app"]} && sudo install -m 0440 sudoers-{c["app"]} /etc/sudoers.d/{c["app"]}
```

## Deploy

```bash
scp deploy.sh rollback.sh {c["user"]}@{c["domain"]}:~/
ssh {c["user"]}@{c["domain"]} 'bash ~/deploy.sh {c["branch"]}'
```

PHP-FPM must run as a user in the `{c["web_group"]}` group with write access to `shared/storage`.
"""


def build(c: dict) -> dict[str, str]:
    files = {
        "deploy.sh": deploy_sh(c),
        "rollback.sh": rollback_sh(c),
        f"nginx-{c['app']}.conf": nginx_conf(c),
        f"cron-{c['app']}": cron(c),
        f"sudoers-{c['app']}": sudoers(c),
    }
    if c["queue"] != "none":
        files[f"supervisor-{c['app']}.conf"] = supervisor_conf(c)
    files["INSTALL.md"] = install_md(c, sorted(files))
    return files


def validate(args) -> list[str]:
    errors = []
    checks = [
        (NAME_RE, args.app, "--app must be lowercase letters, digits, - or _ (max 40)"),
        (DOMAIN_RE, args.domain, "--domain must be a hostname like example.com"),
        (REPO_RE, args.repo, "--repo must be git@host:org/repo.git, https://... or ssh://..."),
        (BRANCH_RE, args.branch, "--branch contains invalid characters"),
        (PHP_RE, args.php, "--php must look like 8.3"),
        (USER_RE, args.user, "--user must be a valid Unix user name"),
        (USER_RE, args.web_group, "--web-group must be a valid Unix group name"),
    ]
    for rx, value, msg in checks:
        if not rx.match(value or ""):
            errors.append(msg)
    if args.base and (not PATH_RE.match(args.base) or ".." in args.base):
        errors.append("--base must be an absolute path without '..'")
    if not 1 <= args.keep <= 50:
        errors.append("--keep must be between 1 and 50")
    if not 1 <= args.workers <= 64:
        errors.append("--workers must be between 1 and 64")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate zero-downtime deploy files for Laravel on a VPS (writes local files only).",
        epilog="Example: gen_deploy.py --app shop --domain shop.example.com "
        "--repo git@github.com:acme/shop.git --queue horizon --out deploy-out",
    )
    ap.add_argument("--app", required=True, help="short app name, used in file and program names")
    ap.add_argument("--domain", required=True, help="public hostname, e.g. shop.example.com")
    ap.add_argument("--repo", required=True, help="git URL the server can clone")
    ap.add_argument("--branch", default="main", help="default git ref to deploy (default main)")
    ap.add_argument("--base", help="deploy root on the server (default /var/www/<app>)")
    ap.add_argument("--php", default="8.3", help="PHP version for FPM socket/service (default 8.3)")
    ap.add_argument("--user", default="deploy", help="deploy user (default deploy)")
    ap.add_argument("--web-group", default="www-data", help="group PHP-FPM runs as (default www-data)")
    ap.add_argument("--queue", choices=["worker", "horizon", "none"], default="worker", help="queue process type")
    ap.add_argument("--workers", type=int, default=2, help="queue:work processes (default 2)")
    ap.add_argument("--keep", type=int, default=5, help="releases to keep (default 5)")
    ap.add_argument("--no-assets", dest="assets", action="store_false", help="skip npm ci && npm run build")
    ap.add_argument("--no-migrate", dest="migrate", action="store_false", help="do not run migrations on deploy")
    out = ap.add_mutually_exclusive_group(required=True)
    out.add_argument("--out", help="directory to write the files into")
    out.add_argument("--print", action="store_true", help="print all files to stdout instead")
    ap.add_argument("--force", action="store_true", help="overwrite existing files in --out")
    args = ap.parse_args(argv)
    args.base = args.base or f"/var/www/{args.app}"
    errors = validate(args)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 2
    c = {
        "app": args.app,
        "domain": args.domain,
        "repo": args.repo,
        "branch": args.branch,
        "base": args.base.rstrip("/"),
        "php": args.php,
        "user": args.user,
        "web_group": args.web_group,
        "queue": args.queue,
        "workers": args.workers,
        "keep": args.keep,
        "assets": args.assets,
        "migrate": args.migrate,
    }
    files = build(c)
    if args.print:
        for name, content in files.items():
            print(f"===== {name} =====\n{content}")
        return 0
    os.makedirs(args.out, exist_ok=True)
    existing = [n for n in files if os.path.exists(os.path.join(args.out, n))]
    if existing and not args.force:
        print(f"error: {', '.join(existing)} already exist in {args.out} (use --force)", file=sys.stderr)
        return 2
    for name, content in files.items():
        path = os.path.join(args.out, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(path, 0o755 if name.endswith(".sh") else 0o644)
    print(f"wrote {len(files)} files to {args.out}: {', '.join(files)}")
    print(f"next: review them, then follow {os.path.join(args.out, 'INSTALL.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
