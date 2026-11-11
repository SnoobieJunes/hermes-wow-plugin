"""T-011 acceptance tests for ``wow_new`` (created 2026-11-11).

The scaffolded addon lives under ``tmp_path``. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from wow_addon_forge import PROVIDES_TOOLS
from wow_addon_forge.apidocs import IndexStore
from wow_addon_forge.headless import World, minimal_api_index
from wow_addon_forge.tools import ForgeTools, register_tools

EVERY = ["core", "log", "sync", "trust", "window", "bridge"]


class _Ctx:
    def __init__(self) -> None:
        self.tools: list[str] = []

    def register_tool(self, **kwargs: object) -> None:
        self.tools.append(str(kwargs["name"]))


def _tools(tmp_path: Path) -> ForgeTools:
    IndexStore(tmp_path / "index").save(minimal_api_index().data)
    return ForgeTools(cache_dir=tmp_path / "index")


def test_every_block_passes_check_and_bundled_tests(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    dest = tmp_path / "Sample"
    created = json.loads(
        tools.handle_new(
            {
                "name": "Sample",
                "title": "Sample",
                "modules": EVERY,
                "dest": str(dest),
            }
        )
    )
    assert created["ok"] is True, created
    assert created["modules"] == EVERY
    assert created["slash"] == "/sample"
    checked = json.loads(tools.handle_check({"path": str(dest)}))
    assert checked["ok"] is True and checked["verdict"] == "pass", checked
    tested = json.loads(tools.handle_test({"path": str(dest)}))
    assert tested["ok"] is True and tested["verdict"] == "pass", tested
    assert tested["failed"] == 0
    assert tested["passed"] >= 1
    shutil.rmtree(dest)


def test_core_only_loads_headless(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    dest = tmp_path / "CoreOnly"
    created = json.loads(
        tools.handle_new(
            {
                "name": "CoreOnly",
                "title": "Core Only",
                "modules": ["core"],
                "dest": str(dest),
            }
        )
    )
    assert created["ok"] is True, created
    assert created["modules"] == ["core"]
    world = World(index=minimal_api_index(), rng_seed=11011)
    client = world.client("Ann", rank=2)
    client.load_addon(dest)
    assert client.errors == []
    assert "/coreonly" in client.registered_slash_commands()
    shutil.rmtree(dest)


def test_non_empty_dest_is_refused(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    dest = tmp_path / "Busy"
    dest.mkdir()
    kept = dest / "keep.txt"
    kept.write_text("leave me", encoding="utf-8")
    refused = json.loads(
        tools.handle_new(
            {
                "name": "Sample",
                "title": "Sample",
                "modules": ["core"],
                "dest": str(dest),
            }
        )
    )
    assert refused["ok"] is False
    assert refused["error"]["code"] == "dest-not-empty"
    assert kept.read_text(encoding="utf-8") == "leave me"
    assert not (dest / "Sample.toc").exists()


def test_custom_slash_registers_and_passes(tmp_path: Path) -> None:
    # [2026-11-11 T-046] Guildhall needs /gh, not the name-derived slash.
    tools = _tools(tmp_path)
    dest = tmp_path / "Probe"
    created = json.loads(
        tools.handle_new(
            {
                "name": "Probe",
                "title": "Probe",
                "modules": EVERY,
                "dest": str(dest),
                "slash": "/GH",
            }
        )
    )
    assert created["ok"] is True, created
    assert created["slash"] == "/gh"
    slash_lua = (dest / "Core" / "Slash.lua").read_text(encoding="utf-8")
    assert '"/gh"' in slash_lua
    assert "@@SLASH@@" not in slash_lua
    world = World(index=minimal_api_index(), rng_seed=46046)
    client = world.client("Ann", rank=2)
    client.load_addon(dest)
    assert client.errors == []
    assert "/gh" in client.registered_slash_commands()
    assert "/probe" not in client.registered_slash_commands()
    tested = json.loads(tools.handle_test({"path": str(dest)}))
    assert tested["ok"] is True and tested["verdict"] == "pass", tested
    shutil.rmtree(dest)


def test_invalid_slash_is_refused(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    for index, bad in enumerate(("gh", "/", "/g h", "/gh!", "")):
        dest = tmp_path / f"Bad{index}"
        refused = json.loads(
            tools.handle_new(
                {
                    "name": "Bad",
                    "title": "Bad",
                    "modules": ["core"],
                    "dest": str(dest),
                    "slash": bad,
                }
            )
        )
        assert refused["ok"] is False, (bad, refused)
        assert refused["error"]["code"] == "bad-slash", (bad, refused)
        assert not dest.exists(), bad
    not_text = json.loads(
        tools.handle_new(
            {
                "name": "Bad",
                "title": "Bad",
                "modules": ["core"],
                "dest": str(tmp_path / "BadType"),
                "slash": 7,
            }
        )
    )
    assert not_text["ok"] is False
    assert not_text["error"]["code"] == "bad-argument"


def test_wow_new_is_registered() -> None:
    ctx = _Ctx()
    registered = register_tools(ctx)
    assert registered == list(PROVIDES_TOOLS)
    assert "wow_new" in registered
