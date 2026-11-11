-- Send throttle for @@ADDON@@ (created 2026-11-11).
-- Purpose: at most one addon message per integer virtual second, with a queue
-- that drops catch-up before authored data.
-- Invariant: a successful send records its second; a second send in that same
-- second is refused even if the caller asks.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Throttle = ns.Throttle or {}

local CAP = 400

function ns.Throttle.new()
    return {
        queue = {},
        sent = 0,
        max_bytes = 0,
        sent_while_restricted = 0,
        max_bucket = 0,
        last_bucket = -1,
        buckets = {},
    }
end

local function drop_catchup(state)
    for index = 1, #state.queue do
        if not state.queue[index].authored then
            table.remove(state.queue, index)
            return true
        end
    end
    return false
end

function ns.Throttle.enqueue(state, text, authored)
    local pieces = ns.Chunk.split(text, 255)
    for i = 1, #pieces do
        while #state.queue >= CAP and not authored do
            if not drop_catchup(state) then
                break
            end
        end
        if #state.queue >= CAP and not authored then
            return
        end
        state.queue[#state.queue + 1] = { text = pieces[i], authored = authored == true }
    end
end

function ns.Throttle.pump(state, send, restricted)
    if restricted then
        state.sent_while_restricted = state.sent_while_restricted + 1
        return false
    end
    if #state.queue == 0 then
        return false
    end
    local bucket = math.floor(GetTime())
    if state.last_bucket == bucket then
        return false
    end
    local item = state.queue[1]
    if type(item.text) ~= "string" or #item.text > 255 then
        table.remove(state.queue, 1)
        return false
    end
    if not send(item.text) then
        return false
    end
    table.remove(state.queue, 1)
    state.last_bucket = bucket
    state.buckets[bucket] = (state.buckets[bucket] or 0) + 1
    if state.buckets[bucket] > state.max_bucket then
        state.max_bucket = state.buckets[bucket]
    end
    if #item.text > state.max_bytes then
        state.max_bytes = #item.text
    end
    state.sent = state.sent + 1
    return true
end

return ns.Throttle
