"""Tests for tether.hooks.inbox_drain + install_claude_code_hooks."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tether.hooks.inbox_drain import (
    find_unread,
    format_messages,
    main as inbox_drain_main,
    write_consumed_atomic,
)
from tether.install import install_claude_code_hooks


# ---------------------------------------------------------------------------
# find_unread — both consumed-pointer formats
# ---------------------------------------------------------------------------
def _write_inbox(tmp: Path, lines: list[dict]) -> Path:
    p = tmp / "inbox.jsonl"
    p.write_text("\n".join(json.dumps(d) for d in lines) + "\n",
                 encoding="utf-8")
    return p


def test_find_unread_update_id_format(tmp_path: Path) -> None:
    inbox = _write_inbox(tmp_path, [
        {"update_id": 100, "text": "first"},
        {"update_id": 101, "text": "second"},
        {"update_id": 102, "text": "third"},
    ])
    consumed = tmp_path / "consumed.json"
    consumed.write_text(json.dumps({"update_id": 100}), encoding="utf-8")

    unread, new_consumed = find_unread(inbox, consumed)
    assert [m["text"] for m in unread] == ["second", "third"]
    assert new_consumed == {"update_id": 102}


def test_find_unread_line_format(tmp_path: Path) -> None:
    """futures-bot uses {'line': N}, not {'update_id': N}."""
    inbox = _write_inbox(tmp_path, [
        {"telegram_msg_id": 1, "text": "a"},
        {"telegram_msg_id": 2, "text": "b"},
        {"telegram_msg_id": 3, "text": "c"},
        {"telegram_msg_id": 4, "text": "d"},
    ])
    consumed = tmp_path / "consumed.json"
    consumed.write_text(json.dumps({"line": 2}), encoding="utf-8")

    unread, new_consumed = find_unread(inbox, consumed)
    assert [m["text"] for m in unread] == ["c", "d"]
    assert new_consumed == {"line": 4}


def test_find_unread_no_consumed_file_starts_from_zero(
    tmp_path: Path,
) -> None:
    inbox = _write_inbox(tmp_path, [
        {"telegram_msg_id": 1, "text": "a"},
        {"telegram_msg_id": 2, "text": "b"},
    ])
    consumed = tmp_path / "consumed.json"  # not created

    unread, new_consumed = find_unread(inbox, consumed)
    assert [m["text"] for m in unread] == ["a", "b"]
    assert new_consumed == {"line": 2}


def test_find_unread_empty_inbox(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox.jsonl"
    inbox.write_text("", encoding="utf-8")
    consumed = tmp_path / "consumed.json"
    unread, new_consumed = find_unread(inbox, consumed)
    assert unread == []
    assert new_consumed == {}


def test_find_unread_no_unread(tmp_path: Path) -> None:
    inbox = _write_inbox(tmp_path, [
        {"update_id": 5, "text": "old"},
    ])
    consumed = tmp_path / "consumed.json"
    consumed.write_text(json.dumps({"update_id": 5}), encoding="utf-8")

    unread, new_consumed = find_unread(inbox, consumed)
    assert unread == []
    assert new_consumed == {}


def test_find_unread_skips_malformed_lines(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox.jsonl"
    inbox.write_text(
        '{"telegram_msg_id": 1, "text": "ok"}\n'
        'not-json-line\n'
        '\n'  # blank
        '{"telegram_msg_id": 2, "text": "ok2"}\n',
        encoding="utf-8",
    )
    consumed = tmp_path / "consumed.json"
    unread, _ = find_unread(inbox, consumed)
    assert [m["text"] for m in unread] == ["ok", "ok2"]


def test_find_unread_corrupted_consumed_file(tmp_path: Path) -> None:
    """Bad JSON in consumed file shouldn't kill the hook."""
    inbox = _write_inbox(tmp_path, [{"telegram_msg_id": 1, "text": "a"}])
    consumed = tmp_path / "consumed.json"
    consumed.write_text("not valid json{{{", encoding="utf-8")

    unread, new_consumed = find_unread(inbox, consumed)
    assert len(unread) == 1
    assert new_consumed == {"line": 1}


# ---------------------------------------------------------------------------
# format_messages
# ---------------------------------------------------------------------------
def test_format_messages_with_timestamp_and_user() -> None:
    msgs = [
        {"received_at_utc": "2026-04-30T00:00:00Z",
         "from_user": "Alice", "text": "hello"},
        {"received_at_utc": "2026-04-30T00:01:00Z",
         "from_user": "Bob", "text": "world"},
    ]
    out = format_messages(msgs)
    assert "Alice: hello" in out
    assert "Bob: world" in out
    assert "[2026-04-30T00:00:00Z]" in out


def test_format_messages_falls_back_to_from_dict() -> None:
    msgs = [{"from": {"username": "user1"}, "text": "hi"}]
    out = format_messages(msgs)
    assert "user1: hi" in out


def test_format_messages_no_user_no_ts() -> None:
    out = format_messages([{"text": "anon"}])
    assert "operator: anon" in out


