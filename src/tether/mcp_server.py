"""tether MCP server — exposes the Tether client as MCP tools.

Run via:
    tether-mcp

Configure in any MCP-aware client (Claude Code, Cursor, Cline, Codex):

    {
      "mcpServers": {
        "tether": {
          "command": "tether-mcp",
          "env": {
            "TELEGRAM_BOT_TOKEN": "...",
            "TELEGRAM_CHAT_ID": "..."
          }
        }
      }
    }

The agent can then call `tether_send` to push status updates to the
operator's phone, and `tether_poll` to fetch any pending operator
messages — without any glue code.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "tether MCP server requires the 'mcp' package. "
        "Install with: pip install 'tether[mcp]'"
    ) from e

from .client import ConfigError, Tether, TetherError


_mcp = FastMCP("tether")
_pager: Tether | None = None


def _get_pager() -> Tether:
    """Lazy-init: don't raise ConfigError at import time so the MCP
    client can probe the server with --help-style requests."""
    global _pager
    if _pager is None:
        _pager = Tether()
    return _pager


@_mcp.tool()
def tether_send(text: str, silent: bool = False) -> str:
    """Send a one-line message to the operator's Telegram.

    Use this whenever the agent has something the operator should know:
    - A status update for a long-running task
    - A finding or result
    - A blocker / question that needs operator input
    - An ack of an inbound operator message (always send this BEFORE
      starting the requested work — see the tether ack-first protocol)

    Args:
        text: message body. Markdown supported (asterisks for bold,
            underscores for italic).
        silent: send without notification sound on the operator's phone.

    Returns: a confirmation string with the Telegram message_id.
    """
    try:
        result = _get_pager().send(text, silent=silent)
        return f"sent (message_id={result.get('message_id')})"
    except ConfigError as e:
        return f"ERROR: tether is not configured. {e}"
    except TetherError as e:
        return f"ERROR: {e}"


@_mcp.tool()
def tether_poll(timeout_seconds: int = 0) -> str:
    """Fetch any pending messages from the operator. JSON-encoded list.

    Use this when:
    - The agent is at a decision point and wants to see if the operator
      has sent guidance.
    - The agent wants to drain the inbox before reporting status (so
      the operator's most recent input is incorporated).

    Args:
        timeout_seconds: long-poll seconds. 0 = immediate return (no
            wait). 30 = wait up to 30 seconds for a message before
            returning. Use 0 for opportunistic polling, 30+ for
            blocking wait-for-input loops.

    Returns: JSON-encoded list of objects with keys
        {update_id, text, from_user, chat_id, received_at_utc, edited}.
        Empty list if no pending messages.
    """
    try:
        msgs = _get_pager().poll_once(timeout=timeout_seconds)
        out = [
            {
                "update_id": m.update_id,
                "text": m.text,
                "from_user": m.from_user,
                "chat_id": m.chat_id,
                "received_at_utc": m.received_at_utc,
                "edited": m.edited,
            }
            for m in msgs
        ]
        return json.dumps(out, indent=2)
    except ConfigError as e:
        return json.dumps({"error": f"tether is not configured. {e}"})
    except TetherError as e:
        return json.dumps({"error": str(e)})


@_mcp.tool()
def tether_whoami() -> str:
    """Verify tether config by calling Telegram getMe.

    Useful diagnostic — call this once at session start to confirm the
    bot token + chat id resolve correctly. Returns the bot's profile
    JSON or an error.
    """
    try:
        info = _get_pager().whoami()
        return json.dumps(info, indent=2)
    except ConfigError as e:
        return f"ERROR: tether is not configured. {e}"
    except TetherError as e:
        return f"ERROR: {e}"


def main() -> None:
    """Entry point — runs the MCP server over stdio."""
    _mcp.run()


if __name__ == "__main__":
    main()
