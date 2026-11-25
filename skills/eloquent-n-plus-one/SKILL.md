---
name: eloquent-n-plus-one
description: Detect and fix Eloquent N+1 query problems in Laravel - parses a query log (DB::listen log lines, DB::getQueryLog() JSON, plain SQL) or a Telescope export, groups queries per request, finds selects repeated in a loop and suggests the exact fix (with(), load(), withCount(), withExists(), withSum()), and reports lazy-loading violations from Model::preventLazyLoading(). Use when a Laravel page or API endpoint is slow, Debugbar or Telescope shows hundreds of queries, the user mentions N+1, eager loading, lazy loading, "too many queries", or wants to add preventLazyLoading or a query-count test.
license: MIT
compatibility: Python 3.8+. Works offline on exported logs; capturing a log needs a local or staging Laravel 8+ app.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Eloquent N+1 detection

Measure first, then fix: capture the real queries of one slow request, let the script find
the repeated ones, change the query, and prove the count dropped.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "This page runs 300 queries", "the API is slow", "Debugbar shows duplicate queries"
- Reviewing a controller, Livewire component, API Resource or Blade view that loops over models
- Adding `Model::preventLazyLoading()` or a test that guards the query count

## When not to use

- A single slow query (missing index, full table scan): use `EXPLAIN` and indexing instead
- Slowness that is not database bound (external APIs, heavy PHP): profile first, see `laravel-performance`
- Production logging of every query on a busy site: capture on staging or for a short window only

## Workflow

1. **Pick one request to measure** (URL or API route) and capture its queries. Choose one:
   - Telescope installed (local/staging): export recent query entries from `php artisan tinker`:
     `file_put_contents('queries.json', DB::table('telescope_entries')->where('type', 'query')->latest('sequence')->limit(2000)->get()->toJson());`
   - No Telescope: add a temporary listener in `AppServiceProvider::boot()` (local only):
     ```php
     if (app()->isLocal()) {
         $rid = (string) \Illuminate\Support\Str::uuid();
         \DB::listen(fn ($q) => logger()->debug('sql', ['sql' => $q->toRawSql(), 'time' => $q->time, 'request' => $rid]));
     }
     ```
     (`toRawSql()` is Laravel 10.15+; on older versions log `$q->sql` and `$q->bindings`.)
     Hit the page once, then use `storage/logs/laravel.log`.
   - In a test or tinker: `DB::enableQueryLog(); ...; file_put_contents('q.json', json_encode(DB::getQueryLog()));`
2. **Run the detector.**
   ```bash
   python3 scripts/find_n_plus_one.py storage/logs/laravel.log
   python3 scripts/find_n_plus_one.py queries.json --threshold 3 --json
   ```
   Each pattern shows how often it ran per request, total time, the source location (Telescope
   records file:line) and the likely fix. Exit 1 = patterns or lazy-loading violations found.
3. **Find the loop.** Open the reported file:line, or search for the relation. Typical places:
   Blade `@foreach ($posts as $post) {{ $post->user->name }}`, API Resources (`$this->user->name`),
   accessors that touch relations, `$appends`, policies called per row, Livewire computed properties.
4. **Apply the fix that matches the pattern** (see [references/eager-loading.md](references/eager-loading.md)):
   | Pattern | Fix |
   | --- | --- |
   | `where users.id = ?` repeated | `Post::with('user')` |
   | `where comments.post_id = ?` repeated | `Post::with('comments')` |
   | `count(*) ... where post_id = ?` | `Post::withCount('comments')` |
   | nested (`post.comments.author`) | `with('comments.author')` |
   | only some columns needed | `with('user:id,name')` (keep the key column) |
   | collection already loaded | `$posts->load('user')` or `loadMissing()` |
   | API Resource conditional | `$this->whenLoaded('user')` |
   Show the user the diff before editing. Do not eager load relations the page does not use.
5. **Verify.** Capture the same request again and re-run the script: the pattern should be
   gone and the total count close to "1 + number of eager-loaded relations".
6. **Prevent regressions** (offer, do not force):
   - `Model::preventLazyLoading(! app()->isProduction());` in `AppServiceProvider::boot()`
     (Laravel 8.43+) or `Model::shouldBeStrict(! app()->isProduction());` (9.35+). Violations
     throw locally; in logs the script reports them as `Model::relation`.
   - A feature test that asserts the query count, see the reference file.

## Output

```
Request GET /posts: 46 queries -> 3 after fix
#1 x15 select * from `users` where `users`.`id` = ?   (resources/views/posts/index.blade.php:12)
   fix: Post::with('user')
#2 x15 select count(*) ... from `comments` where `post_id` = ?
   fix: Post::withCount('comments'); use $post->comments_count in the view
Diff: app/Http/Controllers/PostController.php (1 line)
Guard: added preventLazyLoading for non-production (optional)
```

## Notes

- The default threshold is 5 repeats per request; use `--threshold 3` for small pages.
- Grouping uses Telescope `batch_id`, the `request` key of the log line, or one group per
  file. Plain SQL files count as one request.
- Recent Laravel 12 releases add `Model::automaticallyEagerLoadRelationships()`. Check that the
  installed version has it before suggesting it, and still prefer explicit `with()` in hot paths.
