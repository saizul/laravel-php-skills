---
name: laravel-testing
description: Write and fix Laravel tests with Pest or PHPUnit - feature tests for HTTP routes and JSON APIs, factories with states and relationships, RefreshDatabase, actingAs and Sanctum, fakes for Http, Mail, Notification, Queue, Event, Bus and Storage, time travel, plus a scanner for test-suite smells (->only() left in, dd()/sleep() in tests, database use without RefreshDatabase, real HTTP calls without Http::fake, tests with no assertions, withoutMiddleware, hard-coded ids). Use when the user asks to add tests for a controller, endpoint, job, policy or Livewire component, convert PHPUnit to Pest, set up factories, fix slow or flaky tests, or review a Laravel test suite.
license: MIT
compatibility: Python 3.8+ for the scanner. Running tests needs PHP 8.2+ and the project's Composer dependencies. Laravel 10-12, Pest 2-3, PHPUnit 10-11.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Laravel testing

Write tests that prove behaviour through the HTTP layer, isolate the outside world with
fakes, and keep the suite fast and deterministic.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Write tests for this controller / endpoint / job / policy / Livewire component"
- "Our tests are slow / flaky", "review our test suite", "convert these PHPUnit tests to Pest"
- Setting up factories, seeders for tests, Sanctum auth in API tests, parallel testing

## When not to use

- Browser end-to-end tests with a real browser (Laravel Dusk, Playwright): different setup
- Static analysis errors: use `php-static-analysis`
- Measuring query counts for N+1: `eloquent-n-plus-one` has the query-count test recipe

## Workflow

1. **Detect the stack.** `composer.json`: `pestphp/pest` (Pest) or only `phpunit/phpunit`.
   Match the existing style; do not convert PHPUnit to Pest unless asked. Check
   `phpunit.xml` for `DB_CONNECTION` (`sqlite` + `:memory:` is fastest) and `tests/Pest.php`
   for global `->use(RefreshDatabase::class)`.
2. **Scan the existing suite (read-only).**
   ```bash
   python3 scripts/find_test_smells.py /path/to/project
   python3 scripts/find_test_smells.py . --fail-on high --json
   ```
   Fix `high` (a focused `->only()` silently skips the rest of CI) and `medium` first. Exit 1 =
   findings at or above `--fail-on` (default `medium`).
3. **Decide what to test** for the code in question:
   | Code | Test type | Key assertions |
   | --- | --- | --- |
   | Web controller | Feature (`$this->get/post`) | status, redirect, view data, `assertDatabaseHas` |
   | JSON API | Feature (`getJson/postJson`) | `assertJson`, `assertJsonPath`, `assertJsonValidationErrors` |
   | Policy / auth | Feature, two users | 403 for the other user, 200 for the owner |
   | Job / listener | Unit-ish, call `handle()` | side effects, fakes asserted |
   | Dispatching code | Feature + `Queue::fake()` | `Queue::assertPushed(Job::class, fn ...)` |
   | Mail / notification | `Mail::fake()` / `Notification::fake()` | `assertSent`, `assertSentTo` |
   | Pure PHP class | Unit (no app boot) | return values |
   Cover the happy path, validation failures, unauthorised access and one edge case.
4. **Write the tests** using the patterns in [references/patterns.md](references/patterns.md)
   (factories, auth, fakes, time, files) and [references/factories.md](references/factories.md).
   Rules: factories instead of hand-built rows; `route()` names instead of hard-coded URLs
   with ids; fake every external boundary (`Http::fake()` + `Http::preventStrayRequests()`);
   one behaviour per test; descriptive names (`it('rejects a duplicate email')`).
5. **Run them** and show the output:
   ```bash
   php artisan test --filter=PostTest          # or: ./vendor/bin/pest --filter "creates a post"
   php artisan test --parallel                 # needs brianium/paratest
   php artisan test --coverage --min=80        # needs Xdebug or PCOV
   ```
   If a test fails, read the failure, fix the test or report the bug it found. Never delete
   or weaken an assertion just to make a test pass; say so if the code is wrong.
6. **Re-run the scanner** so new tests do not add smells.

## Output

```
Added tests/Feature/PostControllerTest.php (6 tests, Pest)
  ✓ guests are redirected to login
  ✓ users can create a post
  ✓ title is required
  ✓ users cannot update someone else's post (403)
  ✓ deleting a post soft-deletes it
  ✓ publishing dispatches NotifySubscribers (Queue::fake)
php artisan test --filter=PostControllerTest: 6 passed (0.41s)
Suite smells: removed ->only() in tests/Feature/UserTest.php:14, added RefreshDatabase to Pest.php
```

## Notes

- `RefreshDatabase` runs migrations once and wraps each test in a transaction. Tests that need
  real commits (some queue or multi-connection tests) can use `DatabaseTruncation` (Laravel 10+).
- Laravel 11+ `phpunit.xml` uses SQLite in memory by default; if production is MySQL/PostgreSQL
  and you rely on JSON columns or full-text search, run CI against the same engine.
