from tasks import (
    doc,
    header,
    task,
    Ctx,
)


@task
def run(c: Ctx):
    """Run tests"""
    header(doc())
    c.run("pytest -v", echo=True, pty=True)
