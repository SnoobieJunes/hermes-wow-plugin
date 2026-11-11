# goose-deuce.md — the deviations log

Why this file exists: the failure mode is the **silent deviation** — the plan says
one thing, the code does another, and nobody finds out until the gap bites. Work
that follows the plan needs no entry here. Work that departs from it is fine
*exactly when it is recorded*, with its reasoning, at the moment it ships.

## The trigger

> Any departure from what the plan, the task, or a project standard said would
> happen — scope cut, approach change, deferral, unplanned addition, standard
> knowingly broken, step skipped, tool or dependency substituted, or a known
> finding knowingly left unfixed — gets an entry in goose-deuce.md, in the same
> commit that ships it.

Honest accounting includes the negative case: findings you are consciously **not**
fixing this pass are listed, with why, so they read as decisions instead of
oversights. When in doubt, write the entry — thirty seconds of logging beats an
hour of archaeology.

**Not a deviation:** choices the plan never spoke to at that granularity — names,
helper extraction, test-case count. But plan *silence* is not an exemption when
the choice is hard to reverse (an on-disk format, a schema, a dependency, a public
interface): log it `[decision]`.

## When to write

In the same commit as the deviation, tagged to it — `Commit(s): this commit` when
the entry is written before the hash exists. Never batched at the end of a
session: an entry reconstructed later records what you wish you had thought.

A deviation discovered **after** its commit is still logged — never silently
dropped. Date it the day you found it, flag the reconstruction in `Why:`, and cite
the shipping commit: `Commit(s): <hash> (logged late, reconstructed YYYY-MM-DD)`.
Late is worse than timely; unlogged is worse than late.

A deviation that ships no code still gets an entry — a skipped gate, a skipped
ritual step, a skipped sweep, a reverted attempt, an approval boundary crossed.
The entry is then its own bookkeeping commit (`goose-deuce: <title>`), written
when the call is made, `Commit(s): this commit`.

## Entry format

New entries go at the **top** of `## Log`, newest first — "the most recent
entries" always means the top of `## Log`. The fenced block is the format
specimen (`<…>` are field descriptions — never filled in the spec, always filled
in an entry):

```markdown
## YYYY-MM-DD — <short title>  [<tag>]
- Task: <T-### / phase / docs/PLAN.md section that governs this work>
- What: <what was actually done — the deviation itself, stated plainly>
- Why: <the rationale, with its evidence named: the failing test, the missing
  credential, the measured number, the foot-gun found>
- Where: <files / modules / functions touched>
- Plan: <what docs/PLAN.md §… or the TASKS.md item said — name it> → <how it now
  stands>. <TASKS.md corrected in this commit — name the item. docs/PLAN.md
  amended in this commit if the deviation falsifies it, otherwise folded at the
  next sweep — say which.>
- Commit(s): <hash(es), or "this commit">
```

**All six fields are required, in this order — an entry missing any field is not
an entry.** The four questions — what was done, why, where, and what the plan said
→ how it now stands — must be answerable from the entry alone, without opening the
diff; `Task:` and `Commit(s):` are what make it findable later. Titles are unique
within a date (they are the citation key).

## Tags

One per entry — the dominant character of the call:

- `[scope]` — something the plan promised is trimmed or not shipped.
- `[approach]` — the plan's goal met by different means than it prescribed.
- `[deferred]` — work moved to later; the owing TASKS.md item is linked in the entry.
- `[extra]` — unplanned work shipped: requested mid-flight, or forced by a finding.
- `[tech-debt]` — an accepted shortcut with a follow-up owed; TASKS.md item linked.
- `[process]` — a project standard or AGENTS.md rule knowingly broken or changed,
  or a lapse being put on the record (late log, stale claim, skipped step).
- `[decision]` — the plan was followed (or was silent) but the call is worth a
  record: a sanctioned fallback taken, an option evaluated and rejected, a
  hard-to-reverse choice made where the plan said nothing.

Trigger → tag: scope cut `[scope]` · approach change / tool or dependency
substituted `[approach]` · deferral `[deferred]` · unplanned addition `[extra]` ·
known finding left unfixed / shortcut accepted `[tech-debt]` · standard broken or
step skipped `[process]` · sanctioned fallback taken, or a hard-to-reverse call
where the plan was silent `[decision]`. `[deferred]` and `[tech-debt]` are the
tags that owe a TASKS.md item — when choosing between one of those and another
tag, choose the owing one.

## Rules

- **Immutable entries.** Corrections are appended inside the entry as a final
  bullet — `- [Correction, YYYY-MM-DD: …]` — never edited into the field they
  correct. Stale paths and superseded claims stay as written: they are a record of
  what the tree looked like at the time.
- **`this commit` is final.** Never backfill a hash into a committed entry — that
  is a rewrite. Recover the hash with `git log --oneline -- goose-deuce.md`. Real
  hashes appear in `Commit(s):` only for entries about *earlier* commits
  (late-logged, or corrections citing where a fix landed).
- **Owed work lives in TASKS.md, not here.** Every `[deferred]` and `[tech-debt]`
  entry names its TASKS.md item; an entry with no item is a silent drop wearing a
  log entry as a disguise.
