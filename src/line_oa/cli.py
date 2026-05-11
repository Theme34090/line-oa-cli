from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .commands import content as content_cmd
from .commands import list_chats, profile, read, send
from .errors import CliError, EXIT_GENERIC


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="line-oa", description="LINE OA CS helper CLI")
    p.add_argument("--config", type=Path, default=None, help="Override config path")
    p.add_argument("--account", default=None, help="Target account (overrides current)")
    p.add_argument("--version", action="version", version=f"line-oa {__version__}")

    sub = p.add_subparsers(dest="cmd", required=True)

    # list
    pl = sub.add_parser(
        "list",
        help="List chats",
        description="List chats with curated triage state and last-message preview.",
        epilog=list_chats.EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pl.add_argument("--limit", type=int, default=25)
    pl.add_argument("--since-days", type=int, default=None)
    pl.add_argument("--waiting", action="store_true",
                    help="Only chats whose latest message is from the customer")
    pl.add_argument("--folder", default="ALL", choices=["ALL", "UNREAD", "PINNED"])
    pl.add_argument("--raw", action="store_true",
                    help="Emit the full LINE response instead of the curated shape")

    # read
    pr = sub.add_parser(
        "read",
        help="Read messages from one chat",
        description="Read messages newest-first; curated to message events only.",
        epilog=read.EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pr.add_argument("chat_id")
    pr.add_argument("--backward", default=None, help="Pagination cursor")
    pr.add_argument("--all", dest="fetch_all", action="store_true",
                    help="Paginate until exhausted (capped at 1000 messages)")
    pr.add_argument("--raw", action="store_true",
                    help="Emit the full LINE response (includes chatRead "
                         "watermarks and quote tokens)")

    # profile
    pp = sub.add_parser(
        "profile",
        help="Get a chat's customer profile",
        description="Customer-identity slice (name, friend, push window).",
        epilog=profile.EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pp.add_argument("chat_id")
    pp.add_argument("--raw", action="store_true",
                    help="Emit the full LINE chat-metadata blob")

    # send
    ps = sub.add_parser(
        "send",
        help="Send a text reply",
        description="Send a text reply; auto-flips the chat to manual mode first.",
        epilog=send.EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
    ps.add_argument("--raw", action="store_true",
                    help="Emit the full LINE API response and HTTP status")

    # content
    pc = sub.add_parser(
        "content",
        help="Fetch a chat attachment by its contentHash",
        description="Fetch a chat attachment (image/video/audio/file) by its contentHash.",
        epilog=content_cmd.EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pc.add_argument("content_hash",
                    help="The contentHash from a media message in `line-oa read`")
    pc.add_argument("--out", default=None,
                    help="Write to this path instead of the cache")
    pc.add_argument("--no-cache", action="store_true",
                    help="Always re-fetch even if cached")

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

    # Lazy import non-build-time deps to keep --help fast.
    from .commands import account, auth, export, install_skill

    dispatch = {
        "list": list_chats.run,
        "read": read.run,
        "profile": profile.run,
        "send": send.run,
        "content": content_cmd.run,
        "account": account.run,
        "auth": auth.run,
        "export": export.run,
        "install-skill": install_skill.run,
    }

    try:
        handler = dispatch.get(args.cmd)
        if handler is None:
            raise CliError(f"unknown command: {args.cmd}", code=EXIT_GENERIC)
        return handler(args)
    except CliError as e:
        print(f"[error] {e}", file=sys.stderr, flush=True)
        return e.code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
