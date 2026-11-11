-- Mirror: the Discord bridge surface for Guildhall (created 2026-11-11).
-- Purpose: SPEC-GUILDHALL §10 on top of the bridge contract (SPEC-PLUGIN
-- §7). Outbound, board posts and calendar events are written into the
-- bridge outbox as Discord-ready text. Inbound, a pushed "post" command
-- becomes a board.post authored by the character that loads it, tagged with
-- its origin; the Board's own permission rule decides, so a non-officer's
-- client refuses and the refusal is reported in the next outbox.
-- Invariants: an inbox id in mirror_seen is never applied twice, across any
-- number of reloads (the set lives in SavedVariables); an outboxed record
-- id in mirror_sent is never outboxed twice by this client. The bridge
-- block keeps its own seen/applied bookkeeping for the generic contract;
-- the mirror's sets are the Guildhall-command authority. Latency is one
-- /reload or logout in each direction, as the contract states. This file
-- has no tab and creates no frames beyond the shared dispatcher.

local ADDON_NAME, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Mirror = ns.Mirror or {}

-- [2026-11-11 T-023] The sent set is capped so a years-old board cannot grow
-- SavedVariables without bound; dropping the oldest id can re-mirror that
-- ancient post once, which a Discord channel tolerates better than an
-- unbounded save file. The cap says so here rather than truncating silently.
local SENT_CAP = 500

-- [2026-11-11 T-023] The mirror's corner of the one SavedVariables table,
-- the same db() shape the bridge block uses: outbox bookkeeping belongs to
-- Bridge, mirror_sent/mirror_seen belong here, both flush together.
local function db()
    local saved = _G[(ADDON_NAME or "Addon") .. "DB"]
    if type(saved) ~= "table" then
        saved = {}
        _G[(ADDON_NAME or "Addon") .. "DB"] = saved
    end
    if type(saved.mirror_sent) ~= "table" then
        saved.mirror_sent = {}
    end
    if type(saved.mirror_seen) ~= "table" then
        saved.mirror_seen = {}
    end
    return saved
end

local function listed(list, value)
    for i = 1, #list do
        if list[i] == value then
            return true
        end
    end
    return false
end

