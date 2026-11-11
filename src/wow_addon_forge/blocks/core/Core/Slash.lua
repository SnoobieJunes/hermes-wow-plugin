-- Slash commands for @@ADDON@@ (created 2026-11-11).
-- Purpose: register the addon's slash command (@@SLASH@@, stamped by wow_new;
-- [2026-11-11 T-046] an unstamped copy falls back to /<addon>).
-- Invariant: an empty argument does not error. wow_check invokes every slash that way.

local ADDON_NAME, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Slash = { last = nil }

local function handle(msg)
    ns.Slash.last = tostring(msg or "")
    if DEFAULT_CHAT_FRAME and DEFAULT_CHAT_FRAME.AddMessage then
        DEFAULT_CHAT_FRAME:AddMessage(ADDON_NAME .. ": " .. ns.Slash.last)
    end
end

local key = string.upper(ADDON_NAME or "@@ADDON@@")
local token = "@@SLASH@@"
if token:sub(1, 2) == "@@" then
    token = "/" .. string.lower(ADDON_NAME or "@@ADDON@@")
end
_G["SLASH_" .. key .. "1"] = token
SlashCmdList[key] = handle
ns.Slash.key = key
ns.Slash.token = token
