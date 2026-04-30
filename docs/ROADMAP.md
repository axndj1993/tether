# Tether Roadmap

Forward-looking work for tether. Items here are scoped enough to start
on without an exploration phase, but aren't yet committed to a release.

## v0.7 — Cold-start daemon

**Problem.** v0.6.1 closes the in-session idle-wake gap (SessionStart
hook arms a Monitor on `inbox_tail`, so messages during idle reach
Claude with sub-second latency). What it does **not** solve: when no
Claude Code session is running at all. A Telegram message at 3am sits
in the inbox until the operator manually starts `claude` again.

**Goal.** A long-running, OS-level daemon that:

1. Watches the configured inbox JSONL for new lines (the existing
   `tether daemon` already writes to it from Telegram, so the watcher
   can sit in the same process or a sibling).
2. On a new inbound message, launches a Claude Code session in the
   target repo with `claude --continue` (or `claude` for a fresh
   session) so the existing v0.6 hook chain takes over from there:
   `UserPromptSubmit` (or `Stop` after the message arrives mid-turn)
   delivers the Telegram message as `additionalContext`.

**Coverage map after v0.7:**

| Window                     | Mechanism                          |
| -------------------------- | ---------------------------------- |
| During a Claude turn       | Stop hook (v0.6.0)                 |
| Between turns              | UserPromptSubmit hook (v0.6.0)     |
| During idle (session live) | SessionStart + Monitor (v0.6.1)    |
| **Cold start (no CC)**     | **Cold-start daemon (v0.7)**       |

### Open design questions

These need answers before implementation, but the broad approach is
fixed:

1. **Process model.** Standalone `tether wake-daemon`, or a flag
   on the existing `tether daemon` (`--auto-wake-claude
   --target-repo <path>`)? Folding into existing `daemon` is
   simpler for ops (one process, one systemd unit / NSSM service /
   launchd plist) but couples ingest with launch.
2. **Launch command.** `claude --continue` resumes the most recent
   conversation in the target repo; `claude --print "..."` would
   one-shot the message. The first preserves context across cold
   starts; the second avoids dragging unrelated history into a
   trivial reply. Initial pick: `--continue` for messages that look
   conversational, `--print` for ones that look like discrete
   commands. Heuristic TBD.
3. **Concurrency.** What happens if the operator already has a
   Claude session open in another terminal when a Telegram message
   arrives? The daemon should detect that and let the in-session
   hook chain handle it instead of double-spawning. Detection via
   `tether.hooks.SessionState` lockfile (new), or via a
   `~/.claude/sessions/*` path scan.
4. **Auth & headlessness.** `claude` requires auth tokens that may
   expire. Daemon needs a graceful failure mode (Telegram-back the
   error, do not crashloop). Consider periodic preflight ping
   `claude --version` / token check.
5. **Per-repo scope.** Operator may run multiple repos with separate
   Telegram bots / inbox files. Daemon config: list of (inbox_path,
   repo_path) pairs, dispatched by which inbox saw the message.
6. **Cross-platform service plumbing.** Windows: NSSM or Win32
   service. macOS: launchd plist. Linux: systemd user unit. Out of
   scope for the daemon itself, but shipped scripts / `tether
   wake-daemon install --service` would close the install loop.

### Anti-scope

Things v0.7 should explicitly **not** do:

- **Not a 24/7 agent autonomy layer.** The daemon's only job is to
  bridge an inbound message to a Claude session that the v0.6 hooks
  already know how to handle. It does not interpret messages,
  rate-limit them, or apply policy.
- **Not a replacement for `/loop`.** The user can still drop into a
  long-running `/loop` for tasks that genuinely need polled
  scheduling. The daemon is for one-shot "operator messaged the bot,
  agent should respond."

### Backwards compatibility

v0.7 is purely additive — no changes to v0.6 hooks, `inbox_drain`,
`inbox_tail`, or `install_claude_code_hooks()`. The daemon is opt-in
via a new CLI command and an explicit service install step.

### Reference notes (from the v0.6.1 build session, 2026-04-29)

- The auto-wake gap was first identified during v0.6.0 testing
  (memory id 10778: "Tether inbound works but lacks auto-wake on
  new messages").
- Decision tree at v0.6.1: ship Monitor + SessionStart now (in-session
  fix, ~half-day), defer cold-start daemon to v0.7 (real feature,
  cross-platform service plumbing, ~half-week).
- Author preference (operator): "later for cold start" — confirmed
  the v0.6.1 / v0.7 split.