- **Re-deferral gets a new entry.** When a deferred item comes due and is pushed
  again, that is a fresh call — log it fresh. It keeps being deferred honestly
  until it ships.
- **Multi-agent collisions** on the top of `## Log` resolve by keeping both
  entries in date order — never by dropping one.
- **The sweep** — at the cadence AGENTS.md → Deviations sets. It is a TASKS.md
  item like any other work. Walk the entries above the previous sweep's marker
  (sweep #1 has no marker: its range starts at the repo's first commit, which is
  also where the weekly clock starts): (1) fold every pending `Plan:` adjustment
  into docs/PLAN.md; (2) verify every `[deferred]` / `[tech-debt]` entry still
  has a live TASKS.md item — restore any orphan and append a `[Correction, …]`
  noting the lapse; (3) close by writing the sweep's own `[process]` entry
  naming the date range covered — that entry is the next sweep's starting
  marker. Full audit checklist: step 5 of
  /Users/auston/Development Projects/Templates/NEW-PROJECT-GUIDE.md.

## Log

<!-- Real entries accumulate below, NEWEST AT THE TOP. The top entries are
     session-start required reading (count: AGENTS.md → Session ritual). -->

## 2026-11-11 — CI clones Hermes to run the catalog gate  [decision]
- Task: T-014
- What: GitHub Actions clones `NousResearch/hermes-agent` at depth 1 into the runner temp directory and runs `uv --directory that run hermes plugins validate . --install-deps`. It does not use the user install script, which writes a home directory.
- Why: The full gate includes `hermes plugins validate`, and a catalog runner does not have Hermes preinstalled. Cloning into the repo would make ruff scan Hermes itself.
- Where: `.github/workflows/ci.yml`.
- Plan: AGENTS.md said validate stays a local gate → T-014 requires it in CI, logged here. TASKS.md T-014 closed in this commit. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — wow_root is the only search, flavor and api_source are defaults  [decision]
- Task: T-039 (`docs/SPEC-PLUGIN.md` §11)
- What: Empty `wow_root` means the two default install folders. A set `wow_root` is the only folder `wow_env` searches when the call omits `root`; an explicit `root` still wins. Omitted `wow_api` `flavor` and `source` use the settings (`_forever_` and `auto`).
- Why: SPEC-PLUGIN §11 names the settings and not which call wins. A setting that lost to a test-injected root list would not honour `wow_root`.
- Where: `src/wow_addon_forge/__init__.py`, `src/wow_addon_forge/tools.py`, `plugin.yaml`.
- Plan: SPEC-PLUGIN §11 left the precedence unspecified → pinned here. TASKS.md T-039 closed in this commit. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — status reports the forever flavor  [decision]
- Task: T-013 (`docs/SPEC-PLUGIN.md` §2)
- What: `/wow status` and `hermes wow status` print the `_forever_` flavor when the install has one, not the first flavor in folder order. `check` exits 1 when `wow_check` verdict is `fail`. The skill, slash command, and CLI are registered only when the context has those methods, so a tool-only test double still loads.
- Why: SPEC-PLUGIN §2 names the surfaces and not which flavor a multi-flavor install reports. Alphabetical order would show Classic Era first and hide the client this plugin builds for.
- Where: `src/wow_addon_forge/cli.py`.
- Plan: SPEC-PLUGIN §2 left the status lines unspecified → pinned here. TASKS.md T-013 closed in this commit. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — wow_new name, module order, and bundled tests  [decision]
- Task: T-011 (`docs/SPEC-PLUGIN.md` §3, §8)
- What: `wow_new` requires a Lua identifier, not the wider install name regex, because the name becomes the `Sample = ns` global and `SampleDB`. Modules are written in order core, log, sync, trust, window, bridge, and a requested module pulls in the blocks it calls. `core` is always included. The bundled checks live in `Tests/scaffold.lua`, which is not listed in the TOC.
- Why: SPEC-PLUGIN §3 names the arguments and not the identifier rule, the module order, or where the bundled tests sit. A name with a hyphen would scaffold a TOC the client cannot load. A second order would make slash and window load before the namespace.
- Where: `src/wow_addon_forge/scaffold.py`.
- Plan: SPEC-PLUGIN §8 left those three unspecified → pinned here. TASKS.md T-011 closed in this commit. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — security scan flags bundled test eval  [finding]
- Task: T-011
- What: `hermes plugins validate .` passes, and its security scan cautions on `eval_string` in `scaffold.py` because the bundled `Tests/scaffold.lua` calls `ctx.client:eval`. Left as written.
- Why: `eval` is the wow_test client method. Renaming the generated call would make the bundled tests fail. The caution is not a validation failure.
- Where: `src/wow_addon_forge/scaffold.py`.
- Plan: not a plan departure. Logged so the caution is not mistaken for an oversight.
- Commit(s): this commit

