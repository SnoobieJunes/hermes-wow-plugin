# HERMES-OVERLAY.md — Hermes-native rules on top of AGENTS.md

AGENTS.md rules all apply, unabridged. This file is true only because the harness
is Hermes Agent. Its six additions:

1. **Memory boundary.** Hermes persists memory across sessions and injects it into
   every turn (the `memory` tool). Project state — the board, deviations, the plan,
   claims, park notes — lives ONLY in the repo files (TASKS.md, goose-deuce.md,
   docs/PLAN.md): portable, auditable, multi-agent-safe. Hermes memory holds only
   cross-project durable facts (owner identity, machine/env facts, standing
   conventions, foot-guns that recur across repos). Never write project-specific
   state to Hermes memory — it is not portable, it leaks into other projects, and
   it is not in the commit audit trail. A "foot-gun" that is repo-specific stays in
   AGENTS.md's snapshot; one that recurs across repos is proposed to the masters
   (AGENTS.md → Maintaining this file), not parked in memory.

2. **Session start.** Resume the project's own Hermes session (`hermes --resume`,
   or the desktop session list) rather than starting cold. Hermes memory is loaded
   by the runtime — do not re-derive it, but treat it as a cache: project truth is
   always re-read from the files (run AGENTS.md → Session ritual in full). Memory
   and the files may never disagree; if they do, the files win and the memory entry
   is corrected.

3. **Delegation = `delegate_task`.** Sub-agents are spawned with the `delegate_task`
   tool; it is the mechanism behind AGENTS.md → Sub-agents and budget. Default
   concurrency is 3 children; for a broad mechanical sweep spawn them in parallel
   and re-test every result before it touches the tree (unchanged from AGENTS.md).
   For long-running autonomous work (hours/days), spawn `hermes` processes via tmux
   per LOOP.md instead of a long delegate loop. A sub-agent's self-report is not
   proof — verify against the gate.

4. **The sweep = a scheduled `cronjob`.** The standing sweep (AGENTS.md →
   Deviations cadence) may run as a Hermes cronjob (`cronjob_manage`) pointed at the
   repo, in addition to the cadence line. A scheduled sweep is board work per
   goose-deuce.md → Rules; it commits like any sweep and NEVER pushes (the never-push
   policy is unchanged). If no cronjob is configured, the cadence line in AGENTS.md
   governs as written.

5. **Cross-project improvements = skills.** When a procedure proves reusable across
   projects, its Hermes-native home is a skill (`skill_manage`, installed under
   $HERMES_HOME/skills, loaded on relevance) — proposed to the owner as a diff,
   applied on approval, exactly like the master templates. Repo files stay the
   source of project law; a skill carries the repeatable procedure, never the law.

6. **Routing for this repo.** Three usage buckets, each with one job. Bulk drafting
   (new modules, test suites, documents) goes to `muse_turn` first: load the
   `muse-harness-orchestration` skill and follow it — chunk to one deliverable per call,
   files on disk are the success criterion, inspect the workspace before any retry, and
   fall back to drafting in the driver only on reported exhaustion or two verified-empty
   stalls. The driver session (the builder) reviews, runs the gate and commits; a Muse
   self-report is never proof. `delegate_task` runs in Advanced Delegation's
   model-routes mode when the owner has switched it on: the tool then offers an `option`
   per task. Pick `claude` to implement, `grok` for adversarial review and second
   opinions (a different model family than the implementer, on purpose), and `free-best`
   for mechanical sweeps. A task that names no option runs on the configured default.
   When the tool offers no `option`, children inherit the driver's model. Muse Wonder
   Full is not a route: it is reached only through `muse_turn`. Every child result is
   reviewed and re-tested before it touches the tree.

**Approval posture.** Hermes `write_approval` and the security settings are the
runtime enforcement behind AGENTS.md → Version control and → Blockers. Destructive
or outward-facing actions (push, release, delete, purchase, anything leaving the
machine) require explicit human approval every time — the Hermes approval prompt
backs this rule, but the rule lives in AGENTS.md; do not rely on the prompt alone.

**Stop / park.** On context exhaustion or a block, park per AGENTS.md → Blockers
(park note → board-only commit → stash). Hermes conversation state does not survive
a restart as work state — the park note in TASKS.md is the source of truth, not the
session transcript. The next session resumes from the note.

**Token budget.** This overlay is injected every Hermes session via the hook. Keep it
thin — it adds only Hermes-native rules; everything else points at AGENTS.md.
