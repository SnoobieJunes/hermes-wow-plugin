"""T-012 acceptance tests for ``wow_bridge`` (created 2026-11-11).

The install lives under ``tmp_path``. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from wow_addon_forge.__main__ import main
from wow_addon_forge.env import RealFileSystem
from wow_addon_forge.luavm import check_syntax, new_runtime
from wow_addon_forge.savedvars import parse_savedvars_lua
from wow_addon_forge.tools import ForgeTools

_TOC = "## Interface: 16001\n## Title: Guildhall\n## X-Forge-Bridge: 1\n\nInbox.lua\n"
_PLAIN_TOC = "## Interface: 16001\n## Title: Plain\n\nCore.lua\n"
_SAVED = (
    "GuildhallDB = {\n"
    '  ["outbox"] = {\n'
    '    { ["id"] = 1, ["t"] = 10, ["kind"] = "post", ["text"] = "hello" },\n'
    '    { ["id"] = 2, ["t"] = 11, ["kind"] = "event", ["text"] = "raid night" },\n'
    "  },\n"
    '  ["inbox_seen"] = { 1 },\n'
    "}\n"
)
_INBOX = (
    "Guildhall_Inbox = {\n"
    '  { ["id"] = 1, ["kind"] = "post", ["via"] = "discord" },\n'
    '  { ["id"] = 2, ["kind"] = "post", ["via"] = "discord" },\n'
    "}\n"
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _layout(tmp_path: Path) -> Path:
    wow = tmp_path / "WoW"
    addon = wow / "_forever_" / "Interface" / "AddOns" / "Guildhall"
    _write(addon / "Guildhall.toc", _TOC)
    _write(addon / "Inbox.lua", _INBOX)
    _write(addon / "Core.lua", "local untouched = true\n")
    saved = wow / "_forever_" / "WTF" / "Account" / "ACC1" / "SavedVariables" / "Guildhall.lua"
    _write(saved, _SAVED)
    plain = wow / "_forever_" / "Interface" / "AddOns" / "Plain"
    _write(plain / "Plain.toc", _PLAIN_TOC)
    _write(plain / "Core.lua", "local plain = true\n")
    return wow


def _tools(tmp_path: Path, wow: Path) -> ForgeTools:
    return ForgeTools(
        fs=RealFileSystem(),
        default_roots=[str(wow)],
        cursor_dir=tmp_path / "cursors",
    )


def test_pull_returns_past_cursor_then_nothing(tmp_path: Path) -> None:
    wow = _layout(tmp_path)
    tools = _tools(tmp_path, wow)
    first = json.loads(tools.handle_bridge({"action": "pull", "addon": "Guildhall"}))
    assert first["ok"] is True
    assert [record["id"] for record in first["records"]] == [1, 2]
    assert first["cursor"] == 2
    cursor_file = tmp_path / "cursors" / "Guildhall.json"
    assert cursor_file.is_file()
    assert not str(cursor_file).startswith(str(wow))
    second = json.loads(tools.handle_bridge({"action": "pull", "addon": "Guildhall"}))
    assert second["ok"] is True
    assert second["records"] == []
    assert second["cursor"] == 2


def test_discord_cli_prints_one_line_per_record_then_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wow = _layout(tmp_path)
    tools = _tools(tmp_path, wow)
    assert main(["bridge", "pull", "--format", "discord"], tools=tools) == 0
    assert capsys.readouterr().out == "[post] hello\n[event] raid night\n"
    assert main(["bridge", "pull", "--format", "discord"], tools=tools) == 0
    assert capsys.readouterr().out == ""


def test_push_keeps_unconsumed_items_and_compiles(tmp_path: Path) -> None:
    wow = _layout(tmp_path)
    tools = _tools(tmp_path, wow)
    core = wow / "_forever_" / "Interface" / "AddOns" / "Guildhall" / "Core.lua"
    before = core.read_text(encoding="utf-8")
    payload = json.loads(
        tools.handle_bridge(
            {
                "action": "push",
                "addon": "Guildhall",
                "records": [{"id": 3, "t": 12, "kind": "post", "data": {"n": 1}, "via": "discord"}],
            }
        )
    )
    assert payload["ok"] is True
    assert payload["kept"] == 1
    assert payload["added"] == 1
    assert payload["dropped_consumed"] == 1
    inbox = Path(payload["path"])
    assert inbox.name == "Inbox.lua"
    text = inbox.read_text(encoding="utf-8")
    assert check_syntax(new_runtime(sandbox=True), text, "Inbox.lua") is None
    parsed = parse_savedvars_lua(text)
    ids = [item["id"] for item in parsed["Guildhall_Inbox"]]
    assert ids == [2, 3]
    assert core.read_text(encoding="utf-8") == before


def test_push_refuses_an_addon_without_the_bridge_header(tmp_path: Path) -> None:
    wow = _layout(tmp_path)
    tools = _tools(tmp_path, wow)
    payload: dict[str, Any] = json.loads(
        tools.handle_bridge({"action": "push", "addon": "Plain", "records": [{"id": 1}]})
    )
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bridge-disabled"
    plain = wow / "_forever_" / "Interface" / "AddOns" / "Plain"
    assert not (plain / "Inbox.lua").exists()
