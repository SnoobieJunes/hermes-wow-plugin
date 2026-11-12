"""Tests for Lua 5.1 syntax and global-access analysis (created 2026-11-11, T-006)."""

from __future__ import annotations

import struct

import pytest

from wow_addon_forge import luacheck, luavm
from wow_addon_forge.luacheck import (
    FORBIDDEN_LUA_GLOBALS,
    LUA_51_SAFE_GLOBALS,
    GlobalAccess,
    LuaFileAnalysis,
    _collect_accesses,
    _compile_and_dump,
    _parse_bytecode,
    analyze_lua,
    check_lua_syntax,
)
from wow_addon_forge.tocfile import Finding as TocFinding

_CHUNK = "Core/Test.lua"


def _read(name: str, line: int) -> GlobalAccess:
    return GlobalAccess(name=name, kind="read", line=line, root=name, member=None)


def _write(name: str, line: int) -> GlobalAccess:
    return GlobalAccess(name=name, kind="write", line=line, root=name, member=None)


def _member(root: str, member: str, line: int) -> GlobalAccess:
    return GlobalAccess(name=f"{root}.{member}", kind="member", line=line, root=root, member=member)


def test_goto_fails_check_lua_syntax_as_lua_52_only() -> None:
    # [2026-11-11 T-006] `goto`/`::label::` arrived in Lua 5.2; the client's Lua 5.1 reads
    # `goto` as a plain name and then chokes on `done`, so the error points at line 1.
    finding = check_lua_syntax("goto done\n::done::\n", _CHUNK)
    assert finding is not None
    assert finding.code == "syntax"
    assert finding.severity == "error"
    assert finding.file == _CHUNK
    assert finding.line == 1


def test_goto_fails_analyze_lua_with_no_accesses() -> None:
    analysis = analyze_lua("goto done\n::done::\n", _CHUNK)
    assert analysis.ok is False
    assert analysis.file == _CHUNK
    assert analysis.accesses == ()
    assert analysis.reads == ()
    assert analysis.writes == ()
    assert analysis.member_accesses == ()
    assert analysis.syntax_error is not None
    assert analysis.syntax_error.code == "syntax"
    assert analysis.syntax_error.severity == "error"
    assert analysis.syntax_error.file == _CHUNK
    assert analysis.syntax_error.line == 1


def test_integer_division_fails_at_exact_line_three() -> None:
    source = "local a = 7\nlocal b = 2\nlocal x = 7 // 2\n"
    # [2026-11-11 T-006] `//` is Lua 5.3 integer division; Lua 5.1 lexes it as two `/`
    # operators in a row, so compilation fails exactly where it is written (line 3).
    finding = check_lua_syntax(source, _CHUNK)
    assert finding is not None
    assert finding.code == "syntax"
    assert finding.severity == "error"
    assert finding.line == 3
    analysis = analyze_lua(source, _CHUNK)
    assert analysis.ok is False
    assert analysis.accesses == ()
    assert analysis.syntax_error is not None
    assert analysis.syntax_error.code == "syntax"
    assert analysis.syntax_error.line == 3


@pytest.mark.parametrize(
    "source",
    ["local x = 1 << 2\n", "local x = ~1\n", "local x = 1 & 2\n", "::done::\n"],
)
def test_other_post_51_syntax_is_rejected(source: str) -> None:
    finding = check_lua_syntax(source, _CHUNK)
    assert finding is not None
    assert finding.code == "syntax"
    assert finding.line == 1


def test_valid_lua_51_source_has_no_syntax_finding() -> None:
    assert check_lua_syntax("local x = 7 / 2\nreturn x\n", _CHUNK) is None
    analysis = analyze_lua("local x = 7 / 2\nreturn x\n", _CHUNK)
    assert analysis.ok is True
    assert analysis.syntax_error is None
    assert analysis.accesses == ()


