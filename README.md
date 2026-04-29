# tether

> Bidirectional comms for AI agents. Your agent calls you. You can call back.

`tether` is a tiny Python package + CLI + MCP server that gives any AI agent
— Claude Code, the Anthropic Agent SDK, Cursor / Cline / Codex plugins, or
your own Python script — a **two-way** chat channel to its operator. Outbound:
send status, alerts, results. Inbound: receive `/status`, `/abort`, free-form
clarifications, course corrections from anywhere.

**Transports:**
- *Telegram* — default (v0.1+)
- *Slack* — added in v0.3 (Bot Token + Socket Mode)
- *Discord, SMS, Signal* — on the roadmap

**Integrations:**
- Plain Python lib (`from tether import Tether`)
- CLI (`tether send`, `tether daemon`, ...)
- MCP server — `tether-mcp` (drop into Claude Code / Cursor / Cline / Codex)

It's deliberately small (~500 LOC for Telegram, ~200 for Slack), and
copy-pasteable. No SaaS, no broker, no daemon you have to babysit. Bring
your own bot token; tether handles the rest.

## Why this exists

> Today's meta-challenge: AI agents do real autonomous work now, but
> the operator UX is desktop-bound. The moment you walk away from your
> machine, you're blind to what your agents are doing and have no way
> to redirect them. People work around it by either babysitting the
> terminal (defeating the point) or checking obsessively (defeating
> the point AND pulling them out of everything else).
>
> Mobile chat solves that. **Every operator already has Telegram or
> Slack on their phone.** `tether` makes the bridge a one-line
> install.

Full motivation, problem framing, features, and roadmap in
[**docs/why.md**](docs/why.md).

> *Sibling project:* [`receipts`](https://github.com/axndj1993/receipts) —
> turn any YouTube video into an evidence audit. Compose the two for
> mobile-driven agent workflows that audit the content the operator
> shares.

The opinionated bit: `tether` ships with an explicit "ack-first"
convention in the docs. When the operator messages the agent, the
**first thing the agent sends back is a one-liner ack** ("Got it, on
it"), THEN it does the work. Sounds trivial; it eliminates the
"is the AI even reading this?" anxiety that kills async oversight in
practice.

## Install

```bash
pip install tether
```

Or, from this repo:

```bash
pip install -e .
```

## Quickstart (5 minutes)

1. **Create a Telegram bot.** Open Telegram, message `@BotFather`, run
   `/newbot`, follow the prompts. You'll get a token like
   `1234567890:AA...`.
2. **Find your chat id.** Send the bot any message from your account,
   then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` — look for
   `"chat":{"id":<NUMBER>,...}`. Copy the number.
3. **Configure tether.** Two options:

   ```bash
   # Option A — env vars (good for shell scripts / CI)
   export TELEGRAM_BOT_TOKEN=1234567890:AA...
   export TELEGRAM_CHAT_ID=987654321

   # Option B — interactive wizard, writes ~/.tether/config.toml (chmod 600)
   tether init
   ```

4. **Try it.**

   ```bash
   tether send "hello from tether"
   tether whoami     # verifies token by calling getMe
   ```

## CLI usage

```bash
tether send "Build started"           # one-liner outbound
tether send "*Bold* and _italic_"      # MarkdownV1 by default
tether send "raw" --parse-mode none    # plain text

tether daemon --inbox ./inbox.jsonl    # long-poll forever, append each
                                       # inbound msg to inbox.jsonl
tether drain  --inbox ./inbox.jsonl    # print unread, advance pointer
                                       # (pairs with daemon for at-most-once)
```

## Python usage

```python
from tether import Tether

p = Tether()                            # reads env vars or ~/.tether/config.toml
p.send("starting long task")

# Long-poll, react to commands
for msg in p.listen(poll_timeout=30):
    if msg.text == "/status":
        p.send(get_status())
    elif msg.text == "/abort":
        p.send("Aborting now.")
        break
    else:
        p.send("Got it, on it.")        # ack-first
        do_the_thing(msg.text)
        p.send("Done.")
```

## Use as a Claude Code Skill

`tether` is designed to drop straight into Claude Code as a Skill.

```markdown
---
name: tether-comms
description: Use whenever the operator may step away from the terminal — emit status updates and accept commands via Telegram. Send a one-line ack BEFORE any new operator message's work begins.
---

# Skill rules

1. On any inbound operator message, immediately send a one-line ack via
   `tether send "<ack>"` BEFORE starting the requested work.
2. After completing the work, send the result.
3. For long-running tasks, send a status update every ~5-10 minutes or
   on each meaningful state change (build done, test failure, etc).
4. For binary decisions that need operator input, send the question +
   wait via `tether drain` until they answer.
```

Then in Claude Code: launch a Monitor on `tether_inbox.jsonl` so each new
operator message wakes Claude near-realtime.

## Architecture

```
┌─────────────────┐    long-poll    ┌──────────────────┐
│ tether.client    │  ─────────────► │ Telegram Bot API │
│  - send()       │  ◄─────────────  │                  │
│  - poll_once()  │    sendMessage  └──────────────────┘
│  - listen()     │
└────────┬────────┘
         │  offset persisted via tmp+rename
         ▼
   ~/.tether/offset.json
```

- **State**: `~/.tether/offset.json` (next-update pointer, atomic write).
- **Config resolution**: ctor arg → env var → `~/.tether/config.toml`.
- **Errors**: `TetherError` (transport/API), `ConfigError` (missing creds).

## Testing

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT.
