# AGENTS.md

Guidance for Codex CLI and other coding agents that use or work on this repository.

## Using the skills

The skills live in `skills/<name>/SKILL.md` and follow the Agent Skills format. Codex
discovers them when they are copied to `~/.agents/skills/` or `.agents/skills/` (see
README "Install"). If you are reading this file inside the repository instead:

1. Pick the skill whose `description` matches the user's request:

   | Request is about | Skill |
   | --- | --- |
   | security review, XSS, SQL injection, CSRF, mass assignment, policies | `laravel-security-review` |
   | too many queries, N+1, eager loading, lazy loading, Telescope/Debugbar | `eloquent-n-plus-one` |
   | migrations, renaming/dropping columns, indexes on big tables | `laravel-migrations-safety` |
   | queue workers, Horizon, Supervisor, failed jobs, retry_after | `laravel-queues-horizon` |
   | writing or fixing Pest/PHPUnit tests, factories, fakes | `laravel-testing` |
   | PHPStan, Larastan, levels, baselines | `php-static-analysis` |
   | slow app, caching, OPcache, PHP-FPM, Octane | `laravel-performance` |
   | deploying to a VPS, Nginx, Supervisor, scheduler cron, rollback | `laravel-deploy-vps` |

2. Read that `SKILL.md` completely and follow its Workflow section in order.
3. Paths such as `scripts/x.py` and `references/y.md` are relative to the skill folder.
   `${CLAUDE_SKILL_DIR}` in the text means that folder; Codex does not expand it.
4. Read files in `references/` only when a workflow step points to them.

## Safety rules (apply to every skill)

- Run only the read-only commands and scripts a workflow lists without asking.
- Propose code changes as diffs and apply them after the user agrees; run the test suite after.
- Before any command that changes data or a server (`migrate`, `migrate:fresh`, `queue:retry`,
  `queue:flush`, `composer require`, package installs, edits under `/etc`, service reloads):
  show the exact command, explain the impact, and wait for explicit confirmation.
- Never run destructive database commands (`migrate:fresh`, `db:wipe`, `migrate:rollback`)
  against shared or production databases.
- Never print or paste secrets (`.env` values, `APP_KEY`, tokens, queue payloads). The scripts
  read only the non-secret `.env` keys they need; keep it that way when summarising.
- Never connect to hosts the user did not name.

## Working on this repository

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python tools/validate_skills.py   # frontmatter, sections, links, marketplace listing
ruff check . && ruff format --check .
pytest
```

- Scripts: Python 3.8+ standard library only, `#!/usr/bin/env python3`, `argparse` with
  `--help`, `--json` where output is structured, exit 0/1/2 (ok / findings / error).
- Every script needs tests in `tests/test_<skill_with_underscores>.py` with fixtures in
  `tests/fixtures/<skill>/` (PHP, Blade, `.env`, JSON exports). Use `example.com`, fake
  values, and never commit real keys or tokens.
- Keep each `SKILL.md` under 400 lines; move detail to `references/`.
- A new skill must be added to `.claude-plugin/marketplace.json` (`plugins[0].skills`), the
  README table, the table above and `CHANGELOG.md`. The validator enforces the manifest.
