"""account list/use/add/remove. Pure config IO."""
from __future__ import annotations

from .. import config as cfgmod
from ..errors import CliError, emit_json, EXIT_OK


def cmd_list(args) -> int:
    cfg = cfgmod.load(args.config)
    accounts = cfg.get("accounts", {})
    emit_json({
        "current": cfg.get("currentAccount"),
        "accounts": [
            {"name": name, "botId": a.get("botId")}
            for name, a in accounts.items()
        ],
    })
    return EXIT_OK


def cmd_use(args) -> int:
    cfg = cfgmod.load(args.config)
    if args.name not in cfg.get("accounts", {}):
        raise CliError(f"account '{args.name}' not found")
    cfg["currentAccount"] = args.name
    cfgmod.save(cfg, args.config)
    emit_json({"current": args.name})
    return EXIT_OK


def cmd_add(args) -> int:
    cfg = cfgmod.load(args.config)
    accounts = cfg.setdefault("accounts", {})
    if args.name in accounts:
        raise CliError(f"account '{args.name}' already exists")
    accounts[args.name] = {"botId": args.bot_id}
    auto_current = cfg.get("currentAccount") is None
    if auto_current:
        cfg["currentAccount"] = args.name
    cfgmod.save(cfg, args.config)
    emit_json({
        "added": args.name,
        "botId": args.bot_id,
        "currentAccount": cfg["currentAccount"],
        "autoCurrent": auto_current,
    })
    return EXIT_OK


def cmd_remove(args) -> int:
    cfg = cfgmod.load(args.config)
    accounts = cfg.get("accounts", {})
    if args.name not in accounts:
        raise CliError(f"account '{args.name}' not found")
    del accounts[args.name]
    if cfg.get("currentAccount") == args.name:
        cfg["currentAccount"] = next(iter(accounts), None)
    cfgmod.save(cfg, args.config)
    emit_json({
        "removed": args.name,
        "currentAccount": cfg["currentAccount"],
    })
    return EXIT_OK


def run(args) -> int:
    if args.account_cmd == "list":
        return cmd_list(args)
    if args.account_cmd == "use":
        return cmd_use(args)
    if args.account_cmd == "add":
        return cmd_add(args)
    if args.account_cmd == "remove":
        return cmd_remove(args)
    raise CliError(f"unknown account subcommand: {args.account_cmd}")