def test_global_reads_and_writes_in_preorder_with_exact_lines() -> None:
    source = (
        "MySaved = {}\n"  # line 1
        "function GlobalFn()\n"  # line 2
        "    local inner = function()\n"  # line 3
        "        return NestedGlobal\n"  # line 4
        "    end\n"  # line 5
        "    InnerWrite = inner\n"  # line 6
        "end\n"  # line 7
        "print( UnknownGlobal )\n"  # line 8
        "TopLevel = GlobalFn\n"  # line 9
    )
    analysis = analyze_lua(source, _CHUNK)
    assert analysis.ok is True
    # [2026-11-11 T-006] Pre-order means every root-chunk access is listed before any
    # nested function's, so InnerWrite (line 6, inside GlobalFn) follows TopLevel
    # (line 9, at top level) even though its line number is smaller.
    assert analysis.accesses == (
        _write("MySaved", 1),
        _write("GlobalFn", 2),
        _read("print", 8),
        _read("UnknownGlobal", 8),
        _read("GlobalFn", 9),
        _write("TopLevel", 9),
        _write("InnerWrite", 6),
        _read("NestedGlobal", 4),
    )
    assert analysis.reads == (
        _read("print", 8),
        _read("UnknownGlobal", 8),
        _read("GlobalFn", 9),
        _read("NestedGlobal", 4),
    )
    assert analysis.writes == (
        _write("MySaved", 1),
        _write("GlobalFn", 2),
        _write("TopLevel", 9),
        _write("InnerWrite", 6),
    )
    assert analysis.member_accesses == ()


def test_member_call_reports_table_member_not_bare_root() -> None:
    analysis = analyze_lua("C_Item.GetItemInfo(x)\n", _CHUNK)
    assert analysis.ok is True
    expected = GlobalAccess(
        name="C_Item.GetItemInfo",
        kind="member",
        root="C_Item",
        member="GetItemInfo",
        line=1,
    )
    assert analysis.member_accesses == (expected,)
    assert analysis.accesses == (expected, _read("x", 1))
    # [2026-11-11 T-006] The API is judged as one name, `C_Item.GetItemInfo`; a bare
    # read of `C_Item` here would make every C_* call look like an unknown global.
    assert analysis.reads == (_read("x", 1),)
    assert all(access.name != "C_Item" for access in analysis.accesses)


def test_member_call_assigned_to_new_local_still_reports_member() -> None:
    analysis = analyze_lua("local info = C_Item.GetItemInfo(x)\n", _CHUNK)
    assert analysis.accesses == (_member("C_Item", "GetItemInfo", 1), _read("x", 1))
    assert analysis.member_accesses == (_member("C_Item", "GetItemInfo", 1),)


def test_colon_method_call_reports_member_via_self() -> None:
    analysis = analyze_lua('C_ChatInfo:SendAddonMessage("p", "m")\n', _CHUNK)
    assert analysis.accesses == (_member("C_ChatInfo", "SendAddonMessage", 1),)
    assert analysis.reads == ()


def test_member_fetch_after_closed_local_scope_still_reports_member() -> None:
    # [2026-11-11 T-006] After `do ... end`, z's register is dead; the GETGLOBAL for
    # C_Item lands in a temporary above the active locals, so it still folds with the
    # following GETTABLE instead of being mistaken for initialising a local.
    analysis = analyze_lua("do local z = 1 end\nlocal f = C_Item.GetItemInfo\n", _CHUNK)
    assert analysis.accesses == (_member("C_Item", "GetItemInfo", 2),)
    assert analysis.reads == ()


def test_member_access_line_is_line_of_the_access() -> None:
    analysis = analyze_lua("local info =\n    C_Item.GetItemInfo(x)\n", _CHUNK)
    assert analysis.member_accesses == (_member("C_Item", "GetItemInfo", 2),)
    assert analysis.reads == (_read("x", 2),)


def test_multiple_member_accesses_keep_source_order() -> None:
    source = "C_Item.GetItemInfo(x)\nC_ChatInfo.SendAddonMessage(y)\n"
    analysis = analyze_lua(source, _CHUNK)
    assert analysis.member_accesses == (
        _member("C_Item", "GetItemInfo", 1),
        _member("C_ChatInfo", "SendAddonMessage", 2),
    )
    assert analysis.reads == (_read("x", 1), _read("y", 2))


