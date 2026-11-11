# SPEC-PLUGIN.md — `wow-addon-forge`

Dated 2026-11-11. Normative. Governed by `docs/PLAN.md`.

## 1. Promise

An addon the agent hands the user has already been parsed as Lua 5.1, checked
call by call against the API of the user's own client build, loaded and run in a
strict stub of the game, and installed with a backup. When it still fails in
game, the plugin reads the error back and the agent fixes it without the user
copying anything.

That is the line between this plugin and a prompt or a skill: the checks are
executed, not described.

## 2. Surfaces

| Surface | Name | Purpose |
|---|---|---|
| Toolset | `wow` | The nine tools in §3 |
| Slash command | `/wow` | `status`, `check <path>`, `errors`, `bridge` — a turn that does not depend on the model choosing a tool |
| CLI | `hermes wow …` | The same verbs for scripts and cron (`hermes wow bridge pull --format discord`) |
| Skill | `wow-addon-builder` | The build workflow and the Forever rules the agent follows |
| Desktop | `Addon Forge` pane | Status, addon list, check results, in-game errors, bridge state |
| Addons | `ForgeProbe`, building blocks | Shipped inside the plugin and installed by it |

`plugin.yaml` is `kind: standalone`; `provides_tools` matches the registrations
one to one.

## 3. Tools

Every tool returns JSON text. Every tool that can fail returns
`{"ok": false, "error": {"code", "message", "hint"}}` instead of raising. No tool
is silent about a cap, a truncation or a fallback.

| Tool | Arguments | Does | Writes |
|---|---|---|---|
| `wow_env` | `root?` | Finds WoW installs, their flavors, client version, Interface number, account count and installed addons (title, Interface list, version) | nothing |
| `wow_api` | `action` = `sync` \| `lookup` \| `search` \| `events` \| `status`; `name?`, `query?`, `flavor?`, `source?` | Builds and queries the API index for a build (§5) | the index cache |
| `wow_new` | `name`, `title`, `modules[]`, `dest` | Scaffolds an addon from the tested building blocks (§8) into a workspace folder | `dest` only |
| `wow_check` | `path`, `flavor?` | Static and headless verification (§4); returns findings and a verdict | nothing |
| `wow_test` | `path`, `tests?`, `clients?` | Runs an addon's own Lua tests in the headless runtime, with simulated guildmates | nothing |
| `wow_install` | `path`, `flavor?`, `mode` = `copy` \| `link`, `dry_run?`, `force?` | Installs into `Interface/AddOns/<name>` after a passing check; backs up what it replaces; says whether a `/reload` or a client restart is needed | the addon folder, the backup folder |
| `wow_errors` | `flavor?`, `account?`, `addon?` | Reads ForgeProbe's saved data: captured Lua errors and the capability probe | nothing |
| `wow_savedvars` | `addon`, `flavor?`, `account?`, `character?`, `path?` | Reads an addon's SavedVariables as JSON, optionally one dotted path | nothing |
| `wow_bridge` | `action` = `pull` \| `push` \| `status`; `addon`, `records?`, `format?` | Outbox pull and inbox push for addons that follow the bridge contract (§7) | the pull cursor, `Inbox.lua` |

Write rules, enforced in code and tested with hostile paths:

- `wow_install` writes only inside `<install>/<flavor>/Interface/AddOns/<name>`
  where `<name>` matches `^[A-Za-z0-9_!-]+$`. Path traversal is refused.
- `wow_bridge push` writes only `Inbox.lua` inside an installed addon whose TOC
  declares `## X-Forge-Bridge: 1`.
- Backups go to the plugin's own data directory, never into the game folder.
- A failed `wow_check` blocks `wow_install` unless `force` is passed, and the
  result says so.

## 4. Verification pipeline (`wow_check`)

Run in this order; later stages run even when earlier ones report errors, so one
call returns the whole picture.

1. **TOC lint.** `## Interface` contains the client's number; every listed file
   exists; no listed file is missing from disk and no `.lua` is unlisted
   (warning); `SavedVariables` names are valid identifiers; the folder name
   equals the TOC name.
2. **Syntax.** Each file is compiled with `loadstring` in a real Lua 5.1 VM.
   Lua 5.2+ syntax (`goto`, `//`, bitwise operators, integer suffixes) fails here
   with file and line.
3. **Global access.** The compiled Lua 5.1 bytecode is walked for `GETGLOBAL`
   and `SETGLOBAL` instructions and for member access on a global namespace
   (`C_Item.GetItemInfo`). Each name is resolved against: Lua 5.1 globals that
   WoW keeps, the API index, and globals the addon itself defines (including its
   SavedVariables).
