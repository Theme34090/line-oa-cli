"""Shared input helpers for command handlers."""
from __future__ import annotations

import sys


def read_text_or_stdin(arg: str) -> str:
    """Return `arg` verbatim, or read stdin when `arg == "-"`.

    Trailing newline is stripped so a `pbpaste | line-oa send U... -`
    pipeline doesn't append an empty line to the message body."""
    if arg == "-":
        return sys.stdin.read().rstrip("\n")
    return arg
