from datetime import UTC, date, datetime, time, timedelta
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import (
    HabitCompletion,
    PushSubscription,
    Reminder,
    ReminderDelivery,
)
from app.domain.schedules import weekdays_to_mask
from app.reminders.schedule import scheduled_occurrences, scheduled_utc
from app.reminders.scheduler import recover_stalled_deliveries, run_once
from app.reminders.sender import ExpiredSubscriptionError, send_push
from tests.conftest import client_database, login
from tests.test_habits import create_habit


def test_spring_forward_time_moves_by_the_dst_gap() -> None:
    scheduled = scheduled_utc(
        date(2026, 3, 8), time(2, 30), "America/New_York"
    )

    assert scheduled == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)


def test_fall_back_ambiguous_time_uses_first_occurrence_only() -> None:
    scheduled = scheduled_utc(
        date(2026, 11, 1), time(1, 30), "America/New_York"
    )

    assert scheduled == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    occurrences = scheduled_occurrences(
        weekdays_mask=weekdays_to_mask([6]),
        local_time=time(1, 30),
        timezone="America/New_York",
        window_start=datetime(2026, 11, 1, 4, 0, tzinfo=UTC),
        window_end=datetime(2026, 11, 1, 7, 0, tzinfo=UTC),
    )
    assert occurrences == [scheduled]


def add_enabled_reminder_and_subscription(client: TestClient) -> tuple[int, int]:
    habit_id = create_habit(client, weekdays=[5])
    database = client_database(client)
    with database.session_factory() as db:
        reminder = db.scalar(select(Reminder).where(Reminder.habit_id == habit_id))
        assert reminder is not None
        reminder.is_enabled = True
        reminder.local_time = time(9, 0)
        subscription = PushSubscription(
            endpoint="https://push.example.test/one",
            p256dh="p256dh",
            auth="auth",
            user_agent="Test",
            is_active=True,
            failure_count=0,
        )
        db.add(subscription)
        db.commit()
        return reminder.id, subscription.id


def test_scheduler_sends_once_per_subscription_and_scheduled_time(
    client: TestClient,
) -> None:
    login(client)
    reminder_id, _subscription_id = add_enabled_reminder_and_subscription(client)
    sent: list[dict[str, str]] = []

    def fake_send(
        _subscription: PushSubscription, payload: dict[str, str], _settings: Settings
    ) -> None:
        sent.append(payload)

    database = client_database(client)
    app = cast(FastAPI, client.app)
    now = datetime(2026, 8, 1, 0, 0, 30, tzinfo=UTC)
    with database.session_factory() as db:
        assert run_once(db, app.state.settings, now=now, send=fake_send) == 1
        assert run_once(db, app.state.settings, now=now, send=fake_send) == 0
        delivery = db.scalar(
            select(ReminderDelivery).where(ReminderDelivery.reminder_id == reminder_id)
        )
        assert delivery is not None
        assert delivery.status == "sent"
        assert delivery.attempt_count == 1

    assert len(sent) == 1
    assert sent[0]["url"] == "/today"
    assert sent[0]["tag"] == "habit-reminder-1-20260801T000000Z"


