# Deploy troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Old code still served after deploy | OPcache with `validate_timestamps=0`, FPM not reloaded; or Nginx uses `$document_root` | Reload FPM in deploy; use `$realpath_root` in `SCRIPT_FILENAME` and `DOCUMENT_ROOT` |
| 502 Bad Gateway | FPM socket path wrong or FPM down | `ls /run/php/`, `systemctl status php8.3-fpm`, match `fastcgi_pass` |
| 500 with empty page, nothing in laravel.log | storage not writable | `namei -l /var/www/shop/shared/storage/logs`; fix group/permissions |
| `No application encryption key has been specified` | `APP_KEY` missing in shared/.env | `php artisan key:generate --show` and put it in `.env`, then `php artisan config:cache` |
| `.env` changes ignored | config is cached | `php artisan config:cache` (deploy does it) |
| `env()` returns null in production | `env()` used outside config/ | move to config files (see `laravel-performance`) |
| `Permission denied (publickey)` on git clone | deploy key missing | add `~deploy/.ssh/id_ed25519.pub` as a read-only deploy key |
| `sudo: a password is required` | sudoers rule missing or path differs | `command -v systemctl`, reinstall `sudoers-<app>` |
| Workers run old code | no `queue:restart` / `horizon:terminate`, or Supervisor `autorestart=false` | both are in deploy.sh / supervisor conf |
| Scheduler does nothing | cron file not installed, wrong user, or missing newline at end of file | `sudo cat /etc/cron.d/<app>`, `grep CRON /var/log/syslog` |
| `npm: command not found` | Node not installed on server | install Node LTS, or build assets in CI and pass `--no-assets` |
| Disk fills with releases | `KEEP` too high or cleanup failed | check `releases/`, lower `--keep` |
| Mixed content / wrong URLs behind a proxy | trusted proxies | `->withMiddleware(fn ($m) => $m->trustProxies(at: '*'))` (Laravel 11+) when behind a load balancer you control |
