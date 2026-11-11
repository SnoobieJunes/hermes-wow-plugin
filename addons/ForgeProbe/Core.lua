-- ForgeProbe: capability probe and Lua error catcher for wow-addon-forge (created 2026-11-11).
-- Purpose: record live client build/event/API/restriction/addon-message facts and capture Lua
-- errors plus ADDON_ACTION_FORBIDDEN / ADDON_ACTION_BLOCKED into a bounded 200-entry SavedVariables
-- ring so Hermes can inspect real WoW: Forever behaviour through `wow_errors`.
-- Invariants owned by this file:
-- - `ForgeProbeDB.errors` never exceeds 200 entries; repeated `(addon, message)` pairs increment
--   `count` and refresh `time` instead of flooding the ring.
-- - Every capability probe step is guarded with `pcall` and `C_EventUtils.IsEventValid`, so an
--   absent or restricted API/event is recorded as data rather than raising a secondary Lua error.
-- - Slash command `/forge` (empty arg, `probe`, `status`, `clear`) is safe during `wow_check`.

local ADDON_NAME, ns = ...

local MAX_ERRORS = 200
local ECHO_PREFIX = "FORGEPROBE"

-- [2026-11-11 T-009] Events listed in docs/INGAME-CHECKLIST.md section A and docs/PLAN.md §3.
local PROBED_EVENTS = {
    "ENCOUNTER_END",
    "BOSS_KILL",
    "PLAYER_PVP_KILLS_CHANGED",
    "PARTY_KILL",
    "UNIT_DIED",
    "PVP_MATCH_COMPLETE",
    "GROUP_ROSTER_UPDATE",
    "NEW_MOUNT_ADDED",
    "ADDON_RESTRICTION_STATE_CHANGED",
    "CHAT_MSG_ADDON",
    "COMBAT_LOG_EVENT_UNFILTERED",
}

-- [2026-11-11 T-009] Core C API namespaces and globals Guildhall and scaffolded addons rely on.
local PROBED_APIS = {
    "C_ChatInfo.SendAddonMessage",
    "C_ChatInfo.RegisterAddonMessagePrefix",
    "C_RestrictedActions.IsAddOnRestrictionActive",
    "C_RestrictedActions.GetAddOnRestrictionState",
    "C_EventUtils.IsEventValid",
    "issecretvalue",
    "UnitIsInMyGuild",
    "GetGuildRosterInfo",
    "GetPVPLifetimeStats",
    "C_Calendar",
    "C_TradeSkillUI",
    "C_Item.GetItemInfo",
    "C_UI.Reload",
}

local RESTRICTION_NAMES = {
    { key = "Combat", fallback = 0 },
    { key = "Encounter", fallback = 1 },
    { key = "ChallengeMode", fallback = 2 },
    { key = "PvPMatch", fallback = 3 },
    { key = "Map", fallback = 4 },
    { key = "Chat", fallback = 5 },
}

ns.name = ADDON_NAME
ns.echoSeq = 0
ns.pendingEchoToken = nil

local function chatPrint(text)
    if DEFAULT_CHAT_FRAME and DEFAULT_CHAT_FRAME.AddMessage then
        DEFAULT_CHAT_FRAME:AddMessage(text)
    end
end

local function ensureDB()
    if type(ForgeProbeDB) ~= "table" then
        ForgeProbeDB = {}
    end
    if type(ForgeProbeDB.errors) ~= "table" then
        ForgeProbeDB.errors = {}
    end
    if type(ForgeProbeDB.probe) ~= "table" then
        ForgeProbeDB.probe = {}
    end
    return ForgeProbeDB
end

-- Extract the originating addon folder name from a WoW or headless chunk path.
-- Why: both `Interface/AddOns/Foo/Bar.lua:10:` (live client) and `Foo/Bar.lua:10:` (headless VM)
-- appear in error messages and tracebacks; skipping ForgeProbe's own wrapper lines attributes the
-- error to the addon that actually raised it.
local function inferAddon(message, stack)
    local combined = tostring(message or "") .. "\n" .. tostring(stack or "")
    local fallback = nil
    for line in string.gmatch(combined, "[^\r\n]+") do
        local live = string.match(line, "[Aa]dd[Oo]ns[/\\]([^/\\:%s]+)[/\\]")
        local candidate = live or string.match(line, "([A-Za-z0-9_!%-]+)/[^:\r\n]+:%d+:")
        if candidate then
            if candidate ~= ADDON_NAME then
                return candidate
            end
            fallback = fallback or candidate
        end
    end
    return fallback or "unknown"
