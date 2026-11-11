#!/usr/bin/env python3
"""Guildhall Discord bridge relay: the in-game board <-> your Discord channel.

Purpose
-------
The addon writes board posts into its SavedVariables outbox; ``wow_bridge pull``
reads them and hands back Discord-ready lines (the *game -> Discord* direction).
``wow_bridge push`` writes ``Inbox.lua``, which the addon reads on ``/reload``
(the *Discord -> game* direction). This relay wires those two file seams to a
real Discord channel so the round trip is visible end to end.

How it works
------------
- Game -> Discord: ``--poll`` loops forever (30 s), pulls the outbox and POSTs each
  new line to the webhook as ``{"content": line}``.
- Discord -> game: ``--send "text"`` (optionally ``--author Name``) pushes an
  outbox-shaped ``post`` command into ``Inbox.lua``. The addon reads it after
  ``/reload``; a non-officer client refuses it and reports that in its outbox.
- ``--once`` does a single pull-and-send, for testing.
- ``--status`` prints the outbox count and cursor without sending anything.

The webhook URL is read from ``$GUILDHALL_DISCORD_WEBHOOK`` (or the ``--webhook``
flag). It is a secret: never commit it, never print it in full.

Exit codes: 0 ok, 1 bad arguments or no webhook, 2 webhook send failed.
Contract: SPEC-PLUGIN section 7 (the bridge) and SPEC-GUILDHALL section 10.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# [2026-11-11 T-059] The tool layer resolves install roots, the pull cursor and
# the Inbox path; driving it directly keeps this relay identical to wow_bridge.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wow_addon_forge.tools import ForgeTools  # noqa: E402

POLL_SECONDS = 30
WEBHOOK_TIMEOUT = 10
WEBHOOK_RETRIES = 3
ADDON = "Guildhall"


def _redact(url: str) -> str:
    """Return the webhook URL safe to print (scheme + host + a short tail)."""
    if not url:
        return "(none)"
    marker = url.find("webhooks/")
    if marker < 0:
        return url[:24] + "…"
    return url[marker : marker + 18] + "…"


def _post_webhook(url: str, content: str) -> None:
    """POST one message to the Discord webhook, retrying transient failures."""
    body = json.dumps({"content": content}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Guildhall-Bridge/1.0"},
        method="POST",
    )
    last: Exception | None = None
    for attempt in range(1, WEBHOOK_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT) as response:
                # Discord answers 204 No Content on a successful post.
                if 200 <= response.status < 300:
                    return
                raise OSError(f"HTTP {response.status}")
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            if attempt < WEBHOOK_RETRIES:
                time.sleep(2 * attempt)
    raise OSError(f"webhook send failed after {WEBHOOK_RETRIES} tries: {last}")


def _pull_once() -> dict[str, Any]:
    """Return the wow_bridge pull result (records + lines) as plain data."""
    result = ForgeTools().bridge_result({"action": "pull", "addon": ADDON})
    if result.get("ok") is not True:
        raise OSError(result.get("error", {}).get("message", "pull failed"))
    return result


def _send_text(author: str | None, text: str) -> dict[str, Any]:
    """Push a Discord-sourced post command into the addon's Inbox.lua."""
    record = {
        # [2026-11-11 T-059] Millisecond timestamp as the integer id: the bridge
        # dedupes by id, so two sends in one millisecond must not collide.
        "id": int(time.time() * 1000),
        "t": int(time.time()),
        "kind": "post",
        "data": {"text": text},
        "via": "discord",
    }
    if author:
        record["data"]["author"] = author
    result = ForgeTools().bridge_result({"action": "push", "addon": ADDON, "records": [record]})
    if result.get("ok") is not True:
        raise OSError(result.get("error", {}).get("message", "push failed"))
    return result


def _line_for(record: dict[str, Any]) -> str:
    """Render one outbox record as the Discord-ready line the tool produces."""
    kind = str(record.get("kind") or "record")
    data = record.get("data")
    if isinstance(data, dict):
        text = str(data.get("text") or "")
        author = str(data.get("author") or "")
    else:
        text = str(record.get("text") or "")
        author = str(record.get("author") or "")
    body = f"{author}: {text}" if author and text else (text or author)
    return f"[{kind}] {body}" if body else f"[{kind}]"


def _cmd_status() -> int:
    try:
        result = _pull_once()
    except OSError as exc:
        print(f"status: could not read the outbox: {exc}")
        return 1
    print(
        f"addon: {result.get('addon')}  cursor: {result.get('cursor')}  "
        f"new records: {len(result.get('records', []))}"
    )
    return 0


def _cmd_send(author: str | None, text: str) -> int:
    if not text.strip():
        print("send: text is empty; nothing pushed")
        return 1
    try:
        result = _send_text(author, text)
    except OSError as exc:
        print(f"send: {exc}")
        return 2
    print(
        f"pushed {result.get('added', 0)} record(s) to {result.get('addon')} "
        f"({result.get('path')}) — /reload in game to apply it"
    )
    return 0


def _cmd_once(webhook: str | None) -> int:
    if not webhook:
        print("once: no webhook set (GUILDHALL_DISCORD_WEBHOOK or --webhook)")
        return 1
    try:
        result = _pull_once()
    except OSError as exc:
        print(f"once: {exc}")
        return 1
    records = result.get("records", [])
    if not records:
        print("once: no new outbox records")
        return 0
    for record in records:
        line = _line_for(record)
        _post_webhook(webhook, line)
        print(f"sent: {line}")
    return 0


def _cmd_poll(webhook: str | None) -> int:
    if not webhook:
        print("poll: no webhook set (GUILDHALL_DISCORD_WEBHOOK or --webhook)")
        return 1
    print(f"polling every {POLL_SECONDS}s; webhook {_redact(webhook)}; Ctrl-C to stop")
    while True:
        try:
            result = _pull_once()
            for record in result.get("records", []):
                line = _line_for(record)
                _post_webhook(webhook, line)
                print(f"sent: {line}")
        except (OSError, ValueError) as exc:
            print(f"poll: {exc}", file=sys.stderr)
        time.sleep(POLL_SECONDS)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--webhook",
        default=os.environ.get("GUILDHALL_DISCORD_WEBHOOK", ""),
        help="Discord webhook URL (or set GUILDHALL_DISCORD_WEBHOOK)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="print outbox status")
    sub.add_parser("once", help="pull once and send new records")
    sub.add_parser("poll", help="poll forever and send new records")
    send = sub.add_parser("send", help="push a Discord-sourced post to the game")
    send.add_argument("text", nargs="+", help="the post text")
    send.add_argument("--author", default=None, help="optional author name")
    args = parser.parse_args(argv)

    if args.command == "status":
        return _cmd_status()
    if args.command == "once":
        return _cmd_once(args.webhook)
    if args.command == "poll":
        return _cmd_poll(args.webhook)
    if args.command == "send":
        return _cmd_send(args.author, " ".join(args.text))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
