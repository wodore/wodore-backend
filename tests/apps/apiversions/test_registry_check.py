"""Tests for the registry release-state check (at most one unreleased version).

The check itself is stdlib-only and CI-gated (test.yml 'api-registry' step,
full tag history); these tests pin its logic with a faked release state.
"""

import pytest

from server.apps.apiversions import registry, registry_check


@pytest.fixture
def release_state(monkeypatch):
    """Fake per-version release state (version -> released?)."""
    state: dict[str, bool] = {}

    def _is_released(version: str) -> bool:
        return state.get(version, False)

    monkeypatch.setattr(registry_check, "is_released", _is_released)
    return state


@pytest.fixture
def two_versions(monkeypatch):
    extra = registry.VersionChange(
        version="zzzz-01-01", description="test-only newer version"
    )
    monkeypatch.setattr(registry, "REGISTRY", registry.REGISTRY + [extra])
    return extra


class TestRegistryCheck:
    """Baseline: dates released, 'unreleased' current. Fake versions must
    sort after 'unreleased' (zzzz-*) to become current."""

    def _release_all_but_current(self, release_state, current=None):
        """Release every non-current version in the fake state."""
        versions = registry.versions()
        target = current or versions[-1]
        for version in versions:
            if version != target:
                release_state[version] = True

    def test_unreleased_current_with_released_old_is_ok(self, release_state):
        self._release_all_but_current(release_state)
        assert registry_check.check() == []
        assert registry_check.main() == 0

    def test_all_released_is_ok(self, release_state, two_versions):
        self._release_all_but_current(release_state, two_versions.version)
        # "unreleased" is always flagged when non-current (it should never
        # survive past a release) — the test fake makes it non-current
        problems = registry_check.check()
        assert len(problems) == 1
        assert "unreleased" in problems[0]

    def test_unreleased_current_with_released_old_is_ok_extra(self, release_state):
        # Without two_versions, "unreleased" IS current → no problems
        # (this test runs without the fixture's fake version)
        self._release_all_but_current(release_state)
        assert registry_check.check() == []

    def test_stacked_unreleased_version_fails(
        self, release_state, two_versions, capsys
    ):
        # "unreleased" is non-current (the fixture version is current)
        # and never released → violation.
        self._release_all_but_current(release_state, two_versions.version)
        # Un-release "unreleased" to trigger the violation
        release_state["unreleased"] = False
        problems = registry_check.check()
        assert len(problems) == 1
        assert "unreleased" in problems[0]
        assert "api-freeze" in problems[0]
        assert registry_check.main() == 1
        stderr = capsys.readouterr().err
        assert "unreleased" in stderr

    def test_guidance_mentions_amend_workflow(self, release_state, two_versions):
        self._release_all_but_current(release_state, two_versions.version)
        release_state["unreleased"] = False
        problems = registry_check.check()
        assert len(problems) == 1
        assert "api-freeze" in problems[0]
