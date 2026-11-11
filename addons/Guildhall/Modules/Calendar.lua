-- Calendar: guild events with roles and sign-ups (created 2026-11-11).
-- Purpose: officers create and edit events, members sign themselves up with a
-- role and a yes/maybe/no status, and the login reminder flags events starting
-- within a day (SPEC-GUILDHALL §8.2).
-- Invariants: events(), role_counts() and reminders() are pure folds over the
-- replicated record log, so two clients holding the same records compute the
-- same rows in the same order. This file creates no frames and writes no
-- SavedVariables.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Calendar = ns.Calendar or {}

-- [2026-11-11 T-020] The login reminder cache: refreshed on PLAYER_LOGIN, read
-- by the tab and the reminder toast. It starts empty so a client that has not
-- logged in yet reports no reminders.
ns.Calendar.last_reminder = {}

-- [2026-11-11 T-020] The member-created-event switch, same shape as
-- Board.allow_members (SPEC-GUILDHALL §8.2): a plain local field that
-- re-registers the event.create Trust kind, so a member's create is accepted by
-- guildmates holding the same switch. A record that crosses to a client still
-- on "officer" is refused by Trust.receive.
ns.Calendar.allow_member_create = false

-- [2026-11-11 T-020] Calendar kinds, registered only when the trust block is
-- loaded. privileged=true is what lets Trust.applies admit a record into
-- derived state (SPEC-GUILDHALL §6). event.cancel is a member kind because the
-- fold applies its own author-or-officer rule on top; event.signup is self_only
-- so a record naming another character is refused at receipt.
if type(ns.Trust) == "table" and type(ns.Trust.add_kind) == "function" then
    ns.Trust.add_kind("event.create", { min = "officer", privileged = true })
    -- [2026-11-11 T-020] event.edit is a member kind like event.cancel: the
    -- fold admits only the event's author or an officer, and an officer-only
    -- receipt minimum would reject a member author's edit on every peer
    -- while the author's own client showed it (driver review).
    ns.Trust.add_kind("event.edit", { min = "member", privileged = true })
    ns.Trust.add_kind("event.cancel", { min = "member", privileged = true })
    ns.Trust.add_kind("event.signup", { min = "member", privileged = true, self_only = true })
end

-- [2026-11-11 T-020] Same guarded shape as Board.self_name: the live 1.60.1
-- index marks UnitName restricted and secret-returning, so the call goes through
-- pcall and a secret result is dropped instead of concatenated.
local function self_name()
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

-- [2026-11-11 T-020] The author's next sequence is one past the highest
-- contiguous sequence the log holds for them (SPEC-GUILDHALL §4: no gaps).
local function next_seq(self)
    local head = ns.Log.heads(ns.Sync.log)[self] or 0
    return head + 1
end

-- [2026-11-11 T-020] Records carry server time; the Clock seam returns 0 when
-- GetServerTime is absent, so a record is still well-formed.
local function now()
    if type(ns.Clock) == "table" and type(ns.Clock.now) == "function" then
        return ns.Clock.now()
    end
    return 0
end

-- [2026-11-11 T-020] One authoring path: build the record, apply it locally and
-- enqueue it for replication (SPEC-GUILDHALL §4-§5). Returns the record so the
-- caller can name it.
local function author(kind, payload)
    local self = self_name()
    local record = {
        a = self,
        s = next_seq(self),
        t = now(),
        k = kind,
        p = payload,
        v = 1,
    }
    ns.Sync.author(record)
    return record
end

local function role_of(self)
    if type(ns.Trust) ~= "table" or type(ns.Trust.role) ~= "function" then
        return nil
    end
    return ns.Trust.role(self)
end

local function is_officer(role)
    return role == "officer" or role == "gm"
end

-- [2026-11-11 T-020] Event ids are "author:seq" (SPEC-GUILDHALL §4 identity).
-- Author names cannot contain a colon, so the first colon splits the two parts.
local function parse_id(event_id)
    if type(event_id) ~= "string" then
        return nil
    end
    local author_name, seq = event_id:match("^([^:]+):(%d+)$")
    if author_name == nil then
        return nil
    end
    return author_name, tonumber(seq)
end

