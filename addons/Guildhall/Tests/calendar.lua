-- Calendar checks for Guildhall (created 2026-11-11).
-- Purpose: prove SPEC-GUILDHALL §8.2 headlessly: an officer's create replicates
-- to a member, a member's sign-up changes the officer's role counts, a sign-up
-- naming another character never counts, a member's create is refused until the
-- setting opens it, a cancel hides the event, the reminder window is 24 hours,
-- and the tab builds only when first shown.
-- Invariant: every case runs in a fresh World; no case reads another's state.

test('officer_create_shows_for_member', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    local bob = ctx.world:client('Bob', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    local id = ann:eval('return Guildhall.Calendar.create("Raid Friday", Guildhall.Clock.now() + 7200)')
    assert_true(id, 'the officer create returned an id')
    ctx.world:advance(5)
    local rows = bob:eval('return Guildhall.Calendar.events()')
    assert_eq(#rows, 1, 'the member sees the event')
    assert_eq(rows[1].id, id, 'the replicated id')
    assert_eq(rows[1].title, 'Raid Friday', 'the replicated title')
end)

test('signup_changes_role_counts', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    local bob = ctx.world:client('Bob', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    local id = ann:eval('return Guildhall.Calendar.create("Raid", Guildhall.Clock.now() + 7200)')
    assert_true(id, 'the officer created the event')
    ctx.world:advance(5)
    assert_true(bob:eval('return Guildhall.Calendar.signup("' .. id .. '", "tank", "yes")'), 'the member signed up')
    ctx.world:advance(5)
    local counts = ann:eval('return Guildhall.Calendar.role_counts("' .. id .. '")')
    assert_eq(counts.tank, 1, 'the officer sees one tank sign-up')
end)

test('signup_naming_another_is_rejected', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    local bob = ctx.world:client('Bob', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    local id = ann:eval('return Guildhall.Calendar.create("Raid", Guildhall.Clock.now() + 3600)')
    assert_true(id, 'the officer created the event')
    ctx.world:advance(5)
    -- [2026-11-11 T-020] Bob forges a sign-up naming Ann as the signer. The
    -- fold must refuse it on both clients: Sync.author applied it locally on
    -- Bob's, and Trust.receive refuses it on Ann's.
    bob:eval([[
        local record = {
            a = "]] .. bob.full_name .. [[",
            s = 999,
            t = Guildhall.Clock.now(),
            k = "event.signup",
            p = {event = "]] .. id .. [[", who = "]] .. ann.full_name .. [[", role = "dps", status = "yes"},
            v = 1,
        }
        Guildhall.Sync.author(record)
    ]])
    ctx.world:advance(5)
    local ann_rows = ann:eval('return Guildhall.Calendar.events()')
    assert_eq(#ann_rows, 1, 'the officer still sees the event')
    assert_eq(#ann_rows[1].signups, 0, 'the officer client holds no sign-up at all')
    local bob_rows = bob:eval('return Guildhall.Calendar.events()')
    assert_eq(#bob_rows, 1, 'the member still sees the event')
    assert_eq(#bob_rows[1].signups, 0, 'the member client holds no sign-up at all')
end)

test('member_create_refused_then_allowed', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    local bob = ctx.world:client('Bob', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    local refused = bob:eval('return Guildhall.Calendar.create("Member event", Guildhall.Clock.now() + 3600)')
    assert_false(refused, 'a member cannot create while the switch is off')
    assert_true(ann:eval('return Guildhall.Calendar.set_allow_member_create(true)'), 'the officer opened member creates')
    assert_true(bob:eval('return Guildhall.Calendar.set_allow_member_create(true)'), 'the member client opened member creates')
    local id = bob:eval('return Guildhall.Calendar.create("Member event", Guildhall.Clock.now() + 3600)')
    assert_true(id, 'the member create returned an id')
    ctx.world:advance(5)
    local rows = ann:eval('return Guildhall.Calendar.events()')
    assert_eq(#rows, 1, 'the officer sees the member-created event')
    assert_eq(rows[1].id, id, 'the replicated id')
end)

test('cancel_hides_event', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    local bob = ctx.world:client('Bob', 2)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    local id = ann:eval('return Guildhall.Calendar.create("Raid", Guildhall.Clock.now() + 3600)')
    assert_true(id, 'the officer created the event')
    ctx.world:advance(5)
    assert_eq(#bob:eval('return Guildhall.Calendar.events()'), 1, 'the member sees the event before the cancel')
    assert_true(ann:eval('return Guildhall.Calendar.cancel("' .. id .. '")'), 'the officer cancelled the event')
    ctx.world:advance(5)
    assert_eq(#ann:eval('return Guildhall.Calendar.events()'), 0, 'the cancelled event is gone on the officer client')
    assert_eq(#bob:eval('return Guildhall.Calendar.events()'), 0, 'the cancelled event is gone on the member client')
    assert_eq(ann:eval('return Guildhall.Calendar.role_counts("' .. id .. '")').tank, nil, 'a cancelled event has no counts')
end)

test('reminder_lists_within_24h', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    local now = ann:eval('return Guildhall.Clock.now()')
    assert_true(type(now) == 'number', 'the clock returned a number')
    local first = ann:eval('return Guildhall.Calendar.create("Soon", ' .. now .. ' + 3600)')
    local second = ann:eval('return Guildhall.Calendar.create("Later", ' .. now .. ' + 90000)')
    assert_true(first and second, 'both events were created')
    local reminders = ann:eval('return Guildhall.Calendar.reminders(' .. now .. ')')
    assert_eq(#reminders, 1, 'only the event within 24 hours is listed')
    assert_eq(reminders[1].id, first, 'the soon event is the one listed')
    assert_eq(reminders[1].title, 'Soon', 'the soon event title')
end)

test('calendar_tab_builds_only_when_first_shown', function(ctx)
    local ann = ctx.world:client('Ann', 1)
    ctx.world:set_network({loss_rate = 0, duplicate_rate = 0})
    assert_false(ann:eval('return Guildhall.CalendarTab.built'), 'the tab is not built at load')
    assert_true(ann:eval('return Guildhall.Window.show_tab("calendar")'), 'the calendar tab can be shown')
    assert_true(ann:eval('return Guildhall.CalendarTab.built'), 'showing the tab built it')
end)