def test_local_alias_of_global_table_is_bare_read_never_member() -> None:
    analysis = analyze_lua("local CI = C_Item\nCI.GetItemInfo(x)\n", _CHUNK)
    # [2026-11-11 T-006] `local CI = C_Item` fetches the table itself: the later
    # CI.GetItemInfo indexes a *local*, so folding it into C_Item.GetItemInfo would
    # invent an API access the bytecode never makes by that name.
    assert analysis.accesses == (_read("C_Item", 1), _read("x", 2))
    assert analysis.member_accesses == ()
    only = analysis.reads[0]
    assert only.kind == "read"
    assert only.member is None
    assert only.root == "C_Item"


def test_local_alias_of_global_table_at_eof_is_bare_read() -> None:
    analysis = analyze_lua("local CI = C_Item\n", _CHUNK)
    assert analysis.accesses == (_read("C_Item", 1),)
    assert analysis.member_accesses == ()


def test_assigning_global_table_to_existing_local_is_bare_read() -> None:
    source = "local x\nx = C_Item\nlocal y = x.GetItemInfo(1)\n"
    analysis = analyze_lua(source, _CHUNK)
    assert analysis.accesses == (_read("C_Item", 2),)
    assert analysis.member_accesses == ()


def test_bare_global_table_passed_as_argument_is_read() -> None:
    analysis = analyze_lua("print(C_Item)\n", _CHUNK)
    assert analysis.accesses == (_read("print", 1), _read("C_Item", 1))
    assert analysis.member_accesses == ()


def test_comments_and_strings_mentioning_globals_produce_no_accesses() -> None:
    source = (
        "-- C_Fake.Nope() and SecretGlobal = 1\n"
        'local s = "C_Fake.Nope(); SecretGlobal = 1"\n'
        "--[[\nOtherGlobal = 2\nC_Fake.Nope()\n]]\n"
        "local t = 'UnknownGlobal'\n"
    )
    analysis = analyze_lua(source, _CHUNK)
    # [2026-11-11 T-006] Accesses come from compiled bytecode, not source text, so
    # names that only appear inside comments or string literals are constants (or
    # nothing at all) and can never surface as global reads or writes.
    assert analysis.ok is True
    assert analysis.accesses == ()


def test_locals_and_upvalues_are_never_globals() -> None:
    source = (
        "local UnknownGlobal = 1\n"
        "local y = UnknownGlobal\n"
        "UnknownGlobal = y + 1\n"
        "local f = function() return UnknownGlobal end\n"
    )
    analysis = analyze_lua(source, _CHUNK)
    assert analysis.accesses == ()


def test_parameters_and_loop_variables_are_never_globals() -> None:
    source = (
        "local function add(a, b) return a + b end\n"
        "for i = 1, 3 do local v = add(i, i) end\n"
        "for k, v in pairs({}) do local w = k end\n"
    )
    analysis = analyze_lua(source, _CHUNK)
    # Only `pairs` is a global here: parameters, loop variables and the local
    # function itself all live in registers/upvalues, never in GETGLOBAL/SETGLOBAL.
    assert analysis.accesses == (_read("pairs", 3),)


def test_dynamic_indexing_reports_bare_reads_not_member() -> None:
    analysis = analyze_lua("local v = C_Item[key]\n", _CHUNK)
    # [2026-11-11 T-006] With a non-constant key there is no member name at compile
    # time, so both the table and the key are ordinary global reads.
    assert analysis.accesses == (_read("C_Item", 1), _read("key", 1))
    assert analysis.member_accesses == ()


def test_dynamic_indexing_with_local_key_reports_only_table_read() -> None:
    source = 'local key = "GetItemInfo"\nlocal v = C_Item[key]\n'
    analysis = analyze_lua(source, _CHUNK)
    assert analysis.accesses == (_read("C_Item", 2),)
    assert analysis.member_accesses == ()


