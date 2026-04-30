"""Auto-install tether's MCP server config into AI agent hosts.

Replaces hand-editing each host's `mcp.json` (or equivalent) with one
command:

    tether install claude-code [--profile NAME]
    tether install cursor      [--profile NAME]
    tether install cline       [--profile NAME]
    tether install codex       [--profile NAME]
    tether install continue    [--profile NAME]
    tether install zed         [--profile NAME]

What it does:

  1. Locates the host's MCP config file (creates it if missing).
  2. Loads existing config (preserving any other servers configured).
  3. Adds (or replaces) the `tether` server block with the right
     `command` (`tether-mcp`) and either inline credentials or a
     `TETHER_PROFILE` env var.
  4. Writes the file back atomically (tmp + rename).
  5. Tells the user "now restart <host>".

The config is host-specific because each host uses a slightly
different file path / shape. We handle the major ones; PRs welcome
for the rest.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable

from .profiles import load_profile_config, DEFAULT_PROFILE_NAME


# ---------------------------------------------------------------------------
# Per-client config description
# ---------------------------------------------------------------------------
class _ClientSpec:
    """Per-host MCP config metadata."""

    def __init__(
        self,
        name: str,
        config_paths: list[Path],
        format: str,                      # "json" | "yaml"
        servers_key_path: list[str],      # JSON path to mcpServers dict
        merger: Callable[[dict, str, dict], dict] | None = None,
    ) -> None:
        self.name = name
        self.config_paths = config_paths
        self.format = format
        self.servers_key_path = servers_key_path
        self.merger = merger


def _claude_code_paths() -> list[Path]:
    """Project-local first, then user-global."""
    paths: list[Path] = []
    # Project scope: Claude Code reads `.mcp.json` at the repo root
    # (NOT `.claude/mcp.json` — that path is silently ignored).
    cwd_local = Path.cwd() / ".mcp.json"
    paths.append(cwd_local)
    # User scope is stored inside `~/.claude.json` (large multi-key file),
    # not as a standalone mcp.json — handle via `claude mcp add -s user`.
    return paths


CLIENTS: dict[str, _ClientSpec] = {
    "claude-code": _ClientSpec(
        name="Claude Code",
        config_paths=_claude_code_paths(),
        format="json",
        servers_key_path=["mcpServers"],
    ),
    "cursor": _ClientSpec(
        name="Cursor",
        config_paths=[
            Path.cwd() / ".cursor" / "mcp.json",
            Path.home() / ".cursor" / "mcp.json",
        ],
        format="json",
        servers_key_path=["mcpServers"],
    ),
    "cline": _ClientSpec(
        # Cline uses VS Code's settings.json for MCP, but the location
        # varies per-OS and the schema is nested. Easiest portable
        # path: write a sidecar JSON that the user can copy, with
        # instructions.
        name="Cline (sidecar)",
        config_paths=[Path.cwd() / ".cline-mcp.json"],
        format="json",
        servers_key_path=["mcpServers"],
    ),
    "codex": _ClientSpec(
        name="Codex CLI",
        config_paths=[
            Path.cwd() / ".codex" / "mcp.json",
            Path.home() / ".codex" / "mcp.json",
        ],
        format="json",
        servers_key_path=["mcpServers"],
    ),
    "continue": _ClientSpec(
        name="Continue.dev",
        config_paths=[
            Path.cwd() / ".continue" / "config.yaml",
            Path.home() / ".continue" / "config.yaml",
        ],
        format="yaml",
        servers_key_path=["mcpServers"],
    ),
    "zed": _ClientSpec(
        name="Zed (sidecar)",
        config_paths=[Path.cwd() / ".zed-mcp.json"],
        format="json",
        servers_key_path=["mcpServers"],
    ),
}


# ---------------------------------------------------------------------------
# Server-block builder
# ---------------------------------------------------------------------------
def _build_server_block(profile: str | None, *, prefer_inline_creds: bool) -> dict:
    """Build the mcpServers entry for `tether-mcp`.

    If `prefer_inline_creds=True` and a profile has loadable credentials,
    embed them in the env block (so MCP hosts that don't pass the
    user's env to subprocesses still get them). Otherwise pin via
    TETHER_PROFILE (cleaner — no token in mcp.json).
    """
    env: dict[str, str] = {}
    if profile and profile != DEFAULT_PROFILE_NAME:
        env["TETHER_PROFILE"] = profile
    if prefer_inline_creds:
        cfg = load_profile_config(profile or DEFAULT_PROFILE_NAME)
        token = cfg.get("bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = cfg.get("chat_id") or os.environ.get("TELEGRAM_CHAT_ID")
        if token:
            env["TELEGRAM_BOT_TOKEN"] = str(token)
        if chat_id:
            env["TELEGRAM_CHAT_ID"] = str(chat_id)
    return {"command": "tether-mcp", **({"env": env} if env else {})}


# ---------------------------------------------------------------------------
# Read / write helpers
# ---------------------------------------------------------------------------
def _read_existing(spec: _ClientSpec, path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    if spec.format == "json":
        return json.loads(raw)
    if spec.format == "yaml":
        try:
            import yaml
        except ImportError:
            raise SystemExit(
                "tether install --continue: requires PyYAML. "
                "Install with: pip install pyyaml"
            )
        return yaml.safe_load(raw) or {}
    raise ValueError(f"unknown format: {spec.format}")


def _write_back(spec: _ClientSpec, path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if spec.format == "json":
        text = json.dumps(data, indent=2) + "\n"
    elif spec.format == "yaml":
        import yaml  # already imported in _read_existing path
        text = yaml.safe_dump(data, sort_keys=False)
    else:
        raise ValueError(f"unknown format: {spec.format}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Top-level install
# ---------------------------------------------------------------------------
def install(
    client: str,
    *,
    profile: str | None = None,
    config_path: Path | None = None,
    inline_creds: bool = False,
    server_name: str = "tether",
) -> Path:
    """Install tether's MCP server into the named client's config.

    Args:
        client: one of CLIENTS keys ("claude-code", "cursor", ...).
        profile: tether profile to pin via env. If unset, the host
            falls back to TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env
            vars at runtime.
        config_path: explicit path to write to. If unset, picks the
            first existing one from spec.config_paths, or the first
            entry if none exist (creating it).
        inline_creds: embed bot_token + chat_id in the mcp.json env
            block. False (default) just sets TETHER_PROFILE so the
            token stays in ~/.tether/profiles/<name>/.
        server_name: key in the mcpServers dict (default "tether").

    Returns the path written.
    """
    if client not in CLIENTS:
        raise SystemExit(
            f"unknown client {client!r}. supported: "
            f"{', '.join(sorted(CLIENTS))}"
        )
    spec = CLIENTS[client]
    if config_path is None:
        # Prefer an existing path (project-local > user-global), else
        # create the first.
        existing = [p for p in spec.config_paths if p.exists()]
        config_path = existing[0] if existing else spec.config_paths[0]

    data = _read_existing(spec, config_path)
    # Walk to mcpServers (typically just one level deep).
    cur = data
    for key in spec.servers_key_path[:-1]:
        cur = cur.setdefault(key, {})
    last = spec.servers_key_path[-1]
    servers = cur.setdefault(last, {})
    if not isinstance(servers, dict):
        # Continue.dev's YAML schema sometimes uses a list. Convert.
        servers = {}
        cur[last] = servers
    servers[server_name] = _build_server_block(
        profile, prefer_inline_creds=inline_creds)
    _write_back(spec, config_path, data)
    return config_path


def auto_detect_chat_id(bot_token: str, *, timeout_s: int = 60) -> int | None:
    """Wait for the user to DM the bot, then auto-detect chat_id.

    Polls Telegram getUpdates with a 30-second long-poll, repeatedly,
    for up to `timeout_s` seconds total. Returns the chat_id of the
    first private-chat message, or None on timeout.

    Replaces the manual "visit getUpdates URL, find chat.id" step
    that's the most error-prone bit of tether's onboarding.
    """
    import time

    import requests

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    deadline = time.time() + timeout_s
    offset = 0
    while time.time() < deadline:
        remaining = max(1, int(deadline - time.time()))
        try:
            resp = requests.get(
                url,
                params={"offset": offset, "timeout": min(30, remaining)},
                timeout=min(35, remaining + 5),
            )
        except requests.RequestException:
            time.sleep(2)
            continue
        try:
            data = resp.json()
        except ValueError:
            time.sleep(2)
            continue
        if not data.get("ok"):
            return None
        for upd in data.get("result", []) or []:
            offset = max(offset, int(upd.get("update_id", 0)) + 1)
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            chat = msg.get("chat") or {}
            if chat.get("type") == "private":
                return int(chat["id"])
    return None


# ---------------------------------------------------------------------------
# Claude Code hooks installer — wires Stop + UserPromptSubmit hooks into
# .claude/settings.json so the agent auto-drains the Telegram inbox at turn
# boundaries.  Pairs with `tether.hooks.inbox_drain` script.
# ---------------------------------------------------------------------------
_TETHER_HOOK_MARKER = "tether.hooks.inbox_drain"


def install_claude_code_hooks(
    project_root: Path | str | None = None,
    *,
    inbox_path: str = "tether_inbox.jsonl",
    consumed_path: str = "tether_inbox.consumed.json",
    settings_filename: str = "settings.json",
) -> Path:
    """Wire Stop + UserPromptSubmit + SessionStart hooks into Claude Code.

    Adds (or replaces) three hooks that run
    `python -m tether.hooks.inbox_drain` to drain unread Telegram
    messages at end-of-turn (Stop), before the next user prompt
    (UserPromptSubmit), and at session start (SessionStart, v0.6.1+).
    The SessionStart entry instructs Claude to spawn a Monitor on
    `tether.hooks.inbox_tail` so messages arriving during idle wake
    the session immediately. Idempotent: re-runs replace any prior
    tether-managed entries (identified by the command substring
    `tether.hooks.inbox_drain`) and preserve unrelated hooks.

    Args:
        project_root: repo root; defaults to CWD. Hooks are written
            relative to `<project_root>/.claude/<settings_filename>`.
        inbox_path: path the daemon writes inbound messages to.
            Relative paths are interpreted at hook-execution time
            against the harness CWD (typically the project root).
        consumed_path: path of the consumed-pointer json (advanced
            by the hook so messages are not double-delivered).
        settings_filename: 'settings.json' for shared, or
            'settings.local.json' for per-machine overrides.

    Returns the path written.
    """
    root = Path(project_root) if project_root else Path.cwd()
    settings_path = root / ".claude" / settings_filename
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    if settings_path.exists():
        raw = settings_path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            raise SystemExit(
                f"could not parse {settings_path}: {e}. "
                "Fix the JSON manually and re-run, or pass a different "
                "settings_filename."
            )
    else:
        data = {}

    if not isinstance(data.get("hooks"), dict):
        data["hooks"] = {}
    hooks_block: dict = data["hooks"]

    py = Path(sys.executable).as_posix()  # forward slashes — bash-friendly
    cmd_template = (
        f'"{py}" -m tether.hooks.inbox_drain '
        f'--event {{event}} '
        f'--inbox "{inbox_path}" '
        f'--consumed "{consumed_path}"'
    )

    for event in ("Stop", "UserPromptSubmit", "SessionStart"):
        existing = hooks_block.get(event, [])
        kept_groups: list[dict] = []
        if isinstance(existing, list):
            for grp in existing:
                if not isinstance(grp, dict):
                    continue
                grp_hooks = grp.get("hooks", [])
                if not isinstance(grp_hooks, list):
                    continue
                kept_hooks = [
                    h for h in grp_hooks
                    if not (
                        isinstance(h, dict)
                        and _TETHER_HOOK_MARKER in str(h.get("command", ""))
                    )
                ]
                if kept_hooks:
                    new_grp = {**grp, "hooks": kept_hooks}
                    kept_groups.append(new_grp)
        kept_groups.append({
            "hooks": [{
                "type": "command",
                "command": cmd_template.format(event=event),
            }]
        })
        hooks_block[event] = kept_groups

    tmp = settings_path.with_suffix(settings_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(settings_path)
    return settings_path


# ---------------------------------------------------------------------------
# Claude Code slash command — `/tether arm` manual fallback for the
# SessionStart-hook-driven Monitor auto-arm.  Pairs with the hooks above.
# ---------------------------------------------------------------------------
_CLAUDE_CODE_COMMAND_TEMPLATE = """\
---
description: Manage tether (Telegram bridge to operator). Subcommand 'arm' starts the idle-wake Monitor.
argument-hint: arm
---

The operator typed `/tether $ARGUMENTS`. Handle the subcommand:

## `arm`

Invoke the `Monitor` tool with these exact parameters (do not modify):

- `command`: `"{python}" -m tether.hooks.inbox_tail --inbox "{inbox_path}"`
- `description`: `tether telegram inbox tail`
- `persistent`: `true`
- `timeout_ms`: `3600000`

This starts a long-running tail of the Telegram inbox JSONL. Each new line becomes a stdout event that wakes the session mid-idle, so operator messages arriving while you're waiting for input reach you in sub-second time.

Before arming, check whether an identical `Monitor` is already running for this session (use `TaskList` if needed). If yes, report the existing task id and skip — do not double-arm. Otherwise, arm and confirm in one short line with the new task id.

## anything else

If `$ARGUMENTS` is empty or not `arm`, list the available subcommand and stop. Currently only `arm` is implemented.
"""


def install_claude_code_command(
    project_root: Path | str | None = None,
    *,
    inbox_path: str = "tether_inbox.jsonl",
) -> Path:
    """Write `.claude/commands/tether.md` for the `/tether` slash command.

    Lets the operator manually arm the idle-wake Monitor with
    `/tether arm` if the v0.6.1+ SessionStart auto-arm misses (e.g.
    Claude treats the directive as informational and waits to be
    reminded).  The command body bakes in the Python interpreter +
    inbox path so Claude's `Monitor` invocation is fully determined.

    Idempotent: the file is owned by tether and re-runs overwrite it.

    Args:
        project_root: repo root; defaults to CWD.
        inbox_path: path the daemon writes inbound messages to. Should
            match whatever was passed to `install_claude_code_hooks`
            (otherwise `/tether arm` will tail a different file than
            the one `Stop`/`UserPromptSubmit` drain).

    Returns the path written.
    """
    root = Path(project_root) if project_root else Path.cwd()
    cmd_path = root / ".claude" / "commands" / "tether.md"
    cmd_path.parent.mkdir(parents=True, exist_ok=True)

    py = Path(sys.executable).as_posix()
    body = _CLAUDE_CODE_COMMAND_TEMPLATE.format(python=py, inbox_path=inbox_path)

    tmp = cmd_path.with_suffix(cmd_path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(cmd_path)
    return cmd_path
