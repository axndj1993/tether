"""Long-running tail of the Telegram inbox JSONL, for Claude Code Monitor.

Companion to ``tether.hooks.inbox_drain``. Where ``inbox_drain`` is a
one-shot hook that fires at session-event boundaries (Stop /
UserPromptSubmit / SessionStart), this script is a *streaming* tail
that runs for the lifetime of the Claude session and emits one
formatted line per new Telegram message.

The intended invocation is via Claude Code's ``Monitor`` tool — each
stdout line becomes a notification, which wakes Claude even from the
idle "waiting for the operator to type" state. That closes the
auto-wake gap left by the turn-boundary-only hooks (a message arriving
during idle would otherwise sit in the inbox until the operator typed
something).

Cross-platform: pure stdlib, polling-based (no inotify / fsevents)
because Windows doesn't have either. Default poll interval is 1.0s,
which is well below the operator's perceptual threshold for
"the bot replied immediately".

Robustness:
  - waits for the inbox file to exist if not yet created
  - handles file truncation (size shrinks below current read offset)
  - handles file rotation / re-creation (file disappears, new file
    appears) by re-opening
  - tolerates malformed JSON lines (skip + keep going)
  - flushes stdout after every emit so the Monitor sees lines
    immediately, not at OS buffer boundaries
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _format_line(obj: dict) -> str:
    """Render one inbox record as `[ts] user: text`. Matches inbox_drain."""
    ts = obj.get("received_at_utc") or obj.get("date") or ""
    user = obj.get("from_user")
    if not user:
        frm = obj.get("from")
        if isinstance(frm, dict):
            user = frm.get("username") or frm.get("first_name") or "operator"
    user = user or "operator"
    text = obj.get("text") or obj.get("message") or ""
    prefix = f"[{ts}] " if ts else ""
    return f"{prefix}{user}: {text}"


def _emit(line: str) -> None:
    """Write one notification line and flush so Monitor sees it."""
    sys.stdout.write(line.rstrip("\n") + "\n")
    sys.stdout.flush()


def _open_at_end(path: Path):
    """Open the inbox for reading and seek to EOF. Returns the handle."""
    f = path.open("r", encoding="utf-8")
    f.seek(0, os.SEEK_END)
    return f


def tail_loop(
    inbox: Path,
    poll_interval: float,
    *,
    emit_existing: bool = False,
    iterations: int | None = None,
) -> int:
    """Tail-F the inbox JSONL and emit each new record.

    Args:
        inbox: path to the inbox JSONL file.
        poll_interval: seconds between filesystem polls when idle.
        emit_existing: if True, replay existing lines once at startup
            (used by tests). Default False — production should only
            emit what arrives *after* the Monitor starts, since the
            turn-boundary hooks already covered the backlog.
        iterations: bound on outer loop iterations (test hook). None
            means run forever.

    Returns process exit code (0 on graceful loop end, non-zero on
    fatal error).
    """
    iters = 0

    # Wait for the inbox file to appear without spinning the CPU.
    while not inbox.exists():
        if iterations is not None and iters >= iterations:
            return 0
        time.sleep(poll_interval)
        iters += 1

    if emit_existing:
        try:
            text = inbox.read_text(encoding="utf-8")
        except OSError:
            text = ""
        for raw in text.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            _emit(_format_line(obj))

    f = _open_at_end(inbox)
    try:
        while True:
            if iterations is not None and iters >= iterations:
                return 0
            iters += 1

            line = f.readline()
            if line:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError:
                    # Skip malformed line, keep tailing.
                    continue
                _emit(_format_line(obj))
                continue

            # No new bytes — check for truncation / rotation.
            try:
                size = inbox.stat().st_size
            except FileNotFoundError:
                # File was rotated away. Wait for the replacement.
                f.close()
                while not inbox.exists():
                    if iterations is not None and iters >= iterations:
                        return 0
                    time.sleep(poll_interval)
                    iters += 1
                f = inbox.open("r", encoding="utf-8")
                # Read from start of the rotated file (treat as new inbox).
                continue

            pos = f.tell()
            if size < pos:
                # File got truncated — re-read from top.
                f.seek(0)
                continue

            time.sleep(poll_interval)
    finally:
        try:
            f.close()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tether.hooks.inbox_tail",
        description=(
            "Tail the Telegram inbox JSONL and emit one line per new "
            "message. Designed to be invoked by Claude Code's Monitor "
            "tool to wake idle sessions when Telegram messages arrive."
        ),
    )
    p.add_argument("--inbox", required=True, help="path to inbox JSONL")
    p.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="seconds between filesystem polls (default: 1.0)",
    )
    p.add_argument(
        "--emit-existing",
        action="store_true",
        help="emit existing inbox lines on startup (test/debug only)",
    )
    args = p.parse_args(argv)

    return tail_loop(
        Path(args.inbox),
        poll_interval=args.poll_interval,
        emit_existing=args.emit_existing,
    )


if __name__ == "__main__":
    sys.exit(main())