4. **API rules.**
   - `unknown-api` (error): a global or namespace member that does not exist in
     this build.
   - `deprecated-api` (error): exists only as a deprecated shim, or was removed
     and has a known replacement; the hint names the replacement.
   - `restricted-api` (warning, error when unguarded): flagged `HasRestrictions`
     or secret-returning in the docs and not inside a recognised guard
     (`C_RestrictedActions`, `InCombatLockdown`, `issecretvalue`, `pcall`).
   - `unknown-event` / `restricted-event`: literal event names passed to
     `RegisterEvent`.
   - `forbidden-global` (error): `io`, `os.execute`, `require`, `loadfile`,
     `dofile`, `package`, `debug.*` beyond what the game exposes.
5. **Headless load.** The addon is loaded in the stub runtime (§6) in TOC order;
   `ADDON_LOADED`, `PLAYER_LOGIN` and `PLAYER_ENTERING_WORLD` fire; every slash
   command the addon registered is invoked with an empty argument; a simulated
   `/reload` dumps and reloads SavedVariables. Any Lua error is a finding with
   file, line and stack.
6. **Efficiency lints** (warning): `OnUpdate` handlers without an elapsed-time
   throttle; `C_Timer.NewTicker` under 0.1 s; frame creation inside handlers
   that fire often; addon messages sent outside a throttle.

Finding shape: `{severity, code, file, line, message, hint}`. Verdict is `pass`
only with zero errors.

## 5. API index

Purpose: one queryable truth for "does this exist in this build, what does it
take, what does it return, is it restricted".

Sources, merged in this order:

1. `Blizzard_APIDocumentationGenerated` — functions, events, enums, tables, with
   `HasRestrictions`, `SecretArguments` and secret-return annotations. Read from
   the user's own export (`<flavor>/BlizzardInterfaceCode`, produced by the
   client console command `ExportInterfaceFiles code`) when present, otherwise
   from the matching branch of `Gethe/wow-ui-source` (`forever`).
2. `Resources/GlobalAPI.lua`, `Events.lua`, `FrameXML.lua`, `WidgetAPI.lua`,
   `Templates.lua`, `Mixins.lua`, `LuaEnum.lua` from the matching branch of
   `Ketho/BlizzardInterfaceResources` — the complete name lists, including
   undocumented globals and Lua-defined functions.

The documentation files are Lua. They are executed in the sandboxed Lua 5.1 VM
with a shim `APIDocumentation:AddDocumentationTable`, never parsed with regular
expressions.

Entry shape: `{name, kind: function|event|enum|table|template|widget-method,
namespace?, args[], returns[], restricted: bool, secret: {args, returns},
deprecated: bool, replacement?, source}`.

The index is cached per `<flavor>-<build>` under the plugin data directory and
is never committed. `wow_api status` reports the build, the source, the age and
the counts. A stale or missing index is an explicit error from every tool that
needs it, with the `sync` call to run.

Network: `sync` from the mirrors is the plugin's only network call. It is
user-triggered, read-only, and disclosed in the README.

## 6. Headless runtime

A strict stand-in for the game inside `lupa.lua51`:

- **Sandbox.** The environment matches the game's: no `io`, no `os` beyond
  `date`/`time`/`difftime`/`clock`, no `require`/`package`/`loadfile`/`dofile`.
  WoW's additions (`strsplit`, `strjoin`, `wipe`, `tinsert`, `format`, `bit`,
  `date`, `time`, `GetTime`) are provided.
- **Strict API.** Every indexed function exists and returns defaults shaped by
  its documented return types. Reading an unknown global, or an unknown member
  of a `C_` namespace, raises an error that names it.
- **Frames.** `CreateFrame` returns objects with every widget method from the
  index. Real behaviour for: parents and children, `Show`/`Hide`/`IsShown`,
  `SetScript`/`GetScript`/`HookScript`, `RegisterEvent`/`UnregisterEvent`
  (unknown names raise, as the client does), templates by name.
- **Clock.** Virtual time. `C_Timer.After`/`NewTimer`/`NewTicker`,
  `GetTime`, `GetServerTime` advance only through `world.advance(seconds)`.
- **SavedVariables.** Loaded before `ADDON_LOADED`, serialised at logout and
  `/reload` exactly as the client does; an unserialisable value is a finding.
- **Addon messages.** A bus between simulated clients. Prefix registration is
  required to receive; 255-byte messages and 16-byte prefixes are enforced;
  the per-prefix throttle is modelled and returns the client's result enum;
  loss, duplication and reordering are injectable; the sender name arrives as
  `Name-Realm`.
- **World fixtures.** Guild roster with ranks, group and raid composition,
  instance state, and addon-restriction regimes that turn sends into queued or
  refused calls.
- **Scenario API** (Python, mirrored in Lua for addon tests):
  `World(index)`, `world.client(name, rank=…)`, `client.load_addon(path)`,
  `client.fire(event, …)`, `client.slash(text)`, `client.eval(lua)`,
  `world.advance(seconds)`, `client.reload()`.

