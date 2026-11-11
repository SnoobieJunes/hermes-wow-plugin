-- Server-time seam for Guildhall (created 2026-11-11).
-- Purpose: one function reads the clock so tests and later blocks do not call
-- GetServerTime themselves.
-- Invariant: now() returns a number. A missing GetServerTime returns 0, not an error.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Clock = {}

function ns.Clock.now()
    if type(GetServerTime) ~= "function" then
        return 0
    end
    local ok, value = pcall(GetServerTime)
    if ok and type(value) == "number" then
        return value
    end
    return 0
end
