# Profiles — multiple bots/chats per machine

`tether` v0.4 introduces **named profiles**. Each profile is one bot
+ one chat + one transport. Different agents (futures-bot, code-
review, dev-experiments) can tether to *different* profiles so their
messages land in *different* channels — clean isolation between
concurrent agentic workstreams.

## When you need this

- You're running Claude Code / agents on **multiple repos
  simultaneously**, and you don't want all their alerts colliding in
  one Telegram chat.
- You have a **personal-bot** and a **team-bot**, with separate chats
  for each.
- One workstream wants Telegram, another wants Slack.
- You want a **repo-level config** that the right bot is automatically
  selected when you `cd` into the project.

## When you don't

If you only ever run one agent or only want one chat, you don't need
profiles. Just configure tether with `TELEGRAM_BOT_TOKEN` env vars OR
`tether init` (which writes `~/.tether/profiles/default/config.toml`).
Everything goes to the `default` profile transparently. Zero
ceremony.

## Resolution priority

When you call `Tether()` (Python) or `tether send` (CLI) without an
explicit profile name, `tether` walks this chain and stops at the
first hit:

1. **Explicit ctor arg / CLI flag** — `Tether(profile="X")` or
   `tether --profile X send …`
2. **`TETHER_PROFILE` env var** — set per-shell or in `mcp.json`'s
   `env` block
3. **`.tether` file** in CWD or any parent dir (auto-detected, like
   `.python-version` from pyenv). Single line, profile name.
4. **`default`** — fallback. v0.3 users with `TELEGRAM_BOT_TOKEN`
   env or flat `~/.tether/config.toml` keep working as `default`
   without any changes.

## Storage layout

```
~/.tether/
    config.toml                       # legacy flat config (read as 'default' fallback)
    profiles/
        futures-bot/
            config.toml               # transport, bot_token, chat_id
            offset.json               # per-profile polling state
        code-review/
            config.toml               # could be Slack
            offset.json               # independent of futures-bot
        dev-experiments/
            ...
```

**Critical**: each profile has its **own** `offset.json`. If
`profile-A` polls Telegram, it advances `profile-A`'s pointer — NOT
`profile-B`'s. Without per-profile state isolation you'd lose
messages on profile-B every time profile-A polled.

## CLI

### Create a profile

```bash
tether init --profile futures-bot
# (interactive wizard prompts for bot token + chat id, verifies via getMe)

tether init --profile code-review
# ...
```

### List + inspect

```bash
tether profiles list
#   default             transport=telegram   chat=987654321
#   futures-bot         transport=telegram   chat=111222333
#   code-review         transport=slack      chat=C012ABCDE

tether profiles current
# profile: default
# source : default
# config : /home/u/.tether/profiles/default/config.toml

tether profiles show futures-bot
#   transport = 'telegram'
#   bot_token = '12345...xyz'    (masked)
#   chat_id   = 111222333
```

### Switch which profile is active in a directory

```bash
cd ~/repos/futures-bot
tether profiles use futures-bot
# wrote /home/u/repos/futures-bot/.tether
# profile 'futures-bot' now active in this directory tree.
```

After this, anywhere inside `~/repos/futures-bot/`, all `tether send`
/ `tether daemon` / etc commands use the `futures-bot` profile
automatically. The `.tether` file is one line, gitignorable, easy to
override.

### One-off override

```bash
tether --profile dev-experiments send "test"
# uses 'dev-experiments' regardless of env / .tether
```

### Delete a profile

```bash
tether profiles delete dev-experiments
# removes ~/.tether/profiles/dev-experiments/
```

## Python

```python
from tether import Tether

# Auto-resolve via the priority chain.
t = Tether()

# Explicit profile.
t = Tether(profile="code-review")

# Direct injection (no profile lookup).
t = Tether(bot_token="...", chat_id=42)
```

The `t.profile_name` attribute tells you which profile was resolved.

## MCP per-project

Each project's `.claude/mcp.json` (or `~/.cursor/mcp.json`, etc) can
pin a profile via the `env` block. The `tether-mcp` server then talks
to that project's bot:

```json
{
  "mcpServers": {
    "tether": {
      "command": "tether-mcp",
      "env": {
        "TETHER_PROFILE": "futures-bot"
      }
    }
  }
}
```

Different project, different `TETHER_PROFILE` value → different bot.
Each Claude Code session pings the right channel.

## "Tether all to one" — when you want collision

If you'd rather have all your agents hit ONE channel (low volume, you
prefer the unified feed), just don't create extra profiles. The
`default` profile catches everything. v0.3 users see no behavior
change.

If you have multiple profiles defined but want them to *also* mirror
to a master channel — that's [v0.5 fan-out / mirror](./why.md#roadmap),
not in v0.4 yet.

## Migration from v0.3

Already had `~/.tether/config.toml`? Already had `TELEGRAM_BOT_TOKEN`
env vars set?

**You don't need to do anything.** v0.4 reads the legacy flat
config and the legacy env vars as the `default` profile. Existing
scripts continue to work unchanged.

To **upgrade** an existing setup into a named profile:

```bash
# Copy your existing flat config into a named profile:
mkdir -p ~/.tether/profiles/main
cp ~/.tether/config.toml ~/.tether/profiles/main/config.toml

# Mark this directory's `.tether` to use it:
cd ~/your-project
tether profiles use main

# Verify:
tether profiles current
# source : dot_tether (/home/u/your-project/.tether)
```

## Troubleshooting

### `tether profiles current` shows source=`default` even though I set `.tether`

`.tether` files are walked from CWD upward. If you ran `tether
profiles use X` in a different directory, the `.tether` file lives
there, not where you're now. Re-run from the project root, or move
the file.

### Polling from one profile is "missing messages" that another profile shows

You configured **two profiles with the same bot token**. Telegram
allows only one long-poll per token; the polls race each other and
each profile only sees a fraction of the updates. Fix: use a
**different bot per profile** (create a new bot in BotFather).

### CI / cron jobs need a specific profile

Set `TETHER_PROFILE` in the job's environment:

```yaml
# GitHub Actions
env:
  TETHER_PROFILE: ci-runner
```

The `default` fallback also works fine if all your CI sends should go
to one channel — same as before.
