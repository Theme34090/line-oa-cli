from __future__ import annotations

import json

from .. import config as cfgmod
from ..client import fetch_tag_catalog, make_client, resolve_tag_names
from ..errors import (
    CliError,
    EXIT_GENERIC,
    EXIT_OK,
    emit_json,
    map_http_status,
)


EPILOG = """\
Catalog ops (operate on the bot's tag catalog):

  list                      List all tags. Curated: [{id, name}].
  create NAME               Create a tag. Idempotent: returns existing
                            tag with `created: false` if name already exists.
                            LINE caps tag names at 20 chars.
  delete NAME --yes         Delete a tag from the catalog. Cascades to all
                            chats that have it. Requires --yes (destructive,
                            irreversible). Use --id to pass a tag ID instead.

Per-chat ops (operate on one chat's tag assignments):

  get    CHATID             Read the chat's current tags. Returns [{id, name}].
  set    CHATID NAME...     Replace the chat's tags with exactly these names.
                            Refuses empty list (use `clear`).
  add    CHATID NAME...     Add tags to the chat (idempotent; no-op if already).
  remove CHATID NAME...     Remove tags from the chat (idempotent; no-op if not).
  clear  CHATID             Remove ALL tags from the chat.

Tag identity:
  By default tags are passed by name. Resolution costs one extra
  GET /tags per invocation. Use --id to skip resolution and pass raw
  LINE tag IDs instead (~26 base32 chars, e.g. agpb6wvltljfu5xaje3fzrwaai).

Mutation output (set/add/remove/clear):
  {chatId, before: [name,...], after: [name,...],
   added: [name,...], removed: [name,...]}

Caveats:
- add/remove are GET-then-PUT internally. Concurrent mutations on the same
  chat race; last write wins. LINE has no CAS endpoint.
- Auto-tags (LINE-assigned) are read-only and not exposed by these commands.
"""


def _write_headers(base: str, bot_id: str, chat_id: str | None) -> dict[str, str]:
    """Headers required for mutating endpoints (PUT/POST/DELETE)."""
    if chat_id:
        referer = f"{base}/{bot_id}/chat/{chat_id}"
    else:
        referer = f"{base}/{bot_id}/settings/tags"
    return {
        "Content-Type": "application/json",
        "Origin": base,
        "Referer": referer,
    }


def _curate_tag(t: dict) -> dict:
    """Project a raw LINE tag blob to {id, name}."""
    return {"id": t.get("tagId"), "name": t.get("name")}


def _resolve_tag_args(
    catalog: list[dict],
    inputs: list[str],
    *,
    by_id: bool,
) -> list[str]:
    """Resolve a list of tag args (names or IDs) to IDs.

    `by_id=True`: treat inputs as IDs verbatim; no catalog lookup, no
    validation. The agent took responsibility.
    `by_id=False`: resolve names against the catalog. Atomic fail with
    rich error if any miss.
    """
    if by_id:
        return list(inputs)
    resolved, unresolved = resolve_tag_names(catalog, inputs)
    if unresolved:
        # Rich error so the agent can self-correct in one turn.
        payload = {
            "error": "tag_not_found",
            "requested": list(inputs),
            "unresolved": unresolved,
            "available": [_curate_tag(t) for t in catalog],
        }
        raise CliError(json.dumps(payload, ensure_ascii=False), code=EXIT_GENERIC)
    return resolved


