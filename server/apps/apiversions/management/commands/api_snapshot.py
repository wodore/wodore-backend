"""Release-time OpenAPI snapshot: freeze the schema per API version.

Run when releasing an API version (README "Releasing an API version"):

    app api_snapshot            # writes server/apps/apiversions/openapi/
    app api_snapshot --check    # CI: exit 1 if current version has none

Snapshots are committed; ``/v1/openapi.json?api_version=<v>`` serves them
for older supported versions (api-docs spec).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from server.apps.apiversions import registry

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "openapi"


def snapshot_path(version: str) -> Path:
    return SNAPSHOT_DIR / f"{version}.json"


def load_snapshot(version: str) -> dict | None:
    path = snapshot_path(version)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def is_released(version: str) -> bool:
    """A version is released once its `api/<version>` tag exists.

    Snapshots of released versions are frozen release records — regenerating
    one would rewrite history (docs drift is intentional, see the runbook).
    While a version is still unreleased (PR iteration, no tag yet),
    regenerating is free.
    """
    try:
        result = subprocess.run(
            ["git", "tag", "-l", f"api/{version}"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return False  # git unavailable: don't block on environment quirks
    return bool(result.stdout.strip())


class Command(BaseCommand):
    help = "Write a frozen OpenAPI snapshot for the current API version."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--check",
            action="store_true",
            help="Do not write; fail if the current version has no snapshot.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite the snapshot even if this version is already "
            "released (tag api/<version> exists).",
        )
        parser.add_argument(
            "--output-dir",
            type=Path,
            default=None,
            help="Write snapshots to this directory instead of the app dir.",
        )

    def handle(self, *args, **options) -> None:
        from server.apps.api.api_v1 import api

        version = registry.current_version()
        target_dir = options["output_dir"] or SNAPSHOT_DIR
        target = target_dir / f"{version}.json"

        if options["check"]:
            if not snapshot_path(version).exists():
                msg = (
                    f"No OpenAPI snapshot for the current API version "
                    f"{version!r}. Run 'app api_snapshot' and commit the "
                    f"file (README: Releasing an API version)."
                )
                raise CommandError(msg)
            self.stdout.write(f"Snapshot present for {version}.")
            return

        if target.exists() and not options["force"] and is_released(version):
            msg = (
                f"Snapshot for {version!r} is frozen (tag 'api/{version}' "
                f"exists — released versions are never regenerated; docs "
                f"drift is intentional). Use --force to override."
            )
            raise CommandError(msg)

        schema = api.get_openapi_schema()
        schema["info"]["version"] = version
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(schema, indent=2, sort_keys=True, default=str) + "\n"
        )  # default=str resolves lazy i18n proxies
        self.stdout.write(f"Snapshot written: {target}")
