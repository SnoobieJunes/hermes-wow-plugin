"""T-039 acceptance tests for plugin settings and wow_root (created 2026-11-11).

The fake install lives under ``tmp_path``. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from conftest import forever_install_files

from wow_addon_forge import register_plugin
from wow_addon_forge.env import DEFAULT_ROOTS


class _Ctx:
    def __init__(self, settings: dict[str, str]) -> None:
        self.settings = settings
        self.handlers: dict[str, Any] = {}

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def register_tool(self, *, name: str, handler: Any, **_: Any) -> None:
        self.handlers[name] = handler


def _write_install(root: Path) -> None:
    for path, text in forever_install_files(str(root)).items():
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def test_config_schema_declares_the_three_settings() -> None:
    manifest = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "plugin.yaml").read_text(encoding="utf-8")
    )
    schema = manifest["config_schema"]
    assert set(schema) == {"wow_root", "flavor", "api_source"}
    assert schema["flavor"]["default"] == "_forever_"
    assert schema["api_source"]["default"] == "auto"
    assert schema["api_source"]["enum"] == ["auto", "export", "mirror"]


def test_wow_root_is_the_only_place_searched(tmp_path: Path) -> None:
    root = tmp_path / "WoW"
    _write_install(root)
    ctx = _Ctx({"wow_root": str(root)})
    register_plugin(ctx)
    found = json.loads(ctx.handlers["wow_env"]({}))
    assert found["ok"] is True, found
    assert found["searched"] == [str(root)]
    flavors = [item["flavor"] for item in found["installs"][0]["flavors"]]
    assert "_forever_" in flavors


def test_no_setting_searches_the_default_locations() -> None:
    ctx = _Ctx({})
    register_plugin(ctx)
    result = json.loads(ctx.handlers["wow_env"]({}))
    assert result["searched"] == list(DEFAULT_ROOTS)


def test_wow_root_is_the_install_root_too(tmp_path: Path) -> None:
    root = tmp_path / "WoW"
    _write_install(root)
    ctx = _Ctx({"wow_root": str(root)})
    register_plugin(ctx)
    saved = json.loads(ctx.handlers["wow_savedvars"]({"addon": "Guildhall", "account": "ACCOUNT1"}))
    assert saved["ok"] is True, saved
    assert "GuildhallDB" in saved["data"]


def test_call_root_targets_one_install(tmp_path: Path) -> None:
    root = tmp_path / "WoW"
    _write_install(root)
    ctx = _Ctx({})
    register_plugin(ctx)
    saved = json.loads(
        ctx.handlers["wow_savedvars"](
            {"addon": "Guildhall", "account": "ACCOUNT1", "root": str(root)}
        )
    )
    assert saved["ok"] is True, saved
