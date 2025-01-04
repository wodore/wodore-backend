from tasks import (
    Ctx,
    doc,
    header,
    success,
    warning,
    task,
)


@task
def lock(c: Ctx):
    """Checking uv lock file"""
    header(doc())
    c.run("uv lock --locked", echo=True, pty=True)


@task
def lint(c: Ctx):
    """Linting code"""
    header(doc())
    c.run("uv run pre-commit run -a", echo=True, pty=True)


@task
def fix(c: Ctx):
    """Fix code with ruff"""
    header(doc())
    c.run("uv run ruff check --fix .", echo=True, pty=True)


@task
def deps(c: Ctx):
    """Checking dependencies"""
    header(doc())
    c.run("uv run deptry .", echo=True, pty=True)


@task
def types(c: Ctx):
    """Static type checking"""
    header(doc())
    c.run("uv run pyright  server", echo=True, pty=True)


@task
def test(c: Ctx):
    """Static type checking"""
    header(doc())
    c.run("pytest -v", echo=True, pty=True)


@task(pre=[lock, lint], default=True)
def check(c: Ctx):
    """Run code quality tools"""
    header("Summary")
    success("Code quality checks passed")
    warning("'check.deps' and 'check.types' were skipped!")