local function mark_sent(saved, key)
    saved.mirror_sent[#saved.mirror_sent + 1] = key
    while #saved.mirror_sent > SENT_CAP do
        table.remove(saved.mirror_sent, 1)
    end
end

-- [2026-11-11 T-023] One outbox write through the bridge block, which owns
-- the id sequence, the outbox cap and the persisted shape (SPEC-PLUGIN §7).
-- Text is rendered here, once, so what Discord reads is what the fold said:
-- the pull side only prefixes the kind.
local function outbox(kind, at, text)
    if type(ns.Bridge) ~= "table" or type(ns.Bridge.post) ~= "function" then
        return nil
    end
    return ns.Bridge.post({ t = at or 0, kind = kind, text = text })
end

-- [2026-11-11 T-023] Outbound scan: every board row and calendar row this
-- client has not mirrored yet, in fold order. Reading the folds (not the
-- raw log) means removed posts and cancelled events that never mirrored
-- stay unmirrored, and Trust has already decided what counts. A Discord-
-- born post mirrors back out under its in-game author's name with no loop
-- risk: the outbox is write-only from here.
function ns.Mirror.scan()
    local saved = db()
    local sent = 0
    if type(ns.Board) == "table" and type(ns.Board.rows) == "function" then
        local rows = ns.Board.rows()
        for i = 1, #rows do
            local row = rows[i]
            if not listed(saved.mirror_sent, row.id) then
                if outbox("board.post", row.t, row.a .. ": " .. row.text) ~= nil then
                    mark_sent(saved, row.id)
                    sent = sent + 1
                end
            end
        end
    end
    if type(ns.Calendar) == "table" and type(ns.Calendar.events) == "function" then
        local rows = ns.Calendar.events()
        for i = 1, #rows do
            local row = rows[i]
            local key = "event:" .. row.id
            if not listed(saved.mirror_sent, key) then
                if outbox("event.create", row.starts, row.title .. " @ " .. tostring(row.starts)) ~= nil then
                    mark_sent(saved, key)
                    sent = sent + 1
                end
            end
        end
    end
    return sent
end

-- [2026-11-11 T-023] The text of a pushed command, from data.text (the
-- contract shape) or a top-level text (the shape the bridge tests push).
-- Anything else is nil and the command refuses as empty rather than posting
-- a placeholder.
local function command_text(item)
    if type(item.data) == "table" and type(item.data.text) == "string" then
        return item.data.text
    end
    if type(item.text) == "string" then
        return item.text
    end
    return nil
end

-- [2026-11-11 T-023] Apply one fresh inbox item. "post" goes through
-- Board.post, so the loading character's own permission is the gate an
-- officer kind needs (SPEC-GUILDHALL §10) and the failure word is the
-- Board's. Every other command kind is refused as unsupported in the
-- outbox -- never silently dropped -- until its task lands.
local function apply_item(item)
    local at = type(item.t) == "number" and item.t or 0
    if item.kind == "post" then
        if type(ns.Board) ~= "table" or type(ns.Board.post) ~= "function" then
            outbox("refused", at, "post: unsupported")
            return false
        end
        local via = type(item.via) == "string" and item.via or "discord"
        local id, err = ns.Board.post(command_text(item) or "", via)
        if id == nil then
            outbox("refused", at, "post: " .. tostring(err))
            return false
        end
        return true
    end
    outbox("refused", at, tostring(item.kind) .. ": unsupported")
    return false
end

-- [2026-11-11 T-023] Inbound pass over the pushed inbox: mark each numeric
-- id seen before applying it, so an erroring or refused item is still
-- consumed exactly once and a reload can never double-post. Returns how
-- many items applied.
function ns.Mirror.ingest()
    local inbox = _G[(ADDON_NAME or "Addon") .. "_Inbox"]
    if type(inbox) ~= "table" then
        return 0
    end
    local saved = db()
    local applied = 0
    for i = 1, #inbox do
        local item = inbox[i]
        if type(item) == "table" and type(item.id) == "number" and not listed(saved.mirror_seen, item.id) then
            saved.mirror_seen[#saved.mirror_seen + 1] = item.id
            if apply_item(item) then
                applied = applied + 1
            end
        end
    end
    return applied
end

-- [2026-11-11 T-023] How many inbox ids this client has consumed; the
-- observable half of "never applied twice".
function ns.Mirror.seen_count()
    return #db().mirror_seen
end

-- [2026-11-11 T-023] The outbound ticker: the record log lives in memory
-- and re-converges over guild sync after a reload, so a post authored
-- seconds before /reload exists only if it reached the persisted outbox
-- first. A slow scan (the Sync pump sets the C_Timer.NewTicker precedent)
-- bounds that window to seconds; the fold read is the only cost.
if type(C_Timer) == "table" and type(C_Timer.NewTicker) == "function" then
    C_Timer.NewTicker(5, function()
        ns.Mirror.scan()
    end)
end

-- [2026-11-11 T-023] Wiring: ingest then scan when this addon finishes
-- loading (a pushed post lands and mirrors back in the same reload), and
-- scan again at login and logout so a session's posts are in the outbox
-- the logout flush writes. Both passes are idempotent by their sets.
if type(ns.Dispatch) == "table" then
    ns.Dispatch:Register("ADDON_LOADED")
    ns.Dispatch:On("ADDON_LOADED", function(loaded)
        if loaded == ADDON_NAME then
            ns.Mirror.ingest()
            ns.Mirror.scan()
        end
    end)
    ns.Dispatch:Register("PLAYER_LOGIN")
    ns.Dispatch:On("PLAYER_LOGIN", function()
        ns.Mirror.scan()
    end)
    ns.Dispatch:Register("PLAYER_LOGOUT")
    ns.Dispatch:On("PLAYER_LOGOUT", function()
        ns.Mirror.scan()
    end)
end

return ns.Mirror
