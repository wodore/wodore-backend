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
)
def app(c: Ctx, infisical: bool = False, cmd: str = ""):
    """Run any app command with --cmd. E.g. 'inv app.app -i --cmd migrate'"""
    cmd_ = ""
    if infisical:
        # NOTE: no --silent here — it swallows the CHILD's stdout too,
        # making interactive commands (createsuperuser) look hung: prompts
        # are printed but never shown. --log-level warn keeps infisical's
        # own output quiet.
        cmd_ += "infisical run --env=dev --path /backend --log-level warn -- "
    cmd_ += f"app {cmd}"
    info(f"Run '{cmd_}'")
    c.run(cmd_, pty=True)


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
        cmd += "infisical run --env=dev --path /backend --log-level warn -- "
    cmd += f"app runserver {port}"
    info(f"Run '{cmd}'")
    c.run(cmd, pty=True)
