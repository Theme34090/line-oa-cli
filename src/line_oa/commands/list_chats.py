"""list — fetch chats with filters."""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

from .. import config as cfgmod
from ..client import make_client
from ..errors import (
    CliError,
    EXIT_OK,
    emit_json,
    map_http_status,
)

PAGE_SIZE = 25  # LINE's natural max


def _is_waiting(chat: dict, bot_id: str) -> bool:
    """True if the latest event came from the customer (not the OA)."""
    evt = chat.get("latestEvent") or {}
    src = evt.get("source") or {}
    user = src.get("userId")
    if not user:
        return False
    return user != bot_id


def run(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)

    cutoff_ms = None
    if args.since_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.since_days)
        cutoff_ms = int(cutoff.timestamp() * 1000)

    target = max(1, args.limit)
    collected: list[dict] = []

    with make_client(cfg, bot_id) as client:
        next_cursor: str | None = None
        done = False
        while not done and len(collected) < target:
            params = {
                "folderType": args.folder,
                "tagIds": "",
                "autoTagIds": "",
                "limit": PAGE_SIZE,
                "prioritizePinnedChat": "true",
            }
            if next_cursor:
                params["next"] = next_cursor
            resp = client.get(f"/api/v2/bots/{bot_id}/chats", params=params)
            if resp.status_code != 200:
                raise CliError(
                    f"list_chats failed: {resp.status_code} {resp.text[:200]}",
                    code=map_http_status(resp.status_code),
                )
            data = resp.json()
            for chat in data.get("list", []):
                if cutoff_ms is not None and chat.get("updatedAt", 0) < cutoff_ms:
                    done = True
                    break
                if args.waiting and not _is_waiting(chat, bot_id):
                    continue
                collected.append(chat)
                if len(collected) >= target:
                    done = True
                    break
            next_cursor = data.get("next")
            if not next_cursor:
                done = True
            else:
                time.sleep(0.2)

    emit_json({
        "account": name,
        "count": len(collected),
        "chats": collected,
    })
    return EXIT_OK
