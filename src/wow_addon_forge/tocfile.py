"""WoW addon TOC parsing and lint for wow-addon-forge (created 2026-11-11).

Invariants owned by this file:
- ``parse_toc`` is the single place TOC line rules live: headers, file lines, and the header
  views (Interface, Title, Version, SavedVariables) that callers report.
- File lines are returned as written apart from the separator: ``\\`` is normalised to ``/`` and
  surrounding whitespace is stripped, nothing else is rewritten by the parser.
- A repeated header key keeps the FIRST value. That is this parser's choice and is not verified
  against the live client.
- ``TocFile.header_lines`` and ``TocFile.file_lines`` record 1-based source positions for lint
  messages and are excluded from equality, so ``TocFile(headers={}, files=())`` still equals
  ``parse_toc("")`` and position data never changes what a TOC *means*.
- ``Finding`` is the shared lint-result shape (docs/SPEC-PLUGIN.md §4); other checkers
  (``luacheck``) re-export it rather than inventing a second shape.
- ``lint_toc`` touches the disk only through the injected ``FileSystem``, so tests run it
  against an in-memory tree on every OS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # [2026-11-11 T-006] env.py imports this module at top level, so the FileSystem protocol
    # is imported for type checking only; importing it at runtime here would be circular.
    from wow_addon_forge.env import FileSystem

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
class Finding:
    """One lint or check result, in the wire shape of docs/SPEC-PLUGIN.md §4.

    Why this exists:
        Every checker in the plugin reports problems the same way, so a caller renders TOC,
        Lua and later findings through one path instead of per-checker shapes.

    Args:
        severity: ``"error"`` (the addon will not load or behave as written) or ``"warning"``
            (it loads, but something is probably unintended).
        code: Stable machine-readable rule name, e.g. ``"missing-file"``.
        file: The file the finding is reported against (the TOC for TOC rules, even when the
            message names another file).
        line: 1-based line number in ``file``, or ``None`` when no single line is to blame.
        message: What is wrong, in one sentence a person can act on.
        hint: How to fix it, in one sentence.

    Failure modes:
        None at construction; ``to_dict`` builds plain JSON-serialisable data only.
    """

    severity: str
    code: str
    file: str
    line: int | None
    message: str
    hint: str

    def to_dict(self) -> dict[str, Any]:
        """Return this finding as plain JSON-serialisable data.

        Why this exists:
            Tool results cross the Hermes boundary as JSON, so the wire shape is pinned in
            one place.

        Returns:
            A dict with exactly the keys ``severity``, ``code``, ``file``, ``line``,
            ``message`` and ``hint``, in that order (docs/SPEC-PLUGIN.md §4).

        Failure modes:
            None.
        """
        return {
            "severity": self.severity,
            "code": self.code,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "hint": self.hint,
        }


# [2026-11-11 T-006] The 21 reserved words of Lua 5.1 (the client's Lua). `goto` is absent on
# purpose: it only became a keyword in Lua 5.2, so `goto` is a legal 5.1 identifier even
# though modern-Lua habits say otherwise.
LUA_51_KEYWORDS: frozenset[str] = frozenset(
    {
        "and",
        "break",
        "do",
        "else",
        "elseif",
        "end",
        "false",
        "for",
        "function",
        "if",
        "in",
        "local",
        "nil",
        "not",
        "or",
        "repeat",
        "return",
        "then",
        "true",
        "until",
        "while",
    }
)

_LUA_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_valid_lua_identifier(name: str) -> bool:
    """Return whether ``name`` is a usable Lua 5.1 variable name.

    Why this exists:
        ``SavedVariables`` entries become global variable names in the client; a name Lua
        cannot hold is silently useless in game, so the spelling rule is owned here once.

    Args:
        name: The candidate name, exactly as written (no stripping is done here).

    Returns:
        ``True`` when ``name`` matches ``^[A-Za-z_][A-Za-z0-9_]*$`` and is not one of the
        21 Lua 5.1 reserved words in ``LUA_51_KEYWORDS``.

    Failure modes:
        None; an unusable name gives ``False``.
    """
    return bool(_LUA_IDENTIFIER.match(name)) and name not in LUA_51_KEYWORDS


def _split_saved_variables(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    return tuple(token.strip() for token in raw.split(",") if token.strip())


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
        header_lines: 1-based line number of the first occurrence of each header key, for
            lint positions. Excluded from equality: where a header sits is not what it means.
        file_lines: ``(normalised_file_path, line_no)`` for each entry in ``files``, in the
            same order. Excluded from equality for the same reason as ``header_lines``.

    Failure modes:
        None at construction; absent or malformed headers surface as empty or ``None`` views
        through the properties below.
    """

    headers: dict[str, str]
    files: tuple[str, ...]
    # [2026-11-11 T-006] compare=False keeps the pre-T-006 equality contract: a hand-built
    # TocFile(headers={}, files=()) must still equal parse_toc(""), positions or not.
    header_lines: dict[str, int] = field(default_factory=dict, compare=False)
    file_lines: tuple[tuple[str, int], ...] = field(default_factory=tuple, compare=False)

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

        Why this exists:
            Reports show the title a reader sees in game, without its colour markup.

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

        Why this exists:
            Reports pair an addon name with the version its TOC declares.

        Returns:
            The version string, or ``None`` when the header is absent or empty.

        Failure modes:
            None.
        """
        raw = self.headers.get("Version")
        if raw is None:
            return None
        return raw.strip() or None

    @property
    def saved_variables(self) -> tuple[str, ...]:
        """Return the account-wide saved-variable names from ``SavedVariables``.

        Why this exists:
            Later checks must know which globals the client persists for this addon, so the
            comma-splitting of the header is owned here.

        Returns:
            The comma-separated tokens of the ``SavedVariables`` header, stripped, with
            empty tokens dropped, in order. A missing header gives ``()``. Tokens are
            returned as written even when invalid; validity is ``lint_toc``'s judgement.

        Failure modes:
            None.
        """
        return _split_saved_variables(self.headers.get("SavedVariables"))

    @property
    def saved_variables_per_character(self) -> tuple[str, ...]:
        """Return the per-character saved-variable names from the matching header.

        Why this exists:
            The per-character names persist separately from the account-wide ones, and
            callers that seed or check saved data need to tell them apart.

        Returns:
            The comma-separated tokens of the ``SavedVariablesPerCharacter`` header,
            stripped, with empty tokens dropped, in order. A missing header gives ``()``.

        Failure modes:
            None.
        """
        return _split_saved_variables(self.headers.get("SavedVariablesPerCharacter"))

    @property
    def all_saved_variables(self) -> tuple[str, ...]:
        """Return every saved-variable name this TOC declares, deduplicated.

        Why this exists:
            Checks that only ask "is this global persisted at all?" should not have to merge
            the two headers (or double-count a name declared in both) themselves.

        Returns:
            ``saved_variables`` followed by any ``saved_variables_per_character`` names not
            already present, order preserved.

        Failure modes:
            None.
        """
        return tuple(dict.fromkeys((*self.saved_variables, *self.saved_variables_per_character)))


def parse_toc(text: str) -> TocFile:
    """Parse TOC text into a ``TocFile``.

    Why this exists:
        The single entry point every caller uses, so the line rules below are the whole
        contract.

    Args:
        text: The full TOC file contents. One leading BOM character is removed if present.

    Returns:
        The parsed ``TocFile``, including 1-based ``header_lines`` / ``file_lines`` positions
        counted on the BOM-stripped text. Blank lines and single-``#`` comments are skipped;
        a ``##`` line is a header only when it contains ``:`` after the ``##`` (an empty key
        is ignored, and a ``##`` line without ``:`` is ignored). A repeated key keeps the
        FIRST value; that is this parser's choice, not verified against the live client.

    Failure modes:
        None; malformed lines are ignored or treated as file lines by the rules above.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    headers: dict[str, str] = {}
    header_lines: dict[str, int] = {}
    files: list[str] = []
    file_lines: list[tuple[str, int]] = []
    # [2026-11-11 T-006] Line numbers are counted after the BOM is stripped, so a BOM can
    # never shift a reported position; the BOM sits on line 1 either way, but counting the
    # stripped text keeps the rule true by construction rather than by luck.
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
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
                header_lines[stripped_key] = line_no
            continue
        if line.startswith("#"):
            continue
        normalised = line.replace("\\", "/")
        files.append(normalised)
        file_lines.append((normalised, line_no))
    return TocFile(
        headers=headers,
        files=tuple(files),
        header_lines=header_lines,
        file_lines=tuple(file_lines),
    )


