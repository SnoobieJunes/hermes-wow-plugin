"""Find WoW installs through an injected filesystem (created 2026-11-11).

Invariants owned by this file:
- Detection never raises for a malformed install: everything skipped or unreadable becomes a
  string in the report's ``warnings``, so an empty result is always explained.
- The client Interface number is DERIVED from the client version, and the report says so; the
  pair 1.60.1 <-> 16001 is the one this project has verified (AGENTS.md foot-guns).
- Account NAMES are never reported (personal data); only the account count leaves this file.
- All filesystem access goes through the ``FileSystem`` protocol, so tests inject an in-memory
  fake and never touch a real install.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from wow_addon_forge import tocfile

DEFAULT_ROOTS: tuple[str, ...] = (
    "/Applications/World of Warcraft",
    "C:\\Program Files (x86)\\World of Warcraft",
)


def hermes_home_dir() -> Path:
    """Return the active Hermes profile home directory.

    Why this exists:
        Inside Hermes Agent, ``hermes_constants.get_hermes_home()`` resolves the active
        profile (including context-local overrides in Desktop and gateway sessions, not
        only ``$HERMES_HOME``). Standalone CLI runs and CI execute outside the Hermes
        checkout where ``hermes_constants`` is not installed, so they fall back to
        ``$HERMES_HOME`` and then ``~/.hermes``.

    Args:
        None.

    Returns:
        Path to the active Hermes home directory (never created by this helper).

    Failure modes:
        None; missing ``hermes_constants`` falls back to environment/home resolution.
    """
    # [2026-11-11 T-060] Import dynamically so standalone `uv run mypy src` and CI run
    # without Hermes's root modules on sys.path while live plugin sessions honour
    # hermes_constants.get_hermes_home() across named profiles.
    try:
        constants_mod = importlib.import_module("hermes_constants")
        get_home = getattr(constants_mod, "get_hermes_home", None)
        if callable(get_home):
            return Path(get_home())
    except ImportError:
        pass
    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    return Path(hermes_home).expanduser() if hermes_home else Path.home() / ".hermes"


class FileSystem(Protocol):
    """The narrow filesystem surface detection needs.

    Why this exists:
        One injected seam keeps detection testable against an in-memory tree on every OS,
        including a Windows-rooted tree on a Mac.

    Failure modes:
        ``list_dir`` and ``read_text`` raise ``OSError`` when a path is missing or unreadable;
        callers turn that into report warnings.
    """

    def is_dir(self, path: str) -> bool:
        """Return whether ``path`` is an existing directory."""
        ...

    def is_file(self, path: str) -> bool:
        """Return whether ``path`` is an existing file."""
        ...

    def list_dir(self, path: str) -> list[str]:
        """Return the sorted entry NAMES (not paths) of a directory, or raise ``OSError``."""
        ...

    def read_text(self, path: str) -> str:
        """Return a file's text, or raise ``OSError``."""
        ...

    def join(self, base: str, *parts: str) -> str:
        """Join ``base`` and ``parts`` into one path string."""
        ...


class RealFileSystem:
    """Production ``FileSystem`` over ``os`` / ``pathlib``.

    Why this exists:
        The one adapter that touches a real disk; everything else in this file stays pure.

    Failure modes:
        ``list_dir`` and ``read_text`` propagate ``OSError`` from the OS unchanged.
    """

    def is_dir(self, path: str) -> bool:
        """Return whether ``path`` is an existing directory.

        Args:
            path: The path to test.

        Returns:
            ``True`` only for an existing directory.

        Failure modes:
            None; a missing path gives ``False``.
        """
        return os.path.isdir(path)

    def is_file(self, path: str) -> bool:
        """Return whether ``path`` is an existing file.

        Args:
            path: The path to test.

        Returns:
            ``True`` only for an existing file.

        Failure modes:
            None; a missing path gives ``False``.
        """
        return os.path.isfile(path)

    def list_dir(self, path: str) -> list[str]:
        """Return the sorted entry names of a real directory.

        Args:
            path: The directory to list.

        Returns:
            Entry names (not paths), sorted.

        Failure modes:
            Raises ``OSError`` when the directory is missing or unreadable.
        """
        return sorted(os.listdir(path))

    def read_text(self, path: str) -> str:
        """Read a real file as text.

        Args:
            path: The file to read.

        Returns:
            The file text, decoded as UTF-8 with an optional BOM (``utf-8-sig``) and with
            undecodable bytes replaced rather than raised.

        Failure modes:
            Raises ``OSError`` when the file is missing or unreadable.
        """
        # [2026-11-11 T-003] utf-8-sig plus errors='replace': a TOC may start with a BOM or
        # hold bytes that are not UTF-8, and neither may abort detection of a whole install.
        return Path(path).read_text(encoding="utf-8-sig", errors="replace")

    def join(self, base: str, *parts: str) -> str:
        """Join path parts with the host separator.

        Args:
            base: The leading path.
            parts: Further path components.

        Returns:
            ``os.path.join(base, *parts)``.

        Failure modes:
            None.
        """
        return os.path.join(base, *parts)


