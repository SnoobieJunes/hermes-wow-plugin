"""Smoke tests for the toolchain gate (created 2026-11-11, T-002).

These exercise real entry points: the root ``register(ctx)`` Hermes calls, the module CLI, and the
embedded Lua 5.1 VM every later check depends on.
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from wow_addon_forge import PLUGIN_ID, PROVIDES_TOOLS, __version__, register_plugin
from wow_addon_forge.__main__ import main
from wow_addon_forge.luavm import check_syntax, lua_version, new_runtime

REPO = Path(__file__).resolve().parent.parent


class RecordingContext:
    """Stand-in for the Hermes PluginContext: records what a plugin registers."""

    def __init__(self) -> None:
        self.tools: list[str] = []

    def register_tool(self, *, name: str, **_: Any) -> None:
        self.tools.append(name)


def _load_root_entrypoint() -> Any:
    # [2026-11-11 T-002] Load the root __init__.py the way Hermes does: by file path, not by name.
    spec = importlib.util.spec_from_file_location("wow_addon_forge_root", REPO / "__init__.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_pyproject_and_package_agree() -> None:
    manifest = yaml.safe_load((REPO / "plugin.yaml").read_text(encoding="utf-8"))
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert manifest["name"] == PLUGIN_ID
    assert manifest["kind"] == "standalone"
    assert manifest["version"] == __version__ == project["version"]
    # The validator fails an entry whose declared tools differ from its registrations.
    assert manifest["provides_tools"] == list(PROVIDES_TOOLS)


def test_root_register_reports_identity_and_matches_registrations() -> None:
    ctx = RecordingContext()
    summary = _load_root_entrypoint().register(ctx)
    assert summary == {"plugin": PLUGIN_ID, "version": __version__, "tools": list(PROVIDES_TOOLS)}
    assert ctx.tools == list(PROVIDES_TOOLS)


def test_register_rejects_missing_context() -> None:
    with pytest.raises(TypeError, match="PluginContext"):
        register_plugin(None)


def test_cli_version_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"{PLUGIN_ID} {__version__}"
    assert main([]) == 0
    assert "usage:" in capsys.readouterr().out


def test_vm_is_lua_5_1_and_runs_a_chunk() -> None:
    runtime = new_runtime()
    assert lua_version(runtime) == "Lua 5.1"
    assert runtime.eval("(function(a, b) return a * b end)(6, 7)") == 42


def test_vm_rejects_syntax_newer_than_5_1_with_file_and_line() -> None:
    runtime = new_runtime()
    message = check_syntax(runtime, "local a = 1\nlocal b = 7 // 2\n", "Core/Bad.lua")
    assert message is not None and message.startswith("Core/Bad.lua:2:")
    assert check_syntax(runtime, "local a = 1\nreturn a\n", "Core/Good.lua") is None


def test_sandbox_matches_what_the_game_exposes() -> None:
    runtime = new_runtime()
    for missing in ("io", "os", "package", "require", "dofile", "loadfile", "debug", "python"):
        assert runtime.eval(missing) is None, missing
    for present in ("date", "time", "difftime", "debugstack", "loadstring", "setfenv"):
        assert runtime.eval(f"type({present})") == "function", present


def test_unsandboxed_runtime_keeps_the_host_libraries() -> None:
    runtime = new_runtime(sandbox=False)
    assert runtime.eval("type(string.dump)") == "function"
    assert runtime.eval("type(os)") == "table"
