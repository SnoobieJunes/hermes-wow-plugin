# TASKS.md — hermes-wow-plugin work queue
<!-- One queue. New DONE entries at the top of Done. Tasks without observable
     acceptance criteria are not pickable — sharpen them first. -->

## Now
- [ ] T-054 — Reconcile live sender identity format with Trust/Sync name keys
      Why: Live T-035 evidence: the guild echo sender arrived as `Friar Baggins` (space, no `-Realm` suffix), while records author `Name-Realm` from UnitName+GetRealmName and Trust resolves roles by name — a mismatch would silently un-verify real guild traffic.
      Accept: Headless: a client whose wire sender lacks the realm suffix (or contains a space) still has its officer records applied and its claims attested exactly as the Name-Realm form does today; the normalisation is in one seam and named. Full gate green.
      Touches: `src/wow_addon_forge/blocks/trust/`, `src/wow_addon_forge/blocks/sync/`, `addons/Guildhall/Core/`, `tests/`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-018, T-035   Gated: none
- [ ] T-036 — In-game acceptance of Guildhall
      Why: Headless passes are not in-game passes (LOOP.md rule 9).
      Accept: INGAME-CHECKLIST lines 6–12 carry results from the live client; every FAIL has a task.
      Touches: `docs/INGAME-CHECKLIST.md`, `TASKS.md`, `CHANGELOG.md`   Depends: T-035, T-023   Gated: owner
- [ ] T-037 — Publish the repository and open the catalog pull request
      Why: The hackathon entry is a catalog PR pinned to a full commit SHA.
      Accept: The owner approves the push; the diff and commit metadata are scanned for secrets and personal data; `plugin-catalog/wow-addon-forge.yaml` pins the 40-character SHA with the SPEC-PLUGIN §13 disclosure; the PR URL is written on this task.
      Touches: `README.md`, `TASKS.md`, `CHANGELOG.md`   Depends: T-014   Gated: owner
- [ ] T-038 — Record the demo, post it, submit the form
      Why: The other two entry requirements, due 2026-11-11 14:00 PST.
      Accept: A demo under 90 seconds is posted on X tagging @NousResearch; the form is submitted with the PR and post URLs; both URLs are written on this task.
      Touches: `docs/`, `README.md`, `TASKS.md`, `CHANGELOG.md`   Depends: T-037   Gated: owner

## Later
- [ ] T-049 — Mirror: remaining Discord commands and outbox kinds
      Why: SPEC-GUILDHALL §10 also promises `event`, `grant` and `approve` inbox commands and sign-up summaries, order requests and Marks milestones in the outbox; T-023 shipped the board round trip and refuses the rest as unsupported (goose-deuce.md 2026-11-11 "Mirror widened Board with an origin tag; remaining §10 surface deferred").
      Accept: Headless: a pushed `event` command creates the event on an officer load and refuses on a member load; `grant` and `approve` follow the Marks officer rules; a sign-up writes a summary line and an approved claim crossing a 50-Mark milestone writes a milestone line. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Mirror.lua`, `addons/Guildhall/Tests/`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`   Depends: T-023   Gated: none
- [ ] T-050 — Persist the replicated record log across reload
      Why: A solo `/reload` currently empties every fold until guild sync re-converges (goose-deuce.md 2026-11-11 "The replicated record log does not survive a solo reload").
      Accept: Headless: a client's board rows, events and balances are identical immediately before and after a solo `client.reload()` with no peer traffic; the persisted form is bounded by the checkpoint/compaction rules. `wow_check` verdict `pass`. Full gate green.
      Touches: `src/wow_addon_forge/blocks/sync/`, `src/wow_addon_forge/blocks/log/`, `tests/`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-017   Gated: none
- [ ] T-048 — Tracker: battleground win bonus and dungeon-completed row
      Why: SPEC-GUILDHALL §7 pays +2 for a battleground win and 15 for a completed dungeon; T-022 could not detect either honestly (goose-deuce.md 2026-11-11 "Tracker ships without the BG win bonus and the dungeon-completed row").
      Accept: After T-035's probe results name a usable faction read and completion signal: headless, a won battleground claims 7 and a lost one 5; a completed dungeon claims 15 once per run. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Tracker.lua`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-022, T-035   Gated: none
- [ ] T-025 — Guildhall Orders: request a craft with tracked phases
      Why: Crafting requests are a daily guild chore that lives in Discord today (SPEC-GUILDHALL §8.5).
      Accept: Headless: an `order.request` moves through the seven phases only in order and only by the requester or the crafter; an out-of-order or third-party `order.phase` is rejected; completing an order authors the crafter's Marks claim once; the order appears in the bridge outbox. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Orders.lua`, `addons/Guildhall/UI/TabOrders.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-021   Gated: none
- [ ] T-026 — Guildhall Roster: profiles and professions
      Why: An in-game armory and "who can craft X" (SPEC-GUILDHALL §8.6).
      Accept: Headless: a profile is published at login and on change, is last-writer-wins, is size-capped, and a profile naming another character is rejected; recipes publish as a compact list; "who can craft" returns the right members. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Roster.lua`, `addons/Guildhall/UI/TabRoster.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-019   Gated: none
