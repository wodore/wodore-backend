from tasks import (
    Ctx,
    doc,
    header,
    task,
)


@task
def run(c: Ctx):
    """Run tests"""
    header(doc())
    c.run("pytest -v", echo=True, pty=True)
