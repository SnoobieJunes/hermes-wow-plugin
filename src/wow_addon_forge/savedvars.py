"""Parse WoW SavedVariables files safely (created 2026-11-11).

Purpose: read an addon's SavedVariables ``.lua`` as JSON-shaped data, optionally select
one dotted path, and extract ``ForgeProbeDB`` (``errors[]`` and ``probe{}``) as written
by ``addons/ForgeProbe/Core.lua``. Shared by ``wow_errors`` (T-009) / ``wow_savedvars`` (T-010).

Invariants owned by this file:
- SavedVariables text runs in a Lua 5.1 VM inside a 100% empty function environment, so
  data literals land in that table while any function call fails instead of executing.
- All filesystem access goes through the ``env.FileSystem`` seam (tests inject a fake).
- Account folder names are personal data (``env.py``): when ``account`` is omitted no
  error message or returned metadata ever contains a raw account name.
- Every foreseeable failure is a ``SavedVarsReadError`` (stable ``code`` + ``hint``);
  no lupa error type leaks to callers.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from wow_addon_forge import env, luavm
from wow_addon_forge.env import FileSystem

_ADDON_NAME_RE = re.compile(r"^[A-Za-z0-9_!-]+$")
_BAD_SAVEDVARS_HINT = (
    "Ensure the SavedVariables file was written cleanly by the WoW client (/reload or logout)."
)
_NO_SAVEDVARS_HINT = (
    "Log in with the addon enabled and run /reload or log out so the client writes SavedVariables."
)

# [2026-11-11 T-009] Compile and call stay in one Lua helper (mirroring luavm.run_chunk_value)
# so either failure phase returns as values Python can classify, always exactly three of them.
# setfenv with a fresh empty table is the whole safety story: no globals or functions exist.
_PARSE_CHUNK = """
return function(source, chunk_name)
    local compiled, message = loadstring(source, chunk_name)
    if not compiled then return "compile", tostring(message), nil end
    local env = {}
    setfenv(compiled, env)
    local ok, failure = pcall(compiled)
    if not ok then return "runtime", tostring(failure), nil end
    return nil, nil, env