- [ ] T-027 — Guildhall Chronicle: milestones and memories
      Why: The long-haul record a returning player comes back to (SPEC-GUILDHALL §8.7).
      Accept: Headless: a level-up, a new mount and a first epic each author one `chron.entry`; entries are private until shared; the guild timeline merges shared entries in time order; duplicates of one milestone are collapsed. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Chronicle.lua`, `addons/Guildhall/UI/TabChronicle.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-019   Gated: none
- [ ] T-028 — Guildhall Quests and Bounties
      Why: Guild-made objectives with Marks rewards, including player bounties (SPEC-GUILDHALL §8.8).
      Accept: Headless: an officer posts each quest type; a member posts one by staking Marks and cannot stake more than their balance; a help-run completes from a Tracker claim with both characters grouped; a bounty claim needs attestation from grouped guildmates or an officer; cancelling refunds the stake; closing pays the reward once. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Quests.lua`, `addons/Guildhall/UI/TabQuests.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-022   Gated: none
- [ ] T-029 — Guildhall Wishlist: the long-haul character plan
      Why: Players plan a character over years; the guild sees who wants what (SPEC-GUILDHALL §8.9).
      Accept: Headless: `wish.set` stores a target item per slot, is self-only and last-writer-wins; the guild view groups members by wanted item; an unresolvable item id is kept and marked pending. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Wishlist.lua`, `addons/Guildhall/UI/TabWishlist.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-019   Gated: none
- [ ] T-030 — Guildhall Plans: personal improvement plans
      Why: Goals that replace parse-chasing (SPEC-GUILDHALL §8.10).
      Accept: Headless: a member sets a plan; an officer sets one for a member and a member cannot set one for another; measured goals read attendance, orders and quests from derived state; no goal type reads combat data. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Plans.lua`, `addons/Guildhall/UI/TabPlans.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-022   Gated: none
- [ ] T-031 — Guildhall Availability: who plays when
      Why: Scheduling without a spreadsheet (SPEC-GUILDHALL §8.11).
      Accept: Headless: `avail.set` stores a weekly grid, self-only; "who is on" for a slot returns the right members filtered by role and activity; slots convert between server and local time correctly across a day boundary. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Availability.lua`, `addons/Guildhall/UI/TabAvailability.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-020   Gated: none
- [ ] T-032 — Guildhall PvP board
      Why: Organised PvP rankings from data Tracker already has (SPEC-GUILDHALL §8.12).
      Accept: Headless: weekly snapshots rank members by honourable-kill delta and battleground results; five clients agree on the ranking after sync. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/PvP.lua`, `addons/Guildhall/UI/TabPvP.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-022   Gated: none
- [ ] T-033 — Guildhall Tabard: proposals and vote
      Why: A guild picks its look together (SPEC-GUILDHALL §8.13).
      Accept: Headless: a member proposes a design; each member holds one live vote that a later vote replaces; the tally is identical on five clients. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Tabard.lua`, `addons/Guildhall/UI/TabTabard.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-019   Gated: none
- [ ] T-045 — Verify export sync against a real Forever `BlizzardInterfaceCode` export
      Why: T-044's export sub-layout is the Gethe mirror's tree, proven against fake installs only, and documentation files that read `Enum.*` at load time fail without a `LuaEnum.lua` (goose-deuce.md 2026-11-11 "export sync layout and resource-list gap").
      Accept: The owner runs `ExportInterfaceFiles code` in the live client; `wow_api` with `source="export"` against that tree returns `source: export` with function/event counts comparable to a mirror sync of the same build, its warnings are pasted into this task, and every layout or Enum gap found becomes a plugin fix or a new task. Full gate green.
      Touches: `src/wow_addon_forge/apidocs.py`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-044   Gated: owner
- [ ] T-004 — Run standing goose-deuce sweep #1
      Why: Keep `docs/PLAN.md`, `TASKS.md`, `AGENTS.md` and `goose-deuce.md` aligned. The cadence is suspended until the hackathon deadline (goose-deuce.md 2026-11-11 "Sweep cadence suspended until the hackathon deadline"); the owner releases this task after 2026-11-11 14:00 PST.
      Accept: Every pending `Plan:` adjustment is folded into `docs/PLAN.md`; no orphaned `[deferred]` or `[tech-debt]` entry; the stranger test passes.
      Touches: `docs/PLAN.md`, `TASKS.md`, `goose-deuce.md`, `AGENTS.md`, `CHANGELOG.md`   Depends: T-000   Gated: owner

## Blocked

## Dropped

## Done
- [x] T-055 — Evolve the checklist guard test past the T-035 live run (2026-11-11, this commit)
      Why: The T-009 guard asserted INGAME-CHECKLIST section A stays NOT RUN until a live run; T-035 was that run, and its commit landed red with a false Tests line (goose-deuce.md 2026-11-11 "T-035 landed on a red suite with a false Tests line; checklist guard evolved").
      Accept: The guard enforces the result format (five results, each NOT RUN or dated PASS/FAIL with build token); full suite green. Full gate green.
      Touches: `tests/test_forgeprobe_and_errors.py`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-035   Gated: none
