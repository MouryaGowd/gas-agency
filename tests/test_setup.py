import os
import stat
import sys

import setup_env


def test_first_run_prompts_and_saves(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    answers = iter(["test-secret-key", "pw-for-dealer", "pw-for-dealer"])  # key, password, confirm
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(setup_env.getpass, "getpass", lambda prompt="": next(answers))
    monkeypatch.setattr("builtins.input", lambda prompt="": "Dealer@Example.COM")
    assert setup_env.main(env) == 0
    saved = setup_env.read_env(env)
    assert saved == {"SECRET_KEY": "test-secret-key", "ADMIN_EMAIL": "dealer@example.com",
                     "ADMIN_PASSWORD": "pw-for-dealer"}
    if os.name != "nt":  # Windows has no POSIX permission bits
        assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_empty_key_generates_random(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    answers = iter(["", "pw", "pw"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(setup_env.getpass, "getpass", lambda prompt="": next(answers))
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    setup_env.main(env)
    assert len(setup_env.read_env(env)["SECRET_KEY"]) >= 32


def test_existing_key_is_not_asked_again(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("SECRET_KEY=keep-me\n")
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("asked")))
    assert setup_env.main(env) == 0
    assert setup_env.read_env(env)["SECRET_KEY"] == "keep-me"


def test_no_terminal_and_no_key_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert setup_env.main(tmp_path / ".env") == 1
