from tasks import info, error, success, warning, echo, env, task, header, Ctx, EnvError  # noqa: F401
import humanize

from python_on_whales import DockerClient

dc = DockerClient(debug=True)


@task
def login(c: Ctx, token: str | None = None):
    """Login to ghcr (github container registry)

    It uses the GITHUB_TOKEN environment variable to login."""
    try:
        token = token or env.str("GITHUB_TOKEN")
    except EnvError:
        token = input("Github package token: ")
    cmd = "docker login ghcr.io -u GITHUB_USERNAME -p $GITHUB_TOKEN"
    echo(cmd)
    try:
        c.run(cmd.replace("$GITHUB_TOKEN", token), pty=True, hide=True)
    except Exception:
        error("Login failed")
    success("Login successful")


def from_pyproject(c: Ctx, name: str):
    return c.run(
        f"uvx --from=toml-cli toml get --toml-path=pyproject.toml {name}", hide=True
    ).stdout.strip()


def check_dirty_files(c: Ctx, force: bool = False):
    dirty_files = (
        c.run("git diff-files --name-only", hide=True)
        .stdout.strip()
        .strip("\n")
        .strip()
        .split("\n")
    )
    if dirty_files and dirty_files[0]:
        header("Git dirty check")
        warning("Dirty  git files:")
        for f in dirty_files:
            echo(f"[red]{f}[/]")
        if not force:
            error("Git is dirty, abort. Use '--force' to ignore.")
        warning("Git is dirty, but it is ignored due to the '--force' flag.")


@task(
    help={
        "extra_tags": "Comma separted list of additional tags",
        "version_tag": "Include tags with version",
        "force": "Force build even with dirty git",
        "no_next_tag": "Do not onclud 'next' tag",
        "push": "Push to registry (defined in 'pyproject.toml')",
        "registry_tag": "Include tags with the registry (is set to true if '--push' is set)",
        "suffix": "Suffix to be added to a tag (e.g. 'dev')",
    }
)
def build(
    c: Ctx,
    extra_tags: str | None = None,
    version_tag: bool = False,
    force: bool = False,
    no_next_tag: bool = False,
    push: bool = False,
    registry_tag: bool = False,
    suffix: str | None = None,
):
    """Build and pulish docker image"""
    check_dirty_files(c, force=force)
    header("Settings")
    tag_names = [] if no_next_tag else ["next"]
    if version_tag:
        major, minor, bugfix = from_pyproject(c, "project.version").split(".")
        package_version = f"v{major}.{minor}.{bugfix}"
        tag_names.extend([f"v{major}", f"v{major}.{minor}", package_version])
        info(f"Package version: '{package_version}'")

    package_name = from_pyproject(c, "project.name")
    info(f"Package name:    '{package_name}'")
    tags = [f"{package_name}:{name}" for name in tag_names]
    push_tags = []
    if extra_tags:
        tags.extend([t.strip() for t in extra_tags.split(",")])
    if registry_tag or push:
        registry = from_pyproject(c, "tool.docker.registry")
        info(f"Registry:        '{registry}'")
        for t in tags:
            push_tags.append(f"{registry}/{t}")
        tags.extend(push_tags)
    if suffix:
        tags = [f"{t}-{suffix.strip('-')}" for t in tags]
    info("Tags:")
    for tag in tags:
        info(f"  - '{tag}'")
    header("Run docker build job")
    image = dc.buildx.build(context_path=".", tags=tags, pull=True)
    success(
        f"Successfully built the container '{image.id.split(":")[1][:12]}' with a size of [blue]{humanize.naturalsize(image.size)}[/] {humanize.naturaltime(image.created)}."
    )
    if push:
        header("Push to registry")
        info(f"Push to '{registry}/{package_name}' with tags:")
        for tag in push_tags:
            info(f"  - '{tag}'")
        dc.push(push_tags)
        success(f"Pushed to 'https://{registry}/{package_name}'.")


@task
def publish(c: Ctx, no_version_tag: bool = False):
    """Publish to docker registry"""
    build(c, push=True, version_tag=not no_version_tag)
