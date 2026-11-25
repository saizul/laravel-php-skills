---
name: php-static-analysis
description: Set up and adopt PHPStan with Larastan for Laravel or plain PHP projects - phpstan.neon config, choosing a level, generating and shrinking a baseline, CI integration, and a script that summarises PHPStan JSON output by error identifier (rule), file and message pattern, summarises phpstan-baseline.neon/.php, and compares two runs to show new and fixed errors. Use when the user wants to add PHPStan or Larastan, raise the level, deal with hundreds of PHPStan errors, understand or reduce a baseline, fix "undefined property/method" errors on Eloquent models, or fail CI only on new errors.
license: MIT
compatibility: Python 3.8+ for the summary script. PHPStan itself needs PHP 7.4+ (PHPStan 2 needs PHP 7.4+, Larastan 3 needs PHP 8.2+ and Laravel 11+).
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# PHP static analysis (PHPStan + Larastan)

Get a project onto PHPStan without drowning in errors: pick a level, baseline the past,
block new errors in CI, then pay the baseline down rule by rule.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Add PHPStan/Larastan to this project", "what level should we use?"
- "PHPStan reports 1,400 errors, where do we start?", "explain our baseline"
- Eloquent magic: `Access to an undefined property App\Models\User::$name`
- CI should fail only on new errors

## When not to use

- Code style (PHP-CS-Fixer, Pint) or automated refactors (Rector): different tools
- Psalm-only projects: concepts transfer, but the config and script do not
- Runtime bugs PHPStan cannot see (wrong business logic): write tests (`laravel-testing`)

## Workflow

1. **Check what exists.** `composer.json` for `phpstan/phpstan`, `larastan/larastan` (old name
   `nunomaduro/larastan`); config files `phpstan.neon`, `phpstan.neon.dist`, `phpstan-baseline.neon`.
   PHP and Laravel versions decide the Larastan major (see [references/setup.md](references/setup.md)).
2. **Install and configure** (if missing). Show the commands and wait for approval before
   changing `composer.json`:
   ```bash
   composer require --dev larastan/larastan        # pulls in phpstan/phpstan
   ```
   Create `phpstan.neon` from the reference (paths `app/`, level 5 to start, Larastan extension).
3. **Run PHPStan with JSON output** (needs the project's PHP and vendor/):
   ```bash
   vendor/bin/phpstan analyse --error-format=json --no-progress --memory-limit=1G > phpstan.json
   ```
4. **Summarise.**
   ```bash
   python3 scripts/phpstan_summary.py phpstan.json
   python3 scripts/phpstan_summary.py phpstan.json --baseline phpstan-baseline.neon
   python3 scripts/phpstan_summary.py phpstan.json --compare phpstan-main.json   # new vs fixed
   python3 scripts/phpstan_summary.py phpstan.json --json
   ```
   Exit 1 = errors (or new errors with `--compare`); `--max-errors N` tolerates N.
5. **Choose the strategy** from the summary:
   - **< ~50 errors**: fix them now, no baseline.
   - **Many errors, few rules** (e.g. 600 x `missingType.*`): baseline, then one PR per rule.
   - **`property.notFound` / `method.notFound` on models**: usually Larastan is missing or
     model `@property` docs/casts are wrong; fix config before baselining.
   - **General errors** (config, unmatched ignore patterns): fix first, they hide real results.
   Generate a baseline only with the user's agreement:
   `vendor/bin/phpstan analyse --generate-baseline` and add `includes: [phpstan-baseline.neon]`.
6. **Gate CI on new errors.** PHPStan fails on anything not in the baseline, so committing
   the baseline is enough; add `reportUnmatchedIgnoredErrors: true` so fixed errors must be
   removed from it. Workflow snippet in the reference.
7. **Pay down** the baseline: pick the rule with the most entries, fix, regenerate the baseline,
   and show the before/after counts with `--baseline`. Raise the level one step at a time.

## Output

```
PHPStan level 5 (Larastan 3): 214 errors in 61 files
By rule:  92 missingType.return | 40 property.notFound | 31 argument.type | ...
Hot files: app/Http/Controllers/OrderController.php (23), app/Services/Checkout.php (17)
Plan:
  1. 40 property.notFound: add @property docs to Order and User (Larastan reads migrations; 3 are typos)
  2. Baseline the rest (174), commit, CI blocks new errors
  3. Next PRs: missingType.return (92), then argument.type (31)
```

## Notes

- Error identifiers (`method.notFound`) appear in JSON from PHPStan 1.11 and in every 2.x
  report; older reports are grouped by normalised message instead.
- Paths are shown relative to the detected project root (the folder above `app/`, `src/`, ...).
