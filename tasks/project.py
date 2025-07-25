from pathlib import Path

import toml

from tasks import (  # noqa: F401
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


@task(
    help={
        "infisical": "Use infisical to run it (secret manager)",
        "cmd": "Docker compose command (default: up)",
    },
)
def docker_compose(c: Ctx, infisical: bool = False, cmd: str = "up"):
    """Run any app command with --cmd. E.g. 'inv app.app -i --cmd migrate'"""
    cmd_ = ""
    if infisical:
        cmd_ += "infisical run --env=dev --path /backend --silent --log-level warn -- "
    cmd_ += f"docker compose {cmd}"
    info(f"Run '{cmd_}'")
    c.run(cmd_)


@task(
    help={
        "dry": "Only show what would be done",
        "infisical": "Use infisical to run it (secret manager)",
    }
)
def update_venv(c: Ctx, dry: bool = False, infisical: bool = False):
    """Updated venv activate script with custom commands"""
    commands = [
        "# CUSTOM COMMAND",
        "source <(inv --print-completion-script bash)",
        "complete -F _complete_invoke -o default invoke inv t",
    ]
    if infisical:
        commands.extend(
            ["# App function with infisical", 'app() { inv app.app -i --cmd "$*"; }']
        )
    commands.append("# Required for bash to work properly")
    commands.append("hash -r 2>/dev/null")

    activate_script = ".venv/bin/activate"
    c.run(f"sed -i '/# CUSTOM COMMAND/,$d' {activate_script}") if not dry else None
    for cmd in commands:
        info(f"Append '{cmd}' to activate script")
        c.run(f"echo '{cmd}' >> {activate_script}") if not dry else None
    success("Updated venv activate script") if not dry else success(
        "Would have updated venv activate script"
    )
    info(f"Run 'source {activate_script}'")


@task(
    help={
        "venv_update": "Updates venv activate script (runs per default)",
        "no_private": "Install no private packages (e.g. hut-service-private)",
        "infisical": "Use infisical to run it (secret manager)",
    }
)
def install(
    c: Ctx, venv_update: bool = True, no_private: bool = False, infisical: bool = False
):
    """Install the virtual environment, pre-commit hooks, and create necessary directories (.volumes/pgdata, media/imagor_data)"""
    echo("🚀 Creating virtual environment using uv")
    args = "--extra private" if not no_private else ""
    c.run(f"uv sync {args}")
    c.run("uv run pre-commit install")

    # Create necessary directories
    echo("📁 Creating necessary directories")
    c.run("mkdir -p .volumes/pgdata")
    c.run("mkdir -p media/imagor_data/{storage,result}")

    if venv_update:
        update_venv(c, infisical=infisical)
    success("Installation done, your are ready to go ...")


@task(help={"no_private": "Install no private packages (e.g. hut-service-private)"})
@task(
    help={
        "package": "Update only this package (e.g. wodore-backend or hut-services-private)"
    }
)
def update(c: Ctx, no_private: bool = False, package: str = ""):
    """Update python packages."""
    echo("🚀 Update python packages using uv")
    args = "--extra private" if not no_private else ""
    if package:
        args += f" --upgrade-package {package}"
    else:
        args += " --upgrade"
    c.run(f"uv sync {args}", echo=True)
    c.run("uv lock", echo=True)


@task(
    help={
        "add_tag": "Add the new tag and push it to remote",
        "unreleased": "Show only unreleased changes",
        "length": "Number of lines to show (mutual exclusive with unreleased)",
    }
)
def release(
    c: Ctx,
    add_tag: bool = False,
    dry: bool = False,
    unreleased: bool = True,
    length: int = -1,
):
    """Prepare a release, update CHANGELOG file and bump versions"""
    new_tag = c.run("git-cliff --bumped-version", hide=True).stdout.strip()
    new_version = new_tag.replace("v", "")
    if dry:
        unreleased = unreleased if length < 0 else False
        length = 0 if (not unreleased and length < 0) else length
        (
            echo("Show only 'unreleased' changes")
            if unreleased
            else (
                echo(f"Show {length} lines of changelog")
                if length > 0
                else echo("Show full changelog")
            )
        )
        header("Changelog start") if dry else None
        cl = (
            c.run(
                f"git-cliff --bump {'--unreleased' if unreleased else ''}",
                hide=True,
            )
            .stdout.strip()
            .split("\n")
        )
        if unreleased or length == 0:
            echo("\n".join(cl))
        else:
            line = "\n".join(cl[:length])
            echo(f"{line}\n...\n")
        header("Changelog end") if dry else None
    else:
        cl = (
            c.run("git-cliff --bump -u --prepend CHANGELOG.md", hide=True)
            .stdout.strip()
            .split("\n")
        )
        c.run(f"bump2version --allow-dirty --new-version {new_version} patch")

        # only prepend new tag -- this way it is possible to edit it.
        # cl = c.run(f"git-cliff --bump {'--prepend CHANGELOG.md' if dry else '-o'}", hide=True).stdout.strip().split("\n")
    if new_tag:
        success(f"Bumped to version '{new_version}' (tag '{new_tag}').")
        info("Please check the entries in 'CHANGELOG.md' and update it accordingly.")
        if add_tag and not dry:
            c.run(f"git tag -f '{new_tag}'")
            c.run(f"git push origin '{new_tag}'")
    else:
        warning("Did not update to new version tag.")


@task(help={"next": "Show next version"})
def version(c: Ctx, next: bool = False):
    """Print current or next (--next) project version"""
    version = "unknown"
    # adopt path to your pyproject.toml
    pyproject_toml_file = Path(__file__).parent.parent / "pyproject.toml"
    if pyproject_toml_file.exists() and pyproject_toml_file.is_file():
        data = toml.load(pyproject_toml_file)
        # check project.version
        if "project" in data and "version" in data["project"]:
            version = data["project"]["version"]
        # check tool.poetry.version
        elif (
            "tool" in data
            and "poetry" in data["tool"]
            and "version" in data["tool"]["poetry"]
        ):
            version = data["tool"]["poetry"]["version"]
    if next:
        new_version = (
            c.run("git-cliff --bumped-version", hide=True)
            .stdout.strip()
            .replace("v", "")
        )
        if new_version == version:
            warning("No newer version available")
        echo(new_version)
        return
    echo(version)
