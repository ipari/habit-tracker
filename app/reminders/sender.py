import json

from pywebpush import WebPushException, webpush  # type: ignore[import-untyped]

from app.config import Settings
from app.db.models import PushSubscription


class ExpiredSubscriptionError(Exception):
    """The remote push service no longer recognizes a subscription."""


def send_push(
    subscription: PushSubscription,
    payload: dict[str, str],
    settings: Settings,
) -> None:
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {
                    "p256dh": subscription.p256dh,
                    "auth": subscription.auth,
                },
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=settings.vapid_private_key.get_secret_value(),
            vapid_claims={"sub": settings.vapid_subject},
            ttl=60 * 60,
            timeout=10,
        )
    except WebPushException as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code in (404, 410):
            raise ExpiredSubscriptionError("Push subscription expired") from exc
        raise
