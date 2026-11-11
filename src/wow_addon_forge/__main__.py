"""Command-line entry for wow-addon-forge: ``python -m wow_addon_forge`` (created 2026-11-11).

Invariant owned by this file: the module CLI is the scriptable twin of the Hermes tools. Verbs are
added by the task that adds the matching tool; this file never grows logic of its own.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from wow_addon_forge import PLUGIN_ID, __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser (kept separate so tests can inspect it)."""
    parser = argparse.ArgumentParser(
        prog="wow_addon_forge",
        description="Build World of Warcraft: Forever addons that load and run.",
    )
    parser.add_argument("--version", action="store_true", help="print the plugin version and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments without the program name; ``None`` reads ``sys.argv``.

    Returns:
        The process exit code: 0 on success.
    """
    args = build_parser().parse_args(argv)
    # [2026-11-11 T-002] --version is the smoke-checkable launch named in AGENTS.md → Commands.
    if args.version:
        print(f"{PLUGIN_ID} {__version__}")
        return 0
    build_parser().print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through `python -m`
    raise SystemExit(main())