- [x] T-035 — Run the in-game probe (2026-11-11, this commit)
      Why: Only the live client says which events fire and whether guild addon messages echo (INGAME-CHECKLIST section A).
      Accept: The owner installs ForgeProbe, logs in on a guilded character, runs `/forge probe`, reloads; `wow_errors` output is pasted into the task; INGAME-CHECKLIST lines 1–5 carry results; any detection the probe shows unusable gets a task.
      Touches: `docs/INGAME-CHECKLIST.md`, `TASKS.md`, `CHANGELOG.md`   Depends: T-009, T-010   Gated: owner
      Owner run 2026-11-11 (wow_errors, pasted in session): build 1.60.1/70888, Interface 16001; echo sent=true result=0 received=true sender="Friar Baggins"; 11/11 events valid, 13/13 APIs present, restrictions inactive; ADDON_ACTION_FORBIDDEN x4 per RunProbe (Core.lua events loop) -> T-052 fixed, T-054 filed.
- [x] T-053 — Window block: a visible tab rail and per-tab containers (2026-11-11, this commit)
      Why: Live T-036 evidence: `/gh` opens the window but there are no tab buttons and no tab is ever shown, so Board/Calendar/Marks are unreachable in game (headless tests call show_tab directly and cannot see this).
      Accept: Headless: opening the window builds one button per registered tab and shows the first tab; clicking a button (its OnClick) shows that tab's container and hides the others; registering after build still gets a button. Block and scaffolded copy identical modulo the name token. `wow_check` verdict `pass`. Full gate green. Live retest recorded under T-036.
      Touches: `src/wow_addon_forge/blocks/window/UI/Window.lua`, `addons/Guildhall/UI/Window.lua`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-019   Gated: none
- [x] T-052 — ForgeProbe: no login auto-probe, truthful registration records (2026-11-11, this commit)
      Why: Live T-035 evidence: the login auto-probe's protected RegisterEvent attempts (4 of 11 events in client 1.60.1) raise ADDON_ACTION_FORBIDDEN and a Blizzard-UI modal on every login, and the old pcall recorded registered=true for blocked calls.
      Accept: Headless regression: no probe table exists after load/login until `/forge probe`; after the slash the probe table exists with `registered` from IsEventRegistered; existing probe tests stay green. `wow_check` on ForgeProbe verdict `pass`. Full gate green. Live retest (no modal at login) recorded under T-036.
      Touches: `addons/ForgeProbe/Core.lua`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-009   Gated: none
- [x] T-051 — Repository hygiene mirrored from Eldr (2026-11-11, this commit)
      Why: The repo publishes today (T-037); Eldr's public-repo setup is the owner's proven model, adapted where its AGPL/CLA apparatus does not fit an MIT plugin.
      Accept: `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/` (bug, feature, config with security link) and `.github/FUNDING.yml` exist and name this repo's tools and rules; `.gitleaks.toml` exists, a local `gitleaks detect` over full history runs clean (findings allowlisted with reasons or none), and CI gains Eldr's hardened gitleaks job (pinned image, commits-scanned assertion); license statements agree across `LICENSE`, `plugin.yaml`, `pyproject.toml` and `README.md`. Full gate green.
      Touches: `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `.github/`, `.gitleaks.toml`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-014   Gated: none
- [x] T-023 — Guildhall Discord mirror, end to end (2026-11-11, this commit)
      Why: The Discord mirror is the demo's closing beat (SPEC-GUILDHALL §10).
      Accept: Built through the plugin's tools (LOOP.md rule 10). A board post authored in a simulated client appears in `wow_bridge pull` output after `client.reload()` as Discord-ready text; a `post` command sent with `wow_bridge push` becomes a `board.post` after the next reload when the loading character is an officer, and is reported refused in the outbox when it is not; an inbox item is never applied twice. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Mirror.lua`, `addons/Guildhall/Modules/Board.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-043   Gated: none
- [x] T-022 — Guildhall Tracker: automatic participation (2026-11-11, this commit)
      Why: Marks must be earned by playing, not by paperwork (SPEC-GUILDHALL §8.4).
      Accept: Built through the plugin's tools (LOOP.md rule 10). Headless, with world fixtures: a dungeon boss kill in a group that is at least half guildmates authors one claim per addon user after the restriction lifts and none while it is active; the same kill in a group under half authors none; a battleground completion and a 5-kill honourable-kill delta each author a claim; attendance inside an event window authors a claim; an event that `IsEventValid` reports invalid disables its detection and the status line says so; no unit or combat API result is used in arithmetic. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Tracker.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-021, T-020   Gated: none
- [x] T-021 — Guildhall Marks ledger (2026-11-11, this commit)
      Why: The internal currency is the owner's core ask; its arithmetic must be exact on every client (SPEC-GUILDHALL §7).
      Accept: Built through the plugin's tools (LOOP.md rule 10). Headless: claims with one dedupe key from at least half the named guildmates are approved with no officer; a lone claim waits and is approved by an officer's `marks.approve`; a second claim with the same key by the same author adds nothing; daily caps hold; `marks.spend` cannot take a balance below zero; a staked reward is refunded on cancel; five clients agree on every balance after sync; balances before and after a checkpoint are equal. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Marks.lua`, `addons/Guildhall/UI/TabMarks.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-043   Gated: none
- [x] T-020 — Guildhall Calendar: events and sign-ups (2026-11-11, this commit)
      Why: Sign-ups are the most-used officer tool and half of the Discord round trip (SPEC-GUILDHALL §8.2).
      Accept: Built through the plugin's tools (LOOP.md rule 10). Headless: an officer's `event.create` appears on a member's client; the member's `event.signup` changes the role counts on the officer's; a sign-up naming another character is rejected; a member's `event.create` is rejected unless the setting allows it; cancelling hides the event; the login reminder lists events starting within 24 hours of virtual time. `wow_check` verdict `pass`. Full gate green.
      Touches: `addons/Guildhall/Modules/Calendar.lua`, `addons/Guildhall/UI/TabCalendar.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `CHANGELOG.md`, `TASKS.md`   Depends: T-043   Gated: none
