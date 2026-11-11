-- Replicated record log for @@ADDON@@ (created 2026-11-11).
-- Purpose: store guild records as a set keyed by (author, sequence).
-- Invariants: applying a record already stored is a no-op; the set does not
-- depend on arrival order. This file does not call the Lua loader.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Log = ns.Log or {}

function ns.Log.new()
    return { by = {}, count = 0 }
end

function ns.Log.apply(log, record)
    if type(record) ~= "table" or type(record.a) ~= "string" or type(record.s) ~= "number" then
        return false
    end
    local by_author = log.by[record.a]
    if by_author == nil then
        by_author = {}
        log.by[record.a] = by_author
    end
    if by_author[record.s] ~= nil then
        return false
    end
    by_author[record.s] = record
    log.count = log.count + 1
    return true
end

-- Exposed after token replacement so Reduce.lua can run in a bare Lua VM too.
@@ADDON@@Log = ns.Log

function ns.Log.contains(log, record)
    local by_author = log.by[record.a]
    return by_author ~= nil and by_author[record.s] ~= nil
end

function ns.Log.list(log)
    local records = {}
    for _, seqs in pairs(log.by) do
        for _, record in pairs(seqs) do
            records[#records + 1] = record
        end
    end
    table.sort(records, function(left, right)
        if left.t ~= right.t then
            return left.t < right.t
        end
        if left.a ~= right.a then
            return left.a < right.a
        end
        return left.s < right.s
    end)
    return records
end

-- Highest sequence present with no gap from 1. Spec storage, used by later sync.
function ns.Log.heads(log)
    local heads = {}
    for author, seqs in pairs(log.by) do
        local seq = 0
        while seqs[seq + 1] ~= nil do
            seq = seq + 1
        end
        heads[author] = seq
    end
    return heads
end

function ns.Log.get(log, author, seq)
    local by_author = log.by[author]
    if by_author == nil then
        return nil
    end
    return by_author[seq]
end

function ns.Log.compact(log, cutoff)
    if type(cutoff) ~= "number" then
        return 0
    end
    local dropped = 0
    for _, seqs in pairs(log.by) do
        for seq, record in pairs(seqs) do
            if record.k ~= "log.checkpoint" and type(record.t) == "number" and record.t < cutoff then
                seqs[seq] = nil
                log.count = log.count - 1
                dropped = dropped + 1
            end
        end
    end
    return dropped
end

return ns.Log
