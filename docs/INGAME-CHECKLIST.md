# INGAME-CHECKLIST.md — live-client acceptance

Dated 2026-11-11. Normative. Only a run in the real WoW: Forever client fills a
`Result:` line. A headless pass is never recorded here.

Format of a result: `Result: PASS | FAIL | NOT RUN — <date> <build> — <what was seen>`.

## A. Probe (required; about 3 minutes)

1. Install ForgeProbe (`wow_install`), start the client, enable it on the
   character screen, log in on a guilded character.
   Result: PASS — 2026-11-11 1.60.1.70888 — ForgeProbe and Guildhall installed, enabled and ticked on a guilded character; neither flagged out of date (owner addon-list screenshot)
2. Type `/forge probe`, wait for "probe complete", then `/reload`.
   Result: PASS — 2026-11-11 1.60.1.70888 — manual `/forge probe` completed (token probe:1794431227:2) and the probe table returned via wow_errors after /reload; the probe also auto-ran at login — that auto-run is removed as of T-052
3. `wow_errors` returns the probe table: build `1.60.1`, Interface `16001`.
   Result: PASS — 2026-11-11 1.60.1.70888 — build version 1.60.1, build 70888, date Nov 9 2026, Interface 16001
4. Recorded by the probe — event validity and registration for
   `ENCOUNTER_END`, `BOSS_KILL`, `PLAYER_PVP_KILLS_CHANGED`, `PARTY_KILL`,
   `UNIT_DIED`, `PVP_MATCH_COMPLETE`, `GROUP_ROSTER_UPDATE`.
   Result: PASS — 2026-11-11 1.60.1.70888 — all 11 probed events valid (incl. COMBAT_LOG_EVENT_UNFILTERED); registration recorded true, BUT 4 attempts per run were blocked (ADDON_ACTION_FORBIDDEN, count 8 over two runs) so those 4 `registered` values are unreliable pre-T-052; T-052 records IsEventRegistered truth — the 4 names are owed to the T-036 retest
5. Recorded by the probe — guild addon-message echo and its result enum.
   Result: PASS — 2026-11-11 1.60.1.70888 — guild echo sent=true, send_result=0, echo_received=true; sender arrived as "Friar Baggins" (space, no -Realm suffix) — identity-format risk filed as T-054

## B. Guildhall loads (required)

6. Guildhall is listed in AddOns, not flagged out of date, and loads with no
   Lua error (`wow_errors` shows none for it).
   Result: PASS — 2026-11-11 1.60.1.70888 — listed, not out of date; wow_errors shows no Guildhall Lua errors (the only entries are ForgeProbe's own ADDON_ACTION_FORBIDDEN records)
7. `/gh` opens the window; every tab opens without an error.
   Result: FAIL — 2026-11-11 1.60.1.70888 — /gh opened the window (status line "sync 0 queue 0 bridge idle" rendered) but no tab buttons existed and no tab was shown, so Board/Calendar/Marks were unreachable; fixed in T-053 (tab rail + containers), live retest pending
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
