# SPEC-GUILDHALL.md — the Guildhall guild addon

Dated 2026-11-11. Normative. Governed by `docs/PLAN.md`.
Working title `Guildhall`; slash commands `/guildhall` and `/gh`.

Guildhall is built only through the `wow-addon-forge` plugin's tools, and only
after the plugin-done gate (PLAN §5). `Core/`, `UI/Theme.lua` and `UI/Window.lua`
are not written here by hand: `wow_new` instantiates them from the plugin's
building blocks. Sections 4–6 describe the behaviour those blocks must have.

## 1. What it is

One addon that gives a guild its own space inside the game: a board, events with
sign-ups, an internal currency earned automatically by playing together, work
orders, a roster, a shared history, guild-made quests, and a mirror to Discord.
It needs no server and no companion app for members. Guildmates who run it sync
with each other over the guild addon channel.

## 2. Platform rules (WoW: Forever)

These are constraints, not preferences. Code that breaks one is wrong.

1. `## Interface: 16001`. Lua 5.1. Retail 12.1.5 API. Every API call and event
   name is looked up in the API index before it is written.
2. No combat data. No combat-log events, no unit health or aura reads, no
   arithmetic on anything a unit or combat API returned. Where an event payload
   might be secret, test it with `issecretvalue` and drop it.
3. No sends while an addon restriction is active. Before every addon message,
   ask `C_RestrictedActions.IsAddOnRestrictionActive` for each regime; if any is
   active, queue and flush on `ADDON_RESTRICTION_STATE_CHANGED`.
4. No protected actions, no secure frames, no taint: Guildhall creates plain
   frames only and never touches Blizzard's secure UI.
5. No gold handling. The addon never trades, mails or bids gold.
6. Free, readable, no advertising, no donation prompts.
7. Events are registered only when `C_EventUtils.IsEventValid(name)` is true.
   A missing event disables the feature that needs it and says so in the UI.

## 3. Files

```
Guildhall.toc            Interface 16001; SavedVariables: GuildhallDB;
                         SavedVariablesPerCharacter: GuildhallCharDB;
                         X-Forge-Bridge: 1
Inbox.lua                data written by the bridge; ships empty
Core/Namespace.lua       addon table, module registry, version
Core/Dispatch.lua        one frame, event fan-out, internal message bus
Core/Clock.lua           server-time seam
Core/Codec.lua           serialiser and safe decoder
Core/Chunker.lua         split and reassemble payloads
Core/Throttle.lua        token bucket and send queue
Core/Restrict.lua        restriction regimes, deferred sends
Core/Log.lua             the record log
Core/Reduce.lua          reducers and derived state
Core/Sync.lua            replication protocol
Core/Trust.lua           roles and record acceptance
Core/Store.lua           SavedVariables schema and migrations
Core/Bridge.lua          outbox and inbox
Core/Slash.lua           /gh commands
UI/Theme.lua             theme tokens (Classic, Modern, Nous)
UI/Widgets.lua           shared row, card, chip, button builders
UI/Window.lua            the window and tab rail, built lazily
UI/Tab<Name>.lua         one file per tab
Modules/<Name>.lua       one file per module (§8)
Tests/*.lua              headless tests; not listed in the TOC
```

Each module registers itself with the namespace and touches other modules only
through the dispatcher and the derived state. Deleting a module file and its TOC
line removes the feature and nothing else.

## 4. Data model: one replicated record log

Everything a guild shares is a **record**:

```
{ a = "Name-Realm",   -- author key, normalised
  s = 17,             -- author's sequence number, starts at 1, no gaps
  t = 1794384000,     -- server time
  k = "board.post",   -- kind
  p = { … },          -- payload, kind-specific, plain data only
  v = 1 }             -- payload schema version
```

- Identity is `(a, s)`. A record is immutable once authored.
- The log is a set. Merging is union; applying a record twice is a no-op.
- Derived state is a pure function of the set: reducers fold records in the
  total order `(t, a, s)`. Entities use last-writer-wins on that order plus
  tombstones; balances are sums over ledger records. Any two members holding
  the same set compute the same state, whatever order records arrived in.
- Storage: `GuildhallDB.guilds[guildKey] = { log = {[a] = {[s] = record}},
  heads = {[a] = highest contiguous s}, checkpoint, settings }`.
- Compaction: an officer-authored `log.checkpoint` record carries the derived
  balances and a cut-off time. Records older than the cut-off that the
  checkpoint covers are dropped. Per-kind retention is a setting.
- A record whose kind or schema version is unknown is stored and replicated but
  not reduced, so older versions never destroy newer data.

Payloads are plain tables of strings, numbers and booleans. The decoder never
executes received text.

## 5. Sync protocol

Channel: `C_ChatInfo.SendAddonMessage(prefix, message, "GUILD")` for broadcast,
`"WHISPER"` for targeted catch-up. One registered prefix. Messages are at most
255 bytes; payloads are chunked as `<id>:<i>/<n>:<bytes>`.

