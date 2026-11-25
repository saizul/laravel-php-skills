# Contributing to laravel-php-skills

Thank you for helping! New checks, new skills, fixes, fixtures from real-world code
(reduced and anonymised) and clearer docs are all welcome.

- [Ways to contribute](#ways-to-contribute)
- [Good first issues](#good-first-issues)
- [Development setup](#development-setup)
- [Repository layout](#repository-layout)
- [Write a new skill](#write-a-new-skill)
- [Quality bar](#quality-bar)
- [Pull request process](#pull-request-process)

## Ways to contribute

| Size | Idea |
| --- | --- |
| 10 minutes | Fix a typo, clarify a workflow step, add a FAQ entry |
| 30 minutes | Add a fixture for a false positive or false negative you hit in a real project |
| 1-2 hours | Add a check to an existing script (see below) |
| Half a day | Write a new skill from the template |

Comment on an issue before you start so nobody else picks the same one.

## Good first issues

Each of these is self-contained and touches one script and its test file.

1. **laravel-security-review: `Storage::download()` with request input.** Report `medium`
   for `Storage::download($request->...)` / `response()->download($request->...)` (path traversal).
2. **laravel-security-review: open redirects.** Report `medium` for `redirect($request->input(...))`
   and `redirect()->away($request->...)`.
3. **laravel-security-review: `routes/` awareness.** Skip the `authorization` finding when the
   matching route in `routes/*.php` has `->can(...)` or `middleware('can:...')`.
4. **eloquent-n-plus-one: Debugbar export.** Accept the JSON that Laravel Debugbar stores in
   `storage/debugbar/*.json` (`queries.statements[].sql`).
5. **eloquent-n-plus-one: `--min-time`.** Only report patterns whose total time exceeds N ms.
6. **laravel-migrations-safety: enum changes.** Flag `->enum(...)->change()` and
   `DB::statement('ALTER TABLE ... MODIFY ... ENUM')` as `high` on MySQL (table rebuild).
7. **laravel-migrations-safety: `--engine pgsql|mysql`.** Tailor messages (e.g. instant
   `ADD COLUMN` on MySQL 8, `CREATE INDEX CONCURRENTLY` on PostgreSQL).
8. **laravel-queues-horizon: Horizon `waits` check.** Warn when `waits` thresholds are missing
   for queues listed in supervisors.
9. **laravel-testing: Pest `->group()` report.** Add `--list-groups` that prints test counts
   per group and file.
10. **php-static-analysis: `--format markdown`.** Print the summary as a Markdown table for
    pull request comments.
11. **laravel-performance: N+1-prone accessors.** Report `info` for `$appends` attributes whose
    accessor touches a relation.
12. **laravel-deploy-vps: `--ci-build`.** Skip `npm` on the server and expect `public/build` in
    a release artifact; generate the matching GitHub Actions job.
13. **New skill: `livewire-review`** (see the roadmap in the README).

## Development setup

```bash
git clone https://github.com/saizul/laravel-php-skills.git
cd laravel-php-skills
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

python tools/validate_skills.py   # SKILL.md frontmatter, sections, links, marketplace listing
ruff check . && ruff format --check .
pytest
```

PHP is not needed: every script reads PHP as text and every test uses fixtures. The
deploy-generator tests run `bash -n`, and `shellcheck` when it is installed.

To try your changes in Claude Code, either copy a skill to `~/.claude/skills/` or add your
checkout as a local marketplace:

```bash
claude plugin marketplace add ./laravel-php-skills
claude plugin install laravel-php-skills@laravel-php-skills
```

For Codex, copy the skill folder to `~/.agents/skills/`.

## Repository layout

```
.claude-plugin/
  marketplace.json      marketplace + plugin entry listing every skill
  plugin.json           plugin manifest (name, version, author)
skills/<name>/
  SKILL.md              frontmatter + workflow (the part agents read)
  scripts/*.py          standalone helpers, Python 3.8+ stdlib only
  references/*.md       detail loaded on demand
templates/skill/        copy this to start a new skill
tests/
  test_<skill>.py       one test module per skill
  fixtures/<skill>/     PHP, Blade, .env, JSON and log inputs for those tests
tools/validate_skills.py
```

## Write a new skill

1. Open a "New skill proposal" issue first so we can agree on scope.
2. Copy the template:
   ```bash
   cp -r templates/skill skills/my-new-skill
   mv skills/my-new-skill/scripts/your_script.py skills/my-new-skill/scripts/my_check.py
   ```
3. Edit `SKILL.md`:
   - `name` equals the folder name: lowercase letters, digits, single hyphens, max 64 chars.
   - `description` (max 1024 chars) says **what** it does with concrete keywords and **when**
     to use it, starting the second part with "Use when ...". This text decides whether
     the agent picks the skill, so list the phrases Laravel developers actually type.
   - Required sections: `## When to use`, `## When not to use`, `## Workflow`, `## Output`.
   - Workflow steps are imperative and numbered, with exact commands, decision points and
     the point where the agent must ask before changing anything.
   - Keep it under 400 lines; move tables, patterns and long configs to `references/`.
4. Write the script: `argparse` with a useful `--help`, `--json` output, exit codes
   0 (ok) / 1 (findings) / 2 (error), read-only by default, no network calls.
5. Add `tests/test_my_new_skill.py` and fixtures in `tests/fixtures/my-new-skill/`. Cover
   a "bad" input, a "good" input that produces no findings, edge cases (comments, strings,
   Laravel 10 vs 11 layouts) and the CLI exit codes.
6. Add the skill to `.claude-plugin/marketplace.json` (`plugins[0].skills`), the README
   skills table, the table in `AGENTS.md`, the bug report dropdown and `CHANGELOG.md`.
7. Run the validator, ruff and pytest.

## Quality bar

- **Safety first.** A skill must never tell the agent to run migrations, delete data, retry
  jobs or change a server without showing the command and getting confirmation.
- **Deterministic where it matters.** If a step is "parse this and find X", write a script
  and test it rather than relying on the model reading 2,000 lines of logs.
- **Low false positives.** Respect comments and strings, skip `vendor/`, prefer `info`/`low`
  for checks that are often wrong, and document known false positives in the references.
- **Version aware.** Say which Laravel/PHP versions a rule or command applies to
  (e.g. `bootstrap/app.php` in Laravel 11+, `app/Http/Kernel.php` before).
- **No secrets.** Scripts never print `.env` values beyond documented non-secret keys and
  never print queue payloads.

## Pull request process

1. Fork, create a branch, make focused commits.
2. Make sure CI passes locally (validator, ruff, pytest).
3. Fill in the pull request template.
4. A maintainer reviews within a few days. Small, focused pull requests are merged fastest.

By contributing you agree that your contributions are licensed under the MIT License.
