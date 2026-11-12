"""Tests for the API index: mirror fetching, index building, lookups and the cache
(created 2026-11-11, T-005).

Invariants owned by this file:
- Hermetic: no network, no real clock, no ``~/.hermes``: every ``ForgeTools`` gets
  ``fetcher=``, ``cache_dir=tmp_path``, ``clock=``; every ``IndexStore`` uses tmp_path.
- No Blizzard source is copied: the Lua below is small, hand-written, invented data in
  Blizzard's documentation-table format.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from conftest import MAC_ROOT, FakeFileSystem, forever_install_files

from wow_addon_forge import luavm
from wow_addon_forge.apidocs import (
    KINDS,
    RESOURCE_FILES,
    SCHEMA_VERSION,
    ApiIndex,
    ApiIndexError,
    IndexStore,
    SourceBundle,
    UrlFetcher,
    build_index,
    default_cache_dir,
    fetch_mirror_bundle,
    load_export_bundle,
    normalise_flavor,
)
from wow_addon_forge.luavm import LuaChunkError

GENERATED_AT = 1_800_000_000.0

FORGE_CHAT_DOC = """
APIDocumentation:AddDocumentationTable({
    Name = "ForgeChat",
    Type = "System",
    Namespace = "C_ForgeChat",
    Functions = {
        {
            Name = "SendPing",
            Type = "Function",
            SecretArguments = "NotAllowed",
            Arguments = {
                { Name = "prefix", Type = "string" },
                { Name = "message", Type = "string" },
                { Name = "chatType", Type = "ForgeAspect", Nilable = true,
                  Default = Enum.ForgeAspect.Text },
                { Name = "target", Type = "string", Nilable = true, Default = "none" },
            },
            Returns = {
                { Name = "result", Type = "ForgePingResult" },
            },
        },
        {
            Name = "GetSecretScore",
            Type = "Function",
            HasRestrictions = true,
            SecretReturns = true,
            SecretArguments = "AllowedWhenUntainted",
            Arguments = {},
            Returns = {
                { Name = "score", Type = "number", ConditionalSecret = true },
            },
        },
        {
            Name = "InForgeLockdown",
            Type = "Function",
            Namespace = "",
            Arguments = {},
            Returns = {
                { Name = "locked", Type = "bool" },
            },
        },
    },
    Events = {
        {
            Name = "ForgePing",
            Type = "Event",
            LiteralName = "FORGE_PING",
            Payload = {
                { Name = "prefix", Type = "string" },
                { Name = "message", Type = "string" },
            },
        },
        {
            Name = "ForgeLogUnfiltered",
            Type = "Event",
            LiteralName = "FORGE_LOG_UNFILTERED",
            HasRestrictions = true,
            SynchronousEvent = true,
            CallbackEvent = true,
        },
    },
    Tables = {
        {
            Name = "ForgePingResult",
            Type = "Enumeration",
            Fields = {
                { Name = "Success", Type = "ForgePingResult", EnumValue = 0 },
                { Name = "Throttled", Type = "ForgePingResult", EnumValue = 1 },
            },
        },
        {
            Name = "ForgePingInfo",
            Type = "Structure",
            Fields = {
                { Name = "sender", Type = "string" },
                { Name = "count", Type = "number" },
            },
        },
        {
            Name = "ForgeChatConstants",
            Type = "Constants",
            Values = {
                { Name = "MAX_LENGTH", Type = "number", Value = 255 },
            },
        },
    },
})
"""

FORGE_FRAME_DOC = """
APIDocumentation:AddDocumentationTable({
    Name = "ForgeFrameAPI",
    Type = "ScriptObject",
    Functions = {
        {
            Name = "SetForgeAlpha",
            Type = "Function",
            Arguments = {
                { Name = "alpha", Type = "number" },
            },
            Returns = {},
        },
    },
    Events = {},
    Tables = {},
})
"""

BROKEN_DOC = "local x = 7 // 2\n"

# [2026-11-11 T-044] The export fixture doc reads no Enum.* value while building its
# table: a client export carries no LuaEnum.lua resource, so an Enum-reading file
# would fail in build_index with a warning (the limitation T-045 verifies for real).
FORGE_EXPORT_DOC = """
APIDocumentation:AddDocumentationTable({
    Name = "ForgeExport",
    Type = "System",
    Namespace = "C_ForgeExport",
    Functions = {
        {
            Name = "SendExportPing",
            Type = "Function",
            Arguments = {
                { Name = "message", Type = "string" },
            },
            Returns = {
                { Name = "sent", Type = "bool" },
            },
        },
    },
    Events = {},
    Tables = {},
})
"""

_EXPORT_TOC = "## Interface: 16001\nForgeExportDocumentation.lua\nForgeFrameAPIDocumentation.lua\n"

EXPORT_DOC_DIR = (
    f"{MAC_ROOT}/_forever_/BlizzardInterfaceCode"
    "/Interface/AddOns/Blizzard_APIDocumentationGenerated"
)


def fixture_export_files() -> dict[str, str]:
    """Return a fake install whose ``_forever_`` flavor holds a client export."""
    files = forever_install_files()
    files[f"{EXPORT_DOC_DIR}/Blizzard_APIDocumentationGenerated.toc"] = _EXPORT_TOC
    files[f"{EXPORT_DOC_DIR}/ForgeExportDocumentation.lua"] = FORGE_EXPORT_DOC
    files[f"{EXPORT_DOC_DIR}/ForgeFrameAPIDocumentation.lua"] = FORGE_FRAME_DOC
    return files


_DOCUMENTATION: dict[str, str] = {
    "ForgeChatDocumentation.lua": FORGE_CHAT_DOC,
    "ForgeFrameAPIDocumentation.lua": FORGE_FRAME_DOC,
    "BrokenDocumentation.lua": BROKEN_DOC,
}

_RESOURCES: dict[str, str] = {
    "LuaEnum.lua": (
        "Enum = { ForgeAspect = { Text = 1, Alpha = 2 }, "
        "ForgeOnlyInLuaEnum = { A = 0 } }\n"
        "Constants = { ForgeLuaConstants = { LIMIT = 16 } }\n"
    ),
    "GlobalAPI.lua": (
        'return {{"C_ForgeChat.SendPing", "C_ForgeItem.GetForgeInfo", '
        '"C_ForgeStore.GetForgeInfo", "UndocumentedForgeCall"}, {"wipe"}}'
    ),
    "Events.lua": (
        'return { ForgeChat = {"FORGE_PING"}, ForgeMisc = {"FORGE_UNDOCUMENTED_EVENT"} }'
    ),
    "FrameXML.lua": 'return {{"ForgeHelper", "GetForgeInfo"}, {"ForgeLoadOnDemandHelper"}}',
    "WidgetAPI.lua": (
        'return { Frame = { inherits = {"Region"}, methods = {"SetScript", "Show"} }, '
        'Region = { inherits = {}, methods = {"GetWidth"} } }'
    ),
    "Templates.lua": (
        'return { ["ForgeButtonTemplate"] = {type = "Button", '
        'inherits = "ForgeBaseTemplate"}, ["ForgeBaseTemplate"] = {type = "Frame"} }'
    ),
    "Mixins.lua": 'return {"ForgeWindowMixin"}',
}

_TOC = (
    "## Interface: 16001\n"
    "## Title: Forge API Documentation\n"
    "# a comment line\n"
    "ForgeChatDocumentation.lua\n"
    "ForgeFrameAPIDocumentation.lua\n"
    "BrokenDocumentation.lua\n"
)

# [2026-11-11 T-005] The raw-host prefix is private in apidocs.py, so the mirror URLs are
# built from the documented layout instead of importing a private constant.
_GETHE = "https://raw.githubusercontent.com/Gethe/wow-ui-source/forever"
_KETHO = "https://raw.githubusercontent.com/Ketho/BlizzardInterfaceResources/forever/Resources"
_DOC_DIR = f"{_GETHE}/Interface/AddOns/Blizzard_APIDocumentationGenerated"


def fixture_bundle() -> SourceBundle:
    """Return a fresh canned mirror bundle for the invented Forge API."""
    return SourceBundle(
        flavor="forever",
        build="1.60.1.70888",
        source="mirror",
        documentation=dict(_DOCUMENTATION),
        resources=dict(_RESOURCES),
    )


def fixture_mirror_files() -> dict[str, str]:
    """Return the url -> text mapping one ``forever`` mirror sync fetches."""
    files: dict[str, str] = {
        f"{_GETHE}/version.txt": "1.60.1.70888\n",
        f"{_DOC_DIR}/Blizzard_APIDocumentationGenerated.toc": _TOC,
    }
    for name, text in _DOCUMENTATION.items():
        files[f"{_DOC_DIR}/{name}"] = text
    for name, text in _RESOURCES.items():
        files[f"{_KETHO}/{name}"] = text
    return files


class FakeFetcher:
    """Canned ``Fetcher``: records every requested url, never touches a socket."""

    def __init__(self, files: dict[str, str]) -> None:
        self._files = dict(files)
        self.urls: list[str] = []
        self._lock = threading.Lock()

    def fetch_text(self, url: str) -> str:
        """Return the canned text for ``url``, or raise ``fetch-failed``."""
        with self._lock:
            self.urls.append(url)
        if url not in self._files:
            raise ApiIndexError(
                "fetch-failed",
                f"{url}: no canned mirror file",
                "Add the url to the FakeFetcher files.",
            )
        return self._files[url]


def built_data(bundle: SourceBundle | None = None) -> dict[str, Any]:
    """Build the fixture index at a fixed time (no real clock)."""
    active = bundle if bundle is not None else fixture_bundle()
    return build_index(active, generated_at=GENERATED_AT)


def entry(data: dict[str, Any], kind: str, name: str) -> dict[str, Any]:
    """Return one index entry by kind and name."""
    result: dict[str, Any] = data["entries"][kind][name]
    return result


def test_a_documented_send_ping_signature_and_secrets() -> None:
    """A: C_ForgeChat.SendPing carries its documented signature and secret facts."""
    send = entry(built_data(), "function", "C_ForgeChat.SendPing")
    assert send["kind"] == "function"
    assert send["namespace"] == "C_ForgeChat"
    assert [arg["name"] for arg in send["args"]] == ["prefix", "message", "chatType", "target"]
    assert [arg["type"] for arg in send["args"]] == ["string", "string", "ForgeAspect", "string"]
    assert [arg["nilable"] for arg in send["args"]] == [False, False, True, True]
    # [2026-11-11 T-005] chatType's default is Enum.ForgeAspect.Text: it is 1 only
    # because LuaEnum.lua ran before the documentation files.
    assert send["args"][2]["default"] == 1
    assert send["args"][3]["default"] == "none"
    assert send["returns"] == [{"name": "result", "type": "ForgePingResult", "nilable": False}]
    assert send["restricted"] is False
    assert send["secret"]["args"] == "NotAllowed"
    assert send["secret"]["returns"] is False
    assert send["deprecated"] is False
    assert send["documented"] is True
    assert send["c_api"] is True


def test_b_get_secret_score_restricted_and_secret() -> None:
    """B: GetSecretScore is restricted, with function- and field-level secret conditions."""
    score = entry(built_data(), "function", "C_ForgeChat.GetSecretScore")
    assert score["restricted"] is True
    assert score["secret"]["args"] == "AllowedWhenUntainted"
    assert score["secret"]["returns"] is True
    assert "SecretReturns" in score["secret"]["conditions"]
    assert "score:ConditionalSecret" in score["secret"]["conditions"]
    assert score["flags"]["HasRestrictions"] is True


def test_c_empty_function_namespace_is_bare_global() -> None:
    """C: a function with Namespace = "" is a bare global with namespace None."""
    data = built_data()
    assert "C_ForgeChat.InForgeLockdown" not in data["entries"]["function"]
    lockdown = entry(data, "function", "InForgeLockdown")
    assert lockdown["name"] == "InForgeLockdown"
    assert lockdown["namespace"] is None


def test_d_events_documented_and_from_events_resource() -> None:
    """D: documented events carry flags/payload; Events.lua-only events are undocumented."""
    data = built_data()
    log = entry(data, "event", "FORGE_LOG_UNFILTERED")
    assert log["restricted"] is True
    assert log["flags"]["HasRestrictions"] is True
    assert log["flags"]["SynchronousEvent"] is True
    assert log["flags"]["CallbackEvent"] is True
    ping = entry(data, "event", "FORGE_PING")
    assert ping["restricted"] is False
    assert ping["documented"] is True
    assert [arg["name"] for arg in ping["args"]] == ["prefix", "message"]
    undocumented = entry(data, "event", "FORGE_UNDOCUMENTED_EVENT")
    assert undocumented["documented"] is False
    assert undocumented["source"] == "Events.lua"


def test_e_enums_constants_and_structure() -> None:
    """E: enums merge documentation and LuaEnum.lua; Constants/Structure are tables."""
    data = built_data()
    result = entry(data, "enum", "Enum.ForgePingResult")
    assert result["values"] == {"Success": 0, "Throttled": 1}
    assert result["documented"] is True
    only_lua = entry(data, "enum", "Enum.ForgeOnlyInLuaEnum")
    assert only_lua["values"] == {"A": 0}
    assert only_lua["documented"] is False
    assert only_lua["source"] == "LuaEnum.lua"
    for enum_entry in data["entries"]["enum"].values():
        assert {"restricted", "secret", "deprecated"} <= set(enum_entry)
    constants = entry(data, "table", "Constants.ForgeChatConstants")
    assert constants["kind"] == "table"
    assert constants["table_type"] == "Constants"
    assert constants["values"] == {"MAX_LENGTH": 255}
    structure = entry(data, "table", "ForgePingInfo")
    assert structure["kind"] == "table"
    assert structure["table_type"] == "Structure"
    assert [field["name"] for field in structure["fields"]] == ["sender", "count"]


def test_f_every_entry_carries_the_common_keys() -> None:
    """F: every entry of every kind has the common answer keys."""
    data = built_data()
    required = {"name", "kind", "restricted", "secret", "deprecated", "documented", "source"}
    seen = 0
    for kind, by_name in data["entries"].items():
        for name, item in by_name.items():
            assert required <= set(item), f"{kind} {name} is missing a common key"
            assert item["name"] == name
            assert item["kind"] == kind
            seen += 1
    assert seen > 0


def test_g_resource_merge_never_overwrites_documentation() -> None:
    """G: GlobalAPI/FrameXML fill gaps, deprecate the Lua spelling, keep documented entries."""
    data = built_data()
    undocumented = entry(data, "function", "UndocumentedForgeCall")
    assert undocumented["documented"] is False
    assert undocumented["c_api"] is True
    assert undocumented["source"] == "GlobalAPI.lua"
    helper = entry(data, "function", "ForgeHelper")
    assert helper["c_api"] is False
    assert helper["source"] == "FrameXML.lua"
    assert helper["deprecated"] is False
    legacy = entry(data, "function", "GetForgeInfo")
    assert legacy["c_api"] is False
    assert legacy["deprecated"] is True
    assert legacy["replacement"] == "C_ForgeItem.GetForgeInfo"
    send = entry(data, "function", "C_ForgeChat.SendPing")
    assert send["documented"] is True
    assert send["source"] == "documentation"
    assert len(send["args"]) == 4


def test_h_script_object_widget_template_and_mixin() -> None:
    """H: ScriptObject/WidgetAPI methods, templates and mixins land in their kinds."""
    data = built_data()
    method = entry(data, "widget-method", "ForgeFrameAPI:SetForgeAlpha")
    assert method["widget"] == "ForgeFrameAPI"
    assert [arg["name"] for arg in method["args"]] == ["alpha"]
    frame_method = entry(data, "widget-method", "Frame:SetScript")
    assert frame_method["widget"] == "Frame"
    assert frame_method["source"] == "WidgetAPI.lua"
    assert data["widgets"]["Frame"]["inherits"] == ["Region"]
    template = entry(data, "template", "ForgeButtonTemplate")
    assert template["widget"] == "Button"
    assert template["inherits"] == "ForgeBaseTemplate"
    mixin = entry(data, "table", "ForgeWindowMixin")
    assert mixin["kind"] == "table"
    assert mixin["table_type"] == "Mixin"


def test_i_broken_doc_file_is_a_warning_and_counts_match() -> None:
    """I: the Lua 5.3 file is a warning naming the file; the build still succeeds."""
    data = built_data()
    assert any("BrokenDocumentation.lua" in warning for warning in data["warnings"])
    assert set(data["counts"]) == set(KINDS)
    for kind in KINDS:
        assert data["counts"][kind] == len(data["entries"][kind])
    assert data["documentation_files"] == 3
    assert data["documentation_files"] == len(fixture_bundle().documentation)


def test_j_missing_resource_is_a_warning_not_an_exception() -> None:
    """J: deleting Mixins.lua from the bundle warns and the build still succeeds."""
    bundle = fixture_bundle()
    del bundle.resources["Mixins.lua"]
    data = built_data(bundle)
    assert any("Mixins.lua" in warning for warning in data["warnings"])
    assert "ForgeWindowMixin" not in data["entries"]["table"]


def test_k_built_index_survives_json_round_trip() -> None:
    """K: the built index is plain data, unchanged by json.dumps/json.loads."""
    data = built_data()
    assert json.loads(json.dumps(data)) == data


def test_l_lookup_found_typo_namespaced_only_and_nonsense() -> None:
    """L: lookup answers hits, and misses with nearest/candidate guidance."""
    index = ApiIndex(built_data())
    function_hit = index.lookup("C_ForgeChat.SendPing")
    assert function_hit["found"] is True
    assert function_hit["kind"] == "function"
    event_hit = index.lookup("FORGE_PING")
    assert event_hit["found"] is True
    assert event_hit["kind"] == "event"
    typo = index.lookup("GetForgeInfoo")
    assert typo["found"] is False
    assert typo["kind"] == "unknown"
    assert "GetForgeInfo" in typo["nearest"]
    bare = index.lookup("SendPing")
    assert bare["found"] is False
    assert bare["kind"] == "unknown"
    assert bare["c_api"] is False
    assert bare["same_name_in_namespaces"] == ["C_ForgeChat.SendPing"]
    assert bare["replacement"] == "C_ForgeChat.SendPing"
    assert "not a C API function" in bare["message"]
    assert "C_ForgeChat.SendPing" in bare["message"]
    nonsense = index.lookup("Zzzzqqqq")
    assert nonsense["found"] is False
    assert nonsense["same_name_in_namespaces"] == []
    assert nonsense["replacement"] is None
    assert "not in the API index" in nonsense["message"]


def test_m_namespace_candidate_ranking_prefers_matching_namespace() -> None:
    """M: with no Lua-defined GetForgeInfo, the matching namespace candidate ranks first."""
    bundle = fixture_bundle()
    bundle.resources["FrameXML.lua"] = 'return {{"ForgeHelper"}, {"ForgeLoadOnDemandHelper"}}'
    index = ApiIndex(built_data(bundle))
    miss = index.lookup("GetForgeInfo")
    assert miss["found"] is False
    assert miss["same_name_in_namespaces"] == [
        "C_ForgeItem.GetForgeInfo",
        "C_ForgeStore.GetForgeInfo",
    ]
    assert miss["replacement"] == "C_ForgeItem.GetForgeInfo"


def test_n_search_case_insensitive_sorted_limited_and_blank() -> None:
    """N: search is case-insensitive, kind-ordered, truncation-aware and rejects blank."""
    index = ApiIndex(built_data())
    found = index.search("FORGE")
    assert found["total"] > 1
    assert found["returned"] == found["total"]
    keys = [(KINDS.index(item["kind"]), item["name"]) for item in found["results"]]
    assert keys == sorted(keys)
    for item in found["results"]:
        assert {"name", "kind", "restricted", "deprecated"} <= set(item)
    limited = index.search("forge", limit=1)
    assert limited["truncated"] is True
    assert limited["returned"] == 1
    assert limited["total"] > limited["returned"]
    with pytest.raises(ApiIndexError) as exc:
        index.search("  ")
    assert exc.value.code == "bad-argument"


def test_o_events_listing_filter_and_truncation() -> None:
    """O: events() lists sorted names, filters case-insensitively and reports truncation."""
    index = ApiIndex(built_data())
    all_events = index.events()
    names = [item["name"] for item in all_events["events"]]
    assert names == sorted(names)
    assert names == ["FORGE_LOG_UNFILTERED", "FORGE_PING", "FORGE_UNDOCUMENTED_EVENT"]
    filtered = index.events("log")
    assert [item["name"] for item in filtered["events"]] == ["FORGE_LOG_UNFILTERED"]
    assert filtered["events"][0]["restricted"] is True
    limited = index.events(limit=1)
    assert limited["truncated"] is True
    assert limited["returned"] == 1
    assert limited["total"] > limited["returned"]


def test_p_status_reports_build_age_and_warnings() -> None:
    """P: status(now=) reports build facts and a never-negative age from generated_at."""
    data = built_data()
    index = ApiIndex(data)
    status = index.status(now=GENERATED_AT + 90.0)
    assert status["build"] == "1.60.1.70888"
    assert status["flavor"] == "forever"
    assert status["source"] == "mirror"
    assert status["schema"] == SCHEMA_VERSION
    assert status["counts"] == data["counts"]
    assert status["age_seconds"] == 90
    assert index.status(now=GENERATED_AT - 10.0)["age_seconds"] == 0
    assert status["generated_at_utc"].endswith("Z")
    assert status["warning_count"] >= 1
    assert status["warnings_truncated"] is False


def test_q_api_index_rejects_wrong_schema_and_missing_entries() -> None:
    """Q: a wrong schema, and data without entries, are both stale-index."""
    with pytest.raises(ApiIndexError) as wrong:
        ApiIndex({"schema": SCHEMA_VERSION + 99, "entries": {}})
    assert wrong.value.code == "stale-index"
    with pytest.raises(ApiIndexError) as missing:
        ApiIndex({"schema": SCHEMA_VERSION})
    assert missing.value.code == "stale-index"


def test_r_index_store_round_trip_and_refusals(tmp_path: Path) -> None:
    """R: IndexStore round-trips, and every bad-cache shape is no-/stale-/bad-argument."""
    store = IndexStore(tmp_path / "cache")
    saved = Path(store.save(built_data()))
    assert saved.name == "forever-1.60.1.70888.json"
    assert saved.parent == tmp_path / "cache"
    assert saved.exists()
    pointer = tmp_path / "cache" / "forever.current"
    assert pointer.read_text(encoding="utf-8") == saved.name
    assert store.load("forever").lookup("C_ForgeChat.SendPing")["found"] is True
    with pytest.raises(ApiIndexError) as empty:
        IndexStore(tmp_path / "empty").load("forever")
    assert empty.value.code == "no-index"
    assert "sync" in empty.value.hint
    missing_dir = tmp_path / "missing"
    missing_dir.mkdir()
    (missing_dir / "forever.current").write_text("forever-9.9.9.99999.json", encoding="utf-8")
    with pytest.raises(ApiIndexError) as missing:
        IndexStore(missing_dir).load("forever")
    assert missing.value.code == "no-index"
    escape_dir = tmp_path / "escape"
    escape_dir.mkdir()
    (escape_dir / "forever.current").write_text("../x.json", encoding="utf-8")
    with pytest.raises(ApiIndexError) as escape:
        IndexStore(escape_dir).load("forever")
    assert escape.value.code == "no-index"
    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    (corrupt_dir / "forever-1.60.1.70888.json").write_text("not json {", encoding="utf-8")
    (corrupt_dir / "forever.current").write_text("forever-1.60.1.70888.json", encoding="utf-8")
    with pytest.raises(ApiIndexError) as corrupt:
        IndexStore(corrupt_dir).load("forever")
    assert corrupt.value.code == "stale-index"
    evil_data = built_data()
    evil_data["build"] = "../evil"
    with pytest.raises(ApiIndexError) as evil:
        IndexStore(tmp_path / "evil").save(evil_data)
    assert evil.value.code == "bad-argument"
    assert not (tmp_path / "evil").exists()


def test_s_normalise_flavor_accepts_and_rejects() -> None:
    """S: None/blank/_forever_/Forever normalise to forever; retail and 5 are bad-argument."""
    for value in (None, "", "forever", "_forever_", " Forever "):
        assert normalise_flavor(value) == "forever"
    for value in ("retail", 5):
        with pytest.raises(ApiIndexError) as exc:
            normalise_flavor(value)
        assert exc.value.code == "bad-argument"


def test_t_fetch_mirror_bundle_and_mirror_refusals() -> None:
    """T: the mirror bundle fetches the layout above and refuses bad mirror data/names."""
    fetcher = FakeFetcher(fixture_mirror_files())
    bundle = fetch_mirror_bundle(fetcher, "forever")
    assert bundle.build == "1.60.1.70888"
    assert bundle.source == "mirror"
    assert bundle.flavor == "forever"
    assert set(bundle.documentation) == {
        "ForgeChatDocumentation.lua",
        "ForgeFrameAPIDocumentation.lua",
        "BrokenDocumentation.lua",
    }
    assert set(bundle.resources) == set(RESOURCE_FILES)
    assert len(bundle.resources) == 7
    assert fetcher.urls
    assert all(url.startswith("https://raw.githubusercontent.com/") for url in fetcher.urls)
    files = fixture_mirror_files()
    doc_url = next(url for url in files if url.endswith("ForgeChatDocumentation.lua"))
    del files[doc_url]
    with pytest.raises(ApiIndexError) as missing:
        fetch_mirror_bundle(FakeFetcher(files), "forever")
    assert missing.value.code == "fetch-failed"
    files = fixture_mirror_files()
    version_url = next(url for url in files if url.endswith("version.txt"))
    files[version_url] = "not a version"
    with pytest.raises(ApiIndexError) as version:
        fetch_mirror_bundle(FakeFetcher(files), "forever")
    assert version.value.code == "bad-mirror-data"
    files = fixture_mirror_files()
    toc_url = next(url for url in files if url.endswith(".toc"))
    files[toc_url] = "## Interface: 16001\n## Title: None\n# no files\n"
    with pytest.raises(ApiIndexError) as no_lua:
        fetch_mirror_bundle(FakeFetcher(files), "forever")
    assert no_lua.value.code == "bad-mirror-data"
    files = fixture_mirror_files()
    # [2026-11-11 T-005] Both spellings of an escaping TOC name must be refused:
    # parse_toc normalises the backslash form to ../evil.lua before apidocs sees it.
    files[toc_url] = files[toc_url] + "..\\evil.lua\nsub/evil.lua\n"
    evil_fetcher = FakeFetcher(files)
    evil_bundle = fetch_mirror_bundle(evil_fetcher, "forever")
    assert any("evil.lua" in warning for warning in evil_bundle.warnings)
    assert all("evil" not in url for url in evil_fetcher.urls)
    assert set(evil_bundle.documentation) == set(bundle.documentation)


def test_u_url_fetcher_refusals_decoding_and_failures() -> None:
    """U: UrlFetcher refuses non-raw urls, decodes UTF-8, and wraps opener failures."""
    opened: list[str] = []

    def opener(url: str, timeout: float) -> bytes:
        opened.append(url)
        return "héllo".encode()

    def failing(url: str, timeout: float) -> bytes:
        raise OSError("no route")

    fetcher = UrlFetcher(opener=opener)
    with pytest.raises(ApiIndexError) as refused:
        fetcher.fetch_text("https://example.com/file.lua")
    assert refused.value.code == "fetch-refused"
    assert opened == []
    good_url = "https://raw.githubusercontent.com/Gethe/wow-ui-source/forever/version.txt"
    assert fetcher.fetch_text(good_url) == "héllo"
    assert opened == [good_url]
    with pytest.raises(ApiIndexError) as failed:
        UrlFetcher(opener=failing).fetch_text(good_url)
    assert failed.value.code == "fetch-failed"
    assert good_url in failed.value.message


def test_v_default_cache_dir_honours_hermes_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """V: default_cache_dir honours get_hermes_home(), HERMES_HOME, else ~/.hermes."""
    import sys
    import types

    profile_home = tmp_path / "profiles" / "officer"
    fake_constants = types.ModuleType("hermes_constants")
    fake_constants.get_hermes_home = lambda: profile_home  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_constants", fake_constants)
    profile_expected = profile_home / "cache" / "wow-addon-forge" / "api-index"
    assert default_cache_dir() == profile_expected
    assert not profile_expected.exists()

    # Module present without callable get_hermes_home falls back to HERMES_HOME:
    monkeypatch.setitem(sys.modules, "hermes_constants", types.ModuleType("hermes_constants"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert default_cache_dir() == tmp_path / "cache" / "wow-addon-forge" / "api-index"

    # Standalone fallback when hermes_constants is absent:
    monkeypatch.delitem(sys.modules, "hermes_constants")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    expected = tmp_path / "cache" / "wow-addon-forge" / "api-index"
    assert default_cache_dir() == expected
    assert not expected.exists()
    fake_home = tmp_path / "home"
    monkeypatch.delenv("HERMES_HOME")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    fallback = fake_home / ".hermes" / "cache" / "wow-addon-forge" / "api-index"
    assert default_cache_dir() == fallback
    assert not fallback.exists()


def test_w_run_chunk_value_and_lua_to_python() -> None:
    """W: run_chunk_value phases, and lua_to_python shape rules including cycles."""
    runtime = luavm.new_runtime()
    assert luavm.run_chunk_value(runtime, "return 42, 99", "Value.lua") == 42
    assert luavm.run_chunk_value(runtime, "local x = 1", "None.lua") is None
    with pytest.raises(LuaChunkError) as compile_exc:
        luavm.run_chunk_value(runtime, "local x = 7 // 2", "Bad.lua")
    assert compile_exc.value.phase == "compile"
    with pytest.raises(LuaChunkError) as runtime_exc:
        luavm.run_chunk_value(runtime, 'error("boom")', "Boom.lua")
    assert runtime_exc.value.phase == "runtime"
    assert "boom" in runtime_exc.value.message
    assert luavm.lua_to_python(runtime.eval("{10, 20, 30}")) == [10, 20, 30]
    assert luavm.lua_to_python(runtime.eval("{10, 20, x = 3}")) == {"1": 10, "2": 20, "x": 3}
    assert luavm.lua_to_python(runtime.eval("{a = 1, b = 'x'}")) == {"a": 1, "b": "x"}
    assert luavm.lua_to_python(runtime.eval("{}")) == []
    assert luavm.lua_to_python(runtime.eval("{a = {b = {1, 2}}}")) == {"a": {"b": [1, 2]}}
    integral = luavm.lua_to_python(2.0)
    assert integral == 2
    assert isinstance(integral, int)
    fractional = luavm.lua_to_python(1.5)
    assert fractional == 1.5
    assert isinstance(fractional, float)
    assert luavm.lua_to_python(runtime.eval("true")) is True
    assert luavm.lua_to_python(runtime.eval("false")) is False
    assert luavm.lua_to_python(runtime.eval("function() return 1 end")) is None
    cyclic = runtime.eval("(function() local t = {} t.self = t return t end)()")
    with pytest.raises(ValueError, match="deeper than 40"):
        luavm.lua_to_python(cyclic)


def test_x_nameless_constants_documentation_tables_are_indexed() -> None:
    """X: nameless *ConstantsDocumentation tables index Enums/Structures without warning."""
    bundle = fixture_bundle()
    del bundle.documentation["BrokenDocumentation.lua"]
    bundle.documentation["ForgeConstantsDocumentation.lua"] = """
