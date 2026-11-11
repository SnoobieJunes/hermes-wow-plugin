"""T-007 acceptance tests for the headless WoW client runtime (created 2026-11-11).

Invariants owned by this file:
- Every scenario is hermetic: addon files live only in a ``FakeFileSystem`` from
  ``fake_fs_factory``, the API world is ``minimal_api_index`` (or a small custom
  ``ApiIndex`` built from it), and nothing touches real disk or ``~/.hermes``.
- Assertions read back exactly what addon Lua observed (recorded event payloads,
  return codes, timer order), never Python-side mirrors of that state, except
  where the contract under test is itself the Python store (SavedVariables).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from wow_addon_forge.apidocs import ApiIndex
from wow_addon_forge.headless import (
    PREFIX_RESULT,
    SEND_RESULT,
    HeadlessError,
    SavedVariablesError,
    SimulatedClient,
    World,
    export_saved_value,
    format_saved_variables_lua,
    import_saved_value,
    minimal_api_index,
)
from wow_addon_forge.luavm import LuaChunkError, new_runtime, run_chunk

ADDON_DIR = "/addons/Probe"

_PROBE_TOC = (
    "## Interface: 16001\n"
    "## Title: Probe\n"
    "## SavedVariables: ProbeDB\n"
    "## SavedVariablesPerCharacter: ProbeCharDB\n"
    "\nCore.lua\nSecond.lua\n"
)

# [2026-11-11 T-007] The fixture addon never auto-registers a prefix: registration
# is the variable under test, so the scenario opts each client in explicitly via
# ``Probe.register()`` and an unregistered client proves the negative case.
_PROBE_CORE = """
local addonName, ns = ...
Probe = { received = {}, pew = nil, roster = 0, roster_arg = nil, pvp = 0,
    restrictions = {}, addon_name = addonName, slash_msg = nil, loaded_name = nil }
ns.marker = "shared-ns"
ProbeDB = ProbeDB or { initialized = true }
ProbeCharDB = ProbeCharDB or {}
local frame = CreateFrame("Frame")
Probe.frame = frame
for _, ev in ipairs({ "CHAT_MSG_ADDON", "PLAYER_ENTERING_WORLD", "ADDON_LOADED",
    "ADDON_RESTRICTION_STATE_CHANGED", "GUILD_ROSTER_UPDATE",
    "PLAYER_PVP_KILLS_CHANGED" }) do frame:RegisterEvent(ev) end
