"""Embedded Lua 5.1 virtual machine for wow-addon-forge (created 2026-11-11).

Invariants owned by this file:
- Every Lua check in the plugin runs in Lua 5.1, the language the WoW client embeds, and never in
  the system interpreter (5.5 on the development machine, which accepts syntax the game rejects).
- A sandboxed VM exposes only what the game exposes: no ``io``, no ``os`` table, no module loading,
  no ``string.dump``, no precompiled binary chunks (``\27Lua``) in ``loadstring``/``load``, and no
  attribute access on Python objects across the ``lupa`` boundary. Addon code that reaches for them
  fails here the way it fails in game.
- ``lupa`` is imported lazily, so the plugin still loads without it and says exactly what is
  missing instead of degrading silently (docs/SPEC-PLUGIN.md §12).
- Addon files are executed through ``run_chunk``, which rejects ``\x1b``-prefixed binary source in
  Python and reports compile and runtime failures as ``LuaChunkError`` instead of letting a lupa
  error type leak.
"""

from __future__ import annotations

from typing import Any

_LUA_BINARY_PREFIX = "\x1b"
_BINARY_CHUNK_MESSAGE = "binary chunks are not allowed"


class LuaVMUnavailableError(RuntimeError):
    """Raised when the embedded Lua 5.1 VM cannot be created (``lupa`` missing or too old)."""


# [2026-11-11 T-060] lupa's register_eval/register_builtins flags do not prevent Lua from
# indexing special attributes (such as __globals__ or __class__) on a Python callable or object
# that crosses into the VM. Raising AttributeError unconditionally lets Lua call Python callbacks
# stored in Lua tables while refusing every attribute read and write on Python objects.
def _deny_python_attributes(obj: Any, attr_name: Any, is_setting: bool) -> str:
    raise AttributeError(f"attribute access on Python objects is not allowed: {attr_name!r}")


# [2026-11-11 T-060] The WoW client has no `os` table (exposing date/time/difftime as globals),
# none of io/package/require/dofile/loadfile/module/debug, no `string.dump`, and refuses
# precompiled Lua 5.1 binary chunks (`\27Lua`), whose C undumper has no bytecode verifier.
# C primitives are captured in local upvalues before user code runs so mutating `string.byte` or
# `type` in `_G` cannot bypass the check on `loadstring` or streamed `load` readers.
_SANDBOX_CHUNK = """
local traceback = debug.traceback
local raw_loadstring = loadstring
local raw_load = load
local raw_type = type
local raw_tostring = tostring
local str_byte = string.byte
date, time, difftime = os.date, os.time, os.difftime
debugstack = function(...) return traceback(...) end
string.dump = nil
loadstring = function(source, ...)
    if raw_type(source) == "string" and str_byte(source, 1) == 27 then
        return nil, "binary chunks are not allowed"
    end
    return raw_loadstring(source, ...)
end
load = function(reader, ...)
    if raw_type(reader) ~= "function" then
        return raw_load(reader, ...)
    end
    local checked_first = false
    local rejected = false
    local compiled, err = raw_load(function()
        local piece = reader()
        if piece == nil then return nil end
        if not checked_first then
            if raw_type(piece) == "number" then
                piece = raw_tostring(piece)
            end
            if raw_type(piece) == "string" and #piece > 0 then
                checked_first = true
                if str_byte(piece, 1) == 27 then
                    rejected = true
                    return nil
                end
            end
        end
        return piece
    end, ...)
    if rejected then
        return nil, "binary chunks are not allowed"
    end
    return compiled, err
end
io, os, package, require, dofile, loadfile, module, debug, python = nil
"""

_SYNTAX_CHUNK = """
return function(source, chunk_name)
    local compiled, message = loadstring(source, chunk_name)
    if compiled then return nil end
    return message
end
"""


def new_runtime(*, sandbox: bool = True) -> Any:
    """Create a Lua 5.1 runtime.

    Why this exists:
        One factory is the seam every check and test goes through, so the Lua version and the
        sandbox are decided in exactly one place.

    Args:
        sandbox: When true (the default) remove everything the WoW client does not expose. Pass
            false only for host-side analysis that never runs addon code.

    Returns:
        A ``lupa.lua51.LuaRuntime``. Strings cross the boundary as UTF-8 text.

    Failure modes:
        Raises ``LuaVMUnavailableError`` when ``lupa`` or its Lua 5.1 build is not importable.
    """
    try:
        from lupa import lua51
    except ImportError as exc:  # pragma: no cover - exercised only on a broken install
        raise LuaVMUnavailableError(
            "The embedded Lua 5.1 VM is unavailable: install lupa>=2.1,<3 "
            "(it ships lupa.lua51). Nothing was checked."
        ) from exc
    # [2026-11-11 T-060] register_eval/register_builtins off and attribute_filter denying all
    # attribute reads/writes on Python objects: Lua code gets no route back into Python.
    runtime = lua51.LuaRuntime(
        register_eval=False,
        register_builtins=False,
        unpack_returned_tuples=True,
        attribute_filter=_deny_python_attributes,
    )
    if sandbox:
        runtime.execute(_SANDBOX_CHUNK)
    return runtime


