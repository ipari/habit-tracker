import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import Habit, PushSubscription, Reminder, ReminderDelivery
from app.db.session import create_database
from app.reminders.schedule import scheduled_occurrences
from app.reminders.sender import ExpiredSubscriptionError, send_push

logger = logging.getLogger(__name__)
SendFunction = Callable[[PushSubscription, dict[str, str], Settings], None]
STALLED_PENDING_TIMEOUT = timedelta(minutes=2)


def delivery_payload(reminder: Reminder, scheduled_for: datetime) -> dict[str, str]:
    occurrence = scheduled_for.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return {
        "title": f"{reminder.habit.emoji} {reminder.habit.name}".strip(),
        "body": "지금 실천하고 오늘의 기록을 이어가세요.",
        "url": "/today",
        "tag": f"habit-reminder-{reminder.habit_id}-{occurrence}",
    }


def existing_delivery(
    db: Session,
    reminder_id: int,
    subscription_id: int,
    scheduled_for: datetime,
) -> ReminderDelivery | None:
    return db.scalar(
        select(ReminderDelivery).where(
            ReminderDelivery.reminder_id == reminder_id,
            ReminderDelivery.subscription_id == subscription_id,
            ReminderDelivery.scheduled_for == scheduled_for,
        )
    )


def deliver_once(
    db: Session,
    reminder: Reminder,
    subscription: PushSubscription,
    scheduled_for: datetime,
    attempted_at: datetime,
    settings: Settings,
    send: SendFunction,
) -> None:
    delivery = existing_delivery(db, reminder.id, subscription.id, scheduled_for)
    if delivery is not None and delivery.status in ("pending", "sent"):
        return
    if delivery is not None and delivery.attempt_count >= 3:
        return
    if delivery is None:
        delivery = ReminderDelivery(
            reminder=reminder,
            subscription=subscription,
            scheduled_for=scheduled_for,
            status="pending",
            attempt_count=0,
            error="",
        )
        db.add(delivery)
    delivery.status = "pending"
    delivery.attempt_count += 1
    delivery.attempted_at = attempted_at
    db.commit()

    try:
        send(subscription, delivery_payload(reminder, scheduled_for), settings)
    except ExpiredSubscriptionError as exc:
        subscription.is_active = False
        subscription.failure_count += 1
        subscription.last_failure_at = attempted_at
        delivery.status = "failed"
        delivery.error = str(exc)[:500]
    except Exception as exc:
        subscription.failure_count += 1
        subscription.last_failure_at = attempted_at
        delivery.status = "failed"
        delivery.error = str(exc)[:500]
        logger.exception("Failed to send reminder %s", reminder.id)
    else:
        subscription.failure_count = 0
        subscription.last_success_at = attempted_at
        delivery.status = "sent"
        delivery.sent_at = attempted_at
        delivery.error = ""
    db.commit()


def recover_stalled_deliveries(
    db: Session,
    now: datetime,
    settings: Settings,
    send: SendFunction,
) -> set[int]:
    """Retry deliveries left in "pending" by a process that died mid-send.

    ``deliver_once`` commits status="pending" before calling ``send``, so a
    crash between that commit and the outcome commit leaves the row stuck.
    The normal retry path in ``run_once`` only considers occurrences inside
    the current lookback window, which a longer outage pushes out of range,
    so stalled deliveries are retried here directly rather than through
    that occurrence loop.
    """
    cutoff = now - STALLED_PENDING_TIMEOUT
    stalled = db.scalars(
        select(ReminderDelivery).where(
            ReminderDelivery.status == "pending",
            ReminderDelivery.attempted_at < cutoff,
        )
    ).all()
    if not stalled:
        return set()

    retried_delivery_ids: set[int] = set()
    terminal_status_changed = False
    for delivery in stalled:
        reminder = delivery.reminder
        subscription = delivery.subscription
        if (
            delivery.attempt_count >= 3
            or not reminder.is_enabled
            or reminder.habit.archived_at is not None
            or not subscription.is_active
        ):
            delivery.status = "failed"
            delivery.error = "발송이 완료되지 않고 중단되었습니다."
            terminal_status_changed = True
            continue
        # Do not commit the intermediate failed state. If the process dies before
        # deliver_once claims the row as pending again, the previous pending state
        # remains recoverable on the next scheduler run.
        delivery.status = "failed"
        delivery.error = "발송이 완료되지 않고 중단되었습니다."
        retried_delivery_ids.add(delivery.id)
        deliver_once(
            db, reminder, subscription, delivery.scheduled_for, now, settings, send
        )
    if terminal_status_changed:
        db.commit()
    return retried_delivery_ids


def run_once(
    db: Session,
    settings: Settings,
    *,
    now: datetime | None = None,
    send: SendFunction = send_push,
) -> int:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    recovered_delivery_ids = recover_stalled_deliveries(db, current, settings, send)
    attempts = len(recovered_delivery_ids)
    window_start = current - timedelta(minutes=settings.reminder_lookback_minutes)
    reminders = db.scalars(
        select(Reminder)
        .join(Reminder.habit)
        .where(Reminder.is_enabled.is_(True), Habit.archived_at.is_(None))
    ).all()
    for reminder in reminders:
        subscriptions = db.scalars(
            select(PushSubscription).where(
                PushSubscription.is_active.is_(True),
                PushSubscription.user_id == reminder.habit.user_id,
            )
        ).all()
        occurrences = scheduled_occurrences(
            weekdays_mask=reminder.weekdays_mask,
            local_time=reminder.local_time,
            timezone=reminder.timezone,
            window_start=window_start,
            window_end=current,
        )
        for scheduled_for in occurrences:
            for subscription in subscriptions:
                if not subscription.is_active:
                    continue
                before = existing_delivery(
                    db, reminder.id, subscription.id, scheduled_for
                )
                if before is not None and before.id in recovered_delivery_ids:
                    continue
                if before is None or (before.status == "failed" and before.attempt_count < 3):
                    attempts += 1
                deliver_once(
                    db,
                    reminder,
                    subscription,
                    scheduled_for,
                    current,
                    settings,
                    send,
                )
    return attempts


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    settings.validate_push_configuration()
    if not settings.push_is_configured:
        raise RuntimeError("Web Push is not configured")
    database = create_database(settings)
    logger.info("Reminder scheduler started")
    try:
        while True:
            with database.session_factory() as db:
                run_once(db, settings)
            time.sleep(settings.reminder_poll_seconds)
    except KeyboardInterrupt:
        logger.info("Reminder scheduler stopped")
    finally:
        database.engine.dispose()


if __name__ == "__main__":
    main()
