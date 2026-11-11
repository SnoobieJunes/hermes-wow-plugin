"""Hermes tool handlers for wow-addon-forge (created 2026-11-11).

Invariants owned by this file:
- Every handler returns JSON text and never raises; a failure is
  ``{"ok": false, "error": {"code", "message", "hint"}}`` (docs/SPEC-PLUGIN.md §3).
- ``register_tools`` registers exactly the names in ``wow_addon_forge.PROVIDES_TOOLS``, which
  plugin.yaml ``provides_tools`` must match 1:1.
- ``wow_env`` writes nothing. ``wow_api`` writes only the API index cache, and only on ``sync``,
  which is also the plugin's only network call.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from wow_addon_forge import TOOLSET
from wow_addon_forge.apidocs import (
    ApiIndex,
    ApiIndexError,
    Fetcher,
    IndexStore,
    UrlFetcher,
    build_index,
    default_cache_dir,
    fetch_mirror_bundle,
    normalise_flavor,
)
from wow_addon_forge.env import FileSystem, RealFileSystem, detect_installs
from wow_addon_forge.luavm import LuaVMUnavailableError

WOW_ENV_SCHEMA: dict[str, Any] = {
    "name": "wow_env",
    "description": (
        "Find World of Warcraft installs on this machine: each flavor folder (for example "
        "_forever_), its client version and Interface number, the number of game accounts, "
        "and the installed addons with title, version and Interface list. Read-only: writes "
        "nothing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "root": {
                "type": "string",
                "description": (
                    "Optional. The World of Warcraft folder to inspect (the one that contains "
                    "_forever_). Omit to search the default locations."
                ),
            },
        },
        "additionalProperties": False,
    },
}

# [2026-11-11 T-005] The action and source lists are shared by the schema, the handler and the
# CLI parser, so the three cannot disagree about what a call may say.
WOW_API_ACTIONS: tuple[str, ...] = ("sync", "lookup", "search", "events", "status")
WOW_API_SOURCES: tuple[str, ...] = ("auto", "mirror", "export")

WOW_API_SCHEMA: dict[str, Any] = {
    "name": "wow_api",
    "description": (
        "Build and query the API index for a World of Warcraft client build: which functions, "
        "events, enums, tables, templates and widget methods exist, what they take and return, "
        "and whether the documentation marks them restricted or secret. Actions: sync "
        "(download the public documentation mirrors and rebuild the index; the plugin's only "
        "network call), status, lookup (one exact name), search (text inside names), events "
        "(event names). Look every API call and event up here before writing addon code."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(WOW_API_ACTIONS),
                "description": "What to do: sync, lookup, search, events or status.",
            },
            "name": {
                "type": "string",
                "description": (
                    "For lookup (required): the exact name, for example "
                    "C_ChatInfo.SendAddonMessage or CHAT_MSG_ADDON."
                ),
            },
            "query": {
                "type": "string",
                "description": (
                    "For search (required): text to find inside names. For events (optional): "
                    "only event names containing this text."
                ),
            },
            "flavor": {
                "type": "string",
                "description": (
                    "Optional. The game flavor. Only forever (also written _forever_) is "
                    "supported; it is the default."
                ),
            },
            "source": {
                "type": "string",
                "enum": list(WOW_API_SOURCES),
                "description": (
                    "For sync. auto (the default) and mirror download the public mirrors. "
                    "export (the client's own exported interface files) is not supported yet "
                    "and returns an error."
                ),
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}

_API_CALL_HINT = 'Call wow_api with an object such as {"action": "status"}.'


def to_json(payload: Mapping[str, Any]) -> str:
    """Serialise ``payload`` as the JSON text a Hermes tool handler returns.

    Why this exists:
        Tool handlers cross the Hermes boundary as JSON text, so the encoding choice is
        pinned in one place.

    Args:
        payload: Plain JSON-serialisable data.

    Returns:
        ``json.dumps(payload, ensure_ascii=False)``, so non-ASCII text such as an addon
        title stays readable instead of becoming ``\\uXXXX`` escapes.

    Failure modes:
        Raises ``TypeError`` when ``payload`` holds a value JSON cannot represent; handlers
        build payloads only from plain data, so this does not happen in normal use.
    """
    return json.dumps(payload, ensure_ascii=False)


def error_result(code: str, message: str, hint: str) -> dict[str, Any]:
    """Build the standard failure result every handler returns instead of raising.

    Why this exists:
        docs/SPEC-PLUGIN.md §3 pins one error shape for all tools, so the shape is built in
        exactly one place.

    Args:
        code: The machine-readable error code, e.g. ``"no-install"``.
        message: What went wrong, for a human reader.
        hint: What to do next, for a human reader.

    Returns:
        ``{"ok": False, "error": {"code": code, "message": message, "hint": hint}}``.

    Failure modes:
        None.
    """
    return {"ok": False, "error": {"code": code, "message": message, "hint": hint}}


class ForgeTools:
    """The plugin's tool handlers, bound to their injected seams.

    Why this exists:
        Handlers need an injected filesystem, network fetcher, cache folder and clock for
        hermetic tests, and the CLI and Hermes registration must share the same result
        builders, so both go through this class.

    Args:
        fs: The filesystem to detect installs through; ``RealFileSystem`` when ``None``.
        default_roots: Install roots to search when a call names no root; ``None`` is passed
            through to ``detect_installs``, which then uses its own ``DEFAULT_ROOTS``.
        fetcher: How ``wow_api sync`` downloads the mirrors; a ``UrlFetcher`` is built at
            sync time when ``None``. Tests inject one so no test reaches the network.
        cache_dir: Where the API index is cached; ``default_cache_dir()`` when ``None``.
            Tests inject a temporary folder so no test touches ``~/.hermes``.
        clock: Returns the current time as epoch seconds; ``time.time`` by default. It stamps
            a new index and measures an index's age.

    Failure modes:
        None at construction; the result builders report every failure as an error result.
    """

    def __init__(
        self,
        fs: FileSystem | None = None,
        default_roots: Sequence[str] | None = None,
        *,
        fetcher: Fetcher | None = None,
        cache_dir: str | os.PathLike[str] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._fs = fs if fs is not None else RealFileSystem()
        self._default_roots = default_roots
        self._fetcher = fetcher
        self._cache_dir = cache_dir
        self._clock = clock

    def env_result(self, args: object = None) -> dict[str, Any]:
        """Return the ``wow_env`` result as plain data.

        Why this exists:
            The Hermes handler and the module CLI report the same result; this is the one
            place that builds it, so the two surfaces cannot drift.

        Args:
            args: Tool arguments. ``None`` is treated as ``{}``. The only recognised key is
                ``root``: absent, ``None`` or ``""`` searches the default roots, and a string
                searches only that folder.

        Returns:
            ``{"ok": True, **report.to_dict()}`` when at least one install is found. When no
            install is found, an ``error_result`` with code ``"no-install"`` plus the
            report's ``searched`` and ``warnings`` lists. A ``"bad-argument"`` error result
            for non-mapping ``args`` or a non-string ``root``, and an ``"internal-error"``
            error result for any unexpected detection failure.

        Failure modes:
            Never raises; every failure is returned as an error result.
        """
        # [2026-11-11 T-003] Typed object, not Mapping: the value comes from a model's tool
        # call, so its shape is checked here at run time instead of promised by an annotation.
        arguments: Mapping[str, Any]
        if args is None:
            arguments = {}
        elif isinstance(args, Mapping):
            arguments = args
        else:
            return error_result(
                "bad-argument",
                f"wow_env arguments must be an object, got {type(args).__name__}",
                'Call wow_env with an object such as {} or {"root": "/path"}.',
            )
        root = arguments.get("root")
        roots: Sequence[str] | None
        if root is None or root == "":
            roots = self._default_roots
        elif not isinstance(root, str):
            return error_result(
                "bad-argument",
                f"root must be a string path, got {type(root).__name__}",
                'Call wow_env with an object such as {} or {"root": "/path"}.',
            )
        else:
            roots = [root]
        try:
            report = detect_installs(self._fs, roots)
        # [2026-11-11 T-003] The tool boundary is the one place a broad except is right:
        # SPEC-PLUGIN §3 says a tool returns an error object instead of raising, and the
        # error is surfaced in that object, not swallowed.
        except Exception as exc:
            return error_result(
                "internal-error",
                f"{type(exc).__name__}: {exc}",
                "This is a bug in wow-addon-forge; please report it with this message.",
            )
        if not report.installs:
            searched = list(report.searched)
            result = error_result(
                "no-install",
                "No World of Warcraft install was found. Searched: " + ", ".join(searched),
                "Pass root with the folder that contains _forever_, for example "
                "/Applications/World of Warcraft.",
            )
            result["searched"] = searched
            result["warnings"] = list(report.warnings)
            return result
        return {"ok": True, **report.to_dict()}

    def handle_env(self, args: object = None, **_kwargs: Any) -> str:
        """Handle a ``wow_env`` tool call and return its result as JSON text.

        Why this exists:
            Hermes handlers return JSON text and may receive extra session keyword
            arguments, so this thin wrapper adapts ``env_result`` to that calling shape.

        Args:
            args: Tool arguments, as for ``env_result``.
            **_kwargs: Extra Hermes session arguments (for example ``task_id``), ignored.

        Returns:
            ``to_json(self.env_result(args))``.

        Failure modes:
            Never raises for tool failures; ``env_result`` returns them as error results.
        """
        return to_json(self.env_result(args))

    def api_result(self, args: object = None) -> dict[str, Any]:
        """Return the ``wow_api`` result as plain data.

        Why this exists:
            The Hermes handler and the ``api`` CLI verb answer from the same index through
            the same code, so a lookup on the command line and a lookup by the model agree.

        Args:
            args: Tool arguments: ``action`` (required, one of ``WOW_API_ACTIONS``),
                ``name`` (lookup), ``query`` (search, events), ``flavor`` and ``source``
                (sync). ``None`` is treated as ``{}``, which fails for the missing action.

        Returns:
            ``{"ok": True, "action": <action>, ...}`` with the fields of the matching
            ``ApiIndex`` method (``status``, ``lookup``, ``search``, ``events``); for
            ``sync`` the new index's status plus ``cache_file``, and a ``note`` when
            ``source`` was ``auto``. A lookup of a name the build does not have is an
            answer, not an error: ``ok`` is true and ``found`` is false.

        Failure modes:
            Never raises. Error codes: ``bad-argument``; ``no-index`` and ``stale-index``
            (with the sync call to run); ``export-not-supported``; ``fetch-failed``,
            ``fetch-refused`` and ``bad-mirror-data`` from a sync; ``lua-vm-unavailable``;
            ``internal-error`` for anything unexpected.
        """
        # [2026-11-11 T-005] Same run-time shape check as env_result: the value comes from a
        # model's tool call.
        arguments: Mapping[str, Any]
        if args is None:
            arguments = {}
        elif isinstance(args, Mapping):
            arguments = args
        else:
            return error_result(
                "bad-argument",
                f"wow_api arguments must be an object, got {type(args).__name__}",
                _API_CALL_HINT,
            )
        action = arguments.get("action")
        if not isinstance(action, str) or action not in WOW_API_ACTIONS:
            return error_result(
                "bad-argument",
                f"action must be one of {', '.join(WOW_API_ACTIONS)}; got {action!r}",
                _API_CALL_HINT,
            )
        try:
            result = self._api_action(action, arguments)
        except ApiIndexError as exc:
            return error_result(exc.code, exc.message, exc.hint)
        except LuaVMUnavailableError as exc:
            # [2026-11-11 T-005] SPEC-PLUGIN §12: a missing VM is its own explicit error, so
            # the user is told to install the dependency instead of seeing a generic failure.
            return error_result(
                "lua-vm-unavailable",
                str(exc),
                "Install the plugin's one dependency, lupa>=2.1,<3, then run the call again.",
            )
        # [2026-11-11 T-005] Same boundary rule as env_result: a tool returns an error object
        # instead of raising, and the error is surfaced in that object.
        except Exception as exc:
            return error_result(
                "internal-error",
                f"{type(exc).__name__}: {exc}",
                "This is a bug in wow-addon-forge; please report it with this message.",
            )
        return result

    def _api_action(self, action: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Run one validated ``wow_api`` action; ``ApiIndexError`` carries every refusal."""
        flavor = normalise_flavor(arguments.get("flavor"))
        store = IndexStore(self._cache_dir if self._cache_dir is not None else default_cache_dir())
        if action == "sync":
            return self._api_sync(store, flavor, arguments.get("source"))
        # [2026-11-11 T-005] Every query action loads the cached index first, so a missing or
        # stale index is the same explicit error (with the sync call to run) from all of them.
        index = store.load(flavor)
        if action == "status":
            return {"ok": True, "action": action, **index.status(now=self._clock())}
        if action == "lookup":
            name = arguments.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ApiIndexError(
                    "bad-argument",
                    "lookup needs name: the exact function, event, enum or template name",
                    'Call wow_api with {"action": "lookup", "name": "C_Item.GetItemInfo"}.',
                )
            return {"ok": True, "action": action, **index.lookup(name.strip())}
        query = arguments.get("query")
        if query is not None and not isinstance(query, str):
            raise ApiIndexError(
                "bad-argument",
                f"query must be text, got {type(query).__name__}",
                'Call wow_api with {"action": "search", "query": "AddonMessage"}.',
            )
        if action == "search":
            if query is None or not query.strip():
                raise ApiIndexError(
                    "bad-argument",
                    "search needs query: text to find inside names",
                    'Call wow_api with {"action": "search", "query": "AddonMessage"}.',
                )
            return {"ok": True, "action": action, **index.search(query.strip())}
        filter_text = query.strip() if query is not None and query.strip() else None
        return {"ok": True, "action": action, **index.events(filter_text)}

    def _api_sync(self, store: IndexStore, flavor: str, source: object) -> dict[str, Any]:
        """Download the mirrors, build the index, cache it, and report its status."""
        chosen = "auto" if source is None or source == "" else source
        if not isinstance(chosen, str) or chosen not in WOW_API_SOURCES:
            raise ApiIndexError(
                "bad-argument",
                f"source must be one of {', '.join(WOW_API_SOURCES)}; got {source!r}",
                'Call wow_api with {"action": "sync"} to use the public mirrors.',
            )
        # [2026-11-11 T-005] The client's own export (SPEC-PLUGIN §5 source 1) is not built:
        # no export exists on the development machine, so its folder layout is unverified.
        # Asking for it is refused out loud instead of quietly using the mirror
        # (goose-deuce.md 2026-11-11 "wow_api sync reads the mirrors only").
        if chosen == "export":
            raise ApiIndexError(
                "export-not-supported",
                "Reading the client's own exported interface files is not supported yet "
                "(TASKS.md T-044). Nothing was downloaded or written.",
                'Call wow_api with {"action": "sync"} to build the index from the public mirrors.',
            )
        fetcher = self._fetcher if self._fetcher is not None else UrlFetcher()
        bundle = fetch_mirror_bundle(fetcher, flavor)
        data = build_index(bundle, generated_at=self._clock())
        cache_file = store.save(data)
        result: dict[str, Any] = {
            "ok": True,
            "action": "sync",
            **ApiIndex(data).status(now=self._clock()),
            "cache_file": cache_file,
        }
        if chosen == "auto":
            result["note"] = (
                "source auto used the public mirrors: reading the client's own export is not "
                "supported yet (TASKS.md T-044)."
            )
        return result

    def handle_api(self, args: object = None, **_kwargs: Any) -> str:
        """Handle a ``wow_api`` tool call and return its result as JSON text.

        Why this exists:
            The same thin adapter as ``handle_env``: Hermes handlers return JSON text and may
            receive extra session keyword arguments.

        Args:
            args: Tool arguments, as for ``api_result``.
            **_kwargs: Extra Hermes session arguments (for example ``task_id``), ignored.

        Returns:
            ``to_json(self.api_result(args))``.

        Failure modes:
            Never raises for tool failures; ``api_result`` returns them as error results.
        """
        return to_json(self.api_result(args))


