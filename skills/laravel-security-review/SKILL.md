---
name: laravel-security-review
description: Security review of a Laravel application - scans PHP, Blade and .env files for mass assignment ($guarded = [], $request->all() into create/update, is_admin in $fillable), SQL injection through whereRaw/DB::raw/DB::select with interpolated variables and orderBy on request input, unescaped Blade output {!! !!}, disabled or wildcard CSRF exceptions, APP_DEBUG=true and hard-coded debug, controllers without authorization, unserialize/exec on input, disabled TLS verification and credentialed wildcard CORS. Use when the user asks to audit, review or harden a Laravel app, check a pull request for security issues, prepare for a pentest or go-live, or asks about XSS, SQL injection, CSRF, mass assignment or policies in Laravel.
license: MIT
compatibility: Python 3.8+. Reads project files as text; PHP and Composer are only needed for the optional composer audit step. Laravel 8-12.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Laravel security review

Find the security mistakes that show up again and again in Laravel code, explain each one
with a concrete fix, and never change code without the user's approval.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Audit / security review my Laravel app", "is this controller safe?", "check this PR"
- Before go-live, a pentest, or after a vulnerability report
- Questions about mass assignment, `{!! !!}`, `whereRaw`, CSRF exceptions, policies, `APP_DEBUG`

## When not to use

- Server hardening (SSH, firewall, TLS on the host): use a server audit, not this skill
- Dependency CVEs only: run `composer audit` (step 4) and stop
- Performance or N+1 questions: use `laravel-performance` or `eloquent-n-plus-one`
- Non-Laravel PHP (WordPress, Symfony): the checks assume Laravel conventions

## Workflow

1. **Locate the project root** (the folder with `artisan` and `composer.json`). Note the
   Laravel version from `composer.json` (`laravel/framework`): Laravel 11+ configures CSRF
   and middleware in `bootstrap/app.php`, older versions in `app/Http/Middleware/` and
   `app/Http/Kernel.php`.
2. **Run the scanner (read-only).**
   ```bash
   python3 scripts/laravel_security_scan.py /path/to/project
   python3 scripts/laravel_security_scan.py /path/to/project --json > security.json
   python3 scripts/laravel_security_scan.py app/Http/Controllers/PostController.php  # one file
   ```
   It skips `vendor/`, `node_modules/`, `storage/`, `public/` and `bootstrap/cache/`.
   Exit 1 = findings at or above `--fail-on` (default `medium`); 2 = bad path.
   For a pull request, scan only the changed files:
   `git diff --name-only origin/main... | grep -E '\.php$|\.env' | xargs python3 scripts/laravel_security_scan.py`
3. **Triage every finding before reporting it.** The scanner reads text, so confirm each hit:
   - `authorization`: open `routes/web.php` / `routes/api.php`. A `->can('update', 'post')`
     or `middleware('can:...')` on the route, or a policy registered with
     `authorizeResource`, makes the finding a false positive. Say so.
   - `blade-unescaped` medium: find where the variable comes from. Admin-written HTML that is
     sanitized on save is acceptable; user-written content is XSS.
   - `raw-sql`: interpolated values that are cast (`(int) $id`) or from an allow-list are
     lower risk, but still recommend bindings.
   - `debug` in `.env.example`: matters because people copy it to servers.
   Use [references/checks.md](references/checks.md) for the explanation and fix of each check.
4. **Check what text scanning cannot see.**
   - Dependencies: `composer audit` (Composer 2.4+), report advisories with package and fix version.
   - Validation: every `store`/`update` should validate (`$request->validate()` or a FormRequest).
   - File uploads: `mimes:`/`mimetypes:` and `max:` rules; files stored outside `public/` unless
     meant to be public; no user-controlled paths in `Storage::download()`.
   - Auth: rate limiting on login/password reset (`throttle` middleware or `RateLimiter`),
     `Password::defaults()` rules, signed URLs for email links.
   - Secrets: `.env` not committed (`git ls-files | grep -E '^\.env$'`), `APP_KEY` set in production.
   The full manual checklist is in [references/manual-review.md](references/manual-review.md).
5. **Report** grouped by severity with file:line, why it matters, and the corrected code.
   Then offer to fix. Apply changes only after the user agrees, one check type at a time, and
   run the test suite (`php artisan test`) after each change.
6. **Re-run the scanner** to confirm the findings are gone. For accepted risks, add
   `// security-scan: ignore` with a reason on that line instead of deleting the check.

## Output

```
Laravel security review (Laravel 11, 42 files scanned): 3 high, 4 medium, 1 low

HIGH  app/Http/Controllers/PostController.php:28  mass assignment
      Post::create($request->all()) lets a user set any column (user_id, is_published).
      fix: Post::create($request->validated()) with StorePostRequest rules for title, body.
HIGH  resources/views/search.blade.php:3  reflected XSS: {!! request('q') !!}
      fix: {{ request('q') }}
MEDIUM PostController@destroy has no authorization (route has no can: middleware)
      fix: Gate::authorize('delete', $post); add PostPolicy::delete
...
Not found by the scanner, checked manually: composer audit (0 advisories), login throttle (ok)
Next step: want me to fix the 3 high findings now?
```

## Notes

- Severities: high = exploitable as-is, medium = exploitable depending on context, low =
  hygiene. `--min-severity medium` hides the rest.
- Never print `.env` values in the report; the scanner only reads `APP_ENV`, `APP_DEBUG` and
  `SESSION_SECURE_COOKIE`.
