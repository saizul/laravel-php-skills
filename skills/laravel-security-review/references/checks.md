# Scanner checks: why they matter and how to fix them

## mass-assignment

| Pattern | Severity | Why |
| --- | --- | --- |
| `protected $guarded = [];` | high | Any request field becomes a column write when combined with `create($request->all())` or `fill()`. |
| `Model::unguard()` | medium | Disables protection for every model until `reguard()`. Fine in seeders only. |
| `is_admin`, `role`, `permissions` in `$fillable` | medium | A registration or profile form can promote a user. |
| `create($request->all())`, `update($request->all())`, `fill($request->all())` | high | Writes whatever the client sends. |

Fix:

```php
// FormRequest
public function rules(): array
{
    return ['title' => ['required', 'string', 'max:200'], 'body' => ['required', 'string']];
}

// Controller
$post = $request->user()->posts()->create($request->validated());
```

Laravel 9+ can throw on silently discarded attributes in development:
`Model::preventSilentlyDiscardingAttributes(! app()->isProduction());`

## raw-sql

Bindings protect values, never identifiers. Vulnerable:

```php
Post::whereRaw("title LIKE '%{$q}%'");
DB::select('select * from posts where user_id = ' . $id);
Post::orderBy($request->input('sort'));            // column name injection
```

Fixed:

```php
Post::where('title', 'like', '%'.$q.'%');
Post::whereRaw('title LIKE ?', ['%'.$q.'%']);
DB::select('select * from posts where user_id = ?', [$id]);
$sort = in_array($request->input('sort'), ['title', 'created_at'], true) ? $request->input('sort') : 'id';
Post::orderBy($sort);
```

Escape `%` and `_` in LIKE input if users must not use wildcards.

## blade-unescaped

`{{ $x }}` runs `htmlspecialchars`. `{!! $x !!}` prints raw HTML.

- Request data (`request()`, `$request`, `old()`) in `{!! !!}` is reflected XSS: high.
- Model content is stored XSS if users can write it: medium until you confirm the source.
- Skipped as safe: `{!! csrf_field() !!}`, `{!! method_field(...) !!}`, `{!! $items->links() !!}`.

If HTML must be rendered (rich text editor), sanitize on save with an HTML purifier and
render the sanitized column. For JSON in scripts use `@json($data)` or `Js::from($data)`.

## csrf

- Laravel 10 and older: `app/Http/Middleware/VerifyCsrfToken.php` `$except`.
- Laravel 11+: `bootstrap/app.php` `$middleware->validateCsrfTokens(except: [...])`.

`'*'` disables CSRF everywhere (high). `webhooks/*` is broad (medium): list the exact path
(`stripe/webhook`) and verify the provider signature in the controller. Token-authenticated
APIs belong in `routes/api.php`, which has no CSRF middleware.

## debug

`APP_DEBUG=true` in production shows stack traces, environment variables and SQL on every
error page (Ignition). In `.env.example` it is medium because the example is usually copied.
`'debug' => true` in `config/app.php` overrides the environment entirely.

## authorization

Controllers with `store`, `update`, `destroy`, `edit`, `delete`, `restore` or `forceDelete`
and none of: `$this->authorize()`, `Gate::authorize()`, `->can()`, `abort_unless()`, a
FormRequest parameter (whose `authorize()` runs first), `authorizeResource()`, or
`middleware('can:...')`/`HasMiddleware` on the class.

Authorization can also live on the route; check before reporting:

```php
Route::put('/posts/{post}', [PostController::class, 'update'])->can('update', 'post');
```

Model-bound routes without a policy are an IDOR: user A can edit user B's post by ID.

## dangerous-call

`unserialize()` on input enables PHP object injection (gadget chains exist in common
packages). Use `json_decode`. Never pass input to `exec`, `shell_exec`, `system`, `passthru`,
`proc_open`, `eval`; use `Process::run(['convert', $path, $out])` with an argument array.

## tls

`Http::withoutVerifying()` or Guzzle `'verify' => false` allows man-in-the-middle attacks
on outgoing calls. Fix the CA bundle (`ca-certificates` package, `curl.cainfo` in php.ini).

## cors

`allowed_origins => ['*']` with `supports_credentials => true` lets any site make
authenticated requests (browsers reject the literal `*` with credentials, so the CORS
package reflects the origin instead). List origins explicitly.

## debug-helper

`dd()`, `dump()`, `var_dump()`, `ray()` in `app/` leak data and stop requests. Use logging.

## Known false positives

- Authorization done in route definitions or a parent controller constructor.
- `$guarded = []` on a model that is only written from trusted code paths (still prefer `$fillable`).
- Raw SQL built from constants (`'... where status = ' . self::ACTIVE`). Add an ignore comment.
