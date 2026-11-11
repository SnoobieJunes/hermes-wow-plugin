<!-- CHANGELOG.md contract (AGENTS.md → Documentation protocol):
     One entry per task with a user-visible effect, newest at the top:
     `<YYYY-MM-DD> — T-<###> — <what changed, user-visible effect>`
     Internal-only tasks get one line ending `(no user-visible change)`. -->

2026-11-11 — T-006 — Added Lua 5.1 syntax and bytecode global/member-access analysis (`luacheck.py`) and TOC lint (`tocfile.py`) ahead of `wow_check` (no user-visible change)
2026-11-11 — T-005 — Added the API index and the `wow_api` tool (plus `python -m wow_addon_forge api`): syncs WoW: Forever 1.60.1 documentation and resource mirrors through the embedded Lua 5.1 VM into a local cache, and answers `status`, `lookup`, `search` and `events` queries with signatures, restriction and secret flags, deprecation replacements and nearest-name suggestions
2026-11-11 — T-040 — Re-phased the plan: the plugin is finished and gated first, then Guildhall is built only through the plugin's tools; the reusable Lua building blocks now live in the plugin (no user-visible change)
2026-11-11 — T-003 — Walking skeleton: Hermes loads the plugin with its first tool, `wow_env`, which reports the WoW installs on the machine — flavors, client version, Interface number, account count and installed addons — as JSON (also `python -m wow_addon_forge env`, read-only); the Guildhall addon has its TOC and first Lua file, which the test suite runs in the Lua 5.1 VM. Not yet run in the live client
2026-11-11 — T-002 — Added the toolchain and the gate: uv, pytest with a coverage floor, ruff, mypy, Hermes plugin validation, CI, and an embedded Lua 5.1 VM with a syntax check (no user-visible change)
2026-11-11 — T-001 — Wrote the normative plan, the plugin spec, the Guildhall spec and the in-game checklist; seeded the backlog T-002..T-038 (no user-visible change)
2026-11-11 — T-000 — Scaffolded the repository, the process files and the task board (no user-visible change)
