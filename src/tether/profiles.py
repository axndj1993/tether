"""Profile system — multiple bots/chats/transports per machine.

Concept: each *profile* is one named bot + chat + transport. Different
agents (futures-bot, code-review, dev-experiments) tether to different
profiles so their messages don't collide in one channel.

Resolution priority (Tether picks the first hit):

  1. Explicit ctor arg / CLI flag (`Tether(profile="X")` / `--profile X`)
  2. `TETHER_PROFILE` env var
  3. `.tether` file in CWD or any parent dir (auto-detected, like
     `.python-version` from pyenv)
  4. `default` profile

Backward compat: v0.3 users with `TELEGRAM_BOT_TOKEN` env vars or a
flat `~/.tether/config.toml` keep working — that becomes the
"default" profile transparently.

Storage layout:

    ~/.tether/
        config.toml                    # global settings + 'default' fallback
        profiles/
            futures-bot/
                config.toml            # transport, bot_token, chat_id
                offset.json            # per-profile polling state
            code-review/
                ...
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_HOME = Path.home() / ".tether"
DOT_TETHER_FILENAME = ".tether"
DEFAULT_PROFILE_NAME = "default"


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        try:
            import tomllib
        except ImportError:  # py<3.11
            import tomli as tomllib  # type: ignore
        with path.open("rb") as fh:
            return dict(tomllib.load(fh) or {})
    except Exception:
        return {}


def _find_dot_tether(start: Path | None = None) -> str | None:
    """Walk upward from CWD looking for `.tether` file. Returns the
    profile name written inside, or None. The file format is one line
    with the profile name (whitespace stripped)."""
    cur = (start or Path.cwd()).resolve()
    for _ in range(20):   # walk up at most 20 levels — defensive guard
        candidate = cur / DOT_TETHER_FILENAME
        if candidate.is_file():
            try:
                name = candidate.read_text(encoding="utf-8").strip()
                if name:
                    return name
            except OSError:
                return None
        if cur.parent == cur:
            return None
        cur = cur.parent
    return None


@dataclass
class ProfileResolution:
    """How a profile was picked. Useful for `tether profiles current`."""
    name: str
    source: str          # "ctor" | "env" | "dot_tether" | "default"
    dot_tether_path: str | None = None


def resolve_profile(*, explicit: str | None = None,
                    state_home: Path | None = None) -> ProfileResolution:
    """Pick the active profile per the priority chain."""
    if explicit:
        return ProfileResolution(name=explicit, source="ctor")
    env = os.environ.get("TETHER_PROFILE")
    if env:
        return ProfileResolution(name=env, source="env")
    dot = _find_dot_tether()
    if dot:
        # Find which dir the .tether came from for diagnostics.
        cur = Path.cwd().resolve()
        path = None
        for _ in range(20):
            if (cur / DOT_TETHER_FILENAME).is_file():
                path = str(cur / DOT_TETHER_FILENAME)
                break
            if cur.parent == cur:
                break
            cur = cur.parent
        return ProfileResolution(name=dot, source="dot_tether",
                                  dot_tether_path=path)
    return ProfileResolution(name=DEFAULT_PROFILE_NAME, source="default")


def profile_dir(name: str, *, state_home: Path | None = None) -> Path:
    """Return the on-disk dir for a profile. Created on first access."""
    home = Path(state_home) if state_home else DEFAULT_HOME
    p = home / "profiles" / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def profile_config_path(name: str, *, state_home: Path | None = None) -> Path:
    return profile_dir(name, state_home=state_home) / "config.toml"


def profile_state_path(name: str, *, state_home: Path | None = None) -> Path:
    return profile_dir(name, state_home=state_home) / "offset.json"


def load_profile_config(name: str, *, state_home: Path | None = None) -> dict:
    """Read a profile's config. Returns empty dict if not configured.

    For the special `default` profile, also fall back to the global
    `~/.tether/config.toml` (backward-compat with v0.3 users who set
    that file before profiles existed).
    """
    cfg = _load_toml(profile_config_path(name, state_home=state_home))
    if cfg:
        return cfg
    if name == DEFAULT_PROFILE_NAME:
        # v0.3 backward-compat: flat config at ~/.tether/config.toml.
        home = Path(state_home) if state_home else DEFAULT_HOME
        return _load_toml(home / "config.toml")
    return {}


def list_profiles(*, state_home: Path | None = None) -> list[str]:
    """List all configured profile names."""
    home = Path(state_home) if state_home else DEFAULT_HOME
    profiles_root = home / "profiles"
    if not profiles_root.is_dir():
        # Default-only setup — show 'default' if there's any v0.3
        # config (env or flat file).
        if (home / "config.toml").exists() or os.environ.get("TELEGRAM_BOT_TOKEN"):
            return [DEFAULT_PROFILE_NAME]
        return []
    return sorted(p.name for p in profiles_root.iterdir() if p.is_dir())


def set_active_profile(name: str, *, repo_root: Path | None = None) -> Path:
    """Write `.tether` to `repo_root` (default CWD). Future invocations
    inside that directory tree pick up the profile automatically."""
    target = (Path(repo_root) if repo_root else Path.cwd()) / DOT_TETHER_FILENAME
    target.write_text(f"{name}\n", encoding="utf-8")
    return target


def write_profile_config(
    name: str,
    config: dict[str, Any],
    *,
    state_home: Path | None = None,
) -> Path:
    """Write a profile's config.toml. Used by `tether init --profile X`."""
    path = profile_config_path(name, state_home=state_home)
    lines: list[str] = []
    for k, v in config.items():
        if isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        elif isinstance(v, bool):
            lines.append(f'{k} = {str(v).lower()}')
        else:
            lines.append(f'{k} = {v}')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def delete_profile(name: str, *, state_home: Path | None = None) -> bool:
    """Remove a profile's directory. Returns True if removed, False if
    didn't exist. Does NOT touch `.tether` files referencing this name
    — the caller should warn the user if any exist."""
    home = Path(state_home) if state_home else DEFAULT_HOME
    p = home / "profiles" / name
    if not p.is_dir():
        return False
    import shutil
    shutil.rmtree(p)
    return True


# ---------------------------------------------------------------------------
# Polling-state helpers — per-profile offset persistence
# ---------------------------------------------------------------------------
def load_offset(name: str, *, state_home: Path | None = None) -> int:
    p = profile_state_path(name, state_home=state_home)
    try:
        return int(json.loads(p.read_text()).get("offset", 0))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return 0


def save_offset(name: str, offset: int, *, state_home: Path | None = None) -> None:
    p = profile_state_path(name, state_home=state_home)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"offset": offset}))
    tmp.replace(p)
