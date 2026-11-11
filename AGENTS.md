# AGENTS.md — hermes-wow-plugin agent operating manual

> **Version 1.0 — last updated 2026-11-11.** This file is law for every agent
> session in this repo. Re-stamp the date on any edit; bump the version when a rule
> or gate changes (not for snapshot facts); log rule changes in goose-deuce.md.

**Who owns which rule** (one owner per rule; everything else points):
this file — the task loop, the TASKS.md format, standards, testing, docs, version
control, the session-start reading count ("Session ritual") and the sweep cadence
("Deviations") · goose-deuce.md — the deviation trigger, entry format, tags ·
TASKS.md — current work state · docs/PLAN.md — the normative plan ·
LOOP.md, if present — loop-only rules (autonomy guard, never-push, pace/stop) ·
the guide (master folder, step 5) — the full sweep/audit checklist.

## Prime directive

Pick **one** task from TASKS.md. Complete it. Test it. Document it. Commit it. Close
it. Only then pick the next. A task is never "mostly done": it is DONE (every gate in
"Definition of Done" passed) or it is not, and the tree is never left dirty or red
*between* tasks. If you cannot finish, do not destroy the attempt: park it
recoverably (see "Blockers, questions, escalation"), restore the tree to the last
green commit, record where the work lives on the task, and stop cleanly.

## Project snapshot  *(keep every line true — this section is verified, not aspirational)*

- **Name / purpose:** `hermes-wow-plugin` — the `wow-addon-forge` Hermes Agent plugin (a
  grounded World of Warcraft: Forever addon builder: API index, static and headless checks,
  install, in-game error loop, Discord bridge) plus `Guildhall`, the guild-management addon
  built with it, for WoW players and guild officers who are not programmers.
- **Stack:** Python 3.11+ (pinned 3.14; `uv`, `pytest`, `ruff`, `mypy`; one runtime
  dependency, `lupa`, for an embedded Lua 5.1 VM), Lua 5.1 (addon code, Interface 16001,
  executed headless under `lupa.lua51`), JavaScript ESM (`@hermes/plugin-sdk` Desktop pane).
- **Agent concurrency:** single-agent (default)
- **Platforms that must work:** macOS on Apple Silicon (live WoW: Forever client, Hermes
  Desktop) and Linux (Python + headless-Lua suite in CI) — the only acceptable
  evidence for a platform is a real command run on it; anything claimed about the live game
  client needs an in-game run recorded in `docs/INGAME-CHECKLIST.md`. Windows install
  layouts are handled in code and unit-tested with hostile paths, but not claimed.
  Never claim a platform works from a run on a different one.
- **Layout:**

  | Path | What lives there |
  |---|---|
  | `src/wow_addon_forge/` | the plugin: install detection, API index, Lua 5.1 checks, headless WoW runtime, install / errors / saved variables, Discord bridge, tool and CLI handlers |
  | `addons/Guildhall/` | the guild addon (Lua 5.1 + TOC, Interface 16001) |
  | `addons/ForgeProbe/` | companion addon the plugin installs: in-game capability probe and Lua error catcher |
  | `skills/` | bundled Hermes skill (`skills/wow-addon-builder/SKILL.md`) |
  | `desktop/`, `dashboard/` | Hermes Desktop pane (`desktop/plugin.js`) and its REST backend |
  | `tests/` | pytest suite: Python units plus Lua suites executed in the embedded Lua 5.1 VM |
  | `scripts/` | loop and review-lane runners (`scripts/night-loop.sh`) |
  | `docs/PLAN.md` | the normative plan — goose-deuce.md `Plan:` fields measure against it |
  | `docs/SPEC-PLUGIN.md`, `docs/SPEC-GUILDHALL.md` | normative product specs; `docs/PLAN.md` points at them |
  | `docs/INGAME-CHECKLIST.md` | normative: the owner-run live-client acceptance steps and their recorded results |
  | `docs/mockups/` | historical: art-direction briefs and approved mockups |
  | `README.md` | install / run / test — executable as written |
  | `CHANGELOG.md` | user-facing history, one entry per task |
  | `TASKS.md` | the single work queue (format below) |
  | `goose-deuce.md` | the deviation log |
  | `LOOP.md` | loop protocol; loops read it first |
  | `HERMES-OVERLAY.md` | Hermes-native rules on top of AGENTS.md |

