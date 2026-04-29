"""Transport abstraction — Telegram is the default, Slack ships in v0.3.

The Tether client is transport-agnostic. Today: Telegram. Tomorrow:
Slack (this module), then Discord, then SMS, then Signal — all behind
the same `send / poll / whoami` interface so call sites stay
identical.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Protocol


# ---------------------------------------------------------------------------
# Common Message dataclass — every transport returns these
# ---------------------------------------------------------------------------
@dataclass
class TransportMessage:
    """A single inbound message, normalized across transports."""
    update_id: str               # transport-native id, kept as string for portability
    chat_id: str                 # channel/chat where it arrived
    chat_type: str               # transport-specific, e.g. "private", "channel"
    from_user: str | None
    from_user_id: str | None
    text: str
    received_at_utc: str         # ISO8601


# ---------------------------------------------------------------------------
# Transport protocol — all backends implement these three methods
# ---------------------------------------------------------------------------
class Transport(Protocol):
    """Bidirectional comms transport.

    Implementations:
      - TelegramTransport (telegram.py — the v0.1/0.2 default)
      - SlackTransport (this module)
      - DiscordTransport, SMSTransport, ... (future)
    """
    name: str

    def send(self, text: str, *, silent: bool = False,
             chat_id: str | None = None) -> dict: ...

    def poll_once(self, *, timeout: int = 0) -> list[TransportMessage]: ...

    def listen(self, *, poll_timeout: int = 30,
               sleep_on_error: float = 5.0) -> Iterator[TransportMessage]: ...

    def whoami(self) -> dict: ...


# ---------------------------------------------------------------------------
# Slack transport
# ---------------------------------------------------------------------------
class SlackTransport:
    """Slack bidirectional transport. Uses Web API (chat.postMessage)
    for outbound + Socket Mode for inbound.

    Setup (one-time):
      1. Create a Slack app at https://api.slack.com/apps.
      2. Add OAuth scopes: chat:write, channels:history, im:history,
         channels:read, app_mentions:read.
      3. Install the app to your workspace; copy the *Bot User OAuth
         Token* (xoxb-...) → SLACK_BOT_TOKEN.
      4. Enable Socket Mode in the app dashboard; generate an *App
         Level Token* with scope connections:write (xapp-...) →
         SLACK_APP_TOKEN.
      5. Subscribe to bot events: message.channels, message.im,
         app_mention.
      6. Pick a default channel for outbound messages → SLACK_CHANNEL_ID.

    Then:
      tether init --transport slack
    or set env vars: SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_CHANNEL_ID.
    """

    name = "slack"

    def __init__(
        self,
        *,
        bot_token: str | None = None,
        app_token: str | None = None,
        channel_id: str | None = None,
        state_dir: Path | str | None = None,
    ) -> None:
        try:
            from slack_sdk import WebClient
            from slack_sdk.socket_mode import SocketModeClient
            from slack_sdk.socket_mode.request import SocketModeRequest  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "slack transport requires the 'slack-sdk' package. "
                "Install with: pip install 'tether[slack]'"
            ) from e
        self._WebClient = WebClient
        self._SocketModeClient = SocketModeClient

        self.bot_token = bot_token or os.environ.get("SLACK_BOT_TOKEN")
        self.app_token = app_token or os.environ.get("SLACK_APP_TOKEN")
        self.channel_id = channel_id or os.environ.get("SLACK_CHANNEL_ID")
        if not self.bot_token:
            raise ValueError(
                "SLACK_BOT_TOKEN missing. Set env var or pass bot_token=. "
                "See SlackTransport docstring for setup."
            )
        if not self.channel_id:
            raise ValueError(
                "SLACK_CHANNEL_ID missing. Pick a channel and set env var "
                "or pass channel_id=."
            )
        self._client = WebClient(token=self.bot_token)
        # Pre-buffered messages from Socket Mode listener; drained by poll_once.
        self._pending: list[TransportMessage] = []
        self._socket: Any = None

    # ----------------- send -----------------
    def send(self, text: str, *, silent: bool = False,
             chat_id: str | None = None) -> dict:
        """Send a message to a Slack channel.

        `silent` is mapped to `unfurl_links=False, unfurl_media=False`
        — Slack's notification semantics differ; we approximate.
        """
        target = chat_id or self.channel_id
        try:
            resp = self._client.chat_postMessage(
                channel=target,
                text=text,
                unfurl_links=not silent,
                unfurl_media=not silent,
            )
        except Exception as e:
            raise RuntimeError(f"slack send failed: {e}") from e
        return dict(resp.data) if hasattr(resp, "data") else dict(resp)

    # ----------------- poll -----------------
    def _ensure_socket(self) -> None:
        """Lazy-connect the Socket Mode client + register message handler."""
        if self._socket is not None:
            return
        if not self.app_token:
            raise ValueError(
                "Inbound polling requires SLACK_APP_TOKEN (xapp-...). "
                "Set env var or pass app_token=. Without it, send-only "
                "is supported."
            )
        sock = self._SocketModeClient(
            app_token=self.app_token, web_client=self._client)

        def handler(client, req):
            if req.type == "events_api":
                event = (req.payload or {}).get("event", {})
                if event.get("type") in ("message", "app_mention"):
                    if event.get("subtype"):
                        # bot_message, message_changed, etc — skip noise.
                        return
                    msg = TransportMessage(
                        update_id=str(event.get("ts", "")),
                        chat_id=str(event.get("channel", "")),
                        chat_type="channel",
                        from_user=event.get("user", None),
                        from_user_id=event.get("user", None),
                        text=event.get("text", "") or "",
                        received_at_utc=time.strftime(
                            "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                    )
                    self._pending.append(msg)
                client.send_socket_mode_response({"envelope_id": req.envelope_id})

        sock.socket_mode_request_listeners.append(handler)
        sock.connect()
        self._socket = sock

    def poll_once(self, *, timeout: int = 0) -> list[TransportMessage]:
        self._ensure_socket()
        if timeout > 0 and not self._pending:
            time.sleep(min(timeout, 30))
        msgs = list(self._pending)
        self._pending.clear()
        return msgs

    def listen(self, *, poll_timeout: int = 30,
               sleep_on_error: float = 5.0) -> Iterator[TransportMessage]:
        self._ensure_socket()
        while True:
            try:
                if self._pending:
                    yield from self.poll_once()
                else:
                    time.sleep(1)
            except Exception:
                time.sleep(sleep_on_error)

    # ----------------- diagnostics -----------------
    def whoami(self) -> dict:
        try:
            resp = self._client.auth_test()
            return dict(resp.data) if hasattr(resp, "data") else dict(resp)
        except Exception as e:
            raise RuntimeError(f"slack auth_test failed: {e}") from e


# ---------------------------------------------------------------------------
# Transport factory
# ---------------------------------------------------------------------------
def make_transport(name: str, **kwargs) -> Transport:
    """Look up a transport by name and construct it.

    Supported names:
      - "telegram"  — the default (returns the existing Tether client)
      - "slack"     — SlackTransport

    Future names (not yet implemented):
      - "discord"
      - "sms" / "twilio"
      - "signal"
    """
    name = name.lower()
    if name == "telegram":
        # Avoid circular import — Tether is already the Telegram transport.
        from .client import Tether
        return Tether(**kwargs)
    if name == "slack":
        return SlackTransport(**kwargs)
    raise ValueError(
        f"unknown transport {name!r}. supported: 'telegram', 'slack'. "
        "Other transports (discord/sms/signal) are on the roadmap."
    )