- [x] T-043 — Guildhall Board (2026-11-11, this commit)
      Why: The first thing a member sees, and the demo's centre (SPEC-GUILDHALL §8.1).
      Accept: Built through the plugin's tools. Headless: posting through the Board's public function creates a `board.post` that a second client shows in its row model; pins sort first; `board.remove` by a non-author member is rejected; the Board tab builds only when first shown. `wow_check` and `wow_test` tool verdicts `pass`, quoted in the commit body. Full gate green.
      Touches: `addons/Guildhall/Modules/Board.lua`, `addons/Guildhall/UI/TabBoard.lua`, `addons/Guildhall/Guildhall.toc`, `addons/Guildhall/Tests/`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`   Depends: T-042, T-047   Gated: none
- [x] T-047 — Carry generic record payloads on the sync wire (2026-11-11, this commit)
      Why: The sync block's wire form only carries `{who, n}` payloads (the T-017 pin), so a `board.post` text cannot replicate — a missing plugin capability found while starting T-043 (LOOP.md rule 10). SPEC-GUILDHALL §4 payloads are kind-specific plain data and §5's `A`/`D` carry "the record".
      Accept: A record whose payload is not exactly `{who, n}` crosses between two headless clients intact (text with commas, over 255 bytes chunked) via a Codec wire form; the legacy `{who, n}` form and the five-client convergence test are unchanged; a payload the Codec cannot encode is never enqueued. Full gate green.
      Touches: `src/wow_addon_forge/blocks/sync/Core/Sync.lua`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-042   Gated: none
- [x] T-042 — Guildhall, scaffolded by the plugin (2026-11-11, this commit)
      Why: The addon is the plugin's acceptance test; it starts from `wow_new`, not from hand-written files (LOOP.md rule 10).
      Accept: The T-003 stub under `addons/Guildhall` and its skeleton test are removed. `wow_new`, called as a tool in the session, creates `addons/Guildhall` with every block, name `Guildhall`, slash `/gh` and the Classic theme. `wow_check` and `wow_test`, called as tools, return `pass`, and their JSON summaries are quoted in the commit body. The five-client convergence test runs against the scaffolded addon. Full gate green.
      Touches: `addons/Guildhall/`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`   Depends: T-041, T-046   Gated: none
- [x] T-046 — Add an optional slash command to `wow_new` (2026-11-11, this commit)
      Why: T-042 requires Guildhall's slash to be `/gh`, but the scaffold derives `/guildhall` from the addon name and `wow_new` has no slash parameter — a missing plugin capability found before the addon task could start (LOOP.md rule 10).
      Accept: `wow_new` accepts an optional `slash` (default `/` + lowercased name); a scaffold created with `slash="/gh"` registers `/gh` headless (its bundled test asserts `/gh`), invalid slash values are refused with a stable error, and existing default-slash scaffolds are unchanged. Full gate green.
      Touches: `src/wow_addon_forge/scaffold.py`, `src/wow_addon_forge/tools.py`, `src/wow_addon_forge/blocks/core/Core/Slash.lua`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`   Depends: T-041   Gated: none
- [x] T-041 — The plugin-done gate: build a throwaway addon end to end through the enabled plugin (2026-11-11, this commit)
      Why: Owner rule: no addon work starts until the plugin is finished and proven by use (PLAN §5).
      Accept: Every tool in SPEC-PLUGIN §3 is registered and `hermes plugins validate . --install-deps` passes. `hermes plugins list` shows `wow-addon-forge` enabled (it is already linked to this repo). A fresh Hermes session started in a scratch directory with the `wow-addon-builder` skill builds a throwaway addon using only the plugin's tools: `wow_env` and `wow_install` against a temporary fake install, `wow_api` against the live index, `wow_new`, `wow_check` with verdict `pass`, `wow_test`, `wow_savedvars` and `wow_errors` on fixtures, and `wow_bridge` pull and push. That session's tool calls and verdicts are saved under `docs/gate/` and summarised in the commit body. Every defect found is fixed in the plugin first and the gate is re-run from a fresh session until it passes clean. Full gate green.
      Touches: `docs/gate/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, and any plugin file a defect requires   Depends: T-014   Gated: none
