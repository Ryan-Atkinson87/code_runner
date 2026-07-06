from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from app.auth import init_auth
from app.routers import health
from app.routers.exec import init_exec_deps
from app.routers.exec import router as exec_router
from app.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings()

    init_auth(settings)
    init_exec_deps(Path(settings.workdir))

    application = FastAPI(title=settings.app_name)
    application.include_router(health.router)
    application.include_router(exec_router)

    return application
