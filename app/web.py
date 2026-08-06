from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse

from app.auth.security import create_csrf_token


def render_template(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    settings = request.app.state.settings
    existing_token = request.cookies.get("csrf")
    csrf_token = existing_token or create_csrf_token(settings.session_secret.get_secret_value())
    template_context = dict(context or {})
    template_context["csrf_token"] = csrf_token
    template_context["request_path"] = request.url.path
    identity = getattr(request.state, "identity", None)
    template_context["show_notification_prompt"] = (
        identity is not None and identity.role == "member"
    )
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request=request,
        name=name,
        context=template_context,
        status_code=status_code,
    )
    if existing_token is None:
        response.set_cookie(
            "csrf",
            csrf_token,
            secure=settings.session_cookie_secure,
            httponly=True,
            samesite="lax",
        )
    return response


def request_has_valid_csrf(request: Request, submitted_token: str) -> bool:
    from app.auth.security import verify_csrf_token

    return verify_csrf_token(
        request.cookies.get("csrf"),
        submitted_token,
        request.app.state.settings.session_secret.get_secret_value(),
    )
