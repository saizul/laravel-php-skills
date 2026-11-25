# Safe migration patterns

During a deploy, old and new code run side by side (rolling restarts, queued jobs from the
old release, long requests). Every schema change must work with both versions.

## Expand / contract (rename a column)

Release 1 (expand):

```php
Schema::table('users', function (Blueprint $table) {
    $table->string('full_name')->nullable();
});
```

```php
// model: write both, read old
protected static function booted(): void
{
    static::saving(fn (User $u) => $u->full_name = $u->name);
}
```

Backfill in batches (command or job, not the migration):

```php
User::whereNull('full_name')->chunkById(1000, function ($users) {
    foreach ($users as $u) {
        $u->updateQuietly(['full_name' => $u->name]);
    }
});
```

Release 2: read `full_name` everywhere, stop writing `name`.
Release 3 (contract): `$table->dropColumn('name');`

## Drop a column

1. Remove every use: model `$fillable`, `$casts`, `$appends`, API resources, queries,
   Blade, factories, seeders, exports. Search: `grep -rn "legacy_flag" app resources database routes`.
2. Deploy. Wait until queued jobs from the old release are processed.
3. Back up, then drop in the next release.

## Add a required column

```php
// Release 1
$table->string('timezone')->nullable();
// backfill job: UPDATE users SET timezone = 'UTC' WHERE timezone IS NULL (in batches)
// Release 2
$table->string('timezone')->nullable(false)->default('UTC')->change();
```

With a constant default you can often do it in one step:
`$table->string('timezone')->default('UTC');` (MySQL 8 instant ADD COLUMN, PostgreSQL 11+ fast default).

## Change a column (`->change()`)

- Laravel 11+ no longer needs `doctrine/dbal` and **drops attributes you do not repeat**:
  `$table->string('email', 320)->nullable()->unique()->change()` must list `nullable()` again
  if the column was nullable.
- Type changes (`string` -> `text`, `int` -> `bigint`) usually rebuild the table on MySQL
  (`ALGORITHM=COPY`) and take an `ACCESS EXCLUSIVE` lock on PostgreSQL.
- For big MySQL tables use `pt-online-schema-change` or `gh-ost`; for PostgreSQL, add a new
  column, backfill, swap.

## Indexes on big tables

MySQL 8 / MariaDB (online, no write lock for most secondary indexes):

```php
DB::statement('ALTER TABLE orders ADD INDEX orders_created_at_index (created_at), ALGORITHM=INPLACE, LOCK=NONE');
```

PostgreSQL (must not run inside a transaction):

```php
return new class extends Migration
{
    public $withinTransaction = false;

    public function up(): void
    {
        DB::statement('CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_created_at_index ON orders (created_at)');
    }

    public function down(): void
    {
        DB::statement('DROP INDEX CONCURRENTLY IF EXISTS orders_created_at_index');
    }
};
```

## Unique index and foreign keys on existing data

Duplicates (fix before adding `->unique()`):

```sql
SELECT username, COUNT(*) c FROM users GROUP BY username HAVING c > 1;
```

Orphans (fix before adding `->constrained()`):

```sql
SELECT COUNT(*) FROM users u LEFT JOIN teams t ON t.id = u.team_id WHERE u.team_id IS NOT NULL AND t.id IS NULL;
```

PostgreSQL can add a foreign key without a long lock: `ALTER TABLE ... ADD CONSTRAINT ... NOT VALID;`
then `ALTER TABLE ... VALIDATE CONSTRAINT ...;` in a later migration.

## Data migrations

Migrations run inside the deploy; a 20-minute `UPDATE` blocks the deploy and may hold locks.

- Schema in migrations, data in jobs/commands (`php artisan app:backfill-timezones`).
- If it must be in a migration: use the query builder (models change over time), `chunkById`,
  and keep it idempotent.

## down() policy

- Reversible: `down()` restores the previous schema (data in dropped columns is still gone).
- One-way: say so.
  ```php
  public function down(): void
  {
      throw new RuntimeException('One-way migration: restore from backup to roll back.');
  }
  ```

## Deploy checklist

- [ ] Backup taken and restore tested recently
- [ ] `php artisan migrate --pretend` reviewed
- [ ] Code in this release works with both the old and the new schema
- [ ] Big-table operations scheduled off-peak or done online
- [ ] `php artisan migrate --force` runs once per deploy (not on every server)
- [ ] `--isolated` (Laravel 9.x+) used when several servers could run migrations at once
