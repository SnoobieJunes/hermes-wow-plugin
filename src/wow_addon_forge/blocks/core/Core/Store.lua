-- SavedVariables schema and migrations for @@ADDON@@ (created 2026-11-11).
-- Purpose: bring a version-1 saved table up to schema 2 without dropping its fields.
-- Invariant: migrate returns a table and does not raise on a non-table.

local ADDON_NAME, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Store = { SCHEMA = 2 }

function ns.Store.migrate(db)
    if type(db) ~= "table" then
        return { schema = ns.Store.SCHEMA, migrated_from = 0 }
    end
    local version = db.schema
    if type(version) ~= "number" then
        version = 1
    end
    if version < 1 then
        version = 1
    end
    if version == 1 then
        db.schema = 2
        db.migrated_from = 1
        if type(db.note) ~= "string" then
            db.note = ""
        end
    end
    if type(db.schema) ~= "number" or db.schema < ns.Store.SCHEMA then
        db.schema = ns.Store.SCHEMA
    end
    return db
end

if type(CreateFrame) == "function" and type(ADDON_NAME) == "string" then
    local frame = CreateFrame("Frame")
    frame:RegisterEvent("ADDON_LOADED")
    frame:SetScript("OnEvent", function(_, _, loaded)
        if loaded ~= ADDON_NAME then
            return
        end
        local dbName = ADDON_NAME .. "DB"
        _G[dbName] = ns.Store.migrate(_G[dbName])
    end)
end

return ns.Store
