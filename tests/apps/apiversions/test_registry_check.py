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
        version="2099-01-01", description="test-only newer version"
    )
    monkeypatch.setattr(registry, "REGISTRY", registry.REGISTRY + [extra])
    return extra


class TestRegistryCheck:
    def test_single_unreleased_current_is_ok(self, release_state):
        # Production state right after rollout: one version, not yet tagged.
        assert registry_check.check() == []
        assert registry_check.main() == 0

    def test_all_released_is_ok(self, release_state, two_versions):
        release_state["2026-10-01"] = True
        release_state[two_versions.version] = True
        assert registry_check.check() == []

    def test_unreleased_current_with_released_old_is_ok(
        self, release_state, two_versions
    ):
        release_state["2026-10-01"] = True
        assert registry_check.check() == []

    def test_stacked_unreleased_version_fails(
        self, release_state, two_versions, capsys
    ):
        # Old version never tagged, newer one stacked on it → violation.
        release_state[two_versions.version] = True
        problems = registry_check.check()
        assert len(problems) == 1
        assert "'2026-10-01'" in problems[0]
        assert "Amend" in problems[0]
        assert registry_check.main() == 1
        stderr = capsys.readouterr().err
        assert "stacked" in stderr

    def test_guidance_mentions_amend_workflow(self, release_state, two_versions):
        release_state[two_versions.version] = True
        assert "keep its version date" in registry_check.check()[0]
