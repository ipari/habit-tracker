import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_REVISION = "20260801_0005"
CURRENT_REVISION = "20260807_0006"


def run_alembic(database_path: Path, revision: str) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "development",
            "DATABASE_URL": f"sqlite:///{database_path}",
        }
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def seed_legacy_relational_data(database_path: Path) -> None:
    now = "2026-08-01 00:00:00"
    with sqlite3.connect(database_path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            """
            INSERT INTO habits
                (id, name, emoji, background_preset, archived_at, created_at, updated_at)
            VALUES (1, '기존 습관', '🌱', 'forest', NULL, ?, ?)
            """,
            (now, now),
        )
        db.execute(
            """
            INSERT INTO habit_schedules
                (id, habit_id, weekdays_mask, effective_from, effective_until,
                 created_at, updated_at)
            VALUES (1, 1, 127, '2026-08-01', NULL, ?, ?)
            """,
            (now, now),
        )
        db.execute(
            """
            INSERT INTO habit_completions
                (id, habit_id, local_date, created_at, updated_at)
            VALUES (1, 1, '2026-08-01', ?, ?)
            """,
            (now, now),
        )
        db.execute(
            """
            INSERT INTO reminders
                (id, habit_id, weekdays_mask, local_time, timezone, is_enabled,
                 created_at, updated_at)
            VALUES (1, 1, 127, '09:00:00', 'Asia/Seoul', 1, ?, ?)
            """,
            (now, now),
        )
        db.execute(
            """
            INSERT INTO push_subscriptions
                (id, endpoint, p256dh, auth, user_agent, is_active, failure_count,
                 last_success_at, last_failure_at, created_at, updated_at)
            VALUES (1, 'https://push.example.test/legacy', ?, ?, 'legacy browser',
                    1, 0, NULL, NULL, ?, ?)
            """,
            ("p" * 65, "a" * 16, now, now),
        )
        db.execute(
            """
            INSERT INTO reminder_deliveries
                (id, reminder_id, subscription_id, scheduled_for, status,
                 attempt_count, attempted_at, sent_at, error, created_at, updated_at)
            VALUES (1, 1, 1, '2026-08-01 00:00:00', 'sent', 1,
                    '2026-08-01 00:00:01', '2026-08-01 00:00:01', '', ?, ?)
            """,
            (now, now),
        )
        db.commit()


def table_count(db: sqlite3.Connection, table: str) -> int:
    return int(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def test_multi_user_upgrade_preserves_all_legacy_relational_data(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy.db"
    run_alembic(database_path, LEGACY_REVISION)
    seed_legacy_relational_data(database_path)

    run_alembic(database_path, "head")

    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            CURRENT_REVISION
        )
        for table in (
            "habits",
            "habit_schedules",
            "habit_completions",
            "reminders",
            "push_subscriptions",
            "reminder_deliveries",
        ):
            assert table_count(db, table) == 1
        assert db.execute(
            "SELECT name, user_id FROM habits WHERE id = 1"
        ).fetchone() == ("기존 습관", None)
        assert db.execute(
            "SELECT weekdays_mask, effective_from FROM habit_schedules WHERE habit_id = 1"
        ).fetchone() == (127, "2026-08-01")
        assert db.execute(
            "SELECT local_date FROM habit_completions WHERE habit_id = 1"
        ).fetchone() == ("2026-08-01",)
        assert db.execute(
            "SELECT local_time, is_enabled FROM reminders WHERE habit_id = 1"
        ).fetchone() == ("09:00:00", 1)
        assert db.execute(
            "SELECT endpoint, user_id FROM push_subscriptions WHERE id = 1"
        ).fetchone() == ("https://push.example.test/legacy", None)
        assert db.execute(
            "SELECT status, attempt_count FROM reminder_deliveries WHERE id = 1"
        ).fetchone() == ("sent", 1)
        assert any(
            row[2] == "users" and row[3] == "user_id"
            for row in db.execute("PRAGMA foreign_key_list(habits)")
        )
        assert any(
            row[2] == "users" and row[3] == "user_id"
            for row in db.execute("PRAGMA foreign_key_list(push_subscriptions)")
        )
