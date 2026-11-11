# hermes-wow-plugin

**Ask for a World of Warcraft addon in plain English. Get one that actually loads.**

`wow-addon-forge` is a [Hermes Agent](https://github.com/NousResearch/hermes-agent)
plugin that builds addons for **World of Warcraft: Forever** — and refuses to hand
you one it hasn't checked. Every addon it makes is checked against the real
client's API, run in a simulated copy of the game, tested, and only then
installed. No Lua errors on login. No "this looked right in the chat window."

It also ships **Guildhall**, a complete guild-management addon built entirely
with the plugin itself — living proof the tools work.

Built for players and guild officers who are not programmers. Programmers are
welcome too — the receipts are all here.

## Why you'd care

- **You play WoW and want a small addon** — a tracker, a reminder, a window
  for that one thing the default UI hides. Today that means learning Lua or
  hoping someone else ships it. Here you describe it, and the addon that shows
  up in your AddOns folder has already passed its exams.
- **You run a guild.** Your guild's life is scattered across Discord threads,
  spreadsheets, and whoever remembers what. Guildhall pulls it into the game:
  a notice board, event sign-ups, and a friendly points system (Marks) people
  earn just by showing up and playing together — no forms, no bookkeeping.
- **Your guild also lives on Discord.** Guildhall mirrors both ways: a post
  made in game shows up in Discord, and an announcement pushed from Discord
  appears on the in-game board. One `/reload` of patience each way.
- **You write addons.** `wow_check` names every removed, renamed, or
  restricted API call in your code by file and line — against the API of the
  client build actually installed, not someone's memory of Classic.

## Meet Guildhall

Type `/gh` in game. You get one window, built the moment you open it (so it
costs nothing while closed):

- **Board** — your guild's notice board. Officers post and pin; everyone
  reads and comments. It syncs to every guildmate running the addon — no
  server, no account, just the guild itself.
- **Calendar** — events with one-click sign-ups and live role counts ("we
  need one more healer"), plus a gentle reminder when something starts soon.
- **Marks** — a small internal currency for saying thanks. Marks are **earned
  by playing, not by paperwork**: finish a boss with guildmates, complete a
  battleground, rack up honourable kills, or show up to a scheduled event and
  the claim writes itself. Claims your group can vouch for approve
  automatically; anything else waits in a one-click officer queue. Daily caps
  keep it sane, and every client's ledger agrees to the Mark.
- **Discord mirror** — board posts and events flow out to Discord as
  ready-to-post text; announcements flow back in and land on the board,
  tagged so people can see where they came from.

Everything syncs between guildmates peer-to-peer inside the game's own chat
channels. There is no backend to sign up for and nothing leaves your machine
except through the files the game itself writes.

## How an addon gets made here

1. **You describe it.** "Make me an addon that counts my guild's dungeon
   runs." A bundled skill walks the agent through the house rules.
2. **It gets checked, for real.** The plugin looks every API call up in an
   index built from your client build's own documentation (WoW: Forever is
   client 1.60.1 — the modern retail API, *not* Classic; most examples online
   are for the wrong game). Then the addon is loaded and exercised in a
   strict simulated game — multiple fake guildmates, message loss, combat
   restrictions, even the client's secret-value rules — before you ever see it.
3. **It gets installed safely.** Only a passing addon is installed, with a
   backup of anything it replaces. If something still breaks in the real
   game, the bundled ForgeProbe companion addon catches the error so the
   agent can read it back and fix the actual problem.

Prefer buttons to chatting? The Hermes Desktop **Addon Forge** pane does
status, check, install, and bridge pull without naming a single tool.

## What's in the box

| Piece | What it does for you |
|---|---|
| `wow_env` | Finds your WoW install and lists your addons |
| `wow_api` | The ground truth: what API calls and events exist in your client build |
| `wow_check` | Six rounds of inspection ending in one verdict: pass, or every reason it would fail |
| `wow_test` | Rehearses addons with simulated guildmates before real ones depend on them |
| `wow_new` | Starts every addon from tested building blocks instead of a blank page |
| `wow_install` | Installs a passing addon, backing up whatever it replaces |
| `wow_savedvars` | Reads back what an addon saved in game, as readable data |
| `wow_errors` | Reads the errors ForgeProbe caught in the live game |
| `wow_bridge` | The Discord seam: pull announcements out, push commands in |
| Guildhall | The guild addon described above — the plugin's own acceptance test |
| ForgeProbe | A tiny companion addon that probes the live client and catches Lua errors |

New addons are scaffolded from the same building blocks Guildhall stands on:
a replicated record log, guild sync that converges even when messages get
lost, rank-based trust rules, a lazy Classic-theme window, and the Discord
bridge. Start from working parts; spend your creativity on the idea.

## Where it's going

Guildhall's next rooms are already designed and queued in
[TASKS.md](TASKS.md) — each one is a chore guilds currently do in Discord or
don't do at all:

- **Work orders** — "can someone craft me…?" as a tracked request with
  phases, instead of a message scrolling away.
- **Roster & professions** — who is who, who can craft what, answered in game.
- **Chronicle** — the guild's scrapbook: level-ups, first mounts, first
  epics, kept over the years a character (and a guild) actually lives.
- **Quests & bounties** — officers and members post small jobs with Marks
  rewards; completion is proven by the same automatic tracking.
- **Wishlist & plans** — long-haul goals per character: the gear you're
  chasing, the things you want to get better at — without parse-chasing.
- **Availability** — who actually plays when, so scheduling stops being
  archaeology across time zones.
- **PvP board and tabard vote** — weekly bragging rights from data the
  tracker already has, and picking the guild's look together.

On the plugin side: the remaining Discord commands (`event`, `grant`,
`approve`), sign-up summaries and Marks milestones in the outbox, the
battleground win bonus, and making Guildhall's memory survive a solo
`/reload` without waiting for a guildmate to re-sync it.

## Honest status

This is young software, built in the open, and we label evidence instead of
rounding up:

- The plugin and Guildhall pass a large automated gate (hundreds of tests,
  including five simulated guildmates converging under 30% message loss).
- Live-client checking is recorded line-by-line in
  [docs/INGAME-CHECKLIST.md](docs/INGAME-CHECKLIST.md). The probe sequence
  has run green on the real 1.60.1 client; some demo-path lines are still
  awaiting their run and say `NOT RUN` until they do. If a line there says
  `FAIL`, there is a task for it.
- Marks detections that the live probe shows unusable switch themselves off
  and say so, rather than guessing.

## Try it

Requires [Hermes Agent](https://github.com/NousResearch/hermes-agent). The
plugin declares one Python dependency, `lupa` (an embedded Lua 5.1 VM), which
Hermes installs only with your consent.

From a checkout:

```bash
uv sync --all-groups
hermes plugins validate . --install-deps
hermes plugins enable wow-addon-forge   # for a linked checkout
```

(Catalog install — `hermes plugins install wow-addon-forge` — arrives with
publication.)

Then just ask Hermes: *"Build me an addon that…"* — or run `/wow status` to
see your install, client build, and index state first.

For development (needs [uv](https://docs.astral.sh/uv/)):

```bash
uv sync --all-groups                                               # install
uv run python -m wow_addon_forge --version                         # prints: wow-addon-forge 0.1.0
uv run python -m wow_addon_forge env                               # JSON: installs, flavors, Interface number, addons
uv run python -m wow_addon_forge api sync --flavor forever         # build the API index for your client
uv run python -m wow_addon_forge api status                        # JSON: cached build, age, entry counts
uv run python -m wow_addon_forge api lookup C_Item.GetItemInfo     # JSON: signature, restriction/secret flags
uv run pytest -x -q                                                # fast tests
uv run pytest --cov=src/wow_addon_forge --cov-fail-under=85 && uv run ruff check . \
  && uv run ruff format --check . && uv run mypy src && hermes plugins validate .   # the full gate
```

Good to know: `api sync` prefers your client's own exported interface code
(`ExportInterfaceFiles code`, zero network) and otherwise downloads the
public documentation mirrors — the result's `note` always says which. The
index is cached under `~/.hermes/cache/wow-addon-forge/`. Lua is always
checked in the embedded Lua 5.1 VM, never the system `lua`.

## Documents

| File | What it is |
|---|---|
| `docs/PLAN.md` | The plan: goal, ground truth, architecture, phases, non-goals |
| `docs/SPEC-PLUGIN.md` | The plugin in full: tools, verification pipeline, bridge contract |
| `docs/SPEC-GUILDHALL.md` | The addon in full: data model, sync, trust, Marks, every module |
| `docs/INGAME-CHECKLIST.md` | Live-client acceptance steps and their recorded results |
| `TASKS.md` | The single work queue — what's done, what's next |
| `AGENTS.md` | How this repo is run (one task, tested, documented, committed) |
| `CONTRIBUTING.md` | The short version for humans |

## Disclosure

This is the catalog disclosure from `docs/SPEC-PLUGIN.md` §13, as the shipping tools behave.

- Network: GitHub raw downloads of the API documentation mirrors, only on `wow_api sync`.
- Reads outside the plugin: the WoW install (`Interface/AddOns`, `WTF/**` SavedVariables, `.build.info`). Account folder names are counted and never printed.
- Writes outside the plugin: `Interface/AddOns/<name>` on `wow_install`, and `Inbox.lua` on `wow_bridge push`. Each is an explicit tool call. Backups and the API index cache stay under `~/.hermes/cache/wow-addon-forge/`.
- No shell commands, no background processes, no stored credentials, no telemetry, no self-update.
- Never: input automation, game memory, or a gold-bid loot system.

## License

MIT. See [LICENSE](LICENSE). Report a vulnerability as [SECURITY.md](SECURITY.md) describes. Contributions follow [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).

World of Warcraft is a trademark of Blizzard Entertainment. This project is not
affiliated with or endorsed by Blizzard.
