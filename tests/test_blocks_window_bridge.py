"""T-019 acceptance tests for the window and bridge blocks (created 2026-11-11).

The instantiated addon and the fake install live under ``tmp_path``. Nothing
here opens ``/Applications``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from wow_addon_forge.apidocs import IndexStore
from wow_addon_forge.check import check_addon
from wow_addon_forge.headless import World, format_saved_variables_lua, minimal_api_index
from wow_addon_forge.tools import ForgeTools

ROOT = Path(__file__).resolve().parents[1]
BLOCKS = ROOT / "src" / "wow_addon_forge" / "blocks"
TOKEN = "@@ADDON@@"
NAME = "Sample"

FILES = [
    "core/Core/Namespace.lua",
    "core/Core/Dispatch.lua",
    "core/Core/Clock.lua",
    "core/Core/Codec.lua",
    "core/Core/Store.lua",
    "core/Core/Slash.lua",
    "log/Core/Log.lua",
    "log/Core/Reduce.lua",
    "sync/Core/Chunk.lua",
    "sync/Core/Throttle.lua",
    "sync/Core/Restrict.lua",
    "sync/Core/Sync.lua",
    "trust/Core/Trust.lua",
    "window/UI/Theme.lua",
    "window/UI/Window.lua",
    "bridge/Bridge.lua",
    "bridge/Inbox.lua",
]


def _dest(relative: str) -> str:
    if relative == "bridge/Bridge.lua":
        return "Bridge.lua"
    if relative == "bridge/Inbox.lua":
        return "Inbox.lua"
    return relative.split("/", 1)[1]


def _instantiate(wow: Path) -> Path:
    addon = wow / "_forever_" / "Interface" / "AddOns" / NAME
    toc_files: list[str] = []
    for relative in FILES:
        dest = _dest(relative)
        target = addon / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (BLOCKS / relative).read_text(encoding="utf-8").replace(TOKEN, NAME)
        target.write_text(text, encoding="utf-8")
        toc_files.append(dest)
    toc = (BLOCKS / "core" / "addon.toc").read_text(encoding="utf-8").replace(TOKEN, NAME)
    toc = toc.replace(
        f"## SavedVariables: {NAME}DB\n",
        f"## SavedVariables: {NAME}DB\n## X-Forge-Bridge: 1\n",
    )
    header, _, _listed = toc.partition("\n\n")
    body = header + "\n\n" + "\n".join(toc_files) + "\n"
    (addon / f"{NAME}.toc").write_text(body, encoding="utf-8")
    return addon


def _known_templates() -> set[str]:
    entries = minimal_api_index().data["entries"]["template"]
    return set(entries)


def test_window_is_lazy_and_classic_uses_known_templates(tmp_path: Path) -> None:
    addon = _instantiate(tmp_path / "WoW")
    world = World(index=minimal_api_index(), rng_seed=19019)
    world.client("Mia", rank=2)
    client = world.client("Vera", rank=2)
    client.load_addon(addon)
    assert client.run_lua("return Sample.Window.built") is False
    assert client.run_lua("return type(Sample.Theme)") == "table"
    assert client.run_lua("return Sample.Theme.name") == "Classic"
    registered = client.run_lua(
        "return Sample.Window.register_tab('notes', function() Sample.Window.note_built = true end)"
    )
    assert registered is True
    assert client.run_lua("return Sample.Window.note_built") is None
    client.run_lua('SlashCmdList["SAMPLE"]("")')
    assert client.run_lua("return Sample.Window.built") is True
    assert client.run_lua("return Sample.Window.note_built") is None
    assert client.run_lua("return Sample.Window.escape_listed()") is True
    assert client.run_lua("return Sample.Window.show_tab('notes')") is True
    assert client.run_lua("return Sample.Window.note_built") is True
    used = str(client.run_lua("return Sample.Window.template_list()")).split(",")
    known = _known_templates()
    assert used
    assert set(used) <= known
    theme_templates = client.run_lua(
        "local t = Sample.Theme.templates; "
        "return t.frame .. ',' .. t.button .. ',' .. t.close .. ',' .. t.scroll"
    )
    assert set(str(theme_templates).split(",")) <= known
    shutil.rmtree(addon)


def test_bridge_outbox_pulls_and_inbox_applies_once(tmp_path: Path) -> None:
    wow = tmp_path / "WoW"
    addon = _instantiate(wow)
    world = World(index=minimal_api_index(), rng_seed=19019)
    world.client("Owen", rank=1)
    client = world.client("Vera", rank=2)
    client.load_addon(addon)
    posted = client.run_lua('return Sample.Bridge.post({id=1, t=10, kind="post", text="hello"})')
    assert posted == 1
    client.flush_saved_variables()
    saved = wow / "_forever_" / "WTF" / "Account" / "ACC" / "SavedVariables" / f"{NAME}.lua"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(
        format_saved_variables_lua(client.account_saved_variables),
        encoding="utf-8",
    )
    tools = ForgeTools(default_roots=[str(wow)], cursor_dir=tmp_path / "cursors")
    pulled = json.loads(tools.handle_bridge({"action": "pull", "addon": NAME}))
    assert pulled["ok"] is True
    assert [record["id"] for record in pulled["records"]] == [1]
    assert pulled["records"][0]["text"] == "hello"
    pushed = json.loads(
        tools.handle_bridge(
            {
                "action": "push",
                "addon": NAME,
                "records": [
                    {"id": 7, "t": 12, "kind": "note", "text": "from discord", "via": "discord"}
                ],
            }
        )
    )
    assert pushed["ok"] is True
    assert pushed["added"] == 1
    client.reload()
    assert client.run_lua("return Sample.Bridge.applied_count()") == 1
    client.reload()
    assert client.run_lua("return Sample.Bridge.applied_count()") == 1
    refused = json.loads(
        tools.handle_bridge(
            {
                "action": "push",
                "addon": NAME,
                "records": [
                    {"id": 8, "t": 13, "kind": "marks.credit", "text": "no", "via": "discord"}
                ],
            }
        )
    )
    assert refused["ok"] is True
    client.reload()
    assert client.run_lua("return Sample.Bridge.applied_count()") == 1
    assert (
        client.run_lua(
            "local n = 0; for i = 1, #SampleDB.outbox do "
            'if SampleDB.outbox[i].kind == "refused" then n = n + 1 end end; return n'
        )
        == 1
    )
    shutil.rmtree(wow)


def test_every_block_passes_wow_check(tmp_path: Path) -> None:
    addon = _instantiate(tmp_path / "WoW")
    IndexStore(tmp_path / "index").save(minimal_api_index().data)
    report = check_addon(addon, index=minimal_api_index())
    assert report["verdict"] == "pass", report["findings"]
    shutil.rmtree(addon)