def test_numeric_indexing_reports_bare_read_not_member() -> None:
    analysis = analyze_lua("local v = GlobalList[1]\n", _CHUNK)
    # [2026-11-11 T-006] The constant key `1` is a number, not a string: a numeric
    # index has no member name, so the access stays a bare read of the table.
    assert analysis.accesses == (_read("GlobalList", 1),)
    assert analysis.member_accesses == ()


def test_constant_string_indexing_reports_member() -> None:
    analysis = analyze_lua('local v = C_Item["GetItemInfo"]\n', _CHUNK)
    assert analysis.accesses == (_member("C_Item", "GetItemInfo", 1),)


def test_empty_string_indexing_reports_bare_read() -> None:
    # [2026-11-11 T-006] An empty member name is not a usable API name, so the
    # empty-string constant does not fold into a member access.
    analysis = analyze_lua('local v = C_Item[""]\n', _CHUNK)
    assert analysis.accesses == (_read("C_Item", 1),)
    assert analysis.member_accesses == ()


def test_member_assignment_reports_bare_table_read() -> None:
    # [2026-11-11 T-006] Only GETTABLE/SELF fetches fold into member accesses; a
    # SETTABLE store (`Table.member = v`) leaves the GETGLOBAL a bare table read.
    analysis = analyze_lua("GlobalTable.member = 1\n", _CHUNK)
    assert analysis.accesses == (_read("GlobalTable", 1),)
    assert analysis.member_accesses == ()
    assert analysis.writes == ()


def test_chained_member_access_reports_only_first_member() -> None:
    analysis = analyze_lua("local name = C_Item.GetItemInfo(x).name\n", _CHUNK)
    assert analysis.accesses == (_member("C_Item", "GetItemInfo", 1), _read("x", 1))


def test_empty_and_comment_only_sources_have_no_accesses() -> None:
    for source in ("", "\n\n", "-- only a comment\n"):
        analysis = analyze_lua(source, _CHUNK)
        assert analysis.ok is True
        assert analysis.accesses == ()


def test_check_lua_syntax_accepts_explicit_runtime() -> None:
    runtime = luavm.new_runtime()
    assert check_lua_syntax("local x = 1\n", _CHUNK, runtime=runtime) is None
    finding = check_lua_syntax("goto done\n::done::\n", _CHUNK, runtime=runtime)
    assert finding is not None
    assert finding.code == "syntax"
    assert finding.line == 1


def test_analyze_lua_accepts_explicit_unsandboxed_runtime() -> None:
    runtime = luavm.new_runtime(sandbox=False)
    analysis = analyze_lua("print(C_Item.GetItemInfo(x))\n", _CHUNK, runtime=runtime)
    assert analysis.ok is True
    assert analysis.accesses == (
        _read("print", 1),
        _member("C_Item", "GetItemInfo", 1),
        _read("x", 1),
    )


def test_luacheck_reexports_tocfile_finding() -> None:
    # [2026-11-11 T-006] One Finding shape across checkers: luacheck re-exports the
    # tocfile class rather than defining a look-alike that could drift apart.
    assert luacheck.Finding is TocFinding


def test_global_access_member_defaults_to_none() -> None:
    access = GlobalAccess(name="MyGlobal", kind="read", line=3, root="MyGlobal")
    assert access.member is None
    assert access.name == access.root


def test_luafileanalysis_split_views_filter_by_kind_in_order() -> None:
    accesses = (
        _read("Alpha", 1),
        _write("Beta", 2),
        _member("C_Item", "GetItemInfo", 3),
        _read("Gamma", 4),
    )
    analysis = LuaFileAnalysis(file=_CHUNK, syntax_error=None, accesses=accesses)
    assert analysis.ok is True
    assert analysis.reads == (_read("Alpha", 1), _read("Gamma", 4))
    assert analysis.writes == (_write("Beta", 2),)
    assert analysis.member_accesses == (_member("C_Item", "GetItemInfo", 3),)


