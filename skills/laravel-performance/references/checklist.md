# Laravel production performance checklist

## Framework caches (run on every deploy, after composer install)

| Command | Caches | Notes |
| --- | --- | --- |
| `php artisan optimize` | Laravel 11+: config, events, routes, views. Laravel 9/10: config, routes | One command for deploys |
| `php artisan config:cache` | `bootstrap/cache/config.php` | `env()` returns null outside config files afterwards |
| `php artisan route:cache` | `bootstrap/cache/routes-v7.php` | Old Laravel versions fail on closure routes; current ones serialize them. Run it in CI to catch errors |
| `php artisan event:cache` | `bootstrap/cache/events.php` | Skips listener discovery |
| `php artisan view:cache` | `storage/framework/views` | Precompiles Blade |
| `php artisan icons:cache` / `filament:cache-components` | package caches | Only if those packages are installed |
| `php artisan optimize:clear` | clears all of the above | |

## Composer

```bash
composer install --no-dev --optimize-autoloader --no-interaction --prefer-dist
# optional, if nothing generates classes at runtime:
composer dump-autoload --classmap-authoritative --no-dev
```

`"config": {"optimize-autoloader": true}` makes it the default.

## OPcache (FPM)

```ini
; /etc/php/8.3/fpm/conf.d/99-opcache.ini
opcache.enable=1
opcache.memory_consumption=256
opcache.interned_strings_buffer=32
opcache.max_accelerated_files=40000
opcache.validate_timestamps=0        ; reload php-fpm on every deploy
opcache.save_comments=1              ; required by attributes/annotations
realpath_cache_size=8M
realpath_cache_ttl=600
```

Check usage from FPM, not the CLI (they have separate OPcache instances): call
`opcache_get_status(false)` from an admin-only route, or use a tool such as `opcache-gui` behind auth.
Signs it is too small: `cache_full: true`, many `oom_restarts`, hit rate < 99%.

Count files to size `max_accelerated_files`: `find /var/www/app/current -name '*.php' | wc -l`.

Preloading (`opcache.preload`) gives small gains and complicates deploys; skip unless benchmarked.

## PHP-FPM pool

```
pm = dynamic          ; or static on dedicated servers
pm.max_children = (RAM for PHP) / (average worker RSS)
pm.start_servers = 25% of max_children
pm.min_spare_servers = 25%
pm.max_spare_servers = 75%
pm.max_requests = 500 ; recycle workers, limits leaks
```

Measure worker RSS: `ps -o rss= -C php-fpm8.3 | awk '{s+=$1; n++} END {print s/n/1024 " MB avg over " n}'`.
Example: 4 GB server, 1 GB for MySQL/Redis/OS, 60 MB per worker: (3072 / 60) ≈ 50.
Watch for `server reached pm.max_children` in `/var/log/php8.3-fpm.log`.

Enable the slow log when hunting slow requests:

```
request_slowlog_timeout = 3s
slowlog = /var/log/php8.3-fpm-slow.log
```

## Drivers

| Concern | Production choice |
| --- | --- |
| Cache | `CACHE_STORE=redis` (Laravel 11+; `CACHE_DRIVER` before) |
| Session | `SESSION_DRIVER=redis` (or `database` on one server) |
| Queue | `QUEUE_CONNECTION=redis` + Horizon, or `database` + `queue:work` |
| Redis client | `REDIS_CLIENT=phpredis` (C extension) is faster than `predis` |
| Logs | `LOG_LEVEL=warning`, `LOG_CHANNEL=daily` or stderr to journald |

## Application code

- Paginate (`->paginate()`, `->cursorPaginate()` for large tables), never `Model::all()` on
  user-facing pages.
- `->count()`, `->exists()`, `->doesntExist()` on the builder, not on collections.
- Select only needed columns for big lists: `->select(['id', 'title'])`.
- `Cache::remember('key', now()->addMinutes(10), fn () => ...)`, `Cache::flexible()` (Laravel 11.23+)
  for stale-while-revalidate.
- Heavy work (emails, PDFs, API calls) in queued jobs.
- Indexes for every `where`/`orderBy` on large tables; check with `EXPLAIN`.
- Avoid `$appends` and accessors that query the database.

## HTTP layer

- Nginx: `gzip on` (or brotli), long `expires`/`Cache-Control: immutable` on hashed Vite assets
  in `/build/`, `fastcgi_buffers` sized for your responses.
- HTTP/2 on TLS; keep-alive to the browser.
- A CDN for static assets if users are far from the server.

## Monitoring

- Laravel Pulse (first-party) for slow requests, queries, jobs and cache hit rates.
- Telescope in staging; avoid in production or gate and prune it (`telescope:prune`).
