from tasks import (
    Ctx,
    doc,
    header,
    success,
    task,
    warning,
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
    """Static type checking (pyrefly, full-strict: every error fails)"""
    header(doc())
    c.run("uv run pyrefly check", echo=True, pty=True)


@task
def test(c: Ctx):
    """Static type checking"""
    header(doc())
    c.run("pytest -v", echo=True, pty=True)


@task(pre=[lock, lint, types], default=True)
def check(c: Ctx):
    """Run code quality tools"""
    header("Summary")
    success("Code quality checks passed")
    warning("'check.deps' was skipped!")
