# Python API reference

`from tether import Tether, Message, TetherError, ConfigError`

## class `Tether`

```python
Tether(
    *,
    bot_token: str | None = None,
    chat_id: int | str | None = None,
    state_dir: Path | str | None = None,
    api_base: str = "https://api.telegram.org",
    session: requests.Session | None = None,
)
```

Configured via (in order): constructor args → env vars
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) → `~/.tether/config.toml`.
Raises `ConfigError` if neither path resolves token+chat.

`state_dir` defaults to `~/.tether`. `api_base` lets you point at a
mock server for tests. `session` accepts an `httpx`-compatible
`requests.Session` for connection pooling, retries, etc.

### Methods

#### `send(text, *, parse_mode="Markdown", chat_id=None, silent=False) -> dict`

Send a text message. Returns the Telegram `Message` dict (so you can
read `message_id` for editing later, etc.).

| Arg          | Type            | Default      | Meaning |
|--------------|-----------------|--------------|---------|
| `text`       | `str`           | required     | message body |
| `parse_mode` | `str` or `None` | `"Markdown"` | `"Markdown"` (V1: `*bold*` `_italic_`), `"MarkdownV2"`, `"HTML"`, or `None` for plain text. |
| `chat_id`    | `int` or `None` | self.chat_id | override target chat (multi-chat use) |
| `silent`     | `bool`          | `False`      | suppress notification sound on the operator's phone |

Raises `TetherError` on transport or API failure (response not-ok).

```python
p.send("*hi*")
p.send("plain", parse_mode=None)
p.send("ssh", silent=True)              # no buzz
```

#### `poll_once(*, timeout=0, allowed_updates=None) -> list[Message]`

One-shot poll. Returns inbound `Message`s since the last call,
advances persisted offset on success.

| Arg               | Type             | Default                      | Meaning |
|-------------------|------------------|------------------------------|---------|
| `timeout`         | `int`            | 0                            | long-poll seconds. 0 = immediate return. 30 = wait up to 30s for a message. |
| `allowed_updates` | `list[str]`/None | `["message","edited_message"]` | filter — see [Telegram Bot API](https://core.telegram.org/bots/api#update). |

Returns `[]` when the queue is empty. Non-`message` updates (callback
queries, channel posts) advance the offset but don't yield Messages.

#### `listen(*, poll_timeout=30, sleep_on_error=5.0) -> Iterator[Message]`

Long-polling iterator. Yields Messages forever until the caller breaks
out or sends KeyboardInterrupt. Wraps `poll_once` in a resilient loop —
on transient `TetherError`, sleeps `sleep_on_error` seconds and retries.

```python
for msg in p.listen():
    handle(msg)            # blocks
```

Suitable for the main loop of a small agent. For agents with their own
event loop, prefer `poll_once` and integrate the polling cadence
yourself.

#### `whoami() -> dict`

Calls `getMe`. Returns the bot's profile. Useful for `tether init` to
verify a token.

## class `Message` (dataclass, frozen-ish)

| Field             | Type         | Meaning |
|-------------------|--------------|---------|
| `update_id`       | `int`        | Telegram's monotonic id; used for offset advancement |
| `chat_id`         | `int`        | source chat (private user, group, channel) |
| `chat_type`       | `str`        | `"private"`, `"group"`, `"supergroup"`, `"channel"` |
| `from_user`       | `str` or None | sender's display name (first_name or username) |
| `from_user_id`    | `int` or None | sender's Telegram user id |
| `text`            | `str`        | message body. Empty for non-text msgs (photo, sticker, etc.) |
| `edited`          | `bool`       | True if this is an edit of an earlier message |
| `received_at_utc` | `str`        | ISO8601, set when poll receives the update |

```python
@dataclass
class Message:
    update_id: int
    chat_id: int
    chat_type: str
    from_user: str | None
    from_user_id: int | None
    text: str
    edited: bool
    received_at_utc: str
```

## Errors

```python
class TetherError(Exception):           # base
class ConfigError(TetherError):         # missing/malformed token or chat id
```

Catch `TetherError` to handle any tether failure (transport, API not-ok,
invalid response). Catch `ConfigError` specifically to prompt the user
to run `tether init`.

## Daemon mode (Python)

`from tether.daemon import run_daemon, drain`

```python
run_daemon(
    *,
    out_path: Path | str,
    tether: Tether | None = None,
    poll_timeout: int = 30,
    print_to_stdout: bool = True,
) -> int
```

Long-polls, appends each inbound `Message` (as JSON) to `out_path`,
returns when KeyboardInterrupt is received. If `print_to_stdout` is
True (default), the same line is also written to stdout — useful for
piping into a `tail`-style consumer or a Claude Code Monitor.

```python
drain(*, in_path: Path | str, consumed_path: Path | str | None = None) -> int
```

Prints any inbox lines newer than the consumed pointer; advances the
pointer atomically. The consumed path defaults to
`<in_path>.consumed.json`. Pair with `run_daemon` for at-most-once
consumption.
