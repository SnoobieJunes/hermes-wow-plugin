"""T-042 checks for the plugin-scaffolded Guildhall addon (created 2026-11-11).

Guildhall under ``addons/Guildhall`` was created by ``wow_new`` called as a tool
in a fresh Hermes session (not hand-written); these tests run against that real
folder: its TOC/slash/theme facts, and the five-client convergence run the task
requires. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wow_addon_forge.headless import World, minimal_api_index
from wow_addon_forge.tocfile import parse_toc

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "addons" / "Guildhall"


def test_toc_slash_and_classic_theme() -> None:
    toc = parse_toc((ADDON / "Guildhall.toc").read_text(encoding="utf-8"))
    assert toc.interface == (16001,)
    assert toc.title == "Guildhall"
    for entry in toc.files:
        assert (ADDON / entry).is_file(), entry
    world = World(index=minimal_api_index(), rng_seed=42042)
    client = world.client("Ann", rank=2)
    client.load_addon(ADDON)
    assert client.errors == []
    # [2026-11-11 T-042] The scaffold was created with slash="/gh" (T-046), so
    # the name-derived /guildhall must NOT be what registers.
    assert "/gh" in client.registered_slash_commands()
    assert "/guildhall" not in client.registered_slash_commands()
    assert client.run_lua("return Guildhall.Theme.name") == "Classic"


def _author(client: Any, full: str, count: int, start: int) -> None:
    for seq in range(start, start + count):
        client.run_lua(
            "Guildhall.Sync.author({"
            f'a="{full}", s={seq}, t={1000 + seq}, k="marks.credit", '
            f'p={{who="{full}", n=1}}, v=1}})'
        )


def test_five_clients_converge_under_loss() -> None:
    # [2026-11-11 T-042] The same loss profile as the sync block's acceptance
    # run (T-017), but against the scaffolded Guildhall folder itself with
    # every block loaded (log, sync, trust, window, bridge). Clients are
    # rank-1 officers: with Trust loaded, marks.credit from a rank-2 member
    # is correctly excluded from balances, which would leave the state hash
    # empty even though the records replicated. The seed matches T-017's run:
    # convergence inside the 600s deadline is a property of that pinned run,
    # not of an arbitrary loss draw.
    world = World(index=minimal_api_index(), rng_seed=17017)
    world.set_network(loss_rate=0.3, duplicate_rate=0.3, reorder_max_delay=2.0)
    early = [world.client(name, rank=1) for name in ("Ann", "Bob", "Cid", "Dee")]
    for client in early:
        client.load_addon(ADDON)
        _author(client, client.full_name, 40, 1)
    world.advance(30)
    eve = world.client("Eve", rank=1)
    eve.load_addon(ADDON)
    _author(eve, eve.full_name, 40, 1)
    clients = [*early, eve]
    deadline = 600.0
    hashes: list[str] = []
    while world.elapsed < deadline:
        world.advance(10)
        hashes = [str(client.run_lua("return Guildhall.Sync.hash()")) for client in clients]
        counts = [
            client.run_lua("return Guildhall.Sync.report()").split(",")[4] for client in clients
        ]
        if len(set(hashes)) == 1 and hashes[0] != "" and set(counts) == {"200"}:
            break
    reports = [client.run_lua("return Guildhall.Sync.report()") for client in clients]
    assert world.elapsed <= deadline
    assert len(set(hashes)) == 1, reports
    assert hashes[0] != ""
    for report in reports:
        _sent, max_bytes, _restricted, _bucket, count = report.split(",")
        assert int(count) == 200, report
        assert int(max_bytes) <= 255, report
    for client in clients:
        assert client.errors == []