-- [2026-11-11 T-020] The folded row for an id, or nil when no accepted,
-- non-cancelled event carries it. Existence for edit, cancel and signup goes
-- through the fold, so a create that Trust refuses (a member's event while the
-- switch is off) is not an event anyone can act on.
local function row_for(event_id)
    if parse_id(event_id) == nil then
        return nil
    end
    local rows = ns.Calendar.events()
    for i = 1, #rows do
        if rows[i].id == event_id then
            return rows[i]
        end
    end
    return nil
end

function ns.Calendar.set_allow_member_create(flag)
    ns.Calendar.allow_member_create = flag and true or false
    -- [2026-11-11 T-020] Re-registering the kind is what makes a member's create
    -- pass Trust.applies on this client: the minimum role moves with the switch.
    if type(ns.Trust) == "table" and type(ns.Trust.add_kind) == "function" then
        ns.Trust.add_kind("event.create", {
            min = ns.Calendar.allow_member_create and "member" or "officer",
            privileged = true,
        })
    end
    return ns.Calendar.allow_member_create
end

function ns.Calendar.create(title, starts)
    if type(title) ~= "string" or title == "" then
        return nil, "empty"
    end
    if #title > 80 then
        return nil, "too-long"
    end
    if type(starts) ~= "number" then
        return nil, "bad-time"
    end
    local self = self_name()
    if self == "" then
        return nil, "no-self"
    end
    if not ns.Calendar.allow_member_create and not is_officer(role_of(self)) then
        return nil, "not-allowed"
    end
    local record = author("event.create", { title = title, starts = starts })
    return record.a .. ":" .. record.s
end

function ns.Calendar.edit(event_id, title, starts)
    local self = self_name()
    local row = row_for(event_id)
    if row == nil then
        return nil, "missing"
    end
    if row.a ~= self and not is_officer(role_of(self)) then
        return nil, "not-allowed"
    end
    author("event.edit", { event = event_id, title = title, starts = starts })
    return true
end

function ns.Calendar.cancel(event_id)
    local self = self_name()
    local row = row_for(event_id)
    if row == nil then
        return nil, "missing"
    end
    if row.a ~= self and not is_officer(role_of(self)) then
        return nil, "not-allowed"
    end
    author("event.cancel", { event = event_id })
    return true
end

function ns.Calendar.signup(event_id, role, status)
    local self = self_name()
    if role == nil then
        role = "dps"
    end
    -- [2026-11-11 T-020] Same string rule as create's title: a non-empty string
    -- within the length cap, with the same error names.
    if type(role) ~= "string" or role == "" then
        return nil, "empty"
    end
    if #role > 20 then
        return nil, "too-long"
    end
    if status == nil then
        status = "yes"
    end
    if status ~= "yes" and status ~= "maybe" and status ~= "no" then
        return nil, "bad-status"
    end
    if role_of(self) == nil then
        return nil, "not-allowed"
    end
    if row_for(event_id) == nil then
        return nil, "missing"
    end
    author("event.signup", { event = event_id, who = self, role = role, status = status })
    return true
end

