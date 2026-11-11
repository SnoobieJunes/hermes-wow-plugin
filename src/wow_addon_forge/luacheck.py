"""Lua 5.1 syntax and global-access analysis for wow-addon-forge (created 2026-11-11).

Invariants owned by this file:
- Source is compiled by the embedded Lua 5.1 VM (``luavm.new_runtime``), never by a newer
  system Lua, so a syntax verdict here is the verdict the WoW client gives at load time.
- Global reads, writes and ``Table.member`` accesses are read from the compiled chunk's own
  bytecode (``string.dump``), not from source text: comments, strings and dead spellings can
  never be mistaken for code, and locals are never mistaken for globals.
- Bytecode crosses the lupa boundary hex-encoded: lupa decodes returned Lua strings as
  UTF-8, so raw dump bytes at or above 0x80 would raise ``UnicodeDecodeError`` in transit.
- Analysis never runs the addon chunk; ``loadstring`` + ``string.dump`` only compile it, in
  an unsandboxed host-side runtime that no addon code ever executes in.
- ``Finding`` is re-exported from ``tocfile`` so every checker reports one shape
  (docs/SPEC-PLUGIN.md §4).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Any

from wow_addon_forge import luavm
from wow_addon_forge.tocfile import Finding

__all__ = [
    "FORBIDDEN_LUA_GLOBALS",
    "LUA_51_SAFE_GLOBALS",
    "Constant",
    "Finding",
    "GlobalAccess",
    "LocVar",
    "LuaFileAnalysis",
    "Proto",
    "analyze_lua",
    "check_lua_syntax",
    "collect_proto_accesses",
    "compile_proto",
]

# [2026-11-11 T-006] The standard globals WoW keeps from Lua 5.1 (plus the game's own string
# helpers and `bit`): reading one of these is never, by itself, a mistake. `os` is absent
# because the client exposes date/time/difftime as bare globals instead (see luavm).
LUA_51_SAFE_GLOBALS: frozenset[str] = frozenset(
    {
        "_G",
        "_VERSION",
        "assert",
        "bit",
        "collectgarbage",
        "date",
        "debugstack",
        "difftime",
        "error",
        "format",
        "gcinfo",
        "getfenv",
        "getmetatable",
        "ipairs",
        "loadstring",
        "math",
        "newproxy",
        "next",
        "pairs",
        "pcall",
        "print",
        "rawequal",
        "rawget",
        "rawset",
        "select",
        "setfenv",
        "setmetatable",
        "string",
        "strjoin",
        "strsplit",
        "table",
        "time",
        "tinsert",
        "tonumber",
        "tostring",
        "tremove",
        "type",
        "unpack",
        "wipe",
        "xpcall",
    }
)

# [2026-11-11 T-006] Globals the client does not expose at all (plus lupa's `python` bridge,
# which must never be reachable from addon code): any access is a load-time nil in game.
FORBIDDEN_LUA_GLOBALS: frozenset[str] = frozenset(
    {"io", "os", "package", "require", "dofile", "loadfile", "module", "python"}
)


@dataclass(frozen=True)
class GlobalAccess:
    """One read, write or member access of a global, found in compiled bytecode.

    Why this exists:
        Later checks judge names (unknown API, forbidden global, undeclared saved variable)
        from facts, so the bytecode walk reports each access once, in this shape, instead
        of every check re-decoding instructions.

    Args:
        name: The full accessed name: ``"C_Item.GetItemInfo"`` for a member access,
            ``"C_Item"`` for a bare read, ``"MyGlobal"`` for a write.
        kind: ``"read"``, ``"write"`` or ``"member"``.
        line: 1-based source line of the access, from the chunk's debug line info.
        root: The global variable or table name, e.g. ``"C_Item"``.
        member: The member name for ``kind == "member"`` (e.g. ``"GetItemInfo"``), else
            ``None``.

    Failure modes:
        None at construction.
    """

    name: str
    kind: str
    line: int
    root: str
    member: str | None = None


@dataclass(frozen=True)
class LuaFileAnalysis:
    """The analysis result for one Lua source file.

    Why this exists:
        A caller checks a whole file in one call and then splits the result by access kind,
        so syntax state and accesses travel together instead of as parallel return values.

    Args:
        file: The chunk name the source was compiled as (the file name in messages).
        syntax_error: The ``syntax`` finding when Lua 5.1 rejected the source, else ``None``.
        accesses: Every global access in the chunk, root function first, then nested
            functions in pre-order. Empty when there is a syntax error.

    Failure modes:
        None at construction; the split views below filter ``accesses`` only.
    """

    file: str
    syntax_error: Finding | None
    accesses: tuple[GlobalAccess, ...]

    @property
    def ok(self) -> bool:
        """Return whether the source compiled as Lua 5.1.

        Why this exists:
            Callers branch on "did it compile?" constantly; naming it once keeps that test
            spelled the same way everywhere.

        Returns:
            ``True`` when ``syntax_error`` is ``None``.

        Failure modes:
            None.
        """
        return self.syntax_error is None

    @property
    def reads(self) -> tuple[GlobalAccess, ...]:
        """Return the bare global reads among ``accesses``.

        Why this exists:
            Unknown-global checks judge reads separately from writes and member accesses.

        Returns:
            The accesses with ``kind == "read"``, in order.

        Failure modes:
            None.
        """
        return tuple(access for access in self.accesses if access.kind == "read")

    @property
    def writes(self) -> tuple[GlobalAccess, ...]:
        """Return the global writes among ``accesses``.

        Why this exists:
            A write to an undeclared name is judged by different rules than a read (it
            creates the global), so callers need the writes on their own.

        Returns:
            The accesses with ``kind == "write"``, in order.

        Failure modes:
            None.
        """
        return tuple(access for access in self.accesses if access.kind == "write")

    @property
    def member_accesses(self) -> tuple[GlobalAccess, ...]:
        """Return the ``Table.member`` accesses among ``accesses``.

        Why this exists:
            API-existence checks judge ``C_Item.GetItemInfo`` as one name, not as a read of
            ``C_Item`` plus noise, so member accesses are split out here.

        Returns:
            The accesses with ``kind == "member"``, in order.

        Failure modes:
            None.
        """
        return tuple(access for access in self.accesses if access.kind == "member")


# [2026-11-11 T-006] Opcode numbers from Lua 5.1 lopcodes.h. Only the ones that touch a
# global by name (GETGLOBAL/SETGLOBAL) or index a just-fetched global by a constant member
# (GETTABLE/SELF) are decoded.
_OP_GETGLOBAL = 5
_OP_GETTABLE = 6
_OP_SETGLOBAL = 7
_OP_SELF = 11

# [2026-11-11 T-006] Compile-only helper: loadstring compiles without running, string.dump
# serialises the chunk, and the dump is hex-encoded inside Lua because lupa decodes returned
# strings as UTF-8 and raw bytes >= 0x80 would raise UnicodeDecodeError crossing back.
_DUMP_CHUNK = """
return function(source, chunk_name)
    local fn, err = loadstring(source, chunk_name)
    if not fn then return nil, tostring(err) end
    local raw = string.dump(fn)
    local hex = raw:gsub(".", function(c)
        return string.format("%02x", string.byte(c))
    end)
    return hex, nil
