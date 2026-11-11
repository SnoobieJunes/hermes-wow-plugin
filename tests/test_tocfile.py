"""Tests for the minimal TOC parser (created 2026-11-11, T-003)."""

from __future__ import annotations

from wow_addon_forge.tocfile import TocFile, parse_toc, strip_ui_escapes

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
