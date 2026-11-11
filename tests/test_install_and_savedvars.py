"""T-010 acceptance tests for ``wow_savedvars`` and ``wow_install`` (created 2026-11-11).

The install lives under ``tmp_path``. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wow_addon_forge.apidocs import IndexStore
from wow_addon_forge.env import RealFileSystem
from wow_addon_forge.headless import minimal_api_index
from wow_addon_forge.tools import ForgeTools

_CLEAN_TOC = "## Interface: 16001\n## Title: Clean\n\nCore.lua\n"
_CLEAN_LUA = "local ready = true\n"
_EXTRA_TOC = "## Interface: 16001\n## Title: Clean\n\nCore.lua\nExtra.lua\n"
_FAIL_LUA = "goto not_lua_51\n"
_NESTED = (
    "CleanDB = {\n"
    '  ["nested"] = { ["deep"] = "value", ["neg"] = -42 },\n'
    '  ["note"] = [[line one\nline two]],\n'
    "}\n"
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _wow(tmp_path: Path) -> Path:
    root = tmp_path / "WoW"
    (root / "_forever_" / "Interface" / "AddOns").mkdir(parents=True)
    return root


def _clean(tmp_path: Path, lua: str = _CLEAN_LUA, toc: str = _CLEAN_TOC) -> Path:
    addon = tmp_path / "src" / "Clean"
    _write(addon / "Clean.toc", toc)
    _write(addon / "Core.lua", lua)
    if "Extra.lua" in toc:
        _write(addon / "Extra.lua", "local extra = 1\n")
    return addon


def _tools(tmp_path: Path, wow: Path) -> ForgeTools:
    IndexStore(tmp_path / "index").save(minimal_api_index().data)
    return ForgeTools(
        fs=RealFileSystem(),
        default_roots=[str(wow)],
        cache_dir=tmp_path / "index",
        data_dir=tmp_path / "backups",
        clock=lambda: 1_700_000_000.0,
    )


def _install(tools: ForgeTools, **kwargs: Any) -> dict[str, Any]:
    return json.loads(tools.handle_install(kwargs))


def test_savedvars_nested_long_string_negative_and_dotted_path(tmp_path: Path) -> None:
    wow = _wow(tmp_path)
    saved = wow / "_forever_" / "WTF" / "Account" / "ACC1" / "SavedVariables" / "Clean.lua"
    _write(saved, _NESTED)
    tools = _tools(tmp_path, wow)
    payload = json.loads(tools.handle_savedvars({"addon": "Clean"}))
    assert payload["ok"] is True
    assert payload["scope"] == "account"
    assert payload["data"]["CleanDB"]["nested"]["neg"] == -42
    assert payload["data"]["CleanDB"]["note"] == "line one\nline two"
    # [2026-11-11 T-010] The account folder name is personal data and must not leak.
    assert "ACC1" not in json.dumps(payload)
    picked = json.loads(tools.handle_savedvars({"addon": "Clean", "path": "CleanDB.nested.deep"}))
    assert picked["ok"] is True
    assert picked["data"] == "value"


def test_install_copies_new_addon_and_reports_restart(tmp_path: Path) -> None:
    wow = _wow(tmp_path)
    source = _clean(tmp_path)
    tools = _tools(tmp_path, wow)
    payload = _install(tools, path=str(source))
    assert payload["ok"] is True
    assert payload["action"] == "restart"
    assert payload["dry_run"] is False
    assert payload["backup"] is None
    assert payload["forced"] is False
    dest = Path(payload["dest"])
    assert dest == wow / "_forever_" / "Interface" / "AddOns" / "Clean"
    assert (dest / "Core.lua").read_text(encoding="utf-8") == _CLEAN_LUA
    assert not str(payload["dest"]).startswith(str(tmp_path / "backups"))


def test_install_backs_up_outside_the_game_and_reports_reload(tmp_path: Path) -> None:
    wow = _wow(tmp_path)
    dest_dir = wow / "_forever_" / "Interface" / "AddOns" / "Clean"
    _write(dest_dir / "Clean.toc", _CLEAN_TOC)
    _write(dest_dir / "Core.lua", "local old = true\n")
    source = _clean(tmp_path)
    tools = _tools(tmp_path, wow)
    before = (dest_dir / "Core.lua").read_text(encoding="utf-8")
    payload = _install(tools, path=str(source))
    assert payload["ok"] is True
    assert payload["action"] == "reload"
    backup = Path(payload["backup"])
    assert backup == tmp_path / "backups" / "Clean-1700000000"
    assert wow not in backup.parents or backup.is_relative_to(tmp_path / "backups")
    assert not str(backup).startswith(str(wow))
    assert (backup / "Core.lua").read_text(encoding="utf-8") == before
    assert (dest_dir / "Core.lua").read_text(encoding="utf-8") == _CLEAN_LUA


def test_install_reports_restart_when_the_toc_gains_a_file(tmp_path: Path) -> None:
    wow = _wow(tmp_path)
    dest_dir = wow / "_forever_" / "Interface" / "AddOns" / "Clean"
    _write(dest_dir / "Clean.toc", _CLEAN_TOC)
    _write(dest_dir / "Core.lua", _CLEAN_LUA)
    source = _clean(tmp_path, toc=_EXTRA_TOC)
    payload = _install(_tools(tmp_path, wow), path=str(source))
    assert payload["ok"] is True
    assert payload["action"] == "restart"
    assert "Extra.lua" in payload["note"]


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    wow = _wow(tmp_path)
    source = _clean(tmp_path)
    addons = wow / "_forever_" / "Interface" / "AddOns"
    before = sorted(p.name for p in addons.iterdir())
    payload = _install(_tools(tmp_path, wow), path=str(source), dry_run=True)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["action"] == "restart"
    assert payload["backup"] is None
    assert sorted(p.name for p in addons.iterdir()) == before
    assert not (tmp_path / "backups").exists()


def test_failed_check_refuses_unless_force(tmp_path: Path) -> None:
    wow = _wow(tmp_path)
    source = _clean(tmp_path, lua=_FAIL_LUA)
    addons = wow / "_forever_" / "Interface" / "AddOns"
    tools = _tools(tmp_path, wow)
    refused = _install(tools, path=str(source))
    assert refused["ok"] is False
    assert refused["error"]["code"] == "check-failed"
    assert list(addons.iterdir()) == []
    forced = _install(tools, path=str(source), force=True)
    assert forced["ok"] is True
    assert forced["forced"] is True
    assert forced["check_verdict"] == "fail"
    assert (addons / "Clean" / "Core.lua").is_file()


def test_install_refuses_traversal_and_absolute_names(tmp_path: Path) -> None:
    wow = _wow(tmp_path)
    tools = _tools(tmp_path, wow)
    addons = wow / "_forever_" / "Interface" / "AddOns"
    for hostile in ("../Evil", str(tmp_path / ".." / "Evil"), str(tmp_path / "src" / "C:Evil")):
        payload = _install(tools, path=hostile)
        assert payload["ok"] is False, hostile
        assert payload["error"]["code"] == "bad-argument", hostile
    assert list(addons.iterdir()) == []


def test_link_mode_symlinks_and_second_install_does_not_delete_source(tmp_path: Path) -> None:
    wow = _wow(tmp_path)
    source = _clean(tmp_path)
    tools = _tools(tmp_path, wow)
    linked = _install(tools, path=str(source), mode="link")
    assert linked["ok"] is True
    dest = Path(linked["dest"])
    assert dest.is_symlink()
    assert dest.resolve() == source.resolve()
    # [2026-11-11 T-010] Replacing the link must unlink it, not rmtree the source.
    copied = _clean(tmp_path / "other")
    replaced = _install(tools, path=str(copied), mode="copy")
    assert replaced["ok"] is True
    assert source.is_dir()
    assert (source / "Core.lua").is_file()
    assert not dest.is_symlink()
    assert (dest / "Core.lua").read_text(encoding="utf-8") == _CLEAN_LUA
