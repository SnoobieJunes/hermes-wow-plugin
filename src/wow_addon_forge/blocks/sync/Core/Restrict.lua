-- Restriction gate for @@ADDON@@ (created 2026-11-11).
-- Purpose: one question, "is any addon restriction active?", so the sync
-- pump can refuse to send without naming a regime.
-- Invariant: a missing API is treated as unrestricted, so a check that cannot
-- run does not stall the queue forever.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Restrict = ns.Restrict or {}

function ns.Restrict.active()
    if type(C_RestrictedActions) ~= "table" then
        return false
    end
    if type(C_RestrictedActions.IsAddOnRestrictionActive) ~= "function" then
        return false
    end
    local ok, active = pcall(C_RestrictedActions.IsAddOnRestrictionActive)
    return ok and active == true
end

return ns.Restrict