- **Commands** (run from repo root; every one of these must actually work):

  ```bash
  ⟨TBD step 3⟩                                          # install / bootstrap
  ⟨TBD step 3⟩                                          # launch (smoke-checkable)
  ⟨TBD step 3⟩                                          # inner loop while iterating
  ⟨TBD step 3⟩                                          # the pre-commit gate
  ⟨TBD step 3⟩                                          # static gates — check mode
                                                        # only; rewrites run BEFORE
                                                        # staging, never as the gate
  ⟨TBD step 3⟩                                          # measures against the floor
  ⟨TBD step 3⟩                                          # Hermes plugin validation gate
  ```

- **Coverage floor:** ⟨TBD step 3⟩% on `src/wow_addon_forge/` lines — measured by the
  coverage command above. Set from the measured number, not a wish. The floor only
  ratchets up; a task may not lower it. (Other sections point here; this line is
  the single owner of the number.)
- **Foot-guns already paid for** *(append as they are discovered — this list is why
  the next session doesn't pay twice)*:
  - **WoW: Forever is not Classic.** Client 1.60.1, `## Interface: 16001`, game type
    `camelot`, retail 12.1.5 ("Midnight") API with secret values. `COMBAT_LOG_EVENT_UNFILTERED`
    is restricted and `CombatLogGetCurrentEventInfo` is absent. Never write addon code from
    memory of Classic or pre-12.0 APIs: look every call and event up in the API index first.
  - **Addons have no network or file I/O.** Game → outside is SavedVariables, flushed only on
    `/reload` or logout. Outside → game is a data `.lua` file inside the addon folder that the
    TOC already lists (re-read on `/reload`; a NEW file needs a client restart).
  - **System `lua` and `luac` are 5.5 — useless for WoW.** Every Lua check and test runs in the
    embedded Lua 5.1 VM (`lupa.lua51`), never the system interpreter.
  - Hermes `PluginManager` skips `register(ctx)` for `kind: model-provider`; the root
    `plugin.yaml` stays `kind: standalone`.
  - `hermes plugins validate` enforces the catalog rules: `provides_tools` must match the
    `ctx.register_tool` calls 1:1; `desktop/plugin.js` may import only `@hermes/plugin-sdk`,
    `react` and `react/jsx-runtime`; no committed `.pyc` or compiled binary (Rule 17).
  - Global git config on this machine has `init.defaultbranch=22`; always `git init -b main`.
  - `muse_turn` only accepts a workspace inside the session cwd: start sessions with
    `--in` this repo.
  - Working reference for every Hermes plugin surface (`register_tool`, `register_command`,
    `register_cli_command`, `register_skill`, dashboard API, Desktop pane):
    `/Users/auston/Development Projects/hermes-coreai` — read it, never edit it.

## Session ritual

**Start — read before you touch anything, in this order:**
1. This file, top to bottom.
2. TASKS.md — the queue and anything already DOING or BLOCKED.
3. The 3 most recent goose-deuce.md entries — the top 3 under its `## Log`.
   (This line owns the count; other files point here.)
4. `git log --oneline -10` and `git status` — the tree must be clean; if it isn't,
   stop and report before doing anything else.
5. If a task is already `[~]` DOING, it is a stale claim from a dead session
   (older than 24h, or no session is running): check `git log` — if its work
   shipped, close it `[x]` with a note about the lapse; if not, reset it to `[ ]`,
   note the abandoned claim on the task, and log a `[process]` entry in
   goose-deuce.md. Never open a second task while one is genuinely `[~]`.
6. Loop sessions (`/loop`, autonomous) read
   `LOOP.md` before the first iteration.
7. After this ritual, read `HERMES-OVERLAY.md` — its rules
   add to, never replace, this file.

**End — leave nothing in flight:**
1. Every started task is DONE and committed, or parked per "Blockers, questions,
   escalation" with its status and location recorded in TASKS.md. No dirty tree,
   no red suite, no half-claimed task.
2. Statuses in TASKS.md match reality; anything discovered-but-not-done is filed as
   a new task, not carried in your head.
3. Report per "Reporting standards" below.

## The task loop

One iteration = one TASKS.md item, finished completely.

1. **PICK** — the first `[ ]` item in `## Now` whose `Depends:` tasks are all `[x]`
   and whose `Gated:` is `none` — unless the session was pointed at a specific
   task. Drop to `## Later` only when `## Now` is empty. Read the task's linked
   plan/context doc before writing code. **If nothing is eligible:** when
   docs/PLAN.md has an undecomposed phase, seed the board from it (a board-only
   commit, `T-###: seed backlog`) and stop for owner review; otherwise report the
   board state and the smallest owner decision that would unblock it, and end the
   session. Never invent work.
2. **CLAIM** — set the task to `[~]` DOING with claimer + date. Single-agent repos:
   the edit rides in the working tree and lands in the task's closing commit.
   Multi-agent repos: fetch and re-read trunk's TASKS.md immediately before
   claiming, then commit the claim to the shared trunk (`T-###: claim` — a
   bookkeeping commit, see "Version control") so two sessions cannot grab the
   same task. If the claim push is rejected, fetch again — a task now claimed by
   someone else is dropped: discard your never-shared local claim commit
   (`git reset --hard @{u}` after the fetch; it rewrites nothing shared) and
   re-run PICK.
3. **PLAN** — restate the acceptance criteria in your own words *in your session
   output*; list the files you expect to touch and the tests you will add. If that
   differs from the task's `Accept`/`Touches`, update the task now — the written
   task is what step 7 measures deviation against. If the criteria are ambiguous
   or the plan looks wrong, stop and escalate — do not guess on decisions that are
   hard to reverse.
4. **IMPLEMENT** — smallest complete change that satisfies the criteria, to the
   standards in "Engineering standards". No drive-by fixes: anything broken that
   you find outside the task's scope becomes a new TASKS.md item, not a detour —
   unless it blocks this task, in which case fix it and record the scope change in
   goose-deuce.md.
5. **TEST** — per "Testing protocol". Fast suite while iterating; the full
   canonical gate before commit. Red = fix or revert. Never end an iteration red.
6. **DOCUMENT** — per "Documentation protocol". Every document the change touches
   is updated in this same iteration: README, CHANGELOG.md, docs, this file.
7. **RECONCILE** — did anything deviate from the task as written, your step-3
   plan, docs/PLAN.md, or the standards? If yes: goose-deuce.md entry now, in this
   commit, per its rules — correct TASKS.md now, and amend docs/PLAN.md now if the
   deviation falsifies a statement in it (otherwise the sweep folds it in; the
   entry says which). If no: the commit body will say "Deviations: none", and it
   must be true.
8. **REVIEW** — stage exactly the task's blast radius (`git add` the named files;
   check `git status --short` for strays), then re-read the whole staged diff
   (`git diff --staged`) as a hostile reviewer: wrong logic, missed call sites,
   broken invariants, untested paths, comments claiming things the tests don't
   prove. Fix findings, re-stage, re-run the gate.