| Message | Sent when | Carries |
|---|---|---|
| `A` announce | A record is authored | The record |
| `H` hello | Login, and at a slow jittered interval | Protocol version, a hash of the sender's heads |
| `V` vector | A received `H` hash differs from mine | My heads, paged |
| `Q` request | A `V` shows records I lack | Author and sequence range |
| `D` data | Answering a `Q`, by whisper | Records |

Rules:

- Sustained send rate at most 1 message per second; bursts within the client's
  per-prefix allowance. The send result enum is honoured: a throttled send is
  re-queued, never dropped.
- Anti-stampede: a member waits a random 0–3 s before answering a `Q` and stays
  silent if someone else answered first.
- Nothing is sent while restricted (§2.3). The queue is bounded; overflow drops
  the oldest catch-up traffic, never an authored record.
- A member who was offline converges after one hello exchange with any member
  who has the records.

## 6. Trust

There are no signatures. Trust comes from two things the game guarantees: the
sender name on an addon message, and guild rank in the roster.

- **Roles.** Guild master = rank 0. Officers = rank index at or below the
  `officerRank` setting (default 1). Everyone else in the roster is a member.
  Non-members are ignored entirely.
- **Verified records.** A record is verified when it arrived directly from its
  author (sender = `a`), or was relayed by an officer. Unverified records are
  stored and shown marked, and never affect the ledger or settings.
- **Who may author what.** Each kind names its minimum role and whether the
  record may only concern its own author (a sign-up signs up the author, no one
  else). Settings records need the guild master. The table lives in
  `Core/Trust.lua` and each module adds its kinds to it.
- **Re-evaluation.** Roles are read from the roster at reduce time, so a
  demotion stops a member's later officer-kind records from applying.
- **Stated limit.** A member with officer rank can forge within that rank's
  powers. Guildhall is built for guilds whose officers are trusted.

## 7. Marks: the guild currency

Marks are an internal, non-tradeable count per character (rolled up per account
alias when a member links alts). The name is a setting. Marks are earned by
taking part, automatically.

**Earning rules** (defaults; all settings, each with a daily cap):

| Activity | Condition | Marks |
|---|---|---|
| Dungeon boss kill | At least half the group are guildmates | 5 |
| Dungeon completed | Same | 15 |
| Raid boss kill | Same | 10 |
| Battleground completed | Same; +2 for a win | 5 |
| World PvP | Per 5 honourable kills while grouped with guildmates | 1 |
| Scheduled guild event attended | In the event's group inside its time window | 10 |
| Work order crafted | Requester confirms receipt | 10 |
| Guild quest or bounty completed | As posted | as posted |
| Officer grant or deduction | Any, with a reason | any |

**How it stays automatic and honest:**

1. Each participant's own client detects the activity (Tracker, §8.4) and
   authors a `marks.claim` with a dedupe key (activity, instance, boss or match,
   day) and the guildmates it saw in the group.
2. Claims with the same key from at least half of the guildmates named in them
   attest each other. An attested claim is approved with no officer involved.
3. A claim that cannot be attested (only one member runs the addon) waits in
   the officer queue for a one-click approval.
4. `marks.grant`, `marks.deduct` and `marks.spend` are officer kinds.
5. Balance = approved claims + grants − deductions − spends, per §4.

Members may stake their own Marks as the reward on a quest or bounty; staking
is a spend that is refunded if the quest is cancelled.

## 8. Modules

Each module lists its record kinds, its tab and its headless acceptance tests.

### 8.1 Board
Posts, pins and comments. Kinds: `board.post` (officer; setting can open it to
members), `board.pin`, `board.comment` (member), `board.remove` (author or
officer). Tab: pinned first, then newest; a post box for those allowed.

### 8.2 Calendar
Guild events with roles and sign-ups. Kinds: `event.create` (officer),
`event.edit`, `event.cancel`, `event.signup` (member, self only: role, status
yes/maybe/no, note). Tab: upcoming list, detail with role counts, one-button
sign-up, a reminder at login and 15 minutes before. Start times are stored as
server time and shown in local time.

### 8.3 Marks
The ledger of §7. Kinds: `marks.claim`, `marks.approve`, `marks.grant`,
`marks.deduct`, `marks.spend`, `marks.rules` (guild master). Tab: balance,
history, guild leaderboard, the officer approval queue.

### 8.4 Tracker
Turns play into claims; has no tab of its own. Detection uses only events that
`IsEventValid` confirms, read outside restrictions:

- Group share: on `GROUP_ROSTER_UPDATE` and at activity start and end, count
  units for which `UnitIsInMyGuild` is true.
- Instance runs: `PLAYER_ENTERING_WORLD` + `GetInstanceInfo`; boss kills from
  `ENCOUNTER_END` / `BOSS_KILL` when usable, otherwise run duration alone.
