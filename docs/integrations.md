# Integrations

Setup instructions for the major AI agent hosts. All of them speak
MCP, so the recipe is the same: install `tether` with the `mcp`
extra, drop a small JSON block into the host's MCP config, point
`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (or `TETHER_PROFILE`) at
your bot. Restart the session. Done.

> **Prerequisite for all of them:** `pip install 'tether[mcp]'` in
> the same Python environment the host launches subprocesses from.
> Verify `tether-mcp` is on `PATH`: `which tether-mcp` (POSIX) /
> `where tether-mcp` (Windows).

## Claude Code

**Config file:** `.claude/mcp.json` (per project) or
`~/.claude/mcp.json` (global).

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

For multi-project workflows, use [profiles](profiles.md) instead of
inline credentials:

```json
{
  "mcpServers": {
    "tether": {
      "command": "tether-mcp",
      "env": { "TETHER_PROFILE": "futures-bot" }
    }
  }
}
```

Restart the Claude Code session. Run `/mcp` — you should see
`tether` listed with three tools (`tether_send`, `tether_poll`,
`tether_whoami`).

**Optional but recommended:** also drop a Skill that codifies the
ack-first protocol:

```bash
mkdir -p .claude/skills
curl -L https://raw.githubusercontent.com/axndj1993/tether/main/examples/claude_code_skill.md \
     -o .claude/skills/tether-comms.md
```

Now whenever Claude is doing operator-facing work, it'll proactively
emit status updates via `tether_send` and ack inbound messages
before working.

### Idle-wake Monitor (v0.6.1+) — auto-arm + manual fallback

`tether install claude-code` writes a `SessionStart` hook that tells
Claude to invoke its `Monitor` tool on a background tail of your inbox
JSONL. While the Monitor is armed, every Telegram message lights up
mid-idle as a stdout event — sub-second wake, even when Claude is just
sitting waiting for you to type.

> **The hook delivers a directive; Claude executes it.** A shell hook
> cannot call the `Monitor` tool — only the Claude session can. v0.6.2
> hardens the directive wording to `MANDATORY FIRST ACTION`, which
> makes auto-arm reliable in practice, but if Claude ever skips it
> (i.e. you message during idle and get no response until you type),
> use the slash command:
>
> ```
> /tether arm
> ```
>
> v0.6.3+ ships this command — `tether install claude-code` writes
> `.claude/commands/tether.md` with the exact `Monitor` params (Python
> interpreter path + inbox path) baked in at install time. The
> command body tells Claude to dedup against any already-running
> Monitor before re-arming.

The parameters Claude should pass to its `Monitor` tool:

| Field         | Value                                                                       |
|---------------|-----------------------------------------------------------------------------|
| `command`     | `<python> -m tether.hooks.inbox_tail --inbox "<inbox-path>"`                |
| `description` | `tether telegram inbox tail`                                                |
| `persistent`  | `true`                                                                      |
| `timeout_ms`  | `3600000` (ignored when `persistent: true`; harness requires the field)     |

- `<python>` — the interpreter that has `tether` importable (same one
  `tether-mcp` runs under). Windows: typically
  `C:/Users/<you>/AppData/Local/Programs/Python/Python3xx/python.exe`.
  POSIX: absolute path from `which python` or your venv.
- `<inbox-path>` — the JSONL your inbox daemon writes to. Defaults to
  `./tether_inbox.jsonl`; projects with their own daemon set it
  explicitly (e.g. `state/telegram_inbox.jsonl` in futures-bot). Match
  whatever you passed to `tether install claude-code --inbox-path ...`.

**Verify the Monitor is armed.** Ask Claude *"is the tether Monitor
running?"* — Claude Code tracks each `Monitor` invocation by task id
(e.g. `brc1jitnm`) and will report whether one is active for the
inbox tail.

**Cold start is still a gap.** If you message the bot while no Claude
session is running, the message sits in the inbox until you start
`claude` next — at which point `UserPromptSubmit` drains it on your
first prompt and `SessionStart` re-arms the Monitor for the new
session's idle window. True 24/7 wake requires the v0.7 cold-start
daemon — see [ROADMAP](ROADMAP.md).

## Cursor

**Config file:** `~/.cursor/mcp.json` (global) or
`.cursor/mcp.json` (per project, Cursor 0.42+).

Same JSON shape as Claude Code:

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

Restart Cursor. Open the chat sidebar → Settings cog → MCP — you
should see `tether` with green status. The three tools are now
available to the Composer's tool-calling loop.

## Cline (VS Code extension)

Cline doesn't read a JSON file directly — its MCP config lives in
VS Code's settings UI:

1. Open the Cline sidebar (icon in the activity bar).
2. Click the gear icon → **MCP Servers**.
3. Click **Add new MCP Server**.
4. Fill in:
   - **Name:** `tether`
   - **Command:** `tether-mcp`
   - **Environment variables:** `TELEGRAM_BOT_TOKEN=...`,
     `TELEGRAM_CHAT_ID=...` (one per line)
5. Save. Restart the Cline session.

Verify with `Use the MCP tool tether_whoami` — Cline will call it
and surface the bot's username.

## Codex CLI (OpenAI)

**Config file:** `~/.codex/mcp.json`. Same shape as Claude Code:

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

Restart `codex`. The MCP tools are auto-loaded — `tether_send` etc.
appear in the tool palette.

## Continue.dev

**Config file:** `~/.continue/config.yaml` (or `.continue/config.yaml`
per project).

Add under `mcpServers`:

```yaml
mcpServers:
  - name: tether
    command: tether-mcp
    env:
      TELEGRAM_BOT_TOKEN: "1234567890:AAH...xyz"
      TELEGRAM_CHAT_ID: "987654321"
