# Known-good queue configuration

## The timeout chain

```
job $timeout  <=  worker --timeout / Horizon 'timeout'  <  retry_after (- a few seconds)  <=  stopwaitsecs
```

- `retry_after` (config/queue.php): how long a reserved job may run before the queue hands
  it to another worker. If a job is still running at that point it runs twice.
- `--timeout` / Horizon `timeout`: the worker kills a job after this many seconds (needs
  the `pcntl` extension). Must be below `retry_after`.
- `stopwaitsecs` (Supervisor): how long Supervisor waits for a graceful stop before SIGKILL.
  Must be longer than the longest job, or deploys kill jobs mid-way.

## config/queue.php

```php
'redis' => [
    'driver' => 'redis',
    'connection' => env('REDIS_QUEUE_CONNECTION', 'default'),
    'queue' => env('REDIS_QUEUE', 'default'),
    'retry_after' => 90,
    'block_for' => null,
    'after_commit' => true,
],

// separate connection for slow jobs (reports, exports)
'redis-long' => [
    'driver' => 'redis',
    'connection' => 'default',
    'queue' => 'long',
    'retry_after' => 1900,
    'block_for' => null,
    'after_commit' => true,
],
```

`after_commit => true` (or `->afterCommit()` per dispatch) makes jobs dispatched inside a DB
transaction wait for the commit, so they do not load rows that do not exist yet.

## Supervisor: queue:work

```ini
[program:laravel-worker]
process_name=%(program_name)s_%(process_num)02d
command=php /var/www/app/current/artisan queue:work redis --queue=high,default --sleep=3 --tries=3 --timeout=60 --max-time=3600
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
user=deploy
numprocs=2
redirect_stderr=true
stdout_logfile=/var/www/app/shared/storage/logs/worker.log
stopwaitsecs=3600
```

Apply: `sudo supervisorctl reread && sudo supervisorctl update && sudo supervisorctl start "laravel-worker:*"`.

## Supervisor: Horizon

```ini
[program:horizon]
process_name=%(program_name)s
command=php /var/www/app/current/artisan horizon
autostart=true
autorestart=true
user=deploy
redirect_stderr=true
stdout_logfile=/var/www/app/shared/storage/logs/horizon.log
stopwaitsecs=3600
```

## config/horizon.php

```php
'defaults' => [
    'supervisor-default' => [
        'connection' => 'redis',
        'queue' => ['high', 'default'],
        'balance' => 'auto',
        'autoScalingStrategy' => 'time',
        'maxProcesses' => 1,
        'maxTime' => 3600,
        'maxJobs' => 0,
        'memory' => 128,
        'tries' => 3,
        'timeout' => 60,
        'nice' => 0,
    ],
    'supervisor-long' => [
        'connection' => 'redis-long',
        'queue' => ['long'],
        'maxProcesses' => 1,
        'tries' => 1,
        'timeout' => 1800,
    ],
],
'environments' => [
    'production' => [
        'supervisor-default' => ['maxProcesses' => 10, 'balanceMaxShift' => 1, 'balanceCooldown' => 3],
        'supervisor-long' => ['maxProcesses' => 2],
    ],
],
'trim' => [
    'recent' => 60,
    'pending' => 60,
    'completed' => 60,
    'recent_failed' => 10080,
    'failed' => 10080,
    'monitored' => 10080,
],
```

Gate the dashboard (`app/Providers/HorizonServiceProvider.php`):

```php
protected function gate(): void
{
    Gate::define('viewHorizon', fn ($user = null) => in_array(optional($user)->email, [
        'ops@example.com',
    ], true));
}
```

Schedule metrics snapshots: `Schedule::command('horizon:snapshot')->everyFiveMinutes();`

## Job class defaults

```php
class SyncInvoice implements ShouldQueue
{
    use Queueable;

    public int $tries = 5;
    public int $timeout = 30;
    public array $backoff = [10, 60, 300];
    public bool $deleteWhenMissingModels = true;

    public function middleware(): array
    {
        return [new \Illuminate\Queue\Middleware\ThrottlesExceptions(10, 5 * 60)];
    }

    public function failed(?\Throwable $e): void
    {
        // notify, mark the record as failed, release locks
    }
}
```

Use `ShouldBeUnique` for jobs that must not overlap, `WithoutOverlapping` middleware for
per-model locks, and `retryUntil()` for time-boxed retries.

## Checklist

- [ ] Production `QUEUE_CONNECTION` is redis/database/sqs, never `sync`
- [ ] Timeout chain holds for every connection, supervisor and job
- [ ] Workers recycle: `--max-time=3600` or Horizon `maxTime`; `autorestart=true`
- [ ] Workers run as the deploy user, not root
- [ ] Deploy runs `queue:restart` or `horizon:terminate`
- [ ] `failed_jobs` table exists (`php artisan make:queue-failed-table` on older apps) and is monitored
- [ ] Horizon: `viewHorizon` gate, `trim` set, `horizon:snapshot` scheduled
- [ ] Redis `maxmemory-policy noeviction` for queue Redis (evicting keys loses jobs)
