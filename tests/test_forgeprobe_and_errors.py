"""T-009 acceptance tests for ForgeProbe and ``wow_errors`` (created 2026-11-11).

Hermetic by construction: addon files live only in a ``FakeFileSystem`` from
``fake_fs_factory``, the API index is saved through ``IndexStore(tmp_path)``,
and the repo's real ``addons/ForgeProbe`` is read only as fixture source or
checked directly (as ``test_check`` does for Guildhall). No test touches a
real WoW install or ``~/.hermes``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from wow_addon_forge import PROVIDES_TOOLS
from wow_addon_forge.apidocs import IndexStore
from wow_addon_forge.check import check_addon
from wow_addon_forge.headless import (
    SimulatedClient,
    World,
    format_saved_variables_lua,
    minimal_api_index,
)
from wow_addon_forge.luavm import LuaVMUnavailableError
from wow_addon_forge.savedvars import (
    SavedVarsReadError,
    parse_savedvars_lua,
    read_forge_probe_errors,
    read_savedvars,
    select_dotted_path,
)
from wow_addon_forge.tools import WOW_ERRORS_SCHEMA, ForgeTools, register_tools

REPO = Path(__file__).resolve().parent.parent
# [2026-11-11 T-009] Same fake macOS root as tests/conftest.py MAC_ROOT; it
# exists only as FakeFileSystem dict keys, never as a real install.
MAC_ROOT = "/Applications/World of Warcraft"
FORGE_DIR = "/addons/ForgeProbe"
BUGGY_DIR = "/addons/BuggyAddon"


def _forgeprobe_files() -> dict[str, str]:
    # [2026-11-11 T-009] The shipped addon is the fixture: reading its real
    # TOC/Lua from the repo into the fake FS proves the headless scenarios run
    # the exact code players install, not a copy that can drift.
    base = REPO / "addons" / "ForgeProbe"
    return {
        f"{FORGE_DIR}/ForgeProbe.toc": (base / "ForgeProbe.toc").read_text(encoding="utf-8"),
        f"{FORGE_DIR}/Core.lua": (base / "Core.lua").read_text(encoding="utf-8"),
    }


# [2026-11-11 T-009] The runtime error hides inside a helper so the captured
# stack must name BuggyAddon/Core.lua at the helper, proving attribution is
# not just reading the first line of the OnEvent frame.
_BUGGY_CORE = (
    "local function explode()\n"
    '    error("buggy-login-boom")\n'
    "end\n"
    'local frame = CreateFrame("Frame")\n'
    'frame:RegisterEvent("PLAYER_LOGIN")\n'
    'frame:SetScript("OnEvent", function(self, event)\n'
    '    if event == "PLAYER_LOGIN" then explode() end\n'
    "end)\n"
)


def _buggy_files() -> dict[str, str]:
    return {
        f"{BUGGY_DIR}/BuggyAddon.toc": "## Interface: 16001\n## Title: BuggyAddon\n\nCore.lua\n",
        f"{BUGGY_DIR}/Core.lua": _BUGGY_CORE,
    }


def _probe_world(fake_fs_factory: Any, *, rank: int | None = 2) -> tuple[World, SimulatedClient]:
    world = World(fs=fake_fs_factory(_forgeprobe_files()))
    client = world.client("Alice", rank=rank)
    client.load_addon(FORGE_DIR)
    return world, client


def _probe_db(client: SimulatedClient) -> dict[str, Any]:
    client.flush_saved_variables()
    db: dict[str, Any] = client.account_saved_variables["ForgeProbeDB"]
    return db


def _chat_text(client: SimulatedClient) -> str:
    return str(client.run_lua('table.concat(DEFAULT_CHAT_FRAME.messages, "\\n")'))


def test_forgeprobe_passes_wow_check_via_tool_and_directly(tmp_path: Path) -> None:
    # [2026-11-11 T-009] Saving through IndexStore(tmp_path) proves handle_check
    # loads the index from cache_dir exactly as production does, hermetically.
    IndexStore(tmp_path).save(minimal_api_index().data)
    tools = ForgeTools(cache_dir=tmp_path)
    payload: dict[str, Any] = json.loads(
        tools.handle_check({"path": str(REPO / "addons" / "ForgeProbe")})
    )
    assert payload["ok"] is True
    assert payload["verdict"] == "pass"
    assert payload["error_count"] == 0
    assert payload["warning_count"] == 0
    assert payload["findings"] == []
    # [2026-11-11 T-009] check_addon directly must agree, so the tool handler
    # is a thin envelope over the pipeline rather than a second pipeline.
    direct = check_addon(str(REPO / "addons" / "ForgeProbe"), index=minimal_api_index())
    assert direct["verdict"] == "pass"
    assert direct["error_count"] == 0
    assert direct["warning_count"] == 0
    assert direct["findings"] == []


def test_ingame_checklist_section_a_still_not_run() -> None:
    lines = (REPO / "docs" / "INGAME-CHECKLIST.md").read_text(encoding="utf-8").splitlines()
    # [2026-11-11 T-009] Lines 10-23 are section A (items 1-5): a headless
    # pass must never be recorded there, so all five stay NOT RUN.
    section_a = "\n".join(lines[9:23])
    assert section_a.count("Result: NOT RUN") == 5


def test_buggy_addon_error_lands_in_forgeprobe_ring_via_wow_errors(
    fake_fs_factory: Any,
) -> None:
    files = {**_forgeprobe_files(), **_buggy_files()}
    world = World(fs=fake_fs_factory(files))
    client = world.client("Alice")
    # [2026-11-11 T-009] ForgeProbe loads first with login=False so its
    # seterrorhandler hook is installed before BuggyAddon's PLAYER_LOGIN
    # error fires during the second addon's login.
    client.load_addon(FORGE_DIR, login=False)
    client.load_addon(BUGGY_DIR, login=True)
    # Second identical login error: deduplication must fold it into count.
    client.fire("PLAYER_LOGIN")
    client.fire("ADDON_ACTION_FORBIDDEN", "BuggyAddon", "SendChatMessage()")
    # [2026-11-11 T-009] reload() flushes ForgeProbeDB before replaying the
    # addons, so account_saved_variables holds the pre-reload ring (count 2)
    # even though the replay's login raises the error a third time in-VM.
    client.reload()
    saved_text = format_saved_variables_lua(
        {"ForgeProbeDB": client.account_saved_variables["ForgeProbeDB"]}
    )
    sv_path = f"{MAC_ROOT}/_forever_/WTF/Account/ACC1/SavedVariables/ForgeProbe.lua"
    tools = ForgeTools(fs=fake_fs_factory({sv_path: saved_text}), default_roots=[MAC_ROOT])
    payload: dict[str, Any] = json.loads(tools.handle_errors({}))
    assert payload["ok"] is True
    buggy = [e for e in payload["errors"] if "buggy-login-boom" in e["message"]]
    assert len(buggy) == 1
    entry = buggy[0]
    assert entry["addon"] == "BuggyAddon"
    # Non-empty stack naming the raising addon proves helper-level capture.
    assert entry["stack"] and "BuggyAddon" in entry["stack"]
    assert entry["count"] == 2
    assert entry["time"] > 0
    forbidden = [e for e in payload["errors"] if "ADDON_ACTION_FORBIDDEN" in e["message"]]
    assert len(forbidden) == 1
    assert forbidden[0]["addon"] == "BuggyAddon"
    assert "SendChatMessage()" in forbidden[0]["message"]
    # [2026-11-11 T-009] The addon filter is exact: BuggyAddon keeps both
    # entries, an unrelated name keeps none but total_captured is unfiltered.
    only: dict[str, Any] = json.loads(tools.handle_errors({"addon": "BuggyAddon"}))
    assert only["error_count"] == 2
    assert all(e["addon"] == "BuggyAddon" for e in only["errors"])
    other: dict[str, Any] = json.loads(tools.handle_errors({"addon": "Other"}))
    assert other["errors"] == [] and other["error_count"] == 0
    assert other["total_captured"] == 2


def test_error_ring_caps_at_200_and_drops_oldest(fake_fs_factory: Any) -> None:
    _world, client = _probe_world(fake_fs_factory)
    # [2026-11-11 T-009] Driving geterrorhandler() directly feeds 205 unique
    # (addon, message) pairs through ForgeProbe's own hook, so the cap is
    # proven at the recordError boundary, not by pre-filling the table.
    client.run_lua(
        'for i = 1, 205 do geterrorhandler()("BuggyAddon/Core.lua:1: unique-error-" .. i) end'
    )
    errors = _probe_db(client)["errors"]
    assert len(errors) == 200
    messages = {e["message"] for e in errors}
    assert "BuggyAddon/Core.lua:1: unique-error-1" not in messages
    assert "BuggyAddon/Core.lua:1: unique-error-6" in messages
    assert errors[0]["message"] == "BuggyAddon/Core.lua:1: unique-error-6"
    assert errors[-1]["message"] == "BuggyAddon/Core.lua:1: unique-error-205"


def test_forge_probe_slash_reports_build_events_apis_and_echo(
    fake_fs_factory: Any,
) -> None:
    world, client = _probe_world(fake_fs_factory)
    assert client.slash("/forge probe") is True
    assert "probe complete" in _chat_text(client)
    world.advance(1.0)
    probe = _probe_db(client)["probe"]
    assert probe["build"]["version"] == "1.60.1"
    assert probe["build"]["interface"] == 16001
    for event in ("ENCOUNTER_END", "BOSS_KILL", "GROUP_ROSTER_UPDATE", "CHAT_MSG_ADDON"):
        assert probe["events"][event]["valid"] is True, event
        assert probe["events"][event]["registered"] is True, event
    # [2026-11-11 T-009] PARTY_KILL/UNIT_DIED are absent from minimal_api_index,
    # so valid/registered False proves the probe records absence as data.
    for event in ("PARTY_KILL", "UNIT_DIED"):
        assert probe["events"][event]["valid"] is False, event
        assert probe["events"][event]["registered"] is False, event
    assert probe["apis"]["C_ChatInfo.SendAddonMessage"] is True
    assert probe["apis"]["C_Item.GetItemInfo"] is True
    assert probe["restrictions"]["Combat"] == {"active": False, "state": 0}
    # [2026-11-11 T-009] Guilded + unrestricted: the GUILD echo must come back
    # to the sender herself, in canonical Name-Realm form.
    echo = probe["echo"]
    assert echo["sent"] is True
    assert echo["send_result"] == 0
    assert echo["echo_received"] is True
    assert echo["echo_sender"] == "Alice-Forever"


def test_probe_does_not_auto_run_at_login(fake_fs_factory: Any) -> None:
    # [2026-11-11 T-052] Regression for the live T-035 finding: the login
    # auto-probe's protected RegisterEvent attempts popped a Blizzard-UI
    # modal on every login. The probe must exist only after /forge probe.
    _world, client = _probe_world(fake_fs_factory)
    # ensureDB() creates an empty probe table at load; probed_at is the
    # field only RunProbe writes, so it is the honest "did it run" signal.
    assert client.run_lua("return ForgeProbeDB.probe.probed_at") is None
    assert client.slash("/forge probe") is True
    assert isinstance(client.run_lua("return ForgeProbeDB.probe.probed_at"), (int, float))


def test_forge_probe_restricted_and_unguilded_skip_echo(fake_fs_factory: Any) -> None:
    _world, client = _probe_world(fake_fs_factory)
    client.set_restriction("Combat", True)
    assert client.slash("/forge probe") is True
    probe = _probe_db(client)["probe"]
    # [2026-11-11 T-009] RestrictionState Active is 2; the probe must report
    # the regime and refuse the echo send instead of eating a lockdown error.
    assert probe["restrictions"]["Combat"] == {"active": True, "state": 2}
    assert probe["echo"]["skipped_reason"] == "restricted"
    assert probe["echo"]["sent"] is False

    _w2, solo = _probe_world(fake_fs_factory, rank=None)
    assert solo.slash("/forge probe") is True
    solo_probe = _probe_db(solo)["probe"]
    assert solo_probe["echo"]["skipped_reason"] == "not-in-guild"
    assert solo_probe["echo"]["sent"] is False


def test_forge_status_and_clear_slash_commands(fake_fs_factory: Any) -> None:
    _world, client = _probe_world(fake_fs_factory)
    client.run_lua('geterrorhandler()("BuggyAddon/Core.lua:9: one-off")')
    assert client.slash("/forge") is True
    assert "1 error(s) captured" in _chat_text(client)
    assert client.slash("/forge clear") is True
    assert "cleared captured errors" in _chat_text(client)
    # [2026-11-11 T-009] wipe() empties the ring in place; the exported empty
    # Lua table is falsy ({}), which is the observable post-clear state.
    assert not _probe_db(client)["errors"]


# [2026-11-11 T-009] One fixture exercises every literal shape the real client
# writes: nested tables, a [[long string]] spanning lines, and negatives.
_NESTED_SV = (
    "MyDB = {\n"
    '    ["nested"] = { ["deep"] = "value", ["neg"] = -42, ["frac"] = -3.5 },\n'
    '    ["note"] = [[line one\nline two]],\n'
    '    ["list"] = { 10, 20, 30 },\n'
    "}\n"
)


def test_parse_savedvars_nested_long_string_negatives_and_bom() -> None:
    data = parse_savedvars_lua("\ufeff" + _NESTED_SV)
    # [2026-11-11 T-009] -42.0 == -42 in Python, so these hold whether
    # lua_to_python folds integral doubles to int or leaves them float.
    assert data["MyDB"]["nested"]["deep"] == "value"
    assert data["MyDB"]["nested"]["neg"] == -42
    assert data["MyDB"]["nested"]["frac"] == -3.5
    assert data["MyDB"]["note"] == "line one\nline two"
    assert data["MyDB"]["list"] == [10, 20, 30]
    assert parse_savedvars_lua("") == {}


def test_select_dotted_path_keys_indices_and_missing() -> None:
    data = parse_savedvars_lua(_NESTED_SV)
    assert select_dotted_path(data, "MyDB.nested.deep") == "value"
    # [2026-11-11 T-009] Indices are 0-based JSON positions, not Lua 1-based:
    # segment "1" must land on the second list element the caller sees.
    assert select_dotted_path(data, "MyDB.list.1") == 20
    assert select_dotted_path(data, None) == data
    assert select_dotted_path(data, "") == data
    with pytest.raises(SavedVarsReadError) as excinfo:
        select_dotted_path(data, "MyDB.nope.deep")
    assert excinfo.value.code == "path-not-found"
    with pytest.raises(SavedVarsReadError) as excinfo:
        select_dotted_path(data, "MyDB.list.9")
    assert excinfo.value.code == "path-not-found"


def test_parse_savedvars_rejects_calls_and_syntax_errors() -> None:
    # [2026-11-11 T-009] The empty function environment is the safety story:
    # os.execute and a bare foo() must fail as data, never execute.
    for hostile in ('X = os.execute("x")\n', "foo()\n", "X = {\n"):
        with pytest.raises(SavedVarsReadError) as excinfo:
            parse_savedvars_lua(hostile)
        assert excinfo.value.code == "bad-savedvars", hostile


def _savedvars_files() -> dict[str, str]:
    account = f"{MAC_ROOT}/_forever_/WTF/Account/ACC1"
    return {
        f"{account}/SavedVariables/Guildhall.lua": 'GuildhallDB = { ["marker"] = "account" }\n',
        f"{account}/Forever/Alice/SavedVariables/Guildhall.lua": (
            'GuildhallDB = { ["marker"] = "char" }\n'
        ),
    }


def test_read_savedvars_account_wide_and_per_character(fake_fs_factory: Any) -> None:
    fs = fake_fs_factory(_savedvars_files())
    wide = read_savedvars(fs, addon="Guildhall", roots=[MAC_ROOT])
    assert wide["scope"] == "account" and wide["flavor"] == "_forever_"
    assert wide["data"]["GuildhallDB"]["marker"] == "account"
    # [2026-11-11 T-009] Whitespace is not a character name: same account-wide file, scope account.
    blank = read_savedvars(fs, addon="Guildhall", roots=[MAC_ROOT], character="   ")
    assert blank["scope"] == "account"
    assert blank["data"]["GuildhallDB"]["marker"] == "account"
    # [2026-11-11 T-009] All three character spellings name the same on-disk
    # <account>/Forever/Alice/ folder and must not fall back to account data.
    for spelling in ("Forever/Alice", "Alice-Forever", "Alice"):
        char = read_savedvars(fs, addon="Guildhall", roots=[MAC_ROOT], character=spelling)
        assert char["scope"] == "character", spelling
        assert char["data"]["GuildhallDB"]["marker"] == "char", spelling
    picked = read_savedvars(fs, addon="Guildhall", roots=[MAC_ROOT], dotted_path="GuildhallDB")
    assert picked["data"] == {"marker": "account"}


_FORGE_SV = 'ForgeProbeDB = { ["errors"] = {}, ["probe"] = {} }\n'


def test_ambiguous_account_never_leaks_names_and_case_insensitive_pick(
    fake_fs_factory: Any,
) -> None:
    base = f"{MAC_ROOT}/_forever_/WTF/Account"
    files = {
        f"{base}/ACC1/SavedVariables/ForgeProbe.lua": _FORGE_SV,
        f"{base}/ACC2/SavedVariables/ForgeProbe.lua": _FORGE_SV,
    }
    fs = fake_fs_factory(files)
    with pytest.raises(SavedVarsReadError) as excinfo:
        read_forge_probe_errors(fs, roots=[MAC_ROOT])
    assert excinfo.value.code == "ambiguous-account"
    # [2026-11-11 T-009] Account folder names are personal data: the error
    # may carry a count but neither raw name may appear in the message.
    assert "ACC1" not in excinfo.value.message
    assert "ACC2" not in excinfo.value.message
    picked = read_forge_probe_errors(fs, roots=[MAC_ROOT], account="acc1")
    assert picked["flavor"] == "_forever_"
    assert picked["errors"] == [] and picked["total_captured"] == 0


def test_no_install_no_savedvars_and_bad_argument_names(fake_fs_factory: Any) -> None:
    with pytest.raises(SavedVarsReadError) as excinfo:
        read_forge_probe_errors(fake_fs_factory({}), roots=[MAC_ROOT])
    assert excinfo.value.code == "no-install"
    files = {f"{MAC_ROOT}/_forever_/WTF/Account/ACC1/SavedVariables/Other.lua": "OtherDB = {}\n"}
    with pytest.raises(SavedVarsReadError) as excinfo:
        read_forge_probe_errors(fake_fs_factory(files), roots=[MAC_ROOT])
    assert excinfo.value.code == "no-savedvars"
    fs = fake_fs_factory(_savedvars_files())
    # [2026-11-11 T-009] Traversal in any of the three name slots is refused
    # before any path is built, not merely normalised away by the filesystem.
    bad_calls: tuple[dict[str, Any], ...] = (
        {"addon": "../evil"},
        {"addon": "Guildhall", "account": "../ACC1"},
        {"addon": "Guildhall", "character": "a/b/c"},
        {"addon": "Guildhall", "character": "..\\Alice"},
    )
    for kwargs in bad_calls:
        with pytest.raises(SavedVarsReadError) as excinfo:
            read_savedvars(fs, roots=[MAC_ROOT], **kwargs)
        assert excinfo.value.code == "bad-argument", kwargs


class _RecordingContext:
    """Stand-in for the Hermes PluginContext: records every register_tool call."""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []

    def register_tool(self, name: str, **kwargs: Any) -> None:
        self.tools.append({"name": name, **kwargs})


def test_wow_errors_registration_and_error_boundaries(
    fake_fs_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = ForgeTools(fs=fake_fs_factory({}), default_roots=[MAC_ROOT])
    ctx = _RecordingContext()
    registered = register_tools(ctx, tools=tools)
    assert registered == list(PROVIDES_TOOLS)
    assert "wow_errors" in registered
    errors_tool = next(item for item in ctx.tools if item["name"] == "wow_errors")
    assert errors_tool["schema"] is WOW_ERRORS_SCHEMA
    assert errors_tool["schema"]["name"] == "wow_errors"
    assert errors_tool["check_fn"]() is True
    # [2026-11-11 T-009] Registration wires the real handler: the recorded
    # handler answers (no-install on the empty fake FS) instead of raising.
    wired: dict[str, Any] = json.loads(errors_tool["handler"]({}))
    assert wired["ok"] is False and wired["error"]["code"] == "no-install"
    for bad_args in ("nope", {"addon": 123}, {"account": "../ACC1"}):
        payload: dict[str, Any] = json.loads(tools.handle_errors(bad_args))
        assert payload["ok"] is False, bad_args
        assert payload["error"]["code"] == "bad-argument", bad_args

    def raise_vm(*_args: Any, **_kwargs: Any) -> Any:
        raise LuaVMUnavailableError("no Lua VM here")

    monkeypatch.setattr("wow_addon_forge.tools.read_forge_probe_errors", raise_vm)
    payload = json.loads(tools.handle_errors({}))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "lua-vm-unavailable"
    assert "no Lua VM here" in payload["error"]["message"]
