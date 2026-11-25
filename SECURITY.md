# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## What counts as a vulnerability

These skills are run by AI agents on real codebases and servers, so unsafe guidance is
treated like a code vulnerability:

- A script that changes files outside its documented output (`gen_deploy.py --out`), modifies
  the project it scans, or runs a command or network call not documented
- A script that prints secrets (`.env` values other than the documented non-secret keys,
  `APP_KEY`, tokens, queue payload data)
- A `SKILL.md` workflow that tells the agent to run a destructive command (`migrate:fresh`,
  `db:wipe`, `queue:flush`, deletes, service restarts) without asking the user first
- Command injection: crafted PHP, Blade, log or config files that make a script execute
  something, or arguments that inject shell into generated deploy files
- Generated files (deploy scripts, sudoers, Nginx, Supervisor) that are insecure by default,
  e.g. broad sudo rights or world-readable `.env`

A check that misses a vulnerability (false negative) is a normal bug: please open an issue.

## Reporting

Please **do not** open a public issue. Use
[GitHub private vulnerability reporting](https://github.com/saizul/laravel-php-skills/security/advisories/new)
with the affected skill, version, impact and steps to reproduce. Redact domains, keys and
any secrets from examples.

You will get an answer within 5 working days. Fixes are released as soon as possible and
credited in the changelog unless you prefer otherwise.
