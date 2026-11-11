"""Embedded Lua 5.1 virtual machine for wow-addon-forge (created 2026-11-11).

Invariants owned by this file:
- Every Lua check in the plugin runs in Lua 5.1, the language the WoW client embeds, and never in
  the system interpreter (5.5 on the development machine, which accepts syntax the game rejects).
- A sandboxed VM exposes only what the game exposes: no ``io``, no ``os`` table, no module loading.
  Addon code that reaches for them fails here the way it fails in game.
- ``lupa`` is imported lazily, so the plugin still loads without it and says exactly what is
  missing instead of degrading silently (docs/SPEC-PLUGIN.md §12).
"""

from __future__ import annotations

from typing import Any


class LuaVMUnavailableError(RuntimeError):
    """Raised when the embedded Lua 5.1 VM cannot be created (``lupa`` missing or too old)."""


# [2026-11-11 T-002] The WoW client has no `os` table: it exposes date/time/difftime as globals,
# and none of io/package/require/dofile/loadfile/module. `python` is lupa's bridge back into the
# host and must never be reachable from addon code. `debugstack` is the game's name for a
# traceback; the full `debug` library is not available to addons.
_SANDBOX_CHUNK = """
local traceback = debug.traceback
date, time, difftime = os.date, os.time, os.difftime
debugstack = function(...) return traceback(...) end
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
    # [2026-11-11 T-002] register_eval/register_builtins off: Lua code gets no route into Python.
    runtime = lua51.LuaRuntime(
        register_eval=False, register_builtins=False, unpack_returned_tuples=True
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
    compile_only = runtime.execute(_SYNTAX_CHUNK)
    # [2026-11-11 T-002] A leading "@" makes Lua print the name as a file, not as a source snippet.
    message = compile_only(source, "@" + chunk_name)
    return None if message is None else str(message)
