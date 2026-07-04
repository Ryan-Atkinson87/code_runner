from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "orchestrator-api"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    root_path: str = ""
    project_config_path: str = ""
    execution_profile_path: str = "execution-profile.yaml"
    db_path: str = ""

    model_config = {"env_prefix": "CODE_RUNNER_"}
