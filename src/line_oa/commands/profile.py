from __future__ import annotations

from .. import config as cfgmod
from ..client import make_client
from ..errors import (
    CliError,
    EXIT_OK,
    emit_json,
    map_http_status,
)
from ._curate import curate_profile


EPILOG = """\
Curated output (default; use --raw for the full chat-metadata blob,
which duplicates fields available from 'line-oa list'):

  {
    "account":             "<name>",
    "chatId":              "U...",
    "name":                "<customer display name>",
    "friend":              <bool; has added the OA as friend>,
    "chatType":            "USER" | "GROUP",
    "pushWindowExpiresAt": <epoch ms; when the 24h reply window closes>
  }

For chat-level state (unread / done / followedUp / lastReceivedAt /
latest message) use 'line-oa list' — that's where chat metadata lives.
"""


def run(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)

    with make_client(cfg, bot_id) as client:
        resp = client.get(f"/api/v1/bots/{bot_id}/chats/{args.chat_id}")
    if resp.status_code != 200:
        raise CliError(
            f"profile failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )

    data = resp.json()
    if args.raw:
        emit_json({
            "account": name,
            "chatId": args.chat_id,
            **data,
        })
    else:
        emit_json({
            "account": name,
            "chatId": args.chat_id,
            **curate_profile(data),
        })
    return EXIT_OK