@dataclass(frozen=True)
class AddonInfo:
    """The reported facts of one installed addon folder.

    Args:
        name: The addon folder name.
        toc: File name of the TOC the facts below were read from.
        title: Plain-text TOC title, or ``None``.
        version: TOC version, or ``None``.
        interface: Interface numbers declared by the chosen TOC.
        supports_client: Whether the client Interface number is in ``interface``; ``None``
            when the client number is unknown.

    Failure modes:
        None; unknown facts are ``None`` by construction.
    """

    name: str
    toc: str
    title: str | None
    version: str | None
    interface: tuple[int, ...]
    supports_client: bool | None


@dataclass(frozen=True)
class FlavorInfo:
    """The reported facts of one flavor folder (one game product under an install root).

    Args:
        flavor: Folder name, e.g. ``_forever_``.
        product: Product code from ``.flavor.info``, e.g. ``wowf``, or ``None``.
        version: Client version from ``.build.info``, e.g. ``1.60.1.70888``, or ``None``.
        interface: Interface number derived from ``version``, e.g. ``16001``, or ``None``.
        accounts: Number of account directories under ``WTF/Account`` (names never reported).
        addons: The addons found under ``Interface/AddOns``, sorted case-insensitively.

    Failure modes:
        None; unknown facts are ``None``, with the reason in the report's warnings.
    """

    flavor: str
    product: str | None
    version: str | None
    interface: int | None
    accounts: int
    addons: tuple[AddonInfo, ...]


@dataclass(frozen=True)
class InstallInfo:
    """One install root that holds at least one flavor folder.

    Args:
        root: The install root path as searched.
        flavors: The flavor folders found under it, in sorted folder-name order.

    Failure modes:
        None.
    """

    root: str
    flavors: tuple[FlavorInfo, ...]


