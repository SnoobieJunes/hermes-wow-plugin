"""Install an addon into a WoW flavor folder, with backup (created 2026-11-11).

Purpose: ``wow_install`` (T-010) copies or links an addon into
``<install>/<flavor>/Interface/AddOns/<name>`` and backs up whatever it replaces
into the plugin data directory, never into the game folder.

Invariants owned by this file:
- The destination name is the source folder's basename and must match
  ``^[A-Za-z0-9_!-]+$``. A ``..`` segment or an absolute addon name is refused
  before any write.
- Writes stay inside the located ``Interface/AddOns/<name>`` directory. Backups
  go to the injected data directory.
- ``dry_run`` reports the same ``reload`` / ``restart`` action a real install
  would, and writes nothing.
- A symlink destination is unlinked, never ``rmtree``'d, so replacing a link
  cannot delete the source tree.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from wow_addon_forge.env import FileSystem, hermes_home_dir
from wow_addon_forge.tocfile import parse_toc

_NAME_RE = re.compile(r"^[A-Za-z0-9_!-]+$")
_TRAVERSAL_HINT = "Pass the addon folder path. The destination name is its basename."
_PATH_HINT = "Pass the path to an existing addon directory containing <Addon>.toc."


def default_data_dir() -> Path:
    """Return the plugin data directory backups are written into.

    Why this exists: SPEC-PLUGIN §3 puts backups in the plugin's own data directory,
        never in the game folder. One function keeps the tool and the tests agreed.
    Args: none.
    Returns: ``<hermes_home>/cache/wow-addon-forge/backups`` via ``hermes_home_dir()``
        (follows ``hermes_constants.get_hermes_home()`` inside Hermes, falling back to
        ``$HERMES_HOME`` and ``~/.hermes`` standalone).
    Failure modes: none.
    """
    # [2026-11-11 T-060] Honour the active Hermes profile home via hermes_home_dir().
    return hermes_home_dir() / "cache" / "wow-addon-forge" / "backups"


class InstallError(Exception):
    """A foreseeable install failure with a stable code and corrective hint.

    Why this exists: the tool layer maps this to the SPEC-PLUGIN §3 error envelope
        without parsing message text.
    Args: code, message, hint. ``str(exc)`` is the message.
    Returns: an instance with ``code``, ``message``, and ``hint``.
    Failure modes: none; construction cannot fail.
    """

    def __init__(self, code: str, message: str, hint: str) -> None:
        self.code = code
        self.message = message
        self.hint = hint
        super().__init__(message)


class InstallWriter(Protocol):
    """Write surface ``install_addon`` needs on top of a readable filesystem.

    Why this exists: tests and production must share one install function, and the
        read-only ``env.FileSystem`` protocol does not grow write methods for this.
    Failure modes: implementations raise ``OSError`` when a write cannot be done.
    """

    def is_dir(self, path: str) -> bool:
        """Return whether ``path`` is an existing directory."""
        ...

    def is_file(self, path: str) -> bool:
        """Return whether ``path`` is an existing file."""
        ...

    def read_text(self, path: str) -> str:
        """Return a file's text, or raise ``OSError``."""
        ...

    def join(self, base: str, *parts: str) -> str:
        """Join ``base`` and ``parts`` into one path string."""
        ...

    def write_tree(self, source: str, dest: str) -> None:
        """Copy ``source`` directory tree to ``dest``, which must not exist."""
        ...

    def link_dir(self, source: str, dest: str) -> None:
        """Point ``dest`` at ``source`` as a directory symlink. ``dest`` must not exist."""
        ...

    def remove_dest(self, path: str) -> None:
        """Remove ``path``. A symlink is unlinked; a directory tree is deleted."""
        ...

    def copy_backup(self, source: str, dest: str) -> None:
        """Copy ``source`` into ``dest`` for a backup. ``dest`` must not exist."""
        ...


def flavor_folder(flavor: str | None) -> str:
    """Return the on-disk flavor folder for a tool argument.

    Why this exists: callers say ``forever``; the install layout says ``_forever_``.
    Args: flavor, or ``None`` / blank for the default ``_forever_``.
    Returns: ``_<name>_`` with the name lowercased and surrounding underscores removed.
    Failure modes: ``InstallError("bad-argument")`` when the name is not letters and digits.
    """
    raw = "_forever_" if flavor is None or not str(flavor).strip() else str(flavor).strip()
    name = raw.strip("_").lower()
    if not name or not re.fullmatch(r"[a-z0-9]+", name):
        raise InstallError(
            "bad-argument",
            f"Invalid flavor {flavor!r}.",
            "Pass a flavor such as forever or _forever_.",
        )
    return f"_{name}_"


