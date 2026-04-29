# Recipes

Patterns for common tether use cases. Each recipe is self-contained.

## Recipe 1 — Heartbeat every N minutes

Send a "still alive" ping at a fixed cadence. Useful for ops dashboards
where silence is scary.

```python
import time
from tether import Tether

p = Tether()

while True:
    p.send(f"💓 alive at {time.strftime('%H:%M:%S')}", silent=True)
    time.sleep(300)   # 5 min
```

`silent=True` suppresses the notification sound; the message still
appears, but doesn't buzz the phone.

## Recipe 2 — Build alert with diff context

Send build status + a snippet of the failing test output:

```python
import subprocess
from tether import Tether

p = Tether()
result = subprocess.run(["pytest"], capture_output=True, text=True)
if result.returncode == 0:
    p.send("✅ tests green")
else:
    fail_lines = [ln for ln in result.stdout.splitlines() if "FAIL" in ln]
    p.send("❌ tests red\n" + "\n".join(fail_lines[:10]))
```

## Recipe 3 — Q&A loop (operator answers a question)

```python
from tether import Tether

p = Tether()
p.send("Should I deploy to prod? (yes/no)")

# Drain any stale messages first
p.poll_once()

# Now wait for the actual answer
for msg in p.listen():
    answer = msg.text.strip().lower()
    if answer in ("yes", "y"):
        p.send("Deploying.")
        deploy()
        break
    elif answer in ("no", "n"):
        p.send("Holding off.")
        break
    else:
        p.send(f"Didn't understand {answer!r}. Reply 'yes' or 'no'.")
```

## Recipe 4 — Run-only-when-allowed gate

Block the agent until the operator types `go`:

```python
from tether import Tether

p = Tether()
p.send("Waiting for `go` to start.")

for msg in p.listen():
    if msg.text.strip().lower() == "go":
        p.send("Starting.")
        run_the_thing()
        p.send("Done.")
        break
```

## Recipe 5 — Multi-channel fan-out

Fire alerts to two operators (e.g. day shift + on-call) when severity
crosses a threshold:

```python
from tether import Tether

p = Tether()  # default chat = day shift
ON_CALL = 222222222

def alert(text, severity):
    p.send(text)
    if severity == "critical":
        p.send("🚨 " + text, chat_id=ON_CALL)
```

## Recipe 6 — Replace stdout for a script

Capture stdout-style logs and ship them piecewise:

```python
import io, sys
from tether import Tether

p = Tether()

class TelegramTee(io.TextIOBase):
    """Mirror writes to terminal AND batch into a 1KB Telegram message."""
    def __init__(self, downstream, tether, batch_size=1000):
        self.downstream = downstream
        self.tether = tether
        self.buf = ""
        self.batch_size = batch_size
    def write(self, data):
        self.downstream.write(data)
        self.buf += data
        if len(self.buf) >= self.batch_size:
            self.flush()
        return len(data)
    def flush(self):
        if self.buf.strip():
            self.tether.send("```\n" + self.buf + "\n```", parse_mode="Markdown")
        self.buf = ""

sys.stdout = TelegramTee(sys.__stdout__, p)
print("hello — this lands on Telegram too")
```

## Recipe 7 — Prefer tether only when remote, else stdout

```python
import os
from tether import Tether, ConfigError

class MaybeTether:
    def __init__(self):
        try:
            self.p = Tether()
        except ConfigError:
            self.p = None
    def send(self, text):
        if self.p is not None:
            self.p.send(text)
        else:
            print(text)

m = MaybeTether()
m.send("works either way")
```

## Recipe 8 — Edit-in-place status updates

Telegram supports message editing. `Tether.send` returns the message id;
use it with `editMessageText`:

```python
from tether import Tether
import requests

p = Tether()
res = p.send("Step 1/3...")
mid = res["message_id"]

# Use the raw API for editMessageText (not yet wrapped in Tether).
def edit(new_text):
    requests.post(
        f"{p.api_base}/bot{p.bot_token}/editMessageText",
        json={"chat_id": p.chat_id, "message_id": mid,
              "text": new_text, "parse_mode": "Markdown"},
    )

edit("Step 2/3...")
edit("Step 3/3 done ✅")
```
