-- Mirror checks for Guildhall (created 2026-11-11).
-- Purpose: prove SPEC-GUILDHALL §10 headlessly from inside the addon suite:
-- a board post lands in the bridge outbox as Discord-ready text, a pushed
-- "post" command becomes a board.post (tagged with its origin) when the
-- loading character may post and is reported refused in the outbox when they
-- may not, and an inbox item is never applied twice. The full wow_bridge
-- file round trip is proven by tests/test_guildhall_mirror.py.
-- Invariant: every case runs in a fresh World; no case reads another's state.

-- [2026-11-11 T-023] Count outbox records of one kind without depending on
-- their ids or order: the bridge owns both.
local function outbox_count_expr(kind)
    return 'local n = 0; for i = 1, #GuildhallDB.outbox do '
        .. 'if GuildhallDB.outbox[i].kind == "' .. kind .. '" then n = n + 1 end end; return n'
end

test('board_post_mirrors_to_outbox', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    ctx.world:set_network({ loss_rate = 0, duplicate_rate = 0 })
    assert_true(ann:eval('return Guildhall.Board.post("Raid Friday 8pm")'), 'the officer posted')
    assert_eq(ann:eval('return Guildhall.Mirror.scan()'), 1, 'one record mirrored')
    assert_eq(ann:eval(outbox_count_expr('board.post')), 1, 'the outbox holds the post')
    assert_eq(ann:eval('return GuildhallDB.outbox[1].text'),
        ann.full_name .. ': Raid Friday 8pm', 'the outbox text is Discord-ready')
    assert_eq(ann:eval('return Guildhall.Mirror.scan()'), 0, 'a second scan mirrors nothing twice')
end)

test('pushed_post_applies_once_with_origin_tag', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    ctx.world:set_network({ loss_rate = 0, duplicate_rate = 0 })
    ann:eval('Guildhall_Inbox = {{id = 7, t = 12, kind = "post", text = "Hello from Discord", via = "discord"}}')
    assert_eq(ann:eval('return Guildhall.Mirror.ingest()'), 1, 'the pushed post applied')
    local row = ann:eval('local rows = Guildhall.Board.rows(); return rows[1].text .. "|" .. rows[1].via')
    assert_eq(row, 'Hello from Discord|discord', 'the row carries its Discord origin')
    assert_eq(ann:eval('return Guildhall.Mirror.ingest()'), 0, 'the same inbox never applies twice')
    assert_eq(ann:eval('return #Guildhall.Board.rows()'), 1, 'still exactly one post')
end)

test('pushed_post_refused_for_member', function(ctx)
    local bob = ctx.world:client('Bob', 2)
    ctx.world:client('Ann', 1)
    ctx.world:set_network({ loss_rate = 0, duplicate_rate = 0 })
    bob:eval('Guildhall_Inbox = {{id = 9, t = 13, kind = "post", text = "Sneaky announcement", via = "discord"}}')
    assert_eq(bob:eval('return Guildhall.Mirror.ingest()'), 0, 'nothing applied for a member loader')
    assert_eq(bob:eval('return #Guildhall.Board.rows()'), 0, 'no post exists')
    assert_eq(bob:eval(outbox_count_expr('refused')), 1, 'the refusal is in the outbox')
    assert_eq(bob:eval('return Guildhall.Mirror.seen_count()'), 1, 'the refused item is still consumed once')
end)

test('unsupported_command_is_refused_not_dropped', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    ctx.world:set_network({ loss_rate = 0, duplicate_rate = 0 })
    ann:eval('Guildhall_Inbox = {{id = 11, t = 14, kind = "grant", text = "Bob 50", via = "discord"}}')
    assert_eq(ann:eval('return Guildhall.Mirror.ingest()'), 0, 'an unlanded command does not apply')
    assert_eq(ann:eval(outbox_count_expr('refused')), 1, 'and the outbox says so')
end)
