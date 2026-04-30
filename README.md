# tether

> Your AI agent calls you. You can call back.

You walk away from your desk for lunch. Ten minutes later your agent
finishes the build. Or hits a stuck dependency. Or needs a y/n on a
deploy. You don't know any of it — your terminal is on a screen
you're not looking at, the AI's working in silence, and "checking
back" means breaking your real work to remote into the laptop.

That's the gap `tether` closes. Your agent (Claude Code, Cursor,
Cline, Codex, Continue, Zed, or your own Python script) gets a
**two-way Telegram or Slack channel** to your phone. It pings you
when it has news. You can reply with `/status`, `/abort`, free-form
clarifications — anywhere, anytime.

```
[You, on a walk]            [Agent, in your IDE]
     ↑                              ↓
     └──────── Telegram / Slack ────┘
```

Lightweight Python (`requests` is the only runtime dep on 3.11+),
no SaaS, no babysit-daemon. Bring your own bot token; tether handles
the rest.

---

## The headline use case: operate Claude Code from your phone

This is what `tether` was built for. Install the MCP server, point
your Claude Code session at it, and you get a fully bidirectional
mobile interface to your AI coding agent:

```
You (in Telegram, on a walk):
  "What's the status?"
  "Audit https://youtu.be/abc"
  "Run the test suite"
  "Show me the diff for the auth refactor"
  "/abort"

Claude Code (running at your desk, replies via Telegram):
  → Reads your message via tether_poll
  → Acks immediately: "Got it, on it."
  → Does the work (runs tests, edits code, calls other tools)
  → Replies with the result + key details
```

You're not "checking on" Claude. You're *driving* it from your
phone. Code edits, test runs, audits, deploys, research — all
operator-facing work flows through Telegram.