function ns.Calendar.events()
    local log = ns.Sync.log
    if type(ns.Log) ~= "table" or type(ns.Log.list) ~= "function" or log == nil then
        return {}
    end
    -- [2026-11-11 T-020] Trust is optional so a log-only client still reads the
    -- calendar; with Trust loaded, a create counts only when Trust.applies
    -- accepts it (SPEC-GUILDHALL §6).
    local trust = nil
    if type(ns.Trust) == "table" and type(ns.Trust.applies) == "function" then
        trust = ns.Trust
    end
    local records = ns.Log.list(log)
    -- [2026-11-11 T-020] Pass one: the accepted creates, keyed by id. Two passes
    -- over Log.list's total (t, a, s) order keep the fold deterministic; an
    -- edit, cancel or signup can sort before its create when they share a
    -- timestamp and the actor's name sorts first.
    local events = {}
    for _, record in ipairs(records) do
        if record.k == "event.create" and (trust == nil or trust.applies(record)) then
            local id = record.a .. ":" .. record.s
            if events[id] == nil then
                local payload = type(record.p) == "table" and record.p or {}
                events[id] = {
                    id = id,
                    a = record.a,
                    title = type(payload.title) == "string" and payload.title or "",
                    starts = type(payload.starts) == "number" and payload.starts or 0,
                    cancelled = false,
                    signups = {},
                }
            end
        end
    end
    -- [2026-11-11 T-020] Pass two: edits (author or officer, last writer wins),
    -- cancels (never unverified, author or officer) and signups (never
    -- unverified, and the payload must name the author — a forged signup naming
    -- someone else never counts anywhere).
    for _, record in ipairs(records) do
        local payload = type(record.p) == "table" and record.p or nil
        local target = payload ~= nil and payload.event or nil
        local event = type(target) == "string" and events[target] or nil
        if record.k == "event.edit" then
            if event ~= nil then
                local from_author = event.a == record.a
                local from_officer = type(trust) == "table" and type(trust.role) == "function" and is_officer(trust.role(record.a))
                if from_author or from_officer then
                    -- [2026-11-11 T-020] A nil field keeps the old value: the
                    -- caller's edit() wrote only what it was given.
                    if type(payload.title) == "string" then
                        event.title = payload.title
                    end
                    if type(payload.starts) == "number" then
                        event.starts = payload.starts
                    end
                end
            end
        elseif record.k == "event.cancel" then
            if event ~= nil and record.unverified ~= true then
                local from_author = event.a == record.a
                local from_officer = type(trust) == "table" and type(trust.role) == "function" and is_officer(trust.role(record.a))
                if from_author or from_officer then
                    event.cancelled = true
                end
            end
        elseif record.k == "event.signup" then
            if event ~= nil and record.unverified ~= true and payload ~= nil and payload.who == record.a then
                event.signups[record.a] = {
                    who = record.a,
                    role = type(payload.role) == "string" and payload.role or "",
                    status = type(payload.status) == "string" and payload.status or "",
                }
            end
        end
    end
    -- [2026-11-11 T-020] Build the rows: latest signup per (event, who) wins
    -- because pass two overwrote earlier ones in total order; counts tallies
    -- the "yes" signups by role.
    local rows = {}
    for _, event in pairs(events) do
        if not event.cancelled then
            local counts = {}
            local signups = {}
            for _, signup in pairs(event.signups) do
                signups[#signups + 1] = signup
                if signup.status == "yes" then
                    counts[signup.role] = (counts[signup.role] or 0) + 1
                end
            end
            table.sort(signups, function(left, right)
                return left.who < right.who
            end)
            rows[#rows + 1] = {
                id = event.id,
                title = event.title,
                starts = event.starts,
                a = event.a,
                counts = counts,
                signups = signups,
            }
        end
    end
    -- [2026-11-11 T-020] Starts ascending, then id ascending: a total order
    -- (identity is unique), so equal inputs sort the same way on every client.
    table.sort(rows, function(left, right)
        if left.starts ~= right.starts then
            return left.starts < right.starts
        end
        return left.id < right.id
    end)
    return rows
end

function ns.Calendar.role_counts(event_id)
    local row = row_for(event_id)
    if row == nil then
        return {}
    end
    return row.counts
end

function ns.Calendar.reminders(current)
    local at = current
    if type(at) ~= "number" then
        at = 0
        if type(ns.Clock) == "table" and type(ns.Clock.now) == "function" then
            local value = ns.Clock.now()
            if type(value) == "number" then
                at = value
            end
        end
    end
    -- [2026-11-11 T-020] The reminder window is the next 24 hours, start times
    -- strictly after now (SPEC-GUILDHALL §8.2).
    local rows = ns.Calendar.events()
    local out = {}
    for i = 1, #rows do
        local row = rows[i]
        if row.starts > at and row.starts <= at + 86400 then
            out[#out + 1] = { id = row.id, title = row.title, starts = row.starts }
        end
    end
    return out
end

-- [2026-11-11 T-020] The login reminder: PLAYER_LOGIN carries no payload, so the
-- listener fires for whatever the client delivers and refreshes last_reminder
-- from the fold (SPEC-GUILDHALL §8.2).
if type(ns.Dispatch) == "table" then
    ns.Dispatch:Register("PLAYER_LOGIN")
    ns.Dispatch:On("PLAYER_LOGIN", function()
        ns.Calendar.last_reminder = ns.Calendar.reminders()
    end)
end

return ns.Calendar
