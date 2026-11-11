"""T-015 acceptance tests for the core building block (created 2026-11-11).

The instantiated addon lives under ``tmp_path``. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from wow_addon_forge.apidocs import IndexStore
from wow_addon_forge.check import check_addon
from wow_addon_forge.headless import World, minimal_api_index
from wow_addon_forge.luavm import new_runtime

BLOCK = Path(__file__).resolve().parents[1] / "src" / "wow_addon_forge" / "blocks" / "core"
TOKEN = "@@ADDON@@"

_SUITE = r"""
return function(codec)
    local encode, decode = codec.encode, codec.decode
    math.randomseed(16001)
    local function rand_string(n)
        local chars = {}
        for i = 1, n do
            chars[i] = string.char(math.random(1, 255))
        end
        return table.concat(chars)
    end
    local function rand_value(depth)
        local roll = math.random(1, 5)
        if roll == 1 then return math.random(0, 1) == 1 end
        if roll == 2 then return math.random(-100000, 100000) end
        if roll == 3 then return (math.random() - 0.5) * 1000 end
        if roll == 4 or depth >= 3 then return rand_string(math.random(0, 12)) end
        local out = {}
        local count = math.random(0, 4)
        for i = 1, count do
            out["k" .. i] = rand_value(depth + 1)
        end
        return out
    end
    local function same(a, b)
        if type(a) ~= type(b) then return false end
        if type(a) ~= "table" then return a == b end
        for key, value in pairs(a) do
            if not same(value, b[key]) then return false end
        end
        for key in pairs(b) do
            if a[key] == nil then return false end
        end
        return true
    end
    local covered = {}
    for byte = 1, 255 do covered[byte] = false end
    local trips = 0
    for i = 1, 500 do
        local value = rand_value(0)
        local text, err = encode(value)
        if text == nil then return false, "encode failed: " .. tostring(err) end
        if text:find("\0", 1, true) then return false, "encoder emitted byte 0" end
        for pos = 1, #text do
            if string.byte(text, pos) == 0 then return false, "encoder emitted byte 0" end
        end
        local back, back_err = decode(text)
        if back_err ~= nil or not same(value, back) then
            return false, "round trip " .. i .. " failed: " .. tostring(back_err)
        end
        trips = trips + 1
    end
    local every = {}
    for byte = 1, 255 do every[byte] = string.char(byte) end
    local all_bytes = table.concat(every)
    local encoded = encode(all_bytes)
    if encoded == nil or encoded:find("\0", 1, true) then
        return false, "all-byte string did not encode"
    end
    local decoded, decoded_err = decode(encoded)
    if decoded ~= all_bytes then
        return false, "all-byte string did not round-trip: " .. tostring(decoded_err)
    end
    local sample, sample_err = encode({ n = 7, ok = true, name = "core" })
    if sample == nil then return false, tostring(sample_err) end
    local hostile = {
        "",
        "Z",
        "I;",
        "I12",
        "H;",
        "H000000000000000;",
        "S1:0;",
        "S1:GG",
        "S0",
        "{",
        "{1}",
        "{1S1:61",
        sample:sub(1, #sample - 1),
        sample .. "X",
        "\0",
        "T\0",
    }
    local rejected = 0
    for i = 1, 200 do
        local mutated = hostile[((i - 1) % #hostile) + 1]
        if i % #hostile == 0 then
            mutated = mutated .. string.char((i % 255) + 1)
        end
        local value, err = decode(mutated)
        if value ~= nil or type(err) ~= "string" or err == "" then
            return false, "mutation " .. i .. " was not rejected"
        end
        rejected = rejected + 1
    end
    return true, trips, rejected
end
"""


def test_codec_round_trips_and_rejects_mutations() -> None:
    runtime = new_runtime(sandbox=True)
    source = (BLOCK / "Core" / "Codec.lua").read_text(encoding="utf-8")
    assert "loadstring(" not in source
    loaded = runtime.execute(source)
    suite = runtime.execute(_SUITE)(loaded)
    if suite[0] is not True:
        raise AssertionError(suite[1])
    assert suite[1] == 500
    assert suite[2] == 200


def test_store_migrates_a_version_1_fixture() -> None:
    runtime = new_runtime(sandbox=True)
    source = (BLOCK / "Core" / "Store.lua").read_text(encoding="utf-8")
    store = runtime.execute(source)
    migrated = runtime.execute(
        'return function(store) return store.migrate({ schema = 1, note = "v1", kept = 4 }) end'
    )(store)
    assert migrated["schema"] == 2
    assert migrated["migrated_from"] == 1
    assert migrated["note"] == "v1"
    assert migrated["kept"] == 4


def _instantiate(dest: Path, name: str) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    for path in BLOCK.rglob("*"):
        if not path.is_file() or path.name == "addon.toc":
            continue
        relative = path.relative_to(BLOCK)
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(path.read_text(encoding="utf-8").replace(TOKEN, name), encoding="utf-8")
    toc = (BLOCK / "addon.toc").read_text(encoding="utf-8").replace(TOKEN, name)
    (dest / f"{name}.toc").write_text(toc, encoding="utf-8")


def test_instantiated_addon_passes_wow_check_and_registers_its_slash(tmp_path: Path) -> None:
    name = "Sample"
    addon = tmp_path / name
    _instantiate(addon, name)
    rendered = (addon / "Core" / "Slash.lua").read_text(encoding="utf-8")
    assert TOKEN not in rendered
    assert name in rendered
    IndexStore(tmp_path / "index").save(minimal_api_index().data)
    report: dict[str, Any] = check_addon(addon, index=minimal_api_index())
    assert report["verdict"] == "pass", report["findings"]
    world = World(index=minimal_api_index())
    client = world.client("Alice")
    client.load_addon(str(addon))
    assert client.slash("/sample") is True
    assert client.run_lua('return SlashCmdList["SAMPLE"] ~= nil') is True
    assert client.run_lua("return Sample.Slash.token") == "/sample"
    assert client.run_lua("return type(Sample.Clock.now())") == "number"
    db = client.run_lua("return SampleDB.schema")
    assert db == 2
