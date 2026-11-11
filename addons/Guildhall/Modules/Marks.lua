-- Marks: the guild currency ledger for Guildhall (created 2026-11-11).
-- Purpose: the ledger of SPEC-GUILDHALL §7 — claims attested by the guildmates
-- they name, one-click officer approvals, officer grants and deductions, member
-- staking of the Marks they own, refunds and a checkpoint the ledger can be
-- compacted against.
-- Invariants: balances(), balance(), pending(), leaderboard() and refund() read
-- one fold over the replicated record log, so two clients holding the same
-- records compute the same numbers in the same order; balances never go below
-- zero, and the daily cap is applied per (who, activity day). This file creates
-- no frames and writes no SavedVariables.

local _, ns = ...
if type(ns) ~= "table" then
    ns = {}
end

ns.Marks = ns.Marks or {}

-- [2026-11-11 T-021] Marks kinds, registered only when the trust block is
-- loaded. privileged=true is what lets Trust.applies admit a record into
-- derived state (SPEC-GUILDHALL §6). claim and spend are self_only: the fold
-- also admits them only when the payload names the author, so a record naming
-- someone else never counts anywhere.
if type(ns.Trust) == "table" and type(ns.Trust.add_kind) == "function" then
    ns.Trust.add_kind("marks.claim", { min = "member", privileged = true, self_only = true })
    ns.Trust.add_kind("marks.approve", { min = "officer", privileged = true })
    ns.Trust.add_kind("marks.grant", { min = "officer", privileged = true })
    ns.Trust.add_kind("marks.deduct", { min = "officer", privileged = true })
    ns.Trust.add_kind("marks.spend", { min = "member", privileged = true, self_only = true })
end

-- [2026-11-11 T-021] Per-day ceiling on the Marks a member earns from claims
-- (SPEC-GUILDHALL §7). Grants, deductions, spends and refunds are not capped:
-- they are officer acts, not activity rewards.
ns.Marks.daily_cap = 100

-- [2026-11-11 T-021] Same guarded shape as Board.self_name and
-- Calendar.self_name: the live 1.60.1 index marks UnitName restricted and
-- secret-returning, so the call goes through pcall and a secret result is
-- dropped instead of concatenated.
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

-- [2026-11-11 T-021] The author's next sequence is one past the highest
-- contiguous sequence the log holds for them (SPEC-GUILDHALL §4: no gaps).
local function next_seq(self)
    local head = ns.Log.heads(ns.Sync.log)[self] or 0
    return head + 1
end

-- [2026-11-11 T-021] Records carry server time; the Clock seam returns 0 when
-- GetServerTime is absent, so a record is still well-formed.
local function now()
    if type(ns.Clock) == "table" and type(ns.Clock.now) == "function" then
        return ns.Clock.now()
    end
    return 0
end

-- [2026-11-11 T-021] One authoring path: build the record, apply it locally and
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

-- [2026-11-11 T-021] Claim ids are "author:seq" (SPEC-GUILDHALL §4 identity).
-- Author names cannot contain a colon, so the first colon splits the two parts.
local function parse_id(claim_id)
    if type(claim_id) ~= "string" then
        return nil
    end
    local author_name, seq = claim_id:match("^([^:]+):(%d+)$")
    if author_name == nil then
        return nil
    end
    return author_name, tonumber(seq)
end

-- [2026-11-11 T-021] The claim record behind an id, or nil when the log holds no
-- such marks.claim. This is the existence check for approve() and refund().
local function claim_for(claim_id)
    local author_name, seq = parse_id(claim_id)
    if author_name == nil then
        return nil
    end
    local record = ns.Log.get(ns.Sync.log, author_name, seq)
    if type(record) == "table" and record.k == "marks.claim" then
        return record
    end
    return nil
end

-- [2026-11-11 T-021] Validation helpers shared by the actions below. A count is
-- a positive integer (a float or a 0 would make the ledger ambiguous), and a
-- string is non-empty and within its cap, matching Board/Calendar's rules.
local function is_count(value)
    return type(value) == "number" and value > 0 and value % 1 == 0
end

local function is_text(value, cap)
    return type(value) == "string" and value ~= "" and #value <= cap
end

-- [2026-11-11 T-021] mates must be a list of character names (SPEC-GUILDHALL §7:
-- the guildmates the claimant saw in the group). A non-string entry is refused
-- here rather than silently skipped by the fold.
local function mate_list(mates)
    if type(mates) ~= "table" then
        return false
    end
    for i = 1, #mates do
        if type(mates[i]) ~= "string" or mates[i] == "" then
            return false
        end
    end
    return true
end

local function has_self(self, mates)
    for i = 1, #mates do
        if mates[i] == self then
            return true
        end
    end
    return false
end

