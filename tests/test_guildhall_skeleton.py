"""Walking-skeleton checks for the Guildhall addon (created 2026-11-11, T-003).

Proves the walking skeleton's addon half: the real ``addons/Guildhall/Guildhall.toc`` parses
and its first Lua file runs in the sandboxed Lua 5.1 VM, executed the way the client runs an
addon file (as a chunk called with the addon name and the shared addon table).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wow_addon_forge.luavm import check_syntax, new_runtime, run_chunk
from wow_addon_forge.tocfile import parse_toc

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "addons" / "Guildhall"


def _load_namespace() -> tuple[Any, Any]:
    runtime = new_runtime()
    ns = runtime.table()
    toc = parse_toc((ADDON / "Guildhall.toc").read_text(encoding="utf-8"))
    source = (ADDON / toc.files[0]).read_text(encoding="utf-8")
    run_chunk(runtime, source, toc.files[0], "Guildhall", ns)
    return runtime, ns


def test_guildhall_toc_declares_interface_title_version_and_existing_files() -> None:
    toc = parse_toc((ADDON / "Guildhall.toc").read_text(encoding="utf-8"))
    assert toc.interface == (16001,)
    assert toc.title == "Guildhall"
    assert toc.version == "0.1.0"
    assert toc.files[0] == "Core/Namespace.lua"
    for entry in toc.files:
        assert (ADDON / entry).is_file(), entry


def test_first_lua_file_of_the_toc_runs_in_lua_5_1_without_error() -> None:
    """The acceptance test of T-003's addon half: Namespace.lua loads as the client loads it."""
    _, ns = _load_namespace()
    assert ns["name"] == "Guildhall"


def test_namespace_version_matches_the_toc_version() -> None:
    """The pytest check Namespace.lua's comment refers to.

    The Lua file does not read the TOC through a client API; the two ``0.1.0`` strings are
    kept equal by this test instead.
    """
    toc = parse_toc((ADDON / "Guildhall.toc").read_text(encoding="utf-8"))
    _, ns = _load_namespace()
    assert ns["version"] == toc.version


def test_every_lua_file_in_the_toc_compiles_as_lua_5_1() -> None:
    toc = parse_toc((ADDON / "Guildhall.toc").read_text(encoding="utf-8"))
    runtime = new_runtime()
    for entry in toc.files:
        if entry.endswith(".lua"):
            source = (ADDON / entry).read_text(encoding="utf-8")
            assert check_syntax(runtime, source, entry) is None, entry


def test_module_registry_iterates_in_registration_order() -> None:
    runtime, ns = _load_namespace()
    probe = runtime.eval(
        "function(ns) "
        "local a = ns:RegisterModule('Board', {}) "
        "ns:RegisterModule('Marks', {}) "
        "local seen = {} "
        "for name, module in ns:IterateModules() do "
        "seen[#seen + 1] = name .. '=' .. tostring(module == ns:GetModule(name)) "
        "end "
        "return table.concat(seen, ','), a.name, ns:GetModule('Nope') "
        "end"
    )
    assert probe(ns) == ("Board=true,Marks=true", "Board", None)


def test_module_registration_rejects_duplicates_empty_names_and_non_tables() -> None:
    runtime, ns = _load_namespace()
    attempt = runtime.eval(
        "function(ns, name, module) "
        "local ok, message = pcall(ns.RegisterModule, ns, name, module) "
        "return ok, message "
        "end"
    )
    ok, _ = attempt(ns, "Board", runtime.table())
    assert ok is True
    ok, message = attempt(ns, "Board", runtime.table())
    assert ok is False
    assert "Board" in message
    assert "already registered" in message
    ok, _ = attempt(ns, "", runtime.table())
    assert ok is False
    ok, message = attempt(ns, "Counter", 5)
    assert ok is False
    assert "must be a table" in message


def test_loading_the_namespace_file_writes_no_global() -> None:
    runtime = new_runtime()
    ns = runtime.table()
    toc = parse_toc((ADDON / "Guildhall.toc").read_text(encoding="utf-8"))
    list_globals = runtime.eval(
        "function() "
        "local names = {} "
        "for key in pairs(_G) do names[#names + 1] = tostring(key) end "
        "table.sort(names) "
        "return table.concat(names, ' ') "
        "end"
    )
    before = list_globals()
    source = (ADDON / toc.files[0]).read_text(encoding="utf-8")
    run_chunk(runtime, source, toc.files[0], "Guildhall", ns)
    assert list_globals() == before