def test_luafileanalysis_ok_is_false_exactly_when_syntax_error_set() -> None:
    error = TocFinding(
        severity="error",
        code="syntax",
        file=_CHUNK,
        line=1,
        message="boom",
        hint="Rewrite using Lua 5.1 syntax.",
    )
    analysis = LuaFileAnalysis(file=_CHUNK, syntax_error=error, accesses=())
    assert analysis.ok is False
    assert analysis.syntax_error is error


def test_safe_and_forbidden_globals_are_disjoint() -> None:
    # [2026-11-11 T-006] A name cannot be both "always fine to read" and "never
    # exposed by the client"; overlap would make later checks contradict themselves.
    assert not (LUA_51_SAFE_GLOBALS & FORBIDDEN_LUA_GLOBALS)


def test_safe_and_forbidden_globals_spot_memberships() -> None:
    assert {"print", "pairs", "tostring", "string", "table", "math"} <= LUA_51_SAFE_GLOBALS
    assert {"io", "os", "require", "dofile", "python"} <= FORBIDDEN_LUA_GLOBALS
    assert "C_Item" not in LUA_51_SAFE_GLOBALS
    assert "C_Item" not in FORBIDDEN_LUA_GLOBALS
    # [2026-11-11 T-006] `os` is deliberately forbidden, not safe: the client exposes
    # date/time/difftime as bare globals instead of the os library.
    assert "os" not in LUA_51_SAFE_GLOBALS
    assert {"date", "time", "difftime"} <= LUA_51_SAFE_GLOBALS


def _dump(source: str) -> bytes:
    bytecode, finding = _compile_and_dump(source, _CHUNK, luavm.new_runtime(sandbox=False))
    assert finding is None
    assert bytecode is not None
    return bytecode


def test_constants_of_every_type_parse_from_real_chunk() -> None:
    source = (
        "local a = UnknownA == nil\n"
        "local b = UnknownB == true\n"
        "local c = UnknownC == false\n"
        "local d = 3.14\n"
        "local e = 42\n"
        'local s = "héllo→wörld"\n'
    )
    proto = _parse_bytecode(_dump(source))
    # [2026-11-11 T-006] Comparison operands are forced to RK form, which is what puts
    # nil/true/false into the constant table at all (plain assignments would use
    # LOADNIL/LOADBOOL instead), so this one chunk carries every constant tag.
    kinds = {constant.kind for constant in proto.constants}
    assert {"nil", "bool", "number", "string"} <= kinds
    assert {c.value for c in proto.constants if c.kind == "bool"} == {True, False}
    assert {c.value for c in proto.constants if c.kind == "number"} == {3.14, 42.0}
    strings = {c.value for c in proto.constants if c.kind == "string"}
    assert "héllo→wörld" in strings
    assert {"UnknownA", "UnknownB", "UnknownC"} <= strings


def test_analyze_source_with_every_constant_type_is_ok() -> None:
    source = (
        "local a = nil\nlocal b = true\nlocal c = false\n"
        "local d = 3.14\nlocal e = 42\n"
        'local s = "héllo→wörld"\n'
        "return s\n"
    )
    analysis = analyze_lua(source, _CHUNK)
    assert analysis.ok is True
    assert analysis.accesses == ()


def _header(endian: str = "<", size_t_size: int = 8) -> bytes:
    endian_byte = 1 if endian == "<" else 0
    return b"\x1bLua" + bytes([0x51, 0, endian_byte, 4, size_t_size, 4, 8, 0])


def _pack_size_t(endian: str, size_t_size: int, value: int) -> bytes:
    fmt = "I" if size_t_size == 4 else "Q"
    return struct.pack(f"{endian}{fmt}", value)


def _lua_string(endian: str, size_t_size: int, text: str) -> bytes:
    raw = text.encode("utf-8") + b"\x00"
    return _pack_size_t(endian, size_t_size, len(raw)) + raw


