import os


class SecretResolutionError(Exception):
    pass


def resolve_secrets(secrets_map: dict[str, str]) -> dict[str, str]:
    """Resolve secret env-var names from project.yaml to their runtime values.

    Args:
        secrets_map: Mapping of logical name -> env-var name (e.g. {"github_pat": "GITHUB_PAT"}).

    Returns:
        Mapping of logical name -> resolved value.

    Raises:
        SecretResolutionError: If any required env var is missing.
    """
    missing = [
        f"  {logical_name} -> ${env_var}"
        for logical_name, env_var in secrets_map.items()
        if env_var not in os.environ
    ]
    if missing:
        detail = "\n".join(missing)
        raise SecretResolutionError(
            f"Missing required environment variables:\n{detail}\n"
            "Set them in .env or export them before starting the engine."
        )

    return {
        logical_name: os.environ[env_var]
        for logical_name, env_var in secrets_map.items()
    }
