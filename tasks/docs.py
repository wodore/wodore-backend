from tasks import info, error, success, header, warning, echo, env, task, Ctx, EnvError  # noqa: F401


@task(help={"port": "Port to serve documentation locally, default: '8000'"})
def serve(c: Ctx, port: int = 8000):
    """Serve docu for preview."""
    dev_addr = f"localhost:{port}"
    c.run(f"mkdocs serve --dev-addr {dev_addr}", echo=True, pty=True)


@task
def build(c: Ctx):
    """Build docu."""
    c.run("mkdocs build", echo=True, pty=True)
    success("Documentation build in 'site' directory.")
    info("Run 'python -m http.server -d site' for testing (not in production).")