9. **COMMIT** — run the "Definition of Done" checklist. Stage TASKS.md with this
   task set to `[x]` DONE `(<YYYY-MM-DD>, this commit)` — the literal token
   `this commit`, since the hash cannot exist inside the commit that creates it
   (goose-deuce.md uses the same device). If this close hits the sweep cadence
   ("Deviations"), promote the standing sweep task to the top of `## Now` — flip
   its `Gated: cadence` to `none` — in the same staged TASKS.md edit, so the
   promotion has a commit home. One task, one commit, message per "Version
   control".
10. **NEXT** — pick the next eligible item (the sweep task, if step 9 just
    promoted it), or land the session per "Session ritual — End".

## The task board — TASKS.md

The single work queue. If work isn't in TASKS.md, it doesn't exist; if a status is
wrong, the board is lying — fix it in the same commit as the work.

**Statuses:**

| Mark | Meaning |
|---|---|
| `[ ]` | TODO — eligible when `Depends:` are done and `Gated:` is none |
| `[~]` | DOING — claimed; carries claimer + date. Exactly one open per agent — the Prime directive, enforced on the board |
| `[x]` | DONE — carries date + the literal `this commit` at close; recover the real hash later with `git log --oneline -- TASKS.md` when citing it |
| `[!]` | BLOCKED — carries the blocker and, if a decision is needed, the question |
| `[-]` | DROPPED — carries the goose-deuce.md entry (date + title) that explains why |