APIDocumentation:AddDocumentationTable({
    Predicates = {},
    Tables = {
        {
            Name = "ForgeBagFlags",
            Type = "Enumeration",
            Fields = {
                { Name = "None", Type = "ForgeBagFlags", EnumValue = 0 },
                { Name = "Locked", Type = "ForgeBagFlags", EnumValue = 1 },
            },
        },
        {
            Name = "ForgeSlotState",
            Type = "Structure",
            Fields = {
                { Name = "slot", Type = "number" },
            },
        },
    },
})
APIDocumentation:AddDocumentationTable({})
"""
    data = built_data(bundle)
    bag_enum = entry(data, "enum", "Enum.ForgeBagFlags")
    assert bag_enum["documented"] is True
    assert bag_enum["values"] == {"None": 0, "Locked": 1}
    slot_struct = entry(data, "table", "ForgeSlotState")
    assert slot_struct["documented"] is True
    assert slot_struct["table_type"] == "Structure"
    assert data["warnings"] == [
        "Skipped malformed documentation table without Name or declarations."
    ]


def test_y_export_bundle_indexes_local_docs() -> None:
    """Y: a fake install's BlizzardInterfaceCode export becomes an export bundle."""
    bundle = load_export_bundle(FakeFileSystem(fixture_export_files()), None, "forever")
    assert bundle is not None
    assert bundle.source == "export"
    assert bundle.build == "1.60.1.70888"
    assert sorted(bundle.documentation) == [
        "ForgeExportDocumentation.lua",
        "ForgeFrameAPIDocumentation.lua",
    ]
    assert bundle.resources == {}
    assert bundle.origin.endswith("BlizzardInterfaceCode")
    data = build_index(bundle, generated_at=GENERATED_AT)
    assert data["source"] == "export"
    ping = entry(data, "function", "C_ForgeExport.SendExportPing")
    assert [arg["name"] for arg in ping["args"]] == ["message"]
    assert any("LuaEnum.lua" in warning for warning in data["warnings"])


