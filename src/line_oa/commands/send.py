from __future__ import annotations

import random
import sys
import time

from .. import config as cfgmod
from ..client import make_client
from ..errors import (
    CliError,
    EXIT_OK,
    emit_json,
    map_http_status,
)


def _make_send_id(chat_id: str) -> str:
    """{chatId}_{epoch_ms}_{8-digit-nonce}. Idempotency key for LINE."""
    ms = int(time.time() * 1000)
    nonce = random.randint(0, 99_999_999)
    return f"{chat_id}_{ms}_{nonce:08d}"


def _write_headers(base: str, bot_id: str, chat_id: str) -> dict[str, str]:
    """Headers required for mutating chat endpoints (PUT, POST)."""
    return {
        "Content-Type": "application/json",
        "Origin": base,
        "Referer": f"{base}/{bot_id}/chat/{chat_id}",
    }


def _read_text(arg: str) -> str:
    if arg == "-":
        return sys.stdin.read().rstrip("\n")
    return arg


def _use_manual_chat(client, base: str, bot_id: str, chat_id: str,
                     expires_at: int) -> None:
    url = f"/api/v2/bots/{bot_id}/chats/{chat_id}/useManualChat"
    resp = client.put(
        url,
        json={"expiresAt": expires_at},
        headers=_write_headers(base, bot_id, chat_id),
    )
    if resp.status_code not in (200, 204):
        raise CliError(
            f"useManualChat failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )


def run(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)

    text = _read_text(args.text)
    if not text.strip():
        raise CliError("refusing to send empty/whitespace text")

    base = cfg.get("baseUrl", "https://chat.line.biz")
    send_id = _make_send_id(args.chat_id)
    body = {"id": "", "type": "textV2", "text": text, "sendId": send_id}
    send_url = f"/api/v1/bots/{bot_id}/chats/{args.chat_id}/messages/send"
    manual_url = f"/api/v2/bots/{bot_id}/chats/{args.chat_id}/useManualChat"
    auto_manual = not args.no_auto_manual
    expires_at = int(time.time() * 1000) + args.manual_ttl_minutes * 60 * 1000

    if args.dry_run:
        plan = {
            "dryRun": True,
            "account": name,
            "send": {"url": send_url, "body": body},
        }
        if auto_manual:
            plan["useManualChat"] = {
                "url": manual_url,
                "body": {"expiresAt": expires_at},
                "ttlMinutes": args.manual_ttl_minutes,
            }
        emit_json(plan)
        return EXIT_OK

    manual_info = None
    with make_client(cfg, bot_id) as client:
        if auto_manual:
            _use_manual_chat(client, base, bot_id, args.chat_id, expires_at)
            manual_info = {
                "expiresAt": expires_at,
                "ttlMinutes": args.manual_ttl_minutes,
            }
        resp = client.post(
            send_url,
            json=body,
            headers=_write_headers(base, bot_id, args.chat_id),
        )
    if resp.status_code not in (200, 201, 204):
        raise CliError(
            f"send failed: {resp.status_code} {resp.text[:300]}",
            code=map_http_status(resp.status_code),
        )

    response_body = None
    if resp.text:
        try:
            response_body = resp.json()
        except Exception:
            response_body = resp.text

    emit_json({
        "account": name,
        "chatId": args.chat_id,
        "sendId": send_id,
        "status": resp.status_code,
        "manualChat": manual_info,
        "response": response_body,
    })
    return EXIT_OK
