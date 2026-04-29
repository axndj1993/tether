"""tether CLI.

Subcommands:
  send TEXT         — send one message
  drain             — print unread inbox lines and advance the consumed pointer
  daemon            — long-poll forever, append each inbound to inbox JSONL
  init              — interactive config wizard (creates a profile)
  whoami            — call getMe to verify token
  profiles          — list / use / current / delete named profiles

All commands accept `--profile NAME` to override profile resolution
(env var TETHER_PROFILE, .tether file in CWD/parents, or 'default').
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .client import ConfigError, Tether, TetherError, DEFAULT_STATE_DIR
from .daemon import drain, run_daemon
from . import profiles as _profiles


def _add_profile_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", default=None,
                        help="profile name (overrides env / .tether file)")


def _cmd_send(args: argparse.Namespace) -> int:
    p = Tether(profile=args.profile)
    p.send(args.text, parse_mode=args.parse_mode, silent=args.silent)
    return 0


def _cmd_drain(args: argparse.Namespace) -> int:
    return drain(in_path=args.inbox, consumed_path=args.consumed)


def _cmd_daemon(args: argparse.Namespace) -> int:
    pager = Tether(profile=args.profile)
    return run_daemon(out_path=args.inbox, pager=pager,
                      poll_timeout=args.poll_timeout)


def _cmd_whoami(args: argparse.Namespace) -> int:
    p = Tether(profile=args.profile)
    info = p.whoami()
    print(json.dumps(info, indent=2))
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    """Interactive config wizard. Writes a profile config + verifies."""
    profile_name = args.profile or _profiles.DEFAULT_PROFILE_NAME
    print(f"tether config wizard — profile: {profile_name!r}")
    print()
    print("1. Create a Telegram bot via @BotFather on Telegram, get the token.")
    print("2. Send the bot any message from your account, then visit:")
    print("   https://api.telegram.org/bot<TOKEN>/getUpdates")
    print("   to find your chat id (look for 'chat':{'id':...}).")
    print()
    token = input("Bot token: ").strip()
    chat_id = input("Chat id (numeric): ").strip()
    if not token or not chat_id:
        print("aborted: empty input", file=sys.stderr)
        return 1
    try:
        chat_id_int = int(chat_id)
    except ValueError:
        print(f"aborted: chat id must be int, got {chat_id!r}", file=sys.stderr)
        return 1

    cfg_path = _profiles.write_profile_config(
        profile_name,
        {"transport": "telegram",
         "bot_token": token,
         "chat_id": chat_id_int},
    )
    print(f"\nWrote {cfg_path}")
    print("Verifying with getMe...")
    try:
        info = Tether(profile=profile_name).whoami()
        print(f"OK — connected as bot @{info.get('username')!r}")
    except TetherError as e:
        print(f"WARN: getMe failed: {e}", file=sys.stderr)
        return 1
    if profile_name != _profiles.DEFAULT_PROFILE_NAME:
        print(
            f"\nTo make this profile auto-active in the current dir, run:"
            f"\n    tether profiles use {profile_name}"
        )
    print(f'\nTry it: tether --profile {profile_name} send "hello"')
    return 0


def _cmd_profiles(args: argparse.Namespace) -> int:
    """Profile management subcommands."""
    op = args.profile_op
    if op == "list":
        names = _profiles.list_profiles()
        if not names:
            print("(no profiles configured — run `tether init` to create one)")
            return 0
        for n in names:
            cfg = _profiles.load_profile_config(n)
            transport = cfg.get("transport", "telegram")
            ident = (cfg.get("chat_id") or cfg.get("channel_id") or "?")
            print(f"  {n:20}  transport={transport:10}  chat={ident}")
        return 0
    if op == "current":
        prof = _profiles.resolve_profile()
        cfg = _profiles.load_profile_config(prof.name)
        print(f"profile: {prof.name}")
        print(f"source : {prof.source}"
              + (f" ({prof.dot_tether_path})" if prof.dot_tether_path else ""))
        print(f"config : {_profiles.profile_config_path(prof.name)}")
        if cfg:
            print(f"transport: {cfg.get('transport', 'telegram')}")
            print(f"chat   : {cfg.get('chat_id') or cfg.get('channel_id') or '(unset)'}")
        else:
            print("config : (empty — falls back to env vars or v0.3 flat config)")
        return 0
    if op == "use":
        path = _profiles.set_active_profile(args.name)
        print(f"wrote {path}\nprofile {args.name!r} now active in this directory tree.")
        return 0
    if op == "delete":
        existed = _profiles.delete_profile(args.name)
        if not existed:
            print(f"profile {args.name!r} not found.", file=sys.stderr)
            return 1
        print(f"removed profile {args.name!r}.")
        return 0
    if op == "show":
        cfg = _profiles.load_profile_config(args.name)
        if not cfg:
            print(f"profile {args.name!r} has no config (or not found).",
                  file=sys.stderr)
            return 1
        for k, v in cfg.items():
            # Mask credentials in output.
            if "token" in k:
                v = (v[:6] + "..." + v[-4:]) if isinstance(v, str) and len(v) > 12 else "***"
            print(f"  {k} = {v!r}")
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tether",
        description="Bidirectional comms for AI agents (Telegram + Slack).",
    )
    p.add_argument("--version", action="version", version=f"tether {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send", help="send a message")
    p_send.add_argument("text", help="message body (markdown supported)")
    p_send.add_argument("--parse-mode", default="Markdown",
                        choices=["Markdown", "MarkdownV2", "HTML", "none"])
    p_send.add_argument("--silent", action="store_true",
                        help="send without notification sound")
    _add_profile_arg(p_send)
    p_send.set_defaults(func=_cmd_send)

    default_inbox = Path.cwd() / "tether_inbox.jsonl"
    p_daemon = sub.add_parser("daemon", help="long-poll, append to inbox JSONL")
    p_daemon.add_argument("--inbox", default=str(default_inbox),
                          help="output JSONL path (default ./tether_inbox.jsonl)")
    p_daemon.add_argument("--poll-timeout", type=int, default=30,
                          help="long-poll seconds per call (default 30)")
    _add_profile_arg(p_daemon)
    p_daemon.set_defaults(func=_cmd_daemon)

    p_drain = sub.add_parser("drain", help="print unread inbox + advance pointer")
    p_drain.add_argument("--inbox", default=str(default_inbox))
    p_drain.add_argument("--consumed", default=None,
                         help="consumed-pointer file (default <inbox>.consumed.json)")
    p_drain.set_defaults(func=_cmd_drain)

    p_init = sub.add_parser("init", help="interactive config wizard")
    _add_profile_arg(p_init)
    p_init.set_defaults(func=_cmd_init)

    p_who = sub.add_parser("whoami", help="verify token via getMe")
    _add_profile_arg(p_who)
    p_who.set_defaults(func=_cmd_whoami)

    p_pr = sub.add_parser("profiles", help="manage profiles")
    pr_sub = p_pr.add_subparsers(dest="profile_op", required=True)
    pr_sub.add_parser("list", help="list all profiles")
    pr_sub.add_parser("current", help="show resolved active profile")
    pr_use = pr_sub.add_parser("use", help="write .tether to CWD")
    pr_use.add_argument("name")
    pr_show = pr_sub.add_parser("show", help="show a profile's config (token masked)")
    pr_show.add_argument("name")
    pr_del = pr_sub.add_parser("delete", help="remove a profile")
    pr_del.add_argument("name")
    p_pr.set_defaults(func=_cmd_profiles)

    args = p.parse_args(argv)
    if args.cmd == "send" and args.parse_mode == "none":
        args.parse_mode = None
    try:
        return args.func(args)
    except ConfigError as e:
        print(f"tether: config error: {e}", file=sys.stderr)
        return 2
    except TetherError as e:
        print(f"tether: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
