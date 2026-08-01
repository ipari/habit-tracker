from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.auth.routes import router as auth_router
from app.calendar.routes import router as calendar_router
from app.config import Settings, get_settings
from app.db.session import create_database
from app.habits.routes import router as habits_router
from app.push.routes import router as push_router
from app.settings.routes import router as settings_router

BASE_DIR = Path(__file__).resolve().parent


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_settings.validate_auth_configuration()
        resolved_settings.validate_push_configuration()
        app.state.database = create_database(resolved_settings)
        yield
        app.state.database.engine.dispose()

    app = FastAPI(title="Habit Tracker", lifespan=lifespan)
    app.state.settings = resolved_settings
    app.state.templates = Jinja2Templates(directory=BASE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    app.include_router(auth_router)
    app.include_router(habits_router)
    app.include_router(calendar_router)
    app.include_router(push_router)
    app.include_router(settings_router)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == 401:
            if request.headers.get("HX-Request") == "true":
                return Response(status_code=401, headers={"HX-Redirect": "/login"})
            if "text/html" in request.headers.get("accept", ""):
                return RedirectResponse("/login", status_code=303)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/today", status_code=303)

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(
            BASE_DIR / "static" / "js" / "sw.js",
            media_type="text/javascript",
            headers={
                "Cache-Control": "no-cache",
                "Service-Worker-Allowed": "/",
            },
        )

    @app.get("/health/live")
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def readiness(request: Request) -> dict[str, str]:
        with request.app.state.database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
