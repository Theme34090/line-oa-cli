from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .. import config as cfgmod
from ..client import iter_chats, make_client
from ..errors import EXIT_OK, CliError, map_http_status


def _download_chat_csv(client, bot_id: str, chat_id: str, tz_offset: int) -> str:
    url = f"/download/{bot_id}/{chat_id}/messages.csv"
    resp = client.get(url, params={"timezoneOffset": f"-{tz_offset}"})
    if resp.status_code != 200:
        raise CliError(
            f"csv download failed for {chat_id}: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    return resp.text


def run(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    tz_offset = cfg.get("timezoneOffset", 420)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    cutoff_ms = None
    if args.go_back_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.go_back_days)
        cutoff_ms = int(cutoff.timestamp() * 1000)
        print(f"filter: last {args.go_back_days}d (since {cutoff:%Y-%m-%d %H:%M UTC})",
              file=sys.stderr, flush=True)

    with make_client(cfg, bot_id) as client:
        print(f"account: {name}", file=sys.stderr, flush=True)
        print("fetching chat list...", file=sys.stderr, flush=True)
        chats: list[dict] = []
        for chat in iter_chats(client, bot_id):
            if cutoff_ms and chat.get("updatedAt", 0) < cutoff_ms:
                break
            chats.append(chat)
            if args.max_chats and len(chats) >= args.max_chats:
                break
        print(f"found {len(chats)} chats", file=sys.stderr, flush=True)

        for i, chat in enumerate(chats, 1):
            chat_id = chat["chatId"]
            display = (chat.get("profile") or {}).get("name") or chat_id
            print(f"[{i}/{len(chats)}] {display} ({chat_id})", file=sys.stderr, flush=True)
            csv_text = _download_chat_csv(client, bot_id, chat_id, tz_offset)
            chat_dir = output_dir / chat_id
            chat_dir.mkdir(parents=True, exist_ok=True)
            (chat_dir / "messages.csv").write_text(csv_text, encoding="utf-8")
            print(f"  saved {csv_text.count(chr(10))} lines", file=sys.stderr, flush=True)
            time.sleep(0.2)

    print("done.", file=sys.stderr, flush=True)
    return EXIT_OK
