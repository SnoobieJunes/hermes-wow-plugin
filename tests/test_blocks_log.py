"""T-016 acceptance tests for the log building block (created 2026-11-11).

The instantiated addon lives under ``tmp_path``. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from wow_addon_forge.apidocs import IndexStore
from wow_addon_forge.check import check_addon
from wow_addon_forge.headless import minimal_api_index
from wow_addon_forge.luavm import new_runtime

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "wow_addon_forge" / "blocks" / "core"
LOG = ROOT / "src" / "wow_addon_forge" / "blocks" / "log"
TOKEN = "@@ADDON@@"


def test_log_selftest_converges_and_compacts() -> None:
    runtime = new_runtime(sandbox=True)
    log_source = (LOG / "Core" / "Log.lua").read_text(encoding="utf-8")
    reduce_source = (LOG / "Core" / "Reduce.lua").read_text(encoding="utf-8")
    log_source = log_source.replace(TOKEN, "Sample")
    reduce_source = reduce_source.replace(TOKEN, "Sample")
    runtime.execute(log_source)
    reduce = runtime.execute(reduce_source)
    ok, detail, dropped = reduce.selftest()
    assert ok is True, detail
    assert detail == 50
    assert dropped >= 1


def test_core_plus_log_passes_wow_check(tmp_path: Path) -> None:
    name = "Sample"
    addon = tmp_path / name
    addon.mkdir()
    core_files = [
        "Core/Namespace.lua",
        "Core/Dispatch.lua",
        "Core/Clock.lua",
        "Core/Codec.lua",
        "Core/Store.lua",
        "Core/Slash.lua",
    ]
    log_files = ["Core/Log.lua", "Core/Reduce.lua"]
    for relative in core_files:
        target = addon / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (CORE / relative).read_text(encoding="utf-8").replace(TOKEN, name)
        target.write_text(text, encoding="utf-8")
    for relative in log_files:
        target = addon / relative
        text = (LOG / relative).read_text(encoding="utf-8").replace(TOKEN, name)
        target.write_text(text, encoding="utf-8")
    toc = (CORE / "addon.toc").read_text(encoding="utf-8").replace(TOKEN, name)
    toc = toc.rstrip() + "\n" + "\n".join(log_files) + "\n"
    (addon / f"{name}.toc").write_text(toc, encoding="utf-8")
    assert TOKEN not in (addon / "Core" / "Log.lua").read_text(encoding="utf-8")
    IndexStore(tmp_path / "index").save(minimal_api_index().data)
    report = check_addon(addon, index=minimal_api_index())
    assert report["verdict"] == "pass", report["findings"]
    shutil.rmtree(addon)