- Battlegrounds: `PVP_MATCH_COMPLETE`.
- World PvP: `PLAYER_PVP_KILLS_CHANGED` and the change in
  `GetPVPLifetimeStats`. Counts only; no victim identity.
- Event attendance: being in the event's group inside its window.

Claims made while restricted are queued locally and authored when the
restriction lifts. What the live client actually delivers for each event is
recorded by ForgeProbe; a detection the probe shows unusable is switched off and
its activity falls back to officer grants.

### 8.5 Orders
Request-a-craft with tracked phases: `ordered → materials sent → materials
received → in progress → complete → shipped → received`. Kinds:
`order.request` (member: item, quantity, note, wanted crafter or open),
`order.accept`, `order.phase` (requester or crafter, only the next legal phase),
`order.cancel`. Mail events may suggest the next phase; the member confirms it.
Completing an order produces the crafter's Marks claim.

### 8.6 Roster
A self-published profile per character: level, class, professions and skill,
equipped item links, last seen, alt link. Kind: `roster.profile` (member, self
only, last-writer-wins, size-capped). Recipes known are published as a compact
id list when the profession window is opened: `roster.recipes`. Tab: searchable
roster, profile card, "who can craft X".

### 8.7 Chronicle
A timeline of milestones: level-ups, first mount, first epic, profession
milestones, first boss kills, guild anniversaries. Kinds: `chron.entry`
(member, self only). Private by default per character, shared by a toggle.
Tab: personal and guild timelines.

### 8.8 Quests and Bounties
Guild-made objectives with Marks rewards. Kinds: `quest.post` (officer, or
member when staking own Marks), `quest.claim`, `quest.attest`, `quest.close`.
Types: help-run (verified by a Tracker claim with both characters in the
group), donation (confirmed by the recipient), craft (links an order), custom
(officer confirms), bounty (a named player target; the claimant's claim needs
attestation from guildmates who were in the group, or officer confirmation).
Automatic bounty detection is enabled only if the probe shows a usable kill
event. Rewards are Marks; any gold promise is free text the addon ignores.

### 8.9 Wishlist
A long-term character plan: per equipment slot, a target item and a note.
Kind: `wish.set` (member, self only). Items are resolved through `C_Item` from
links or ids. Tab: my plan; guild view of who wants what.

### 8.10 Plans
Personal improvement plans that replace parse-chasing. Kinds: `plan.set`
(member self, or officer for a member), `plan.checkin`. Goals are self-reported
or measured from Guildhall's own non-combat data: attendance, events joined,
orders crafted, quests done. Never combat performance.

### 8.11 Availability
A weekly grid of when each member plays, with roles and interests. Kind:
`avail.set` (member, self only). Tab: "who is on" for a chosen slot, filterable
by role and activity.

### 8.12 PvP
Guild leaderboard from honourable-kill deltas and battleground results that
Tracker already records. No new kinds beyond a weekly `pvp.snapshot`.

### 8.13 Tabard
Design proposals and a vote. Kinds: `tabard.propose`, `tabard.vote` (member, one
live vote each). Rendering uses the game's emblem textures when the probe shows
them reachable; otherwise proposals are described and colour-swatched.

## 9. Interface

One movable window (about 900×560), closed with Escape, opened by `/gh` and the
addon compartment button. A left tab rail; each tab's frames are built the first
time it is shown. Lists use the client's scroll box. All colours, fonts and
textures come from `UI/Theme.lua`; a theme is one table. The theme is
Classic, built on the stock frame templates (the owner's choice, 2026-11-11).
A status line shows guildmates in sync, queued sends, and bridge state.

## 10. Bridge

Guildhall follows the bridge contract in SPEC-PLUGIN §7.

- Outbox: new board posts, events, sign-up summaries, order requests and Marks
  milestones are written as text ready for Discord.
- Inbox: commands (`post`, `event`, `grant`, `approve`) become records authored
  by the character that loads them, tagged with their Discord origin. Officer
  kinds need that character to be an officer; otherwise the command is listed
  as refused in the next outbox.

## 11. Performance budget

- No `OnUpdate`. Timers only while a queue is non-empty.
- At most 1 addon message per second sustained.
- Derived state is cached and updated incrementally; a full re-reduce happens
  only at load and after compaction.
- Frames are created lazily and reused.
- SavedVariables are bounded by retention and checkpoints.

## 12. Tests

- Codec: round-trip property tests; malformed input is rejected without error.
- Log and reducers: shuffled application yields one state hash.
- Sync: 5 simulated clients converge under 30% loss, reordering, duplication
  and a late joiner, with no message over 255 bytes and nothing sent while
  restricted.
- Trust: forged and out-of-role records never reach the ledger or settings.
- Marks: attestation thresholds, caps, refunds, checkpoint equivalence.
- Every module: its kinds, its reducer, its tab model, loaded headless.
- The whole addon: `wow_check` verdict `pass`.
- In game: `docs/INGAME-CHECKLIST.md`.
