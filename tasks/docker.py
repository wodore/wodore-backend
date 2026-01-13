import os
import tempfile
import time
from pathlib import Path
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
DEFAULT_DISTRO = "alpine"

RUN_WEBSERVER_PROD = (
    "gunicorn -b 0.0.0.0:{port} -w {workers} --preload server.wsgi:application"
)

RUN_WEBSERVER_DEV = "python -Wd manage.py runserver 0.0.0.0:{port}"


@task
def login(c: Ctx, token: str | None = None):
    """Login to ghcr (github container registry)

    It uses the GITHUB_TOKEN environment variable to login."""
    try:
        token = token or env.str("DOCKER_GITHUB_TOKEN")
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


def get_tags(
    c: Ctx,
    suffix: str | None = None,
    version_tag: bool = False,
    registry_tag: bool = False,
    no_edge_tag: bool = False,
    extra_tags: str | None = None,
    package_name: str | None = None,
    registry: str | None = None,
    no_sha_tag: bool = False,
) -> tuple[list[str], list[str]]:
    from datetime import datetime

    tag_names = [] if no_edge_tag else ["edge"]
    if version_tag:
        major, minor, bugfix = from_pyproject(c, "project.version").split(".")
        package_version = f"{major}.{minor}.{bugfix}"
        tag_names.extend(["latest", f"{major}", f"{major}.{minor}", package_version])
        info(f"Package version: '{package_version}'")

    if not no_sha_tag:
        git_short_hash = c.run("git rev-parse --short HEAD", hide=True).stdout.strip()
        # Add timestamp + SHA tag (matching CI format: YYYYMMDDTHHmm-sha-<short-sha>)
        timestamp = datetime.now().strftime("%Y%m%dT%H%M")
        tag_names += [f"{timestamp}-sha-{git_short_hash}"]
        info(f"Git hash:        '{git_short_hash}'")
        info(f"Timestamp tag:   '{timestamp}-sha-{git_short_hash}'")
    package_name = package_name or from_pyproject(c, "project.name")
    tags = [f"{package_name}:{name}" for name in tag_names]
    push_tags = []
    if extra_tags:
        tags.extend([t.strip() for t in extra_tags.split(",")])
    if suffix:
        tags = [f"{t}-{suffix.strip('-')}" for t in tags]
    if registry_tag:
        registry = registry or from_pyproject(c, "tool.docker.registry")
        info(f"Registry:        '{registry}'")
        for t in tags:
            push_tags.append(f"{registry}/{t}")
        tags.extend(push_tags)
    info("Tags:")
    for tag in tags:
        info(f"  - '{tag}'")
    return (tags, push_tags)


class DotEnv(object):
    """Create django .env file and delete it afterwards again"""

    def __init__(self, context: Ctx):
        fd, self.path = tempfile.mkstemp()
        dot_env = context.run(
            "./docker/django/get_env.sh --env dev", hide=True
        ).stdout.strip()
        with os.fdopen(fd, "w") as tmp:
            tmp.write(dot_env)

    def __enter__(self):
        return self.path

    def __exit__(self, type, value, traceback):
        info(f"Remove .env file: '{self.path}'")
        os.remove(self.path)


def get_distros(
    distro: Literal["alpine", "ubuntu", "all"] = DEFAULT_DISTRO,
) -> list[Literal["alpine", "ubuntu"]]:
    if distro not in ["alpine", "ubuntu", "all"]:
        error("Supported distros: 'alpine', 'ubuntu', or 'all'")
    if distro == "all":
        distros = ["alpine", "ubuntu"]
    else:
        distros = [distro]
    return distros


@task(
    help={
        "distro": "Distro name: alpine, ubuntu or all",
        "tag": "tag used (without repo and distor, e.g. edge or 0.2.3)",
        "slim": "include slim builds",
    }
)
def show(
    c: Ctx,
    distro: Literal["alpine", "ubuntu", "all"] = "alpine",
    tag: str = "edge",
    slim: bool = False,
):
    """Show docker image information"""
    distros = get_distros(distro)
    package_name = from_pyproject(c, "project.name")
    docker_ls = [f"{package_name}:{tag}-{d}" for d in distros]
    if slim:
        docker_ls += [f"{package_name}:{tag}-{d}-slim" for d in distros]
    filters = [f"--filter reference={ls}" for ls in docker_ls]
    out = (
        c.run(f"docker images {' '.join(filters)}", hide=True)
        .stdout.strip()
        .split("\n")
    )
    echo(f"[b]{out[0]}[/]")
    for line in out[1:]:
        echo(f"[green]{line}[/]") if "-slim" in line else echo(f"[blue]{line}[/]")


