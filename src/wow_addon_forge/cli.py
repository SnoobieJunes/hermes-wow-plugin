"""Slash command and CLI verbs for wow-addon-forge (created 2026-11-11).

Invariants owned by this file:
- ``/wow status`` and ``hermes wow status`` print the same install, build, and index lines.
- ``check`` exits non-zero when ``wow_check`` verdict is ``fail``.
- This file writes nothing. It only reads through the injected ``ForgeTools``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from wow_addon_forge.tools import ForgeTools

SKILL_NAME = "wow-addon-builder"
SKILL_DESCRIPTION = "Use when building a WoW Forever addon."


def skill_path() -> Path:
    """Return the bundled ``SKILL.md`` path.

    Why this exists: registration and the frontmatter test must name one file.
    Returns: the path under the repo ``skills/`` directory.
    Failure modes: none; the file may be absent, and the caller checks ``is_file``.
    """
    return Path(__file__).resolve().parents[2] / "skills" / SKILL_NAME / "SKILL.md"


def format_status(tools: ForgeTools) -> str:
    """Print install, build, and index state as three labeled lines.

    Why this exists: ``/wow status`` and the CLI ``status`` verb must say the same
        thing, so the text is built once.
    Args: tools, the injected ``ForgeTools`` (a fake install in tests).
    Returns: a multi-line status string. A missing install or index is still a line.
    Failure modes: none; tool errors become a labeled line, not an exception.
    """
    env = tools.env_result({})
    api = tools.api_result({"action": "status"})
    lines = ["wow status"]
    if env.get("ok") and env.get("installs"):
        install = env["installs"][0]
        flavors = install.get("flavors") or [{}]
        flavor = next(
            (item for item in flavors if item.get("flavor") == "_forever_"),
            flavors[0],
        )
        lines.append(
            f"install: {install.get('root')} flavor={flavor.get('flavor')} "
            f"addons={flavor.get('addon_count')}"
        )
        lines.append(f"build: {flavor.get('version')} interface={flavor.get('interface')}")
    else:
        code = (env.get("error") or {}).get("code", "missing")
        lines.append(f"install: {code}")
        lines.append("build: unknown")
    if api.get("ok"):
        lines.append(
            f"index: flavor={api.get('flavor')} build={api.get('build')} source={api.get('source')}"
        )
    else:
        code = (api.get("error") or {}).get("code", "missing")
        lines.append(f"index: {code}")
    return "\n".join(lines)


def run_check(tools: ForgeTools, path: str) -> tuple[str, int]:
    """Run ``wow_check`` and map a ``fail`` verdict to a non-zero exit.

    Why this exists: the CLI ``check`` verb is a scriptable twin of the tool, and a
        failing addon must not look like success to a shell.
    Args: tools; path, the addon folder.
    Returns: ``(text, exit_code)``. Exit 1 when the verdict is ``fail`` or the tool
        errors. Exit 0 only when the verdict is ``pass``.
    Failure modes: none; a tool error is exit 1 with the JSON error text.
    """
    result = tools.check_result({"path": path})
    if not result.get("ok"):
        return json.dumps(result), 1
    verdict = str(result.get("verdict"))
    code = 0 if verdict == "pass" else 1
    return f"verdict: {verdict}", code


def handle_slash(raw_args: str = "", *, tools: ForgeTools | None = None) -> str:
    """Handle ``/wow``. ``status`` is the default.

    Why this exists: a turn that does not depend on the model choosing a tool
        (SPEC-PLUGIN §2).
    Args: raw_args, the text after ``/wow``; tools, injected in tests.
    Returns: the status text, a check verdict, or a usage line.
    Failure modes: none.
    """
    active = tools if tools is not None else ForgeTools()
    text = (raw_args or "").strip()
    if text in ("", "status"):
        return format_status(active)
    if text == "check" or text.startswith("check "):
        path = text[5:].strip()
        if path == "":
            return "usage: /wow check <path>"
        body, _code = run_check(active, path)
        return body
    return "usage: /wow status | check <path> | errors | bridge"


def add_status_and_check(subparsers: Any) -> None:
    """Add ``status`` and ``check`` verbs to an existing subparser group.

    Why this exists: the module CLI already owns the subparsers; Hermes hands a
        fresh parser. Both must grow the same two verbs.
    Args: subparsers, the object returned by ``add_subparsers``.
    Returns: none.
    Failure modes: none.
    """
    subparsers.add_parser("status", help="print install, build and index state")
    check = subparsers.add_parser("check", help="run wow_check; exit non-zero on fail")
    check.add_argument("path", help="addon folder to check")


def setup_wow_cli(parser: argparse.ArgumentParser) -> None:
    """Add ``status`` and ``check`` to a ``hermes wow`` subparser.

    Why this exists: ``ctx.register_cli_command`` hands us the parser; the verbs
        stay next to the slash handler so they cannot drift.
    Args: parser, the subparser Hermes provides.
    Returns: none; the parser gains the verbs.
    Failure modes: none.
    """
    add_status_and_check(parser.add_subparsers(dest="wow_verb"))


def handle_wow_cli(ns: argparse.Namespace, *, tools: ForgeTools | None = None) -> int:
    """Run one ``hermes wow`` verb and print its text.

    Why this exists: the Hermes CLI handler and the module CLI share this exit code.
    Args: ns, with ``wow_verb`` and, for check, ``path``; tools, injected in tests.
    Returns: the process exit code.
    Failure modes: none; an unknown verb returns 2.
    """
    active = tools if tools is not None else ForgeTools()
    verb = getattr(ns, "wow_verb", None)
    if verb == "status":
        print(format_status(active))
        return 0
    if verb == "check":
        text, code = run_check(active, str(ns.path))
        print(text)
        return code
    return 2


def register_surfaces(ctx: Any) -> None:
    """Register the skill, ``/wow``, and ``hermes wow`` when the context supports them.

    Why this exists: ``register(ctx)`` is the one place Hermes learns these surfaces.
        A test double that only has ``register_tool`` must still succeed.
    Args: ctx, a PluginContext or a recording stub.
    Returns: none.
    Failure modes: a missing method is skipped, not raised.
    """
    register_skill = getattr(ctx, "register_skill", None)
    path = skill_path()
    if callable(register_skill) and path.is_file():
        register_skill(SKILL_NAME, path, description=SKILL_DESCRIPTION)
    register_command = getattr(ctx, "register_command", None)
    if callable(register_command):
        register_command(
            "wow",
            handler=handle_slash,
            description="Print WoW install, build, and index state, or check an addon.",
            args_hint="[status|check <path>]",
        )
    register_cli = getattr(ctx, "register_cli_command", None)
    if callable(register_cli):
        register_cli(
            name="wow",
            help="WoW addon forge status and check",
            setup_fn=setup_wow_cli,
            handler_fn=handle_wow_cli,
            description="Print install, build, and index state, or check an addon.",
        )