-- [2026-11-11 T-021] The single fold every reader walks: balances, the stake
-- bookkeeping refund() needs, and the id sets attestation and approval built.
-- Everything downstream (balances(), pending(), leaderboard(), refund()) is a
-- pure function of this, so a client that re-runs it after new records arrive
-- never has to re-derive earlier decisions.
local function fold()
    local log = ns.Sync.log
    local empty = {
        balances = {},
        staked = {},
        refunded = {},
        spender = {},
        firsts = {},
        attested = {},
        approved = {},
    }
    if type(ns.Log) ~= "table" or type(ns.Log.list) ~= "function" or log == nil then
        return empty
    end
    -- [2026-11-11 T-021] Trust is optional so a log-only client still reads the
    -- ledger; with Trust loaded, an officer act counts only when Trust.applies
    -- accepts it (SPEC-GUILDHALL §6).
    local trust = nil
    if type(ns.Trust) == "table" and type(ns.Trust.applies) == "function" then
        trust = ns.Trust
    end
    local function applies(record)
        return trust == nil or trust.applies(record)
    end

    local records = ns.Log.list(log)

    -- [2026-11-11 T-021] Pass 1, firsts: each author's first claim per key. A
    -- later claim with the same key from the same author is a retry, not more
    -- Marks — the dedupe key exists to make retries harmless (SPEC-GUILDHALL §7).
    local firsts = {}
    local first_ids = {}
    for _, record in ipairs(records) do
        if record.k == "marks.claim" and record.unverified ~= true then
            local payload = type(record.p) == "table" and record.p or nil
            local key = payload ~= nil and type(payload.key) == "string" and payload.key or nil
            local who = payload ~= nil and type(payload.who) == "string" and payload.who or nil
            if key ~= nil and who ~= nil and who == record.a then
                local id = record.a .. ":" .. record.s
                local seen = first_ids[who .. "\001" .. key]
                if seen == nil then
                    first_ids[who .. "\001" .. key] = id
                    firsts[id] = record
                end
            end
        end
    end

    -- [2026-11-11 T-021] Pass 2, attested: a first-claim is attested when at
    -- least half of the guildmates it names (ceil(n/2)) also authored a
    -- first-claim with the same key (SPEC-GUILDHALL §7: claims with the same key
    -- from half the named mates attest each other).
    local key_authors = {}
    for _, record in pairs(firsts) do
        local payload = record.p
        local key = payload.key
        local who = payload.who
        if key_authors[key] == nil then
            key_authors[key] = {}
        end
        if key_authors[key][who] == nil then
            key_authors[key][who] = true
        end
    end
    local attested = {}
    for id, record in pairs(firsts) do
        local payload = record.p
        local mates = type(payload.mates) == "table" and payload.mates or {}
        local total = #mates
        if total >= 1 then
            local seen = {}
            local count = 0
            for i = 1, total do
                local mate = mates[i]
                if type(mate) == "string" and seen[mate] == nil then
                    seen[mate] = true
                    if key_authors[payload.key] ~= nil and key_authors[payload.key][mate] then
                        count = count + 1
                    end
                end
            end
            if count >= math.ceil(total / 2) then
                attested[id] = true
            end
        end
    end

    -- [2026-11-11 T-021] Pass 3, approved: every attested claim, plus every claim
    -- an accepted marks.approve names. The approve record itself must clear
    -- Trust (or there is no trust block at all), so a forged approval cannot
    -- credit anyone.
    local approved = {}
    for id in pairs(attested) do
        approved[id] = true
    end
    for _, record in ipairs(records) do
        if record.k == "marks.approve" and applies(record) then
            -- [2026-11-11 T-021] Written as a plain if, not an and/or value
            -- idiom: "A and B or nil" yields the boolean B, not the claim id,
            -- which silently approved nothing (driver review).
            local claim = nil
            if type(record.p) == "table" and type(record.p.claim) == "string" then
                claim = record.p.claim
            end
            if claim ~= nil and firsts[claim] ~= nil then
                approved[claim] = true
            end
        end
    end

    -- [2026-11-11 T-021] Pass 4, the ledger itself: one sequential pass in
    -- Log.list's total (t, a, s) order, balances never below zero. The daily cap
    -- is counted per (who, bucket) where the bucket is floor(t/86400) over the
    -- whole claim record (SPEC-GUILDHALL §7, "activity-before-first"), so an
    -- activity's date decides the bucket, not the order records arrived in; a
    -- checkpoint replaces balances wholesale and clears the buckets, which is
    -- what makes Log.compact safe.
    local balances = {}
    local buckets = {}
    local staked = {}
    local refunded = {}
    local spender = {}

    for _, record in ipairs(records) do
        local payload = type(record.p) == "table" and record.p or nil
        if record.k == "marks.claim" and approved[record.a .. ":" .. record.s] then
            local who = payload ~= nil and type(payload.who) == "string" and payload.who or nil
            local amount = payload ~= nil and is_count(payload.n) and payload.n or nil
            if who ~= nil and amount ~= nil then
                local at = type(record.t) == "number" and record.t or 0
                -- [2026-11-11 T-021] The cap is per activity as well as per day
                -- (SPEC-GUILDHALL §7 gives each earning rule its own cap); the
                -- activity is the claim key's text before its first colon.
                local activity = type(payload.key) == "string" and payload.key:match("^([^:]*)") or ""
                local bucket = activity .. "\001" .. math.floor(at / 86400)
                local credited = 0
                if buckets[who] == nil then
                    buckets[who] = {}
                end
                local used = buckets[who][bucket] or 0
                if used < ns.Marks.daily_cap then
                    credited = math.min(amount, ns.Marks.daily_cap - used)
                    buckets[who][bucket] = used + credited
                end
                if credited > 0 then
                    balances[who] = (balances[who] or 0) + credited
                end
            end
        elseif record.k == "marks.grant" and applies(record) then
            local who = payload ~= nil and type(payload.who) == "string" and payload.who or nil
            local amount = payload ~= nil and is_count(payload.n) and payload.n or nil
            local stake = payload ~= nil and type(payload.stake) == "string" and payload.stake or nil
            if who ~= nil and amount ~= nil then
                if stake ~= nil then
                    -- [2026-11-11 T-021] A staked refund returns at most what
                    -- the stake actually debited, less what earlier refunds
                    -- already returned, and only to the character that staked.
                    local spent = staked[stake] or 0
                    local returned = refunded[stake] or 0
                    local remaining = spent - returned
                    local target = spender[stake] or who
                    if remaining > 0 then
                        local credited = math.min(amount, remaining)
                        balances[target] = (balances[target] or 0) + credited
                        refunded[stake] = returned + credited
                    end
                else
                    balances[who] = (balances[who] or 0) + amount
                end
            end
        elseif record.k == "marks.deduct" and applies(record) then
            local who = payload ~= nil and type(payload.who) == "string" and payload.who or nil
            local amount = payload ~= nil and is_count(payload.n) and payload.n or nil
            if who ~= nil and amount ~= nil then
                local held = balances[who] or 0
                local debited = math.min(held, amount)
                if debited > 0 then
                    balances[who] = held - debited
                end
            end
        elseif record.k == "marks.spend" and record.unverified ~= true and payload ~= nil and payload.who == record.a then
            local amount = is_count(payload.n) and payload.n or nil
            local stake = type(payload.stake) == "string" and payload.stake or nil
            if amount ~= nil then
                local held = balances[record.a] or 0
                local debited = math.min(held, amount)
                if debited > 0 then
                    balances[record.a] = held - debited
                    if stake ~= nil then
                        -- [2026-11-11 T-021] Only the debited part is staked: a
                        -- member spending more than they hold stakes nothing
                        -- extra, so a refund can never pay out Marks that were
                        -- never taken.
                        staked[stake] = (staked[stake] or 0) + debited
                        spender[stake] = record.a
                    end
                end
            end
        elseif record.k == "log.checkpoint" and applies(record) then
            -- [2026-11-11 T-021] Only string->number entries survive: the
            -- snapshot is officer-authored, but a malformed field is dropped
            -- rather than poisoning every later balance.
            local saved = type(payload.balances) == "table" and payload.balances or {}
            balances = {}
            for who, amount in pairs(saved) do
                if type(who) == "string" and type(amount) == "number" then
                    balances[who] = amount
                end
            end
            buckets = {}
        end
    end

    return {
        balances = balances,
        staked = staked,
        refunded = refunded,
        spender = spender,
        firsts = firsts,
        attested = attested,
        approved = approved,
    }
