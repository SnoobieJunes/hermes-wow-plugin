# PLAN.md — hermes-wow-plugin normative plan

Dated 2026-11-11. Every goose-deuce.md `Plan:` field measures against this file.
The two product specs it points at are normative as well:
`docs/SPEC-PLUGIN.md` (the Hermes plugin) and `docs/SPEC-GUILDHALL.md` (the guild
addon). Where this file and a spec disagree, this file wins and the spec is fixed.

## 1. Goal

Ship **`wow-addon-forge`**, a Hermes Agent plugin that lets a non-programmer ask
for a World of Warcraft: Forever addon and get one that has already been checked
against the real client API, loaded and run headless, and installed. Prove it
with **Guildhall**, a full guild-management addon built with the plugin.

Hard deadline: the Hermes Agent Plugin Hackathon closes **2026-11-11 14:00 PST**.
Entry = a catalog pull request pinned to a 40-character commit, a demo video
under 90 seconds posted on X, and the entry form.

## 2. Users and observable success

| User | What they do | Success they can observe |
|---|---|---|
| A WoW player who cannot code | "Build me an addon that …" in Hermes | The addon appears in the game's AddOns list and loads with no Lua error |
| A guild officer | Runs a guild from inside the game | Board, events, sign-ups, the Marks ledger and work orders sync between guildmates |
| A guild's Discord | Reads and steers the guild from Discord | A post or sign-up made in game shows up in Discord; a Discord command shows up in game after `/reload` |
| An addon author | Uses the tools directly | `wow_check` names every unknown, deprecated or restricted API call by file and line |

The plan is met when all of these are true and evidenced:

1. `hermes plugins validate . --install-deps` passes at the pinned commit.
2. `wow_check` on `addons/Guildhall` reports 0 unknown API names, 0 unguarded
   restricted calls and a passing headless load.
3. The headless simulation converges: 5 simulated guild members reach the same
   state hash under 30% message loss, reordering and a late joiner.
4. Every line of `docs/INGAME-CHECKLIST.md` marked required carries a recorded
   in-game result from the live WoW: Forever client.
5. A 90-second demo shows prompt → verified addon → in game → Discord round trip.

Items 1–3 are provable by a loop. Items 4–5 need the owner at the game.

## 3. Ground truth this plan is built on

Verified 2026-11-11 against the `forever` branches of `Gethe/wow-ui-source`
(build 1.60.1.70888, 643 API documentation files) and
`Ketho/BlizzardInterfaceResources`, and against the owner's install:

- WoW: Forever is client 1.60.1, `## Interface: 16001`. It runs the retail
  12.1.5 ("Midnight") API, not Classic's. Lua is 5.1.
- Old global names are gone from the C API: `GetItemInfo`, `SendChatMessage` and
  `ReloadUI` are absent; `C_Item.GetItemInfo`, `C_ChatInfo.SendChatMessage` and
  `C_UI.Reload` exist. A model writing from memory produces code that fails.
- The combat log is closed to addons: `C_CombatLog` is filter and retention
  controls only. Guildhall reads no combat data.
- Present in the client: `C_ChatInfo.SendAddonMessage` (returns a
  `SendAddonMessageResult`), `C_RestrictedActions.IsAddOnRestrictionActive`,
  `C_EventUtils.IsEventValid`, `issecretvalue`, `UnitIsInMyGuild`,
  `GetGuildRosterInfo`, `GetPVPLifetimeStats`, `C_Calendar`, `C_TradeSkillUI`,
  and the events `ENCOUNTER_END`, `BOSS_KILL`, `PLAYER_PVP_KILLS_CHANGED`,
  `PVP_MATCH_COMPLETE`, `GROUP_ROSTER_UPDATE`, `NEW_MOUNT_ADDED`,
  `ADDON_RESTRICTION_STATE_CHANGED`. Present does not mean unrestricted: what
  actually fires, and with readable payloads, is what the in-game probe records.
- Addons have no network and no file I/O. Game → outside is SavedVariables
  (written on `/reload` or logout). Outside → game is a data `.lua` file in the
  addon folder that the TOC already lists.
- Reported by community documentation, not verified here: addons cannot message
  other players inside instances; GDKP is not allowed in Forever. Both are
  treated as true: sends queue while restricted, and no gold-bid loot system is
  built.