end
"""

_SYNTAX_LINE = re.compile(r":(\d+):\s*(.*)$", re.DOTALL)

_SYNTAX_HINT = (
    "Rewrite using Lua 5.1 syntax (no goto, ::label::, // integer division, or bitwise operators)."
)


@dataclass(frozen=True)
class _Constant:
    # [2026-11-11 T-006] Constants keep their Lua type tag beside the value: the string "1",
    # the number 1.0 and nil must never be confused when an operand is resolved, and plain
    # Python values would blur exactly those cases (True == 1.0, "1" vs 1).
    kind: str  # "nil", "bool", "number" or "string"
    value: Any


@dataclass(frozen=True)
class _LocVar:
    varname: str
    startpc: int
    endpc: int


@dataclass(frozen=True)
class _Proto:
    source: str
    linedefined: int
    lastlinedefined: int
    nups: int
    numparams: int
    is_vararg: int
    maxstacksize: int
    code: tuple[int, ...]
    constants: tuple[_Constant, ...]
    protos: tuple[_Proto, ...]
    lineinfo: tuple[int, ...]
    locvars: tuple[_LocVar, ...]
    upvalues: tuple[str, ...]


class _Reader:
    """Bounds-checked cursor over one binary chunk, in the chunk's own byte order."""

    def __init__(self, data: bytes, endian: str, size_t_size: int) -> None:
        self._data = data
        self._endian = endian
        self._size_t_size = size_t_size
        self._offset = 12  # past the validated 12-byte header

    def read_bytes(self, count: int) -> bytes:
        """Return the next ``count`` bytes, or raise ``ValueError`` when truncated."""
        if count < 0 or self._offset + count > len(self._data):
            raise ValueError(
                f"truncated Lua bytecode: wanted {count} bytes at offset {self._offset}, "
                f"chunk is {len(self._data)} bytes"
            )
        chunk = self._data[self._offset : self._offset + count]
        self._offset += count
        return chunk

    def read_u8(self) -> int:
        """Return the next unsigned byte."""
        return self.read_bytes(1)[0]

    def read_int(self) -> int:
        """Return the next signed 4-byte ``int`` (header validation pinned the size to 4)."""
        return int(struct.unpack(f"{self._endian}i", self.read_bytes(4))[0])

    def read_uint(self) -> int:
        """Return the next unsigned 4-byte value (one instruction word)."""
        return int(struct.unpack(f"{self._endian}I", self.read_bytes(4))[0])

    def read_count(self, what: str) -> int:
        """Return the next ``int`` as a non-negative element count named ``what``."""
        count = self.read_int()
        if count < 0:
            raise ValueError(f"malformed Lua bytecode: negative {what} count {count}")
        return count

    def read_size_t(self) -> int:
        """Return the next ``size_t`` (4 or 8 bytes, as the header declared)."""
        fmt = "I" if self._size_t_size == 4 else "Q"
        return int(struct.unpack(f"{self._endian}{fmt}", self.read_bytes(self._size_t_size))[0])

    def read_number(self) -> float:
        """Return the next Lua number (an 8-byte double; the integral flag was checked 0)."""
        return float(struct.unpack(f"{self._endian}d", self.read_bytes(8))[0])

    def read_string(self) -> str:
        """Return the next length-prefixed string with its trailing NUL stripped."""
        length = self.read_size_t()
        if length == 0:
            return ""
        raw = self.read_bytes(length)
        if raw.endswith(b"\x00"):
            raw = raw[:-1]
        return raw.decode("utf-8", errors="replace")


