"""Config IO. Single JSON file at ~/.config/line-oa/config.json (XDG-aware)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import CliError, EXIT_NO_ACCOUNT

DEFAULT_BASE_URL = "https://chat.line.biz"
DEFAULT_TZ_OFFSET = 420  # GMT+7, Thailand


def config_path() -> Path:
    override = os.environ.get("LINE_OA_CONFIG")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "line-oa" / "config.json"


def empty_config() -> dict[str, Any]:
    return {
        "baseUrl": DEFAULT_BASE_URL,
        "timezoneOffset": DEFAULT_TZ_OFFSET,
        "cookies": {},
        "accounts": {},
        "currentAccount": None,
    }


def load(path: Path | None = None) -> dict[str, Any]:
    p = path or config_path()
    if not p.exists():
        return empty_config()
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # Backfill defaults for forward-compat
    cfg = empty_config()
    cfg.update(data)
    cfg.setdefault("cookies", {})
    cfg.setdefault("accounts", {})
    cfg.setdefault("currentAccount", None)
    return cfg


def save(cfg: dict[str, Any], path: Path | None = None) -> None:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    tmp.replace(p)
    try:
        p.chmod(0o600)
    except OSError:
        pass


def resolve_account(cfg: dict[str, Any], flag: str | None) -> tuple[str, str]:
    """Return (name, botId). Errors with exit 5 if none can be resolved."""
    name = flag or os.environ.get("LINE_OA_ACCOUNT") or cfg.get("currentAccount")
    if not name:
        raise CliError(
            "no account selected\n"
            "  - configure: line-oa account add <name> <botId>\n"
            "  - or pass:   line-oa --account NAME <command>\n"
            "  - see also:  line-oa account list",
            code=EXIT_NO_ACCOUNT,
        )
    accounts = cfg.get("accounts", {})
    if name not in accounts:
        raise CliError(
            f"account '{name}' not found. known: {sorted(accounts.keys()) or '(none)'}",
            code=EXIT_NO_ACCOUNT,
        )
    bot_id = accounts[name].get("botId")
    if not bot_id:
        raise CliError(f"account '{name}' has no botId", code=EXIT_NO_ACCOUNT)
    return name, bot_id
