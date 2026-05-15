from __future__ import annotations

import json
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

CONTENT_HOST = "https://chat-content.line.biz"


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


def fetch_content(
    client: httpx.Client,
    bot_id: str,
    content_hash: str,
) -> tuple[bytes, str]:
    """Download a chat attachment (image/video/audio/file) by its contentHash.

    Returns (bytes, content_type). The endpoint lives on a different host
    (chat-content.line.biz), but shares the cookie jar with the main client.
    """
    url = f"{CONTENT_HOST}/bot/{bot_id}/{content_hash}"
    resp = client.get(
        url,
        headers={"Accept": "image/*,video/*,audio/*,application/octet-stream,*/*;q=0.8"},
    )
    if resp.status_code != 200:
        raise CliError(
            f"content fetch failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    return resp.content, resp.headers.get("content-type", "application/octet-stream")


SEARCH_TARGET_TYPES = {
    "message": "MESSAGE",
    "profile": "CHAT_PROFILE",
}


def fetch_search_page(
    client: httpx.Client,
    bot_id: str,
    query: str,
    *,
    target_type: str = "message",
    page_size: int = CHAT_LIST_PAGE_SIZE,
    next_cursor: str | None = None,
) -> dict:
    """Fetch one page of /api/v1/bots/{bot}/chats/search.

    Returns the raw {list, next, total} blob. `target_type` is the friendly
    name; mapped to LINE's searchTargetType (MESSAGE | CHAT_PROFILE)."""
    api_target = SEARCH_TARGET_TYPES[target_type]
    params: dict[str, Any] = {
        "query": query,
        "searchTargetType": api_target,
        "limit": page_size,
    }
    if next_cursor:
        params["next"] = next_cursor
    resp = client.get(f"/api/v1/bots/{bot_id}/chats/search", params=params)
    if resp.status_code != 200:
        raise CliError(
            f"search failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    return resp.json()


def iter_chats(
    client: httpx.Client,
    bot_id: str,
    *,
    folder: str = "ALL",
    tag_ids: str | None = None,
    page_size: int = CHAT_LIST_PAGE_SIZE,
    sleep_seconds: float = 0.2,
) -> Iterator[dict]:
    """Yield chats from /api/v2/bots/{bot}/chats, paginating until exhausted.
    Caller decides when to stop (cutoff, max-count, etc.).

    `tag_ids`: single LINE tag ID (opaque, ~26 base32 chars) to filter by.
    Multi-tag filtering not supported yet (LINE accepts the param in
    multiple shapes but AND/OR semantics aren't documented).
    """
    next_cursor: str | None = None
    while True:
        params = {
            "folderType": folder,
            "tagIds": tag_ids or "",
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


def fetch_chat(client: httpx.Client, bot_id: str, chat_id: str) -> dict:
    """GET /api/v1/bots/{bot}/chats/{chat}. Returns the full LINE chat-metadata
    blob — profile, tagIds, autoTagIds, latestEvent, etc."""
    resp = client.get(f"/api/v1/bots/{bot_id}/chats/{chat_id}")
    if resp.status_code != 200:
        raise CliError(
            f"chat fetch failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    return resp.json()


def write_headers(
    base: str, bot_id: str, *, chat_id: str | None = None,
) -> dict[str, str]:
    """Headers required for mutating endpoints (PUT/POST/DELETE).

    `chat_id` controls the Referer: a chat ID yields `/<bot>/chat/<chat>`
    (per-chat ops like send / tag-assignment); omitting it yields
    `/<bot>/settings/tags` (catalog ops)."""
    referer = (
        f"{base}/{bot_id}/chat/{chat_id}" if chat_id
        else f"{base}/{bot_id}/settings/tags"
    )
    return {
        "Content-Type": "application/json",
        "Origin": base,
        "Referer": referer,
    }


def fetch_tag_catalog(client: httpx.Client, bot_id: str) -> list[dict]:
    """GET /api/v1/bots/{bot}/tags. Returns the full LINE tag list:
    [{"tagId", "name", "count", "createdAt", "updatedAt"}, ...].
    Curate at the call site if you want a leaner shape."""
    resp = client.get(f"/api/v1/bots/{bot_id}/tags")
    if resp.status_code != 200:
        raise CliError(
            f"tag catalog fetch failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    return resp.json().get("list", [])


def resolve_tag_names(
    catalog: list[dict],
    names: list[str],
) -> tuple[list[str], list[str]]:
    """Map tag names → IDs against the catalog.

    Returns (resolved_ids, unresolved_names). Order of `names` is
    preserved in `resolved_ids` for deterministic output.
    """
    by_name = {t["name"]: t["tagId"] for t in catalog}
    resolved: list[str] = []
    unresolved: list[str] = []
    for n in names:
        tid = by_name.get(n)
        if tid is None:
            unresolved.append(n)
        else:
            resolved.append(tid)
    return resolved, unresolved


def resolve_tag_args(
    catalog: list[dict],
    inputs: list[str],
    *,
    by_id: bool,
) -> list[str]:
    """Resolve a list of tag args (names or IDs) to IDs, atomic-or-fail.

    `by_id=True`: treat inputs as IDs verbatim; no catalog lookup, no
    validation. The caller takes responsibility.
    `by_id=False`: resolve names against the catalog. On any miss,
    raise a CliError with a JSON payload embedding the full catalog so
    an agent caller can self-correct in one turn.
    """
    if by_id:
        return list(inputs)
    resolved, unresolved = resolve_tag_names(catalog, inputs)
    if unresolved:
        payload = {
            "error": "tag_not_found",
            "requested": list(inputs),
            "unresolved": unresolved,
            "available": [
                {"id": t.get("tagId"), "name": t.get("name")} for t in catalog
            ],
        }
        raise CliError(json.dumps(payload, ensure_ascii=False))
    return resolved
