from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "agent-runner"
    host: str = "0.0.0.0"
    port: int = 8000
    workdir: str = "/workspace"
    token: str = ""

    model_config = {"env_prefix": "AGENT_RUNNER_"}
