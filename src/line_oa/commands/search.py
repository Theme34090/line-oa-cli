from __future__ import annotations

import time

from .. import config as cfgmod
from ..client import fetch_search_page, make_client
from ..errors import EXIT_OK, emit_json
from ._curate import curate_chat


MAX_ALL_HITS = 500  # safety cap for --all


EPILOG = """\
Curated output (default; use --raw for the full LINE response):

  {
    "account": "<name>",
    "query":   "<echoed query string>",
    "type":    "message" | "profile",
    "count":   <hits on this page>,
    "total":   <total matches across all pages, per LINE>,
    "next":    <pagination cursor or null>,
    "hits": [
      {
        "chatId":             "U...",
        "name":               "<customer display name>",
        "unread":             <bool>,
        "done":               <bool>,
        "followedUp":         <bool>,
        "lastReceivedAt":     <epoch ms; last inbound from customer>,
        "latest": {
          "from":      "customer" | "manual" | "automated",
          "type":      "text" | "sticker" | "image" | ...,
          "text":      <string; null for non-text>,
          "timestamp": <epoch ms>
        },
        "foundMessagesCount": <int>
      }
    ]
  }

Important: `latest` is the chat's most recent message — NOT the matching
message. LINE's search API returns which chats matched, not which specific
messages. To see the matching text, follow up with:
  line-oa read <chatId>
and filter for the query term.

Target types:
  --type message  Search inside message text (default).
                  foundMessagesCount = number of matching messages.
  --type profile  Search customer display names.
                  foundMessagesCount is always 0 (match is on profile).

Pagination:
  Default returns the first page (--limit hits, default 25) plus a `next`
  cursor. Pass --next <token> to resume. Use --all to paginate until
  exhausted (capped at 500 hits).

Useful follow-ups (jq):
  Just chatIds:  .hits[].chatId
  Unread hits:   .hits[] | select(.unread)
  Names + count: .hits[] | "\\(.name)\\t\\(.foundMessagesCount)"
"""


def _curate_hit(hit: dict, bot_id: str) -> dict:
    curated = curate_chat(hit.get("chat") or {}, bot_id)
    curated["foundMessagesCount"] = hit.get("foundMessagesCount", 0)
    return curated


def run(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)

    page_size = max(1, args.limit)

    with make_client(cfg, bot_id) as client:
        if not args.fetch_all:
            data = fetch_search_page(
                client, bot_id, args.query,
                target_type=args.type,
                page_size=page_size,
                next_cursor=args.next,
            )
            hits = data.get("list", [])
            if not args.raw:
                hits = [_curate_hit(h, bot_id) for h in hits]
            emit_json({
                "account": name,
                "query": args.query,
                "type": args.type,
                "count": len(hits),
                "total": data.get("total"),
                "next": data.get("next"),
                "hits": hits,
            })
            return EXIT_OK

        all_hits: list = []
        total: int | None = None
        next_cursor: str | None = args.next
        capped = False
        while True:
            data = fetch_search_page(
                client, bot_id, args.query,
                target_type=args.type,
                page_size=page_size,
                next_cursor=next_cursor,
            )
            if total is None:
                total = data.get("total")
            page = data.get("list", [])
            all_hits.extend(page)
            next_cursor = data.get("next")
            if not next_cursor or not page:
                break
            if len(all_hits) >= MAX_ALL_HITS:
                capped = True
                break
            time.sleep(0.2)

        if len(all_hits) > MAX_ALL_HITS:
            all_hits = all_hits[:MAX_ALL_HITS]
            capped = True

        hits = all_hits if args.raw else [_curate_hit(h, bot_id) for h in all_hits]
        emit_json({
            "account": name,
            "query": args.query,
            "type": args.type,
            "count": len(hits),
            "total": total,
            "next": next_cursor if capped else None,
            "capped": capped,
            "hits": hits,
        })
        return EXIT_OK
