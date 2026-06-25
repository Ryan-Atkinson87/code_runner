from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

from app.auth.dependencies import init_session_store
from app.auth.router import router as auth_router
from app.auth.sessions import SessionStore
from app.config.schema import ProjectConfig
from app.github.client import GitHubClient
from app.routers import health
from app.routers.blockers import init_blockers_deps
from app.routers.blockers import router as blockers_router
from app.routers.config import init_config_deps
from app.routers.config import router as config_router
from app.routers.profile import init_profile_deps
from app.routers.profile import router as profile_router
from app.routers.prs import init_prs_deps
from app.routers.prs import router as prs_router
from app.routers.usage import init_usage_deps
from app.routers.usage import router as usage_router
from app.settings import Settings
from app.usage.monitor import UsageMonitor
from app.usage.policy import UsagePolicy

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.blockers.store import BlockerStore
    from app.engine.profile_generation import ProfileGenerationResult


def create_app(
    settings: Settings | None = None,
    session_store: SessionStore | None = None,
    usage_monitor: UsageMonitor | None = None,
    usage_policy: UsagePolicy | None = None,
    blocker_store: BlockerStore | None = None,
    active_run_id_fn: Callable[[], int | None] | None = None,
    github_client: GitHubClient | None = None,
    repo_name: str = "",
    project_config: ProjectConfig | None = None,
    profile_generate_fn: Callable[..., Awaitable[ProfileGenerationResult]] | None = None,
    profile_output_path: Path | None = None,
) -> FastAPI:
    if settings is None:
        settings = Settings()

    store = session_store or SessionStore()
    init_session_store(store)

    if usage_monitor is not None and usage_policy is not None:
        init_usage_deps(usage_monitor, usage_policy)

    if blocker_store is not None and active_run_id_fn is not None:
        init_blockers_deps(blocker_store, active_run_id_fn)

    if github_client is not None and repo_name:
        init_prs_deps(github_client, repo_name)

    if project_config is not None:
        init_config_deps(project_config)

    if profile_generate_fn is not None:
        init_profile_deps(
            profile_generate_fn,
            profile_output_path or Path("execution-profile.yaml"),
        )

    application = FastAPI(
        title=settings.app_name,
        root_path=settings.root_path,
    )

    application.include_router(health.router)
    application.include_router(auth_router)
    application.include_router(usage_router)
    application.include_router(blockers_router)
    application.include_router(prs_router)
    application.include_router(config_router)
    application.include_router(profile_router)

    return application
