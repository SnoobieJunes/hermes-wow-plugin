# LOOP.md — protocol for `/loop` and autonomous sessions

AGENTS.md rules all apply, unabridged. One iteration = one full pass of
AGENTS.md → The task loop (all ten steps, PICK→NEXT) over one TASKS.md item —
never breadth-first, never a shortened loop. Deviations land in goose-deuce.md
per its rules, in the same commit, exactly as in an interactive session.

What a loop adds on top:

1. **Autonomy guard** — PICK skips `Gated: owner` and `Gated: hardware` items
   unless the loop was pointed at one; a loop never answers its own escalations.
2. **Verification** — fast inner loop while iterating: `uv run pytest -x -q`.
   Before commit, the full gate exactly as AGENTS.md → Project snapshot writes
   it, foot-gun flags included. Red = fix or revert; never end an iteration red.
3. **Push** — loops never push product commits. Not with prior approval, not
   once, not ever: pushing is an interactive-session action under AGENTS.md →
   Version control, and blanket authorization given at launch does not survive
   into iterations. The one carve-out is AGENTS.md's own: in a multi-agent repo,
   the standing-approved claim/board bookkeeping pushes still apply — or the
   loop's claims guard nothing.
4. **Budget** — subagents per AGENTS.md → Sub-agents and budget. Don't leave an
   item half-open at context exhaustion: finish it, or park it per AGENTS.md →
   Blockers, questions, escalation before the window closes.
5. **Pace** — schedule the next wakeup only after the tree is green and
   committed.
6. **Stop** — if two consecutive iterations yield no committable work
   (everything eligible needs the owner or hardware), park the loop: report the
   board state and the smallest owner decision that unblocks it (AGENTS.md →
   The task loop → PICK), and end. A stuck loop parks itself instead of
   spinning.
7. **Untouchables** — the real WoW install and its `WTF/` SavedVariables (a loop never
   installs into the live game; install steps are `Gated: owner`), `~/.hermes/config.yaml`
   (the plugin is already linked and enabled; nothing else there changes),
   `~/.hermes/.env`, `/Users/auston/Development Projects/hermes-coreai`, the generated API
   index cache (regenerate it, never hand-edit it), and `docs/INGAME-CHECKLIST.md` result
   lines (only an in-game run fills them).
8. **Review inbox** — a separate read-only review lane writes findings to `.review/`
   (git-ignored; it never commits). Before PICK, file every unfiled `.review/*.md` finding
   as a TASKS.md item at the top of `## Now` — the board edit rides in the next closing
   commit — and move the finding file to `.review/filed/`. Findings are never fixed as
   drive-bys.
9. **In-game truth** — nothing about the live client is claimed from a headless run. A task
   whose Accept needs the game is `Gated: owner`; its headless half ships and the in-game
   half becomes a line in `docs/INGAME-CHECKLIST.md`.
10. **Plugin first, then the addon through the plugin** — no file under `addons/Guildhall`
    is created or changed before T-041 (the plugin-done gate) is closed. After it, addon
    work goes through the plugin's own tools, called in the session: `wow_new` creates,
    `wow_api` answers every API question, `wow_check` and `wow_test` verify, and their
    verdicts are quoted in the commit body. The addon is the plugin's acceptance test: a
    defect or a missing capability found while building it is filed as a plugin task at
    the top of `## Now` and fixed before the addon task resumes. Never work around the
    plugin by hand.
11. **Drafting ahead** — while the gate runs on the claimed task, children may draft the
    next eligible tasks, but only into `.loop/drafts/T-###/` (git-ignored), never into the
    working tree. A draft is untrusted input: it is reviewed and applied only after its
    task is claimed, and it changes nothing about one claimed task and one commit at a
    time.
