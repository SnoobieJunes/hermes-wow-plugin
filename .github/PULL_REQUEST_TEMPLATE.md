## Summary

<!-- What and why, briefly. Name the TASKS.md task: T-###. -->

## Task surface

- Task: <!-- e.g. "T-023 (SPEC-GUILDHALL §10)" — or "none, filed T-###" -->
- [ ] Acceptance criteria from the task are quoted or linked above
- [ ] Anything that deviated from the task or the plan has a `goose-deuce.md` entry in this PR
- [ ] `TASKS.md` and `CHANGELOG.md` updated in this PR (one task, one commit)

## Test evidence

<!-- Commands you actually ran and their final summary lines. "It compiles"
     is not evidence; nothing merges red. -->

- [ ] Full gate green: `pytest --cov --cov-fail-under=85`, `ruff check`, `ruff format --check`, `mypy src`, `hermes plugins validate .`
- [ ] Addon touched → `wow_check` verdict `pass` and `wow_test` result quoted
- [ ] Any in-game claim is recorded in `docs/INGAME-CHECKLIST.md` (a headless pass is not an in-game pass)

## Proven vs inferred

<!-- What you observed by running it, on which platform — and what is only
     inferred, compile-checked, or untested. -->