def test_scheduler_skips_all_devices_when_habit_is_already_completed(
    client: TestClient,
) -> None:
    login(client)
    reminder_id, _subscription_id = add_enabled_reminder_and_subscription(client)
    sent: list[dict[str, str]] = []

    def fake_send(
        _subscription: PushSubscription, payload: dict[str, str], _settings: Settings
    ) -> None:
        sent.append(payload)

    database = client_database(client)
    app = cast(FastAPI, client.app)
    scheduled_for = scheduled_utc(date(2026, 8, 1), time(9, 0), "Asia/Seoul")
    with database.session_factory() as db:
        reminder = db.get(Reminder, reminder_id)
        assert reminder is not None
        db.add(HabitCompletion(habit_id=reminder.habit_id, local_date=date(2026, 8, 1)))
        db.add(
            PushSubscription(
                endpoint="https://push.example.test/two",
                p256dh="p256dh-two",
                auth="auth-two",
                user_agent="Second test device",
                is_active=True,
                failure_count=0,
            )
        )
        db.commit()

        assert (
            run_once(
                db,
                app.state.settings,
                now=scheduled_for + timedelta(seconds=30),
                send=fake_send,
            )
            == 0
        )
        deliveries = db.scalars(
            select(ReminderDelivery).where(
                ReminderDelivery.reminder_id == reminder_id
            )
        ).all()
        assert len(deliveries) == 2
        assert {delivery.status for delivery in deliveries} == {"skipped"}
        assert {delivery.attempt_count for delivery in deliveries} == {0}
        assert all(delivery.attempted_at is None for delivery in deliveries)

        completion = db.scalar(
            select(HabitCompletion).where(
                HabitCompletion.habit_id == reminder.habit_id,
                HabitCompletion.local_date == date(2026, 8, 1),
            )
        )
        assert completion is not None
        db.delete(completion)
        db.commit()
        assert (
            run_once(
                db,
                app.state.settings,
                now=scheduled_for + timedelta(minutes=1),
                send=fake_send,
            )
            == 0
        )

    assert sent == []


def test_scheduler_uses_reminder_timezone_to_find_completion(
    client: TestClient,
) -> None:
    login(client)
    reminder_id, _subscription_id = add_enabled_reminder_and_subscription(client)
    database = client_database(client)
    app = cast(FastAPI, client.app)
    local_date = date(2026, 8, 1)
    scheduled_for = scheduled_utc(local_date, time(9, 0), "America/Los_Angeles")

    def unexpected_send(
        _subscription: PushSubscription, _payload: dict[str, str], _settings: Settings
    ) -> None:
        raise AssertionError("a completed habit must not send a reminder")

    with database.session_factory() as db:
        reminder = db.get(Reminder, reminder_id)
        assert reminder is not None
        reminder.timezone = "America/Los_Angeles"
        db.add(HabitCompletion(habit_id=reminder.habit_id, local_date=local_date))
        db.commit()

        assert (
            run_once(
                db,
                app.state.settings,
                now=scheduled_for + timedelta(seconds=30),
                send=unexpected_send,
            )
            == 0
        )
        delivery = db.scalar(
            select(ReminderDelivery).where(
                ReminderDelivery.reminder_id == reminder_id
            )
        )
        assert delivery is not None
        assert delivery.status == "skipped"


def test_expired_subscription_is_disabled(client: TestClient) -> None:
    login(client)
    _reminder_id, subscription_id = add_enabled_reminder_and_subscription(client)

    def expired_send(
        _subscription: PushSubscription, _payload: dict[str, str], _settings: Settings
    ) -> None:
        raise ExpiredSubscriptionError("gone")

    database = client_database(client)
    app = cast(FastAPI, client.app)
    with database.session_factory() as db:
        run_once(
            db,
            app.state.settings,
            now=datetime(2026, 8, 1, 0, 0, 30, tzinfo=UTC),
            send=expired_send,
        )
        subscription = db.get(PushSubscription, subscription_id)
        assert subscription is not None
        assert subscription.is_active is False


def test_transient_failure_retries_at_most_three_times(client: TestClient) -> None:
    login(client)
    reminder_id, subscription_id = add_enabled_reminder_and_subscription(client)
    calls = 0

    def failing_send(
        _subscription: PushSubscription, _payload: dict[str, str], _settings: Settings
    ) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("temporary push service failure")

    database = client_database(client)
    app = cast(FastAPI, client.app)
    now = datetime(2026, 8, 1, 0, 0, 30, tzinfo=UTC)
    with database.session_factory() as db:
        assert run_once(db, app.state.settings, now=now, send=failing_send) == 1
        assert run_once(db, app.state.settings, now=now, send=failing_send) == 1
        assert run_once(db, app.state.settings, now=now, send=failing_send) == 1
        assert run_once(db, app.state.settings, now=now, send=failing_send) == 0
        delivery = db.scalar(
            select(ReminderDelivery).where(
                ReminderDelivery.reminder_id == reminder_id,
                ReminderDelivery.subscription_id == subscription_id,
            )
        )
        assert delivery is not None
        assert delivery.status == "failed"
        assert delivery.attempt_count == 3

    assert calls == 3


