# Manual review checklist

Things the scanner cannot judge. Go through them after the scan.

## Authentication

- [ ] Login, register, password reset and 2FA routes are rate limited
      (`->middleware('throttle:5,1')` or `RateLimiter::for('login', ...)`).
- [ ] Password rules use `Password::min(12)->uncompromised()` (or the app's `Password::defaults()`).
- [ ] Session is regenerated on login (`$request->session()->regenerate()`); starter kits do this.
- [ ] `SESSION_SECURE_COOKIE=true`, `SESSION_HTTP_ONLY` default true, `same_site` = `lax` or `strict`.
- [ ] Email verification / password reset links are signed (`URL::temporarySignedRoute`) and expire.
- [ ] Sanctum: tokens have abilities and expiry (`expiration` in `config/sanctum.php`), SPA
      `stateful` domains list only real front-ends.

## Authorization

- [ ] Every model-bound route has a policy check (IDOR). Try: can user A open `/posts/{id-of-B}/edit`?
- [ ] Admin areas use a gate or middleware on the route group, not only hidden links.
- [ ] Livewire components authorize in actions and do not trust public properties (`#[Locked]`).
- [ ] Filament/Nova resources have policies.

## Validation and input

- [ ] Every write validates. Arrays use `array:allowed,keys` or nested rules.
- [ ] Uploads: `file`, `mimes:jpg,png,pdf`, `max:` (KB); stored with `store()` (random name), not
      `storeAs($request->name)`.
- [ ] No user-controlled paths in `Storage::get/download`, `response()->file()`, `include`.
- [ ] Redirects to user-supplied URLs use an allow-list (`redirect()->intended()` is safe).
- [ ] SSRF: outgoing requests to user-supplied URLs are restricted (no `169.254.169.254`, internal hosts).

## Output

- [ ] JSON responses use API Resources and do not expose `password`, tokens or internal flags
      (`$hidden` on models).
- [ ] Error pages in production are generic (`APP_DEBUG=false`).
- [ ] `Content-Security-Policy` and other security headers set at the web server or with middleware.

## Secrets and config

- [ ] `.env` is not in git: `git ls-files | grep -E '(^|/)\.env$'` returns nothing.
- [ ] `APP_KEY` is set and was not rotated without re-encrypting data.
- [ ] `config/logging.php` does not log request bodies with passwords; `$dontFlash` covers secrets.
- [ ] Telescope, Horizon, Pulse, Log Viewer dashboards are gated in production
      (`viewTelescope`, `viewHorizon`, `viewPulse` gates).

## Dependencies

```bash
composer audit                 # Composer 2.4+, reads the lock file
composer outdated --direct     # what is behind
npm audit --omit=dev           # front-end build dependencies
```

Report advisories with package, installed version, fixed version and CVE.