## 2026-11-11 — Classic-only theme and outbox cap  [decision]
- Task: T-019 (`docs/SPEC-GUILDHALL.md` §9–§10, `docs/SPEC-PLUGIN.md` §7)
- What: The window block ships one theme table, Classic, using only `BasicFrameTemplateWithInset`, `UIPanelButtonTemplate`, `UIPanelCloseButton`, and `UIPanelScrollFrameTemplate`. Modern and Nous are not tables yet. The bridge outbox keeps 50 records and drops the oldest. `inbox_seen` and `applied` are lists of ids. An officer or guild-master kind loaded by anyone else is marked seen, not applied, and a `refused` outbox record is written. The slash registered by `core` opens the window.
- Why: The accept requires one theme table and names Classic. The spec file list also names Modern and Nous, and does not name the outbox cap or the seen-id shape. `wow_bridge push` already reads `inbox_seen` as a list of ids; a map would not match it.
- Where: `src/wow_addon_forge/blocks/window/UI/Theme.lua`, `src/wow_addon_forge/blocks/bridge/Bridge.lua`.
- Plan: SPEC-GUILDHALL §9 left the other themes unnamed as tables → Classic only, logged here. TASKS.md T-019 closed in this commit. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — Trust kind table and reduce-time rank  [decision]
- Task: T-018 (`docs/SPEC-GUILDHALL.md` §6)
- What: `officerRank` defaults to 1. Starter kinds: `marks.credit`, `marks.debit`, and `log.checkpoint` need an officer; `settings.set` needs the guild master; `self.act` is member-only and may name only its author. A direct record whose author is now below that minimum does not affect balances, including one stored before the demotion. An officer relay is marked `relay` and counts while that sender is still an officer. A third-party sender stores the record with `unverified` and it does not count. `receive` returns `ignored`, `rejected`, `unverified`, or `accepted`. Sync asks Trust before applying a wire record when Trust is loaded.
- Why: SPEC-GUILDHALL §6 names the rules and not the kind table or the mark field. Marks and settings will call these kinds; a second spelling would fork acceptance.
- Where: `src/wow_addon_forge/blocks/trust/Core/Trust.lua`, `src/wow_addon_forge/blocks/log/Core/Reduce.lua`, `src/wow_addon_forge/blocks/sync/Core/Sync.lua`.
- Plan: SPEC-GUILDHALL §6 left the kind table unspecified → pinned here. TASKS.md T-018 closed in this commit. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — Sync wire prefix and message grammar  [decision]
- Task: T-017 (`docs/SPEC-GUILDHALL.md` §5)
- What: The sync block speaks prefix `GHSYNC` on `GUILD`. Kinds are `A`/`D` (author, seq, time, kind, who, amount), `H` (state hash), `V` (author heads), `Q` (a missing range), and `C` (a 255-byte chunk). At most one send per integer `GetTime` second. Catch-up is dropped before authored data when the queue exceeds 400. `ns.Log.get` is the lookup sync uses.
- Why: SPEC-GUILDHALL §5 names the limits and the hello/vector/request/data idea, and does not name the prefix or the bytes. Trust and Marks will parse these messages; a second spelling would fork the wire.
- Where: `src/wow_addon_forge/blocks/sync/Core/Sync.lua`, `src/wow_addon_forge/blocks/log/Core/Log.lua`.
- Plan: SPEC-GUILDHALL §5 left the grammar unspecified → pinned here. TASKS.md T-017 closed in this commit. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — Log reducer kinds and state hash  [decision]
- Task: T-016 (`docs/SPEC-GUILDHALL.md` §4)
- What: The log block reduces three kinds: `marks.credit` and `marks.debit` sum `p.n` into `p.who`, and `log.checkpoint` replaces balances with `p.balances` then allows compaction of records older than `p.cutoff`. Any other kind is stored and not folded. The state hash is sorted `who=amount` pairs joined by `|`.
- Why: SPEC-GUILDHALL §4 says balances are sums and a checkpoint carries derived balances, and does not name the ledger kinds or the hash. Sync and Marks will call these kinds; a second spelling would fork the log.
- Where: `src/wow_addon_forge/blocks/log/Core/Reduce.lua`.
- Plan: SPEC-GUILDHALL §4 left the kind names and hash form unspecified → pinned here. TASKS.md T-016 closed in this commit. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — Core block token and codec text form  [decision]
- Task: T-015 (`docs/SPEC-PLUGIN.md` §8)
- What: The addon-name token in `src/wow_addon_forge/blocks/core/` is the literal `@@ADDON@@`. The codec is a tagged text form (booleans, integers, IEEE-754 hex floats, hex strings, tables). Decode parses that text and does not execute it. Numeric table keys are encoded with a `#` prefix so they survive as numbers.
- Why: SPEC-PLUGIN §8 requires a token and a codec that does not run received text, and does not name the token or the wire form. Later blocks and `wow_new` have to use the same token or instantiation splits.
- Where: `src/wow_addon_forge/blocks/core/`.
- Plan: SPEC-PLUGIN §8 left the token spelling and the codec form unspecified → pinned here. TASKS.md T-015 closed in this commit. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — Bridge cursor, inbox_seen, and Discord lines  [decision]
- Task: T-012 (`docs/SPEC-PLUGIN.md` §7)
- What: Three contracts pinned. (1) The pull cursor is `{"cursor": N}` in `$HERMES_HOME/cache/wow-addon-forge/bridge-cursors/<addon>.json`, not in the game folder. Pull returns outbox records with `id` strictly greater than that cursor, then stores the max id returned. (2) `push` keeps existing `Inbox.lua` items unless their id is listed in SavedVariables `inbox_seen`. A missing `inbox_seen` keeps every existing item, and the result says so. (3) `bridge pull --format discord` prints `[kind] text` one line per record and prints nothing when there are none. An omitted addon name uses the single installed addon whose TOC declares `## X-Forge-Bridge: 1`.
- Why: SPEC-PLUGIN §7 names the cursor, the inbox shape and the Discord cron command without saying where the cursor is stored, which inbox items are unconsumed, or what a Discord line looks like. Putting the cursor in the game folder would be a write the disclosure does not list.
- Where: `src/wow_addon_forge/bridge.py`, `src/wow_addon_forge/__main__.py`.
- Plan: SPEC-PLUGIN §7 left those three choices unspecified → pinned here. TASKS.md T-012 closed in this commit. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — wow_install reload versus restart, and absolute source paths  [decision]
- Task: T-010 (`docs/SPEC-PLUGIN.md` §3)
- What: Two contracts pinned. (1) `wow_install` reports `restart` when the destination folder is new, when either TOC is missing, or when the incoming TOC lists a file the installed TOC did not; otherwise `reload`. (2) An absolute source path is allowed. What is refused is a `..` segment and an addon basename that is not `^[A-Za-z0-9_!-]+$` (a colon counts as an absolute name). The destination is always `<AddOns>/<basename>`. `force` overrides a `fail` verdict only; a check that could not run still blocks the write. Backups go to `$HERMES_HOME/cache/wow-addon-forge/backups`.
- Why: SPEC-PLUGIN §3 says the tool reports whether a `/reload` or a client restart is needed, and AGENTS.md's foot-gun says a new file needs a restart while a file the TOC already lists is re-read on `/reload`. The accept line "refuses `../` and absolute names" does not forbid an absolute source path; forbidding that would make a normal addon folder un-installable.
- Where: `src/wow_addon_forge/install.py` (`client_action`, `addon_name`), `src/wow_addon_forge/tools.py` (`install_result`).
- Plan: SPEC-PLUGIN §3 named the report and the name regex without the reload/restart cases → pinned here. TASKS.md T-010 closed in this commit. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — ForgeProbe ring contract and SavedVariables parse safety  [decision]
- Task: T-009 (`docs/SPEC-PLUGIN.md` §3, §8)
- What: Three contracts pinned. (1) `wow_errors` returns `{ok, flavor, errors[{message, stack, addon, count, time}], error_count, total_captured, probe}` and never includes a raw account folder name in an error message. (2) SavedVariables Lua runs in an empty Lua 5.1 function environment (`setfenv`); a function call fails as `bad-savedvars` instead of executing. Dotted paths are 0-based JSON indices. `parse_savedvars_lua`, `select_dotted_path`, `read_savedvars` and `locate_savedvars_file` are the one parser T-010 will reuse; `wow_savedvars` itself is not registered in this task. (3) ForgeProbe's slash is `/forge` (`probe`, empty/`status`, `clear`); the error ring holds 200 entries, deduped by `(addon, message)` with `count` incremented; the error hook is installed at file load, before `PLAYER_LOGIN`.
- Why: SPEC-PLUGIN §8 names the ring fields and the probe contents but not the JSON envelope, the empty-environment safety rule, or the slash token. The empty environment is what makes executing client-written Lua safe. Account folder names are personal data (`env.py`).
- Where: `addons/ForgeProbe/Core.lua`, `addons/ForgeProbe/ForgeProbe.toc`, `src/wow_addon_forge/savedvars.py`, `src/wow_addon_forge/tools.py`, `tests/test_forgeprobe_and_errors.py`.
- Plan: SPEC-PLUGIN §8 described ForgeProbe and `wow_errors` without the JSON envelope or the SavedVariables sandbox → pinned here. TASKS.md T-009 closed in this commit. `docs/PLAN.md` is not falsified; nothing to fold. T-010 still owns registering the `wow_savedvars` tool.
- Commit(s): this commit

