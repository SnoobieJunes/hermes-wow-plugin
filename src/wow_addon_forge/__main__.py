"""Command-line entry for wow-addon-forge: ``python -m wow_addon_forge`` (created 2026-11-11).

Invariant owned by this file: the module CLI is the scriptable twin of the Hermes tools. Verbs are
added by the task that adds the matching tool; this file never grows logic of its own. The ``env``
verb is the twin of the ``wow_env`` tool and the ``api`` verb the twin of ``wow_api``: each calls
``ForgeTools`` and prints the result as JSON.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from wow_addon_forge import PLUGIN_ID, __version__
from wow_addon_forge.tools import WOW_API_ACTIONS, WOW_API_SOURCES, ForgeTools


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (kept separate so tests can inspect it).

    Why this exists:
        Tests and ``main`` must agree on the one CLI shape, so the parser is built here
        exactly once per caller.

    Returns:
        A parser with ``--version``, the ``env`` verb (optional ``--root PATH``) and the
        ``api`` verb (an action, an optional name or query, ``--flavor`` and ``--source``).
        The verb is not required: no verb prints usage.

    Failure modes:
        None at construction; unknown arguments are rejected at parse time by argparse.
    """
    parser = argparse.ArgumentParser(
        prog="wow_addon_forge",
        description="Build World of Warcraft: Forever addons that load and run.",
    )
    parser.add_argument("--version", action="store_true", help="print the plugin version and exit")
    subparsers = parser.add_subparsers(dest="verb")
    # [2026-11-11 T-003] The env verb mirrors the wow_env tool argument-for-argument: one
    # optional --root, and no CLI-only options to drift from the tool schema.
    env_parser = subparsers.add_parser("env", help="find WoW installs and installed addons")
    env_parser.add_argument(
        "--root",
        metavar="PATH",
        default=None,
        help="the World of Warcraft folder to inspect (default: search default locations)",
    )
    # [2026-11-11 T-005] The api verb mirrors the wow_api tool. The tool's `name` (lookup) and
    # `query` (search, events) are one optional positional here, because a shell user types
    # `api lookup C_Item.GetItemInfo`, not a flag; main() maps it onto the right argument.
    api_parser = subparsers.add_parser("api", help="build and query the API index")
    api_parser.add_argument(
        "action",
        choices=WOW_API_ACTIONS,
        help="sync downloads the mirrors and rebuilds the index; the rest only read it",
    )
    api_parser.add_argument(
        "term",
        nargs="?",
        default=None,
        help="lookup: the exact name; search: text to find; events: an optional filter",
    )
    api_parser.add_argument(
        "--flavor",
        default=None,
        help="the game flavor (default and only supported value: forever)",
    )
    api_parser.add_argument(
        "--source",
        choices=WOW_API_SOURCES,
        default=None,
        help="sync only: where the documentation comes from (default: auto)",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, tools: ForgeTools | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments without the program name; ``None`` reads ``sys.argv``.
        tools: The ``ForgeTools`` the verbs call; a default ``ForgeTools`` is built when
            ``None``. Tests inject one so the real game install, the network and the real
            index cache are never touched.

    Returns:
        The process exit code: 0 on success, and for the ``env`` and ``api`` verbs 1 when
        the result's ``ok`` is false.

    Failure modes:
        Argparse exits by raising ``SystemExit`` for malformed arguments, including a name
        or query given to ``api sync`` or ``api status``, which take none; a tool failure is
        printed as the standard error result JSON and returned as exit code 1, not raised.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    # [2026-11-11 T-002] --version is the smoke-checkable launch named in AGENTS.md → Commands.
    if args.version:
        print(f"{PLUGIN_ID} {__version__}")
        return 0
    if args.verb == "env":
        # [2026-11-11 T-003] The verb only calls ForgeTools and prints: all detection and
        # error shaping stay in tools/env, so the CLI and the Hermes tool agree by sharing
        # the same result builder.
        result = (tools if tools is not None else ForgeTools()).env_result({"root": args.root})
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1
    if args.verb == "api":
        # [2026-11-11 T-005] An ignored argument would be a silent drop, so a name or query
        # on an action that takes none is a usage error (exit status 2), not a no-op.
        if args.term is not None and args.action in ("sync", "status"):
            parser.error(f"api {args.action} takes no name or query (got {args.term!r})")
        call: dict[str, object] = {"action": args.action}
        if args.flavor is not None:
            call["flavor"] = args.flavor
        if args.source is not None:
            call["source"] = args.source
        if args.term is not None:
            call["name" if args.action == "lookup" else "query"] = args.term
        result = (tools if tools is not None else ForgeTools()).api_result(call)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through `python -m`
    raise SystemExit(main())
