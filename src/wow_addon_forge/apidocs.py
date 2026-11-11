"""WoW client API index: fetch mirror documentation, index it, and answer lookups from the
cached result (created 2026-11-11).

Invariants owned by this file:
- ``fetch_mirror_bundle`` is the plugin's only network path, and it only fetches
  ``https://raw.githubusercontent.com/`` URLs from the two verified mirrors (Gethe/wow-ui-source
  for the generated documentation, Ketho/BlizzardInterfaceResources for the resource lists).
- Lua files are EXECUTED in the sandboxed Lua 5.1 VM through ``luavm``, never parsed with
  regular expressions: the documentation tables and resource lists are Lua data, and only the
  VM reads Lua data without guessing at the grammar.
- Documentation wins over resource lists: a merged resource entry never overwrites a documented
  entry, so a signature is never replaced by a bare name.
- Every index is plain JSON-serialisable data stamped with ``SCHEMA_VERSION``; anything skipped
  while building is recorded in the index's ``warnings``, never swallowed silently.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import tempfile
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from wow_addon_forge import luavm, tocfile

SCHEMA_VERSION = 1
DEFAULT_FLAVOR = "forever"
MIRROR_BRANCHES: dict[str, str] = {"forever": "forever"}
RESOURCE_FILES: tuple[str, ...] = (
    "LuaEnum.lua",
    "GlobalAPI.lua",
    "Events.lua",
    "FrameXML.lua",
    "WidgetAPI.lua",
    "Templates.lua",
    "Mixins.lua",
)
KINDS: tuple[str, ...] = (
    "function",
    "event",
    "enum",
    "table",
    "template",
    "widget-method",
)

_RAW_PREFIX = "https://raw.githubusercontent.com/"
_SYNC_HINT = (
    'Run wow_api with {"action": "sync"} (command line: '
    "python -m wow_addon_forge api sync --flavor forever)."
)
_NO_VALUE: Any = object()

# [2026-11-11 T-005] The shim captures documentation tables in a local the documentation files
# cannot reach, so a file that (re)defines globals cannot lose or forge earlier tables; the
# returned collector is the only handle, and build_index converts it once at the end.
_SHIM_CHUNK = """
local collector = {}
APIDocumentation = {
    AddDocumentationTable = function(_, t) collector[#collector + 1] = t end,
}
return collector
"""


class ApiIndexError(Exception):
    """Raised for every caller-visible API-index failure, with a stable code and a fix hint.

    Why this exists:
        Tool callers report these failures to a model and a human, so each one carries a
        machine-readable ``code`` and a ``hint`` naming the next step, instead of a raw
        ``OSError`` or ``KeyError`` whose meaning callers would have to guess.

    Args:
        code: Stable failure code, e.g. ``"bad-argument"``, ``"fetch-failed"``,
            ``"no-index"``, ``"stale-index"``.
        message: What went wrong, in one sentence. ``str(exc)`` is exactly this.
        hint: The next step that fixes it, e.g. run a sync.

    Returns:
        Nothing; this is an exception type.

    Failure modes:
        None at construction.
    """

    def __init__(self, code: str, message: str, hint: str) -> None:
        self.code = code
        self.message = message
        self.hint = hint
        super().__init__(message)


class Fetcher(Protocol):
    """The narrow text-fetching surface the mirror sync needs.

    Why this exists:
        One injected seam keeps the only network path testable: tests supply canned mirror
        files and never touch a socket.

    Args:
        None; implementors take their own construction arguments.

    Returns:
        Nothing; this is a protocol.

    Failure modes:
        ``fetch_text`` raises ``ApiIndexError`` for a refused or failed fetch.
    """

    def fetch_text(self, url: str) -> str:
        """Return the text at ``url``, or raise ``ApiIndexError``."""
        ...


def _urlopen_bytes(url: str, timeout: float) -> bytes:  # pragma: no cover - live network
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return bytes(response.read())


class UrlFetcher:
    """Production ``Fetcher`` over HTTPS, restricted to raw GitHub mirror URLs.

    Why this exists:
        The one adapter that touches the network; every URL it will open starts with
        ``https://raw.githubusercontent.com/``, so a bad argument or a poisoned file list can
        never turn the sync into a fetch of an arbitrary address.

    Args:
        timeout: Per-request timeout in seconds.
        opener: ``(url, timeout) -> bytes``; tests inject a fake. The default opens the URL
            with ``urllib.request.urlopen``.

    Returns:
        Nothing; construct then call ``fetch_text``.

    Failure modes:
        ``fetch_text`` raises ``ApiIndexError`` (``"fetch-refused"`` or ``"fetch-failed"``).
    """

    def __init__(
        self,
        timeout: float = 30.0,
        opener: Callable[[str, float], bytes] | None = None,
    ) -> None:
        self._timeout = timeout
        self._opener = opener if opener is not None else _urlopen_bytes

    def fetch_text(self, url: str) -> str:
        """Fetch one mirror file as text.

        Why this exists:
            The refusal rule and the error translation live in exactly one place, so no
            caller can fetch past them.

        Args:
            url: The URL to fetch; only ``https://raw.githubusercontent.com/`` URLs pass.

        Returns:
            The response decoded as UTF-8, with undecodable bytes replaced.

        Failure modes:
            Raises ``ApiIndexError("fetch-refused", ...)`` for any other URL, and
            ``ApiIndexError("fetch-failed", ...)`` when the opener raises ``OSError`` or
            ``ValueError``.
        """
        if not url.startswith(_RAW_PREFIX):
            raise ApiIndexError(
                "fetch-refused",
                f"Refused URL {url}: only {_RAW_PREFIX} URLs are fetched.",
                "Use a raw.githubusercontent.com mirror URL.",
            )
        try:
            payload = self._opener(url, self._timeout)
        except (OSError, ValueError) as exc:
            raise ApiIndexError(
                "fetch-failed",
                f"{url}: {type(exc).__name__}: {exc}",
                "Check the network connection and retry.",
            ) from exc
        return payload.decode("utf-8", errors="replace")


@dataclass
class SourceBundle:
    """The raw mirror texts one index build consumes.

    Why this exists:
        Fetching (network) and indexing (Lua execution) are separate steps with separate
        failures; this bundle is the hand-off, so a build can be re-run or tested on canned
        texts without fetching again.

    Args:
        flavor: Normalised flavor, e.g. ``"forever"``.
        build: Client build string from the mirror's ``version.txt``, e.g. ``"1.60.1.70888"``.
        source: Where the texts came from; ``"mirror"`` for ``fetch_mirror_bundle``.
        documentation: Documentation file name to Lua text, in name order.
        resources: Resource file name to Lua text, in name order.
        warnings: One string per skip during fetching (refused file names); build warnings
            are added to these by ``build_index``.

    Returns:
        Nothing; this is a data holder.

    Failure modes:
        None at construction.
    """

    flavor: str
    build: str
    source: str
    documentation: dict[str, str]
    resources: dict[str, str]
    warnings: list[str] = field(default_factory=list)


def normalise_flavor(flavor: object) -> str:
    """Normalise a flavor argument to a supported flavor name.

    Why this exists:
        Flavor arrives from folders (``_forever_``), tool arguments (``"Forever"``) and
        defaults; one normalisation means every later lookup compares the same spelling.

    Args:
        flavor: ``None``, ``""``, or a flavor name in any case, with optional surrounding
            whitespace and leading/trailing underscores.

    Returns:
        The normalised flavor, a key of ``MIRROR_BRANCHES``; ``"forever"`` for ``None``, an
        empty string, or a string that is empty after stripping.

    Failure modes:
        Raises ``ApiIndexError("bad-argument", ...)`` naming the supported flavors when the
        value is not a string or the normalised name is not supported.
    """
    if flavor is None:
        return DEFAULT_FLAVOR
    supported = ", ".join(sorted(MIRROR_BRANCHES))
    if not isinstance(flavor, str):
        raise ApiIndexError(
            "bad-argument",
            f"Unsupported flavor {flavor!r}; supported flavors: {supported}.",
            f"Use one of: {supported}.",
        )
    normalised = flavor.strip().lower().strip("_")
    if not normalised:
        return DEFAULT_FLAVOR
    if normalised not in MIRROR_BRANCHES:
        raise ApiIndexError(
            "bad-argument",
            f"Unsupported flavor {flavor!r}; supported flavors: {supported}.",
            f"Use one of: {supported}.",
        )
    return normalised


def _fetch_one(pair: tuple[Fetcher, str]) -> str:
    fetcher, url = pair
    return fetcher.fetch_text(url)


def _fetch_many(fetcher: Fetcher, urls: Mapping[str, str], max_workers: int) -> dict[str, str]:
    names = sorted(urls)
    if not names:
        return {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # [2026-11-11 T-005] executor.map preserves submission order and re-raises the first
        # failure it meets, so one failed file aborts the whole bundle (a partial index would
        # silently answer "not in the API" for functions that exist).
        texts = list(executor.map(_fetch_one, [(fetcher, urls[name]) for name in names]))
    return dict(zip(names, texts, strict=True))


def fetch_mirror_bundle(fetcher: Fetcher, flavor: str, *, max_workers: int = 16) -> SourceBundle:
    """Fetch every mirror text needed to build an index for ``flavor``.

    Why this exists:
        The plugin's only network path. It pins the verified layout of the two public
        mirrors, so the branch, the documentation TOC and the resource list are read from
        exactly one place.

    Args:
        fetcher: The ``Fetcher`` to read through (production: ``UrlFetcher``).
        flavor: Flavor name; normalised with ``normalise_flavor``.
        max_workers: Thread pool width for the file fetches.

    Returns:
        A ``SourceBundle`` with ``source="mirror"``, the mirror build string, the
        documentation and resource texts in sorted name order, and one warning per refused
        documentation file name.

    Failure modes:
        Raises ``ApiIndexError("bad-mirror-data", ...)`` when ``version.txt`` is not a dotted
        build of 3 or 4 numeric parts, or when the documentation TOC lists no usable Lua
        file. Any fetch failure propagates as its ``ApiIndexError`` and no partial bundle is
        returned. Raises ``ApiIndexError("bad-argument", ...)`` for an unsupported flavor.
    """
    normalised = normalise_flavor(flavor)
    branch = MIRROR_BRANCHES[normalised]
    warnings: list[str] = []
    build = fetcher.fetch_text(f"{_RAW_PREFIX}Gethe/wow-ui-source/{branch}/version.txt").strip()
    parts = build.split(".")
    if len(parts) not in (3, 4) or not all(part.isdigit() for part in parts):
        raise ApiIndexError(
            "bad-mirror-data",
            f"Mirror version.txt for flavor {normalised} is not a dotted build: {build!r}.",
            "Retry later; if it persists, the mirror layout has changed.",
        )
    doc_dir = (
        f"{_RAW_PREFIX}Gethe/wow-ui-source/{branch}"
        "/Interface/AddOns/Blizzard_APIDocumentationGenerated/"
    )
    toc_text = fetcher.fetch_text(doc_dir + "Blizzard_APIDocumentationGenerated.toc")
    doc_urls: dict[str, str] = {}
    for name in tocfile.parse_toc(toc_text).files:
        if not name.endswith(".lua"):
            continue
        # [2026-11-11 T-005] Documentation files live flat in one directory; a name with a
        # separator or ".." would fetch outside it, so it is refused and recorded rather
        # than followed or silently dropped.
        if "/" in name or "\\" in name or ".." in name:
            warnings.append(f"Refused documentation file name {name!r} in mirror TOC; skipped.")
            continue
        doc_urls[name] = doc_dir + name
    if not doc_urls:
        raise ApiIndexError(
            "bad-mirror-data",
            f"Mirror documentation TOC for flavor {normalised} lists no Lua files.",
            "Retry later; if it persists, the mirror layout has changed.",
        )
    documentation = _fetch_many(fetcher, doc_urls, max_workers)
    resource_urls = {
        name: f"{_RAW_PREFIX}Ketho/BlizzardInterfaceResources/{branch}/Resources/{name}"
        for name in RESOURCE_FILES
    }
    resources = _fetch_many(fetcher, resource_urls, max_workers)
    return SourceBundle(
        flavor=normalised,
        build=build,
        source="mirror",
        documentation=documentation,
        resources=resources,
        warnings=warnings,
    )


def _as_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, bool, int, float))


def _list_of(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _string_list(value: Any, label: str, warnings: list[str]) -> list[str]:
    strings: list[str] = []
    for item in _list_of(value):
        if isinstance(item, str):
            strings.append(item)
        else:
            warnings.append(f"{label}: skipped non-string entry {item!r}.")
    return strings


def _field_dict(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    parsed_field: dict[str, Any] = {
        "name": _as_str(raw.get("Name")),
        "type": _as_str(raw.get("Type")),
        "nilable": bool(raw.get("Nilable")),
    }
    if "Default" in raw:
        parsed_field["default"] = raw["Default"]
    if "InnerType" in raw:
        parsed_field["inner_type"] = raw["InnerType"]
    if "Mixin" in raw:
        parsed_field["mixin"] = raw["Mixin"]
    # [2026-11-11 T-005] Documentation prose is dropped on purpose: the index answers
    # existence/signature/secret questions, and prose would multiply its size without being
    # machine-checkable. Every other scalar survives in flags so a new Blizzard flag is
    # visible the day it appears, not lost until this file learns its name.
    excluded = {"Name", "Type", "Nilable", "Default", "InnerType", "Mixin", "Documentation"}
    flags: dict[str, Any] = {
        str(key): item for key, item in raw.items() if key not in excluded and _is_scalar(item)
    }
    if flags:
        parsed_field["flags"] = flags
    return parsed_field


def _field_dicts(raw: Any, label: str, warnings: list[str]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for item in _list_of(raw):
        parsed_field = _field_dict(item)
        if parsed_field is None:
            warnings.append(f"{label}: skipped non-table field {item!r}.")
        else:
            fields.append(parsed_field)
    return fields


def _flags(raw: dict[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {str(key): item for key, item in raw.items() if key not in excluded}


def _secret(flags: dict[str, Any], secret_fields: list[dict[str, Any]]) -> dict[str, Any]:
    conditions: set[str] = set()
    for key, value in flags.items():
        if not value:
            continue
        if (
            key in {"SecretReturns", "SecretReturnsForAspect", "SecretPayloads"}
            or key.startswith("SecretWhen")
            or key.startswith("SecretIn")
        ):
            conditions.add(key)
    for secret_field in secret_fields:
        field_flags = secret_field.get("flags")
        if not isinstance(field_flags, dict):
            continue
        for flag_name in ("ConditionalSecret", "SecretValue", "ConditionalSecretContents"):
            if field_flags.get(flag_name) is True:
                conditions.add(f"{secret_field['name']}:{flag_name}")
    ordered = sorted(conditions)
    secret_args = flags.get("SecretArguments")
    return {
        "args": secret_args if isinstance(secret_args, str) else None,
        "returns": bool(ordered),
        "conditions": ordered,
    }


def _base_entry(name: str, kind: str, source: str, *, documented: bool) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "restricted": False,
        "secret": {"args": None, "returns": False, "conditions": []},
        "deprecated": False,
        "documented": documented,
        "source": source,
    }


def _namespace_of(name: str) -> str | None:
    if "." not in name:
        return None
    namespace = name.rsplit(".", 1)[0]
    return namespace or None


def _namespace_candidates(names: Iterable[str], bare: str) -> list[str]:
    scored: list[tuple[int, str]] = []
    for name in names:
        if "." not in name or name.rsplit(".", 1)[1] != bare:
            continue
        namespace = name.rsplit(".", 1)[0]
        core = namespace[2:] if namespace.startswith("C_") else namespace
        # [2026-11-11 T-005] A namespace whose C_-stripped name occurs inside the bare name
        # (C_Item inside GetItemInfo) is almost always the intended replacement, so those
        # rank before the merely alphabetical candidates.
        rank = 0 if core and core in bare else 1
        scored.append((rank, name))
    scored.sort()
    return [name for _, name in scored]


def _function_entry(
    raw: dict[str, Any],
    *,
    name: str,
    kind: str,
    system_name: str,
    namespace: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    label = f"documentation {name}"
    args = _field_dicts(raw.get("Arguments"), label, warnings)
    returns = _field_dicts(raw.get("Returns"), label, warnings)
    flags = _flags(raw, {"Name", "Type", "Namespace", "Arguments", "Returns", "Documentation"})
    entry = _base_entry(name, kind, "documentation", documented=True)
    entry["restricted"] = flags.get("HasRestrictions") is True
    entry["secret"] = _secret(flags, returns)
    if kind == "widget-method":
        entry["widget"] = system_name
    else:
        entry["namespace"] = namespace
        entry["system"] = system_name or None
        entry["c_api"] = True
    entry["args"] = args
    entry["returns"] = returns
    entry["flags"] = flags
    return entry


def _add_documented_functions(
    system: dict[str, Any],
    system_name: str,
    entries: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
) -> None:
    label = system_name or "<unnamed>"
    is_widget = system.get("Type") == "ScriptObject"
    if is_widget and not system_name:
        if _list_of(system.get("Functions")):
            warnings.append("Skipped ScriptObject documentation table without a Name.")
        return
    system_namespace = system.get("Namespace")
    for raw in _list_of(system.get("Functions")):
        if not isinstance(raw, dict) or not _as_str(raw.get("Name")):
            warnings.append(f"{label}: skipped function without a name.")
            continue
        func_name = _as_str(raw.get("Name"))
        if is_widget:
            name = f"{system_name}:{func_name}"
            entry = _function_entry(
                raw,
                name=name,
                kind="widget-method",
                system_name=system_name,
                namespace=None,
                warnings=warnings,
            )
            entries["widget-method"][name] = entry
            continue
        # [2026-11-11 T-005] A function's own Namespace overrides the system's, and "" there
        # means a true global living inside a namespaced system; using the system's namespace
        # for it would invent a C_ name the client does not have.
        if "Namespace" in raw:
            own = raw.get("Namespace")
            namespace = own if isinstance(own, str) and own else None
        else:
            namespace = (
                system_namespace if isinstance(system_namespace, str) and system_namespace else None
            )
        name = f"{namespace}.{func_name}" if namespace else func_name
        entries["function"][name] = _function_entry(
            raw,
            name=name,
            kind="function",
            system_name=system_name,
            namespace=namespace,
            warnings=warnings,
        )


def _add_documented_events(
    system: dict[str, Any],
    system_name: str,
    entries: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
) -> None:
    label = system_name or "<unnamed>"
    for raw in _list_of(system.get("Events")):
        if not isinstance(raw, dict) or not _as_str(raw.get("LiteralName")):
            warnings.append(f"{label}: skipped event without a LiteralName.")
            continue
        name = _as_str(raw.get("LiteralName"))
        args = _field_dicts(raw.get("Payload"), f"documentation {name}", warnings)
        flags = _flags(
            raw,
            {"Name", "Type", "LiteralName", "Namespace", "Payload", "Documentation"},
        )
        entry = _base_entry(name, "event", "documentation", documented=True)
        entry["restricted"] = flags.get("HasRestrictions") is True
        entry["secret"] = _secret(flags, args)
        entry["system"] = system_name or None
        entry["args"] = args
        entry["returns"] = []
        entry["flags"] = flags
        entries["event"][name] = entry


def _add_documented_tables(
    system: dict[str, Any],
    system_name: str,
    entries: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
) -> None:
    label = system_name or "<unnamed>"
    for raw in _list_of(system.get("Tables")):
        if not isinstance(raw, dict) or not _as_str(raw.get("Name")):
            warnings.append(f"{label}: skipped table without a name.")
            continue
        table_name = _as_str(raw.get("Name"))
        table_type = _as_str(raw.get("Type"))
        if table_type == "Enumeration":
            values: dict[str, Any] = {}
            for item in _list_of(raw.get("Fields")):
                if isinstance(item, dict) and _as_str(item.get("Name")):
                    values[_as_str(item.get("Name"))] = item.get("EnumValue")
                else:
                    warnings.append(f"Enum.{table_name}: skipped field {item!r}.")
            name = f"Enum.{table_name}"
            entry = _base_entry(name, "enum", "documentation", documented=True)
            entry["values"] = values
            entries["enum"][name] = entry
        elif table_type == "Constants":
            constants: dict[str, Any] = {}
            for item in _list_of(raw.get("Values")):
                if isinstance(item, dict) and _as_str(item.get("Name")):
                    constants[_as_str(item.get("Name"))] = item.get("Value")
                else:
                    warnings.append(f"Constants.{table_name}: skipped value {item!r}.")
            name = f"Constants.{table_name}"
            entry = _base_entry(name, "table", "documentation", documented=True)
            entry["table_type"] = "Constants"
            entry["values"] = constants
            entries["table"][name] = entry
        elif table_type == "Structure":
            entry = _base_entry(table_name, "table", "documentation", documented=True)
            entry["table_type"] = "Structure"
            entry["fields"] = _field_dicts(
                raw.get("Fields"), f"documentation {table_name}", warnings
            )
            entries["table"][table_name] = entry
        else:
            entry = _base_entry(table_name, "table", "documentation", documented=True)
            entry["table_type"] = table_type
            entries["table"][table_name] = entry


def _add_documented_systems(
    systems: Any,
    entries: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
) -> None:
    for system in _list_of(systems):
        # [2026-11-11 T-005] Blizzard's *ConstantsDocumentation.lua files pass tables with
        # `Tables` / `Predicates` and no top-level `Name`. Skipping nameless tables dropped
        # documented Structures and Enums on the floor; only non-dict or empty tables are
        # malformed.
        if not isinstance(system, dict) or not (
            _as_str(system.get("Name"))
            or any(key in system for key in ("Functions", "Events", "Tables", "Predicates"))
        ):
            warnings.append("Skipped malformed documentation table without Name or declarations.")
            continue
        system_name = _as_str(system.get("Name"))
        _add_documented_functions(system, system_name, entries, warnings)
        _add_documented_events(system, system_name, entries, warnings)
        _add_documented_tables(system, system_name, entries, warnings)


def _resource_value(runtime: Any, bundle: SourceBundle, name: str, warnings: list[str]) -> Any:
    text = bundle.resources.get(name)
    if text is None:
        warnings.append(f"{name}: resource is missing; skipped.")
        return _NO_VALUE
    try:
        return luavm.lua_to_python(luavm.run_chunk_value(runtime, text, name))
    except luavm.LuaChunkError as exc:
        warnings.append(f"{name}: {exc.phase}: {exc.message}")
        return _NO_VALUE
    except ValueError as exc:
        warnings.append(f"{name}: {exc}")
        return _NO_VALUE


def _resource_function_entry(name: str, source: str, *, c_api: bool) -> dict[str, Any]:
    entry = _base_entry(name, "function", source, documented=False)
    entry["namespace"] = _namespace_of(name)
    entry["system"] = None
    entry["args"] = []
    entry["returns"] = []
    entry["flags"] = {}
    entry["c_api"] = c_api
    return entry


def _merge_global_api(
    value: Any,
    entries: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
) -> None:
    for array in _list_of(value):
        for name in _string_list(array, "GlobalAPI.lua", warnings):
            if name not in entries["function"]:
                entries["function"][name] = _resource_function_entry(
                    name, "GlobalAPI.lua", c_api=True
                )


def _merge_resource_events(
    value: Any,
    entries: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
) -> None:
    if not isinstance(value, dict):
        warnings.append("Events.lua: expected a table of system to event names; skipped.")
        return
    for system_name in sorted(value, key=str):
        for name in _string_list(value[system_name], "Events.lua", warnings):
            if name in entries["event"]:
                continue
            entry = _base_entry(name, "event", "Events.lua", documented=False)
            entry["system"] = str(system_name)
            entry["args"] = []
            entry["returns"] = []
            entry["flags"] = {}
            entries["event"][name] = entry


def _merge_frame_xml(
    value: Any,
    entries: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
) -> None:
    for array in _list_of(value):
        for name in _string_list(array, "FrameXML.lua", warnings):
            if name in entries["function"]:
                continue
            entry = _resource_function_entry(name, "FrameXML.lua", c_api=False)
            bare = name.rsplit(".", 1)[-1]
            candidates = _namespace_candidates(entries["function"], bare)
            # [2026-11-11 T-005] A FrameXML global whose bare name also lives in a C_
            # namespace is the old spelling of that API, so it is reported deprecated with
            # its replacement instead of looking like an equally good modern name.
            if candidates:
                entry["deprecated"] = True
                entry["replacement"] = candidates[0]
            entries["function"][name] = entry


def _merge_lua_enum_globals(
    enum_global: Any,
    constants_global: Any,
    entries: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
) -> None:
    if isinstance(enum_global, dict):
        for key in sorted(enum_global, key=str):
            name = f"Enum.{key}"
            if name in entries["enum"]:
                continue
            entry = _base_entry(name, "enum", "LuaEnum.lua", documented=False)
            item = enum_global[key]
            entry["values"] = item if isinstance(item, dict) else {}
            if not isinstance(item, dict):
                warnings.append(f"LuaEnum.lua: {name} is not a table of values; values empty.")
            entries["enum"][name] = entry
    elif enum_global is not None:
        warnings.append("LuaEnum.lua: global Enum is not a table; skipped.")
    if isinstance(constants_global, dict):
        for key in sorted(constants_global, key=str):
            name = f"Constants.{key}"
            if name in entries["table"]:
                continue
            entry = _base_entry(name, "table", "LuaEnum.lua", documented=False)
            item = constants_global[key]
            entry["table_type"] = "Constants"
            entry["values"] = item if isinstance(item, dict) else {}
            if not isinstance(item, dict):
                warnings.append(f"LuaEnum.lua: {name} is not a table of values; values empty.")
            entries["table"][name] = entry
    elif constants_global is not None:
        warnings.append("LuaEnum.lua: global Constants is not a table; skipped.")


def _merge_templates(
    value: Any,
    entries: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
) -> None:
    if not isinstance(value, dict):
        warnings.append("Templates.lua: expected a table of template names; skipped.")
        return
    for name in sorted(value, key=str):
        if str(name) in entries["template"]:
            continue
        raw = value[name]
        widget: Any = None
        inherits: Any = None
        if isinstance(raw, dict):
            widget = raw.get("type")
            inherits = raw.get("inherits") or None
        else:
            warnings.append(f"Templates.lua: {name} is not a table; widget unknown.")
        entry = _base_entry(str(name), "template", "Templates.lua", documented=False)
        entry["widget"] = widget if isinstance(widget, str) else None
        entry["inherits"] = inherits
        entries["template"][str(name)] = entry


def _merge_widget_api(
    value: Any,
    entries: dict[str, dict[str, dict[str, Any]]],
    widgets: dict[str, Any],
    warnings: list[str],
) -> None:
    if not isinstance(value, dict):
        warnings.append("WidgetAPI.lua: expected a table of widget types; skipped.")
        return
    for widget_type in sorted(value, key=str):
        raw = value[widget_type]
        inherits: list[str] = []
        methods: list[str] = []
        if isinstance(raw, dict):
            inherits = _string_list(raw.get("inherits"), "WidgetAPI.lua", warnings)
            methods = _string_list(raw.get("methods"), "WidgetAPI.lua", warnings)
        else:
            warnings.append(f"WidgetAPI.lua: {widget_type} is not a table; skipped details.")
        widgets[str(widget_type)] = {"inherits": inherits, "methods": methods}
        for method in methods:
            name = f"{widget_type}:{method}"
            if name in entries["widget-method"]:
                continue
            entry = _base_entry(name, "widget-method", "WidgetAPI.lua", documented=False)
            entry["widget"] = str(widget_type)
            entry["args"] = []
            entry["returns"] = []
            entry["flags"] = {}
            entries["widget-method"][name] = entry


def _merge_mixins(
    value: Any,
    entries: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
) -> None:
    for name in _string_list(value, "Mixins.lua", warnings):
        if name in entries["table"]:
            continue
        entry = _base_entry(name, "table", "Mixins.lua", documented=False)
        entry["table_type"] = "Mixin"
        entries["table"][name] = entry


def _run_lua_enum(runtime: Any, bundle: SourceBundle, warnings: list[str]) -> tuple[Any, Any]:
    text = bundle.resources.get("LuaEnum.lua")
    if text is None:
        warnings.append("LuaEnum.lua: resource is missing; skipped.")
        return None, None
    try:
        luavm.run_chunk(runtime, text, "LuaEnum.lua")
    except luavm.LuaChunkError as exc:
        warnings.append(f"LuaEnum.lua: {exc.phase}: {exc.message}")
        return None, None
    globals_table = runtime.globals()
    try:
        enum_global = luavm.lua_to_python(globals_table["Enum"])
        constants_global = luavm.lua_to_python(globals_table["Constants"])
    except ValueError as exc:
        warnings.append(f"LuaEnum.lua: {exc}")
        return None, None
    return enum_global, constants_global


def build_index(bundle: SourceBundle, *, generated_at: float) -> dict[str, Any]:
    """Build the plain-data API index from one fetched bundle.

    Why this exists:
        The single place that turns mirror Lua into the index every lookup answers from:
        documentation first (signatures, secret and restriction facts), then the resource
        lists filling gaps without ever overwriting a documented entry.

    Args:
        bundle: The fetched texts from ``fetch_mirror_bundle`` (or a canned bundle).
        generated_at: Build time as a POSIX timestamp, stamped into the index verbatim.

    Returns:
        A JSON-serialisable dict with ``schema``, ``flavor``, ``build``, ``source``,
        ``generated_at``, ``documentation_files``, ``counts`` (per kind in ``KINDS``),
        ``warnings``, ``widgets`` and ``entries`` (kind to name to entry). Every entry has
        ``name``, ``kind``, ``restricted``, ``secret``, ``deprecated``, ``documented`` and
        ``source``, plus its kind-specific keys.

    Failure modes:
        Raises ``luavm.LuaVMUnavailableError`` when the VM cannot be created. A documentation
        or resource file that fails to compile or run, a missing resource, and every skipped
        table, field or name are appended to the returned ``warnings`` and the build
        continues; an unconvertible documentation collector is likewise a warning with no
        documented entries.
    """
    warnings: list[str] = list(bundle.warnings)
    entries: dict[str, dict[str, dict[str, Any]]] = {kind: {} for kind in KINDS}
    widgets: dict[str, Any] = {}
    runtime = luavm.new_runtime()
    collector = luavm.run_chunk_value(runtime, _SHIM_CHUNK, "apidocs-shim.lua")
    # [2026-11-11 T-005] LuaEnum.lua runs FIRST: it assigns the globals Enum and Constants,
    # and documentation files reference them (for example Enum.SecretAspect.Text) while
    # building their tables; without it those files fail and the index loses real systems.
    enum_global, constants_global = _run_lua_enum(runtime, bundle, warnings)
    for name in sorted(bundle.documentation):
        try:
            luavm.run_chunk(runtime, bundle.documentation[name], name)
        except luavm.LuaChunkError as exc:
            warnings.append(f"{name}: {exc.phase}: {exc.message}")
    try:
        systems = luavm.lua_to_python(collector)
    except ValueError as exc:
        warnings.append(f"documentation: {exc}")
        systems = []
    _add_documented_systems(systems, entries, warnings)
    global_api = _resource_value(runtime, bundle, "GlobalAPI.lua", warnings)
    if global_api is not _NO_VALUE:
        _merge_global_api(global_api, entries, warnings)
    resource_events = _resource_value(runtime, bundle, "Events.lua", warnings)
    if resource_events is not _NO_VALUE:
        _merge_resource_events(resource_events, entries, warnings)
    frame_xml = _resource_value(runtime, bundle, "FrameXML.lua", warnings)
    if frame_xml is not _NO_VALUE:
        _merge_frame_xml(frame_xml, entries, warnings)
    _merge_lua_enum_globals(enum_global, constants_global, entries, warnings)
    templates = _resource_value(runtime, bundle, "Templates.lua", warnings)
    if templates is not _NO_VALUE:
        _merge_templates(templates, entries, warnings)
    widget_api = _resource_value(runtime, bundle, "WidgetAPI.lua", warnings)
    if widget_api is not _NO_VALUE:
        _merge_widget_api(widget_api, entries, widgets, warnings)
    mixins = _resource_value(runtime, bundle, "Mixins.lua", warnings)
    if mixins is not _NO_VALUE:
        _merge_mixins(mixins, entries, warnings)
    return {
        "schema": SCHEMA_VERSION,
        "flavor": bundle.flavor,
        "build": bundle.build,
        "source": bundle.source,
        "generated_at": float(generated_at),
        "documentation_files": len(bundle.documentation),
        "counts": {kind: len(entries[kind]) for kind in KINDS},
        "warnings": warnings,
        "widgets": widgets,
        "entries": entries,
    }


class ApiIndex:
    """A loaded index that answers status, lookup, search and event questions.

    Why this exists:
        Callers ask the same four questions of the plain index data; this wrapper owns the
        answer shapes (including the not-found guidance that points at the namespaced
        spelling) so no caller re-derives them.

    Args:
        data: Index data as built by ``build_index`` or loaded from JSON.

    Returns:
        Nothing; construct then call the query methods.

    Failure modes:
        Raises ``ApiIndexError("stale-index", ...)`` when ``data["schema"]`` is not
        ``SCHEMA_VERSION`` or ``"entries"`` is missing.
    """

    def __init__(self, data: Mapping[str, Any]) -> None:
        if data.get("schema") != SCHEMA_VERSION or "entries" not in data:
            raise ApiIndexError(
                "stale-index",
                "The API index is missing, incomplete, or from an older schema.",
                _SYNC_HINT,
            )
        self._data = data

    @property
    def data(self) -> Mapping[str, Any]:
        """Return the underlying index data.

        Why this exists:
            Callers that must serialise or forward the whole index read it here instead of
            reaching into a private attribute.

        Args:
            None.

        Returns:
            The mapping passed to the constructor, unchanged.

        Failure modes:
            None.
        """
        return self._data

    def _kind_entries(self, kind: str) -> Mapping[str, Any]:
        entries = self._data.get("entries")
        if not isinstance(entries, Mapping):
            return {}
        kind_entries = entries.get(kind)
        return kind_entries if isinstance(kind_entries, Mapping) else {}

    def _all_names(self) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for kind in KINDS:
            for name in sorted(self._kind_entries(kind), key=str):
                text = str(name)
                if text not in seen:
                    seen.add(text)
                    names.append(text)
        return names

    def status(self, *, now: float) -> dict[str, Any]:
        """Report what this index is and how old it is.

        Why this exists:
            A lookup answer is only trustworthy with its build and age attached; this is the
            one place that computes them.

        Args:
            now: The current time as a POSIX timestamp.

        Returns:
            A dict with ``flavor``, ``build``, ``source``, ``schema``, ``generated_at``,
            ``generated_at_utc`` (ISO 8601 UTC, seconds, ending ``"Z"``), ``age_seconds``
            (never negative), ``documentation_files``, ``counts``, ``warning_count``,
            ``warnings`` (first 20) and ``warnings_truncated``.

        Failure modes:
            None; missing or malformed fields degrade to defaults (``generated_at`` 0,
            counts recomputed from the entries).
        """
        raw_generated = self._data.get("generated_at")
        generated = (
            float(raw_generated)
            if isinstance(raw_generated, (int, float)) and not isinstance(raw_generated, bool)
            else 0.0
        )
        raw_warnings = self._data.get("warnings")
        all_warnings = (
            [str(item) for item in raw_warnings] if isinstance(raw_warnings, list) else []
        )
        raw_counts = self._data.get("counts")
        counts = (
            dict(raw_counts)
            if isinstance(raw_counts, Mapping)
            else {kind: len(self._kind_entries(kind)) for kind in KINDS}
        )
        return {
            "flavor": self._data.get("flavor"),
            "build": self._data.get("build"),
            "source": self._data.get("source"),
            "schema": self._data.get("schema"),
            "generated_at": generated,
            "generated_at_utc": datetime.fromtimestamp(generated, tz=UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "age_seconds": max(0, int(now - generated)),
            "documentation_files": self._data.get("documentation_files"),
            "counts": counts,
            "warning_count": len(all_warnings),
            "warnings": all_warnings[:20],
            "warnings_truncated": len(all_warnings) > 20,
        }

    def lookup(self, name: str) -> dict[str, Any]:
        """Look one name up across every kind, in ``KINDS`` order.

        Why this exists:
            The central question "does this API exist, and what is it?" gets one answer
            shape whether the name hits or misses, and a miss for a bare name points at the
            namespaced spelling instead of only saying no.

        Args:
            name: The exact name to find, e.g. ``"C_Item.GetItemInfo"`` or ``"GetItemInfo"``.

        Returns:
            ``{"found": True, **entry}`` on an exact match. Otherwise a dict with
            ``found`` False, ``name``, ``kind`` ``"unknown"``, ``c_api`` False, ``flavor``,
            ``build``, ``same_name_in_namespaces`` (the namespace candidates, only computed
            when ``name`` has no ``"."``), ``replacement`` (first candidate or ``None``),
            ``nearest`` (up to 8 close names, case-insensitive, cutoff 0.6) and ``message``.

        Failure modes:
            None; an unknown name is a normal answer, not an error.
        """
        for kind in KINDS:
            kind_entries = self._kind_entries(kind)
            if name in kind_entries:
                entry = kind_entries[name]
                if isinstance(entry, Mapping):
                    return {"found": True, **dict(entry)}
                return {"found": True, "name": name, "kind": kind}
        flavor = self._data.get("flavor")
        build = self._data.get("build")
        candidates = (
            _namespace_candidates(self._kind_entries("function"), name) if "." not in name else []
        )
        lowered: dict[str, str] = {}
        for existing in self._all_names():
            lowered.setdefault(existing.lower(), existing)
        close = difflib.get_close_matches(name.lower(), list(lowered), n=8, cutoff=0.6)
        nearest = [lowered[item] for item in close]
        if candidates:
            message = (
                f"{name} is not a C API function in build {build} ({flavor}). "
                f"The same function name exists in a namespace: {', '.join(candidates)}."
            )
        else:
            message = f"{name} is not in the API index for build {build} ({flavor})."
        return {
            "found": False,
            "name": name,
            "kind": "unknown",
            "c_api": False,
            "flavor": flavor,
            "build": build,
            "same_name_in_namespaces": candidates,
            "replacement": candidates[0] if candidates else None,
            "nearest": nearest,
            "message": message,
        }

    def search(self, query: str, *, limit: int = 50) -> dict[str, Any]:
        """Search entry names by case-insensitive substring.

        Why this exists:
            Discovery questions ("what mentions ItemInfo?") need a bounded, ordered answer
            over every kind, not a raw dump of the index.

        Args:
            query: The substring to find; must not be empty or blank.
            limit: Maximum number of results to return.

        Returns:
            ``{"query", "total", "returned", "truncated", "results"}`` where results are
            sorted by (``KINDS`` order, name) and each is a dict with ``name``, ``kind``,
            ``restricted`` and ``deprecated``.

        Failure modes:
            Raises ``ApiIndexError("bad-argument", ...)`` for an empty or blank query.
        """
        if not query.strip():
            raise ApiIndexError(
                "bad-argument",
                "Search query must not be empty.",
                "Pass a non-empty substring to search for.",
            )
        needle = query.strip().lower()
        results: list[dict[str, Any]] = []
        for kind in KINDS:
            kind_entries = self._kind_entries(kind)
            for name in sorted(kind_entries, key=str):
                if needle not in str(name).lower():
                    continue
                entry = kind_entries[name]
                mapping_entry = entry if isinstance(entry, Mapping) else {}
                results.append(
                    {
                        "name": str(name),
                        "kind": kind,
                        "restricted": bool(mapping_entry.get("restricted")),
                        "deprecated": bool(mapping_entry.get("deprecated")),
                    }
                )
        effective = max(0, limit)
        return {
            "query": query,
            "total": len(results),
            "returned": min(len(results), effective),
            "truncated": len(results) > effective,
            "results": results[:effective],
        }

    def events(self, query: str | None = None, *, limit: int = 200) -> dict[str, Any]:
        """List event names, optionally filtered by substring.

        Why this exists:
            Event registration needs the literal event names with their restriction facts;
            this answers it without exposing whole payload signatures.

        Args:
            query: Optional case-insensitive substring; ``None`` lists every event.
            limit: Maximum number of events to return.

        Returns:
            ``{"query", "total", "returned", "truncated", "events"}`` where events are
            sorted by name and each is a dict with ``name``, ``restricted``, ``documented``
            and ``system``.

        Failure modes:
            None; no match is an empty list with ``total`` 0.
        """
        needle = query.lower() if query else None
        kind_entries = self._kind_entries("event")
        events: list[dict[str, Any]] = []
        for name in sorted(kind_entries, key=str):
            if needle is not None and needle not in str(name).lower():
                continue
            entry = kind_entries[name]
            mapping_entry = entry if isinstance(entry, Mapping) else {}
            events.append(
                {
                    "name": str(name),
                    "restricted": bool(mapping_entry.get("restricted")),
                    "documented": bool(mapping_entry.get("documented")),
                    "system": mapping_entry.get("system"),
                }
            )
        effective = max(0, limit)
        return {
            "query": query,
            "total": len(events),
            "returned": min(len(events), effective),
            "truncated": len(events) > effective,
            "events": events[:effective],
        }


def _atomic_write_text(path: Path, text: str) -> None:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(text)
        # [2026-11-11 T-005] Write-then-replace in the same directory: a crash mid-write can
        # only leave the old index or the whole new one, never a half-written file a later
        # read would mistake for a corrupt sync.
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


class IndexStore:
    """The on-disk cache of built indexes: one JSON per flavor+build, plus a pointer file.

    Why this exists:
        Indexes are rebuilt per client build; the ``<flavor>-<build>.json`` files keep old
        builds addressable while ``<flavor>.current`` names the one lookups load.

    Args:
        cache_dir: Directory the index and pointer files live in.

    Returns:
        Nothing; construct then call ``save`` or ``load``.

    Failure modes:
        ``save`` and ``load`` raise ``ApiIndexError`` as documented on each method;
        filesystem errors other than a missing pointer or index propagate from ``save``.
    """

    def __init__(self, cache_dir: str | os.PathLike[str]) -> None:
        self._cache_dir = Path(cache_dir)

    def save(self, data: Mapping[str, Any]) -> str:
        """Write an index and point its flavor at it.

        Why this exists:
            The atomic write and the pointer update are one operation; splitting them would
            let a caller publish an index no lookup can find, or a pointer at a half file.

        Args:
            data: Index data with ``flavor`` and ``build`` keys.

        Returns:
            The index file path as a string.

        Failure modes:
            Raises ``ApiIndexError("bad-argument", ...)`` when flavor or build does not match
            ``^[A-Za-z0-9_.-]+$`` (they become a file name). Other filesystem errors
            propagate as ``OSError``.
        """
        flavor = data.get("flavor")
        build = data.get("build")
        if not (
            isinstance(flavor, str)
            and isinstance(build, str)
            and re.fullmatch(r"[A-Za-z0-9_.-]+", flavor)
            and re.fullmatch(r"[A-Za-z0-9_.-]+", build)
        ):
            raise ApiIndexError(
                "bad-argument",
                f"Index flavor and build must match ^[A-Za-z0-9_.-]+$: "
                f"flavor={flavor!r}, build={build!r}.",
                "Build the index from a mirror bundle with a well-formed flavor and build.",
            )
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{flavor}-{build}.json"
        index_path = self._cache_dir / file_name
        _atomic_write_text(index_path, json.dumps(dict(data), ensure_ascii=False, indent=2))
        _atomic_write_text(self._cache_dir / f"{flavor}.current", file_name)
        return str(index_path)

    def load(self, flavor: str) -> ApiIndex:
        """Load the current index for ``flavor``.

        Why this exists:
            Every "no usable index" situation gets one of two codes here: nothing was ever
            synced (``"no-index"``) or what is cached cannot be trusted (``"stale-index"``),
            both with the sync command as the hint.

        Args:
            flavor: Flavor name as saved, e.g. ``"forever"``.

        Returns:
            The loaded ``ApiIndex``.

        Failure modes:
            Raises ``ApiIndexError("no-index", ...)`` when the pointer or the file it names
            is missing, or when the pointer names anything but a plain file name. Raises
            ``ApiIndexError("stale-index", ...)`` when the file is unreadable, is not valid
            JSON, is not a JSON object, or fails the ``ApiIndex`` schema check.
        """
        no_index = ApiIndexError(
            "no-index",
            f"No API index for flavor {flavor} in {self._cache_dir}.",
            _SYNC_HINT,
        )
        if "/" in flavor or "\\" in flavor or ".." in flavor:
            raise no_index
        try:
            pointer_text = (self._cache_dir / f"{flavor}.current").read_text(encoding="utf-8")
        except OSError as exc:
            raise no_index from exc
        file_name = pointer_text.strip()
        # [2026-11-11 T-005] The pointer is data, not a path: anything with a separator or
        # ".." could aim a read outside the cache, so it is treated as no index at all.
        if not file_name or "/" in file_name or "\\" in file_name or ".." in file_name:
            raise no_index
        index_path = self._cache_dir / file_name
        try:
            text = index_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise no_index from exc
        except OSError as exc:
            raise ApiIndexError(
                "stale-index",
                f"The API index in {self._cache_dir} could not be read: {exc}",
                _SYNC_HINT,
            ) from exc
        try:
            parsed: Any = json.loads(text)
        except ValueError as exc:
            raise ApiIndexError(
                "stale-index",
                f"The API index in {self._cache_dir} is not valid JSON: {exc}",
                _SYNC_HINT,
            ) from exc
        if not isinstance(parsed, dict):
            raise ApiIndexError(
                "stale-index",
                f"The API index in {self._cache_dir} is not a JSON object.",
                _SYNC_HINT,
            )
        return ApiIndex(parsed)


def default_cache_dir() -> Path:
    """Return the default directory for cached API indexes.

    Why this exists:
        The cache location follows the Hermes home convention; pinning it in one place keeps
        the CLI, the tools and the tests in agreement.

    Args:
        None.

    Returns:
        ``$HERMES_HOME/cache/wow-addon-forge/api-index`` when ``HERMES_HOME`` is set and
        non-empty, else ``~/.hermes/cache/wow-addon-forge/api-index``.

    Failure modes:
        None.
    """
    hermes_home = os.environ.get("HERMES_HOME")
    base = Path(hermes_home) if hermes_home else Path.home() / ".hermes"
    return base / "cache" / "wow-addon-forge" / "api-index"