def wow_tools_available() -> bool:
    """Report whether the wow tools can run at all.

    Why this exists:
        Hermes asks a ``check_fn`` before offering a tool. ``wow_env`` needs nothing but a
        readable disk, and a machine without a WoW install is a result the tool reports
        (``no-install``), not a reason to hide the tool. ``wow_api`` reports a missing index
        or a missing Lua VM the same way, as an error result. So the tools are always
        available.

    Returns:
        Always ``True``.

    Failure modes:
        None.
    """
    return True


def register_tools(ctx: Any, *, tools: ForgeTools | None = None) -> list[str]:
    """Register every tool in ``PROVIDES_TOOLS`` on the Hermes context.

    Why this exists:
        Registration is the one place tool names, schemas and handlers meet, so the
        ``PROVIDES_TOOLS`` and plugin.yaml ``provides_tools`` agreement is kept in one spot.

    Args:
        ctx: The Hermes ``PluginContext`` or a test double, with a callable
            ``register_tool``.
        tools: The ``ForgeTools`` whose handlers to register; a default ``ForgeTools`` is
            built when ``None``.

    Returns:
        The tool names registered, in registration order: ``["wow_env", "wow_api"]``.

    Failure modes:
        Raises ``TypeError`` when ``ctx.register_tool`` is missing or not callable.
    """
    register_tool = getattr(ctx, "register_tool", None)
    # [2026-11-11 T-003] A plugin that silently registers nothing is worse than one that
    # fails to load, so a context without register_tool is rejected here, not ignored.
    if not callable(register_tool):
        raise TypeError(
            "register_tools(ctx) needs a context with register_tool; got " + type(ctx).__name__
        )
    active = tools if tools is not None else ForgeTools()
    # [2026-11-11 T-005] One spec row per tool: each tool task adds a row (wow_api is the
    # second), and the returned names stay in registration order by construction.
    specs = (
        (
            "wow_env",
            WOW_ENV_SCHEMA,
            active.handle_env,
            "Find WoW installs, flavors, client version, Interface number and installed addons.",
            "🧭",
        ),
        (
            "wow_api",
            WOW_API_SCHEMA,
            active.handle_api,
            "Build and query the index of functions, events and enums in a WoW client build.",
            "📚",
        ),
    )
    registered: list[str] = []
    for name, schema, handler, description, emoji in specs:
        register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=handler,
            check_fn=wow_tools_available,
            description=description,
            emoji=emoji,
        )
        registered.append(name)
    return registered
