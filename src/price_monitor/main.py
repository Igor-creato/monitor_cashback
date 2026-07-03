from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from price_monitor.core.config import Settings
from price_monitor.core.logging import configure_logging
from price_monitor.core.security import AuthenticationError
from price_monitor.db.session import get_session


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Monitor Cashback Service",
        version="0.1.0",
        openapi_url="/openapi.json",
        docs_url="/docs",
    )
    app.state.settings = settings or Settings()

    @app.get("/health/live", tags=["health"])
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.exception_handler(AuthenticationError)
    async def authentication_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
        request_id = request.headers.get("X-Request-Id", "")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": {
                    "code": "authentication_failed",
                    "message": str(exc),
                    "request_id": request_id,
                }
            },
        )

    return app


app = create_app()
