from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import require_auth
from app.engine.run_manager import RunControlError, RunController, RunNotFoundError, RunStatus

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_auth)])

_controller: RunController | None = None


def init_run_controller(controller: RunController) -> None:
    global _controller
    _controller = controller


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
