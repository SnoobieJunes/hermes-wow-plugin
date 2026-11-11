-- Guildhall addon namespace (created 2026-11-11).
-- Purpose: set up the private table the WoW client passes to every file of this addon, and
-- provide the module registry later files use to find each other.
-- Invariants owned by this file:
-- - This file is first in the TOC; it defines the addon table every later file receives.
-- - It writes no global variable.
-- - Module iteration order is registration order.

local ADDON_NAME, ns = ...

ns.name = ADDON_NAME
-- [2026-11-11 T-003] Kept equal to the TOC "## Version" by a pytest check rather than read
-- through a client API, so this file stays pure Lua 5.1 with no WoW API call.
ns.version = "0.1.0"
ns.modules = {}
-- [2026-11-11 T-003] `pairs` order is unspecified in Lua, and replicated state must not depend
-- on it, so registration order is recorded in this array alongside the name -> module map.
ns.moduleOrder = {}

-- Register a module table under a unique name.
-- Why: later files receive only this shared table, so the registry is how they locate the
-- modules other files defined, in a deterministic order.
-- Inputs: `name` (non-empty string), `module` (table). Sets `module.name = name`.
-- Output: returns `module`.
-- Failure modes: errors at the caller when `name` is not a non-empty string, when `module`
-- is not a table, or when `name` is already registered.
function ns:RegisterModule(name, module)
    if type(name) ~= "string" or name == "" then
        error("RegisterModule: name must be a non-empty string", 2)
    end
    if type(module) ~= "table" then
        error("RegisterModule: module '" .. name .. "' must be a table", 2)
    end
    if self.modules[name] ~= nil then
        error("RegisterModule: module '" .. name .. "' is already registered", 2)
    end
    self.modules[name] = module
    self.moduleOrder[#self.moduleOrder + 1] = name
    module.name = name
    return module
end

-- Look up a registered module by name.
-- Why: callers should not reach into `ns.modules` directly, so the registry layout can change
-- without touching them.
-- Input: `name` (string).
-- Output: the module table registered under `name`, or nil when none is.
-- Failure modes: none; an unknown name returns nil.
function ns:GetModule(name)
    return self.modules[name]
end

-- Iterate the registered modules in registration order.
-- Why: start-up and replicated state must visit modules in the order they registered, never in
-- the unspecified order of `pairs`.
-- Inputs: none beyond the shared table.
-- Output: an iterator usable as `for name, module in ns:IterateModules() do`, yielding each
-- registered name and module table once, in registration order.
-- Failure modes: none; with no modules registered the loop body never runs.
function ns:IterateModules()
    -- [2026-11-11 T-003] A closure over an index walks moduleOrder once. Each call to
    -- IterateModules gets its own index, so two loops over the registry do not disturb each other.
    local index = 0
    return function()
        index = index + 1
        local name = self.moduleOrder[index]
        if name ~= nil then
            return name, self.modules[name]
        end
    end
end
