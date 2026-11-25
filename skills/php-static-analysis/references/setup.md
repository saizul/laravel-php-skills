# PHPStan / Larastan setup

## Versions

| Project | Install |
| --- | --- |
| Laravel 11/12, PHP 8.2+ | `composer require --dev larastan/larastan:^3.0` (PHPStan 2) |
| Laravel 9/10, PHP 8.0+ | `composer require --dev larastan/larastan:^2.0` (PHPStan 1) |
| Plain PHP | `composer require --dev phpstan/phpstan` (+ `phpstan/extension-installer` for extensions) |

Check the Larastan README for the current support matrix before pinning.

## phpstan.neon (Laravel)

```neon
includes:
    - vendor/larastan/larastan/extension.neon
    - phpstan-baseline.neon            # after generating one

parameters:
    level: 5
    paths:
        - app/
        - config/
        - database/
        - routes/
    tmpDir: storage/framework/cache/phpstan   # keep the cache out of /tmp in CI
    reportUnmatchedIgnoredErrors: true
    # checkModelProperties: true       # Larastan: validate column names in where('col') etc.
```

Commit `phpstan.neon.dist` if developers keep a local `phpstan.neon` override.

## Plain PHP

```neon
parameters:
    level: 6
    paths: [src, tests]
    phpVersion: 80300                  # analyse for PHP 8.3
```

## Levels (cumulative)

| Level | Adds |
| --- | --- |
| 0 | unknown classes, functions, methods on `$this`, wrong arg counts, undefined variables (always) |
| 1 | possibly undefined variables, magic methods/properties on classes with `__call`/`__get` |
| 2 | unknown methods on all expressions, PHPDoc validation |
| 3 | return types, property types |
| 4 | dead code, always-true/false conditions |
| 5 | argument types |
| 6 | missing typehints (`missingType.*`) |
| 7 | union types partially wrong |
| 8 | nullable types (method calls on `?Foo`) |
| 9 | strict `mixed` |
| 10 | (PHPStan 2) implicit `mixed` too |

Start at the highest level with a manageable error count (often 5), baseline, then move up.

## Baseline workflow

```bash
vendor/bin/phpstan analyse --generate-baseline                 # writes phpstan-baseline.neon
vendor/bin/phpstan analyse --generate-baseline phpstan-baseline.php   # PHP format (faster to load)
```

- Regenerate after fixing errors so the counts shrink; with `reportUnmatchedIgnoredErrors`,
  PHPStan reports entries that no longer match.
- Never hand-edit counts upward to hide new errors.
- Review a baseline diff in PRs: it should only ever shrink.

## Common Laravel errors

| Error | Usual fix |
| --- | --- |
| `Access to an undefined property App\Models\X::$col` | Larastan installed? Column exists in migrations? Add `@property` for accessors or virtual columns |
| `Call to an undefined method Builder::scopeName()` | call `->active()` not `->scopeActive()`; Laravel 12 `#[Scope]` attribute or `@method` |
| `Relation 'x' is not found` | relation method missing or misspelled in `with('x')` |
| `return type with generic class HasMany does not specify its types` | `/** @return HasMany<Comment, $this> */` (Larastan 3) |
| `Called 'env' outside of the config directory` | move to `config/*.php`, read with `config()` |
| `Parameter #1 ... expects int, string given` for request input | `$request->integer('id')`, `->string()`, `->boolean()` |
| `Cannot call method x() on App\Models\User|null` (level 8) | `$request->user()` can be null: guard or use `auth()->user()` with a check |

Ignore a single line only with a reason:

```php
/** @phpstan-ignore property.notFound (legacy column, removed in #123) */
```

## CI (GitHub Actions)

```yaml
- uses: shivammathur/setup-php@v2
  with:
    php-version: '8.3'
    coverage: none
- run: composer install --no-interaction --no-progress --prefer-dist
- run: vendor/bin/phpstan analyse --no-progress --error-format=github
```

Optional summary as a job artifact:

```yaml
- run: vendor/bin/phpstan analyse --no-progress --error-format=json > phpstan.json || true
- run: python3 scripts/phpstan_summary.py phpstan.json
```

## Memory and speed

- `--memory-limit=1G` (or `-1` locally) for large projects.
- Keep `tmpDir` cached between CI runs (`actions/cache` on `storage/framework/cache/phpstan`).
- `parallel` settings in `phpstan.neon` (`maximumNumberOfProcesses`) for CI runners with few CPUs.
