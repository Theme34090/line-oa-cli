"""line-oa CLI dispatch."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .errors import CliError, EXIT_GENERIC


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="line-oa", description="LINE OA CS helper CLI")
    p.add_argument("--config", type=Path, default=None, help="Override config path")
    p.add_argument("--account", default=None, help="Target account (overrides current)")
    p.add_argument("--version", action="version", version=f"line-oa {__version__}")

    sub = p.add_subparsers(dest="cmd", required=True)

    # list
    pl = sub.add_parser("list", help="List chats")
    pl.add_argument("--limit", type=int, default=25)
    pl.add_argument("--since-days", type=int, default=None)
    pl.add_argument("--waiting", action="store_true",
                    help="Only chats whose latest message is from the customer")
    pl.add_argument("--folder", default="ALL", choices=["ALL", "UNREAD", "PINNED"])

    # read
    pr = sub.add_parser("read", help="Read messages from one chat")
    pr.add_argument("chat_id")
    pr.add_argument("--backward", default=None, help="Pagination cursor")
    pr.add_argument("--all", dest="fetch_all", action="store_true",
                    help="Paginate until exhausted (capped at 1000 messages)")

    # profile
    pp = sub.add_parser("profile", help="Get a chat's customer profile")
    pp.add_argument("chat_id")

    # send
    ps = sub.add_parser("send", help="Send a text reply")
    ps.add_argument("chat_id")
    ps.add_argument("text", help='Message text, or "-" to read from stdin')
    ps.add_argument("--dry-run", action="store_true")
    ps.add_argument("--no-auto-manual", action="store_true",
                    help="Don't auto-flip the chat to manual mode before sending. "
                         "Sends will fail with 'not_manual_chat_mode' unless the "
                         "chat is already manual.")
    ps.add_argument("--manual-ttl-minutes", type=int, default=60,
                    help="How long to keep the chat in manual mode (default 60). "
                         "Auto-reverts to auto/bot mode after this expires.")

    # account group
    pa = sub.add_parser("account", help="Manage OA accounts")
    pa_sub = pa.add_subparsers(dest="account_cmd", required=True)
    pa_sub.add_parser("list", help="Show all accounts + current")
    pa_use = pa_sub.add_parser("use", help="Set current account")
    pa_use.add_argument("name")
    pa_add = pa_sub.add_parser("add", help="Register an account")
    pa_add.add_argument("name")
    pa_add.add_argument("bot_id")
    pa_rm = pa_sub.add_parser("remove", help="Remove an account")
    pa_rm.add_argument("name")

    # auth group
    pau = sub.add_parser("auth", help="Auth / cookie management")
    pau_sub = pau.add_subparsers(dest="auth_cmd", required=True)
    pau_fc = pau_sub.add_parser("from-curl", help="Refresh cookies from a pasted cURL")
    pau_fc.add_argument("--input", dest="input_file", default=None,
                        help="Read cURL from FILE instead of stdin")
    pau_fc.add_argument("--no-validate", action="store_true")
    pau_sub.add_parser("status", help="Check session is alive")

    # export
    pe = sub.add_parser("export", help="Bulk-download all chats as CSV")
    pe.add_argument("--go-back-days", type=int, default=None)
    pe.add_argument("--max-chats", type=int, default=None)
    pe.add_argument("--output-dir", type=Path, default=Path("./output"))

    # install-skill
    sub.add_parser("install-skill",
                   help="Copy the line-oa skill to ~/.claude/skills/line-oa/")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Lazy import to keep --help fast.
    from .commands import account, auth, export, install_skill, list_chats, profile, read, send

    try:
        if args.cmd == "list":
            return list_chats.run(args)
        if args.cmd == "read":
            return read.run(args)
        if args.cmd == "profile":
            return profile.run(args)
        if args.cmd == "send":
            return send.run(args)
        if args.cmd == "account":
            return account.run(args)
        if args.cmd == "auth":
            return auth.run(args)
        if args.cmd == "export":
            return export.run(args)
        if args.cmd == "install-skill":
            return install_skill.run(args)
        parser.error(f"unknown command: {args.cmd}")
    except CliError as e:
        print(f"[error] {e}", file=sys.stderr, flush=True)
        return e.code
    except KeyboardInterrupt:
        return 130

    return EXIT_GENERIC


if __name__ == "__main__":
    sys.exit(main())
