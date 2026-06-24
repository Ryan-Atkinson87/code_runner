from fastapi import FastAPI

from app.auth.dependencies import init_session_store
from app.auth.router import router as auth_router
from app.auth.sessions import SessionStore
from app.routers import health
from app.routers.usage import init_usage_deps
from app.routers.usage import router as usage_router
from app.settings import Settings
from app.usage.monitor import UsageMonitor
from app.usage.policy import UsagePolicy


def create_app(
    settings: Settings | None = None,
    session_store: SessionStore | None = None,
    usage_monitor: UsageMonitor | None = None,
    usage_policy: UsagePolicy | None = None,
) -> FastAPI:
    if settings is None:
        settings = Settings()

    store = session_store or SessionStore()
    init_session_store(store)

    if usage_monitor is not None and usage_policy is not None:
        init_usage_deps(usage_monitor, usage_policy)

    application = FastAPI(
        title=settings.app_name,
        root_path=settings.root_path,
    )

    application.include_router(health.router)
    application.include_router(auth_router)
    application.include_router(usage_router)

    return application
