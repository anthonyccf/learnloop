"""Application factory, middleware, error handling, and route registration."""

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError

from learnloop.api.dependencies import ApiContext
from learnloop.api.routes import activity, assessments, courses, documents, health, plans, sessions
from learnloop.core.config import get_settings
from learnloop.core.errors import ServiceError
from learnloop.persistence.database import (
    session_factory,
)
from learnloop.services.clients import Services


def create_app(settings=None, factory=None, services=None):
    settings = settings or get_settings()
    factory = factory or session_factory(settings)
    services = services or Services(settings)

    @asynccontextmanager
    async def lifespan(app):
        if not settings.api_token.get_secret_value():
            raise RuntimeError("Set API_TOKEN before starting the API.")
        yield

    app = FastAPI(title="LearnLoop API", version="0.1.0", lifespan=lifespan)
    app.state.factory, app.state.services = factory, services
    context = ApiContext(settings=settings, factory=factory, services=services)

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        return Response(
            json.dumps({"detail": exc.message, "code": exc.code}),
            status_code=503 if exc.retryable else 422,
            media_type="application/json",
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        # Never echo SQL, credentials, provider bodies or uploaded content.
        return Response(
            json.dumps(
                {"detail": "The operation failed. Check service readiness and server logs."}
            ),
            status_code=500,
            media_type="application/json",
        )

    @app.exception_handler(IntegrityError)
    async def conflict(request, exc):
        return Response(
            json.dumps(
                {
                    "detail": "This operation conflicts with an existing record. Refresh and reuse the original operation ID."
                }
            ),
            status_code=409,
            media_type="application/json",
        )

    @app.middleware("http")
    async def body_limit(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and (
            not length.isdecimal() or int(length) > settings.max_upload_bytes + 1024 * 1024
        ):
            return Response("Request body is too large.", status_code=413)
        return await call_next(request)

    for routes in (health, courses, documents, sessions, assessments, activity, plans):
        app.include_router(routes.build_router(context))
    return app
