"""Headless WoW: Forever 1.60.1 runtime for wow-addon-forge (created 2026-11-11).

Invariants owned by this package:
- Addon code executes inside a sandboxed Lua 5.1 VM (``lupa.lua51``) against a closed API surface
  derived from an ``ApiIndex``; reading unknown globals or unknown ``C_*`` members, or registering
  unknown events, fails loudly by name.
- Time, addon-message routing/throttling, guild/group state, and restriction regimes are owned
  deterministically by ``World`` and ``SimulatedClient``, never by wall-clock time or OS state.
"""

from __future__ import annotations

from .runtime import (
    PREFIX_RESULT,
    RESTRICTION_STATE,
    RESTRICTION_TYPE,
    SEND_RESULT,
    HeadlessError,
    LuaErrorRecord,
    SimulatedClient,
    World,
    minimal_api_index,
)
from .savedvars_io import (
    SavedVariablesError,
    export_saved_value,
    format_saved_variables_lua,
    import_saved_value,
)

__all__ = [
    "PREFIX_RESULT",
    "RESTRICTION_STATE",
    "RESTRICTION_TYPE",
    "SEND_RESULT",
    "HeadlessError",
    "LuaErrorRecord",
    "SavedVariablesError",
    "SimulatedClient",
    "World",
    "export_saved_value",
    "format_saved_variables_lua",
    "import_saved_value",
    "minimal_api_index",
]
