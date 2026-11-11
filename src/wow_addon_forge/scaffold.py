"""Scaffold an addon from the tested building blocks (created 2026-11-11).

Invariants owned by this file:
- A scaffold writes only inside ``dest``. A dest that already has entries is refused
  before any write.
- The addon name becomes a Lua global, so it must be a Lua identifier. The token
  ``@@ADDON@@`` in every copied file is replaced with that name.
- Modules are emitted in block order (core, log, sync, trust, window, bridge), and a
  requested module pulls in the blocks it calls. ``core`` is always included.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

TOKEN = "@@ADDON@@"
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ORDER = ("core", "log", "sync", "trust", "window", "bridge")
_NEEDS = {
    "core": (),
    "log": ("core",),
    "sync": ("core", "log"),
    "trust": ("core", "log"),
    "window": ("core",),
    "bridge": ("core",),
}
_EXTRA_FILES: dict[str, tuple[tuple[str, str], ...]] = {
    "log": (("Core/Log.lua", "Core/Log.lua"), ("Core/Reduce.lua", "Core/Reduce.lua")),
    "sync": (
        ("Core/Chunk.lua", "Core/Chunk.lua"),
        ("Core/Throttle.lua", "Core/Throttle.lua"),
        ("Core/Restrict.lua", "Core/Restrict.lua"),
        ("Core/Sync.lua", "Core/Sync.lua"),
    ),
    "trust": (("Core/Trust.lua", "Core/Trust.lua"),),
    "window": (("UI/Theme.lua", "UI/Theme.lua"), ("UI/Window.lua", "UI/Window.lua")),
    "bridge": (("Bridge.lua", "Bridge.lua"), ("Inbox.lua", "Inbox.lua")),
}

_BLOCKS = Path(__file__).resolve().parent / "blocks"


class ScaffoldError(Exception):
    """A foreseeable scaffold failure with a stable code and corrective hint.

    Why this exists: the tool layer maps this to the SPEC-PLUGIN §3 error envelope.
    Args: code, message, hint. ``str(exc)`` is the message.
    Returns: an instance with ``code``, ``message``, and ``hint``.
    Failure modes: none; construction cannot fail.
    """

    def __init__(self, code: str, message: str, hint: str) -> None:
        self.code = code
        self.message = message
        self.hint = hint
        super().__init__(message)


def _resolve_modules(modules: list[str]) -> list[str]:
    wanted = set(modules)
    for name in list(wanted):
        wanted.update(_NEEDS[name])
    return [name for name in _ORDER if name in wanted]


def _core_toc_files() -> tuple[str, list[str]]:
    toc_path = _BLOCKS / "core" / "addon.toc"
    text = toc_path.read_text(encoding="utf-8")
    interface = "## Interface: 16001"
    files: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Interface:"):
            interface = stripped
        elif stripped and not stripped.startswith("#"):
            files.append(stripped)
    return interface, files


def _module_copies(module: str) -> list[tuple[Path, str]]:
    if module == "core":
        _, files = _core_toc_files()
        return [(_BLOCKS / "core" / relative, relative) for relative in files]
    return [(_BLOCKS / module / source, dest) for source, dest in _EXTRA_FILES[module]]


def _tests_lua(name: str, modules: set[str]) -> str:
    slash = "/" + name.lower()
    key = "SLASH_" + name.upper() + "1"
    lines = [
        "-- Bundled scaffold checks for " + name + " (created 2026-11-11).",
        "test('slash is registered', function(ctx)",
        "    ctx.client:load_addon()",
        f'    assert_eq(ctx.client:eval("{key}"), "{slash}")',
        "end)",
    ]
    if "log" in modules:
        lines.extend(
            [
                "test('log stores a record', function(ctx)",
                "    ctx.client:load_addon()",
                "    assert_true(ctx.client:eval('"
                + name
                + ".Log.apply("
                + name
                + '.Log.new(), {a = "A", s = 1, t = 1, k = "note", v = 1})\'))',
                "end)",
            ]
        )
    if "window" in modules:
        lines.extend(
            [
                "test('window builds on first slash', function(ctx)",
                "    ctx.client:load_addon()",
                f"    assert_false(ctx.client:eval('{name}.Window.built'))",
                f"    assert_eq(ctx.client:eval('{name}.Theme.name'), 'Classic')",
                f'    assert_true(ctx.client:slash("{slash}"))',
                f"    assert_true(ctx.client:eval('{name}.Window.built'))",
                "end)",
            ]
        )
    return "\n".join(lines) + "\n"


def scaffold_addon(
    *,
    name: str,
    title: str,
    modules: list[str],
    dest: str | os.PathLike[str],
) -> dict[str, object]:
    """Copy the named building blocks into ``dest`` and write its TOC.

    Why this exists: ``wow_new`` is how an addon starts from code that already
        passes, instead of from an empty file (SPEC-PLUGIN §3, §8).
    Args: name, the addon folder and Lua global; title, the TOC title; modules,
        block names; dest, the addon folder to create or fill.
    Returns: ``addon``, ``path``, ``modules`` (resolved order), ``slash``, ``files``.
    Failure modes: ``ScaffoldError`` for a bad name, unknown module, a ``..`` dest,
        a dest that is a file, or a dest that already has entries. Nothing is
        written in those cases.
    """
    if not _NAME_RE.fullmatch(name):
        raise ScaffoldError(
            "bad-name",
            f"Addon name {name!r} is not a Lua identifier.",
            "Use a name of letters, digits and underscores, starting with a letter.",
        )
    unknown = [item for item in modules if item not in _NEEDS]
    if unknown:
        raise ScaffoldError(
            "bad-module",
            "Unknown building block: " + ", ".join(unknown),
            "Choose from core, log, sync, trust, window, bridge.",
        )
    if not modules:
        raise ScaffoldError(
            "bad-module",
            "wow_new needs at least one module.",
            "Pass modules including core, or the blocks you want.",
        )
    dest_path = Path(dest)
    if ".." in dest_path.parts:
        raise ScaffoldError(
            "bad-path",
            "dest must not contain a '..' segment.",
            "Pass the addon folder itself, not a path that walks upward.",
        )
    if dest_path.is_file():
        raise ScaffoldError(
            "bad-path",
            f"dest is a file, not a folder: {dest_path}",
            "Pass a new or empty directory.",
        )
    if dest_path.is_dir() and any(dest_path.iterdir()):
        raise ScaffoldError(
            "dest-not-empty",
            f"dest already has files: {dest_path}",
            "Pass a new or empty directory. Nothing was written.",
        )
    resolved = _resolve_modules(modules)
    copies: list[tuple[Path, str]] = []
    for module in resolved:
        copies.extend(_module_copies(module))
    missing = [str(source) for source, _dest in copies if not source.is_file()]
    if missing:
        raise ScaffoldError(
            "missing-block",
            "A building-block file is missing: " + missing[0],
            "The plugin's blocks directory is incomplete. Nothing was written.",
        )
    interface, _core_files = _core_toc_files()
    title_line = " ".join(title.split())
    if title_line == "":
        title_line = name
    toc_files = [relative for _source, relative in copies]
    if "bridge" in resolved and "Inbox.lua" not in toc_files:
        toc_files.append("Inbox.lua")
    header = [
        interface,
        f"## Title: {title_line}",
        f"## Notes: Scaffolded by wow_new for {name}.",
        f"## SavedVariables: {name}DB",
    ]
    if "bridge" in resolved:
        header.append("## X-Forge-Bridge: 1")
    toc_text = "\n".join(header) + "\n\n" + "\n".join(toc_files) + "\n"
    dest_path.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for source, relative in copies:
        target = dest_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8").replace(TOKEN, name)
        target.write_text(text, encoding="utf-8")
        written.append(relative)
    toc_name = f"{name}.toc"
    (dest_path / toc_name).write_text(toc_text, encoding="utf-8")
    written.append(toc_name)
    tests_rel = "Tests/scaffold.lua"
    tests_path = dest_path / tests_rel
    tests_path.parent.mkdir(parents=True, exist_ok=True)
    tests_path.write_text(_tests_lua(name, set(resolved)), encoding="utf-8")
    written.append(tests_rel)
    return {
        "addon": name,
        "path": str(dest_path),
        "modules": resolved,
        "slash": "/" + name.lower(),
        "files": written,
    }
