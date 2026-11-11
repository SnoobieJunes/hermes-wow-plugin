"""T-022 driver-side checks for the Guildhall Tracker (created 2026-11-11).

The addon-side cases live in ``addons/Guildhall/Tests/tracker.lua`` (run by
``wow_test``); these run the same acceptance behaviors from pytest against
the real scaffolded folder: boss kills at and below the half-guild bar, the
restriction queue, battleground and honourable-kill claims, event
attendance, and the invalid-event status line. Nothing here opens
``/Applications``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wow_addon_forge.headless import World, minimal_api_index

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "addons" / "Guildhall"


def _guild_group(world: World, names: list[str]) -> list[Any]:
    clients = [world.client(name, rank=2) for name in names]
    for client in clients:
        client.load_addon(ADDON)
    world.set_group(names)
    return clients


def _balance(client: Any) -> Any:
    return client.run_lua(f'return Guildhall.Marks.balance("{client.full_name}")')


def test_boss_kill_half_guild_claims_and_attests() -> None:
    world = World(index=minimal_api_index(), rng_seed=22021)
    world.set_network(loss_rate=0, duplicate_rate=0)
    clients = _guild_group(world, ["Ann", "Bob", "Cid", "Dee"])
    for client in clients:
        client.set_instance(in_instance=True, instance_type="party", name="Pit", instance_id=42)
        client.fire("BOSS_KILL", 99, "Boss")
    world.advance(10)
    for client in clients:
        assert _balance(client) == 5
        assert client.errors == []


def test_boss_kill_under_half_guild_authors_nothing() -> None:
    world = World(index=minimal_api_index(), rng_seed=22022)
    world.set_network(loss_rate=0, duplicate_rate=0)
    ann = world.client("Ann", rank=2)
    bob = world.client("Bob", rank=2)
    # Three unguilded group members: two of five is below the half bar.
    for name in ("Pug1", "Pug2", "Pug3"):
        world.client(name, rank=None)
    for client in (ann, bob):
        client.load_addon(ADDON)
    world.set_group(["Ann", "Bob", "Pug1", "Pug2", "Pug3"])
    for client in (ann, bob):
        client.set_instance(in_instance=True, instance_type="party", name="Pit", instance_id=42)
        client.fire("BOSS_KILL", 99, "Boss")
    world.advance(10)
    for client in (ann, bob):
        assert _balance(client) == 0
        assert client.run_lua("return #Guildhall.Marks.pending()") == 0
        assert client.errors == []


def test_boss_kill_queues_under_restriction_and_authors_on_lift() -> None:
    world = World(index=minimal_api_index(), rng_seed=22023)
    world.set_network(loss_rate=0, duplicate_rate=0)
    clients = _guild_group(world, ["Ann", "Bob", "Cid", "Dee"])
    for client in clients:
        client.set_instance(in_instance=True, instance_type="party", name="Pit", instance_id=42)
        client.set_restriction("Combat", True)
        client.fire("BOSS_KILL", 99, "Boss")
    world.advance(10)
    for client in clients:
        assert client.run_lua("return Guildhall.Tracker.pending_count()") == 1
        assert _balance(client) == 0
        assert client.run_lua("return #Guildhall.Marks.pending()") == 0
    for client in clients:
        client.set_restriction("Combat", False)
    world.advance(10)
    for client in clients:
        assert client.run_lua("return Guildhall.Tracker.pending_count()") == 0
        assert _balance(client) == 5
        assert client.errors == []


def test_battleground_and_hk_delta_claim() -> None:
    world = World(index=minimal_api_index(), rng_seed=22024)
    world.set_network(loss_rate=0, duplicate_rate=0)
    clients = _guild_group(world, ["Ann", "Bob", "Cid", "Dee"])
    for client in clients:
        client.set_instance(in_instance=True, instance_type="pvp", name="Gulch", instance_id=7)
        client.fire("PVP_MATCH_COMPLETE", 1, 600)
    world.advance(10)
    for client in clients:
        assert _balance(client) == 5
    # Five honourable kills each: one block, one Mark, attested by the group.
    for client in clients:
        client.set_pvp_kills(5)
    world.advance(10)
    for client in clients:
        assert _balance(client) == 6
        assert client.errors == []


def test_attendance_inside_event_window_claims() -> None:
    world = World(index=minimal_api_index(), rng_seed=22025)
    world.set_network(loss_rate=0, duplicate_rate=0)
    ann = world.client("Ann", rank=1)
    others = [world.client(name, rank=2) for name in ("Bob", "Cid", "Dee")]
    clients = [ann, *others]
    for client in clients:
        client.load_addon(ADDON)
    event_id = ann.run_lua(f'return Guildhall.Calendar.create("Raid night", {world.server_time})')
    assert isinstance(event_id, str) and event_id
    world.advance(10)
    # Forming the group inside the window is the attendance detection.
    world.set_group(["Ann", "Bob", "Cid", "Dee"])
    world.advance(10)
    for client in clients:
        assert _balance(client) == 10
        assert client.errors == []


def test_invalid_event_disables_detection_and_status_says_so() -> None:
    world = World(index=minimal_api_index(), rng_seed=22026)
    world.set_network(loss_rate=0, duplicate_rate=0)
    world.disable_event("BOSS_KILL")
    ann = world.client("Ann", rank=2)
    ann.load_addon(ADDON)
    line = ann.run_lua("return Guildhall.Tracker.status_line")
    assert isinstance(line, str)
    assert "BOSS_KILL invalid" in line
    assert "battlegrounds: on" in line
    assert ann.errors == []
