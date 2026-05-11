"""export — bulk-download all chats as LINE-native CSVs."""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .. import config as cfgmod
from ..client import make_client
from ..errors import (
    EXIT_OK,
    EXIT_SESSION_EXPIRED,
    CliError,
    map_http_status,
)


def _list_chats(client, bot_id: str, cutoff_ms: int | None, max_chats: int | None):
    all_chats = []
    next_cursor: str | None = None
    done = False
    while not done:
        params = {
            "folderType": "ALL",
            "tagIds": "",
            "autoTagIds": "",
            "limit": 25,
            "prioritizePinnedChat": "true",
        }
        if next_cursor:
            params["next"] = next_cursor
        resp = client.get(f"/api/v2/bots/{bot_id}/chats", params=params)
        if resp.status_code != 200:
            raise CliError(
                f"list_chats: {resp.status_code} {resp.text[:200]}",
                code=map_http_status(resp.status_code),
            )
        data = resp.json()
        for chat in data.get("list", []):
            if cutoff_ms and chat.get("updatedAt", 0) < cutoff_ms:
                done = True
                break
            all_chats.append(chat)
            if max_chats and len(all_chats) >= max_chats:
                done = True
                break
        next_cursor = data.get("next")
        if not next_cursor:
            done = True
        else:
            time.sleep(0.2)
    return all_chats


def _download_chat_csv(client, bot_id: str, chat_id: str, tz_offset: int) -> str | None:
    url = f"/download/{bot_id}/{chat_id}/messages.csv"
    resp = client.get(url, params={"timezoneOffset": f"-{tz_offset}"})
    if resp.status_code in (401, 302):
        raise CliError("session expired mid-run; refresh cookies", code=EXIT_SESSION_EXPIRED)
    if resp.status_code != 200:
        print(f"  [warn] {resp.status_code} {resp.text[:200]}", file=sys.stderr, flush=True)
        return None
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
        chats = _list_chats(client, bot_id, cutoff_ms, args.max_chats)
        print(f"found {len(chats)} chats", file=sys.stderr, flush=True)

        for i, chat in enumerate(chats, 1):
            chat_id = chat["chatId"]
            display = (chat.get("profile") or {}).get("name") or chat_id
            print(f"[{i}/{len(chats)}] {display} ({chat_id})", file=sys.stderr, flush=True)
            csv_text = _download_chat_csv(client, bot_id, chat_id, tz_offset)
            if csv_text is None:
                continue
            chat_dir = output_dir / chat_id
            chat_dir.mkdir(parents=True, exist_ok=True)
            (chat_dir / "messages.csv").write_text(csv_text, encoding="utf-8")
            print(f"  saved {csv_text.count(chr(10))} lines", file=sys.stderr, flush=True)
            time.sleep(0.2)

    print("done.", file=sys.stderr, flush=True)
    return EXIT_OK