```

Reload the Continue extension (VS Code: Ctrl/Cmd+Shift+P →
"Continue: Reload Window"). Tools appear under the Continue chat's
tool drawer.

## Zed

**Config:** open Zed Settings (`Cmd/Ctrl ,`) and add to
`assistant.mcp_servers`:

```jsonc
{
  "assistant": {
    "mcp_servers": {
      "tether": {
        "command": "tether-mcp",
        "env": {
          "TELEGRAM_BOT_TOKEN": "1234567890:AAH...xyz",
          "TELEGRAM_CHAT_ID": "987654321"
        }
      }
    }
  }
}
```

Restart the Assistant panel. Zed shows MCP tools with a small icon
next to the chat input.

## Anthropic SDK / Agent SDK (no MCP host)

If you're building an agent loop yourself with the Anthropic SDK or
the Agent SDK, wire tether as a regular tool instead of via MCP:

```python
import anthropic
from tether import Tether

p = Tether()    # auto-resolves profile
client = anthropic.Anthropic()

tools = [
    {
        "name": "tether_send",
        "description": (
            "Send a one-line update to the operator's Telegram. Use "
            "after any meaningful state change (build done, test "
            "failed, etc.) or to ack an inbound message before "
            "starting work on it. Markdown: asterisks=bold, "
            "underscores=italic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text":   {"type": "string"},
                "silent": {"type": "boolean"},
            },
            "required": ["text"],
        },
    },
]

def call_tool(name: str, input: dict) -> str:
    if name == "tether_send":
        p.send(input["text"], silent=input.get("silent", False))
        return "sent"
    raise ValueError(f"unknown tool {name}")
```

For inbound, expose a `tether_poll` tool that calls
`p.poll_once(timeout=...)` and returns the messages.

## Plain Python script (no AI host at all)

The simplest case — a long-running script that reports milestones
and listens for `/status` / `/abort`:

```python
from tether import Tether

p = Tether()
p.send("Job started.")
try:
    for msg in p.listen(poll_timeout=30):
        text = msg.text.strip()
        if text == "/status":
            p.send(f"Phase {phase}, ETA {eta}m.")
        elif text == "/abort":
            p.send("Aborting.")
            break
        else:
            p.send(f"Ack: {text}")
            handle(text)
except KeyboardInterrupt:
    p.send("Interrupted by signal.")
finally:
    p.send("Job ended.")
```

The same shape works in `examples/quickstart.py` — ~25-line
async-oversight pattern.

## CI / cron sidecar (no AI required)

`tether` is just a notifier with a Python wrapper. Use it from any
shell script:

```bash
# In a CI step:
tether send "Deploy started: ${COMMIT_SHA:0:8}"
./deploy.sh && tether send "✅ Deploy OK" || tether send "❌ Deploy FAILED"

# In a cron job:
0 8 * * * /opt/scripts/morning_report.sh | head -c 4000 | xargs -I{} tether send "{}"
```

## Multi-agent / multi-chat

Use [profiles](profiles.md) for clean isolation:

```bash
# Per-project: project-A pings bot-A's chat
cd ~/repos/project-a
tether profiles use bot-a

# Per-project: project-B pings bot-B's chat
cd ~/repos/project-b
tether profiles use bot-b
```

Each project's MCP config can pin a profile via `TETHER_PROFILE`.

## Bot security tips

- **Never commit the token.** Treat it like a password. Use env
  vars or `~/.tether/profiles/<name>/config.toml` (the `init`
  wizard chmods it `600`).
- **Lock the bot to your chat id.** Telegram bots can be DM'd by
  anyone who knows the username. Either:
  - Have the agent ignore messages where
    `msg.chat_id != self.chat_id`.
  - Add a passphrase: ignore messages until the operator sends
    `unlock <SECRET>`.
- **Rotate** if the token leaks: BotFather → `/revoke` → set new
  token.
