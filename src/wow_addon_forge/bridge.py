"""Outbox pull and inbox push for the forge bridge (created 2026-11-11).

Purpose: ``wow_bridge`` (T-012, SPEC-PLUGIN §7). The game writes an outbox into
SavedVariables; this module returns records past a cursor and advances that
cursor. The outside writes ``Inbox.lua``, which the addon reads on ``/reload``.

Invariants owned by this file:
- The cursor lives in the plugin data directory, never in the game folder.
- ``push`` writes only ``<AddOns>/<name>/Inbox.lua``, and only when the TOC
  declares ``## X-Forge-Bridge: 1``.
- The replacement ``Inbox.lua`` is compiled as Lua 5.1 before it replaces the
  old file. A compile failure leaves the old file in place.
- An item already in ``Inbox.lua`` is kept unless its id is listed in
  ``inbox_seen`` in SavedVariables (the addon has consumed it).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from wow_addon_forge.env import FileSystem, hermes_home_dir
from wow_addon_forge.headless.savedvars_io import format_saved_variables_lua
from wow_addon_forge.install import InstallError, addon_name, flavor_folder, locate_addons_dir
from wow_addon_forge.luavm import check_syntax, new_runtime
from wow_addon_forge.savedvars import (
    SavedVarsReadError,
    parse_savedvars_lua,
    read_savedvars,
)
from wow_addon_forge.tocfile import parse_toc

_BRIDGE_HEADER = "x-forge-bridge"
_SEEN_KEY = "inbox_seen"
_OUTBOX_KEY = "outbox"


class BridgeError(Exception):
    """A foreseeable bridge failure with a stable code and corrective hint.

    Why this exists: the tool layer maps this to the SPEC-PLUGIN §3 error envelope.
    Args: code, message, hint. ``str(exc)`` is the message.
    Returns: an instance with ``code``, ``message``, and ``hint``.
    Failure modes: none; construction cannot fail.
    """

    def __init__(self, code: str, message: str, hint: str) -> None:
        self.code = code
        self.message = message
        self.hint = hint
        super().__init__(message)


def default_cursor_dir() -> Path:
    """Return the directory pull cursors are stored in.

    Why this exists: the cursor is plugin state, not game state (SPEC-PLUGIN §3
        writes the pull cursor, not a file under ``WTF``).
    Args: none.
    Returns: ``<hermes_home>/cache/wow-addon-forge/bridge-cursors`` via
        ``hermes_home_dir()`` (follows ``hermes_constants.get_hermes_home()`` inside
        Hermes, falling back to ``$HERMES_HOME`` and ``~/.hermes`` standalone).
    Failure modes: none.
    """
    # [2026-11-11 T-060] Honour the active Hermes profile home via hermes_home_dir().
    return hermes_home_dir() / "cache" / "wow-addon-forge" / "bridge-cursors"


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _records(value: Any) -> list[dict[str, Any]]:
    items: list[Any]
    if isinstance(value, list):
        items = value
    elif isinstance(value, Mapping):
        items = [value[key] for key in sorted(value, key=str)]
    else:
        return []
    records: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        record_id = _as_int(item.get("id"))
        if record_id is None:
            continue
        records.append({str(key): item[key] for key in item})
        records[-1]["id"] = record_id
    return records


def _find_key(variables: Mapping[str, Any], key: str) -> Any:
    if key in variables:
        return variables[key]
    for value in variables.values():
        if isinstance(value, Mapping) and key in value:
            return value[key]
    return None


def bridge_declared(fs: FileSystem, addon_dir: str, name: str) -> bool:
    """Return whether the addon's TOC opts into the bridge.

    Why this exists: push is refused without ``## X-Forge-Bridge: 1`` (SPEC-PLUGIN §3).
    Args: fs seam; addon_dir; name, the folder and TOC basename.
    Returns: ``True`` only when that header's value is ``1``.
    Failure modes: a missing or unreadable TOC returns ``False``, not an exception.
    """
    toc_path = fs.join(addon_dir, f"{name}.toc")
    if not fs.is_file(toc_path):
        return False
    try:
        parsed = parse_toc(fs.read_text(toc_path))
    except OSError:
        return False
    for header, value in parsed.headers.items():
        if header.lower() == _BRIDGE_HEADER and value.strip() == "1":
            return True
    return False


def _addons_dir(fs: FileSystem, roots: Sequence[str], flavor: str | None) -> str:
    try:
        folder = flavor_folder(flavor)
    except InstallError as exc:
        raise BridgeError(exc.code, exc.message, exc.hint) from exc
    try:
        return locate_addons_dir(fs, roots, folder)
    except InstallError as exc:
        raise BridgeError(exc.code, exc.message, exc.hint) from exc


def list_bridge_addons(fs: FileSystem, roots: Sequence[str], flavor: str | None) -> list[str]:
    """Return addon folder names under the flavor whose TOC opts into the bridge.

    Why this exists: ``bridge pull`` with no addon name is the cron command, so it
        must find the single opted-in addon instead of guessing among all of them.
    Args: fs seam; roots; flavor (default ``_forever_``).
    Returns: folder names, sorted.
    Failure modes: propagates ``BridgeError`` from a missing or ambiguous install.
    """
    addons_dir = _addons_dir(fs, roots, flavor)
    names = [name for name in fs.list_dir(addons_dir) if fs.is_dir(fs.join(addons_dir, name))]
    return sorted(name for name in names if bridge_declared(fs, fs.join(addons_dir, name), name))


def _resolve_addon(
    fs: FileSystem, roots: Sequence[str], flavor: str | None, addon: str | None
) -> str:
    if addon is not None and addon.strip():
        try:
            return addon_name(addon.strip())
        except InstallError as exc:
            raise BridgeError(exc.code, exc.message, exc.hint) from exc
    found = list_bridge_addons(fs, roots, flavor)
    if len(found) == 1:
        return found[0]
    if not found:
        raise BridgeError(
            "no-bridge",
            "No installed addon declares X-Forge-Bridge: 1.",
            "Pass addon, or add ## X-Forge-Bridge: 1 to the addon's TOC.",
        )
    raise BridgeError(
        "ambiguous-addon",
        f"Found {len(found)} bridge addons; pass addon to choose one.",
        "Pass the addon folder name.",
    )


def _cursor_path(cursor_dir: str | os.PathLike[str], addon: str) -> Path:
    return Path(cursor_dir) / f"{addon}.json"


def read_cursor(cursor_dir: str | os.PathLike[str], addon: str) -> int:
    """Return the last pulled id for ``addon``, or 0 when no cursor file exists.

    Why this exists: a missing cursor is the first pull, not an error.
    Args: cursor_dir; addon folder name (already validated).
    Returns: the stored integer cursor, or 0.
    Failure modes: ``BridgeError("bad-cursor")`` when the file exists but is not
        a JSON object with an integer ``cursor``.
    """
    path = _cursor_path(cursor_dir, addon)
    if not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(
            "bad-cursor",
            f"Cursor file for {addon} could not be read: {exc}",
            "Delete the cursor file to pull from the start, or fix the JSON.",
        ) from exc
    if not isinstance(payload, dict):
        raise BridgeError(
            "bad-cursor",
            f"Cursor file for {addon} is not an object.",
            'The file must be JSON like {"cursor": 0}.',
        )
    cursor = _as_int(payload.get("cursor"))
    if cursor is None:
        raise BridgeError(
            "bad-cursor",
            f"Cursor file for {addon} has no integer cursor.",
            'The file must be JSON like {"cursor": 0}.',
        )
    return cursor


def write_cursor(cursor_dir: str | os.PathLike[str], addon: str, cursor: int) -> None:
    """Store ``cursor`` for ``addon`` under the plugin data directory.

    Why this exists: the next pull must not return records already handed out.
    Args: cursor_dir; addon; cursor, the highest id returned.
    Returns: none.
    Failure modes: ``OSError`` when the directory cannot be created or written.
    """
    path = _cursor_path(cursor_dir, addon)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"cursor": cursor}) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def discord_line(record: Mapping[str, Any]) -> str:
    """Return one Discord-ready line for an outbox record.

    Why this exists: ``bridge pull --format discord`` prints one line per record
        and the cron job delivers that text. Newlines would split one record.
    Args: record with ``kind`` and optional ``text``.
    Returns: ``[kind] text``, with newlines in the text replaced by spaces.
    Failure modes: none; a missing kind becomes ``record`` and a missing text is empty.
    """
    kind = str(record.get("kind") or "record").replace("\n", " ")
    text = str(record.get("text") or "").replace("\n", " ").strip()
    if text:
        return f"[{kind}] {text}"
    return f"[{kind}]"


def pull_outbox(
    fs: FileSystem,
    *,
    roots: Sequence[str],
    cursor_dir: str | os.PathLike[str],
    addon: str | None = None,
    flavor: str | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    """Return outbox records whose id is past the cursor, then advance the cursor.

    Why this exists: SPEC-PLUGIN §7 — pull returns records past the stored cursor.
    Args: fs seam; roots; cursor_dir; optional addon (the single bridge addon when
        omitted); flavor; account when more than one game account holds the file.
    Returns: ``addon``, ``cursor`` (the new cursor), ``records``, ``lines``.
    Failure modes: ``BridgeError`` when the addon cannot be resolved.
        ``SavedVarsReadError`` propagates from the SavedVariables read.
    """
    name = _resolve_addon(fs, roots, flavor, addon)
    saved = read_savedvars(fs, addon=name, roots=roots, flavor=flavor, account=account)
    records = _records(_find_key(saved["data"], _OUTBOX_KEY))
    cursor = read_cursor(cursor_dir, name)
    fresh = [record for record in records if int(record["id"]) > cursor]
    fresh.sort(key=lambda record: int(record["id"]))
    new_cursor = max((int(record["id"]) for record in fresh), default=cursor)
    if fresh:
        write_cursor(cursor_dir, name, new_cursor)
    return {
        "action": "pull",
        "addon": name,
        "cursor": new_cursor,
        "records": fresh,
        "lines": [discord_line(record) for record in fresh],
    }


def _records_ids(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        return list(value.values())
    return []


def _load_inbox(path: Path, global_name: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    parsed = parse_savedvars_lua(text, chunk_name=str(path))
    return _records(parsed.get(global_name))


def push_inbox(
    fs: FileSystem,
    *,
    roots: Sequence[str],
    addon: str,
    records: Sequence[Mapping[str, Any]],
    flavor: str | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    """Rewrite ``Inbox.lua`` with new records plus unconsumed existing items.

    Why this exists: SPEC-PLUGIN §7 — push is the only outside-to-game write, and
        it must not drop items the addon has not ingested yet.
    Args: fs seam; roots; addon folder name; records to append; flavor; account.
    Returns: ``addon``, ``path``, ``kept``, ``added``, ``dropped_consumed``.
    Failure modes: ``BridgeError`` when the TOC does not opt in, the name is
        unsafe, the generated file does not compile, or the existing inbox cannot
        be parsed. The old ``Inbox.lua`` is left in place on a compile failure.
    """
    try:
        name = addon_name(addon)
    except InstallError as exc:
        raise BridgeError(exc.code, exc.message, exc.hint) from exc
    addons_dir = _addons_dir(fs, roots, flavor)
    addon_dir = fs.join(addons_dir, name)
    if not fs.is_dir(addon_dir):
        raise BridgeError(
            "bad-path",
            f"Addon folder is not installed: {name}",
            "Install the addon before pushing to its Inbox.lua.",
        )
    if not bridge_declared(fs, addon_dir, name):
        raise BridgeError(
            "bridge-disabled",
            f"{name} does not declare ## X-Forge-Bridge: 1.",
            "Add that TOC header before pushing. Nothing was written.",
        )
    incoming = _records(list(records))
    inbox_path = Path(fs.join(addon_dir, "Inbox.lua"))
    try:
        existing = _load_inbox(inbox_path, f"{name}_Inbox")
    except SavedVarsReadError as exc:
        raise BridgeError(exc.code, exc.message, exc.hint) from exc
    seen: set[int] = set()
    seen_note = "no inbox_seen; kept every existing inbox item"
    try:
        saved = read_savedvars(fs, addon=name, roots=roots, flavor=flavor, account=account)
    except SavedVarsReadError as exc:
        if exc.code != "no-savedvars":
            raise
        saved = None
        seen_note = "no SavedVariables; kept every existing inbox item"
    if saved is not None:
        raw_seen = _find_key(saved["data"], _SEEN_KEY)
        if raw_seen is not None:
            seen = {
                item
                for item in (_as_int(value) for value in _records_ids(raw_seen))
                if item is not None
            }
            seen_note = "dropped inbox items whose id is in inbox_seen"
    kept = [item for item in existing if int(item["id"]) not in seen]
    dropped = len(existing) - len(kept)
    have = {int(item["id"]) for item in kept}
    added = [item for item in incoming if int(item["id"]) not in have]
    merged = kept + added
    global_name = f"{name}_Inbox"
    text = format_saved_variables_lua({global_name: merged})
    runtime = new_runtime(sandbox=True)
    syntax = check_syntax(runtime, text, "Inbox.lua")
    if syntax is not None:
        raise BridgeError(
            "bad-inbox",
            f"Refusing to replace Inbox.lua: {syntax}",
            "The generated file did not compile as Lua 5.1. The old file is unchanged.",
        )
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = inbox_path.with_suffix(".lua.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, inbox_path)
    return {
        "action": "push",
        "addon": name,
        "path": str(inbox_path),
        "kept": len(kept),
        "added": len(added),
        "dropped_consumed": dropped,
        "note": seen_note,
    }


def bridge_status(
    fs: FileSystem,
    *,
    roots: Sequence[str],
    cursor_dir: str | os.PathLike[str],
    addon: str | None = None,
    flavor: str | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    """Report whether the addon opts in, the cursor, and the outbox size.

    Why this exists: the tool's ``status`` action has to answer without pulling.
    Args: as ``pull_outbox``.
    Returns: ``addon``, ``bridge``, ``cursor``, ``outbox``.
    Failure modes: ``BridgeError`` when the addon cannot be resolved. A missing
        SavedVariables file is reported as ``outbox: 0`` with a note, not an error,
        because status is a read of what is there.
    """
    name = _resolve_addon(fs, roots, flavor, addon)
    addons_dir = _addons_dir(fs, roots, flavor)
    enabled = bridge_declared(fs, fs.join(addons_dir, name), name)
    note = None
    try:
        saved = read_savedvars(fs, addon=name, roots=roots, flavor=flavor, account=account)
        count = len(_records(_find_key(saved["data"], _OUTBOX_KEY)))
    except SavedVarsReadError as exc:
        if exc.code != "no-savedvars":
            raise
        count = 0
        note = exc.message
    result: dict[str, Any] = {
        "action": "status",
        "addon": name,
        "bridge": enabled,
        "cursor": read_cursor(cursor_dir, name),
        "outbox": count,
    }
    if note is not None:
        result["note"] = note
    return result
