-- Tracker: automatic participation for Guildhall (created 2026-11-11).
-- Purpose: turn play into Marks claims with no paperwork (SPEC-GUILDHALL
-- §8.4): a dungeon or raid boss kill, a battleground completion, every five
-- honourable kills and attendance inside a scheduled event's window each
-- author one marks.claim through the Marks module, but only when at least
-- half the group are guildmates (SPEC-GUILDHALL §7 earning rules).
-- Invariants: detection reads game state only while no addon restriction is
-- active; a detection that fires under a restriction is queued as an intent
-- and processed when the restriction lifts, so no claim exists while the
-- restriction is active. No unit or combat API result is ever used in
-- arithmetic: names and ids are compared or stringified, group counts are
-- this file's own tallies over fixed unit tokens, and the one subtraction --
-- the honourable-kill delta -- runs on the lifetime counter SPEC-GUILDHALL
-- §8.4 names for exactly that purpose, read only outside restrictions. A
-- detection whose event C_EventUtils.IsEventValid reports invalid stays off
-- and says so in the status line. This file has no tab and creates no frames
-- beyond the shared dispatcher.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Tracker = ns.Tracker or {}

-- [2026-11-11 T-022] The earning table of SPEC-GUILDHALL §7, as settings a
-- later marks.rules record can replace: dungeon boss 5, raid boss 10,
-- battleground completed 5 (the +2 win bonus needs the player's faction,
-- which no confirmed API in this build hands the tracker -- owed work is on
-- the board), one Mark per five honourable kills, event attendance 10. The
-- attendance window is the two hours from the event's start: Calendar rows
-- carry a start and no duration, so the window is pinned here rather than
-- guessed per event.
ns.Tracker.amounts = { dungeon = 5, raid = 10, bg = 5, hk = 1, attend = 10 }
ns.Tracker.hk_block = 5
ns.Tracker.attend_window = 7200

-- [2026-11-11 T-022] Local, per-session state. _pending holds intents caught
-- under a restriction (the roster is read when they are processed, not when
-- they are caught, because unit reads under a restriction can hand back
-- secret values). _seen stops this client re-authoring a key it already
-- claimed; the Marks fold dedupes per author and key regardless, so _seen
-- is a courtesy to the sync queue, never the correctness argument. _hk_seen
-- is the lifetime honourable-kill baseline the next block is measured from;
-- it starts unset so kills earned before this session never claim.
ns.Tracker._pending = {}
ns.Tracker._seen = {}
ns.Tracker._hk_seen = nil
ns.Tracker._hk_day = nil
ns.Tracker._hk_blocks = 0
ns.Tracker.status_line = ""

-- [2026-11-11 T-022] Same guarded clock seam as Marks.now and Calendar.now:
-- records and day keys ride on server time, 0 when the seam is absent.
local function now()
    if type(ns.Clock) == "table" and type(ns.Clock.now) == "function" then
        local value = ns.Clock.now()
        if type(value) == "number" then
            return value
        end
    end
    return 0
end

-- [2026-11-11 T-022] The dedupe day of SPEC-GUILDHALL §7 step 1: whole days
-- of server time. The division runs on this addon's own Clock seam value,
-- never on a unit or combat result.
local function day_key()
    return tostring(math.floor(now() / 86400))
end

-- [2026-11-11 T-022] One restriction question, asked through the core seam
-- so a missing block reads as unrestricted (the Restrict invariant) instead
-- of stalling detection forever.
local function restricted()
    if type(ns.Restrict) == "table" and type(ns.Restrict.active) == "function" then
        return ns.Restrict.active() == true
    end
    return false
end

-- [2026-11-11 T-022] Whether the client says an event exists. A missing
-- C_EventUtils reads as valid (the Dispatch:Register convention); an
-- explicit false is the only "invalid" answer, and it disables the matching
-- detection (SPEC-GUILDHALL §8.4: "only events that IsEventValid confirms").
local function event_ok(event)
    if type(C_EventUtils) == "table" and type(C_EventUtils.IsEventValid) == "function" then
        local ok, valid = pcall(C_EventUtils.IsEventValid, event)
        return ok and valid == true
    end
    return true
end

-- [2026-11-11 T-022] A unit's Name-Realm, or nil when the token names nobody
-- or the answer is a secret value. UnitName is secret-returning in the live
-- 1.60.1 index, so the pcall-plus-issecretvalue guard mirrors Marks'
-- self_name; the tracker additionally never calls this while restricted
-- (intents queue instead), which is the stronger half of the defence.
local function unit_full_name(unit)
    local ok, name, realm = pcall(UnitName, unit)
    if not ok or type(name) ~= "string" or name == "" then
        return nil
    end
    local secret_ok, secret = pcall(issecretvalue, name)
    if secret_ok and secret then
        return nil
    end
    if type(realm) ~= "string" or realm == "" then
        realm = ""
        local realm_ok, realm_name = pcall(GetRealmName)
        if realm_ok and type(realm_name) == "string" then
            local realm_secret_ok, realm_secret = pcall(issecretvalue, realm_name)
            if not (realm_secret_ok and realm_secret) then
                realm = realm_name
            end
        end
    end
    if realm ~= "" and not name:find("-", 1, true) then
        return name .. "-" .. realm
    end
    return name