def lua_version(runtime: Any) -> str:
    """Return the VM's ``_VERSION`` string (``"Lua 5.1"`` for every runtime this module makes)."""
    # [2026-11-11 T-002] Read the global directly: the Hermes install scanner flags `.eval(`
    # in plugin code as a caution a reviewer must read, so plugin code never calls it.
    return str(runtime.globals()["_VERSION"])


def check_syntax(runtime: Any, source: str, chunk_name: str) -> str | None:
    """Compile ``source`` as Lua 5.1 without running it.

    Why this exists:
        Models trained on newer Lua emit ``//``, ``goto`` and bitwise operators. WoW rejects them
        at load time; this reports the same error, with the same file and line, before install.

    Args:
        runtime: A runtime from ``new_runtime``.
        source: The Lua source text.
        chunk_name: The file name to show in messages (for example ``Core/Codec.lua``).

    Returns:
        ``None`` when the chunk compiles, otherwise Lua's message, e.g.
        ``Core/Codec.lua:12: unexpected symbol near '/'``.
    """
    # [2026-11-11 T-060] Reject binary chunks (\x1bLua) in Python before touching the VM, so even
    # an unsandboxed caller never hands precompiled bytecode to Lua 5.1's unverified undumper.
    if source.startswith(_LUA_BINARY_PREFIX):
        return f"{chunk_name}:1: {_BINARY_CHUNK_MESSAGE}"
    compile_only = runtime.execute(_SYNTAX_CHUNK)
    # [2026-11-11 T-002] A leading "@" makes Lua print the name as a file, not as a source snippet.
    message = compile_only(source, "@" + chunk_name)
    return None if message is None else str(message)


# [2026-11-11 T-003] Compile and call stay in one Lua helper so a failure in either phase comes
# back as values Python can classify, instead of a lupa error whose type callers must not depend
# on. `tostring` on the failure keeps a non-string error value (for example `error({})`) from
# crossing the boundary as a Lua object Python cannot report.
_RUN_CHUNK = """
return function(source, chunk_name, ...)
    local compiled, message = loadstring(source, chunk_name)
    if not compiled then return "compile", tostring(message) end
    local ok, failure = pcall(compiled, ...)
    if not ok then return "runtime", tostring(failure) end
    return nil, nil
end
"""


class LuaChunkError(RuntimeError):
    """Raised by run_chunk when a chunk fails to compile or raises while running.

    Why this exists:
        Callers report addon failures without depending on a lupa error type, so the VM seam
        translates both failure phases into this one exception.

    Args:
        phase: ``"compile"`` when Lua rejected the source, ``"runtime"`` when the compiled
            chunk raised.
        message: Lua's own message for the failure.

    Attributes:
        phase: The phase that failed, as passed in.
        message: Lua's message, as passed in. ``str(exc)`` is ``f"{phase}: {message}"``.
    """

    def __init__(self, phase: str, message: str) -> None:
        self.phase = phase
        self.message = message
        super().__init__(f"{phase}: {message}")


def run_chunk(runtime: Any, source: str, chunk_name: str, *args: Any) -> None:
    """Run ``source`` as one addon file, the way the WoW client runs it.

    Why this exists:
        The client executes each addon file as a chunk called with arguments (the addon name
        and the shared addon table), which the file reads as ``...``. Running a file any other
        way here would exercise a shape the game never produces.

    Args:
        runtime: A runtime from ``new_runtime``.
        source: The Lua source text.
        chunk_name: The file name to show in messages (for example ``Core/Namespace.lua``).
        *args: Passed to the chunk as its ``...``. Callers pass a Lua table made with
            ``runtime.table()`` when the chunk expects a table, as the shared addon table.

    Returns:
        ``None`` on success. Return values of the chunk are discarded: the client ignores
        them, and addon files communicate through the shared table instead.

    Failure modes:
        Raises ``LuaChunkError`` with phase ``"compile"`` when the source does not compile,
        and with phase ``"runtime"`` when the chunk raises. The message is Lua's own and
        starts with ``chunk_name:<line>:`` for ordinary errors.
    """
    # [2026-11-11 T-060] Reject precompiled binary chunks (\x1bLua) in Python before crossing
    # into Lua, matching the WoW client's own refusal of bytecode files.
    if source.startswith(_LUA_BINARY_PREFIX):
        raise LuaChunkError("compile", f"{chunk_name}: {_BINARY_CHUNK_MESSAGE}")
    runner = runtime.execute(_RUN_CHUNK)
    # [2026-11-11 T-003] unpack_returned_tuples=True makes the helper's two return values a
    # Python 2-tuple; a leading "@" makes Lua print chunk_name as a file in its messages.
    phase, message = runner(source, "@" + chunk_name, *args)
    if phase is not None:
        raise LuaChunkError(str(phase), str(message))


