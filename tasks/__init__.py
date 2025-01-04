from _env import EnvError, env
from _logger import doc, echo, error, header, info, success, warning
from invoke.collection import Collection
from invoke.context import Context as Ctx
from invoke.tasks import task

import tasks.changelog as changelog
import tasks.check as check
import tasks.docker as docker
import tasks.docs as docs
import tasks.project as project
import tasks.tests as tests


@task
def help(c: Ctx):
    """Show this help"""
    c.run("inv --list", pty=True)


ns = Collection(
    project.install,
    project.release,
    project.version,
    project.update_venv,
    docs,
    tests,
    check,
    docker,
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
