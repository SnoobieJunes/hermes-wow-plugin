"""T-023 driver-side checks for the Guildhall Discord mirror (created 2026-11-11).

The addon-side cases live in ``addons/Guildhall/Tests/mirror.lua`` (run by
``wow_test``); these run the full round trip from pytest: the real addon in
a fake install, ``wow_bridge`` pull/push through ``ForgeTools`` and
``client.reload()`` as the latency seam, exactly like the bridge-block
acceptance test. Nothing here opens ``/Applications``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from wow_addon_forge.headless import World, format_saved_variables_lua, minimal_api_index
from wow_addon_forge.tools import ForgeTools

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "addons" / "Guildhall"
NAME = "Guildhall"


def _install(tmp_path: Path) -> tuple[Path, Path]:
    wow = tmp_path / "WoW"
    target = wow / "_forever_" / "Interface" / "AddOns" / NAME
    shutil.copytree(ADDON, target)
    return wow, target


def _flush_to_disk(wow: Path, client: Any) -> None:
    client.flush_saved_variables()
    saved = wow / "_forever_" / "WTF" / "Account" / "ACC" / "SavedVariables" / f"{NAME}.lua"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(format_saved_variables_lua(client.account_saved_variables), encoding="utf-8")


def _tools(tmp_path: Path, wow: Path) -> ForgeTools:
    return ForgeTools(default_roots=[str(wow)], cursor_dir=tmp_path / "cursors")


def test_board_post_pulls_as_discord_text_after_reload(tmp_path: Path) -> None:
    wow, target = _install(tmp_path)
    world = World(index=minimal_api_index(), rng_seed=23023)
    world.set_network(loss_rate=0, duplicate_rate=0)
    ann = world.client("Ann", rank=1)
    ann.load_addon(target)
    post_id = ann.run_lua('return Guildhall.Board.post("Raid Friday 8pm")')
    assert isinstance(post_id, str) and post_id
    # The mirror's outbound ticker moves the post into the persisted outbox
    # in-session; the reload is what flushes that outbox to disk for pull.
    world.advance(6)
    ann.reload()
    _flush_to_disk(wow, ann)
    pulled = json.loads(_tools(tmp_path, wow).handle_bridge({"action": "pull", "addon": NAME}))
    assert pulled["ok"] is True
    board = [r for r in pulled["records"] if r["kind"] == "board.post"]
    assert len(board) == 1, pulled["records"]
    assert board[0]["text"] == f"{ann.full_name}: Raid Friday 8pm"
    assert pulled["lines"] == [f"[board.post] {ann.full_name}: Raid Friday 8pm"]
    assert ann.errors == []
    shutil.rmtree(wow)


def test_pushed_post_applies_once_for_officer(tmp_path: Path) -> None:
    wow, target = _install(tmp_path)
    world = World(index=minimal_api_index(), rng_seed=23024)
    world.set_network(loss_rate=0, duplicate_rate=0)
    ann = world.client("Ann", rank=1)
    ann.load_addon(target)
    # Push resolves the install through WTF/Account: one login's save first.
    _flush_to_disk(wow, ann)
    pushed = json.loads(
        _tools(tmp_path, wow).handle_bridge(
            {
                "action": "push",
                "addon": NAME,
                "records": [
                    {
                        "id": 7,
                        "t": 12,
                        "kind": "post",
                        "text": "Hello from Discord",
                        "via": "discord",
                    }
                ],
            }
        )
    )
    assert pushed["ok"] is True and pushed["added"] == 1
    ann.reload()
    rows = ann.run_lua(
        "local r = Guildhall.Board.rows(); "
        'return #r .. "|" .. (r[1].text or "") .. "|" .. (r[1].via or "")'
    )
    assert rows == "1|Hello from Discord|discord"
    assert ann.run_lua("return Guildhall.Mirror.seen_count()") == 1
    # A second reload must not apply the same inbox item twice. The record
    # log itself is in-memory and re-converges over guild sync, so the
    # once-only evidence across a solo reload is the persisted seen set.
    ann.reload()
    assert ann.run_lua("return Guildhall.Mirror.seen_count()") == 1
    assert ann.run_lua("return Guildhall.Mirror.ingest()") == 0
    assert ann.run_lua("return #Guildhall.Board.rows()") == 0
    assert ann.errors == []
    shutil.rmtree(wow)


def test_pushed_post_refused_for_member_and_reported(tmp_path: Path) -> None:
    wow, target = _install(tmp_path)
    world = World(index=minimal_api_index(), rng_seed=23025)
    world.set_network(loss_rate=0, duplicate_rate=0)
    world.client("Ann", rank=1)
    bob = world.client("Bob", rank=2)
    bob.load_addon(target)
    _flush_to_disk(wow, bob)
    pushed = json.loads(
        _tools(tmp_path, wow).handle_bridge(
            {
                "action": "push",
                "addon": NAME,
                "records": [
                    {
                        "id": 9,
                        "t": 13,
                        "kind": "post",
                        "text": "Sneaky announcement",
                        "via": "discord",
                    }
                ],
            }
        )
    )
    assert pushed["ok"] is True
    bob.reload()
    assert bob.run_lua("return #Guildhall.Board.rows()") == 0
    _flush_to_disk(wow, bob)
    pulled = json.loads(_tools(tmp_path, wow).handle_bridge({"action": "pull", "addon": NAME}))
    assert pulled["ok"] is True
    refused = [r for r in pulled["records"] if r["kind"] == "refused"]
    assert len(refused) == 1, pulled["records"]
    assert refused[0]["text"] == "post: not-allowed"
    assert bob.errors == []
    shutil.rmtree(wow)
