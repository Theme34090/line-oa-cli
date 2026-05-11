from __future__ import annotations

import time

from .. import config as cfgmod
from ..client import make_client
from ..errors import (
    CliError,
    EXIT_OK,
    emit_json,
    map_http_status,
)
from ._curate import curate_event

MAX_ALL_MESSAGES = 1000  # safety cap for --all


EPILOG = """\
Curated output (default; use --raw for the full LINE response, including
chatRead watermark events, quote tokens, and source metadata):

  {
    "account":  "<name>",
    "chatId":   "U...",
    "messages": [
      {
        "id":        "<message id>",
        "timestamp": <epoch ms>,
        "from":      "customer" | "manual" | "automated",
        "type":      "text" | "sticker" | "image" | "video" | "file" | ...,
        "text":      <string; null for non-text>
      }
    ],
    "backward": "<pagination cursor or null>"
  }

Messages come newest-first. Pass --backward <token> to fetch older,
or --all to paginate until exhausted (capped at 1000 messages).

Curated mode drops non-message events (chatRead watermarks etc.).
Use --raw if you need them.
"""


def _fetch_page(client, bot_id: str, chat_id: str, backward: str | None) -> dict:
    url = f"/api/v3/bots/{bot_id}/chats/{chat_id}/messages"
    params = {"backward": backward} if backward else {}
    resp = client.get(url, params=params)
    if resp.status_code != 200:
        raise CliError(
            f"read failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    return resp.json()


def _curate_messages(events: list[dict], bot_id: str) -> list[dict]:
    out = []
    for evt in events:
        curated = curate_event(evt, bot_id)
        if curated is not None:
            out.append(curated)
    return out


def run(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)

    with make_client(cfg, bot_id) as client:
        if not args.fetch_all:
            data = _fetch_page(client, bot_id, args.chat_id, args.backward)
            events = data.get("list", [])
            messages = events if args.raw else _curate_messages(events, bot_id)
            emit_json({
                "account": name,
                "chatId": args.chat_id,
                "messages": messages,
                "backward": data.get("backward"),
            })
            return EXIT_OK

        all_events: list = []
        backward: str | None = args.backward
        while True:
            data = _fetch_page(client, bot_id, args.chat_id, backward)
            page = data.get("list", [])
            all_events.extend(page)
            backward = data.get("backward")
            if not backward or not page:
                break
            if len(all_events) >= MAX_ALL_MESSAGES:
                break
            time.sleep(0.2)

        messages = all_events if args.raw else _curate_messages(all_events, bot_id)
        emit_json({
            "account": name,
            "chatId": args.chat_id,
            "messages": messages,
            "backward": backward,
            "capped": len(all_events) >= MAX_ALL_MESSAGES,
        })
        return EXIT_OK