This pattern is field-tested: the entire `tether` repo + its sibling
[`receipts`](https://github.com/axndj1993/receipts) were built over
a 14-hour session where the operator drove Claude Code *exclusively*
from Telegram (laptop closed by hour 6). Every commit, every code
review, every backtest — driven by phone messages, results streamed
back as one-line summaries.

The opinionated [ack-first](#the-opinionated-bit-ack-first-protocol)
protocol makes it actually comfortable instead of just possible.

Setup is two lines in `.claude/mcp.json` — see the [integrations
guide](docs/integrations.md#claude-code).

## Other use cases

**A solo dev running long jobs:** "kick off a 90-min test suite,
walk away, get a Telegram ping when it's green or red — with the
first failing test stack-trace inline if red."

**An ops engineer:** "every deploy step pings the team channel,
operators reply `/abort` from their phones if the canary metrics
look wrong."

**A trader running a live agent:** "trade hits stop, agent texts me
the lifecycle ID + P&L; I can text `/flatten` from my phone to
override."

**Multiple agents on multiple repos:** [profiles](docs/profiles.md)
let one machine run 3 agents talking to 3 separate Telegram chats —
no message collision.

**CI without a SaaS:** `tether send` from a GitHub Actions step is a
one-liner that beats setting up Slack webhooks.

> *Sibling project:* [`receipts`](https://github.com/axndj1993/receipts) —
> turn any YouTube video into an evidence audit. Compose the two:
> operator shares a YouTube URL via Telegram → agent audits with
> receipts → result back via tether. Mobile-driven workflow, ~15
> lines of agent logic.

---

## What problem this solves

Long-running agentic work needs an operator. Today's agent UIs are
desktop-bound: the moment you walk away from your machine, you're
blind to what your agent is doing and have no way to redirect it.
People work around it by either babysitting the terminal (defeating
the point of agents) or checking obsessively (defeating the point of
mobility). Mobile chat solves it: **every operator already has
Telegram or Slack on their phone** — `tether` makes the bridge a
one-line install.

Full motivation, problem framing, features, roadmap in
[**docs/why.md**](docs/why.md).

---

## The opinionated bit: ack-first protocol

When the operator messages the agent, the **first thing the agent
sends back is a one-liner ack** ("Got it, on it"), THEN it does the
work, THEN it sends the result. Sounds trivial; in practice it's
the difference between comfortable async oversight and operator
anxiety. Without an ack, the operator stares at silence wondering
whether the message was even received. The ack closes the loop in
one line.

This convention is baked into the docs and the [Claude Code Skill
template](examples/claude_code_skill.md) — it's part of what makes
`tether` a complete UX answer, not just a Telegram wrapper.

---

## Install

The recommended install is from GitHub — that's where the current
v0.6.x line lives (Claude Code hooks, MCP server, `tether install`
auto-config, `/tether arm` slash command, etc):

```bash
pip install 'tether[all] @ git+https://github.com/axndj1993/tether'
# or scoped:
pip install 'tether[mcp] @ git+https://github.com/axndj1993/tether'   # + MCP server
pip install 'tether[slack] @ git+https://github.com/axndj1993/tether' # + Slack transport
```

> A legacy v0.2 also exists on PyPI under the name `pager-cli`
> (`pip install pager-cli`). It pre-dates the MCP server, Claude Code
> integration, and onboarding wizard — pin to GitHub for current
> features. PyPI rename to `tether` pending namespace availability.

## 60-second start

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather);
   note the token.
2. Send your bot any message; visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your
   `chat.id`.
3. Configure:
   ```bash
   tether init                              # interactive wizard
   # OR
   export TELEGRAM_BOT_TOKEN=...
   export TELEGRAM_CHAT_ID=...
   ```
4. Try it:
   ```bash
   tether send "*hello* from tether"
   tether whoami      # confirms bot connected
   ```
5. Drop into your AI agent host: see the [integrations
   guide](docs/integrations.md) for explicit per-tool setup
   (Claude Code, Cursor, Cline, Codex, Continue.dev, Zed).

## Python

```python
from tether import Tether

t = Tether()                                # auto-resolves profile
t.send("Build started")                      # outbound

for msg in t.listen(poll_timeout=30):        # inbound
    if msg.text == "/status":
        t.send(get_status())
    elif msg.text == "/abort":
        t.send("Aborting.")
        break
    else:
        t.send(f"Got it: {msg.text!r}")      # ack-first
        do_work(msg.text)
        t.send("Done.")
```

That's the entire pattern.

## What's inside

| Layer             | What it does |
|-------------------|---|
| `tether send`     | Outbound: one-line CLI / Python lib for status, alerts, results. |
| `tether daemon`   | Inbound: long-poll forever; append messages to JSONL for at-most-once consumption by the agent. |
| `tether init`     | Interactive setup wizard: walks token + chat-id config, optionally auto-installs into your AI host. |
| `tether install`  | Auto-writes tether's MCP config (and Claude Code hooks + `/tether arm` slash command) into Claude Code / Cursor / Cline / Codex / Continue / Zed. |
| `tether-mcp`      | MCP server: drops `tether_send` / `tether_poll` into Claude Code, Cursor, Cline, Codex, etc. as native tools. |
| `tether profiles` | Multi-bot support: futures-bot pings one channel, code-review pings another. Auto-detected via `.tether` file in CWD. |

Transports: **Telegram** (default), **Slack** (Bot Token + Socket
Mode). Discord / SMS / Signal on the roadmap.

## Documentation

| Page                                    | What's in it |
|-----------------------------------------|---|
| [Why tether](docs/why.md)               | Full motivation + roadmap |
| [Installation](docs/installation.md)    | Bot creation, config, verify |
| [Quickstart](docs/quickstart.md)        | 5-minute walkthrough |
| [API reference](docs/api-reference.md)  | Every Python class/method |
| [CLI reference](docs/cli-reference.md)  | Every subcommand/flag |
| [Integrations](docs/integrations.md)    | Step-by-step for Claude Code, Cursor, Cline, Codex, Continue.dev, Zed |
| [MCP server](docs/mcp.md)               | Drop tether into MCP-aware clients as native tools |
| [Transports](docs/transports.md)        | Slack setup + Transport protocol |
| [Profiles](docs/profiles.md)            | Multiple bots/chats per machine |
| [Recipes](docs/recipes.md)              | Heartbeat, build alerts, Q&A loops, multi-channel fan-out, edit-in-place |
| [Architecture](docs/architecture.md)    | What state lives where, polling model, design choices |
| [Troubleshooting](docs/troubleshooting.md) | Common failure modes |

## License

MIT.
