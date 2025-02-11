from tasks import (  # noqa: F401
    Ctx,
    EnvError,
    echo,
    env,
    error,
    header,
    info,
    success,
    task,
    warning,
)


@task(
    help={
        "infisical": "Use infisical to run it (secret manager)",
    },
    aliases=["runserver"],
)
def run(c: Ctx, port: str = "8093", infisical: bool = False):
    """Run django 'runserver', only for development"""
    cmd = ""
    if infisical:
        cmd += "infisical run --env=dev --path /backend --silent --log-level warn -- "
    cmd += f"app runserver {port}"
    info(f"Run '{cmd}'")
    c.run(cmd)
