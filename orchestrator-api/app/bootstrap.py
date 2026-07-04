from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from app.blockers.store import BlockerStore
from app.config.loader import load_project_config
from app.db.store import StateStore
from app.engine.profile_generation import generate_proposal
from app.engine.run_manager import RunController
from app.engine.scheduler import WaveScheduler
from app.engine.wave_driver import run_wave
from app.github.client import GitHubClient
from app.handoff.engine import HandoffEngine
from app.observability.rollup import RollupStore
from app.profile.loader import load_execution_profile
from app.providers import get_adapter
from app.secrets.resolver import resolve_secrets
from app.usage.api_reader import ApiUsageReader
from app.usage.monitor import UsageMonitor
from app.usage.policy import UsagePolicy
from app.usage.subscription import SubscriptionUsageReader
from app.wave.reader import read_wave

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine
    from typing import Any

    from app.config.schema import ProjectConfig
    from app.engine.profile_generation import ProfileGenerationResult
    from app.providers.types import ProviderName
    from app.settings import Settings
    from app.usage.reader import UsageReader

_DEFAULT_MODEL = "claude-sonnet-4-6"
_CLAUDE_CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


@dataclass
class BootstrapResult:
    store: StateStore
    project_config: ProjectConfig
    github_client: GitHubClient
    run_controller: RunController
    usage_monitor: UsageMonitor
    usage_policy: UsagePolicy
    blocker_store: BlockerStore
    rollup_store: RollupStore
    profile_generate_fn: Callable[[], Awaitable[ProfileGenerationResult]]
    wave_run_fn: Callable[[int, str, str], Coroutine[Any, Any, None]]


def should_bootstrap(settings: Settings) -> bool:
    """Whether enough real config is present to wire production dependencies.

    Both a project.yaml path and a DB path are required — without either,
    ``create_app`` falls back to its existing test/stub behaviour untouched.
    """
    return bool(settings.project_config_path) and bool(settings.db_path)


def _build_usage_reader(project_config: ProjectConfig) -> UsageReader:
    provider = project_config.provider.default
    plan = project_config.provider.plan
    if plan:
        return SubscriptionUsageReader(
            credentials_path=_CLAUDE_CREDENTIALS_PATH,
            provider=provider,
            plan=plan,
        )
    return ApiUsageReader(provider=provider, plan=plan)


def _repo_paths(project_config: ProjectConfig) -> dict[str, Path]:
    root = Path(project_config.project.root)
    return {repo.name: root / repo.path for repo in project_config.repos}


def build_dependencies(settings: Settings) -> BootstrapResult:
    """Construct real, wired dependencies for ``create_app`` from ``settings``.

    This is the composition root: every subsystem built in isolation across
    Phases 1-7 is assembled here into the objects the routers expect. Nothing
    here is AI-driven — Spec Principle 1 (deterministic wiring).
    """
    store = StateStore(settings.db_path)
    store.open()

    project_config = load_project_config(settings.project_config_path)
    secrets = resolve_secrets(project_config.secrets)

    github_client = GitHubClient(
        token=secrets["github_pat"],
        owner=project_config.integrations.github.owner,
    )

    primary_repo = project_config.repos[0].name if project_config.repos else ""
    run_controller = RunController(
        conn=store.conn,
        github_client=github_client,
        project_name=project_config.project.name,
        repo_name=primary_repo,
    )

    usage_reader = _build_usage_reader(project_config)
    usage_policy = UsagePolicy(peak_hour_throttle_enabled=project_config.usage.peak_hour_throttle)
    usage_monitor = UsageMonitor(
        reader=usage_reader,
        policy=usage_policy,
        scheduler=WaveScheduler(),
        threshold_percent=project_config.usage.threshold_percent,
        provider=project_config.provider.default,
        plan=project_config.provider.plan,
    )

    blocker_store = BlockerStore(store.conn)
    rollup_store = RollupStore(store.conn)

    profile_adapter = get_adapter(project_config.provider.default)
    profile_model = project_config.provider.models.planning or _DEFAULT_MODEL
    profile_generate_fn = functools.partial(
        generate_proposal,
        project_config,
        list(_repo_paths(project_config).values()),
        profile_adapter,
        profile_model,
    )

    wave_run_fn = _build_wave_run_fn(settings, project_config, github_client, store, blocker_store)

    return BootstrapResult(
        store=store,
        project_config=project_config,
        github_client=github_client,
        run_controller=run_controller,
        usage_monitor=usage_monitor,
        usage_policy=usage_policy,
        blocker_store=blocker_store,
        rollup_store=rollup_store,
        profile_generate_fn=profile_generate_fn,
        wave_run_fn=wave_run_fn,
    )


def _build_wave_run_fn(
    settings: Settings,
    project_config: ProjectConfig,
    github_client: GitHubClient,
    store: StateStore,
    blocker_store: BlockerStore,
) -> Callable[[int, str, str], Coroutine[Any, Any, None]]:
    async def _wave_run_fn(run_id: int, wave_name: str, provider: str) -> None:
        provider_name = cast("ProviderName", provider)
        wave = read_wave(github_client, project_config, wave_name)
        profile = load_execution_profile(settings.execution_profile_path)
        adapter = get_adapter(provider_name)
        handoff_engine = HandoffEngine(github_client)
        model = project_config.provider.models.implementing or _DEFAULT_MODEL

        # No canonical base-skill/persona-prompt/overlay content exists yet
        # (Spec §17.3/§17.4/§17.6 — tool-level content, not this issue's
        # composition-root wiring). A real run will raise inside
        # compose_and_render until that content lands; logged by the
        # wave task's done-callback rather than surfacing here.
        await run_wave(
            wave=wave,
            project_config=project_config,
            profile=profile,
            adapter=adapter,
            handoff_engine=handoff_engine,
            db_conn=store.conn,
            repo_paths=_repo_paths(project_config),
            skills=[],
            base_prompts={},
            overlays=[],
            model=model,
            wave_name=wave_name,
            run_id=run_id,
            provider=provider_name,
            provider_models=project_config.provider.models,
            blocker_store=blocker_store,
        )

    return _wave_run_fn
