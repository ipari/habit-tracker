from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.security import AuthenticatedIdentity, read_session_token


def get_db(request: Request) -> Iterator[Session]:
    yield from request.app.state.database.session()


DbSession = Annotated[Session, Depends(get_db)]


def optional_identity(request: Request) -> AuthenticatedIdentity | None:
    return read_session_token(request.app.state.settings, request.cookies.get("session"))


def require_identity(request: Request) -> AuthenticatedIdentity:
    identity = optional_identity(request)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return identity


CurrentIdentity = Annotated[AuthenticatedIdentity, Depends(require_identity)]
