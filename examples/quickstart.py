"""Quickstart: a tiny bot loop that reacts to /status and /abort.

Run with:
    export TELEGRAM_BOT_TOKEN=...
    export TELEGRAM_CHAT_ID=...
    python examples/quickstart.py
"""
from tether import Tether

p = Tether()

p.send("*Quickstart bot up.* Send /status or /abort.")
try:
    for msg in p.listen(poll_timeout=30):
        text = msg.text.strip()
        if text == "/status":
            p.send("Still running. Nothing to report.")
        elif text == "/abort":
            p.send("Bye.")
            break
        else:
            # Ack-first convention: confirm receipt before doing the work.
            p.send(f"Got it: {text!r}")
            # ... do the work ...
            p.send("Done.")
except KeyboardInterrupt:
    p.send("Interrupted.")
