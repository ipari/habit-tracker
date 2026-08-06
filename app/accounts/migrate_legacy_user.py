import getpass
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts.service import normalize_email, validate_new_password
from app.config import get_settings
from app.db.models import AppSettings, Habit, PushSubscription, User
from app.db.session import create_database


@dataclass(frozen=True)
class LegacyMigrationResult:
    user: User
    user_created: bool
    settings_migrated: int
    habits_migrated: int
    subscriptions_migrated: int
    total_habits: int
    user_habits: int


def migrate_legacy_data(
    db: Session,
    email_input: str,
    password: str | None = None,
    confirmation: str | None = None,
    *,
    allow_existing_user: bool = False,
) -> LegacyMigrationResult:
    email, normalized_email = normalize_email(email_input)
    user = db.scalar(select(User).where(User.normalized_email == normalized_email))
    user_created = user is None
    if user is not None and not allow_existing_user:
        raise ValueError("이미 가입된 이메일입니다.")
    if user is None:
        if password is None or confirmation is None:
            raise ValueError("새 회원의 초기 비밀번호가 필요합니다.")
        user = User(
            email=email,
            normalized_email=normalized_email,
            password_hash=validate_new_password(password, confirmation),
        )
        db.add(user)
        db.flush()

    legacy_settings = db.scalar(
        select(AppSettings).where(AppSettings.user_id.is_(None)).limit(1)
    )
    settings_migrated = int(legacy_settings is not None)
    if legacy_settings is None:
        if db.scalar(
            select(AppSettings.id).where(AppSettings.user_id == user.id)
        ) is None:
            db.add(AppSettings(user_id=user.id, timezone="UTC"))
    else:
        current_settings = db.scalar(
            select(AppSettings).where(AppSettings.user_id == user.id)
        )
        if current_settings is None:
            legacy_settings.user_id = user.id
        else:
            current_settings.timezone = legacy_settings.timezone
            db.delete(legacy_settings)

    legacy_habits = db.scalars(
        select(Habit).where(Habit.user_id.is_(None))
    ).all()
    for habit in legacy_habits:
        habit.user_id = user.id

    legacy_subscriptions = db.scalars(
        select(PushSubscription).where(PushSubscription.user_id.is_(None))
    ).all()
    for subscription in legacy_subscriptions:
        subscription.user_id = user.id

    db.commit()
    total_habits = db.scalar(select(func.count(Habit.id))) or 0
    user_habits = (
        db.scalar(select(func.count(Habit.id)).where(Habit.user_id == user.id)) or 0
    )
    return LegacyMigrationResult(
        user=user,
        user_created=user_created,
        settings_migrated=settings_migrated,
        habits_migrated=len(legacy_habits),
        subscriptions_migrated=len(legacy_subscriptions),
        total_habits=total_habits,
        user_habits=user_habits,
    )


def main() -> None:
    settings = get_settings()
    database = create_database(settings)
    email_input = input("기존 데이터를 이전할 회원 이메일: ")
    try:
        with database.session_factory() as db:
            _, normalized_email = normalize_email(email_input)
            existing_user = db.scalar(
                select(User).where(User.normalized_email == normalized_email)
            )
            password: str | None = None
            confirmation: str | None = None
            if existing_user is None:
                password = getpass.getpass("초기 비밀번호(8자 이상): ")
                confirmation = getpass.getpass("초기 비밀번호 확인: ")
            else:
                print("이미 존재하는 회원입니다. 미소유 데이터만 이 회원에게 연결합니다.")
            result = migrate_legacy_data(
                db,
                email_input,
                password,
                confirmation,
                allow_existing_user=True,
            )
    finally:
        database.engine.dispose()
    action = "생성하고" if result.user_created else "사용해"
    print(f"{result.user.email} 회원을 {action} 기존 데이터 연결을 완료했습니다.")
    print(
        "연결된 데이터: "
        f"설정 {result.settings_migrated}개, "
        f"습관 {result.habits_migrated}개, "
        f"푸시 구독 {result.subscriptions_migrated}개"
    )
    print(
        f"현재 데이터베이스의 습관: 전체 {result.total_habits}개, "
        f"해당 회원 소유 {result.user_habits}개"
    )
    if result.total_habits == 0:
        print(
            "주의: 현재 데이터베이스에 습관이 없습니다. 기존 데이터가 있던 "
            "Docker volume과 DATABASE_URL을 사용 중인지 확인하세요."
        )
    elif result.user_habits == 0:
        print(
            "주의: 습관이 다른 회원 소유로 이미 지정되어 있어 자동 이전하지 않았습니다."
        )


if __name__ == "__main__":
    main()
