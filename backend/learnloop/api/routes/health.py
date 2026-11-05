"""Health HTTP endpoints; registered by the application factory."""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select, text

from learnloop.api.dependencies import ApiContext
from learnloop.persistence.database import (
    Course,
)


def build_router(context: ApiContext):
    router = APIRouter(tags=["Health"])
    factory = context.factory
    owner = context.owner
    services = context.services
    settings = context.settings

    @router.get("/health/live")
    def live():
        return {"status": "ok", "service": "learnloop-api"}

    @router.get("/health/ready")
    def ready(principal=Depends(owner)):
        statuses = {}
        for name, check in {
            context.factory.kw["bind"].dialect.name: lambda: check_database(),
            "sqlite_vec" if settings.uses_sqlite else "qdrant": lambda: services.check_collection(),
            "embeddings": lambda: {"dimensions": len(services.embed("LearnLoop readiness check."))},
        }.items():
            try:
                statuses[name] = {"status": "ok", **check()}
            except Exception:
                statuses[name] = {"status": "unavailable"}
        statuses["generation"] = {
            "status": "configured" if settings.generation_ready else "not_configured",
            "model": settings.llm_model,
        }
        ok = all(item["status"] in ("ok", "green", "configured") for item in statuses.values())
        return Response(
            json.dumps({"status": "ready" if ok else "degraded", "services": statuses}),
            status_code=200 if ok else 503,
            media_type="application/json",
        )

    def check_database():
        with factory() as db:
            db.execute(text("SELECT 1"))
            db.execute(select(Course.id).limit(1))
        return {}

    return router
