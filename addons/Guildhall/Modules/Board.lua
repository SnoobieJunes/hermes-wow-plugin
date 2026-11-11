-- Board: posts, pins and comments for Guildhall (created 2026-11-11).
-- Purpose: the guild's message board. Posts are officer-authored unless the
-- allow_members switch opens them; pins and comments hang off a post; a post is
-- removed by its author or by an officer.
-- Invariants: rows() is a pure fold over the replicated record log, so two
-- clients holding the same records compute the same list in the same order.
-- This file creates no frames and writes no SavedVariables.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Board = ns.Board or {}

-- [2026-11-11 T-043] The member-posting switch is a plain field, not a synced
-- setting (SPEC-GUILDHALL §8.1): it re-registers the local Trust kind, so a
-- member's post is accepted by guildmates holding the same switch. A record
-- that crosses to a client still on "officer" is refused by Trust.receive.
ns.Board.allow_members = false

-- [2026-11-11 T-043] Board kinds, registered only when the trust block is
-- loaded. privileged=true is what lets Trust.applies admit a record into
-- derived state (SPEC-GUILDHALL §6). board.remove and board.comment are member
-- kinds because rows() applies its own author-or-officer rule on top.
if type(ns.Trust) == "table" and type(ns.Trust.add_kind) == "function" then
    ns.Trust.add_kind("board.post", { min = "officer", privileged = true })
    ns.Trust.add_kind("board.pin", { min = "officer", privileged = true })
    ns.Trust.add_kind("board.remove", { min = "member", privileged = true })
    ns.Trust.add_kind("board.comment", { min = "member", privileged = true })
end

-- [2026-11-11 T-043] Same guarded shape as Core/Sync.lua's self_name: the live
-- 1.60.1 index marks UnitName restricted and secret-returning, so the call goes
-- through pcall and a secret result is dropped instead of concatenated.
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

-- [2026-11-11 T-043] The author's next sequence is one past the highest
-- contiguous sequence the log holds for them (SPEC-GUILDHALL §4: no gaps).
local function next_seq(self)
    local head = ns.Log.heads(ns.Sync.log)[self] or 0
    return head + 1
end

-- [2026-11-11 T-043] Records carry server time; the Clock seam returns 0 when
-- GetServerTime is absent, so a record is still well-formed.
local function now()
    if type(ns.Clock) == "table" and type(ns.Clock.now) == "function" then
        return ns.Clock.now()
    end
    return 0
end

-- [2026-11-11 T-043] One authoring path: build the record, apply it locally and
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

-- [2026-11-11 T-043] Post ids are "author:seq" (SPEC-GUILDHALL §4 identity).
-- Author names cannot contain a colon, so the first colon splits the two parts.
local function parse_id(post_id)
    if type(post_id) ~= "string" then
        return nil
    end
    local author_name, seq = post_id:match("^([^:]+):(%d+)$")
    if author_name == nil then
        return nil
    end
    return author_name, tonumber(seq)
end

-- [2026-11-11 T-043] The post record behind an id, or nil when the log holds no
-- such board.post. This is the existence check for comment and remove.
local function record_for(post_id)
    local author_name, seq = parse_id(post_id)
    if author_name == nil then
        return nil
    end
    local record = ns.Log.get(ns.Sync.log, author_name, seq)
    if type(record) == "table" and record.k == "board.post" then
        return record
    end
    return nil
end

-- [2026-11-11 T-043] Pin needs the post to be visible right now: a removed or
-- unaccepted post is not pinnable, so the check goes through rows().
local function post_in_rows(post_id)
    local rows = ns.Board.rows()
    for i = 1, #rows do
        if rows[i].id == post_id then
            return true
        end
    end
    return false
end

function ns.Board.set_allow_members(flag)
    ns.Board.allow_members = flag and true or false
    -- [2026-11-11 T-043] Re-registering the kind is what makes a member's post
    -- pass Trust.applies on this client: the minimum role moves with the switch.
    if type(ns.Trust) == "table" and type(ns.Trust.add_kind) == "function" then
        ns.Trust.add_kind("board.post", {
            min = ns.Board.allow_members and "member" or "officer",
            privileged = true,
        })
    end
    return ns.Board.allow_members
end

