from pathlib import Path

from tasks import (
    Ctx,
    doc,
    header,
    task,
)

_ENV_TEST = Path(__file__).parent.parent / ".env.test"


def _load_env_test():
    """Load .env.test into the current process (key=value lines, no quotes)."""
    if not _ENV_TEST.exists():
        return
    import os
    import re

    with open(_ENV_TEST) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            if m:
                key, val = m.group(1), m.group(2).strip().strip("'\"")
                os.environ.setdefault(key, val)


@task(
    default=True,
    help={
        "create": "Recreate the test database (first run or schema changed)",
        "infisical": "Use infisical to inject secrets instead of .env.test",
        "args": "Extra pytest arguments (e.g. '-k test_name')",
    },
)
def run(c: Ctx, create: bool = False, infisical: bool = False, args: str = ""):
    """Run tests (uses .env.test by default, or -i for infisical)"""
    if not infisical:
        _load_env_test()
    header(doc())

    pytest_args = []
    if create:
        pytest_args.append("--create-db")
    if args:
        pytest_args.append(args)

    cmd = ""
    if infisical:
        cmd += "infisical run --env=dev --path /backend --silent --log-level warn -- "
    cmd += f"pytest -v {' '.join(pytest_args)}"

    c.run(cmd, echo=True, pty=True)
