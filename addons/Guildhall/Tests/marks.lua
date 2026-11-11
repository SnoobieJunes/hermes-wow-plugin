-- Marks checks for Guildhall (created 2026-11-11).
-- Purpose: prove SPEC-GUILDHALL §7 headlessly: an attested claim credits every
-- client, a lone claim waits for the officer, a duplicate key credits once, the
-- daily cap is per activity, a spend never drives a balance below zero, a
-- cancelled stake refunds, five clients agree, a checkpoint preserves balances,
-- and the tab builds only when first shown.
-- Invariant: every case runs in a fresh World; no case reads another's state.

-- [2026-11-11 T-021] The four named mates of an attested claim, taken from the
-- clients' own Name-Realm identities so the payload is real rather than forged.
local function mate_list(...)
    local mates = {}
    for i = 1, select("#", ...) do
        local client = select(i, ...)
        mates[#mates + 1] = client.full_name
    end
    return mates
end

-- [2026-11-11 T-021] A Lua table literal of mate names, for interpolating into an
-- eval string: {"Ann-Forever", "Bob-Forever"} is what Marks.claim expects.
local function mate_literal(mates)
    local parts = {}
    for i = 1, #mates do
        parts[i] = string.format("%q", mates[i])
    end
    return "{" .. table.concat(parts, ", ") .. "}"
end

-- [2026-11-11 T-021] The ledger rendered as a sorted "who=balance|..." string:
-- pairs() order is not stable across clients, so the comparison has to be
-- built from a sort rather than from table iteration.
local BALANCES_EXPR = [[
    local rows = {}
    for who, amount in pairs(Guildhall.Marks.balances()) do
        rows[#rows + 1] = who .. "=" .. tostring(amount)
    end
    table.sort(rows)
    return table.concat(rows, "|")
]]

test('attested_claims_approve_without_officer', function(ctx)
    local ann = ctx.world:client('Ann', 2)
    local bob = ctx.world:client('Bob', 2)
    local cid = ctx.world:client('Cid', 2)
    local dee = ctx.world:client('Dee', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    local mates = mate_list(ann, bob, cid, dee)
    for _, client in ipairs({ann, bob, cid, dee}) do
        local ok = client:eval('return Guildhall.Marks.claim("dungeon:run1", 5, ' .. mate_literal(mates) .. ')')
        assert_true(ok, 'the claim on ' .. client.name .. ' returned an id')
    end
    ctx.world:advance(5)
    for _, client in ipairs({ann, bob, cid, dee}) do
        assert_eq(client:eval('return Guildhall.Marks.balance("' .. client.full_name .. '")'), 5,
            'the attested claim credited ' .. client.name)
    end
end)

test('lone_claim_waits_for_officer', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    local bob = ctx.world:client('Bob', 2)
    local cid = ctx.world:client('Cid', 2)
    local dee = ctx.world:client('Dee', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    -- [2026-11-11 T-021] Four named mates but only Bob claims: one of four is
    -- below the half-of-mates attestation bar, so the claim stays pending.
    local mates = mate_list(ann, bob, cid, dee)
    local id = bob:eval('return Guildhall.Marks.claim("dungeon:solo", 5, ' .. mate_literal(mates) .. ')')
    assert_true(id, 'the lone claim returned an id')
    ctx.world:advance(5)
    assert_eq(ann:eval('return #Guildhall.Marks.pending()'), 1, 'the officer holds one pending claim')
    assert_eq(ann:eval('return Guildhall.Marks.balance("' .. bob.full_name .. '")'), 0, 'the lone claim has not credited anyone yet')
    assert_true(ann:eval('return Guildhall.Marks.approve("' .. id .. '")'), 'the officer approved the claim')
    ctx.world:advance(5)
    assert_eq(bob:eval('return Guildhall.Marks.balance("' .. bob.full_name .. '")'), 5, 'the approved claim credits the member')
end)

test('duplicate_key_adds_nothing', function(ctx)
    local ann = ctx.world:client('Ann', 2)
    local bob = ctx.world:client('Bob', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    local mates = mate_list(ann, bob)
    for _, client in ipairs({ann, bob}) do
        assert_true(client:eval('return Guildhall.Marks.claim("dungeon:run2", 5, ' .. mate_literal(mates) .. ')'),
            'the first claim on ' .. client.name .. ' returned an id')
        assert_true(client:eval('return Guildhall.Marks.claim("dungeon:run2", 5, ' .. mate_literal(mates) .. ')'),
            'the retried claim on ' .. client.name .. ' returned an id')
    end
    ctx.world:advance(5)
    for _, client in ipairs({ann, bob}) do
        assert_eq(client:eval('return Guildhall.Marks.balance("' .. client.full_name .. '")'), 5,
            'the duplicate key credited ' .. client.name .. ' only once')
    end
end)

test('daily_cap_holds', function(ctx)
    local ann = ctx.world:client('Ann', 2)
    local bob = ctx.world:client('Bob', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    for _, client in ipairs({ann, bob}) do
        client:eval('Guildhall.Marks.daily_cap = 6')
    end
    local mates = mate_list(ann, bob)
    -- [2026-11-11 T-021] The two capped claims use different keys with the same
    -- "dungeon" activity prefix: a repeat of one key is a retry and credits
    -- nothing, so the per-activity cap needs two distinct claim keys.
    local first = ann:eval('return Guildhall.Marks.claim("dungeon:capped", 5, ' .. mate_literal(mates) .. ')')
    assert_true(first, 'the first capped claim returned an id')
    ctx.world:advance(3)
    assert_eq(ann:eval('return Guildhall.Marks.balance("' .. ann.full_name .. '")'), 5, 'the first claim credited 5')
    assert_true(ann:eval('return Guildhall.Marks.claim("dungeon:capped2", 5, ' .. mate_literal(mates) .. ')'),
        'the second capped claim returned an id')
    ctx.world:advance(3)
    assert_eq(ann:eval('return Guildhall.Marks.balance("' .. ann.full_name .. '")'), 6,
        'the second claim credited only the cap remainder')
    -- [2026-11-11 T-021] The cap is per activity (SPEC-GUILDHALL §7): a different
    -- activity on the same day has its own bucket and credits in full.
    assert_true(ann:eval('return Guildhall.Marks.claim("raid:run9", 5, ' .. mate_literal(mates) .. ')'),
        'the other-activity claim returned an id')
    ctx.world:advance(3)
    assert_eq(ann:eval('return Guildhall.Marks.balance("' .. ann.full_name .. '")'), 11,
        'the other activity credited its own 5')
end)

test('spend_never_below_zero', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    local bob = ctx.world:client('Bob', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    assert_true(ann:eval('return Guildhall.Marks.grant("' .. bob.full_name .. '", 5)'), 'the officer granted 5')
    ctx.world:advance(5)
    assert_false(bob:eval('return Guildhall.Marks.spend(9)'), 'spending more than held is refused')
    assert_eq(bob:eval('return Guildhall.Marks.balance("' .. bob.full_name .. '")'), 5, 'the refused spend left the balance alone')
    assert_true(bob:eval('return Guildhall.Marks.spend(5, "quest1")'), 'the stake spend returned true')
    ctx.world:advance(5)
    assert_eq(bob:eval('return Guildhall.Marks.balance("' .. bob.full_name .. '")'), 0, 'the stake spend emptied the balance')
    -- [2026-11-11 T-021] Bob crafts a spend straight into the log. A spend is a
    -- self-only debit and Bob holds 0 after the stake, so the fold debits
    -- math.min(0, 5) = nothing: a crafted spend can never credit, and it cannot
    -- drive an honest balance below zero on the officer client either.
    bob:eval([[
        local record = {
            a = "]] .. bob.full_name .. [[",
            s = 99,
            t = 9999,
            k = "marks.spend",
            p = {who = "]] .. bob.full_name .. [[", n = 5},
            v = 1,
        }
        Guildhall.Sync.author(record)
    ]])
    ctx.world:advance(5)
    assert_eq(ann:eval('return Guildhall.Marks.balance("' .. bob.full_name .. '")'), 0,
        'the forged spend credited nothing on the officer client')
end)

test('stake_refunded_on_cancel', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    local bob = ctx.world:client('Bob', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    assert_true(ann:eval('return Guildhall.Marks.grant("' .. bob.full_name .. '", 5)'), 'the officer granted 5')
    ctx.world:advance(5)
    assert_true(bob:eval('return Guildhall.Marks.spend(5, "quest1")'), 'the member staked 5')
    ctx.world:advance(5)
    assert_true(ann:eval('return Guildhall.Marks.refund("quest1")'), 'the officer refunded the stake')
    ctx.world:advance(5)
    assert_eq(bob:eval('return Guildhall.Marks.balance("' .. bob.full_name .. '")'), 5, 'the refund returned the stake')
    assert_false(ann:eval('return Guildhall.Marks.refund("quest1")'), 'a second refund of the same stake is refused')
end)

test('five_clients_agree', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    local bob = ctx.world:client('Bob', 2)
    local cid = ctx.world:client('Cid', 2)
    local dee = ctx.world:client('Dee', 2)
    local eve = ctx.world:client('Eve', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    local mates = mate_list(ann, bob, cid, dee, eve)
    assert_true(ann:eval('return Guildhall.Marks.claim("dungeon:run5", 5, ' .. mate_literal(mates) .. ')'),
        'the officer claim returned an id')
    assert_true(bob:eval('return Guildhall.Marks.claim("dungeon:run5", 5, ' .. mate_literal(mates) .. ')'),
        'the member claim returned an id')
    assert_true(ann:eval('return Guildhall.Marks.grant("' .. eve.full_name .. '", 3)'), 'the officer granted 3')
    ctx.world:advance(5)
    assert_true(eve:eval('return Guildhall.Marks.spend(2, "bounty1")'), 'the member staked 2')
    ctx.world:advance(5)
    local expected = ann:eval(BALANCES_EXPR)
    assert_true(expected ~= nil and expected ~= '', 'the officer rendered a non-empty balances string')
    for _, client in ipairs({ann, bob, cid, dee, eve}) do
        assert_eq(client:eval(BALANCES_EXPR), expected, 'the balances agree on ' .. client.name)
    end
end)

test('checkpoint_preserves_balances', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    local bob = ctx.world:client('Bob', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    assert_true(ann:eval('return Guildhall.Marks.grant("' .. bob.full_name .. '", 5)'), 'the officer granted 5')
    ctx.world:advance(5)
    local before = ann:eval(BALANCES_EXPR)
    assert_true(before ~= nil and before ~= '', 'the officer rendered a non-empty balances string')
    assert_true(ann:eval('return Guildhall.Marks.checkpoint()'), 'the officer checkpointed the ledger')
    ctx.world:advance(5)
    assert_eq(ann:eval(BALANCES_EXPR), before, 'the checkpoint preserved the officer balances')
    assert_eq(bob:eval(BALANCES_EXPR), before, 'the checkpoint preserved the member balances')
end)

test('marks_tab_builds_only_when_first_shown', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    assert_false(ann:eval('return Guildhall.MarksTab.built'), 'the tab is not built at load')
    assert_true(ann:eval('return Guildhall.Window.show_tab("marks")'), 'the marks tab can be shown')
    assert_true(ann:eval('return Guildhall.MarksTab.built'), 'showing the tab built it')
end)