frame:SetScript("OnEvent", function(self, event, ...)
    if event == "CHAT_MSG_ADDON" then
        local prefix, message, channel, sender, target = ...
        Probe.received[#Probe.received + 1] = { prefix = prefix, message = message,
            channel = channel, sender = sender, target = target }
    elseif event == "PLAYER_ENTERING_WORLD" then Probe.pew = { ... }
    elseif event == "ADDON_RESTRICTION_STATE_CHANGED" then
        local regime, state = ...
        Probe.restrictions[#Probe.restrictions + 1] = regime .. ":" .. state
    elseif event == "GUILD_ROSTER_UPDATE" then
        Probe.roster = Probe.roster + 1; Probe.roster_arg = ...
    elseif event == "PLAYER_PVP_KILLS_CHANGED" then Probe.pvp = Probe.pvp + 1
    elseif event == "ADDON_LOADED" then Probe.loaded_name = ... end
end)
function Probe.register(p) return C_ChatInfo.RegisterAddonMessagePrefix(p or "PROBE") end
function Probe.send(p, m, c, t) return C_ChatInfo.SendAddonMessage(p, m, c, t) end
function Probe.dump_received()
    local parts = {}
    for i = 1, #Probe.received do local r = Probe.received[i]
        parts[#parts + 1] = table.concat(
            { r.prefix, r.message, r.channel, r.sender, tostring(r.target) }, "|") end
    return table.concat(parts, ";")
end
function Probe.clear() Probe.received = {} end
SLASH_PROBE1 = "/probe"; SLASH_PROBE2 = "/prb"
SlashCmdList["PROBE"] = function(msg) Probe.slash_msg = msg end
"""

_PROBE_SECOND = """
local addonName, ns = ...
Probe.ns_from_second = ns.marker
Probe.second_addon_name = addonName
"""


def _probe_files() -> dict[str, str]:
    return {
        f"{ADDON_DIR}/Probe.toc": _PROBE_TOC,
        f"{ADDON_DIR}/Core.lua": _PROBE_CORE,
        f"{ADDON_DIR}/Second.lua": _PROBE_SECOND,
    }


def _world(fake_fs_factory: Any, **kwargs: Any) -> World:
    return World(fs=fake_fs_factory(_probe_files()), **kwargs)


def _pair(fake_fs_factory: Any, **kwargs: Any) -> tuple[World, SimulatedClient, SimulatedClient]:
    world = _world(fake_fs_factory, **kwargs)
    alice = world.client("Alice")
    bob = world.client("Bob")
    alice.load_addon(ADDON_DIR)
    bob.load_addon(ADDON_DIR)
    return world, alice, bob


def _lua(client: SimulatedClient, source: str) -> Any:
    return client.run_lua(source)


def _received(client: SimulatedClient) -> str:
    return str(_lua(client, "Probe.dump_received()"))


def _send(
    client: SimulatedClient, prefix: str, message: str, channel: str, target: str = ""
) -> Any:
    # [2026-11-11 T-007] An empty target is passed as a real empty string only by
    # accident of spelling; WoW treats it as "no target", which WHISPER tests use.
    if target:
        return _lua(
            client,
            f'Probe.send("{prefix}", "{message}", "{channel}", "{target}")',
        )
    return _lua(client, f'Probe.send("{prefix}", "{message}", "{channel}")')


def test_guild_message_only_reaches_registered_prefix(fake_fs_factory: Any) -> None:
    _world_obj, alice, bob = _pair(fake_fs_factory)
    assert alice.errors == [] and bob.errors == []
    # [2026-11-11 T-007] Both clients loaded the same TOC+Lua files in order and
    # shared one ``...`` namespace table across Core.lua and Second.lua.
    assert alice.loaded_addons == ("Probe",)
    assert _lua(alice, "Probe.addon_name") == "Probe"
    assert _lua(alice, "Probe.ns_from_second") == "shared-ns"
    assert _lua(alice, "Probe.loaded_name") == "Probe"
    # Unregistered Bob: the send itself succeeds, delivery is what is gated.
    assert _send(alice, "PROBE", "hello", "GUILD") == SEND_RESULT["Success"] == 0
    assert _received(bob) == ""
    assert _lua(bob, 'C_ChatInfo.IsAddonMessagePrefixRegistered("PROBE")') is False
    assert _lua(bob, "Probe.register()") == PREFIX_RESULT["Success"] == 0
    assert _lua(bob, 'C_ChatInfo.IsAddonMessagePrefixRegistered("PROBE")') is True
    assert _lua(bob, "Probe.register()") == PREFIX_RESULT["DuplicatePrefix"] == 1
    assert _send(alice, "PROBE", "hello", "GUILD") == 0
    # [2026-11-11 T-007] Sender arrives in canonical Name-Realm form even though
    # the scenario created the client with the short name "Alice".
    assert _received(bob) == "PROBE|hello|GUILD|Alice-Forever|Alice-Forever"
    prefixes = _lua(bob, "C_ChatInfo.GetRegisteredAddonMessagePrefixes()[1]")
    assert prefixes == "PROBE"


def test_guild_echo_to_sender_true_vs_false(fake_fs_factory: Any) -> None:
    _w1, alice, bob = _pair(fake_fs_factory)
    _lua(alice, "Probe.register()")
    _lua(bob, "Probe.register()")
    assert _send(alice, "PROBE", "echo", "GUILD") == 0
    assert _received(alice) == "PROBE|echo|GUILD|Alice-Forever|Alice-Forever"
    assert _received(bob) == "PROBE|echo|GUILD|Alice-Forever|Alice-Forever"

    _w2, alice2, bob2 = _pair(fake_fs_factory, echo_guild_to_sender=False)
    _lua(alice2, "Probe.register()")
    _lua(bob2, "Probe.register()")
    assert _send(alice2, "PROBE", "echo", "GUILD") == 0
    # [2026-11-11 T-007] echo_guild_to_sender=False removes only the sender's own
    # copy; guildmates are unaffected.
    assert _received(alice2) == ""
    assert _received(bob2) == "PROBE|echo|GUILD|Alice-Forever|Alice-Forever"


def test_whisper_hit_target_required_and_target_offline(fake_fs_factory: Any) -> None:
    _world_obj, alice, bob = _pair(fake_fs_factory)
    _lua(bob, "Probe.register()")
    assert _send(alice, "PROBE", "psst", "WHISPER", "Bob") == 0
    assert _received(bob) == "PROBE|psst|WHISPER|Alice-Forever|Bob-Forever"
    # Full Name-Realm spelling resolves to the same client.
    assert _send(alice, "PROBE", "again", "WHISPER", "Bob-Forever") == 0
    assert _received(bob).count("WHISPER") == 2
    result = _send(alice, "PROBE", "nobody", "WHISPER")
    assert result == SEND_RESULT["TargetRequired"] == 6
    bob.logout()
    assert bob.online is False
    result = _send(alice, "PROBE", "gone", "WHISPER", "Bob")
    assert result == SEND_RESULT["TargetOffline"] == 12
    assert _received(bob).count("WHISPER") == 2


def test_party_raid_require_group_and_unguilded_guild_send(fake_fs_factory: Any) -> None:
    world, alice, bob = _pair(fake_fs_factory)
    _lua(alice, "Probe.register()")
    _lua(bob, "Probe.register()")
    assert _send(alice, "PROBE", "p", "PARTY") == SEND_RESULT["NotInGroup"] == 5
    assert _send(alice, "PROBE", "r", "RAID") == SEND_RESULT["NotInGroup"] == 5
    assert _lua(alice, "IsInGroup()") is False
    world.set_group(["Alice", "Bob"])
    assert _lua(alice, "IsInGroup()") is True
    assert _lua(alice, "IsInRaid()") is False
    assert _lua(alice, "GetNumGroupMembers()") == 2
    assert _send(alice, "PROBE", "p", "PARTY") == 0
    assert "PARTY" in _received(bob)
    # A party is not a raid: RAID stays refused until the group becomes one.
    assert _send(alice, "PROBE", "r", "RAID") == SEND_RESULT["NotInGroup"] == 5
    world.set_group(["Alice", "Bob"], raid=True)
    assert _lua(alice, "IsInRaid()") is True
    _lua(bob, "Probe.clear()")
    assert _send(alice, "PROBE", "r", "RAID") == 0
    assert _received(bob) == "PROBE|r|RAID|Alice-Forever|Alice-Forever"

    carol = world.client("Carol", rank=None)
    assert _lua(carol, "IsInGuild()") is False
    result = _lua(carol, 'C_ChatInfo.SendAddonMessage("PROBE", "hi", "GUILD")')
    assert result == SEND_RESULT["NotInGuild"] == 10


def test_message_and_prefix_byte_limits(fake_fs_factory: Any) -> None:
    _world_obj, alice, bob = _pair(fake_fs_factory)
    _lua(bob, "Probe.register()")
    ok = _lua(
        alice,
        'C_ChatInfo.SendAddonMessage("PROBE", string.rep("x", 255), "GUILD")',
    )
    assert ok == SEND_RESULT["Success"] == 0
    assert _lua(bob, "#Probe.received") == 1
    assert _lua(bob, "#Probe.received[1].message") == 255
    refused = _lua(
        alice,
        'C_ChatInfo.SendAddonMessage("PROBE", string.rep("x", 256), "GUILD")',
    )
    # [2026-11-11 T-007] 256 bytes is refused at send time: no CHAT_MSG_ADDON
    # fires, so Bob's log is unchanged rather than holding a truncated copy.
    assert refused == SEND_RESULT["InvalidMessage"] == 2
    assert _lua(bob, "#Probe.received") == 1
    for bad in ('""', '"12345678901234567"'):
        reg = _lua(alice, f"C_ChatInfo.RegisterAddonMessagePrefix({bad})")
        assert reg == PREFIX_RESULT["InvalidPrefix"] == 2
        sent = _lua(alice, f'C_ChatInfo.SendAddonMessage({bad}, "hi", "GUILD")')
        assert sent == SEND_RESULT["InvalidPrefix"] == 1
    assert _lua(bob, "#Probe.received") == 1
    # Sixteen bytes is the inclusive upper bound for a prefix.
    reg16 = _lua(alice, 'C_ChatInfo.RegisterAddonMessagePrefix("1234567890123456")')
    assert reg16 == PREFIX_RESULT["Success"] == 0


def test_token_bucket_throttles_eleventh_and_refills_on_advance(
    fake_fs_factory: Any,
) -> None:
    world, alice, bob = _pair(fake_fs_factory)
    _lua(alice, "Probe.register()")
    _lua(bob, "Probe.register()")
    for index in range(10):
        assert _send(alice, "PROBE", f"m{index}", "GUILD") == 0
    assert _lua(bob, "#Probe.received") == 10
    throttled = _send(alice, "PROBE", "m10", "GUILD")
    # [2026-11-11 T-007] The burst bucket holds exactly 10 tokens at t=0: send 11
    # inside the same virtual second is refused and delivers nothing.
    assert throttled == SEND_RESULT["AddonMessageThrottle"] == 3
    assert _lua(bob, "#Probe.received") == 10
    # A fresh prefix does not help Alice (per-client bucket is also empty)...
    assert _send(alice, "OTHER", "m10", "GUILD") == 3
    # ...but Bob's buckets are his own, so he can still send at the same instant.
    assert _send(bob, "PROBE", "from-bob", "GUILD") == 0
    world.advance(1.0)
    # [2026-11-11 T-007] One virtual second refills exactly one token: one send
    # succeeds, the very next is throttled again.
    assert _send(alice, "PROBE", "m10", "GUILD") == 0
    assert _lua(bob, "#Probe.received") == 12
    assert _send(alice, "PROBE", "m11", "GUILD") == 3
    assert _lua(bob, "#Probe.received") == 12


def _shaped_index() -> ApiIndex:
    data: Any = copy.deepcopy(minimal_api_index().data)
    functions: Any = data["entries"]["function"]

    def add(name: str, returns: list[dict[str, Any]]) -> None:
        functions[name] = {
            "name": name,
            "kind": "function",
            "namespace": name.rsplit(".", 1)[0] if "." in name else None,
            "system": None,
            "args": [],
            "returns": returns,
            "flags": {},
            "c_api": True,
            "restricted": False,
            "secret": {"args": None, "returns": False, "conditions": []},
            "deprecated": False,
            "documented": True,
            "source": "test",
        }

    add("C_Probe.GetFlag", [{"type": "bool"}])
    add("C_Probe.GetCount", [{"type": "number"}])
    add("C_Probe.GetText", [{"type": "string"}])
    add("C_Probe.GetTable", [{"type": "table"}])
    add("C_Probe.GetMaybe", [{"type": "string", "nilable": True}])
    add("C_Probe.GetPair", [{"type": "bool"}, {"type": "number"}, {"type": "string"}])
    add("ProbeGlobalFn", [{"type": "number"}])
    data["entries"]["table"]["Constants.ProbeConsts"] = {
        "name": "Constants.ProbeConsts",
        "kind": "table",
        "values": {"Max": 7},
        "restricted": False,
        "secret": {"args": None, "returns": False, "conditions": []},
        "deprecated": False,
        "documented": True,
        "source": "test",
    }
    return ApiIndex(data)


def test_unknown_c_member_global_enum_constants_raise_named(
    fake_fs_factory: Any,
) -> None:
    world = World(minimal_api_index(), fs=fake_fs_factory(_probe_files()))
    alice = world.client("Alice")
    cases = [
        ("C_Item.NoSuchFunction", "C_Item.NoSuchFunction"),
        ("UnknownGlobalName", "UnknownGlobalName"),
        ("debug", "debug"),
        ("Enum.Nope", "Nope"),
        ("Constants.Nope", "Nope"),
    ]
    for source, named in cases:
        with pytest.raises(LuaChunkError) as exc:
            _lua(alice, source)
        # [2026-11-11 T-007] Strictness must name the typo: a bare "attempt to
        # index nil" would hide which API the addon author got wrong.
        assert named in str(exc.value)


def test_documented_function_returns_shaped_defaults(fake_fs_factory: Any) -> None:
    world = World(_shaped_index(), fs=fake_fs_factory(_probe_files()))
    alice = world.client("Alice")
    shaped: list[tuple[str, Any]] = [
        ("type(C_Item.GetItemInfo)", "function"),
        ("type(C_Probe.GetFlag)", "function"),
        ("type(ProbeGlobalFn)", "function"),
        ("C_Probe.GetFlag()", False),
        ("C_Probe.GetCount()", 0),
        ("C_Probe.GetText()", ""),
        ("type(C_Probe.GetTable())", "table"),
        ("C_Probe.GetMaybe()", None),
        ("ProbeGlobalFn()", 0),
    ]
    for source, expected in shaped:
        assert _lua(alice, source) == expected, source
    pair = _lua(
        alice,
        'local a, b, c = C_Probe.GetPair()\nreturn tostring(a) .. "|" .. tostring(b) .. "|" .. c',
    )
    assert pair == "false|0|"
    # [2026-11-11 T-007] Each table default is a fresh table: mutating one
    # return value must not poison the next call's default.
    fresh = _lua(
        alice,
        "local t = C_Probe.GetTable()\nt.x = 1\nreturn C_Probe.GetTable().x",
    )
    assert fresh is None
    assert _lua(alice, "Enum.SendAddonMessageResult.InvalidMessage") == 2
    assert _lua(alice, "Constants.ProbeConsts.Max") == 7


def test_unknown_event_registration_and_disable_enable(fake_fs_factory: Any) -> None:
    world, alice, _bob = _pair(fake_fs_factory)
    _lua(alice, 'ProbeEvtFrame = CreateFrame("Frame")')
    for verb in ("RegisterEvent", "UnregisterEvent"):
        with pytest.raises(LuaChunkError) as exc:
            _lua(alice, f'ProbeEvtFrame:{verb}("NOT_A_REAL_EVENT")')
        assert "NOT_A_REAL_EVENT" in str(exc.value)
    with pytest.raises(HeadlessError):
        alice.fire("NOT_A_REAL_EVENT")
    assert _lua(alice, 'C_EventUtils.IsEventValid("BOSS_KILL")') is True
    world.disable_event("BOSS_KILL")
    assert _lua(alice, 'C_EventUtils.IsEventValid("BOSS_KILL")') is False
    with pytest.raises(HeadlessError):
        alice.fire("BOSS_KILL")
    with pytest.raises(LuaChunkError) as exc:
        _lua(alice, 'ProbeEvtFrame:RegisterEvent("BOSS_KILL")')
    assert "BOSS_KILL" in str(exc.value)
    world.enable_event("BOSS_KILL")
    assert _lua(alice, 'C_EventUtils.IsEventValid("BOSS_KILL")') is True
    assert _lua(alice, 'ProbeEvtFrame:RegisterEvent("BOSS_KILL")') is True
    alice.fire("BOSS_KILL", 1234)


def test_timers_fire_in_due_then_registration_order(fake_fs_factory: Any) -> None:
    world, alice, _bob = _pair(fake_fs_factory)
    _lua(
        alice,
        "TimerLog = {}\n"
        "local function add(v) TimerLog[#TimerLog + 1] = v end\n"
        'C_Timer.After(0.5, function() add("late") end)\n'
        "C_Timer.After(0.1, function()\n"
        '    add("early1")\n'
        '    C_Timer.After(0.2, function() add("nested") end)\n'
        "end)\n"
        'C_Timer.After(0.1, function() add("early2") end)',
    )
    assert _lua(alice, 'table.concat(TimerLog, ",")') == ""
    world.advance(1.0)
    # [2026-11-11 T-007] (due, seq) ordering: the two 0.1 timers keep
    # registration order, and the nested timer scheduled at t=0.1 for +0.2
    # lands at 0.3, before the 0.5 timer registered first.
    assert _lua(alice, 'table.concat(TimerLog, ",")') == "early1,early2,nested,late"


def test_timer_handles_ticker_iterations_and_self_cancel(
    fake_fs_factory: Any,
) -> None:
    world, alice, _bob = _pair(fake_fs_factory)
    _lua(
        alice,
        "TimerLog = {}\n"
        "local function add(v) TimerLog[#TimerLog + 1] = v end\n"
        'KeptTimer = C_Timer.NewTimer(0.2, function() add("kept") end)\n'
        'DeadTimer = C_Timer.NewTimer(0.2, function() add("dead") end)\n'
        "DeadTimer:Cancel()\n"
        'Ticker = C_Timer.NewTicker(0.1, function() add("tick") end, 3)\n'
        "SelfCount = 0\n"
        "SelfTicker = C_Timer.NewTicker(0.1, function(handle)\n"
        "    SelfCount = SelfCount + 1\n"
        '    add("self")\n'
        "    if SelfCount >= 2 then handle:Cancel() end\n"
        "end)",
    )
    # [2026-11-11 T-007] SelfTicker cancels itself through the handle passed to
    # its callback on its second tick, while Ticker stops via its iteration cap.
    assert _lua(alice, "DeadTimer:IsCancelled()") is True
    assert _lua(alice, "KeptTimer:IsCancelled()") is False
    world.advance(1.0)
    log = str(_lua(alice, 'table.concat(TimerLog, ",")'))
    assert "dead" not in log
    assert log.count("kept") == 1
    assert log.count("tick") == 3
    assert log.count("self") == 2
    assert _lua(alice, "Ticker:IsCancelled()") is True
    assert _lua(alice, "SelfTicker:IsCancelled()") is True
    assert _lua(alice, "KeptTimer:IsCancelled()") is True


def test_virtual_clocks_advance_and_negative_advance_raises(
    fake_fs_factory: Any,
) -> None:
    world, alice, _bob = _pair(fake_fs_factory)
    assert _lua(alice, "GetTime()") == 0
    assert _lua(alice, "GetServerTime()") == 1_800_000_000
    assert _lua(alice, "time()") == 1_800_000_000
    world.advance(2.5)
    assert _lua(alice, "GetTime()") == pytest.approx(2.5)
    assert _lua(alice, "GetServerTime()") == 1_800_000_002
    assert _lua(alice, "time()") == 1_800_000_002
    with pytest.raises(ValueError, match="advance"):
        world.advance(-1)


def _pew(client: SimulatedClient) -> str:
    return str(_lua(client, "tostring(Probe.pew[1]) .. '|' .. tostring(Probe.pew[2])"))


def test_saved_variables_survive_reload_and_c_ui_reload(fake_fs_factory: Any) -> None:
    _world_obj, alice, _bob = _pair(fake_fs_factory)
    assert _pew(alice) == "true|false"
    _lua(
        alice,
        "ProbeDB = {\n"
        '    name = "vault", count = 3, ratio = 1.5, flag = true,\n'
        '    list = { "a", "b" }, sparse = { [1] = "a", [5] = "b" },\n'
        "    nested = { inner = { 1, 2, 3 }, deep = { on = false } },\n"
        "}\n"
        'ProbeCharDB = { char = "Alice", seen = false, gold = 42 }',
    )
    alice.reload()
    # [2026-11-11 T-007] PEW payload flips from initial login (true,false) to
    # reload (false,true); Probe.pew is rebuilt per VM, so this is the new one.
    assert _pew(alice) == "false|true"
    assert _lua(alice, "ProbeDB.name") == "vault"
    assert _lua(alice, "ProbeDB.count") == 3
    assert _lua(alice, "ProbeDB.ratio") == pytest.approx(1.5)
    assert _lua(alice, "ProbeDB.flag") is True
    assert _lua(alice, "ProbeDB.list[2]") == "b"
    # [2026-11-11 T-007] Sparse integer keys stay sparse: [5] must not be
    # renumbered to [2] by an array-shaped round-trip.
    assert _lua(alice, "ProbeDB.sparse[5]") == "b"
    assert _lua(alice, "ProbeDB.sparse[2]") is None
    assert _lua(alice, "ProbeDB.nested.inner[3]") == 3
    assert _lua(alice, "ProbeDB.nested.deep.on") is False
    assert _lua(alice, "ProbeCharDB.char") == "Alice"
    assert alice.account_saved_variables["ProbeDB"] == {
        "name": "vault",
        "count": 3,
        "ratio": 1.5,
        "flag": True,
        "list": ["a", "b"],
        "sparse": {1: "a", 5: "b"},
        "nested": {"inner": [1, 2, 3], "deep": {"on": False}},
    }
    assert alice.character_saved_variables["ProbeCharDB"] == {
        "char": "Alice",
        "seen": False,
        "gold": 42,
    }
    _lua(alice, "ProbeDB.count = 99")
    _lua(alice, "C_UI.Reload()")
    assert _lua(alice, "ProbeDB.count") == 99
    assert _pew(alice) == "false|true"


def test_unserialisable_saved_variables_raise_on_flush(fake_fs_factory: Any) -> None:
    _world_obj, alice, _bob = _pair(fake_fs_factory)
    _lua(alice, "ProbeDB.bad = function() end")
    with pytest.raises(SavedVariablesError) as exc:
        alice.reload()
    assert exc.value.var_name == "ProbeDB"
    assert "ProbeDB.bad" in exc.value.path
    _lua(alice, "ProbeDB.bad = nil")
    for bad_lua in ("math.huge", "0 / 0", "ProbeDB"):
        _lua(alice, f"ProbeDB.bad = {bad_lua}")
        # [2026-11-11 T-007] Inf, NaN (0/0) and a self-cycle have no on-disk
        # SavedVariables form; each must fail at flush, naming ProbeDB.bad.
        with pytest.raises(SavedVariablesError) as bad_exc:
            alice.flush_saved_variables()
        assert "ProbeDB.bad" in bad_exc.value.path
        _lua(alice, "ProbeDB.bad = nil")
    alice.flush_saved_variables()


def test_format_saved_variables_round_trips_control_bytes() -> None:
    original = 'a\x00b\n\t"\\z'
    text = format_saved_variables_lua({"MyDB": {"s": original, "n": 1, "ok": True}})
    runtime = new_runtime()
    run_chunk(runtime, text, "MyDB.lua")
    # [2026-11-11 T-007] The formatted text is loaded by a bare Lua VM (no
    # headless bootstrap), proving it is valid standalone SavedVariables Lua.
    assert runtime.globals()["MyDB"]["s"] == original
    assert runtime.globals()["MyDB"]["n"] == 1
    assert runtime.globals()["MyDB"]["ok"] is True
    with pytest.raises(SavedVariablesError):
        format_saved_variables_lua({"bad name": {}})


def test_combat_restriction_locks_down_addon_messages(fake_fs_factory: Any) -> None:
    _world_obj, alice, bob = _pair(fake_fs_factory)
    _lua(bob, "Probe.register()")
    combat = "Enum.AddOnRestrictionType.Combat"
    assert _lua(alice, f"C_RestrictedActions.IsAddOnRestrictionActive({combat})") is False
    assert _lua(alice, "InCombatLockdown()") is False
    assert _lua(alice, f"C_RestrictedActions.GetAddOnRestrictionState({combat})") == 0
    alice.set_restriction("Combat", True)
    assert _lua(alice, f"C_RestrictedActions.IsAddOnRestrictionActive({combat})") is True
    assert _lua(alice, "C_RestrictedActions.IsAddOnRestrictionActive(0)") is True
    assert _lua(alice, "InCombatLockdown()") is True
    state = _lua(alice, f"C_RestrictedActions.GetAddOnRestrictionState({combat})")
    assert state == 2
    # [2026-11-11 T-007] The event payload is (restrictionType, state) as raw
    # enum integers: Combat=0 flipping to Active=2, then Inactive=0 on lift.
    events = _lua(alice, 'table.concat(Probe.restrictions, ";")')
    assert events == "0:2"
    refused = _send(alice, "PROBE", "locked", "GUILD")
    assert refused == SEND_RESULT["AddOnMessageLockdown"] == 11
    assert _received(bob) == ""
    alice.set_restriction("Combat", False)
    assert _lua(alice, "InCombatLockdown()") is False
    assert _lua(alice, f"C_RestrictedActions.GetAddOnRestrictionState({combat})") == 0
    assert _lua(alice, 'table.concat(Probe.restrictions, ";")') == "0:2;0:0"
    assert _send(alice, "PROBE", "free", "GUILD") == 0
    assert _received(bob) == "PROBE|free|GUILD|Alice-Forever|Alice-Forever"
    with pytest.raises(ValueError, match="restriction"):
        alice.set_restriction("NoSuchRegime", True)


def test_frames_widgets_visibility_scripts_and_layout(fake_fs_factory: Any) -> None:
    world, alice, _bob = _pair(fake_fs_factory)
    _lua(
        alice,
        'ParentF = CreateFrame("Frame", "ParentF", UIParent)\n'
        'ChildF = CreateFrame("Button", "ChildF", ParentF)\n'
        "ParentF.log = {}\n"
        'ParentF:SetScript("OnShow", function() ParentF.log[#ParentF.log+1]="show" end)\n'
        'ParentF:HookScript("OnShow", function() ParentF.log[#ParentF.log+1]="hook" end)\n'
        'ParentF:SetScript("OnHide", function() ParentF.log[#ParentF.log+1]="hide" end)\n'
        "ParentF:SetSize(100, 50)\n"
        "ParentF:SetAlpha(0.5)\n"
        'ParentF:SetPoint("CENTER", UIParent, "CENTER", 10, -5)\n'
        'ParentF:SetFrameStrata("HIGH")\n'
        "ParentF:SetFrameLevel(7)\n"
        'FontS = ParentF:CreateFontString(nil, "OVERLAY")\n'
        'FontS:SetText("label")\n'
        'Tex = ParentF:CreateTexture(nil, "BACKGROUND")\n'
        'Tex:SetTexture("tex/path")',
    )
    frame_checks: list[tuple[str, Any]] = [
        ("ChildF:GetParent() == ParentF", True),
        ("ParentF:GetNumChildren()", 1),
        ("ParentF:GetChildren() == ChildF", True),
        ("ChildF:GetObjectType()", "Button"),
        ('ChildF:IsObjectType("Frame")', True),
        ("ParentF:GetWidth()", 100),
        ("ParentF:GetHeight()", 50),
        ("ParentF:GetNumPoints()", 1),
        ("ParentF:GetPoint(1)", "CENTER"),
        ("ParentF:GetFrameStrata()", "HIGH"),
        ("ParentF:GetFrameLevel()", 7),
        ("ParentF:GetNumRegions()", 2),
        ("FontS:GetObjectType()", "FontString"),
        ("FontS:GetText()", "label"),
        ("FontS:GetParent() == ParentF", True),
        ("Tex:GetTexture()", "tex/path"),
        ('type(ParentF:GetScript("OnShow"))', "function"),
    ]
    for source, expected in frame_checks:
        assert _lua(alice, source) == expected, source
    size = _lua(alice, "local w, h = ParentF:GetSize()\nreturn w .. 'x' .. h")
    assert size == "100x50"
    assert _lua(alice, "ParentF:GetAlpha()") == pytest.approx(0.5)
    _lua(alice, "ParentF:Hide()")
    assert _lua(alice, "ParentF:IsShown()") is False
    # [2026-11-11 T-007] IsVisible walks ancestors: the child is still "shown"
    # itself, but not visible while its parent is hidden.
    assert _lua(alice, "ChildF:IsShown()") is True
    assert _lua(alice, "ChildF:IsVisible()") is False
    _lua(alice, "ParentF:Show()")
    assert _lua(alice, "ChildF:IsVisible()") is True
    assert _lua(alice, 'table.concat(ParentF.log, ",")') == "hide,show,hook"
    _lua(alice, "ChildF:SetParent(UIParent)")
    assert _lua(alice, "ParentF:GetNumChildren()") == 0
    assert _lua(alice, "ChildF:GetParent() == UIParent") is True
    with pytest.raises(LuaChunkError) as exc:
        _lua(alice, 'CreateFrame("Frame", nil, nil, "NoSuchTemplate")')
    assert "NoSuchTemplate" in str(exc.value)
    known = _lua(alice, 'type(CreateFrame("Button", nil, nil, "UIPanelButtonTemplate"))')
    assert known == "table"
    world.add_template("MyTemplate")
    added = _lua(alice, 'type(CreateFrame("Frame", nil, nil, "MyTemplate"))')
    assert added == "table"


def test_wow_lua_stdlib_extensions(fake_fs_factory: Any) -> None:
    _world_obj, alice, _bob = _pair(fake_fs_factory)
    split = _lua(
        alice,
        'local a, b, c = strsplit(",", "x,y,z")\nreturn a .. "|" .. b .. "|" .. c',
    )
    assert split == "x|y|z"
    assert _lua(alice, 'strjoin("-", "a", "b", 3)') == "a-b-3"
    assert _lua(alice, 'strtrim("  pad  ")') == "pad"
    wiped = _lua(
        alice,
        "local t = { 1, 2, x = 3 }\nlocal same = wipe(t)\n"
        "return tostring(same == t) .. '|' .. tostring(next(t))",
    )
    assert wiped == "true|nil"
    # [2026-11-11 T-007] bit.* is signed 32-bit: bnot(0) is -1, and arshift
    # sign-extends where rshift does not.
    bit_checks = [
        ("bit.band(12, 10)", 8),
        ("bit.bor(12, 10)", 14),
        ("bit.bxor(12, 10)", 6),
        ("bit.bnot(0)", -1),
        ("bit.lshift(1, 4)", 16),
        ("bit.rshift(16, 2)", 4),
        ("bit.arshift(-16, 2)", -4),
    ]
    for source, expected in bit_checks:
        assert _lua(alice, source) == expected, source
    mixed = _lua(
        alice,
        "local obj = Mixin({ a = 1 }, { b = 2 }, { a = 9 })\n"
        "local made = CreateFromMixins({ x = 5 })\n"
        "return obj.a .. '|' .. obj.b .. '|' .. made.x",
    )
    assert mixed == "9|2|5"
    assert _lua(alice, "issecretvalue(42)") is False


def test_slash_commands_dispatch_and_listing(fake_fs_factory: Any) -> None:
    _world_obj, alice, _bob = _pair(fake_fs_factory)
    assert alice.registered_slash_commands() == ["/prb", "/probe"]
    assert alice.slash("/probe hello world") is True
    assert _lua(alice, "Probe.slash_msg") == "hello world"
    assert alice.slash("/prb second alias") is True
    assert _lua(alice, "Probe.slash_msg") == "second alias"
    assert alice.slash("/nosuchcommand hi") is False
    assert _lua(alice, "Probe.slash_msg") == "second alias"


def test_error_handler_and_client_errors_capture_addon_failures(
    fake_fs_factory: Any,
) -> None:
    files = {
        "/addons/Broken/Broken.toc": (
            "## Interface: 16001\n\nFirst.lua\nBoom.lua\nSyntax.lua\nAfter.lua\n"
        ),
        "/addons/Broken/First.lua": (
            "ProbeErr = {}\nseterrorhandler(function(msg) ProbeErr[#ProbeErr + 1] = msg end)\n"
        ),
        "/addons/Broken/Boom.lua": 'error("boom-runtime")\n',
        "/addons/Broken/Syntax.lua": "local broken =\n",
        "/addons/Broken/After.lua": 'AfterBroken = "still-loaded"\n',
    }
    world = World(fs=fake_fs_factory(files))
    alice = world.client("Alice")
    alice.load_addon("/addons/Broken")
    messages = [record.message for record in alice.errors]
    # [2026-11-11 T-007] Loading continues past both a runtime error and a
    # compile error, each recorded once; the file after them still ran.
    assert any("boom-runtime" in message for message in messages)
    assert any(message.startswith("compile:") for message in messages)
    assert _lua(alice, "#ProbeErr") >= 2
    assert _lua(alice, "AfterBroken") == "still-loaded"
    assert _lua(alice, "type(geterrorhandler())") == "function"
    with pytest.raises(HeadlessError):
        alice.load_addon("/addons/NoSuchAddon")


def test_guild_unit_instance_and_pvp_helpers(fake_fs_factory: Any) -> None:
    _world_obj, alice, bob = _pair(fake_fs_factory)
    checks: list[tuple[str, Any]] = [
        (
            'local g, rn, r, rm = GetGuildInfo("player")\nreturn g.."|"..rn.."|"..r.."|"..rm',
            "Guildhall|Member|2|Forever",
        ),
        ("local t, o = GetNumGuildMembers()\nreturn t .. '|' .. o", "2|2"),
        (
            "local n, rn, r, lv, cf = GetGuildRosterInfo(1)\n"
            "return table.concat({ n, rn, r, lv, cf }, '|')",
            "Alice-Forever|Member|2|80|WARRIOR",
        ),
        ("GetGuildRosterInfo(99)", None),
        ('local n, rm = UnitName("player")\nreturn n .. "-" .. rm', "Alice-Forever"),
        ('local n, rm = UnitFullName("Bob")\nreturn n .. "-" .. rm', "Bob-Forever"),
        ('UnitName("NobodyHere")', None),
        # [2026-11-11 T-007] GUIDs come from creation order, stable across runs.
        ('UnitGUID("player")', "Player-1-00000001"),
        ('UnitGUID("Bob")', "Player-1-00000002"),
        ('UnitIsUnit("player", "Alice")', True),
        ('UnitIsUnit("player", "Bob")', False),
        ('UnitIsInMyGuild("Bob")', True),
        ("IsInGuild()", True),
        ("GetRealmName()", "Forever"),
        ("IsLoggedIn()", True),
        (
            "local v, b, _, i = GetBuildInfo()\nreturn v .. '|' .. b .. '|' .. i",
            "1.60.1|70888|16001",
        ),
    ]
    for source, expected in checks:
        assert _lua(alice, source) == expected, source
    roster_before = _lua(alice, "Probe.roster")
    bob.set_rank(0)
    assert bob.rank_name == "Guild Master"
    assert _lua(alice, "Probe.roster") == roster_before + 1
    assert _lua(alice, "Probe.roster_arg") is True
    bob_guild = _lua(
        alice,
        "local _, rank_name, rank = GetGuildInfo(\"Bob\")\nreturn rank_name .. '|' .. rank",
    )
    assert bob_guild == "Guild Master|0"
    _lua(alice, "C_GuildInfo.GuildRoster()")
    assert _lua(alice, "Probe.roster_arg") is False
    alice.set_instance(
        in_instance=True,
        instance_type="raid",
        name="Keep",
        difficulty_id=14,
        max_players=20,
        instance_id=99,
    )
    in_inst = _lua(
        alice,
        "local inside, kind = IsInInstance()\nreturn tostring(inside) .. '|' .. kind",
    )
    assert in_inst == "true|raid"
    info = _lua(
        alice,
        "local name, kind, diff, _, maxp, _, _, map_id = GetInstanceInfo()\n"
        "return table.concat({ name, kind, diff, maxp, map_id }, '|')",
    )
    assert info == "Keep|raid|14|20|99"
    pvp_before = _lua(alice, "Probe.pvp")
    alice.set_pvp_kills(123)
    assert _lua(alice, "Probe.pvp") == pvp_before + 1
    assert _lua(alice, "GetPVPLifetimeStats()") == 123


def test_deterministic_network_loss_duplicate_and_reorder(
    fake_fs_factory: Any,
) -> None:
    _w1, alice, bob = _pair(fake_fs_factory, loss_rate=1.0, rng_seed=7)
    _lua(bob, "Probe.register()")
    # [2026-11-11 T-007] Loss is a wire property: the sender still sees Success
    # while every copy vanishes before delivery.
    assert _send(alice, "PROBE", "lost", "GUILD") == 0
    assert _received(bob) == ""

    _w2, alice2, bob2 = _pair(fake_fs_factory, duplicate_rate=1.0, rng_seed=7)
    _lua(bob2, "Probe.register()")
    assert _send(alice2, "PROBE", "twice", "GUILD") == 0
    assert _received(bob2).count("twice") == 2

    world3, alice3, bob3 = _pair(fake_fs_factory, reorder_max_delay=5.0, rng_seed=0)
    _lua(bob3, "Probe.register()")
    assert _send(alice3, "PROBE", "slow", "WHISPER", "Bob") == 0
    # [2026-11-11 T-007] With seed 0 the first (only) reorder draw is ~4.22s,
    # so nothing is delivered at send time but the copy lands by t=5.
    assert _received(bob3) == ""
    world3.advance(5.0)
    assert _received(bob3) == "PROBE|slow|WHISPER|Alice-Forever|Bob-Forever"

    world3.set_network(loss_rate=1.0, reorder_max_delay=0.0)
    assert _send(alice3, "PROBE", "gone", "WHISPER", "Bob") == 0
    assert _received(bob3).count("gone") == 0


def test_guildhall_loads_in_world_and_savedvars_python_containers_round_trip() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    world = World()
    alice = world.client("Alice", rank=0)
    assert alice.load_addon(repo_root / "addons" / "Guildhall") == "Guildhall"
    assert alice.errors == []
    assert alice.eval("1 + 1") == 2

    exported = export_saved_value(
        {"arr": [1, 2.5, True, False, None], "empty": [], "map": {True: "yes", 2.0: "two"}},
        var_name="StateDB",
    )
    assert exported["arr"] == [1, 2.5, True, False, None]
    assert exported["map"] == {True: "yes", 2: "two"}
    formatted = format_saved_variables_lua({"StateDB": exported})
    rt = new_runtime()
    run_chunk(rt, formatted, "StateDB.lua")
    reimported = import_saved_value(rt, exported)
    assert export_saved_value(reimported, var_name="StateDB") == {
        "arr": [1, 2.5, True, False],
        "empty": {},
        "map": {True: "yes", 2: "two"},
    }
    cyc: list[Any] = []
    cyc.append(cyc)
    with pytest.raises(SavedVariablesError):
        export_saved_value(cyc, var_name="CycDB")
    with pytest.raises(SavedVariablesError):
        import_saved_value(rt, cyc)


def test_string_namespace_keeps_the_lua_string_library() -> None:
    data = copy.deepcopy(minimal_api_index().data)
    data["entries"]["function"]["string.lower"] = {
        "name": "string.lower",
        "kind": "function",
        "namespace": "string",
        "system": None,
        "args": [],
        "returns": [{"type": "string"}],
        "flags": {},
        "c_api": True,
        "restricted": False,
        "secret": {"args": None, "returns": False, "conditions": []},
        "deprecated": False,
        "documented": True,
        "source": "test",
    }
    client = World(ApiIndex(data)).client("Player", rank=0)
    assert client.eval('string.lower("Ab")') == "ab"