A status change moves the task to the matching section in the same edit — statuses
and sections never disagree.

**Format** — the fenced block below is the format specimen (its `<…>` are field
descriptions — never fill them; they define TASKS.md for the life of the repo).
A task is not pickable until its `Accept:` names something an agent can run:

```markdown
# TASKS.md — <project> work queue
<!-- One queue. New DONE entries at the top of Done. Tasks without observable
     acceptance criteria are not pickable — sharpen them first. -->

## Now
- [ ] T-012 — <imperative title, e.g. "Add retry with backoff to the fetcher">
      Why: <value in one line>
      Accept: <observable criteria — commands to run and expected result>
      Touches: <files/areas>   Depends: <T-### or none>   Gated: <none | owner | hardware | cadence>
- [~] T-011 — <title> — DOING <claimer> <YYYY-MM-DD>

## Later
- [ ] T-013 — <…>

## Blocked
- [!] T-009 — <title> — BLOCKED <YYYY-MM-DD>: <blocker>. Decision needed: <question, options, recommendation>

## Dropped
- [-] T-005 — <title> — DROPPED <YYYY-MM-DD> (goose-deuce.md <YYYY-MM-DD> "<title>")

## Done
- [x] T-010 — <title> (<YYYY-MM-DD>, this commit)
```

**Rules:** anyone may add tasks; only the claimer edits a DOING task (stale claims:
see "Session ritual"); task IDs are never reused; when a blocker clears (the owner
answers, the dependency lands), the task returns `[!]` → `[ ]` and moves back to
`## Now` in the same edit that records the answer; a DROPPED task always pairs
with a goose-deuce.md entry; deferrals and accepted shortcuts recorded in
goose-deuce.md always pair with a live TASKS.md item — owed work lives on the
board, not in the log.

## Engineering standards

- **Modular, never monolithic.** Small units with one job behind clear seams
  (one module per responsibility: install detection, API index, Lua checks, headless
  runtime, bridge, tool handlers; in the addon, one Lua file per module behind the core
  event bus and record log; injected protocols for HTTP, filesystem, clock and
  randomness). Code is written so a stranger can extend or delete
  a feature without archaeology.
- **Dependencies are injected at seams** (network, clock, randomness, filesystem,
  external services) so tests run hermetically — no live network, no real clock,
  no developer-machine state.
