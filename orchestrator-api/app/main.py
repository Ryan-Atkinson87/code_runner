from fastapi import FastAPI

from app.auth.dependencies import init_session_store
from app.auth.router import router as auth_router
from app.auth.sessions import SessionStore
from app.routers import health
from app.settings import Settings


def create_app(
    settings: Settings | None = None,
    session_store: SessionStore | None = None,
) -> FastAPI:
    if settings is None:
        settings = Settings()

    store = session_store or SessionStore()
    init_session_store(store)

    application = FastAPI(
        title=settings.app_name,
        root_path=settings.root_path,
    )

    application.include_router(health.router)
    application.include_router(auth_router)

    return application
