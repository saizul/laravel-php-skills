---
name: laravel-performance
description: Make a Laravel app fast in production - audits config/route/event/view caching, env() calls outside config/ that break config:cache, APP_DEBUG and LOG_LEVEL, cache/session/queue drivers, debug packages installed in production, Composer autoloader optimisation, OPcache, realpath cache, JIT and Xdebug settings (from php.ini or php -i), and Model::all() / ->get()->count() patterns; includes checklists for PHP-FPM sizing, Redis, HTTP caching and Laravel Octane. Use when a Laravel site is slow, TTFB is high, the user prepares a production deploy, asks about php artisan optimize, config:cache, OPcache tuning, Octane, FrankenPHP, Swoole or RoadRunner, or wants a performance review.
license: MIT
compatibility: Python 3.8+. Reads project files and php.ini / php -i output as text. Laravel 9-12, PHP 8.1+.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Laravel performance

Fix the cheap, high-impact things first (caches, OPcache, drivers, debug off), then measure
before touching code.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "The site is slow", "high TTFB", "optimise Laravel for production", "prepare for a traffic spike"
- Questions about `php artisan optimize`, `config:cache`, OPcache, PHP-FPM workers, Octane
- After moving to a new server or PHP version

## When not to use

- A specific page with too many queries: use `eloquent-n-plus-one`
- Slow or failing background jobs: use `laravel-queues-horizon`
- Front-end performance (bundle size, images, Core Web Vitals): different tools
- Deploy mechanics (symlinks, Nginx, Supervisor): use `laravel-deploy-vps`

## Workflow

1. **Gather inputs.** Project root (local checkout or the deployed release, e.g.
   `/var/www/app/current`). PHP settings of the **FPM** SAPI, not the CLI:
   `php-fpm8.3 -i > php-i.txt` on the server, or the files in `/etc/php/8.3/fpm/` (`php.ini`,
   `conf.d/*opcache*.ini`). Ask whether the target is production.
2. **Run the audit (read-only).**
   ```bash
   python3 scripts/perf_audit.py /path/to/project
   python3 scripts/perf_audit.py /var/www/app/current --deployed --php-ini php-i.txt
   python3 scripts/perf_audit.py . --production --php-ini /etc/php/8.3/fpm/conf.d/10-opcache.ini --json
   ```
   `--deployed` also checks that `bootstrap/cache` and compiled views exist. Only
   `APP_ENV`, `APP_DEBUG`, `LOG_LEVEL`, cache/session/queue driver keys are read from `.env`.
   Exit 1 = findings at or above `--fail-on` (default `medium`).
3. **Fix in this order** (biggest win per minute; details in [references/checklist.md](references/checklist.md)):
   1. `APP_DEBUG=false`, Xdebug off, OPcache on and sized.
   2. `env()` outside `config/`: move into config files **before** enabling `config:cache`,
      otherwise those values become `null` in production.
   3. Deploy runs `composer install --no-dev --optimize-autoloader` and `php artisan optimize`
      (and `php artisan view:cache` / `event:cache` on Laravel 9/10).
   4. Cache, session and queue on Redis; workers for queued jobs.
   5. PHP-FPM `pm.max_children` sized to RAM (formula in the checklist).
   6. Code: pagination instead of `::all()`, `count()` instead of `get()->count()`, cache
      expensive queries (`Cache::remember`), eager loading.
4. **Measure** before and after, with the same URL and warm caches:
   ```bash
   curl -s -o /dev/null -w 'ttfb=%{time_starttransfer}s total=%{time_total}s\n' https://example.com/
   ```
   For load, `ab -n 500 -c 20` or `hey`/`wrk` against **staging**, never production without approval.
   Use Telescope/Debugbar/Pulse or `DB::listen` locally to see where time goes.
5. **Octane** only after the basics, and only if the app is safe for a long-running process
   (no static/singleton state leaks between requests). Read
   [references/octane.md](references/octane.md) and present the risks before proposing it.
6. **Report** findings with the exact change and the command or config line. Changes to server
   config (php.ini, FPM pools) and service reloads need the user's confirmation.

## Output

```
Performance audit (production, PHP 8.3 FPM)
HIGH   app/Services/Feature.php:9  env('FEATURE_X') outside config -> null after config:cache
HIGH   OPcache: Xdebug loaded in FPM (xdebug.mode=debug)
MEDIUM bootstrap/cache: config and routes not cached -> add `php artisan optimize` to deploy
MEDIUM max_accelerated_files=10000 (vendor has ~14k files) -> 40000
Plan: 1) move 3 env() calls to config/features.php  2) disable Xdebug  3) deploy script: optimize
Measured: TTFB / 410 ms -> 95 ms after steps 1-3
```

## Notes

- `php artisan optimize:clear` removes all caches; after `config:cache`, edits to `.env` need
  another `config:cache` to take effect.
- With `opcache.validate_timestamps=0`, PHP-FPM must be reloaded on every deploy or old code keeps running.
