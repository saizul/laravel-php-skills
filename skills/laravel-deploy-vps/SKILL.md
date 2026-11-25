---
name: laravel-deploy-vps
description: Deploy a Laravel app to a single Ubuntu/Debian VPS with zero downtime - generates a releases/shared/current-symlink deploy script with composer --no-dev, Vite build, migrations, php artisan optimize, atomic symlink switch, PHP-FPM reload for OPcache, queue:restart or horizon:terminate, health check and release cleanup, plus a rollback script, an Nginx server block using $realpath_root, Supervisor config for queue workers or Horizon, the scheduler cron entry and a sudoers rule. Use when the user wants to deploy Laravel to a VPS (DigitalOcean, Hetzner, Contabo, Linode, EC2), replace git pull deploys or FTP, set up Nginx, PHP-FPM, Supervisor or the scheduler for Laravel, or fix downtime and stale code after deploys.
license: MIT
compatibility: Python 3.8+ to generate files. Target server - Ubuntu 22.04/24.04 or Debian 12 with Nginx, PHP-FPM 8.2+, Composer, Git, Supervisor; Laravel 10-12.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Laravel deploy to a VPS

Generate reviewed, boring deploy files: each deploy builds a fresh release next to the live
one and switches a symlink, so users never hit a half-updated app and rollback takes a second.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- First deploy of a Laravel app to a VPS, or replacing `git pull && php artisan migrate` on the live directory
- "Users get 500s during deploys", "old code still runs after deploy", "set up Supervisor/cron for Laravel"
- Moving from shared hosting or Forge/Ploi to a self-managed server

## When not to use

- Platforms that deploy for you (Laravel Cloud, Forge, Vapor, Ploi, Envoyer): use their pipeline
- Containers / Kubernetes: build an image instead
- Multi-server deploys behind a load balancer: the layout works, but you need an orchestrator
  (Deployer, Envoy, CI with several hosts) and a shared session/cache store
- Server hardening (SSH, firewall, TLS policy): do that first with a server audit

## Workflow

1. **Collect facts** (ask, do not guess): domain, git URL and branch, PHP version on the
   server (`php -v`), deploy user, queue setup (none / `queue:work` / Horizon), whether the app
   builds assets with Vite, Laravel version (`/up` health route exists in Laravel 11+;
   older apps need `HEALTH_URL` pointing at a real page).
2. **Generate the files locally** (writes only to `--out`; refuses to overwrite without `--force`):
   ```bash
   python3 scripts/gen_deploy.py --app shop --domain shop.example.com \
     --repo git@github.com:acme/shop.git --branch main --php 8.3 --queue horizon --out deploy-out
   python3 scripts/gen_deploy.py ... --queue worker --workers 3 --no-assets --print   # preview
   ```
   Output: `deploy.sh`, `rollback.sh`, `nginx-<app>.conf`, `supervisor-<app>.conf`,
   `cron-<app>`, `sudoers-<app>`, `INSTALL.md`.
3. **Review the files with the user.** Point out: migrations run *before* the switch while the
   old release still serves traffic, so schema changes must be backward compatible (see
   `laravel-migrations-safety`); `shared/.env` and `shared/storage` survive releases; the deploy
   user reloads PHP-FPM through a single sudoers rule.
4. **One-time server setup.** Walk through `INSTALL.md` step by step. Every command that
   installs packages, creates users, edits `/etc` or reloads services must be shown to the user
   and confirmed before running it. Validate before reloads: `sudo nginx -t`,
   `sudo visudo -cf sudoers-<app>`, `sudo supervisorctl reread`.
5. **First deploy.** Create `shared/.env` with production values (`APP_ENV=production`,
   `APP_DEBUG=false`, `APP_KEY`), then run `bash deploy.sh` as the deploy user and watch the
   output. On failure before the switch, the live site is untouched: fix and re-run.
6. **Verify**:
   ```bash
   curl -sI https://shop.example.com | head -n 5
   readlink -f /var/www/shop/current
   sudo supervisorctl status
   tail -n 50 /var/www/shop/shared/storage/logs/laravel.log
   ```
   The scheduler: `php artisan schedule:list`; after a minute, check its log output.
7. **Rollback** if needed: `bash rollback.sh` switches to the previous release. It does not
   roll back migrations; that is why migrations must be backward compatible.

Reference material: [references/deploy-flow.md](references/deploy-flow.md) (directory layout,
permissions, zero-downtime rules, CI deploys) and
[references/troubleshooting.md](references/troubleshooting.md).

## Output

```
Generated deploy-out/ (7 files) for shop.example.com, PHP 8.3, Horizon
Server steps (each confirmed): packages, deploy user, /var/www/shop, nginx site, certbot,
supervisor (horizon), cron, sudoers
First deploy: release 20261125093012 live, /up 200, horizon running
Rollback: bash ~/rollback.sh
```

## Notes

- `fastcgi_param SCRIPT_FILENAME $realpath_root...` matters: with `$document_root` PHP-FPM and
  OPcache can keep serving the old release through the symlink.
- The generated Nginx block listens on port 80; `certbot --nginx` adds the TLS server and redirect.
