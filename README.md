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

Status (2026-11-11, T-012): Hermes loads the plugin and eight tools work: `wow_env`
(install and addon detection), `wow_api` (cached WoW: Forever 1.60.1 API index),
`wow_check` (six-stage static and headless addon verification), `wow_test`
(isolated multi-client headless Lua 5.1 test runner), `wow_errors` (reads
ForgeProbe's SavedVariables), `wow_savedvars` (reads any addon's SavedVariables as
JSON), `wow_install` (copies or links an addon into `Interface/AddOns` after
`wow_check` passes, backing up a replaced folder outside the game), and `wow_bridge`
(pulls an outbox past a cursor, or pushes `Inbox.lua` for an addon that declares
`## X-Forge-Bridge: 1`). The `core` building block (`src/wow_addon_forge/blocks/core/`)
is the namespace, dispatcher, clock, store, safe codec and slash command a scaffolded
addon stands on, plus the `log` block (record set and order-independent reducers). `addons/ForgeProbe`
ships with the plugin and passes `wow_check`; it has not been run in the live client
(`docs/INGAME-CHECKLIST.md` section A is still `NOT RUN`). Secret-value simulation in
the headless runtime arrives in T-034; until it lands, `issecretvalue` returns `false`
in the stub and the static `restricted-api` rule in `wow_check` is the only defence
against unguarded secret returns. Guildhall is one skeleton file that passes
`wow_check`; it has not been loaded in the live game client. Everything else below is
planned, and nothing is claimed to work until its task is closed in `TASKS.md`.

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
uv sync --all-groups                                               # install
uv run python -m wow_addon_forge --version                        # prints: wow-addon-forge 0.1.0
uv run python -m wow_addon_forge env                              # JSON: installs, flavors, Interface number, addons
uv run python -m wow_addon_forge api sync --flavor forever        # download forever API mirrors and cache the index
uv run python -m wow_addon_forge api status                       # JSON: cached build, age, entry counts
uv run python -m wow_addon_forge api lookup C_Item.GetItemInfo    # JSON: signature, restriction/secret flags
uv run pytest -x -q                                               # fast tests
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

`api` is the command-line twin of the `wow_api` tool (`sync`, `status`, `lookup <name>`,
`search <query>`, `events [query]`). `api sync` fetches the `forever` branches of
`Gethe/wow-ui-source` and `Ketho/BlizzardInterfaceResources` over HTTPS from
`raw.githubusercontent.com`, executes the Lua tables in the sandboxed Lua 5.1 VM, and
writes the index atomically under `$HERMES_HOME/cache/wow-addon-forge/api-index` (or
`~/.hermes/cache/wow-addon-forge/api-index`). Reading a local `BlizzardInterfaceCode`
export (`--source export`) is deferred to T-044 and returns an explicit
`export-not-supported` error.

## What the plugin touches on your machine

Planned, per `docs/SPEC-PLUGIN.md` §13; becomes a tested statement in T-014.
Today the shipping tools are `wow_env` (reads `.build.info`, `.flavor.info`, addon TOC
files under `Interface/AddOns`, and counts folders under `WTF/Account` without reporting
account names), `wow_api` (fetches the public GitHub documentation mirrors on `sync`
and writes only the API index cache under `~/.hermes/cache/wow-addon-forge/api-index`),
`wow_check` / `wow_test` (read the target addon folder and the cached API index and
write nothing), `wow_errors` (reads `WTF/Account/**/SavedVariables/ForgeProbe.lua`
only, writes nothing, and never prints an account folder name), `wow_savedvars`
(reads one addon's SavedVariables the same way, still without printing an account
name), and `wow_install` (writes only `<install>/<flavor>/Interface/AddOns/<name>`
and a backup under `~/.hermes/cache/wow-addon-forge/backups`, never inside the game
folder). `wow_errors` and `wow_savedvars` have no command-line twin yet. `wow_bridge`
also has `python -m wow_addon_forge bridge pull --format discord`, which prints one
line per new outbox record and nothing when there is none. Latency in each direction
is one `/reload` or logout. The plugin holds no Discord credential.

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
