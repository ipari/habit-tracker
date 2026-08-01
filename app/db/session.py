import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings

MINIMUM_SQLITE_VERSIONS = ((3, 44, 6), (3, 50, 7), (3, 51, 3))


def sqlite_version_is_supported(version: tuple[int, int, int]) -> bool:
    if version[:2] == (3, 44):
        return version >= MINIMUM_SQLITE_VERSIONS[0]
    if version[:2] == (3, 50):
        return version >= MINIMUM_SQLITE_VERSIONS[1]
    return version >= MINIMUM_SQLITE_VERSIONS[2]


def require_supported_sqlite() -> None:
    version = tuple(int(part) for part in sqlite3.sqlite_version.split("."))
    if len(version) != 3 or not sqlite_version_is_supported(version):
        required = "3.51.3+, or a fixed 3.50.7/3.44.6 maintenance release"
        raise RuntimeError(f"Unsupported SQLite {sqlite3.sqlite_version}; required: {required}")


@dataclass(frozen=True)
class Database:
    engine: Engine
    session_factory: sessionmaker[Session]

    def session(self) -> Iterator[Session]:
        with self.session_factory() as db_session:
            yield db_session


def create_database(settings: Settings) -> Database:
    settings.ensure_sqlite_parent()
    require_supported_sqlite()
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False, "timeout": 5},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: Any, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return Database(engine=engine, session_factory=sessionmaker(engine, expire_on_commit=False))
