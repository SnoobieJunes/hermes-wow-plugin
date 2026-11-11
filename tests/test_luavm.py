"""Tests for run_chunk, the addon-file executor in the Lua VM seam (created 2026-11-11, T-003).

Invariants owned by this file:
- A chunk runs the way the WoW client runs an addon file: it receives its arguments as ``...``.
- Compile and runtime failures surface as ``LuaChunkError`` carrying Lua's own file-and-line
  message, never as a lupa error type.
"""

from __future__ import annotations

import pytest

from wow_addon_forge.luavm import LuaChunkError, new_runtime, run_chunk


def test_run_chunk_passes_varargs_to_the_chunk() -> None:
    runtime = new_runtime()
    ns = runtime.table()
    run_chunk(runtime, "local name, t = ...\nt.seen = name\n", "Core/A.lua", "Guildhall", ns)
    assert ns["seen"] == "Guildhall"


def test_run_chunk_returns_none_on_success() -> None:
    runtime = new_runtime()
    assert run_chunk(runtime, "local a = 1\n", "Core/Ok.lua") is None


def test_run_chunk_syntax_error_is_a_compile_failure() -> None:
    runtime = new_runtime()
    with pytest.raises(LuaChunkError) as exc:
        run_chunk(runtime, "local a = 1\nlocal b = 7 // 2\n", "Core/Bad.lua")
    assert exc.value.phase == "compile"
    assert exc.value.message.startswith("Core/Bad.lua:2:")


def test_run_chunk_runtime_error_is_a_runtime_failure() -> None:
    runtime = new_runtime()
    with pytest.raises(LuaChunkError) as exc:
        run_chunk(runtime, 'local x = 1\nerror("kaboom")\n', "Core/Boom.lua")
    assert exc.value.phase == "runtime"
    assert exc.value.message.startswith("Core/Boom.lua:2:")
    assert "kaboom" in exc.value.message
    assert str(exc.value).startswith("runtime: ")


def test_run_chunk_non_string_error_value_is_a_runtime_failure() -> None:
    runtime = new_runtime()
    with pytest.raises(LuaChunkError) as exc:
        run_chunk(runtime, "error({})\n", "Core/Table.lua")
    assert exc.value.phase == "runtime"


def test_run_chunk_sandboxed_chunk_cannot_reach_io() -> None:
    runtime = new_runtime()
    with pytest.raises(LuaChunkError) as exc:
        run_chunk(runtime, 'return io.open("x")', "Core/Leak.lua")
    assert exc.value.phase == "runtime"
    assert "io" in exc.value.message
