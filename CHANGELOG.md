# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `laravel-migrations-safety`: `drop-index` check for `dropIndex`, `dropPrimary`, `dropFullText`
  and `dropSpatialIndex` (low, medium on `--big-tables`), `dropUnique` (medium) and
  `dropForeign` (low).

### Fixed

- `laravel-migrations-safety`: `dropConstrainedForeignId()`, `dropConstrainedForeignIdFor()`
  and `dropForeignIdFor()` drop the column too and are now reported as `drop-column` (high).

## [0.1.0] - 2026-11-25

### Added

- `laravel-security-review`: scanner for mass assignment, raw SQL with interpolation,
  unescaped Blade output, CSRF exceptions, debug settings, missing controller authorization,
  dangerous calls on request input, disabled TLS verification and credentialed wildcard CORS.
- `eloquent-n-plus-one`: N+1 detector for query logs, `DB::getQueryLog()` dumps and Telescope
  exports with eager-loading suggestions and lazy-loading violation counts.
- `laravel-migrations-safety`: migration checker for destructive, locking and non-reversible
  operations, with expand/contract patterns.
- `laravel-queues-horizon`: queue/Horizon/Supervisor configuration check (timeout chain) and
  failed jobs triage by job class and cause.
- `laravel-testing`: Pest/PHPUnit patterns, factories and fakes, plus a test-suite smell scanner.
- `php-static-analysis`: PHPStan/Larastan setup and baseline strategy, PHPStan JSON and
  baseline summariser with run comparison.
- `laravel-performance`: production audit (env() outside config, caches, drivers, dev packages,
  OPcache/JIT/Xdebug) and checklists for PHP-FPM and Octane.
- `laravel-deploy-vps`: generator for zero-downtime deploy and rollback scripts, Nginx,
  Supervisor, scheduler cron and sudoers files.
- Claude Code plugin marketplace manifest, `tools/validate_skills.py`, CI and release workflows.

[Unreleased]: https://github.com/saizul/laravel-php-skills/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/saizul/laravel-php-skills/releases/tag/v0.1.0
