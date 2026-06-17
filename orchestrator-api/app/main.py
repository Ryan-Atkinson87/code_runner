from fastapi import FastAPI

from app.routers import health
from app.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings()

    application = FastAPI(
        title=settings.app_name,
        root_path=settings.root_path,
    )

    application.include_router(health.router)

    return application
