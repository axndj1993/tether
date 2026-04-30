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
    cwd_local = Path.cwd() / ".claude" / "mcp.json"
    paths.append(cwd_local)
    paths.append(Path.home() / ".claude" / "mcp.json")
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