@task(
    default=True,
    name="build",
    help={
        "distro": "Distro name: alpine*, ubuntu or all",
        "extra_tags": "Comma separted list of additional tags",
        "version_tag": "Include tags with version",
        "force": "Force build even with dirty git",
        "no_edge_tag": "Do not include 'edge' tag",
        "push": "Push to registry (defined in 'pyproject.toml' or with --registry)",
        "registry_tag": "Include tags with the registry (is set to true if '--push' is set)",
        "suffix": "Suffix to be added to a tag (e.g. 'dev')",
        "with_dev": "Build with dev dependencies",
        "django_env": "Django environment: development, production, prod_development",
        "registry": "Registry name, can be set in the 'pyproject.toml#tool.docker.registry' section",
        "plain": "Plain progressbar",
        "rebuild": "Force rebuild",
        "no_sha_tag": "Do not include git hash (sha) tag",
    },
)
def buildx(
    c: Ctx,
    distro: Literal["alpine", "ubuntu", "all"] = DEFAULT_DISTRO,
    extra_tags: str | None = None,
    version_tag: bool = False,
    force: bool = False,
    no_edge_tag: bool = False,
    push: bool = False,
    registry_tag: bool = False,
    suffix: str | None = None,
    with_dev: bool = False,
    django_env: Literal[
        "development", "production", "prod_development"
    ] = "development",
    registry: str | None = None,
    github_user: str | None = None,
    github_token: str | None = None,
    plain: bool = False,
    rebuild: bool = False,
    no_sha_tag: bool = False,
):
    """Build and pulish (with --push) docker image"""
    distros = get_distros(distro)
    github_user = github_user if github_user else env.str("DOCKER_GITHUB_USER", "")
    github_token = github_token if github_token else env.str("DOCKER_GITHUB_TOKEN", "")
    if not github_token:
        warning(
            "No github token found in env var 'READ_GITHUB_TOKEN' or '--github-token' parameter."
        )
        warning("Private repos are not installed.")
    else:
        info(f"Github user:     '{github_user}'")
    for dist in distros:
        check_dirty_files(c, force=force)
        suffix_ = dist if suffix is None else suffix
        package_name = from_pyproject(c, "project.name")
        header("Settings")
        info(f"Package name:    '{package_name}'")
        info(f"Distro:          '{dist}'")
        tags, push_tags = get_tags(
            c,
            suffix=suffix_,
            version_tag=version_tag,
            registry_tag=registry_tag or push,
            no_edge_tag=no_edge_tag,
            extra_tags=extra_tags,
            package_name=package_name,
            registry=registry,
            no_sha_tag=no_sha_tag,
        )
        dockerfile = f"./docker/django/Dockerfile.{dist}"
        git_short_hash = c.run("git rev-parse --short HEAD", hide=True).stdout.strip()
        build_args = {
            "DJANGO_ENV": django_env,
            "WITH_DEV": "1" if with_dev else "0",
            "GIT_HASH": git_short_hash,
        }
        info(f"Git hash:        '{git_short_hash}'")
        info(f"Django env:      '{django_env}'")
        info(f"Wit dev deps:    '{with_dev}'")
        header("Run docker build job")
        secrets = []
        if github_token:
            if not github_user:
                error(
                    "Github user must be set if github token is set (READ_GITHUB_USER or --github-user)"
                )
            os.environ["READ_GITHUB_TOKEN"] = github_token
            os.environ["READ_GITHUB_USER"] = github_user
            secrets.append("id=READ_GITHUB_TOKEN")
            secrets.append("id=READ_GITHUB_USER")
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
                # ssh="default",
                build_args=build_args,
                progress="plain" if plain else "auto",
                secrets=secrets,
                cache=not rebuild,
            )
        except Exception as e:
            error(f"Failed to build the container.\n{e}")
        success(
            f"Successfully built the container '{image.id.split(':')[1][:12]}' with a size of [blue]{humanize.naturalsize(image.size)}[/] {humanize.naturaltime(image.created)}."
        )
        if push:
            pkg_registry, _ = push_tags[0].split(":")
            header("Push to registry")
            info(f"Push to '{pkg_registry}' with tags:")
            for tag in push_tags:
                info(f"  - '{tag}'")
            dc.push(push_tags)
            success(f"Pushed to 'https://{pkg_registry}'.")
    show(c, distro=distro, tag=tags[0].split(":")[1].split("-")[0])


