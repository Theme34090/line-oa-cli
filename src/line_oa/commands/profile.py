"""profile — fetch a chat's customer profile + chat metadata."""
from __future__ import annotations

from .. import config as cfgmod
from ..client import make_client
from ..errors import (
    CliError,
    EXIT_OK,
    emit_json,
    map_http_status,
)


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
    emit_json({
        "account": name,
        "chatId": args.chat_id,
        **data,
    })
    return EXIT_OK
