"""Registry release-state check: at most ONE unreleased API version.

API versions are cut at release time (the docker build shipping the
registry's current version cuts the `api/<date>` tag — see
.github/workflows/new-api-version.yml). Therefore every registry version
except the current one must be released (tagged). A breaking change merged
while the current version is still unreleased must AMEND that version's
``VersionChange`` (merge transforms into it, keep its date, regenerate its
snapshot) instead of stacking a new version on top — a version no client
ever received must not become its own contract boundary, and it would never
be tagged (CI tags only the current version).

Usage (stdlib-only, no Django, no venv):

    python3 -m server.apps.apiversions.registry_check

Exit 0 = healthy, exit 1 = stacking violation (with guidance).
CI runs this on every PR (.github/workflows/test.yml, job ``api-registry``,
with full tag history) — it cannot live in the pytest suite because test
checkouts are shallow and would see every version as unreleased.
"""

from __future__ import annotations

import sys

from . import registry
from .releases import is_released

AMEND_GUIDANCE = (
    "Amend the unreleased VersionChange in your PR instead of stacking a "
    "new version: merge/extend its transforms, keep its version date, "
    "regenerate its snapshot ('app api_snapshot'). Alternatively release "
    "first so the older version gets its api/ tag."
)


def check() -> list[str]:
    """All violations: non-current versions that were never released."""
    problems: list[str] = []
    versions = registry.versions()
    for version in versions[:-1]:  # everything except the current one
        if version == registry.UNRELEASED:
            # "unreleased" must never survive a release — if it's no
            # longer current, the freeze step was skipped.
            problems.append(
                "API version 'unreleased' is no longer current: a newer "
                "version was stacked on it. Run 'inv api-freeze' to "
                "assign a real date before adding the next version."
            )
            continue
        if not is_released(version):
            problems.append(
                f"API version {version!r} is no longer current but was "
                f"never released (no 'api/{version}' tag): a newer version "
                f"was stacked on an unreleased one. {AMEND_GUIDANCE}"
            )
    return problems


def main() -> int:
    versions = registry.versions()
    current = registry.current_version()
    print(f"Registry: {len(versions)} version(s)")
    for version in versions:
        state = "released" if is_released(version) else "UNRELEASED"
        marker = " (current)" if version == current else ""
        print(f"  {version}  {state}{marker}")
    problems = check()
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    print("OK: at most one unreleased version (the current one).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
