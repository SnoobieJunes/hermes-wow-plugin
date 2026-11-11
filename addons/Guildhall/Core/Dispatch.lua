-- Event dispatcher for Guildhall (created 2026-11-11).
-- Purpose: one frame fans WoW events out to listeners, and an internal bus carries
-- messages that are not WoW events.
-- Invariants: an unknown or invalid event is not registered; a listener error is
-- reported and does not stop the other listeners.

local ADDON_NAME, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Dispatch = { listeners = {}, bus = {} }

function ns.Dispatch:On(event, fn)
    if type(event) ~= "string" or type(fn) ~= "function" then
        return nil, "On needs an event name and a function"
    end
    local list = self.listeners[event]
    if list == nil then
        list = {}
        self.listeners[event] = list
    end
    list[#list + 1] = fn
    return true
end

function ns.Dispatch:Emit(event, ...)
    local list = self.bus[event]
    if type(list) ~= "table" then
        return 0
    end
    local delivered = 0
    for i = 1, #list do
        local ok = pcall(list[i], ...)
        if ok then
            delivered = delivered + 1
        end
    end
    return delivered
end

function ns.Dispatch:Listen(event, fn)
    if type(event) ~= "string" or type(fn) ~= "function" then
        return nil, "Listen needs an event name and a function"
    end
    local list = self.bus[event]
    if list == nil then
        list = {}
        self.bus[event] = list
    end
    list[#list + 1] = fn
    return true
end

local function fanout(event, ...)
    local list = ns.Dispatch.listeners[event]
    if type(list) ~= "table" then
        return
    end
    for i = 1, #list do
        pcall(list[i], ...)
    end
end

local frame = CreateFrame("Frame")
ns.Dispatch.frame = frame

function ns.Dispatch:Register(event)
    if type(C_EventUtils) == "table" and type(C_EventUtils.IsEventValid) == "function" then
        local ok, valid = pcall(C_EventUtils.IsEventValid, event)
        if not ok or valid ~= true then
            return false
        end
    end
    local ok = pcall(frame.RegisterEvent, frame, event)
    return ok == true
end

frame:SetScript("OnEvent", function(_, event, ...)
    fanout(event, ...)
end)

ns.Dispatch:Register("ADDON_LOADED")
ns.Dispatch:Register("PLAYER_LOGIN")
ns.Dispatch:On("ADDON_LOADED", function(loaded)
    if loaded == ADDON_NAME then
        ns.Dispatch:Emit("ready", ADDON_NAME)
    end
end)
