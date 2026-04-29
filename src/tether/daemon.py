"""Daemon mode — long-poll Telegram, append each inbound message to a JSONL.

Useful when an agent wants to consume messages out-of-band: agent reads
the JSONL when convenient, advances a "consumed" pointer to avoid
double-handling.
"""
from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path

from .client import Tether, TetherError


def run_daemon(
    *,
    out_path: Path | str,
    tether: Tether | None = None,
    poll_timeout: int = 30,
    print_to_stdout: bool = True,
) -> int:
    """Run the daemon. Returns when KeyboardInterrupt is received.

    Each inbound message is appended as one JSON object per line to
    `out_path`. The same line is also printed to stdout (so a
    `tail -f`-style consumer or a Claude Code Monitor can react).
    """
    p = tether or Tether()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"[tether] daemon listening as bot id={p.chat_id}, out={out}",
          file=sys.stderr, flush=True)
    try:
        for msg in p.listen(poll_timeout=poll_timeout):
            line = json.dumps(dataclasses.asdict(msg))
            with out.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            if print_to_stdout:
                print(line, flush=True)
    except KeyboardInterrupt:
        print("[tether] daemon stopped via SIGINT", file=sys.stderr)
        return 0
    except TetherError as e:
        print(f"[tether] daemon fatal: {e}", file=sys.stderr)
        return 1
    return 0


def drain(*, in_path: Path | str, consumed_path: Path | str | None = None) -> int:
    """Print all inbox lines newer than the consumed pointer; advance it.

    Pairs with `daemon` for at-most-once consumption: the daemon writes
    every inbound msg to `in_path`; `drain` reads + prints any unread
    lines and updates `consumed_path` so the next drain skips them.
    """
    in_p = Path(in_path)
    if not in_p.exists():
        return 0
    consumed_p = Path(consumed_path) if consumed_path else in_p.with_suffix(".consumed.json")
    last_consumed_id = -1
    if consumed_p.exists():
        try:
            last_consumed_id = int(json.loads(consumed_p.read_text()).get("update_id", -1))
        except (json.JSONDecodeError, ValueError):
            pass
    new_max = last_consumed_id
    count = 0
    with in_p.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            uid = int(obj.get("update_id", -1))
            if uid <= last_consumed_id:
                continue
            print(raw)
            new_max = max(new_max, uid)
            count += 1
    if count > 0:
        consumed_p.write_text(json.dumps({"update_id": new_max}))
    print(f"[tether] drained {count} message(s)", file=sys.stderr)
    return 0