def test_stalled_pending_delivery_outside_lookback_window_is_retried(
    client: TestClient,
) -> None:
    """A crash-interrupted delivery must be retried even after an outage
    longer than reminder_lookback_minutes pushes its scheduled_for out of
    the normal occurrence-scan window."""
    login(client)
    reminder_id, subscription_id = add_enabled_reminder_and_subscription(client)
    scheduled_for = datetime(2026, 7, 1, 9, 0, 0, tzinfo=UTC)
    stuck_attempted_at = datetime(2026, 7, 1, 9, 0, 5, tzinfo=UTC)
    # A Monday, far from any of this Saturday reminder's own occurrences, so
    # the only attempt in this run_once call is the recovered stalled one.
    now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)
    sent: list[dict[str, str]] = []

    def fake_send(
        _subscription: PushSubscription, payload: dict[str, str], _settings: Settings
    ) -> None:
        sent.append(payload)

    database = client_database(client)
    app = cast(FastAPI, client.app)
    with database.session_factory() as db:
        db.add(
            ReminderDelivery(
                reminder_id=reminder_id,
                subscription_id=subscription_id,
                scheduled_for=scheduled_for,
                status="pending",
                attempt_count=1,
                attempted_at=stuck_attempted_at,
            )
        )
        db.commit()

        assert run_once(db, app.state.settings, now=now, send=fake_send) == 1

        delivery = db.scalar(
            select(ReminderDelivery).where(
                ReminderDelivery.reminder_id == reminder_id,
                ReminderDelivery.subscription_id == subscription_id,
            )
        )
        assert delivery is not None
        assert delivery.status == "sent"
        assert delivery.attempt_count == 2

    assert len(sent) == 1


def test_recover_stalled_deliveries_stops_at_three_attempts(client: TestClient) -> None:
    login(client)
    reminder_id, subscription_id = add_enabled_reminder_and_subscription(client)
    now = datetime(2026, 8, 1, 0, 0, 30, tzinfo=UTC)
    app = cast(FastAPI, client.app)

    def fake_send(
        _subscription: PushSubscription, _payload: dict[str, str], _settings: Settings
    ) -> None:
        raise AssertionError("should not retry a delivery that already used 3 attempts")

    database = client_database(client)
    with database.session_factory() as db:
        db.add(
            ReminderDelivery(
                reminder_id=reminder_id,
                subscription_id=subscription_id,
                scheduled_for=datetime(2026, 7, 1, 9, 0, 0, tzinfo=UTC),
                status="pending",
                attempt_count=3,
                attempted_at=datetime(2026, 7, 1, 9, 0, 5, tzinfo=UTC),
            )
        )
        db.commit()

        assert recover_stalled_deliveries(db, now, app.state.settings, fake_send) == set()

        delivery = db.scalar(
            select(ReminderDelivery).where(
                ReminderDelivery.reminder_id == reminder_id,
                ReminderDelivery.subscription_id == subscription_id,
            )
        )
        assert delivery is not None
        assert delivery.status == "failed"
        assert delivery.attempt_count == 3


def test_recover_stalled_delivery_skips_retry_after_completion(
    client: TestClient,
) -> None:
    login(client)
    reminder_id, subscription_id = add_enabled_reminder_and_subscription(client)
    scheduled_for = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
    now = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)
    app = cast(FastAPI, client.app)

    def unexpected_send(
        _subscription: PushSubscription, _payload: dict[str, str], _settings: Settings
    ) -> None:
        raise AssertionError("a completed habit must not retry a stalled reminder")

    database = client_database(client)
    with database.session_factory() as db:
        reminder = db.get(Reminder, reminder_id)
        assert reminder is not None
        db.add(HabitCompletion(habit_id=reminder.habit_id, local_date=date(2026, 7, 1)))
        db.add(
            ReminderDelivery(
                reminder_id=reminder_id,
                subscription_id=subscription_id,
                scheduled_for=scheduled_for,
                status="pending",
                attempt_count=1,
                attempted_at=scheduled_for + timedelta(seconds=5),
            )
        )
        db.commit()

        assert run_once(db, app.state.settings, now=now, send=unexpected_send) == 0

        delivery = db.scalar(
            select(ReminderDelivery).where(
                ReminderDelivery.reminder_id == reminder_id,
                ReminderDelivery.subscription_id == subscription_id,
            )
        )
        assert delivery is not None
        assert delivery.status == "skipped"
        assert delivery.attempt_count == 1