def _synthetic_chunk(
    endian: str = "<",
    size_t_size: int = 8,
    *,
    source: str | None = "@synthetic.lua",
    linedefined: int = 7,
    code: tuple[int, ...] = (),
    constants: bytes = b"",
    constant_count: int = 0,
    lineinfo: tuple[int, ...] = (),
) -> bytes:
    parts = [_header(endian, size_t_size)]
    if source is None:
        parts.append(_pack_size_t(endian, size_t_size, 0))
    else:
        parts.append(_lua_string(endian, size_t_size, source))
    parts.append(struct.pack(f"{endian}i", linedefined))
    parts.append(struct.pack(f"{endian}i", linedefined + 2))
    parts.append(bytes([0, 0, 2, 2]))
    parts.append(struct.pack(f"{endian}i", len(code)))
    parts.extend(struct.pack(f"{endian}I", word) for word in code)
    parts.append(struct.pack(f"{endian}i", constant_count))
    parts.append(constants)
    parts.append(struct.pack(f"{endian}i", 0))
    parts.append(struct.pack(f"{endian}i", len(lineinfo)))
    parts.extend(struct.pack(f"{endian}i", line) for line in lineinfo)
    parts.append(struct.pack(f"{endian}i", 0))
    parts.append(struct.pack(f"{endian}i", 0))
    return b"".join(parts)


def test_synthetic_chunk_with_every_constant_type_parses() -> None:
    constants = b"".join(
        [
            b"\x00",
            b"\x01\x01",
            b"\x01\x00",
            b"\x03" + struct.pack("<d", 3.14),
            b"\x03" + struct.pack("<d", 42.0),
            b"\x04" + _lua_string("<", 8, "héllo→wörld"),
        ]
    )
    proto = _parse_bytecode(_synthetic_chunk(constants=constants, constant_count=6))
    assert [(c.kind, c.value) for c in proto.constants] == [
        ("nil", None),
        ("bool", True),
        ("bool", False),
        ("number", 3.14),
        ("number", 42.0),
        ("string", "héllo→wörld"),
    ]


@pytest.mark.parametrize("endian,size_t_size", [("<", 4), ("<", 8), (">", 4), (">", 8)])
def test_synthetic_minimal_chunk_parses_in_either_endianness(endian: str, size_t_size: int) -> None:
    # [2026-11-11 T-006] endian=0 in the header means big-endian: every multi-byte
    # field (ints, size_t, instruction words) must be read in the chunk's own order,
    # which the distinctive instruction word below would expose if flipped.
    chunk = _synthetic_chunk(endian, size_t_size, code=(0x01020304,))
    proto = _parse_bytecode(chunk)
    assert proto.source == "@synthetic.lua"
    assert proto.linedefined == 7
    assert proto.lastlinedefined == 9
    assert proto.code == (0x01020304,)
    assert proto.constants == ()
    assert proto.protos == ()


def test_synthetic_chunk_with_absent_source_string_parses() -> None:
    proto = _parse_bytecode(_synthetic_chunk(source=None))
    assert proto.source == ""


def test_collect_accesses_line_fallbacks_from_synthetic_proto() -> None:
    constants = b"\x04" + _lua_string("<", 8, "MyGlobal")
    constants += b"\x04" + _lua_string("<", 8, "OtherGlobal")
    getglobal = 5  # GETGLOBAL A=0 Bx=0
    setglobal = 7 | (1 << 14)  # SETGLOBAL A=0 Bx=1
    proto = _parse_bytecode(
        _synthetic_chunk(
            code=(getglobal, setglobal),
            constants=constants,
            constant_count=2,
            lineinfo=(0, 13),
        )
    )
    accesses: list[GlobalAccess] = []
    _collect_accesses(proto, accesses)
    # [2026-11-11 T-006] A lineinfo entry of 0 is "no line recorded", so the read
    # falls back to the function's own linedefined (7) while the write keeps its
    # recorded line (13).
    assert accesses == [_read("MyGlobal", 7), _write("OtherGlobal", 13)]


def test_collect_accesses_ignores_global_with_missing_constant() -> None:
    getglobal_missing = 5 | (5 << 14)  # GETGLOBAL Bx=5, but no constants exist
    proto = _parse_bytecode(_synthetic_chunk(code=(getglobal_missing,)))
    accesses: list[GlobalAccess] = []
    _collect_accesses(proto, accesses)
    assert accesses == []