@dataclass(frozen=True)
class EnvReport:
    """The full detection result: installs found, roots searched, and everything skipped.

    Args:
        installs: Installs that held at least one flavor folder.
        searched: Every root that was looked at, in search order.
        warnings: One string per skip, unreadable path, or unknown fact; nothing is
            swallowed silently.

    Failure modes:
        None; ``to_dict`` builds plain JSON-serialisable data only.
    """

    installs: tuple[InstallInfo, ...]
    searched: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return this report as plain JSON-serialisable data.

        Why this exists:
            Tool results cross the Hermes boundary as JSON, so the wire shape is pinned in
            one place.

        Returns:
            ``{"installs": [...], "searched": [...], "warnings": [...]}`` with, per flavor,
            the keys ``flavor``, ``product``, ``version``, ``interface``,
            ``interface_source``, ``accounts``, ``addon_count`` and ``addons`` in that order.
            ``interface_source`` is ``"derived-from-version"`` when ``interface`` is known,
            else ``None``.

        Failure modes:
            None.
        """
        # [2026-11-11 T-003] Account names are personal data: only the count is serialised.
        installs: list[dict[str, Any]] = []
        for install in self.installs:
            flavors: list[dict[str, Any]] = []
            for flavor in install.flavors:
                addons: list[dict[str, Any]] = [
                    {
                        "name": addon.name,
                        "toc": addon.toc,
                        "title": addon.title,
                        "version": addon.version,
                        "interface": list(addon.interface),
                        "supports_client": addon.supports_client,
                    }
                    for addon in flavor.addons
                ]
                flavors.append(
                    {
                        "flavor": flavor.flavor,
                        "product": flavor.product,
                        "version": flavor.version,
                        "interface": flavor.interface,
                        "interface_source": (
                            "derived-from-version" if flavor.interface is not None else None
                        ),
                        "accounts": flavor.accounts,
                        "addon_count": len(flavor.addons),
                        "addons": addons,
                    }
                )
            installs.append({"root": install.root, "flavors": flavors})
        return {
            "installs": installs,
            "searched": list(self.searched),
            "warnings": list(self.warnings),
        }


def interface_from_version(version: str) -> int | None:
    """Derive the Interface number from a dotted client version.

    Why this exists:
        ``.build.info`` records the client version, not the Interface number addons declare
        support for, so the number is derived: major*10000 + minor*100 + patch.

    Args:
        version: A dotted version such as ``1.60.1.70888``.

    Returns:
        The derived number (``16001`` for ``1.60.1.70888``), or ``None`` unless there are at
        least three dot-separated all-digit parts with minor < 100 and patch < 100.

    Failure modes:
        None; an underivable version gives ``None``.
    """
    # [2026-11-11 T-003] The Interface number is DERIVED from the client version; the pair
    # 1.60.1 <-> 16001 is the one this project has verified (AGENTS.md foot-guns), and the
    # report says the number is derived.
    parts = version.split(".")
    if len(parts) < 3:
        return None
    major_text, minor_text, patch_text = parts[0], parts[1], parts[2]
    if not (major_text.isdigit() and minor_text.isdigit() and patch_text.isdigit()):
        return None
    major, minor, patch = int(major_text), int(minor_text), int(patch_text)
    if minor >= 100 or patch >= 100:
        return None
    return major * 10000 + minor * 100 + patch


def parse_build_info(text: str) -> dict[str, str]:
    """Parse ``.build.info`` text into a product-code to version-string map.

    Why this exists:
        One install root can carry several products; each flavor looks its product up here
        to learn its client version.

    Args:
        text: Pipe-delimited text whose first line is a header of ``Name!TYPE:n`` cells.
            CRLF line endings are tolerated.

    Returns:
        Product code (e.g. ``wowf``) to version string (e.g. ``1.60.1.70888``). Returns
        ``{}`` unless both a ``Version`` and a ``Product`` column exist. Blank lines, rows
        with fewer cells than needed, and rows with an empty product cell are skipped; the
        first row for a product wins.

    Failure modes:
        None; malformed input degrades to fewer rows or ``{}``.
    """
    lines = text.splitlines()
    if not lines:
        return {}
    columns = [cell.split("!", 1)[0].strip() for cell in lines[0].split("|")]
    if "Version" not in columns or "Product" not in columns:
        return {}
    version_index = columns.index("Version")
    product_index = columns.index("Product")
    needed = max(version_index, product_index)
    versions: dict[str, str] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split("|")
        if len(cells) <= needed:
            continue
        product = cells[product_index].strip()
        if not product or product in versions:
            continue
        versions[product] = cells[version_index].strip()
    return versions


def parse_flavor_info(text: str) -> str | None:
    """Parse ``.flavor.info`` text into its product code.

    Args:
        text: The file text: a header line ``Product Flavor!STRING:0`` then the code.

    Returns:
        The second non-empty stripped line (e.g. ``wowf``), or ``None`` when there are
        fewer than two.

    Failure modes:
        None.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    return lines[1]


def _list_dir(fs: FileSystem, path: str, warnings: list[str]) -> list[str]:
    try:
        return fs.list_dir(path)
    except OSError as exc:
        warnings.append(f"{path} could not be listed: {exc}")
        return []


