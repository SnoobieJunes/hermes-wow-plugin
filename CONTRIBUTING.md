# Contributing to hermes-wow-plugin

<!-- [2026-11-11 T-051] Adapted from the Eldr repository's contributor setup;
     its CLA/DCO apparatus is deliberately not mirrored (this repo is MIT,
     single-license). AGENTS.md is the full operating manual; this file is
     the front door. -->

This repository holds `wow-addon-forge` (a Hermes Agent plugin that builds
World of Warcraft: Forever addons) and `Guildhall`, the guild addon built with
it. Contributions are welcome. The process below is the same one the project's
own work follows — it is written down in [AGENTS.md](AGENTS.md), and that file
wins wherever the two differ.

## Ground rules

- **One task, one commit.** Work is queued in [TASKS.md](TASKS.md). Pick (or
  file) a task with observable acceptance criteria, finish it completely, and
  land it as one commit whose body attests what actually ran. The format is
  specified in AGENTS.md → Version control.
- **Never write addon code from memory of another WoW era.** WoW: Forever is
  client 1.60.1 (`## Interface: 16001`) on the retail 12.x API with secret
  values. Look every function and event up first:
  `uv run python -m wow_addon_forge api lookup <Name>`.
- **All Lua runs in the embedded Lua 5.1 VM** (`lupa.lua51`). The system
  `lua`/`luac` are 5.5 and prove nothing about the game.
- **Headless-green is not in-game-true.** Only a run in the live client,
  recorded in [docs/INGAME-CHECKLIST.md](docs/INGAME-CHECKLIST.md), supports a
  claim about the game. Label everything else headless or untested.
- **Deviations are logged, not hidden.** Anything that departs from the plan
  or a task gets an entry in [goose-deuce.md](goose-deuce.md) in the same
  commit. Its header owns the rules.
- **No secrets, ever.** Credentials live in the OS keychain or Hermes `.env`;
  the repo stores references only. `gitleaks` runs in CI over full history.

## Building and testing

```bash
uv sync --all-groups                                  # bootstrap
uv run python -m wow_addon_forge --version            # smoke check
uv run pytest -x -q                                   # inner loop
# The full pre-commit gate (all of it, green, before any commit):
uv run pytest --cov=src/wow_addon_forge --cov-fail-under=85 \
  && uv run ruff check . && uv run ruff format --check . \
  && uv run mypy src && hermes plugins validate .
```

Addon changes additionally quote a `wow_check` verdict of `pass` and the
`wow_test` result for `addons/Guildhall` in the commit body — Guildhall is the
plugin's acceptance test and is built only through the plugin's own tools
(AGENTS.md, LOOP.md rule 10).

## Comments

Every code change carries dated, educational comments —
`[YYYY-MM-DD T-###] <what and why>` — asserting only behaviour a test or a run
has actually exercised. The standard lives in AGENTS.md → Comment standard; a
stale comment is a bug.

## Pull requests

Fork, branch from `main`, one task per PR. The PR template asks for the task
ID, the gate output, and an honest split between what was proven by running it
and what is inferred. Nothing merges red.

## Licensing of contributions

This project is MIT-licensed ([LICENSE](LICENSE)); by contributing you agree
your contribution is licensed under the same terms. There is no CLA.
Questions of conduct follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md);
vulnerabilities follow [SECURITY.md](SECURITY.md), never a public issue.
