from __future__ import annotations

from typing import Any, get_args

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from app.auth.dependencies import require_auth
from app.config.loader import save_project_config
from app.config.schema import (
    EgressSection,
    ProjectConfig,
    ProviderModels,
    ProviderSection,
)
from app.providers.types import ProviderName

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(require_auth)])

_config: ProjectConfig | None = None
_config_path: str = ""


def init_config_deps(config: ProjectConfig, config_path: str = "") -> None:
    global _config, _config_path
    _config = config
    _config_path = config_path


def _get_config() -> ProjectConfig:
    if _config is None:
        raise RuntimeError("ProjectConfig not initialised")
    return _config


class ProviderConfigResponse(BaseModel):
    default: str
    plan: str
    models: ProviderModels


class EgressConfigResponse(BaseModel):
    allow: list[str]


class NotificationsConfigResponse(BaseModel):
    telegram: bool
    email: bool


class ConfigResponse(BaseModel):
    project_name: str
    project_description: str
    provider: ProviderConfigResponse
    egress: EgressConfigResponse
    notifications: NotificationsConfigResponse
    secrets: dict[str, str] = Field(default_factory=dict)


class ProvidersResponse(BaseModel):
    providers: list[str]


class UpdateProviderRequest(BaseModel):
    default: str | None = None
    plan: str | None = None
    models: dict[str, str] | None = None


class UpdateEgressRequest(BaseModel):
    allow: list[str]


class NotificationToggleRequest(BaseModel):
    telegram: bool | None = None
    email: bool | None = None


def _config_response(config: ProjectConfig) -> ConfigResponse:
    return ConfigResponse(
        project_name=config.project.name,
        project_description=config.project.description,
        provider=ProviderConfigResponse(
            default=config.provider.default,
            plan=config.provider.plan,
            models=config.provider.models,
        ),
        egress=EgressConfigResponse(allow=config.egress.allow),
        notifications=NotificationsConfigResponse(
            telegram=config.notifications.telegram,
            email=config.notifications.email,
        ),
        secrets=config.secrets,
    )


@router.get("", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    config = _get_config()
    return _config_response(config)


@router.get("/providers", response_model=ProvidersResponse)
async def get_providers() -> ProvidersResponse:
    return ProvidersResponse(providers=list(get_args(ProviderName)))


@router.put("/provider", response_model=ConfigResponse)
async def update_provider(body: UpdateProviderRequest) -> ConfigResponse:
    config = _get_config()

    update: dict[str, Any] = {}
    if body.default is not None:
        if body.default not in ("claude", "codex", "gemini"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid provider: {body.default}",
            )
        update["default"] = body.default
    if body.plan is not None:
        update["plan"] = body.plan
    if body.models is not None:
        update["models"] = body.models

    try:
        new_provider = config.provider.model_copy(update=update)
        ProviderSection.model_validate(new_provider.model_dump())
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    config.provider = new_provider
    if _config_path:
        save_project_config(config, _config_path)
    return _config_response(config)


@router.put("/egress", response_model=ConfigResponse)
async def update_egress(body: UpdateEgressRequest) -> ConfigResponse:
    config = _get_config()

    try:
        new_egress = EgressSection(allow=body.allow)
        EgressSection.model_validate(new_egress.model_dump())
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    config.egress = new_egress
    if _config_path:
        save_project_config(config, _config_path)
    return _config_response(config)


@router.put("/notifications", response_model=ConfigResponse)
async def update_notifications(
    body: NotificationToggleRequest,
) -> ConfigResponse:
    config = _get_config()

    update: dict[str, Any] = {}
    if body.telegram is not None:
        update["telegram"] = body.telegram
    if body.email is not None:
        update["email"] = body.email

    config.notifications = config.notifications.model_copy(update=update)
    if _config_path:
        save_project_config(config, _config_path)
    return _config_response(config)
