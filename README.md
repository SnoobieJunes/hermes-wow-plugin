# hermes-wow-plugin

Two things in one repository:

- **`wow-addon-forge`** — a [Hermes Agent](https://github.com/NousResearch/hermes-agent)
  plugin that builds World of Warcraft: Forever addons that load and run. It
  checks every API call against the real client build, loads the addon in a
  strict stub of the game inside a Lua 5.1 VM, installs it with a backup, and
  reads in-game Lua errors back so the agent can fix them.
- **Guildhall** — a guild-management addon built with the plugin: a board,
  events and sign-ups, Marks (an internal currency earned automatically by
  playing together), work orders, a roster, a shared history, guild quests, and
  a mirror to Discord.

For WoW players and guild officers who are not programmers.

Status (2026-11-11, T-003): walking skeleton. Hermes loads the plugin and one tool
works: `wow_env`, which reports the WoW installs on this machine. Guildhall is one
file that the test suite runs in a Lua 5.1 VM; it has not been loaded in the live
game client. Everything else below is planned, and nothing is claimed to work
until its task is closed in `TASKS.md`.

## Why a plugin and not a prompt

WoW: Forever runs the retail 12.1.5 API with addon restrictions, not the Classic
API most examples are written for. `GetItemInfo`, `SendChatMessage` and
`ReloadUI` are gone from the client's C API; the combat log is closed to addons.
A model writing from memory produces addons that fail to load. The plugin
executes the checks instead of describing them.

## Documents

| File | What it is |
|---|---|
| `docs/PLAN.md` | The normative plan: goal, ground truth, architecture, phases, non-goals |
| `docs/SPEC-PLUGIN.md` | The plugin: nine tools, the verification pipeline, the API index, the headless runtime, the bridge contract |
| `docs/SPEC-GUILDHALL.md` | The addon: record log, sync protocol, trust model, Marks, every module |
| `docs/INGAME-CHECKLIST.md` | Live-client acceptance steps and their recorded results |
| `AGENTS.md` | The process every agent session follows |
| `TASKS.md` | The single work queue |

## Install, run, test

For development (needs [uv](https://docs.astral.sh/uv/); Hermes Agent for the last line):

```bash
uv sync --all-groups                         # install
uv run python -m wow_addon_forge --version   # prints: wow-addon-forge 0.1.0
uv run python -m wow_addon_forge env         # JSON: installs, flavors, Interface number, addons
uv run pytest -x -q                          # fast tests
uv run pytest --cov=src/wow_addon_forge --cov-fail-under=85 && uv run ruff check . \
  && uv run ruff format --check . && uv run mypy src && hermes plugins validate .   # the full gate
```

Lua code is checked and tested in an embedded Lua 5.1 VM (`lupa`), not the system `lua`.
Install instructions for users arrive in T-014.

`env` is the command-line twin of the `wow_env` tool. It only reads. It looks in
`/Applications/World of Warcraft` and `C:\Program Files (x86)\World of Warcraft`;
pass `--root "/path/to/World of Warcraft"` for any other folder. With no install
found it prints a `no-install` error as JSON and exits with status 1. The Interface
number it reports is derived from the client version (1.60.1 gives 16001) and the
output says so in `interface_source`.

## What the plugin touches on your machine

Planned, per `docs/SPEC-PLUGIN.md` §13; becomes a tested statement in T-014.
Today the only tool is `wow_env`, and it only reads: `.build.info`, each flavor
folder's `.flavor.info`, the TOC files under `Interface/AddOns`, and the folder
names under `WTF/Account`, which it counts and never reports.

- Network: downloads of the public API documentation mirrors, only when you run
  an API sync.
- Reads: your WoW install (`Interface/AddOns`, SavedVariables under `WTF`).
- Writes: an addon folder when you install one, and `Inbox.lua` when you push
  from the bridge.
- Never: input automation, game memory, gold-bid loot systems, telemetry.

## License

MIT — the file arrives in T-014.

World of Warcraft is a trademark of Blizzard Entertainment. This project is not
affiliated with or endorsed by Blizzard.
