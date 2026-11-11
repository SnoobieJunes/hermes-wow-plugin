# INGAME-CHECKLIST.md — live-client acceptance

Dated 2026-11-11. Normative. Only a run in the real WoW: Forever client fills a
`Result:` line. A headless pass is never recorded here.

Format of a result: `Result: PASS | FAIL | NOT RUN — <date> <build> — <what was seen>`.

## A. Probe (required; about 3 minutes)

1. Install ForgeProbe (`wow_install`), start the client, enable it on the
   character screen, log in on a guilded character.
   Result: NOT RUN
2. Type `/forge probe`, wait for "probe complete", then `/reload`.
   Result: NOT RUN
3. `wow_errors` returns the probe table: build `1.60.1`, Interface `16001`.
   Result: NOT RUN
4. Recorded by the probe — event validity and registration for
   `ENCOUNTER_END`, `BOSS_KILL`, `PLAYER_PVP_KILLS_CHANGED`, `PARTY_KILL`,
   `UNIT_DIED`, `PVP_MATCH_COMPLETE`, `GROUP_ROSTER_UPDATE`.
   Result: NOT RUN
5. Recorded by the probe — guild addon-message echo and its result enum.
   Result: NOT RUN

## B. Guildhall loads (required)

6. Guildhall is listed in AddOns, not flagged out of date, and loads with no
   Lua error (`wow_errors` shows none for it).
   Result: NOT RUN
7. `/gh` opens the window; every tab opens without an error.
   Result: NOT RUN
8. A board post survives `/reload`.
   Result: NOT RUN

## C. Sync (required for the demo)

9. A second guildmate with Guildhall sees a board post within 10 seconds.
   Result: NOT RUN
10. A guildmate who logs in afterwards receives it.
    Result: NOT RUN

## D. Discord bridge (required for the demo)

11. A board post made in game appears in the Discord channel after `/reload`.
    Result: NOT RUN
12. A post pushed from Discord appears on the board after `/reload`.
    Result: NOT RUN

## E. Tracker (optional; needs play time)

13. A dungeon run with a guildmate produces a Marks claim after leaving the
    instance.
    Result: NOT RUN
14. A battleground produces a claim.
    Result: NOT RUN
15. Nothing is sent and no error is raised during combat or inside an instance.
    Result: NOT RUN
