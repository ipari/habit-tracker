import base64

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dependencies import CurrentIdentity, DbSession
from app.db.models import PushSubscription
from app.web import request_has_valid_csrf

router = APIRouter(prefix="/api/push", tags=["push"])


def decode_base64url(value: str) -> bytes:
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except ValueError as exc:
        raise ValueError("Invalid base64url value") from exc


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=255)
    auth: str = Field(min_length=16, max_length=255)

    @field_validator("p256dh")
    @classmethod
    def validate_p256dh(cls, value: str) -> str:
        decoded = decode_base64url(value)
        if len(decoded) != 65 or decoded[0] != 4:
            raise ValueError("p256dh must be an uncompressed P-256 public key")
        return value

    @field_validator("auth")
    @classmethod
    def validate_auth(cls, value: str) -> str:
        if len(decode_base64url(value)) < 16:
            raise ValueError("auth secret is too short")
        return value


class SubscriptionPayload(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: SubscriptionKeys

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("Push endpoint must use HTTPS")
        return value


def require_json_csrf(request: Request) -> None:
    if not request_has_valid_csrf(request, request.headers.get("x-csrf-token", "")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


@router.get("/config")
def push_config(request: Request, _identity: CurrentIdentity) -> dict[str, str | bool]:
    settings = request.app.state.settings
    return {
        "configured": settings.push_is_configured,
        "publicKey": settings.vapid_public_key if settings.push_is_configured else "",
    }


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
def save_subscription(
    payload: SubscriptionPayload,
    request: Request,
    db: DbSession,
    _identity: CurrentIdentity,
) -> dict[str, str]:
    require_json_csrf(request)
    if not request.app.state.settings.push_is_configured:
        raise HTTPException(status_code=503, detail="Web Push is not configured")
    subscription = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    if subscription is None:
        subscription = PushSubscription(endpoint=payload.endpoint)
        db.add(subscription)
    subscription.p256dh = payload.keys.p256dh
    subscription.auth = payload.keys.auth
    subscription.user_agent = request.headers.get("user-agent", "")[:512]
    subscription.is_active = True
    subscription.failure_count = 0
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Could not save push subscription") from exc
    return {"status": "subscribed"}


class UnsubscribePayload(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("Push endpoint must use HTTPS")
        return value


@router.delete("/subscriptions")
def disable_subscription(
    payload: UnsubscribePayload,
    request: Request,
    db: DbSession,
    _identity: CurrentIdentity,
) -> dict[str, str]:
    require_json_csrf(request)
    subscription = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    if subscription is not None:
        subscription.is_active = False
        try:
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(
                status_code=503, detail="Could not disable push subscription"
            ) from exc
    return {"status": "unsubscribed"}
