## What does this pull request do?

<!-- One or two sentences. Link the issue: "Closes #123". -->

## Type

- [ ] New skill
- [ ] New check or option in an existing script
- [ ] Workflow / reference improvement
- [ ] Bug fix
- [ ] Repository tooling (validator, CI)

## Checklist

- [ ] `python tools/validate_skills.py` passes
- [ ] `ruff check . && ruff format --check .` passes
- [ ] `pytest` passes; new script behaviour has tests with fixtures in `tests/fixtures/<skill>/`
- [ ] Scripts use only the Python standard library (or POSIX shell), support `--help`, have a
      `--json` option where output is structured, and exit non-zero on findings
- [ ] Read-only / dry-run by default; any command that changes code, data or a server is shown
      to the user and needs confirmation in the SKILL.md workflow
- [ ] Fixtures use example.com and obviously fake values; no real keys, tokens, customer data
      or production logs
- [ ] New skills: listed in `.claude-plugin/marketplace.json`, the README skills table and CHANGELOG.md
