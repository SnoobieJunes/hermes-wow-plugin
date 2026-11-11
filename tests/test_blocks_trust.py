"""T-018 acceptance tests for the trust building block (created 2026-11-11).

The instantiated addon lives under ``tmp_path``. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from wow_addon_forge.apidocs import IndexStore
from wow_addon_forge.check import check_addon
from wow_addon_forge.headless import World, minimal_api_index

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "wow_addon_forge" / "blocks" / "core"
LOG = ROOT / "src" / "wow_addon_forge" / "blocks" / "log"
TRUST = ROOT / "src" / "wow_addon_forge" / "blocks" / "trust"
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
TRUST_FILES = ["Core/Trust.lua"]


def _instantiate(root: Path) -> Path:
    addon = root / NAME
    addon.mkdir()
    sources = [(CORE, relative) for relative in CORE_FILES]
    sources += [(LOG, relative) for relative in LOG_FILES]
    sources += [(TRUST, relative) for relative in TRUST_FILES]
    for base, relative in sources:
        target = addon / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (base / relative).read_text(encoding="utf-8").replace(TOKEN, NAME)
        target.write_text(text, encoding="utf-8")
    toc = (CORE / "addon.toc").read_text(encoding="utf-8").replace(TOKEN, NAME)
    extra = LOG_FILES + TRUST_FILES
    toc_text = toc.rstrip() + "\n" + "\n".join(extra) + "\n"
    (addon / f"{NAME}.toc").write_text(toc_text, encoding="utf-8")
    return addon


def _record(author: str, seq: int, kind: str, who: str) -> str:
    return f'{{a="{author}", s={seq}, t={1000 + seq}, k="{kind}", p={{who="{who}", n=1}}, v=1}}'


def _receive(author: str, seq: int, kind: str, who: str, sender: str) -> str:
    record = _record(author, seq, kind, who)
    return f'Sample.Trust.receive(Sample.Trust.log, {record}, "{sender}")'


def _balance(who: str) -> str:
    return (
        f'local state = Sample.Reduce.fold(Sample.Trust.log); return state.balances["{who}"] or 0'
    )


def test_trust_rules_hold_in_a_headless_roster(tmp_path: Path) -> None:
    addon = _instantiate(tmp_path)
    world = World(index=minimal_api_index(), rng_seed=18018)
    world.client("Gina", rank=0)
    owen = world.client("Owen", rank=1)
    world.client("Mia", rank=2)
    world.client("Ned", rank=None)
    viewer = world.client("Vera", rank=2)
    viewer.load_addon(addon)
    mia = "Mia-Forever"
    owen_name = owen.full_name
    ned = "Ned-Forever"

    direct = viewer.run_lua("return " + _receive(mia, 1, "marks.credit", mia, mia))
    assert direct == "rejected", direct
    assert viewer.run_lua(_balance(mia)) == 0
    assert viewer.run_lua(f'return Sample.Trust.mark_of(Sample.Trust.log, "{mia}", 1)') == "missing"

    relayed = viewer.run_lua("return " + _receive(mia, 1, "marks.credit", mia, owen_name))
    assert relayed == "accepted", relayed
    assert viewer.run_lua(_balance(mia)) == 1
    mark = viewer.run_lua(f'return Sample.Trust.mark_of(Sample.Trust.log, "{mia}", 1)')
    assert mark == "verified", mark

    third = viewer.run_lua("return " + _receive(owen_name, 1, "marks.credit", owen_name, mia))
    assert third == "unverified", third
    third_mark = viewer.run_lua(f'return Sample.Trust.mark_of(Sample.Trust.log, "{owen_name}", 1)')
    assert third_mark == "unverified", third_mark
    assert viewer.run_lua(_balance(owen_name)) == 0

    foreign = viewer.run_lua("return " + _receive(mia, 2, "self.act", owen_name, mia))
    assert foreign == "rejected", foreign
    assert viewer.run_lua(f'return Sample.Trust.mark_of(Sample.Trust.log, "{mia}", 2)') == "missing"

    own = viewer.run_lua("return " + _receive(owen_name, 2, "marks.credit", owen_name, owen_name))
    assert own == "accepted", own
    assert viewer.run_lua(_balance(owen_name)) == 1
    owen.set_rank(3)
    assert viewer.run_lua(_balance(owen_name)) == 0
    later = viewer.run_lua("return " + _receive(owen_name, 3, "marks.credit", owen_name, owen_name))
    assert later == "rejected", later
    assert viewer.run_lua(_balance(owen_name)) == 0

    ignored = viewer.run_lua("return " + _receive(ned, 1, "marks.credit", ned, ned))
    assert ignored == "ignored", ignored
    assert viewer.run_lua(f'return Sample.Trust.mark_of(Sample.Trust.log, "{ned}", 1)') == "missing"
    shutil.rmtree(addon)


def test_core_log_trust_passes_wow_check(tmp_path: Path) -> None:
    addon = _instantiate(tmp_path)
    IndexStore(tmp_path / "index").save(minimal_api_index().data)
    report = check_addon(addon, index=minimal_api_index())
    assert report["verdict"] == "pass", report["findings"]
    shutil.rmtree(addon)
