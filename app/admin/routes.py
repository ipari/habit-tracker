from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.accounts.service import (
    cancel_invitation,
    create_invitation,
    create_password_reset,
)
from app.auth.dependencies import AdminIdentity, DbSession
from app.auth.security import revoke_user_sessions
from app.db.models import Invitation, User
from app.web import render_template, request_has_valid_csrf

router = APIRouter(prefix="/admin")


def invite_url(request: Request, invitation: Invitation) -> str:
    return str(request.url_for("signup_page", code=invitation.code))


def invitation_row(
    request: Request,
    invitation: Invitation,
    joined_counts: dict[int, int],
) -> dict[str, object]:
    return {
        "invitation": invitation,
        "url": invite_url(request, invitation),
        "joined_count": joined_counts.get(invitation.id, 0),
    }


def admin_context(
    request: Request,
    db: DbSession,
    *,
    reset_url: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    users = db.scalars(select(User).order_by(User.created_at.desc(), User.id.desc())).all()
    invitations = db.scalars(
        select(Invitation).order_by(Invitation.created_at.desc(), Invitation.id.desc())
    ).all()
    joined_counts: dict[int, int] = {
        invitation_id: count
        for invitation_id, count in db.execute(
            select(User.invitation_id, func.count(User.id))
            .where(User.invitation_id.is_not(None))
            .group_by(User.invitation_id)
        ).all()
        if invitation_id is not None
    }
    active_admin_invitation = next(
        (
            invitation
            for invitation in invitations
            if invitation.created_by_admin and invitation.is_active
        ),
        None,
    )
    active_member_invitations = {
        invitation.created_by_user_id: invitation
        for invitation in invitations
        if invitation.created_by_user_id is not None and invitation.is_active
    }
    user_rows: list[dict[str, object]] = []
    for user in users:
        created = [item for item in invitations if item.created_by_user_id == user.id]
        invited_count = sum(joined_counts.get(item.id, 0) for item in created)
        active_invitation = active_member_invitations.get(user.id)
        user_rows.append(
            {
                "user": user,
                "joined_invitation": user.invitation,
                "invited_count": invited_count,
                "active_invitation": (
                    invitation_row(request, active_invitation, joined_counts)
                    if active_invitation is not None
                    else None
                ),
            }
        )
    return {
        "user_rows": user_rows,
        "admin_invitation": (
            invitation_row(request, active_admin_invitation, joined_counts)
            if active_admin_invitation is not None
            else None
        ),
        "reset_url": reset_url,
        "error": error,
    }


@router.get("", response_class=HTMLResponse)
def admin_page(
    request: Request, db: DbSession, _identity: AdminIdentity
) -> HTMLResponse:
    return render_template(request, "admin/index.html", admin_context(request, db))


@router.post("/invitations")
def create_admin_invitation(
    request: Request,
    db: DbSession,
    _identity: AdminIdentity,
    csrf_token: Annotated[str, Form()],
) -> Response:
    if not request_has_valid_csrf(request, csrf_token):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    try:
        create_invitation(db, created_by_admin=True)
        db.commit()
    except (SQLAlchemyError, RuntimeError):
        db.rollback()
        return render_template(
            request,
            "admin/index.html",
            admin_context(request, db, error="초대 링크를 만들지 못했습니다."),
            503,
        )
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/invitations/{invitation_id}/cancel")
def cancel_admin_invitation(
    invitation_id: int,
    request: Request,
    db: DbSession,
    _identity: AdminIdentity,
    csrf_token: Annotated[str, Form()],
) -> Response:
    if not request_has_valid_csrf(request, csrf_token):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    invitation = db.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    cancel_invitation(invitation)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse("초대를 취소하지 못했습니다.", status_code=503)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/status")
def update_user_status(
    user_id: int,
    request: Request,
    db: DbSession,
    _identity: AdminIdentity,
    is_active: Annotated[bool, Form()],
    csrf_token: Annotated[str, Form()],
) -> Response:
    if not request_has_valid_csrf(request, csrf_token):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = is_active
    if not is_active:
        revoke_user_sessions(db, user.id)
        for invitation in user.created_invitations:
            cancel_invitation(invitation)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse("회원 상태를 변경하지 못했습니다.", status_code=503)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/reset")
def create_user_reset(
    user_id: int,
    request: Request,
    db: DbSession,
    _identity: AdminIdentity,
    csrf_token: Annotated[str, Form()],
) -> Response:
    if not request_has_valid_csrf(request, csrf_token):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        _reset, raw_token = create_password_reset(db, user.id)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse("재설정 링크를 만들지 못했습니다.", status_code=503)
    reset_url = str(request.url_for("reset_page", raw_token=raw_token))
    return render_template(
        request, "admin/index.html", admin_context(request, db, reset_url=reset_url)
    )


@router.post("/users/{user_id}/delete")
def delete_user(
    user_id: int,
    request: Request,
    db: DbSession,
    _identity: AdminIdentity,
    csrf_token: Annotated[str, Form()],
) -> Response:
    if not request_has_valid_csrf(request, csrf_token):
        return HTMLResponse("요청이 만료되었습니다.", status_code=403)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        for invitation in list(user.created_invitations):
            cancel_invitation(invitation)
            invitation.creator = None
        revoke_user_sessions(db, user.id)
        db.delete(user)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse("회원을 삭제하지 못했습니다.", status_code=503)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
