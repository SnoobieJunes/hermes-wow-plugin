-- Tracker checks for Guildhall (created 2026-11-11).
-- Purpose: prove SPEC-GUILDHALL §8.4 headlessly from inside the addon suite:
-- a boss kill in a half-guild group claims and attests, the same kill under
-- half authors nothing, a kill caught under a restriction queues and authors
-- on lift, a battleground and a five-kill block claim, attendance inside an
-- event window claims, and an invalid event turns its detection off in the
-- status line.
-- Invariant: every case runs in a fresh World; no case reads another's state.

-- [2026-11-11 T-022] Four guildmates in one group inside the same instance:
-- the shared setup the positive cases detect against.
local function guild_party(ctx)
    local clients = {}
    for _, name in ipairs({ 'Ann', 'Bob', 'Cid', 'Dee' }) do
        clients[#clients + 1] = ctx.world:client(name, 2)
    end
    ctx.world:set_network({ loss_rate = 0, duplicate_rate = 0 })
    ctx.world:set_group({ 'Ann', 'Bob', 'Cid', 'Dee' })
    for _, client in ipairs(clients) do
        client:set_instance({ in_instance = true, instance_type = 'party', name = 'Pit', instance_id = 42 })
    end
    return clients
end

test('boss_kill_claims_for_half_guild_group', function(ctx)
    local clients = guild_party(ctx)
    for _, client in ipairs(clients) do
        client:fire('BOSS_KILL', 99, 'Boss')
    end
    ctx.world:advance(5)
    for _, client in ipairs(clients) do
        assert_eq(client:eval('return Guildhall.Marks.balance("' .. client.full_name .. '")'), 5,
            'the boss claim credited ' .. client.name)
    end
end)

test('boss_kill_under_half_authors_nothing', function(ctx)
    local ann = ctx.world:client('Ann', 2)
    local bob = ctx.world:client('Bob', 2)
    -- [2026-11-11 T-022] The harness defaults a client to guild rank 2, so
    -- the unguilded pugs are made by clearing the rank: two of five is below
    -- the half-the-group bar, so no claim may exist.
    for _, name in ipairs({ 'Pug1', 'Pug2', 'Pug3' }) do
        ctx.world:client(name):set_rank()
    end
    ctx.world:set_network({ loss_rate = 0, duplicate_rate = 0 })
    ctx.world:set_group({ 'Ann', 'Bob', 'Pug1', 'Pug2', 'Pug3' })
    for _, client in ipairs({ ann, bob }) do
        client:set_instance({ in_instance = true, instance_type = 'party', name = 'Pit', instance_id = 42 })
        client:fire('BOSS_KILL', 99, 'Boss')
    end
    ctx.world:advance(5)
    for _, client in ipairs({ ann, bob }) do
        assert_eq(client:eval('return Guildhall.Marks.balance("' .. client.full_name .. '")'), 0,
            'no balance for ' .. client.name)
        assert_eq(client:eval('return #Guildhall.Marks.pending()'), 0, 'no pending claim for ' .. client.name)
    end
end)

test('boss_kill_queues_while_restricted', function(ctx)
    local clients = guild_party(ctx)
    for _, client in ipairs(clients) do
        client:set_restriction('Combat', true)
        client:fire('BOSS_KILL', 99, 'Boss')
    end
    ctx.world:advance(5)
    for _, client in ipairs(clients) do
        assert_eq(client:eval('return Guildhall.Tracker.pending_count()'), 1, 'queued on ' .. client.name)
        assert_eq(client:eval('return Guildhall.Marks.balance("' .. client.full_name .. '")'), 0,
            'nothing authored while restricted on ' .. client.name)
    end
    for _, client in ipairs(clients) do
        client:set_restriction('Combat', false)
    end
    ctx.world:advance(5)
    for _, client in ipairs(clients) do
        assert_eq(client:eval('return Guildhall.Marks.balance("' .. client.full_name .. '")'), 5,
            'authored on lift for ' .. client.name)
    end
end)

test('battleground_and_hk_block_claim', function(ctx)
    local clients = guild_party(ctx)
    for _, client in ipairs(clients) do
        client:set_instance({ in_instance = true, instance_type = 'pvp', name = 'Gulch', instance_id = 7 })
        client:fire('PVP_MATCH_COMPLETE', 1, 600)
        client:set_pvp_kills(5)
    end
    ctx.world:advance(5)
    for _, client in ipairs(clients) do
        assert_eq(client:eval('return Guildhall.Marks.balance("' .. client.full_name .. '")'), 6,
            'bg 5 plus one hk block for ' .. client.name)
    end
end)

test('attendance_inside_window_claims', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    local clients = { ann }
    for _, name in ipairs({ 'Bob', 'Cid', 'Dee' }) do
        clients[#clients + 1] = ctx.world:client(name, 2)
    end
    ctx.world:set_network({ loss_rate = 0, duplicate_rate = 0 })
    local starts = ann:eval('return Guildhall.Clock.now()')
    assert_true(ann:eval('return Guildhall.Calendar.create("Raid night", ' .. tostring(starts) .. ')'),
        'the officer created the event')
    ctx.world:advance(5)
    ctx.world:set_group({ 'Ann', 'Bob', 'Cid', 'Dee' })
    ctx.world:advance(5)
    for _, client in ipairs(clients) do
        assert_eq(client:eval('return Guildhall.Marks.balance("' .. client.full_name .. '")'), 10,
            'attendance credited ' .. client.name)
    end
end)

test('invalid_event_disables_detection', function(ctx)
    ctx.world:disable_event('BOSS_KILL')
    local ann = ctx.world:client('Ann', 2)
    local line = ann:eval('return Guildhall.Tracker.status_line')
    assert_true(type(line) == 'string' and line:find('BOSS_KILL invalid', 1, true) ~= nil,
        'the status line names the invalid event')
end)
