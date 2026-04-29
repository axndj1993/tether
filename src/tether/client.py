"""Core tether client — Telegram bot API wrapper, offset-persistent."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import requests


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class TetherError(Exception):
    """Base error for tether. Catch this to handle any tether failure."""


class ConfigError(TetherError):
    """Raised when bot token / chat id is missing or malformed."""


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------
@dataclass
class Message:
    """A single inbound message from Telegram."""
    update_id: int
    chat_id: int
    chat_type: str          # "private", "group", "supergroup", "channel"
    from_user: str | None   # display name, may be None for anonymous
    from_user_id: int | None
    text: str
    edited: bool
    received_at_utc: str    # ISO8601

    @classmethod
    def from_update(cls, update: dict) -> "Message | None":
        """Parse a Telegram getUpdates entry into a Message. Returns None
        for non-message updates (e.g. callback queries, channel posts)."""
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return None
        chat = msg.get("chat") or {}
        from_user = msg.get("from") or {}
        return cls(
            update_id=update["update_id"],
            chat_id=chat.get("id", 0),
            chat_type=chat.get("type", "unknown"),
            from_user=(from_user.get("first_name") or from_user.get("username")),
            from_user_id=from_user.get("id"),
            text=msg.get("text", ""),
            edited="edited_message" in update,
            received_at_utc=time.strftime("%Y-%m-%dT%H:%M:%S+00:00",
                                         time.gmtime()),
        )


# ---------------------------------------------------------------------------
# Tether
# ---------------------------------------------------------------------------
DEFAULT_API_BASE = "https://api.telegram.org"
DEFAULT_STATE_DIR = Path.home() / ".tether"


class Tether:
    """Telegram tether client.

    Reads bot token + chat id from (in order):
      1. constructor args (`bot_token=`, `chat_id=`)
      2. env vars `$TELEGRAM_BOT_TOKEN`, `$TELEGRAM_CHAT_ID`
      3. `~/.tether/config.toml` keys `bot_token`, `chat_id`

    Offset (next-update pointer) is persisted to
    `state_dir/offset.json` so polling resumes across restarts.

    Examples:
        p = Tether()
        p.send("hello")
        for m in p.listen(timeout=30):
            print(m.text)
    """

    def __init__(
        self,
        *,
        bot_token: str | None = None,
        chat_id: int | str | None = None,
        state_dir: Path | str | None = None,
        api_base: str = DEFAULT_API_BASE,
        session: requests.Session | None = None,
        profile: str | None = None,
    ) -> None:
        # ---- Profile resolution (v0.4) ----------------------------------
        # If the caller didn't pass explicit token/chat creds, try to
        # resolve a profile and load its config. Backward-compatible:
        # v0.3 users with TELEGRAM_BOT_TOKEN env or a flat
        # ~/.tether/config.toml continue to work via the 'default'
        # profile fallback.
        from .profiles import (resolve_profile, load_profile_config,
                                profile_dir as _profile_dir)
        prof = resolve_profile(explicit=profile)
        self.profile_name = prof.name
        prof_cfg = load_profile_config(prof.name)

        self.bot_token = (bot_token
                           or os.environ.get("TELEGRAM_BOT_TOKEN")
                           or prof_cfg.get("bot_token"))
        self.chat_id = (chat_id
                         if chat_id is not None
                         else (os.environ.get("TELEGRAM_CHAT_ID")
                               or prof_cfg.get("chat_id")))

        if not self.bot_token:
            raise ConfigError(
                f"No bot token (profile={prof.name!r}, source={prof.source}). "
                "Set $TELEGRAM_BOT_TOKEN or pass bot_token=, "
                f"or run `tether init --profile {prof.name}` to set up."
            )
        if self.chat_id is None:
            raise ConfigError(
                f"No chat id (profile={prof.name!r}, source={prof.source}). "
                "Set $TELEGRAM_CHAT_ID or pass chat_id=, "
                f"or run `tether init --profile {prof.name}` to set up."
            )
        try:
            self.chat_id = int(self.chat_id)
        except (TypeError, ValueError) as e:
            raise ConfigError(f"chat_id must be an integer, got {self.chat_id!r}") from e

        self.api_base = api_base.rstrip("/")
        self._session = session or requests.Session()
        # Per-profile state dir. Explicit `state_dir=` override wins
        # (used by tests). Otherwise: profile-specific subdir under
        # ~/.tether/profiles/<name>/.
        if state_dir is not None:
            self.state_dir = Path(state_dir)
        else:
            self.state_dir = _profile_dir(prof.name)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._offset_path = self.state_dir / "offset.json"

    # ----------------- config resolution (legacy helper) -----------------
    @staticmethod
    def _resolve(toml_key: str, env_key: str) -> str | None:
        """Legacy v0.1-v0.3 resolver. Kept for any external code that
        was poking at this private method. New code should use the
        profiles module instead."""
        env = os.environ.get(env_key)
        if env:
            return env
        cfg_path = DEFAULT_STATE_DIR / "config.toml"
        if not cfg_path.exists():
            return None
        try:
            try:
                import tomllib
            except ImportError:  # py<3.11
                import tomli as tomllib  # type: ignore
            with cfg_path.open("rb") as fh:
                return (tomllib.load(fh) or {}).get(toml_key)
        except Exception:
            return None

    # ----------------- offset persistence -----------------
    def _load_offset(self) -> int:
        try:
            return int(json.loads(self._offset_path.read_text()).get("offset", 0))
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return 0

    def _save_offset(self, offset: int) -> None:
        # Atomic write via rename to avoid half-written state on crash.
        tmp = self._offset_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"offset": offset}))
        tmp.replace(self._offset_path)

    # ----------------- API helpers -----------------
    def _api(self, method: str, **params: Any) -> dict:
        url = f"{self.api_base}/bot{self.bot_token}/{method}"
        try:
            resp = self._session.post(url, json=params, timeout=60)
        except requests.RequestException as e:
            raise TetherError(f"telegram api {method} failed: {e}") from e
        try:
            data = resp.json()
        except ValueError as e:
            raise TetherError(f"telegram api {method} non-json: {resp.text!r}") from e
        if not data.get("ok"):
            raise TetherError(
                f"telegram api {method} returned not-ok: "
                f"{data.get('description') or data}"
            )
        return data.get("result", {})

    # ----------------- send -----------------
    def send(self, text: str, *, parse_mode: str | None = "Markdown",
             chat_id: int | None = None, silent: bool = False) -> dict:
        """Send a text message. Returns the Telegram Message dict.

        Args:
            text: message body. Telegram MarkdownV1 (asterisks bold, _italic_).
            parse_mode: "Markdown", "MarkdownV2", "HTML", or None for plain.
            chat_id: override default chat id (multi-chat scenarios).
            silent: send without notification sound.
        """
        params: dict[str, Any] = {
            "chat_id": chat_id if chat_id is not None else self.chat_id,
            "text": text,
            "disable_notification": silent,
        }
        if parse_mode:
            params["parse_mode"] = parse_mode
        return self._api("sendMessage", **params)

    # ----------------- receive -----------------
    def poll_once(self, *, timeout: int = 0, allowed_updates: list[str] | None = None
                  ) -> list[Message]:
        """One-shot poll. Returns inbound Messages since last call,
        advances persisted offset on success.

        Args:
            timeout: long-poll seconds. 0 = immediate return.
            allowed_updates: filter list (default ["message", "edited_message"]).
        """
        offset = self._load_offset()
        result = self._api(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            allowed_updates=allowed_updates or ["message", "edited_message"],
        )
        msgs: list[Message] = []
        new_offset = offset
        for upd in result:
            new_offset = max(new_offset, upd["update_id"] + 1)
            m = Message.from_update(upd)
            if m is not None:
                msgs.append(m)
        if new_offset != offset:
            self._save_offset(new_offset)
        return msgs

    def listen(self, *, poll_timeout: int = 30,
               sleep_on_error: float = 5.0) -> Iterator[Message]:
        """Long-polling iterator. Yields Messages until interrupted.

        Wraps poll_once in a resilient loop — on transient API failures,
        sleeps `sleep_on_error` and retries. Caller should catch
        KeyboardInterrupt to exit cleanly.
        """
        while True:
            try:
                for m in self.poll_once(timeout=poll_timeout):
                    yield m
            except TetherError:
                time.sleep(sleep_on_error)

    # ----------------- diagnostics -----------------
    def whoami(self) -> dict:
        """Return getMe info — useful for `tether init` to verify the token."""
        return self._api("getMe")
