"""Curation helpers — project LINE's raw blobs to lean CS-facing shapes.

Each curated shape is documented in the calling command's argparse epilog
(visible via `line-oa <cmd> --help`). Pass --raw to get the full LINE
response instead of the curated projection.
"""
from __future__ import annotations

AUTO_RESPONSE_BIZ_ID = "__AUTO_RESPONSE"

MESSAGE_EVENT_TYPES = ("messageSent", "message")


def derive_from(source_user_id: str | None, biz_id: str | None,
                bot_id: str) -> str:
    """Categorize the sender of a chat event.

    Returns one of:
      - "customer"  — sent by the chat's customer (source.userId != bot_id)
      - "automated" — sent by the OA's auto-response (bizId == __AUTO_RESPONSE)
      - "manual"    — sent by a human operator on the OA side
                      (web console / CLI / any other non-auto bizId)
    """
    if source_user_id and source_user_id != bot_id:
        return "customer"
    if biz_id == AUTO_RESPONSE_BIZ_ID:
        return "automated"
    return "manual"


def curate_event(evt: dict, bot_id: str) -> dict | None:
    """Project a LINE chat event to the lean message shape.

    Returns None for non-message events (chatRead watermarks, state
    transitions, etc.) so the caller can filter them out."""
    if evt.get("type") not in MESSAGE_EVENT_TYPES:
        return None
    msg = evt.get("message") or {}
    return {
        "id": msg.get("id"),
        "timestamp": evt.get("timestamp"),
        "from": derive_from(
            (evt.get("source") or {}).get("userId"),
            evt.get("bizId"),
            bot_id,
        ),
        "type": msg.get("type"),
        "text": msg.get("text"),
    }


def curate_chat(chat: dict, bot_id: str) -> dict:
    """Project a LINE chat-list entry to the lean CS shape."""
    profile = chat.get("profile") or {}
    evt = chat.get("latestEvent") or {}
    msg = evt.get("message") or {}
    latest = None
    if evt:
        latest = {
            "from": derive_from(
                (evt.get("source") or {}).get("userId"),
                evt.get("bizId"),
                bot_id,
            ),
            "type": msg.get("type"),
            "text": msg.get("text"),
            "timestamp": evt.get("timestamp"),
        }
    return {
        "chatId": chat.get("chatId"),
        "name": profile.get("name"),
        "unread": not chat.get("read", False),
        "done": chat.get("done", False),
        "followedUp": chat.get("followedUp", False),
        "lastReceivedAt": chat.get("lastReceivedAt"),
        "latest": latest,
    }


def curate_profile(chat_data: dict) -> dict:
    """Project LINE's chat-metadata blob to the customer-identity slice."""
    profile = chat_data.get("profile") or {}
    return {
        "name": profile.get("name"),
        "friend": profile.get("friend"),
        "chatType": chat_data.get("chatType"),
        "pushWindowExpiresAt": profile.get("lastActivityExpiresAt"),
    }