end

-- [2026-11-11 T-022] The group as the tracker is allowed to see it: walk the
-- fixed unit tokens (player plus a superset scan, party1..40 or raid1..40), keep the distinct
-- Name-Realm identities, and tally how many UnitIsInMyGuild confirms. The
-- loop bounds are this file's constants -- GetNumGroupMembers' return is
-- never a loop bound or an operand -- and the counts are this file's own
-- integers, which is what keeps "no unit API result in arithmetic" true
-- while still letting the half-the-group rule be a comparison of tallies.
local function roster()
    local units = { "player" }
    local raid_ok, in_raid = pcall(IsInRaid)
    local prefix = raid_ok and in_raid == true and "raid" or "party"
    -- [2026-11-11 T-022] Scan a superset of tokens and dedupe by identity
    -- below: whether party1 means "first member" or "first other member",
    -- every real member is reached and tokens naming nobody read as nil.
    for i = 1, 40 do
        units[#units + 1] = prefix .. i
    end
    local total, guild_count = 0, 0
    local mates, counted = {}, {}
    for i = 1, #units do
        local full = unit_full_name(units[i])
        if full ~= nil and counted[full] == nil then
            counted[full] = true
            total = total + 1
            local guild_ok, in_guild = pcall(UnitIsInMyGuild, units[i])
            if guild_ok and in_guild == true then
                guild_count = guild_count + 1
                mates[#mates + 1] = full
            end
        end
    end
    table.sort(mates)
    return mates, total, guild_count
end

-- [2026-11-11 T-022] The §7 condition, exactly: grouped (a solo player is
-- not "a group at least half guildmates" in any sense the attestation rule
-- can use) and at least half the counted group confirmed guildmates.
local function guild_share_ok(total, guild_count)
    return total >= 2 and guild_count * 2 >= total
end

-- [2026-11-11 T-022] Instance identity for dedupe keys: the map id and the
-- instance type from GetInstanceInfo, stringified and compared only. A
-- missing or malformed answer yields "0" and "none", so key building never
-- fails on a client standing in the open world.
local function instance_tag()
    local ok, _, kind, _, _, _, _, map_id = pcall(GetInstanceInfo)
    if not ok then
        return "0", "none"
    end
    local tag = "0"
    if type(map_id) == "number" or type(map_id) == "string" then
        tag = tostring(map_id)
    end
    return tag, type(kind) == "string" and kind or "none"
end

-- [2026-11-11 T-022] Author one claim unless this session already authored
-- its key. Marks.claim does the record work (attestation mates, self-only
-- payload); the tracker only decides that play happened.
local function claim_once(key, amount, mates)
    if ns.Tracker._seen[key] == true then
        return nil
    end
    if type(ns.Marks) ~= "table" or type(ns.Marks.claim) ~= "function" then
        return nil
    end
    local id = ns.Marks.claim(key, amount, mates)
    if type(id) == "string" then
        ns.Tracker._seen[key] = true
    end
    return id
end

-- [2026-11-11 T-022] A boss intent becomes a claim when the group passes
-- the share rule. The activity word follows the instance type (a raid boss
-- pays the raid rate), and the key is (activity, instance, boss, day) so
-- every participant's client builds the identical key and the claims attest
-- each other (SPEC-GUILDHALL §7 steps 1-2).
local function process_boss(encounter)
    local mates, total, guild_count = roster()
    if not guild_share_ok(total, guild_count) then
        return nil
    end
    local tag, kind = instance_tag()
    local activity = kind == "raid" and "raid" or "dungeon"
    local key = activity .. ":" .. tag .. ":" .. encounter .. ":" .. day_key()
    return claim_once(key, ns.Tracker.amounts[activity], mates)
end

-- [2026-11-11 T-022] A battleground intent: the match tag is built only
-- from the event's own payload (winner and duration, stringified), because
-- participants must derive the same key without sharing a clock reading.
local function process_bg(match)
    local mates, total, guild_count = roster()
    if not guild_share_ok(total, guild_count) then
        return nil
    end
    local tag = instance_tag()
    return claim_once("bg:" .. tag .. ":" .. match .. ":" .. day_key(), ns.Tracker.amounts.bg, mates)
end

-- [2026-11-11 T-022] The lifetime honourable-kill counter, or nil when the
-- answer is unusable (absent API, secret value, not a number). Read only
-- outside restrictions -- the callers gate on restricted() first.
local function read_hk()
    local ok, kills = pcall(GetPVPLifetimeStats)
    if not ok or type(kills) ~= "number" then
        return nil
    end
    local secret_ok, secret = pcall(issecretvalue, kills)
    if secret_ok and secret then
        return nil
    end
    return kills
end

-- [2026-11-11 T-022] World PvP blocks: the first read only sets the
-- baseline, so a lifetime of earlier kills claims nothing. Each full block
-- of five since the baseline advances the baseline by five whether or not
-- it claims -- kills earned outside a guild group do not bank into a later
-- group (§7: "while grouped with guildmates") -- and claims one Mark when
-- the share rule passes. The key ordinal counts this client's blocks today,
-- so guildmates pvping together walk the same ordinals and attest.
local function process_hk()
    local kills = read_hk()
    if kills == nil then
        return nil
    end
    if ns.Tracker._hk_seen == nil then
        ns.Tracker._hk_seen = kills
        return nil
    end
    local today = day_key()
    if ns.Tracker._hk_day ~= today then
        ns.Tracker._hk_day = today
        ns.Tracker._hk_blocks = 0
    end
    local claimed = nil
    while kills - ns.Tracker._hk_seen >= ns.Tracker.hk_block do
        ns.Tracker._hk_seen = ns.Tracker._hk_seen + ns.Tracker.hk_block
        ns.Tracker._hk_blocks = ns.Tracker._hk_blocks + 1
        local mates, total, guild_count = roster()
        if guild_share_ok(total, guild_count) then
            claimed = claim_once("hk:" .. today .. ":" .. ns.Tracker._hk_blocks, ns.Tracker.amounts.hk, mates) or claimed
        end
    end
    return claimed
end

-- [2026-11-11 T-022] Attendance: inside a live event's window (start to
-- start + attend_window, read from the Calendar fold so cancelled events
-- are already gone) and in a group passing the share rule. Checked on
-- roster and world-entry events and callable directly, because no single
-- game event means "the event started".
function ns.Tracker.check_attendance()
    if type(ns.Calendar) ~= "table" or type(ns.Calendar.events) ~= "function" then
        return nil
    end
    local claimed = nil
    local at = now()
    local rows = ns.Calendar.events()
    for i = 1, #rows do
        local row = rows[i]
        if at >= row.starts and at <= row.starts + ns.Tracker.attend_window then
            local mates, total, guild_count = roster()
            if guild_share_ok(total, guild_count) then
                claimed = claim_once("attend:" .. row.id, ns.Tracker.amounts.attend, mates) or claimed
            end
        end
    end
    return claimed
end

-- [2026-11-11 T-022] Run one queued or fresh intent now. The day inside a
-- key is the processing day: a restriction that straddles midnight pays the
-- claim into the day it could first be authored, which is also the day
-- every other participant's client reaches when the same restriction lifts.
local function process(intent)
    if intent.kind == "boss" then
        return process_boss(intent.tag)
    elseif intent.kind == "bg" then
        return process_bg(intent.tag)
    elseif intent.kind == "hk" then
        return process_hk()
    elseif intent.kind == "attend" then
        return ns.Tracker.check_attendance()
    end
    return nil
end

-- [2026-11-11 T-022] The one entry every detection funnels through: under a
-- restriction the intent queues untouched (no roster read, no claim);
-- otherwise it processes immediately. Duplicate queued intents collapse so
-- a long encounter cannot grow the queue per event.
local function detect(kind, tag)
    if restricted() then
        local pending = ns.Tracker._pending
        for i = 1, #pending do
            if pending[i].kind == kind and pending[i].tag == tag then
                return nil
            end
        end
        pending[#pending + 1] = { kind = kind, tag = tag }
        return nil
    end
    return process({ kind = kind, tag = tag })
end

-- [2026-11-11 T-022] Flush the queue in catch order once unrestricted.
-- Called when the restriction state changes and on world entry, so a missed
-- state event cannot strand an intent for the session.
function ns.Tracker.flush()
    if restricted() then
        return 0
    end
    local pending = ns.Tracker._pending
    ns.Tracker._pending = {}
    for i = 1, #pending do
        process(pending[i])
    end
    ns.Tracker.refresh_status()
    return #pending
end

-- [2026-11-11 T-022] The detection set and the human label each status line
-- uses. GROUP_ROSTER_UPDATE, PLAYER_ENTERING_WORLD and PLAYER_LOGIN carry
-- no claim of their own: they re-run attendance and the HK baseline, so
-- they are wiring, not detections, and stay out of the status lines.
local DETECTIONS = {
    { event = "BOSS_KILL", label = "boss kills" },
    { event = "ENCOUNTER_END", label = "encounters" },
    { event = "PVP_MATCH_COMPLETE", label = "battlegrounds" },
    { event = "PLAYER_PVP_KILLS_CHANGED", label = "world pvp" },
}

-- [2026-11-11 T-022] Recompute the status lines from the client's own
-- answers right now: one line per detection, "off" naming the invalid event
-- that disabled it, plus the queued-intent count while any wait. Recomputed
-- live (never cached from load time), so an event disabled after load is
-- reported on the next read.
function ns.Tracker.status()
    local lines = {}
    for i = 1, #DETECTIONS do
        local detection = DETECTIONS[i]
        if event_ok(detection.event) then
            lines[#lines + 1] = "tracker " .. detection.label .. ": on"
        else
            lines[#lines + 1] = "tracker " .. detection.label .. ": off (" .. detection.event .. " invalid)"
        end
    end
    if #ns.Tracker._pending > 0 then
        lines[#lines + 1] = "tracker queued: " .. #ns.Tracker._pending
    end
    return lines
end

-- [2026-11-11 T-022] The single-line rendering other surfaces (a tab, a
-- slash reply) can show without knowing the table shape.
function ns.Tracker.refresh_status()
    ns.Tracker.status_line = table.concat(ns.Tracker.status(), "; ")
    return ns.Tracker.status_line
end

-- [2026-11-11 T-022] How many intents wait for a restriction to lift; the
-- observable half of "queued locally and authored when it lifts" (§8.4).
function ns.Tracker.pending_count()
    return #ns.Tracker._pending
end

-- [2026-11-11 T-022] Event wiring. Registration goes through Dispatch,
-- which itself refuses an IsEventValid-invalid event, and every handler
-- re-checks event_ok so a detection switched off mid-session stays off even
-- if a stale registration fires. Boss identity comes from the event payload
-- alone (encounterID, stringified -- BOSS_KILL and a successful
-- ENCOUNTER_END name the same fight, and the shared key makes the pair
-- author at most one claim per client).
if type(ns.Dispatch) == "table" then
    local function on_boss(event)
        return function(encounter_id, ...)
            if not event_ok(event) then
                return
            end
            if event == "ENCOUNTER_END" then
                -- [2026-11-11 T-022] ENCOUNTER_END payload order per the live
                -- index: encounterID, encounterName, difficultyID, groupSize,
                -- success -- success is fifth, compared and never computed on.
                local success = select(5, encounter_id, ...)
                if success ~= 1 and success ~= true then
                    return
                end
            end
            detect("boss", tostring(encounter_id))
        end
    end
    for i = 1, #DETECTIONS do
        ns.Dispatch:Register(DETECTIONS[i].event)
    end
    ns.Dispatch:On("BOSS_KILL", on_boss("BOSS_KILL"))
    ns.Dispatch:On("ENCOUNTER_END", on_boss("ENCOUNTER_END"))
    ns.Dispatch:On("PVP_MATCH_COMPLETE", function(winner, duration)
        if event_ok("PVP_MATCH_COMPLETE") then
            detect("bg", tostring(winner) .. ":" .. tostring(duration))
        end
    end)
    ns.Dispatch:On("PLAYER_PVP_KILLS_CHANGED", function()
        if event_ok("PLAYER_PVP_KILLS_CHANGED") then
            detect("hk", nil)
        end
    end)
    ns.Dispatch:Register("ADDON_RESTRICTION_STATE_CHANGED")
    ns.Dispatch:On("ADDON_RESTRICTION_STATE_CHANGED", function()
        ns.Tracker.flush()
    end)
    ns.Dispatch:Register("GROUP_ROSTER_UPDATE")
    ns.Dispatch:On("GROUP_ROSTER_UPDATE", function()
        detect("attend", nil)
    end)
    ns.Dispatch:Register("PLAYER_ENTERING_WORLD")
    ns.Dispatch:On("PLAYER_ENTERING_WORLD", function()
        ns.Tracker.flush()
        detect("attend", nil)
    end)
    ns.Dispatch:Register("PLAYER_LOGIN")
    ns.Dispatch:On("PLAYER_LOGIN", function()
        -- [2026-11-11 T-022] Baseline the HK counter at login (outside any
        -- restriction a fresh login can be in) so the first kills event of
        -- the session measures a delta instead of only setting the mark.
        if not restricted() and ns.Tracker._hk_seen == nil then
            ns.Tracker._hk_seen = read_hk()
        end
        detect("attend", nil)
    end)
end

ns.Tracker.refresh_status()

return ns.Tracker
