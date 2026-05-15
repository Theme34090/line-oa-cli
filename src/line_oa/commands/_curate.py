"""Curation helpers — project LINE's raw blobs to lean CS-facing shapes.

Each curated shape is documented in the calling command's argparse epilog
(visible via `line-oa <cmd> --help`). Pass --raw to get the full LINE
response instead of the curated projection.
"""
from __future__ import annotations

AUTO_RESPONSE_BIZ_ID = "__AUTO_RESPONSE"

MESSAGE_EVENT_TYPES = ("messageSent", "message")

# Message subtypes that carry a fetchable contentHash (chat-content.line.biz).
MEDIA_MESSAGE_TYPES = ("image", "video", "audio", "file")


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
    msg_type = msg.get("type")
    return {
        "id": msg.get("id"),
        "timestamp": evt.get("timestamp"),
        "from": derive_from(
            (evt.get("source") or {}).get("userId"),
            evt.get("bizId"),
            bot_id,
        ),
        "type": msg_type,
        "text": msg.get("text"),
        "contentHash": msg.get("contentHash") if msg_type in MEDIA_MESSAGE_TYPES else None,
    }


def curate_chat(
    chat: dict,
    bot_id: str,
    *,
    tag_id_to_name: dict[str, str] | None = None,
) -> dict:
    """Project a LINE chat-list entry to the lean CS shape.

    `tag_id_to_name`: optional ID→name map. When provided, the curated
    shape gains a `tags: [name, ...]` field (unresolved IDs render as the
    raw ID string so nothing silently disappears). When omitted, no
    `tags` field is included.
    """
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
    out = {
        "chatId": chat.get("chatId"),
        "name": profile.get("name"),
        "unread": not chat.get("read", False),
        "done": chat.get("done", False),
        "followedUp": chat.get("followedUp", False),
        "lastReceivedAt": chat.get("lastReceivedAt"),
        "latest": latest,
    }
    if tag_id_to_name is not None:
        out["tags"] = [
            tag_id_to_name.get(tid, tid)
            for tid in (chat.get("tagIds") or [])
        ]
    return out


def curate_tag(t: dict) -> dict:
    """Project a raw LINE tag blob ({tagId, name, count, ...}) to {id, name}."""
    return {"id": t.get("tagId"), "name": t.get("name")}


def curate_note(n: dict) -> dict:
    """Project a raw LINE note blob to the lean shape.

    `authorId` (LINE's `userBizId`) is the OA staff member's UUID —
    no display-name endpoint exists, so it's surfaced as-is."""
    return {
        "id": n.get("noteId"),
        "body": n.get("body"),
        "authorId": n.get("userBizId"),
        "createdAt": n.get("createdAt"),
        "updatedAt": n.get("updatedAt"),
    }


def tag_id_to_name(catalog: list[dict]) -> dict[str, str]:
    """Build an ID→name lookup from a tag catalog."""
    return {t["tagId"]: t["name"] for t in catalog}


def ids_to_names(catalog: list[dict], ids: list[str]) -> list[str]:
    """Look up names for a list of IDs. Unknown IDs render as the raw ID
    string so nothing silently disappears."""
    by_id = tag_id_to_name(catalog)
    return [by_id.get(i, i) for i in ids]


def curate_profile(chat_data: dict) -> dict:
    """Project LINE's chat-metadata blob to the customer-identity slice."""
    profile = chat_data.get("profile") or {}
    return {
        "name": profile.get("name"),
        "friend": profile.get("friend"),
        "chatType": chat_data.get("chatType"),
        "pushWindowExpiresAt": profile.get("lastActivityExpiresAt"),
    }
