"""Hermes tool handlers for wow-addon-forge (created 2026-11-11).

Invariants owned by this file:
- Every handler returns JSON text and never raises; a failure is
  ``{"ok": false, "error": {"code", "message", "hint"}}`` (docs/SPEC-PLUGIN.md §3).
- ``register_tools`` registers exactly the names in ``wow_addon_forge.PROVIDES_TOOLS``, which
  plugin.yaml ``provides_tools`` must match 1:1.
- ``wow_env`` writes nothing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from wow_addon_forge import TOOLSET
from wow_addon_forge.env import FileSystem, RealFileSystem, detect_installs

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
    """The plugin's tool handlers, bound to one filesystem and one set of default roots.

    Why this exists:
        Handlers need an injected filesystem for hermetic tests, and the CLI and Hermes
        registration must share the same ``env_result`` logic, so both go through this class.

    Args:
        fs: The filesystem to detect installs through; ``RealFileSystem`` when ``None``.
        default_roots: Install roots to search when a call names no root; ``None`` is passed
            through to ``detect_installs``, which then uses its own ``DEFAULT_ROOTS``.

    Failure modes:
        None at construction; ``env_result`` reports every failure as an error result.
    """

    def __init__(
        self, fs: FileSystem | None = None, default_roots: Sequence[str] | None = None
    ) -> None:
        self._fs = fs if fs is not None else RealFileSystem()
        self._default_roots = default_roots

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


def wow_tools_available() -> bool:
    """Report whether the wow tools can run at all.

    Why this exists:
        Hermes asks a ``check_fn`` before offering a tool. ``wow_env`` needs nothing but a
        readable disk, and a machine without a WoW install is a result the tool reports
        (``no-install``), not a reason to hide the tool, so the tool is always available.

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
        The tool names registered, in registration order: ``["wow_env"]``.

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
    # [2026-11-11 T-003] One spec row per tool: later tasks add a row, and the returned
    # names stay in registration order by construction.
    specs = (
        (
            "wow_env",
            WOW_ENV_SCHEMA,
            active.handle_env,
            "Find WoW installs, flavors, client version, Interface number and installed addons.",
            "🧭",
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
