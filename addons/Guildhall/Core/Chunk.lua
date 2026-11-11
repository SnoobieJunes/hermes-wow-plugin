-- Message chunker for Guildhall (created 2026-11-11).
-- Purpose: split a logical addon message so every piece is at most 255 bytes,
-- and reassemble those pieces in arrival order.
-- Invariant: a text that already fits is returned unchanged, so short records
-- are not wrapped.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Chunk = ns.Chunk or {}

local MAX_BYTES = 255
local HEADER = 16

function ns.Chunk.split(text, max_bytes)
    max_bytes = max_bytes or MAX_BYTES
    if type(text) ~= "string" or #text <= max_bytes then
        return { text }
    end
    local budget = max_bytes - HEADER
    if budget < 1 then
        budget = 1
    end
    local parts = {}
    local index = 1
    while index <= #text do
        parts[#parts + 1] = text:sub(index, index + budget - 1)
        index = index + budget
    end
    local id = string.format("%04x", math.random(0, 65535))
    local total = #parts
    local out = {}
    for piece = 1, total do
        out[piece] = string.format("C,%s,%d,%d,%s", id, piece, total, parts[piece])
    end
    return out
end

function ns.Chunk.accept(sender, text, pending)
    if type(text) ~= "string" then
        return nil
    end
    local id, index, total, payload = text:match("^C,([^,]+),(%d+),(%d+),(.*)$")
    if id == nil then
        return text
    end
    local key = tostring(sender) .. ":" .. id
    local box = pending[key]
    if box == nil then
        box = { total = tonumber(total), parts = {} }
        pending[key] = box
    end
    box.parts[tonumber(index)] = payload
    for piece = 1, box.total do
        if box.parts[piece] == nil then
            return nil
        end
    end
    pending[key] = nil
    return table.concat(box.parts)
end

function ns.Chunk.selftest()
    local text = string.rep("x", 600)
    local pieces = ns.Chunk.split(text, 255)
    if #pieces < 2 then
        return false, "long text was not split"
    end
    local pending = {}
    local whole = nil
    for i = 1, #pieces do
        if #pieces[i] > 255 then
            return false, "piece over 255"
        end
        whole = ns.Chunk.accept("peer", pieces[i], pending)
    end
    if whole ~= text then
        return false, "reassembly mismatch"
    end
    local short = ns.Chunk.split("ok", 255)
    if #short ~= 1 or short[1] ~= "ok" then
        return false, "short text was wrapped"
    end
    return true
end

return ns.Chunk
