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

## Two-way comms via turn-boundary hooks (v0.6+)

By default, `tether install claude-code` (and `tether init --install
claude-code`) now also wires two Claude Code hooks into
`.claude/settings.json`:

- **`Stop` hook** — fires after every Claude turn. Reads the inbox
  jsonl, finds messages received during the turn, and force-continues
  Claude with them so the agent acks + handles them before yielding
  back to you.
- **`UserPromptSubmit` hook** — fires when you submit a terminal
  prompt. Prepends any unread Telegram messages to the prompt as
  additional context, so Claude sees the inbox alongside what you
  just typed.

Together: **as long as a Claude session is alive, every operator
Telegram message gets a reply at the next turn boundary** — no
polling loop needed. The hook also advances the consumed-pointer
file atomically so messages aren't double-delivered.

### Configuring inbox / consumed paths

The defaults assume tether's native daemon (writes to
`./tether_inbox.jsonl`, pointer at `./tether_inbox.consumed.json`).
If your project already has a Telegram daemon writing to a different
path (e.g. futures-bot's `state/telegram_inbox.jsonl`), pass them
explicitly:

```bash
tether install claude-code \
  --inbox-path state/telegram_inbox.jsonl \
  --consumed-path state/telegram_inbox_consumed.json
```

The hook auto-detects two on-disk pointer formats:
- `{"update_id": N}` — tether's native daemon
- `{"line": N}` — line-count-based (custom daemons)

### Opting out

```bash
tether install claude-code --no-hooks   # MCP only, no hooks
```

You can also pin to `settings.local.json` instead of the shared
`settings.json` (useful when team members run different daemons):

```bash
tether install claude-code --settings-filename settings.local.json
```

### Idle-wake via Monitor + SessionStart (v0.6.1+, hardened in v0.6.2)

The `Stop` and `UserPromptSubmit` hooks only fire at **turn
boundaries** — not while Claude is sitting idle waiting for the
operator to type. So a Telegram message arriving during idle would
sit in the inbox until the next prompt or response.

v0.6.1 closes that gap with a third hook, `SessionStart`. On every
new Claude Code session it emits an `additionalContext` directive
that tells Claude to invoke its `Monitor` tool on a long-running
tail of the inbox JSONL:

> **v0.6.2 hardening.** The directive now leads with `MANDATORY
> FIRST ACTION` and explicit `BEFORE ANY OTHER TOOL CALL OR REPLY`
> framing. The original v0.6.1 wording was too soft — operators
> reported sessions where Claude treated the directive as
> informational and waited to be reminded. The reword makes the
> imperative unmistakable; you should never have to ask Claude to
> arm the Monitor.

```
python -m tether.hooks.inbox_tail --inbox <inbox_path>
```

The tail process polls the inbox file every second; each new line
becomes a stdout event, which Claude Code surfaces as an
in-conversation notification. That wakes the agent mid-idle, with
sub-second latency, for the lifetime of the session. Stop and
UserPromptSubmit still run in parallel — Monitor is purely additive
and only fills the idle window.

`tether install claude-code` writes all three hook entries
automatically. No extra flags required.

#### Monitor tool parameters (auto-arm + manual fallback)

The `SessionStart` hook delivers a directive; Claude itself must call
the `Monitor` tool to actually arm the tail. The exact arguments:

| Field         | Value                                                                       |
|---------------|-----------------------------------------------------------------------------|
| `command`     | `<python> -m tether.hooks.inbox_tail --inbox "<inbox-path>"`                |
| `description` | `tether telegram inbox tail`                                                |
| `persistent`  | `true`                                                                      |
| `timeout_ms`  | `3600000` (ignored when `persistent: true`; harness still requires it)      |

If you ever notice the Monitor didn't auto-arm (Telegram messages sent
during idle don't reach Claude until you type), use the slash command:

```
/tether arm
```

v0.6.3+ ships this command — `tether install claude-code` writes
`.claude/commands/tether.md` with the Monitor params baked in. Claude
will dedup against any already-running Monitor before re-arming. To
verify, ask *"is the tether Monitor running?"* — Claude Code tracks
each `Monitor` by task id and will report status.

See [integrations.md → Claude Code → Idle-wake
Monitor](integrations.md#idle-wake-monitor-v061--auto-arm--manual-fallback)
for the full reference, including how to pick the right Python
interpreter path on Windows vs POSIX.

### Still a limitation: cold start

If you message your bot when **no Claude session is running at all**,
nothing wakes it — the message just sits in the inbox until you start
`claude` again (at which point the `UserPromptSubmit` hook drains it
on your first prompt, and the `SessionStart` hook arms Monitor for
the next idle window). For true 24/7 wake, run a `/loop` polling
pattern alongside the hooks, or invoke Claude from your runtime when
a message arrives.

The hooks are the right answer for "Claude is running locally and
the operator wants two-way comms" — which is the 90% case for
agent-assisted dev.

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