# ---------------------------------------------------------------------------
# write_consumed_atomic — survives missing parent dirs
# ---------------------------------------------------------------------------
def test_write_consumed_atomic_creates_parent(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "consumed.json"
    write_consumed_atomic(target, {"update_id": 42})
    assert json.loads(target.read_text(encoding="utf-8")) == {"update_id": 42}


# ---------------------------------------------------------------------------
# main() — hook event JSON output
# ---------------------------------------------------------------------------
def test_main_stop_event_with_unread(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    inbox = _write_inbox(tmp_path, [
        {"telegram_msg_id": 1, "from_user": "Op", "text": "ping"},
    ])
    consumed = tmp_path / "consumed.json"

    rc = inbox_drain_main([
        "--event", "Stop",
        "--inbox", str(inbox),
        "--consumed", str(consumed),
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "block"
    assert "ping" in out["reason"]
    assert "ack-first" in out["reason"]
    # Pointer advanced.
    assert json.loads(consumed.read_text(encoding="utf-8")) == {"line": 1}


def test_main_user_prompt_submit_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    inbox = _write_inbox(tmp_path, [
        {"telegram_msg_id": 1, "from_user": "Op", "text": "msg"},
    ])
    consumed = tmp_path / "consumed.json"

    rc = inbox_drain_main([
        "--event", "UserPromptSubmit",
        "--inbox", str(inbox),
        "--consumed", str(consumed),
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["continue"] is True
    hook_out = out["hookSpecificOutput"]
    assert hook_out["hookEventName"] == "UserPromptSubmit"
    assert "msg" in hook_out["additionalContext"]


def test_main_no_unread_emits_noop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    inbox = tmp_path / "inbox.jsonl"
    inbox.write_text("", encoding="utf-8")
    consumed = tmp_path / "consumed.json"

    rc = inbox_drain_main([
        "--event", "Stop",
        "--inbox", str(inbox),
        "--consumed", str(consumed),
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"continue": True, "suppressOutput": True}
    # Pointer NOT created (nothing to advance).
    assert not consumed.exists()


def test_main_missing_inbox_is_noop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """A fresh repo with no daemon yet should not break the hook."""
    rc = inbox_drain_main([
        "--event", "Stop",
        "--inbox", str(tmp_path / "nope.jsonl"),
        "--consumed", str(tmp_path / "nope.consumed.json"),
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"continue": True, "suppressOutput": True}


def test_main_runnable_as_module(tmp_path: Path) -> None:
    """python -m tether.hooks.inbox_drain --event Stop ... — end-to-end."""
    inbox = _write_inbox(tmp_path, [
        {"telegram_msg_id": 9, "from_user": "Op", "text": "shell"},
    ])
    consumed = tmp_path / "consumed.json"
    proc = subprocess.run(
        [sys.executable, "-m", "tether.hooks.inbox_drain",
         "--event", "Stop",
         "--inbox", str(inbox),
         "--consumed", str(consumed)],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["decision"] == "block"
    assert "shell" in out["reason"]


# ---------------------------------------------------------------------------
# install_claude_code_hooks
# ---------------------------------------------------------------------------
def test_install_hooks_creates_settings_when_absent(tmp_path: Path) -> None:
    written = install_claude_code_hooks(project_root=tmp_path)
    assert written == tmp_path / ".claude" / "settings.json"
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert "hooks" in data
    assert "Stop" in data["hooks"]
    assert "UserPromptSubmit" in data["hooks"]
    # The command embeds the marker so reinstall can identify it.
    stop_cmd = data["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert "tether.hooks.inbox_drain" in stop_cmd
    assert "--event Stop" in stop_cmd


def test_install_hooks_preserves_unrelated_settings(tmp_path: Path) -> None:
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    settings = settings_dir / "settings.json"
    settings.write_text(json.dumps({
        "permissions": {"allow": ["Bash(ls *)"]},
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "echo unrelated"}]}
            ]
        }
    }), encoding="utf-8")

    install_claude_code_hooks(project_root=tmp_path)
    data = json.loads(settings.read_text(encoding="utf-8"))
    # Unrelated permission preserved
    assert data["permissions"]["allow"] == ["Bash(ls *)"]
    # Unrelated Stop hook preserved (separate group)
    stop_groups = data["hooks"]["Stop"]
    commands = [
        h["command"]
        for grp in stop_groups
        for h in grp.get("hooks", [])
    ]
    assert "echo unrelated" in commands
    assert any("tether.hooks.inbox_drain" in c for c in commands)


def test_install_hooks_idempotent_replaces_prior_tether_entry(
    tmp_path: Path,
) -> None:
    install_claude_code_hooks(
        project_root=tmp_path,
        inbox_path="old_inbox.jsonl",
        consumed_path="old.consumed.json",
    )
    install_claude_code_hooks(
        project_root=tmp_path,
        inbox_path="new_inbox.jsonl",
        consumed_path="new.consumed.json",
    )
    data = json.loads(
        (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    stop_cmds = [
        h["command"]
        for grp in data["hooks"]["Stop"]
        for h in grp.get("hooks", [])
    ]
    # Exactly one tether entry remains.
    tether_cmds = [c for c in stop_cmds if "tether.hooks.inbox_drain" in c]
    assert len(tether_cmds) == 1
    assert "new_inbox.jsonl" in tether_cmds[0]
    assert "old_inbox.jsonl" not in tether_cmds[0]


def test_install_hooks_handles_corrupt_settings(tmp_path: Path) -> None:
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        "not-json{{{", encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        install_claude_code_hooks(project_root=tmp_path)


def test_install_hooks_settings_local_filename(tmp_path: Path) -> None:
    written = install_claude_code_hooks(
        project_root=tmp_path,
        settings_filename="settings.local.json",
    )
    assert written.name == "settings.local.json"
    assert written.exists()