- [x] T-044 — Support local `BlizzardInterfaceCode` client exports in `wow_api sync` (2026-11-11, this commit)
      Why: SPEC-PLUGIN §5 lists `<flavor>/BlizzardInterfaceCode` (produced by `ExportInterfaceFiles code`) ahead of the public mirrors when present on disk; deferred from T-005 until an export folder layout is verified.
      Accept: Unit tests against a fake install holding `<flavor>/BlizzardInterfaceCode` prove `wow_api` with `source="export"` and `source="auto"` indexes the local export with zero network calls, and falls back to the mirror under `auto` (saying so in `note`) when no export folder is present. Full gate green.
      Touches: `src/wow_addon_forge/apidocs.py`, `src/wow_addon_forge/tools.py`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-005, T-039   Gated: none
- [x] T-034 — Secret-value simulation in the headless runtime (2026-11-11, this commit)
      Why: Code that works out of combat and errors in combat is the failure the static rule cannot fully see (SPEC-PLUGIN §6).
      Accept: With a restriction regime active, documented secret-returning functions return an opaque value; arithmetic, comparison or concatenation on it raises a `secret-value` finding with file and line; passing it to a widget setter does not; Guildhall and ForgeProbe stay at verdict `pass`. Full gate green.
      Touches: `src/wow_addon_forge/headless/`, `src/wow_addon_forge/check.py`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-008   Gated: none
- [x] T-024 — Desktop pane `Addon Forge` and its backend (2026-11-11, this commit)
      Why: Non-technical users get buttons instead of tool names; judges score polish (SPEC-PLUGIN §10).
      Accept: `desktop/plugin.js` and `dashboard/plugin_api.py` exist; the validator's `desktop surface` check passes; backend route tests against a fake install return status, the addon list and a check result; the pane imports nothing but `@hermes/plugin-sdk`, `react` and `react/jsx-runtime` and contains no JSX. Full gate green.
      Touches: `desktop/plugin.js`, `dashboard/`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-014   Gated: none
- [x] T-014 — Catalog-ready baseline (2026-11-11, this commit)
      Why: From this commit on, any commit can be pinned for the hackathon entry (PLAN §5).
      Accept: `hermes plugins validate . --install-deps` passes with 0 failures; `LICENSE` (MIT), `SECURITY.md` and a README disclosure section covering SPEC-PLUGIN §13 exist; `.github/workflows/ci.yml` runs the full gate on macOS and Linux; `plugin.yaml` `provides_tools` lists exactly the registered tools; version `0.1.0` agrees in `plugin.yaml`, `pyproject.toml` and the package; a cold clone passes the gate.
      Touches: `LICENSE`, `SECURITY.md`, `README.md`, `.github/workflows/ci.yml`, `plugin.yaml`, `pyproject.toml`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-013   Gated: none
- [x] T-039 — Declare the plugin settings and make `wow_env` honour `wow_root` (2026-11-11, this commit)
      Why: SPEC-PLUGIN §11 names three settings (`wow_root`, `flavor`, `api_source`) and no task carried them; without `wow_root`, a user whose game is outside the two default folders must pass `root` on every call. Found while building T-003.
      Accept: `plugin.yaml` declares `config_schema` with `wow_root`, `flavor` (default `_forever_`) and `api_source` (`auto` | `export` | `mirror`); a unit test registers the plugin with a context that supplies `wow_root` (read the way `hermes-coreai` reads its settings) naming a fake install, and `wow_env` with no `root` finds it and searches nowhere else; with no setting the default locations are searched; `hermes plugins validate .` reports the config schema as declared and passes. Full gate green.
      Touches: `plugin.yaml`, `src/wow_addon_forge/tools.py`, `src/wow_addon_forge/__init__.py`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-003   Gated: none
- [x] T-013 — Skill `wow-addon-builder`, `/wow`, and `hermes wow` (2026-11-11, this commit)
      Why: The tools need the workflow that uses them, and a path that does not depend on the model choosing a tool (SPEC-PLUGIN §2, §9).
      Accept: `skills/wow-addon-builder/SKILL.md` has valid frontmatter and is registered by `register(ctx)`; `/wow status` and the CLI `status` verb print install, build and index state from a fake install in tests; the CLI `check <fixture>` exits non-zero on verdict `fail`; `hermes plugins validate .` passes. Full gate green.
      Touches: `skills/wow-addon-builder/SKILL.md`, `src/wow_addon_forge/cli.py`, `plugin.yaml`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-012, T-011   Gated: none
