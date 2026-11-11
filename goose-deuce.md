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

## 2026-11-11 — Loop starts without the step-3 owner review  [decision]
- Task: T-001, T-002 (NEW-PROJECT-GUIDE.md step 3, "Scaffold-A sessions stop here")
- What: The task loop starts the night of 2026-11-11 straight after T-002's cold-clone gate, without waiting for the owner to review the seeded backlog.
- Why: Owner instruction in the kickoff session ("set everything up following our procedures and get to work … in a loop while I sleep"). The hackathon closes 2026-11-11 14:00 PST and the owner is asleep for most of the remaining hours. The backlog was shown to the owner in that session's report.
- Where: `TASKS.md` (T-002..T-038 seeded and immediately pickable), `scripts/` (the loop runner arrives with T-002).
- Plan: The guide says a kickoff session stops after step 3 for owner review before any product code → the review is waived for this project by the owner; the board is reviewed in the morning instead. `docs/PLAN.md` is not falsified.
- Commit(s): this commit

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

