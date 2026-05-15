from __future__ import annotations

from .. import config as cfgmod
from ..client import (
    fetch_chat,
    fetch_tag_catalog,
    make_client,
    resolve_tag_args,
    write_headers,
)
from ..errors import (
    CliError,
    EXIT_OK,
    emit_json,
    map_http_status,
)
from ._curate import curate_tag, tag_id_to_name


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


def _put_chat_tags(
    client, base: str, bot_id: str, chat_id: str, tag_ids: list[str],
) -> None:
    """PUT /api/v1/bots/{bot}/chats/{chat}/tags. Replaces the entire list."""
    resp = client.put(
        f"/api/v1/bots/{bot_id}/chats/{chat_id}/tags",
        json={"tagIds": tag_ids},
        headers=write_headers(base, bot_id, chat_id=chat_id),
    )
    if resp.status_code not in (200, 204):
        raise CliError(
            f"set tags failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )


def _chat_tag_ids(client, bot_id: str, chat_id: str) -> list[str]:
    """Current tagIds (manual tags only) for one chat."""
    return list(fetch_chat(client, bot_id, chat_id).get("tagIds") or [])


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
            "tags": [curate_tag(t) for t in catalog],
        })
    return EXIT_OK


def cmd_create(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    base = cfg.get("baseUrl", "https://chat.line.biz")
    tag_name = args.name
    if not tag_name.strip():
        raise CliError("refusing to create an empty/whitespace tag name")

    headers = write_headers(base, bot_id)
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
            tag_id = resolve_tag_args(catalog, [args.tag], by_id=False)[0]
            tag_name = args.tag

        resp = client.delete(
            f"/api/v1/bots/{bot_id}/tags/{tag_id}",
            headers=write_headers(base, bot_id),
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
        current_ids = _chat_tag_ids(client, bot_id, args.chat_id)
        # Skip the catalog GET when the chat has no tags — there's
        # nothing to resolve.
        by_id = tag_id_to_name(fetch_tag_catalog(client, bot_id)) if current_ids else {}
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
    by_id = tag_id_to_name(catalog)

    def names(ids: list[str]) -> list[str]:
        return [by_id.get(i, i) for i in ids]

    before_set = set(before_ids)
    after_set = set(after_ids)
    return {
        "account": account,
        "chatId": chat_id,
        "before":  names(before_ids),
        "after":   names(after_ids),
        "added":   names([t for t in after_ids if t not in before_set]),
        "removed": names([t for t in before_ids if t not in after_set]),
    }


def _load_catalog_if_resolving_names(client, bot_id: str, by_id: bool) -> list[dict]:
    """Fetch the tag catalog only when names need resolving. In --id
    mode the catalog isn't required (resolve_tag_args is a passthrough,
    and the mutation response falls back to raw IDs)."""
    return [] if by_id else fetch_tag_catalog(client, bot_id)


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
        catalog = _load_catalog_if_resolving_names(client, bot_id, args.by_id)
        new_ids = resolve_tag_args(catalog, args.tags, by_id=args.by_id)
        before_ids = _chat_tag_ids(client, bot_id, args.chat_id)
        _put_chat_tags(client, base, bot_id, args.chat_id, new_ids)

    emit_json(_mutation_response(name, args.chat_id, before_ids, new_ids, catalog))
    return EXIT_OK


def cmd_add(args) -> int:
    if not args.tags:
        raise CliError(
            "no tags supplied to `tag add`. Pass one or more tag names "
            "(or IDs with --id).",
        )

    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    base = cfg.get("baseUrl", "https://chat.line.biz")

    with make_client(cfg, bot_id) as client:
        catalog = _load_catalog_if_resolving_names(client, bot_id, args.by_id)
        ids_to_add = resolve_tag_args(catalog, args.tags, by_id=args.by_id)
        before_ids = _chat_tag_ids(client, bot_id, args.chat_id)
        before_set = set(before_ids)
        new_ids = before_ids + [i for i in ids_to_add if i not in before_set]
        if new_ids != before_ids:
            _put_chat_tags(client, base, bot_id, args.chat_id, new_ids)

    emit_json(_mutation_response(name, args.chat_id, before_ids, new_ids, catalog))
    return EXIT_OK


def cmd_remove(args) -> int:
    if not args.tags:
        raise CliError(
            "no tags supplied to `tag remove`. Pass one or more tag names "
            "(or IDs with --id); use `tag clear` to remove all tags.",
        )

    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    base = cfg.get("baseUrl", "https://chat.line.biz")

    with make_client(cfg, bot_id) as client:
        catalog = _load_catalog_if_resolving_names(client, bot_id, args.by_id)
        ids_to_remove = resolve_tag_args(catalog, args.tags, by_id=args.by_id)
        before_ids = _chat_tag_ids(client, bot_id, args.chat_id)
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
        before_ids = _chat_tag_ids(client, bot_id, args.chat_id)
        # Catalog only needed to resolve before-IDs → names for the
        # response. Skip when there's nothing to resolve.
        catalog = fetch_tag_catalog(client, bot_id) if before_ids else []
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
