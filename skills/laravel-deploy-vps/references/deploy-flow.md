# Zero-downtime deploy flow

## Directory layout

```
/var/www/shop/
  current -> releases/20261125093012      (Nginx root: current/public)
  releases/
    20261124170501/
    20261125093012/
      .env -> ../../shared/.env
      storage -> ../../shared/storage
  shared/
    .env                                    (640, owner deploy, group www-data)
    storage/                                (2775, group www-data)
```

## Order of steps (and why)

1. **Clone into a new directory** - the live release is never modified.
2. **Link shared `.env` and `storage`** - uploads, logs, sessions and cache survive releases.
3. **`composer install --no-dev --optimize-autoloader`** - no dev packages in production.
4. **Build assets** (`npm ci && npm run build`) - or build in CI and ship `public/build`.
5. **Migrate** (`php artisan migrate --force`) - runs while the old release serves traffic, so
   migrations must work with the old code (expand/contract). With several servers, run it on one
   (`--isolated` needs a cache store that supports locks).
6. **`php artisan optimize`** (+ `view:cache`) - config, routes, events and views cached for
   the new release before it goes live.
7. **Atomic switch** - `ln -sfn` to a temp link then `mv -T` (rename is atomic on the same filesystem).
8. **Reload PHP-FPM** - with `opcache.validate_timestamps=0` this is what makes new code run;
   `reload` finishes in-flight requests gracefully.
9. **Restart queue workers** - `queue:restart` / `horizon:terminate` let workers finish the
   current job, then Supervisor starts them on the new release.
10. **Health check** - fail loudly so the operator can run `rollback.sh`.
11. **Clean up** - keep the last N releases for rollback.

## Permissions

- Code is owned by the deploy user and read-only for PHP-FPM.
- Only `shared/storage` and `bootstrap/cache` need to be writable by the PHP-FPM user/group.
- Setgid (`2775`) on `shared/storage` keeps new files in the `www-data` group. If PHP-FPM writes
  files the deploy user cannot change, set `umask 0002` for both or run FPM's pool as the deploy
  user (`user = deploy`, `group = www-data` in `/etc/php/8.3/fpm/pool.d/www.conf`).
- `.env`: `chmod 640`, never world readable.

## Maintenance mode

Not needed for normal deploys. For risky migrations:
`php artisan down --render="errors::503" --secret="<random>"` on the current release, deploy,
`php artisan up`. The secret URL lets you check the site while it is down.

## Deploying from CI (GitHub Actions)

```yaml
deploy:
  needs: test
  runs-on: ubuntu-latest
  if: github.ref == 'refs/heads/main'
  environment: production
  steps:
    - name: Deploy over SSH
      env:
        SSH_KEY: ${{ secrets.DEPLOY_SSH_KEY }}
        HOST: ${{ vars.DEPLOY_HOST }}
      run: |
        install -m 600 /dev/null ~/.ssh_key && printf '%s\n' "$SSH_KEY" > ~/.ssh_key
        ssh -i ~/.ssh_key -o StrictHostKeyChecking=accept-new deploy@"$HOST" "bash ~/deploy.sh $GITHUB_REF_NAME"
```

Pin the host key in `known_hosts` instead of `accept-new` when you can. `deploy.sh` takes a
branch or tag name (`git clone --branch`); to deploy an exact commit SHA, change the clone step
to a full clone followed by `git checkout "$REF"`.

## Scheduler and queues

- One cron line per server runs `schedule:run` every minute. With several servers, use
  `->onOneServer()` on tasks (needs a shared cache store).
- Long tasks: `->withoutOverlapping()` and `->runInBackground()`.
- `php artisan schedule:work` is for local development, not for cron.

## Health endpoint

Laravel 11+ registers `/up` in `bootstrap/app.php` (`health: '/up'`). For older apps add:

```php
Route::get('/up', fn () => response('ok'));
```

and keep it outside auth and maintenance-mode exceptions as needed.
