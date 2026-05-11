from __future__ import annotations

from datetime import datetime, timezone, timedelta

from .. import config as cfgmod
from ..client import iter_chats, make_client
from ..errors import EXIT_OK, emit_json
from ._curate import curate_chat, derive_from


EPILOG = """\
Curated output (default; use --raw for the full LINE response):

  {
    "account": "<name>",
    "count":   <int>,
    "chats": [
      {
        "chatId":         "U...",
        "name":           "<customer display name>",
        "unread":         <bool>,
        "done":           <bool>,
        "followedUp":     <bool>,
        "lastReceivedAt": <epoch ms; last inbound from customer>,
        "latest": {
          "from":      "customer" | "manual" | "automated",
          "type":      "text" | "sticker" | "image" | "video" | "file" | ...,
          "text":      <string; null for non-text>,
          "timestamp": <epoch ms>
        }
      }
    ]
  }

"from" semantics:
  customer  — the customer sent the latest message
  manual    — a human OA operator sent it (web console / CLI)
  automated — the OA's auto-response sent it (bizId == __AUTO_RESPONSE)

Useful filters (jq):
  Unread:           .chats[] | select(.unread)
  Waiting for CS:   .chats[] | select(.latest.from == "customer")
  Bot-handled:      .chats[] | select(.latest.from == "automated")
  Open queue:       .chats[] | select(.unread and (.done | not))
"""


def _is_waiting(chat: dict, bot_id: str) -> bool:
    """True iff the latest event came from the customer (not the OA)."""
    evt = chat.get("latestEvent") or {}
    sender = derive_from(
        (evt.get("source") or {}).get("userId"),
        evt.get("bizId"),
        bot_id,
    )
    return sender == "customer"


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

    if not args.raw:
        collected = [curate_chat(c, bot_id) for c in collected]

    emit_json({
        "account": name,
        "count": len(collected),
        "chats": collected,
    })
    return EXIT_OK
