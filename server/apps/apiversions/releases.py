"""Release-state helpers shared by snapshotting and registry checks.

Stdlib-only (no Django import) so CI can run these from a plain python3.
"""

from __future__ import annotations

import subprocess


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