def _parse_constant(reader: _Reader) -> _Constant:
    tag = reader.read_u8()
    if tag == 0:
        return _Constant(kind="nil", value=None)
    if tag == 1:
        return _Constant(kind="bool", value=reader.read_u8() != 0)
    if tag == 3:
        return _Constant(kind="number", value=reader.read_number())
    if tag == 4:
        return _Constant(kind="string", value=reader.read_string())
    raise ValueError(f"malformed Lua bytecode: unknown constant type tag {tag}")


def _parse_proto(reader: _Reader) -> _Proto:
    # [2026-11-11 T-006] Field order is ldump.c's DumpFunction exactly, and in Lua 5.1 the
    # nested protos come BEFORE the debug block (5.2+ moved things around) — reading debug
    # first would desynchronise every byte that follows.
    source = reader.read_string()
    linedefined = reader.read_int()
    lastlinedefined = reader.read_int()
    nups = reader.read_u8()
    numparams = reader.read_u8()
    is_vararg = reader.read_u8()
    maxstacksize = reader.read_u8()

    sizecode = reader.read_count("code")
    code = tuple(reader.read_uint() for _ in range(sizecode))

    sizek = reader.read_count("constants")
    constants = tuple(_parse_constant(reader) for _ in range(sizek))

    sizep = reader.read_count("protos")
    protos = tuple(_parse_proto(reader) for _ in range(sizep))

    sizelineinfo = reader.read_count("lineinfo")
    lineinfo = tuple(reader.read_int() for _ in range(sizelineinfo))

    sizelocvars = reader.read_count("locvars")
    locvars = tuple(
        _LocVar(
            varname=reader.read_string(),
            startpc=reader.read_int(),
            endpc=reader.read_int(),
        )
        for _ in range(sizelocvars)
    )

    sizeupvalues = reader.read_count("upvalues")
    upvalues = tuple(reader.read_string() for _ in range(sizeupvalues))

    return _Proto(
        source=source,
        linedefined=linedefined,
        lastlinedefined=lastlinedefined,
        nups=nups,
        numparams=numparams,
        is_vararg=is_vararg,
        maxstacksize=maxstacksize,
        code=code,
        constants=constants,
        protos=protos,
        lineinfo=lineinfo,
        locvars=locvars,
        upvalues=upvalues,
    )


