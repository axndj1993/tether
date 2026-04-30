"""Tests for tether.hooks.inbox_tail — the long-running Monitor companion."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from threading import Thread

import pytest  # noqa: F401  (used implicitly via fixtures)

from tether.hooks.inbox_tail import _format_line, tail_loop


def _write_lines(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )


def _append_line(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# _format_line — pure helper, must match inbox_drain.format_messages output
# ---------------------------------------------------------------------------
def test_format_line_with_ts_and_user() -> None:
    rec = {
        "received_at_utc": "2026-04-30T00:43:16Z",
        "from_user": "Gautam",
        "text": "Hi",
    }
    assert _format_line(rec) == "[2026-04-30T00:43:16Z] Gautam: Hi"


def test_format_line_falls_back_to_from_dict() -> None:
    rec = {"from": {"username": "op"}, "text": "yo"}
    assert _format_line(rec) == "op: yo"


def test_format_line_default_user_when_missing() -> None:
    rec = {"text": "anon"}
    assert _format_line(rec) == "operator: anon"


# ---------------------------------------------------------------------------
# tail_loop — emit_existing path (deterministic, no threading needed)
# ---------------------------------------------------------------------------
def test_tail_loop_emit_existing_replays_all_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    inbox = tmp_path / "inbox.jsonl"
    _write_lines(inbox, [
        {"from_user": "A", "text": "one"},
        {"from_user": "B", "text": "two"},
    ])
    rc = tail_loop(
        inbox,
        poll_interval=0.0,
        emit_existing=True,
        iterations=1,  # exit immediately after replay
    )
    assert rc == 0
    out = capsys.readouterr().out.splitlines()
    assert out == ["A: one", "B: two"]


def test_tail_loop_emit_existing_skips_malformed_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    inbox = tmp_path / "inbox.jsonl"
    inbox.write_text(
        "{\"from_user\": \"A\", \"text\": \"good\"}\n"
        "garbage{{{\n"
        "{\"from_user\": \"B\", \"text\": \"also good\"}\n",
        encoding="utf-8",
    )
    tail_loop(inbox, poll_interval=0.0, emit_existing=True, iterations=1)
    out = capsys.readouterr().out.splitlines()
    assert out == ["A: good", "B: also good"]


def test_tail_loop_waits_for_inbox_to_appear_then_exits(
    tmp_path: Path,
) -> None:
    """When the inbox doesn't exist and iterations is bounded, return 0."""
    inbox = tmp_path / "not_yet.jsonl"
    rc = tail_loop(
        inbox,
        poll_interval=0.0,
        emit_existing=False,
        iterations=2,  # bound the wait loop
    )
    assert rc == 0


# ---------------------------------------------------------------------------
# tail_loop — streaming new lines (threaded; fast poll interval)
# ---------------------------------------------------------------------------
def test_tail_loop_emits_appended_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    inbox = tmp_path / "inbox.jsonl"
    inbox.write_text("", encoding="utf-8")

    # Bound the loop so the test always terminates.
    def runner() -> None:
        tail_loop(inbox, poll_interval=0.01, iterations=200)

    t = Thread(target=runner, daemon=True)
    t.start()

    # Give the loop time to seek to EOF.
    time.sleep(0.1)

    _append_line(inbox, {"from_user": "X", "text": "live"})
    _append_line(inbox, {"from_user": "Y", "text": "also live"})

    # Wait up to ~2s for the loop to finish its bounded iterations.
    t.join(timeout=2.5)
    assert not t.is_alive(), "tail_loop didn't terminate within iteration bound"

    out = capsys.readouterr().out.splitlines()
    assert "X: live" in out
    assert "Y: also live" in out


# ---------------------------------------------------------------------------
# CLI argv smoke — `python -m tether.hooks.inbox_tail --help` / arg parse
# ---------------------------------------------------------------------------
def test_inbox_tail_help_runs(tmp_path: Path) -> None:
    """argparse + module entrypoint wiring is correct."""
    proc = subprocess.run(
        [sys.executable, "-m", "tether.hooks.inbox_tail", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--inbox" in proc.stdout
    assert "--poll-interval" in proc.stdout
