# CLI reference

`tether <subcommand>`

## `tether send TEXT [options]`

Send one message. Returns 0 on success, 1 on API failure, 2 on missing
config.

| Option            | Default      | Meaning |
|-------------------|--------------|---------|
| `TEXT` (positional) | required   | message body. Surround with quotes if it contains spaces or shell-special characters. |
| `--parse-mode`    | `Markdown`   | one of `Markdown`, `MarkdownV2`, `HTML`, `none`. `none` sends plain text (no formatting). |
| `--silent`        | off          | suppress notification sound on the operator's phone. |

```bash
tether send "build started"
tether send "*bold* and _italic_"
tether send "raw <html>" --parse-mode none
tether send "fyi only" --silent
```

## `tether daemon [options]`

Long-poll Telegram forever, append every inbound message (as JSON, one
per line) to `--inbox`. Also writes the same line to stdout for tailing.

Stop with `Ctrl-C`. Returns 0 on clean exit, 1 on fatal error.

| Option           | Default                 | Meaning |
|------------------|-------------------------|---------|
| `--inbox`        | `./tether_inbox.jsonl`   | path to append-only JSONL file. |
| `--poll-timeout` | `30`                    | long-poll seconds per `getUpdates` call. Lower = more requests; higher = more delay before Ctrl-C takes effect. |

```bash
tether daemon --inbox ./inbox.jsonl
tether daemon --inbox ./inbox.jsonl --poll-timeout 10
```

## `tether drain [options]`

Print inbox lines newer than the persisted "consumed" pointer; advance
the pointer atomically. At-most-once delivery semantics: lines printed
once will not be printed by subsequent `drain` calls (unless you delete
the consumed file).

| Option       | Default                                | Meaning |
|--------------|----------------------------------------|---------|
| `--inbox`    | `./tether_inbox.jsonl`                  | inbox file (must match the daemon). |
| `--consumed` | `<inbox>.consumed.json`                | pointer file; persists `update_id`. |

```bash
tether drain
tether drain --inbox /var/log/tether.jsonl
```

## `tether init`

Interactive config wizard. Prompts for bot token + chat id, writes
`~/.tether/config.toml` with permissions `0o600` (POSIX), then verifies
the token by calling `getMe`. Idempotent — re-running it overwrites.

```bash
tether init
```

## `tether whoami`

Calls `getMe`. Prints the bot's profile JSON. Useful for verifying
that a token is valid without sending a message.

```bash
tether whoami
# {
#   "id": 1234567890,
#   "is_bot": true,
#   "first_name": "my-claude-tether",
#   "username": "my_claude_tether_bot",
#   ...
# }
```

## `tether --version`

Prints the tether version and exits.

## Exit codes

| Code | Meaning |
|------|---------|
| 0    | success |
| 1    | runtime error (transport, API not-ok, daemon fatal) |
| 2    | config error (missing token / chat id / malformed value) |

## Environment variables

| Variable               | Meaning |
|------------------------|---------|
| `TELEGRAM_BOT_TOKEN`   | Bot token. Highest-priority config source. |
| `TELEGRAM_CHAT_ID`     | Default chat id. Highest-priority config source. |

Env vars override `~/.tether/config.toml`.