- [x] T-011 — `wow_new`: scaffold an addon from the building blocks (2026-11-11, this commit)
      Why: A weak model, or a user in a hurry, starts from code that already passes; it is also how Guildhall will be created (SPEC-PLUGIN §3, §8).
      Accept: `wow_new` with every block produces an addon whose `wow_check` verdict is `pass` and whose bundled Lua tests pass under `wow_test`; with only `core` it produces an addon that loads headless; it refuses a non-empty `dest`; the tool is registered and `hermes plugins validate .` passes. Full gate green.
      Touches: `src/wow_addon_forge/scaffold.py`, `src/wow_addon_forge/tools.py`, `plugin.yaml`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-019   Gated: none
- [x] T-019 — Building blocks `window` and `bridge`: one lazy window with the Classic theme, and the bridge client (2026-11-11, this commit)
      Why: Every scaffolded addon needs a window that costs nothing until opened and, optionally, the Discord seam (SPEC-GUILDHALL §9, SPEC-PLUGIN §7).
      Accept: Headless: the window is built on first open and not before; a tab a module registers builds only when first shown; the theme is one table and Classic uses only frame templates the API index confirms for this build; the bridge block writes an outbox that `wow_bridge pull` reads and ingests an `Inbox.lua` written by `wow_bridge push`, never applying an item twice. An addon instantiated from every block gets `wow_check` verdict `pass`. Full gate green.
      Touches: `src/wow_addon_forge/blocks/window/`, `src/wow_addon_forge/blocks/bridge/`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-018, T-012   Gated: none
- [x] T-018 — Building block `trust`: roles and record acceptance (2026-11-11, this commit)
      Why: With no signatures, rank and sender are the only defences; they must hold (SPEC-GUILDHALL §6).
      Accept: Headless: a member-authored officer-kind record never reaches derived state; the same record relayed by an officer does; a record received from a third party is stored marked unverified and excluded from privileged effects; a self-only kind naming another character is rejected; demoting an author stops later records from applying; a non-member's messages are ignored. `wow_check` verdict `pass`. Full gate green.
      Touches: `src/wow_addon_forge/blocks/trust/`, `tests/`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-017   Gated: none
- [x] T-017 — Building block `sync`: chunker, throttle, restriction queue, protocol (2026-11-11, this commit)
      Why: Guildmates must converge without a server, inside the client's message limits (SPEC-GUILDHALL §5).
      Accept: Headless simulation on an addon instantiated from the blocks: 5 clients, 200 records authored across them, 30% loss with reordering and duplication, one client joining late — all five reach one state hash within 10 simulated minutes; no message exceeds 255 bytes; no client sustains more than 1 message per second; nothing is sent while a restriction is active and the queue flushes when it lifts. `wow_check` verdict `pass`. Full gate green.
      Touches: `src/wow_addon_forge/blocks/sync/`, `tests/`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-016, T-007   Gated: none
- [x] T-016 — Building block `log`: the replicated record log and reducers (2026-11-11, this commit)
      Why: One replicated log is the whole data model; convergence depends on it being order-independent (SPEC-GUILDHALL §4).
      Accept: Lua tests prove: applying the same 300 generated records in 50 shuffled orders yields one state hash; a duplicate record is a no-op; an unknown kind is stored but not reduced; a checkpoint followed by compaction leaves derived balances unchanged. An addon instantiated from `core` + `log` gets `wow_check` verdict `pass`. Full gate green.
      Touches: `src/wow_addon_forge/blocks/log/`, `tests/`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-015   Gated: none
- [x] T-015 — Building block `core`: namespace, dispatcher, clock, store, codec, slash (2026-11-11, this commit)
      Why: Every addon the plugin scaffolds stands on these, Guildhall first (SPEC-PLUGIN §8, SPEC-GUILDHALL §3).
      Accept: The block is Lua templates with an addon-name token under `src/wow_addon_forge/blocks/core/`. Lua tests run by pytest prove: the codec round-trips 500 random nested tables (strings with every byte 1–255, integers, floats, booleans), its output never contains byte 0, and 200 mutated inputs are rejected by returning nil plus a message, never by raising; the store migrates a version-1 fixture; the slash command registers under the instantiated addon's name. An addon instantiated from the block gets `wow_check` verdict `pass`. Full gate green.
      Touches: `src/wow_addon_forge/blocks/core/`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-008   Gated: none
- [x] T-012 — `wow_bridge` and the bridge contract (2026-11-11, this commit)
      Why: The Discord link is two files; the contract makes any addon able to use it (SPEC-PLUGIN §7).
      Accept: With a SavedVariables fixture and a temporary addon folder: `pull` returns only records past the cursor and advances it; a second `pull` returns none; `push` writes an `Inbox.lua` that compiles in the Lua 5.1 VM and keeps earlier unconsumed items; `push` to an addon without `## X-Forge-Bridge: 1` is refused; `uv run python -m wow_addon_forge bridge pull --format discord` prints one line per record and nothing when there is none. Full gate green.
      Touches: `src/wow_addon_forge/bridge.py`, `src/wow_addon_forge/tools.py`, `src/wow_addon_forge/__main__.py`, `plugin.yaml`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-010   Gated: none
