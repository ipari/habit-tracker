import pytest
from argon2 import PasswordHasher
from pydantic import ValidationError

from app.config import Settings


def test_production_rejects_insecure_cookie() -> None:
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        Settings(
            _env_file=None,
            app_env="production",
            session_secret="a-unique-production-secret-with-32-characters",
            session_cookie_secure=False,
        )


def test_production_rejects_default_secret() -> None:
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings(_env_file=None, app_env="production", session_cookie_secure=True)


def test_auth_configuration_requires_environment_credentials() -> None:
    with pytest.raises(RuntimeError, match="not configured"):
        Settings(_env_file=None).validate_auth_configuration()


def test_auth_configuration_rejects_non_argon2id_hash() -> None:
    settings = Settings(
        habit_tracker_username="owner",
        habit_tracker_password_hash="$argon2i$v=19$m=65536,t=3,p=4$c2FsdA$ZmFrZWhhc2g",
    )
    with pytest.raises(RuntimeError, match="Argon2id"):
        settings.validate_auth_configuration()


def test_auth_configuration_accepts_argon2id() -> None:
    password_hash = PasswordHasher().hash("a sufficiently long password")
    settings = Settings(
        habit_tracker_username="owner",
        habit_tracker_password_hash=password_hash,
    )
    settings.validate_auth_configuration()
    assert password_hash not in repr(settings)
