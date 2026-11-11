"""T-013 acceptance tests for the skill, /wow, and the CLI (created 2026-11-11).

The fake install lives under ``tmp_path``. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import forever_install_files

from wow_addon_forge import register_plugin
from wow_addon_forge.__main__ import main
from wow_addon_forge.apidocs import IndexStore
from wow_addon_forge.cli import (
    SKILL_DESCRIPTION,
    SKILL_NAME,
    handle_slash,
    handle_wow_cli,
    skill_path,
)
from wow_addon_forge.env import RealFileSystem
from wow_addon_forge.headless import minimal_api_index
from wow_addon_forge.tools import ForgeTools, register_tools


class _Ctx:
    def __init__(self) -> None:
        self.tools: list[str] = []
        self.skills: list[dict[str, Any]] = []
        self.commands: list[str] = []
        self.cli: list[str] = []

    def register_tool(self, *, name: str, **_: Any) -> None:
        self.tools.append(name)

    def register_skill(self, name: str, path: Path, description: str = "") -> None:
        self.skills.append({"name": name, "path": Path(path), "description": description})

    def register_command(self, name: str, **_: Any) -> None:
        self.commands.append(name)

    def register_cli_command(self, name: str, **_: Any) -> None:
        self.cli.append(name)


def _tools(tmp_path: Path) -> ForgeTools:
    root = tmp_path / "WoW"
    for path, text in forever_install_files(str(root)).items():
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    IndexStore(tmp_path / "index").save(minimal_api_index().data)
    return ForgeTools(
        fs=RealFileSystem(),
        default_roots=[str(root)],
        cache_dir=tmp_path / "index",
    )


def _assert_status(text: str, root: Path) -> None:
    assert "install:" in text
    assert str(root) in text
    assert "_forever_" in text
    assert "build: 1.60.1.70888" in text
    assert "index:" in text
    assert "1.60.1.70888" in text.split("index:", 1)[1]


def test_skill_frontmatter_is_registered() -> None:
    raw = skill_path().read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    frontmatter = yaml.safe_load(raw.split("---", 2)[1])
    assert frontmatter["name"] == SKILL_NAME
    assert frontmatter["description"] == SKILL_DESCRIPTION
    assert len(frontmatter["description"]) <= 60
    ctx = _Ctx()
    register_plugin(ctx)
    assert ctx.skills[0]["name"] == SKILL_NAME
    assert ctx.skills[0]["path"] == skill_path()
    assert "wow" in ctx.commands
    assert "wow" in ctx.cli
    assert register_tools(ctx)  # tools still register on the same context


def test_slash_and_cli_status_print_fake_install(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = _tools(tmp_path)
    root = tmp_path / "WoW"
    slash = handle_slash("status", tools=tools)
    _assert_status(slash, root)
    assert main(["status"], tools=tools) == 0
    _assert_status(capsys.readouterr().out, root)
    namespace = argparse.Namespace(wow_verb="status", path=None)
    assert handle_wow_cli(namespace, tools=tools) == 0
    _assert_status(capsys.readouterr().out, root)


def test_cli_check_exits_nonzero_on_fail(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    bad = tmp_path / "BadAddon"
    bad.mkdir()
    (bad / "BadAddon.toc").write_text(
        "## Interface: 16001\n## Title: Bad\n\nMissing.lua\n",
        encoding="utf-8",
    )
    code = main(["check", str(bad)], tools=tools)
    assert code != 0
