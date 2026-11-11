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

Status (2026-11-11, T-011): Hermes loads the plugin and nine tools work: `wow_env`
(install and addon detection), `wow_api` (cached WoW: Forever 1.60.1 API index),
`wow_check` (six-stage static and headless addon verification), `wow_test`
(isolated multi-client headless Lua 5.1 test runner), `wow_errors` (reads
ForgeProbe's SavedVariables), `wow_savedvars` (reads any addon's SavedVariables as
JSON), `wow_install` (copies or links an addon into `Interface/AddOns` after
`wow_check` passes, backing up a replaced folder outside the game), and `wow_bridge`
(pulls an outbox past a cursor, or pushes `Inbox.lua` for an addon that declares
`## X-Forge-Bridge: 1`), and `wow_new` (scaffolds an addon from those blocks into an empty folder). `/wow status` and `hermes wow status` print the install, build, and index. Set `wow_root` when the game is not in a default folder; `wow_env` then searches only that folder. The `core` building block (`src/wow_addon_forge/blocks/core/`)
is the namespace, dispatcher, clock, store, safe codec and slash command a scaffolded
addon stands on, plus the `log` block (record set and order-independent reducers), the `sync` block (chunked, throttled guild exchange), and the `trust` block (roster rank gates which records count), the `window` block (one lazy Classic window), and the `bridge` block (outbox and inbox for `wow_bridge`). `addons/ForgeProbe`
ships with the plugin and passes `wow_check`; it has not been run in the live client
(`docs/INGAME-CHECKLIST.md` section A is still `NOT RUN`). Secret-value simulation in
the headless runtime is in. A documented secret return is opaque while a restriction
is active; arithmetic and concatenation on it are `secret-value` findings, and a
widget setter may hold the value. `issecretvalue` is true for that value. The static
`restricted-api` rule still flags an unguarded secret-returning call. Guildhall is one skeleton file that passes
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

## Install

Requires [Hermes Agent](https://github.com/NousResearch/hermes-agent). The plugin declares one Python dependency, `lupa`, which Hermes installs only with your consent.

From a checkout, for development:

```bash
uv sync --all-groups
hermes plugins validate . --install-deps
```

A linked checkout is enabled with `hermes plugins enable wow-addon-forge`. Catalog install (`hermes plugins install wow-addon-forge`) waits until the plugin is published. Hermes Desktop shows an Addon Forge pane (`desktop/plugin.js`) whose buttons call `dashboard/plugin_api.py`: status, addons, check, install, and bridge pull.

`env` is the command-line twin of the `wow_env` tool. It only reads. It looks in
`/Applications/World of Warcraft` and `C:\Program Files (x86)\World of Warcraft`,
or only in `wow_root` when that setting is set. Pass `--root` for any other folder.
With no install found it prints a `no-install` error as JSON and exits with status 1.
The Interface number it reports is derived from the client version (1.60.1 gives 16001)
and the output says so in `interface_source`.

`api` is the command-line twin of the `wow_api` tool (`sync`, `status`, `lookup <name>`,
`search <query>`, `events [query]`). `api sync` (default `--source auto`) first looks
for a local client export — `<flavor>/BlizzardInterfaceCode`, written by the in-game
console command `ExportInterfaceFiles code` — under the same installs `env` searches;
when one is present it is indexed with no network call, and the result's `note` names
the export folder. With no export on disk, `auto` falls back to the mirrors and
`note` says so: it fetches the `forever` branches of `Gethe/wow-ui-source` and
`Ketho/BlizzardInterfaceResources` over HTTPS from `raw.githubusercontent.com`.
`--source export` reads only the local export and returns `export-not-found` when
none is present; `--source mirror` always downloads. Either way the Lua tables are
executed in the sandboxed Lua 5.1 VM, and the index is written atomically under
`$HERMES_HOME/cache/wow-addon-forge/api-index` (or
`~/.hermes/cache/wow-addon-forge/api-index`). An export carries none of the Ketho
resource lists, so an export index covers the documented API only; its warnings say
so, and a mirror sync is the way to index undocumented names too.

## Disclosure

This is the catalog disclosure from `docs/SPEC-PLUGIN.md` §13, as the shipping tools behave.

- Network: GitHub raw downloads of the API documentation mirrors, only on `wow_api sync`.
- Reads outside the plugin: the WoW install (`Interface/AddOns`, `WTF/**` SavedVariables, `.build.info`). Account folder names are counted and never printed.
- Writes outside the plugin: `Interface/AddOns/<name>` on `wow_install`, and `Inbox.lua` on `wow_bridge push`. Each is an explicit tool call. Backups and the API index cache stay under `~/.hermes/cache/wow-addon-forge/`.
- No shell commands, no background processes, no stored credentials, no telemetry, no self-update.
- Never: input automation, game memory, or a gold-bid loot system.

`wow_env` looks in `/Applications/World of Warcraft` and `C:\Program Files (x86)\World of Warcraft`, or only in `wow_root` when that setting is set. Pass `--root` to look at one other folder. With no install found it prints a `no-install` error as JSON and exits with status 1. The Interface number it reports is derived from the client version (1.60.1 gives 16001) and the output says so in `interface_source`.

## License

MIT. See [LICENSE](LICENSE). Report a vulnerability as [SECURITY.md](SECURITY.md) describes.

World of Warcraft is a trademark of Blizzard Entertainment. This project is not
affiliated with or endorsed by Blizzard.