# [2026-11-11 T-005] This helper always returns exactly three values (phase, message, result)
# with explicit nils, so Python can unpack a fixed tuple whether the chunk failed or returned
# nothing; a Lua function that sometimes returns two values would make a nil first result
# indistinguishable from a short return list at the lupa boundary.
_RUN_CHUNK_VALUE = """
return function(source, chunk_name)
    local compiled, message = loadstring(source, chunk_name)
    if not compiled then return "compile", tostring(message), nil end
    local ok, result = pcall(compiled)
    if not ok then return "runtime", tostring(result), nil end
    return nil, nil, result
end
"""


def run_chunk_value(runtime: Any, source: str, chunk_name: str) -> Any:
    """Run ``source`` with no arguments and return its first return value.

    Why this exists:
        Host-side data files (the API documentation resources) communicate by RETURNING a
        table, unlike addon files, which the client calls with ``...`` and whose returns it
        ignores. This is the mirror of ``run_chunk`` for those files: same loadstring/pcall
        classification, but the value crosses back.

    Args:
        runtime: A runtime from ``new_runtime``.
        source: The Lua source text.
        chunk_name: The file name to show in messages (for example ``Events.lua``).

    Returns:
        The chunk's first return value as lupa presents it, or ``None`` when the chunk
        returns nothing. Tables stay Lua tables; callers convert with ``lua_to_python``.

    Failure modes:
        Raises ``LuaChunkError`` with phase ``"compile"`` when the source does not compile,
        and with phase ``"runtime"`` when the chunk raises.
    """
    # [2026-11-11 T-060] Reject precompiled binary chunks (\x1bLua) in Python before crossing
    # into Lua, keeping run_chunk_value aligned with run_chunk.
    if source.startswith(_LUA_BINARY_PREFIX):
        raise LuaChunkError("compile", f"{chunk_name}: {_BINARY_CHUNK_MESSAGE}")
    runner = runtime.execute(_RUN_CHUNK_VALUE)
    # [2026-11-11 T-005] A leading "@" makes Lua print chunk_name as a file in its messages,
    # exactly as in run_chunk; the helper's three explicit returns unpack as a 3-tuple.
    phase, message, result = runner(source, "@" + chunk_name)
    if phase is not None:
        raise LuaChunkError(str(phase), str(message))
    return result


def lua_to_python(value: Any) -> Any:
    """Convert a Lua value to plain JSON-shaped Python data.

    Why this exists:
        Documentation and resource files hand back Lua tables whose shape Python callers
        cannot serialise or compare. One recursive conversion owns the shape rules so every
        caller sees the same plain data.

    Args:
        value: A value that crossed the lupa boundary (or a plain Python scalar).

    Returns:
        A Lua table whose keys are exactly ``1..n`` (``n >= 1``) becomes a list in index
        order; an empty table becomes ``[]``; any other table becomes a dict with string keys
        (non-string keys via ``str()``). ``bool`` and ``str`` pass through, a float with an
        integral value becomes an ``int``, other numbers are unchanged, ``None`` stays
        ``None``, and Lua functions, userdata and threads become ``None``.

    Failure modes:
        Raises ``ValueError`` when nesting goes past 40 levels, which a cyclic table always
        does; real documentation data nests only a handful of levels.
    """
    return _lua_to_python(value, 0)


def _lua_to_python(value: Any, depth: int) -> Any:
    # [2026-11-11 T-005] The depth limit is the cycle guard: Lua tables can reference
    # themselves (Enum tables do not, but a hostile or corrupt file can), and an unguarded
    # recursion would hang instead of failing with a reportable error.
    if depth > 40:
        raise ValueError(
            "Lua value nested deeper than 40 levels; refusing to convert (cyclic table?)"
        )
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # [2026-11-11 T-005] Lua 5.1 has one number type; an integral float is an integer in
        # every sense the data means (enum values, counts), so it serialises as one.
        return int(value) if value.is_integer() else value
    from lupa import lua51

    if lua51.lua_type(value) != "table":
        return None
    pairs: list[tuple[Any, Any]] = [(key, item) for key, item in value.items()]
    if not pairs:
        return []
    indexed: dict[int, Any] = {}
    is_array = True
    for key, item in pairs:
        if isinstance(key, bool):
            is_array = False
            break
        if isinstance(key, int):
            indexed[key] = item
        elif isinstance(key, float) and key.is_integer():
            indexed[int(key)] = item
        else:
            is_array = False
            break
    if is_array and sorted(indexed) == list(range(1, len(pairs) + 1)):
        return [_lua_to_python(indexed[index], depth + 1) for index in range(1, len(pairs) + 1)]
    converted: dict[str, Any] = {}
    for key, item in pairs:
        if isinstance(key, str):
            dict_key = key
        elif isinstance(key, float) and key.is_integer():
            dict_key = str(int(key))
        elif isinstance(key, (bool, int, float)) or key is None:
            dict_key = str(key)
        else:
            dict_key = str(_lua_to_python(key, depth + 1))
        converted[dict_key] = _lua_to_python(item, depth + 1)
    return converted
