"""Minimal WoW addon TOC parser for wow-addon-forge (created 2026-11-11).

Invariants owned by this file:
- This is the minimal parser the walking skeleton needs: headers, file lines, and the three
  header views (Interface, Title, Version) that environment detection reports. Lint (missing
  files, SavedVariables names) belongs to task T-006 and is deliberately absent here.
- File lines are returned as written apart from the separator: ``\\`` is normalised to ``/`` and
  surrounding whitespace is stripped, nothing else is rewritten or checked.
- A repeated header key keeps the FIRST value. That is this parser's choice and is not verified
  against the live client.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# [2026-11-11 T-003] Colour escapes are '|c' plus 8 hex digits and the reset '|r'; matching is
# case-insensitive so '|C' and '|R' written by hand are removed too.
_UI_ESCAPES = re.compile(r"\|c[0-9a-f]{8}|\|r", re.IGNORECASE)


def strip_ui_escapes(text: str) -> str:
    """Remove WoW UI colour escapes from ``text`` and strip surrounding whitespace.

    Why this exists:
        Titles carry display markup such as ``Questie|cFF00FF00 v12.6.4|r``; reports want the
        plain text a reader sees.

    Args:
        text: The raw text, usually a ``## Title:`` header value.

    Returns:
        The text with every ``|c`` + 8-hex-digit sequence and every ``|r`` removed
        (case-insensitive), then whitespace-stripped.

    Failure modes:
        None; text without escapes is returned stripped but otherwise unchanged.
    """
    return _UI_ESCAPES.sub("", text).strip()


@dataclass(frozen=True)
class TocFile:
    """The parsed facts of one TOC file.

    Why this exists:
        Callers report title, version and Interface numbers without re-reading raw lines, so
        the header spelling rules live here exactly once.

    Args:
        headers: ``## Key: Value`` lines, key and value stripped, keys stored exactly as
            written (case-sensitive); a repeated key keeps the first value.
        files: Every non-blank, non-comment line in order, stripped, with ``\\`` normalised
            to ``/``.

    Failure modes:
        None at construction; absent or malformed headers surface as empty or ``None`` views
        through the properties below.
    """

    headers: dict[str, str]
    files: tuple[str, ...]

    @property
    def interface(self) -> tuple[int, ...]:
        """Return the Interface numbers from the ``Interface`` header.

        Why this exists:
            Whether an addon supports a client is decided by membership in this tuple, so
            the comma-and-digits parsing is owned here.

        Returns:
            One integer per comma-separated all-digit token, in order, e.g.
            ``## Interface: 16001, 11507`` becomes ``(16001, 11507)``. Tokens that are not
            all digits are dropped, and a missing header gives ``()``.

        Failure modes:
            None; a malformed header degrades to fewer (or zero) numbers.
        """
        raw = self.headers.get("Interface")
        if raw is None:
            return ()
        numbers: list[int] = []
        for token in raw.split(","):
            stripped = token.strip()
            if stripped.isdigit():
                numbers.append(int(stripped))
        return tuple(numbers)

    @property
    def title(self) -> str | None:
        """Return the plain-text ``Title`` header.

        Returns:
            The title passed through ``strip_ui_escapes``, or ``None`` when the header is
            absent or empty after stripping.

        Failure modes:
            None.
        """
        raw = self.headers.get("Title")
        if raw is None:
            return None
        return strip_ui_escapes(raw) or None

    @property
    def version(self) -> str | None:
        """Return the ``Version`` header.

        Returns:
            The version string, or ``None`` when the header is absent or empty.

        Failure modes:
            None.
        """
        raw = self.headers.get("Version")
        if raw is None:
            return None
        return raw.strip() or None


def parse_toc(text: str) -> TocFile:
    """Parse TOC text into a ``TocFile``.

    Why this exists:
        The single entry point every caller uses, so the line rules below are the whole
        contract. This is the minimal parser the walking skeleton needs: file lines are
        returned as written apart from the separator, and lint (missing files, SavedVariables
        names) belongs to task T-006.

    Args:
        text: The full TOC file contents. One leading BOM character is removed if present.

    Returns:
        The parsed ``TocFile``. Blank lines and single-``#`` comments are skipped; a ``##``
        line is a header only when it contains ``:`` after the ``##`` (an empty key is
        ignored, and a ``##`` line without ``:`` is ignored). A repeated key keeps the FIRST
        value; that is this parser's choice, not verified against the live client.

    Failure modes:
        None; malformed lines are ignored or treated as file lines by the rules above.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    headers: dict[str, str] = {}
    files: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("##"):
            key, separator, value = line[2:].partition(":")
            if not separator:
                continue
            stripped_key = key.strip()
            # [2026-11-11 T-003] First value wins for a repeated key; our choice, not verified
            # against the live client.
            if stripped_key and stripped_key not in headers:
                headers[stripped_key] = value.strip()
            continue
        if line.startswith("#"):
            continue
        files.append(line.replace("\\", "/"))
    return TocFile(headers=headers, files=tuple(files))