def _parse_bytecode(data: bytes) -> _Proto:
    # [2026-11-11 T-006] The 12-byte header (lundump.c) pins every width the reader uses, so
    # each byte is checked against the one layout this parser implements rather than trusted:
    # a dump from any other Lua version or build must fail loudly here, not misparse quietly.
    if len(data) < 12:
        raise ValueError(f"malformed Lua bytecode: {len(data)} bytes, header alone needs 12")
    if data[0:4] != b"\x1bLua":
        raise ValueError("malformed Lua bytecode: missing \\x1bLua signature")
    if data[4] != 0x51:
        raise ValueError(f"malformed Lua bytecode: version 0x{data[4]:02x}, expected 0x51")
    if data[5] != 0:
        raise ValueError(f"malformed Lua bytecode: format {data[5]}, expected 0")
    if data[6] == 1:
        endian = "<"
    elif data[6] == 0:
        endian = ">"
    else:
        raise ValueError(f"malformed Lua bytecode: endianness byte {data[6]}, expected 0 or 1")
    if data[7] != 4:
        raise ValueError(f"malformed Lua bytecode: int size {data[7]}, expected 4")
    if data[8] not in (4, 8):
        raise ValueError(f"malformed Lua bytecode: size_t size {data[8]}, expected 4 or 8")
    if data[9] != 4:
        raise ValueError(f"malformed Lua bytecode: instruction size {data[9]}, expected 4")
    if data[10] != 8:
        raise ValueError(f"malformed Lua bytecode: number size {data[10]}, expected 8")
    if data[11] != 0:
        raise ValueError(f"malformed Lua bytecode: integral flag {data[11]}, expected 0")
    try:
        return _parse_proto(_Reader(data, endian, data[8]))
    except (struct.error, RecursionError) as exc:
        raise ValueError(f"malformed Lua bytecode: {exc}") from exc


def _string_constant(proto: _Proto, index: int) -> str | None:
    if 0 <= index < len(proto.constants):
        constant = proto.constants[index]
        if constant.kind == "string" and isinstance(constant.value, str):
            return constant.value
    return None


def _line_at(proto: _Proto, pc: int) -> int:
    if 0 <= pc < len(proto.lineinfo) and proto.lineinfo[pc] > 0:
        return proto.lineinfo[pc]
    return proto.linedefined if proto.linedefined > 0 else 1