def _put_chat_tags(
    client, base: str, bot_id: str, chat_id: str, tag_ids: list[str],
) -> None:
    """PUT /api/v1/bots/{bot}/chats/{chat}/tags. Replaces the entire list."""
    headers = _write_headers(base, bot_id, chat_id)
    resp = client.put(
        f"/api/v1/bots/{bot_id}/chats/{chat_id}/tags",
        json={"tagIds": tag_ids},
        headers=headers,
    )
    if resp.status_code not in (200, 204):
        raise CliError(
            f"set tags failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )


def _get_chat_tag_ids(client, bot_id: str, chat_id: str) -> list[str]:
    """GET /chats/{id} and return its current tagIds (manual tags only)."""
    resp = client.get(f"/api/v1/bots/{bot_id}/chats/{chat_id}")
    if resp.status_code != 200:
        raise CliError(
            f"chat fetch failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    return list(resp.json().get("tagIds") or [])


def _ids_to_names(catalog: list[dict], ids: list[str]) -> list[str]:
    """Look up names for a list of IDs. Unknown IDs render as the raw ID
    so nothing silently disappears."""
    by_id = {t["tagId"]: t["name"] for t in catalog}
    return [by_id.get(i, i) for i in ids]


# ---- catalog subcommands -----------------------------------------------

def cmd_list(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    with make_client(cfg, bot_id) as client:
        catalog = fetch_tag_catalog(client, bot_id)
    if args.raw:
        emit_json({"account": name, "count": len(catalog), "tags": catalog})
    else:
        emit_json({
            "account": name,
            "count": len(catalog),
            "tags": [_curate_tag(t) for t in catalog],
        })
    return EXIT_OK


def cmd_create(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    base = cfg.get("baseUrl", "https://chat.line.biz")
    tag_name = args.name
    if not tag_name.strip():
        raise CliError("refusing to create an empty/whitespace tag name")

    headers = _write_headers(base, bot_id, None)
    with make_client(cfg, bot_id) as client:
        resp = client.post(
            f"/api/v1/bots/{bot_id}/tags",
            json={"name": tag_name},
            headers=headers,
        )
        if resp.status_code == 200 or resp.status_code == 201:
            data = resp.json()
            emit_json({
                "account": name,
                "id": data.get("tagId"),
                "name": data.get("name"),
                "created": True,
            })
            return EXIT_OK
        # 409 → tag already exists; resolve to the existing one (idempotent).
        if resp.status_code == 409:
            catalog = fetch_tag_catalog(client, bot_id)
            existing = next(
                (t for t in catalog if t.get("name") == tag_name), None,
            )
            if existing is None:
                # 409 but no matching tag — race or LINE quirk. Surface raw.
                raise CliError(
                    f"create returned 409 but tag '{tag_name}' not in "
                    f"catalog; LINE response: {resp.text[:200]}",
                )
            emit_json({
                "account": name,
                "id": existing.get("tagId"),
                "name": existing.get("name"),
                "created": False,
            })
            return EXIT_OK
        raise CliError(
            f"create tag failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )


def cmd_delete(args) -> int:
    if not args.yes:
        raise CliError(
            "tag delete is destructive (removes tag from catalog and "
            "from all chats it's attached to). Re-run with --yes to confirm.",
        )

    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    base = cfg.get("baseUrl", "https://chat.line.biz")

    with make_client(cfg, bot_id) as client:
        if args.by_id:
            tag_id = args.tag
            tag_name = None
        else:
            catalog = fetch_tag_catalog(client, bot_id)
            ids = _resolve_tag_args(catalog, [args.tag], by_id=False)
            tag_id = ids[0]
            tag_name = args.tag

        headers = _write_headers(base, bot_id, None)
        resp = client.delete(
            f"/api/v1/bots/{bot_id}/tags/{tag_id}",
            headers=headers,
        )
    if resp.status_code not in (200, 204):
        raise CliError(
            f"delete tag failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    emit_json({
        "account": name,
        "deleted": {"id": tag_id, "name": tag_name},
    })
    return EXIT_OK


# ---- per-chat subcommands ----------------------------------------------

def cmd_get(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    with make_client(cfg, bot_id) as client:
        current_ids = _get_chat_tag_ids(client, bot_id, args.chat_id)
        catalog = fetch_tag_catalog(client, bot_id)
    by_id = {t["tagId"]: t["name"] for t in catalog}
    emit_json({
        "account": name,
        "chatId": args.chat_id,
        "tags": [
            {"id": tid, "name": by_id.get(tid, tid)}
            for tid in current_ids
        ],
    })
    return EXIT_OK


def _mutation_response(
    account: str, chat_id: str, before_ids: list[str],
    after_ids: list[str], catalog: list[dict],
) -> dict:
    before_set = set(before_ids)
    after_set = set(after_ids)
    added = [tid for tid in after_ids if tid not in before_set]
    removed = [tid for tid in before_ids if tid not in after_set]
    return {
        "account": account,
        "chatId": chat_id,
        "before":  _ids_to_names(catalog, before_ids),
        "after":   _ids_to_names(catalog, after_ids),
        "added":   _ids_to_names(catalog, added),
        "removed": _ids_to_names(catalog, removed),
    }


def cmd_set(args) -> int:
    if not args.tags:
        raise CliError(
            "no tags supplied. Use `line-oa tag clear "
            f"{args.chat_id}` to remove all tags from this chat.",
        )

    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    base = cfg.get("baseUrl", "https://chat.line.biz")

    with make_client(cfg, bot_id) as client:
        catalog = fetch_tag_catalog(client, bot_id)
        new_ids = _resolve_tag_args(catalog, args.tags, by_id=args.by_id)
        before_ids = _get_chat_tag_ids(client, bot_id, args.chat_id)
        _put_chat_tags(client, base, bot_id, args.chat_id, new_ids)

    emit_json(_mutation_response(name, args.chat_id, before_ids, new_ids, catalog))
    return EXIT_OK


def cmd_add(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    base = cfg.get("baseUrl", "https://chat.line.biz")

    with make_client(cfg, bot_id) as client:
        catalog = fetch_tag_catalog(client, bot_id)
        ids_to_add = _resolve_tag_args(catalog, args.tags, by_id=args.by_id)
        before_ids = _get_chat_tag_ids(client, bot_id, args.chat_id)
        # Idempotent: drop any already present.
        before_set = set(before_ids)
        new_ids = before_ids + [i for i in ids_to_add if i not in before_set]
        if new_ids != before_ids:
            _put_chat_tags(client, base, bot_id, args.chat_id, new_ids)

    emit_json(_mutation_response(name, args.chat_id, before_ids, new_ids, catalog))
    return EXIT_OK


def cmd_remove(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    base = cfg.get("baseUrl", "https://chat.line.biz")

    with make_client(cfg, bot_id) as client:
        catalog = fetch_tag_catalog(client, bot_id)
        ids_to_remove = _resolve_tag_args(catalog, args.tags, by_id=args.by_id)
        before_ids = _get_chat_tag_ids(client, bot_id, args.chat_id)
        remove_set = set(ids_to_remove)
        new_ids = [i for i in before_ids if i not in remove_set]
        if new_ids != before_ids:
            _put_chat_tags(client, base, bot_id, args.chat_id, new_ids)

    emit_json(_mutation_response(name, args.chat_id, before_ids, new_ids, catalog))
    return EXIT_OK


def cmd_clear(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    base = cfg.get("baseUrl", "https://chat.line.biz")

    with make_client(cfg, bot_id) as client:
        catalog = fetch_tag_catalog(client, bot_id)
        before_ids = _get_chat_tag_ids(client, bot_id, args.chat_id)
        if before_ids:
            _put_chat_tags(client, base, bot_id, args.chat_id, [])

    emit_json(_mutation_response(name, args.chat_id, before_ids, [], catalog))
    return EXIT_OK


def run(args) -> int:
    sub = args.tag_cmd
    handlers = {
        "list":   cmd_list,
        "create": cmd_create,
        "delete": cmd_delete,
        "get":    cmd_get,
        "set":    cmd_set,
        "add":    cmd_add,
        "remove": cmd_remove,
        "clear":  cmd_clear,
    }
    handler = handlers.get(sub)
    if handler is None:
        raise CliError(f"unknown tag subcommand: {sub}")
    return handler(args)
