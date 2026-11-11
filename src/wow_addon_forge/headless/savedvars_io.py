"""Strict SavedVariables serialisation for the headless client (created 2026-11-11).

Invariants owned by this file:
- A value the WoW client cannot write to a SavedVariables file (a Lua function, userdata,
  thread, cyclic table, NaN/Inf number, or a table key that is not a string, number or
  boolean) fails here with ``SavedVariablesError`` instead of being dropped or mangled,
  because a silently lossy export would test addon state the game never persists.
- Export preserves exact Lua table keys. Unlike ``luavm.lua_to_python``, which stringifies
  keys for JSON-shaped documentation data, a SavedVariables table may be a pure ``1..n``
  array, a sparse integer-keyed table, or a mixed integer/string/boolean-keyed table, and
  each shape round-trips to the same shape in Lua.
- Import always builds real Lua tables inside the target runtime, never Python containers
  left on the Lua side, so addon code can use ``#t``, ``pairs``, ``ipairs``, ``tinsert``
  and ``wipe`` on imported state exactly as it does in game.
- Formatted SavedVariables text is valid Lua 5.1 that ``luavm.run_chunk`` can load back to
  an identical value; every control byte, backslash and quote in a string is escaped.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

# [2026-11-11 T-007] Lua 5.1 numbers are doubles, so integers are only exact up to 2^53;
# an integral float past that bound stays a float rather than becoming a Python int whose
# decimal text would name a different double when Lua reads it back.
_MAX_SAFE_INTEGER = 2**53

_MAX_DEPTH = 64

_LUA_KEYWORDS = frozenset(
    {
        "and",
        "break",
        "do",
        "else",
        "elseif",
        "end",
        "false",
        "for",
        "function",
        "if",
        "in",
        "local",
        "nil",
        "not",
        "or",
        "repeat",
        "return",
        "then",
        "true",
        "until",
        "while",
    }
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SavedVariablesError(ValueError):
    """Raised when a value cannot be serialised as SavedVariables data.

    Why this exists:
        Callers must tell the addon author exactly which variable, and where inside it,
        holds state the WoW client would refuse to persist, instead of reporting a bare
        conversion failure with no location.

    Args:
        var_name: The SavedVariables global the offending value belongs to.
        path: Location of the offending value inside that global, in dotted/bracketed
            form rooted at ``var_name`` (for example ``MyDB.profile.items[3]``); equal to
            ``var_name`` when the top-level value itself is at fault.
        reason: Why the value cannot be serialised.

    Attributes:
        var_name: The ``var_name`` passed in.
        path: The ``path`` passed in.
        reason: The ``reason`` passed in. ``str(exc)`` is ``f"{path}: {reason}"``.

    Failure modes:
        This exception is itself the failure report; constructing it never fails.
    """

    def __init__(self, var_name: str, path: str, reason: str) -> None:
        self.var_name = var_name
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


def _child_path(path: str, key: Any) -> str:
    if isinstance(key, str) and _IDENTIFIER_RE.match(key):
        return f"{path}.{key}"
    if isinstance(key, bool):
        return f"{path}[{str(key).lower()}]"
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}[{key!r}]"


def _safe_integer(value: float) -> int | None:
    if value.is_integer() and abs(value) <= _MAX_SAFE_INTEGER:
        return int(value)
    return None


def _export_number(value: float, *, var_name: str, path: str) -> int | float:
    # [2026-11-11 T-007] The client writes numbers as decimal text; NaN and Inf have no
    # Lua 5.1 literal that reads back as the same value, so they are refused here rather
    # than formatted into a name Lua would resolve as an (unknown) global.
    if math.isnan(value) or math.isinf(value):
        raise SavedVariablesError(
            var_name=var_name,
            path=path,
            reason=f"non-finite number ({value!r}) cannot be saved",
        )
    as_int = _safe_integer(value)
    return as_int if as_int is not None else value


def _export_key(key: Any, *, var_name: str, path: str) -> str | int | float | bool:
    if isinstance(key, bool) or isinstance(key, str) or isinstance(key, int):
        return key
    if isinstance(key, float):
        return _export_number(key, var_name=var_name, path=path)
    from lupa import lua51

    lua_type = lua51.lua_type(key)
    kind = lua_type if lua_type is not None else type(key).__name__
    raise SavedVariablesError(
        var_name=var_name,
        path=path,
        reason=f"unserialisable table key of type {kind}",
    )


def export_saved_value(value: Any, *, var_name: str) -> Any:
    """Convert a Lua (or Python) SavedVariables value into plain Python data.

    Why this exists:
        Persisting or comparing addon state from Python needs plain data, but the generic
        ``luavm.lua_to_python`` conversion stringifies keys and drops functions silently.
        SavedVariables demand the opposite: exact keys and a loud refusal of anything the
        client itself could not write to disk.

    Args:
        value: The value read from ``_G[var_name]`` in a ``lupa.lua51`` runtime, or an
            equivalent plain Python value (``None``, ``bool``, ``int``, ``float``,
            ``str``, ``list`` or ``dict``).
        var_name: The SavedVariables global ``value`` came from; used only to locate
            failures in the raised error.

    Returns:
        Plain Python data. ``None``, ``bool``, ``str`` and ``int`` pass through; a finite
        integral float within the exactly-representable range becomes an ``int``, any
        other finite float stays a ``float``. A table whose keys are exactly ``1..n``
        contiguous ints (``n >= 1``) becomes a ``list``; an empty table becomes ``{}``;
        any other table becomes a ``dict`` keeping its ``str``/``int``/``float``/``bool``
        keys (integral float keys become ``int`` keys).

    Failure modes:
        Raises ``SavedVariablesError`` for a NaN/Inf number or key, a key that is not a
        string, number or boolean, a Lua function, userdata or thread anywhere in the
        value, any other unrecognised object, and for nesting deeper than 64 levels,
        which a cyclic table always reaches.
    """
    return _export_value(value, var_name=var_name, path=var_name, depth=0, seen=set())


def _export_value(value: Any, *, var_name: str, path: str, depth: int, seen: set[int]) -> Any:
    # [2026-11-11 T-007] The depth limit is the real cycle guard for Lua tables: lupa may
    # hand back a fresh wrapper object for the same subtable on every lookup, so id()
    # alone cannot recognise a Lua cycle. The id set still catches Python-side cycles
    # (and same-wrapper Lua cycles) immediately, and entries leave the set on exit so a
    # shared but acyclic subtable (a DAG) exports once per reference, as the client
    # would write it.
    if depth > _MAX_DEPTH:
        raise SavedVariablesError(
            var_name=var_name,
            path=path,
            reason="table nested deeper than 64 levels (cyclic table?)",
        )
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        return _export_number(value, var_name=var_name, path=path)
    if isinstance(value, list):
        return _export_sequence(value, var_name=var_name, path=path, depth=depth, seen=seen)
    if isinstance(value, dict):
        pairs = list(value.items())
        return _export_pairs(pairs, value, var_name=var_name, path=path, depth=depth, seen=seen)
    from lupa import lua51

    lua_type = lua51.lua_type(value)
    if lua_type == "table":
        pairs = [(key, item) for key, item in value.items()]
        return _export_pairs(pairs, value, var_name=var_name, path=path, depth=depth, seen=seen)
    kind = lua_type if lua_type is not None else type(value).__name__
    raise SavedVariablesError(
        var_name=var_name,
        path=path,
        reason=f"unserialisable Lua {kind}",
    )


def _export_sequence(
    value: list[Any], *, var_name: str, path: str, depth: int, seen: set[int]
) -> list[Any]:
    marker = id(value)
    if marker in seen:
        raise SavedVariablesError(
            var_name=var_name,
            path=path,
            reason="cyclic table cannot be saved",
        )
    seen.add(marker)
    try:
        return [
            _export_value(
                item,
                var_name=var_name,
                path=_child_path(path, index),
                depth=depth + 1,
                seen=seen,
            )
            for index, item in enumerate(value, start=1)
        ]
    finally:
        seen.discard(marker)


def _export_pairs(
    pairs: list[tuple[Any, Any]],
    table: Any,
    *,
    var_name: str,
    path: str,
    depth: int,
    seen: set[int],
) -> Any:
    marker = id(table)
    if marker in seen:
        raise SavedVariablesError(
            var_name=var_name,
            path=path,
            reason="cyclic table cannot be saved",
        )
    if not pairs:
        return {}
    seen.add(marker)
    try:
        converted: list[tuple[str | int | float | bool, Any]] = []
        for raw_key, item in pairs:
            key = _export_key(raw_key, var_name=var_name, path=path)
            converted.append(
                (
                    key,
                    _export_value(
                        item,
                        var_name=var_name,
                        path=_child_path(path, key),
                        depth=depth + 1,
                        seen=seen,
                    ),
                )
            )
    finally:
        seen.discard(marker)
    # [2026-11-11 T-007] A boolean key must not count as the integer 1 (True == 1 in
    # Python, but [true] and [1] are different keys in Lua), so the array test checks
    # the key type before its value; a table holding both is a dict, never a list.
    int_keys = [key for key, _ in converted if isinstance(key, int) and not isinstance(key, bool)]
    if len(int_keys) == len(converted) and sorted(int_keys) == list(range(1, len(converted) + 1)):
        by_index = dict(converted)
        return [by_index[index] for index in range(1, len(converted) + 1)]
    return dict(converted)


def import_saved_value(runtime: Any, data: Any) -> Any:
    """Convert plain Python data into Lua values inside ``runtime``.

    Why this exists:
        Restoring SavedVariables into a fresh VM must put real Lua tables on the Lua
        side: addon code measures them with ``#t``, walks them with ``pairs`` and
        mutates them with ``tinsert``/``wipe``, none of which work on a Python list or
        dict that merely crossed the boundary as an opaque object.

    Args:
        runtime: A ``lupa.lua51`` runtime (from ``luavm.new_runtime``) the tables are
            created in.
        data: Plain Python data as produced by ``export_saved_value``: ``None``,
            ``bool``, ``int``, ``float``, ``str``, ``list`` or ``dict`` with
            ``str``/``int``/``float``/``bool`` keys.

    Returns:
        The corresponding Lua value. Scalars pass through as the values ``runtime``
        converts at assignment time; a ``list`` becomes a Lua table populated at
        1-based indices in order, and a ``dict`` becomes a Lua table populated
        key-for-key. Nested containers become nested Lua tables.

    Failure modes:
        Raises ``SavedVariablesError`` for a value or dict key outside the plain-data
        shapes above, and for nesting deeper than 64 levels, which a cyclic Python
        structure always reaches.
    """
    return _import_value(runtime, data, path="<import>", depth=0, seen=set())


def _import_value(runtime: Any, data: Any, *, path: str, depth: int, seen: set[int]) -> Any:
    if depth > _MAX_DEPTH:
        raise SavedVariablesError(
            var_name="<import>",
            path=path,
            reason="table nested deeper than 64 levels (cyclic table?)",
        )
    if data is None or isinstance(data, (bool, str, int, float)):
        return data
    if isinstance(data, (list, dict)):
        marker = id(data)
        if marker in seen:
            raise SavedVariablesError(
                var_name="<import>",
                path=path,
                reason="cyclic table cannot be saved",
            )
        seen.add(marker)
        try:
            # [2026-11-11 T-007] Building the table empty and assigning each entry
            # keeps sparse integer keys sparse: table_from on a sequence would renumber
            # a dict like {[1] = "a", [5] = "b"} into a dense 1..2 array.
            table = runtime.table()
            if isinstance(data, list):
                entries: list[tuple[Any, Any]] = list(enumerate(data, start=1))
            else:
                entries = list(data.items())
            for key, item in entries:
                lua_key = _import_key(key, path=path)
                table[lua_key] = _import_value(
                    runtime,
                    item,
                    path=_child_path(path, key),
                    depth=depth + 1,
                    seen=seen,
                )
            return table
        finally:
            seen.discard(marker)
    raise SavedVariablesError(
        var_name="<import>",
        path=path,
        reason=f"unserialisable Python {type(data).__name__}",
    )


def _import_key(key: Any, *, path: str) -> str | int | float | bool:
    if isinstance(key, (bool, str, int, float)):
        return key
    raise SavedVariablesError(
        var_name="<import>",
        path=path,
        reason=f"unserialisable table key of type {type(key).__name__}",
    )


def format_saved_variables_lua(variables: Mapping[str, Any]) -> str:
    """Format exported SavedVariables as Lua 5.1 SavedVariables file text.

    Why this exists:
        The on-disk form the client reads and writes is ordinary Lua assignment text;
        producing it here, with the same escaping the client depends on, lets a saved
        state be stored, diffed and loaded back through ``luavm.run_chunk`` unchanged.

    Args:
        variables: Mapping of SavedVariables global name to plain Python data as
            produced by ``export_saved_value``.

    Returns:
        One ``<var_name> = <lua_literal>`` assignment per variable, each ending with a
        newline, in mapping order. An empty mapping returns an empty string.

    Failure modes:
        Raises ``SavedVariablesError`` for a variable name that is not a valid Lua
        identifier (or is a Lua keyword), for a NaN/Inf number or key, for an
        unsupported value or key type, and for nesting deeper than 64 levels.
    """
    chunks: list[str] = []
    for var_name, value in variables.items():
        if not _IDENTIFIER_RE.match(var_name) or var_name in _LUA_KEYWORDS:
            raise SavedVariablesError(
                var_name=var_name,
                path=var_name,
                reason="invalid SavedVariables name",
            )
        literal = _format_value(value, var_name=var_name, path=var_name, depth=0, indent=0)
        chunks.append(f"{var_name} = {literal}\n")
    return "".join(chunks)


def _format_value(value: Any, *, var_name: str, path: str, depth: int, indent: int) -> str:
    if depth > _MAX_DEPTH:
        raise SavedVariablesError(
            var_name=var_name,
            path=path,
            reason="table nested deeper than 64 levels (cyclic table?)",
        )
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _format_float(value, var_name=var_name, path=path)
    if isinstance(value, str):
        return _format_string(value)
    if isinstance(value, list):
        if not value:
            return "{}"
        inner = "\t" * (indent + 1)
        lines = ["{"]
        for index, item in enumerate(value, start=1):
            rendered = _format_value(
                item,
                var_name=var_name,
                path=_child_path(path, index),
                depth=depth + 1,
                indent=indent + 1,
            )
            lines.append(f"{inner}{rendered},")
        lines.append("\t" * indent + "}")
        return "\n".join(lines)
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = "\t" * (indent + 1)
        lines = ["{"]
        for raw_key, item in value.items():
            key = _export_key(raw_key, var_name=var_name, path=path)
            rendered = _format_value(
                item,
                var_name=var_name,
                path=_child_path(path, key),
                depth=depth + 1,
                indent=indent + 1,
            )
            lines.append(f"{inner}[{_format_key(key)}] = {rendered},")
        lines.append("\t" * indent + "}")
        return "\n".join(lines)
    raise SavedVariablesError(
        var_name=var_name,
        path=path,
        reason=f"unserialisable Python {type(value).__name__}",
    )


def _format_key(key: str | int | float | bool) -> str:
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, int):
        return str(key)
    if isinstance(key, float):
        # [2026-11-11 T-007] _export_key already rejected NaN/Inf and folded integral
        # keys to int, so a float key reaching here formats with repr, which names the
        # exact same double when Lua parses it back.
        return repr(key)
    return _format_string(key)


def _format_float(value: float, *, var_name: str, path: str) -> str:
    number = _export_number(value, var_name=var_name, path=path)
    if isinstance(number, int):
        return str(number)
    # [2026-11-11 T-007] repr gives the shortest decimal that round-trips to the same
    # double, and Lua 5.1 accepts both its fixed and exponent forms as number literals.
    return repr(number)


def _format_string(value: str) -> str:
    # [2026-11-11 T-007] Decimal escapes are written with exactly three digits: Lua
    # reads at most three digits after a backslash, so a digit that follows the escape
    # in the original string can never be absorbed into it.
    pieces: list[str] = ['"']
    for char in value:
        code = ord(char)
        if char == '"':
            pieces.append('\\"')
        elif char == "\\":
            pieces.append("\\\\")
        elif char == "\n":
            pieces.append("\\n")
        elif char == "\r":
            pieces.append("\\r")
        elif char == "\t":
            pieces.append("\\t")
        elif code < 0x20 or code == 0x7F:
            pieces.append(f"\\{code:03d}")
        else:
            pieces.append(char)
    pieces.append('"')
    return "".join(pieces)
