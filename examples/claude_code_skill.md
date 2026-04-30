---
name: tether-comms
description: Use whenever the operator may step away from the terminal — emit status updates and accept commands via Telegram. Sends a one-line ack BEFORE any new operator message's work begins.
---

# tether-comms skill

When this skill is active, Claude treats the operator's Telegram channel
(via the `tether` CLI) as a first-class output surface alongside the
terminal.

## Setup (one-time)

1. `pip install tether`
2. `tether init` — interactive wizard. Sets `~/.tether/config.toml`.
3. Verify: `tether send "claude code skill loaded"`

## Rules Claude must follow

### 1. Ack-first on inbound messages — *Telegram inbound only*

When a new operator message lands in `tether_inbox.jsonl` (i.e. the
operator messaged the agent via Telegram / Slack), the **first
action** in Claude's response is a one-line ack:

```bash
tether send "Got it. Running X now."
```

Then do the work. Then send the result.

**Why:** the operator can't see Claude's terminal spinner. Without an
explicit ack, they don't know if the message was received or if Claude
is already working. The ack eliminates that ambiguity in one line.

**Important — channel-routing rule.** This protocol applies *only* to
messages received via `tether_poll` / the inbox JSONL. **If the
operator types directly in the terminal where Claude is running, reply
in the terminal — do NOT send a Telegram ack for terminal messages.**
Cross-piping the channels phone-buzzes the operator for messages they
typed at their desk, and splits the conversation across two surfaces
that no longer line up. Rule of thumb: **reply on the channel the
message arrived from.**

### 2. Dual-deliver important findings

For trade-relevant findings, completion notices, blockers, risk-state
changes, and incidents — emit BOTH to the terminal (full detail) AND to
Telegram (one-line summary). The terminal is the source of truth; the
phone is the notification surface.

### 3. Send proactively at meaningful state changes

Don't wait to be asked. Send when:
- A long-running command starts / finishes
- A test suite turns green / red
- An error or anomaly is detected
- A binary decision is needed from the operator

### 4. Don't ask permission for routine sends

Sending a Telegram update is not a "shared system" change — it's
notification. Money-spending and admin-control actions still require
operator confirmation; everything else is just a message.

## Suggested launcher pattern (v0.6.1+)

Two pieces are needed for a fully two-way Claude session:

1. **A daemon writing the inbox JSONL.** For projects that don't
   already have one, run `tether daemon --inbox ./tether_inbox.jsonl`
   in a background terminal. Many host projects (e.g. futures-bot)
   ship their own daemon and write to a project-specific path; in
   that case use theirs and pass `tether install claude-code
   --inbox-path <path>` so the hooks read from the same file.

2. **The Monitor tool tailing that JSONL inside Claude Code.** This
   is what wakes Claude mid-idle. As of v0.6.1+, `tether install
   claude-code` writes a `SessionStart` hook that tells Claude to
   invoke `Monitor` automatically on every new session — no manual
   launch needed.

   If auto-arm misses (Telegram messages sent during idle don't reach
   Claude until you next type), use the slash command:

   ```
   /tether arm
   ```

   v0.6.3+ ships this command — `tether install claude-code` writes
   `.claude/commands/tether.md` with the Monitor params (Python
   interpreter + inbox path) baked in. The canonical reference
   (including how to pick the right Python interpreter on Windows vs
   POSIX) is in [docs/integrations.md → Claude Code → Idle-wake
   Monitor](../docs/integrations.md#idle-wake-monitor-v061--auto-arm--manual-fallback).

The other two hooks (`Stop`, `UserPromptSubmit`) handle inbox draining
at turn boundaries — written by the same `tether install` command, no
extra wiring needed.
