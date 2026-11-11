"""Tests for WoW install detection (created 2026-11-11, T-003).

Hermetic by construction: detection runs against the in-memory ``FakeFileSystem`` from
``tests/conftest.py`` (reached through fixtures), except one ``RealFileSystem`` test whose
install is written under pytest's ``tmp_path``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from wow_addon_forge.env import (
    DEFAULT_ROOTS,
    AddonInfo,
    EnvReport,
    FileSystem,
    FlavorInfo,
    RealFileSystem,
    detect_installs,
    interface_from_version,
    parse_build_info,
    parse_flavor_info,
)

_WIN_ROOT = "C:\\Program Files (x86)\\World of Warcraft"


def _flavor(report: EnvReport, name: str) -> FlavorInfo:
    return next(
        flavor for install in report.installs for flavor in install.flavors if flavor.flavor == name
    )


def _addon(flavor: FlavorInfo, name: str) -> AddonInfo:
    return next(addon for addon in flavor.addons if addon.name == name)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.60.1.70888", 16001),
        ("5.5.4.70631", 50504),
        ("1.15.9.70576", 11509),
        ("1.60", None),
        ("abc", None),
        ("", None),
        ("1.100.1.5", None),
    ],
)
def test_interface_from_version_table(version: str, expected: int | None) -> None:
    assert interface_from_version(version) == expected


def test_parse_build_info_maps_the_three_products(forever_files: dict[str, str]) -> None:
    text = next(content for path, content in forever_files.items() if path.endswith(".build.info"))
    assert parse_build_info(text) == {
        "wow_classic_era": "1.15.9.70576",
        "wow_classic": "5.5.4.70631",
        "wowf": "1.60.1.70888",
    }


def test_parse_build_info_tolerates_crlf_and_a_short_row() -> None:
    text = (
        "Branch!STRING:0|Version!STRING:0|Product!STRING:0\r\n"
        "us|1.60.1.70888|wowf\r\n"
        "us|1.2.3\r\n"
        "\r\n"
        "us|5.5.4.70631|wow_classic\r\n"
    )
    assert parse_build_info(text) == {"wowf": "1.60.1.70888", "wow_classic": "5.5.4.70631"}


def test_parse_build_info_without_product_column_returns_empty() -> None:
    text = "Branch!STRING:0|Version!STRING:0\nus|1.60.1.70888\n"
    assert parse_build_info(text) == {}


def test_parse_flavor_info_returns_the_product_code() -> None:
    assert parse_flavor_info("Product Flavor!STRING:0\nwowf\n") == "wowf"
    assert parse_flavor_info("Product Flavor!STRING:0\n") is None
    assert parse_flavor_info("") is None


def test_detect_finds_mac_install_on_default_roots(forever_fs: FileSystem) -> None:
    report = detect_installs(forever_fs)
    assert report.searched == DEFAULT_ROOTS
    assert len(report.installs) == 1
    assert [flavor.flavor for flavor in report.installs[0].flavors] == [
        "_classic_era_",
        "_forever_",
    ]
    forever = _flavor(report, "_forever_")
    assert forever.product == "wowf"
    assert forever.version == "1.60.1.70888"
    assert forever.interface == 16001
    assert forever.accounts == 2
    assert [addon.name for addon in forever.addons] == ["Guildhall", "TrailMap"]
    trail_map = _addon(forever, "TrailMap")
    assert trail_map.toc == "TrailMap_Camelot.toc"
    assert trail_map.title == "TrailMap v2.3.0"
    assert trail_map.version == "2.3.0"
    assert trail_map.supports_client is True
    guildhall = _addon(forever, "Guildhall")
    assert guildhall.toc == "Guildhall.toc"
    assert guildhall.interface == (16001,)
    assert guildhall.supports_client is True


def test_folder_without_matching_toc_warns_and_is_not_listed(
    forever_fs: FileSystem,
) -> None:
    report = detect_installs(forever_fs)
    forever = _flavor(report, "_forever_")
    assert all(addon.name != "NoToc" for addon in forever.addons)
    assert any("NoToc" in warning for warning in report.warnings)


def test_windows_rooted_tree_is_found_on_default_roots(
    fake_fs_factory: Callable[..., FileSystem],
    forever_files: dict[str, str],
    mac_root: str,
) -> None:
    windows_files = {
        path.replace(mac_root, _WIN_ROOT): content for path, content in forever_files.items()
    }
    report = detect_installs(fake_fs_factory(windows_files))
    assert report.searched == DEFAULT_ROOTS
    assert [install.root for install in report.installs] == [_WIN_ROOT]
    assert _flavor(report, "_forever_").interface == 16001


def test_missing_explicit_root_is_skipped_silently(forever_fs: FileSystem) -> None:
    report = detect_installs(forever_fs, roots=["/elsewhere"])
    assert report.installs == ()
    assert report.searched == ("/elsewhere",)
    assert report.warnings == ()


def test_existing_root_without_flavor_folder_warns(
    fake_fs_factory: Callable[..., FileSystem], mac_root: str
) -> None:
    report = detect_installs(fake_fs_factory({f"{mac_root}/Launcher.db": "x"}), roots=[mac_root])
    assert report.installs == ()
    assert any("no flavor folder" in warning for warning in report.warnings)


def test_missing_build_info_leaves_versions_unknown(
    fake_fs_factory: Callable[..., FileSystem],
    forever_files: dict[str, str],
    mac_root: str,
) -> None:
    files = {
        path: content for path, content in forever_files.items() if not path.endswith(".build.info")
    }
    report = detect_installs(fake_fs_factory(files), roots=[mac_root])
    forever = _flavor(report, "_forever_")
    assert forever.version is None
    assert forever.interface is None
    assert all(addon.supports_client is None for addon in forever.addons)
    assert _addon(forever, "TrailMap").toc == "TrailMap.toc"
    # [2026-11-11 T-003] One cause, one line: the missing file is reported once, not once more
    # per flavor as a "no row for product" warning.
    assert [warning for warning in report.warnings if ".build.info" in warning] == [
        f"{mac_root}/.build.info is missing; client versions are unknown"
    ]


def test_build_info_without_usable_columns_warns_once_and_leaves_versions_unknown(
    fake_fs_factory: Callable[..., FileSystem],
    forever_files: dict[str, str],
    mac_root: str,
) -> None:
    files = dict(forever_files)
    files[f"{mac_root}/.build.info"] = "Branch!STRING:0|Active!DEC:1\nus|1\n"
    report = detect_installs(fake_fs_factory(files), roots=[mac_root])
    assert _flavor(report, "_forever_").version is None
    assert [warning for warning in report.warnings if ".build.info" in warning] == [
        f"{mac_root}/.build.info has no Version and Product row; client versions are unknown"
    ]


def test_product_without_a_build_info_row_warns_and_names_the_product(
    fake_fs_factory: Callable[..., FileSystem],
    forever_files: dict[str, str],
    mac_root: str,
) -> None:
    files = dict(forever_files)
    files[f"{mac_root}/_forever_/.flavor.info"] = "Product Flavor!STRING:0\nwow_unlisted\n"
    report = detect_installs(fake_fs_factory(files), roots=[mac_root])
    forever = _flavor(report, "_forever_")
    assert forever.product == "wow_unlisted"
    assert forever.version is None
    assert any("wow_unlisted" in warning for warning in report.warnings)


def test_missing_flavor_info_still_lists_flavor_via_interface_dir(
    fake_fs_factory: Callable[..., FileSystem],
    forever_files: dict[str, str],
    mac_root: str,
) -> None:
    files = {
        path: content
        for path, content in forever_files.items()
        if not path.endswith("_forever_/.flavor.info")
    }
    report = detect_installs(fake_fs_factory(files), roots=[mac_root])
    forever = _flavor(report, "_forever_")
    assert forever.product is None
    assert any(".flavor.info" in warning for warning in report.warnings)


def test_unreadable_toc_candidate_is_dropped_with_a_warning(
    fake_fs_factory: Callable[..., FileSystem],
    forever_files: dict[str, str],
    mac_root: str,
) -> None:
    camelot = f"{mac_root}/_forever_/Interface/AddOns/TrailMap/TrailMap_Camelot.toc"
    fs = fake_fs_factory(forever_files, unreadable={camelot})
    report = detect_installs(fs, roots=[mac_root])
    trail_map = _addon(_flavor(report, "_forever_"), "TrailMap")
    assert trail_map.toc == "TrailMap.toc"
    assert trail_map.supports_client is False
    assert any("TrailMap_Camelot.toc" in warning for warning in report.warnings)


def test_to_dict_is_json_serializable_and_hides_account_names(
    forever_fs: FileSystem,
) -> None:
    data = detect_installs(forever_fs).to_dict()
    dumped = json.dumps(data)
    flavors = data["installs"][0]["flavors"]
    forever = next(flavor for flavor in flavors if flavor["flavor"] == "_forever_")
    assert list(forever.keys()) == [
        "flavor",
        "product",
        "version",
        "interface",
        "interface_source",
        "accounts",
        "addon_count",
        "addons",
    ]
    assert forever["interface_source"] == "derived-from-version"
    assert forever["addon_count"] == 2
    assert "ACCOUNT1" not in dumped
    assert "ACCOUNT2" not in dumped


def test_real_filesystem_detects_install_under_tmp_path(tmp_path: Path) -> None:
    (tmp_path / ".build.info").write_text(
        "Branch!STRING:0|Version!STRING:0|Product!STRING:0\nus|1.60.1.70888|wowf\n",
        encoding="utf-8",
    )
    flavor_dir = tmp_path / "_forever_"
    flavor_dir.mkdir()
    (flavor_dir / ".flavor.info").write_text("Product Flavor!STRING:0\nwowf\n", encoding="utf-8")
    demo_dir = flavor_dir / "Interface" / "AddOns" / "Demo"
    demo_dir.mkdir(parents=True)
    # [2026-11-11 T-003] A BOM in front and one byte (0xFF) that is not UTF-8 in the title: the
    # real adapter must decode both without raising.
    (demo_dir / "Demo.toc").write_bytes(
        b"\xef\xbb\xbf## Interface: 16001\n## Title: Demo\xff\n## Version: 0.1.0\n\nMain.lua\n"
    )
    fs = RealFileSystem()
    report = detect_installs(fs, roots=[str(tmp_path)])
    forever = _flavor(report, "_forever_")
    assert forever.product == "wowf"
    assert forever.version == "1.60.1.70888"
    assert forever.interface == 16001
    demo = _addon(forever, "Demo")
    assert demo.toc == "Demo.toc"
    assert demo.title == "Demo\ufffd"
    assert demo.interface == (16001,)
    assert demo.supports_client is True
    with pytest.raises(OSError):
        fs.list_dir(str(tmp_path / "missing"))


def test_interface_from_version_rejects_a_non_numeric_part() -> None:
    assert interface_from_version("1.x.1.70888") is None


def test_parse_build_info_handles_empty_text_empty_product_and_repeats() -> None:
    assert parse_build_info("") == {}
    text = "Version!STRING:0|Product!STRING:0\n9.9.9.1|\n1.60.1.70888|wowf\n2.0.0.1|wowf\n"
    assert parse_build_info(text) == {"wowf": "1.60.1.70888"}


def test_unreadable_and_malformed_entries_become_warnings_never_errors(
    fake_fs_factory: Callable[..., FileSystem],
    forever_files: dict[str, str],
    mac_root: str,
) -> None:
    """Detection's promise: an OSError or a malformed file is one warning naming the path."""
    addons = f"{mac_root}/_forever_/Interface/AddOns"
    files = dict(forever_files)
    files[f"{mac_root}/_classic_era_/.flavor.info"] = "only one line\n"
    files[f"{mac_root}/_stray_"] = "a file named like a flavor folder\n"
    files[f"{mac_root}/_cache_/data.bin"] = "a folder named like one, with no game in it\n"
    files[f"{addons}/OldMap/OldMap_Classic.toc"] = "## Interface: 11509\n\nMain.lua\n"
    unreadable = {
        f"{mac_root}/.build.info",
        f"{mac_root}/_forever_/.flavor.info",
        f"{addons}/Guildhall/Guildhall.toc",
        f"{addons}/TrailMap",
    }
    report = detect_installs(fake_fs_factory(files, unreadable=unreadable), roots=[mac_root])
    assert [flavor.flavor for flavor in report.installs[0].flavors] == [
        "_classic_era_",
        "_forever_",
    ]
    assert _flavor(report, "_classic_era_").product is None
    forever = _flavor(report, "_forever_")
    assert forever.product is None
    assert forever.version is None
    # [2026-11-11 T-003] OldMap has neither a TOC matching the (unknown) client nor a base
    # TOC, so the first candidate by name is reported; the other two addons are skipped.
    assert [addon.name for addon in forever.addons] == ["OldMap"]
    old_map = _addon(forever, "OldMap")
    assert old_map.toc == "OldMap_Classic.toc"
    assert old_map.supports_client is None
    for fragment in (
        "/.build.info could not be read",
        "/_forever_/.flavor.info could not be read",
        "/_classic_era_/.flavor.info could not be parsed",
        "/Guildhall/Guildhall.toc could not be read",
        "/AddOns/TrailMap could not be listed",
    ):
        assert any(fragment in warning for warning in report.warnings), fragment
    assert not any("TrailMap has no TOC" in warning for warning in report.warnings)


def test_unlistable_addons_folder_warns_and_reports_no_addons(
    fake_fs_factory: Callable[..., FileSystem],
    forever_files: dict[str, str],
    mac_root: str,
) -> None:
    addons = f"{mac_root}/_forever_/Interface/AddOns"
    report = detect_installs(fake_fs_factory(forever_files, unreadable={addons}), roots=[mac_root])
    forever = _flavor(report, "_forever_")
    assert forever.interface == 16001
    assert forever.addons == ()
    assert any(f"{addons} could not be listed" in warning for warning in report.warnings)
