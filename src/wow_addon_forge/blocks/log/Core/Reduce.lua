-- Reducers for @@ADDON@@ (created 2026-11-11).
-- Purpose: derived state is a pure function of the record set, folded in
-- order (t, a, s). An unknown kind is stored by the log and ignored here.
-- Invariant: the same set always hashes the same, whatever order it arrived in.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Reduce = ns.Reduce or {}
if ns.Log == nil then
    ns.Log = @@ADDON@@Log
end

local function copy_balances(source)
    local balances = {}
    if type(source) ~= "table" then
        return balances
    end
    for who, amount in pairs(source) do
        if type(who) == "string" and type(amount) == "number" then
            balances[who] = amount
        end
    end
    return balances
end

function ns.Reduce.fold(log)
    local balances = {}
    for _, record in ipairs(ns.Log.list(log)) do
        local allowed = ns.Trust == nil or type(ns.Trust.applies) ~= "function" or ns.Trust.applies(record)
        local payload = record.p
        if not allowed then
            -- A trust block is loaded and this record must not affect balances.
        elseif record.k == "marks.credit" and type(payload) == "table" then
            local who = payload.who
            local amount = payload.n
            if type(who) == "string" and type(amount) == "number" then
                balances[who] = (balances[who] or 0) + amount
            end
        elseif record.k == "marks.debit" and type(payload) == "table" then
            local who = payload.who
            local amount = payload.n
            if type(who) == "string" and type(amount) == "number" then
                balances[who] = (balances[who] or 0) - amount
            end
        elseif record.k == "log.checkpoint" and type(payload) == "table" then
            balances = copy_balances(payload.balances)
        end
    end
    return { balances = balances }
end

function ns.Reduce.hash(state)
    local names = {}
    for who in pairs(state.balances) do
        names[#names + 1] = who
    end
    table.sort(names)
    local parts = {}
    for i = 1, #names do
        local who = names[i]
        parts[#parts + 1] = who .. "=" .. string.format("%.0f", state.balances[who])
    end
    return table.concat(parts, "|")
end

function ns.Reduce.selftest()
    local function make_records()
        local records = {}
        for author_i = 1, 10 do
            local author = "M" .. author_i .. "-Realm"
            for seq = 1, 30 do
                records[#records + 1] = {
                    a = author,
                    s = seq,
                    t = 1000 + ((author_i * 17 + seq * 13) % 500),
                    k = "marks.credit",
                    p = { who = author, n = (seq % 5) + 1 },
                    v = 1,
                }
            end
        end
        return records
    end

    local function copy_list(records)
        local out = {}
        for i = 1, #records do
            out[i] = records[i]
        end
        return out
    end

    local function apply_all(records)
        local log = ns.Log.new()
        for i = 1, #records do
            ns.Log.apply(log, records[i])
        end
        return log
    end

    local base = make_records()
    if #base ~= 300 then
        return false, "expected 300 records"
    end
    local expected = ns.Reduce.hash(ns.Reduce.fold(apply_all(base)))
    for seed = 1, 50 do
        local shuffled = copy_list(base)
        math.randomseed(seed * 17 + 3)
        for i = #shuffled, 2, -1 do
            local j = math.random(1, i)
            shuffled[i], shuffled[j] = shuffled[j], shuffled[i]
        end
        local hashed = ns.Reduce.hash(ns.Reduce.fold(apply_all(shuffled)))
        if hashed ~= expected then
            return false, "shuffle " .. seed .. " diverged"
        end
    end

    local log = apply_all(base)
    local before = log.count
    local again = ns.Log.apply(log, base[1])
    if again ~= false or log.count ~= before then
        return false, "duplicate was not a no-op"
    end
    if ns.Reduce.hash(ns.Reduce.fold(log)) ~= expected then
        return false, "duplicate changed the hash"
    end

    local unknown = {
        a = "M1-Realm",
        s = 99,
        t = 50,
        k = "no.such",
        p = { who = "M1-Realm", n = 999 },
        v = 1,
    }
    if ns.Log.apply(log, unknown) ~= true or ns.Log.contains(log, unknown) ~= true then
        return false, "unknown kind was not stored"
    end
    if ns.Reduce.hash(ns.Reduce.fold(log)) ~= expected then
        return false, "unknown kind was reduced"
    end

    local balances = ns.Reduce.fold(log).balances
    local checkpoint = {
        a = "Officer-Realm",
        s = 1,
        t = 2000,
        k = "log.checkpoint",
        p = { cutoff = 2000, balances = balances },
        v = 1,
    }
    ns.Log.apply(log, checkpoint)
    local after_checkpoint = ns.Reduce.hash(ns.Reduce.fold(log))
    local dropped = ns.Log.compact(log, 2000)
    if dropped < 1 then
        return false, "compaction dropped nothing"
    end
    if ns.Reduce.hash(ns.Reduce.fold(log)) ~= after_checkpoint then
        return false, "compaction changed balances"
    end
    return true, 50, dropped
end

return ns.Reduce
