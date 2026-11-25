# Laravel Octane notes

Octane keeps the application booted in memory between requests (servers: FrankenPHP,
Swoole/OpenSwoole, RoadRunner). It removes per-request boot cost, typically the largest
part of a fast endpoint's time. It also changes the rules for your code.

## Is the app ready?

- [ ] No state in static properties or singletons that depends on the request or user
      (e.g. a service storing `auth()->user()` in its constructor).
- [ ] Services that need the request receive it per call, or are bound with `scoped()`
      instead of `singleton()`.
- [ ] No `config()` / container mutation at runtime that should not persist.
- [ ] Packages are Octane-compatible (check each package's docs: Livewire, Filament, Inertia are).
- [ ] Memory is stable over thousands of requests (run a load test, watch RSS).
- [ ] File uploads and long responses tested under the chosen server.

## Install

```bash
composer require laravel/octane
php artisan octane:install            # choose frankenphp, swoole or roadrunner
php artisan octane:start --workers=4 --max-requests=500
```

`--max-requests` recycles workers to contain leaks. Reload after deploys:
`php artisan octane:reload`.

## Supervisor

```ini
[program:octane]
command=php /var/www/app/current/artisan octane:start --server=frankenphp --host=127.0.0.1 --port=8000 --workers=4 --max-requests=500
user=deploy
autostart=true
autorestart=true
stopwaitsecs=60
redirect_stderr=true
stdout_logfile=/var/www/app/shared/storage/logs/octane.log
```

Nginx proxies to `127.0.0.1:8000` (`proxy_pass`, with `Host`, `X-Forwarded-For`,
`X-Forwarded-Proto` headers and `trustProxies` configured in Laravel).

## Pitfalls

| Symptom | Cause |
| --- | --- |
| User A sees user B's data | request/user cached in a singleton or static property |
| Memory grows until restart | arrays appended to static properties, listeners registered per request |
| Config change not visible | workers keep old config: `octane:reload` |
| Old code after deploy | deploy did not run `octane:reload` |
| `dd()` / `exit()` kill the worker | do not use them in Octane apps |

## When not to use Octane

- Most time is spent in the database or external APIs (Octane does not speed those up).
- The team cannot audit packages and code for state leakage.
- Shared hosting or no process manager.
