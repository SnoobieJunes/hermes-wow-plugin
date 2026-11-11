# TASKS.md — hermes-wow-plugin work queue
<!-- One queue. New DONE entries at the top of Done. Tasks without observable
     acceptance criteria are not pickable — sharpen them first. -->

## Now
- [ ] T-001 — Write the normative plan, both product specs, the living docs, and the phase-1 backlog
      Why: The architecture, the two product specs and the task breakdown must exist and agree before any product code.
      Accept: `docs/PLAN.md`, `docs/SPEC-PLUGIN.md`, `docs/SPEC-GUILDHALL.md` and `docs/INGAME-CHECKLIST.md` are written and dated; `README.md` is expanded; `CHANGELOG.md` has entries for T-000 and T-001; the step-2 gate passes (each of `grep -c "Why:" TASKS.md`, `"Accept:"`, `"Touches:"`, `"Depends:"`, `"Gated:"` is at least `grep -c '^- \[ \]' TASKS.md`).
      Touches: `docs/PLAN.md`, `docs/SPEC-PLUGIN.md`, `docs/SPEC-GUILDHALL.md`, `docs/INGAME-CHECKLIST.md`, `README.md`, `CHANGELOG.md`, `TASKS.md`   Depends: T-000   Gated: none
- [ ] T-002 — Stand up the toolchain, the mechanical gates, and a real smoke test
      Why: Every later task needs one automated gate: tests, lint, format, types, coverage, and Hermes plugin validation.
      Accept: `uv sync --all-groups`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` and `hermes plugins validate .` all pass; the smoke test runs a Lua chunk in the embedded Lua 5.1 VM and imports the package; every `TBD step 3` marker in `AGENTS.md` and `LOOP.md` is replaced; the AGENTS.md layout table gains the `plugin.yaml`, `__init__.py` row; a cold clone passes the full gate.
      Touches: `pyproject.toml`, `.python-version`, `uv.lock`, `plugin.yaml`, `__init__.py`, `src/wow_addon_forge/__init__.py`, `tests/test_smoke.py`, `.github/workflows/ci.yml`, `AGENTS.md`, `LOOP.md`, `README.md`, `CHANGELOG.md`, `TASKS.md`   Depends: T-001   Gated: none
- [ ] T-003 — Build the walking skeleton: the plugin loads, one real tool answers, one addon file runs headless
      Why: Prove the architecture end to end before building on it: Hermes loads the plugin, a tool reads the real install layout through an injected filesystem, and addon Lua executes in Lua 5.1.
      Accept: `hermes plugins validate .` passes with one declared tool `wow_env`; a unit test feeds `wow_env` a fake install tree and gets flavor `forever`, Interface `16001` and the addon list back as JSON; a test loads `addons/Guildhall/Guildhall.toc` and its first Lua file in the Lua 5.1 VM with no error; the full gate is green.
      Touches: `plugin.yaml`, `__init__.py`, `src/wow_addon_forge/`, `addons/Guildhall/`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`   Depends: T-002   Gated: none

## Later
- [ ] T-004 — Run standing goose-deuce sweep #1
      Why: Keep `docs/PLAN.md`, `TASKS.md`, `AGENTS.md` and `goose-deuce.md` aligned at the 10-task / weekly cadence.
      Accept: Every pending `Plan:` adjustment is folded into `docs/PLAN.md`; no orphaned `[deferred]` or `[tech-debt]` entry; the stranger test passes.
      Touches: `docs/PLAN.md`, `TASKS.md`, `goose-deuce.md`, `AGENTS.md`, `CHANGELOG.md`   Depends: T-000   Gated: cadence

## Blocked

## Dropped

## Done
- [x] T-000 — Scaffold hermes-wow-plugin from templates (2026-11-11, this commit)
      Why: Wire the repository layout, the process law, the deviation log and the task board before any plan or code.
      Accept: The step-1 gate passes (no `⟨` outside `TBD step 3`, no `WORKED-EXAMPLE`, every layout path exists, `CLAUDE.md -> AGENTS.md`).
      Touches: `AGENTS.md`, `CLAUDE.md`, `goose-deuce.md`, `LOOP.md`, `HERMES-OVERLAY.md`, `TASKS.md`, `docs/`, `CHANGELOG.md`, `.gitignore`, `README.md`   Depends: none   Gated: none
