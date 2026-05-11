from __future__ import annotations

import time
from typing import Any, Iterator

import httpx

from .errors import CliError, map_http_status

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
# Hardcoded build-date that chat.line.biz UI sends. Will rot when LINE bumps it.
CLIENT_VERSION = "20240513144702"

CHAT_LIST_PAGE_SIZE = 25  # LINE's natural max


def make_client(cfg: dict[str, Any], bot_id: str) -> httpx.Client:
    cookies = cfg.get("cookies") or {}
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    xsrf = cookies.get("XSRF-TOKEN", "")
    base = cfg.get("baseUrl", "https://chat.line.biz")

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie_str,
        "Referer": f"{base}/{bot_id}/chat/",
        "User-Agent": USER_AGENT,
        "x-oa-chat-client-version": CLIENT_VERSION,
    }
    if xsrf:
        headers["X-XSRF-TOKEN"] = xsrf

    return httpx.Client(
        base_url=base,
        timeout=60,
        follow_redirects=False,
        headers=headers,
    )


def iter_chats(
    client: httpx.Client,
    bot_id: str,
    *,
    folder: str = "ALL",
    page_size: int = CHAT_LIST_PAGE_SIZE,
    sleep_seconds: float = 0.2,
) -> Iterator[dict]:
    """Yield chats from /api/v2/bots/{bot}/chats, paginating until exhausted.
    Caller decides when to stop (cutoff, max-count, etc.)."""
    next_cursor: str | None = None
    while True:
        params = {
            "folderType": folder,
            "tagIds": "",
            "autoTagIds": "",
            "limit": page_size,
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
        yield from data.get("list", [])
        next_cursor = data.get("next")
        if not next_cursor:
            return
        time.sleep(sleep_seconds)