end

-- Record one error or blocked-action event into the bounded 200-entry ring.
local function recordError(rawText, explicitStack, explicitAddon)
    local db = ensureDB()
    local ring = db.errors
    local full = tostring(rawText or "unknown error")
    local firstNl = string.find(full, "\n", 1, true)
    local message = full
    local stack = tostring(explicitStack or "")
    if firstNl then
        message = string.sub(full, 1, firstNl - 1)
        if stack == "" then
            stack = string.sub(full, firstNl + 1)
        end
    end
    if stack == "" and type(debugstack) == "function" then
        local ok, trace = pcall(debugstack, 3)
        if ok and type(trace) == "string" then
            stack = trace
        end
    end
    local addon = explicitAddon or inferAddon(message, stack)
    local now = GetServerTime()

    for i = #ring, 1, -1 do
        local existing = ring[i]
        if type(existing) == "table"
            and existing.message == message
            and existing.addon == addon then
            existing.count = (tonumber(existing.count) or 1) + 1
            existing.time = now
            if stack ~= "" then
                existing.stack = stack
            end
            table.remove(ring, i)
            ring[#ring + 1] = existing
            return
        end
    end

    ring[#ring + 1] = {
        message = message,
        stack = stack,
        addon = addon,
        count = 1,
        time = now,
    }
    while #ring > MAX_ERRORS do
        table.remove(ring, 1)
    end
end

-- [2026-11-11 T-009] Install the global Lua error hook at file load time so load-time errors in
-- addons listed after ForgeProbe are captured before ADDON_LOADED or PLAYER_LOGIN even fires.
local previousHandler = geterrorhandler()
local inErrorHook = false
seterrorhandler(function(err)
    if not inErrorHook then
        inErrorHook = true
        pcall(recordError, err, nil, nil)
        inErrorHook = false
    end
    if type(previousHandler) == "function" then
        pcall(previousHandler, err)
    end
end)

-- Check whether a dotted (`C_ChatInfo.SendAddonMessage`) or bare (`issecretvalue`) API exists.
-- Guarded with `pcall` so strict `__index` metatables in the headless runtime never raise out.
local function checkApiPresent(apiName)
    local nsName, member = string.match(apiName, "^([^%.]+)%.(.+)$")
    if nsName then
        local ok, exists = pcall(function()
            local tbl = rawget(_G, nsName) or _G[nsName]
            if type(tbl) ~= "table" then
                return false
            end
            local val = tbl[member]
            return val ~= nil
        end)
        return ok and exists == true
    end
    local ok, exists = pcall(function()
        local val = rawget(_G, apiName)
        if val ~= nil then
            return true
        end
        return _G[apiName] ~= nil
    end)
    return ok and exists == true
end

local probeScratchFrame = CreateFrame("Frame")

-- Run the full capability probe and store plain data into `ForgeProbeDB.probe`.
function ns:RunProbe(announce)
    local db = ensureDB()
    local version, buildNum, buildDate, interfaceNum = GetBuildInfo()

    local eventsReport = {}
    for _, evName in ipairs(PROBED_EVENTS) do
        local validOk, isValid = pcall(C_EventUtils.IsEventValid, evName)
        local valid = validOk and isValid == true
        local registered = false
        if valid then
            local regOk = pcall(probeScratchFrame.RegisterEvent, probeScratchFrame, evName)
            if regOk then
                registered = true
                pcall(probeScratchFrame.UnregisterEvent, probeScratchFrame, evName)
            end
        end
        eventsReport[evName] = {
            valid = valid,
            registered = registered,
        }
    end

    local apisReport = {}
    for _, apiName in ipairs(PROBED_APIS) do
        apisReport[apiName] = checkApiPresent(apiName)
    end

    local restrictionsReport = {}
    local enumTbl = rawget(_G, "Enum")
    local restrictionEnum = type(enumTbl) == "table" and rawget(enumTbl, "AddOnRestrictionType") or nil
    for _, item in ipairs(RESTRICTION_NAMES) do
        local regimeId = item.fallback
        if type(restrictionEnum) == "table" and type(restrictionEnum[item.key]) == "number" then
            regimeId = restrictionEnum[item.key]
        end
        local okActive, active = pcall(C_RestrictedActions.IsAddOnRestrictionActive, regimeId)
        local okState, state = pcall(C_RestrictedActions.GetAddOnRestrictionState, regimeId)
        restrictionsReport[item.key] = {
            active = okActive and active == true,
            state = okState and tonumber(state) or 0,
        }
    end

    C_ChatInfo.RegisterAddonMessagePrefix(ECHO_PREFIX)
    ns.echoSeq = ns.echoSeq + 1
    local token = "probe:" .. tostring(GetServerTime()) .. ":" .. tostring(ns.echoSeq)
    local echoReport = {
        prefix = ECHO_PREFIX,
        token = token,
        sent = false,
        send_result = nil,
        echo_received = false,
        echo_sender = nil,
        skipped_reason = nil,
    }
    db.probe = {
        probed_at = GetServerTime(),
        build = {
            version = tostring(version or ""),
            build = tostring(buildNum or ""),
            date = tostring(buildDate or ""),
            interface = tonumber(interfaceNum) or 0,
        },
        events = eventsReport,
        apis = apisReport,
        restrictions = restrictionsReport,
        echo = echoReport,
    }

    local anyRestrictedOk, anyRestricted = pcall(C_RestrictedActions.IsAddOnRestrictionActive)
    if not IsInGuild() then
        echoReport.skipped_reason = "not-in-guild"
    elseif anyRestrictedOk and anyRestricted then
        echoReport.skipped_reason = "restricted"
    else
        ns.pendingEchoToken = token
        local sendOk, result = pcall(
            C_ChatInfo.SendAddonMessage, ECHO_PREFIX, token, "GUILD"
        )
        echoReport.sent = sendOk
        echoReport.send_result = sendOk and tonumber(result) or -1
    end

    if announce then
        chatPrint("ForgeProbe: probe complete")
    end
    return db.probe
end

local eventFrame = CreateFrame("Frame")
eventFrame:RegisterEvent("ADDON_LOADED")
eventFrame:RegisterEvent("PLAYER_LOGIN")
eventFrame:RegisterEvent("CHAT_MSG_ADDON")
eventFrame:RegisterEvent("ADDON_ACTION_FORBIDDEN")
eventFrame:RegisterEvent("ADDON_ACTION_BLOCKED")

eventFrame:SetScript("OnEvent", function(_, event, ...)
    if event == "ADDON_LOADED" then
        local loadedName = ...
        if loadedName == ADDON_NAME then
            ensureDB()
            C_ChatInfo.RegisterAddonMessagePrefix(ECHO_PREFIX)
        end
    elseif event == "PLAYER_LOGIN" then
        ns:RunProbe(false)
    elseif event == "CHAT_MSG_ADDON" then
        local prefix, text, _, sender = ...
        if prefix == ECHO_PREFIX and ns.pendingEchoToken and text == ns.pendingEchoToken then
            local db = ensureDB()
            if type(db.probe) == "table" and type(db.probe.echo) == "table" then
                db.probe.echo.echo_received = true
                db.probe.echo.echo_sender = tostring(sender or "")
            end
        end
    elseif event == "ADDON_ACTION_FORBIDDEN" or event == "ADDON_ACTION_BLOCKED" then
        local badAddon, badFunc = ...
        local who = tostring(badAddon or "unknown")
        local fn = tostring(badFunc or "unknown")
        recordError(event .. ": " .. who .. " called " .. fn, "", who)
    end
end)

SLASH_FORGEPROBE1 = "/forge"
SlashCmdList["FORGEPROBE"] = function(msg)
    local arg = string.lower(string.match(tostring(msg or ""), "^%s*(%S*)") or "")
    if arg == "probe" then
        ns:RunProbe(true)
    elseif arg == "clear" then
        local db = ensureDB()
        wipe(db.errors)
        chatPrint("ForgeProbe: cleared captured errors")
    else
        local db = ensureDB()
        chatPrint("ForgeProbe: " .. tostring(#db.errors) .. " error(s) captured")
    end
end
