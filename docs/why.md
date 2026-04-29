# Why tether exists

## Today's meta-challenge: the agent firehose

AI agents do real autonomous work now — research, deployments,
monitoring, multi-hour reasoning loops, multi-step coding tasks. But
the operator UX is desktop-bound: Claude Code, Cursor, Cline, Codex,
the terminal. The moment you walk away from your machine, you're blind
to what your agents are doing and have no way to redirect them.

People work around it by either:

- **Babysitting the terminal** — defeating the point of having an agent
  that can run autonomously, OR
- **Checking back obsessively** — defeating the point of mobility, AND
  pulling you out of whatever else you were doing every few minutes.

Neither is actually working. The "AI agent" abstraction promised
*delegation* — the ability to hand off a complex task and trust it to
run. We don't have the operator-side primitives that make delegation
comfortable, so most operators end up watching agents work like
nervous parents.

That's the problem `tether` solves.

## What tether does

Tether is a tiny Python package + CLI + MCP server that gives any AI
agent a **two-way chat channel** to its operator, carried over the
universally-installed-on-everyone's-phone messaging apps.

**Outbound** (agent → operator):
- Status updates ("starting test suite", "build green", "deploy done")
- Blockers ("API quota hit, need new key")
- Completion alerts ("task done, here's the diff")
- Anomalies ("unexpected error in step 3, here's the traceback")

**Inbound** (operator → agent):
- Slash commands (`/status`, `/abort`, `/diff`, anything you define)
- Free-form clarifications ("the auth code goes in `auth.py` not `app.py`")
- Course corrections ("skip step 4, do step 5 first")
- Approvals ("ok deploy")

Both flow over the same channel — your phone's messaging app of
choice.

## The opinionated bit: ack-first protocol

Tether ships with one piece of opinionated UX baked into the docs:
**when the operator sends a message, the agent's first action MUST be a
one-line ack — BEFORE doing the requested work.**

```bash
pager send "Got it, on it."        # ack
# then: do the actual work
pager send "Done: <result>"        # report
```

This sounds trivial. In practice it's the difference between
comfortable async oversight and operator anxiety. Without an ack, the
operator stares at silence wondering whether the message was even
received. The ack closes the loop in one line.

This convention emerged from real use building a multi-strategy
trading bot with Claude Code as the operator-side AI. It's now
documented in the [Skill template](../examples/claude_code_skill.md)
and the [MCP server docs](mcp.md).

## Features

- **Multi-transport from day 1.** Telegram (default), Slack (v0.3),
  Discord/SMS/Signal on the roadmap. Same Python interface, swap one
  config line.

- **Three integration paths:**
  - **Python library** — `from tether import Tether; t = Tether(); t.send("hi")`
  - **CLI** — `tether send`, `tether daemon`, `tether drain`, `tether init`
  - **MCP server** — `tether-mcp` drops into Claude Code / Cursor /
    Cline / Codex as native tools (`tether_send`, `tether_poll`,
    `tether_whoami`).

- **Bring-your-own-bot.** No SaaS, no broker, no babysit-daemon. Your
  data stays in your Telegram/Slack/etc chats.

- **Atomic offset persistence.** Polling resumes across restarts; the
  offset file uses tmp+rename so a crash mid-write can't corrupt
  state.

- **Resilient long-poll.** `listen()` retries transient API failures
  automatically (5s backoff). Operator's message latency stays
  bounded.

## What tether solves

- **Async oversight without anxiety.** Run agents at lunch / on a
  walk / traveling. The agent calls when it matters; you can interrupt
  anytime.

- **Multi-agent fan-in.** Five agents (data pipeline, code reviewer,
  log monitor, deploy orchestrator, research bot) → one operator
  inbox. Each agent identifies itself in the ack.

- **Operator handoff.** Different shifts share the same channel.
  Day-shift sees yesterday's history when they wake up.

- **CI / cron sidecar.** Not even AI-specific — `pager send` from a
  build script gives you mobile-aware DevOps without a SaaS bill.

## Composition with `receipts`

Tether's sibling project is [`receipts`](https://github.com/axndj1993/receipts)
— turn any YouTube video into an evidence audit. They share the
philosophy: extract the *primitive* you need, ship it tiny, let users
compose.

Together: your agent receives a YouTube URL via tether (operator on
phone), audits it via receipts, sends the verdict back via tether.
Two MCP servers, ~15 lines of agent logic, mobile-driven workflow
end-to-end.

## What tether is NOT

- **Not a Telegram bot framework.** It's a primitive — outbound +
  inbound + ack-first. If you want a full bot framework with
  conversational state machines, plugin systems, and database
  integrations, look at python-telegram-bot or aiogram.

- **Not an AI-agent framework.** It's a *channel* that AI agents can
  use. Bring your own agent.

- **Not a hosted service.** No SaaS, no central broker. The whole
  thing runs in your process with one HTTP dependency (Telegram or
  Slack API). You can audit ~600 LOC.

## Roadmap

- **v0.1** — Telegram, Python lib, CLI ✓
- **v0.2** — MCP server ✓
- **v0.3** — Slack transport, Transport protocol ✓
- **v0.4** *(planned)* — Discord transport, opinionated patterns
  (interrupt-driven, schedule-driven, condition-driven sends) as
  built-in primitives
- **v0.5** *(planned)* — SMS via Twilio, Signal via signal-cli
- **v1.0** *(planned)* — optional SaaS layer for users who don't want
  to manage bot tokens themselves: session-scoped channels, multi-
  agent orchestration, end-to-end encryption.

The Telegram/Slack bridges are the pragmatic v0.x transports. The
*protocol* (ack-first, dual-deliver important findings, proactive
sends at meaningful state changes) is the lasting value.