## 4. Architecture

```
Hermes session ──► wow-addon-forge (Python, src/wow_addon_forge/)
                   ├─ env        find installs, flavors, Interface, addons
                   ├─ apidocs    build + query the API index for a build
                   ├─ luacheck   Lua 5.1 syntax, global-access analysis, TOC lint
                   ├─ headless   strict stub of the WoW runtime in a Lua 5.1 VM
                   ├─ install    copy/link into Interface/AddOns with backup
                   ├─ savedvars  SavedVariables ⇄ JSON, ForgeProbe results
                   └─ bridge     outbox pull / inbox push (the Discord seam)
                         │ files only: AddOns/<name>/, WTF/**/SavedVariables/
                         ▼
WoW: Forever client ──► addons/Guildhall (Lua 5.1)
                        Core: codec, record log, sync, trust, store, bridge
                        Modules: Board, Calendar, Marks, Tracker, Orders, …
                        UI: one window, lazy tabs, theme tokens
                   └──► addons/ForgeProbe  capability probe + error catcher
```

Seams (injected, so tests stay hermetic): filesystem root, HTTP fetcher, clock,
randomness, and the Lua VM factory. Nothing in the suite touches the real WoW
install, the network or `~/.hermes`.

The plugin talks to the game only through files the game itself reads and
writes. It never automates input and never reads game memory.

## 5. Phases

| Phase | Tasks | Outcome |
|---|---|---|
| 0 Setup | T-000..T-003 | Process files, plan, toolchain, walking skeleton |
| 1 Forge core | T-005..T-012 | API index, Lua analysis, headless runtime, the nine tools |
| 2 Shippable plugin | T-013, T-014 | Skill, `/wow`, `hermes wow`, catalog-ready baseline. **From here every commit is pinnable.** |
| 3 Guildhall MVP | T-015..T-023 | Core, record log, sync, trust, UI shell, Board, Calendar, Marks, Tracker, bridge |
| 4 Desktop | T-024 | The Addon Forge pane |
| 5 Guildhall modules | T-025..T-034 | Orders, Roster, Chronicle, Quests and Bounties, Wishlist, Plans, Availability, PvP, Tabard, secret-value simulation |
| 6 Owner | T-035..T-038 | In-game probe and acceptance, push, catalog PR, demo, form |

Order is priority. A loop that runs out of night leaves a shippable plugin and
as much of Guildhall as it reached; nothing later is allowed to break phase 2.

Schedule for 2026-11-11 (PST): loops stop picking new product tasks at 09:30.
09:30–11:30 owner in-game probe, acceptance and fixes. 11:30–12:30 demo capture.
12:30–13:30 push, catalog PR, X post, form. 30 minutes of slack.

## 6. Non-goals

- No GDKP or any gold-bid loot system. Marks are an internal, non-tradeable
  guild currency earned by participation; the addon never moves gold.
- No combat-log parsing, damage meters, or anything that needs combat data.
- No input automation, memory reading, or any channel besides the files the
  game reads and writes.
- No real-time Discord link. Latency is one `/reload` or logout.
- No per-player companion app requirement. Guildmates sync in game; one machine
  running Hermes mirrors to Discord.
- No bundling of Blizzard's source. The API index is built on the user's machine
  from their own client export or the public mirrors, and cached.
- No paid tier, advertising or in-game donation prompts (Blizzard addon policy).
- No claim of Classic or retail support. Code is flavor-aware; only Forever is
  tested.
- No cryptographic signatures inside the addon. Trust rests on the game server
  authenticating message senders and on guild rank (see SPEC-GUILDHALL §6).

## 7. Risks

| Risk | Mitigation |
|---|---|
| The live client behaves differently from the docs | ForgeProbe records what really fires; headless results are never reported as in-game results |
| A loop stalls overnight | Per-iteration wall-clock cap, driver failover, stop file, log per iteration |
| Guildhall grows past what one night can test | Strict priority order; modules are independent reducers over one tested sync core |
| Catalog validation breaks late | `hermes plugins validate .` is part of every commit's gate |
| An officer-rank member forges records | Documented limit of the trust model; cooperative guilds are the target |
