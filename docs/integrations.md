# Integrations

Three patterns for plugging `tether` into AI agents.

## Pattern 1 — Claude Code Skill

Drop `examples/claude_code_skill.md` into your project's `.claude/skills/`
folder (or `~/.claude/skills/` for global). The skill activates whenever
Claude is doing work that an operator might want to monitor remotely.

The skill enforces:

- **Ack-first** on inbound messages
- **Dual-deliver** important findings (terminal full + Telegram one-liner)
- **Proactive sends** at meaningful state changes
- **No permission needed** for routine sends (only for money/admin actions)

Pair with two background processes at session start:

```bash
# 1. Long-poll daemon: appends each inbound msg to JSONL
tether daemon --inbox ./tether_inbox.jsonl &

# 2. Tail-monitor (Claude Code's Monitor tool): notifies Claude per-line
tail -F ./tether_inbox.jsonl
```

When a new line lands, Claude:
1. Acks via `tether send "Got it..."`
2. Drains the consumed pointer (`tether drain --inbox ./tether_inbox.jsonl`)
3. Does the work
4. Sends the result

## Pattern 2 — Anthropic SDK / Agent SDK

Wire tether into a `@tool` so Claude can call it directly.

```python
import anthropic
from tether import Tether

p = Tether()
client = anthropic.Anthropic()

tools = [
    {
        "name": "telegram_send",
        "description": "Send a one-line update to the operator via Telegram. "
                       "Use after any meaningful state change (build done, "
                       "test failed, etc.) or to ack an inbound message before "
                       "starting work on it. Markdown supported (asterisks for "
                       "bold).",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "message body"},
                "silent": {"type": "boolean", "description": "no notification sound"},
            },
            "required": ["text"],
        },
    },
]

def call_tool(name, input):
    if name == "telegram_send":
        p.send(input["text"], silent=input.get("silent", False))
        return "sent"
    raise ValueError(f"unknown tool {name}")

# ... rest of the agent loop ...
```

For inbound, expose a `telegram_check` tool that calls `p.poll_once()`
and returns any new messages, OR run `tether daemon` separately and have
Claude read the inbox file.

## Pattern 3 — Plain Python script

The simplest case: a long-running script that reports milestones and
listens for `/status` / `/abort`.

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

This is the same shape as `examples/quickstart.py` — a 25-line
async-oversight pattern.

## Pattern 4 — As a notifier sidecar (no AI required)

`tether` is also useful for plain CI / cron jobs. It's a tiny notifier:

```bash
# In a CI step:
tether send "Deploy started: ${COMMIT_SHA:0:8}"
./deploy.sh && tether send "✅ Deploy OK" || tether send "❌ Deploy FAILED"

# In a cron job:
0 8 * * * /opt/scripts/morning_report.sh | head -c 4000 | xargs -I{} tether send "{}"
```

## Multi-agent / multi-chat

For multiple agents sharing one bot but talking to different operators
(or one operator with multiple "channels"):

```python
agent_a = Tether(chat_id=111111111)   # operator 1
agent_b = Tether(chat_id=222222222)   # operator 2 (or same op, different topic)
```

Each call to `send()` accepts `chat_id=` to override per-message:

```python
p = Tether()                           # default chat
p.send("alpha update", chat_id=111)
p.send("beta update", chat_id=222)
```

## Bot security tips

- **Never commit the token.** Treat it like a password. Use env vars or
  `~/.tether/config.toml` (the `init` wizard chmods it `600`).
- **Lock the bot to your chat id.** Telegram bots can be DM'd by anyone
  who knows the username. Either:
  - Have the agent ignore messages where `msg.chat_id != self.chat_id`.
  - Add a passphrase: ignore messages until the operator sends
    `unlock <SECRET>`.
- **Rotate** if the token leaks: BotFather → `/revoke` → set new token.
