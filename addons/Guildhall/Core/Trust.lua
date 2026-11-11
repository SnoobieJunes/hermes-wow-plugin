-- Record acceptance for Guildhall (created 2026-11-11).
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
    for index = 1, total do
        local roster_name, _, rank = GetGuildRosterInfo(index)
        if roster_name == name and type(rank) == "number" then
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