end
"""


class SavedVarsReadError(Exception):
    """A foreseeable SavedVariables failure with a stable code and corrective hint.

    Why this exists: callers report why a read failed and what to do next without parsing
        message text or depending on a lupa/OS error type.
    Args: code (``"bad-argument"`` | ``"no-install"`` | ``"no-savedvars"`` |
        ``"ambiguous-account"`` | ``"bad-savedvars"`` | ``"path-not-found"``), message,
        hint. ``str(exc)`` is the message.
    Returns: an instance with ``code``, ``message``, and ``hint`` attributes.
    Failure modes: none; construction cannot fail.
    """

    def __init__(self, code: str, message: str, hint: str) -> None:
        self.code = code
        self.message = message
        self.hint = hint
        super().__init__(message)


def parse_savedvars_lua(
    text: str, *, chunk_name: str = "SavedVariables.lua", runtime: Any | None = None
) -> dict[str, Any]:
    """Parse SavedVariables Lua text into plain JSON-shaped Python data.

    Why this exists: only a real Lua 5.1 VM parses every shape the client writes (nested
        tables, ``[[...]]`` long strings, negative numbers, booleans), and only an empty
        function environment makes running that source safe.
    Args: text (one leading UTF-8 BOM stripped); chunk_name for Lua messages; runtime
        from ``luavm.new_runtime`` (a fresh sandboxed one is created when ``None``).
    Returns: the globals the file assigned, via ``luavm.lua_to_python``; empty -> ``{}``.
    Failure modes: ``SavedVarsReadError("bad-savedvars")`` on compile/runtime failure
        (any attempted function call included) or ``ValueError`` from ``lua_to_python``;
        ``luavm.LuaVMUnavailableError`` when no runtime was given and none can be created.
    """
    # [2026-11-11 T-009] The client may write a BOM, which Lua 5.1 rejects, so remove one.
    clean = text.removeprefix("\ufeff")
    active = luavm.new_runtime(sandbox=True) if runtime is None else runtime
    # [2026-11-11 T-009] A leading "@" makes Lua print chunk_name as a file, as in run_chunk.
    lua_chunk_name = chunk_name if chunk_name.startswith("@") else "@" + chunk_name
    try:
        runner = active.execute(_PARSE_CHUNK)
        phase, message, env_value = runner(clean, lua_chunk_name)
    except Exception as exc:
        raise SavedVarsReadError(
            "bad-savedvars", f"{chunk_name} could not be executed: {exc}", _BAD_SAVEDVARS_HINT
        ) from exc
    if phase is not None:
        raise SavedVarsReadError(
            "bad-savedvars",
            f"{chunk_name} failed to parse ({phase}): {message}",
            _BAD_SAVEDVARS_HINT,
        )
    try:
        # [2026-11-11 T-009] A plain dict only arrives from a host-side stand-in runtime;
        # real Lua tables always go through luavm.lua_to_python.
        converted: Any = (
            dict(env_value) if type(env_value) is dict else luavm.lua_to_python(env_value)
        )
    except ValueError as exc:
        raise SavedVarsReadError(
            "bad-savedvars", f"{chunk_name} could not be converted: {exc}", _BAD_SAVEDVARS_HINT
        ) from exc
    # [2026-11-11 T-009] lua_to_python maps an empty Lua table to []; top-level globals are {}.
    if converted == []:
        return {}
    if not isinstance(converted, dict):
        raise SavedVarsReadError(
            "bad-savedvars",
            f"{chunk_name} did not produce a table of globals.",
            _BAD_SAVEDVARS_HINT,
        )
    return {str(key): value for key, value in converted.items()}


def select_dotted_path(data: Any, dotted_path: str | None) -> Any:
    """Select one value from converted SavedVariables data by dotted path.

    Why this exists: ``wow_savedvars`` reads SavedVariables as JSON (SPEC-PLUGIN §3), so
        callers name a subpath instead of receiving a whole file to find one key.
    Args: data as from ``parse_savedvars_lua``; dotted_path of dot-separated segments
        (string key on a mapping, 0-based index on a list), or ``None``/``""`` for all.
    Returns: the selected value, or ``data`` unchanged when no path was given.
    Failure modes: ``SavedVarsReadError("path-not-found")`` at the first unmatched segment.
    """
    if dotted_path is None or dotted_path == "":
        return data
    current: Any = data
    for segment in dotted_path.split("."):
        if isinstance(current, Mapping) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit() and int(segment) < len(current):
            # [2026-11-11 T-009] 0-based JSON index, not Lua 1-based: lua_to_python already
            # re-indexed arrays from 0, so the path must match the JSON the caller sees.
            # isdigit() excludes negatives, so only the upper bound needs checking.
            current = current[int(segment)]
        else:
            raise SavedVarsReadError(
                "path-not-found",
                f"Path {dotted_path!r} not found at segment {segment!r}.",
                "Inspect the top-level SavedVariables first without path.",
            )
    return current


def _normalise_flavor(flavor: str | None) -> str:
    if flavor is None or not flavor.strip():
        return "_forever_"
    # [2026-11-11 T-009] Callers say "forever"; disk says "_forever_". Wrap only missing sides.
    name = flavor.strip()
    if not name.startswith("_"):
        name = "_" + name
    if not name.endswith("_"):
        name = name + "_"
    return name


def _dir_names(fs: FileSystem, path: str) -> list[str]:
    try:
        names = sorted(fs.list_dir(path))
    except OSError:
        return []
    return [name for name in names if fs.is_dir(fs.join(path, name))]


def _find_dir_name(fs: FileSystem, parent: str, wanted: str) -> str:
    # [2026-11-11 T-009] Disk casing need not match a caller's spelling: exact dir wins,
    # else the first case-insensitive match, else the caller's name (is_file will say no).
    if fs.is_dir(fs.join(parent, wanted)):
        return wanted
    for name in _dir_names(fs, parent):
        if name.lower() == wanted.lower():
            return name
    return wanted


def _realm_char_path(fs: FileSystem, account_dir: str, realm: str, char: str, file: str) -> str:
    realm_dir = fs.join(account_dir, _find_dir_name(fs, account_dir, realm))
    char_name = _find_dir_name(fs, realm_dir, char)
    return fs.join(realm_dir, char_name, "SavedVariables", file)


def _character_paths(fs: FileSystem, account_dir: str, character: str, file: str) -> list[str]:
    if "/" in character:
        # [2026-11-11 T-009] "Realm/Char" is the on-disk order: <account>/<realm>/<char>/.
        realm, char = (part.strip() for part in character.split("/", 1))
        return [_realm_char_path(fs, account_dir, realm, char, file)]
    if "-" in character:
        # [2026-11-11 T-009] "Char-Realm": character names hold no hyphen, so split on the
        # first one and leave any hyphens inside the realm name intact.
        char, realm = (part.strip() for part in character.split("-", 1))
        return [_realm_char_path(fs, account_dir, realm, char, file)]
    paths: list[str] = []
    for realm in _dir_names(fs, account_dir):
        # [2026-11-11 T-009] Account-wide SavedVariables sits beside the realm folders but
        # is not a realm; scanning it as one would invent bogus characters.
        if realm.lower() == "savedvariables":
            continue
        realm_dir = fs.join(account_dir, realm)
        for char in _dir_names(fs, realm_dir):
            if char.lower() == character.lower():
                paths.append(fs.join(realm_dir, char, "SavedVariables", file))
    return paths


def locate_savedvars_file(
    fs: FileSystem,
    *,
    addon: str,
    roots: Sequence[str] | None = None,
    flavor: str | None = None,
    account: str | None = None,
    character: str | None = None,
) -> tuple[str, str]:
    """Locate one addon's SavedVariables file inside a WoW install.

    Why this exists: the ``<root>/<flavor>/WTF/Account/<account>/...`` layout and the rule
        that an omitted ``account`` never leaks account names are shared by every reader.
    Args: fs seam; addon (``^[A-Za-z0-9_!-]+$``); roots (default ``env.DEFAULT_ROOTS``);
        flavor (default ``"_forever_"``, ``"forever"`` wraps to it); account (case-insensitive
        folder match; omitted = scan all accounts, exactly one may hold the file);
        character (``None``/``""`` = account-wide, else ``"Realm/Char"`` | ``"Char-Realm"``
        | bare ``"Char"`` searched across realm folders).
    Returns: ``(resolved_file_path, flavor_folder)``.
    Failure modes: ``SavedVarsReadError`` — ``"bad-argument"``, ``"no-install"`` (no root
        holds ``<flavor>/WTF/Account``), ``"no-savedvars"``, ``"ambiguous-account"``.
    """
    if not addon or not _ADDON_NAME_RE.match(addon):
        raise SavedVarsReadError(
            "bad-argument",
            f"Invalid addon name {addon!r}.",
            "Pass an addon folder name using letters, digits, '_', '!' or '-' only.",
        )
    if account and ("/" in account or "\\" in account or ".." in account):
        raise SavedVarsReadError(
            "bad-argument",
            f"Invalid account name {account!r}.",
            "Pass a plain account folder name without path separators.",
        )
    account_clean = account.strip() if account else ""
    character_clean = character.strip() if character else ""
    if character_clean:
        # [2026-11-11 T-009] One "/" is legal here only as the "Realm/Char" separator, not
        # traversal; backslashes, "..", empty sides, and extra slashes stay refused.
        sides = (
            character_clean.split("/") if "/" in character_clean else (character_clean.split("-"))
        )
        bad = "\\" in character_clean or ".." in character_clean or character_clean.count("/") > 1
        if bad or any(not side.strip() for side in sides):
            raise SavedVarsReadError(
                "bad-argument",
                f"Invalid character name {character!r}.",
                "Pass 'Char', 'Realm/Char' or 'Char-Realm' without path traversal.",
            )
    flavor_folder = _normalise_flavor(flavor)
    addon_file = f"{addon}.lua"
    found_install = False
    matches: list[str] = []
    for root in env.DEFAULT_ROOTS if roots is None else roots:
        account_root = fs.join(root, flavor_folder, "WTF", "Account")
        if not fs.is_dir(account_root):
            continue
        found_install = True
        for account_name in _dir_names(fs, account_root):
            if account_clean and account_name.lower() != account_clean.lower():
                continue
            account_dir = fs.join(account_root, account_name)
            if character_clean:
                candidates = _character_paths(fs, account_dir, character_clean, addon_file)
            else:
                candidates = [fs.join(account_dir, "SavedVariables", addon_file)]
            matches.extend(p for p in candidates if fs.is_file(p) and p not in matches)
    if not found_install:
        raise SavedVarsReadError(
            "no-install",
            f"No WoW install with flavor {flavor_folder} and a WTF/Account folder was found.",
            "Check the install path and flavor, or log in once so WTF/Account is created.",
        )
    if not matches:
        raise SavedVarsReadError(
            "no-savedvars",
            f"No SavedVariables file found for addon {addon!r} under flavor {flavor_folder}.",
            _NO_SAVEDVARS_HINT,
        )
    if not account_clean and len(matches) > 1:
        # [2026-11-11 T-009] A count, never the folder names: the caller supplied no
        # account, so this file must not be the place that reveals them (env.py invariant).
        raise SavedVarsReadError(
            "ambiguous-account",
            f"Found SavedVariables for {addon!r} in {len(matches)} game accounts; "
            "pass account to choose one.",
            "Pass the account parameter to select which game account to read.",
        )
    return matches[0], flavor_folder


def _read_and_parse(fs: FileSystem, path: str, chunk_name: str) -> dict[str, Any]:
    try:
        text = fs.read_text(path)
    except OSError as exc:
        raise SavedVarsReadError(
            "bad-savedvars", f"{chunk_name} could not be read: {exc}", _BAD_SAVEDVARS_HINT
        ) from exc
    return parse_savedvars_lua(text, chunk_name=chunk_name)


def read_savedvars(
    fs: FileSystem,
    *,
    addon: str,
    roots: Sequence[str] | None = None,
    flavor: str | None = None,
    account: str | None = None,
    character: str | None = None,
    dotted_path: str | None = None,
) -> dict[str, Any]:
    """Read one addon's SavedVariables as JSON-shaped data, or one dotted path of it.

    Why this exists: ``wow_savedvars`` is a thin JSON wrapper over locate + read + parse +
        select; keeping the composition here leaves the tool layer owning no parsing rules.
    Args: as ``locate_savedvars_file``, plus dotted_path into the parsed data.
    Returns: ``{"addon", "flavor", "scope" ("account"|"character"), "data"}``; never an
        account folder name.
    Failure modes: propagates ``SavedVarsReadError`` from locate/parse/select; an
        unreadable located file raises it with code ``"bad-savedvars"``.
    """
    path, flavor_folder = locate_savedvars_file(
        fs, addon=addon, roots=roots, flavor=flavor, account=account, character=character
    )
    variables = _read_and_parse(fs, path, f"{addon}.lua")
    return {
        "addon": addon,
        "flavor": flavor_folder,
        # [2026-11-11 T-009] Whitespace-only character is account-wide, as locate treats it.
        "scope": "character" if character and character.strip() else "account",
        "data": select_dotted_path(variables, dotted_path),
    }


def _as_str(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        return value
    return default if value is None else str(value)


def _as_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def extract_forge_probe(
    variables: Mapping[str, Any], *, addon_filter: str | None = None
) -> dict[str, Any]:
    """Extract normalised ``ForgeProbeDB`` errors and probe from parsed SavedVariables.

    Why this exists: ``wow_errors`` reports what ForgeProbe captured, but the raw table has
        Lua-shaped gaps (empty tables as ``[]``, counts as floats); one normaliser owns the
        ``Core.lua`` shapes ``errors[]`` / ``probe{}`` (fields ``message`` … ``time``).
    Args: variables as from ``parse_savedvars_lua``; addon_filter keeps only errors whose
        ``addon`` matches it case-insensitively (surrounding whitespace ignored).
    Returns: ``{"errors", "error_count", "total_captured" (before filtering), "probe"}``;
        a missing/malformed ``ForgeProbeDB`` yields empty errors and probe ``{}``.
    Failure modes: none; malformed entries are skipped or defaulted, never raised.
    """
    raw_db = variables.get("ForgeProbeDB")
    db: Mapping[str, Any] = raw_db if isinstance(raw_db, Mapping) else {}
    raw_errors = db.get("errors")
    # [2026-11-11 T-009] An empty Lua errors table arrives as [], already the empty list;
    # a mapping only appears for a sparse Lua array, whose values in key order are entries.
    items: list[Any] = []
    if isinstance(raw_errors, list):
        items = raw_errors
    elif isinstance(raw_errors, Mapping):
        items = [raw_errors[key] for key in sorted(raw_errors, key=str)]
    all_errors: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        # [2026-11-11 T-009] Defaults mirror Core.lua: recordError starts count at 1 and
        # inferAddon falls back to "unknown", so unwritten fields read as the addon reports.
        all_errors.append(
            {
                "message": _as_str(item.get("message")),
                "stack": _as_str(item.get("stack")),
                "addon": _as_str(item.get("addon"), "unknown"),
                "count": _as_int(item.get("count"), 1),
                "time": _as_int(item.get("time"), 0),
            }
        )
    wanted = addon_filter.strip().lower() if addon_filter else ""
    if wanted:
        filtered = [e for e in all_errors if str(e["addon"]).lower() == wanted]
    else:
        filtered = all_errors
    raw_probe = db.get("probe")
    probe: dict[str, Any] = {}
    if isinstance(raw_probe, Mapping):
        probe = dict(raw_probe)
        # [2026-11-11 T-009] events/apis/restrictions are keyed tables in Core.lua, so an
        # empty one arriving as [] (or a nil field) means {}, never a list.
        for key in ("events", "apis", "restrictions"):
            if probe.get(key) == [] or (key in probe and probe[key] is None):
                probe[key] = {}
    # [2026-11-11 T-009] raw_probe == [] (empty table) or None (never probed) both mean {}.
    return {
        "errors": filtered,
        "error_count": len(filtered),
        "total_captured": len(all_errors),
        "probe": probe,
    }


def read_forge_probe_errors(
    fs: FileSystem,
    *,
    roots: Sequence[str] | None = None,
    flavor: str | None = None,
    account: str | None = None,
    addon_filter: str | None = None,
) -> dict[str, Any]:
    """Read ForgeProbe's captured errors and latest probe from its SavedVariables.

    Why this exists: ``wow_errors`` (T-009) needs exactly one read — account-wide
        ``ForgeProbe.lua`` for a flavor, parsed safely and normalised.
    Args: fs seam; roots/flavor/account as ``locate_savedvars_file``; addon_filter as
        ``extract_forge_probe``.
    Returns: ``{"flavor", "errors", "error_count", "total_captured", "probe"}``.
    Failure modes: propagates ``SavedVarsReadError`` from locate/parse; an unreadable
        located file raises it with code ``"bad-savedvars"``.
    """
    path, flavor_folder = locate_savedvars_file(
        fs, addon="ForgeProbe", roots=roots, flavor=flavor, account=account
    )
    variables = _read_and_parse(fs, path, "ForgeProbe.lua")
    return {"flavor": flavor_folder, **extract_forge_probe(variables, addon_filter=addon_filter)}
