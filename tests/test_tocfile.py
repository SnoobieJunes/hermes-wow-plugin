"""Tests for the TOC parser and TOC lint (created 2026-11-11, T-003; extended T-006)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from wow_addon_forge.env import FileSystem
from wow_addon_forge.tocfile import (
    Finding,
    TocFile,
    is_valid_lua_identifier,
    lint_toc,
    parse_toc,
    strip_ui_escapes,
)

_EXAMPLE = (
    "# a comment line (single hash)\n"
    "## Interface: 16001\n"
    "## Title: Questie|cFF00FF00 v12.6.4|r\n"
    "## Version: 12.6.4\n"
    "## SavedVariables: QuestieConfig, QuestieProfilerEnabled\n"
    "\n"
    "Modules\\Libs\\QuestieLoader.lua\n"
    "embeds.xml\n"
)


def test_headers_and_files_parsed_in_order() -> None:
    parsed = parse_toc(_EXAMPLE)
    assert parsed.headers == {
        "Interface": "16001",
        "Title": "Questie|cFF00FF00 v12.6.4|r",
        "Version": "12.6.4",
        "SavedVariables": "QuestieConfig, QuestieProfilerEnabled",
    }
    assert parsed.files == ("Modules/Libs/QuestieLoader.lua", "embeds.xml")
    assert parsed.interface == (16001,)
    assert parsed.version == "12.6.4"


def test_backslashes_normalised_to_forward_slashes() -> None:
    assert parse_toc("Core\\Deep\\File.lua\n").files == ("Core/Deep/File.lua",)


def test_bom_is_tolerated() -> None:
    parsed = parse_toc("\ufeff## Version: 1.0\nMain.lua\n")
    assert parsed.version == "1.0"
    assert parsed.files == ("Main.lua",)


def test_crlf_is_tolerated() -> None:
    parsed = parse_toc("## Version: 1.0\r\n\r\nMain.lua\r\n")
    assert parsed.version == "1.0"
    assert parsed.files == ("Main.lua",)


def test_comments_and_blank_lines_are_skipped() -> None:
    parsed = parse_toc("# just a comment\n\n   \nMain.lua\n# another\n")
    assert parsed.headers == {}
    assert parsed.files == ("Main.lua",)


def test_double_hash_line_without_colon_is_ignored() -> None:
    parsed = parse_toc("## not a header\n## Version: 1.0\n")
    assert parsed.headers == {"Version": "1.0"}


def test_repeated_key_keeps_the_first_value() -> None:
    parsed = parse_toc("## Version: 1.0\n## Version: 2.0\n")
    assert parsed.headers["Version"] == "1.0"
    assert parsed.version == "1.0"


def test_interface_list_drops_non_digit_tokens() -> None:
    assert parse_toc("## Interface: 16001, 11507 ,abc\n").interface == (16001, 11507)


def test_missing_interface_header_gives_empty_tuple() -> None:
    assert parse_toc("## Version: 1.0\n").interface == ()


def test_title_colour_escapes_are_stripped() -> None:
    assert strip_ui_escapes("Questie|cFF00FF00 v12.6.4|r") == "Questie v12.6.4"
    assert parse_toc(_EXAMPLE).title == "Questie v12.6.4"


def test_title_and_version_are_none_when_absent() -> None:
    parsed = parse_toc("Main.lua\n")
    assert parsed.title is None
    assert parsed.version is None


def test_title_empty_after_stripping_escapes_is_none() -> None:
    assert parse_toc("## Title: |cFF00FF00|r\n").title is None


def test_empty_text_parses_to_empty_toc() -> None:
    assert parse_toc("") == TocFile(headers={}, files=())


# [2026-11-11 T-006] Everything below extends the T-003 parser contract above: the Finding
# wire shape, Lua 5.1 identifier rules, saved-variable views, source positions and lint_toc.

_ADDON_DIR = "/games/WoW/_forever_/Interface/AddOns/MyAddon"
_TOC_NAME = "MyAddon.toc"
# Line map: 1 Interface, 2 Title, 3 blank, 4 Main.lua, 5 Core\Util.lua.
_CLEAN_TOC = "## Interface: 16001\n## Title: MyAddon\n\nMain.lua\nCore\\Util.lua\n"


def _addon_files(
    addon_dir: str = _ADDON_DIR, extra: dict[str, str] | None = None
) -> dict[str, str]:
    files = {
        f"{addon_dir}/Main.lua": "MainGlobal = {}\n",
        f"{addon_dir}/Core/Util.lua": "UtilGlobal = {}\n",
    }
    if extra:
        files.update(extra)
    return files


def _lint(
    fake_fs_factory: Callable[..., FileSystem],
    toc_text: str,
    files: dict[str, str],
    *,
    addon_dir: str = _ADDON_DIR,
    toc_filename: str = _TOC_NAME,
    folder_name: str | None = None,
    unreadable: set[str] | None = None,
) -> list[Finding]:
    return lint_toc(
        parse_toc(toc_text),
        toc_filename=toc_filename,
        addon_dir=addon_dir,
        fs=fake_fs_factory(files, unreadable=unreadable),
        folder_name=folder_name,
    )


def _codes(findings: list[Finding]) -> list[str]:
    return [finding.code for finding in findings]


def _only(findings: list[Finding], code: str) -> Finding:
    matches = [finding for finding in findings if finding.code == code]
    assert len(matches) == 1, findings
    return matches[0]


def test_finding_to_dict_exact_keys_order_and_values() -> None:
    finding = Finding(
        severity="warning",
        code="unlisted-file",
        file="MyAddon.toc",
        line=None,
        message="Lua file 'Extra.lua' is not listed.",
        hint="Add 'Extra.lua' to MyAddon.toc.",
    )
    as_dict = finding.to_dict()
    # [2026-11-11 T-006] The key order is part of the wire shape (docs/SPEC-PLUGIN.md §4),
    # so it is asserted separately from dict equality, which would ignore order.
    assert list(as_dict.keys()) == ["severity", "code", "file", "line", "message", "hint"]
    assert as_dict == {
        "severity": "warning",
        "code": "unlisted-file",
        "file": "MyAddon.toc",
        "line": None,
        "message": "Lua file 'Extra.lua' is not listed.",
        "hint": "Add 'Extra.lua' to MyAddon.toc.",
    }


def test_finding_to_dict_carries_line_number() -> None:
    finding = Finding(
        severity="error",
        code="missing-file",
        file="MyAddon.toc",
        line=7,
        message="Listed file 'Gone.lua' does not exist.",
        hint="Create the file.",
    )
    assert finding.to_dict()["line"] == 7


@pytest.mark.parametrize(
    "name",
    ["GuildhallDB", "_private", "_", "A", "x9", "DB_2", "Local", "NIL"],
)
def test_is_valid_lua_identifier_accepts_plain_names(name: str) -> None:
    assert is_valid_lua_identifier(name) is True


def test_is_valid_lua_identifier_accepts_goto_in_lua_51() -> None:
    # [2026-11-11 T-006] `goto` only became a keyword in Lua 5.2; in the client's Lua 5.1
    # it is an ordinary identifier, so a saved variable may legally be named `goto`.
    assert is_valid_lua_identifier("goto") is True


@pytest.mark.parametrize(
    "name",
    ["123bad", "bad-name", "a b", "", "9", "a.b", "a/b", "héllo", " name", "name "],
)
def test_is_valid_lua_identifier_rejects_bad_spellings(name: str) -> None:
    assert is_valid_lua_identifier(name) is False


@pytest.mark.parametrize(
    "name",
    [
        "local",
        "function",
        "end",
        "nil",
        "true",
        "false",
        "and",
        "break",
        "do",
        "else",
        "elseif",
        "for",
        "if",
        "in",
        "not",
        "or",
        "repeat",
        "return",
        "then",
        "until",
        "while",
    ],
)
def test_is_valid_lua_identifier_rejects_lua_51_keywords(name: str) -> None:
    assert is_valid_lua_identifier(name) is False


def test_saved_variables_views_split_strip_and_drop_empty_tokens() -> None:
    parsed = parse_toc(
        "## SavedVariables: GuildhallDB, QuestieConfig ,, SharedDB\n"
        "## SavedVariablesPerCharacter: CharDB,  SharedDB , GuildhallDB\n"
    )
    assert parsed.saved_variables == ("GuildhallDB", "QuestieConfig", "SharedDB")
    assert parsed.saved_variables_per_character == ("CharDB", "SharedDB", "GuildhallDB")


def test_all_saved_variables_deduplicates_in_declared_order() -> None:
    parsed = parse_toc(
        "## SavedVariables: GuildhallDB, SharedDB\n"
        "## SavedVariablesPerCharacter: SharedDB, CharDB, GuildhallDB\n"
    )
    # [2026-11-11 T-006] A name declared in both headers is persisted once; first
    # appearance wins and keeps its position instead of moving to the second header.
    assert parsed.all_saved_variables == ("GuildhallDB", "SharedDB", "CharDB")


def test_all_saved_variables_deduplicates_within_one_header() -> None:
    parsed = parse_toc("## SavedVariables: GuildhallDB, GuildhallDB, OtherDB\n")
    assert parsed.saved_variables == ("GuildhallDB", "GuildhallDB", "OtherDB")
    assert parsed.all_saved_variables == ("GuildhallDB", "OtherDB")


def test_saved_variables_views_are_empty_when_headers_absent() -> None:
    parsed = parse_toc("Main.lua\n")
    assert parsed.saved_variables == ()
    assert parsed.saved_variables_per_character == ()
    assert parsed.all_saved_variables == ()


def test_saved_variables_views_are_empty_when_headers_blank() -> None:
    parsed = parse_toc("## SavedVariables:\n## SavedVariablesPerCharacter:   \n")
    assert parsed.saved_variables == ()
    assert parsed.saved_variables_per_character == ()
    assert parsed.all_saved_variables == ()


def test_saved_variables_views_return_invalid_tokens_as_written() -> None:
    # [2026-11-11 T-006] The parser views report what was written, even unusable names;
    # judging them is lint_toc's job, so nothing is silently dropped here.
    parsed = parse_toc("## SavedVariables: 123bad, local\n")
    assert parsed.saved_variables == ("123bad", "local")
    assert parsed.all_saved_variables == ("123bad", "local")


def test_header_lines_and_file_lines_are_one_based() -> None:
    parsed = parse_toc(_EXAMPLE)
    assert parsed.header_lines == {
        "Interface": 2,
        "Title": 3,
        "Version": 4,
        "SavedVariables": 5,
    }
    assert parsed.file_lines == (
        ("Modules/Libs/QuestieLoader.lua", 7),
        ("embeds.xml", 8),
    )


def test_header_lines_keep_first_occurrence_of_repeated_key() -> None:
    parsed = parse_toc("## Version: 1.0\n\n## Version: 2.0\nMain.lua\n")
    assert parsed.header_lines == {"Version": 1}
    assert parsed.file_lines == (("Main.lua", 4),)


def test_positions_with_bom_match_positions_without_bom() -> None:
    body = "## Interface: 16001\n## Title: MyAddon\n\nMain.lua\n"
    with_bom = parse_toc("\ufeff" + body)
    without_bom = parse_toc(body)
    # [2026-11-11 T-006] Positions are counted on the BOM-stripped text, so a BOM must
    # never shift a reported line; both parses must agree line for line.
    assert with_bom.header_lines == without_bom.header_lines == {"Interface": 1, "Title": 2}
    assert with_bom.file_lines == without_bom.file_lines == (("Main.lua", 4),)


def test_positions_count_blank_and_comment_lines() -> None:
    parsed = parse_toc("# note\n\n## Interface: 16001\n   \n# another\nMain.lua\n")
    assert parsed.header_lines == {"Interface": 3}
    assert parsed.file_lines == (("Main.lua", 6),)


def test_tocfile_equality_ignores_positions() -> None:
    parsed = parse_toc("## Interface: 16001\nMain.lua\n")
    hand_built = TocFile(headers={"Interface": "16001"}, files=("Main.lua",))
    assert parsed == hand_built
    shifted = TocFile(
        headers={"Interface": "16001"},
        files=("Main.lua",),
        header_lines={"Interface": 99},
        file_lines=(("Main.lua", 99),),
    )
    # [2026-11-11 T-006] compare=False on the position fields: where a line sits is not
    # what the TOC means, so position data alone never breaks equality.
    assert parsed == shifted


def test_tocfile_equality_still_sees_headers_and_files() -> None:
    parsed = parse_toc("## Interface: 16001\nMain.lua\n")
    assert parsed != TocFile(headers={"Interface": "11507"}, files=("Main.lua",))
    assert parsed != TocFile(headers={"Interface": "16001"}, files=("Other.lua",))


def test_lint_clean_addon_passes_with_pruned_test_and_hidden_files(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    files = _addon_files(
        extra={
            # [2026-11-11 T-006] Tests/ and dot-folders are pruned by _walk_lua_files:
            # addon test files are deliberately never listed in a TOC, so their mere
            # presence on disk must not produce unlisted-file warnings.
            f"{_ADDON_DIR}/Tests/Spec.lua": "SpecGlobal = {}\n",
            f"{_ADDON_DIR}/tests/Unit.lua": "UnitGlobal = {}\n",
            f"{_ADDON_DIR}/.git/ignore.lua": "IgnoredGlobal = {}\n",
            f"{_ADDON_DIR}/.hidden/AlsoIgnored.lua": "HiddenGlobal = {}\n",
            f"{_ADDON_DIR}/readme.txt": "not lua\n",
        }
    )
    assert _lint(fake_fs_factory, _CLEAN_TOC, files) == []


def test_lint_clean_addon_with_valid_saved_variables_passes(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    toc_text = (
        "## Interface: 11507, 16001\n"
        "## SavedVariables: GuildhallDB, goto, _private\n"
        "## SavedVariablesPerCharacter: CharDB\n"
        "\nMain.lua\nCore\\Util.lua\n"
    )
    # [2026-11-11 T-006] `goto` is a legal Lua 5.1 identifier (see above), so this
    # SavedVariables header is clean even though modern-Lua habits flag the word.
    assert _lint(fake_fs_factory, toc_text, _addon_files()) == []


def test_lint_flags_listed_file_that_does_not_exist_with_exact_line(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    toc_text = "## Interface: 16001\n\nMain.lua\nMissing.lua\n"
    files = {f"{_ADDON_DIR}/Main.lua": "MainGlobal = {}\n"}
    findings = _lint(fake_fs_factory, toc_text, files)
    assert _codes(findings) == ["missing-file"]
    finding = findings[0]
    assert finding.severity == "error"
    assert finding.code == "missing-file"
    assert finding.file == _TOC_NAME
    assert finding.line == 4
    assert "Missing.lua" in finding.message


def test_lint_flags_each_missing_file_in_toc_order(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    toc_text = "## Interface: 16001\nGone.lua\nCore\\AlsoGone.lua\n"
    findings = _lint(fake_fs_factory, toc_text, {f"{_ADDON_DIR}/readme.txt": "x\n"})
    assert _codes(findings) == ["missing-file", "missing-file"]
    assert [finding.line for finding in findings] == [2, 3]
    assert "Gone.lua" in findings[0].message
    assert "Core/AlsoGone.lua" in findings[1].message


def test_lint_name_mismatch_derived_from_addon_dir(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    findings = _lint(fake_fs_factory, _CLEAN_TOC, _addon_files(), toc_filename="OtherName.toc")
    assert _codes(findings) == ["toc-name-mismatch"]
    finding = findings[0]
    assert finding.severity == "error"
    assert finding.file == "OtherName.toc"
    assert finding.line == 1
    assert "OtherName.toc" in finding.message
    assert "MyAddon" in finding.message
    assert "MyAddon.toc" in finding.hint


def test_lint_name_mismatch_derived_from_windows_addon_dir(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    # [2026-11-11 T-006] folder_name=None derives the folder from addon_dir after
    # normalising backslashes, so a Windows-shaped path resolves on every OS.
    win_dir = r"C:\WoW\_forever_\Interface\AddOns\MyAddon"
    files = _addon_files(addon_dir=win_dir)
    clean = _lint(fake_fs_factory, _CLEAN_TOC, files, addon_dir=win_dir)
    assert clean == []
    findings = _lint(
        fake_fs_factory,
        _CLEAN_TOC,
        files,
        addon_dir=win_dir,
        toc_filename="WrongName.toc",
    )
    assert _codes(findings) == ["toc-name-mismatch"]
    assert "MyAddon" in findings[0].message


def test_lint_name_mismatch_uses_explicit_folder_name(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    findings = _lint(fake_fs_factory, _CLEAN_TOC, _addon_files(), folder_name="CustomFolder")
    assert _codes(findings) == ["toc-name-mismatch"]
    assert "CustomFolder" in findings[0].message
    assert "CustomFolder.toc" in findings[0].hint


def test_lint_explicit_folder_name_overrides_addon_dir(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    other_dir = "/games/WoW/_forever_/Interface/AddOns/Different"
    files = _addon_files(addon_dir=other_dir)
    findings = _lint(
        fake_fs_factory,
        _CLEAN_TOC,
        files,
        addon_dir=other_dir,
        folder_name="MyAddon",
    )
    assert findings == []


def test_lint_name_check_tolerates_trailing_slash_and_uppercase_extension(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    findings = _lint(
        fake_fs_factory,
        _CLEAN_TOC,
        _addon_files(),
        addon_dir=f"{_ADDON_DIR}/",
        toc_filename="MyAddon.TOC",
    )
    assert "toc-name-mismatch" not in _codes(findings)


def test_lint_flags_missing_interface_header(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    toc_text = "## Title: MyAddon\n\nMain.lua\nCore\\Util.lua\n"
    findings = _lint(fake_fs_factory, toc_text, _addon_files())
    assert _codes(findings) == ["toc-interface"]
    finding = findings[0]
    assert finding.severity == "error"
    assert finding.file == _TOC_NAME
    # [2026-11-11 T-006] With no Interface header there is no line to blame, so the
    # finding falls back to line 1 and reports the declared set as "none".
    assert finding.line == 1
    assert "16001" in finding.message
    assert "none" in finding.message


def test_lint_flags_interface_without_client_number_at_exact_header_line(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    toc_text = "# note\n## Title: MyAddon\n## Interface: 11507\n\nMain.lua\nCore\\Util.lua\n"
    findings = _lint(fake_fs_factory, toc_text, _addon_files())
    assert _codes(findings) == ["toc-interface"]
    finding = findings[0]
    assert finding.severity == "error"
    assert finding.line == 3
    assert "16001" in finding.message
    assert "11507" in finding.message
    assert "16001" in finding.hint


def test_lint_interface_list_including_client_number_passes(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    toc_text = "## Interface: 11507, 16001\nMain.lua\nCore\\Util.lua\n"
    assert _lint(fake_fs_factory, toc_text, _addon_files()) == []


def test_lint_interface_header_with_only_non_digit_tokens_fails(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    toc_text = "## Interface: abc\nMain.lua\nCore\\Util.lua\n"
    findings = _lint(fake_fs_factory, toc_text, _addon_files())
    finding = _only(findings, "toc-interface")
    assert finding.line == 1
    assert "none" in finding.message


@pytest.mark.parametrize(
    "bad_name",
    ["123bad", "bad-name", "a b", "local", "function", "end", "nil", "true"],
)
def test_lint_flags_invalid_saved_variable_names(
    fake_fs_factory: Callable[..., FileSystem], bad_name: str
) -> None:
    toc_text = (
        f"## Interface: 16001\n## SavedVariables: GoodDB, {bad_name}\n\nMain.lua\nCore\\Util.lua\n"
    )
    findings = _lint(fake_fs_factory, toc_text, _addon_files())
    assert _codes(findings) == ["invalid-savedvar"]
    finding = findings[0]
    assert finding.severity == "error"
    assert finding.file == _TOC_NAME
    assert finding.line == 2
    assert bad_name in finding.message
    assert "SavedVariables" in finding.message


@pytest.mark.parametrize(
    "raw_value,empty_slots",
    [("Foo,", 1), (", Foo", 1), ("Foo,, Bar", 1), ("Foo, ", 1), (",", 2)],
)
def test_lint_flags_empty_saved_variable_slots_in_non_blank_header(
    fake_fs_factory: Callable[..., FileSystem], raw_value: str, empty_slots: int
) -> None:
    toc_text = f"## Interface: 16001\n## SavedVariables: {raw_value}\n\nMain.lua\nCore\\Util.lua\n"
    findings = _lint(fake_fs_factory, toc_text, _addon_files())
    # [2026-11-11 T-006] A trailing comma in `Foo,` leaves an empty slot: unlike a blank
    # header (which declares nothing, legally), a non-blank value with an empty entry
    # names something the client cannot persist, so it is flagged as "(empty entry)".
    assert _codes(findings) == ["invalid-savedvar"] * empty_slots
    assert all(finding.line == 2 for finding in findings)
    assert all("(empty entry)" in finding.message for finding in findings)


@pytest.mark.parametrize(
    "saved_header",
    ["", "## SavedVariables:\n", "## SavedVariables:   \n"],
)
def test_lint_ignores_absent_or_blank_saved_variables_header(
    fake_fs_factory: Callable[..., FileSystem], saved_header: str
) -> None:
    toc_text = "## Interface: 16001\n" + saved_header + "\nMain.lua\nCore\\Util.lua\n"
    assert _lint(fake_fs_factory, toc_text, _addon_files()) == []


def test_lint_flags_invalid_per_character_saved_variable_at_its_line(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    toc_text = (
        "## Interface: 16001\n"
        "## SavedVariables: GoodDB\n"
        "## SavedVariablesPerCharacter: 123bad\n"
        "\nMain.lua\nCore\\Util.lua\n"
    )
    findings = _lint(fake_fs_factory, toc_text, _addon_files())
    assert _codes(findings) == ["invalid-savedvar"]
    finding = findings[0]
    assert finding.line == 3
    assert "SavedVariablesPerCharacter" in finding.message
    assert "123bad" in finding.message


def test_lint_reports_each_invalid_saved_variable_in_order(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    toc_text = (
        "## Interface: 16001\n"
        "## SavedVariables: 123bad, GoodDB, local\n"
        "\nMain.lua\nCore\\Util.lua\n"
    )
    findings = _lint(fake_fs_factory, toc_text, _addon_files())
    assert _codes(findings) == ["invalid-savedvar", "invalid-savedvar"]
    assert "123bad" in findings[0].message
    assert "local" in findings[1].message
    assert [finding.line for finding in findings] == [2, 2]


@pytest.mark.parametrize(
    "bad_path",
    ["../Escape.lua", "/abs/File.lua", "C:/abs/File.lua", "Core//Double.lua"],
)
def test_lint_flags_invalid_file_paths(
    fake_fs_factory: Callable[..., FileSystem], bad_path: str
) -> None:
    toc_text = f"## Interface: 16001\n\nMain.lua\n{bad_path}\nCore\\Util.lua\n"
    findings = _lint(fake_fs_factory, toc_text, _addon_files())
    # [2026-11-11 T-006] The path is judged as written before any join, and an invalid
    # path is reported once as invalid-file-path, never also as missing-file.
    assert _codes(findings) == ["invalid-file-path"]
    finding = findings[0]
    assert finding.severity == "error"
    assert finding.file == _TOC_NAME
    assert finding.line == 4
    assert bad_path in finding.message


@pytest.mark.parametrize(
    "bad_line,shown",
    [
        ("..\\Escape.lua", "../Escape.lua"),
        ("Core\\..\\Escape.lua", "Core/../Escape.lua"),
        ("Core\\\\Double.lua", "Core//Double.lua"),
        ("./../Escape.lua", "./../Escape.lua"),
    ],
)
def test_lint_flags_invalid_file_paths_written_with_backslashes(
    fake_fs_factory: Callable[..., FileSystem], bad_line: str, shown: str
) -> None:
    toc_text = f"## Interface: 16001\n\n{bad_line}\nMain.lua\nCore\\Util.lua\n"
    findings = _lint(fake_fs_factory, toc_text, _addon_files())
    assert _codes(findings) == ["invalid-file-path"]
    assert findings[0].line == 3
    assert shown in findings[0].message


def test_lint_emits_unlisted_file_warnings_for_root_and_nested_lua(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    files = _addon_files(
        extra={
            f"{_ADDON_DIR}/Extra.lua": "ExtraGlobal = {}\n",
            f"{_ADDON_DIR}/Core/Deep/Nested.lua": "NestedGlobal = {}\n",
        }
    )
    findings = _lint(fake_fs_factory, _CLEAN_TOC, files)
    assert _codes(findings) == ["unlisted-file", "unlisted-file"]
    # [2026-11-11 T-006] _walk_lua_files returns sorted relative paths, so the nested
    # Core path is reported before the root-level Extra.lua.
    assert "Core/Deep/Nested.lua" in findings[0].message
    assert "Extra.lua" in findings[1].message
    for finding in findings:
        assert finding.severity == "warning"
        assert finding.file == _TOC_NAME
        assert finding.line is None


def test_lint_unlisted_file_matching_is_case_sensitive_and_extension_aware(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    files = _addon_files(
        extra={
            f"{_ADDON_DIR}/Shouty.LUA": "ShoutyGlobal = {}\n",
            f"{_ADDON_DIR}/notes.lua.txt": "not a lua file\n",
        }
    )
    findings = _lint(fake_fs_factory, _CLEAN_TOC, files)
    assert _codes(findings) == ["unlisted-file"]
    assert "Shouty.LUA" in findings[0].message


def test_lint_tolerates_unreadable_subdirectory(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    locked_dir = f"{_ADDON_DIR}/Locked"
    files = _addon_files(
        extra={
            f"{locked_dir}/Secret.lua": "SecretGlobal = {}\n",
            f"{_ADDON_DIR}/Visible.lua": "VisibleGlobal = {}\n",
        }
    )
    findings = _lint(fake_fs_factory, _CLEAN_TOC, files, unreadable={locked_dir})
    # [2026-11-11 T-006] An unreadable subdir is skipped by the walk (its PermissionError
    # is an OSError), so Secret.lua is neither reported nor fatal; readable siblings
    # are still checked, which is why Visible.lua alone is flagged.
    assert _codes(findings) == ["unlisted-file"]
    assert "Visible.lua" in findings[0].message
    assert all("Secret.lua" not in finding.message for finding in findings)


def test_lint_tolerates_unreadable_addon_dir(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    findings = _lint(fake_fs_factory, _CLEAN_TOC, _addon_files(), unreadable={_ADDON_DIR})
    assert findings == []


def test_lint_hand_built_toc_without_positions_falls_back_to_line_one(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    toc = TocFile(headers={}, files=("Missing.lua",))
    findings = lint_toc(
        toc,
        toc_filename=_TOC_NAME,
        addon_dir=_ADDON_DIR,
        fs=fake_fs_factory({f"{_ADDON_DIR}/readme.txt": "x\n"}),
    )
    assert _codes(findings) == ["toc-interface", "missing-file"]
    assert [finding.line for finding in findings] == [1, 1]


def test_lint_honours_explicit_client_interface(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    toc = parse_toc("## Interface: 11507\nMain.lua\nCore\\Util.lua\n")
    findings = lint_toc(
        toc,
        toc_filename=_TOC_NAME,
        addon_dir=_ADDON_DIR,
        fs=fake_fs_factory(_addon_files()),
        client_interface=11507,
    )
    assert findings == []


def test_lint_findings_come_in_rule_order(
    fake_fs_factory: Callable[..., FileSystem],
) -> None:
    toc_text = "## SavedVariables: local\n\nMissing.lua\n../Escape.lua\nMain.lua\nCore\\Util.lua\n"
    files = _addon_files(extra={f"{_ADDON_DIR}/Extra.lua": "ExtraGlobal = {}\n"})
    findings = _lint(fake_fs_factory, toc_text, files, toc_filename="WrongName.toc")
    assert _codes(findings) == [
        "toc-name-mismatch",
        "toc-interface",
        "invalid-savedvar",
        "missing-file",
        "invalid-file-path",
        "unlisted-file",
    ]
