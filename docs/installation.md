# Installation

## Requirements

- Python 3.10 or later
- Internet access (to reach `api.telegram.org`)
- A Telegram account (for the operator)

## Install the package

### From PyPI (recommended)

```bash
pip install tether
```

### From source (this repo)

```bash
git clone https://github.com/axndj1993/tether.git
cd tether
pip install -e .            # editable
# or:
pip install -e ".[dev]"     # editable + test dependencies (pytest, responses)
```

### Verify

```bash
tether --version
# tether 0.1.0
```

## Create the Telegram bot

`tether` talks to a **bot account** that you own. The bot relays messages
between your phone and the agent.

1. Open Telegram on your phone or desktop and start a chat with
   [`@BotFather`](https://t.me/BotFather).
2. Send `/newbot`. Pick a display name (e.g. *"my-claude-tether"*) and a
   username ending in `bot` (e.g. *`my_claude_tether_bot`*).
3. BotFather replies with a bot token of the form:

   ```
   1234567890:AAH...xyz
   ```

   This is the secret. Treat it like a password — never commit it.

## Find your chat id

`tether` needs to know **which chat** to send messages to. The simplest
way:

1. In Telegram, send any message to your new bot (e.g. `start`). The bot
   won't reply yet, but the message creates a conversation.
2. In a browser, visit:

   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

   Replace `<TOKEN>` with the value from BotFather.

3. Look for a JSON snippet like:

   ```json
   {"chat": {"id": 987654321, "first_name": "Gautam", ...}}
   ```

   The integer in `"id"` is your chat id.

If `getUpdates` returns `{"result": []}`, send the bot another message
and refresh. Updates expire after 24h.

## Configure tether

You have three ways. Pick whichever fits.

### Option 1 — interactive wizard (easiest)

```bash
tether init
```

Prompts for token + chat id, writes `~/.tether/config.toml` with mode
`0o600` on POSIX, then verifies via `getMe`. Done.

### Option 2 — environment variables (good for CI / shell scripts)

```bash
export TELEGRAM_BOT_TOKEN=1234567890:AAH...xyz
export TELEGRAM_CHAT_ID=987654321
```

`tether` reads env first, so they override any config file.

### Option 3 — `~/.tether/config.toml`

```toml
bot_token = "1234567890:AAH...xyz"
chat_id = 987654321
```

`chmod 600` it. The wizard does this for you on POSIX.

## Verify it works

```bash
tether whoami
# {"id": 1234567890, "is_bot": true, "username": "my_claude_tether_bot", ...}

tether send "first message from tether"
# Check your Telegram — you should see the message arrive.
```

You're done. See [quickstart](quickstart.md) for the next steps.

## Uninstall

```bash
pip uninstall tether
rm -rf ~/.tether       # clears state + config
```