def test_recover_stalled_deliveries_ignores_recent_pending(client: TestClient) -> None:
    login(client)
    reminder_id, subscription_id = add_enabled_reminder_and_subscription(client)
    now = datetime(2026, 8, 1, 0, 0, 30, tzinfo=UTC)
    app = cast(FastAPI, client.app)

    database = client_database(client)
    with database.session_factory() as db:
        db.add(
            ReminderDelivery(
                reminder_id=reminder_id,
                subscription_id=subscription_id,
                scheduled_for=datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC),
                status="pending",
                attempt_count=1,
                attempted_at=now,
            )
        )
        db.commit()

        assert recover_stalled_deliveries(db, now, app.state.settings, send_push) == set()

        delivery = db.scalar(
            select(ReminderDelivery).where(
                ReminderDelivery.reminder_id == reminder_id,
                ReminderDelivery.subscription_id == subscription_id,
            )
        )
        assert delivery is not None
        assert delivery.status == "pending"


def test_stalled_recovery_keeps_pending_if_process_dies_before_retry_claim(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client)
    reminder_id, subscription_id = add_enabled_reminder_and_subscription(client)
    now = datetime(2026, 8, 1, 0, 10, 0, tzinfo=UTC)
    database = client_database(client)
    app = cast(FastAPI, client.app)

    class SchedulerCrash(BaseException):
        pass

    def crash_before_claim(*_args: object, **_kwargs: object) -> None:
        raise SchedulerCrash

    monkeypatch.setattr("app.reminders.scheduler.deliver_once", crash_before_claim)
    with database.session_factory() as db:
        db.add(
            ReminderDelivery(
                reminder_id=reminder_id,
                subscription_id=subscription_id,
                scheduled_for=datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC),
                status="pending",
                attempt_count=1,
                attempted_at=datetime(2026, 8, 1, 0, 0, 5, tzinfo=UTC),
            )
        )
        db.commit()

        with pytest.raises(SchedulerCrash):
            recover_stalled_deliveries(db, now, app.state.settings, send_push)

    with database.session_factory() as db:
        delivery = db.scalar(
            select(ReminderDelivery).where(
                ReminderDelivery.reminder_id == reminder_id,
                ReminderDelivery.subscription_id == subscription_id,
            )
        )
        assert delivery is not None
        assert delivery.status == "pending"
        assert delivery.attempt_count == 1


def test_recovered_delivery_is_not_retried_twice_in_same_run(
    client: TestClient,
) -> None:
    login(client)
    reminder_id, subscription_id = add_enabled_reminder_and_subscription(client)
    scheduled_for = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    now = datetime(2026, 8, 1, 0, 3, 0, tzinfo=UTC)
    calls = 0

    def failing_send(
        _subscription: PushSubscription, _payload: dict[str, str], _settings: Settings
    ) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("temporary push service failure")

    database = client_database(client)
    app = cast(FastAPI, client.app)
    with database.session_factory() as db:
        db.add(
            ReminderDelivery(
                reminder_id=reminder_id,
                subscription_id=subscription_id,
                scheduled_for=scheduled_for,
                status="pending",
                attempt_count=1,
                attempted_at=datetime(2026, 8, 1, 0, 0, 5, tzinfo=UTC),
            )
        )
        db.commit()

        assert run_once(db, app.state.settings, now=now, send=failing_send) == 1

        delivery = db.scalar(
            select(ReminderDelivery).where(
                ReminderDelivery.reminder_id == reminder_id,
                ReminderDelivery.subscription_id == subscription_id,
            )
        )
        assert delivery is not None
        assert delivery.status == "failed"
        assert delivery.attempt_count == 2

    assert calls == 1
