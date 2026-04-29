"""tether — Telegram bidirectional comms for AI agents.

Your agent calls you. You can call back.

Quickstart:

    from tether import Tether

    p = Tether()                       # reads $TELEGRAM_BOT_TOKEN + $TELEGRAM_CHAT_ID
    p.send("Build started")           # outbound
    for msg in p.listen():            # inbound — yields Message
        if msg.text == "/status":
            p.send(get_status())
        elif msg.text == "/abort":
            break

Or as a daemon writing inbound to a JSONL file:

    tether daemon --out inbox.jsonl

CLI:

    tether send "Hello"
    tether drain
    tether daemon
    tether init    # config wizard
"""
from __future__ import annotations

from .client import Tether, Message, TetherError, ConfigError
from .transports import Transport, TransportMessage, SlackTransport, make_transport

__all__ = [
    "Tether", "Message", "TetherError", "ConfigError",
    "Transport", "TransportMessage", "SlackTransport", "make_transport",
]
__version__ = "0.4.0"