def _collect_accesses(proto: _Proto, accesses: list[GlobalAccess]) -> None:
    # [2026-11-11 T-006] Pre-order: this function's own accesses first, then each nested
    # function's in definition order, so a file reads top-down the way its author wrote it.
    code = proto.code
    pc = 0
    while pc < len(code):
        inst = code[pc]
        # [2026-11-11 T-006] Lua 5.1 instruction layout (lopcodes.h): opcode in the low 6
        # bits, A in the next 8, then C and B in 9 bits each; Bx is B and C read as one
        # 18-bit constant index. A B/C operand at or above 0x100 is a constant index (RK),
        # not a register.
        op = inst & 0x3F
        a = (inst >> 6) & 0xFF
        bx = (inst >> 14) & 0x3FFFF
        if op == _OP_GETGLOBAL:
            gname = _string_constant(proto, bx)
            if gname is not None:
                line = _line_at(proto, pc)
                # [2026-11-11 T-006] Distinguish an expression temporary (`C_Item.GetItemInfo`)
                # from a local variable (`local CI = C_Item` or `local x; x = C_Item`). In Lua
                # 5.1's register allocator (ldebug.c luaF_getlocalname / lcode.c), active
                # locals after instruction `pc` occupy registers `0 .. active_locals - 1` where
                # `lv.startpc <= pc + 1 < lv.endpc`, and a brand-new local declared at `pc`
                # has `lv.startpc == pc + 1` (even when `startpc == endpc` right before RETURN).
                # Only a register above the active locals is a temporary that may fold with an
                # immediate GETTABLE/SELF into a `Table.member` access.
                active_locals = sum(1 for lv in proto.locvars if lv.startpc <= pc + 1 < lv.endpc)
                starts_local = any(lv.startpc == pc + 1 for lv in proto.locvars)
                is_local_target = starts_local or (a < active_locals)
                member: str | None = None
                if not is_local_target and pc + 1 < len(code):
                    next_inst = code[pc + 1]
                    next_op = next_inst & 0x3F
                    next_b = (next_inst >> 23) & 0x1FF
                    next_c = (next_inst >> 14) & 0x1FF
                    if next_op in (_OP_GETTABLE, _OP_SELF) and next_b == a:
                        if next_c & 0x100:
                            candidate = _string_constant(proto, next_c & 0xFF)
                            if candidate:
                                member = candidate
                if member is not None:
                    accesses.append(
                        GlobalAccess(
                            name=f"{gname}.{member}",
                            kind="member",
                            line=line,
                            root=gname,
                            member=member,
                        )
                    )
                    # [2026-11-11 T-006] The GETTABLE/SELF at pc + 1 is part of this one
                    # member access, so it is consumed here and never re-read on its own.
                    pc += 2
                    continue
                accesses.append(
                    GlobalAccess(name=gname, kind="read", line=line, root=gname, member=None)
                )
        elif op == _OP_SETGLOBAL:
            gname = _string_constant(proto, bx)
            if gname is not None:
                accesses.append(
                    GlobalAccess(
                        name=gname,
                        kind="write",
                        line=_line_at(proto, pc),
                        root=gname,
                        member=None,
                    )
                )
        pc += 1
    for child in proto.protos:
        _collect_accesses(child, accesses)


def _syntax_finding(error_text: str, chunk_name: str) -> Finding:
    # [2026-11-11 T-006] With the "@" prefix, Lua reports "<chunk>:<line>: <message>" and
    # prints the chunk name as a file. Only the first ":<digits>:" is the position; anything
    # unparseable still reports at line 1 with Lua's full text rather than being dropped.
    match = _SYNTAX_LINE.search(error_text)
    if match is not None:
        line_no = int(match.group(1))
        message = match.group(2).strip() or error_text
    else:
        line_no = 1
        message = error_text
    return Finding(
        severity="error",
        code="syntax",
        file=chunk_name,
        line=line_no,
        message=message,
        hint=_SYNTAX_HINT,
    )