def _read_text(fs: FileSystem, path: str, warnings: list[str], reason: str) -> str | None:
    try:
        return fs.read_text(path)
    except OSError as exc:
        warnings.append(f"{path} could not be read: {exc}; {reason}")
        return None


def _flavor_folders(fs: FileSystem, root: str, warnings: list[str]) -> list[str]:
    names: list[str] = []
    for name in sorted(_list_dir(fs, root, warnings)):
        if len(name) <= 2 or not name.startswith("_") or not name.endswith("_"):
            continue
        flavor_path = fs.join(root, name)
        if not fs.is_dir(flavor_path):
            continue
        if fs.is_file(fs.join(flavor_path, ".flavor.info")) or fs.is_dir(
            fs.join(flavor_path, "Interface")
        ):
            names.append(name)
    return names


def _build_versions(fs: FileSystem, root: str, warnings: list[str]) -> dict[str, str] | None:
    # [2026-11-11 T-003] None means "unknown, and already explained in one warning". Callers
    # must not add a per-flavor "no row" warning on top of it: one cause, one line.
    build_path = fs.join(root, ".build.info")
    if not fs.is_file(build_path):
        warnings.append(f"{build_path} is missing; client versions are unknown")
        return None
    text = _read_text(fs, build_path, warnings, "client versions are unknown")
    if text is None:
        return None
    versions = parse_build_info(text)
    if not versions:
        warnings.append(f"{build_path} has no Version and Product row; client versions are unknown")
        return None
    return versions


def _flavor_product(fs: FileSystem, flavor_path: str, warnings: list[str]) -> str | None:
    info_path = fs.join(flavor_path, ".flavor.info")
    if not fs.is_file(info_path):
        warnings.append(f"{info_path} is missing; product is unknown")
        return None
    text = _read_text(fs, info_path, warnings, "product is unknown")
    if text is None:
        return None
    product = parse_flavor_info(text)
    if product is None:
        warnings.append(f"{info_path} could not be parsed; product is unknown")
    return product


def _account_count(fs: FileSystem, flavor_path: str, warnings: list[str]) -> int:
    # [2026-11-11 T-003] Only the count is kept: account folder names are personal data and
    # never enter the report.
    account_root = fs.join(flavor_path, "WTF", "Account")
    if not fs.is_dir(account_root):
        return 0
    return sum(
        1
        for name in _list_dir(fs, account_root, warnings)
        if fs.is_dir(fs.join(account_root, name))
    )


def _is_toc_candidate(file_name: str, folder: str) -> bool:
    lowered = file_name.lower()
    if not lowered.endswith(".toc"):
        return False
    stem = lowered[: -len(".toc")]
    base = folder.lower()
    return stem == base or stem.startswith(base + "_") or stem.startswith(base + "-")


def _choose_toc(
    parsed: Sequence[tuple[str, tocfile.TocFile]], folder: str, client_interface: int | None
) -> tuple[str, tocfile.TocFile]:
    # [2026-11-11 T-003] The choice is by Interface match, then the base '<D>.toc', then the
    # first candidate in sorted order. It is NOT a claim about which suffixed TOC the live
    # client prefers (not verified in game).
    if client_interface is not None:
        for name, parsed_toc in parsed:
            if client_interface in parsed_toc.interface:
                return name, parsed_toc
    base_name = f"{folder}.toc".lower()
    for name, parsed_toc in parsed:
        if name.lower() == base_name:
            return name, parsed_toc
    return parsed[0]


