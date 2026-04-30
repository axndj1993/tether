# Onboarding — three commands, three minutes

`tether` v0.5 cuts setup from ~8 hand-edited steps to **3 commands**.
The wizard auto-detects your chat id and auto-writes the AI client's
MCP config; you never paste a JSON block or hunt for `chat.id` in a
raw API response again.

## The 3-command path (Claude Code)

```bash
# 1. Install
pip install 'tether[mcp]'

# 2. Set up: bot token in, chat id auto-detected, config auto-written
tether init --profile futures-bot --install claude-code

# 3. Restart Claude Code session
```

That's it. After step 2, `tether` has:
- created the profile config at `~/.tether/profiles/futures-bot/config.toml`
- verified the bot via Telegram getMe
- written the right `mcpServers` block into your project's
  `.claude/mcp.json` (creating the file if missing, preserving any
  other MCP servers you had configured)
- told you to restart

## What `tether init` does interactively

```
tether setup wizard — profile: 'futures-bot'

Step 1 of 3: Bot token.
  Open Telegram, message @BotFather, run /newbot.
  Paste the token below.

Bot token: 1234567890:AAH...xyz

Step 2 of 3: Chat id.
  Now open Telegram, search for your bot by username,
  and send it ANY message (e.g. /start). Don't close
  this terminal.

  Waiting up to 60 seconds for your message... detected chat_id=987654321

Wrote profile config: /home/u/.tether/profiles/futures-bot/config.toml

Step 3 of 3: Verifying with Telegram getMe...
OK — connected as bot @'my_claude_pager_bot'

Wrote Claude Code MCP config: /your/repo/.claude/mcp.json
Restart Claude Code to pick up the new server.
```

The `auto-detect chat id` magic: while you're at the wizard prompt,
tether is long-polling Telegram. You DM your bot, the message lands,
tether picks the `chat.id` out of the update, and fills it in. No
URL-typing in a browser, no `from.id` vs `chat.id` confusion.

## Other clients

Same wizard, different `--install` target:

```bash
tether init --profile myproj --install cursor
tether init --profile myproj --install codex
tether init --profile myproj --install continue
tether init --profile myproj --install zed
tether init --profile myproj --install cline      # writes a sidecar
```

## Add to an EXISTING setup (skip init)

If you've already run `tether init` and have a profile, just install
the MCP block:

```bash
tether install claude-code --profile futures-bot
tether install cursor --profile myproj
```

Existing servers in the host's config are preserved. The `tether`
key is replaced (idempotent).

## Inline credentials vs profile pinning

By default, `tether install` pins the host's MCP config to a
**profile name** (`TETHER_PROFILE=futures-bot` in the env block). The
actual bot token + chat id stay in `~/.tether/profiles/<name>/config.toml`
which is `chmod 600` and outside the project tree.

Some MCP hosts don't pass the user's env to subprocesses cleanly. For
those, embed credentials directly:

```bash
tether install claude-code --profile futures-bot --inline-creds
```

The mcp.json env block then carries `TELEGRAM_BOT_TOKEN` +
`TELEGRAM_CHAT_ID` literally. **Add `.claude/mcp.json` to .gitignore
if you go this route** — the file now contains your bot token.

## Manual override (skip auto-detect)

If you already know your chat id (e.g. it's listed in a script
that's been working), pass `--chat-id`:

```bash
tether init --profile myproj --chat-id 987654321 --install claude-code
```

Skips the "DM your bot" step.

## Troubleshooting

**"timeout — no message received"**: The wizard polled for 60s and
saw no message land. Check:
- Did you actually DM the bot from Telegram? (Search for the username
  BotFather gave you, then send `/start`.)
- Is the token correct? Re-run with --chat-id N if you can find it
  the manual way.
- Is the network blocked from reaching `api.telegram.org`?

**"WARN: getMe failed"**: Token is wrong or expired. Re-check what
BotFather gave you.

**"unknown client"**: `tether install --help` lists the supported
hosts. Want to add one? PRs welcome — see
[`src/tether/install.py`](../src/tether/install.py) for the
`CLIENTS` dict.

## Comparison: v0.4 → v0.5 onboarding

| Step                                | v0.4 (manual)                                     | v0.5 (wizard)                          |
|-------------------------------------|---------------------------------------------------|----------------------------------------|
| Install pkg                         | ✓                                                 | ✓                                      |
| Create Telegram bot                 | manual @BotFather (unavoidable)                   | manual @BotFather (unavoidable)        |
| **Find chat id**                    | manual: visit getUpdates URL, find `chat.id`      | **auto-detected** (DM the bot, wizard reads update) |
| Configure tether                    | `tether init`                                     | folded into `tether init`              |
| Verify                              | `tether send`                                     | folded into `tether init`              |
| **Edit `.claude/mcp.json`**         | manual JSON edit                                  | **auto-written** by `--install`        |
| Restart Claude                      | manual                                            | manual                                 |
| Verify                              | `/mcp` in Claude                                  | `/mcp` in Claude                       |

Net: from ~8 steps + 2 error-prone hand-edits to **3 commands** with
zero hand-edits.
