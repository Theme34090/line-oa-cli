from __future__ import annotations

import random
import time

from .. import config as cfgmod
from ..client import make_client, write_headers
from ..errors import (
    CliError,
    EXIT_OK,
    emit_json,
    map_http_status,
)
from ._io import read_text_or_stdin


EPILOG = """\
Curated output (default; use --raw for the full LINE API response and
HTTP status):

  {
    "account":    "<name>",
    "chatId":     "U...",
    "sent":       true,
    "sendId":     "<idempotency key; {chatId}_{epochMs}_{nonce}>",
    "manualMode": {
      "flippedNow": <bool; did this call PUT useManualChat?>,
      "expiresAt":  <epoch ms; when manual mode reverts to auto>
    } | null
  }

Send fails on chats in auto/bot mode with HTTP 400 'not_manual_chat_mode'.
By default this command PUTs /useManualChat first so the send succeeds;
pass --no-auto-manual to opt out and rely on the chat already being manual.

--dry-run emits the planned request bodies without contacting LINE.
"""


def _make_send_id(chat_id: str) -> str:
    """{chatId}_{epoch_ms}_{8-digit-nonce}. Idempotency key for LINE."""
    ms = int(time.time() * 1000)
    nonce = random.randint(0, 99_999_999)
    return f"{chat_id}_{ms}_{nonce:08d}"


def _use_manual_chat(client, url: str, expires_at: int,
                     headers: dict[str, str]) -> None:
    resp = client.put(url, json={"expiresAt": expires_at}, headers=headers)
    if resp.status_code not in (200, 204):
        raise CliError(
            f"useManualChat failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )


def run(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)

    text = read_text_or_stdin(args.text)
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
    headers = write_headers(base, bot_id, chat_id=args.chat_id)
    with make_client(cfg, bot_id) as client:
        if auto_manual:
            _use_manual_chat(client, manual_url, expires_at, headers)
            manual_info = {
                "flippedNow": True,
                "expiresAt": expires_at,
            }
        resp = client.post(send_url, json=body, headers=headers)
    if resp.status_code not in (200, 201, 204):
        raise CliError(
            f"send failed: {resp.status_code} {resp.text[:300]}",
            code=map_http_status(resp.status_code),
        )

    if args.raw:
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
    else:
        emit_json({
            "account": name,
            "chatId": args.chat_id,
            "sent": True,
            "sendId": send_id,
            "manualMode": manual_info,
        })
    return EXIT_OK
