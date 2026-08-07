from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import AppSettings, Habit, Invitation, User
from tests.conftest import (
    TEST_PASSWORD,
    client_database,
    csrf_token,
    login,
)
from tests.test_habits import create_habit


def clear_auth(client: TestClient) -> None:
    client.cookies.delete("session")
    client.cookies.delete("csrf")


def login_as(client: TestClient, identifier: str, password: str) -> str:
    clear_auth(client)
    token = csrf_token(client)
    response = client.post(
        "/login",
        data={"username": identifier, "password": password, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    session = client.cookies.get("session")
    assert session is not None
    return cast(str, session)


def create_owner_invitation(client: TestClient) -> Invitation:
    login(client)
    response = client.post(
        "/settings/invitations",
        data={"csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with client_database(client).session_factory() as db:
        invitation = db.scalar(select(Invitation).order_by(Invitation.id.desc()))
        assert invitation is not None
        db.expunge(invitation)
        return invitation


def test_admin_page_groups_invitation_action_and_shows_member_count(
    client: TestClient,
) -> None:
    login_as(client, "admin", TEST_PASSWORD)

    page = client.get("/admin")

    assert page.status_code == 200
    assert "<title>관리자 · Habit Tracker</title>" in page.text
    assert "<h1>관리자</h1>" in page.text
    assert "회원 관리" not in page.text
    assert 'class="section-count">1명</span>' in page.text
    invitation_section = page.text.split(
        'aria-labelledby="admin-invitation-title"', 1
    )[1].split("</section>", 1)[0]
    assert invitation_section.index(
        'class="settings-surface admin-surface invitation-surface"'
    ) < (
        invitation_section.index('action="/admin/invitations"')
    )
    assert 'class="member-invite-empty"' in invitation_section


def test_admin_member_list_is_compact_and_shows_relative_last_access(
    client: TestClient,
) -> None:
    with client_database(client).session_factory() as db:
        owner = db.scalar(select(User).where(User.normalized_email == "owner"))
        assert owner is not None
        owner.last_login_at = datetime.now(UTC) - timedelta(days=3, hours=1)
        db.commit()

    login_as(client, "admin", TEST_PASSWORD)
    page = client.get("/admin")

    assert page.status_code == 200
    assert 'class="member-disclosure"' in page.text
    assert "3일 전 마지막 접속" in page.text
    assert "가입일" in page.text
    assert "마지막 로그인" in page.text
    assert "초대한 인원" in page.text
    assert "data-reset-link-form" in page.text
    assert ">비밀번호 재설정</button>" in page.text
    assert "일회용 재설정 링크" not in page.text


def signup_with_invitation(
    client: TestClient, code: str, email: str, password: str = "member password"
) -> None:
    clear_auth(client)
    page = client.get(f"/invite/{code}")
    assert page.status_code == 200
    response = client.post(
        f"/invite/{code}",
        data={
            "email": email,
            "password": password,
            "password_confirmation": password,
            "csrf_token": csrf_token(client),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/today"


def test_invitation_is_twelve_characters_and_reusable(client: TestClient) -> None:
    invitation = create_owner_invitation(client)
    assert len(invitation.code) == 12

    signup_with_invitation(client, invitation.code, "First@Example.com")
    signup_with_invitation(client, invitation.code, "second@example.com")

    with client_database(client).session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 3
        stored = db.get(Invitation, invitation.id)
        assert stored is not None
        assert stored.is_active is True
        assert stored.last_joined_at is not None
        first = db.scalar(
            select(User).where(User.normalized_email == "first@example.com")
        )
        assert first is not None
        assert first.email == "First@Example.com"
        assert first.invitation_id == invitation.id


def test_canceled_invitation_blocks_new_signup_but_keeps_history(
    client: TestClient,
) -> None:
    invitation = create_owner_invitation(client)
    settings_page = client.get("/settings")
    assert "이 초대 링크를 삭제하면 신규 가입이 중단됩니다." in settings_page.text
    signup_with_invitation(client, invitation.code, "joined@example.com")
    login_as(client, "owner", TEST_PASSWORD)
    response = client.post(
        f"/settings/invitations/{invitation.id}/cancel",
        data={"csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert response.status_code == 303

    clear_auth(client)
    assert client.get(f"/invite/{invitation.code}").status_code == 410
    with client_database(client).session_factory() as db:
        joined = db.scalar(
            select(User).where(User.normalized_email == "joined@example.com")
        )
        assert joined is not None
        assert joined.invitation_id == invitation.id


def test_member_has_only_one_active_invitation_and_can_replace_deleted_link(
    client: TestClient,
) -> None:
    first = create_owner_invitation(client)
    second_create = client.post(
        "/settings/invitations",
        data={"csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert second_create.status_code == 303
    settings_page = client.get("/settings")
    assert "초대 링크</h2>" in settings_page.text
    assert ">생성</button>" not in settings_page.text

    with client_database(client).session_factory() as db:
        owner = db.scalar(select(User).where(User.normalized_email == "owner"))
        assert owner is not None
        assert db.scalar(
            select(func.count(Invitation.id)).where(
                Invitation.created_by_user_id == owner.id,
                Invitation.is_active.is_(True),
            )
        ) == 1

    canceled = client.post(
        f"/settings/invitations/{first.id}/cancel",
        data={"csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert canceled.status_code == 303
    replaced = client.post(
        "/settings/invitations",
        data={"csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert replaced.status_code == 303
    with client_database(client).session_factory() as db:
        owner = db.scalar(select(User).where(User.normalized_email == "owner"))
        assert owner is not None
        invitations = db.scalars(
            select(Invitation)
            .where(Invitation.created_by_user_id == owner.id)
            .order_by(Invitation.id)
        ).all()
        assert len(invitations) == 2
        assert invitations[0].is_active is False
        assert invitations[1].is_active is True
        assert invitations[1].code != first.code


def test_member_invited_count_survives_invitation_replacement(
    client: TestClient,
) -> None:
    first = create_owner_invitation(client)
    signup_with_invitation(client, first.code, "first-invite@example.com")

    login_as(client, "owner", TEST_PASSWORD)
    canceled = client.post(
        f"/settings/invitations/{first.id}/cancel",
        data={"csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert canceled.status_code == 303
    created = client.post(
        "/settings/invitations",
        data={"csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert created.status_code == 303
    with client_database(client).session_factory() as db:
        owner = db.scalar(select(User).where(User.normalized_email == "owner"))
        assert owner is not None
        owner_id = owner.id
        second = db.scalar(
            select(Invitation).where(
                Invitation.created_by_user_id == owner_id,
                Invitation.is_active.is_(True),
            )
        )
        assert second is not None
        second_code = second.code

    signup_with_invitation(client, second_code, "second-invite@example.com")
    login_as(client, "admin", TEST_PASSWORD)
    page = client.get("/admin")

    assert page.status_code == 200
    owner_details = page.text.split(f'data-user-id="{owner_id}"', 1)[1].split(
        "</details>", 1
    )[0]
    assert second_code in owner_details
    assert "<dt>초대한 인원</dt><dd>2명</dd>" in owner_details


def test_admin_separates_own_link_and_can_force_disable_member_link(
    client: TestClient,
) -> None:
    member_invitation = create_owner_invitation(client)
    with client_database(client).session_factory() as db:
        owner = db.scalar(select(User).where(User.normalized_email == "owner"))
        assert owner is not None
        owner_id = owner.id

    login_as(client, "admin", TEST_PASSWORD)
    for _attempt in range(2):
        created = client.post(
            "/admin/invitations",
            data={"csrf_token": csrf_token(client)},
            follow_redirects=False,
        )
        assert created.status_code == 303

    page = client.get("/admin")
    assert "내 초대 링크" in page.text
    assert "초대 링크 삭제" in page.text
    assert "비밀번호 재설정" in page.text
    assert "비활성화" not in page.text
    assert "/status" not in page.text
    assert member_invitation.code in page.text
    admin_invitation_section = page.text.split(
        'aria-labelledby="admin-invitation-title"', 1
    )[1].split("</section>", 1)[0]
    assert 'class="member-invite-card"' in admin_invitation_section
    assert 'class="member-invite-link"' in admin_invitation_section
    assert "가입 0명" in admin_invitation_section
    assert "생성 ·" not in admin_invitation_section
    assert "마지막 가입" not in admin_invitation_section
    with client_database(client).session_factory() as db:
        assert db.scalar(
            select(func.count(Invitation.id)).where(
                Invitation.created_by_admin.is_(True),
                Invitation.is_active.is_(True),
            )
        ) == 1

    disabled = client.post(
        f"/admin/invitations/{member_invitation.id}/cancel",
        data={"csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert disabled.status_code == 303
    with client_database(client).session_factory() as db:
        stored = db.get(Invitation, member_invitation.id)
        owner = db.get(User, owner_id)
        assert stored is not None and stored.is_active is False
        assert owner is not None and owner.is_active is True


def test_admin_member_status_endpoint_is_not_available(client: TestClient) -> None:
    login(client)
    with client_database(client).session_factory() as db:
        owner = db.scalar(select(User).where(User.normalized_email == "owner"))
        assert owner is not None
        owner_id = owner.id

    login_as(client, "admin", TEST_PASSWORD)
    response = client.post(
        f"/admin/users/{owner_id}/status",
        data={"is_active": "false", "csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_admin_and_member_routes_are_role_separated(client: TestClient) -> None:
    login(client)
    assert client.get("/admin").status_code == 403

    login_as(client, "admin", TEST_PASSWORD)
    assert client.get("/admin").status_code == 200
    assert client.get("/today").status_code == 403


def test_habit_settings_and_push_data_are_isolated_by_member(
    client: TestClient,
) -> None:
    owner_habit_id = create_habit(client)
    invitation = create_owner_invitation(client)
    signup_with_invitation(client, invitation.code, "other@example.com")

    today = client.get("/today")
    assert "물 마시기" not in today.text
    assert client.get(f"/habits/{owner_habit_id}").status_code == 404
    with client_database(client).session_factory() as db:
        other = db.scalar(
            select(User).where(User.normalized_email == "other@example.com")
        )
        owner = db.scalar(select(User).where(User.normalized_email == "owner"))
        assert other is not None and owner is not None
        assert db.scalar(
            select(AppSettings.timezone).where(AppSettings.user_id == other.id)
        ) == "UTC"
        assert db.scalar(
            select(Habit.user_id).where(Habit.id == owner_habit_id)
        ) == owner.id


def test_admin_can_create_invitation_and_one_time_password_reset(
    client: TestClient,
) -> None:
    member_session = login(client)
    with client_database(client).session_factory() as db:
        owner = db.scalar(select(User).where(User.normalized_email == "owner"))
        assert owner is not None
        owner_id = owner.id

    login_as(client, "admin", TEST_PASSWORD)
    created = client.post(
        "/admin/invitations",
        data={"csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert created.status_code == 303
    reset = client.post(
        f"/admin/users/{owner_id}/reset",
        data={"csrf_token": csrf_token(client)},
    )
    assert reset.status_code == 200
    assert reset.headers["cache-control"] == "no-store"
    marker = "/reset/"
    reset_url = reset.json()["reset_url"]
    raw_token = reset_url.split(marker, 1)[1]
    assert reset_url not in client.get("/admin").text

    clear_auth(client)
    reset_page = client.get(f"{marker}{raw_token}")
    assert reset_page.status_code == 200
    changed = client.post(
        f"{marker}{raw_token}",
        data={
            "password": "new member password",
            "password_confirmation": "new member password",
            "csrf_token": csrf_token(client),
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert client.get(f"{marker}{raw_token}").status_code == 410
    clear_auth(client)
    client.cookies.set("session", member_session)
    assert client.get("/today").status_code == 401
    login_as(client, "owner", "new member password")
    assert client.get("/today").status_code == 200

    with client_database(client).session_factory() as db:
        admin_invitation = db.scalar(
            select(Invitation).where(Invitation.created_by_admin.is_(True))
        )
        assert admin_invitation is not None


def test_admin_delete_removes_owned_data_and_preserves_invitation_history(
    client: TestClient,
) -> None:
    owner_habit_id = create_habit(client)
    invitation = create_owner_invitation(client)
    signup_with_invitation(client, invitation.code, "survivor@example.com")
    with client_database(client).session_factory() as db:
        owner = db.scalar(select(User).where(User.normalized_email == "owner"))
        assert owner is not None
        owner_id = owner.id

    login_as(client, "admin", TEST_PASSWORD)
    deleted = client.post(
        f"/admin/users/{owner_id}/delete",
        data={"csrf_token": csrf_token(client)},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    with client_database(client).session_factory() as db:
        assert db.get(User, owner_id) is None
        assert db.get(Habit, owner_habit_id) is None
        survivor = db.scalar(
            select(User).where(User.normalized_email == "survivor@example.com")
        )
        preserved = db.get(Invitation, invitation.id)
        assert survivor is not None
        assert preserved is not None
        assert survivor.invitation_id == preserved.id
        assert preserved.created_by_user_id is None
        assert preserved.is_active is False


def test_member_password_change_revokes_all_sessions(client: TestClient) -> None:
    old_session = login(client)
    response = client.post(
        "/settings/password",
        data={
            "current_password": TEST_PASSWORD,
            "new_password": "changed member password",
            "new_password_confirmation": "changed member password",
            "csrf_token": csrf_token(client),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    clear_auth(client)
    client.cookies.set("session", old_session)
    assert client.get("/today").status_code == 401
    login_as(client, "owner", "changed member password")
    assert client.get("/today").status_code == 200
