"""tether CLI.

Subcommands:
  send TEXT       — send one message
  drain           — print unread inbox lines and advance the consumed pointer
  daemon          — long-poll forever, append each inbound to inbox JSONL
  init            — interactive config wizard
  whoami          — call getMe to verify token
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


def _cmd_send(args: argparse.Namespace) -> int:
    p = Tether()
    p.send(args.text, parse_mode=args.parse_mode, silent=args.silent)
    return 0


def _cmd_drain(args: argparse.Namespace) -> int:
    return drain(in_path=args.inbox, consumed_path=args.consumed)


def _cmd_daemon(args: argparse.Namespace) -> int:
    return run_daemon(out_path=args.inbox, poll_timeout=args.poll_timeout)


def _cmd_whoami(_: argparse.Namespace) -> int:
    p = Tether()
    info = p.whoami()
    print(json.dumps(info, indent=2))
    return 0


def _cmd_init(_: argparse.Namespace) -> int:
    """Interactive config wizard. Writes ~/.tether/config.toml."""
    print("tether config wizard")
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
    DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    cfg = DEFAULT_STATE_DIR / "config.toml"
    cfg.write_text(
        f'bot_token = "{token}"\n'
        f"chat_id = {chat_id_int}\n",
        encoding="utf-8",
    )
    # Permissions tighten on POSIX; Windows keeps NTFS defaults.
    try:
        os.chmod(cfg, 0o600)
    except OSError:
        pass
    print(f"\nWrote {cfg}")
    print("Verifying with getMe...")
    try:
        info = Tether().whoami()
        print(f"OK — connected as bot @{info.get('username')!r}")
    except TetherError as e:
        print(f"WARN: getMe failed: {e}", file=sys.stderr)
        return 1
    print('\nTry it: tether send "hello from tether"')
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tether",
        description="Telegram bidirectional comms for AI agents.",
    )
    p.add_argument("--version", action="version", version=f"tether {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send", help="send a message")
    p_send.add_argument("text", help="message body (markdown supported)")
    p_send.add_argument("--parse-mode", default="Markdown",
                        choices=["Markdown", "MarkdownV2", "HTML", "none"])
    p_send.add_argument("--silent", action="store_true",
                        help="send without notification sound")
    p_send.set_defaults(func=_cmd_send)

    default_inbox = Path.cwd() / "tether_inbox.jsonl"
    p_daemon = sub.add_parser("daemon", help="long-poll, append to inbox JSONL")
    p_daemon.add_argument("--inbox", default=str(default_inbox),
                          help="output JSONL path (default ./tether_inbox.jsonl)")
    p_daemon.add_argument("--poll-timeout", type=int, default=30,
                          help="long-poll seconds per call (default 30)")
    p_daemon.set_defaults(func=_cmd_daemon)

    p_drain = sub.add_parser("drain", help="print unread inbox + advance pointer")
    p_drain.add_argument("--inbox", default=str(default_inbox))
    p_drain.add_argument("--consumed", default=None,
                         help="consumed-pointer file (default <inbox>.consumed.json)")
    p_drain.set_defaults(func=_cmd_drain)

    p_init = sub.add_parser("init", help="interactive config wizard")
    p_init.set_defaults(func=_cmd_init)

    p_who = sub.add_parser("whoami", help="verify token via getMe")
    p_who.set_defaults(func=_cmd_whoami)

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
