"""Six-stage addon verification and Lua test runner for wow-addon-forge (created 2026-11-11).

Invariants owned by this file:
- ``check_addon`` runs every stage of docs/SPEC-PLUGIN.md section 4 even when an earlier
  stage reported errors, so one call returns the whole picture in one findings list.
- Global-access, event, and efficiency verdicts come from compiled Lua 5.1 bytecode
  (``luacheck.compile_proto``), never from source text, so comments and strings cannot
  be mistaken for code and locals cannot be mistaken for globals.
- Headless load runs against the strict ``ApiIndex`` the caller supplied, through the
  injected ``FileSystem`` seam, so a verdict never depends on a real client install.
- ``run_addon_tests`` re-runs each test case in a fresh ``World`` with a sandboxed
  coordinator Lua 5.1 VM, so no test can observe another test's state.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from wow_addon_forge import env, luacheck, luavm, tocfile
from wow_addon_forge.apidocs import ApiIndex
from wow_addon_forge.env import FileSystem, RealFileSystem
from wow_addon_forge.headless.runtime import HeadlessError, SimulatedClient, World
from wow_addon_forge.headless.savedvars_io import SavedVariablesError
from wow_addon_forge.luacheck import FORBIDDEN_LUA_GLOBALS, LUA_51_SAFE_GLOBALS, Proto
from wow_addon_forge.tocfile import Finding

__all__ = ["check_addon", "run_addon_tests"]

# [2026-11-11 T-008] Replacements for removed bare globals the index cannot suggest itself
# (its namespace-candidate logic only fires when a dotted twin exists under the same leaf
# name); these are consulted only when ``index.lookup`` gives no replacement of its own.
_KNOWN_REMOVED_REPLACEMENTS: dict[str, str] = {
    "ReloadUI": "C_UI.Reload",
    "CombatLogGetCurrentEventInfo": (
        "none (combat log payloads are closed to addons in WoW: Forever)"
    ),
    "GetAddOnMetadata": "C_AddOns.GetAddOnMetadata",
    "IsAddOnLoaded": "C_AddOns.IsAddOnLoaded",
    "LoadAddOn": "C_AddOns.LoadAddOn",
    "GetNumAddOns": "C_AddOns.GetNumAddOns",
    "GetAddOnInfo": "C_AddOns.GetAddOnInfo",
}

# [2026-11-11 T-008] Bare WoW globals that are always legal to read: the Lua 5.1 safe set
# plus the client's own string helpers and always-present UI objects. Anything else bare
# must be answered by the API index, by the TOC, or by the addon itself.
_WOW_RUNTIME_GLOBALS: frozenset[str] = LUA_51_SAFE_GLOBALS | frozenset(
    {
        "strfind",
        "strmatch",
        "strsub",
        "strlen",
        "strlower",
        "strupper",
        "strrep",
        "strbyte",
        "strchar",
        "gsub",
        "strtrim",
        "sort",
        "concat",
        "Mixin",
        "CreateFromMixins",
        "issecretvalue",
        "GetTime",
        "GetServerTime",
        "seterrorhandler",
        "geterrorhandler",
        "CreateFrame",
        "UIParent",
        "DEFAULT_CHAT_FRAME",
        "SlashCmdList",
        "hash_SlashCmdList",
        "UISpecialFrames",
        "Enum",
        "Constants",
    }
)

# [2026-11-11 T-008] Tables whose members are library functions or addon data, not C API
# entries: looking ``string.format`` up as an API name would report a false unknown-api.
_BUILTIN_MEMBER_ROOTS: frozenset[str] = frozenset(
    {
        "_G",
        "string",
        "table",
        "math",
        "bit",
        "SlashCmdList",
        "hash_SlashCmdList",
        "UISpecialFrames",
        "UIParent",
        "DEFAULT_CHAT_FRAME",
    }
)

# [2026-11-11 T-008] Touching any of these in a function (or an enclosing one) counts as a
# restriction/secret guard: restricted calls there are downgraded from error to warning.
_GUARD_NAMES: frozenset[str] = frozenset(
    {
        "C_RestrictedActions",
        "C_RestrictedActions.IsAddOnRestrictionActive",
        "C_RestrictedActions.GetAddOnRestrictionState",
        "InCombatLockdown",
        "issecretvalue",
        "pcall",
        "xpcall",
    }
)

# [2026-11-11 T-008] Lua 5.1 opcodes (lopcodes.h) the literal-call scans decode. Instruction
# layout: opcode low 6 bits, A next 8, then C and B in 9 bits each; Bx is B/C as one field.
_OP_LOADK, _OP_GETGLOBAL, _OP_GETTABLE, _OP_SELF = 1, 5, 6, 11
_OP_EQ, _OP_LT, _OP_LE, _OP_CALL, _OP_TAILCALL, _OP_CLOSURE = 23, 24, 25, 28, 29, 36

_CLIENT_NAMES: tuple[str, ...] = ("Alice", "Bob", "Carol", "Dave", "Eve")


def _op(inst: int) -> int:
    return inst & 0x3F


def _a(inst: int) -> int:
    return (inst >> 6) & 0xFF


def _b(inst: int) -> int:
    return (inst >> 23) & 0x1FF


def _c(inst: int) -> int:
    return (inst >> 14) & 0x1FF


def _bx(inst: int) -> int:
    return (inst >> 14) & 0x3FFFF


def _const_str(proto: Proto, index: int) -> str | None:
    if 0 <= index < len(proto.constants):
        constant = proto.constants[index]
        if constant.kind == "string" and isinstance(constant.value, str):
            return constant.value
    return None


def _const_num(proto: Proto, index: int) -> float | None:
    if 0 <= index < len(proto.constants):
        constant = proto.constants[index]
        if constant.kind == "number" and isinstance(constant.value, (int, float)):
            return float(constant.value)
    return None


def _rk_str(proto: Proto, operand: int) -> str | None:
    # [2026-11-11 T-008] An RK operand at or above 0x100 is a constant index, not a register.
    return _const_str(proto, operand & 0xFF) if operand & 0x100 else None


def _line_at(proto: Proto, pc: int) -> int:
    if 0 <= pc < len(proto.lineinfo) and proto.lineinfo[pc] > 0:
        return proto.lineinfo[pc]
    return proto.linedefined if proto.linedefined > 0 else 1


def _walk_protos(proto: Proto) -> Iterator[Proto]:
    yield proto
    for child in proto.protos:
        yield from _walk_protos(child)


def _folder_name(addon_path: str) -> str:
    return addon_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _join_rel(fs: FileSystem, base: str, relative: str) -> str:
    return fs.join(base, *relative.replace("\\", "/").split("/"))


def _is_safe_rel(relative: str) -> bool:
    # [2026-11-11 T-008] TOC file lines are addon-relative by contract; an absolute path or
    # a ".." segment would read outside the addon folder, so such lines are never opened.
    if not relative or relative.startswith("/") or relative.startswith("\\"):
        return False
    return all(part not in ("", "..") for part in relative.split("/"))


def _is_toc_candidate(file_name: str, folder: str) -> bool:
    lowered = file_name.lower()
    if not lowered.endswith(".toc"):
        return False
    stem = lowered[: -len(".toc")]
    base = folder.lower()
    return stem == base or stem.startswith(base + "_") or stem.startswith(base + "-")


def _choose_toc(
    fs: FileSystem, addon_path: str, folder: str, client_interface: int
) -> tuple[str, tocfile.TocFile] | None:
    try:
        entries = fs.list_dir(addon_path)
    except OSError:
        return None
    candidates = sorted(
        name
        for name in entries
        if fs.is_file(fs.join(addon_path, name)) and _is_toc_candidate(name, folder)
    )
    if not candidates:
        return None
    parsed: list[tuple[str, tocfile.TocFile]] = []
    for name in candidates:
        try:
            parsed.append((name, tocfile.parse_toc(fs.read_text(fs.join(addon_path, name)))))
        except OSError:
            continue
    if not parsed:
        return None
    # [2026-11-11 T-008] Same choice as env detection and headless loading: Interface match
    # first, then the base "<Folder>.toc", then the first candidate in sorted order, so the
    # TOC linted here is the TOC the later stages load.
    for name, parsed_toc in parsed:
        if client_interface in parsed_toc.interface:
            return name, parsed_toc
    for name, parsed_toc in parsed:
        if name.lower() == f"{folder}.toc".lower():
            return name, parsed_toc
    return parsed[0]


def _proto_has_guard(proto: Proto) -> bool:
    return any(
        access.name in _GUARD_NAMES or access.root in _GUARD_NAMES
        for access in luacheck.collect_proto_accesses(proto, recursive=False)
    )


def _createframe_names(proto: Proto) -> set[str]:
    # [2026-11-11 T-008] CreateFrame(type, "Name", ...) creates a real global named "Name";
    # collecting those literal names keeps later reads of the frame from reading as typos.
    names: set[str] = set()
    for current in _walk_protos(proto):
        code = current.code
        for pc, inst in enumerate(code):
            if _op(inst) != _OP_GETGLOBAL or _const_str(current, _bx(inst)) != "CreateFrame":
                continue
            target = _a(inst) + 2
            for ahead in range(pc + 1, min(len(code), pc + 8)):
                nxt = code[ahead]
                if _op(nxt) in (_OP_CALL, _OP_TAILCALL):
                    break
                if _op(nxt) == _OP_LOADK and _a(nxt) == target:
                    value = _const_str(current, _bx(nxt))
                    if value:
                        names.add(value)
                    break
    return names


def _literal_register_events(proto: Proto) -> list[tuple[str, int]]:
    events: list[tuple[str, int]] = []
    code = proto.code
    for pc, inst in enumerate(code):
        if _rk_str(proto, _c(inst)) != "RegisterEvent":
            continue
        base = _a(inst)
        if _op(inst) == _OP_SELF:
            if pc + 2 >= len(code):
                continue
            load, call = code[pc + 1], code[pc + 2]
            if _op(load) != _OP_LOADK or _a(load) != base + 2:
                continue
            if _op(call) not in (_OP_CALL, _OP_TAILCALL) or _a(call) != base:
                continue
            name = _const_str(proto, _bx(load))
            if name:
                events.append((name, _line_at(proto, pc)))
        elif _op(inst) == _OP_GETTABLE:
            # [2026-11-11 T-008] Dot spelling frame.RegisterEvent(frame, "EV"): receiver is
            # copied into R(a+1) and the literal into R(a+2) before the call on R(a).
            for ahead in range(pc + 1, min(len(code), pc + 6)):
                nxt = code[ahead]
                if _op(nxt) in (_OP_CALL, _OP_TAILCALL):
                    break
                if _op(nxt) == _OP_LOADK and _a(nxt) == base + 2:
                    name = _const_str(proto, _bx(nxt))
                    after = code[ahead + 1] if ahead + 1 < len(code) else 0
                    if name and _op(after) in (_OP_CALL, _OP_TAILCALL) and _a(after) == base:
                        events.append((name, _line_at(proto, pc)))
                    break
    return events


def _event_entries(index: ApiIndex) -> Mapping[str, Any]:
    entries = index.data.get("entries")
    if not isinstance(entries, Mapping):
        return {}
    events = entries.get("event")
    return events if isinstance(events, Mapping) else {}


def _index_namespaces(index: ApiIndex) -> set[str]:
    namespaces: set[str] = set()
    entries = index.data.get("entries")
    if not isinstance(entries, Mapping):
        return namespaces
    for kind_entries in entries.values():
        if not isinstance(kind_entries, Mapping):
            continue
        for name, entry in kind_entries.items():
            text = str(name)
            root = text.split(".", 1)[0]
            if root.startswith("C_"):
                namespaces.add(root)
            if isinstance(entry, Mapping):
                declared = entry.get("namespace")
                if isinstance(declared, str) and declared.startswith("C_"):
                    namespaces.add(declared)
    return namespaces


def _has_throttle(handler: Proto) -> bool:
    for current in _walk_protos(handler):
        if any(_op(inst) in (_OP_EQ, _OP_LT, _OP_LE) for inst in current.code):
            return True
    return any(
        access.name == "GetTime" or access.root == "GetTime"
        for access in luacheck.collect_proto_accesses(handler, recursive=True)
    )


def _accesses_name(handler: Proto, wanted: str) -> bool:
    return any(
        access.name == wanted or access.root == wanted
        for access in luacheck.collect_proto_accesses(handler, recursive=True)
    )


def check_addon(
    addon_dir: str | os.PathLike[str],
    *,
    index: ApiIndex,
    fs: FileSystem | None = None,
    restriction: str | None = None,
) -> dict[str, Any]:
    """Run the six-stage ``wow_check`` verification pipeline over one addon folder.

    Why this exists:
        One call must answer "will this addon load and behave in the current client?"
        across TOC, syntax, API, event, headless-load, and efficiency rules, with later
        stages still running when earlier ones fail so the caller fixes everything in
        one pass instead of discovering errors one run at a time.

    Args:
        addon_dir: Path of the addon folder, as ``fs`` understands it.
        index: The API index for the client build being checked against.
        fs: Filesystem seam; ``RealFileSystem`` when ``None``.
        restriction: Optional regime name. When set, the headless load runs with
            that regime active so documented secret returns are opaque.

    Returns:
        A dict with ``addon``, ``path``, ``flavor``, ``build``, ``verdict`` (``"pass"``
        when no error-severity finding exists, else ``"fail"``), ``error_count``,
        ``warning_count``, and ``findings`` as ``Finding.to_dict()`` items in stage order.

    Failure modes:
        Raises ``ValueError`` when ``addon_dir`` is not an existing directory (the tool
        handler maps this to ``bad-path``). Addon problems are findings, never raised.
    """
    active_fs: FileSystem = fs if fs is not None else RealFileSystem()
    addon_path = os.fsdecode(addon_dir)
    if not active_fs.is_dir(addon_path):
        raise ValueError(f"Addon path is not an existing directory: {addon_path}")
    folder_name = _folder_name(addon_path)
    build = index.data.get("build")
    client_interface = env.interface_from_version(str(build)) or 16001
    findings: list[Finding] = []

    # [2026-11-11 T-008] Stage 1: TOC lint. Without a TOC there is no file list to run
    # later stages over, so that single case returns early with a missing-toc finding.
    chosen = _choose_toc(active_fs, addon_path, folder_name, client_interface)
    if chosen is None:
        missing = Finding(
            "error",
            "missing-toc",
            f"{folder_name}.toc",
            1,
            f"No TOC named after folder '{folder_name}' was found in {addon_path}.",
            f"Create '{folder_name}.toc' in the addon folder.",
        )
        return {
            "addon": folder_name,
            "path": addon_path,
            "flavor": index.data.get("flavor"),
            "build": build,
            "verdict": "fail",
            "error_count": 1,
            "warning_count": 0,
            "findings": [missing.to_dict()],
        }
    toc_name, toc = chosen
    findings.extend(
        tocfile.lint_toc(
            toc,
            toc_filename=toc_name,
            addon_dir=addon_path,
            fs=active_fs,
            folder_name=folder_name,
            client_interface=client_interface,
        )
    )

    # [2026-11-11 T-008] Stage 2: Lua 5.1 syntax via one shared unsandboxed compile-only
    # runtime; successfully compiled Protos are kept so stages 3, 4, and 6 never recompile.
    compile_rt = luavm.new_runtime(sandbox=False)
    compiled_files: list[tuple[str, Proto]] = []
    for rel_file in toc.files:
        if not rel_file.lower().endswith(".lua") or not _is_safe_rel(rel_file):
            continue
        file_path = _join_rel(active_fs, addon_path, rel_file)
        if not active_fs.is_file(file_path):
            continue
        source = active_fs.read_text(file_path)
        proto, syntax_finding = luacheck.compile_proto(source, rel_file, runtime=compile_rt)
        if syntax_finding is not None:
            findings.append(syntax_finding)
        elif proto is not None:
            compiled_files.append((rel_file, proto))

    # [2026-11-11 T-008] Stages 3-4 preparation: globals the addon itself brings into
    # being (saved variables, the Forge bridge inbox, plain writes, named frames) are
    # legal reads in any file, because load order makes them visible across the addon.
    addon_globals: set[str] = set(toc.all_saved_variables)
    if toc.headers.get("X-Forge-Bridge") == "1":
        addon_globals.add(f"{folder_name}_Inbox")
    for _rel, root_proto in compiled_files:
        for access in luacheck.collect_proto_accesses(root_proto, recursive=True):
            if access.kind == "write":
                addon_globals.add(access.name)
        addon_globals.update(_createframe_names(root_proto))
    allowed_globals: set[str] = set(_WOW_RUNTIME_GLOBALS) | _index_namespaces(index) | addon_globals
    builtin_member_roots: set[str] = set(_BUILTIN_MEMBER_ROOTS) | addon_globals
    event_entries = _event_entries(index)

    def check_proto(rel_file: str, proto: Proto, parent_guarded: bool) -> None:
        # [2026-11-11 T-008] Guard status inherits downward: an outer InCombatLockdown or
        # pcall check protects the closures it creates, matching how the code runs.
        guarded = parent_guarded or _proto_has_guard(proto)
        for access in luacheck.collect_proto_accesses(proto, recursive=False):
            if access.kind == "write":
                continue
            if access.root in FORBIDDEN_LUA_GLOBALS or access.root == "debug":
                findings.append(
                    Finding(
                        "error",
                        "forbidden-global",
                        rel_file,
                        access.line,
                        f"Forbidden global '{access.name}' is not available in the WoW "
                        "addon sandbox.",
                        "Remove filesystem/OS/module/debug calls; use SavedVariables, "
                        "C_Timer, or debugstack.",
                    )
                )
                continue
            if access.kind == "read" and access.name in allowed_globals:
                continue
            if access.kind == "member" and access.root in builtin_member_roots:
                continue
            info = index.lookup(access.name)
            if info["found"]:
                if info.get("deprecated") is True:
                    repl = info.get("replacement")
                    hint = f"Use {repl} instead." if repl else "Remove the deprecated call."
                    findings.append(
                        Finding(
                            "error",
                            "deprecated-api",
                            rel_file,
                            access.line,
                            f"'{access.name}' is deprecated in build {build}."
                            + (f" Replacement: {repl}." if repl else ""),
                            hint,
                        )
                    )
                elif info.get("restricted") is True or (
                    isinstance(info.get("secret"), Mapping)
                    and info["secret"].get("returns") is True
                ):
                    findings.append(
                        Finding(
                            "warning" if guarded else "error",
                            "restricted-api",
                            rel_file,
                            access.line,
                            f"'{access.name}' is restricted or secret-returning in build "
                            f"{build}"
                            + (
                                " (guarded)."
                                if guarded
                                else " and is called without a restriction/secret guard."
                            ),
                            "Guard with C_RestrictedActions.IsAddOnRestrictionActive, "
                            "InCombatLockdown, issecretvalue, or pcall.",
                        )
                    )
            else:
                repl = info.get("replacement") or _KNOWN_REMOVED_REPLACEMENTS.get(access.name)
                if repl:
                    findings.append(
                        Finding(
                            "error",
                            "deprecated-api",
                            rel_file,
                            access.line,
                            f"'{access.name}' was removed from the C API in build {build}; "
                            f"replacement: {repl}.",
                            f"Replace '{access.name}' with {repl}.",
                        )
                    )
                else:
                    nearest = info.get("nearest") or []
                    hint = (
                        f"Did you mean: {', '.join(str(n) for n in nearest[:4])}?"
                        if nearest
                        else "Look up valid API names with wow_api lookup or search."
                    )
                    findings.append(
                        Finding(
                            "error",
                            "unknown-api",
                            rel_file,
                            access.line,
                            f"'{access.name}' does not exist in build {build}.",
                            hint,
                        )
                    )
        for ev_name, line in _literal_register_events(proto):
            ev_entry = event_entries.get(ev_name)
            if not isinstance(ev_entry, Mapping):
                findings.append(
                    Finding(
                        "error",
                        "unknown-event",
                        rel_file,
                        line,
                        f"Event '{ev_name}' does not exist in build {build}.",
                        "Check event names with wow_api events or guard with "
                        "C_EventUtils.IsEventValid.",
                    )
                )
            elif ev_entry.get("restricted") is True:
                findings.append(
                    Finding(
                        "warning" if guarded else "error",
                        "restricted-event",
                        rel_file,
                        line,
                        f"Event '{ev_name}' is restricted in build {build}"
                        + (
                            " (guarded)."
                            if guarded
                            else " and is registered without a restriction guard."
                        ),
                        "Avoid restricted events or guard registration behind "
                        "C_RestrictedActions / pcall.",
                    )
                )
        for child in proto.protos:
            check_proto(rel_file, child, guarded)

    for compiled_rel, compiled_proto in compiled_files:
        check_proto(compiled_rel, compiled_proto, False)

    # [2026-11-11 T-008] Stage 5: headless load, slash smoke, and /reload. This runs even
    # when earlier stages failed: the runtime records per-file errors instead of aborting,
    # exactly like the client's error handler, so one bad file hides nothing downstream.
    headless_client: SimulatedClient | None = None
    try:
        world = World(index, fs=active_fs)
        headless_client = world.client("Player", rank=0)
        if restriction:
            # [2026-11-11 T-034] Default checks stay unrestricted. A caller that
            # names a regime sees secret returns as opaque values.
            headless_client.set_restriction(restriction, True)
        headless_client.load_addon(addon_path, login=True)
        for command in headless_client.registered_slash_commands():
            headless_client.slash(command)
        try:
            headless_client.reload()
        except SavedVariablesError as exc:
            findings.append(
                Finding(
                    "error",
                    "unserialisable-savedvar",
                    toc_name,
                    None,
                    f"SavedVariables failed to serialise on reload: {exc}",
                    "Store only booleans, finite numbers, strings, and non-cyclic "
                    "tables in SavedVariables.",
                )
            )
    except HeadlessError as exc:
        findings.append(
            Finding(
                "error",
                "headless-error",
                toc_name,
                1,
                str(exc),
                "Fix the addon TOC and file list so the headless client can load it.",
            )
        )
    if headless_client is not None:
        position = re.compile(rf"(?:^|@|\s){re.escape(folder_name)}/([^:\s]+):(\d+):")
        for err in list(headless_client.errors):
            # [2026-11-11 T-008] Compile failures were already reported in stage 2 with
            # the exact syntax code; reporting them again here would double-count.
            if err.message.startswith("compile:"):
                continue
            match = position.search(err.message) or position.search(err.stack)
            err_file = match.group(1) if match else toc_name
            err_line = int(match.group(2)) if match else 1
            full_msg = (
                f"{err.message}\nStack:\n{err.stack.strip()}" if err.stack.strip() else err.message
            )
            secretish = "secret-value" in err.message or (
                restriction is not None
                and "attempt to compare" in err.message
                and "table" in err.message
            )
            finding_code = "secret-value" if secretish else "headless-error"
            hint = (
                "Do not use a secret value in arithmetic, comparison or concatenation. "
                "Test it with issecretvalue, or pass it to a widget setter."
                if finding_code == "secret-value"
                else "Fix the runtime Lua error raised during load, login, slash "
                "invocation, or reload."
            )
            findings.append(
                Finding(
                    "error",
                    finding_code,
                    err_file,
                    err_line,
                    full_msg,
                    hint,
                )
            )

    # [2026-11-11 T-008] Stage 6: efficiency lints from the same bytecode. OnUpdate runs
    # every frame, so unthrottled work, frame creation, and addon messages there are the
    # classic raid-night performance bugs; sub-0.1s tickers are the timer spelling of it.
    for rel_file, root_proto in compiled_files:
        for proto in _walk_protos(root_proto):
            code = proto.code
            for pc, inst in enumerate(code):
                if _op(inst) == _OP_SELF and _rk_str(proto, _c(inst)) in (
                    "SetScript",
                    "HookScript",
                ):
                    if pc + 2 >= len(code):
                        continue
                    load, closure = code[pc + 1], code[pc + 2]
                    if _op(load) != _OP_LOADK or _a(load) != _a(inst) + 2:
                        continue
                    if _const_str(proto, _bx(load)) != "OnUpdate":
                        continue
                    if _op(closure) != _OP_CLOSURE or _bx(closure) >= len(proto.protos):
                        continue
                    handler = proto.protos[_bx(closure)]
                    line = _line_at(proto, pc)
                    if not _has_throttle(handler):
                        findings.append(
                            Finding(
                                "warning",
                                "unthrottled-onupdate",
                                rel_file,
                                line,
                                "OnUpdate handler has no elapsed-time comparison or GetTime check.",
                                "Accumulate elapsed seconds and return early until your "
                                "threshold (e.g. 0.1s) is reached, or use C_Timer.",
                            )
                        )
                    if _accesses_name(handler, "CreateFrame"):
                        findings.append(
                            Finding(
                                "warning",
                                "frame-in-handler",
                                rel_file,
                                line,
                                "CreateFrame is called inside an OnUpdate handler.",
                                "Create frames once (or lazily on first open) and reuse "
                                "them instead of allocating frames every tick.",
                            )
                        )
                    if _accesses_name(handler, "C_ChatInfo.SendAddonMessage"):
                        findings.append(
                            Finding(
                                "warning",
                                "unthrottled-addon-message",
                                rel_file,
                                line,
                                "C_ChatInfo.SendAddonMessage is called inside an OnUpdate handler.",
                                "Send addon messages through a token-bucket throttle or "
                                "C_Timer queue, never directly on OnUpdate.",
                            )
                        )
                if (
                    _op(inst) == _OP_GETGLOBAL
                    and _const_str(proto, _bx(inst)) == "C_Timer"
                    and pc + 2 < len(code)
                ):
                    fetch, load = code[pc + 1], code[pc + 2]
                    if _op(fetch) != _OP_GETTABLE or _b(fetch) != _a(inst):
                        continue
                    if _rk_str(proto, _c(fetch)) != "NewTicker":
                        continue
                    if _op(load) != _OP_LOADK or _a(load) != _a(fetch) + 1:
                        continue
                    interval = _const_num(proto, _bx(load))
                    if interval is not None and interval < 0.1:
                        findings.append(
                            Finding(
                                "warning",
                                "fast-ticker",
                                rel_file,
                                _line_at(proto, pc),
                                f"C_Timer.NewTicker interval ({interval}s) is under 0.1s.",
                                "Use a ticker interval of at least 0.1s so the addon "
                                "stays light in raids and cities.",
                            )
                        )

    error_count = sum(1 for finding in findings if finding.severity == "error")
    warning_count = sum(1 for finding in findings if finding.severity == "warning")
    return {
        "addon": folder_name,
        "path": addon_path,
        "flavor": index.data.get("flavor"),
        "build": build,
        "verdict": "pass" if error_count == 0 else "fail",
        "error_count": error_count,
        "warning_count": warning_count,
        "findings": [finding.to_dict() for finding in findings],
    }


# [2026-11-11 T-008] WoW helpers and assertions the coordinator VM offers test files.
# The coordinator is a plain sandboxed VM (not a simulated client), so wipe/strsplit/
# strjoin/bit must be supplied here or test code written against the game would nil out.
_HELPERS_LUA = """
rawset(_G, "wipe", function(t) for k in pairs(t) do t[k] = nil end return t end)
rawset(_G, "strjoin", function(delim, ...)
    local parts = {}
    for i = 1, select("#", ...) do parts[i] = tostring(select(i, ...)) end
    return table.concat(parts, delim)
end)
rawset(_G, "strsplit", function(delim, text, limit)
    local out, pos = {}, 1
    text = tostring(text or "")
    while true do
        if limit and #out >= limit - 1 then out[#out + 1] = text:sub(pos) break end
        local first, last = text:find(delim, pos, true)
        if not first then out[#out + 1] = text:sub(pos) break end
        out[#out + 1] = text:sub(pos, first - 1)
        pos = last + 1
    end
    return unpack(out)
end)
if rawget(_G, "bit") == nil then
    local function norm(x) return math.floor(tonumber(x) or 0) % 4294967296 end
    local function logic(a, b, keep)
        a, b = norm(a), norm(b)
        local result, place = 0, 1
        for _ = 1, 32 do
            local abit, bbit = a % 2, b % 2
            if keep(abit, bbit) then result = result + place end
            a, b = math.floor(a / 2), math.floor(b / 2)
            place = place * 2
        end
        return result
    end
    rawset(_G, "bit", {
        band = function(a, b) return logic(a, b, function(x, y) return x == 1 and y == 1 end) end,
        bor = function(a, b) return logic(a, b, function(x, y) return x == 1 or y == 1 end) end,
        bxor = function(a, b) return logic(a, b, function(x, y) return x ~= y end) end,
        bnot = function(a) return 4294967295 - norm(a) end,
        lshift = function(a, n) return norm(norm(a) * 2 ^ (tonumber(n) or 0)) end,
        rshift = function(a, n) return math.floor(norm(a) / 2 ^ (tonumber(n) or 0)) end,
    })
end
local function fail(kind, msg, detail)
    error((msg and tostring(msg) .. ": " or "") .. kind .. " failed: " .. detail, 3)
end
rawset(_G, "assert_eq", function(actual, expected, msg)
    if actual ~= expected then
        fail("assert_eq", msg, tostring(actual) .. " ~= " .. tostring(expected))
    end
end)
rawset(_G, "assert_true", function(value, msg)
    if not value then fail("assert_true", msg, "got " .. tostring(value)) end
end)
rawset(_G, "assert_false", function(value, msg)
    if value then fail("assert_false", msg, "got " .. tostring(value)) end
end)
rawset(_G, "assert_error", function(fn, msg)
    if pcall(fn) then fail("assert_error", msg, "call did not raise") end
end)
rawset(_G, "ForgeTest", {
    assert_eq = assert_eq, assert_true = assert_true,
    assert_false = assert_false, assert_error = assert_error,
})
"""

# [2026-11-11 T-008] Discovery runs a test file once in a throwaway VM with a recording
# ``test`` global, only to learn case names/order; nothing from that VM is reused, so a
# file that fails at top level is one "<load>" failure and cannot poison other files.
_DISCOVER_LUA = """
return function(source, chunk_name)
    local names = {}
    rawset(_G, "test", function(name, fn) names[#names + 1] = tostring(name) end)
    local stack = ""
    local function handler(err)
        stack = tostring(debugstack and debugstack("", 2) or "")
        return tostring(err)
    end
    local fn, err = loadstring(source, "@" .. chunk_name)
    if not fn then return false, tostring(err), "", names end
    local ok, ret = xpcall(fn, handler)
    if not ok then return false, tostring(ret), stack, names end
    if #names == 0 and type(ret) == "table" then
        local keys = {}
        for key, value in pairs(ret) do
            if type(key) == "string" and type(value) == "function" then
                keys[#keys + 1] = key
            end
        end
        table.sort(keys)
        names = keys
    end
    return true, "", "", names
end
"""

# [2026-11-11 T-008] Coordinator setup: builds ``ctx`` (world/client wrappers over Python
# callbacks) and a runner that re-executes the test file and invokes only case ``idx``.
# The scenario method spelled like the client's run-a-snippet entry point is defined here
# in Lua over ``cbs.run_lua`` so Python source only ever calls ``client.run_lua(...)``.
# Running in this separate VM is what lets a test reload the primary client mid-case:
# the client's VM is rebuilt while the coordinator chunk keeps running untouched, and
# the ``_G`` __index proxy below still forwards bare global reads to that fresh VM.
_COORD_LUA = """
return function(py)
    local cases = {}
    rawset(_G, "test", function(name, fn)
        cases[#cases + 1] = {name = tostring(name), fn = fn}
    end)
    local function make_client(cbs)
        local w = {name = cbs.name, full_name = cbs.full_name}
        w.load_addon = function(self_tbl, p) return cbs.load_addon(p) end
        w.fire = function(self_tbl, ev, ...) return cbs.fire(ev, ...) end
        w.slash = function(self_tbl, txt) return cbs.slash(txt) end
        w.eval = function(self_tbl, src) return cbs.run_lua(src) end
        w.reload = function(self_tbl) return cbs.reload() end
        w.logout = function(self_tbl) return cbs.logout() end
        w.set_restriction = function(self_tbl, reg, act)
            return cbs.set_restriction(reg, act)
        end
        w.set_rank = function(self_tbl, r) return cbs.set_rank(r) end
        w.set_instance = function(self_tbl, opts) return cbs.set_instance(opts) end
        w.set_pvp_kills = function(self_tbl, hk) return cbs.set_pvp_kills(hk) end
        return w
    end
    local world_tbl = {}
    world_tbl.advance = function(self_tbl, sec) return py.world_advance(sec) end
    world_tbl.client = function(self_tbl, name, rank)
        return make_client(py.world_client(name, rank))
    end
    world_tbl.set_group = function(self_tbl, names, raid)
        return py.world_set_group(names, raid)
    end
    world_tbl.set_network = function(self_tbl, opts) return py.world_set_network(opts) end
    world_tbl.disable_event = function(self_tbl, ev) return py.world_disable_event(ev) end
    world_tbl.enable_event = function(self_tbl, ev) return py.world_enable_event(ev) end
    local ctx = {world = world_tbl, clients = {}}
    for i = 1, py.client_count do ctx.clients[i] = make_client(py.client_cbs(i)) end
    ctx.client = ctx.clients[1]
    setmetatable(_G, {__index = function(t, key) return py.raw_get(key) end})
    return function(source, chunk_name, idx)
        local stack = ""
        local function handler(err)
            stack = tostring(debugstack and debugstack("", 2) or "")
            return tostring(err)
        end
        local fn, err = loadstring(source, "@" .. chunk_name)
        if not fn then return false, tostring(err), "" end
        local ok, ret = xpcall(fn, handler)
        if not ok then return false, tostring(ret), stack end
        local case_fn = nil
        if cases[idx] then
            case_fn = cases[idx].fn
        elseif type(ret) == "table" then
            local keys = {}
            for key, value in pairs(ret) do
                if type(key) == "string" and type(value) == "function" then
                    keys[#keys + 1] = key
                end
            end
            table.sort(keys)
            if keys[idx] then case_fn = ret[keys[idx]] end
        end
        if type(case_fn) ~= "function" then
            return false, "test case " .. tostring(idx) .. " not found", ""
        end
        local ok2, err2 = xpcall(function() return case_fn(ctx) end, handler)
        if not ok2 then return false, tostring(err2), stack end
        return true, "", ""
    end
end
"""


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _lua_str_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    try:
        converted = luavm.lua_to_python(value)
    except (TypeError, ValueError):
        return []
    if isinstance(converted, list):
        return [str(item) for item in converted]
    if isinstance(converted, dict):
        return [str(converted[key]) for key in sorted(converted, key=str)]
    return []


def _lua_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    try:
        converted = luavm.lua_to_python(value)
    except (TypeError, ValueError):
        return {}
    if isinstance(converted, dict):
        return {str(key): item for key, item in converted.items()}
    return {}


def _walk_lua_files(fs: FileSystem, root: str) -> list[str]:
    found: list[str] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = fs.list_dir(current)
        except OSError:
            continue
        for name in sorted(entries, reverse=True):
            full = fs.join(current, name)
            if fs.is_dir(full):
                stack.append(full)
            elif fs.is_file(full) and name.lower().endswith(".lua"):
                found.append(full)
    return sorted(found)


def _discover_names(source: str, rel_test: str) -> tuple[list[str], tuple[str, str] | None]:
    # [2026-11-11 T-060] Reject precompiled binary test chunks in Python before VM entry.
    if source.startswith("\x1b"):
        return [], (f"{rel_test}: binary chunks are not allowed", "")
    disc_rt = luavm.new_runtime(sandbox=True)
    disc_rt.execute(_HELPERS_LUA)
    result = disc_rt.execute(_DISCOVER_LUA)(source, rel_test)
    ok, msg, stack, names = False, "", "", None
    if isinstance(result, tuple):
        padded = (*result, None, None, None, None)
        ok, msg, stack, names = (
            bool(padded[0]),
            str(padded[1] or ""),
            str(padded[2] or ""),
            padded[3],
        )
    if not ok:
        return [], (msg or "test file failed to load", stack)
    return _lua_str_list(names), None


def _bridge_value(source_rt: Any, target_rt: Any, value: Any, depth: int = 0) -> Any:
    # [2026-11-11 T-008] lupa forbids passing _LuaTable / _LuaFunction objects directly
    # between two distinct LuaRuntime instances ("cannot mix objects from different Lua
    # runtimes"). Scalars pass as-is, tables rebuild recursively in target_rt (preserving
    # nested functions as well as data!), and Lua functions become forwarding closures.
    if depth > 40 or value is None or isinstance(value, (bool, int, float, str)):
        return None if depth > 40 else value
    if isinstance(value, tuple):
        return tuple(_bridge_value(source_rt, target_rt, item, depth + 1) for item in value)
    from lupa import lua51

    ltype = lua51.lua_type(value)
    if ltype == "table":
        rebuilt = target_rt.table()
        for raw_k, raw_v in value.items():
            bk = _bridge_value(source_rt, target_rt, raw_k, depth + 1)
            bv = _bridge_value(source_rt, target_rt, raw_v, depth + 1)
            if bk is not None and bv is not None:
                rebuilt[bk] = bv
        return rebuilt
    if ltype == "function" or callable(value):

        def _forward(*args: Any) -> Any:
            marshalled = [_bridge_value(target_rt, source_rt, arg, depth + 1) for arg in args]
            return _bridge_value(source_rt, target_rt, value(*marshalled), depth + 1)

        return _forward
    return None


def _client_cbs(coord_rt: Any, client: SimulatedClient, addon_path: str) -> Any:
    table = coord_rt.table()
    table["name"] = client.name
    table["full_name"] = client.full_name
    table["load_addon"] = lambda p=None: client.load_addon(str(p) if p else addon_path)
    table["fire"] = lambda ev, *args: client.fire(
        str(ev), *(_bridge_value(coord_rt, client.runtime, arg) for arg in args)
    )
    table["slash"] = lambda txt="": client.slash(str(txt))
    table["run_lua"] = lambda src="": _bridge_value(
        client.runtime, coord_rt, client.run_lua(str(src))
    )
    table["reload"] = client.reload
    table["logout"] = client.logout

    def set_restriction(regime: Any, active: Any = None) -> None:
        reg: str | int = regime if isinstance(regime, str) else _as_int(regime)
        client.set_restriction(reg, True if active is None else bool(active))

    def set_instance(opts: Any = None) -> None:
        data = _lua_dict(opts)
        client.set_instance(
            in_instance=bool(data.get("in_instance", data.get("inInstance", True))),
            instance_type=str(data.get("instance_type") or data.get("type") or "none"),
            name=str(data.get("name") or ""),
            difficulty_id=_as_int(data.get("difficulty_id")),
            max_players=_as_int(data.get("max_players")),
            instance_id=_as_int(data.get("instance_id")),
        )

    table["set_restriction"] = set_restriction
    table["set_rank"] = lambda r=None: client.set_rank(None if r is None else _as_int(r))
    table["set_instance"] = set_instance
    table["set_pvp_kills"] = lambda hk=0: client.set_pvp_kills(_as_int(hk))
    return table


def _run_one_case(
    *,
    source: str,
    rel_test: str,
    idx: int,
    addon_path: str,
    index: ApiIndex,
    fs: FileSystem,
    clients: int,
) -> tuple[bool, str, str]:
    # [2026-11-11 T-060] Reject precompiled binary test chunks in Python before VM entry.
    if source.startswith("\x1b"):
        return False, f"{rel_test}: binary chunks are not allowed", ""
    world = World(index, fs=fs)
    clients_list: list[SimulatedClient] = []
    for position in range(clients):
        name = _CLIENT_NAMES[position] if position < len(_CLIENT_NAMES) else f"Member{position + 1}"
        created = world.client(name, rank=0 if position == 0 else 2)
        created.load_addon(addon_path, login=True)
        clients_list.append(created)
    primary = clients_list[0]
    # [2026-11-11 T-008] Fresh World plus fresh coordinator per case: isolation comes
    # from construction, not from trying to undo whatever the previous case mutated.
    coord_rt = luavm.new_runtime(sandbox=True)
    coord_rt.execute(_HELPERS_LUA)
    py = coord_rt.table()
    py["client_count"] = len(clients_list)
    py["client_cbs"] = lambda i: _client_cbs(coord_rt, clients_list[_as_int(i, 1) - 1], addon_path)
    py["raw_get"] = lambda key: (
        _bridge_value(primary.runtime, coord_rt, primary.controller.raw_get_global(key))
        if isinstance(key, str)
        else None
    )
    py["world_advance"] = lambda sec=0: world.advance(float(sec))

    def world_client(name: Any, rank: Any = None) -> Any:
        created = world.client(str(name), rank=2 if rank is None else _as_int(rank, 2))
        created.load_addon(addon_path, login=True)
        clients_list.append(created)
        return _client_cbs(coord_rt, created, addon_path)

    def set_network(opts: Any = None) -> None:
        data = _lua_dict(opts)
        world.set_network(
            loss_rate=float(data["loss_rate"]) if data.get("loss_rate") is not None else None,
            duplicate_rate=(
                float(data["duplicate_rate"]) if data.get("duplicate_rate") is not None else None
            ),
            reorder_max_delay=(
                float(data["reorder_max_delay"])
                if data.get("reorder_max_delay") is not None
                else None
            ),
        )

    py["world_client"] = world_client
    py["world_set_group"] = lambda names, raid=None: world.set_group(
        _lua_str_list(names), raid=bool(raid)
    )
    py["world_set_network"] = set_network
    py["world_disable_event"] = lambda ev: world.disable_event(str(ev))
    py["world_enable_event"] = lambda ev: world.enable_event(str(ev))
    runner = coord_rt.execute(_COORD_LUA)(py)
    result = runner(source, rel_test, idx)
    if isinstance(result, tuple):
        padded_result = (*result, None, None, None)
        return bool(padded_result[0]), str(padded_result[1] or ""), str(padded_result[2] or "")
    return bool(result), "", ""


def run_addon_tests(
    addon_dir: str | os.PathLike[str],
    *,
    index: ApiIndex,
    fs: FileSystem | None = None,
    tests: str | Sequence[str] | None = None,
    clients: int = 1,
) -> dict[str, Any]:
    """Run an addon's Lua test files headlessly, one isolated world per test case.

    Why this exists:
        ``wow_test`` proves behaviour, not just loadability: each ``test(name, fn)``
        case (or function in a returned table) runs against freshly loaded simulated
        clients and drives them through ``ctx`` exactly as docs/SPEC-PLUGIN.md
        sections 3 and 6 describe, so multi-client synchronisation is testable
        without a game install.

    Args:
        addon_dir: Path of the addon folder, as ``fs`` understands it.
        index: The API index the simulated clients enforce.
        fs: Filesystem seam; ``RealFileSystem`` when ``None``.
        tests: ``None``/``""`` to discover ``Tests``/``tests`` under the addon, or a
            path (or sequence of paths) relative to the addon folder, each a ``.lua``
            file or a directory walked for ``.lua`` files.
        clients: Number of simulated clients created per case (at least 1).

    Returns:
        A dict with ``addon``, ``path``, ``verdict``, ``total``, ``passed``,
        ``failed``, and ``results``; each result has ``name``, ``file``, and
        ``status``, plus ``message``/``stack`` on failure. A file that fails during
        discovery contributes one failed ``"<load>"`` result.

    Failure modes:
        Raises ``ValueError`` when ``clients`` is below 1, when ``addon_dir`` is not
        an existing directory, or when a named test path does not exist. Test
        failures are results, never raised.
    """
    if clients < 1:
        raise ValueError("clients must be >= 1")
    active_fs: FileSystem = fs if fs is not None else RealFileSystem()
    addon_path = os.fsdecode(addon_dir)
    if not active_fs.is_dir(addon_path):
        raise ValueError(f"Addon path is not an existing directory: {addon_path}")
    folder_name = _folder_name(addon_path)

    test_paths: list[str] = []
    if tests is None or tests == "":
        for subdir in ("Tests", "tests"):
            candidate = active_fs.join(addon_path, subdir)
            if active_fs.is_dir(candidate):
                test_paths = _walk_lua_files(active_fs, candidate)
                break
    else:
        entries = [tests] if isinstance(tests, str) else list(tests)
        for entry in entries:
            resolved = (
                entry if entry.startswith(addon_path) else _join_rel(active_fs, addon_path, entry)
            )
            if active_fs.is_file(resolved):
                if resolved.lower().endswith(".lua"):
                    test_paths.append(resolved)
            elif active_fs.is_dir(resolved):
                test_paths.extend(_walk_lua_files(active_fs, resolved))
            else:
                raise ValueError(f"Test path not found: {entry}")

    results: list[dict[str, Any]] = []
    for test_path in test_paths:
        normalised = test_path.replace("\\", "/")
        base = addon_path.replace("\\", "/").rstrip("/")
        rel_test = (
            normalised[len(base) :].lstrip("/")
            if normalised.startswith(base)
            else normalised.rsplit("/", 1)[-1]
        )
        source = active_fs.read_text(test_path)
        try:
            names, load_error = _discover_names(source, rel_test)
        except Exception as exc:  # noqa: BLE001 - a discovery blow-up is a load failure
            names, load_error = [], (str(exc), "")
        if load_error is not None:
            results.append(
                {
                    "name": "<load>",
                    "file": rel_test,
                    "status": "fail",
                    "message": load_error[0],
                    "stack": load_error[1],
                }
            )
            continue
        for idx, case_name in enumerate(names, start=1):
            try:
                passed_ok, message, stack = _run_one_case(
                    source=source,
                    rel_test=rel_test,
                    idx=idx,
                    addon_path=addon_path,
                    index=index,
                    fs=active_fs,
                    clients=clients,
                )
            except Exception as exc:  # noqa: BLE001 - harness errors fail the case
                passed_ok, message, stack = False, str(exc), ""
            if passed_ok:
                results.append({"name": case_name, "file": rel_test, "status": "pass"})
            else:
                results.append(
                    {
                        "name": case_name,
                        "file": rel_test,
                        "status": "fail",
                        "message": message,
                        "stack": stack,
                    }
                )
    passed = sum(1 for result in results if result["status"] == "pass")
    failed = len(results) - passed
    return {
        "addon": folder_name,
        "path": addon_path,
        "verdict": "pass" if failed == 0 else "fail",
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "results": results,
    }
