from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import require_auth
from app.engine.run_manager import RunControlError, RunController, RunNotFoundError, RunStatus

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.config.schema import ProjectConfig
    from app.usage.monitor import UsageMonitor

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_auth)])

_controller: RunController | None = None
_monitor: UsageMonitor | None = None
_project_config: ProjectConfig | None = None
_wave_run_fn: Callable[[int, str, str], Coroutine[Any, Any, None]] | None = None


def init_run_controller(
    controller: RunController,
    monitor: UsageMonitor | None = None,
    project_config: ProjectConfig | None = None,
    wave_run_fn: Callable[[int, str, str], Coroutine[Any, Any, None]] | None = None,
) -> None:
    global _controller, _monitor, _project_config, _wave_run_fn
    _controller = controller
    _monitor = monitor
    _project_config = project_config
    _wave_run_fn = wave_run_fn


def _get_controller() -> RunController:
    if _controller is None:
        raise RuntimeError("RunController not initialised")
    return _controller


class WaveInfo(BaseModel):
    name: str
    milestone_number: int
    state: str


class WavesResponse(BaseModel):
    waves: list[WaveInfo]


class StartRunRequest(BaseModel):
    wave: str = Field(min_length=1)
    provider: Literal["claude", "codex", "gemini"] = "claude"


class RunResponse(BaseModel):
    run_id: int
    project: str
    wave: str
    provider: str
    status: RunStatus


class RunStatusResponse(BaseModel):
    active: bool
    run: RunResponse | None = None


@router.get("/waves", response_model=WavesResponse)
async def list_waves() -> WavesResponse:
    controller = _get_controller()
    waves = controller.list_waves()
    return WavesResponse(
        waves=[
            WaveInfo(name=w["name"], milestone_number=w["milestone_number"], state=w["state"])
            for w in waves
        ]
    )


@router.get("/status", response_model=RunStatusResponse)
async def get_run_status() -> RunStatusResponse:
    controller = _get_controller()
    state = controller.get_active_run()
    if state is None:
        return RunStatusResponse(active=False)
    return RunStatusResponse(
        active=state.status in (RunStatus.RUNNING, RunStatus.PAUSED),
        run=RunResponse(
            run_id=state.run_id,
            project=state.project,
            wave=state.wave,
            provider=state.provider,
            status=state.status,
        ),
    )


@router.post("/start", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def start_run(body: StartRunRequest) -> RunResponse:
    controller = _get_controller()
    try:
        state = controller.start_run(
            project=controller.project_name,
            wave=body.wave,
            provider=body.provider,
        )
    except RunControlError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if _monitor is not None:
        plan = _project_config.provider.plan if _project_config is not None else ""
        _monitor.switch_reader(_monitor.reader, body.provider, plan)

    if _wave_run_fn is not None:
        task = asyncio.create_task(
            _wave_run_fn(state.run_id, body.wave, body.provider),
            name=f"wave-{state.run_id}",
        )
        controller.set_active_task(task)

        def _log_task_result(t: asyncio.Task[None]) -> None:
            if not t.cancelled() and (exc := t.exception()):
                logger.error("Wave task failed: %s", exc, exc_info=exc)

        task.add_done_callback(_log_task_result)

    return RunResponse(
        run_id=state.run_id,
        project=state.project,
        wave=state.wave,
        provider=state.provider,
        status=state.status,
    )


@router.post("/{run_id}/stop", response_model=RunResponse)
async def stop_run(run_id: int) -> RunResponse:
    controller = _get_controller()
    try:
        state = controller.stop_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RunControlError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RunResponse(
        run_id=state.run_id,
        project=state.project,
        wave=state.wave,
        provider=state.provider,
        status=state.status,
    )


@router.post("/{run_id}/pause", response_model=RunResponse)
async def pause_run(run_id: int) -> RunResponse:
    controller = _get_controller()
    try:
        state = controller.pause_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RunControlError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RunResponse(
        run_id=state.run_id,
        project=state.project,
        wave=state.wave,
        provider=state.provider,
        status=state.status,
    )


@router.post("/{run_id}/resume", response_model=RunResponse)
async def resume_run(run_id: int) -> RunResponse:
    controller = _get_controller()
    try:
        state = controller.resume_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RunControlError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return RunResponse(
        run_id=state.run_id,
        project=state.project,
        wave=state.wave,
        provider=state.provider,
        status=state.status,
    )
