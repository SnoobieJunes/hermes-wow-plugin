"""T-043 driver-side checks for the Guildhall Board (created 2026-11-11).

The addon-side cases live in ``addons/Guildhall/Tests/board.lua`` (run by
``wow_test``); these run the same acceptance behaviors from pytest against the
real scaffolded folder, plus the forged-remove fold rule a local API refusal
alone cannot prove. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wow_addon_forge.headless import World, minimal_api_index

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "addons" / "Guildhall"

_ROWS = (
    "local r = Guildhall.Board.rows(); local parts = {}; "
    "for i, row in ipairs(r) do "
    'parts[#parts + 1] = (row.pinned and "*" or "") .. row.text .. ":" .. #row.comments '
    'end; return table.concat(parts, "|")'
)


def _pair(seed: int) -> tuple[Any, Any, Any]:
    world = World(index=minimal_api_index(), rng_seed=seed)
    world.set_network(loss_rate=0, duplicate_rate=0)
    ann = world.client("Ann", rank=1)
    bob = world.client("Bob", rank=2)
    ann.load_addon(ADDON)
    bob.load_addon(ADDON)
    return world, ann, bob


def test_post_pin_comment_replicate_and_forged_remove_is_ignored() -> None:
    world, ann, bob = _pair(43043)
    post_id = ann.run_lua('return Guildhall.Board.post("Raid Friday")')
    assert isinstance(post_id, str) and post_id
    ann.run_lua('return Guildhall.Board.post("Second")')
    assert ann.run_lua(f'return Guildhall.Board.pin("{post_id}")') is True
    world.advance(5)  # the post must reach Bob before he can comment on it
    assert bob.run_lua(f'return Guildhall.Board.comment("{post_id}", "coming")') is True
    world.advance(10)
    # Pinned post first with its replicated comment, on the member's client.
    assert bob.run_lua(f"return (function() {_ROWS} end)()") == "*Raid Friday:1|Second:0"
    # A forged remove record authored directly into sync (bypassing the
    # Board.remove API check) must not remove the post anywhere: the fold
    # only honours a remove from the post's author or an officer.
    bob.run_lua(
        "Guildhall.Sync.author({"
        f'a="{bob.full_name}", s=99, t=9999, k="board.remove", '
        f'p={{post="{post_id}"}}, v=1}})'
    )
    world.advance(10)
    assert "Raid Friday" in str(ann.run_lua(f"return (function() {_ROWS} end)()"))
    # The author's own remove through the API does replicate.
    assert ann.run_lua(f'return Guildhall.Board.remove("{post_id}")') is True
    world.advance(10)
    assert bob.run_lua(f"return (function() {_ROWS} end)()") == "Second:0"
    assert ann.errors == [] and bob.errors == []


def test_board_tab_builds_only_when_first_shown() -> None:
    world = World(index=minimal_api_index(), rng_seed=43044)
    ann = world.client("Ann", rank=1)
    ann.load_addon(ADDON)
    assert ann.run_lua("return Guildhall.BoardTab.built") is False
    assert ann.run_lua('return Guildhall.Window.show_tab("board")') is True
    assert ann.run_lua("return Guildhall.BoardTab.built") is True
    assert ann.errors == []