- **Adding a third-party dependency is a task of its own**, with the justification
  in the task (why the stdlib/existing deps won't do), a license check, and a
  pinned lockfile entry. An unplanned or substituted dependency is a goose-deuce.md
  trigger.
- **No dead code, no commented-out code, no TODO without a task ID.** A TODO is
  written `TODO(T-###):` or it is deleted and filed on the board instead.
- **Errors are handled or surfaced, never swallowed.** Nothing is silent: caps,
  truncations, fallbacks, and partial results say so in their output.
- **Style is mechanical:** `ruff format` formats, `ruff check` lints, `mypy`
  passes. Zero warnings is the baseline; a rule worth violating is worth a
  goose-deuce.md entry.

### Comment standard — timestamped, educational  *(non-negotiable)*

Every code change is timestamped in the comments and explains **what** this code
does and **why** it was written this way. The bar: a competent developer new to
this repo could reconstruct the design — and its history — from the comments alone.

- **Format:** `[YYYY-MM-DD T-###] <explanation>`, behind each language's own
  comment leader. The date is the day the comment was written or last made true
  again; the task ID ties the code to the board and the commit.
- **File headers** state the file's purpose and creation date, and name the
  invariants the file owns.
- **Every public function/class/module** gets a doc comment: what it does, why it
  exists, inputs/outputs, failure modes.
- **Non-obvious decisions get a why-comment** — trade-offs weighed, alternatives
  rejected, foot-guns defended against, with a pointer to the goose-deuce.md entry
  when the decision was a deviation.
- **Comments are maintained like code.** If you change a line, you update its
  comment and re-stamp the date; untouched comments keep their original date. A
  stale comment is a bug, and the diff review (task-loop step 8) hunts for them.
- **The honesty bound on verbosity:** never write a comment asserting behaviour
  you have not exercised. "Educational" means teaching what is true and proven,
  not narrating intentions.

```python
# GOOD — dated, educational, ties to the board, states the why + foot-gun:
# [2026-08-11 T-041] Retry only on 429/5xx, honouring Retry-After — never on other 4xx.
# BAD — narrates the obvious, no date/why:  # increment the counter
# BAD — asserts the unexercised: "the UI displays this note" (nothing reads it yet)
```

### Scope discipline

The task defines the blast radius. Refactors, renames, dependency bumps, and
"while I'm here" improvements outside the task's Touches list are new TASKS.md
items. If the task genuinely cannot be completed without widening scope, widen it
*visibly*: goose-deuce.md entry + updated task, then proceed.

## Testing protocol

- **Every behaviour change ships with tests in the same commit.** New feature →
  new tests proving the acceptance criteria. Bug fix → a regression test that
  **fails against the old code** — run it against the pre-fix tree (stash the fix
  or check out the parent) and watch it fail before you trust it. A lock that
  never failed locks nothing.
- **The full gate runs before every commit:** the full test command plus the
  static gates and the coverage command from "Project snapshot". Record the gate
  commands and their final summary lines in the commit body's `Tests:` line.
  Red = fix or revert; nothing commits red, and no test is deleted, weakened,
  skipped, or marked expected-fail to force progress — that requires a
  goose-deuce.md entry and a TASKS.md item to restore it.
- **Formatters that rewrite run before staging; the gate only verifies** (check
  mode), so nothing mutates after the reviewed diff is staged.
- **A green suite is not evidence by itself.** Tests written by the same pass that
  wrote the code encode the code's assumptions. Attack from outside them:
  adversarial diff re-read (task-loop step 8), exercise the real entry points
  (CLI, tool handlers, the plugin validator), and run `hermes plugins validate .`
  plus a headless load of every changed addon in a fresh Lua 5.1 VM — a suite's
  load order can hide a cycle the product will hit.
- **Tests are deterministic and hermetic.** Seams from "Engineering standards"
  keep them off the network and the real clock; a flaky test is a bug with its own
  task, not a re-run button. Tests never touch real user state (`~/.hermes`, the
  real WoW install and its SavedVariables, dotfiles).
- **Test the platform you claim.** A regression that only reproduces on Linux CI
  or a Windows install layout must be written so it fails on **every** OS
  (hand the code the hostile input directly instead of constructing it from the
  local environment).
- **Coverage:** floor and command live in "Project snapshot". New code arrives
  covered; the floor ratchets up, never down.

## Documentation protocol

A change isn't done until every document it invalidates is updated **in the same
commit** — a doc that says "open" about a shipped thing, or "works" about a
removed thing, is a lie with a timestamp.

Living documents and their contracts:

| Document | Contract |
|---|---|
| `README.md` | how to install, run, and test — always executable as written |
| `CHANGELOG.md` | one entry per task with a user-visible effect, format `<YYYY-MM-DD> — T-<###> — <what changed, user-visible effect>`; internal-only tasks get one line ending `(no user-visible change)` — silence is never the answer |
| `docs/PLAN.md` | the normative plan; amended when falsified (task-loop step 7) or at the sweep |
| `AGENTS.md` (this file) | the process and snapshot stay true; version line re-stamped on change |
| `TASKS.md` | statuses match reality at every commit |
| `goose-deuce.md` | every deviation, recorded per its own rules |

Docs follow the same comment standard: dated, explaining what and why, asserting
only what is true and exercised.

## Deviations — goose-deuce.md

The plan is not sacred; silent departure from it is the failure mode.
**Trigger (summary — goose-deuce.md → "The trigger" is authoritative):** anything
that departed from what the plan, the task, or a project standard said would
happen — including a step skipped or a known finding knowingly left unfixed —
gets an entry there, in the same commit that ships it. When in doubt, write the
entry.

Each entry records what was done, why, where, and what the plan said → how it now
stands. Entry format, tags, and rules are owned by goose-deuce.md — follow its
header. The contract this file adds:

- Entries land at commit time, tagged to the commit — a late-discovered deviation
  is still logged, per goose-deuce.md's rules; unlogged is the only failure.
- Every deferral and accepted shortcut pairs with a live TASKS.md item.
- The 3 most recent entries are session-start reading ("Session ritual" owns
  the count).
- **The sweep** — every 10 closed tasks or weekly, whichever comes first
  (this line owns the cadence). The sweep is board work: keep a standing
  `T-### — goose-deuce sweep` item with `Gated: cadence`; task-loop step 9
  promotes it when the cadence hits and step 10 picks it; when it closes it
  files the next one. The sweep's
  actions are in goose-deuce.md → Rules; the full audit checklist is step 5 of
  the guide at /Users/auston/Development Projects/Templates/NEW-PROJECT-GUIDE.md.

## Version control

- **One task, one commit.** No mixed concerns, no unrelated files — never
  `git add` anything outside the task's blast radius, and review
  `git status --short` for strays before staging.
- **Bookkeeping commits are one exception:** a claim (`T-###: claim`), a
  board-only seed (`T-###: seed backlog`), a park (`T-###: park — <where the
  work lives>`), or a standalone deviation entry (`goose-deuce: <title>`). They
  touch process files only, carry a one-line body, and attest nothing — no
  product code, so no gate applies.
- **The sweep task is the second, narrower exception — to one-task-one-commit
  only:** it may produce several commits (`T-###: sweep — <what>`), each an
  ordinary, fully-gated commit (the Definition of Done applies to each); its
  closing commit carries the board `[x]` and the `[process]` marker entry.
- **Branching:** trunk-based on `main` for a single-agent repo.
- **Message format** — the fenced block is a format specimen (`<…>` stays):

  ```
  T-<###>: <imperative summary, ≤72 chars>

  What: <the change, one or two lines>
  Why: <the reason — the task's Why, or tighter>
  Tests: <gate commands> → <final summaries, e.g. "218 passed; lint/format/types
         clean; coverage 84%">
  Docs: <files updated | "none invalidated">
  Deviations: <none | goose-deuce.md YYYY-MM-DD "short title">
  ```

  Every line of that body is an attestation, not a wish — write it after the gate
  runs, not before.
- **Undoing a shipped task:** a revert commit referencing the original, the work
  reopened under a **new** ID (IDs are never reused), a CHANGELOG.md correction
  entry, and a goose-deuce.md entry. Never silently re-edit or quietly patch over.
- **Push policy: never push without explicit human approval** (bookkeeping
  carve-out above excepted, multi-agent only). Commit locally; every push to a
  shared remote is publication. Scan the diff for
  secrets/keys/personal data before any approved push.
- **Never:** force-push or rewrite shared history; commit secrets, keys, or
  `.env` (keep them in Hermes `.env` / the OS keychain; the repo stores
  references only); commit generated files marked do-not-edit; touch
  the real WoW install under `/Applications/World of Warcraft` and its `WTF/`
  SavedVariables (read-only outside a task whose Accept names an install step),
  `~/.hermes/config.yaml`, `~/.hermes/.env`,
  `/Users/auston/Development Projects/hermes-coreai` (reference only), and any compiled
  binary or `.pyc` (Catalog Rule 17).

## Sub-agents and budget

Main-loop work is the default. Sub-agents are for broad mechanical sweeps and
independent adversarial review — use the cheaper routes named in HERMES-OVERLAY.md for
sweeps, and cross-check important claims with an adversarial pass rather than
trusting one context's self-report. Everything a sub-agent produces is read,
reviewed, and re-tested by the main loop before it touches the tree.

## Blockers, questions, escalation

- **Blocked?** Mark the task `[!]` with the blocker, move it to `## Blocked`, and
  pick the next eligible task. Never force progress through a gate (delete a
  failing test, bypass a check, guess at a credential).
- **Parking unfinished work** (context exhaustion, session end, newly blocked) —
  in this order, or the stash eats the note that points to it:
  (1) on the task, write the park note — what's done, what's left, where the
  work will live; (2) commit the board alone (`T-###: park — <where>`, a
  bookkeeping commit); (3) then move the product-code remainder out of the tree:
  `git stash push -u -m "T-###"` or a `wip/T-###` branch. Discarding uncommitted
  work is not reversible and needs approval like any other deletion. The next
  session resumes from the park note instead of restarting.
- **Unsure?** Present a decision, don't bury one. On the task, write: the
  question, the options, your recommendation, and what is hard to reverse about
  it. Then continue elsewhere if anything is eligible, else end the session.
- **Hard-to-reverse or outward-facing actions** — pushes, releases, deletions of
  data, purchases, anything leaving the machine — require explicit human approval
  every time. Approval for one instance is not approval for the next.

## Reporting standards

- Lead with the fact or the outcome, never with reassurance. No flattery, no
  validation openers, no reflexive apologies.
- **Proven vs. inferred, always labeled.** "Proven" means you ran it and saw the
  output — name the command and the platform. Anything else is inferred,
  compile-checked, or untested, and is labeled as such. Never report a build,
  test, or feature as working without having run it and seen it pass.
- Bad news is reported plainly, with the output that shows it: a red suite, a
  skipped step, a claim that turned out false. If something was claimed done and
  wasn't, say exactly that.

## Definition of Done  *(run before every product commit — bookkeeping commits are exempt, per "Version control". The body's `Tests:`/`Docs:`/`Deviations:` lines attest to those three; the rest are gates you run, not lines you write.)*

- [ ] Acceptance criteria demonstrably met — the task's Accept commands were run
      and showed the required result
- [ ] Full gate green: full tests + lint + format-check + types + coverage at or
      above the snapshot floor, summaries captured for the commit body
- [ ] New/changed behaviour covered by tests; any bug fix's regression test was
      seen failing against the old code
- [ ] Engineering standards held: no dead code or commented-out code, TODOs carry
      task IDs, new dependencies were their own task, errors surfaced not
      swallowed, zero warnings
- [ ] Comments meet the standard: dated `[YYYY-MM-DD T-###]`, educational,
      asserting only exercised behaviour; changed lines' comments re-stamped
- [ ] Every invalidated document updated in this commit (README, CHANGELOG.md,
      docs/PLAN.md, this file's snapshot if reality moved)
- [ ] Deviations recorded in goose-deuce.md in this commit — or
      "Deviations: none" is true
- [ ] TASKS.md staged in this commit: this task `[x]` DONE with date +
      `this commit`; discovered work filed as new tasks
- [ ] Staged diff scanned for secrets/keys/tokens (a deliberate read of
      `git diff --staged`)
- [ ] Diff re-read adversarially; no strays, no scope creep, no stale comments
- [ ] Commit message in the format above, every attestation true

**Bootstrap exception:** commits made before the full gate exists (repo scaffold
through the toolchain task) waive the gate-dependent items only; each waived item
is named honestly in the commit body (e.g. `Tests: none yet — gate arrives in
T-002`). The waiver ends the moment the snapshot commands run green.

## Maintaining this file

This file is the process; drift kills it. When reality changes — a command, a
layout, a floor, a rule — update the snapshot or the rule **in the same commit**,
re-stamp the version line, and log rule changes in goose-deuce.md. When a
foot-gun costs an hour, append it to the snapshot's foot-gun list so it never
costs two. Improvements worth keeping across projects are proposed to the owner
for the master templates at
/Users/auston/Development Projects/Templates/ — masters change only with owner
approval, and each master records its changes in its own dated header line.

**Token budget:** every character here is injected into every turn. Trim
aggressively; the snapshot is the only section that grows with the project. Re-
measure bytes each sweep and justify or trim any growth over 5%.
