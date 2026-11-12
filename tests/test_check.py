"""T-008 acceptance tests for ``wow_check`` / ``wow_test`` (created 2026-11-11).

Hermetic by construction: addon files live only in a ``FakeFileSystem`` from
``fake_fs_factory`` and the API index is saved through ``IndexStore(tmp_path)``,
so no test touches the network or ``~/.hermes`` (the repo's real
``addons/Guildhall`` is the one read-only exception). Line assertions are
exact: fixture Lua is numbered, so a finding's ``file``/``line`` pair proves
which stage reported which source line.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from wow_addon_forge import PROVIDES_TOOLS
from wow_addon_forge.apidocs import ApiIndex, IndexStore
from wow_addon_forge.check import check_addon, run_addon_tests
from wow_addon_forge.headless import minimal_api_index
from wow_addon_forge.luavm import LuaVMUnavailableError
from wow_addon_forge.tools import ForgeTools, register_tools

REPO = Path(__file__).resolve().parent.parent


def _index() -> ApiIndex:
    # [2026-11-11 T-008] minimal_api_index() already carries C_Item.GetItemInfo
    # (so a bare GetItemInfo call resolves to it as the replacement), the core
    # C_ChatInfo/C_Timer/C_RestrictedActions surface and PLAYER_LOGIN. Only the
    # three facts the acceptance criteria name are added on top.
    base = minimal_api_index(
        extra_functions=("C_Probe.GetSecret", "OldDeprecatedShim"),
        extra_events=("COMBAT_LOG_EVENT_UNFILTERED",),
    )
    data: Any = copy.deepcopy(base.data)
    secret = data["entries"]["function"]["C_Probe.GetSecret"]
    secret["restricted"] = True
    secret["secret"] = {"args": None, "returns": True, "conditions": ["SecretReturns"]}
    data["entries"]["function"]["OldDeprecatedShim"]["deprecated"] = True
    data["entries"]["event"]["COMBAT_LOG_EVENT_UNFILTERED"]["restricted"] = True
    return ApiIndex(data)


def _tools(fake_fs_factory: Any, files: dict[str, str], tmp_path: Path) -> ForgeTools:
    # [2026-11-11 T-008] Saving through IndexStore proves the tool path loads
    # the index from cache_dir exactly as production does, from tmp_path only.
    IndexStore(tmp_path).save(_index().data)
    return ForgeTools(fs=fake_fs_factory(files), cache_dir=tmp_path)


def _addon(
    folder: str, lua_files: dict[str, str], *, saved: str | None = None, bridge: bool = False
) -> tuple[str, dict[str, str]]:
    """Return ``(addon_dir, files)`` for a TOC-valid fake addon folder."""
    base = f"/addons/{folder}"
    headers = ["## Interface: 16001", f"## Title: {folder}"]
    if saved is not None:
        headers.append(f"## SavedVariables: {saved}")
    if bridge:
        headers.append("## X-Forge-Bridge: 1")
    toc = "\n".join([*headers, "", *lua_files]) + "\n"
    files = {f"{base}/{folder}.toc": toc}
    for name, source in lua_files.items():
        files[f"{base}/{name}"] = source
    return base, files


def _check(
    fake_fs_factory: Any, files: dict[str, str], base: str, tmp_path: Path
) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        _tools(fake_fs_factory, files, tmp_path).handle_check({"path": base})
    )
    return payload


def _findings(payload: dict[str, Any], code: str) -> list[dict[str, Any]]:
    return [item for item in payload["findings"] if item["code"] == code]


def _one(payload: dict[str, Any], code: str, file: str, line: int | None) -> dict[str, Any]:
    matches = [
        item for item in _findings(payload, code) if item["file"] == file and item["line"] == line
    ]
    # [2026-11-11 T-008] Exact (code, file, line) matching: a finding of the
    # right code on the wrong line is a different bug, not a pass.
    assert len(matches) == 1, (code, file, line, payload["findings"])
    return matches[0]


# [2026-11-11 T-008] Broken-fixture lines are numbered in the trailing comments;
# GetItemInfo must be line 2 and the restricted RegisterEvent line 3.
_BROKEN_MAIN = (
    'local frame = CreateFrame("Frame")\n'  # line 1
    "GetItemInfo(1234)\n"  # line 2
    'frame:RegisterEvent("COMBAT_LOG_EVENT_UNFILTERED")\n'  # line 3
)
_BROKEN_SYNTAX = (
    "-- Lua 5.3 integer division does not exist in the client's Lua 5.1.\n"  # line 1
    "local x = 7 // 2\n"  # line 2
)


def test_broken_reports_deprecated_restricted_and_syntax(
    fake_fs_factory: Any, tmp_path: Path
) -> None:
    base, files = _addon("Broken", {"Main.lua": _BROKEN_MAIN, "SyntaxBad.lua": _BROKEN_SYNTAX})
    payload = _check(fake_fs_factory, files, base, tmp_path)
    # [2026-11-11 T-008] ok is True even on verdict fail: the check ran and the
    # addon failed it, which is an answer, not a tool error.
    assert payload["ok"] is True
    assert payload["verdict"] == "fail"
    deprecated = _one(payload, "deprecated-api", "Main.lua", 2)
    assert deprecated["severity"] == "error"
    # The replacement must name the namespaced twin that exists in the index.
    assert "C_Item.GetItemInfo" in deprecated["message"] + deprecated["hint"]
    restricted = _one(payload, "restricted-event", "Main.lua", 3)
    assert restricted["severity"] == "error"
    assert "COMBAT_LOG_EVENT_UNFILTERED" in restricted["message"]
    syntax = _one(payload, "syntax", "SyntaxBad.lua", 2)
    assert syntax["severity"] == "error"
    # [2026-11-11 T-008] The same verdicts come out of check_addon directly, so
    # the tool handler is a thin envelope over the pipeline, not a second one.
    direct = check_addon(base, index=_index(), fs=fake_fs_factory(files))
    assert direct["verdict"] == "fail"
    _one(direct, "deprecated-api", "Main.lua", 2)
    _one(direct, "restricted-event", "Main.lua", 3)
    _one(direct, "syntax", "SyntaxBad.lua", 2)


# [2026-11-11 T-008] Clean fixture: the PLAYER_LOGIN handler errors on the
# second login (which only a Stage-5 /reload can cause) unless the slash
# command already mutated CleanDB.slash, so findings == [] is itself proof
# that Stage 5 ran the slash command before the reload.
_CLEAN_CORE = (
    "CleanDB = CleanDB or { logins = 0, slash = 0 }\n"
    'local frame = CreateFrame("Frame", "CleanGlobalFrame")\n'
    'frame:RegisterEvent("PLAYER_LOGIN")\n'
    'frame:SetScript("OnEvent", function(self, event) if event == "PLAYER_LOGIN" then '
    "CleanDB.logins = (CleanDB.logins or 0) + 1 "
    'if CleanDB.logins == 2 and CleanDB.slash ~= 1 then error("no slash") end end end)\n'
    "local item = C_Item.GetItemInfo(1)\nlocal inbox = Clean_Inbox\n"
    'SLASH_CLEAN1 = "/clean"\n'
    'SlashCmdList["CLEAN"] = function(msg) CleanDB.slash = (CleanDB.slash or 0) + 1 end\n'
)

# [2026-11-11 T-008] Stage-5 probe: identical bookkeeping, but the second
# login deliberately errors with the counters in the message. The resulting
# headless-error finding is externally observable proof (not just absence of
# proof) that slash + /reload ran, with slash first.
_PROBE5_CORE = (
    "Probe5DB = Probe5DB or { logins = 0, slash = 0 }\n"
    'local frame = CreateFrame("Frame")\nframe:RegisterEvent("PLAYER_LOGIN")\n'
    'frame:SetScript("OnEvent", function(self, event) if event == "PLAYER_LOGIN" then '
    "Probe5DB.logins = (Probe5DB.logins or 0) + 1 if Probe5DB.logins == 2 then "
    'error("stage5-probe logins=2 slash=" .. tostring(Probe5DB.slash)) end end end)\n'
    'SLASH_PROBE51 = "/probe5"\n'
    'SlashCmdList["PROBE5"] = function(msg) Probe5DB.slash = (Probe5DB.slash or 0) + 1 end\n'
)


def test_clean_addon_passes_with_empty_findings(fake_fs_factory: Any, tmp_path: Path) -> None:
    base, files = _addon("Clean", {"Core.lua": _CLEAN_CORE}, saved="CleanDB", bridge=True)
    payload = _check(fake_fs_factory, files, base, tmp_path)
    assert payload["ok"] is True and payload["verdict"] == "pass"
    assert payload["error_count"] == 0 and payload["warning_count"] == 0
    assert payload["findings"] == []


def test_stage5_slash_and_reload_actually_run(fake_fs_factory: Any, tmp_path: Path) -> None:
    base, files = _addon("Probe5", {"Core.lua": _PROBE5_CORE}, saved="Probe5DB")
    payload = _check(fake_fs_factory, files, base, tmp_path)
    assert payload["verdict"] == "fail"
    probes = [
        item
        for item in _findings(payload, "headless-error")
        if "stage5-probe logins=2 slash=1" in item["message"]
    ]
    # [2026-11-11 T-008] logins=2 can only be reached through the reload's
    # second PLAYER_LOGIN, and slash=1 only through Stage 5 invoking /probe5
    # before that reload flushed Probe5DB. One marker proves both, in order.
    assert len(probes) == 1


def test_real_guildhall_addon_passes_check() -> None:
    direct = check_addon(str(REPO / "addons" / "Guildhall"), index=_index())
    assert direct["verdict"] == "pass"
    assert direct["error_count"] == 0


# [2026-11-11 T-008] error() is on line 2; the OnEvent call into explode() is
# what Stage 5's login dispatch must surface, with the helper's line blamed.
_BOOM_CORE = (
    "local function explode()\n"  # line 1
    '    error("login exploded")\n'  # line 2
    "end\n"  # line 3
    'local frame = CreateFrame("Frame")\n'  # line 4
    'frame:RegisterEvent("PLAYER_LOGIN")\n'  # line 5
    'frame:SetScript("OnEvent", function(self, event)\n'  # line 6
    '    if event == "PLAYER_LOGIN" then explode() end\n'  # line 7
    "end)\n"  # line 8
)


def test_login_error_is_headless_error_with_stack(fake_fs_factory: Any, tmp_path: Path) -> None:
    base, files = _addon("Boom", {"Core.lua": _BOOM_CORE})
    payload = _check(fake_fs_factory, files, base, tmp_path)
    assert payload["ok"] is True
    assert payload["verdict"] == "fail"
    boom = [
        item
        for item in _findings(payload, "headless-error")
        if item["file"] == "Core.lua" and item["line"] == 2
    ]
    assert boom, payload["findings"]
    assert "login exploded" in boom[0]["message"]
    # [2026-11-11 T-008] "Stack:" is check.py's own framing of the captured
    # Lua traceback; without it the finding would name no call chain.
    assert "Stack:" in boom[0]["message"]


# [2026-11-11 T-008] Static-stage fixtures keep the offending calls inside a
# never-called local function: stages 3-4 judge compiled bytecode, and the
# uncalled body keeps Stage 5 from adding unrelated headless errors.
_STATIC_CORE = (
    "local function never_called()\n"  # line 1
    '    io.open("secret.txt")\n'  # line 2
    '    os.execute("rm -rf /")\n'  # line 3
    '    require("socket")\n'  # line 4
    "    debug.getinfo(1)\n"  # line 5
    "    MadeUpGlobal()\n"  # line 6
    "    C_Item.MadeUp()\n"  # line 7
    "    ReloadUI()\n"  # line 8
    "    OldDeprecatedShim()\n"  # line 9
    "end\n"  # line 10
)


def test_forbidden_unknown_and_deprecated_globals(fake_fs_factory: Any, tmp_path: Path) -> None:
    base, files = _addon("StaticBad", {"Core.lua": _STATIC_CORE})
    payload = _check(fake_fs_factory, files, base, tmp_path)
    assert payload["verdict"] == "fail"
    for line, named in ((2, "io"), (3, "os"), (4, "require"), (5, "debug")):
        finding = _one(payload, "forbidden-global", "Core.lua", line)
        assert named in finding["message"]
    _one(payload, "unknown-api", "Core.lua", 6)
    _one(payload, "unknown-api", "Core.lua", 7)
    # [2026-11-11 T-008] ReloadUI has no namespaced twin under its own leaf
    # name, so C_UI.Reload can only come from check.py's removed-globals map.
    reload_ui = _one(payload, "deprecated-api", "Core.lua", 8)
    assert "C_UI.Reload" in reload_ui["message"] + reload_ui["hint"]
    # A deprecated: True index entry is deprecated-api, not unknown-api.
    shim = _one(payload, "deprecated-api", "Core.lua", 9)
    assert "OldDeprecatedShim" in shim["message"]
    assert "deprecated" in shim["message"]


def _restricted_core(guard_line: str | None) -> str:
    lines = ['local frame = CreateFrame("Frame")', "local function act()"]
    if guard_line is not None:
        lines.append(f"    {guard_line}")
    lines.append("    C_Probe.GetSecret()")
    lines.append('    frame:RegisterEvent("COMBAT_LOG_EVENT_UNFILTERED")')
    lines.append("end")
    return "\n".join(lines) + "\n"


def test_restricted_unguarded_is_error_and_guarded_is_warning(
    fake_fs_factory: Any, tmp_path: Path
) -> None:
    base, files = _addon("Unguarded", {"Core.lua": _restricted_core(None)})
    payload = _check(fake_fs_factory, files, base, tmp_path)
    assert payload["verdict"] == "fail"
    api = _findings(payload, "restricted-api")
    event = _findings(payload, "restricted-event")
    assert len(api) == 1 and api[0]["severity"] == "error"
    assert len(event) == 1 and event[0]["severity"] == "error"

    guards = (
        "if C_RestrictedActions.IsAddOnRestrictionActive(0) then return end",
        "if InCombatLockdown() then return end",
        "local ok = pcall(function() return true end)",
    )
    for guard in guards:
        base, files = _addon("Guarded", {"Core.lua": _restricted_core(guard)})
        guarded = _check(fake_fs_factory, files, base, tmp_path)
        # [2026-11-11 T-008] Each guard spelling alone must downgrade BOTH
        # restricted findings to warnings, so a guarded addon still passes.
        assert guarded["verdict"] == "pass", (guard, guarded["findings"])
        assert guarded["error_count"] == 0
        api = _findings(guarded, "restricted-api")
        event = _findings(guarded, "restricted-event")
        assert len(api) == 1 and api[0]["severity"] == "warning"
        assert len(event) == 1 and event[0]["severity"] == "warning"


_UNKNOWN_EVENT_CORE = (
    'local f = CreateFrame("Frame")\n'  # line 1
    "local function never_called()\n"  # line 2
    '    f:RegisterEvent("NO_SUCH_EVENT")\n'  # line 3
    '    f.RegisterEvent(f, "NO_SUCH_EVENT")\n'  # line 4
    "end\n"  # line 5
)


def test_unknown_event_colon_and_dot_spellings(fake_fs_factory: Any, tmp_path: Path) -> None:
    base, files = _addon("BadEvents", {"Core.lua": _UNKNOWN_EVENT_CORE})
    payload = _check(fake_fs_factory, files, base, tmp_path)
    assert payload["verdict"] == "fail"
    # [2026-11-11 T-008] The dot spelling compiles to GETTABLE, not SELF; both
    # bytecode shapes must be recognised as literal event registrations.
    _one(payload, "unknown-event", "Core.lua", 3)
    _one(payload, "unknown-event", "Core.lua", 4)


def test_unserialisable_savedvar_fails_reload(fake_fs_factory: Any, tmp_path: Path) -> None:
    core = "BadDB = { callback = function() end }\n"
    base, files = _addon("BadSave", {"Core.lua": core}, saved="BadDB")
    payload = _check(fake_fs_factory, files, base, tmp_path)
    assert payload["verdict"] == "fail"
    # [2026-11-11 T-008] A function inside a SavedVariables table only fails
    # when Stage 5's reload tries to serialise it; no other stage can see it.
    finding = _one(payload, "unserialisable-savedvar", "BadSave.toc", None)
    assert finding["severity"] == "error"


def test_missing_toc_fails_early(fake_fs_factory: Any, tmp_path: Path) -> None:
    files = {"/addons/NoTocAddon/Main.lua": "local x = 1\n"}
    payload = _check(fake_fs_factory, files, "/addons/NoTocAddon", tmp_path)
    assert payload["ok"] is True
    assert payload["verdict"] == "fail"
    assert payload["error_count"] == 1
    _one(payload, "missing-toc", "NoTocAddon.toc", 1)


_EFFICIENCY_CORE = (
    'local frame = CreateFrame("Frame")\n'
    'frame:SetScript("OnUpdate", function(self, elapsed) CreateFrame("Frame") '
    'C_ChatInfo.SendAddonMessage("PING", "x", "GUILD") end)\n'
    "C_Timer.NewTicker(0.05, function() end)\n"
)
_THROTTLED_CORE = (
    'local frame = CreateFrame("Frame")\n'
    'frame:SetScript("OnUpdate", function(self, elapsed) '
    "if elapsed < 0.1 then return end end)\n"
)


def test_stage6_efficiency_warnings_and_throttle(fake_fs_factory: Any, tmp_path: Path) -> None:
    base, files = _addon("Heavy", {"Core.lua": _EFFICIENCY_CORE})
    payload = _check(fake_fs_factory, files, base, tmp_path)
    # [2026-11-11 T-008] Stage 6 is warnings-only: a wasteful addon still
    # loads, so verdict stays pass while warning_count carries the signal.
    assert payload["verdict"] == "pass"
    assert payload["error_count"] == 0
    assert payload["warning_count"] > 0
    for code in ("unthrottled-onupdate", "frame-in-handler", "unthrottled-addon-message"):
        found = _findings(payload, code)
        assert len(found) == 1 and found[0]["severity"] == "warning", code
    ticker = _findings(payload, "fast-ticker")
    assert len(ticker) == 1 and ticker[0]["severity"] == "warning"
    assert "0.05" in ticker[0]["message"]

    base, files = _addon("Light", {"Core.lua": _THROTTLED_CORE})
    light = _check(fake_fs_factory, files, base, tmp_path)
    assert light["verdict"] == "pass"
    # The elapsed comparison compiles to LT: exactly the throttle Stage 6 wants.
    assert _findings(light, "unthrottled-onupdate") == []
    assert light["findings"] == []


_TESTEE_CORE = (
    "Testee = { received = {} }\n"
    'local frame = CreateFrame("Frame")\nframe:RegisterEvent("CHAT_MSG_ADDON")\n'
    'C_ChatInfo.RegisterAddonMessagePrefix("TESTEE")\n'
    'frame:SetScript("OnEvent", function(self, event, prefix, message) '
    'if event == "CHAT_MSG_ADDON" and prefix == "TESTEE" then '
    "Testee.received[#Testee.received + 1] = message end end)\n"
    "function Testee.answer() return 42 end\n"
    "function Testee.dump() return table.concat(Testee.received, ';') end\n"
    'function Testee.send(m) return C_ChatInfo.SendAddonMessage("TESTEE", m, "GUILD") end\n'
)
_SUITE_LUA = (
    'test("adds_numbers", function(ctx) assert_eq(ctx.client:eval("1 + 2"), 3) '
    'assert_eq(ctx.client:eval("Testee.answer()"), 42) end)\n'
    'test("broken_case", function(ctx) assert_eq(1, 2) end)\n'
)
_MULTI_LUA = (
    'test("multi_client_guild", function(ctx)\n'
    "    assert_eq(#ctx.clients, 2)\n"
    "    ctx.world:set_network({ loss_rate = 0, duplicate_rate = 0 })\n"
    '    ctx.world:set_group({ "Alice", "Bob" }, false)\n'
    "    assert_eq(ctx.clients[1]:eval('Testee.send(\"hello\")'), 0)\n"
    "    ctx.world:advance(0.1)\n"
    "    assert_eq(ctx.clients[2]:eval('Testee.dump()'), 'hello')\n"
    '    local late = ctx.world:client("Late", 2)\n'
    "    assert_eq(late:eval('Testee.dump()'), '')\n"
    "    assert_eq(ctx.clients[1]:eval('Testee.send(\"again\")'), 0)\n"
    "    ctx.world:advance(0.1)\n"
    "    assert_eq(late:eval('Testee.dump()'), 'again')\n"
    "    assert_eq(ctx.clients[2]:eval('Testee.dump()'), 'hello;again')\n"
    "    ctx.client:reload()\n"
    "    assert_eq(ctx.client:eval('Testee.dump()'), '')\n"
    "end)\n"
)
_TABLE_LUA = "return { test_alpha = function(ctx) assert_eq(ctx.client:eval('2 + 3'), 5) end }\n"
_BROKEN_TEST_LUA = "local x = 7 // 2\n"


def _testee() -> tuple[str, dict[str, str]]:
    base, files = _addon("Testee", {"Core.lua": _TESTEE_CORE})
    files[f"{base}/Tests/suite.lua"] = _SUITE_LUA
    files[f"{base}/Tests/multi.lua"] = _MULTI_LUA
    files[f"{base}/Tests/table_suite.lua"] = _TABLE_LUA
    files[f"{base}/Tests/broken.lua"] = _BROKEN_TEST_LUA
    return base, files


def _test_payload(
    fake_fs_factory: Any, files: dict[str, str], base: str, tmp_path: Path, **args: Any
) -> dict[str, Any]:
    tools = _tools(fake_fs_factory, files, tmp_path)
    payload: dict[str, Any] = json.loads(tools.handle_test({"path": base, **args}))
    return payload


def test_wow_test_reports_pass_and_fail_by_name(fake_fs_factory: Any, tmp_path: Path) -> None:
    base, files = _testee()
    payload = _test_payload(fake_fs_factory, files, base, tmp_path, tests="Tests/suite.lua")
    assert payload["ok"] is True
    assert payload["verdict"] == "fail"
    assert (payload["total"], payload["passed"], payload["failed"]) == (2, 1, 1)
    by_name = {item["name"]: item for item in payload["results"]}
    assert by_name["adds_numbers"]["status"] == "pass"
    broken = by_name["broken_case"]
    assert broken["status"] == "fail"
    # [2026-11-11 T-008] A failed case must carry its Lua assertion text and
    # a stack, or the caller can only know THAT it failed, never where.
    assert "assert_eq" in broken["message"] and "1 ~= 2" in broken["message"]
    assert isinstance(broken["stack"], str) and broken["stack"] != ""
    direct = run_addon_tests(
        base, index=_index(), fs=fake_fs_factory(files), tests="Tests/suite.lua"
    )
    assert direct["verdict"] == "fail"
    assert (direct["total"], direct["passed"], direct["failed"]) == (2, 1, 1)
    assert {item["name"]: item["status"] for item in direct["results"]} == {
        "adds_numbers": "pass",
        "broken_case": "fail",
    }


def test_wow_test_multi_client_and_table_form(fake_fs_factory: Any, tmp_path: Path) -> None:
    base, files = _testee()
    multi = _test_payload(
        fake_fs_factory, files, base, tmp_path, tests="Tests/multi.lua", clients=2
    )
    # [2026-11-11 T-008] This one Lua case drives set_network, set_group, a
    # cross-client GUILD message, advance, a late world:client, and a
    # mid-test client:reload (proved by Testee state reading back empty).
    assert multi["ok"] is True and multi["verdict"] == "pass", multi
    assert [(item["name"], item["status"]) for item in multi["results"]] == [
        ("multi_client_guild", "pass")
    ]
    direct = run_addon_tests(
        base,
        index=_index(),
        fs=fake_fs_factory(files),
        tests="Tests/multi.lua",
        clients=2,
    )
    assert direct["verdict"] == "pass" and direct["passed"] == 1

    table_run = _test_payload(fake_fs_factory, files, base, tmp_path, tests="Tests/table_suite.lua")
    assert table_run["verdict"] == "pass"
    assert [(item["name"], item["status"]) for item in table_run["results"]] == [
        ("test_alpha", "pass")
    ]


def test_wow_test_broken_file_is_load_failure(fake_fs_factory: Any, tmp_path: Path) -> None:
    base, files = _testee()
    payload = _test_payload(fake_fs_factory, files, base, tmp_path, tests="Tests/broken.lua")
    assert payload["ok"] is True
    assert payload["verdict"] == "fail"
    assert (payload["total"], payload["passed"], payload["failed"]) == (1, 0, 1)
    only = payload["results"][0]
    # [2026-11-11 T-008] A file that never loads has no case names; the single
    # synthetic "<load>" failure is how it counts as failed, not invisible.
    assert only["name"] == "<load>" and only["status"] == "fail"
    assert only["file"] == "Tests/broken.lua" and only["message"]


def _error_code(payload: dict[str, Any]) -> str:
    assert payload["ok"] is False
    code: str = payload["error"]["code"]
    assert payload["error"]["message"] and payload["error"]["hint"]
    return code


def test_check_and_test_tool_error_boundaries(fake_fs_factory: Any, tmp_path: Path) -> None:
    base, files = _testee()
    tools = _tools(fake_fs_factory, files, tmp_path)
    # [2026-11-11 T-008] Tool arguments arrive from a model, so every shape
    # failure is a bad-argument error object, never a raised exception.
    for handler in (tools.handle_check, tools.handle_test):
        assert _error_code(json.loads(handler([]))) == "bad-argument"
        assert _error_code(json.loads(handler(None))) == "bad-argument"
        assert _error_code(json.loads(handler({}))) == "bad-argument"
        assert _error_code(json.loads(handler({"path": "  "}))) == "bad-argument"
        assert _error_code(json.loads(handler({"path": 123}))) == "bad-argument"
        missing = json.loads(handler({"path": "/addons/DoesNotExist"}))
        assert _error_code(missing) == "bad-path"
    # wow_test argument validation happens before any index or path work.
    for bad_args in (
        {"path": base, "tests": 123},
        {"path": base, "tests": ["Tests/suite.lua", 1]},
        {"path": base, "clients": 0},
        {"path": base, "clients": True},
        {"path": base, "clients": "2"},
    ):
        # [2026-11-11 T-008] clients=True is an int subclass in Python; the
        # handler must still refuse it, or True would silently mean 1 client.
        assert _error_code(json.loads(tools.handle_test(bad_args))) == "bad-argument"


def test_missing_cached_index_is_no_index(fake_fs_factory: Any, tmp_path: Path) -> None:
    base, files = _testee()
    # [2026-11-11 T-008] An empty cache dir (never synced) is no-index for both
    # tools; pointing cache_dir at tmp_path keeps ~/.hermes out of the picture.
    tools = ForgeTools(fs=fake_fs_factory(files), cache_dir=tmp_path / "empty")
    assert _error_code(json.loads(tools.handle_check({"path": base}))) == "no-index"
    assert _error_code(json.loads(tools.handle_test({"path": base}))) == "no-index"


def test_lua_vm_unavailable_is_mapped_for_both_tools(
    fake_fs_factory: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, files = _testee()
    tools = _tools(fake_fs_factory, files, tmp_path)

    def raise_vm(*_args: Any, **_kwargs: Any) -> Any:
        raise LuaVMUnavailableError("no Lua VM here")

    monkeypatch.setattr("wow_addon_forge.tools.check_addon", raise_vm)
    payload = json.loads(tools.handle_check({"path": base}))
    assert _error_code(payload) == "lua-vm-unavailable"
    assert "no Lua VM here" in payload["error"]["message"]
    monkeypatch.setattr("wow_addon_forge.tools.run_addon_tests", raise_vm)
    payload = json.loads(tools.handle_test({"path": base}))
    assert _error_code(payload) == "lua-vm-unavailable"
    assert "no Lua VM here" in payload["error"]["message"]


class _RecordingContext:
    """Stand-in for the Hermes PluginContext: records every register_tool call."""

    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []

    def register_tool(self, name: str, **kwargs: Any) -> None:
        self.tools.append({"name": name, **kwargs})


def test_register_tools_registers_check_and_test_tools(
    fake_fs_factory: Any, tmp_path: Path
) -> None:
    base, files = _addon("Clean", {"Core.lua": _CLEAN_CORE}, saved="CleanDB", bridge=True)
    tools = _tools(fake_fs_factory, files, tmp_path)
    ctx = _RecordingContext()
    registered = register_tools(ctx, tools=tools)
    assert {"wow_env", "wow_api", "wow_check", "wow_test"} <= set(registered)
    assert registered == list(PROVIDES_TOOLS)
    assert [item["name"] for item in ctx.tools] == registered
    for item in ctx.tools:
        assert item["schema"]["name"] == item["name"]
        assert item["check_fn"]() is True
        assert item["description"]
    # [2026-11-11 T-008] Registration must wire the real handlers, not just
    # names: the recorded wow_check handler runs the clean fixture end to end.
    check_tool = next(item for item in ctx.tools if item["name"] == "wow_check")
    payload = json.loads(check_tool["handler"]({"path": base}))
    assert payload["ok"] is True and payload["verdict"] == "pass"


def test_wow_test_auto_discovery_cross_vm_bridge_and_helpers(
    fake_fs_factory: Any, tmp_path: Path
) -> None:
    base, files = _addon("Auto", {"Core.lua": _TESTEE_CORE})
    files[f"{base}/Tests/auto.lua"] = (
        'test("scenario_helpers", function(ctx)\n'
        "    assert_eq(Testee.answer(), 42)\n"
        "    assert_true(true)\n"
        "    assert_false(false)\n"
        '    assert_error(function() error("expected") end)\n'
        '    assert_eq(strjoin("-", strsplit(",", "a,b")), "a-b")\n'
        "    assert_eq(bit.band(15, 6), 6)\n"
        "    local t = { 1, 2 }; wipe(t); assert_eq(#t, 0)\n"
        '    ctx.world:disable_event("BOSS_KILL")\n'
        '    ctx.world:enable_event("BOSS_KILL")\n'
        '    ctx.client:fire("BOSS_KILL", { id = 1 })\n'
        '    ctx.client:set_restriction("Combat", true)\n'
        '    ctx.client:set_restriction("Combat", false)\n'
        '    ctx.client:set_instance({ in_instance = true, instance_type = "party", name = "D" })\n'
        "    ctx.client:set_rank(1)\n"
        "    ctx.client:set_pvp_kills(10)\n"
        "    ctx.client:logout()\n"
        "end)\n"
    )
    payload = _test_payload(fake_fs_factory, files, base, tmp_path)
    assert payload["ok"] is True and payload["verdict"] == "pass", payload
    assert payload["passed"] == 1
    folder_payload = _test_payload(fake_fs_factory, files, base, tmp_path, tests=["Tests"])
    assert folder_payload["verdict"] == "pass" and folder_payload["passed"] == 1
    missing_test = _test_payload(fake_fs_factory, files, base, tmp_path, tests="Tests/nope.lua")
    assert _error_code(missing_test) == "bad-path"


def test_wow_check_and_wow_test_reject_binary_lua_chunks(
    fake_fs_factory: Any, tmp_path: Path
) -> None:
    # [2026-11-11 T-060] Neither wow_check nor wow_test may accept \x1b-prefixed bytecode.
    binary = "\x1bLuaQ\x00\x01\x04\x08\x04\x08\x00"
    bad_base, bad_files = _addon("BinCheck", {"Core.lua": binary})
    report = check_addon(bad_base, index=_index(), fs=fake_fs_factory(bad_files))
    assert report["verdict"] == "fail"
    assert any(
        f["code"] == "syntax" and "binary chunks are not allowed" in f["message"]
        for f in report["findings"]
    )
    test_base, test_files = _addon("BinTest", {"Core.lua": "local ok = 1\n"})
    test_files[f"{test_base}/Tests/bin.lua"] = binary
    test_report = run_addon_tests(test_base, index=_index(), fs=fake_fs_factory(test_files))
    assert test_report["verdict"] == "fail"
    assert test_report["failed"] == 1
    assert "binary chunks are not allowed" in test_report["results"][0]["message"]
    from wow_addon_forge.check import _run_one_case

    ok_case, msg_case, _ = _run_one_case(
        source=binary,
        rel_test="Tests/bin.lua",
        idx=1,
        addon_path=test_base,
        index=_index(),
        fs=fake_fs_factory(test_files),
        clients=1,
    )
    assert ok_case is False and "binary chunks are not allowed" in msg_case
