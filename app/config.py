import base64
from functools import lru_cache
from pathlib import Path
from typing import Self

from argon2 import extract_parameters
from argon2.exceptions import InvalidHashError
from argon2.low_level import Type
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01  # type: ignore[import-untyped]
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./data/habit_tracker.db"
    habit_tracker_username: str = Field(default="", max_length=64)
    habit_tracker_password_hash: SecretStr = SecretStr("")
    session_secret: SecretStr = Field(
        default=SecretStr("development-only-secret-change-me"), min_length=32
    )
    session_cookie_secure: bool = False
    session_ttl_hours: int = Field(default=24 * 30, ge=1, le=24 * 365)
    vapid_public_key: str = Field(default="", max_length=128)
    vapid_private_key: SecretStr = SecretStr("")
    vapid_subject: str = Field(default="", max_length=256)
    reminder_poll_seconds: int = Field(default=30, ge=5, le=300)
    reminder_lookback_minutes: int = Field(default=5, ge=1, le=60)

    @model_validator(mode="after")
    def validate_production_security(self) -> Self:
        if self.app_env == "production":
            if self.session_secret.get_secret_value() == "development-only-secret-change-me":
                raise ValueError("production requires a unique SESSION_SECRET")
            if not self.session_cookie_secure:
                raise ValueError("production requires SESSION_COOKIE_SECURE=true")
        return self

    def validate_auth_configuration(self) -> None:
        password_hash = self.habit_tracker_password_hash.get_secret_value()
        if not self.habit_tracker_username.strip() or not password_hash:
            raise RuntimeError("Authentication environment variables are not configured")
        try:
            parameters = extract_parameters(password_hash)
        except InvalidHashError as exc:
            raise RuntimeError("HABIT_TRACKER_PASSWORD_HASH is not a valid Argon2id hash") from exc
        if parameters.type is not Type.ID:
            raise RuntimeError("HABIT_TRACKER_PASSWORD_HASH must use Argon2id")

    @property
    def push_is_configured(self) -> bool:
        return bool(
            self.vapid_public_key
            and self.vapid_private_key.get_secret_value()
            and self.vapid_subject
        )

    def validate_push_configuration(self) -> None:
        private_key = self.vapid_private_key.get_secret_value()
        provided = (bool(self.vapid_public_key), bool(private_key), bool(self.vapid_subject))
        if not any(provided):
            return
        if not all(provided):
            raise RuntimeError(
                "VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, and VAPID_SUBJECT must be configured together"
            )
        if not (
            self.vapid_subject.startswith("mailto:")
            or self.vapid_subject.startswith("https://")
        ):
            raise RuntimeError("VAPID_SUBJECT must start with mailto: or https://")
        try:
            decoded_public = base64.urlsafe_b64decode(
                self.vapid_public_key + "=" * (-len(self.vapid_public_key) % 4)
            )
            vapid = Vapid01.from_string(private_key)
            derived_public = vapid.public_key.public_bytes(
                encoding=serialization.Encoding.X962,
                format=serialization.PublicFormat.UncompressedPoint,
            )
        except Exception as exc:
            raise RuntimeError("VAPID keys are invalid") from exc
        if decoded_public != derived_public:
            raise RuntimeError("VAPID public and private keys do not match")

    def ensure_sqlite_parent(self) -> None:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Habit Tracker currently supports SQLite database URLs only")
        database_path = self.database_url.removeprefix(prefix)
        if database_path == ":memory:" or database_path.startswith("file:"):
            return
        Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
