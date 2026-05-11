"""httpx client builder."""
from __future__ import annotations

from typing import Any

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
# Hardcoded build-date that chat.line.biz UI sends. Will rot when LINE bumps it.
CLIENT_VERSION = "20240513144702"


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
