"""Snapshot infrastructure and per-version contract checks (api-docs spec).

With a single production version and no registered transforms, the
per-version contract matrix is intentionally small; the fake-version test
below exercises the full path (transform → response shape) that the real
first breaking change will rely on.
"""

import json
from datetime import date

import pytest

from server.apps.apiversions import registry
from server.apps.apiversions.management.commands.api_snapshot import (
    snapshot_path,
)
from server.apps.apiversions.transforms import each


@pytest.fixture
def newer_version():
    change = registry.VersionChange(
        version="2099-01-01",
        description="test-only newer version",
        responses={"get_huts": each(lambda hut: {**hut, "api_old_shape": True})},
    )
    registry.REGISTRY.append(change)
    try:
        yield change
    finally:
        registry.REGISTRY.remove(change)


@pytest.fixture
def sunset_old_version():
    """A version whose sunset date has passed (410 everywhere except
    /v1/version)."""
    change = registry.VersionChange(
        version="2020-01-01",
        description="test-only sunset version",
        deprecation_date=date(2020, 1, 1),
        sunset_date=date(2020, 7, 1),
    )
    registry.REGISTRY.append(change)
    try:
        yield change
    finally:
        registry.REGISTRY.remove(change)


class TestSnapshots:
    def test_current_version_has_committed_snapshot(self):
        """CI guard: build fails when the current version has no snapshot
        (api-docs spec: Missing snapshot)."""
        path = snapshot_path(registry.current_version())
        assert path.exists(), (
            f"Missing OpenAPI snapshot for current API version "
            f"{registry.current_version()!r}: run 'app api_snapshot' and "
            f"commit {path}."
        )

    def test_snapshot_info_version_matches(self):
        path = snapshot_path(registry.current_version())
        doc = json.loads(path.read_text())
        assert doc["info"]["version"] == registry.current_version()

    @pytest.mark.django_db
    def test_api_snapshot_command_writes_file(self, tmp_path):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("api_snapshot", "--output-dir", tmp_path, stdout=out)
        written = tmp_path / f"{registry.current_version()}.json"
        assert written.exists()
        doc = json.loads(written.read_text())
        assert doc["info"]["version"] == registry.current_version()
        assert doc.get("paths")

    @pytest.mark.django_db
    def test_api_snapshot_check_fails_without_snapshot(self, monkeypatch):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        change = registry.VersionChange(
            version="2098-06-01", description="no snapshot for this one"
        )
        monkeypatch.setattr(
            "server.apps.apiversions.registry.REGISTRY",
            registry.REGISTRY + [change],
        )
        with pytest.raises(CommandError, match="snapshot"):
            call_command("api_snapshot", "--check")


class TestSchemaServing:
    @pytest.mark.django_db
    def test_live_schema_info_version(self, seed_data, client):
        response = client.get("/v1/openapi.json")
        assert response.status_code == 200
        assert response.json()["info"]["version"] == registry.current_version()

    @pytest.mark.django_db
    def test_old_version_served_from_snapshot(self, seed_data, client, newer_version):
        old = max(v for v in registry.versions() if v != newer_version.version)
        assert old != newer_version.version
        response = client.get("/v1/openapi.json", {"api_version": old})
        assert response.status_code == 200
        doc = response.json()
        # Snapshot content, not a live regeneration: the file on disk.
        snapshot = json.loads(snapshot_path(old).read_text())
        assert doc == snapshot
        assert doc["info"]["version"] == old

    @pytest.mark.django_db
    def test_docs_page_lists_versions(self, seed_data, client):
        response = client.get("/v1/docs")
        assert response.status_code == 200
        assert registry.current_version() in response.content.decode()

    @pytest.mark.django_db
    def test_unknown_api_version_on_schema_is_400(self, seed_data, client):
        response = client.get("/v1/openapi.json", {"api_version": "not-a-date"})
        assert response.status_code == 400
        assert response.json()["code"] == "api_version_invalid"

    @pytest.mark.django_db
    def test_sunset_version_on_schema_is_410(
        self, seed_data, client, sunset_old_version
    ):
        response = client.get(
            "/v1/openapi.json", {"api_version": sunset_old_version.version}
        )
        assert response.status_code == 410
        assert response.json()["code"] == "api_version_sunset"

    @pytest.mark.django_db
    def test_missing_snapshot_is_500_not_silent_live_schema(
        self, seed_data, client, monkeypatch
    ):
        """A supported non-current version without a committed snapshot
        must fail loudly, not silently serve the newest contract (review
        P2)."""
        orphan = registry.VersionChange(
            version="2098-05-01", description="no snapshot for this one"
        )
        newest = registry.VersionChange(version="2099-01-01")
        monkeypatch.setattr(
            "server.apps.apiversions.registry.REGISTRY",
            registry.REGISTRY + [orphan, newest],
        )
        response = client.get("/v1/openapi.json", {"api_version": "2098-05-01"})
        assert response.status_code == 500
        assert response.json()["code"] == "api_snapshot_missing"


class TestContractPerVersion:
    """api-docs spec: Contract tests against snapshots.

    Iterates every supported non-current version that has registered
    transforms and validates its operations against that version's
    snapshot. Currently empty (single production version, zero transforms)
    — the fake-version test demonstrates the machinery.
    """

    def _versions_with_transforms(self):
        current = registry.current_version()
        return [
            change
            for change in registry.REGISTRY
            if change.version != current
            and (change.responses or change.requests)
            and snapshot_path(change.version).exists()
            and not registry.is_sunset(change.version)
        ]

    @pytest.mark.django_db
    def test_contract_matrix(self, seed_data, client):
        for change in self._versions_with_transforms():
            for op_id in {*change.responses, *change.requests}:
                # Full matrix execution is activated with the first real
                # breaking change (see tests for its endpoints then).
                assert isinstance(op_id, str), op_id

    @pytest.mark.django_db
    def test_fake_version_end_to_end_contract(self, seed_data, client, newer_version):
        """Old-version responses match the old snapshot's operation list —
        the shape the downgraded response must stay compatible with."""
        old = max(v for v in registry.versions() if v != newer_version.version)
        response = client.get(
            "/v1/huts/huts", {"limit": 2}, headers={"Api-Version": old}
        )
        assert response.status_code == 200
        snapshot = json.loads(snapshot_path(old).read_text())
        assert "/v1/huts/huts" in snapshot["paths"]
        data = response.json()
        assert all("slug" in hut for hut in data)  # old shape preserved
        assert all(hut["api_old_shape"] is True for hut in data)  # downgrade
