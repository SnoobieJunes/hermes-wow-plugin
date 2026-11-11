-- Guild sync protocol for Guildhall (created 2026-11-11).
-- Purpose: move the record log between clients on the guild addon channel,
-- one message per second, and hold the queue while a restriction is active.
-- Invariant: derived state is still the log's; this file only moves records.
-- Wire prefix and grammar are pinned in goose-deuce.md.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

local PREFIX = "GHSYNC"

ns.Sync = {
    prefix = PREFIX,
    log = nil,
    throttle = nil,
    pending = {},
    peer_heads = {},
    authored = {},
    announce_i = 0,
    last_hello = -10,
}

local function self_name()
    -- [2026-11-11 T-041] Same guarded shape as Bridge.self_name: the live
    -- 1.60.1 index marks UnitName restricted / secret-returning, so call it
    -- through pcall and drop a secret result instead of concatenating it.
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

-- [2026-11-11 T-047] Two wire forms. The legacy form (T-017 pin) carries
-- exactly {who, n} and is unchanged. Any other payload (SPEC-GUILDHALL §4:
-- kind-specific plain data, e.g. a board post's text) rides as
-- "<kind>2,a,s,t,k,<Codec text>" with the Codec output as the last field, so
-- commas inside it are safe; the chunker already splits long texts.
local function is_legacy_payload(payload)
    if type(payload) ~= "table" then
        return false
    end
    if type(payload.who) ~= "string" or type(payload.n) ~= "number" then
        return false
    end
    local keys = 0
    for _ in pairs(payload) do
        keys = keys + 1
    end
    return keys == 2
end

local function encode(kind, record)
    if is_legacy_payload(record.p) then
        return string.format(
            "%s,%s,%d,%d,%s,%s,%d",
            kind,
            record.a,
            record.s,
            record.t,
            record.k,
            record.p.who,
            record.p.n
        )
    end
    if type(ns.Codec) ~= "table" or type(ns.Codec.encode) ~= "function" then
        return nil
    end
    local payload = type(record.p) == "table" and record.p or {}
    local encoded = ns.Codec.encode(payload)
    if type(encoded) ~= "string" then
        return nil
    end
    return string.format("%s2,%s,%d,%d,%s,%s", kind, record.a, record.s, record.t, record.k, encoded)
end

local function apply_encoded(text, sender)
    local kind, author, seq, time, record_kind, who, amount =
        text:match("^([AD]),([^,]+),(%d+),(%d+),([^,]+),([^,]+),(%d+)$")
    local payload = nil
    if kind ~= nil then
        payload = { who = who, n = tonumber(amount) }
    else
        local encoded
        kind, author, seq, time, record_kind, encoded =
            text:match("^([AD])2,([^,]+),(%d+),(%d+),([^,]+),(.+)$")
        if kind == nil then
            return
        end
        if type(ns.Codec) ~= "table" or type(ns.Codec.decode) ~= "function" then
            return
        end
        payload = ns.Codec.decode(encoded)
        if type(payload) ~= "table" then
            return
        end
    end
    local record = {
        a = author,
        s = tonumber(seq),
        t = tonumber(time),
        k = record_kind,
        p = payload,
        v = 1,
    }
    if ns.Trust ~= nil and type(ns.Trust.receive) == "function" then
        ns.Trust.receive(ns.Sync.log, record, sender)
        return
    end
    ns.Log.apply(ns.Sync.log, record)
end

local function vector_text()
    local heads = ns.Log.heads(ns.Sync.log)
    local authors = {}
    for author in pairs(heads) do
        authors[#authors + 1] = author
    end
    table.sort(authors)
    local parts = {}
    for i = 1, #authors do
        local author = authors[i]
        parts[#parts + 1] = author .. ":" .. tostring(heads[author])
    end
    return "V," .. table.concat(parts, ";")
end

local function on_message(text, sender)
    if ns.Trust ~= nil and ns.Trust.role(sender) == nil then
        return
    end
    if text:sub(1, 2) == "H," then
        if text:sub(3) ~= ns.Sync.hash() then
            ns.Throttle.enqueue(ns.Sync.throttle, vector_text(), false)
        end
        return
    end
    if text:sub(1, 2) == "V," then
        local body = text:sub(3)
        if body == "" then
            return
        end
        for entry in string.gmatch(body, "[^;]+") do
            local author, head = entry:match("^([^:]+):(%d+)$")
            if author ~= nil then
                local known = ns.Sync.peer_heads[author] or 0
                local value = tonumber(head)
                if value > known then
                    ns.Sync.peer_heads[author] = value
                end
            end
        end
        return
    end
    if text:sub(1, 2) == "Q," then
        local author, from_seq, to_seq = text:match("^Q,([^,]+),(%d+),(%d+)$")
        if author == nil then
            return
        end
        for seq = tonumber(from_seq), tonumber(to_seq) do
            local record = ns.Log.get(ns.Sync.log, author, seq)
            if record ~= nil and type(record.p) == "table" then
                local encoded = encode("D", record)
                if encoded ~= nil then
                    ns.Throttle.enqueue(ns.Sync.throttle, encoded, false)
                    return
                end
            end
        end
        return
    end
    if
        text:sub(1, 2) == "A,"
        or text:sub(1, 2) == "D,"
        or text:sub(1, 3) == "A2,"
        or text:sub(1, 3) == "D2,"
    then
        apply_encoded(text, sender)
    end
end

local function on_addon(prefix, text, _, sender)
    if prefix ~= PREFIX or type(text) ~= "string" then
        return
    end
    if sender == self_name() then
        return
    end
    local whole = ns.Chunk.accept(sender, text, ns.Sync.pending)
    if whole == nil then
        return
    end
    on_message(whole, sender)
end

local function send(text)
    if type(C_ChatInfo) ~= "table" or type(C_ChatInfo.SendAddonMessage) ~= "function" then
        return false
    end
    local ok, result = pcall(C_ChatInfo.SendAddonMessage, PREFIX, text, "GUILD")
    return ok and result == 0
end

local function missing_request()
    local heads = ns.Log.heads(ns.Sync.log)
    for author, peer in pairs(ns.Sync.peer_heads) do
        local ours = heads[author] or 0
        if peer > ours then
            return string.format("Q,%s,%d,%d", author, ours + 1, peer)
        end
    end
    return nil
end

function ns.Sync.hash()
    return ns.Reduce.hash(ns.Reduce.fold(ns.Sync.log))
end

function ns.Sync.author(record)
    if ns.Log.apply(ns.Sync.log, record) then
        -- [2026-11-11 T-047] A payload the Codec cannot encode stays local:
        -- it is in the log (Log.apply already happened) but never enqueued.
        local encoded = encode("A", record)
        if encoded ~= nil then
            ns.Sync.authored[#ns.Sync.authored + 1] = record
            ns.Throttle.enqueue(ns.Sync.throttle, encoded, true)
        end
    end
    return ns.Sync.log.count
end

function ns.Sync.tick()
    local restricted = ns.Restrict.active()
    if restricted then
        return
    end
    if #ns.Sync.throttle.queue > 0 then
        ns.Throttle.pump(ns.Sync.throttle, send, false)
        return
    end
    local request = missing_request()
    if request ~= nil then
        ns.Throttle.enqueue(ns.Sync.throttle, request, false)
        ns.Throttle.pump(ns.Sync.throttle, send, false)
        return
    end
    local now = GetTime()
    if now - ns.Sync.last_hello >= 5 then
        ns.Throttle.enqueue(ns.Sync.throttle, "H," .. ns.Sync.hash(), false)
        ns.Sync.last_hello = now
        ns.Throttle.pump(ns.Sync.throttle, send, false)
        return
    end
    if #ns.Sync.authored == 0 then
        return
    end
    ns.Sync.announce_i = (ns.Sync.announce_i % #ns.Sync.authored) + 1
    local record = ns.Sync.authored[ns.Sync.announce_i]
    local encoded = encode("A", record)
    if encoded ~= nil then
        ns.Throttle.enqueue(ns.Sync.throttle, encoded, true)
    end
    ns.Throttle.pump(ns.Sync.throttle, send, false)
end

function ns.Sync.report()
    local throttle = ns.Sync.throttle
    return string.format(
        "%d,%d,%d,%d,%d",
        throttle.sent,
        throttle.max_bytes,
        throttle.sent_while_restricted,
        throttle.max_bucket,
        ns.Sync.log.count
    )
end

ns.Sync.log = ns.Log.new()
ns.Sync.throttle = ns.Throttle.new()
if ns.Trust ~= nil then
    ns.Trust.log = ns.Sync.log
end

if type(C_ChatInfo) == "table" and type(C_ChatInfo.RegisterAddonMessagePrefix) == "function" then
    pcall(C_ChatInfo.RegisterAddonMessagePrefix, PREFIX)
end
if type(ns.Dispatch) == "table" then
    ns.Dispatch:Register("CHAT_MSG_ADDON")
    ns.Dispatch:On("CHAT_MSG_ADDON", on_addon)
    ns.Dispatch:Register("ADDON_RESTRICTION_STATE_CHANGED")
    ns.Dispatch:On("ADDON_RESTRICTION_STATE_CHANGED", function()
        if not ns.Restrict.active() then
            ns.Sync.tick()
        end
    end)
end
if type(C_Timer) == "table" and type(C_Timer.NewTicker) == "function" then
    C_Timer.NewTicker(1, function()
        ns.Sync.tick()
    end)
end

return ns.Sync