def _compile_and_dump(
    source: str, chunk_name: str, runtime: Any | None
) -> tuple[bytes | None, Finding | None]:
    # [2026-11-11 T-006] sandbox=False: this runtime only compiles (loadstring) and dumps;
    # the addon chunk is never called, so it needs no WoW-shaped globals and addon code
    # never executes here.
    active = runtime if runtime is not None else luavm.new_runtime(sandbox=False)
    dump_fn = active.execute(_DUMP_CHUNK)
    # [2026-11-11 T-006] A leading "@" makes Lua print the name as a file in its messages,
    # exactly as in luavm; unpack_returned_tuples presents the helper's (hex, err) pair as
    # a Python tuple, with a trailing nil possibly shortened to a single value.
    result = dump_fn(source, "@" + chunk_name)
    hex_text: Any = None
    error_text: Any = None
    if isinstance(result, tuple):
        if len(result) >= 2:
            hex_text, error_text = result[0], result[1]
        elif len(result) == 1:
            hex_text = result[0]
    elif result is not None:
        hex_text = result
    if hex_text is None:
        message = str(error_text) if error_text is not None else "Lua compilation failed"
        return None, _syntax_finding(message, chunk_name)
    # [2026-11-11 T-006] bytes.fromhex is the Python half of the hex bridge: every dump byte
    # was turned into two ASCII hex digits inside Lua, so nothing at or above 0x80 ever had
    # to survive lupa's UTF-8 string decoding.
    return bytes.fromhex(str(hex_text)), None


def check_lua_syntax(source: str, chunk_name: str, *, runtime: Any | None = None) -> Finding | None:
    """Compile ``source`` as Lua 5.1 without running it, as a ``Finding``.

    Why this exists:
        Callers that only gate on "does the client accept this file?" get the shared
        finding shape directly, instead of translating a raw Lua message themselves.

    Args:
        source: The Lua source text.
        chunk_name: The file name to report against (for example ``Core/Codec.lua``).
        runtime: A runtime from ``luavm.new_runtime`` (sandboxed or unsandboxed), or
            ``None`` to make a new runtime. A supplied runtime is only asked to compile,
            never to run ``source``.

    Returns:
        ``None`` when the source compiles, otherwise a ``syntax`` error finding carrying
        Lua's line and message.

    Failure modes:
        Raises ``luavm.LuaVMUnavailableError`` when no runtime is supplied and the embedded
        Lua 5.1 VM cannot be created; a source that merely fails to compile is a finding,
        never an exception.
    """
    # [2026-11-11 T-006] Delegate to luavm.check_syntax so syntax-only checks work on a
    # sandboxed runtime too without paying for string.dump + hex conversion.
    active = runtime if runtime is not None else luavm.new_runtime()
    error_text = luavm.check_syntax(active, source, chunk_name)
    return None if error_text is None else _syntax_finding(error_text, chunk_name)


