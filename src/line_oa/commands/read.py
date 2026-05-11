"""read — fetch messages for one chat. Paginated via 'backward' cursor."""
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

MAX_ALL_MESSAGES = 1000  # safety cap for --all


def _fetch_page(client, bot_id: str, chat_id: str, backward: str | None) -> dict:
    url = f"/api/v3/bots/{bot_id}/chats/{chat_id}/messages"
    params = {}
    if backward:
        params["backward"] = backward
    resp = client.get(url, params=params)
    if resp.status_code != 200:
        raise CliError(
            f"read failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    return resp.json()


def run(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)

    with make_client(cfg, bot_id) as client:
        if not args.fetch_all:
            data = _fetch_page(client, bot_id, args.chat_id, args.backward)
            emit_json({
                "account": name,
                "chatId": args.chat_id,
                "messages": data.get("list") or data.get("messages") or [],
                "backward": data.get("backward"),
            })
            return EXIT_OK

        # --all: paginate until exhausted or capped
        all_msgs: list = []
        backward: str | None = args.backward
        while True:
            data = _fetch_page(client, bot_id, args.chat_id, backward)
            page = data.get("list") or data.get("messages") or []
            all_msgs.extend(page)
            backward = data.get("backward")
            if not backward or not page:
                break
            if len(all_msgs) >= MAX_ALL_MESSAGES:
                break
            time.sleep(0.2)

        emit_json({
            "account": name,
            "chatId": args.chat_id,
            "messages": all_msgs,
            "backward": backward,
            "capped": len(all_msgs) >= MAX_ALL_MESSAGES,
        })
        return EXIT_OK
