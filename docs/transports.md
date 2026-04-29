# Transports

`tether` v0.3 introduces a transport abstraction. The Telegram backend
that ships in v0.1/0.2 is now one of multiple transports — Slack lands
in v0.3, and Discord/SMS/Signal are on the roadmap.

## What's a transport?

A transport implements three methods:

```python
class Transport(Protocol):
    name: str
    def send(self, text, *, silent=False, chat_id=None) -> dict: ...
    def poll_once(self, *, timeout=0) -> list[TransportMessage]: ...
    def listen(self, *, poll_timeout=30, sleep_on_error=5.0) -> Iterator[TransportMessage]: ...
    def whoami(self) -> dict: ...
```

Implementations:

| Name       | Module                       | Status |
|------------|------------------------------|--------|
| `telegram` | `tether.client.Tether`       | v0.1+ (default) |
| `slack`    | `tether.transports.SlackTransport` | **v0.3 (new)** |
| `discord`  | —                            | roadmap |
| `sms`      | —                            | roadmap (Twilio) |
| `signal`   | —                            | roadmap |

## Picking a transport

### Python

```python
from tether import make_transport

# Telegram (default — same as Tether())
t = make_transport("telegram")

# Slack
t = make_transport("slack")

# Either way, the API is the same:
t.send("hello")
for msg in t.listen():
    print(msg.text)
```

### CLI

The CLI defaults to Telegram for backward compatibility. To pick
Slack:

```bash
tether send "hello" --transport slack
```

(Coming soon — v0.3 wires the flag into all CLI subcommands.)

## Slack setup (one-time)

1. **Create the Slack app** at https://api.slack.com/apps → "From
   scratch". Pick your workspace.

2. **OAuth scopes**. Sidebar → "OAuth & Permissions" → Bot Token Scopes:
   - `chat:write`         — to send messages
   - `channels:history`   — to read public-channel messages
   - `im:history`         — to read direct messages
   - `app_mentions:read`  — to react when @-mentioned
   - `channels:read`      — to look up channels

3. **Install to workspace**. Same page, "Install to Workspace" button.
   You'll get a *Bot User OAuth Token* starting with `xoxb-`.

4. **Enable Socket Mode**. Sidebar → "Socket Mode" → toggle ON. You'll
   be prompted to create an *App-Level Token*; give it the
   `connections:write` scope. Copy the resulting token (starts with
   `xapp-`).

5. **Subscribe to events**. Sidebar → "Event Subscriptions" → toggle
   ON. Under "Subscribe to bot events" add:
   - `message.channels`
   - `message.im`
   - `app_mention`

6. **Invite the bot** to whichever channel you want it in. In Slack
   itself: `/invite @your-bot-name` from inside the channel.

7. **Find the channel id.** Right-click the channel → View channel
   details → at the bottom, "Channel ID: C012ABCDE". Copy it.

## Configure tether for Slack

```bash
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
export SLACK_CHANNEL_ID=C012ABCDE
```

Verify:

```python
from tether import SlackTransport
t = SlackTransport()
print(t.whoami())                       # confirms auth
t.send("hello from tether/slack")        # check Slack — message lands
```

## Inbound polling

Telegram uses long-poll (HTTP `getUpdates`); Slack uses Socket Mode
(WebSocket). Both expose `listen()` as a blocking iterator that yields
`TransportMessage`s.

The Slack `SocketModeClient` runs in a background thread inside the
process. `listen()` polls a thread-safe queue and yields messages as
they arrive.

```python
from tether import SlackTransport

t = SlackTransport()
t.send("agent online")
for msg in t.listen(poll_timeout=30):
    if msg.text.strip().lower() == "/status":
        t.send("Still running.")
    elif msg.text.strip().lower() == "/abort":
        t.send("Bye.")
        break
```

## Outbound only (Slack send + no Socket Mode)

If you don't need inbound, you can skip the App Token + Socket Mode +
event subscriptions. Just install the bot with `chat:write` scope and
set `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID`. Then:

```python
t = SlackTransport()       # works — listen() will error if you call it
t.send("hello")
```

This is the minimum-viable Slack notifier setup. Useful for CI / cron
jobs that only emit events.

## Notification semantics

Slack and Telegram differ on "silent" sends:

- **Telegram silent=True** → `disable_notification=true` → message
  arrives, no buzz.
- **Slack silent=True** → no direct equivalent. tether maps it to
  `unfurl_links=False, unfurl_media=False` (less attention-grabbing
  visually). The notification itself still fires per the recipient's
  Slack settings.

If you need true Slack quiet-time, integrate with the recipient's Do
Not Disturb settings via `dnd.setSnooze` — out of scope for tether
v0.3.

## Adding a new transport

The `Transport` protocol is the only contract. Implement
`send`/`poll_once`/`listen`/`whoami`, return `TransportMessage`s with
populated fields, and register in `tether.transports.make_transport`.

Roughly 100 lines per transport. PRs welcome.
