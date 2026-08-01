from collections.abc import Iterator

import pytest
from argon2 import PasswordHasher

from app.auth.hash_password import main


def test_hash_command_reads_interactively_and_prints_only_hash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    password = "a private password phrase"
    answers: Iterator[str] = iter((password, password))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))

    main()

    captured = capsys.readouterr()
    password_hash = captured.out.strip()
    assert captured.err == ""
    assert password not in captured.out
    assert password_hash.startswith("$argon2id$")
    assert PasswordHasher().verify(password_hash, password)


def test_hash_command_rejects_mismatch_without_printing_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers: Iterator[str] = iter(("first private password", "second private password"))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))

    with pytest.raises(SystemExit):
        main()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "first private password" not in captured.err
    assert "second private password" not in captured.err


def test_hash_command_accepts_eight_character_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    password = "12345678"
    answers: Iterator[str] = iter((password, password))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))

    main()

    password_hash = capsys.readouterr().out.strip()
    assert PasswordHasher().verify(password_hash, password)


def test_hash_command_rejects_password_shorter_than_eight_characters(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    password = "1234567"
    answers: Iterator[str] = iter((password, password))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))

    with pytest.raises(SystemExit):
        main()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "at least 8 characters" in captured.err
    assert password not in captured.err
