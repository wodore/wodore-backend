import os
from pathlib import Path
import tempfile
import time
from typing import Literal
import humanize
from python_on_whales import DockerClient

from tasks import (
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

dc = DockerClient(debug=True)

DJANGO_DATABASE_HOST = "django-local-postgis"


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
        "no_edge_tag": "Do not include 'edge' tag",
        "push": "Push to registry (defined in 'pyproject.toml')",
        "registry_tag": "Include tags with the registry (is set to true if '--push' is set)",
        "suffix": "Suffix to be added to a tag (e.g. 'dev')",
    }
)
def build(
    c: Ctx,
    distro: Literal["alpine", "ubuntu"] = "alpine",
    extra_tags: str | None = None,
    version_tag: bool = False,
    force: bool = False,
    no_edge_tag: bool = False,
    push: bool = False,
    registry_tag: bool = False,
    suffix: str | None = None,
    with_dev: bool = False,
    env: Literal["development", "production", "prod_development"] = "development",
):
    """Build and pulish docker image"""
    if distro not in ["alpine", "ubuntu", "all"]:
        error("Supported distros: 'alpine', 'ubuntu', or 'all'")
    if distro == "all":
        distros = ["alpine", "ubuntu"]
    else:
        distros = [distro]
    for dist in distros:
        check_dirty_files(c, force=force)
        header("Settings")
        tag_names = [] if no_edge_tag else ["edge"]
        if version_tag:
            major, minor, bugfix = from_pyproject(c, "project.version").split(".")
            package_version = f"{major}.{minor}.{bugfix}"
            tag_names.extend([f"{major}", f"{major}.{minor}", package_version])
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
        suffix = dist if suffix is None else suffix
        if suffix:
            tags = [f"{t}-{suffix.strip('-')}" for t in tags]
        info("Tags:")
        for tag in tags:
            info(f"  - '{tag}'")
        header("Run docker build job")
        dockerfile = f"./docker/django/Dockerfile.{dist}"
        build_args = {"DJANGO_ENV": env, "WITH_DEV": "1" if with_dev else "0"}
        labels = {
            "org.opencontainers.image.description": f"Wodore backend based on {dist} (gdal) image"
        }
        try:
            image = dc.buildx.build(
                context_path=".",
                tags=tags,
                pull=True,
                labels=labels,
                file=dockerfile,
                ssh="default",
                build_args=build_args,
            )
        except Exception as e:
            error(f"Failed to build the container.\n{e}")
        success(
            f"Successfully built the container '{image.id.split(':')[1][:12]}' with a size of [blue]{humanize.naturalsize(image.size)}[/] {humanize.naturaltime(image.created)}."
        )
        if push:
            header("Push to registry")
            info(f"Push to '{registry}/{package_name}' with tags:")
            for tag in push_tags:
                info(f"  - '{tag}'")
            dc.push(push_tags)
            success(f"Pushed to 'https://{registry}/{package_name}'.")


@task
def run(
    c: Ctx,
    distro: Literal["alpine", "ubuntu"] = "alpine",
    extra_tags: str | None = None,
    version_tag: bool = False,
    no_edge_tag: bool = False,
    tag: str = "edge",
    suffix: str | None = None,
    env: Literal["development", "production", "prod_development"] = "development",
    port: int = 8010,
    detach: bool = False,
):
    """Build and pulish docker image"""
    if distro not in ["alpine", "ubuntu"]:
        error("Supported distros: 'alpine', 'ubuntu', or 'all'")
    package_name = from_pyproject(c, "project.name")
    suffix = distro if suffix is None else suffix
    image = f"{package_name}:{tag}-{suffix}"
    cmd = ["python", "-Wd", "manage.py", "runserver", f"0.0.0.0:{port}"]
    fd, path = tempfile.mkstemp()
    joblib_tmp = Path("./.joblib_tmp")
    (joblib_tmp / "py_file_cache/joblib").mkdir(mode=0o777, parents=True, exist_ok=True)
    (joblib_tmp / "hut_services_private").mkdir(mode=0o777, parents=True, exist_ok=True)
    (joblib_tmp / "hut_services").mkdir(mode=0o777, parents=True, exist_ok=True)
    joblib_tmp.chmod(0o777)
    fail = 0
    for dir in joblib_tmp.glob("**/"):
        try:
            dir.chmod(0o777)
        except PermissionError as e:
            fail += 1
            if fail < 4:
                warning("Change chmod to 0777: " + str(e))
            elif fail == 4:
                warning("...")
    try:
        dot_env = c.run(
            "./docker/django/get_env.sh --env dev", hide=True
        ).stdout.strip()
        with os.fdopen(fd, "w") as tmp:
            tmp.write(dot_env)
        info(f"Run docker container '{image}' with command '{' '.join(cmd)}'")
        container = dc.run(
            image=image,
            command=cmd,
            tty=not detach,
            detach=detach,
            # name=package_name,
            publish=[(port, port)],
            volumes=[(f"./{joblib_tmp}", "/tmp/py_file_cache/joblib")],
            networks=["wodore-backend_postgresnet"],
            envs={"DJANGO_DATABASE_HOST": DJANGO_DATABASE_HOST},
            env_files=[path],
        )
        if detach:
            time.sleep(2)
    finally:
        info(f"Remove .env file: '{path}'")
        os.remove(path)
        try:
            joblib_tmp.rmdir()
        except OSError as e:
            warning("Remove directory: " + str(e))
    if detach:
        info(f"Open 'http://0.0.0.0:{port}'.")
        info(f"Run 'docker stop {container.name}' to stop the container again")


@task
def publish(c: Ctx, no_version_tag: bool = False):
    """Publish to docker registry"""
    build(c, push=True, version_tag=not no_version_tag)
