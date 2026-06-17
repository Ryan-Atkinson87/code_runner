from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectSection(BaseModel):
    name: str
    description: str = ""
    root: str = ""


class GitHubIntegration(BaseModel):
    owner: str
    project_board: int | str | None = None


class NotionIntegration(BaseModel):
    workspace: str = ""
    dashboard_page: str = ""
    social_context_page: str = ""


class IntegrationsSection(BaseModel):
    github: GitHubIntegration
    notion: NotionIntegration | None = None


class BranchesSection(BaseModel):
    integration: str = "dev"
    agent_pattern: str = "code-runner/<wave-slug>"
    sync_strategy: Literal["merge", "rebase"] = "merge"


class WaveEntry(BaseModel):
    name: str
    repos: list[dict[str, str]] = Field(default_factory=list)


class WavesSection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: Literal["milestone-name", "explicit", "plan-file"] = "milestone-name"
    plan_file: str = ""
    entries: list[WaveEntry] = Field(default_factory=list, alias="list")


class RepoCommands(BaseModel):
    test: str = ""
    lint: str = ""
    typecheck: str = ""


class RepoEntry(BaseModel):
    name: str
    path: str = "."
    role: str = ""
    backend: bool = False
    package_manager: str = ""
    commands: RepoCommands = Field(default_factory=RepoCommands)


class ProviderModels(BaseModel):
    planning: str = ""
    implementing: str = ""
    reviewing: str = ""


class ProviderSection(BaseModel):
    default: Literal["claude", "codex", "gemini"] = "claude"
    plan: str = ""
    models: ProviderModels = Field(default_factory=ProviderModels)


class UsageSection(BaseModel):
    threshold_percent: int = 80
    peak_hour_throttle: bool = True
    meters: dict[str, Any] = Field(default_factory=dict)


class EgressSection(BaseModel):
    allow: list[str] = Field(default_factory=list)


class NotificationsSection(BaseModel):
    telegram: bool = True
    email: bool = False


class LimitsSection(BaseModel):
    test_fix_attempts: int = 3
    review_cycles: int = 2


class ProjectConfig(BaseModel):
    project: ProjectSection
    integrations: IntegrationsSection
    branches: BranchesSection = Field(default_factory=BranchesSection)
    waves: WavesSection = Field(default_factory=WavesSection)
    repos: list[RepoEntry]
    provider: ProviderSection = Field(default_factory=ProviderSection)
    usage: UsageSection = Field(default_factory=UsageSection)
    egress: EgressSection = Field(default_factory=EgressSection)
    notifications: NotificationsSection = Field(default_factory=NotificationsSection)
    limits: LimitsSection = Field(default_factory=LimitsSection)
    secrets: dict[str, str]
