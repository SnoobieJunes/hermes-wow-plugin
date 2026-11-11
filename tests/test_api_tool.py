"""Tests for the ``wow_api`` tool handler and the ``api`` CLI verb
(created 2026-11-11, T-005).

Invariants owned by this file:
- Hermetic: no network, no real clock, no ``~/.hermes``: every ``ForgeTools`` gets
  ``fetcher=``, ``cache_dir=tmp_path``, ``clock=``; every ``IndexStore`` uses tmp_path.
- The Lua fixtures are the small, hand-written, invented ones in ``test_apidocs``; no
  Blizzard source is copied here either.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import forever_install_files
from test_apidocs import (
    FakeFetcher,
    fixture_bundle,
    fixture_export_files,
    fixture_mirror_files,
)

import wow_addon_forge.tools as tools_module
from wow_addon_forge import PROVIDES_TOOLS
from wow_addon_forge.__main__ import main
from wow_addon_forge.luavm import LuaVMUnavailableError
from wow_addon_forge.tools import (
    WOW_API_ACTIONS,
    WOW_API_SCHEMA,
    ForgeTools,
    register_tools,
)

FIXED_TIME = 1_800_000_000.0


class ExplodingFetcher:
    """A ``Fetcher`` whose every fetch fails with a non-``ApiIndexError``."""

    def fetch_text(self, url: str) -> str:
        """Always raise, as a broken network layer would."""
        raise RuntimeError("boom")


class RecordingContext:
    """Stand-in for the Hermes PluginContext: records every ``register_tool`` call."""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []

    def register_tool(self, name: str, **kwargs: Any) -> None:
        self.tools.append({"name": name, **kwargs})


def make_tools(
    fake_fs_factory: Any,
    cache_dir: Path,
    fetcher: Any | None = None,
    files: dict[str, str] | None = None,
) -> ForgeTools:
    """Build hermetic ``ForgeTools``: fake fs, fake fetcher, tmp cache, fixed clock."""
    active = fetcher if fetcher is not None else FakeFetcher(fixture_mirror_files())
    return ForgeTools(
        fs=fake_fs_factory(files if files is not None else {}),
        fetcher=active,
        cache_dir=cache_dir,
        clock=lambda: FIXED_TIME,
    )


def call(tools: ForgeTools, args: Any) -> dict[str, Any]:
    """Run one ``wow_api`` call and decode its JSON text."""
    payload: dict[str, Any] = json.loads(tools.handle_api(args))
    return payload


def synced(tools: ForgeTools) -> dict[str, Any]:
    """Sync ``tools`` once and return the (asserted-ok) sync payload."""
    payload = call(tools, {"action": "sync"})
    assert payload["ok"] is True
    return payload


def test_01_sync_then_status(fake_fs_factory: Any, tmp_path: Path) -> None:
    """1: sync builds and caches the index (auto notes the mirror fallback); status ages 0."""
    assert fixture_bundle().build == "1.60.1.70888"
    tools = make_tools(fake_fs_factory, tmp_path)
    payload = call(tools, {"action": "sync"})
    assert payload["ok"] is True
    assert payload["action"] == "sync"
    assert payload["build"] == "1.60.1.70888"
    assert payload["source"] == "mirror"
    assert payload["counts"]
    cache_file = Path(payload["cache_file"])
    assert cache_file.is_relative_to(tmp_path)
    assert cache_file.exists()
    assert "fell back" in payload["note"]
    assert "BlizzardInterfaceCode" in payload["note"]
    mirror = call(tools, {"action": "sync", "source": "mirror"})
    assert mirror["ok"] is True
    assert "note" not in mirror
    status = call(tools, {"action": "status"})
    assert status["ok"] is True
    assert status["build"] == "1.60.1.70888"
    assert status["age_seconds"] == 0


def test_02_queries_before_sync_are_no_index(fake_fs_factory: Any, tmp_path: Path) -> None:
    """2: status/lookup/search/events before any sync are no-index and fetch nothing."""
    fetcher = FakeFetcher(fixture_mirror_files())
    tools = make_tools(fake_fs_factory, tmp_path, fetcher)
    calls: list[dict[str, Any]] = [
        {"action": "status"},
        {"action": "lookup", "name": "C_ForgeChat.SendPing"},
        {"action": "search", "query": "forge"},
        {"action": "events"},
    ]
    for args in calls:
        payload = call(tools, args)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "no-index"
        assert "sync" in payload["error"]["hint"]
    assert fetcher.urls == []


def test_03_lookup_hits_misses_and_bad_names(fake_fs_factory: Any, tmp_path: Path) -> None:
    """3: lookup answers hits as ok, misses as found False, bad names as bad-argument."""
    tools = make_tools(fake_fs_factory, tmp_path)
    synced(tools)
    hit = call(tools, {"action": "lookup", "name": "C_ForgeChat.SendPing"})
    assert hit["ok"] is True
    assert hit["found"] is True
    assert len(hit["args"]) == 4
    miss = call(tools, {"action": "lookup", "name": "GetForgeInfoo"})
    assert miss["ok"] is True
    assert miss["found"] is False
    assert miss["kind"] == "unknown"
    assert miss["nearest"]
    bad_calls: list[dict[str, Any]] = [
        {"action": "lookup"},
        {"action": "lookup", "name": "  "},
        {"action": "lookup", "name": 7},
    ]
    for args in bad_calls:
        payload = call(tools, args)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "bad-argument"


def test_04_search_and_events_require_and_use_query(fake_fs_factory: Any, tmp_path: Path) -> None:
    """4: search needs a text query; events lists with and without one."""
    tools = make_tools(fake_fs_factory, tmp_path)
    synced(tools)
    bad_calls: list[dict[str, Any]] = [
        {"action": "search"},
        {"action": "search", "query": "  "},
        {"action": "search", "query": 7},
        {"action": "events", "query": 7},
    ]
    for args in bad_calls:
        payload = call(tools, args)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "bad-argument"
    found = call(tools, {"action": "search", "query": "forge"})
    assert found["ok"] is True
    assert found["total"] > 0
    assert found["results"]
    all_events = call(tools, {"action": "events"})
    assert all_events["ok"] is True
    assert all_events["total"] == 3
    filtered = call(tools, {"action": "events", "query": "log"})
    assert filtered["ok"] is True
    assert [item["name"] for item in filtered["events"]] == ["FORGE_LOG_UNFILTERED"]


def test_05_bad_action_and_non_mapping_args(fake_fs_factory: Any, tmp_path: Path) -> None:
    """5: a missing/unknown/non-string action, and non-mapping args, are bad-argument."""
    tools = make_tools(fake_fs_factory, tmp_path)
    for args in ({}, {"action": "explode"}, {"action": 7}):
        payload = call(tools, args)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "bad-argument"
        for action in WOW_API_ACTIONS:
            assert action in payload["error"]["message"]
    for args in ([], None):
        payload = call(tools, args)
        assert payload["ok"] is False
        assert payload["error"]["code"] == "bad-argument"


def test_06_export_source_refused_and_unknown_source(fake_fs_factory: Any, tmp_path: Path) -> None:
    """6: source export with no export on disk is export-not-found; others bad-argument."""
    fetcher = FakeFetcher(fixture_mirror_files())
    tools = make_tools(fake_fs_factory, tmp_path, fetcher)
    payload = call(tools, {"action": "sync", "source": "export"})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "export-not-found"
    assert fetcher.urls == []
    assert list(tmp_path.iterdir()) == []
    other = call(tools, {"action": "sync", "source": "carrier-pigeon"})
    assert other["ok"] is False
    assert other["error"]["code"] == "bad-argument"
    assert fetcher.urls == []
    assert list(tmp_path.iterdir()) == []


def test_07_flavor_spellings(fake_fs_factory: Any, tmp_path: Path) -> None:
    """7: flavor _forever_ syncs; flavor retail is bad-argument."""
    tools = make_tools(fake_fs_factory, tmp_path)
    payload = call(tools, {"action": "sync", "flavor": "_forever_"})
    assert payload["ok"] is True
    assert payload["flavor"] == "forever"
    retail = call(tools, {"action": "status", "flavor": "retail"})
    assert retail["ok"] is False
    assert retail["error"]["code"] == "bad-argument"


def test_08_missing_documentation_file_fails_the_sync(fake_fs_factory: Any, tmp_path: Path) -> None:
    """8: a mirror missing one documentation file is fetch-failed and writes no index."""
    files = fixture_mirror_files()
    doc_url = next(url for url in files if url.endswith("ForgeChatDocumentation.lua"))
    del files[doc_url]
    tools = make_tools(fake_fs_factory, tmp_path, FakeFetcher(files))
    payload = call(tools, {"action": "sync"})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "fetch-failed"
    assert list(tmp_path.iterdir()) == []
    status = call(tools, {"action": "status"})
    assert status["ok"] is False
    assert status["error"]["code"] == "no-index"


def test_09_fetcher_runtime_error_becomes_internal_error(
    fake_fs_factory: Any, tmp_path: Path
) -> None:
    """9: a fetcher raising RuntimeError is internal-error, surfaced and never raised."""
    tools = make_tools(fake_fs_factory, tmp_path, ExplodingFetcher())
    payload = call(tools, {"action": "sync"})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "internal-error"
    assert "RuntimeError" in payload["error"]["message"]
    assert "boom" in payload["error"]["message"]


def test_10_missing_lua_vm_is_lua_vm_unavailable(
    fake_fs_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """10: LuaVMUnavailableError from build_index maps to lua-vm-unavailable."""

    def no_vm(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise LuaVMUnavailableError("no vm")

    monkeypatch.setattr(tools_module, "build_index", no_vm)
    tools = make_tools(fake_fs_factory, tmp_path)
    payload = call(tools, {"action": "sync"})
    assert payload["ok"] is False
    assert payload["error"]["code"] == "lua-vm-unavailable"
    assert "no vm" in payload["error"]["message"]


def test_11_handle_api_ignores_extra_kwargs(fake_fs_factory: Any, tmp_path: Path) -> None:
    """11: extra Hermes session kwargs (task_id=...) are ignored."""
    tools = make_tools(fake_fs_factory, tmp_path)
    synced(tools)
    payload: dict[str, Any] = json.loads(
        tools.handle_api({"action": "status"}, task_id="t1", session_id="s1")
    )
    assert payload["ok"] is True
    assert payload["build"] == "1.60.1.70888"


def test_12_register_tools_and_wow_api_schema(fake_fs_factory: Any, tmp_path: Path) -> None:
    """12: register_tools matches PROVIDES_TOOLS; the wow_api schema pins the actions."""
    tools = make_tools(fake_fs_factory, tmp_path)
    ctx = RecordingContext()
    registered = register_tools(ctx, tools=tools)
    assert {"wow_env", "wow_api"} <= set(registered)
    assert registered == list(PROVIDES_TOOLS)
    api_tool = next(item for item in ctx.tools if item["name"] == "wow_api")
    assert api_tool["schema"] is WOW_API_SCHEMA
    assert api_tool["toolset"] == "wow"
    answered: dict[str, Any] = json.loads(api_tool["handler"]({"action": "sync"}))
    assert answered["ok"] is True
    parameters = WOW_API_SCHEMA["parameters"]
    assert parameters["required"] == ["action"]
    assert parameters["properties"]["action"]["enum"] == list(WOW_API_ACTIONS)
    for key in ("name", "query", "flavor", "source"):
        assert key in parameters["properties"]


def test_13_cli_api_verb(
    fake_fs_factory: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """13: the api CLI verb mirrors the tool: exit codes, JSON prints, usage errors."""
    tools = make_tools(fake_fs_factory, tmp_path)
    assert main(["api", "sync", "--flavor", "forever"], tools=tools) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert main(["api", "status"], tools=tools) == 0
    assert json.loads(capsys.readouterr().out)["build"] == "1.60.1.70888"
    assert main(["api", "lookup", "C_ForgeChat.SendPing"], tools=tools) == 0
    lookup = json.loads(capsys.readouterr().out)
    assert len(lookup["args"]) == 4
    assert main(["api", "search", "forge"], tools=tools) == 0
    assert json.loads(capsys.readouterr().out)["total"] > 0
    assert main(["api", "events", "log"], tools=tools) == 0
    events = json.loads(capsys.readouterr().out)
    assert [item["name"] for item in events["events"]] == ["FORGE_LOG_UNFILTERED"]
    empty = make_tools(fake_fs_factory, tmp_path / "empty")
    assert main(["api", "status"], tools=empty) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "no-index"
    with pytest.raises(SystemExit) as status_extra:
        main(["api", "status", "extra"], tools=tools)
    assert status_extra.value.code == 2
    capsys.readouterr()
    with pytest.raises(SystemExit) as sync_extra:
        main(["api", "sync", "extra"], tools=tools)
    assert sync_extra.value.code == 2
    capsys.readouterr()
    assert main(["api", "sync", "--source", "export"], tools=tools) == 1
    exported = json.loads(capsys.readouterr().out)
    assert exported["error"]["code"] == "export-not-found"


def test_14_export_and_auto_sync_use_local_export_without_network(
    fake_fs_factory: Any, tmp_path: Path
) -> None:
    """14: source export, then auto, index the fake install's export; zero fetches."""
    fetcher = FakeFetcher(fixture_mirror_files())
    tools = make_tools(fake_fs_factory, tmp_path, fetcher, files=fixture_export_files())
    payload = call(tools, {"action": "sync", "source": "export"})
    assert payload["ok"] is True
    assert payload["source"] == "export"
    assert payload["build"] == "1.60.1.70888"
    assert "BlizzardInterfaceCode" in payload["note"]
    assert fetcher.urls == []
    hit = call(tools, {"action": "lookup", "name": "C_ForgeExport.SendExportPing"})
    assert hit["ok"] is True
    assert hit["found"] is True
    auto = call(tools, {"action": "sync", "source": "auto"})
    assert auto["ok"] is True
    assert auto["source"] == "export"
    assert fetcher.urls == []


def test_15_auto_falls_back_to_mirror_without_export(fake_fs_factory: Any, tmp_path: Path) -> None:
    """15: auto on an install with no export folder uses the mirror and says so."""
    fetcher = FakeFetcher(fixture_mirror_files())
    tools = make_tools(fake_fs_factory, tmp_path, fetcher, files=forever_install_files())
    payload = call(tools, {"action": "sync", "source": "auto"})
    assert payload["ok"] is True
    assert payload["source"] == "mirror"
    assert "fell back" in payload["note"]
    assert fetcher.urls != []
