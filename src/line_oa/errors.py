"""Exit codes and error helpers.

The skill watches these distinctly:
  2 -> session expired, prompt user to re-paste cURL
  5 -> no account selected, prompt user to add/use
"""
from __future__ import annotations

import json
import sys

EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_SESSION_EXPIRED = 2
EXIT_CHAT_NOT_FOUND = 3
EXIT_RATE_LIMITED = 4
EXIT_NO_ACCOUNT = 5


class CliError(Exception):
    def __init__(self, message: str, code: int = EXIT_GENERIC):
        super().__init__(message)
        self.code = code


def die(message: str, code: int = EXIT_GENERIC) -> "NoReturn":  # type: ignore[name-defined]
    print(f"[error] {message}", file=sys.stderr, flush=True)
    sys.exit(code)


def map_http_status(status: int) -> int:
    if status in (401, 403):
        return EXIT_SESSION_EXPIRED
    if status == 302:
        return EXIT_SESSION_EXPIRED
    if status == 404:
        return EXIT_CHAT_NOT_FOUND
    if status == 429:
        return EXIT_RATE_LIMITED
    return EXIT_GENERIC


def emit_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))
