from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from price_monitor.api.v1 import (
    admin,
    health,
    internal,
    price_history,
    products,
    sources,
    watchlist,
)
from price_monitor.core.config import Settings
from price_monitor.core.idempotency import IdempotencyConflictError
from price_monitor.core.logging import configure_logging
from price_monitor.core.security import AuthenticationError
from price_monitor.core.url_policy import UnsafeUrlError


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Price Monitor Service",
        version="0.1.0",
        openapi_url="/openapi.json",
        docs_url="/docs",
    )
    app.state.settings = settings or Settings()

    app.include_router(health.router)
    app.include_router(admin.router)
    app.include_router(watchlist.router)
    app.include_router(products.router)
    app.include_router(price_history.router)
    app.include_router(sources.router)
    app.include_router(internal.router)

    @app.exception_handler(AuthenticationError)
    async def authentication_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
        return _error_response(
            request=request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="authentication_failed",
            message=str(exc),
        )

    @app.exception_handler(UnsafeUrlError)
    async def unsafe_url_handler(request: Request, exc: UnsafeUrlError) -> JSONResponse:
        return _error_response(
            request=request,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="unsafe_url",
            message=str(exc),
        )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_handler(request: Request, exc: IdempotencyConflictError) -> JSONResponse:
        return _error_response(
            request=request,
            status_code=status.HTTP_409_CONFLICT,
            code="idempotency_conflict",
            message=str(exc),
        )

    return app


def _error_response(*, request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    request_id = request.headers.get("X-Request-Id", "")
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


app = create_app()
