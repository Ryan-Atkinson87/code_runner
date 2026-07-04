from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

from app.auth.dependencies import init_session_store
from app.auth.router import router as auth_router
from app.auth.sessions import SessionStore
from app.bootstrap import build_dependencies, should_bootstrap
from app.config.schema import ProjectConfig
from app.engine.run_manager import RunController
from app.github.client import GitHubClient
from app.progress.bus import ProgressBus
from app.routers import health
from app.routers.blockers import init_blockers_deps
from app.routers.blockers import router as blockers_router
from app.routers.config import init_config_deps
from app.routers.config import router as config_router
from app.routers.profile import init_profile_deps
from app.routers.profile import router as profile_router
from app.routers.progress import init_progress_bus
from app.routers.progress import router as progress_router
from app.routers.prs import init_prs_deps
from app.routers.prs import router as prs_router
from app.routers.reports import init_reports_deps
from app.routers.reports import router as reports_router
from app.routers.runs import init_run_controller
from app.routers.runs import router as runs_router
from app.routers.usage import init_usage_deps
from app.routers.usage import router as usage_router
from app.settings import Settings
from app.usage.monitor import UsageMonitor
from app.usage.policy import UsagePolicy

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine
    from typing import Any

    from app.blockers.store import BlockerStore
    from app.engine.profile_generation import ProfileGenerationResult
    from app.observability.rollup import RollupStore


def _active_run_id_fn(controller: RunController) -> Callable[[], int | None]:
    def _get() -> int | None:
        active = controller.get_active_run()
        return active.run_id if active is not None else None

    return _get


def create_app(
    settings: Settings | None = None,
    session_store: SessionStore | None = None,
    run_controller: RunController | None = None,
    usage_monitor: UsageMonitor | None = None,
    usage_policy: UsagePolicy | None = None,
    blocker_store: BlockerStore | None = None,
    active_run_id_fn: Callable[[], int | None] | None = None,
    github_client: GitHubClient | None = None,
    repo_name: str = "",
    project_config: ProjectConfig | None = None,
    config_path: str | Path = "",
    profile_generate_fn: Callable[..., Awaitable[ProfileGenerationResult]] | None = None,
    profile_output_path: Path | None = None,
    progress_bus: ProgressBus | None = None,
    rollup_store: RollupStore | None = None,
    wave_run_fn: Callable[[int, str, str], Coroutine[Any, Any, None]] | None = None,
) -> FastAPI:
    if settings is None:
        settings = Settings()

    if should_bootstrap(settings):
        built = build_dependencies(settings)
        run_controller = run_controller or built.run_controller
        usage_monitor = usage_monitor or built.usage_monitor
        usage_policy = usage_policy or built.usage_policy
        blocker_store = blocker_store or built.blocker_store
        active_run_id_fn = active_run_id_fn or _active_run_id_fn(built.run_controller)
        github_client = github_client or built.github_client
        repo_name = repo_name or (
            built.project_config.repos[0].name if built.project_config.repos else ""
        )
        project_config = project_config or built.project_config
        config_path = config_path or settings.project_config_path
        profile_generate_fn = profile_generate_fn or built.profile_generate_fn
        profile_output_path = profile_output_path or Path(settings.execution_profile_path)
        rollup_store = rollup_store or built.rollup_store
        wave_run_fn = wave_run_fn or built.wave_run_fn

    store = session_store or SessionStore()
    init_session_store(store)

    if run_controller is not None:
        init_run_controller(
            run_controller,
            monitor=usage_monitor,
            project_config=project_config,
            wave_run_fn=wave_run_fn,
        )

    if usage_monitor is not None and usage_policy is not None:
        init_usage_deps(usage_monitor, usage_policy)

    if blocker_store is not None and active_run_id_fn is not None:
        init_blockers_deps(blocker_store, active_run_id_fn)

    if github_client is not None and repo_name:
        init_prs_deps(github_client, repo_name)

    if project_config is not None:
        init_config_deps(project_config, str(config_path))

    if profile_generate_fn is not None:
        init_profile_deps(
            profile_generate_fn,
            profile_output_path or Path("execution-profile.yaml"),
        )

    _bus = progress_bus or ProgressBus()
    init_progress_bus(_bus)

    if rollup_store is not None:
        init_reports_deps(rollup_store)

    application = FastAPI(
        title=settings.app_name,
        root_path=settings.root_path,
    )

    application.include_router(health.router)
    application.include_router(auth_router)
    application.include_router(runs_router)
    application.include_router(progress_router)
    application.include_router(usage_router)
    application.include_router(blockers_router)
    application.include_router(prs_router)
    application.include_router(config_router)
    application.include_router(profile_router)
    application.include_router(reports_router)

    return application
