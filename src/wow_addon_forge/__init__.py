"""wow-addon-forge: a Hermes plugin that builds WoW: Forever addons that load and run.

Created 2026-11-11. Invariants owned by this file:
- ``__version__`` is the single version; ``plugin.yaml`` and ``pyproject.toml`` must agree with it
  (``tests/test_smoke.py`` enforces that).
- ``PROVIDES_TOOLS`` is the single list of tool names; ``plugin.yaml`` ``provides_tools`` must match
  it exactly, because the Hermes validator treats a mismatch as a security failure.
"""

from __future__ import annotations

from typing import Any

# [2026-11-11 T-002] Canonical identity shared by the manifest, the CLI and the tests.
__version__ = "0.1.0"
PLUGIN_ID = "wow-addon-forge"
TOOLSET = "wow"
# [2026-11-11 T-009] Registered tools in registration order; plugin.yaml provides_tools
# must match this tuple 1:1.
PROVIDES_TOOLS: tuple[str, ...] = ("wow_env", "wow_api", "wow_check", "wow_test", "wow_errors")

__all__ = ["PLUGIN_ID", "PROVIDES_TOOLS", "TOOLSET", "__version__", "register_plugin"]


def register_plugin(ctx: Any) -> dict[str, Any]:
    """Register every plugin surface on ``ctx`` and describe what was registered.

    Why this exists:
        The root ``__init__.py`` delegates here so the package can be imported and tested without
        Hermes on the path.

    Args:
        ctx: The Hermes ``PluginContext``, the validator's recording context, or a test double.

    Returns:
        ``{"plugin", "version", "tools"}`` — the identity and the tool names registered.

    Failure modes:
        Raises ``TypeError`` when ``ctx`` is ``None`` or has no ``register_tool``.
    """
    if ctx is None:
        raise TypeError("register_plugin(ctx) needs a Hermes PluginContext, got None")
    # [2026-11-11 T-003] Imported here, not at module top: tools.py imports this package for
    # TOOLSET, so a top-level import would be a cycle, and the plugin root stays import-light.
    from wow_addon_forge.tools import register_tools

    return {"plugin": PLUGIN_ID, "version": __version__, "tools": register_tools(ctx)}
