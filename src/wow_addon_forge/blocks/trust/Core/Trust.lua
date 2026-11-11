-- Record acceptance for @@ADDON@@ (created 2026-11-11).
-- Purpose: decide, from the sender name and the live guild roster, whether a
-- record is ignored, rejected, stored unverified, or allowed into derived state.
-- Invariant: roles are read when asked, not when the record arrived, so a
-- demotion changes what already-stored direct records may affect.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Trust = ns.Trust or {}
ns.Trust.officerRank = 1

local ROLE_RANK = { gm = 0, officer = 1, member = 2 }

ns.Trust.kinds = {
    ["marks.credit"] = { min = "officer", privileged = true },
    ["marks.debit"] = { min = "officer", privileged = true },
    ["log.checkpoint"] = { min = "officer", privileged = true },
    ["settings.set"] = { min = "gm", privileged = true },
    ["self.act"] = { min = "member", self_only = true, privileged = true },
}

function ns.Trust.add_kind(name, spec)
    if type(name) == "string" and type(spec) == "table" then
        ns.Trust.kinds[name] = spec
    end
end

local function meets(role, minimum)
    if role == nil or ROLE_RANK[role] == nil or ROLE_RANK[minimum] == nil then
        return false
    end
    return ROLE_RANK[role] <= ROLE_RANK[minimum]
end

-- [2026-11-11 T-054] The short form of a Name-Realm identity: everything
-- before the first dash (character names never contain one, realms are what
-- follows it). Live Forever returns bare names from the roster, UnitName and
-- CHAT_MSG_ADDON senders while record authors are built Name-Realm — seen
-- live 2026-11-11: "Friar Baggins" vs "Friar Baggins-<realm>", rank 1, still
-- refused as not-allowed. role() is the one seam every permission check
-- funnels through, so it matches exact first, then short-form.
local function short_name(name)
    return (tostring(name):match("^[^%-]+")) or tostring(name)
end

function ns.Trust.role(name)
    if type(name) ~= "string" or name == "" then
        return nil
    end
    if type(GetNumGuildMembers) ~= "function" or type(GetGuildRosterInfo) ~= "function" then
        return nil
    end
    local total = GetNumGuildMembers()
    if type(total) ~= "number" then
        return nil
    end
    local wanted = short_name(name)
    for index = 1, total do
        local roster_name, _, rank = GetGuildRosterInfo(index)
        -- [2026-11-11 T-054] Exact match wins; short-form equality is the
        -- fallback for clients that disagree about the realm suffix. Two
        -- guildmates sharing a short name on different realms would take
        -- the first roster hit — indistinguishable in the game's own guild
        -- UI too, and ranks are guild-scoped, so the risk is cosmetic.
        local same = roster_name == name
            or (type(roster_name) == "string" and short_name(roster_name) == wanted)
        if same and type(rank) == "number" then
            if rank == 0 then
                return "gm"
            end
            if rank <= ns.Trust.officerRank then
                return "officer"
            end
            return "member"
        end
    end
    return nil
end

local function copy_record(record)
    return {
        a = record.a,
        s = record.s,
        t = record.t,
        k = record.k,
        v = record.v or 1,
        p = record.p,
    }
end

function ns.Trust.applies(record)
    if type(record) ~= "table" or record.unverified == true then
        return false
    end
    local spec = ns.Trust.kinds[record.k]
    if type(spec) ~= "table" or spec.privileged ~= true then
        return false
    end
    if type(record.relay) == "string" then
        return meets(ns.Trust.role(record.relay), "officer")
    end
    return meets(ns.Trust.role(record.a), spec.min)
end

function ns.Trust.receive(log, record, sender)
    if type(record) ~= "table" or type(record.a) ~= "string" then
        return "rejected"
    end
    local sender_role = ns.Trust.role(sender)
    if sender_role == nil then
        return "ignored"
    end
    local spec = ns.Trust.kinds[record.k]
    if type(spec) == "table" and spec.self_only == true then
        local who = type(record.p) == "table" and record.p.who or nil
        if who ~= record.a then
            return "rejected"
        end
    end
    local stored = copy_record(record)
    stored.sender = sender
    if sender == record.a then
        local minimum = type(spec) == "table" and spec.min or "member"
        if not meets(sender_role, minimum) then
            return "rejected"
        end
        stored.direct = true
        ns.Log.apply(log, stored)
        return "accepted"
    end
    if meets(sender_role, "officer") then
        stored.relay = sender
        ns.Log.apply(log, stored)
        return "accepted"
    end
    stored.unverified = true
    ns.Log.apply(log, stored)
    return "unverified"
end

function ns.Trust.mark_of(log, author, seq)
    local record = ns.Log.get(log, author, seq)
    if record == nil then
        return "missing"
    end
    if record.unverified == true then
        return "unverified"
    end
    return "verified"
end

if ns.Sync ~= nil and ns.Sync.log ~= nil then
    ns.Trust.log = ns.Sync.log
else
    ns.Trust.log = ns.Log.new()
end

return ns.Trust
