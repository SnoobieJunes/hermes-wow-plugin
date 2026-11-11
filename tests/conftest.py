"""Shared in-memory filesystem and install tree for the test suite (created 2026-11-11, T-003).

Invariants owned by this file:
- Tests built on ``FakeFileSystem`` are hermetic: they never read a real install, so the live
  game paths below exist only as in-memory dict keys.
- The tree mirrors the on-disk layout observed on a real install, with fake all-zero keys.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

MAC_ROOT = "/Applications/World of Warcraft"

_BUILD_INFO_HEADER = (
    "Branch!STRING:0|Active!DEC:1|Build Key!HEX:16|CDN Key!HEX:16|Install Key!HEX:16|"
    "IM Size!DEC:4|CDN Path!STRING:0|CDN Hosts!STRING:0|CDN Servers!STRING:0|"
    "Tags!STRING:0|Armadillo!STRING:0|Last Activated!STRING:0|Version!STRING:0|"
    "KeyRing!HEX:16|Product!STRING:0"
)

# [2026-11-11 T-003] All-zero hex keys: the tree is fake data, so no cell may look like a
# real build or CDN key copied off a machine.
_ZERO_KEY = "00000000000000000000000000000000"


def _normalise(path: str) -> str:
    return path.replace("\\", "/")


def _build_info_row(version: str, product: str) -> str:
    cells = [""] * 15
    cells[0] = "us"
    cells[1] = "1"
    cells[2] = _ZERO_KEY
    cells[3] = _ZERO_KEY
    cells[4] = _ZERO_KEY
    cells[5] = "0"
    cells[12] = version
    cells[13] = _ZERO_KEY
    cells[14] = product
    return "|".join(cells)


class FakeFileSystem:
    """In-memory ``FileSystem`` over a ``dict`` of file path to text.

    Directories are implied by the file paths (every ancestor of a file is a directory).
    Paths are compared as plain strings with backslashes normalised to ``/``, so a
    Windows-rooted tree works on every OS.

    Args:
        files: File path to text content.
        unreadable: Paths whose ``read_text`` / ``list_dir`` raise ``PermissionError``.

    Failure modes:
        ``list_dir`` of a non-directory and ``read_text`` of a missing file raise
        ``FileNotFoundError``; an unreadable path raises ``PermissionError``.
    """

    def __init__(self, files: dict[str, str], unreadable: set[str] | None = None) -> None:
        self._files = {_normalise(path): text for path, text in files.items()}
        self._unreadable = {_normalise(path) for path in unreadable} if unreadable else set()
        self._dirs: set[str] = set()
        for path in self._files:
            parent = path
            while "/" in parent:
                parent = parent.rsplit("/", 1)[0]
                if not parent:
                    self._dirs.add("/")
                    break
                self._dirs.add(parent)

    def _clean(self, path: str) -> str:
        cleaned = _normalise(path).rstrip("/")
        return cleaned if cleaned else "/"

    def is_dir(self, path: str) -> bool:
        """Return whether ``path`` is an implied directory."""
        return self._clean(path) in self._dirs

    def is_file(self, path: str) -> bool:
        """Return whether ``path`` is a file in the dict."""
        return _normalise(path) in self._files

    def list_dir(self, path: str) -> list[str]:
        """Return the sorted entry names of an implied directory.

        Failure modes:
            Raises ``PermissionError`` for an unreadable path and ``FileNotFoundError``
            for a non-directory.
        """
        cleaned = self._clean(path)
        if cleaned in self._unreadable:
            raise PermissionError(cleaned)
        if cleaned not in self._dirs:
            raise FileNotFoundError(cleaned)
        prefix = "/" if cleaned == "/" else cleaned + "/"
        names: set[str] = set()
        for candidate in self._dirs | set(self._files):
            if candidate.startswith(prefix):
                remainder = candidate[len(prefix) :]
                if remainder:
                    names.add(remainder.split("/", 1)[0])
        return sorted(names)

    def read_text(self, path: str) -> str:
        """Return a file's text from the dict.

        Failure modes:
            Raises ``PermissionError`` for an unreadable path and ``FileNotFoundError``
            for a missing file.
        """
        normalised = _normalise(path)
        if normalised in self._unreadable:
            raise PermissionError(normalised)
        if normalised not in self._files:
            raise FileNotFoundError(normalised)
        return self._files[normalised]

    def join(self, base: str, *parts: str) -> str:
        """Join ``base`` (trailing ``/`` stripped) and ``parts`` with ``/``."""
        cleaned_base = _normalise(base).rstrip("/")
        return "/".join([cleaned_base, *(_normalise(part) for part in parts)])


def forever_install_files(root: str = MAC_ROOT) -> dict[str, str]:
    """Return the fake install tree under ``root`` as a file dict for ``FakeFileSystem``.

    Args:
        root: The install root the tree is hung under (the macOS default root unless given).

    Returns:
        File path to text: a ``.build.info`` with three products, a ``_forever_`` flavor
        with two accounts and the addons Guildhall, TrailMap (base plus ``_Camelot`` TOC)
        and NoToc, a ``_classic_era_`` flavor marker, and a stray ``Launcher.db``.

    Failure modes:
        None.
    """
    build_info = (
        _BUILD_INFO_HEADER
        + "\n"
        + _build_info_row("1.15.9.70576", "wow_classic_era")
        + "\n"
        + _build_info_row("5.5.4.70631", "wow_classic")
        + "\n"
        + _build_info_row("1.60.1.70888", "wowf")
        + "\n"
    )
    return {
        f"{root}/.build.info": build_info,
        f"{root}/_forever_/.flavor.info": "Product Flavor!STRING:0\nwowf\n",
        f"{root}/_forever_/Interface/AddOns/Guildhall/Guildhall.toc": (
            "## Interface: 16001\n## Title: Guildhall\n## Version: 0.1.0\n\nCore\\Namespace.lua\n"
        ),
        f"{root}/_forever_/Interface/AddOns/TrailMap/TrailMap.toc": (
            "# fallback for unsupported clients\n## Interface: 00000\n"
            "## Title: TrailMap|cFFFF0000 game client not supported|r\n\nError.lua\n"
        ),
        f"{root}/_forever_/Interface/AddOns/TrailMap/TrailMap_Camelot.toc": (
            "## Interface: 16001\n## Title: TrailMap|cFF00FF00 v2.3.0|r\n"
            "## Version: 2.3.0\n\nMain.lua\n"
        ),
        f"{root}/_forever_/Interface/AddOns/NoToc/readme.txt": "not an addon\n",
        f"{root}/_forever_/WTF/Account/ACCOUNT1/SavedVariables/Guildhall.lua": (
            "GuildhallDB = {}\n"
        ),
        f"{root}/_forever_/WTF/Account/ACCOUNT2/SavedVariables/Guildhall.lua": (
            "GuildhallDB = {}\n"
        ),
        f"{root}/_classic_era_/.flavor.info": "Product Flavor!STRING:0\nwow_classic_era\n",
        f"{root}/Launcher.db": "x",
    }


@pytest.fixture
def forever_fs() -> FakeFileSystem:
    """Return a ``FakeFileSystem`` holding the default fake install tree."""
    return FakeFileSystem(forever_install_files())


@pytest.fixture
def forever_files() -> dict[str, str]:
    """Return a fresh copy of the default fake install tree for a test to edit."""
    return forever_install_files()


@pytest.fixture
def mac_root() -> str:
    """Return the macOS default install root used as the fake tree's root."""
    return MAC_ROOT


@pytest.fixture
def fake_fs_factory() -> Callable[..., FakeFileSystem]:
    """Return the ``FakeFileSystem`` constructor so tests can build custom trees."""
    return FakeFileSystem
