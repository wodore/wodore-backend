import pytest

from django.test import Client


def test_version_endpoint(client: Client):
    response = client.get("/v1/version")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert "hash" in data


@pytest.mark.django_db
def test_health_endpoint(client: Client):
    response = client.get("/health/")
    assert response.status_code == 200


def test_live_health_endpoint(client: Client):
    """Shallow liveness probe: must stay dependency-free (no db marker)."""
    response = client.get("/health/live/")
    assert response.status_code == 200
