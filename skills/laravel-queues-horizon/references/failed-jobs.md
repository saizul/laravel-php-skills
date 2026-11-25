# Failed jobs playbook

## Commands

| Command | Effect |
| --- | --- |
| `php artisan queue:failed` | list failed jobs (id, connection, queue, class, failed at) |
| `php artisan queue:retry <id> [<id> ...]` | push the listed jobs back on their queue |
| `php artisan queue:retry --queue=emails` | retry every failed job of one queue |
| `php artisan queue:retry all` | retry everything (rarely a good idea) |
| `php artisan queue:forget <id>` | delete one failed job |
| `php artisan queue:prune-failed --hours=168` | delete failed jobs older than 7 days |
| `php artisan queue:flush` | delete **all** failed jobs |
| `php artisan horizon:forget <id>` / `horizon:clear` | Horizon equivalents (clear empties a queue) |

Retry, forget, prune and flush change data: show the command and wait for confirmation.

## Causes and what to do

| Cause (script label) | Typical exception | Action |
| --- | --- | --- |
| timeout | `MaxAttemptsExceededException`, `TimeoutExceededException`, "has timed out" | Fix the timeout chain, move slow jobs to a long queue, then retry |
| missing-model | `ModelNotFoundException` | Record was deleted; forget, set `$deleteWhenMissingModels = true` |
| db-lock | Deadlock, lock wait timeout, SQLSTATE 40001 | Retry; add `$backoff`; shorten transactions |
| database | other `QueryException` | Check pending migrations / schema mismatch, fix, retry |
| external | `ConnectionException`, cURL 7/28, 429, 502-504 | Retry when healthy; `$backoff`, `ThrottlesExceptions`, `RateLimited` middleware |
| memory | "Allowed memory size exhausted" | Chunk work, raise memory limits, recycle workers |
| deploy-mismatch | class not found, undefined method, incomplete class | Workers ran old code or payload is stale: restart workers; old payloads may need forget |
| bug | `TypeError`, `ErrorException`, validation errors | Fix the code, deploy, then retry |

## Before retrying

1. Is the job idempotent? Emails, payments and webhooks may run twice if a previous attempt
   partly succeeded. Check the side effect (was the email sent? is the payment recorded?).
2. Is the cause fixed and deployed, and were workers restarted?
3. Retry a few ids first, watch `queue:failed` / Horizon, then the rest.

## Monitoring

- Alert on `Illuminate\Queue\Events\JobFailed` (listener that notifies Slack/email, rate limited).
- Horizon: "Failed Jobs" and wait-time thresholds in `config/horizon.php` `waits`.
- Without Horizon: `php artisan queue:monitor redis:default --max=100` on the scheduler
  (emits `QueueBusy` events).
