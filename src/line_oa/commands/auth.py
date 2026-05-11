from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

import httpx

from .. import config as cfgmod
from ..client import make_client
from ..errors import (
    EXIT_GENERIC,
    EXIT_OK,
    EXIT_SESSION_EXPIRED,
    CliError,
    emit_json,
    map_http_status,
)

_REFERER_BOT_RE = re.compile(r"chat\.line\.biz/(U[a-f0-9]{32})(?:/|$)")


def _read_curl(args) -> str:
    if args.input_file:
        return Path(args.input_file).read_text(encoding="utf-8")
    if sys.stdin.isatty():
        raise CliError(
            "no cURL on stdin\n"
            "  paste a cURL from chat.line.biz DevTools, e.g.:\n"
            "    pbpaste | line-oa auth from-curl"
        )
    return sys.stdin.read()


def _parse_curl(curl_text: str) -> dict:
    """Tokenize a cURL command, extract cookies and referer-derived botId."""
    # cURL "Copy as cURL" uses \-line continuations; strip before shlex.
    cleaned = curl_text.replace("\\\n", " ").replace("\\\r\n", " ")
    try:
        tokens = shlex.split(cleaned, posix=True)
    except ValueError as e:
        raise CliError(f"cURL not parseable: {e}")

    cookies: dict[str, str] = {}
    referer = ""
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("-b", "--cookie") and i + 1 < len(tokens):
            cookies = _parse_cookie_header(tokens[i + 1])
            i += 2
            continue
        if t in ("-H", "--header") and i + 1 < len(tokens):
            header = tokens[i + 1]
            lower = header.lower()
            if lower.startswith("referer:"):
                referer = header.split(":", 1)[1].strip()
            elif lower.startswith("cookie:"):
                if not cookies:
                    cookies = _parse_cookie_header(header.split(":", 1)[1].strip())
            i += 2
            continue
        i += 1

    if not cookies:
        raise CliError("no -b/--cookie or 'Cookie:' header found in cURL")

    bot_id = ""
    m = _REFERER_BOT_RE.search(referer)
    if m:
        bot_id = m.group(1)

    return {"cookies": cookies, "botId": bot_id, "referer": referer}


def _parse_cookie_header(value: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in value.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _validate_session(cfg: dict, account_name: str) -> int:
    """Call list?limit=1 against the given account. Returns exit code."""
    bot_id = cfg["accounts"][account_name]["botId"]
    base = cfg.get("baseUrl", "https://chat.line.biz")
    with make_client(cfg, bot_id) as client:
        try:
            resp = client.get(
                f"/api/v2/bots/{bot_id}/chats",
                params={"folderType": "ALL", "limit": 1, "prioritizePinnedChat": "true"},
            )
        except httpx.HTTPError as e:
            print(f"[error] network: {e}", file=sys.stderr)
            return EXIT_GENERIC
    if resp.status_code == 200:
        return EXIT_OK
    if resp.status_code in (302, 401, 403):
        return EXIT_SESSION_EXPIRED
    print(f"[error] unexpected validation status {resp.status_code}: {resp.text[:200]}",
          file=sys.stderr)
    return map_http_status(resp.status_code)


def cmd_from_curl(args) -> int:
    curl_text = _read_curl(args)
    parsed = _parse_curl(curl_text)
    cfg = cfgmod.load(args.config)
    cfg["cookies"] = parsed["cookies"]
    cfgmod.save(cfg, args.config)

    print(f"ok: cookies written to {cfgmod.config_path() if not args.config else args.config}",
          file=sys.stderr)
    if parsed["botId"]:
        print(f"detected botId in referer: {parsed['botId']}", file=sys.stderr)
        known = {a["botId"]: name for name, a in cfg.get("accounts", {}).items()}
        if parsed["botId"] in known:
            print(f"  this OA is registered as '{known[parsed['botId']]}'", file=sys.stderr)
        else:
            print("  this OA is not registered. To add it:", file=sys.stderr)
            print(f"    line-oa account add <name> {parsed['botId']}", file=sys.stderr)
    else:
        print("no botId found in referer (cookies still saved)", file=sys.stderr)

    if args.no_validate:
        return EXIT_OK
    current = cfg.get("currentAccount")
    if not current:
        print("(no currentAccount set; skipping validation)", file=sys.stderr)
        return EXIT_OK
    code = _validate_session(cfg, current)
    if code == EXIT_OK:
        print(f"validated against account '{current}': session alive", file=sys.stderr)
    elif code == EXIT_SESSION_EXPIRED:
        print(f"validation failed for account '{current}': session is dead",
              file=sys.stderr)
    return code


def cmd_status(args) -> int:
    cfg = cfgmod.load(args.config)
    name, _bot_id = cfgmod.resolve_account(cfg, args.account)
    code = _validate_session(cfg, name)
    emit_json({
        "account": name,
        "alive": code == EXIT_OK,
        "code": code,
    })
    return code


def run(args) -> int:
    if args.auth_cmd == "from-curl":
        return cmd_from_curl(args)
    if args.auth_cmd == "status":
        return cmd_status(args)
    raise CliError(f"unknown auth subcommand: {args.auth_cmd}")
