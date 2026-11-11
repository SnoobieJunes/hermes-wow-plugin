"""T-021 driver-side checks for the Guildhall Marks ledger (created 2026-11-11).

The addon-side cases live in ``addons/Guildhall/Tests/marks.lua`` (run by
``wow_test``); these run the acceptance behaviors from pytest against the real
scaffolded folder, including the officer-approval path and the exact balance
arithmetic. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wow_addon_forge.headless import World, minimal_api_index

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "addons" / "Guildhall"

_BALANCES = (
    "local rows = {}; "
    "for who, amount in pairs(Guildhall.Marks.balances()) do "
    'rows[#rows + 1] = who .. "=" .. tostring(amount) end; '
    'table.sort(rows); return table.concat(rows, "|")'
)


def _mates(*clients: Any) -> str:
    names = ", ".join(f'"{client.full_name}"' for client in clients)
    return "{" + names + "}"


def test_attest_approve_spend_refund_and_agree() -> None:
    world = World(index=minimal_api_index(), rng_seed=21021)
    world.set_network(loss_rate=0, duplicate_rate=0)
    ann = world.client("Ann", rank=1)
    bob = world.client("Bob", rank=2)
    cid = world.client("Cid", rank=2)
    dee = world.client("Dee", rank=2)
    eve = world.client("Eve", rank=2)
    clients = [ann, bob, cid, dee, eve]
    for client in clients:
        client.load_addon(ADDON)
    mates = _mates(ann, bob, cid, dee)
    # Two of the four named mates claim: exactly half, so both attest.
    for client in (bob, cid):
        claim = client.run_lua(f'return Guildhall.Marks.claim("dungeon:run1", 5, {mates})')
        assert isinstance(claim, str) and claim
    # Dee's lone claim names four mates but nobody else claims that key.
    lone = dee.run_lua(f'return Guildhall.Marks.claim("dungeon:solo", 7, {mates})')
    world.advance(10)
    assert eve.run_lua(f'return Guildhall.Marks.balance("{bob.full_name}")') == 5
    assert eve.run_lua(f'return Guildhall.Marks.balance("{dee.full_name}")') == 0
    assert ann.run_lua("return #Guildhall.Marks.pending()") == 1
    # Officer approval is the regression this file exists to lock: the fold
    # once reduced the approved claim id to a boolean and credited nothing.
    assert ann.run_lua(f'return Guildhall.Marks.approve("{lone}")') is True
    world.advance(10)
    assert eve.run_lua(f'return Guildhall.Marks.balance("{dee.full_name}")') == 7
    # Stake and refund round-trip through the officer.
    assert bob.run_lua('return Guildhall.Marks.spend(5, "quest1")') is True
    world.advance(10)
    assert eve.run_lua(f'return Guildhall.Marks.balance("{bob.full_name}")') == 0
    assert ann.run_lua('return Guildhall.Marks.refund("quest1")') is True
    world.advance(10)
    rendered = [str(client.run_lua(f"return (function() {_BALANCES} end)()")) for client in clients]
    assert len(set(rendered)) == 1, rendered
    assert f"{bob.full_name}=5" in rendered[0]
    assert f"{cid.full_name}=5" in rendered[0]
    assert f"{dee.full_name}=7" in rendered[0]
    for client in clients:
        assert client.errors == []


def test_checkpoint_and_tab() -> None:
    world = World(index=minimal_api_index(), rng_seed=21022)
    world.set_network(loss_rate=0, duplicate_rate=0)
    ann = world.client("Ann", rank=1)
    bob = world.client("Bob", rank=2)
    ann.load_addon(ADDON)
    bob.load_addon(ADDON)
    assert ann.run_lua("return Guildhall.MarksTab.built") is False
    assert ann.run_lua(f'return Guildhall.Marks.grant("{bob.full_name}", 9)') is True
    world.advance(10)
    before = ann.run_lua(f"return (function() {_BALANCES} end)()")
    assert ann.run_lua("return Guildhall.Marks.checkpoint()") is True
    world.advance(10)
    assert ann.run_lua(f"return (function() {_BALANCES} end)()") == before
    assert bob.run_lua(f"return (function() {_BALANCES} end)()") == before
    assert ann.run_lua('return Guildhall.Window.show_tab("marks")') is True
    assert ann.run_lua("return Guildhall.MarksTab.built") is True
    lines = ann.run_lua('return table.concat(Guildhall.MarksTab.lines, "|")')
    assert lines == f"{bob.full_name}: 9|pending: 0"
    assert ann.errors == [] and bob.errors == []
