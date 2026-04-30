"""Claude Code hook: drain Telegram inbox at turn boundaries.

Wired by `tether install claude-code` into the project's
`.claude/settings.json`. Three events:

  - **Stop**: fires after a Claude turn. If unread Telegram messages
    arrived during the turn, the hook outputs `decision: block` so
    Claude force-continues and processes them before yielding control.

  - **UserPromptSubmit**: fires when the operator submits a terminal
    prompt. Hook prepends any unread Telegram messages as additional
    context, so Claude sees them alongside the new prompt.

  - **SessionStart** (v0.6.1+): fires once per session. Emits
    additionalContext directing Claude to invoke the Monitor tool on
    `tether.hooks.inbox_tail`, so new Telegram messages wake the
    session even during idle (between turns).

Together these cover the full Claude-is-alive surface area:
Stop = "during my turn", UserPromptSubmit = "between turns",
SessionStart + Monitor = "during idle". (Idle wake when Claude is
*not* running at all is a separate problem — use a `/loop` polling
loop or run `tether daemon` + `tether drain` periodically.)

Robust to two on-disk consumed-pointer formats:
  - `{"update_id": N}` — tether's native daemon format
  - `{"line": N}`      — line-count-based (e.g. futures-bot's existing daemon)

The pointer is advanced atomically *before* the hook returns, so a
crash mid-hook does not double-deliver — the messages are considered
delivered once Claude is told about them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def find_unread(
    inbox_path: Path, consumed_path: Path
) -> tuple[list[dict], dict]:
    """Read inbox + consumed pointer, return (unread_msgs, new_consumed)."""
    if not inbox_path.exists():
        return [], {}

    consumed: dict = {}
    if consumed_path.exists():
        try:
            text = consumed_path.read_text(encoding="utf-8")
            consumed = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            consumed = {}

    use_update_id = "update_id" in consumed
    last_uid = int(consumed.get("update_id", -1))
    last_line = int(consumed.get("line", 0))

    unread: list[dict] = []
    new_uid = last_uid
    line_count = 0

    raw_text = inbox_path.read_text(encoding="utf-8")
    for raw_line in raw_text.splitlines():
        raw = raw_line.strip()
        if not raw:
            continue
        line_count += 1
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if use_update_id and "update_id" in obj:
            uid = int(obj["update_id"])
            if uid > last_uid:
                unread.append(obj)
                new_uid = max(new_uid, uid)
        else:
            if line_count > last_line:
                unread.append(obj)

    new_consumed: dict = {}
    if use_update_id and new_uid > last_uid:
        new_consumed["update_id"] = new_uid
    elif unread and not use_update_id:
        new_consumed["line"] = line_count
    return unread, new_consumed


def format_messages(messages: list[dict]) -> str:
    """Render messages as one line per item: `[ts] user: text`."""
    out = []
    for m in messages:
        ts = m.get("received_at_utc") or m.get("date") or ""
        user = m.get("from_user")
        if not user:
            frm = m.get("from")
            if isinstance(frm, dict):
                user = frm.get("username") or frm.get("first_name") or "operator"
        user = user or "operator"
        text = m.get("text") or m.get("message") or ""
        prefix = f"[{ts}] " if ts else ""
        out.append(f"{prefix}{user}: {text}")
    return "\n".join(out)


def write_consumed_atomic(consumed_path: Path, new_consumed: dict) -> None:
    consumed_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = consumed_path.with_suffix(consumed_path.suffix + ".tmp")
    tmp.write_text(json.dumps(new_consumed), encoding="utf-8")
    tmp.replace(consumed_path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tether.hooks.inbox_drain",
        description="Drain Telegram inbox at Claude turn boundaries.",
    )
    p.add_argument(
        "--event",
        choices=["Stop", "UserPromptSubmit", "SessionStart"],
        required=True,
    )
    p.add_argument("--inbox", required=True,
                   help="path to telegram inbox jsonl")
    p.add_argument("--consumed", required=True,
                   help="path to consumed-pointer json")
    args = p.parse_args(argv)

    inbox = Path(args.inbox)
    consumed = Path(args.consumed)

    if args.event == "SessionStart":
        # SessionStart fires once per session. We don't drain the inbox
        # here (the next UserPromptSubmit will). Instead we emit an
        # additionalContext directive that tells Claude to spawn a
        # Monitor on the inbox-tail script, so new messages wake the
        # session even during idle. Without this, messages arriving
        # between turns sit in the inbox until the operator types.
        py = sys.executable.replace("\\", "/")
        inbox_arg = str(inbox).replace("\\", "/")
        tail_cmd = (
            f'"{py}" -m tether.hooks.inbox_tail --inbox "{inbox_arg}"'
        )
        out = {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    "Tether two-way comms (v0.6.1+): to receive Telegram "
                    "messages while idle (between operator prompts), "
                    "invoke the Monitor tool ONCE this session with these "
                    "exact parameters — `command`: " + tail_cmd + " — "
                    "`description`: tether telegram inbox tail — "
                    "`persistent`: true — `timeout_ms`: 3600000. Each "
                    "stdout line is one new Telegram message and will "
                    "wake you mid-idle. The Stop and UserPromptSubmit "
                    "hooks still run in parallel; Monitor is purely "
                    "additive to close the idle-wake gap. Skip this "
                    "step if a Monitor with the same command is already "
                    "running for this session."
                ),
            },
        }
        sys.stdout.write(json.dumps(out))
        return 0

    try:
        unread, new_consumed = find_unread(inbox, consumed)
    except OSError:
        # I/O failure: emit a no-op response so the hook never blocks
        # the Claude turn over a transient FS issue.
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        return 0

    if not unread:
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        return 0

    body = format_messages(unread)

    # Advance pointer BEFORE returning so a re-fire doesn't double-deliver.
    if new_consumed:
        try:
            write_consumed_atomic(consumed, new_consumed)
        except OSError:
            # Best-effort. Fall through with the messages still delivered;
            # next run may re-deliver, which the operator can ignore.
            pass

    if args.event == "Stop":
        out = {
            "decision": "block",
            "reason": (
                "Operator sent the following Telegram messages while you "
                "were responding (auto-drained by tether hook). Per the "
                "ack-first protocol, send a one-line ack via tether_send "
                "for each, then handle the request:\n\n" + body
            ),
        }
    else:  # UserPromptSubmit
        out = {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    "Unread Telegram messages (auto-drained by tether "
                    "hook):\n" + body
                ),
            },
        }
    sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
