"""T-020 driver-side checks for the Guildhall Calendar (created 2026-11-11).

The addon-side cases live in ``addons/Guildhall/Tests/calendar.lua`` (run by
``wow_test``); these run the acceptance behaviors from pytest against the real
scaffolded folder, including a forged signup naming another character.
Nothing here opens ``/Applications``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wow_addon_forge.headless import World, minimal_api_index

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "addons" / "Guildhall"

_TITLES = (
    "local rows = Guildhall.Calendar.events(); local parts = {}; "
    "for i, row in ipairs(rows) do parts[#parts + 1] = row.title end; "
    'return table.concat(parts, "|")'
)


def _pair(seed: int) -> tuple[Any, Any, Any]:
    world = World(index=minimal_api_index(), rng_seed=seed)
    world.set_network(loss_rate=0, duplicate_rate=0)
    ann = world.client("Ann", rank=1)
    bob = world.client("Bob", rank=2)
    ann.load_addon(ADDON)
    bob.load_addon(ADDON)
    return world, ann, bob


def test_create_signup_counts_forged_signup_and_cancel() -> None:
    world, ann, bob = _pair(20020)
    now = ann.run_lua("return Guildhall.Clock.now()")
    event_id = ann.run_lua(f'return Guildhall.Calendar.create("Raid Night", {now} + 3600)')
    assert isinstance(event_id, str) and event_id
    world.advance(5)
    assert bob.run_lua(f"return (function() {_TITLES} end)()") == "Raid Night"
    assert bob.run_lua(f'return Guildhall.Calendar.signup("{event_id}", "tank", "yes")') is True
    world.advance(5)
    assert ann.run_lua(f'return Guildhall.Calendar.role_counts("{event_id}").tank') == 1
    # A forged signup naming Ann, authored directly into sync by Bob, must
    # never count: receipt is self-only and the fold requires who == author.
    bob.run_lua(
        "Guildhall.Sync.author({"
        f'a="{bob.full_name}", s=98, t=9998, k="event.signup", '
        f'p={{event="{event_id}", who="{ann.full_name}", role="healer", status="yes"}}, v=1}})'
    )
    world.advance(5)
    assert ann.run_lua(f'return Guildhall.Calendar.role_counts("{event_id}").healer') is None
    # Member create is refused while the switch is off, allowed once on.
    assert bob.run_lua(f'return Guildhall.Calendar.create("Bob Night", {now} + 7200)') is None
    ann.run_lua("return Guildhall.Calendar.set_allow_member_create(true)")
    bob.run_lua("return Guildhall.Calendar.set_allow_member_create(true)")
    bob_id = bob.run_lua(f'return Guildhall.Calendar.create("Bob Night", {now} + 7200)')
    assert isinstance(bob_id, str) and bob_id
    world.advance(5)
    assert "Bob Night" in str(ann.run_lua(f"return (function() {_TITLES} end)()"))
    # The member author's own edit replicates (event.edit is a member kind;
    # the fold admits only the author or an officer).
    assert bob.run_lua(f'return Guildhall.Calendar.edit("{bob_id}", "Bob Night II")') is True
    world.advance(5)
    assert "Bob Night II" in str(ann.run_lua(f"return (function() {_TITLES} end)()"))
    # Cancelling hides the event on both clients.
    assert ann.run_lua(f'return Guildhall.Calendar.cancel("{event_id}")') is True
    world.advance(5)
    assert "Raid Night" not in str(bob.run_lua(f"return (function() {_TITLES} end)()"))
    assert ann.errors == [] and bob.errors == []


def test_reminder_window_and_tab_lazy() -> None:
    world, ann, _bob = _pair(20021)
    assert ann.run_lua("return Guildhall.CalendarTab.built") is False
    out = ann.run_lua(
        "local now = Guildhall.Clock.now(); "
        'Guildhall.Calendar.create("Soon", now + 3600); '
        'Guildhall.Calendar.create("Later", now + 90000); '
        "local r = Guildhall.Calendar.reminders(now); "
        "local parts = {}; for i, row in ipairs(r) do parts[#parts + 1] = row.title end; "
        'return table.concat(parts, "|")'
    )
    assert out == "Soon"
    assert ann.run_lua('return Guildhall.Window.show_tab("calendar")') is True
    assert ann.run_lua("return Guildhall.CalendarTab.built") is True
    assert ann.errors == []
