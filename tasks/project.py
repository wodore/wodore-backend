from tasks import info, error, success, header, warning, echo, env, task, Ctx, EnvError  # noqa: F401
import toml
from pathlib import Path


@task
def update_venv(c: Ctx, dry: bool = False):
    """Updated venv activate script with custom commands"""
    commands = [
        "# custom command",
        'alias t="inv -p"',
        'alias tl="inv --list"',
        "source <(inv --print-completion-script bash)",
        "complete -F _complete_invoke -o default invoke inv t",
    ]
    for cmd in commands:
        info(f"Append '{cmd}' to activate script")
        c.run(f"echo '{cmd}' >> .venv/bin/activate") if not dry else None
    success("Updated venv activate script") if not dry else success(
        "Would have updated venv activate script"
    )
    info("Run 'source .venv/bin/activate'")


@task(help={"venv_update": "Updates venv activate script (runs per default)"})
def install(c: Ctx, venv_update: bool = True):
    """Install the uv environment and install the pre-commit hooks"""
    echo("🚀 Creating virtual environment using pyenv and poetry")
    c.run("uv sync")
    c.run("uv run pre-commit install")
    if venv_update:
        update_venv(c)
    success("Installation done, your are ready to go ...")


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
            echo(f"{"\n".join(cl[:length])}\n...\n")
        header("Changelog end") if dry else None
    else:
        cl = (
            c.run("git-cliff --bump -u --prepend CHANGELOG.md", hide=True)
            .stdout.strip()
            .split("\n")
        )
        c.run(f"bump2version --new-version {new_version} patch")

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
