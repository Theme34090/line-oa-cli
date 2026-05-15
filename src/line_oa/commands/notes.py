from __future__ import annotations

from .. import config as cfgmod
from ..client import make_client, write_headers
from ..errors import (
    CliError,
    EXIT_OK,
    emit_json,
    map_http_status,
)
from ._curate import curate_note
from ._io import read_text_or_stdin


EPILOG = """\
Notes are per-chat free-form text scratchpads (CS context like
"prefers email", "VIP — escalate to Mgr", "follow up Tue").

Subcommands:

  list   CHATID                       List all notes on a chat. Curated:
                                      [{id, body, authorId, createdAt, updatedAt}].
  add    CHATID BODY                  Create a new note. Returns the new note
                                      (use the returned `id` for later edit/delete).
                                      BODY="-" reads from stdin.
  edit   CHATID NOTEID BODY           Replace a note's body. Returns the updated note.
                                      BODY="-" reads from stdin.
  delete CHATID NOTEID --yes          Delete a note. Destructive (no soft-delete,
                                      no undelete); --yes is required.

Note identity:
  Notes are addressed by raw note ID (~26 base32 chars, e.g.
  agpcwqa5srd2efuudvb6bfbmai). There is no human-readable name.
  Run `line-oa notes list CHATID` first to discover IDs.

Curated output shapes (use --raw for LINE's verbatim response):

  list:   {account, chatId, count, notes: [Note, ...]}
  add:    {account, chatId, note: Note}
  edit:   {account, chatId, note: Note}
  delete: {account, chatId, deleted: {id}}

  Note: {id, body, authorId, createdAt, updatedAt}

  authorId is the OA staff member's UUID; no display-name lookup.

Caveats:
- Empty/whitespace bodies are refused on add/edit.
- delete is idempotent server-side — LINE returns 200 even for a
  note that no longer exists, so a stale ID looks like success.
  Run `notes list` first if you need to confirm the note was real.
- `list` returns the full set in one call; LINE's notes endpoint does
  not appear to paginate.
"""


def _notes_url(bot_id: str, chat_id: str, note_id: str | None = None) -> str:
    base = f"/api/v1/bots/{bot_id}/chats/{chat_id}/notes"
    return f"{base}/{note_id}" if note_id else base


def cmd_list(args) -> int:
    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    with make_client(cfg, bot_id) as client:
        resp = client.get(_notes_url(bot_id, args.chat_id))
    if resp.status_code != 200:
        raise CliError(
            f"list notes failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    data = resp.json()
    notes = data.get("list", [])
    if args.raw:
        emit_json({"account": name, "chatId": args.chat_id, **data})
    else:
        emit_json({
            "account": name,
            "chatId": args.chat_id,
            "count": len(notes),
            "notes": [curate_note(n) for n in notes],
        })
    return EXIT_OK


def cmd_add(args) -> int:
    body = read_text_or_stdin(args.body)
    if not body.strip():
        raise CliError("refusing to create an empty/whitespace note")

    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    base = cfg.get("baseUrl", "https://chat.line.biz")

    with make_client(cfg, bot_id) as client:
        resp = client.post(
            _notes_url(bot_id, args.chat_id),
            json={"body": body},
            headers=write_headers(base, bot_id, chat_id=args.chat_id),
        )
    if resp.status_code not in (200, 201):
        raise CliError(
            f"add note failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    note = resp.json()
    emit_json({
        "account": name,
        "chatId": args.chat_id,
        "note": note if args.raw else curate_note(note),
    })
    return EXIT_OK


def cmd_edit(args) -> int:
    body = read_text_or_stdin(args.body)
    if not body.strip():
        raise CliError("refusing to edit a note to empty/whitespace body")

    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    base = cfg.get("baseUrl", "https://chat.line.biz")

    with make_client(cfg, bot_id) as client:
        resp = client.put(
            _notes_url(bot_id, args.chat_id, args.note_id),
            json={"body": body},
            headers=write_headers(base, bot_id, chat_id=args.chat_id),
        )
    if resp.status_code != 200:
        raise CliError(
            f"edit note failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    note = resp.json()
    emit_json({
        "account": name,
        "chatId": args.chat_id,
        "note": note if args.raw else curate_note(note),
    })
    return EXIT_OK


def cmd_delete(args) -> int:
    if not args.yes:
        raise CliError(
            "notes delete is destructive (no undelete). "
            "Re-run with --yes to confirm.",
        )

    cfg = cfgmod.load(args.config)
    name, bot_id = cfgmod.resolve_account(cfg, args.account)
    base = cfg.get("baseUrl", "https://chat.line.biz")

    with make_client(cfg, bot_id) as client:
        resp = client.delete(
            _notes_url(bot_id, args.chat_id, args.note_id),
            headers=write_headers(base, bot_id, chat_id=args.chat_id),
        )
    if resp.status_code not in (200, 204):
        raise CliError(
            f"delete note failed: {resp.status_code} {resp.text[:200]}",
            code=map_http_status(resp.status_code),
        )
    emit_json({
        "account": name,
        "chatId": args.chat_id,
        "deleted": {"id": args.note_id},
    })
    return EXIT_OK


def run(args) -> int:
    sub = args.notes_cmd
    handlers = {
        "list":   cmd_list,
        "add":    cmd_add,
        "edit":   cmd_edit,
        "delete": cmd_delete,
    }
    handler = handlers.get(sub)
    if handler is None:
        raise CliError(f"unknown notes subcommand: {sub}")
    return handler(args)
