# Architecture

`tether` is deliberately small. This page documents what state lives
where, the threading model, and the design choices.

## Component map

```
   ┌─────────────────────┐
   │ tether.Tether         │  — public API (send, poll_once, listen, whoami)
   │  - bot_token        │
   │  - chat_id          │
   │  - state_dir        │
   └──┬──────────────────┘
      │
   ┌──▼──────────────────┐
   │ requests.Session    │  — HTTP transport (single connection pool per
   │                     │     Tether instance, 60s timeout per call)
   └──┬──────────────────┘
      │  HTTPS POST
   ┌──▼──────────────────┐
   │ api.telegram.org    │  — Telegram Bot API
   │  /bot<TOKEN>/<call> │
   └─────────────────────┘
```

```
   ┌─────────────────────┐
   │ tether.daemon        │  — long-running JSONL writer
   │  - run_daemon()     │
   │  - drain()          │
   └──┬──────────────────┘
      │
   ┌──▼──────────────────┐
   │ inbox.jsonl         │  — append-only message log
   └──┬──────────────────┘
      │
   ┌──▼──────────────────┐
   │ inbox.consumed.json │  — at-most-once consumed pointer
   └─────────────────────┘
```

## State

| File                              | Purpose                                                     | Atomicity |
|-----------------------------------|-------------------------------------------------------------|-----------|
| `~/.tether/config.toml`            | Bot token + default chat id (alternative to env vars)       | One-shot write |
| `~/.tether/offset.json`            | Telegram next-update pointer; persists across restarts      | tmp + rename |
| `<inbox>.jsonl` (user-chosen)     | Daemon writes one inbound message per line                  | append, fsync-on-flush |
| `<inbox>.consumed.json` (default) | Highest update_id already consumed by `drain`               | one-shot write |

Both pointer files use the **temp-file + rename** pattern so a crash
mid-write can't leave them half-written. The same pattern is used by
git, sqlite, and most production-grade state stores.

## Polling model

`poll_once()` issues a single `getUpdates` request with the persisted
offset. On success, it advances the offset to `max(update_id) + 1` and
returns the messages.

`listen()` calls `poll_once()` in a loop with `timeout=poll_timeout`
(default 30s). Telegram's long-poll holds the request open until either
a message arrives OR the timeout expires, then returns. So the
operator's message latency is bounded by HTTP round-trip + processing
in the agent loop — typically <500ms in practice.

On `TetherError` (transport timeout, API not-ok), `listen()` sleeps
`sleep_on_error` (default 5s) and retries. This handles transient
network blips without crashing the agent.

### Why long-poll instead of webhooks?

- **No public IP / TLS cert needed.** Long-poll works behind any
  firewall.
- **Stateless server side.** Telegram doesn't have to know about your
  agent's address.
- **Simpler local dev.** No `ngrok` or reverse proxy.

The trade-off: each poll is one HTTPS round-trip. At a 30s long-poll,
that's ~120 requests/hr per agent — well within Telegram's bot limits.

## Configuration precedence

`Tether.__init__` resolves credentials in this order, stopping at the
first hit:

1. Constructor argument (`bot_token=`, `chat_id=`)
2. Environment variable (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)
3. `~/.tether/config.toml`

This order maximizes explicit control: a script that explicitly passes
a token never gets surprised by a stray env var, and env vars in CI
beat any user's leftover home-dir config.

## Error model

```
TetherError                    — base; catch this for any tether failure
└── ConfigError               — missing or malformed token / chat id
```

Errors carry the original cause via `__cause__` (`raise ... from e`).
The CLI maps:

- `ConfigError`     → exit 2, "config error" message
- `TetherError`      → exit 1, error message

## Threading and concurrency

Each `Tether` instance owns one `requests.Session` and is **not
thread-safe**. To use tether from multiple threads, give each thread its
own instance, or wrap calls in a lock.

`run_daemon` runs in the foreground of whichever process you start it
in. To run as a background service, fork it via your OS's facility
(`systemd`, `supervisord`, `nssm` on Windows, etc.) — tether doesn't
fork itself.

## Where tether intentionally does NOT go

- **No webhooks.** See above.
- **No persistence of message history.** That's the agent's job; the
  inbox JSONL is a simple append-only log you can rotate yourself.
- **No multi-bot orchestration.** One Tether = one bot = one default
  chat. Compose at a higher level if you need fan-out.
- **No retries on outbound `send`.** If `send` fails, the caller
  decides — tether doesn't queue a buffer that could re-send stale
  messages later.
- **No structured commands DSL.** Slash commands are just strings;
  parse them however your agent likes.

These are deliberate. The package stays under ~400 LOC and one
dependency (`requests`) so it's easy to audit.

## Why "ack-first" lives in the docs, not the code

The ack-first convention (immediately reply to an inbound message
before doing the work) is a UX rule, not an API constraint. Different
agents will want different ack texts, different ack timing, different
"is this command operational vs noise?" classification. Tether doesn't
prescribe — it documents the convention and gives you the primitive.
