"""T-024 acceptance tests for the Addon Forge pane backend (created 2026-11-11).

The fake install lives under ``tmp_path``. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from dashboard import plugin_api
from tests.conftest import forever_install_files
from wow_addon_forge.apidocs import IndexStore
from wow_addon_forge.headless import minimal_api_index
from wow_addon_forge.tools import ForgeTools

_ALLOWED_IMPORTS = {"@hermes/plugin-sdk", "react", "react/jsx-runtime"}


def _write_install(root: Path) -> None:
    for path, text in forever_install_files(str(root)).items():
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _tools(tmp_path: Path) -> ForgeTools:
    root = tmp_path / "WoW"
    _write_install(root)
    IndexStore(tmp_path / "index").save(minimal_api_index().data)
    return ForgeTools(default_roots=[str(root)], cache_dir=tmp_path / "index")


def test_routes_return_status_addons_and_a_check(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    status = asyncio.run(plugin_api.get_status(tools=tools))
    assert status["ok"] is True
    assert status["flavor"] == "_forever_"
    assert status["build"] == "1.60.1.70888"

    listed = asyncio.run(plugin_api.get_addons(tools=tools))
    assert listed["ok"] is True
    assert "Guildhall" in listed["addons"]

    addon = tmp_path / "WoW" / "_forever_" / "Interface" / "AddOns" / "Guildhall"
    checked = asyncio.run(plugin_api.post_check(body={"path": str(addon)}, tools=tools))
    assert checked["ok"] is True
    assert isinstance(checked["verdict"], str)


def test_long_routes_are_registered() -> None:
    source = Path("dashboard/plugin_api.py").read_text(encoding="utf-8")
    for decorator in (
        '@router.get("/status")',
        '@router.get("/addons")',
        '@router.post("/check")',
        '@router.post("/install")',
        '@router.post("/bridge/pull")',
    ):
        assert decorator in source


def test_pane_imports_only_the_sdk_and_has_no_jsx() -> None:
    source = Path("desktop/plugin.js").read_text(encoding="utf-8")
    assert "<div" not in source
    assert "jsx(" in source
    imports = re.findall(r"from\s+['\"]([^'\"]+)['\"]", source)
    assert imports
    assert set(imports) <= _ALLOWED_IMPORTS