def analyze_lua(source: str, chunk_name: str, *, runtime: Any | None = None) -> LuaFileAnalysis:
    """Compile ``source`` as Lua 5.1 and collect its global accesses from the bytecode.

    Why this exists:
        Unknown-API, forbidden-global and saved-variable checks all judge the same facts —
        which globals a file reads, writes and indexes into — so those facts are decoded
        once, from the compiled chunk the client would run, instead of guessed from text.

    Args:
        source: The Lua source text.
        chunk_name: The file name to report against (for example ``Core/Codec.lua``).
        runtime: A runtime from ``luavm.new_runtime``, or ``None`` to make an unsandboxed
            host-side one. A supplied runtime is only asked to compile, never to run
            ``source``.

    Returns:
        A ``LuaFileAnalysis`` whose ``syntax_error`` is set (and ``accesses`` empty) when
        Lua 5.1 rejects the source; otherwise every global read, write and member access
        in the root function and all nested functions, in pre-order. A
        ``Table.member`` fetch is one ``"member"`` access, except when the fetch only
        initialises a new local (``local CI = C_Item``), which stays a bare ``"read"``.

    Failure modes:
        Raises ``luavm.LuaVMUnavailableError`` when no runtime is supplied and the embedded
        Lua 5.1 VM cannot be created, and ``ValueError`` if the VM's own dump cannot be
        parsed back (a bug or version skew, never a property of the addon source). A
        source that fails to compile is reported in the result, never raised.
    """
    bytecode, finding = _compile_and_dump(source, chunk_name, runtime)
    if finding is not None or bytecode is None:
        return LuaFileAnalysis(file=chunk_name, syntax_error=finding, accesses=())
    proto = _parse_bytecode(bytecode)
    accesses: list[GlobalAccess] = []
    _collect_accesses(proto, accesses)
    return LuaFileAnalysis(file=chunk_name, syntax_error=None, accesses=tuple(accesses))


# [2026-11-11 T-008] Public aliases and entry points so wow_check (check.py) can inspect
# per-Proto guard scopes, literal RegisterEvent/CreateFrame calls, and efficiency lints
# from the exact compiled Lua 5.1 bytecode tree without duplicating undump logic.
Constant = _Constant
LocVar = _LocVar
Proto = _Proto


def collect_proto_accesses(proto: Proto, *, recursive: bool = True) -> tuple[GlobalAccess, ...]:
    """Collect global accesses in ``proto`` (and optionally its nested child ``protos``).

    Why this exists:
        Guard checks in ``wow_check`` ask what one enclosing function references before
        deciding whether a restricted call inside it is guarded; non-recursive collection
        answers per-function without mixing sibling closures together.

    Args:
        proto: A compiled function block from ``compile_proto``.
        recursive: When true, include nested child functions in pre-order; when false,
            collect only ``proto``'s own instructions.

    Returns:
        The ``GlobalAccess`` items found.

    Failure modes:
        None.
    """
    if recursive:
        items: list[GlobalAccess] = []
        _collect_accesses(proto, items)
        return tuple(items)
    shallow = _Proto(
        source=proto.source,
        linedefined=proto.linedefined,
        lastlinedefined=proto.lastlinedefined,
        nups=proto.nups,
        numparams=proto.numparams,
        is_vararg=proto.is_vararg,
        maxstacksize=proto.maxstacksize,
        code=proto.code,
        constants=proto.constants,
        protos=(),
        lineinfo=proto.lineinfo,
        locvars=proto.locvars,
        upvalues=proto.upvalues,
    )
    items = []
    _collect_accesses(shallow, items)
    return tuple(items)


def compile_proto(
    source: str, chunk_name: str, *, runtime: Any | None = None
) -> tuple[Proto | None, Finding | None]:
    """Compile ``source`` as Lua 5.1 and return ``(root_proto, syntax_finding)``.

    Why this exists:
        ``wow_check`` runs syntax, global-access, event-registration, and efficiency
        analysis over the same compiled chunk; exposing the parsed ``Proto`` avoids
        compiling and dumping each file twice.

    Args:
        source: Lua 5.1 source text.
        chunk_name: Relative file path reported in findings.
        runtime: Optional unsandboxed ``luavm.new_runtime(sandbox=False)``.

    Returns:
        ``(proto, None)`` when compilation succeeds, or ``(None, Finding)`` with
        ``code="syntax"`` when Lua 5.1 rejects ``source``.

    Failure modes:
        Raises ``luavm.LuaVMUnavailableError`` if no Lua 5.1 VM can be created.
    """
    bytecode, finding = _compile_and_dump(source, chunk_name, runtime)
    if finding is not None or bytecode is None:
        return None, finding
    return _parse_bytecode(bytecode), None
