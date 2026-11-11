"""Tests for the Hermes tool handlers and the ``env`` CLI verb (created 2026-11-11, T-003).

Invariants owned by this file:
- Every ``ForgeTools`` here is built with an injected fake filesystem, and every ``main`` call
  either injects ``tools=`` or passes an explicit ``--root`` under ``tmp_path``, so no test ever
  reads a real game install.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from wow_addon_forge import PROVIDES_TOOLS
from wow_addon_forge.__main__ import main
from wow_addon_forge.tools import WOW_ENV_SCHEMA, ForgeTools, register_tools


class RecordingContext:
    """Stand-in for the Hermes PluginContext: records every ``register_tool`` call."""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []

    def register_tool(self, name: str, **kwargs: Any) -> None:
        self.tools.append({"name": name, **kwargs})


class ExplodingFileSystem:
    """A ``FileSystem`` whose ``is_dir`` always fails with a non-``OSError``."""

    def is_dir(self, path: str) -> bool:
        raise RuntimeError("disk on fire")

    def is_file(self, path: str) -> bool:
        return False

    def list_dir(self, path: str) -> list[str]:
        return []

    def read_text(self, path: str) -> str:
        return ""

    def join(self, base: str, *parts: str) -> str:
        return "/".join([base.rstrip("/"), *parts])


def test_wow_env_reports_forever_flavor_interface_16001_and_addons_as_json(
    forever_fs: Any, mac_root: str
) -> None:
    """The acceptance test of T-003: the fake _forever_ install, reported end to end."""
    raw = ForgeTools(fs=forever_fs).handle_env({})
    assert isinstance(raw, str)
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["installs"][0]["root"] == mac_root
    flavors = payload["installs"][0]["flavors"]
    forever = next(f for f in flavors if f["flavor"] == "_forever_")
    assert forever["interface"] == 16001
    assert forever["interface_source"] == "derived-from-version"
    assert forever["version"] == "1.60.1.70888"
    assert forever["product"] == "wowf"
    assert forever["accounts"] == 2
    assert [a["name"] for a in forever["addons"]] == ["Guildhall", "TrailMap"]
    guildhall = next(a for a in forever["addons"] if a["name"] == "Guildhall")
    assert guildhall == {
        "name": "Guildhall",
        "toc": "Guildhall.toc",
        "title": "Guildhall",
        "version": "0.1.0",
        "interface": [16001],
        "supports_client": True,
    }


def test_wow_env_with_explicit_root_searches_only_that_root(
    forever_files: dict[str, str], mac_root: str, fake_fs_factory: Any
) -> None:
    files: dict[str, str] = {}
    for path, text in forever_files.items():
        files["/games/wow" + path[len(mac_root) :]] = text
    payload = json.loads(
        ForgeTools(fs=fake_fs_factory(files)).handle_env({"root": "/games/wow"}),
    )
    assert payload["ok"] is True
    assert payload["searched"] == ["/games/wow"]


def test_wow_env_no_install_reports_searched_and_warnings(fake_fs_factory: Any) -> None:
    payload = json.loads(ForgeTools(fs=fake_fs_factory({})).handle_env({}))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "no-install"
    assert payload["error"]["message"]
    assert payload["error"]["hint"]
    assert len(payload["searched"]) == 2
    assert payload["warnings"] == []


def test_wow_env_none_and_empty_root_behave_like_empty_args(forever_fs: Any) -> None:
    tools = ForgeTools(fs=forever_fs)
    assert json.loads(tools.handle_env(None))["ok"] is True
    assert json.loads(tools.handle_env({"root": ""}))["ok"] is True
    assert json.loads(tools.handle_env({}))["ok"] is True


def test_wow_env_non_string_root_is_bad_argument(forever_fs: Any) -> None:
    payload = json.loads(ForgeTools(fs=forever_fs).handle_env({"root": 123}))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad-argument"
    assert "int" in payload["error"]["message"]


def test_wow_env_non_mapping_args_is_bad_argument(forever_fs: Any) -> None:
    payload = json.loads(ForgeTools(fs=forever_fs).handle_env([]))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad-argument"
    assert "list" in payload["error"]["message"]


def test_default_roots_replace_the_built_in_search_locations(
    forever_files: dict[str, str], mac_root: str, fake_fs_factory: Any
) -> None:
    """With no ``root`` argument the configured default roots are searched, and only those."""
    files = {"/games/wow" + path[len(mac_root) :]: text for path, text in forever_files.items()}
    tools = ForgeTools(fs=fake_fs_factory(files), default_roots=["/games/wow"])
    payload = json.loads(tools.handle_env({}))
    assert payload["ok"] is True
    assert payload["searched"] == ["/games/wow"]
    assert payload["installs"][0]["root"] == "/games/wow"


def test_wow_env_filesystem_failure_is_internal_error_not_raised() -> None:
    payload = json.loads(ForgeTools(fs=ExplodingFileSystem()).handle_env({}))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "internal-error"
    assert "RuntimeError" in payload["error"]["message"]
    assert "disk on fire" in payload["error"]["message"]


def test_handle_env_ignores_extra_hermes_kwargs(forever_fs: Any) -> None:
    payload = json.loads(ForgeTools(fs=forever_fs).handle_env({}, task_id="t1", session_id="s1"))
    assert payload["ok"] is True


def test_wow_env_json_keeps_non_ascii_addon_title_unescaped(
    forever_files: dict[str, str], mac_root: str, fake_fs_factory: Any
) -> None:
    files = dict(forever_files)
    files[f"{mac_root}/_forever_/Interface/AddOns/Zauber/Zauber.toc"] = (
        "## Interface: 16001\n## Title: Zauberküche\n## Version: 1.0\n\nMain.lua\n"
    )
    raw = ForgeTools(fs=fake_fs_factory(files)).handle_env({})
    assert "Zauberküche" in raw


def test_wow_env_never_leaks_account_names(forever_fs: Any) -> None:
    raw = ForgeTools(fs=forever_fs).handle_env({})
    assert "ACCOUNT1" not in raw


def test_register_tools_matches_provides_tools_and_registers_wow_env(forever_fs: Any) -> None:
    ctx = RecordingContext()
    registered = register_tools(ctx, tools=ForgeTools(fs=forever_fs))
    assert "wow_env" in registered
    assert registered == list(PROVIDES_TOOLS)
    assert len(ctx.tools) == len(PROVIDES_TOOLS)
    tool = next(item for item in ctx.tools if item["name"] == "wow_env")
    assert tool["name"] == "wow_env"
    assert tool["toolset"] == "wow"
    assert tool["schema"] is WOW_ENV_SCHEMA
    assert tool["schema"]["name"] == "wow_env"
    assert tool["check_fn"]() is True
    assert tool["description"]
    assert json.loads(tool["handler"]({}))["ok"] is True


def test_register_tools_rejects_context_without_register_tool() -> None:
    with pytest.raises(TypeError, match="register_tool"):
        register_tools(object())


def test_wow_env_schema_shape() -> None:
    parameters = WOW_ENV_SCHEMA["parameters"]
    assert parameters["type"] == "object"
    assert parameters["properties"]["root"]["type"] == "string"
    assert not parameters.get("required")


def test_cli_env_with_root_returns_zero_and_prints_json(
    forever_fs: Any, mac_root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["env", "--root", mac_root], tools=ForgeTools(fs=forever_fs)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_cli_env_no_install_returns_one_and_prints_error_json(
    fake_fs_factory: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["env"], tools=ForgeTools(fs=fake_fs_factory({}))) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "no-install"


def test_cli_env_with_empty_tmp_root_returns_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["env", "--root", str(tmp_path)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "no-install"
    assert payload["searched"] == [str(tmp_path)]
