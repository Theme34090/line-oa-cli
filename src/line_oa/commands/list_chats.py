from __future__ import annotations

from datetime import datetime, timezone, timedelta

from .. import config as cfgmod
from ..client import iter_chats, make_client
from ..errors import EXIT_OK, emit_json


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
        for chat in iter_chats(client, bot_id, folder=args.folder):
            if cutoff_ms is not None and chat.get("updatedAt", 0) < cutoff_ms:
                break
            if args.waiting and not _is_waiting(chat, bot_id):
                continue
            collected.append(chat)
            if len(collected) >= target:
                break

    emit_json({
        "account": name,
        "count": len(collected),
        "chats": collected,
    })
    return EXIT_OK
