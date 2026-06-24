from fastapi import FastAPI

from app.auth.dependencies import init_session_store
from app.auth.router import router as auth_router
from app.auth.sessions import SessionStore
from app.engine.run_manager import RunController
from app.routers import health
from app.routers.runs import init_run_controller
from app.routers.runs import router as runs_router
from app.settings import Settings


def create_app(
    settings: Settings | None = None,
    session_store: SessionStore | None = None,
    run_controller: RunController | None = None,
) -> FastAPI:
    if settings is None:
        settings = Settings()

    store = session_store or SessionStore()
    init_session_store(store)

    if run_controller is not None:
        init_run_controller(run_controller)

    application = FastAPI(
        title=settings.app_name,
        root_path=settings.root_path,
    )

    application.include_router(health.router)
    application.include_router(auth_router)
    application.include_router(runs_router)

    return application