end

-- [2026-11-11 T-021] Every reader goes through fold(), so a balances() call and
-- a leaderboard() call can never disagree.
function ns.Marks.balances()
    return fold().balances
end

function ns.Marks.balance(who)
    if type(who) ~= "string" then
        return 0
    end
    local held = fold().balances[who]
    if type(held) == "number" and held > 0 then
        return held
    end
    return 0
end

function ns.Marks.pending()
    local state = fold()
    local rows = {}
    for id, record in pairs(state.firsts) do
        if state.approved[id] == nil then
            rows[#rows + 1] = {
                id = id,
                who = record.p.who,
                key = record.p.key,
                n = type(record.p.n) == "number" and record.p.n or 0,
            }
        end
    end
    -- [2026-11-11 T-021] Id ascending: a total order over unique identities, so
    -- the officer queue lists the same rows in the same order on every client.
    table.sort(rows, function(left, right)
        return left.id < right.id
    end)
    return rows
end

function ns.Marks.leaderboard()
    local rows = {}
    for who, amount in pairs(fold().balances) do
        if type(who) == "string" and type(amount) == "number" and amount > 0 then
            rows[#rows + 1] = { who = who, balance = amount }
        end
    end
    -- [2026-11-11 T-021] Balance descending, then name ascending: a total order,
    -- so equal ledgers rank the same way on every client.
    table.sort(rows, function(left, right)
        if left.balance ~= right.balance then
            return left.balance > right.balance
        end
        return left.who < right.who
    end)
    return rows
end

-- [2026-11-11 T-021] A member claims Marks for an activity: a dedupe key, a
-- positive count and the guildmates they saw in the group (SPEC-GUILDHALL §7).
-- self_only at receipt means a claim naming another character never lands.
function ns.Marks.claim(key, amount, mates)
    if not is_text(key, 80) then
        return nil, "bad-key"
    end
    if not is_count(amount) then
        return nil, "bad-amount"
    end
    if not mate_list(mates) then
        return nil, "bad-mates"
    end
    local self = self_name()
    if self == "" then
        return nil, "no-self"
    end
    if not has_self(self, mates) then
        return nil, "bad-mates"
    end
    if role_of(self) == nil then
        return nil, "not-allowed"
    end
    local record = author("marks.claim", { who = self, key = key, n = amount, mates = mates })
    return record.a .. ":" .. record.s
end

-- [2026-11-11 T-021] The officer one-click approval: an unattested claim becomes
-- approved, which is what credits it in the fold.
function ns.Marks.approve(claim_id)
    local self = self_name()
    if not is_officer(role_of(self)) then
        return nil, "not-allowed"
    end
    if claim_for(claim_id) == nil then
        return nil, "missing"
    end
    author("marks.approve", { claim = claim_id })
    return true
end

-- [2026-11-11 T-021] An officer grants Marks to a character, optionally against
-- a stake the fold can refund later.
function ns.Marks.grant(who, amount)
    local self = self_name()
    if not is_officer(role_of(self)) then
        return nil, "not-allowed"
    end
    if type(who) ~= "string" or who == "" then
        return nil, "bad-who"
    end
    if not is_count(amount) then
        return nil, "bad-amount"
    end
    author("marks.grant", { who = who, n = amount })
    return true
end

-- [2026-11-11 T-021] An officer deducts Marks from a character; the fold debits
-- at most the balance held, so a deduction cannot drive it below zero.
function ns.Marks.deduct(who, amount)
    local self = self_name()
    if not is_officer(role_of(self)) then
        return nil, "not-allowed"
    end
    if type(who) ~= "string" or who == "" then
        return nil, "bad-who"
    end
    if not is_count(amount) then
        return nil, "bad-amount"
    end
    author("marks.deduct", { who = who, n = amount })
    return true
end

-- [2026-11-11 T-021] A member stakes their own Marks as a quest or bounty reward
-- (SPEC-GUILDHALL §7): always the caller, never a parameter, so no one can
-- stake another character's balance.
function ns.Marks.spend(amount, stake)
    if stake ~= nil and not is_text(stake, 40) then
        return nil, "bad-stake"
    end
    if not is_count(amount) then
        return nil, "bad-amount"
    end
    local self = self_name()
    if role_of(self) == nil then
        return nil, "not-allowed"
    end
    if ns.Marks.balance(self) < amount then
        return nil, "insufficient"
    end
    author("marks.spend", { who = self, n = amount, stake = stake })
    return true
end

-- [2026-11-11 T-021] An officer refunds a cancelled stake: the fold says how much
-- the stake actually debited and which character staked it, and the refund is a
-- grant back to them, capped at what is still outstanding.
function ns.Marks.refund(stake)
    local self = self_name()
    if not is_officer(role_of(self)) then
        return nil, "not-allowed"
    end
    if type(stake) ~= "string" or stake == "" then
        return nil, "missing"
    end
    local state = fold()
    local spender_name = state.spender[stake]
    if spender_name == nil then
        return nil, "missing"
    end
    local remaining = (state.staked[stake] or 0) - (state.refunded[stake] or 0)
    if remaining <= 0 then
        return nil, "already-refunded"
    end
    author("marks.grant", { who = spender_name, n = remaining, stake = stake })
    return true
end

-- [2026-11-11 T-021] An officer snapshots the ledger. The fold adopts the
-- snapshot and forgets every daily-cap bucket, so Log.compact can drop the
-- records the checkpoint superseded without changing any balance.
function ns.Marks.checkpoint()
    local self = self_name()
    if not is_officer(role_of(self)) then
        return nil, "not-allowed"
    end
    author("log.checkpoint", { balances = fold().balances, cutoff = now() })
    return true
end

return ns.Marks
