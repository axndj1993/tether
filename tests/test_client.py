"""Tests for tether.client. Telegram API is mocked via `responses`.

Tests intentionally exercise the real public surface (send, poll_once,
listen, offset persistence, config resolution) — no internals are
peeked at.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import responses

from tether import ConfigError, Message, Tether, TetherError


BOT = "12345:test"
CHAT = 99


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "tether_state"


@pytest.fixture
def p(state_dir: Path) -> Tether:
    return Tether(bot_token=BOT, chat_id=CHAT, state_dir=state_dir)


# ----------------------------------------------------------------------
# Config resolution
# ----------------------------------------------------------------------
def test_missing_token_raises_config_error(monkeypatch, state_dir):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with patch("tether.client.DEFAULT_STATE_DIR", state_dir):
        with pytest.raises(ConfigError, match="bot token"):
            Tether(state_dir=state_dir)


def test_missing_chat_raises_config_error(monkeypatch, state_dir):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with patch("tether.client.DEFAULT_STATE_DIR", state_dir):
        with pytest.raises(ConfigError, match="chat id"):
            Tether(bot_token=BOT, state_dir=state_dir)


def test_chat_id_must_be_int(state_dir):
    with pytest.raises(ConfigError, match="chat_id must be an integer"):
        Tether(bot_token=BOT, chat_id="not-a-number", state_dir=state_dir)


def test_env_var_resolution(monkeypatch, state_dir):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(CHAT))
    p = Tether(state_dir=state_dir)
    assert p.bot_token == BOT
    assert p.chat_id == CHAT


# ----------------------------------------------------------------------
# send
# ----------------------------------------------------------------------
@responses.activate
def test_send_posts_to_correct_url(p: Tether):
    responses.add(
        responses.POST,
        f"https://api.telegram.org/bot{BOT}/sendMessage",
        json={"ok": True, "result": {"message_id": 42}},
    )
    out = p.send("hello")
    assert out["message_id"] == 42
    body = json.loads(responses.calls[0].request.body)
    assert body["chat_id"] == CHAT
    assert body["text"] == "hello"
    assert body["parse_mode"] == "Markdown"


@responses.activate
def test_send_api_failure_raises_tether_error(p: Tether):
    responses.add(
        responses.POST,
        f"https://api.telegram.org/bot{BOT}/sendMessage",
        json={"ok": False, "description": "unauthorized"},
    )
    with pytest.raises(TetherError, match="unauthorized"):
        p.send("hi")


# ----------------------------------------------------------------------
# poll_once + offset persistence
# ----------------------------------------------------------------------
def _make_update(update_id: int, text: str) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": CHAT, "type": "private"},
            "from": {"id": CHAT, "first_name": "Tester"},
            "text": text,
        },
    }


@responses.activate
def test_poll_once_returns_messages_and_advances_offset(p: Tether):
    responses.add(
        responses.POST,
        f"https://api.telegram.org/bot{BOT}/getUpdates",
        json={"ok": True, "result": [
            _make_update(101, "hi"),
            _make_update(102, "/status"),
        ]},
    )
    msgs = p.poll_once()
    assert len(msgs) == 2
    assert isinstance(msgs[0], Message)
    assert msgs[0].text == "hi"
    assert msgs[1].text == "/status"
    # Offset advances to max(update_id) + 1.
    assert json.loads((p.state_dir / "offset.json").read_text())["offset"] == 103


@responses.activate
def test_poll_once_persists_offset_atomically(p: Tether):
    responses.add(
        responses.POST,
        f"https://api.telegram.org/bot{BOT}/getUpdates",
        json={"ok": True, "result": [_make_update(7, "first")]},
    )
    p.poll_once()
    assert (p.state_dir / "offset.json").exists()
    # No leftover .tmp file (atomic rename succeeded).
    assert not (p.state_dir / "offset.tmp").exists()


@responses.activate
def test_poll_once_skips_non_message_updates(p: Tether):
    """E.g. callback queries don't have a 'message' field — should yield 0
    messages but still advance the offset."""
    responses.add(
        responses.POST,
        f"https://api.telegram.org/bot{BOT}/getUpdates",
        json={"ok": True, "result": [
            {"update_id": 200, "callback_query": {"id": "cb"}},
        ]},
    )
    msgs = p.poll_once()
    assert msgs == []
    assert json.loads((p.state_dir / "offset.json").read_text())["offset"] == 201


@responses.activate
def test_poll_once_uses_stored_offset(p: Tether):
    (p.state_dir / "offset.json").write_text(json.dumps({"offset": 555}))

    captured = {}
    def callback(req):
        captured["body"] = json.loads(req.body)
        return (200, {}, json.dumps({"ok": True, "result": []}))
    responses.add_callback(
        responses.POST,
        f"https://api.telegram.org/bot{BOT}/getUpdates",
        callback=callback,
    )
    p.poll_once()
    assert captured["body"]["offset"] == 555
