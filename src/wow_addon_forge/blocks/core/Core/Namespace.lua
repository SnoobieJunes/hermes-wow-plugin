-- Core namespace for @@ADDON@@ (created 2026-11-11).
-- Purpose: the private table every other core file shares, plus the module registry.
-- Invariants: this file is first in the TOC; it writes no SavedVariables; module order is
-- registration order, not pairs() order.

local ADDON_NAME, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.name = ADDON_NAME or "@@ADDON@@"
ns.modules = {}
ns.moduleOrder = {}

-- Register a module table under a unique name.
-- Why: later files only receive this shared table, so the registry is how they find
-- each other without a global lookup.
function ns:RegisterModule(name, module)
    if type(name) ~= "string" or name == "" then
        error("RegisterModule: name must be a non-empty string", 2)
    end
    if type(module) ~= "table" then
        error("RegisterModule: module must be a table", 2)
    end
    if self.modules[name] ~= nil then
        error("RegisterModule: module '" .. name .. "' is already registered", 2)
    end
    self.modules[name] = module
    self.moduleOrder[#self.moduleOrder + 1] = name
    module.name = name
    return module
end

-- Exposed after token replacement so a headless test can reach the namespace.
@@ADDON@@ = ns