- [x] T-010 — `wow_savedvars` and `wow_install` (2026-11-11, this commit)
      Why: Reading game data and installing safely are the two file seams to the client (SPEC-PLUGIN §3 write rules).
      Accept: Against a temporary fake install: SavedVariables with nested tables, long strings and negative numbers convert to JSON; a dotted `path` returns one subtree; install copies the addon, backs up a pre-existing folder into the plugin data directory, refuses when `wow_check` fails unless `force`, writes nothing under `dry_run`, refuses `../` and absolute names, and reports `reload` versus `restart` correctly. No test touches `/Applications`. Full gate green.
      Touches: `src/wow_addon_forge/savedvars.py`, `src/wow_addon_forge/install.py`, `src/wow_addon_forge/tools.py`, `plugin.yaml`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-008   Gated: none
- [x] T-009 — ForgeProbe addon and `wow_errors` (2026-11-11, this commit)
      Why: The docs say what exists; only the live client says what fires. ForgeProbe records it and catches Lua errors so the agent can read them (SPEC-PLUGIN §8).
      Accept: `wow_check addons/ForgeProbe` verdict `pass`; headless, an error raised by a second fixture addon lands in ForgeProbe's saved ring with message and stack; `/forge probe` fills the probe table in the stub; `wow_errors` turns a SavedVariables fixture into JSON with `errors[]` and `probe{}`. Full gate green. The in-game half stays `NOT RUN` in `docs/INGAME-CHECKLIST.md` section A.
      Touches: `addons/ForgeProbe/`, `src/wow_addon_forge/savedvars.py`, `src/wow_addon_forge/tools.py`, `src/wow_addon_forge/__init__.py`, `plugin.yaml`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-008   Gated: none
- [x] T-008 — `wow_check` and `wow_test` (2026-11-11, this commit)
      Why: The plugin's promise is one call that returns every reason an addon would fail (SPEC-PLUGIN §4).
      Accept: A fixture addon that calls a removed global, registers a restricted event unguarded and contains Lua 5.3 syntax yields findings `deprecated-api` (or `unknown-api`), `restricted-event` and `syntax`, each with file and line, and verdict `fail`; a clean fixture yields `pass`; a fixture that errors in `PLAYER_LOGIN` yields `headless-error` with a stack; `wow_test` runs a fixture Lua test file and reports one pass and one fail by name. Both tools are registered; `hermes plugins validate .` passes. Full gate green.
      Touches: `src/wow_addon_forge/check.py`, `src/wow_addon_forge/luacheck.py`, `src/wow_addon_forge/tools.py`, `src/wow_addon_forge/__init__.py`, `plugin.yaml`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-007   Gated: none
- [x] T-007 — Headless runtime: the strict stub of the game (2026-11-11, this commit)
      Why: "It runs" has to be executed, not asserted (SPEC-PLUGIN §6); it is also what lets a loop test Guildhall without the client.
      Accept: Tests prove: two simulated clients load a fixture addon; a guild addon message fires `CHAT_MSG_ADDON` on the other client only if it registered the prefix, with sender `Name-Realm`; a 256-byte message is refused; the 11th message inside one second returns the throttle result; reading an unknown `C_` member raises an error naming it; `RegisterEvent` of an unknown event raises; timers fire in order under `world.advance`; SavedVariables survive `client.reload()`; an active restriction regime turns a send into a refused call. Full gate green.
      Touches: `src/wow_addon_forge/headless/`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-005, T-006   Gated: none
- [x] T-006 — Lua 5.1 static analysis and TOC lint (2026-11-11, this commit)
      Why: Syntax and name errors must be caught before anything runs (SPEC-PLUGIN §4 stages 1–3).
      Accept: Tests prove: a file using `goto` or `//` fails with code `syntax` and its line; global reads and writes of a fixture are listed with lines; `C_Item.GetItemInfo(x)` is reported as member access `C_Item.GetItemInfo`; `local CI = C_Item` is reported as a read of `C_Item`; TOC parsing returns the Interface list, the SavedVariables names and the file list, and flags a listed file that does not exist. Full gate green.
      Touches: `src/wow_addon_forge/luacheck.py`, `src/wow_addon_forge/tocfile.py`, `tests/`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-003   Gated: none
