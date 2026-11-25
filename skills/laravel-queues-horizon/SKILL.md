---
name: laravel-queues-horizon
description: Configure, check and debug Laravel queues and Horizon - verifies that worker and job timeouts stay below retry_after, Supervisor stopwaitsecs, autorestart, --tries and --max-time, Horizon tries/trim/viewHorizon gate, QUEUE_CONNECTION=sync in production and after_commit, and triages the failed_jobs table by job class and root cause (timeouts, missing models, deadlocks, external APIs, memory, stale payloads after deploys) with retry or forget commands. Use when jobs run twice, never run, time out, pile up or fail, when setting up queue workers, Supervisor or Horizon on a server, after a deploy breaks jobs, or when the user asks about failed jobs, queue:retry, retry_after, backoff or Horizon configuration.
license: MIT
compatibility: Python 3.8+. Reads config and Supervisor files as text; triage reads an export of the failed_jobs table. Laravel 9-12, Horizon 5.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Laravel queues and Horizon

Get queue workers configured so jobs run exactly once, survive deploys and fail loudly,
then turn a wall of failed jobs into a short list of causes.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- Setting up workers: Supervisor `queue:work`, Horizon, or reviewing existing config
- Symptoms: jobs run twice, `MaxAttemptsExceededException`, jobs stuck in `pending`, Redis memory growing
- "We have 3,000 failed jobs", "what is safe to retry?", jobs broke after a deploy

## When not to use

- Scheduling recurring tasks (that is the scheduler; see `laravel-deploy-vps` for the cron line)
- Slow job code itself (profile it like any PHP code, see `laravel-performance`)
- Laravel Vapor / SQS-only setups: SQS uses visibility timeouts; most Supervisor checks do not apply

## Workflow

1. **Collect the config.** From the project: `config/queue.php`, `config/horizon.php` (if
   `laravel/horizon` is in `composer.json`), `app/Jobs/`. From the server:
   `/etc/supervisor/conf.d/*.conf`. Ask which connection production uses (`QUEUE_CONNECTION`).
2. **Run the config check (read-only).**
   ```bash
   python3 scripts/queue_config_check.py /path/to/project
   python3 scripts/queue_config_check.py . --supervisor /etc/supervisor/conf.d/laravel-worker.conf --json
   ```
   Exit 1 = findings at or above `--fail-on` (default `medium`). The `--json` output also
   contains the parsed settings (retry_after per connection, supervisors, job timeouts).
3. **Fix the timeout chain first** (most "job ran twice" bugs):
   `job $timeout` <= `worker --timeout` (or Horizon `timeout`) < `retry_after` - a few seconds
   <= Supervisor `stopwaitsecs`. Long jobs get their own connection with a larger `retry_after`
   and their own worker/supervisor. Details and known-good files:
   [references/config.md](references/config.md).
4. **Triage failed jobs** (if any). Export to a file (do not paste payloads into the chat):
   ```bash
   # MySQL / MariaDB
   mysql --batch -e "SELECT uuid, connection, queue, payload, exception, failed_at FROM failed_jobs ORDER BY id DESC LIMIT 5000" app > failed_jobs.tsv
   # PostgreSQL (JSON, because unaligned psql output does not escape newlines)
   psql -At -c "SELECT json_agg(f) FROM (SELECT uuid, connection, queue, payload, exception, failed_at FROM failed_jobs ORDER BY id DESC LIMIT 5000) f" app > failed_jobs.json
   python3 scripts/failed_jobs_triage.py failed_jobs.tsv --ids
   ```
   Groups are job class + exception + normalised message, with a cause and advice.
5. **Decide per group** using [references/failed-jobs.md](references/failed-jobs.md):
   - `missing-model`: forget, and set `$deleteWhenMissingModels = true`.
   - `timeout`: fix the timeout chain, then retry.
   - `external` / `db-lock`: retry after the dependency is healthy; add `$backoff`.
   - `bug` / `deploy-mismatch`: fix and deploy first, restart workers, then retry.
   Show the `queue:retry` / `queue:forget` commands and **wait for the user to confirm**. Retrying
   jobs that send emails, charge cards or call webhooks can do it twice; check idempotency first.
   Never run `queue:flush` (deletes all failed jobs) or `horizon:clear` without explicit approval.
6. **Deploy hygiene.** Workers keep old code in memory. Every deploy must run
   `php artisan queue:restart` (queue:work) or `php artisan horizon:terminate` (Horizon), and
   Supervisor must restart them (`autorestart=true`).
7. **Verify**: re-run the config check; for Horizon, `php artisan horizon:status`; for workers,
   `sudo supervisorctl status`. Watch new failures with `php artisan queue:failed`.

## Output

```
Queue review (redis, Horizon 5)
HIGH   config/horizon.php  supervisor-1 timeout 90s is not below retry_after 90s -> jobs run twice
       fix: timeout 60, retry_after 90 (or a 'long' connection with retry_after 1900 for reports)
MEDIUM /etc/supervisor/conf.d/horizon.conf  stopwaitsecs unset -> deploys kill running jobs
Failed jobs: 8 in 3 groups
  4x GenerateReport  timeout       -> after fixing timeouts: php artisan queue:retry <4 ids>
  3x SendInvoice     missing-model -> forget (invoice deleted); add $deleteWhenMissingModels
  1x SyncCrm         external      -> retry once the CRM API is up
Commands to run (after your OK): ...
```

## Notes

- The checker reads only `QUEUE_CONNECTION` from `.env`. The triage script prints job
  class names and the first exception line, never payload data.
- Laravel 11+ default `config/queue.php` uses `database`; workers still need a process manager.
