"""Dashboard REST backend for the Addon Forge pane (created 2026-11-11).

Invariants owned by this file:
- Routes are ``GET /status``, ``GET /addons``, ``POST /check``, ``POST /install``,
  ``POST /bridge/pull``, and ``GET /errors``.
- Every tool call runs in ``asyncio.to_thread`` so a long check does not block the
  gateway event loop.
- Tests inject ``ForgeTools``. The process default is used only when none is injected.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# [2026-11-11 T-024] Hermes loads this file by path, not as an installed package.
_SRC_DIR = str(Path(__file__).resolve().parents[1] / "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from wow_addon_forge.tools import ForgeTools  # noqa: E402


class _FallbackAPIRouter:
    """Record routes when FastAPI is not installed, so tests can list them."""

    def __init__(self) -> None:
        self.routes: list[dict[str, Any]] = []

    def get(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a GET handler."""

        def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.routes.append({"method": "GET", "path": path, "endpoint": fn})
            return fn

        return _decorator

    def post(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a POST handler."""

        def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.routes.append({"method": "POST", "path": path, "endpoint": fn})
            return fn

        return _decorator


try:
    from fastapi import APIRouter as _RouterCls  # type: ignore[import-not-found]
except ImportError:
    _RouterCls = _FallbackAPIRouter

router = _RouterCls()


def _tools(tools: ForgeTools | None) -> ForgeTools:
    """Return the injected tools, or a process-default set when a route has none."""
    return tools if tools is not None else ForgeTools()


def _object(body: object) -> dict[str, Any]:
    """Return a mapping body, or an empty object when the caller sent none."""
    return body if isinstance(body, dict) else {}


def _addon_names(report: dict[str, Any]) -> list[str]:
    """Collect addon folder names from a ``wow_env`` result, forever flavor first."""
    names: list[str] = []
    installs = report.get("installs")
    if not isinstance(installs, list):
        return names
    for install in installs:
        if not isinstance(install, dict):
            continue
        flavors = install.get("flavors")
        if not isinstance(flavors, list):
            continue
        ordered = sorted(
            flavors,
            key=lambda item: (
                0 if isinstance(item, dict) and item.get("flavor") == "_forever_" else 1
            ),
        )
        for flavor in ordered:
            if not isinstance(flavor, dict):
                continue
            addons = flavor.get("addons")
            if not isinstance(addons, list):
                continue
            for addon in addons:
                if isinstance(addon, dict) and isinstance(addon.get("name"), str):
                    names.append(addon["name"])
    return names


def status_dict(tools: ForgeTools) -> dict[str, Any]:
    """Return install status for the pane's Game section."""
    report = tools.env_result({})
    if report.get("ok") is not True:
        return report
    installs = report.get("installs")
    first = installs[0] if isinstance(installs, list) and installs else {}
    flavors = first.get("flavors") if isinstance(first, dict) else None
    flavor_list = flavors if isinstance(flavors, list) else []
    forever = next(
        (
            item
            for item in flavor_list
            if isinstance(item, dict) and item.get("flavor") == "_forever_"
        ),
        flavor_list[0] if flavor_list else {},
    )
    flavor = forever if isinstance(forever, dict) else {}
    return {
        "ok": True,
        "root": first.get("root") if isinstance(first, dict) else None,
        "flavor": flavor.get("flavor"),
        "build": flavor.get("version"),
        "interface": flavor.get("interface"),
        "addon_count": flavor.get("addon_count"),
    }


def addons_dict(tools: ForgeTools) -> dict[str, Any]:
    """Return the addon folder names the Game section found."""
    report = tools.env_result({})
    if report.get("ok") is not True:
        return report
    return {"ok": True, "addons": _addon_names(report)}


def check_dict(tools: ForgeTools, body: object) -> dict[str, Any]:
    """Run ``wow_check`` for the path in ``body``."""
    return tools.check_result(_object(body))


def install_dict(tools: ForgeTools, body: object) -> dict[str, Any]:
    """Run ``wow_install`` for the path in ``body``."""
    return tools.install_result(_object(body))


def bridge_pull_dict(tools: ForgeTools, body: object) -> dict[str, Any]:
    """Run ``wow_bridge`` pull. An omitted addon lets the tool pick the only bridge addon."""
    payload = {"action": "pull", **_object(body)}
    payload["action"] = "pull"
    return tools.bridge_result(payload)


def errors_dict(tools: ForgeTools, body: object) -> dict[str, Any]:
    """Read ForgeProbe errors. ``body`` may name flavor, account, addon, or root."""
    return tools.errors_result(_object(body))


async def get_status(*, tools: ForgeTools | None = None) -> dict[str, Any]:
    """GET /status. Offloads the install scan."""
    chosen = _tools(tools)
    return await asyncio.to_thread(status_dict, chosen)


async def get_addons(*, tools: ForgeTools | None = None) -> dict[str, Any]:
    """GET /addons. Offloads the install scan."""
    chosen = _tools(tools)
    return await asyncio.to_thread(addons_dict, chosen)


async def post_check(
    body: dict[str, Any] | None = None, *, tools: ForgeTools | None = None
) -> dict[str, Any]:
    """POST /check. Offloads the headless check."""
    chosen = _tools(tools)
    return await asyncio.to_thread(check_dict, chosen, body)


async def post_install(
    body: dict[str, Any] | None = None, *, tools: ForgeTools | None = None
) -> dict[str, Any]:
    """POST /install. Offloads the copy into AddOns."""
    chosen = _tools(tools)
    return await asyncio.to_thread(install_dict, chosen, body)


async def post_bridge_pull(
    body: dict[str, Any] | None = None, *, tools: ForgeTools | None = None
) -> dict[str, Any]:
    """POST /bridge/pull. Offloads the SavedVariables read."""
    chosen = _tools(tools)
    return await asyncio.to_thread(bridge_pull_dict, chosen, body)


async def get_errors(
    body: dict[str, Any] | None = None, *, tools: ForgeTools | None = None
) -> dict[str, Any]:
    """GET /errors. Offloads the ForgeProbe read."""
    chosen = _tools(tools)
    return await asyncio.to_thread(errors_dict, chosen, body)


@router.get("/status")  # type: ignore[untyped-decorator]
async def _route_status() -> dict[str, Any]:
    return await get_status()


@router.get("/addons")  # type: ignore[untyped-decorator]
async def _route_addons() -> dict[str, Any]:
    return await get_addons()


@router.post("/check")  # type: ignore[untyped-decorator]
async def _route_check(body: dict[str, Any] | None = None) -> dict[str, Any]:
    return await post_check(body)


@router.post("/install")  # type: ignore[untyped-decorator]
async def _route_install(body: dict[str, Any] | None = None) -> dict[str, Any]:
    return await post_install(body)


@router.post("/bridge/pull")  # type: ignore[untyped-decorator]
async def _route_bridge_pull(body: dict[str, Any] | None = None) -> dict[str, Any]:
    return await post_bridge_pull(body)


@router.get("/errors")  # type: ignore[untyped-decorator]
async def _route_errors() -> dict[str, Any]:
    return await get_errors()
