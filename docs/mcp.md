# MCP server

`tether` ships an MCP (Model Context Protocol) server that exposes the
Tether client as native tools to any MCP-aware AI client — Claude Code,
Cursor, Cline, Codex, etc.

## Why MCP?

Without MCP: every agent that wants to use Tether has to write Python
glue (a tool wrapper, a CLI subprocess, etc).

With MCP: the agent's host (Claude Code, Cursor, ...) handles the
protocol; the agent sees `tether_send` / `tether_poll` as first-class
tools alongside its built-ins.

## Install

```bash
pip install 'tether[mcp]'      # adds the `mcp` package as a dep
```

This installs an additional console script: `tether-mcp`.

## Configure Claude Code

Edit `.claude/mcp.json` in your project (or `~/.claude/mcp.json` for
global):

```json
{
  "mcpServers": {
    "tether": {
      "command": "tether-mcp",
      "env": {
        "TELEGRAM_BOT_TOKEN": "1234567890:AAH...xyz",
        "TELEGRAM_CHAT_ID": "987654321"
      }
    }
  }
}
```

Restart the Claude Code session. Verify by running `/mcp` — you should
see `tether` listed with three tools.

## Configure Cursor / Cline / other MCP clients

The format is the same. Each client docs section will tell you where
its `mcp.json` lives:

- **Cursor** — `~/.cursor/mcp.json`
- **Cline** — VS Code settings → Cline → MCP Servers
- **Codex** — `~/.codex/mcp.json`

The `command` and `env` keys are universal.

## Tools exposed

### `tether_send(text: str, silent: bool = False) -> str`

Send a one-line message to the operator's Telegram. Returns a
confirmation string with the message id.

```
> tether_send(text="Build started", silent=False)
"sent (message_id=123)"
```

### `tether_poll(timeout_seconds: int = 0) -> str`

Fetch any pending operator messages. Returns JSON-encoded list
(possibly empty). `timeout_seconds=0` polls immediately;
`timeout_seconds=30` waits up to 30 seconds for a message before
returning (use this for blocking wait-for-input loops).

```
> tether_poll(timeout_seconds=0)
[
  {
    "update_id": 1234,
    "text": "/status",
    "from_user": "Gautam",
    "chat_id": 99,
    "received_at_utc": "2026-04-29T15:48:22+00:00",
    "edited": false
  }
]
```

### `tether_whoami() -> str`

Verify config by calling Telegram getMe. Useful diagnostic at session
start.

## The ack-first protocol via MCP

Strongly recommended pattern when the agent has the Tether MCP server
available:

1. After every `tether_poll` that returns a non-empty list, the agent's
   FIRST action MUST be `tether_send` with a one-line ack — BEFORE any
   other tool call.
2. Then the agent does the requested work.
3. Then `tether_send` with the result.

Example agent flow (pseudocode):

```
loop:
    msgs = tether_poll(timeout_seconds=30)
    for msg in msgs:
        tether_send(text=f"Got it: {msg.text}")     # ack
        result = handle(msg.text)                    # work
        tether_send(text=f"Done: {result}")          # report
```

This is the same convention as the [Skill template](../examples/claude_code_skill.md);
it just happens via MCP tools instead of CLI subprocess.

## Bidirectional usage with the daemon

Some patterns (e.g. running the daemon to log all inbound to a JSONL
file for later replay) use both the MCP server AND the daemon at the
same time. They're independent: the daemon polls + writes to a file;
the MCP server polls + returns to the calling agent. Both share the
same `~/.tether/offset.json` persisted offset, so a poll from one
advances the other's view too.

If you only need MCP-style tool access (no file logging), skip the
daemon — `tether_poll` is enough.

## Troubleshooting

### "tether is not configured" returned from any tool

The MCP host didn't pass `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` env
vars to the server. Check your `mcp.json` `env:` block.

Alternatively, configure once via `tether init` (writes
`~/.tether/config.toml`); the MCP server will pick it up without any
env vars in the host config.

### MCP server doesn't appear in /mcp listing

Check the `command` value resolves on PATH. If you installed in a
virtualenv, the host needs to be told the venv's Python — usually with
a fully-qualified path:

```json
"command": "/Users/you/.venvs/agents/bin/tether-mcp"
```

### `mcp` import error at server start

You installed `tether` without the `mcp` extra. Run:

```bash
pip install 'tether[mcp]'
```

## Reference: full session example

```
User: "Run the test suite, ping me when it's done."

Claude (with tether MCP):
  → bash run "pytest"
  ← (3 minutes later) all 487 tests passed
  → tether_send(text="✅ test suite green — 487/487 in 3m02s")
  ← "sent (message_id=1234)"
```

The user gets the ping on their phone. They reply:

```
User (Telegram): "/status"
```

Claude (some seconds later, polling):

```
  → tether_poll(timeout_seconds=30)
  ← [{"text": "/status", ...}]
  → tether_send(text="Got it. Currently idle, last task: tests green.")
```

The whole loop is ~10 lines of agent code, zero glue, all native MCP.
