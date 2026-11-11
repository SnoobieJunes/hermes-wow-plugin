"""Root Hermes plugin entrypoint for ``wow-addon-forge`` (created 2026-11-11).

Invariants owned by this file:
- Makes ``src/wow_addon_forge`` importable when Hermes loads this directory directly with
  ``importlib.util.spec_from_file_location`` (no editable install required).
- Exposes ``register(ctx)`` for ``PluginManager`` and ``hermes plugins validate .``.
- Stays import-light: nothing here imports ``lupa``; the Lua VM loads only when a tool needs it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# [2026-11-11 T-002] Put src/ on sys.path so the package resolves from a plain plugin checkout.
_SRC_DIR = str(Path(__file__).resolve().parent / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from wow_addon_forge import register_plugin  # noqa: E402


def register(ctx: Any) -> dict[str, Any]:
    """Register the ``wow-addon-forge`` plugin with the Hermes ``PluginContext``.

    Why this exists:
        Hermes and ``hermes plugins validate`` call ``register(ctx)`` as the single entrypoint of
        a ``kind: standalone`` plugin.

    Args:
        ctx: The Hermes ``PluginContext`` (or the validator's recording context).

    Returns:
        A summary of the plugin identity and what was registered.

    Failure modes:
        Raises ``TypeError`` when ``ctx`` is ``None`` so a misconfigured caller fails loudly.
    """
    return register_plugin(ctx)