- [x] T-005 — Build the API index and the `wow_api` tool (2026-11-11, this commit)
      Why: Every other check needs one queryable truth for what exists in the user's client build (SPEC-PLUGIN §5).
      Accept: Unit tests over a small hand-written fixture in Blizzard's documentation-table format (no Blizzard source committed) prove functions, events and enums are indexed with `restricted`, `secret` and `deprecated` fields, and that `lookup` of a missing name returns `unknown` with nearest matches. One live run, its output recorded in the commit body: `uv run python -m wow_addon_forge api sync --flavor forever` then `api status` prints build `1.60.1` with more than 4000 functions and more than 1200 events; `api lookup C_ChatInfo.SendAddonMessage` shows four arguments; `api lookup GetItemInfo` reports it is not a C API function and names `C_Item.GetItemInfo`; `api lookup COMBAT_LOG_EVENT_UNFILTERED` prints the restriction flags read from the documentation. `wow_api` is registered and `hermes plugins validate .` passes. Full gate green.
      Touches: `src/wow_addon_forge/apidocs.py`, `src/wow_addon_forge/luavm.py`, `src/wow_addon_forge/tools.py`, `src/wow_addon_forge/__main__.py`, `src/wow_addon_forge/__init__.py`, `plugin.yaml`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-003   Gated: none
- [x] T-040 — Re-phase the plan: the plugin first, then the addon built through it (2026-11-11, this commit)
      Why: Owner decision after reviewing the board: the plugin is finished and gated before any addon work, and the addon is built only with the plugin's tools so it proves the plugin.
      Accept: `docs/PLAN.md` §5 states the phases, the gate and the rules; the building blocks move into the plugin (T-015..T-019 re-scoped, T-011 after them); T-041 (gate), T-042 (scaffold) and T-043 (Board) exist; LOOP.md rules 10–11 and HERMES-OVERLAY.md addition 6 match; the step-2 field-count gate passes; the full gate is green.
      Touches: `docs/PLAN.md`, `docs/SPEC-PLUGIN.md`, `docs/SPEC-GUILDHALL.md`, `LOOP.md`, `HERMES-OVERLAY.md`, `AGENTS.md`, `TASKS.md`, `CHANGELOG.md`, `goose-deuce.md`   Depends: T-003   Gated: none
- [x] T-003 — Build the walking skeleton: the plugin loads, one real tool answers, one addon file runs headless (2026-11-11, this commit)
      Why: Prove the architecture end to end before building on it: Hermes loads the plugin, a tool reads an install layout through an injected filesystem, and addon Lua executes in Lua 5.1.
      Accept: `hermes plugins validate .` passes with one declared tool `wow_env`; a unit test feeds `wow_env` a fake install tree and gets flavor `_forever_`, Interface `16001` and the addon list back as JSON; a test loads `addons/Guildhall/Guildhall.toc` and its first Lua file in the Lua 5.1 VM with no error; the full gate is green.
      Touches: `plugin.yaml`, `__init__.py`, `src/wow_addon_forge/`, `addons/Guildhall/`, `tests/`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-002   Gated: none
- [x] T-002 — Stand up the toolchain, the mechanical gates, and a real smoke test (2026-11-11, this commit)
      Why: Every later task needs one automated gate: tests, lint, format, types, coverage, and Hermes plugin validation.
      Accept: `uv sync --all-groups`, `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` and `hermes plugins validate .` all pass; the smoke test runs a Lua chunk in the embedded Lua 5.1 VM and imports the package; every `TBD step 3` marker in `AGENTS.md` and `LOOP.md` is replaced; the AGENTS.md layout table gains the `plugin.yaml`, `__init__.py` row; a cold clone passes the full gate.
      Touches: `pyproject.toml`, `.python-version`, `uv.lock`, `plugin.yaml`, `__init__.py`, `src/wow_addon_forge/`, `tests/test_smoke.py`, `.github/workflows/ci.yml`, `AGENTS.md`, `LOOP.md`, `README.md`, `CHANGELOG.md`, `TASKS.md`   Depends: T-001   Gated: none
- [x] T-001 — Write the normative plan, both product specs, the living docs, and the phase-1 backlog (2026-11-11, this commit)
      Why: The architecture, the two product specs and the task breakdown must exist and agree before any product code.
      Accept: `docs/PLAN.md`, `docs/SPEC-PLUGIN.md`, `docs/SPEC-GUILDHALL.md` and `docs/INGAME-CHECKLIST.md` are written and dated; `README.md` is expanded; `CHANGELOG.md` has entries for T-000 and T-001; the step-2 gate passes.
      Touches: `docs/PLAN.md`, `docs/SPEC-PLUGIN.md`, `docs/SPEC-GUILDHALL.md`, `docs/INGAME-CHECKLIST.md`, `README.md`, `CHANGELOG.md`, `TASKS.md`, `goose-deuce.md`   Depends: T-000   Gated: none
- [x] T-000 — Scaffold hermes-wow-plugin from templates (2026-11-11, this commit)
      Why: Wire the repository layout, the process law, the deviation log and the task board before any plan or code.
      Accept: The step-1 gate passes (no placeholder outside `TBD step 3`, no `WORKED-EXAMPLE`, every layout path exists, `CLAUDE.md -> AGENTS.md`).
      Touches: `AGENTS.md`, `CLAUDE.md`, `goose-deuce.md`, `LOOP.md`, `HERMES-OVERLAY.md`, `TASKS.md`, `docs/`, `CHANGELOG.md`, `.gitignore`, `README.md`   Depends: none   Gated: none
