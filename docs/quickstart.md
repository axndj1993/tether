# Quickstart — five minutes to a two-way bot loop

This walks through a working tether loop end-to-end: outbound, inbound,
and the ack-first convention that makes async oversight tolerable.

Prereq: completed [installation](installation.md) (tether installed +
config in place).

## 1. Outbound — your first message

```bash
tether send "Build started"
```

Your phone buzzes. Done. Try the markdown:

```bash
tether send "*Done.* P&L = +\$321.45"
```

The asterisks render as bold (Telegram MarkdownV1 by default). Pass
`--parse-mode none` to send raw text.

## 2. Inbound — listen for one message

In one terminal:

```bash
tether daemon --inbox ./inbox.jsonl
```

This long-polls Telegram. Every message you send to your bot gets
appended to `inbox.jsonl` as one JSON object per line, AND printed to
stdout.

In another terminal, on your phone, send the bot `hello world`. The
daemon prints:

```
{"update_id": 1234, "chat_id": 99, "from_user": "Gautam", "text": "hello world", ...}
```

`Ctrl-C` stops the daemon.

## 3. Inbound — drain pattern

For "at-most-once" inbox consumption (don't re-process the same message
on restart):

```bash
# In one terminal:
tether daemon --inbox ./inbox.jsonl

# In another, after you've sent a few messages:
tether drain --inbox ./inbox.jsonl
# {"update_id": 1234, ...}
# {"update_id": 1235, ...}
# [tether] drained 2 message(s)

tether drain --inbox ./inbox.jsonl
# [tether] drained 0 message(s)
```

`drain` writes its consumed-pointer to `inbox.jsonl.consumed.json`. If
your agent calls `drain` after handling each message, you have at-most-
once delivery semantics with crash safety.

## 4. The ack-first loop in Python

The opinionated bit: when an operator sends a message, the agent's
**first action** is a one-line ack BEFORE doing the work. This makes
async oversight tolerable — the operator knows their input was received.

```python
# examples/quickstart.py
from tether import Tether

p = Tether()
p.send("*Quickstart bot up.* Send /status or /abort.")

for msg in p.listen(poll_timeout=30):
    text = msg.text.strip()
    if text == "/status":
        p.send("Still running. Nothing to report.")
    elif text == "/abort":
        p.send("Bye.")
        break
    else:
        p.send(f"Got it: {text!r}")        # ack-first
        result = do_the_thing(text)         # the work
        p.send(f"Done: {result}")           # follow-up
```

Run:

```bash
python examples/quickstart.py
```

Now message your bot from your phone. You'll see the ack arrive
immediately; the result follows once the work finishes. That single
pattern is half the value of `tether`.

## 5. Useful next reads

- [API reference](api-reference.md) — every Python class/method
- [CLI reference](cli-reference.md) — every subcommand
- [Integrations](integrations.md) — Claude Code, Anthropic SDK, plain Python
- [Troubleshooting](troubleshooting.md) — when getUpdates returns nothing, etc.
- [Architecture](architecture.md) — what's persisted, why, and where