def test_z_export_bundle_absent_and_broken() -> None:
    """Z: no export folder gives None; a folder without the doc TOC is bad-export-data."""
    assert load_export_bundle(FakeFileSystem(forever_install_files()), None, "forever") is None
    assert load_export_bundle(FakeFileSystem({}), None, "forever") is None
    broken = forever_install_files()
    broken[f"{MAC_ROOT}/_forever_/BlizzardInterfaceCode/readme.txt"] = "exported\n"
    with pytest.raises(ApiIndexError) as raised:
        load_export_bundle(FakeFileSystem(broken), None, "forever")
    assert raised.value.code == "bad-export-data"


def test_zb_export_flat_layout_and_unknown_build() -> None:
    """ZB: the flat doc-addon layout loads; an unknown client version is bad-export-data."""
    flat_dir = f"{MAC_ROOT}/_forever_/BlizzardInterfaceCode/Blizzard_APIDocumentationGenerated"
    flat = forever_install_files()
    flat[f"{flat_dir}/Blizzard_APIDocumentationGenerated.toc"] = _EXPORT_TOC
    flat[f"{flat_dir}/ForgeExportDocumentation.lua"] = FORGE_EXPORT_DOC
    flat[f"{flat_dir}/ForgeFrameAPIDocumentation.lua"] = FORGE_FRAME_DOC
    bundle = load_export_bundle(FakeFileSystem(flat), None, "forever")
    assert bundle is not None
    assert bundle.build == "1.60.1.70888"
    no_build = fixture_export_files()
    del no_build[f"{MAC_ROOT}/.build.info"]
    with pytest.raises(ApiIndexError) as raised:
        load_export_bundle(FakeFileSystem(no_build), None, "forever")
    assert raised.value.code == "bad-export-data"


def test_za_export_toc_refuses_escaping_file_names() -> None:
    """ZA: an export TOC entry escaping the doc folder is refused and warned, not read."""
    files = fixture_export_files()
    files[f"{EXPORT_DOC_DIR}/Blizzard_APIDocumentationGenerated.toc"] = (
        "## Interface: 16001\n../Evil.lua\nForgeExportDocumentation.lua\n"
    )
    files[f"{MAC_ROOT}/_forever_/BlizzardInterfaceCode/Interface/AddOns/Evil.lua"] = "-- evil\n"
    bundle = load_export_bundle(FakeFileSystem(files), None, "forever")
    assert bundle is not None
    assert sorted(bundle.documentation) == ["ForgeExportDocumentation.lua"]
    assert any("Evil.lua" in warning for warning in bundle.warnings)
