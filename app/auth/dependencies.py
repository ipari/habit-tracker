from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.security import AuthenticatedIdentity, read_session_token


def get_db(request: Request) -> Iterator[Session]:
    yield from request.app.state.database.session()


DbSession = Annotated[Session, Depends(get_db)]


def optional_identity(request: Request, db: Session) -> AuthenticatedIdentity | None:
    identity = read_session_token(
        request.app.state.settings, db, request.cookies.get("session")
    )
    request.state.identity = identity
    return identity


def require_identity(request: Request, db: DbSession) -> AuthenticatedIdentity:
    identity = optional_identity(request, db)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return identity


CurrentIdentity = Annotated[AuthenticatedIdentity, Depends(require_identity)]


def require_member(identity: CurrentIdentity) -> AuthenticatedIdentity:
    if identity.role != "member" or identity.user_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return identity


def require_admin(identity: CurrentIdentity) -> AuthenticatedIdentity:
    if identity.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return identity


MemberIdentity = Annotated[AuthenticatedIdentity, Depends(require_member)]
AdminIdentity = Annotated[AuthenticatedIdentity, Depends(require_admin)]
