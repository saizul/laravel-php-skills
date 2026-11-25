---
name: laravel-migrations-safety
description: Review Laravel database migrations for production risk before they run - flags dropColumn, dropIfExists and truncate in up(), renameColumn and Schema::rename, ->change() on big tables, NOT NULL columns without defaults, unique indexes and foreign keys added to existing tables, data backfills inside migrations, raw DB::statement, and missing or empty down() methods - then plans safe expand/contract rollouts. Use when the user writes or reviews a migration, asks whether a migration is safe to deploy, plans a zero-downtime schema change, renames or drops a column, adds an index to a large table, or runs php artisan migrate in production.
license: MIT
compatibility: Python 3.8+. Reads migration files as text; the optional pretend step needs PHP and a database connection. MySQL 8, MariaDB, PostgreSQL.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Laravel migration safety

Catch the migrations that lose data, lock big tables or break the code that is still running
during a deploy, and turn them into safe multi-step rollouts.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Is this migration safe to run in production?", "review my migrations before deploy"
- Renaming or dropping columns/tables, changing column types, adding indexes or foreign keys
- Planning zero-downtime deploys where old and new code run at the same time
- A migration that timed out, locked a table or failed half way

## When not to use

- Designing a schema from scratch with no production data yet (nothing to protect; just review naming)
- Query performance or N+1 issues: use `eloquent-n-plus-one`
- Running the migration: this skill reviews; the user (or their deploy pipeline) runs it

## Workflow

1. **Find the pending migrations.** On the target environment, `php artisan migrate:status`
   lists what has not run. Locally, use the files added since the last release
   (`git diff --name-only v1.4.0... -- database/migrations`).
2. **Ask which tables are big** (rows or traffic), e.g. `users`, `orders`, `events`. If the
   user does not know: MySQL `SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema = DATABASE() ORDER BY table_rows DESC LIMIT 10;`
   PostgreSQL `SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 10;`
3. **Run the checker (read-only).**
   ```bash
   python3 scripts/migration_safety.py . --big-tables users,orders
   python3 scripts/migration_safety.py database/migrations/2026_11_02_000000_alter_users_table.php
   python3 scripts/migration_safety.py . --since 2026_11_01 --json
   ```
   Exit 1 = findings at or above `--fail-on` (default `high`). Use `--fail-on medium` in CI.
4. **Decide per finding** using [references/safe-patterns.md](references/safe-patterns.md):
   - **drop-column / drop-table**: is any deployed code still reading it? If yes, split into
     release N (stop using it, remove from `$fillable`/`$casts`/resources) and release N+1 (drop).
   - **rename**: never in one step on a live app. Use expand/contract (add, dual-write,
     backfill, switch reads, drop).
   - **change** on a big table: may copy the whole table. Plan online DDL or a maintenance window.
     Laravel 11+: `->change()` must repeat every modifier you want to keep (`nullable()`, `default()`).
   - **not-null-no-default**: add as nullable, backfill, then make it required.
   - **unique-on-existing / foreign-key**: check duplicates / orphans first (queries in the reference).
   - **data-migration**: move large backfills to a queued job or artisan command that runs in chunks.
   - **missing-down / empty-down**: write `down()`, or say explicitly that the migration is
     one-way and rollback = restore from backup.
5. **Preview the SQL** without running it: `php artisan migrate --pretend` (shows the
   statements Laravel will send). Point out statements that rebuild a table.
6. **Report and propose the rewritten migration(s)**, split into release steps when needed.
   Do not run `migrate`, `migrate:rollback` or `migrate:fresh` against any shared or production
   database; `migrate:fresh` drops every table. Remind the user to back up first.

## Output

```
Migration review (3 pending, big tables: users)
HIGH   2026_11_02_alter_users_table.php:14  renameColumn name -> full_name
       Old code still selects `name` during the deploy -> 500s until all servers switch.
       Plan: R1 add full_name + write both, backfill job; R2 read full_name; R3 drop name.
MEDIUM ...:16  timezone NOT NULL without default on users (4.2M rows)
       fix: ->nullable(), backfill, then ->nullable(false)->change() in a later release
Rewritten migrations: (code)
Before running: backup, php artisan migrate --pretend, run off-peak.
```

## Notes

- `Schema::create` blocks are only checked for `->change()`; new tables have no rows to protect.
- The checker does not know your database engine. On MySQL 8 many `ADD COLUMN` operations
  are instant; on PostgreSQL 11+ adding a column with a constant default is fast. Mention it.