def _addon_info(
    fs: FileSystem,
    addon_path: str,
    folder: str,
    client_interface: int | None,
    warnings: list[str],
) -> AddonInfo | None:
    try:
        entries = fs.list_dir(addon_path)
    except OSError as exc:
        # [2026-11-11 T-003] Reported as unlistable and nothing else: falling through would add
        # a second, wrong warning that the folder has no TOC.
        warnings.append(f"{addon_path} could not be listed: {exc}; skipped")
        return None
    candidates = sorted(
        name
        for name in entries
        if fs.is_file(fs.join(addon_path, name)) and _is_toc_candidate(name, folder)
    )
    if not candidates:
        warnings.append(f"{addon_path} has no TOC named after its folder; skipped")
        return None
    parsed: list[tuple[str, tocfile.TocFile]] = []
    for name in candidates:
        toc_path = fs.join(addon_path, name)
        text = _read_text(fs, toc_path, warnings, "candidate dropped")
        if text is not None:
            parsed.append((name, tocfile.parse_toc(text)))
    if not parsed:
        return None
    chosen_name, chosen = _choose_toc(parsed, folder, client_interface)
    supports_client = None if client_interface is None else client_interface in chosen.interface
    return AddonInfo(
        name=folder,
        toc=chosen_name,
        title=chosen.title,
        version=chosen.version,
        interface=chosen.interface,
        supports_client=supports_client,
    )


def _flavor_addons(
    fs: FileSystem, flavor_path: str, client_interface: int | None, warnings: list[str]
) -> tuple[AddonInfo, ...]:
    addons_root = fs.join(flavor_path, "Interface", "AddOns")
    if not fs.is_dir(addons_root):
        return ()
    folders = sorted(
        (
            name
            for name in _list_dir(fs, addons_root, warnings)
            if fs.is_dir(fs.join(addons_root, name))
        ),
        key=str.lower,
    )
    addons: list[AddonInfo] = []
    for folder in folders:
        info = _addon_info(fs, fs.join(addons_root, folder), folder, client_interface, warnings)
        if info is not None:
            addons.append(info)
    return tuple(addons)


def _flavor_info(
    fs: FileSystem,
    root: str,
    flavor: str,
    versions: dict[str, str] | None,
    warnings: list[str],
) -> FlavorInfo:
    flavor_path = fs.join(root, flavor)
    product = _flavor_product(fs, flavor_path, warnings)
    version: str | None = None
    if product is not None and versions is not None:
        version = versions.get(product)
        if version is None:
            warnings.append(
                f"no .build.info row for product {product} under {root}; version is unknown"
            )
    interface = interface_from_version(version) if version is not None else None
    return FlavorInfo(
        flavor=flavor,
        product=product,
        version=version,
        interface=interface,
        accounts=_account_count(fs, flavor_path, warnings),
        addons=_flavor_addons(fs, flavor_path, interface, warnings),
    )


def detect_installs(fs: FileSystem, roots: Sequence[str] | None = None) -> EnvReport:
    """Detect WoW installs under ``roots`` through the injected filesystem.

    Why this exists:
        The one entry point the ``wow_env`` tool reports from: which installs, flavors,
        client versions, accounts and addons are actually on this machine.

    Args:
        fs: The filesystem to look through (``RealFileSystem`` in production).
        roots: Install roots to search, in order; ``DEFAULT_ROOTS`` when ``None``.

    Returns:
        An ``EnvReport``. Every root appears in ``searched``; a root that is not a directory
        is skipped silently, and a root with no flavor folder (an entry longer than two
        characters, wrapped in ``_``, holding ``.flavor.info`` or ``Interface``) earns a
        warning and is not treated as an install. Each flavor's product comes from
        ``.flavor.info``, its version from ``.build.info``, and its Interface number is
        derived from that version.

    Failure modes:
        Never raises for a malformed install: any ``OSError`` from listing or reading becomes
        a warning naming the path, and the affected listing is treated as empty.
    """
    warnings: list[str] = []
    searched: list[str] = []
    installs: list[InstallInfo] = []
    for root in DEFAULT_ROOTS if roots is None else roots:
        searched.append(root)
        if not fs.is_dir(root):
            continue
        flavors = _flavor_folders(fs, root, warnings)
        if not flavors:
            warnings.append(
                f"{root} exists but holds no flavor folder such as _forever_; "
                "not treated as a WoW install"
            )
            continue
        versions = _build_versions(fs, root, warnings)
        installs.append(
            InstallInfo(
                root=root,
                flavors=tuple(
                    _flavor_info(fs, root, flavor, versions, warnings) for flavor in flavors
                ),
            )
        )
    return EnvReport(
        installs=tuple(installs),
        searched=tuple(searched),
        warnings=tuple(warnings),
    )
