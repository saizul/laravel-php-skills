# laravel-php-skills

[![CI](https://github.com/saizul/laravel-php-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/saizul/laravel-php-skills/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/saizul/laravel-php-skills?sort=semver)](https://github.com/saizul/laravel-php-skills/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/saizul/laravel-php-skills?style=social)](https://github.com/saizul/laravel-php-skills/stargazers)

**Agent Skills that make Claude Code and Codex useful on real Laravel apps: find the security hole, the N+1, the migration that locks prod, and ship it safely.**

Eight skills for the work every Laravel team repeats: security review, Eloquent N+1 hunting,
migration safety, queues and Horizon, testing with Pest or PHPUnit, PHPStan/Larastan adoption,
production performance and zero-downtime deploys to a VPS. Each skill is a step-by-step
workflow plus a tested, standard-library-only Python script that reads your PHP, Blade,
config and log files as text, so the agent gets exact answers instead of guessing.

- **Works without PHP installed.** Scripts analyse source and exports as text, so they run in
  CI, on a laptop or inside the agent sandbox.
- **Read-only by default.** Scanners report; the deploy generator only writes files to a
  folder you choose. Every command that changes code, data or a server is shown to you first.
- **Tested.** 120+ tests with PHP, Blade, `.env`, Telescope and PHPStan fixtures, on Python 3.11-3.13 in CI.
- **Current Laravel.** Laravel 11/12 structure (`bootstrap/app.php`, `routes/console.php`,
  `CACHE_STORE`), with notes for Laravel 9/10.

## Skills

| Skill | What it does | Try asking |
| --- | --- | --- |
| [laravel-security-review](skills/laravel-security-review/SKILL.md) | Scans for `$guarded = []`, `create($request->all())`, `whereRaw`/`DB::raw` with interpolation, `{!! !!}`, wildcard CSRF exceptions, `APP_DEBUG=true`, controllers without authorization, `unserialize` on input, disabled TLS verification, credentialed `*` CORS | "Do a security review of this Laravel app before go-live" |
| [eloquent-n-plus-one](skills/eloquent-n-plus-one/SKILL.md) | Parses query logs, `DB::getQueryLog()` dumps or Telescope exports, finds queries repeated per request and suggests `with()`, `withCount()`, `withExists()`; reports `preventLazyLoading` violations | "The /orders page runs 300 queries, fix it" |
| [laravel-migrations-safety](skills/laravel-migrations-safety/SKILL.md) | Flags `dropColumn`, `renameColumn`, `->change()` on big tables, NOT NULL without default, unique/foreign keys on existing tables, dropped indexes and constraints, data backfills, missing `down()`; plans expand/contract | "Is this migration safe to run on production?" |
| [laravel-queues-horizon](skills/laravel-queues-horizon/SKILL.md) | Checks the timeout chain (job / worker / `retry_after` / `stopwaitsecs`), Supervisor and Horizon config; triages `failed_jobs` by job and cause with retry/forget commands | "Jobs run twice and we have 3,000 failed jobs" |
| [laravel-testing](skills/laravel-testing/SKILL.md) | Pest/PHPUnit patterns, factories, fakes, Sanctum; scans the suite for `->only()`, `dd()`, `sleep()`, missing `RefreshDatabase`, real HTTP, tests without assertions | "Write feature tests for PostController" |
| [php-static-analysis](skills/php-static-analysis/SKILL.md) | PHPStan + Larastan setup, level and baseline strategy; summarises PHPStan JSON by rule and file, summarises baselines, compares runs (new vs fixed) | "Add Larastan and tell me where the 800 errors come from" |
| [laravel-performance](skills/laravel-performance/SKILL.md) | Audits `env()` outside config, `optimize` caches, debug packages in `require`, drivers, OPcache/JIT/Xdebug from `php.ini` or `php -i`, `::all()` patterns; FPM sizing and Octane notes | "Our Laravel site has 600 ms TTFB, what should we fix first?" |
| [laravel-deploy-vps](skills/laravel-deploy-vps/SKILL.md) | Generates a releases/symlink `deploy.sh`, `rollback.sh`, Nginx block, Supervisor (workers or Horizon), scheduler cron and sudoers rule | "Set up zero-downtime deploys to my Hetzner VPS" |

## Install

### Claude Code: plugin marketplace (recommended)

```text
/plugin marketplace add saizul/laravel-php-skills
/plugin install laravel-php-skills@laravel-php-skills
```

Or from your shell:

```bash
claude plugin marketplace add saizul/laravel-php-skills
claude plugin install laravel-php-skills@laravel-php-skills
```

Plugin skills are namespaced, e.g. `/laravel-php-skills:eloquent-n-plus-one`. Claude also
picks them up automatically when your request matches a skill's description. Update later
with `/plugin marketplace update laravel-php-skills`.

### Claude Code: copy the skills

```bash
git clone https://github.com/saizul/laravel-php-skills.git
# all projects (personal skills)
mkdir -p ~/.claude/skills && cp -r laravel-php-skills/skills/* ~/.claude/skills/
# or only one project (commit it so the whole team gets it)
mkdir -p .claude/skills && cp -r laravel-php-skills/skills/laravel-security-review .claude/skills/
```

Each release also has one zip per skill and an all-skills zip under
[Releases](https://github.com/saizul/laravel-php-skills/releases).

### Codex CLI

Codex reads skills from `~/.agents/skills` (all repositories) and `.agents/skills` in a
repository (from the current directory up to the repository root):

```bash
git clone https://github.com/saizul/laravel-php-skills.git
mkdir -p ~/.agents/skills && cp -r laravel-php-skills/skills/* ~/.agents/skills/
# or per project
mkdir -p .agents/skills && cp -r laravel-php-skills/skills/laravel-testing .agents/skills/
```

Codex also ships a `$skill-installer` skill that can install skills from a GitHub repository;
ask it to install from `saizul/laravel-php-skills`. Skill locations and the installer are
described in the [Codex skills documentation](https://developers.openai.com/codex/skills);
check it if your Codex version behaves differently. [AGENTS.md](AGENTS.md) explains how
Codex and other agents should use these skills.

### Any other agent

The skills follow the open [Agent Skills format](https://agentskills.io/specification):
a folder with `SKILL.md` (YAML frontmatter + instructions), `scripts/` and `references/`.
Point your agent at the folder, or run the scripts yourself; every script has `--help`.

## Usage examples

```text
> Review app/ for security problems; we go live on Friday.
  (Runs laravel_security_scan.py, checks routes/ for can: middleware before reporting
   missing authorization, then proposes FormRequest + policy fixes one finding at a time.)

> Here is a Telescope export of the dashboard request. Why is it slow?
  (find_n_plus_one.py: "x48 select * from users where id = ?" at resources/views/dashboard.blade.php:31
   -> Order::with('customer'); "x48 count(*) from items" -> withCount('items'). Re-measures after.)

> I need to rename users.name to full_name without downtime.
  (migration_safety.py flags the rename; the skill writes three migrations and a backfill job.)
```

Run the scripts directly too:

```bash
python3 skills/laravel-security-review/scripts/laravel_security_scan.py /path/to/app --fail-on high
python3 skills/laravel-migrations-safety/scripts/migration_safety.py . --big-tables users,orders
python3 skills/php-static-analysis/scripts/phpstan_summary.py phpstan.json --baseline phpstan-baseline.neon
python3 skills/laravel-deploy-vps/scripts/gen_deploy.py --app shop --domain shop.example.com \
  --repo git@github.com:acme/shop.git --queue horizon --out deploy-out
```

The scanners exit 1 on findings, so they also work as CI gates.

## How skills work

At startup the agent loads only each skill's `name` and `description` (about 100 tokens
each). When your request matches a description, it reads that skill's `SKILL.md`: the
workflow, decision points and safety rules. Longer material lives in `references/` and is
read only when a step needs it. Scripts run as normal commands, so their output is exact
and repeatable.

```
skills/<skill-name>/
  SKILL.md          frontmatter (name, description) + workflow
  scripts/          standalone Python 3 helpers (stdlib only, --help, --json)
  references/       checklists, patterns, known-good configs
```

## FAQ

**Do I need PHP or a running app?**
No for the scripts: they read files as text. Some workflow steps use your tools when you have
them (`php artisan test`, `vendor/bin/phpstan`, `composer audit`), and the skill says so.

**Will the agent change my code or server on its own?**
The skills tell it not to. Scanners are read-only, and the deploy generator only writes to the
`--out` folder. Fixes are proposed as diffs, and server commands are shown for your
confirmation. Your agent's own permission settings still apply.

**Does anything leave my machine?**
No script makes network calls or sends telemetry. The generated `deploy.sh` calls your own
health URL when you run it on your server.

**Is this a replacement for PHPStan, Larastan or Enlightn?**
No. The security and performance scanners catch common, high-signal Laravel mistakes quickly
and explain them; PHPStan/Larastan do full type analysis, and the `php-static-analysis` skill
helps you adopt them.

**Which versions?**
Laravel 10-12 first, with notes for 9. PHP 8.2+. Pest 2/3 and PHPUnit 10/11. Horizon 5.
Python 3.8+ for the scripts.

**False positives?**
Text scanning has limits (authorization done in routes, sanitised HTML in `{!! !!}`). The
workflows tell the agent to confirm each finding before reporting it, and you can silence a
line with `// security-scan: ignore`.

## Roadmap

Ideas for new skills (great first contributions; see [CONTRIBUTING.md](CONTRIBUTING.md)):

- `livewire-review` - public property exposure, missing `#[Locked]`, authorization in actions
- `laravel-api-resources` - consistent API Resources, pagination meta, versioning, OpenAPI
- `filament-admin-review` - policies on resources, gated panels, heavy table queries
- `laravel-upgrade-helper` - checklist and code scanner for 10 -> 11 -> 12 upgrades
- `composer-dependency-audit` - parse `composer.lock` for abandoned/outdated packages
- `laravel-caching-strategy` - cache keys, tags, `Cache::flexible`, invalidation patterns
- `pest-migration` - convert PHPUnit classes to Pest files
- `laravel-logging-observability` - channels, context, Pulse, structured logs

## Contributing

Contributions are welcome: new checks, new skills, fixes and better docs. Read
[CONTRIBUTING.md](CONTRIBUTING.md) for the skill template, the quality bar and
how to run the validator and tests:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python tools/validate_skills.py && ruff check . && ruff format --check . && pytest
```

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) and report security issues
privately as described in [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) (c) Saizul Amin