Secret-value simulation is in: while a restriction is active, a documented secret
return is an opaque value. Arithmetic and concatenation on it raise a
`secret-value` finding. Relational comparison with a number is Lua 5.1's
`attempt to compare table with number`, classified as the same finding when the
check runs under a restriction (goose-deuce.md 2026-11-11). A widget setter may
hold the value. `issecretvalue` is true for it.

## 7. Bridge contract

Any addon can opt in; Guildhall is the first.

- TOC declares `## X-Forge-Bridge: 1` and lists `Inbox.lua`.
- **Outbox** (game → outside): the addon's SavedVariables table has
  `outbox = { {id, t, kind, text, data}, … }` — bounded, oldest dropped.
  `wow_bridge pull` returns records with `id` past the stored cursor.
- **Inbox** (outside → game): `Inbox.lua` assigns `<Addon>_Inbox = { {id, t,
  kind, data, via}, … }`. The addon ingests unseen ids at load and remembers
  them in SavedVariables. `wow_bridge push` rewrites the file atomically and
  validates that it compiles as Lua 5.1 before replacing the old one.
- Delivery to Discord is Hermes's job, not the plugin's: a cron job with
  `no_agent` runs `hermes wow bridge pull --format discord` and Hermes delivers
  the output to the configured channel. The plugin never holds a Discord
  credential.
- Latency is stated wherever the bridge is described: one `/reload` or logout
  in each direction.

## 8. Shipped addons and building blocks

- **ForgeProbe** — on login and on `/forge probe` it records, into its own
  SavedVariables: build info; for a list of events, `C_EventUtils.IsEventValid`
  and whether registration succeeds; presence of a list of API names; the
  addon-restriction regimes and their state; an addon-message echo test and its
  result enum. It captures Lua errors and `ADDON_ACTION_FORBIDDEN` /
  `ADDON_ACTION_BLOCKED` into a 200-entry ring (message, stack, addon, count,
  time). It passes `wow_check` like any other addon.
- **Building blocks** (`wow_new` modules, in `src/wow_addon_forge/blocks/`): `core`
  (namespace, event dispatcher, clock, slash, the safe codec with no `loadstring` on
  received data, versioned SavedVariables with migrations), `log` (the replicated
  record log and reducers), `sync` (chunking, throttle, restriction queue,
  guild-channel replication), `trust` (roles and record acceptance), `window` (one
  lazy window, theme tokens, the Classic theme), `bridge` (the §7 contract). The
  blocks are written and tested in the plugin before any addon exists. Each is a Lua
  template with an addon-name token and its own Lua tests. Guildhall is scaffolded
  from them and is their first real consumer.

## 9. Skill `wow-addon-builder`

The workflow, in order: `wow_env` → `wow_api status` (sync if stale) → `wow_new`
→ write code, looking every call and event up with `wow_api lookup` first →
`wow_check` until the verdict is `pass` → `wow_test` → `wow_install` (the user
approves the write) → ask the user to `/reload` → `wow_errors` → fix and repeat.

It also carries: the Forever rules from PLAN §3; the building-block reference;
the bridge recipe including the cron job; Blizzard's addon policy (free,
readable code, no advertising or donation prompts); and the hard refusals — no
input automation, no memory reading, no gold-bid loot systems.

## 10. Desktop pane and backend

`desktop/plugin.js` imports only `@hermes/plugin-sdk`, `react` and
`react/jsx-runtime`, uses theme variables, and patches nothing. Sections: Game,
Addons, Check results, In-game errors, Bridge. Buttons call the backend:
`GET /status`, `GET /addons`, `POST /check`, `POST /install`,
`POST /bridge/pull` in `dashboard/plugin_api.py`. Long calls run off the request
thread.

## 11. Configuration

`config_schema`: `wow_root` (default: auto-detect —
`/Applications/World of Warcraft`, `C:\Program Files (x86)\World of Warcraft`),
`flavor` (default `_forever_`), `api_source` (`auto` | `export` | `mirror`).
No secrets. No environment variables required.

## 12. Dependencies

One runtime dependency: `lupa>=2.1,<3` (MIT; bundles Lua 5.1). It is what makes
the checks real. Without it every tool that needs the VM returns an explicit
`lua-vm-unavailable` error; nothing degrades silently. Declared in
`pyproject.toml` so Hermes installs it with consent.

## 13. Disclosure (catalog rule 13)

- Network: GitHub raw downloads of the API documentation mirrors, only on
  `wow_api sync`.
- Reads outside the plugin: the WoW install (`Interface/AddOns`, `WTF/**`
  SavedVariables, `.build.info`).
- Writes outside the plugin: `Interface/AddOns/<name>` on install, `Inbox.lua`
  on bridge push. Each is an explicit tool call the user can see.
- No shell commands, no background processes, no stored credentials, no
  telemetry, no self-update.
