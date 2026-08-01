import pytest

from app.db.session import sqlite_version_is_supported


@pytest.mark.parametrize(
    ("version", "supported"),
    [
        ((3, 44, 5), False),
        ((3, 44, 6), True),
        ((3, 49, 1), False),
        ((3, 50, 6), False),
        ((3, 50, 7), True),
        ((3, 51, 2), False),
        ((3, 51, 3), True),
        ((3, 53, 2), True),
    ],
)
def test_sqlite_version_policy(version: tuple[int, int, int], supported: bool) -> None:
    assert sqlite_version_is_supported(version) is supported
