"""T-017 acceptance tests for the sync building block (created 2026-11-11).

The instantiated addon and the simulation live under ``tmp_path``. Nothing here
opens ``/Applications``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from wow_addon_forge.apidocs import IndexStore
from wow_addon_forge.check import check_addon
from wow_addon_forge.headless import World, minimal_api_index
from wow_addon_forge.luavm import new_runtime

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "wow_addon_forge" / "blocks" / "core"
LOG = ROOT / "src" / "wow_addon_forge" / "blocks" / "log"
SYNC = ROOT / "src" / "wow_addon_forge" / "blocks" / "sync"
TOKEN = "@@ADDON@@"
NAME = "Sample"

CORE_FILES = [
    "Core/Namespace.lua",
    "Core/Dispatch.lua",
    "Core/Clock.lua",
    "Core/Codec.lua",
    "Core/Store.lua",
    "Core/Slash.lua",
]
LOG_FILES = ["Core/Log.lua", "Core/Reduce.lua"]
SYNC_FILES = [
    "Core/Chunk.lua",
    "Core/Throttle.lua",
    "Core/Restrict.lua",
    "Core/Sync.lua",
]


def _instantiate(root: Path) -> Path:
    addon = root / NAME
    addon.mkdir()
    sources = [(CORE, relative) for relative in CORE_FILES]
    sources += [(LOG, relative) for relative in LOG_FILES]
    sources += [(SYNC, relative) for relative in SYNC_FILES]
    for base, relative in sources:
        target = addon / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (base / relative).read_text(encoding="utf-8").replace(TOKEN, NAME)
        target.write_text(text, encoding="utf-8")
    toc = (CORE / "addon.toc").read_text(encoding="utf-8").replace(TOKEN, NAME)
    extra = LOG_FILES + SYNC_FILES
    toc_text = toc.rstrip() + "\n" + "\n".join(extra) + "\n"
    (addon / f"{NAME}.toc").write_text(toc_text, encoding="utf-8")
    return addon


def _author(client: Any, full: str, count: int, start: int) -> None:
    for seq in range(start, start + count):
        client.run_lua(
            "Sample.Sync.author({"
            f'a="{full}", s={seq}, t={1000 + seq}, k="marks.credit", '
            f'p={{who="{full}", n=1}}, v=1}})'
        )


def test_chunk_splits_and_rejoins() -> None:
    runtime = new_runtime(sandbox=True)
    source = (SYNC / "Core" / "Chunk.lua").read_text(encoding="utf-8")
    chunk = runtime.execute(source.replace(TOKEN, NAME))
    assert chunk.selftest() is True


def test_restriction_holds_the_queue_then_flushes(tmp_path: Path) -> None:
    addon = _instantiate(tmp_path)
    world = World(index=minimal_api_index(), rng_seed=17017)
    client = world.client("Ann", rank=2)
    client.load_addon(addon)
    full = client.full_name
    _author(client, full, 3, 1)
    client.set_restriction("Combat", True)
    world.advance(5)
    held = client.run_lua("return Sample.Sync.report()")
    assert held.startswith("0,"), held
    assert held.split(",")[2] == "0"
    client.set_restriction("Combat", False)
    world.advance(5)
    flushed = client.run_lua("return Sample.Sync.report()")
    sent, max_bytes, restricted, bucket, _count = flushed.split(",")
    assert int(sent) >= 3, flushed
    assert int(bucket) <= 1, flushed
    assert int(max_bytes) <= 255
    assert restricted == "0"
    shutil.rmtree(addon)


def test_five_clients_converge_under_loss(tmp_path: Path) -> None:
    addon = _instantiate(tmp_path)
    world = World(index=minimal_api_index(), rng_seed=17017)
    world.set_network(loss_rate=0.3, duplicate_rate=0.3, reorder_max_delay=2.0)
    early = [world.client(name, rank=2) for name in ("Ann", "Bob", "Cid", "Dee")]
    for client in early:
        client.load_addon(addon)
        _author(client, client.full_name, 40, 1)
    world.advance(30)
    eve = world.client("Eve", rank=2)
    eve.load_addon(addon)
    _author(eve, eve.full_name, 40, 1)
    clients = [*early, eve]
    deadline = 600.0
    hashes: list[str] = []
    while world.elapsed < deadline:
        world.advance(10)
        hashes = [str(client.run_lua("return Sample.Sync.hash()")) for client in clients]
        counts = [client.run_lua("return Sample.Sync.report()").split(",")[4] for client in clients]
        if len(set(hashes)) == 1 and hashes[0] != "" and set(counts) == {"200"}:
            break
    reports = [client.run_lua("return Sample.Sync.report()") for client in clients]
    assert world.elapsed <= deadline
    assert len(set(hashes)) == 1, reports
    assert hashes[0] != ""
    for report in reports:
        sent, max_bytes, restricted, bucket, count = report.split(",")
        assert int(count) == 200, report
        assert int(max_bytes) <= 255, report
        assert int(bucket) <= 1, report
        assert restricted == "0", report
        assert int(sent) >= 1
    shutil.rmtree(addon)


def test_generic_payload_crosses_intact(tmp_path: Path) -> None:
    # [2026-11-11 T-047] A board-style payload (text with commas, a boolean,
    # and one long enough to chunk) must arrive intact on a second client;
    # the T-017 wire form only carried {who, n}.
    addon = _instantiate(tmp_path)
    world = World(index=minimal_api_index(), rng_seed=47047)
    ann = world.client("Ann", rank=2)
    bob = world.client("Bob", rank=2)
    ann.load_addon(addon)
    bob.load_addon(addon)
    long_text = "guild, hall " * 30
    ann.run_lua(
        "Sample.Sync.author({"
        f'a="{ann.full_name}", s=1, t=1001, k="board.post", '
        'p={text="hello, guild", pin=true}, v=1})'
    )
    ann.run_lua(
        "Sample.Sync.author({"
        f'a="{ann.full_name}", s=2, t=1002, k="board.post", '
        f'p={{text="{long_text}"}}, v=1}})'
    )
    deadline = 180.0
    got: list[str] = []
    while world.elapsed < deadline:
        world.advance(5)
        got = [
            str(
                bob.run_lua(
                    f'local r = Sample.Log.get(Sample.Sync.log, "{ann.full_name}", {seq}); '
                    "return r ~= nil and r.p.text or ''"
                )
            )
            for seq in (1, 2)
        ]
        if got == ["hello, guild", long_text]:
            break
    assert got == ["hello, guild", long_text], bob.run_lua("return Sample.Sync.report()")
    pin = bob.run_lua(
        f'local r = Sample.Log.get(Sample.Sync.log, "{ann.full_name}", 1); return r.p.pin'
    )
    assert pin is True
    assert bob.errors == []
    shutil.rmtree(addon)


def test_core_log_sync_passes_wow_check(tmp_path: Path) -> None:
    addon = _instantiate(tmp_path)
    IndexStore(tmp_path / "index").save(minimal_api_index().data)
    report = check_addon(addon, index=minimal_api_index())
    assert report["verdict"] == "pass", report["findings"]
    shutil.rmtree(addon)