def _walk_lua_files(fs: FileSystem, addon_dir: str) -> list[str]:
    # [2026-11-11 T-006] Iterative walk over the FileSystem seam: no os.walk (tests inject an
    # in-memory tree), and hidden folders plus Tests/ are pruned because addon test files are
    # deliberately never listed in a TOC. Paths come back relative with "/" separators so
    # they compare directly against the normalised TOC file lines.
    found: list[str] = []
    stack: list[tuple[str, str]] = [(addon_dir, "")]
    while stack:
        dir_path, prefix = stack.pop()
        try:
            entries = fs.list_dir(dir_path)
        except OSError:
            continue
        for name in sorted(entries, reverse=True):
            full_path = fs.join(dir_path, name)
            relative = f"{prefix}{name}"
            if fs.is_dir(full_path):
                if name.startswith(".") or name.lower() == "tests":
                    continue
                stack.append((full_path, f"{relative}/"))
            elif fs.is_file(full_path) and name.lower().endswith(".lua"):
                found.append(relative)
    return sorted(found)


def lint_toc(
    toc: TocFile,
    *,
    toc_filename: str,
    addon_dir: str,
    fs: FileSystem,
    folder_name: str | None = None,
    client_interface: int = 16001,
) -> list[Finding]:
    """Lint one parsed TOC against the addon folder on disk.

    Why this exists:
        The client fails silently on TOC mistakes a machine can catch exactly: a TOC whose
        name does not match its folder never loads, a wrong Interface number marks the addon
        out of date, an unusable SavedVariables name never persists, and a listed-but-missing
        file aborts the load. One function owns those rules so every caller reports alike.

    Args:
        toc: The parsed TOC, from ``parse_toc`` (a hand-built ``TocFile`` without position
            data lints with line 1 fallbacks).
        toc_filename: The TOC's file name, e.g. ``MyAddon.toc``; findings are reported
            against it.
        addon_dir: Path of the addon folder, as the injected ``fs`` understands it.
        fs: The filesystem seam all disk access goes through.
        folder_name: The folder name the TOC must match. When ``None`` it is derived from
            the last ``/``-separated component of ``addon_dir``.
        client_interface: The client Interface number the TOC must declare support for.

    Returns:
        Findings in rule order: ``toc-name-mismatch``, ``toc-interface``,
        ``invalid-savedvar``, ``invalid-file-path`` / ``missing-file``, then
        ``unlisted-file`` warnings. An empty list means the TOC passed every rule.

    Failure modes:
        None raised for a malformed TOC or an unreadable folder: rule violations become
        findings, and directories that cannot be listed are skipped during the
        unlisted-file walk.
    """
    findings: list[Finding] = []
    expected_folder = (
        folder_name
        if folder_name is not None
        else addon_dir.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    )

    toc_stem = toc_filename[:-4] if toc_filename.lower().endswith(".toc") else toc_filename
    if toc_stem != expected_folder:
        findings.append(
            Finding(
                severity="error",
                code="toc-name-mismatch",
                file=toc_filename,
                line=1,
                message=(
                    f"TOC file '{toc_filename}' does not match its addon folder "
                    f"'{expected_folder}'; the client only loads a TOC named after its folder."
                ),
                hint=f"Rename the TOC to '{expected_folder}.toc' or rename the folder.",
            )
        )

    if client_interface not in toc.interface:
        declared = ", ".join(str(number) for number in toc.interface) or "none"
        findings.append(
            Finding(
                severity="error",
                code="toc-interface",
                file=toc_filename,
                line=toc.header_lines.get("Interface", 1),
                message=(
                    f"## Interface does not include the client interface "
                    f"{client_interface} (declared: {declared})."
                ),
                hint=f"Add {client_interface} to the ## Interface header.",
            )
        )

    for header_key in ("SavedVariables", "SavedVariablesPerCharacter"):
        raw = toc.headers.get(header_key)
        # [2026-11-11 T-006] An absent or blank header declares nothing, which is legal; only
        # a header that names something unusable (or leaves an empty slot between commas in
        # a non-blank value) is an error, so `## SavedVariables:` alone stays quiet while a
        # trailing comma in `Foo,` does not.
        if raw is None or raw.strip() == "":
            continue
        for token in raw.split(","):
            stripped = token.strip()
            if stripped and is_valid_lua_identifier(stripped):
                continue
            shown = stripped if stripped else "(empty entry)"
            findings.append(
                Finding(
                    severity="error",
                    code="invalid-savedvar",
                    file=toc_filename,
                    line=toc.header_lines.get(header_key, 1),
                    message=(
                        f"## {header_key} entry {shown!r} is not a valid Lua 5.1 "
                        f"identifier, so the client cannot persist it."
                    ),
                    hint=(
                        "Use letters, digits and underscores, do not start with a digit, "
                        "and do not use a Lua keyword."
                    ),
                )
            )

    listed = toc.file_lines if toc.file_lines else tuple((f, 1) for f in toc.files)
    for rel_path, line_no in listed:
        segments = rel_path.split("/")
        # [2026-11-11 T-006] The path is judged as written, before any join: an absolute path,
        # a ".." segment or an empty segment would let a TOC reach outside its own folder,
        # which the client never loads and a checker must never follow onto the real disk.
        is_absolute = rel_path.startswith("/") or (len(rel_path) >= 2 and rel_path[1] == ":")
        if is_absolute or ".." in segments or "" in segments:
            findings.append(
                Finding(
                    severity="error",
                    code="invalid-file-path",
                    file=toc_filename,
                    line=line_no,
                    message=(
                        f"Listed file '{rel_path}' is not a relative path inside the addon folder."
                    ),
                    hint="List files relative to the addon folder, with no '..'.",
                )
            )
            continue
        if not fs.is_file(fs.join(addon_dir, *segments)):
            findings.append(
                Finding(
                    severity="error",
                    code="missing-file",
                    file=toc_filename,
                    line=line_no,
                    message=f"Listed file '{rel_path}' does not exist in the addon folder.",
                    hint="Create the file or remove its line from the TOC.",
                )
            )

    listed_set = set(toc.files)
    for relative in _walk_lua_files(fs, addon_dir):
        if relative not in listed_set:
            findings.append(
                Finding(
                    severity="warning",
                    code="unlisted-file",
                    file=toc_filename,
                    line=None,
                    message=(
                        f"Lua file '{relative}' exists in the addon folder but is not "
                        f"listed in the TOC, so the client will never load it."
                    ),
                    hint=f"Add '{relative}' to {toc_filename} or remove the file.",
                )
            )

    return findings
