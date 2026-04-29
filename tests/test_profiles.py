"""Tests for tether.profiles — multi-profile resolution + per-profile state."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tether import profiles as p


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    """Isolate profile state to a tmp dir for each test."""
    fake_home = tmp_path / "tether_home"
    fake_home.mkdir()
    monkeypatch.setattr(p, "DEFAULT_HOME", fake_home)
    # Also unset any TETHER_PROFILE env that might leak in.
    monkeypatch.delenv("TETHER_PROFILE", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    return fake_home


def test_resolve_profile_default_when_nothing_configured(home, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    res = p.resolve_profile()
    assert res.name == "default"
    assert res.source == "default"


def test_resolve_profile_explicit_arg_wins(home, monkeypatch):
    monkeypatch.setenv("TETHER_PROFILE", "from_env")
    res = p.resolve_profile(explicit="from_arg")
    assert res.name == "from_arg"
    assert res.source == "ctor"


def test_resolve_profile_env_var(home, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TETHER_PROFILE", "futures-bot")
    res = p.resolve_profile()
    assert res.name == "futures-bot"
    assert res.source == "env"


def test_resolve_profile_dot_tether_in_cwd(home, monkeypatch, tmp_path):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".tether").write_text("code-review\n")
    monkeypatch.chdir(repo)
    res = p.resolve_profile()
    assert res.name == "code-review"
    assert res.source == "dot_tether"
    assert res.dot_tether_path is not None


def test_resolve_profile_dot_tether_in_parent(home, monkeypatch, tmp_path):
    """Walks up from CWD looking for .tether like .python-version."""
    repo = tmp_path / "myrepo"
    sub = repo / "src" / "deeply" / "nested"
    sub.mkdir(parents=True)
    (repo / ".tether").write_text("paren_repo\n")
    monkeypatch.chdir(sub)
    res = p.resolve_profile()
    assert res.name == "paren_repo"
    assert res.source == "dot_tether"


def test_resolve_priority_arg_beats_env_beats_file(home, monkeypatch, tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / ".tether").write_text("from_file\n")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("TETHER_PROFILE", "from_env")
    # ctor arg > env > file
    assert p.resolve_profile(explicit="from_arg").name == "from_arg"
    # env > file
    assert p.resolve_profile().name == "from_env"


def test_per_profile_state_isolation(home):
    p.save_offset("a", 100)
    p.save_offset("b", 200)
    assert p.load_offset("a") == 100
    assert p.load_offset("b") == 200
    # The two profiles must NOT share state.
    p.save_offset("a", 999)
    assert p.load_offset("a") == 999
    assert p.load_offset("b") == 200   # unchanged


def test_load_profile_config_returns_dict(home):
    p.write_profile_config("foo", {"transport": "telegram",
                                    "bot_token": "xxx",
                                    "chat_id": 42})
    cfg = p.load_profile_config("foo")
    assert cfg["transport"] == "telegram"
    assert cfg["bot_token"] == "xxx"
    assert cfg["chat_id"] == 42


def test_default_profile_falls_back_to_flat_config(home):
    """v0.3 backward-compat — flat ~/.tether/config.toml is read as
    the 'default' profile when no profile-specific config exists."""
    flat = home / "config.toml"
    flat.write_text(
        'bot_token = "legacy"\n'
        "chat_id = 7\n",
        encoding="utf-8",
    )
    cfg = p.load_profile_config("default")
    assert cfg["bot_token"] == "legacy"
    assert cfg["chat_id"] == 7


def test_list_profiles_empty(home):
    assert p.list_profiles() == []


def test_list_profiles_after_creation(home):
    p.write_profile_config("alpha", {"bot_token": "a"})
    p.write_profile_config("bravo", {"bot_token": "b"})
    names = p.list_profiles()
    assert "alpha" in names
    assert "bravo" in names


def test_set_active_profile_writes_dot_tether(home, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    path = p.set_active_profile("myproj")
    assert path.exists()
    assert path.read_text().strip() == "myproj"
    # Also: subsequent resolve should now pick this up.
    res = p.resolve_profile()
    assert res.name == "myproj"
    assert res.source == "dot_tether"


def test_delete_profile(home):
    p.write_profile_config("doomed", {"bot_token": "x"})
    assert "doomed" in p.list_profiles()
    assert p.delete_profile("doomed") is True
    assert "doomed" not in p.list_profiles()
    assert p.delete_profile("never_existed") is False