def addon_name(path: str) -> str:
    """Return the safe addon folder name for a source path, or refuse it.

    Why this exists: SPEC-PLUGIN §3 allows writes only under ``AddOns/<name>`` where
        ``<name>`` matches ``^[A-Za-z0-9_!-]+$``. Traversal and absolute names never
        become a destination.
    Args: path, the addon folder the caller named.
    Returns: the final path segment, which is the destination folder name.
    Failure modes: ``InstallError("bad-argument")`` on an empty path, a ``..`` segment,
        or a basename that is not a safe addon name (slash, colon, dot, absolute).
    """
    if not isinstance(path, str) or not path.strip():
        raise InstallError("bad-argument", "wow_install needs a non-empty path.", _TRAVERSAL_HINT)
    normalised = path.strip().replace("\\", "/")
    parts = [part for part in normalised.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise InstallError(
            "bad-argument",
            f"Refused path {path!r}: traversal is not an addon name.",
            _TRAVERSAL_HINT,
        )
    name = parts[-1]
    # [2026-11-11 T-010] A colon is a drive-absolute name (C:Evil). The regex also
    # rejects slashes, so the destination cannot escape AddOns.
    if ":" in name or not _NAME_RE.fullmatch(name):
        raise InstallError(
            "bad-argument",
            f"Refused addon name {name!r}.",
            "Addon names are letters, digits, '_', '!' and '-' only.",
        )
    return name


def locate_addons_dir(fs: FileSystem, roots: Sequence[str], folder: str) -> str:
    """Find the one ``Interface/AddOns`` directory for a flavor under ``roots``.

    Why this exists: install must not guess when two installs both have the flavor,
        and must not write anywhere except that directory.
    Args: fs seam; roots to search; folder such as ``_forever_``.
    Returns: the single ``<root>/<folder>/Interface/AddOns`` path.
    Failure modes: ``InstallError("no-install")`` when none match,
        ``InstallError("ambiguous-install")`` when more than one does.
    """
    matches = [
        fs.join(root, folder, "Interface", "AddOns")
        for root in roots
        if fs.is_dir(fs.join(root, folder, "Interface", "AddOns"))
    ]
    if not matches:
        raise InstallError(
            "no-install",
            f"No WoW install with flavor {folder} and an Interface/AddOns folder was found.",
            "Check the install path and flavor, or create the AddOns folder by logging in once.",
        )
    if len(matches) > 1:
        raise InstallError(
            "ambiguous-install",
            f"Found {len(matches)} installs with flavor {folder}; pass one root.",
            "Set the plugin wow_root, or call again with a single install root.",
        )
    return matches[0]


def _toc_files(fs: FileSystem, addon_dir: str, name: str) -> set[str] | None:
    toc_path = fs.join(addon_dir, f"{name}.toc")
    if not fs.is_file(toc_path):
        return None
    return set(parse_toc(fs.read_text(toc_path)).files)


def client_action(
    *, existed: bool, old_files: set[str] | None, new_files: set[str] | None
) -> tuple[str, str]:
    """Decide whether the client needs ``/reload`` or a restart after this install.

    Why this exists: a new addon folder, or a TOC that lists a file the installed
        TOC did not, is invisible until a client restart (AGENTS.md foot-gun). A
        change to files the old TOC already listed is picked up on ``/reload``.
    Args: existed, whether the destination folder was already there; old_files and
        new_files, the TOC file lists, or ``None`` when that TOC is missing.
    Returns: ``(action, note)`` where action is ``reload`` or ``restart``.
    Failure modes: none; a missing TOC is ``restart``, the conservative answer.
    """
    if not existed:
        return "restart", "new addon folder; the client lists it only after a restart"
    if old_files is None or new_files is None:
        return "restart", "TOC missing; a restart is the safe load"
    added = new_files - old_files
    if added:
        names = ", ".join(sorted(added))
        return "restart", f"new TOC file(s) {names}; a new file needs a client restart"
    return "reload", "every listed file was already in the installed TOC; /reload is enough"


def _backup_path(data_dir: str, name: str, clock: Callable[[], float], fs: FileSystem) -> str:
    stamp = str(int(clock()))
    candidate = fs.join(data_dir, f"{name}-{stamp}")
    suffix = 2
    while fs.is_dir(candidate) or fs.is_file(candidate):
        candidate = fs.join(data_dir, f"{name}-{stamp}-{suffix}")
        suffix += 1
    return candidate


def install_addon(
    fs: FileSystem,
    writer: InstallWriter,
    *,
    source: str,
    addons_dir: str,
    data_dir: str,
    clock: Callable[[], float],
    mode: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Copy or link ``source`` into ``addons_dir/<name>``, backing up a replacement.

    Why this exists: the write rules (destination, backup location, dry-run, reload
        versus restart) live in one function the tool handler does not reimplement.
    Args: fs for reads; writer for the mutating calls; source addon folder; addons_dir
        the located ``Interface/AddOns``; data_dir for backups; clock for the backup
        stamp; mode ``copy`` or ``link``; dry_run to report without writing.
    Returns: ``addon``, ``dest``, ``mode``, ``action``, ``note``, ``backup`` (or
        ``None``), ``dry_run``. Does not include the check verdict; the caller does.
    Failure modes: ``InstallError`` for an unsafe name, a missing source, a bad mode,
        or a destination that is not inside ``addons_dir``. ``OSError`` from the writer
        propagates so the tool can report ``install-failed``.
    """
    if mode not in ("copy", "link"):
        raise InstallError(
            "bad-argument",
            f"mode must be copy or link, got {mode!r}.",
            "Pass mode copy (default) or link.",
        )
    name = addon_name(source)
    if not fs.is_dir(source):
        raise InstallError("bad-path", f"Addon path is not a directory: {source}", _PATH_HINT)
    dest = fs.join(addons_dir, name)
    prefix = addons_dir.rstrip("/\\") + "/"
    if not dest.replace("\\", "/").startswith(prefix.replace("\\", "/")):
        raise InstallError(
            "bad-argument",
            f"Refused destination {dest!r}: it is not inside AddOns.",
            _TRAVERSAL_HINT,
        )
    existed = fs.is_dir(dest)
    action, note = client_action(
        existed=existed,
        old_files=_toc_files(fs, dest, name) if existed else None,
        new_files=_toc_files(fs, source, name),
    )
    backup = _backup_path(data_dir, name, clock, fs) if existed else None
    if dry_run:
        return {
            "addon": name,
            "dest": dest,
            "mode": mode,
            "action": action,
            "note": note,
            "backup": backup,
            "dry_run": True,
        }
    if existed and backup is not None:
        writer.copy_backup(dest, backup)
        writer.remove_dest(dest)
    if mode == "link":
        writer.link_dir(source, dest)
    else:
        writer.write_tree(source, dest)
    return {
        "addon": name,
        "dest": dest,
        "mode": mode,
        "action": action,
        "note": note,
        "backup": backup,
        "dry_run": False,
    }


class RealInstallWriter:
    """Production ``InstallWriter`` over ``os`` / ``shutil`` (created 2026-11-11).

    Why this exists: ``env.RealFileSystem`` stays read-only; install writes go through
        this adapter so a test can still inject a fake.
    Failure modes: ``OSError`` from the OS propagates unchanged.
    """

    def is_dir(self, path: str) -> bool:
        """Return whether ``path`` is an existing directory, following links."""
        return Path(path).is_dir()

    def is_file(self, path: str) -> bool:
        """Return whether ``path`` is an existing file."""
        return Path(path).is_file()

    def read_text(self, path: str) -> str:
        """Return a file's UTF-8 text."""
        return Path(path).read_text(encoding="utf-8")

    def join(self, base: str, *parts: str) -> str:
        """Join with ``pathlib`` so the production layout matches the OS."""
        return str(Path(base, *parts))

    def write_tree(self, source: str, dest: str) -> None:
        """Copy ``source`` to ``dest`` with ``shutil.copytree``."""
        shutil.copytree(source, dest)

    def link_dir(self, source: str, dest: str) -> None:
        """Symlink ``dest`` to the absolute ``source`` directory."""
        os.symlink(os.path.abspath(source), dest, target_is_directory=True)

    def remove_dest(self, path: str) -> None:
        """Unlink a symlink; otherwise delete a directory tree or a file.

        Why a symlink is unlinked only: ``shutil.rmtree`` on a link can delete the
        source tree the link points at, which is the opposite of a backup.
        """
        target = Path(path)
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    def copy_backup(self, source: str, dest: str) -> None:
        """Copy ``source`` to ``dest``, following a directory symlink so the bytes are kept."""
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, dest, symlinks=False)
