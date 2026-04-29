# Troubleshooting

## `tether: config error: No bot token.`

You haven't set the token. Pick one:

```bash
export TELEGRAM_BOT_TOKEN=...        # env var
# or
tether init                            # interactive, writes ~/.tether/config.toml
```

## `tether whoami` returns "unauthorized"

The token is wrong, expired, or revoked. Talk to BotFather:

```
/mybots → pick the bot → API token
```

…to view or regenerate. If you regenerate, all old tokens become invalid.

## `tether send` succeeds but no message arrives on my phone

Most common: wrong chat id. Verify with:

```bash
tether send "test" 2>&1   # check exit code
```

If exit 0, the API accepted the send but the chat may be a stale id
(e.g., you copied a `from.id` instead of `chat.id` — those can differ
in groups).

Re-derive the chat id:

1. Send the bot any message from the operator's account.
2. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates`.
3. Find `"chat":{"id":<NUMBER>}`. That's the integer.

## `tether daemon` keeps printing the same message

You haven't `drain`ed. The daemon writes every inbound message to the
inbox JSONL; it doesn't track what your agent has consumed. To advance
the consumed pointer:

```bash
tether drain --inbox ./inbox.jsonl
```

Now the next `drain` will print only newer messages.

## Daemon polls but receives nothing

Check three things:

1. **Send the bot a message first.** Telegram drops messages older
   than 24h, and a bot with no chat history has nothing to deliver.

2. **Verify the offset isn't stuck way ahead.** If you've been
   experimenting:

   ```bash
   cat ~/.tether/offset.json
   ```

   To reset and force a re-fetch of everything still in the queue:

   ```bash
   rm ~/.tether/offset.json
   ```

3. **Confirm the bot wasn't disabled.** BotFather → `/mybots` → status.

## "Conflict: terminated by other getUpdates request"

You have two tethers polling the same bot simultaneously. Telegram
allows one long-poll per token. Either:

- Stop one of them (Ctrl-C the daemon, or kill the script).
- Use **two separate bots** — one per agent / per chat.

## My message has special chars that break MarkdownV1

MarkdownV1 (Telegram's default) parses `* _ [ ` and `` ` `` literally.
Either escape them with backslash:

```python
p.send(r"\_underscore\_")
```

Or switch to plain mode:

```python
p.send("raw text *with* literal asterisks", parse_mode=None)
```

Or upgrade to MarkdownV2 (stricter rules but better-defined escaping).

## High latency on inbound — message takes seconds to arrive

Two causes:

1. **`poll_timeout` too high relative to your handler.** If you set
   `poll_timeout=30`, the daemon may be mid-poll when you send. Telegram
   *should* end the long-poll early on a new message, but some networks
   delay this. Lowering to 10 reduces worst case.

2. **Network instability.** `requests` doesn't auto-retry on transient
   timeouts; `listen()` does (5s sleep, then retry). If you see latency
   spikes, check if `listen()` is in its error-sleep window.

## Memory growth over long runs

The daemon's `inbox.jsonl` grows append-only. For long-running deployments,
rotate periodically:

```bash
mv inbox.jsonl inbox.$(date +%Y%m%d).jsonl
touch inbox.jsonl   # daemon will pick up the new file on next poll
```

The daemon doesn't lock the file; rename + recreate is safe.

## `ImportError: cannot import name 'Tether'`

You installed `tether` but imported it elsewhere with a name clash.
Verify:

```bash
python -c "import tether; print(tether.__file__)"
```

Should print something inside the tether site-packages. If it points
to your own `tether.py`, rename your file (Python prefers local modules
over installed packages).