@pytest.mark.parametrize("data", [b"", b"\x1bLua", b"\x1bLuaQ\x00\x01\x04\x08\x04\x08"])
def test_parse_bytecode_rejects_short_header(data: bytes) -> None:
    with pytest.raises(ValueError, match="header alone needs 12"):
        _parse_bytecode(data)


def test_parse_bytecode_rejects_bad_magic() -> None:
    data = b"\x1bLub" + _header()[4:] + b"\x00" * 32
    with pytest.raises(ValueError, match="signature"):
        _parse_bytecode(data)


@pytest.mark.parametrize(
    "index,value,fragment",
    [
        (4, 0x52, "version 0x52, expected 0x51"),
        (5, 1, "format 1, expected 0"),
        (6, 2, "endianness byte 2, expected 0 or 1"),
        (7, 8, "int size 8, expected 4"),
        (8, 5, "size_t size 5, expected 4 or 8"),
        (9, 8, "instruction size 8, expected 4"),
        (10, 4, "number size 4, expected 8"),
        (11, 1, "integral flag 1, expected 0"),
    ],
)
def test_parse_bytecode_rejects_bad_header_bytes(index: int, value: int, fragment: str) -> None:
    header = bytearray(_header())
    header[index] = value
    # [2026-11-11 T-006] Extra body bytes keep these cases honest: each failure must
    # come from the header check itself, never from running out of bytes later.
    with pytest.raises(ValueError, match=fragment):
        _parse_bytecode(bytes(header) + b"\x00" * 64)


def test_parse_bytecode_rejects_wrong_version_0x52() -> None:
    # Lua 5.2 dumps must fail loudly at the version byte, not misparse quietly.
    header = bytearray(_header())
    header[4] = 0x52
    with pytest.raises(ValueError, match="0x52"):
        _parse_bytecode(bytes(header) + _synthetic_chunk()[12:])


def test_parse_bytecode_rejects_truncated_body() -> None:
    with pytest.raises(ValueError, match="truncated Lua bytecode"):
        _parse_bytecode(_header())
    chunk = _synthetic_chunk(code=(0x01020304,))
    with pytest.raises(ValueError, match="truncated Lua bytecode"):
        _parse_bytecode(chunk[:-1])


def test_parse_bytecode_rejects_unknown_constant_tag() -> None:
    chunk = _synthetic_chunk(constants=b"\x63", constant_count=1)
    with pytest.raises(ValueError, match="unknown constant type tag 99"):
        _parse_bytecode(chunk)


def test_parse_bytecode_rejects_negative_code_count() -> None:
    parts = [
        _header(),
        _lua_string("<", 8, "@synthetic.lua"),
        struct.pack("<i", 0),
        struct.pack("<i", 0),
        bytes([0, 0, 2, 2]),
        struct.pack("<i", -1),
    ]
    with pytest.raises(ValueError, match="negative code count -1"):
        _parse_bytecode(b"".join(parts))


def test_parse_bytecode_of_real_dump_roundtrips_root_proto() -> None:
    proto = _parse_bytecode(_dump("print(UnknownGlobal)\n"))
    assert proto.constants
    assert any(c.kind == "string" and c.value == "UnknownGlobal" for c in proto.constants)
    accesses: list[GlobalAccess] = []
    _collect_accesses(proto, accesses)
    assert accesses == [_read("print", 1), _read("UnknownGlobal", 1)]


def test_analyze_lua_rejects_binary_chunk_before_unsandboxed_compile() -> None:
    # [2026-11-11 T-060] Static analysis uses sandbox=False to call string.dump on compiled
    # source; it must refuse \x1b-prefixed binary bytecode in Python before loadstring runs.
    analysis = analyze_lua("\x1bLuaQ\x00\x01\x04\x08\x04\x08\x00", _CHUNK)
    assert analysis.ok is False
    assert analysis.syntax_error is not None
    assert analysis.syntax_error.code == "syntax"
    assert "binary chunks are not allowed" in analysis.syntax_error.message