## 2026-11-11 — wow_check finding codes, bytecode efficiency rules, and wow_test coordinator VM  [decision]
- Task: T-008 (`docs/SPEC-PLUGIN.md` §3, §4, §6)
- What: Three public contracts pinned in `src/wow_addon_forge/check.py` and `tools.py`: (1) `wow_check` returns `{ok: true, addon, path, flavor, build, verdict: "pass"|"fail", error_count, warning_count, findings[]}` where `verdict == "pass"` iff `error_count == 0`, using codes `missing-toc`, `syntax`, `forbidden-global`, `deprecated-api`, `unknown-api`, `restricted-api` (`warning` when guarded in the enclosing `Proto` via `C_RestrictedActions` / `InCombatLockdown` / `issecretvalue` / `pcall` / `xpcall`, `error` when unguarded), `unknown-event`, `restricted-event` (same guard rule), `headless-error` (with `Stack:`), `unserialisable-savedvar`, and Stage 6 warnings `unthrottled-onupdate`, `frame-in-handler`, `unthrottled-addon-message`, `fast-ticker`. (2) `wow_test` accepts both `test(name, fn)` and table-returning `{name = fn}` suites under `Tests/*.lua`, running each test case in a fresh `World` from a separate sandboxed coordinator Lua 5.1 VM that marshals tables and functions across `lupa` runtimes (`_bridge_value`) so `ctx.client:reload()` can rebuild a client VM mid-test without tearing down the running test coroutine. (3) Tool errors (`bad-argument`, `bad-path`, `no-index`, `stale-index`, `lua-vm-unavailable`) return `ok: false`, whereas addon check/test failures return `ok: true, verdict: "fail"`.
- Why: Running multi-client tests inside `primary.runtime` directly would destroy the test frame on `ctx.client:reload()`, while passing raw `_LuaTable` / `_LuaFunction` objects across two `lupa.lua51.LuaRuntime` instances raises `"cannot mix objects from different Lua runtimes"` (caught during verification and solved by `_bridge_value`).
- Where: `src/wow_addon_forge/check.py`, `src/wow_addon_forge/luacheck.py`, `src/wow_addon_forge/tools.py`, `src/wow_addon_forge/__init__.py`, `plugin.yaml`, `tests/test_check.py`, `tests/test_api_tool.py`.
- Plan: SPEC-PLUGIN §3–§4 named the six stages and primary API rule codes without specifying the Stage 5/6 finding codes or the Lua test-file registration protocol → pinned here. TASKS.md updated in this commit (`luacheck.py`, `__init__.py`, `goose-deuce.md` added to T-008 Touches). `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — Headless runtime lazy API resolution, lupa C-lookup guard, and throttle buckets  [decision]
- Task: T-007 (`docs/SPEC-PLUGIN.md` §6)
- What: Four architectural choices in `src/wow_addon_forge/headless/`: (1) `World` pre-indexes the `ApiIndex` once and `SimulatedClient` resolves `C_*` members, bare globals, `Enum.*` and `Constants.*` lazily through Lua `__index` metatables, wrapping Python callbacks in Lua closures so `type(fn) == "function"` holds in Lua while keeping client creation under 5 ms even on the 12,949-function index. (2) `_G.__index` inspects `debugstack("", 3)` and returns `nil` when the immediate caller is C (`lupa` issues an unprotected `lua_getglobal(L, "debug")` before `lua_pcall`, which panics the C process if `__index` calls `error()`), while raising `"unknown global: <key>"` for every Lua-frame access (`debug` included), except declared `SavedVariables` / `<Addon>_Inbox` allowed to read as `nil` before initialisation. (3) Addon-message throttling enforces both a per-prefix and a per-client token bucket (burst 10, refill 1.0/s on virtual time), returning `Enum.SendAddonMessageResult.AddonMessageThrottle` (`3`), and `echo_guild_to_sender` defaults to `True` (configurable). (4) `minimal_api_index()` provides a self-contained 1.60.1 core `ApiIndex` so unit tests run hermetically without `~/.hermes`.
- Why: Eagerly registering 12,949 functions per client would make 5-client sync tests slow; engine-load testing caught both `lupa`'s unprotected `lua_getglobal(L, "debug")` C panic and `lupa` exposing bare Python callables as `userdata` instead of `function`.
- Where: `src/wow_addon_forge/headless/__init__.py`, `src/wow_addon_forge/headless/lua_env.py`, `src/wow_addon_forge/headless/runtime.py`, `src/wow_addon_forge/headless/savedvars_io.py`, `tests/test_headless.py`.
- Plan: SPEC-PLUGIN §6 specified the headless runtime capabilities without prescribing lazy metatable resolution, `echo_guild_to_sender`, or the `minimal_api_index` test helper → recorded here. TASKS.md updated in this commit (`goose-deuce.md` added to T-007 Touches). `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — TOC lint codes, Tests/ pruning, and Lua 5.1 bytecode global-access contract  [decision]
- Task: T-006 (`docs/SPEC-PLUGIN.md` §4 stages 1–3)
- What: Three public contracts pinned for `wow_check` (T-008) and addon scaffolding (T-011): (1) `tocfile.Finding` (`{severity, code, file, line, message, hint}`) is the single finding type shared across checkers, and `lint_toc` emits codes `toc-name-mismatch`, `toc-interface`, `invalid-savedvar`, `invalid-file-path`, `missing-file` (all `error`) and `unlisted-file` (`warning`), pruning dot-folders and `Tests/` / `tests/` during the unlisted-Lua scan because `wow_test` test files are never listed in an addon TOC. (2) `luacheck` transfers `string.dump` bytecode across the `lupa` boundary as hex (raw bytes >= `0x80` fail `lupa`'s UTF-8 string decoder) and parses the Lua 5.1 `lundump.c` binary chunk directly. (3) `GETGLOBAL` folds with an immediate string-constant `GETTABLE` or `SELF` into `kind="member"` (`C_Item.GetItemInfo`) only when the target register is an expression temporary (`not starts_local and a >= active_locals` from `proto.locvars`), keeping `local CI = C_Item` and `local x; x = C_Item` as bare `kind="read"` accesses.
- Why: SPEC-PLUGIN §4 stages 1–3 describe the rules without naming the TOC finding codes, how `Tests/` interacts with unlisted-file warnings, or how Lua 5.1 bytecode separates `C_Item.GetItemInfo(x)` from `local CI = C_Item`. Verifying `lupa.lua51`'s `locvars` layout against `ldebug.c` (`luaF_getlocalname`) caught local-reassignment register reuse (`x = C_Item`) as well as new-local declarations.
- Where: `src/wow_addon_forge/tocfile.py`, `src/wow_addon_forge/luacheck.py`, `tests/test_tocfile.py`, `tests/test_luacheck.py`.
- Plan: SPEC-PLUGIN §4 stages 1–3 left TOC error codes and the `Tests/` folder exemption unspecified → pinned here. TASKS.md updated in this commit (`goose-deuce.md` added to T-006 Touches). `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — wow_api sync reads the mirrors only  [deferred]
- Task: T-005 (`docs/SPEC-PLUGIN.md` §5 source 1; §3 `wow_api` row)
- What: `wow_api` with `action="sync"` builds the index from the public GitHub mirrors (`Gethe/wow-ui-source` and `Ketho/BlizzardInterfaceResources`). Passing `source="export"` returns an explicit `export-not-supported` error without touching the network or disk, and `source="auto"` (the default) uses the mirrors and includes a `note` saying local export reading is not yet supported. Local `<flavor>/BlizzardInterfaceCode` support is filed as T-044 in `## Later`.
- Why: No `BlizzardInterfaceCode` client export exists on this machine (`ExportInterfaceFiles code` has not been run in the live client), so its directory layout on WoW: Forever is unverified. Guessing at an unverified path layout would violate AGENTS.md's honesty bound; refusing `export` explicitly and noting the fallback on `auto` keeps every tool result truthful while unblocking T-007 and T-008.
- Where: `src/wow_addon_forge/tools.py` (`WOW_API_SCHEMA`, `ForgeTools._api_sync`), `tests/test_api_tool.py` (`test_01_sync_then_status`, `test_06_export_source_refused_and_unknown_source`), `TASKS.md` (T-044).
- Plan: SPEC-PLUGIN §5 says `Blizzard_APIDocumentationGenerated` is read from `<flavor>/BlizzardInterfaceCode` when present, otherwise from `Gethe/wow-ui-source` → mirror source ships in T-005, local export source is deferred to T-044 with explicit `export-not-supported` refusal and `auto` fallback note. TASKS.md updated in this commit (T-044 added; `goose-deuce.md` added to T-005 Touches). `docs/PLAN.md` §6 ("from their own client export or the public mirrors") is not falsified; folded at sweep T-004 if T-044 has not shipped by then.
- Commit(s): this commit

## 2026-11-11 — API index cache layout, LuaEnum load order, and wow_api wire shapes  [decision]
- Task: T-005 (`docs/SPEC-PLUGIN.md` §3, §5)
- What: Four hard-to-reverse choices where SPEC-PLUGIN §5 left details open: (1) On-disk cache lives under `$HERMES_HOME/cache/wow-addon-forge/api-index/` (default `~/.hermes/cache/wow-addon-forge/api-index/`) as `<flavor>-<build>.json` (`schema: 1`) plus an atomic `<flavor>.current` pointer file. (2) `LuaEnum.lua` executes in the sandboxed Lua 5.1 VM *before* the `Blizzard_APIDocumentationGenerated` files so `Enum.*` and `Constants.*` globals referenced inside default values evaluate instead of raising nil-index errors, and nameless `{Tables = {...}}` documentation tables (Blizzard's `*ConstantsDocumentation.lua` shape) are indexed alongside named systems. (3) `secret` carries `{args, returns, conditions[]}` so T-034 knows which return fields or regimes are secret, and `widgets` records `{inherits[], methods[]}` for T-007's `CreateFrame` stub. (4) `wow_api` `lookup` of a missing name returns `ok: true, found: false, kind: "unknown"` with `same_name_in_namespaces`, `replacement` and `nearest` (missing API is an answer, whereas missing index is `ok: false, error.code: "no-index"`).
- Why: Later tools (`headless/`, `wow_check`, `wow_new`, Desktop pane, T-034) consume this JSON schema directly; running the real `forever` mirror sync (642 documentation files) proved both the `LuaEnum.lua` load-order dependency and the nameless `*ConstantsDocumentation.lua` table shape (indexing 967 enums and 4,397 tables with 1 upstream warning instead of 232 skipped tables).
- Where: `src/wow_addon_forge/apidocs.py`, `src/wow_addon_forge/luavm.py`, `src/wow_addon_forge/tools.py`, `src/wow_addon_forge/__main__.py`, `tests/test_apidocs.py`, `tests/test_api_tool.py`.
- Plan: SPEC-PLUGIN §5 specified entry kinds and caching per `<flavor>-<build>` under the plugin data directory without naming the exact path, pointer file, load order or `lookup` miss fields → pinned here. TASKS.md updated in this commit. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — Owner re-phase: the plugin first, then the addon built through it  [decision]
- Task: T-040 (`docs/PLAN.md` §5; `docs/SPEC-PLUGIN.md` §8; `docs/SPEC-GUILDHALL.md` §3; LOOP.md rules 10–11)
- What: The owner paused the loop at 01:08 after one closed task (T-003), reviewed the board, and decided: (1) keep `lupa` as the embedded Lua 5.1 engine; (2) the plugin is finished first — every tool, the building blocks, the skill, catalog validation, enabled in Hermes, and a throwaway addon built end to end through its tools (T-041) — before the first line of the addon; (3) Guildhall is then built only through the plugin's tools, in the order Board, events and sign-ups, Marks with automatic tracking, Discord mirror, then the rest; (4) the in-game window uses the Classic theme; (5) commits carry the GitHub noreply address. Two questions were skipped and decided by the agent: Guildhall stays inside this repository, and the names (`wow-addon-forge`, `Guildhall`, Marks) stay. Consequences applied here: the reusable Lua (core, log, sync, trust, window, bridge) is written in the plugin as building blocks instead of being extracted from Guildhall afterwards; T-015..T-019 are re-scoped to blocks; T-011 (`wow_new`) follows them; T-041, T-042 and T-043 are new; loops may work Guildhall tasks until 11:00 instead of 09:30.
- Why: Owner instruction: "build the plugin first … the addon is the test to make sure what you are building is legit", and the demo shows the plugin plus the addon it built. The earlier order built Guildhall's core by hand and extracted the blocks later, which proved the addon, not the plugin.
- Where: `docs/PLAN.md` §4–§5, `docs/SPEC-PLUGIN.md` §8, `docs/SPEC-GUILDHALL.md` header and §9, `LOOP.md` rules 7, 10, 11, `HERMES-OVERLAY.md` addition 6, `AGENTS.md` (layout row, two foot-guns), `TASKS.md` (reorder, re-scope, T-040..T-043, T-005 park note). Outside the tree: the four existing local commits were rewritten to the noreply author before any push, so every hash changed; the plugin was linked into `~/.hermes/plugins` and enabled with `hermes plugins enable` while the owner was present; T-005's in-flight work is parked in two stashes named on the task.
- Plan: PLAN §5 had Guildhall's core built in the addon (old T-015..T-019) with `wow_new` extracted from it afterwards (old T-011), and loops stopping at 09:30 → blocks in the plugin, the gate before any addon file, addon work through the tools only, loops until 11:00 on addon tasks. `docs/PLAN.md` is amended in this commit. At the measured pace Marks, tracking and the Discord mirror are at risk for the demo; the plan says so.
- Commit(s): this commit

## 2026-11-11 — wow_env result shape and where its facts come from  [decision]
- Task: T-003 (`docs/SPEC-PLUGIN.md` §3, the `wow_env` row; §11)
- What: Three hard-to-reverse calls the spec left open, and one early file. (1) The `wow_env` JSON shape: `{ok, installs[{root, flavors[{flavor, product, version, interface, interface_source, accounts, addon_count, addons[{name, toc, title, version, interface[], supports_client}]}]}], searched[], warnings[]}`; a failure is `{ok: false, error{code, message, hint}}` with codes `no-install`, `bad-argument` and `internal-error`. (2) The client Interface number is derived from the client version in `.build.info` (major×10000 + minor×100 + patch) and labelled `interface_source: "derived-from-version"`. (3) When an addon folder holds several TOC files, the one reported is the first whose Interface list contains the client's number, else `<Folder>.toc`, else the first by name; the output names the file it read. (4) `tocfile.py` ships now with a minimal parser (headers and the file list), because `wow_env` and the Guildhall load test both need it; T-006 still owns the lint and extends the file.
- Why: (1) Every later tool, the skill and the Desktop pane read this shape. (2) A read-only look at the owner's install shows `.build.info` has `Version` and `Product` columns and each flavor folder a `.flavor.info` holding the product code (`wowf` for `_forever_`); no file on disk states the Interface number, and 1.60.1 ↔ 16001 is the pair `docs/PLAN.md` §3 verified. (3) The same install has an addon with `_Camelot.toc` and `_Forever.toc` side by side, both `## Interface: 16001`; which one the client prefers is not verified, so the choice is by Interface match instead of by suffix.
- Where: `src/wow_addon_forge/env.py`, `src/wow_addon_forge/tools.py`, `src/wow_addon_forge/tocfile.py`, `tests/test_env.py`, `tests/test_tools.py`, `tests/test_tocfile.py`.
- Plan: SPEC-PLUGIN §3 lists what `wow_env` finds but not the keys, the source of the Interface number or a TOC choice rule, and T-006's Touches implied it would create `tocfile.py` → recorded here as decisions. TASKS.md corrected in this commit: T-003's Touches gains `goose-deuce.md`, and T-039 is filed for the SPEC-PLUGIN §11 settings that no task carried. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — Coverage floor set at 85%, below the measured 100%  [decision]
- Task: T-002 (AGENTS.md → Project snapshot, "Set from the measured number, not a wish")
- What: The floor is 85% on `src/wow_addon_forge/` lines. The measured number at T-002 is 100% over 44 statements.
- Why: The measurement covers three small modules. The modules arriving next do filesystem and HTTP work behind seams; a floor pinned to 100% from a 44-statement sample would stop an unattended loop on defensive branches rather than on real gaps. 85% is the floor the sibling plugin `hermes-coreai` holds with the same toolchain.
- Where: `AGENTS.md` (snapshot commands and floor), `.github/workflows/ci.yml`, `README.md`.
- Plan: The standard says the floor is set from the measured number → set below it once, on purpose; it only ratchets up from here, and the first sweep (T-004) raises it to just under the then-measured number. `docs/PLAN.md` is not falsified.
- Commit(s): this commit

## 2026-11-11 — Loop starts without the step-3 owner review  [decision]
- Task: T-001, T-002 (NEW-PROJECT-GUIDE.md step 3, "Scaffold-A sessions stop here")
- What: The task loop starts the night of 2026-11-11 straight after T-002's cold-clone gate, without waiting for the owner to review the seeded backlog.
- Why: Owner instruction in the kickoff session ("set everything up following our procedures and get to work … in a loop while I sleep"). The hackathon closes 2026-11-11 14:00 PST and the owner is asleep for most of the remaining hours. The backlog was shown to the owner in that session's report.
- Where: `TASKS.md` (T-002..T-038 seeded and immediately pickable), `scripts/` (the loop runner arrives with T-002).
- Plan: The guide says a kickoff session stops after step 3 for owner review before any product code → the review is waived for this project by the owner; the board is reviewed in the morning instead. `docs/PLAN.md` is not falsified.
- Commit(s): this commit
- [Correction, 2026-11-11: the owner did review the board after all — he paused the loop at 01:08, after T-003, re-phased it and restarts it himself; see "Owner re-phase: the plugin first, then the addon built through it".]
- [Correction, 2026-11-11: the loop runners live in the git-ignored `.loop/` directory, not `scripts/`, so no script that spawns Hermes ships at the catalog pin (catalog rule 12). Fixed in T-002.]

## 2026-11-11 — Sweep cadence suspended until the hackathon deadline  [deferred]
- Task: T-004 (AGENTS.md → Deviations, "every 10 closed tasks or weekly")
- What: The standing sweep will not be promoted when the tenth task closes. T-004 is `Gated: owner` until 2026-11-11 14:00 PST.
- Why: A sweep costs one to two loop iterations and the night has room for roughly thirty. The read-only review lane (LOOP.md rule 8) covers adversarial review continuously in the meantime. Owner priority is speed to the deadline.
- Where: `TASKS.md` (T-004 moved to `Gated: owner` with the reason on the task).
- Plan: AGENTS.md says the sweep runs every 10 closed tasks → deferred once, to after the deadline; the owing item is T-004. `docs/PLAN.md` is not falsified; nothing to fold.
- Commit(s): this commit

## 2026-11-11 — Scaffold-time design calls: names, one runtime dependency, a review lane  [decision]
- Task: T-000, T-001 (`docs/PLAN.md` §4, §6; `docs/SPEC-PLUGIN.md` §12; LOOP.md rule 8)
- What: Four hard-to-reverse calls made while the owner was unavailable. (1) Names: plugin `wow-addon-forge`, tools prefixed `wow_`, guild addon `Guildhall` with `/gh`, currency "Marks", default theme Classic. (2) One runtime dependency, `lupa>=2.1,<3`, for an embedded Lua 5.1 VM. (3) LOOP.md gained two repo-specific rules beyond the template: a read-only review lane that writes to `.review/` and never commits, and "nothing about the live client is claimed from a headless run". (4) The plugin and the addon live in one repository so the catalog pin covers both.
- Why: (1) The owner asked for both specs and a running loop the same night; names are cheap to change before the first push and are listed here so they can be. (2) The system `lua` is 5.5 and cannot check Lua 5.1 code; `lupa` (MIT, bundles Lua 5.1; `lupa.lua51` verified importable under Python 3.12 and 3.14 on this machine) is what turns the checks from described into executed. (3) A second model family reviewing continuously, with no write access to the tree, adds review without merge risk. (4) One pin, one validation gate.
- Where: `AGENTS.md` (snapshot), `LOOP.md` (rules 8–9), `HERMES-OVERLAY.md` (addition 6), `docs/PLAN.md`, `docs/SPEC-PLUGIN.md`, `docs/SPEC-GUILDHALL.md`.
- Plan: Plan silence on names and on a dependency policy beyond AGENTS.md's "a dependency is a task of its own" → recorded here as decisions; the dependency itself is added and locked in T-002, whose Accept names it. `docs/PLAN.md` states all four.
- Commit(s): this commit

