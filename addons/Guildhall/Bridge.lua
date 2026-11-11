-- Bridge client for Guildhall (created 2026-11-11).
-- Purpose: write an outbox SavedVariables table wow_bridge can pull, and ingest
-- Inbox.lua once per id. Officer kinds from a non-officer are refused, not applied.
-- Invariant: an id already in inbox_seen is never applied again.

local ADDON_NAME, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

local CAP = 50

ns.Bridge = {
    state = "idle",
    applied = {},
}

local function db()
    local name = (ADDON_NAME or "Addon") .. "DB"
    local saved = _G[name]
    if type(saved) ~= "table" then
        saved = {}
        _G[name] = saved
    end
    if type(saved.outbox) ~= "table" then
        saved.outbox = {}
    end
    if type(saved.inbox_seen) ~= "table" then
        saved.inbox_seen = {}
    end
    if type(saved.applied) ~= "table" then
        saved.applied = {}
    end
    return saved
end

local function already_seen(saved, id)
    for i = 1, #saved.inbox_seen do
        if saved.inbox_seen[i] == id then
            return true
        end
    end
    return false
end

local function self_name()
    if type(UnitName) ~= "function" then
        return ""
    end
    -- [2026-11-11 T-041] The live 1.60.1 index marks UnitName restricted /
    -- secret-returning, so the call goes through pcall and a secret result is
    -- dropped instead of concatenated (the fresh-session gate caught the
    -- unguarded call: wow_check verdict fail, Bridge.lua restricted-api).
    local ok, name, realm = pcall(UnitName, "player")
    if not ok or type(name) ~= "string" then
        return ""
    end
    local secret_ok, secret = pcall(issecretvalue, name)
    if secret_ok and secret then
        return ""
    end
    if type(realm) ~= "string" or realm == "" then
        realm = ""
        if type(GetRealmName) == "function" then
            local realm_ok, realm_name = pcall(GetRealmName)
            if realm_ok and type(realm_name) == "string" then
                local realm_secret_ok, realm_secret = pcall(issecretvalue, realm_name)
                if not (realm_secret_ok and realm_secret) then
                    realm = realm_name
                end
            end
        end
    end
    if realm ~= "" and not name:find("-", 1, true) then
        return name .. "-" .. realm
    end
    return name
end

local function officer_kind(kind)
    if type(ns.Trust) ~= "table" or type(ns.Trust.kinds) ~= "table" then
        return false
    end
    local spec = ns.Trust.kinds[kind]
    if type(spec) ~= "table" then
        return false
    end
    return spec.min == "officer" or spec.min == "gm"
end

local function may_apply(kind)
    if not officer_kind(kind) then
        return true
    end
    if type(ns.Trust.role) ~= "function" then
        return false
    end
    local role = ns.Trust.role(self_name())
    if kind == "settings.set" then
        return role == "gm"
    end
    return role == "officer" or role == "gm"
end

function ns.Bridge.post(record)
    local saved = db()
    local id = record.id
    if type(id) ~= "number" then
        id = #saved.outbox + 1
    end
    saved.outbox[#saved.outbox + 1] = {
        id = id,
        t = record.t or 0,
        kind = record.kind or "note",
        text = record.text or "",
        data = record.data,
    }
    while #saved.outbox > CAP do
        table.remove(saved.outbox, 1)
    end
    ns.Bridge.state = "outbox"
    return id
end

function ns.Bridge.ingest()
    local inbox = _G[(ADDON_NAME or "Addon") .. "_Inbox"]
    if type(inbox) ~= "table" then
        return 0
    end
    local saved = db()
    local fresh = 0
    for i = 1, #inbox do
        local item = inbox[i]
        local id = type(item) == "table" and item.id or nil
        if type(id) == "number" and not already_seen(saved, id) then
            saved.inbox_seen[#saved.inbox_seen + 1] = id
            if may_apply(item.kind) then
                saved.applied[#saved.applied + 1] = id
                ns.Bridge.applied[id] = true
                fresh = fresh + 1
            else
                ns.Bridge.post({
                    id = 100000 + id,
                    t = item.t or 0,
                    kind = "refused",
                    text = tostring(item.kind),
                })
            end
        end
    end
    if fresh > 0 then
        ns.Bridge.state = "inbox"
    end
    return fresh
end

function ns.Bridge.applied_count()
    local saved = db()
    return #saved.applied
end

if type(ns.Dispatch) == "table" then
    ns.Dispatch:Register("ADDON_LOADED")
    ns.Dispatch:On("ADDON_LOADED", function(loaded)
        if loaded == ADDON_NAME then
            ns.Bridge.ingest()
        end
    end)
end

return ns.Bridge
