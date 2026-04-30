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
from . import install as _install


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
    """Interactive config wizard with chat-id auto-detection.

    Replaces the manual 'visit getUpdates URL, find chat.id' step
    that's the biggest friction point in tether's onboarding. After
    the user pastes their bot token, the wizard prompts them to DM
    the bot, then auto-detects the chat id via Telegram getUpdates.

    With `--install <client>` (e.g. claude-code), also writes the
    host's MCP config in the same wizard pass — replacing the manual
    JSON edit.
    """
    profile_name = args.profile or _profiles.DEFAULT_PROFILE_NAME
    print(f"tether setup wizard — profile: {profile_name!r}")
    print()
    print("Step 1 of 3: Bot token.")
    print("  Open Telegram, message @BotFather, run /newbot.")
    print("  Paste the token below.")
    print()
    token = input("Bot token: ").strip()
    if not token:
        print("aborted: empty token", file=sys.stderr)
        return 1

    chat_id_int: int | None
    if args.chat_id is not None:
        # Operator passed --chat-id explicitly; skip auto-detect.
        try:
            chat_id_int = int(args.chat_id)
        except ValueError:
            print(f"--chat-id must be an integer, got {args.chat_id!r}",
                  file=sys.stderr)
            return 1
    else:
        print()
        print("Step 2 of 3: Chat id.")
        print("  Now open Telegram, search for your bot by username,")
        print("  and send it ANY message (e.g. /start). Don't close")
        print("  this terminal.")
        print()
        print("  Waiting up to 60 seconds for your message... ", end="",
              flush=True)
        chat_id_int = _install.auto_detect_chat_id(token, timeout_s=60)
        if chat_id_int is None:
            print()
            print("(timeout — no message received)", file=sys.stderr)
            print(
                "Fallback: visit "
                f"https://api.telegram.org/bot{token[:8]}.../getUpdates "
                "in a browser, find chat.id, and re-run with --chat-id N",
                file=sys.stderr,
            )
            return 1
        print(f"detected chat_id={chat_id_int}")

    cfg_path = _profiles.write_profile_config(
        profile_name,
        {"transport": "telegram",
         "bot_token": token,
         "chat_id": chat_id_int},
    )
    print()
    print(f"Wrote profile config: {cfg_path}")

    print()
    print("Step 3 of 3: Verifying with Telegram getMe...")
    try:
        info = Tether(profile=profile_name).whoami()
        print(f"OK — connected as bot @{info.get('username')!r}")
    except TetherError as e:
        print(f"WARN: getMe failed: {e}", file=sys.stderr)
        return 1

    # Optional: auto-install into a host's MCP config.
    if args.install:
        client = args.install
        try:
            written = _install.install(
                client, profile=profile_name,
                inline_creds=args.inline_creds,
            )
        except SystemExit as e:
            print(f"install failed: {e}", file=sys.stderr)
            return 1
        spec = _install.CLIENTS[client]
        print()
        print(f"Wrote {spec.name} MCP config: {written}")
        # Claude Code: also wire turn-boundary inbox-drain hooks
        # (uses default inbox/consumed paths — re-run `tether install
        # claude-code --inbox-path X` if you have a custom daemon).
        if client == "claude-code" and not args.no_hooks:
            try:
                hooks_path = _install.install_claude_code_hooks(
                    project_root=Path.cwd(),
                )
            except SystemExit as e:
                print(f"hook install failed: {e}", file=sys.stderr)
                return 1
            print(f"Wrote Claude Code hooks: {hooks_path}")
            print("  (Stop + UserPromptSubmit auto-drain the Telegram inbox)")
        print(f"Restart {spec.name} to pick up the new server.")
        return 0

    if profile_name != _profiles.DEFAULT_PROFILE_NAME:
        print(
            f"\nTo make this profile auto-active in the current dir, run:"
            f"\n    tether profiles use {profile_name}"
        )
    print()
    print('Setup complete. Try it: tether send "hello"')
    print()
    print("Next: install into your AI client with one command, e.g.:")
    print("    tether install claude-code")
    print("    tether install cursor")
    print("    tether install codex")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    """Auto-write tether's MCP server block into a host's config.

    Replaces the manual 'edit .claude/mcp.json' step. Locates the
    right config file for the chosen host, preserves any existing
    servers, adds (or replaces) the `tether` block.

    For `claude-code`, also wires Stop + UserPromptSubmit hooks into
    `.claude/settings.json` so the agent auto-drains the Telegram
    inbox at turn boundaries (replacing manual polling). Use
    `--no-hooks` to opt out.
    """
    profile_name = args.profile or _profiles.resolve_profile().name
    try:
        written = _install.install(
            args.client, profile=profile_name,
            inline_creds=args.inline_creds,
        )
    except SystemExit as e:
        print(f"install failed: {e}", file=sys.stderr)
        return 1
    spec = _install.CLIENTS[args.client]
    print(f"Wrote {spec.name} MCP config: {written}")
    print(f"Profile pinned: {profile_name}")

    # Claude Code only: optional turn-boundary hook installer.
    if args.client == "claude-code" and not args.no_hooks:
        try:
            hooks_path = _install.install_claude_code_hooks(
                project_root=Path.cwd(),
                inbox_path=args.inbox_path,
                consumed_path=args.consumed_path,
                settings_filename=args.settings_filename,
            )
        except SystemExit as e:
            print(f"hook install failed: {e}", file=sys.stderr)
            return 1
        print(f"Wrote Claude Code hooks: {hooks_path}")
        print("  - Stop: drains Telegram inbox at end of turn "
              "(force-continues if unread)")
        print("  - UserPromptSubmit: prepends unread inbox messages "
              "before each prompt")
        print(f"  - inbox: {args.inbox_path}")
        print(f"  - consumed: {args.consumed_path}")

    print(f"Restart {spec.name} to pick up the new server.")
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

    p_init = sub.add_parser("init",
                              help="interactive setup wizard (auto-detects chat id)")
    _add_profile_arg(p_init)
    p_init.add_argument("--chat-id", default=None,
                        help="explicit chat id (skips auto-detection)")
    p_init.add_argument(
        "--install", default=None,
        choices=list(_install.CLIENTS.keys()),
        help="also auto-install MCP config into this AI agent host",
    )
    p_init.add_argument("--inline-creds", action="store_true",
                        help="embed bot token + chat id in the host's MCP "
                             "config (default: pin TETHER_PROFILE only)")
    p_init.add_argument(
        "--no-hooks", action="store_true",
        help="(--install claude-code) skip the Stop + UserPromptSubmit "
             "inbox-drain hooks",
    )
    p_init.set_defaults(func=_cmd_init)

    p_install = sub.add_parser(
        "install",
        help="auto-write tether's MCP block into an AI host's config",
    )
    p_install.add_argument(
        "client",
        choices=list(_install.CLIENTS.keys()),
        help="AI agent host (claude-code/cursor/cline/codex/continue/zed)",
    )
    _add_profile_arg(p_install)
    p_install.add_argument(
        "--inline-creds", action="store_true",
        help="embed bot token + chat id in the host's MCP config "
             "(default: pin TETHER_PROFILE only)",
    )
    # Claude Code hooks (turn-boundary inbox drain).
    p_install.add_argument(
        "--no-hooks", action="store_true",
        help="(claude-code) skip wiring the Stop + UserPromptSubmit "
             "hooks that auto-drain the Telegram inbox",
    )
    p_install.add_argument(
        "--inbox-path", default="tether_inbox.jsonl",
        help="(claude-code) path the daemon writes inbound messages to "
             "(default: tether_inbox.jsonl)",
    )
    p_install.add_argument(
        "--consumed-path", default="tether_inbox.consumed.json",
        help="(claude-code) path of the consumed-pointer json "
             "(default: tether_inbox.consumed.json)",
    )
    p_install.add_argument(
        "--settings-filename", default="settings.json",
        choices=["settings.json", "settings.local.json"],
        help="(claude-code) which settings file to write hooks to "
             "(default: settings.json — shared across the team)",
    )
    p_install.set_defaults(func=_cmd_install)

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
