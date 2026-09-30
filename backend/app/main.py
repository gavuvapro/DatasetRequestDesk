"""FastAPI application factory for Dataset Request Desk."""
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import analytics, auth, episodes, health, requests, users
from app.logger import setup_logging

setup_logging()
logger = logging.getLogger("app")


class StructuredLoggingMiddleware:
    """One JSON log line per request: method, path, status, duration, user_id."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        # Pull the bearer token from headers to attribute the request to a user
        # without depending on FastAPI's dependency machinery inside middleware.
        user_id = None
        try:
            for key, value in scope.get("headers", []):
                if key == b"authorization":
                    from app.core.security import decode_token

                    parts = value.decode().split(" ", 1)
                    if len(parts) == 2 and parts[0].lower() == "bearer":
                        payload = decode_token(parts[1])
                        if payload and "sub" in payload:
                            user_id = payload.get("sub")
                    break
        except Exception:  # noqa: BLE001 - logging must never break the request
            user_id = None

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            path = scope.get("path", "")
            if path != "/health":  # keep health checks out of the log firehose
                logging.getLogger("app.request").info(
                    scope.get("method", "?") + " " + path,
                    extra={
                        "extra_fields": {
                            "event": "http_request",
                            "method": scope.get("method", "?"),
                            "path": path,
                            "status": status_code,
                            "duration_ms": duration_ms,
                            "user_id": user_id,
                        }
                    },
                )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Dataset Request Desk API",
        version="1.0.0",
        description="Internal platform for robot teleoperation dataset requests.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # internal tool; tighten per deployment
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(StructuredLoggingMiddleware)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(episodes.router)
    app.include_router(requests.router)
    app.include_router(analytics.router)

    return app


app = create_app()
