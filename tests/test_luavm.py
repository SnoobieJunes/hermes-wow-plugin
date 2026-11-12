"""Tests for run_chunk, the addon-file executor in the Lua VM seam (created 2026-11-11, T-003).

Invariants owned by this file:
- A chunk runs the way the WoW client runs an addon file: it receives its arguments as ``...``.
- Compile and runtime failures surface as ``LuaChunkError`` carrying Lua's own file-and-line
  message, never as a lupa error type.
"""

from __future__ import annotations

import pytest

from wow_addon_forge.luavm import (
    LuaChunkError,
    check_syntax,
    new_runtime,
    run_chunk,
    run_chunk_value,
)


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


def test_dumped_function_fed_to_loadstring_and_load_fails_under_sandbox() -> None:
    # [2026-11-11 T-060] Dump a real Lua 5.1 function in an unsandboxed host VM (hex-encoded
    # across the UTF-8 lupa boundary), then reconstruct the raw binary chunk inside
    # new_runtime(sandbox=True) and prove loadstring/load refuse it while string.dump is nil.
    host_rt = new_runtime(sandbox=False)
    hex_dump = str(
        host_rt.execute(
            """
            local raw = string.dump(function() return 99 end)
            return (raw:gsub(".", function(c) return string.format("%02x", string.byte(c)) end))
            """
        )
    )
    sandbox_rt = new_runtime(sandbox=True)
    assert sandbox_rt.eval("string.dump") is None
    probe = sandbox_rt.execute(
        """
        return function(hex)
            local dumped = hex:gsub("..", function(pair)
                return string.char(tonumber(pair, 16))
            end)
            local f1, e1 = loadstring(dumped)
            local sent = false
            local f2, e2 = load(function()
                if sent then return nil end
                sent = true
                return dumped
            end)
            local idx = 0
            local f3, e3 = load(function()
                idx = idx + 1
                if idx == 1 then return string.sub(dumped, 1, 1) end
                if idx == 2 then return string.sub(dumped, 2) end
                return nil
            end)
            -- Mutating globals after sandbox init must not defeat captured upvalues.
            string.byte = function() return 0 end
            _G.type = function() return "number" end
            local f4, e4 = loadstring(dumped)
            local ok_text = loadstring("return 6 * 7")()
            local text_sent = false
            local ok_load = load(function()
                if text_sent then return nil end
                text_sent = true
                return "return 40 + 2"
            end)()
            local ok_num_load = load(function()
                if idx < 10 then idx = 10; return "-- " end
                if idx == 10 then idx = 11; return 123 end
                return nil
            end)
            local bad_load_ok = pcall(load, "not-a-reader")
            return f1 == nil, e1, f2 == nil, e2, f3 == nil, e3, f4 == nil, e4,
                   ok_text, ok_load, ok_num_load ~= nil, bad_load_ok
        end
        """
    )
    results = probe(hex_dump)
    assert results == (
        True,
        "binary chunks are not allowed",
        True,
        "binary chunks are not allowed",
        True,
        "binary chunks are not allowed",
        True,
        "binary chunks are not allowed",
        42,
        42,
        True,
        False,
    )


def test_python_entry_points_reject_binary_chunk_prefix() -> None:
    binary_source = "\x1bLuaQ\x00\x01\x04\x08\x04\x08\x00"
    for sandbox in (True, False):
        runtime = new_runtime(sandbox=sandbox)
        syntax_msg = check_syntax(runtime, binary_source, "Core/Bin.lua")
        assert syntax_msg == "Core/Bin.lua:1: binary chunks are not allowed"
        with pytest.raises(LuaChunkError) as exc_chunk:
            run_chunk(runtime, binary_source, "Core/Bin.lua")
        assert exc_chunk.value.phase == "compile"
        assert "binary chunks are not allowed" in exc_chunk.value.message
        with pytest.raises(LuaChunkError) as exc_val:
            run_chunk_value(runtime, binary_source, "Core/Bin.lua")
        assert exc_val.value.phase == "compile"
        assert "binary chunks are not allowed" in exc_val.value.message


def test_attribute_filter_blocks_python_object_attribute_reads_and_writes() -> None:
    class _SecretHolder:
        secret = "top-secret"

    holder = _SecretHolder()
    runtime = new_runtime(sandbox=True)
    bridge = runtime.table()
    bridge["add_one"] = lambda n: n + 1
    bridge["holder"] = holder
    checker = runtime.execute(
        """
        return function(b)
            local call_res = b.add_one(41)
            local ok_fn_attr, err_fn_attr = pcall(function() return b.add_one.__globals__ end)
            local ok_obj_get, err_obj_get = pcall(function() return b.holder.secret end)
            local ok_obj_set, err_obj_set = pcall(function() b.holder.secret = "pwned" end)
            return call_res, ok_fn_attr, tostring(err_fn_attr),
                   ok_obj_get, tostring(err_obj_get), ok_obj_set, tostring(err_obj_set)
        end
        """
    )
    call_res, ok_fn, err_fn, ok_get, err_get, ok_set, err_set = checker(bridge)
    assert call_res == 42
    assert ok_fn is False and "attribute access on Python objects is not allowed" in err_fn
    assert ok_get is False and "attribute access on Python objects is not allowed" in err_get
    assert ok_set is False and "attribute access on Python objects is not allowed" in err_set
    assert holder.secret == "top-secret"