-- [2026-11-11 T-023] The optional via tag records a post's origin when it was
-- authored on behalf of an outside channel (SPEC-GUILDHALL §10: inbox commands
-- become records "tagged with their Discord origin"). It rides in the payload,
-- so every client folding the log sees the same tag; in-game posts pass nil
-- and their payloads stay byte-identical to the T-043 shape.
function ns.Board.post(text, via)
    if type(text) ~= "string" or text == "" then
        return nil, "empty"
    end
    if #text > 500 then
        return nil, "too-long"
    end
    if via ~= nil and (type(via) ~= "string" or via == "" or #via > 32) then
        return nil, "bad-via"
    end
    local self = self_name()
    if self == "" then
        return nil, "no-self"
    end
    if not ns.Board.allow_members and not is_officer(role_of(self)) then
        return nil, "not-allowed"
    end
    local payload = { text = text }
    if via ~= nil then
        payload.via = via
    end
    local record = author("board.post", payload)
    return record.a .. ":" .. record.s
end

function ns.Board.pin(post_id)
    local self = self_name()
    if not is_officer(role_of(self)) then
        return nil, "not-allowed"
    end
    if not post_in_rows(post_id) then
        return nil, "missing"
    end
    author("board.pin", { post = post_id })
    return true
end

function ns.Board.comment(post_id, text)
    local self = self_name()
    if role_of(self) == nil then
        return nil, "not-allowed"
    end
    if type(text) ~= "string" or text == "" then
        return nil, "empty"
    end
    if #text > 500 then
        return nil, "too-long"
    end
    if record_for(post_id) == nil then
        return nil, "missing"
    end
    author("board.comment", { post = post_id, text = text })
    return true
end

function ns.Board.remove(post_id)
    local self = self_name()
    local post = record_for(post_id)
    if post == nil then
        return nil, "missing"
    end
    if post.a ~= self and not is_officer(role_of(self)) then
        return nil, "not-allowed"
    end
    author("board.remove", { post = post_id })
    return true
end

function ns.Board.rows()
    local log = ns.Sync.log
    if type(ns.Log) ~= "table" or type(ns.Log.list) ~= "function" or log == nil then
        return {}
    end
    -- [2026-11-11 T-043] Trust is optional so a log-only client still reads the
    -- board; with Trust loaded, a post or pin counts only when Trust.applies
    -- accepts it (SPEC-GUILDHALL §6).
    local trust = nil
    if type(ns.Trust) == "table" and type(ns.Trust.applies) == "function" then
        trust = ns.Trust
    end
    local records = ns.Log.list(log)
    -- [2026-11-11 T-043] Pass one: the accepted posts, keyed by id. Two passes
    -- over Log.list's total (t, a, s) order keep the fold deterministic; a
    -- remove needs its target's author, which may sort after it.
    local posts = {}
    local seqs = {}
    for _, record in ipairs(records) do
        if record.k == "board.post" and (trust == nil or trust.applies(record)) then
            local id = record.a .. ":" .. record.s
            posts[id] = record
            seqs[id] = record.s
        end
    end
    -- [2026-11-11 T-043] Pass two: pins (officer records only), removes (author
    -- or officer, never unverified) and comments (never unverified).
    local pinned = {}
    local removed = {}
    local comments = {}
    for _, record in ipairs(records) do
        local payload = type(record.p) == "table" and record.p or nil
        local target = payload ~= nil and payload.post or nil
        if record.k == "board.pin" then
            -- [2026-11-11 T-043] Same rule as posts: without a trust block the
            -- pin counts; with one it must pass Trust.applies (driver review).
            if type(target) == "string" and (trust == nil or trust.applies(record)) then
                pinned[target] = true
            end
        elseif record.k == "board.remove" then
            if record.unverified ~= true and type(target) == "string" then
                local counts = posts[target] ~= nil and posts[target].a == record.a
                if not counts and type(trust) == "table" and type(trust.role) == "function" then
                    counts = is_officer(trust.role(record.a))
                end
                if counts then
                    removed[target] = true
                end
            end
        elseif record.k == "board.comment" then
            if record.unverified ~= true and type(target) == "string" then
                if comments[target] == nil then
                    comments[target] = {}
                end
                comments[target][#comments[target] + 1] = {
                    a = record.a,
                    text = type(payload.text) == "string" and payload.text or "",
                }
            end
        end
    end
    local rows = {}
    for id, post in pairs(posts) do
        if not removed[id] then
            rows[#rows + 1] = {
                id = id,
                a = post.a,
                t = type(post.t) == "number" and post.t or 0,
                text = type(post.p) == "table" and type(post.p.text) == "string" and post.p.text or "",
                -- [2026-11-11 T-023] The origin tag, present only on posts an
                -- outside channel authored through the mirror; absent (nil)
                -- keeps pre-T-023 rows and payloads exactly as they were.
                via = type(post.p) == "table" and type(post.p.via) == "string" and post.p.via or nil,
                pinned = pinned[id] == true,
                comments = comments[id] or {},
            }
        end
    end
    -- [2026-11-11 T-043] Pinned first, then newest, then author, then highest
    -- sequence: a total order (identity is unique), so equal inputs sort the
    -- same way on every client.
    table.sort(rows, function(left, right)
        if left.pinned ~= right.pinned then
            return left.pinned
        end
        if left.t ~= right.t then
            return left.t > right.t
        end
        if left.a ~= right.a then
            return left.a < right.a
        end
        return seqs[left.id] > seqs[right.id]
    end)
    return rows
end

return ns.Board
