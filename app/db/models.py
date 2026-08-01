from datetime import UTC, date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (CheckConstraint("id = 1", name="ck_app_settings_singleton"),)


class Habit(Base):
    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    emoji: Mapped[str] = mapped_column(String(32))
    background_preset: Mapped[str] = mapped_column(String(32), default="dawn")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    schedules: Mapped[list["HabitSchedule"]] = relationship(
        back_populates="habit", cascade="all, delete-orphan"
    )
    completions: Mapped[list["HabitCompletion"]] = relationship(
        back_populates="habit", cascade="all, delete-orphan"
    )
    reminder: Mapped["Reminder | None"] = relationship(
        back_populates="habit", cascade="all, delete-orphan", uselist=False
    )


class HabitSchedule(Base):
    __tablename__ = "habit_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"))
    weekdays_mask: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_until: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    habit: Mapped[Habit] = relationship(back_populates="schedules")

    __table_args__ = (
        CheckConstraint(
            "weekdays_mask >= 1 AND weekdays_mask <= 127",
            name="ck_habit_schedules_weekdays_mask",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_habit_schedules_valid_period",
        ),
        UniqueConstraint("habit_id", "effective_from", name="uq_habit_schedule_start"),
        Index("ix_habit_schedules_lookup", "habit_id", "effective_from", "effective_until"),
    )


class HabitCompletion(Base):
    __tablename__ = "habit_completions"

    id: Mapped[int] = mapped_column(primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"))
    local_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    habit: Mapped[Habit] = relationship(back_populates="completions")

    __table_args__ = (
        UniqueConstraint("habit_id", "local_date", name="uq_habit_completion_date"),
        Index("ix_habit_completions_date", "local_date"),
    )


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habits.id", ondelete="CASCADE"), unique=True)
    weekdays_mask: Mapped[int] = mapped_column(Integer)
    local_time: Mapped[time] = mapped_column(Time)
    timezone: Mapped[str] = mapped_column(String(64))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    habit: Mapped[Habit] = relationship(back_populates="reminder")
    deliveries: Mapped[list["ReminderDelivery"]] = relationship(
        back_populates="reminder", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "weekdays_mask >= 1 AND weekdays_mask <= 127",
            name="ck_reminders_weekdays_mask",
        ),
    )


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    deliveries: Mapped[list["ReminderDelivery"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )


class ReminderDelivery(Base):
    __tablename__ = "reminder_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    reminder_id: Mapped[int] = mapped_column(ForeignKey("reminders.id", ondelete="CASCADE"))
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("push_subscriptions.id", ondelete="CASCADE")
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    reminder: Mapped[Reminder] = relationship(back_populates="deliveries")
    subscription: Mapped[PushSubscription] = relationship(back_populates="deliveries")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_reminder_deliveries_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_reminder_deliveries_attempt_count"),
        UniqueConstraint(
            "reminder_id",
            "subscription_id",
            "scheduled_for",
            name="uq_reminder_delivery_target",
        ),
        Index("ix_reminder_deliveries_status", "status", "scheduled_for"),
    )