@task(
    help={
        "build": "Build container first (run 'docker.build')",
        "distro": "Distro name: alpine, ubuntu or all",
        "extra_tags": "Comma separted list of additional tags",
        "version_tag": "Include tags with version",
        "no_edge_tag": "Do not include 'edge' tag",
        "push": "Push to registry (defined in 'pyproject.toml')",
        "registry_tag": "Include tags with the registry (is set to true if '--push' is set)",
        "suffix": "Suffix to be added to a tag (e.g. 'dev')",
        "port": "Open port",
        "tag_fat": "Tag used for the fat image (default: edge)",
        "force": "Force build even with dirty git",
        "registry": "Registry name, can be set in pyproject.toml tool.docker.registry",
        "no_sha_tag": "Do not include git hash (sha) tag",
    }
)
def slim(
    c: Ctx,
    distro: Literal["alpine", "ubuntu"] = DEFAULT_DISTRO,
    extra_tags: str | None = None,
    version_tag: bool = False,
    no_edge_tag: bool = False,
    push: bool = False,
    registry_tag: bool = False,
    suffix: str | None = None,
    port: int = 8010,
    tag_fat: str = "edge",
    registry: str | None = None,
    force: bool = False,
    build: bool = False,
    no_sha_tag: bool = False,
):
    """Slim and publish docker image"""
    if build:
        buildx(
            c,
            distro=distro,
            version_tag=version_tag,
            no_edge_tag=no_edge_tag,
            push=push,
            registry_tag=registry_tag,
            registry=registry,
            force=force,
        )
    distros = get_distros(distro)
    run_webserver = RUN_WEBSERVER_DEV.format(port=port, workers=2)
    docker_ls = []
    for dist in distros:
        package_name = from_pyproject(c, "project.name")
        docker_image = f"{package_name}:{tag_fat}-{dist}"
        header("Settings")
        info(f"Package name:    '{package_name}'")
        info(f"Distro:          '{dist}'")
        info(f"Target:          '{docker_image}'")
        suffix_ = f"{dist}-slim" if suffix is None else suffix
        tags, push_tags = get_tags(
            c,
            suffix=suffix_,
            version_tag=version_tag,
            registry_tag=registry_tag or push,
            no_edge_tag=no_edge_tag,
            extra_tags=extra_tags,
            package_name=package_name,
            registry=registry,
            no_sha_tag=no_sha_tag,
        )
        tag_args = [f'--tag "{tag}"' for tag in tags]
        cmd = [
            "mint slim",
            f"--target {docker_image}",
            '--workdir "/code"',
            f"--expose {port}",
            f"--env DJANGO_DATABASE_HOST={DJANGO_DATABASE_HOST}",
            f'--cmd "{run_webserver}"',
            f"--publish-port {port}:{port}",
            *tag_args,
            f'--label org.opencontainers.image.description="Wodore backend based on {dist} (gdal) image and slimmed down"',
            "--network wodore-backend_postgresnet",
            "--include-workdir",
            '--http-probe-cmd "crawl:/v1/huts/huts.geojson?limit=5"',
            '--http-probe-cmd "crawl:/v1/huts/bookings.geojson"',
            '--http-probe-cmd "crawl:/"',
            "--http-probe",
        ]
        with DotEnv(c) as dot_env_file:
            cmd.append(f"--env-file {dot_env_file}")
            header("Run docker slim job")
            echo(" \\\n  ".join(cmd))
            c.run(" ".join(cmd))
        if push:
            pkg_registry, _ = push_tags[0].split(":")
            header("Push to registry")
            info(f"Push to '{pkg_registry}' with tags:")
            for tag in push_tags:
                info(f"  - '{tag}'")
            dc.push(push_tags)
            success(f"Pushed to 'https://{pkg_registry}'.")
        docker_ls.append(tags[0])
    show(c, distro=distro, tag=tags[0].split(":")[1].split("-")[0], slim=True)


@task(
    help={
        "distro": "Distro name: alpine, ubuntu or all",
        "tag": "Tag which should be run (default: edge) (without '-slim', use --slim option)",
        "slim": "Use slim version",
        "gunicorn": "Run gunicorn instead of development server",
        "suffix": "Suffix to be added to a tag (e.g. 'dev')",
        "port": "Open port",
        "detach": "Detach run",
    }
)
def run(
    c: Ctx,
    distro: Literal["alpine", "ubuntu"] = DEFAULT_DISTRO,
    tag: str = "edge",
    slim: bool = False,
    gunicorn: bool = False,
    suffix: str | None = None,
    port: int = 8010,
    detach: bool = False,
):
    """Run a docker image"""
    if distro not in ["alpine", "ubuntu"]:
        error("Supported distros: 'alpine', 'ubuntu', or 'all'")
    package_name = from_pyproject(c, "project.name")
    suffix = distro if suffix is None else suffix
    suffix = suffix + "-slim" if slim else suffix
    image = f"{package_name}:{tag}-{suffix}"
    cmd = (
        (RUN_WEBSERVER_PROD if gunicorn else RUN_WEBSERVER_DEV)
        .format(port=port, workers=2)
        .split(" ")
    )
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
    with DotEnv(c) as dot_env_file:
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
            env_files=[dot_env_file],
        )
        if detach:
            time.sleep(2)
    # try:
    #    joblib_tmp.rmdir()
    # except OSError as e:
    #    warning("Remove directory: " + str(e))
    if detach:
        info(f"Open 'http://0.0.0.0:{port}'.")
        info(f"Run 'docker stop {container.name}' to stop the container again")


@task(
    # aliases = ["pub"],
    help={
        "distro": "Distro name: alpine, ubuntu or all (default: ubuntu)",
        "version_tag": "Include tags with version",
        "slim": "Include slim version as well",
    }
)
def publish(
    c: Ctx,
    version_tag: bool = False,
    distro: Literal["alpine", "ubuntu"] = DEFAULT_DISTRO,
    slim: bool = False,
):
    """Publish to docker registry"""
    buildx(c, distro=distro, version_tag=version_tag, push=True)
    if slim:
        slim(c, push=True, version_tag=version_tag, distro=distro)
