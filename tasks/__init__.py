from invoke.collection import Collection
from invoke.context import Context as Ctx
from invoke.tasks import task

# Bind the re-exported helpers BEFORE loading submodules: siblings do
# `from tasks import EnvError, doc, ...` while `tasks` is still initializing
# (partial-module import), so this order is load-bearing.
from tasks._env import EnvError, env  # isort: skip
from tasks._logger import doc, echo, error, header, info, success, warning  # isort: skip

from tasks import app, changelog, check, docker, docs, project, tests


@task
def help(c: Ctx):
    """Show this help"""
    c.run("inv --list", pty=True)


ns = Collection(
    app,
    app.run,
    project.install,
    project.update,
    project.release,
    project.api_release,
    project.api_freeze,
    project.version,
    project.update_venv,
    project.docker_compose,
    docs,
    tests,
    check,
    docker,
    docker.publish,
    changelog.changelog,
    help,
)


__all__ = (
    "Ctx",
    "EnvError",
    "doc",
    "echo",
    "env",
    "error",
    "header",
    "info",
    "install",
    "success",
    "warning",
)
